# SimZ1 — Tarea 2: limpieza de carga y causa propagada

Estado: **LISTO PARA VALIDATE/PREFLIGHT**, respaldado por pruebas focalizadas.
Esto no aprueba una corrida masiva ni sustituye Validate integrado.

La Tarea 1 permanece intacta: su cierre registra 74 pruebas aprobadas y la lectura
nativa de los 75 enlaces correctos de `z1_97936`. Se leyó ese cierre y su evidencia;
no se repitió la investigación ni se inició MATSim entre tareas.

## Corrección y alcance

`SimZ1Freight` se registra como `MobsimBeforeCleanupListener`. El callback nativo
encola un marcador de ciclo de vida en el mismo `EventsManager`, antes de los
abortos emitidos por los motores en `QSim.cleanupSim()`. El estado cambia cuando
el handler consume ese marcador, no desde el hilo del callback: un aborto normal
que aún esté en cola antes del marcador conserva su rechazo. No se llama a una
barrera del gestor manteniendo el monitor sincronizado del handler.

Un actor de la flota que nunca partió puede cerrar únicamente tras ese marcador,
con tiempo finito, no decreciente y no anterior al inicio de cleanup. Queda como
`aborted_before_departure`, con evidencia `qsim_cleanup_without_departure`, hora
y fuentes terminales. No se rellenan partida, entrada/salida vial ni infracción
de residencia; no se crea una llegada. `requireApproved()` sigue rechazándolo.

El estado de cleanup usa un token nuevo en cada `reset()`. Se mantienen los pares
`stuckAndAbort`/`vehicle aborts` del mismo instante, rechazando repeticiones y
conflictos. También se rechaza una partida posterior al cierre sin partida.
Los camiones que esperaban incorporación no adquieren residencia vial; los que
estaban en tráfico conservan las infracciones observadas al abortar.
`notifyAfterMobsim()` persiste el informe incluso si la excepción primaria impide
alcanzar `IterationEnds`; ese callback no invoca `requireApproved()` para generar
otro fallo de cierre. La guarda de aprobación permanece en `IterationEnds` y se
comprueba directamente en los casos incompletos.

`diagnostico_causal_log()` ahora separa el primer error impreso de la excepción
propagada. Un bloque explícito y completo `SIMZ1_CAUSE` tiene precedencia sobre
el orden cronológico de los ERROR. Conserva cadena, líneas originales y errores
secundarios. Los bloques incompletos, ramas ambiguas o bloques contradictorios
no se resuelven escogiendo la última excepción: se registra incertidumbre.

Se ajustó `SimZ1FailureReport` porque el formato anterior usaba solamente profundidad
para causas y excepciones suprimidas; no permitía distinguirlas con certeza.
El formato nuevo etiqueta `root`, `cause`, `suppressed` e `injector`, y termina
con `SIMZ1_CAUSE end`. El extractor conserva la lectura explícita del formato
histórico lineal. No se reescriben los logs anteriores.

| Archivo | Métodos/cambios de la Tarea 2 |
| --- | --- |
| `src/main/java/gt/edu/uvg/sim/zona1/SimZ1Freight.java` | `install`, `notifyMobsimBeforeCleanup`, `beforeCleanup`, `notifyAfterMobsim`, `reset`, `handleEvent`, `writeReport`; marcador privado de cleanup. |
| `src/main/java/gt/edu/uvg/sim/zona1/SimZ1FailureReport.java` | `print`/`report`: relaciones de excepciones y fin explícito del bloque. |
| `python/ejecutar_simz1.py` | `_primer_error_log`, `diagnostico_causal_log` y cierre fallido de `ejecutar`: persisten causa propagada, primer ERROR, secundarios e incertidumbre. |
| `src/test/java/gt/edu/uvg/sim/zona1/SimZ1FreightClosureCheck.java` | `neverDepartedCleanup`, `orderedUnstartedCleanup` y `main`: componentes y gestor paralelo real, sin QSim. |
| `src/test/java/gt/edu/uvg/sim/zona1/SimZ1FailureReportCheck.java` | Etiquetas y salida real Java para comprobar el extractor Python. |
| `python/test_simz1_signals_config.py` | `CausalDiagnosticTests`: log histórico, incertidumbre, secundarios y lanzador con proceso sustituido por un doble inerte. |
| `python/test_simz1_failure_cleanup.py` | Entrada focal de compilación y pruebas; evidencia y preservación de hashes. |
| `scripts/simz1_workflow.ps1` | Ejecuta la regresión nueva después de la Tarea 1 y antes de publicar recibos. |

