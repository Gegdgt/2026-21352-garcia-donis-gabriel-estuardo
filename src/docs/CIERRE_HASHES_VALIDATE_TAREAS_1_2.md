# SimZ1: expectativas de hashes después de las Tareas 1 y 2

Se corrigió exclusivamente la expectativa de `test_15`. Las ocho comprobaciones
focalizadas finales pasan con código **0**. Esto no declara aprobado Validate,
preflight ni la masiva. No se ejecutó Java, Controller/QSim ni simulación en esta
reparación; tampoco Validate integrado, DryRun o Run1000.

## Revisión completa

Se leyeron AGENTS.md, el diff existente, los cierres
`CORRECCION_SERIALIZACION_RUTAS_SIMZ1.md`, `CIERRE_CARGA_Y_CAUSA_PRIMARIA_SIMZ1.md`
y `CIERRE_CORRECCION_7_OSM_180K.md`, sus evidencias focalizadas y el Validate fallido
`runtime/validation/balanced-launch-17c07d9325bb4acea54002f02c611133/Validate.log`.

Se compararon las **115 entradas** de `preserved-input-hashes.json`: 105 coinciden
con su hash histórico y diez difieren. De las diez, siete ya estaban exceptuadas
por Corrección 7, una es el recibo tratado por su valor al inicio de la suite y
dos son cambios autorizados de la Tarea 2. **No se encontró un cambio protegido
inesperado o sin justificación.** No se atribuyen las excepciones previas a las
Tareas 1/2.

En la tabla, los Java pertenecen a `src/main/java/gt/edu/uvg/sim/zona1/`.
Los hashes abreviados se conservan completos en
`runtime/validate-hash-xkzywdco/audit-before.json`.

| Ruta | Histórico → actual (prefijos SHA256) | Clasificación y tratamiento |
| --- | --- | --- |
| `python/simz1_balanced_od.py` | `02efcfb71ac3` → `803a8a18c823` | Excepción previa de Corrección 7, sin renovación. |
| `python/simz1_od_policy.py` | `e7442da8eb39` → `89b8d66d3986` | Excepción previa de Corrección 7, sin renovación. |
| `python/simz1_workflow_state.py` | `5f3fdfb99483` → `a8e16e858347` | Excepción previa de Corrección 7; fingerprint intacto. |
| `CongestionAwareRerouting.java` | `215a2dc75801` → `e3de1c295f18` | Excepción previa de Corrección 7, sin renovación. |
| `ExperiencedTimeRouting.java` | `58920c0825de` → `08abb5460c8d` | Excepción previa de Corrección 7, sin renovación. |
| `SimZ1RouteSafety.java` | `6905c60cd221` → `323102eafde2` | Excepción previa de Corrección 7, sin renovación. |
| `SimZ1TurnRouter.java` | `b4f9a6d42180` → `43e787803802` | Excepción previa de Corrección 7, sin renovación. |
| `runtime/workflow/validated-balanced-gateway-v1.json` | `cec20a291daa` → `d689e77b4ec2` | Caso especial existente: comprobar valor inicial de la suite. Sin aprobación nueva. |
| `SimZ1FailureReport.java` | `00954a86207d` → `8c5aca71cf44` | A: Tarea 2 autorizada y demostrada; expectativa estática renovada. |
| `SimZ1Freight.java` | `5de26967ad3a` → `8623b0d798d9` | A: Tarea 2 autorizada y demostrada; expectativa estática renovada. |

Los siete archivos exceptuados coinciden con HEAD (considerando los bytes CRLF
del checkout), y sus cambios están descritos en el cierre de Corrección 7. Los
dos Java renovados tienen una base HEAD que coincide con el hash histórico; se
revisó su diff completo. El recibo actual coincide también con los hashes antes
y después de la evidencia de la Tarea 2; no se deduce de ello aprobación vigente.

## Expectativas revisadas

`REVIEWED_SOURCE_EXPECTATIONS`, junto a `test_15`, registra ruta, hash sustituido,
hash esperado, motivo, cierre y cobertura. No toma hashes observados como
expectativa al ejecutar las pruebas.

| Archivo | SHA256 histórico sustituido | SHA256 nuevo esperado |
| --- | --- | --- |
| `SimZ1FailureReport.java` | `00954a86207d6d3a42e44c5356101498eebc17978b3a56fdc6adb9482362c777` | `8c5aca71cf44fdf77a48cb2cd46ee96cf4fff6350bb175287b51bf3694166a1c` |
| `SimZ1Freight.java` | `5de26967ad3a8eee80ca7d45d42c16ab9e634d8dc56ebc9cce844005dd03219c` | `8623b0d798d901fffbda5d4e33d7978081bd90a34b92b2cdcd096d6b7dc51612` |

`SimZ1FailureReport.print/report` distingue la causa propagada de las ramas
suprimidas/injector y delimita el bloque. Cobertura previa: `SimZ1FailureReportCheck`,
su ida/vuelta al extractor Python y `CausalDiagnosticTests`.

