# Recuperación y fuente SQLite directa de SimZ1

Revisión del 21 de octubre de 2026. Solo SimZ1; se conservan los insumos OSM,
los resultados científicos y los laboratorios anteriores.

## Evidencia de la corrida histórica

Corrida: `run-massive-fixed-97e840b02c044fc39497debc91300a6d`.
Identidad: `simz1-0dd152dabbc24d1d84d9b738c449cc35`, iteración `0`.
SHA256 de `run-manifest.json`:
`2d93aa7cd197200761917e6cf0c1c7d2848aaeb5102b502e744799bd8814f456`.

El manifiesto científico registra `completed/valid`, 227187 personas/viajes,
154387 viajes completados y 72800 censurados. Esto no significa que todos
llegaron ni acredita estabilidad física. No se altera su significado.

La inspección actual, de solo lectura, comprobó identidad, esquema e índices
de SQLite, inventario/tamaños y metadatos acotados de `0000.html`. No se repitió
el análisis de los 10322591 segmentos, el hash de toda la base ni su comprobación
completa. La auditoría anterior del usuario validó los 81 HTML; esta revisión
no repite esa lectura de 31,46 GB.

| Evidencia existente | Bytes | GiB |
|---|---:|---:|
| `webgl-source/replay.sqlite` | 24926273536 | 23,214 |
| 81 HTML `0000.html`–`0080.html` | 31458970472 | 29,298 |
| Ambos conjuntos | 56385244008 | 52,513 |

Faltan `0081.html`–`0095.html` y `export-manifest.json`. Los HTML llegan hasta
20:15. `export_identity` coincide con el manifiesto científico. Existen índices
`segments_block(block,segment)`, `segments_journey(journey,id)`,
`lanes_time(time,seq)` y `lanes_vehicle_time(vehicle,time,seq)`. Consultas de
extremos por índice encontraron segmento 10322591, registro de carril 40829251
y pertenencia al bloque 95; no sustituyen la validación de integridad.

Los metadatos registran 186123 vehículos seleccionados con eventos, 186066 con
segmentos dibujables, 57 sin segmentos y `unsampled_vehicles=0`. Conservar
227187 personas no exige inventar 227187 posiciones visibles. Algunos campos
de tipo de agente/vehículo son `null` en esta corrida y siguen no disponibles.
Los viajes censurados conservan identidad, nulos y último instante observado.

## Causa y viabilidad

El fallo original ocurrió después de MATSim: `block_records()` ordenaba BLOBs
y metadatos repetidos mediante `USE TEMP B-TREE FOR ORDER BY`. A 52,51 GiB
persistentes se sumó almacenamiento temporal SQLite. La recuperación posterior
eligió `E:`, que no existe, y revisó los HTML antes de detectar la imposibilidad
de escritura. El continuo recibió después una ruta inexistente. Además,
`--audit-only` devolvía 0 aunque faltaban 15 bloques y el manifiesto final.

**Los 96 HTML no son necesarios para consultar movimientos.** El continuo ya
lee segmentos, `Motion_Plan`, viajes y carriles desde SQLite por ventanas de
120 segundos. Los HTML proporcionaban configuración visual y series nativas de
señales/incidentes. El contrato directo separa esas funciones sin declarar
completa una exportación paginada parcial.

Esta base histórica no guarda señales/incidentes. No se encontró una caché
`simz1-native-side-data-*.json` en workspace ni TEMP. Las observaciones faltantes
de 20:15 a 24:00 requieren leer los eventos nativos una vez para recuperar solo
señales/incidentes, o reutilizar una caché validada equivalente. No se extraen
ni calculan de nuevo trayectorias, ni se extrapolan fases semafóricas.

## Contratos e integridad

`export-manifest.json` sigue exigiendo todos los HTML declarados. La fuente
directa publica otro contrato: `sqlite-source/sqlite-source-manifest.json`,
`schema_version: 1`, `source_type: sqlite-direct-v1`, `status: complete` y
`sample_rate: 1`. Sus bloques son referencias al índice `segment_blocks`, no
una afirmación de que existen HTML.