El fingerprint existente incluye recursivamente las fuentes Java, pruebas Python
y scripts modificados. Una prueba con un árbol temporal verifica que cada uno de
los ocho componentes de ejecución/prueba cambia ese fingerprint. No se renovó
ningún recibo ni se marcó Validate aprobado.

## Evidencia y pruebas ejecutadas

Corrida histórica de solo lectura:
`scenarios/zona1/montecarlo/run-bg180-dd9e2a9d64fc4764835fed6602faf191`.
Run: `simz1-8545ef106cbe43ce8fabb81bf0bc0a41`.

El log completo tiene SHA256
`f986ce076a40f3659936572d52ee222e0c312a96a1a891bce4366b40c0cde367`.
La lectura corregida identifica la cadena explícita de las líneas **2532 y 2551**:
`Occupancy route cursor mismatch for z1_97936: 0`. El stack de cleanup con
`Freight abort without departure: freight_000002` queda como secundario.
El manifiesto histórico conserva su cadena vacía y diagnóstico antiguo.
El roster sigue indicando partida `52.69614317752584`, posterior al cleanup en 1.0.

Ejecuciones finales del 2026-11-01:

| Ejecución | Resultado real |
| --- | --- |
| `.venv\Scripts\python.exe -B python\test_simz1_failure_cleanup.py` | **21 pruebas, código 0**, cero fallos/errores/omisiones. |
| JDK17, compilación de dos fuentes y tres checks Java en directorio separado | **0**; no se reemplazó `target/classes`. |
| `SimZ1FreightClosureCheck.main()` | **0**; conserva rechazos y termina `finishProcessing()` para el no iniciado durante cleanup. |
| `SimZ1FailureReportCheck.main()` y extracción de su salida real | **0**; la causa no se sustituye por la excepción suprimida. |
| Siete contratos PowerShell aislados: códigos, wrappers, primer ensayo, resultados nativos, herramientas fallidas, validador fallido y sintaxis | **7 pruebas, código 0**. |

Artefactos finales: `runtime/failure-cleanup-632wnuky/`, con resultados, comandos,
códigos Java, copia completa del log histórico y hashes antes/después en
`preservation.json`. Contratos PowerShell:
`runtime/failure-cleanup-wbftvjsd/manual-contract-tests.log`.
El informe nativo de la prueba de `notifyAfterMobsim` se conserva como
`freight-unstarted-report.csv`. Los cinco bloques manuales se validaron con el
parser de PowerShell y metadata de sus parámetros, código 0, sin ejecutarlos.

El check paralelo genera deliberadamente un aborto **antes** del marcador para
comprobar su rechazo. Su ERROR esperado permanece en el log del check, cuyo
código final es 0. La fixture del lanzador devuelve deliberadamente código 1:
se verifica que el manifiesto temporal queda `failed`, conserva ese código, el
log íntegro y no modifica `latest-successful`. Un primer intento de esa prueba
devolvió 1 por duplicar CRLF en el doble de proceso; corregido el doble, la suite
focal completa pasó. No se ocultaron errores de una ejecución real.

No se ejecutaron Controller/QSim, Validate integrado, Run1000, DryRun masivo,
generación/corrida masiva ni visor. No se modificaron movimiento, rutas, horarios,
ventanas, OSM, accesos efectivos, separación 0.10 m, FIFO o guardas físicas.

## Comandos manuales completos

**No ejecutados en esta tarea.** Se comprueban sintaxis, parámetros contra las
entradas actuales y códigos mediante contratos aislados; no se afirma que hayan
pasado Validate o preflight reales. Ejecutar cada bloque por separado y detenerse
ante un fallo. Validate integrado sí contiene pruebas de simulación existentes.

