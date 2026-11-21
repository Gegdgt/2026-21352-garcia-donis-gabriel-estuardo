# Read-only supervision of the two approved final presentations. No simulation commands.
[CmdletBinding()]
param(
    [switch]$Both,
    [switch]$Run1000,
    [switch]$Run10K,
    [switch]$Check,
    [switch]$Open,
    [switch]$Stop,
    [ValidateRange(10,900)][int]$StartupTimeoutSeconds = 600
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
$helperPath = Join-Path $projectRoot 'python/simz1_viewers_readonly.py'
$runtimeRoot = Join-Path $projectRoot 'runtime/viewers'
$serviceRoot = Join-Path $runtimeRoot 'services'
$logRoot = Join-Path $runtimeRoot 'logs'
$mutex = $null
$ownsMutex = $false
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Get-Sha256Bytes([byte[]]$Bytes) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($algorithm.ComputeHash($Bytes))).Replace('-','').ToLowerInvariant() }
    finally { $algorithm.Dispose() }
}

function Invoke-ReadOnlyVerification([string]$Run) {
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $pythonPath
    $startInfo.Arguments = '-B "' + $helperPath + '" --run ' + $Run + ' --verify-only'
    $startInfo.WorkingDirectory = $projectRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.EnvironmentVariables['PYTHONDONTWRITEBYTECODE'] = '1'
    $verification = [Diagnostics.Process]::Start($startInfo)
    $proof = Get-ProcessEvidence $verification.Id
    $outputTask = $verification.StandardOutput.ReadToEndAsync()
    $errorTask = $verification.StandardError.ReadToEndAsync()
    try {
        if (-not $verification.WaitForExit($StartupTimeoutSeconds * 1000)) {
            $null = Assert-SameProcess $proof
            $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($proof.pid)")
            $childProofs = @()
            foreach ($child in $children) {
                $childProof = Get-ProcessEvidence $child.ProcessId
                if ($childProof.command_line -notlike ('*' + $helperPath + '*--run ' + $Run + ' --verify-only*') -or
                    $childProof.executable -notmatch '(?i)[\\/]python\.exe$' -or $childProof.owner -cne $proof.owner) {
                    throw "Verificacion agotada con hijo no identificado; PID $($proof.pid). No se detuvo un proceso desconocido."
                }
                $childProofs += $childProof
            }
            foreach ($childProof in $childProofs) { $null = Assert-SameProcess $childProof; Stop-Process -Id $childProof.pid }
            if (-not $verification.HasExited) { $null = Assert-SameProcess $proof; $verification.Kill() }
            throw "La verificacion de $Run excedio $StartupTimeoutSeconds segundos; no se inicio ningun servicio nuevo."
        }
        $stdout = $outputTask.GetAwaiter().GetResult()
        $stderr = $errorTask.GetAwaiter().GetResult()
        if ($verification.ExitCode -ne 0) { throw "Identidad/replay $Run rechazado (codigo $($verification.ExitCode)): $stderr" }
        return $stdout | ConvertFrom-Json
    } finally { $verification.Dispose() }
}

function Get-ProcessEvidence([int]$ProcessId) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId"
    if (-not $process) { throw "El proceso $ProcessId ya termino." }
    $owner = Invoke-CimMethod -InputObject $process -MethodName GetOwner
    if ($owner.ReturnValue -ne 0) { throw "No se pudo identificar al propietario de PID $ProcessId." }
    return [pscustomobject]@{
        pid = [int]$process.ProcessId
        parent_pid = [int]$process.ParentProcessId
        created_utc = $process.CreationDate.ToUniversalTime().ToString('o')
        executable = $process.ExecutablePath
        command_line = $process.CommandLine
        owner = "$($owner.Domain)\$($owner.User)"
    }
}

function Assert-SameProcess($Saved) {
    $current = Get-ProcessEvidence $Saved.pid
    foreach ($key in @('pid','parent_pid','created_utc','executable','command_line','owner')) {
        if ($current.$key -cne $Saved.$key) { throw "PID $($Saved.pid) cambio ($key). No se detuvo ningun proceso desconocido." }
    }
    return $current
}

function Get-Listeners([int]$Port) {
    # This Windows session has returned null/wrong State values for real listening
    # sockets. Include bound endpoints (remote port 0), then require HTTP + owner.
    return @(Get-NetTCPConnection -ErrorAction Stop | Where-Object { $_.LocalPort -eq $Port -and $_.RemotePort -eq 0 })
}

