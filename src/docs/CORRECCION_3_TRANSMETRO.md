# SimZ1 — Corrección 3: progreso nativo y reservas del Transmetro

Estado de entrega: implementación y regresiones preparadas; **sin compilar ni
ejecutar**. La aceptación funcional queda pendiente de los resultados manuales.
Esta entrega termina en la Corrección 3.

## Hallazgo y límites de la evidencia

Se encontró una dependencia circular en `SimZ1CorridorOccupancy.originalSlot()`.
El método rechazaba cualquier reserva con pasaje activo, también después de que
el vehículo había entrado nativamente al dominio receptor. Por ello,
`QueueWithBuffer.originalSlotHeads()` dejaba de enumerar ese vehículo y
`QLinkLanesImpl.moveIndependentOriginalSlot()` no podía transferirlo a su carril
terminal libre cuando la cabeza del buffer compartido esperaba por otro carril.
El propietario necesitaba avanzar para despejar el pasaje, pero ese mecanismo
de avance exigía implícitamente que el pasaje ya estuviera liberado.

Es un defecto de habilitación del progreso nativo entre carriles independientes,
no un motivo para adelantar la liberación de la reserva. El caso está descrito
como una regresión nativa con un bus de 13.5 m en el slot 1 y una cabeza anterior
del slot 0 cuyo terminal está lleno. Antes del cambio, `originalSlot(bus)` devuelve
`-1` por el pasaje activo; después identifica su slot 1. La prueba preparada
comprueba la transferencia real y la conservación de los locks hasta el despeje.
No se ha ejecutado para afirmar un resultado PASS.

El snapshot histórico consultado, sin modificarlo, fue:

`runtime/diagnostics/masiva-220k-20261031/220-6e92a0d51d9f4d63b5c32970c8bdd6f9/monitor/state_19h.json.gz`

Para `ptbus_transmetro_L12_031`, ordinal 444455:

- Pasaje adquirido a 25440; entrada al receptor a 25447; slot receptor 1.
- Último progreso a 25501, en `osm_1057486080_0_forward.original`.
- Tanto `nativeFrontBoundMeters` como `modeledFrontLowerBoundMeters` valen
  11.448971553979469 m, inferiores a `clearanceFrontMeters=17.279379950716642`.
- El extremo de `.original` en `scenarios/zona1/lanes.xml` es exactamente
  `57.24485776989736 - 45.79588621591789 = 11.448971553979469` m.
- El líder de su slot, `z1_01834`, tiene cota 41.20010826610374 m y huella 4.6 m.
  Su restricción longitudinal, 36.60010826610374 m, no explica la cota menor del
  bus: el límite disponible del bus es el extremo de su cola nativa.
- `z1_206622`, ordinal anterior 443690 y slot 2, también permanece registrado
  en `.original`, con la misma cota de extremo.
- A 68399, `z1_01834` registra rechazo nativo de almacenamiento hacia
  `osm_1057486080_1_forward.original`.

Estos datos son compatibles con el bloqueo entre slots descrito, y acreditan
presión de almacenamiento posterior. El snapshot **no conserva el orden completo
del buffer ni una decisión interna de transferencia para el bus**. Por eso no
se afirma que ese defecto sea la causa única y demostrada de toda la retención
histórica, ni que QSim hubiera desplazado al bus sin notificarlo al ledger.
Tampoco acredita una reserva obsoleta después de un despeje completado.

En términos de las hipótesis solicitadas: A sigue siendo una espera físicamente
necesaria con las cotas disponibles; B y C no están demostradas; D tiene evidencia
nativa en el corredor posterior. El defecto localizado puede impedir un avance
legal dentro del receptor, aun sin atribuirle toda la congestión de 22 Calle.
No se cambia la descarga de ese corredor en esta corrección.

## Cambios y seguridad física

`src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/SimZ1CorridorOccupancy.java`:

- `originalSlot()`: permite identificar el slot ya reservado de un propietario
  con pasaje activo solo después de alcanzar nativamente el dominio receptor.
  Excluye conectores, salidas con reserva retenida en origen, enlaces anteriores
  al receptor y estados sin evidencia nativa de entrada al enlace actual.
- `advanceTime()`, `recompute()` y `releasePassage()`: añaden observaciones;
  conservan exactamente sus predicados y acciones de liberación.
- Nuevos `passageStorageWait()`, `passageWaiting()` y `passageDiagnostic()`:
  observan condiciones y deduplican categorías/condiciones de espera.
  El constructor conserva el tipo de dinámica de tráfico para atribuir
  almacenamiento solo cuando su semántica nativa lo permite.

`QLinkLanesImpl.moveBufferToNextLane()` y
`Zona1QNodeImpl.moveVehicleOverNode()` añaden una llamada diagnóstica tras un
rechazo de recepción. No repiten la consulta de admisión ni cambian su resultado.

`QueueWithBuffer` y `SimZ1PassageTimeListener` permanecen sin cambios. La revisión
del código actual confirmó estas notificaciones existentes:

| Transición | Notificación existente |
|---|---|
| Llegada al buffer, incluida actividad | `addToBuffer()` → `progress()` |
| Vencimiento de earliest exit en cola | `doSimStep()` → `advanceEligible()` |
| Transferencia a otro carril/enlace | `addFromUpstream()` → `enter()` → `nativeEntry()` |
| Reinserción después de parada de transporte | `addTransitSlightlyUpstreamOfStop()` → `enter()` |
| Liberación de espacio por un líder | `release()` → `recompute()` del mismo slot |
| Tiempo mínimo sin otra transición | `notifyMobsimBeforeSimStep()` → `advanceTime()` |
| Llegada nativa confirmada | `letVehicleArrive()==true` → `release(...,"arrival")` |
| Aborto/limpieza nativa | Rutas existentes `release(...,"abort")` / `clearLink()` |

El nuevo reconocimiento de slot no mueve ningún vehículo por sí mismo. La
transferencia sigue requiriendo recepción nativa, `canEnter()`, compatibilidad
del terminal y el mismo slot reservado. `popOriginalSlotHead()` mantiene FIFO
dentro de cada slot, la edad de la cabeza bloqueada y la deuda de flujo.

La liberación por despeje sigue exigiendo simultáneamente `now >= notBefore` y
`frontBound >= clearFront`. La cota sigue siendo el mínimo entre el extremo
nativo acreditado y la cota del líder menos su huella, que incluye 0.10 m.
Consumir un deadline sin despeje no libera nada; `recompute()` sigue pudiendo
liberar después de un avance posterior. Las salidas nativas confirmadas conservan
su semántica de retirar la ocupación y los locks. No hay timeout, teletransporte,
reducción de dimensiones, nuevo crédito de flujo ni liberación de un bus inmóvil.

## Diagnósticos para próximas corridas

Nuevo evento `simz1OccupancyPassageState`, con `reason`:

| Nombre | Evidencia necesaria |
|---|---|
| `passage_waiting_for_time` | Tiempo mínimo aún no cumplido; se informa también si falta cuerpo |
| `passage_waiting_for_body_clearance` | Tiempo cumplido y extremo nativo suficiente, pero la cota conservadora/FIFO sigue debajo del umbral |
| `passage_waiting_for_native_progress` | Tiempo cumplido y extremo nativo registrado insuficiente; no significa por sí solo un fallo de sincronización |
| `passage_waiting_for_downstream_storage` | Cuerpo aún sin despeje y rechazo del receptor real `QueueWithBuffer`, dinámica `queue` y carga PCU mayor o igual a su almacenamiento |
| `passage_released_after_clearance` | Liberación por ambas condiciones cumplidas, no por salida nativa |

Incluye vehículo, ordinal, enlace, slot, cola, cotas, umbral, tiempo mínimo,
banderas de las condiciones, dimensión, gap y líder cuando existe. El rechazo
de almacenamiento incluye receptor y carga/capacidad PCU. Siempre conserva
`positionsObserved=false` y `laneObserved=false`.