El contrato vincula `run_id`, iteración, hash del manifiesto científico, base
externa con ruta/tamaño/fecha/SHA256, validación SQLite, configuración y series
nativas. `source-config.json` y `source-side.json` tienen tamaños y hashes.
La publicación histórica valida el HTML ancla y muestras contra SQLite, esquema,
índices, `quick_check`, cantidad/continuidad de IDs, extremos por bloque y hash
de la base. Valida que la serie semafórica completa concuerde con su conteo y
procedencia. No basta que la base pueda abrirse.

La base se abre con `mode=ro` y `query_only=ON`: no se copia, modifica, reindexa
ni ejecuta `VACUUM`. El continuo conserva el hash de su manifiesto de fuente y
la identidad de cada viaje. El servidor revisa identidad, esquema, tamaños y
fechas, hashes de metadatos y del manifiesto nativo; no vuelve a hashear 24,93 GB
en cada ventana. Rechaza fuentes incompletas o incompatibles. La publicación
final sucede después de validar componentes; un archivo parcial no es un
contrato completo. `--resume-incomplete` reutiliza solo evidencia verificada de
la misma preparación.

La preparación histórica del usuario realizará la lectura completa necesaria
para `quick_check` y hash. No se ejecutó en esta tarea. Tampoco se publicaron
el contrato/visor real ni se validaron todas sus ventanas: **no se declara
recuperado el visor histórico**. Los fixtures pequeños verifican comportamiento
de ventanas y UI sin MATSim, servidores ni navegadores.

## Espacio y temporales

Solo se encontró `C:` como volumen con letra, NTFS: 9910747136 bytes libres en
la lectura de referencia, unos 9,91 GB / 9,23 GiB; cambia con el uso del equipo.
`E:` no existe. `TEMP`/`TMP` apuntan a `C:\Users\gegdg\AppData\Local\Temp`.
No se hallaron `-wal`, `-shm` ni `-journal` junto a SQLite.

| Alternativa | Espacio adicional |
|---|---|
| SQLite histórico directo | Cero copia de SQLite y cero HTML de movimientos nuevos. Configuración, series nativas, recibos y aplicación; tamaño final aún no medido. El contrato limita cada JSON de metadatos a 128 MiB y comprueba espacio antes de publicarlo. |
| Completar en la carpeta original | Estimación anterior: 7,69 GB de HTML faltante más staging/caché/reserva. Aproximadamente 11,00 GB libres si destino/scratch comparten volumen; no caben en los 9,91 GB observados. |
| Destino externo nuevo, scratch en el mismo volumen | Copia además los 31458970472 bytes existentes. Aproximadamente 42,45 GB libres incluyendo staging/caché/reserva. |
| Destino externo y scratch en volúmenes distintos | Aproximadamente 41,92 GB libres en destino y 3,30 GB en scratch, con reservas separadas de 2 GiB. |
| Nueva extracción SQLite directa | Sin HTML de movimientos. El ejemplo presupuesta 32 GiB para SQLite y 32 GiB para scratch, más reserva de 2 GiB por volumen; no es una medición ni garantía para cualquier demanda. |

Los valores 7,69/39,77/1,15 GB del diagnóstico anterior están redondeados; no son
bytes exactos. El paginado calcula `destination_required_bytes` como copia de
HTML existentes + HTML faltantes estimados + mayor bloque de staging; scratch
es ese mayor bloque + 512 MiB. Si comparten volumen, cuenta el staging una vez
y añade caché y reserva. El preflight actual y los controles de escritura
prevalecen sobre estas estimaciones.

La preparación directa comprueba el tamaño serializado de sus metadatos y
presupuesta dos copias más 64 MiB de reserva predeterminada antes de publicación
atómica. Recuperar las
series nativas también exige espacio previo en scratch y limita su caché a
128 MiB; `source-config.json` y `source-side.json` admiten como máximo 128 MiB
cada uno. El preflight de scratch histórico exige 128 + 64 = 192 MiB libres;
el destino calcula `2 × (configuración + series + 64 KiB) + 64 MiB`, además de
los controles de espacio del continuo. La fuente conserva las series en
`source-side.json`, sin gzip. No se promete un tamaño
real exacto hasta crear los metadatos. La nueva extracción usa presupuestos
explícitos para la base e índices, aplica `max_page_count` a SQLite y exige
64 GiB más 2 GiB de reserva si los presupuestos de 32 GiB comparten volumen.
Son configurables; no incluyen resultados científicos ni reservan físicamente
capacidad. Elegir una ruta temporal real: `SQLITE_TMPDIR` por sí
solo no redirige todos los temporales SQLite en Windows.

