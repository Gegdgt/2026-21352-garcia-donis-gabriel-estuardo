# C529-D — Retención confirmada entre fases e instalación nativa

Se corrige la pérdida de evidencia física de C529-C entre intervalos permisivos cortos. Se conservan C529-A y C529-B. Esto no identifica la causa del atasco histórico ni garantiza descargar la red o completar 180000. No se ejecutó Controller, QSim.run, Validate completo, DryRun, una simulación ni generación de población.

La evidencia focal está en `runtime/c529-d-k8cmz56b/`. Sus JSON/CSV son pruebas de componentes: no son corridas, certificados de llegada, manifiestos completed/valid ni aprobaciones.

## Reproducción antes/después

Primero se ejecutó la fixture contra producción C sin modificar; queda en `runtime/c529-d-before/` (`baseline-sources.json`, `compile.log`, `before.log`, CSV y las dos fuentes copiadas). El comando definitivo también reconstruye esas fuentes desde el commit `340657007640f3c5e7a55d3dbdca39a63d48f09b`, verifica sus SHA256 y las compila aisladamente. No hace rollback del árbol de trabajo.

`signal-evidence.json` verifica el XML fuente: 163 sistemas, 305 configuraciones, ciclo 80; 155 intervalos 0–47 y 150 intervalos 49–78. La fixture usa `Zona1FixedTimeController`, `SignalSystemImpl`, `AmberLogicImpl`, eventos `SignalGroupStateChangedEvent` y permiso de la QLane nativa. Los 47/29 segundos incluyen ámbar. El receptor contiene un vehículo real y no acepta otro; los rechazos proceden de `Zona1QNodeImpl` y `StopAndYield`, sin mocks de GO ni de almacenamiento.

Se consultan 800 pasos, t=80..879, con la misma cabeza/carril/movimiento y evaluaciones cada 60 s. Una muestra completada de 209 s, observada a −391, permanece caducada. La parada exigida inicialmente sigue aplicándose.

| Intervalo permitido | Máximo continuo antes/después | Total físico confirmado | Pérdidas de historia antes → después | Evaluaciones elegibles antes → después | Elegibles en rojo |
|---|---:|---:|---:|---:|---:|
| 0–47 / ciclo 80 | 46 s | 455 s | 10 → 0 | 0 → 9 | 0 |
| 49–78 / ciclo 80 | 28 s | 280 s | 10 → 0 | 0 → 3 | 0 |

Los CSV `before/phase-0-47.csv`, `before/phase-49-78.csv`, `after/phase-0-47.csv` y `after/phase-49-78.csv` registran permiso, color, motivo nativo, conteo físico independiente, intervalo continuo, acumulado, pérdida de historia, evaluación y resultado de `retained()`/`snapshot()`. Los nueve reinicios del intervalo continuo después de la reparación son esperados; ya no borran el acumulado. Las 455 s incluyen el descuento de la parada inicial; no son 10 × 47 s.

## Semántica temporal

Sea h el paso QSim (1 s en estas fixtures), F una confirmación nativa de WAIT físico con permiso y R un WAIT de señal con `nativeHasGreen=false`, color conocido RED/REDYELLOW y motivo `signal_*`. Para una misma cabeza, enlace, carril y siguiente movimiento, el acumulado es:

`W = Σ (t_i − t_(i−1))`, únicamente para pares consecutivos F→F con `0 ≤ t_i − t_(i−1) ≤ h`.

El primer F de cada intervalo aporta cero. R aporta cero. R→F aporta cero. Las confirmaciones duplicadas al mismo timestamp aportan cero. Nunca se suma el intervalo completo entre el primer y último rechazo como si fuese ocupación física continua.

La historia W se conserva a través de R solamente con una cadena observada sin huecos mayores que h y con edad de la última confirmación física ≤300 s. Un hueco, señal desconocida, parada ordinaria, identidad/movimiento diferente o decisión no física invalida el episodio; un F posterior inicia W=0. No se amplió `freshness()` para salvar los rojos.

