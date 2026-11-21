#requires -Version 5.1
<#!
.SYNOPSIS
Extrae la seleccion revisada de SimZ1 sin modificar el origen.
.DESCRIPTION
La vista previa es el comportamiento predeterminado. -Aplicar copia solamente
los archivos enumerados en docs/seleccion_fuentes.csv, comprobando sus SHA256.
No ejecuta simulaciones, no elimina archivos y no realiza operaciones Git de escritura.
#>
[CmdletBinding()]
param(
    [string]$Origen = 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala',
    [string]$Destino = '',
    [switch]$Aplicar
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($Destino)) { $Destino = $PSScriptRoot }
$expectedRemote = 'https://github.com/Gegdgt/2026-21352-garcia-donis-gabriel-estuardo'

function Canonical-Directory([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    if (-not $item.PSIsContainer) { throw "No es un directorio: $Path" }
    $current = $item
    while ($null -ne $current) {
        if (($current.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "No se permiten enlaces/junctions en las rutas: $($current.FullName)"
        }
        $current = $current.Parent
    }
    return $item.FullName.TrimEnd('\', '/')
}
function Safe-Child([string]$Root, [string]$Relative) {
    if ([IO.Path]::IsPathRooted($Relative) -or $Relative -match '(^|[\\/])\.\.([\\/]|$)|:') {
        throw "Ruta relativa no permitida: $Relative"
    }
    $path = [IO.Path]::GetFullPath((Join-Path $Root $Relative))
    if (-not $path.StartsWith($Root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Ruta fuera de la raiz: $Relative"
    }
    $probe = $path
    while ($probe.Length -gt $Root.Length) {
        if (Test-Path -LiteralPath $probe) {
            $entry = Get-Item -LiteralPath $probe -Force
            if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Enlace/junction no permitido: $Relative"
            }
        }
        $probe = Split-Path -Parent $probe
    }
    return $path
}
function Sensitive-Reason([string]$Relative, [string]$Path) {
    if ($Relative -match '(?i)(^|/)(\.env($|\.)|id_rsa|id_ed25519|credentials[^/]*|secrets?\.[^/]+)$|\.(pfx|p12|key|pem)$') {
        return 'Nombre potencialmente sensible; requiere revision manual'
    }
    # No imprimir valores encontrados. XML/OSM tambien se revisan como texto.
    if ([IO.Path]::GetExtension($Path) -in @('.jar', '.png', '.jpg', '.jpeg', '.gif', '.gz', '.zip')) { return '' }
    $body = [IO.File]::ReadAllText($Path)
    if ($body -match '(?m)-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bgh[pousr]_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b|\bAKIA[0-9A-Z]{16}\b|\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b|https?://[A-Za-z0-9._%+-]+:[A-Za-z0-9._%+~=-]+@') {
        return 'Patron de credencial; requiere revision manual'
    }
    if ($body -match '(?im)^\s*["'']?(?:password|passwd|api[_-]?key|access[_-]?token|client[_-]?secret)["'']?\s*[:=]\s*["''][^"''\r\n]{16,}["'']') {
        return 'Asignacion potencialmente sensible; requiere revision manual'
    }
    return ''
}

$sourceRoot = Canonical-Directory $Origen
$destRoot = Canonical-Directory $Destino
if ($sourceRoot.Equals($destRoot, [StringComparison]::OrdinalIgnoreCase) -or
    $sourceRoot.StartsWith($destRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or
    $destRoot.StartsWith($sourceRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Origen y destino deben ser directorios separados, sin anidamiento.'
}
if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot 'pom.xml')) -or
    -not (Test-Path -LiteralPath (Join-Path $sourceRoot 'python/prepare_simz1.py'))) {
    throw 'El origen no tiene la estructura esperada de SimZ1.'
}
$gitRoot = & git -C $destRoot rev-parse --show-toplevel
if ($LASTEXITCODE -ne 0 -or (Canonical-Directory $gitRoot) -ne $destRoot) {
    throw 'El destino debe ser la raiz del clon del fork personal.'
}
$remotes = @(& git -C $destRoot remote get-url --all origin)
if ($LASTEXITCODE -ne 0 -or $remotes.Count -ne 1) { throw 'No se pudo verificar origin.' }
$remote = $remotes[0].Trim().TrimEnd('/') -replace '\.git$', ''
if ($remote -cne $expectedRemote -and $remote -cne 'git@github.com:Gegdgt/2026-21352-garcia-donis-gabriel-estuardo') {
    throw "El remoto origin no corresponde al fork autorizado: $remote"
}
$pushRemotes = @(& git -C $destRoot remote get-url --push --all origin)
if ($LASTEXITCODE -ne 0 -or $pushRemotes.Count -ne 1) { throw 'No se pudo verificar remoto de push.' }
$pushRemote = $pushRemotes[0].Trim().TrimEnd('/') -replace '\.git$', ''
if ($pushRemote -cne $expectedRemote -and $pushRemote -cne 'git@github.com:Gegdgt/2026-21352-garcia-donis-gabriel-estuardo') {
    throw 'La URL de push no corresponde al fork autorizado.'
}
# Adaptacion de empaquetado: las reglas originales mas cercanas tendrian
# precedencia sobre .gitattributes raiz y cambiarian bytes CRLF al hacer commit.
$packaging = [ordered]@{
    'src/scenarios/.gitattributes'="** -text`n";
    'src/scenarios/.gitignore'="!/zona1/od/balanced-gateway-v1/access-review-v2/osm-evidence/*.log`n!/zona1/od/balanced-gateway-v1/access-review-v2/osm-evidence/correction7/*.log`n"
}
foreach ($relative in $packaging.Keys) {
    $path = Safe-Child $destRoot $relative
    if ((Test-Path -LiteralPath $path) -and [IO.File]::ReadAllText($path) -cne $packaging[$relative]) {
        throw "Adaptacion de empaquetado diferente; no sobrescribir: $relative"
    }
}
$planPath = Safe-Child $destRoot 'docs/seleccion_fuentes.csv'
$selection = @(Import-Csv -LiteralPath $planPath -Encoding UTF8)
if ($selection.Count -eq 0) { throw 'Seleccion vacia.' }
$seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$checks = [Collections.Generic.List[object]]::new()
$blocked = [Collections.Generic.List[object]]::new()
foreach ($row in $selection) {
    $relative = $row.ruta.Replace('\', '/')
    if (-not $seen.Add($relative)) { throw "Ruta duplicada: $relative" }
    if ($relative -match '(^|/)(\.git|\.venv|venv|node_modules|__pycache__|target|build|runtime|output|tmp|temp)(/|$)|(^|/)montecarlo/run-') {
        throw "Directorio prohibido en seleccion: $relative"
    }
    if ($relative -match '\.(pyc|class|sqlite|db)$') { throw "Producto no permitido: $relative" }
    $source = Safe-Child $sourceRoot $relative
    $target = Safe-Child $destRoot ('src/' + $relative)
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        $blocked.Add([pscustomobject]@{ruta=$relative; motivo='Falta en origen'}); continue
    }
    $file = Get-Item -LiteralPath $source -Force
    if ($file.Length -gt 25MB) {
        $blocked.Add([pscustomobject]@{ruta=$relative; motivo='Mayor de 25 MiB; requiere decision explicita'}); continue
    }
    $sensitive = Sensitive-Reason $relative $source
    if ($sensitive) { $blocked.Add([pscustomobject]@{ruta=$relative; motivo=$sensitive}); continue }
    $hash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -cne $row.sha256 -or $file.Length -ne [long]$row.bytes) {
        $blocked.Add([pscustomobject]@{ruta=$relative; motivo='El origen difiere de la seleccion revisada'}); continue
    }
    $action = 'copiar'
    if (Test-Path -LiteralPath $target) {
        if (-not (Test-Path -LiteralPath $target -PathType Leaf) -or
            (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -cne $hash) {
            $blocked.Add([pscustomobject]@{ruta=$relative; motivo='Destino diferente; no se sobrescribe'}); continue
        }
        $action = 'identico'
    }
    $checks.Add([pscustomobject]@{ruta=$relative; destino=('src/' + $relative); categoria=$row.categoria; motivo=$row.motivo; bytes=$file.Length; sha256=$hash; accion=$action})
}

# Enumerar metadatos, nunca contenidos de corridas/SQLite. No seguir junctions.
$excluded = [Collections.Generic.List[object]]::new()
$pending = [Collections.Generic.Stack[string]]::new()
$pending.Push($sourceRoot)
while ($pending.Count -gt 0) {
    $directory = $pending.Pop()
    foreach ($entry in Get-ChildItem -LiteralPath $directory -Force -ErrorAction Stop) {
        $relative = $entry.FullName.Substring($sourceRoot.Length + 1).Replace('\', '/')
        if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            $excluded.Add([pscustomobject]@{ruta=$relative; bytes=''; categoria='enlace'; motivo='No seguir enlaces o junctions'}); continue
        }
        if ($entry.PSIsContainer) {
            # Dependencias instaladas y Git se inventarian como subarboles; no se copian.
            if ($entry.Name -in @('.git', '.venv', 'venv', 'node_modules', '__pycache__', '.pytest_cache')) {
                $excluded.Add([pscustomobject]@{ruta=($relative + '/**'); bytes=''; categoria='entorno-cache-git'; motivo='Subarbol excluido; no pertenece a las fuentes distribuibles'})
            } elseif ($relative -match '^(runtime|output|target|build|tmp|temp|audits|evidence|graficas_tesis_v2)(/|$)|^scenarios/zona1/(montecarlo|audit-[^/]+|versions)(/|$)') {
                $excluded.Add([pscustomobject]@{ruta=($relative + '/**'); bytes=''; categoria='generado-historico'; motivo='Subarbol de productos excluido; listado inicial por archivo en docs/inventario_excluidos_completo.csv.gz'})
            } else { $pending.Push($entry.FullName) }
        } elseif (-not $seen.Contains($relative)) {
            $category = 'no-seleccionado'
            $reason = 'Fuera de la seleccion explicita revisada; no se incorpora'
            if ($relative -match '(^|/)(runtime|output|target|build|tmp|temp|audits|evidence)(/|$)|(^|/)montecarlo/|(^|/)audit-') {
                $category = 'generado-historico'; $reason = 'Corrida, resultado, diagnostico, temporal o compilado'
            }
            if ($entry.Length -gt 25MB) { $category = 'grande-excluido'; $reason = 'Mayor de 25 MiB; no incorporar sin revision explicita' }
            if ($relative -match '(?i)(^|/)(\.env($|\.)|id_rsa|id_ed25519|credentials[^/]*|secrets?\.[^/]+)$|\.(pem|pfx|p12|key)$') {
                $category = 'potencialmente-sensible'; $reason = 'Nombre sensible; no se lee ni incorpora'
            }
            $excluded.Add([pscustomobject]@{ruta=$relative; bytes=$entry.Length; categoria=$category; motivo=$reason})
        }
    }
}
$reportRoot = Safe-Child $destRoot 'docs/extraccion'
New-Item -ItemType Directory -Path $reportRoot -Force | Out-Null
foreach ($name in @('vista_previa.csv','inventario_excluidos.csv','bloqueados.json','inventario_incluidos.csv','resumen.json')) {
    $null = Safe-Child $destRoot ('docs/extraccion/' + $name)
}
$checks | Export-Csv -LiteralPath (Join-Path $reportRoot 'vista_previa.csv') -NoTypeInformation -Encoding UTF8
$excluded | Sort-Object ruta | Export-Csv -LiteralPath (Join-Path $reportRoot 'inventario_excluidos.csv') -NoTypeInformation -Encoding UTF8
ConvertTo-Json -InputObject @($blocked.ToArray()) -Depth 4 | Set-Content -LiteralPath (Join-Path $reportRoot 'bloqueados.json') -Encoding UTF8
if ($blocked.Count -gt 0) {
    @{modo='bloqueado'; bloqueados=$blocked.Count; copiados=0} | ConvertTo-Json |
        Set-Content -LiteralPath (Join-Path $reportRoot 'resumen.json') -Encoding UTF8
    $blocked | Format-Table -AutoSize | Out-Host
    throw "$($blocked.Count) incorporaciones bloqueadas. No se copio ningun archivo de fuentes."
}
if ($Aplicar) {
    foreach ($folder in @('capturas', 'demo', 'docs')) {
        $directory = Safe-Child $destRoot $folder
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
        if (@(Get-ChildItem -LiteralPath $directory -Force).Count -eq 0) {
            [IO.File]::WriteAllText((Join-Path $directory '.gitkeep'), '')
        }
    }
    foreach ($row in $checks) {
        $source = Safe-Child $sourceRoot $row.ruta
        $target = Safe-Child $destRoot $row.destino
        if ($row.accion -eq 'copiar') {
            # Revalidar inmediatamente antes de copiar; nunca sobrescribir.
            if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -cne $row.sha256) {
                throw "Cambio concurrente en origen: $($row.ruta)"
            }
            New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
            [IO.File]::Copy($source, $target, $false)
        }
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -cne $row.sha256) {
            throw "Error de integridad de copia: $($row.ruta)"
        }
    }
    foreach ($relative in $packaging.Keys) {
        $path = Safe-Child $destRoot $relative
        if (-not (Test-Path -LiteralPath $path)) {
            New-Item -ItemType Directory -Path (Split-Path -Parent $path) -Force | Out-Null
            [IO.File]::WriteAllText($path, $packaging[$relative], [Text.UTF8Encoding]::new($false))
        }
    }
    $checks | Export-Csv -LiteralPath (Join-Path $reportRoot 'inventario_incluidos.csv') -NoTypeInformation -Encoding UTF8
}
$summary = [ordered]@{
    modo=$(if ($Aplicar) {'aplicado'} else {'vista-previa'});
    origen=$sourceRoot; destino=$destRoot; remoto=$remote;
    archivos_seleccionados=$checks.Count; bytes=($checks | Measure-Object bytes -Sum).Sum;
    para_copiar=@($checks | Where-Object accion -eq 'copiar').Count;
    identicos=@($checks | Where-Object accion -eq 'identico').Count;
    entradas_excluidas=$excluded.Count; bloqueados=$blocked.Count;
    adaptaciones_empaquetado=@($packaging.Keys);
    aviso='Los subarboles de Git, entornos y caches se reportan agrupados. No hubo simulacion, commit, push ni PR.'
}
$summary | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $reportRoot 'resumen.json') -Encoding UTF8
$summary | ConvertTo-Json | Write-Output