## Abrir la corrida histórica

Comandos para ejecución posterior del usuario; no se ejecutaron exportaciones
masivas, MATSim, servidores ni navegadores en esta revisión. Usar el entorno
Python del proyecto, preparado según el [README](../README.md).

```powershell
Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$py = '.\.venv\Scripts\python.exe'
$run = (Resolve-Path -LiteralPath 'scenarios\zona1\montecarlo\run-massive-fixed-97e840b02c044fc39497debc91300a6d').Path
$source = Join-Path $run 'webgl-source'
# Nuevos artefactos fuera de la corrida original.
$work = Join-Path (Get-Location).Path 'runtime\simz1-227187-direct'
$viewer = Join-Path $work 'webgl-continuo'
$scratch = Join-Path $work 'scratch'
New-Item -ItemType Directory -Force -Path $scratch | Out-Null
& $py -B .\python\simz1_continuous_replay.py --source $source --output $viewer --sqlite-direct --run-dir $run --iteration 0 --allow-native-side-scan --temp-dir $scratch --window-seconds 120 --start 0 --end 86400
if ($LASTEXITCODE -ne 0) { throw 'Fuente incompleta/inválida; conservar originales y parciales.' }
& $py -B .\python\verify_simz1_continuous_data.py --directory $viewer --offline
if ($LASTEXITCODE -ne 0) { throw 'Las ventanas no pasaron su verificación; no abrir el visor.' }
& $py -B .\python\serve_simz1_continuous.py --directory $viewer --port 8793 --open
```

La lectura de base/eventos puede tardar. Tras una interrupción, repetir la
preparación agregando `--resume-incomplete`. Para reabrir un visor ya preparado,
ejecutar solo el comando del servidor. Valida antes de atender peticiones;
`Ctrl+C` lo cierra. No repetir MATSim para corregir el export.

La comprobación `--offline` compara los datos de ventanas 00:00, 07:48, 12:00,
23:59 y 24:00 con la fuente, sin iniciar un servidor ni navegador. Comprueba
identidad, campos nativos, `Motion_Plan`, viajes, carriles y señales. Esta
comprobación sobre la corrida histórica queda para la ejecución del usuario.

## Auditoría y alternativa paginada

| Estado | Código | Significado |
|---|---:|---|
| `COMPLETE` | 0 | Bloques esperados y manifiesto final válidos. |
| `INCOMPLETE` | 2 | Faltan bloques o manifiesto. |
| `INVALID` | 3 | Corrupción, identidad o contrato incompatible. |
| `STORAGE_UNAVAILABLE` | 4 | Unidad/carpeta no disponible o destino no escribible. |
| `INSUFFICIENT_SPACE` | 5 | Espacio disponible insuficiente. |

`--diagnose` genera un informe de solo lectura: 0 significa **diagnóstico
obtenido**, no exportación completa. Expone operación y estado separadamente.
`--audit-only`/`--verify-final` exige completitud: 81/96 o manifiesto ausente
devuelve un código distinto de cero. Ninguna exportación parcial es `successful`
ni `valid` como resultado final.

```powershell
& $py -B .\python\simz1_recover_paged.py --run-dir $run --source $source --iteration 0 --expected-blocks 96 --diagnose
# Se espera INCOMPLETE/código 2 en la fuente histórica:
& $py -B .\python\simz1_recover_paged.py --run-dir $run --source $source --iteration 0 --expected-blocks 96 --verify-final
```

Elegir unidades reales con `Get-PSDrive -PSProvider FileSystem`; no hay una
letra externa predeterminada. La recuperación valida unidad, escritura,
sistema de archivos y espacio antes de inspeccionar/copiar masivamente.
Omitir `--output` reutiliza la carpeta original sin copiar sus 81 HTML. Otra
carpeta conserva los originales pero necesita copiarlos. Este comando está
condicionado a que el preflight encuentre capacidad suficiente:

```powershell
& $py -B .\python\simz1_recover_paged.py --run-dir $run --source $source --temp-dir $scratch --iteration 0 --expected-blocks 96 --reserve-gib 2
if ($LASTEXITCODE -ne 0) { throw 'Recuperación no completada; conservar la evidencia.' }
& $py -B .\python\simz1_recover_paged.py --run-dir $run --source $source --iteration 0 --expected-blocks 96 --verify-final
if ($LASTEXITCODE -ne 0) { throw 'No abrir como export paginado completo.' }
```

Para otra ubicación agregar `--output $destination` con una ruta real. El
SQLite se referencia, ahorrando otros 23,21 GiB de copia. Reanudar con las
mismas rutas verifica recibos y reutiliza los bloques íntegros byte por byte;
genera solo faltantes y publica el manifiesto al final. No sobrescribe un
original corrupto ni elimina parciales fallidos.

## Futuras corridas de 150000–250000 personas

Desde un clon limpio seguir la instalación y preparación del
[README](../README.md): resultados locales y derivados OSM ignorados no aparecen
por clonar Git. Registrar insumos con hash y semillas. Este ejemplo pide una
corrida nueva, una iteración y rango inclusivo; conserva los supuestos del modo
`network` y `redistribute`. No acredita calibración ni capacidad vial. Elegir
antes un volumen real con espacio para resultados científicos, base y scratch;
los 9,23 GiB libres actuales en `C:` no cumplen el presupuesto de extracción.

```powershell
$py = '.\.venv\Scripts\python.exe'
Get-PSDrive -PSProvider FileSystem | Format-Table Name,Root,Free
$base = (Resolve-Path -LiteralPath (Read-Host 'Carpeta existente en una unidad real con espacio para la corrida y exportacion')).Path
# Presupuesto del export: 64 GiB + 2 GiB reserva; prever ademas los resultados MATSim.
& $py -B -c "import sys; sys.path.insert(0,'python'); from simz1_recovery_io import preflight_storage; print(preflight_storage(sys.argv[1],64*1024**3,2*1024**3,probe_write=True,largest_file_bytes=32*1024**3))" $base
if ($LASTEXITCODE -ne 0) { throw 'Elegir almacenamiento con capacidad suficiente antes de simular.' }
$future = Join-Path $base ('run-direct-' + [guid]::NewGuid().ToString('N'))
& $py -B .\python\ejecutar_simz1.py --config .\scenarios\zona1\config-simz1.xml --run-dir $future --mode montecarlo --massive --min-agents 150000 --max-agents 250000 --seed 20261021 --matsim-seed 20261021 --iterations 1 --corridor-policy redistribute --temporal-profile full-day --trips-per-person 1 --drain-seconds 0
if ($LASTEXITCODE -ne 0) { throw 'MATSim no terminó validado; conservar la corrida.' }
$newSource = Join-Path $future 'webgl-source'
$newViewer = Join-Path $future 'webgl-continuo'
$newScratch = Join-Path $future 'replay-scratch'
New-Item -ItemType Directory -Force -Path $newScratch | Out-Null
& $py -B .\python\visualizador_z1.py --run-dir $future --iteration 0 --sqlite-direct --output (Join-Path $newSource 'index.html') --window-seconds 900 --replay-start 0 --replay-end 86400 --sqlite-budget-gib 32 --scratch-budget-gib 32 --temp-dir $newScratch
if ($LASTEXITCODE -ne 0) { throw 'Fuente detenida; no volver a ejecutar MATSim.' }
& $py -B .\python\simz1_continuous_replay.py --source (Join-Path $newSource 'sqlite-source') --output $newViewer --window-seconds 120 --start 0 --end 86400
if ($LASTEXITCODE -ne 0) { throw 'El continuo no quedó completo.' }
& $py -B .\python\verify_simz1_continuous_data.py --directory $newViewer --offline
if ($LASTEXITCODE -ne 0) { throw 'Las ventanas no pasaron su verificación.' }
& $py -B .\python\serve_simz1_continuous.py --directory $newViewer --port 8793 --open
```