function Assert-FreePort([int]$Port) {
    $probe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,$Port)
    $probe.ExclusiveAddressUse = $true
    try { $probe.Start() } catch { throw "Puerto $Port ocupado/reservado. No se inicio otra copia ni se detuvo su propietario." }
    finally { $probe.Stop() }
}

function Get-PendingStart($Service) {
    $record = Read-ServiceRecord $Service
    if (-not $record -or -not $record.started_process) { return $null }
    $candidate = Get-CimInstance Win32_Process -Filter "ProcessId=$($record.started_process.pid)"
    if (-not $candidate -or $candidate.CreationDate.ToUniversalTime().ToString('o') -cne $record.started_process.created_utc) { return $null }
    $null = Assert-SameProcess $record.started_process
    if (-not (Test-Command $Service $record.started_process)) { throw 'Registro de arranque incompatible.' }
    return $record
}

function Test-Command($Service, $Process) {
    if ($Process.executable -notmatch '(?i)[\\/]python(?:w)?\.exe$') { return $false }
    $command = $Process.command_line.Replace('\','/').ToLowerInvariant()
    $expected = $Service.script.Replace('\','/').ToLowerInvariant()
    $pathPattern = '(?:^|[\s"]){0}(?=[\s"]|$)' -f [regex]::Escape($expected)
    if ($command -notmatch $pathPattern) { return $false }
    if ($Service.role -eq 'backend' -and $Service.script -eq $helperPath) {
        return ($command -match ('--run\s+' + $Service.run + '(?:\s|$)') -and $command -match '--serve-backend(?:\s|$)')
    }
    return $command -match ('--port\s+' + $Service.port + '(?:\s|$)')
}

function Get-HttpJson([string]$Url) {
    return Invoke-RestMethod -Uri $Url -TimeoutSec 3 -ErrorAction Stop
}

function Assert-Identity($Actual, $Expected) {
    foreach ($key in @('run_id','launch_id','iteration','run_manifest_sha256','source_version','source_fingerprint','visual_policy')) {
        if ($Actual.$key -cne $Expected.$key) { throw "Identidad HTTP incompatible: $key." }
    }
}

function Get-ServiceStatus($Service) {
    $listeners = @(Get-Listeners $Service.port)
    if ($listeners.Count -eq 0) { return [pscustomobject]@{state='off'; process=$null; detail='Sin listener'} }
    $owners = @($listeners.OwningProcess | Select-Object -Unique)
    if ($owners.Count -ne 1 -or @($listeners | Where-Object LocalAddress -ne '127.0.0.1').Count -gt 0) {
        throw "Puerto $($Service.port) ocupado con enlaces incompatibles. PIDs: $($owners -join ', '). No se modifico el puerto."
    }
    $process = Get-ProcessEvidence $owners[0]
    $compatibleCommand = Test-Command $Service $process
    if (-not $compatibleCommand -and $Service.role -eq 'backend') {
        $historic = $Service.Clone()
        $historic.script = $Service.expected.backend_script
        $compatibleCommand = Test-Command $historic $process
    }
    if (-not $compatibleCommand) {
        throw "Puerto $($Service.port) ocupado por PID $($process.pid) incompatible: $($process.command_line). No se detuvo."
    }
    try {
        $actual = Get-HttpJson "$($Service.address)/api/visual-build"
        Assert-Identity $actual $Service.expected.identity
        if ($Service.role -eq 'presentation') {
            $build = Get-HttpJson "$($Service.address)/api/presentation-build"
            Assert-Identity $build.native_identity $Service.expected.identity
            if ($build.presentation_sha256 -cne $Service.expected.presentation_sha256 -or
                $build.source_http -cne "http://127.0.0.1:$($Service.expected.backend_port)") {
                throw 'La presentacion o su dependencia no coincide con la version final.'
            }
            $expectedHtml = $Service.expected.presentation_sha256
        } else { $expectedHtml = $Service.expected.backend_html_sha256 }
        $response = Invoke-WebRequest -UseBasicParsing -Uri "$($Service.address)/index.html" -TimeoutSec 3
        $actualHtml = Get-Sha256Bytes $response.RawContentStream.ToArray()
        if ($response.StatusCode -ne 200 -or $actualHtml -cne $expectedHtml) { throw 'HTML diferente de la version aprobada.' }
        return [pscustomobject]@{state='ready'; process=$process; detail='Listener + HTTP + identidad + SHA256 HTML correctos'}
    } catch {
        return [pscustomobject]@{state='unavailable'; process=$process; detail=$_.Exception.Message}
    }
}

function Get-RecordPath($Service) { return Join-Path $serviceRoot ($Service.name + '.json') }

function Read-ServiceRecord($Service) {
    $path = Get-RecordPath $Service
    if (Test-Path -LiteralPath $path) { return Get-Content -Raw -Encoding UTF8 -LiteralPath $path | ConvertFrom-Json }
    return $null
}

function Save-ServiceRecord($Service, $Status, $Started, [string]$Stdout, [string]$Stderr) {
    $record = [ordered]@{
        schema_version=1; service=$Service.name; run_id=$Service.expected.identity.run_id
        launch_id=$Service.expected.identity.launch_id; iteration=0
        manifest_sha256=$Service.expected.identity.run_manifest_sha256
        port=$Service.port; url="$($Service.address)/index.html"; state=$Status.state
        checked_utc=[DateTime]::UtcNow.ToString('o')
        working_directory=$(if ($Started) { $projectRoot } else { $null })
        working_directory_basis=$(if ($Started) { 'Start-Process -WorkingDirectory' } else { 'Not observed: compatible existing process' })
        process=$Status.process; started_process=$Started; stdout_log=$Stdout; stderr_log=$Stderr
    }
    $path = Get-RecordPath $Service
    $temporary = "$path.$([guid]::NewGuid().ToString('N')).tmp"
    [IO.File]::WriteAllText($temporary, ($record | ConvertTo-Json -Depth 8), $utf8)
    Move-Item -LiteralPath $temporary -Destination $path -Force
}

function Show-Service($Service, $Status) {
    $processIdText = if ($Status.process) { $Status.process.pid } else { '-' }
    Write-Output "$($Service.name): $($Status.state), puerto $($Service.port), PID $processIdText"
    Write-Output "  RunId: $($Service.expected.identity.run_id)"
    Write-Output "  $($Status.detail)"
    $record = Read-ServiceRecord $Service
    if ($record -and $Status.process -and $record.process -and $record.process.created_utc -eq $Status.process.created_utc -and $record.process.pid -eq $Status.process.pid) {
        Write-Output "  stdout: $($record.stdout_log)"
        Write-Output "  stderr: $($record.stderr_log)"
    }
}

function Start-ViewerService($Service) {
    $status = Get-ServiceStatus $Service
    if ($status.state -eq 'ready') {
        $old = Read-ServiceRecord $Service
        if (-not $old -or $old.state -ne 'ready' -or -not $old.process -or $old.process.pid -ne $status.process.pid -or $old.process.created_utc -ne $status.process.created_utc) {
            $pending = Get-PendingStart $Service
            if ($pending -and ($status.process.pid -eq $pending.started_process.pid -or $status.process.parent_pid -eq $pending.started_process.pid)) {
                Save-ServiceRecord $Service $status $pending.started_process $pending.stdout_log $pending.stderr_log
            } else { Save-ServiceRecord $Service $status $null '' '' }
        }
        Show-Service $Service $status
        return
    }
    $pending = Get-PendingStart $Service
    if ($status.state -ne 'off' -and -not $pending) {
        throw "$($Service.name) tiene PID $($status.process.pid) pero no esta disponible: $($status.detail). Revise sus logs; no se duplico."
    }
    if ($pending) {
        Write-Output "Esperando arranque existente de $($Service.name), PID $($pending.started_process.pid); sin duplicarlo."
        $started = $pending.started_process
        $stdout = $pending.stdout_log
        $stderr = $pending.stderr_log
        $child = Get-Process -Id $started.pid
    } else {
    Assert-FreePort $Service.port
    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)
    $stdout = Join-Path $logRoot "$($Service.name)-$stamp.stdout.log"
    $stderr = Join-Path $logRoot "$($Service.name)-$stamp.stderr.log"
    $arguments = @('-B','-u', ('"' + $Service.script + '"')) + $Service.arguments
    Write-Output "Iniciando $($Service.name) en $($Service.port)..."
    $child = Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $started = Get-ProcessEvidence $child.Id
    $child.PriorityClass = 'BelowNormal'
    $status = [pscustomobject]@{state='starting'; process=$null; detail='Esperando HTTP'}
    Save-ServiceRecord $Service $status $started $stdout $stderr
    }
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt $StartupTimeoutSeconds) {
        $child.Refresh()
        if ($child.HasExited) {
            $status.state = 'failed'
            Save-ServiceRecord $Service $status $started $stdout $stderr
            throw "$($Service.name) termino con codigo $($child.ExitCode). Consulte $stderr y $stdout."
        }
        $status = Get-ServiceStatus $Service
        if ($status.state -eq 'ready') {
            Save-ServiceRecord $Service $status $started $stdout $stderr
            Show-Service $Service $status
            return
        }
        Start-Sleep -Milliseconds 250
    }
    $status.state = 'startup_timeout'
    Save-ServiceRecord $Service $status $started $stdout $stderr
    throw "$($Service.name) no confirmo disponibilidad en $StartupTimeoutSeconds s: $($status.detail). Consulte $stderr. No se abrira el navegador ni se creara otra copia."
}

