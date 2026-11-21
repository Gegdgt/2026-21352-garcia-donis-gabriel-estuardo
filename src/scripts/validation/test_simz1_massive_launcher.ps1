# Read-only launcher guards: parse AST, import selected pure guards, mock CIM/disk.
# Never dot-source or invoke the launcher's top level; never run Maven, Java/QSim,
# population generation, replay services or a browser. No test files are written.
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$simz1TestRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$simz1LauncherPath = Join-Path $simz1TestRoot 'scripts\run_simz1_massive_verified.ps1'
$simz1Tokens = $null
$simz1Errors = $null
$simz1Ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $simz1LauncherPath, [ref]$simz1Tokens, [ref]$simz1Errors)
if ($simz1Errors.Count) { throw ($simz1Errors | Out-String) }
$script:simz1Assertions = 0
function Assert-Review([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw ('FAIL: ' + $Message) }
    $script:simz1Assertions++
}
function Assert-Rejected([scriptblock]$Action, [string]$Pattern) {
    $rejected = $false
    try { & $Action } catch {
        if ($_.Exception.Message -notlike $Pattern) { throw }
        $rejected = $true
    }
    Assert-Review $rejected ('Expected rejection: ' + $Pattern)
}

# The allowlist intentionally excludes Invoke-Checked/Invoke-Contract and all
# top-level statements, so default launcher behavior cannot execute in this test.
foreach ($name in @('Assert-NoReparsePath', 'Assert-NoDestinationUsers', 'Assert-DiskReserve')) {
    $definitions = @($simz1Ast.FindAll({ param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
    }, $false))
    Assert-Review ($definitions.Count -eq 1) ('Unique guard: ' + $name)
    Invoke-Expression $definitions[0].Extent.Text
}

function Get-CimInstance {
    param($ClassName, $ErrorAction)
    if ($script:simz1CimDenied) { throw 'fixture CIM unavailable' }
    return $script:simz1Processes
}
$script:simz1CimDenied = $false
$script:simz1Processes = @()
$simz1Destination = Join-Path $simz1TestRoot ('target\never-created-review-' + [guid]::NewGuid().ToString('N'))
Assert-Review (-not (Test-Path -LiteralPath $simz1Destination)) 'Fixture destination is new'
Assert-NoDestinationUsers @($simz1Destination)
Assert-NoReparsePath $simz1Destination
$script:simz1Assertions += 2

$script:simz1Processes = @([pscustomobject]@{
    ProcessId = 999999; Name = 'java.exe'
    CommandLine = 'java -Ddestination=' + $simz1Destination.Replace('\', '/')
})
Assert-Rejected { Assert-NoDestinationUsers @($simz1Destination) } '*utiliza el destino*'
$script:simz1Processes = @([pscustomobject]@{
    ProcessId = 999999; Name = 'python.exe'; CommandLine = $null
})
Assert-Rejected { Assert-NoDestinationUsers @($simz1Destination) } '*No se puede inspeccionar*'
$script:simz1Processes = @([pscustomobject]@{
    ProcessId = 999999; Name = 'python.exe'; CommandLine = 'python unrelated.py'
})
Assert-NoDestinationUsers @($simz1Destination)
$script:simz1Assertions++
$script:simz1CimDenied = $true
Assert-Rejected { Assert-NoDestinationUsers @($simz1Destination) } '*CIM unavailable*'
$script:simz1CimDenied = $false

# Simulate a junction without creating one or following it. Other paths retain
# real read-only Test-Path/Get-Item behavior through qualified cmdlet names.
function Test-Path {
    param([string]$LiteralPath, [string]$PathType)
    if ($LiteralPath -eq $simz1Destination) { return $true }
    if ($PathType) { return Microsoft.PowerShell.Management\Test-Path -LiteralPath $LiteralPath -PathType $PathType }
    return Microsoft.PowerShell.Management\Test-Path -LiteralPath $LiteralPath
}
function Get-Item {
    param([string]$LiteralPath, [switch]$Force)
    if ($LiteralPath -eq $simz1Destination) {
        return [pscustomobject]@{ Attributes = [IO.FileAttributes]::ReparsePoint }
    }
    return Microsoft.PowerShell.Management\Get-Item -LiteralPath $LiteralPath -Force:$Force
}
Assert-Rejected { Assert-NoReparsePath $simz1Destination } '*Reparse point*'

$MinimumFreeGiB = 64
Assert-Rejected {
    Assert-DiskReserve @([pscustomobject]@{ actual_volume = 'fixture:'; available_bytes = 1GB; path = 'fixture' })
} '*Espacio insuficiente*'
Assert-DiskReserve @([pscustomobject]@{ actual_volume = 'fixture:'; available_bytes = 128GB; path = 'fixture' })
$script:simz1Assertions++
Assert-Rejected {
    Assert-DiskReserve @(
        [pscustomobject]@{ actual_volume = 'fixture:'; available_bytes = 128GB; path = 'first' },
        [pscustomobject]@{ actual_volume = 'fixture:'; available_bytes = 2GB; path = 'second' })
} '*Espacio insuficiente*'

# Structural safety: the single invocation carrying all simulation arguments is
# inside the ELSE branch of if ($PrepareOnly), never in its prepared-plan branch.
$simz1Calls = @($simz1Ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.CommandAst] -and
    $node.GetCommandName() -eq 'Invoke-Checked' -and
    @($node.CommandElements | Where-Object { $_.Extent.Text -eq '$simz1Arguments' }).Count -gt 0
}, $true))
Assert-Review ($simz1Calls.Count -eq 1) 'Exactly one simulation launcher invocation'
$simz1Guard = $simz1Calls[0].Parent
while ($null -ne $simz1Guard -and -not ($simz1Guard -is [System.Management.Automation.Language.IfStatementAst])) {
    $simz1Guard = $simz1Guard.Parent
}
Assert-Review ($null -ne $simz1Guard -and $simz1Guard.Clauses[0].Item1.Extent.Text -eq '$PrepareOnly') 'Simulation call is guarded by PrepareOnly'
Assert-Review ($null -ne $simz1Guard.ElseClause -and
    $simz1Calls[0].Extent.StartOffset -ge $simz1Guard.ElseClause.Extent.StartOffset -and
    $simz1Calls[0].Extent.EndOffset -le $simz1Guard.ElseClause.Extent.EndOffset) 'Only the execution branch calls the launcher'