El estado de almacenamiento solo atribuye el rechazo de esa cola: no deduce una
cadena causal completa hasta 22 Calle, una señal, ni una posición microscópica.
Las salidas siguen identificándose mediante los eventos existentes
`simz1OccupancyPassage RELEASE` / `simz1OccupancyReservation EXIT`.

No hay escaneo global ni polling nuevo. Cada pasaje conserva una categoría y dos
banderas para suprimir repeticiones mientras permanece en las mismas condiciones.
Los eventos existentes de progreso y el formato de los históricos no cambian.
Los lectores que solo manejan eventos antiguos pueden ignorar este nuevo tipo;
para analizar sus categorías deben seleccionar `simz1OccupancyPassageState`.

## Regresiones preparadas, sin ejecutar

`SimZ1TransitPassageReleaseCheck` reconstruye estados de ciclo de vida mediante
el hook real `acquirePassage()`; no pretende validar la autorización de rutas.
`SimZ1TransitPassageNativeCheck` usa las clases nativas reales de cola y enlace,
un driver de transporte controlado y snapshots aislados de almacenamiento lleno.
No crea un controller ni lanza una corrida de QSim.

| Cobertura pedida | Caso preparado |
|---|---|
| 1, 5, 7 | Bus detenido, buffer sin transiciones, interpretación conservadora hasta 19:00 |
| 2 | Cota exacta después del deadline consumido; liberación única |
| 3 | Cota alcanzada antes del tiempo mínimo fraccionario |
| 4 | Líder libera espacio; recomputación del bus sin inventar extremo nativo |
| 6 | Entrada a carril y siguiente enlace; integración real de cola/buffer/transferencia |
| 8 | FIFO de seguidores y paso nativo del slot independiente con pasaje activo |
| 9 | Cuatro locks propios liberados; pasaje de otro propietario permanece intacto |
| 10 | Salida nativa real de bus, aparcamiento, VehicleLeavesTraffic y ausencia de huérfanas; ID reutilizado/deadline antiguo |
| 11 | 13.5 m, 4.5 m, 2.1 m y 8 m |
| 12 | Separación de 0.10 m, sin FORCE; sin alterar edad, slot ni cabeza bloqueada |

También se preparan comprobaciones de deduplicación durante esperas repetidas y
de no atribuir almacenamiento bloqueado a un receptor disponible.

## Ejecución manual exacta en PowerShell

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& .\scripts\check_simz1_transit_passage.ps1
```

El script crea un directorio `target/correction3-<UUID>`, invoca `test-compile`
con `-DskipTests` y ejecuta únicamente los dos nuevos `main` con
`-Dexec.classpathScope=test`. No borra ni reemplaza compilaciones anteriores.
Compila fuentes de prueba, pero no ejecuta las siete regresiones ya aprobadas,
Validate, Run1000, benchmarks ni escenarios masivos. Requiere el entorno JDK/Maven
habitual del proyecto. El script queda entregado, no ejecutado por el agente.

## Conservación y verificación realizada

Comparación textual con el contenido inicial de esta sesión: intactos los bloques
de prioridad/recepción, rutas, retornos opuestos, reruteo, admisión, adquisición,
`release()`, progreso nativo y reglas de señales. Conservada la tolerancia `1e-8`
de la Corrección 2B. Los hashes de `UnsignalizedPriority`,
`CongestionAwareRerouting`, `QueueWithBuffer`, `SimZ1PassageTimeListener` y las 28
fuentes de prueba preexistentes del paquete son idénticos a los iniciales.
No se sobrescribió el diff previo de las Correcciones 1 y 2.

Solo se realizaron lecturas, edición de fuentes/documentación, comparación de
texto/hashes y revisión de diferencias. No se ejecutó Maven, compilación, Java,
Python, pruebas, MATSim, Validate, Run1000, simulaciones ni benchmarks. No se
abrieron subagentes ni se modificaron archivos históricos, geometría, carriles,
capacidades, dimensiones de producción, señales, rutas o demanda.