Exportación y servidor están separados de MATSim. Una interrupción posterior
al SQLite finalizado conserva `spool-ready.json.gz`; repetir el comando
`visualizador_z1.py --sqlite-direct` reanuda la publicación del contrato, sin
generar agentes ni sobrescribir la fuente. No reanuda la extracción de eventos
interrumpida antes de finalizar SQLite: esa base se conserva y se rechaza como
fuente completa; no se publica un manifiesto que la oculte.

## Limpieza segura

No se borró ningún archivo. No se identificó un temporal histórico concreto
que sea seguro eliminar ahora. No ejecutar limpieza genérica de TEMP, SQLite,
HTML ni corridas protegidas de 100000 y 229629 personas.

Después de cerrar exportador/servidor y verificar el contrato final, inventariar
únicamente scratch de esa preparación. Antes de retirar un archivo, comprobar
su ruta absoluta, identidad y que ningún manifiesto final lo referencia. Una
caché nativa permite reanudar sin releer eventos; los recibos evitan auditorías.
Los `.partial`/`.tmp` son evidencia hasta revisar su origen. Conservar
`replay.sqlite`, los 81 HTML, eventos, planes, insumos, logs y manifiestos
científicos. No ejecutar `VACUUM` sobre la fuente histórica.

## Validación pequeña de esta revisión

Resultado final: **88 pruebas Python aprobadas** en 53,865 segundos, usando
`.venv` y `unittest`. Se seleccionaron explícitamente los casos sin servidor de
replay paginado/continuo, junto con recuperación, fuente directa, ciclo de
exportación, verificador offline, cierre diario, contexto y caché. No se
eliminaron pruebas. Una conexión del fixture de contexto se cierra ahora
explícitamente para liberar su SQLite en Windows.

La prueba de exportación nueva utiliza XML constante con dos segmentos: ejecuta
el exportador, SQLite, configuración, publicación del contrato y consultas
continuas reales del fixture, sin generar población ni ejecutar MATSim. La
fuente diaria tiene seis registros y cubre 00:00, 07:48, 12:00, 23:59 y 24:00,
seek inverso, viajes completos, nulos, carriles y señales. Los fallos cubren
unidad ausente, permisos, capacidad, FAT32, 81/96, 96/96, manifiesto ausente,
corrupción/truncamiento, identidades, pertenencias temporales faltantes o
duplicadas, payload incompatible, interrupción y reanudación.

También aprobaron las seis suites Node (DOM/Deck/HTTP simulados, sin navegador):
`test_simz1_continuous_replay.cjs`, `test_simz1_continuous_bootstrap.cjs`,
`test_simz1_vehicle_card.cjs`, `test_simz1_vehicle_picking.cjs`,
`test_simz1_vehicle_focus.cjs` y `test_simz1_spatial_view.cjs`.
Comprueban tarjeta de seis campos, hover, selección, seguimiento, cambios de
ventana, carriles, etiquetas y conservación de identidad. No miden FPS reales.

AST de 15 archivos Python e inventario JSON de instalación: correctos.
`git diff --check`: sin errores de espacios. Las pruebas masivas, los casos
HTTP que abren puertos y las corridas protegidas quedaron fuera de ejecución.

## Archivos de esta revisión

- Fuente y exportación: `python/simz1_sqlite_source.py`,
  `python/simz1_sqlite_export.py`, `python/simz1_continuous_replay.py`,
  `python/simz1_paged_replay.py`, `python/visualizador_z1.py`.
- Recuperación y auditoría: `python/simz1_recover_paged.py`,
  `python/simz1_recovery_io.py`, `python/simz1_recovery_native.py`,
  `python/verify_simz1_continuous_data.py`.
- Pruebas: `python/test_simz1_sqlite_source.py`,
  `python/test_simz1_sqlite_export.py`, `python/test_simz1_continuous_offline.py`,
  `python/test_simz1_paged_recovery.py`, `python/test_simz1_paged_replay.py`,
  `python/test_simz1_transition_context.py`.
- Documentación/inventario: este documento existente y
  `scripts/installation/simz1-required-files.json`.

`serve_simz1_continuous.py` fue revisado y conserva sus controles: instancia
`ContinuousReplay` antes de abrir el servidor y usa su contrato verificado.
Los cambios previos ajenos a esta tarea se conservaron. No se hizo commit ni push.