function Stop-ViewerService($Service) {
    $record = Read-ServiceRecord $Service
    if (-not $record) {
        if (@(Get-Listeners $Service.port).Count -eq 0) { Write-Output "$($Service.name): apagado."; return }
        throw "No hay registro de propiedad para $($Service.name). No se detuvo ningun proceso."
    }
    if ($record.run_id -cne $Service.expected.identity.run_id -or $record.port -ne $Service.port) {
        throw "Registro incompleto/incompatible para $($Service.name); revisar manualmente."
    }
    $savedProcess = if ($record.process) { $record.process } else { $record.started_process }
    if (-not $savedProcess) { throw 'El registro no contiene proceso verificable.' }
    $live = Get-CimInstance Win32_Process -Filter "ProcessId=$($savedProcess.pid)"
    if (-not $live) {
        if (@(Get-Listeners $Service.port).Count -gt 0) { throw "Puerto $($Service.port) ahora pertenece a otro proceso. No se detuvo." }
        Write-Output "$($Service.name): ya apagado."; return
    }
    $current = Assert-SameProcess $savedProcess
    if (-not (Test-Command $Service $current)) { throw 'El proceso no pertenece al lanzador registrado.' }
    $listeners = @(Get-Listeners $Service.port)
    if (@($listeners | Where-Object OwningProcess -ne $current.pid).Count -gt 0) { throw 'Listener cambiado; cierre rechazado.' }
    # Only direct multiprocessing readers of this exact, verified Python server.
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($current.pid)")
    $readers = @()
    foreach ($reader in $children) {
        $evidence = Get-ProcessEvidence $reader.ProcessId
        $isReader = $evidence.executable -ceq $current.executable -and $evidence.command_line -match 'multiprocessing\.spawn.*spawn_main.*--multiprocessing-fork'
        $isStartingChild = -not $record.process -and (Test-Command $Service $evidence)
        if ((-not $isReader -and -not $isStartingChild) -or $evidence.owner -cne $current.owner -or
            [DateTime]$evidence.created_utc -lt [DateTime]$current.created_utc) {
            throw "Hijo no reconocido PID $($reader.ProcessId); cierre rechazado antes de intervenir."
        }
        if (@(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($evidence.pid)").Count -gt 0) {
            throw "PID $($evidence.pid) tiene descendientes no registrados; cierre rechazado antes de intervenir."
        }
        $readers += $evidence
    }
    # Recheck every identity immediately before stopping; never kill by process name.
    foreach ($reader in $readers) { $null = Assert-SameProcess $reader; Stop-Process -Id $reader.pid -ErrorAction Stop }
    if (Get-CimInstance Win32_Process -Filter "ProcessId=$($current.pid)") {
        $null = Assert-SameProcess $current
        Stop-Process -Id $current.pid -ErrorAction Stop
    }
    $stopped = [pscustomobject]@{state='stopped'; process=$current; detail='Cierre solicitado y propiedad comprobada'}
    Save-ServiceRecord $Service $stopped $record.started_process $record.stdout_log $record.stderr_log
    Write-Output "$($Service.name): detenido PID $($current.pid), puerto $($Service.port)."
}

try {
    if (($Both -and ($Run1000 -or $Run10K)) -or ($Run1000 -and $Run10K)) { throw 'Seleccione solo -Both, -Run1000 o -Run10K.' }
    if ($Stop -and ($Check -or $Open)) { throw '-Stop no se combina con -Check ni -Open.' }
    if ($Check -and $Open) { throw '-Check es solo lectura; no se combina con -Open.' }
    if (-not $Stop) {
        foreach ($file in @($pythonPath,$helperPath)) { if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Archivo requerido ausente: $file" } }
    }
    $selected = if ($Run1000) { @('run1000') } elseif ($Run10K) { @('run10k') } else { @('run1000','run10k') }
    if (-not $Check) {
        $key = (Get-Sha256Bytes ([Text.Encoding]::UTF8.GetBytes($projectRoot.ToLowerInvariant()))).Substring(0,24)
        $mutex = New-Object System.Threading.Mutex($false, "Local\SimZ1Viewers-$key")
        try { $ownsMutex = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $ownsMutex = $true }
        if (-not $ownsMutex) { throw 'Otro lanzador de visores esta trabajando. Espere a que termine y use -Check.' }
    }
    # Both pinned datasets are checked before starting any service. This performs no export/build.
    $verified = @{}
    if ($Stop) {
        # Stopping a recorded process must remain possible when an input is missing.
        # These are the fixed publication identities, not experimental parameters.
        $deliveryRoot = Join-Path $projectRoot 'runtime/diagnostics/run10k-v8-thesis-viewer-20261108'
        $verified['run1000'] = [pscustomobject]@{identity=[pscustomobject]@{run_id='simz1-9d15f07ccc134aa69c60fdcbc887ea3f';launch_id='a32f15487b1a49ac910ba799175658ca';run_manifest_sha256='3399203616a3884cb17e360d46160cbd43bc006f44eb146e0d08aba1b249a427'};backend_port=8799;presentation_port=8804;presentation_script=(Join-Path $deliveryRoot 'cleanup-run1000-20261109/clean_viewer.py')}
        $verified['run10k'] = [pscustomobject]@{identity=[pscustomobject]@{run_id='simz1-cdffd75c4bdb47a7bfb507efe2c8c4e9';launch_id='e496c091b9ef46ee9ca381576135e299';run_manifest_sha256='8d51af2202ceb29ec32aa782f18fa05440436c1fb6a879beeb8f11a086e3213f'};backend_port=8801;presentation_port=8803;presentation_script=(Join-Path $deliveryRoot 'cleanup-20261109/clean_viewer.py')}
    } else { foreach ($run in @('run1000','run10k')) {
        $verified[$run] = Invoke-ReadOnlyVerification $run
        if ($verified[$run].status -cne 'verified_read_only') { throw "Contrato de verificacion inesperado: $run" }
    } }
    $services = @()
    foreach ($run in $selected) {
        $expected = $verified[$run]
        $services += @{name="$run-backend";run=$run;role='backend';port=$expected.backend_port;address="http://127.0.0.1:$($expected.backend_port)";script=$helperPath;arguments=@('--run',$run,'--serve-backend');expected=$expected}
        $services += @{name="$run-presentation";run=$run;role='presentation';port=$expected.presentation_port;address="http://127.0.0.1:$($expected.presentation_port)";script=$expected.presentation_script;arguments=@('--port',[string]$expected.presentation_port);expected=$expected}
    }
    if ($Check) {
        $allReady = $true
        foreach ($service in $services) {
            try { $status = Get-ServiceStatus $service; Show-Service $service $status; if ($status.state -ne 'ready') { $allReady = $false } }
            catch { Write-Output "$($service.name): CONFLICTO/ERROR: $($_.Exception.Message)"; $allReady = $false }
        }
        foreach ($run in $selected) { Write-Output "URL final $run : http://127.0.0.1:$($verified[$run].presentation_port)/index.html" }
        if (-not $allReady) { exit 2 }
        exit 0
    }
    if ($Stop) {
        [array]::Reverse($services)
        foreach ($service in $services) { Stop-ViewerService $service }
        exit 0
    }
    # Detect occupied/incompatible ports before creating any child process.
    foreach ($service in $services) {
        $status = Get-ServiceStatus $service
        if ($status.state -eq 'unavailable' -and -not (Get-PendingStart $service)) { throw "$($service.name) ya tiene un listener pero no pasa HTTP/identidad: $($status.detail). No se duplico." }
        if ($status.state -eq 'off' -and -not (Get-PendingStart $service)) { Assert-FreePort $service.port }
    }
    $null = New-Item -ItemType Directory -Path $serviceRoot,$logRoot -Force
    foreach ($service in $services) { Start-ViewerService $service }
    foreach ($run in $selected) {
        $url = "http://127.0.0.1:$($verified[$run].presentation_port)/index.html"
        Write-Output "URL final $run : $url"
        if ($Open) {
            $edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
            if (-not $edge) { throw "Microsoft Edge no se encontro. Los servidores siguen activos; abra $url en su navegador." }
            Start-Process -FilePath $edge -ArgumentList $url
        }
    }
    exit 0
} catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
} finally {
    if ($ownsMutex) { $mutex.ReleaseMutex() }
    if ($mutex) { $mutex.Dispose() }
}