La elegibilidad actual exige además cabeza realmente ofrecida y lista, identidad y posición nativas coincidentes, siguiente movimiento permitido por el carril, ruta/ocurrencia consistente, señal nativa permisiva, confirmación F fresca (≤2h) y `receiverFeasibility()` todavía rechazando por causa física. Un verde sin nueva confirmación F no reactiva la historia. En rojo `snapshot()` devuelve vacío, aunque pueda conservar una pausa comprobada. Si comprueba recepción libre, elimina la evidencia incluso en rojo.

El umbral no cambia: con `nominal=max(1,longitud/velocidadLibre)`, se exige `nominal+W ≥ 3×nominal` y `W ≥ 60`. Este valor sirve exclusivamente para severidad. No entra en el costo de ruta ni pronostica demora futura.

Se mantiene un agregado por cabeza, sin listas de eventos o reconstrucción de historial. La pausa está limitada a 300 s desde la última confirmación física; una cadena válida puede abarcar varios ciclos, usando memoria constante para tiempos. La firma de ruta conserva una copia del itinerario/índice por cabeza consultada y se limpia con su evidencia. El trabajo por evento sigue siendo local; la revalidación ocurre en la evaluación existente, cada 60 s.

`LinkEnter`/`LinkLeave`, abandono de tráfico, aborto y nueva incorporación limpian lo correspondiente. La consulta verifica el plan mediante `PlanAgent.getCurrentPlanElement()` sin clonarlo. Detecta cambios de ruta posteriores a su firma, incluso modificaciones in situ que conservan el siguiente enlace. El único instalador de producción invalida explícitamente la evidencia en toda instalación, también si sólo cambia un tramo posterior.

| Campo de diagnóstico | Significado |
|---|---|
| `activeRetentionTimeBasis` | `confirmed_physical_intervals_v2` |
| `activeRetentionAccumulatedPhysicalSeconds` | W, suma confirmada entre intervalos |
| `activeRetentionConfirmedSeconds` | `last−since`, intervalo físico continuo más reciente; conserva el significado C |
| `activeRetentionSince` / `activeRetentionLastConfirmed` | Inicio del intervalo reciente / última confirmación física |
| `activeRetentionLastStateObserved` | Último F o R aceptado; R no rejuvenece la confirmación física |
| `activeRetentionEvidenceSpanSeconds` | Tiempo transcurrido desde el primer F del episodio; incluye pausas y **no** representa espera física |
| `activeRetentionUsedAsTravelTime` | Siempre `false` |

Las observaciones completadas mantienen su timestamp y TTL de 300 s. Los costos conservan el modelo existente: muestra reciente de giro, de enlace o velocidad libre/perfil/vehículo, con el tiempo ya transcurrido del enlace actual descontado una sola vez. No se altera el criterio `candidateCost + 1e-9 < oldCost`.

## Instalación de producción, reserva activa y OD obligatorio

`SimZ1RetentionInstallationFixture` configura colas y agentes nativos, `wholeVehicleReservation=true`, almacenamiento estricto, carro de 4.5 m y huella de 4.6 m. Su red es sintética; no modifica las fuentes físicas. El receptor `slow` contiene un vehículo con reserva corporal real.

El contrato EXTERNAL_EXTERNAL_THROUGH se vincula al viaje `a-road:trip:0001` mediante `simz1TripId`, `simz1SpatialOD`, `simz1Trips` y el elemento de escenario `SimZ1TripOd`. La cadena de entrada es `e0,eC,eI`; la salida obligatoria es `V,B,xE`. A/V/B/C usan los enlaces de la secuencia OSM 17478998: `A,V,B` está prohibida; `A,H,C,V,B` es compatible.

El prefijo inicial `e0,eC,eI,A,loop,return,A` es **estado sintético de entrada**, sembrado mediante el cursor del agente nativo y eventos de entrada de prueba. No se afirma haber ejecutado físicamente esas seis transiciones. La comprobación física comienza en la segunda ocurrencia de A, índice 6. No se certifica ninguna llegada. Esto prueba conservación del prefijo por ocurrencia durante la instalación, no la ejecución completa del viaje desde el origen.