Assert-Review ($simz1Guard.Clauses[0].Item2.Extent.Text -notmatch 'Invoke-Checked|Invoke-Contract|ejecutar_simz1') 'PrepareOnly branch performs no external launch'

# The resource, concurrency and byte-identity guards must precede the only
# simulation invocation. These assertions inspect actual control-flow statements.
$simz1BeforeLaunch = $simz1Ast.Extent.Text.Substring(0, $simz1Calls[0].Extent.StartOffset)
Assert-Review ($simz1BeforeLaunch -match 'Assert-DiskReserve \$simz1State.prelaunch_volumes') 'Disk rechecked before launch'
Assert-Review ($simz1BeforeLaunch -match "throw 'Falta comprobante exitoso de concurrencia") 'Four-thread evidence required before launch'
Assert-Review ($simz1BeforeLaunch -match 'throw "Las clases del launcher difieren de las probadas:') 'Class mismatch rejects launch'
foreach ($name in @('$simz1Workspace', '$simz1Run')) {
    $assignments = @($simz1Ast.FindAll({ param($node)
        $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and $node.Left.Extent.Text -eq $name
    }, $true))
    Assert-Review ($assignments.Count -eq 1 -and $assignments[0].Right.Extent.Text -match '\[guid\]::NewGuid\(\)') ('Independent GUID: ' + $name)
}

# Reproduce Windows PowerShell native-argument quoting with the actual harmless
# venv probe, without invoking the launch script or its external-call wrapper.
$simz1Probe = @($simz1Ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.StringConstantExpressionAst] -and
    $node.Value.StartsWith('import sys,sqlite3,numpy,pandas,matplotlib;')
}, $true))
Assert-Review ($simz1Probe.Count -eq 1) 'One inspectable venv probe'
$simz1Python = Join-Path $simz1TestRoot '.venv\Scripts\python.exe'
$simz1ProbeResult = & $simz1Python -B -c $simz1Probe[0].Value
Assert-Review ($LASTEXITCODE -eq 0) 'Real venv probe survives PowerShell native quoting'
Assert-Review (@($simz1ProbeResult).Count -ge 3) 'Venv probe returns version, executable and SQLite version'
Assert-Review (-not (Microsoft.PowerShell.Management\Test-Path -LiteralPath $simz1Destination)) 'No fixture destination created'
Write-Host "PASS: $script:simz1Assertions launcher guard assertions; no top-level launch, simulation, server, browser or files created."