Validate:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_simz1_110k_balanced_gateway.ps1 -Action Validate
$code = $LASTEXITCODE
switch ($code) {
    0 { Write-Host 'Validate integrado termino correctamente; aun falta preflight.' }
    1 { throw 'Validate fallo. Conservar evidencia; no ejecutar DryRun ni Run.' }
    default { throw "Validate devolvio codigo inesperado $code; detenerse." }
}
```

DryRun de la entrada exacta 180000, semilla 20261023, una iteración:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -DryRun
$code = $LASTEXITCODE
switch ($code) {
    0 { Write-Host 'Preflight paso; no se ejecuto MATSim. Revisar la evidencia del lanzamiento.' }
    1 { throw 'Preflight bloqueado/fallido. No ejecutar Run ni modificar aprobaciones.' }
    default { throw "Preflight devolvio codigo inesperado $code; detenerse." }
}
```

Run, solo cuando se decida ejecutar una nueva corrida después de los controles:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -Run
$code = $LASTEXITCODE
switch ($code) {
    0 { Write-Host 'Pipeline completed/valid y screening_pass; no equivale a calibracion cientifica.' }
    1 { throw 'Fallo/bloqueo tecnico. Revisar estado, manifiesto y logs; no repetir MATSim automaticamente.' }
    3 { Write-Warning 'MATSim completed/valid, pero screening review_required. Conservar resultados y revisar evidencia.' }
    default { throw "Codigo inesperado $code. Conservar el codigo y toda la evidencia." }
}
```

Los dos bloques anteriores exigen el gate normal de Run1000 vigente. Si se decide
**expresamente** un primer ensayo sin Run1000, ambos wrappers admiten agregar
`-FirstScaleTrial`: registra esa elección y sigue exigiendo Validate/fingerprint
y runtime correctos. No es una aprobación ni se añadió por defecto.

Monitoreo por LaunchId explícito (el nombre del script también cubre 180K):

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_simz1_110k.ps1 -List
if ($LASTEXITCODE -ne 0) { throw 'No se pudo listar la evidencia de lanzamientos.' }
$launchId = Read-Host 'LaunchId exacto de la nueva corrida'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_simz1_110k.ps1 -LaunchId $launchId -Watch
if ($LASTEXITCODE -ne 0) { throw 'Monitoreo detenido; revisar los archivos de evidencia.' }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_simz1_110k.ps1 -LaunchId $launchId -Evidence
if ($LASTEXITCODE -ne 0) { throw 'No se pudo leer la evidencia solicitada.' }
```

AnalysisOnly, exclusivamente para una corrida seleccionada `completed/valid`:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$runDir = Read-Host 'Ruta exacta de la corrida completed/valid'
$runId = Read-Host 'run_id esperado de esa corrida'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_with_analysis.ps1 -AnalysisOnly -RunDir $runDir -ExpectedRunId $runId
$code = $LASTEXITCODE
switch ($code) {
    0 { Write-Host 'Analisis/empaquetado completos y screening_pass; MATSim no se repitio.' }
    1 { throw 'Identidad/estado invalido o fallo de posproceso. Conservar la corrida y corregir el analisis.' }
    3 { Write-Warning 'Resultados conservados; screening review_required. No es fallo nativo de MATSim.' }
    default { throw "AnalysisOnly devolvio codigo inesperado $code; conservar evidencia." }
}
```

La corrida histórica fallida de esta tarea **no** es candidata a AnalysisOnly.
Código 1 puede representar un fallo previo, nativo o de posproceso: comprobar
`state.json` y `run-manifest.json` antes de decidir el siguiente paso. Código 3
solo significa revisión requerida cuando el contrato confirma `completed/valid`;
no se convierte automáticamente en aprobación ni en fallo de MATSim.

Pendiente: Validate integrado, preflight real y comportamiento en QSim. Ninguno
se ejecutó aquí; no hay aprobación de la masiva.