La fixture llama `initializeNative()` y `evaluate()`; los callbacks de QSim delegan a estos mismos métodos. No hay segundo instalador. Se recorren `eligible`, `locate`, `candidate`, `SimZ1TripOd.forLeg`, `SimZ1TurnRouter.path`, `SimZ1RouteSafety.validateReplacement`, `SimZ1CorridorOccupancy.replacementIssue`, `activeCandidateIssue`, evaluación de costos y el `attempt()` original. Sólo ese código de producción clona/instala la ruta y reinicia/verifica las cachés.

| Comprobación | Resultado |
|---|---|
| Antes | `[prefijo índice6],slow,detour,C,V,B,xE` |
| Instalado a t=480 | `[mismo prefijo índice6],H,C,V,B,xE` |
| Costo restante | 109.8 → 12.0 s; retención confirmada 464 s excluida del costo |
| Cursor al instalar | 6 → 6; mismo vehículo y destino |
| Reservas/locks al instalar | Snapshot idéntico antes/después; ninguna adquisición o liberación por consultar/rerutear |
| Sin mejora a t=780 | Ruta legal idéntica rechazada con `no_expected_improvement`; ruta, cursor y reservas conservados |
| Pasos nativos posteriores | `QLinkLanesImpl.doSimStep` y `Zona1QNodeImpl.moveVehicleOverNode`; siguiente movimiento efectivo A→H, cursor 6→7, `LinkEnterEvent` nativo |
| Negativa con terminal comprometida | Candidato OD/OSM compatible rechazado por `occupancy_reserved_terminal_slot`; misma ruta anterior, cursor 6, siguiente `slow`, ledger/locks intactos |

`after/installation.json` guarda ambas rutas, índices, decisiones reales, snapshots de ledger y el evento nativo de movimiento. El caso de no mejora utiliza una muestra completada sintética del enlace común C, aplicada igualmente a ambas estimaciones; no altera el costo para provocar una mejora. La prueba termina tras el siguiente movimiento, antes de llegada y de completar la cadena de salida. Las restricciones de toda la ruta instalada sí se validan. No se fuerza una reserva, se cambia de carril ni se elimina un vehículo.

## Cambios y pruebas focalizadas

Producción: solamente `SimZ1ActiveRetention.java` (`Wait`, `decision`, revalidación de cabeza/ruta, `snapshot`, limpieza) y `CongestionAwareRerouting.java` (seams de colaboradores/evaluación usados por los callbacks existentes, diagnóstico temporal e invalidación al instalar). No cambian router, OD, prioridad, pasajes, costos, semáforos ni `requireApproved()`.

Pruebas: se extiende `SimZ1RetentionFixture` para conectar el controlador y sus eventos reales; se añaden `SimZ1RetentionPhases`, `SimZ1RetentionPhaseCheck`, `SimZ1RetentionLifecycleCheck`, `SimZ1RetentionInstallationFixture` y `SimZ1RetentionInstallationCheck`. `python/test_simz1_retention_phases.py` compila antes/después y ejecuta todo focalmente con JDK17. `scripts/simz1_workflow.ps1` la llama después de C y propaga errores antes de publicar cualquier validación.

`python/test_simz1_sequence_contract.py` actualiza únicamente la expectativa de `CongestionAwareRerouting`: SHA D `063465c290bc0eba15fa5637d4e1425b4e44a8b5c499417c1c64851dd96cb13b`. Conserva el SHA histórico `215a2dc7580141477fb9d963aab1f1727d7022ae65f599cfad6898b4dc32b6f6`; el SHA C `fb8665999316ff2e913bf87ea56e46444f24941ad14e05f3f829c1f7c164da00` queda fijado en la reproducción antes. No se excluye ningún archivo. El fingerprint existente detecta las fuentes/pruebas nuevas sin modificar su implementación.

El comando focal es:

```powershell
& .\.venv\Scripts\python.exe -B .\python\test_simz1_retention_phases.py --with-routing-regressions
if ($LASTEXITCODE -ne 0) { throw 'Fallo C529-D o sus regresiones de routing.' }
```

Requiere las dependencias/clases base existentes de `target` y `C:\Program Files\Java\jdk-17`; compila aisladamente todas las fuentes cambiadas y los controles A/B usados. No lanza el motor.

Evidencias de la ejecución definitiva:

- `focused-results.json`: PASS, 16 comandos; 13 con código 0 y tres rechazos de mutantes con código 1 esperado. Las 88 comparaciones de históricos/recibos/controles conservados son verdaderas; el comando Python termina con código 0.
- `before-phases.log` / `after-phases.log`: ambos contraejemplos; código 0 significa que se comprobó el resultado esperado antes/después.
- `lifecycle.log`: 1281 aserciones, código 0. Rojo con recepción libre, pausa válida, hueco desconocido, color desconocido, pausa >300 s, señal actual sin confirmación nueva, duplicados, cambio de ruta incluso in situ, carril e identidad.
- `installation.log`: 496 aserciones, código 0; instalación, reserva negativa y falta de mejora por el mismo `attempt()`.
- `C529-C-regression.log`: 65 comprobaciones, código 0; continuidad de 316 s, receptor liberado, movimiento/aborto/salida, incorporación, servicios excluidos, carril incompatible, estimaciones coherentes, cohorte 50%, presupuesto 100, cooldown 300 y frecuencia 60.
- Mutantes aislados `red-clears`, `red-credited`, `reservation-bypassed`: compilación 0, prueba 1 **esperado**, con aserción específica. Demuestran que la suite detecta borrar el historial en rojo, sumarle el rojo e ignorar la reserva. No mutan producción.
- `integration.json`: 112 fuentes protegidas y sensibilidad del fingerprint para cada fuente/prueba incluida; `protected-mutations.log`: siete pruebas de expectativa/hash, código 0.
- `C529-B-routing-regressions.log`: 362 comprobaciones B y paridad Java/Python en 26 rutas; conserva el rechazo histórico de z1_60650 y la secuencia 17478998. Evidencia propia: `runtime/c529-b-wmvlaekk/focused-results.json`, PASS, doce comandos con código 0.

No se ejecuta por rutina la suite global. No se modificaron el paquete C529, corrida histórica, red/carriles/capacidades, geometría, señales/ciclos, servicios, horarios, demanda, semilla, contratos, recibos ni aprobaciones. Se preserva N=180000: 79200 carros, 99000 motos, 1800 camiones y 269 buses adicionales, semilla 20261023 e iteración 0.

## Comandos manuales pendientes

Son operaciones independientes, para que el usuario las ejecute cuando corresponda. No se ejecutaron durante C529-D. Configurar JDK17 en la consola:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Stop'
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17'
$env:Path = "$env:JAVA_HOME\bin;$env:Path"
& "$env:JAVA_HOME\bin\java.exe" -version
if ($LASTEXITCODE -ne 0) { throw 'JDK17 no disponible.' }
```

Validate integrado, única operación que podrá renovar su recibo si todos sus checks pasan:

```powershell
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\simz1_workflow.ps1 -Action Validate -OdMode balanced-gateway-v1
if ($LASTEXITCODE -ne 0) { throw 'Validate fallo; detenerse.' }
```

DryRun/preflight explícito para 180000:

```powershell
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -DryRun -FirstScaleTrial -JavaHome 'C:\Program Files\Java\jdk-17'
if ($LASTEXITCODE -ne 0) { throw 'DryRun fallo; detenerse.' }
```

Ejecución manual 180000, únicamente después de revisar Validate y preflight:

```powershell
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -Run -FirstScaleTrial -JavaHome 'C:\Program Files\Java\jdk-17'
if ($LASTEXITCODE -ne 0) { throw 'Run180000 fallo; revisar la causa y evidencias.' }
```

`-FirstScaleTrial` existe en el wrapper de DryRun/Run, no en Validate; conserva su significado de ausencia de Run1000 previo. El wrapper fija N=180000 y seed=20261023 y conserva sus controles de aceptación. La operación real es `-Run`, no un `-Action Run180000` inexistente.

Quedan sin comprobar aquí la integración de callbacks bajo un QSim completo/concurrente, desempeño y cobertura de eventos en toda la red, efectividad de alternativas bajo carga real, viajes completos, descargas, llegadas y gráficas de 180000. La prueba sí ejecuta la instalación y el siguiente movimiento nativo controlado; no extrapola ese resultado a una corrida aprobada.