`SimZ1Freight` conserva el marcador ordenado de cleanup, el resultado auditable
`aborted_before_departure`, el reinicio entre iteraciones y la persistencia del
informe tras un fallo, sin inventar movimiento ni aprobar incompletos. Cobertura
previa: `SimZ1FreightClosureCheck`, incluyendo gestor paralelo y cierre sin
Controller/QSim. Se conservaron rutas y `notifyBeforeMobsim()`.

Estas comprobaciones figuran en `runtime/failure-cleanup-632wnuky/`: 21 pruebas
con código 0, compilación JDK17 y los dos checks con código 0. Se leyó esa evidencia;
no se volvió a ejecutar la Tarea 2. La evidencia de la Tarea 1 en
`runtime/route-xml-keq3_9er/evidence.json` conserva sus 74 pruebas focalizadas y la
lectura nativa corregida; no se rehízo su investigación ni se modificó producción.

## Cambio y protección

Único archivo de código modificado en esta reparación:
`python/test_simz1_sequence_contract.py`.

- Mapa estático de las dos expectativas revisadas.
- `check_protected_sources()` comprueba primero que cada hash sustituido
  corresponde al baseline original. Compara todos los archivos protegidos y
  reúne las discrepancias; ausencia o hash incorrecto siguen bloqueando.
- `test_15` usa esa comprobación y conserva su aritmética de composición y cuotas.
  Se siguen comprobando **108 entradas**: 105 originales, dos renovadas y el
  recibo inicial. Las siete excepciones presentes en el baseline no se amplían.
- `ProtectedSourceExpectationTests`: siete pruebas pequeñas con copias temporales
  de fuentes y texto sintético para el recibo; ningún recibo real se copia.
- La entrada existente de la suite incluye la clase nueva. Validate ya invoca
  esa entrada antes de emitir recibos; no se modificó el workflow.

El mapa está dentro del archivo Python que el fingerprint existente ya recorre.
Las mutaciones verifican que los dos Java y el valor estático nuevo alteran la
huella. No se modificó `fingerprint()` ni se redujeron sus dependencias.
Las comprobaciones existentes de secuencias, física, composición y servicios
permanecen; no se repitió la suite completa ni el probe Java en esta reparación.

## Resultados y preservación

Artefactos: `runtime/validate-hash-xkzywdco/`.

| Ejecución | Resultado real |
| --- | --- |
| `test_15` antes de reparar | 1 prueba; FAIL; código 1. |
| Primer ensayo de las ocho pruebas | `test_15` OK; siete errores por una ruta de fixture equivocada; código 1. Se corrigió el paquete de `SimZ1CorridorOccupancy` usado solo en la copia temporal. |
| Ejecución final: `test_15` y siete pruebas nuevas | **8 OK; código 0**, sin omisiones. |
| `git diff --check` | Código 0. |

Los negativos comprueban cada Java renovado con un byte cambiado, archivos
ausentes, un byte cambiado en una copia de `SimZ1CorridorOccupancy`, baseline
sustituido incorrectamente o ausente, y desacuerdo con el recibo inicial.
Se conservan logs completos y comandos/códigos de los intentos fallidos y final.

`preserved-input-hashes.json` conserva 115 entradas y exactamente el SHA256
`cccb52f3484bc614e238eaf2cf44c5e2b62dc7f5a586400bb04d15ea083cb8c2`.
Los 15 archivos de `runtime/workflow/`, incluidos los recibos Validate/Run1000,
permanecen intactos. El recibo de Validate mantiene SHA256
`d689e77b4ec2163bf3df27e070a2f306e6a570008c79bfa7fb7d7cbf11c4fa50`.
La comparación antes/después y los 115 registros completos están en
`preservation.json` y `audit-before.json`. Se preservó el diff anterior, incluida
la expectativa XML de la Tarea 1 en este mismo test.

## Comandos manuales

Comprobación focal reproducible, sin simulación:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
Push-Location .\python
try {
    & ..\.venv\Scripts\python.exe -B -m unittest -v `
        test_simz1_sequence_contract.SequenceRegressionTests.test_15_protected_sources_physics_composition_receipt `
        test_simz1_sequence_contract.ProtectedSourceExpectationTests
    if ($LASTEXITCODE -ne 0) { throw "Pruebas focalizadas fallaron: $LASTEXITCODE" }
} finally {
    Pop-Location
}
```

Validate integrado, **para ejecución posterior por el usuario; no ejecutado aquí**:

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

La decisión de primera escala sin otra Run1000 ya está tomada: los comandos
posteriores del wrapper `run_simz1_180k_balanced_gateway.ps1` deben conservar
`-DryRun -FirstScaleTrial` y `-Run -FirstScaleTrial`, respectivamente. Esa opción
no omite Validate ni fingerprint. Este cierre no ejecuta ninguno de esos pasos.

Configuración intacta: 180000 no públicos (79200 carros, 99000 motos, 1800 camiones),
269 buses adicionales, semilla 20261023, una iteración y JDK17; sin cambios en
mapa, accesos, semáforos, FIFO, reservas, separación, dimensiones u horarios.
