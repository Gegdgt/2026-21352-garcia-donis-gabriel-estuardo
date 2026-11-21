# SimZ1 — Corrección 4: descarga entre corredores

Estado: cambio y regresiones preparados, **sin compilar ni ejecutar**. No se
afirma PASS. La aceptación funcional queda pendiente de la ejecución manual.
Esta fase termina aquí; no incluye generación OD ni preparación de 110000.

## Defecto localizado

`QueueWithBuffer.subtractConsumptionOfVehiclesThatAreAlreadyInTheBuffer()`
restaba los grants retenidos en todo el buffer compartido de `.original` al
techo de recuperación de flujo. Una cabeza detenida por un terminal puede así
impedir que la cabeza nativa lista de otro slot llegue siquiera al buffer.
`originalSlotHeads()` y el avance entre carriles independientes de las
Correcciones anteriores solo ven los vehículos que ya están en ese buffer.

Ejemplo estático reproducido por la nueva regresión: `.original` de un enlace
de 57.24485776989736 m, tres carriles, partición 20/80 y 6000 veh/h. Con pasos
de 1 s, el cupo es 1.6666667 PCU/paso. El camión compacto de 3.5 PCU ya ofrecido
deja deuda de aproximadamente -1.8333333 PCU. Mientras permanece en el buffer,
el techo antiguo también es -1.8333333: ni la actualización rápida ni la lenta
pueden recuperar saldo positivo para la cabeza lista de otro slot.

Esto es una dependencia artificial entre carriles independientes, anterior al
split interno. No prueba que esa fuera la causa única del colapso de 220000.
La aserción `ORIGINAL_RETAINED_GRANT` está diseñada para fallar con el método
anterior y permitir el avance con el nuevo; **ese contraste no se ejecutó**.

## Cambio acotado y antes/después

Único archivo de producción cambiado en esta fase:
`src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/QueueWithBuffer.java`.

- Método existente afectado:
  `subtractConsumptionOfVehiclesThatAreAlreadyInTheBuffer()`.
- Método privado nuevo: `independentOriginalHeadMayAccumulate()`.

Antes, el grant retenido en un slot imponía permanentemente el mismo techo
negativo al conjunto de `.original`. Ahora se conserva el techo nativo normal
para recuperar el débito cuando se prueban simultáneamente estas condiciones:

1. Ledger SimZ1 instalado, dinámica `queue`, cola nativa FIFO y `.original`
   con dos o más carriles representados.
2. Cabeza real de `vehQueue` con earliest-exit cumplido; no se busca ni extrae
   un seguidor por detrás de ella.
3. `originalSlot()` identifica su reserva y las de todos los cuerpos del buffer.
4. Ningún cuerpo del buffer pertenece a su mismo slot.
5. El último grant del buffer procede de un instante anterior, evitando usar
   este tratamiento para añadir grants nuevos en el mismo instante.

El cambio **no pone saldo positivo**, no borra deuda, no aumenta la tasa ni el
techo nativo `flowCapacityPerTimeStep`. Los actualizadores existentes recuperan
el saldo al ritmo normal; `addToBuffer()` vuelve a cargar el consumo PCU normal.
La retirada del buffer conserva la contabilidad y la edad de la cabeza retenida.
La actualización lenta conserva además su condición de verde.

La disponibilidad del carril terminal se sigue comprobando en
`QLinkLanesImpl.moveBufferToNextLane()` / `moveIndependentOriginalSlot()`, con
recepción nativa, `canEnter()` y slot compatible. Recuperar flujo no autoriza
por sí solo una transferencia. La admisión y la prioridad continúan usando el
plan físico y la consulta pura de la Corrección 1; no se creó otro sistema de
reservas ni otro criterio de recepción.

La nueva excepción no aplica a una cabeza del mismo slot, una reserva sin
identificación segura, un cuerpo todavía en conector, colas terminales, colas
sin ledger o dinámicas ajenas a `queue`. Tampoco reorganiza `vehQueue` si su
cabeza pertenece al carril bloqueado: cualquier cambio adicional necesitaría
su propia evidencia y comprobación física.

## Receptores históricos y límites de atribución

Se leyeron `monitor/domains.json`, snapshots de 07:00 y 19:00, la red y carriles
actuales, y el resumen horario existente. No se alteraron esos archivos.
La revisión de la corrida es anterior a las Correcciones 1–3.

| Receptor | Dominio / longitudes (m) | Carriles | Almacenamiento útil por carril (m) |
|---|---|---:|---:|
| `osm_420120094_5_forward`, 14 Calle | 6.9835889446 | 1 | 1.9812220640 |
| `osm_1274975830_0_forward`, 8a Avenida | 7.9312903543 | 1 | 4.4301714500 |
| `osm_405188986_0_backward`, 10a Calle | 8.7527585331 | 1 | 2.2527432388 |
| `osm_64387808_0_forward` | tres subdivisiones, 19.3021615088 total | 1 | 12.5738688924 |
| `osm_48273209_13_forward`, 9a Calle | dos subdivisiones, 9.1915275903 total | 2 | 4.1915130107 |

Por tanto, la longitud de un solo enlace no equivale siempre a la capacidad
del dominio. En 14 Calle, el siguiente tramo recto identificado es
`osm_420120094_6_forward`, de 31.1248371118 m y un carril. No se convirtió el
conector de 1.9812 m útiles en un estacionamiento para una carrocería completa.

También se revisaron las dependencias registradas de 6a Avenida, 22 Calle y
7a Avenida. Entre ellas aparecen `osm_1057486080_0_forward` → `_1_forward`
en 6a Avenida y `osm_34994087_5_forward` → `osm_1358273945_2_forward`
entre 22 Calle y 7a Avenida. El primero aporta las dimensiones del split
57.2448577699 / 11.4489715540 / 45.7958862159 m usado por la fixture nativa.
Son referencias de enlaces y registros históricos, no una reconstrucción
completa del orden de sus buffers.

Los últimos registros `turn_go` por vehículo no prueban una transferencia:
se requiere el evento nativo de entrada/salida correspondiente. Tampoco
acreditan que ese vehículo siga siendo una cabeza ofrecida en el snapshot.
Los snapshots no permiten atribuir el defecto nuevo a todas esas dependencias,
ni afirmar que sigan presentes tras las tres correcciones anteriores.

No se encontró otra inconsistencia demostrable que justifique cambiar
`QLinkLanesImpl`, `Zona1QNodeImpl`, `SimZ1CorridorOccupancy` o
`UnsignalizedPriority` en esta fase. Se conservan el rechazo por receptor
realmente ocupado, las reservas activas sin despeje y la congestión auténtica.
El exceso de demanda o su distribución siguen siendo explicaciones posibles
del colapso residual; este parche no demuestra estabilidad de una corrida masiva.

## Revisión de almacenamiento y descarga

El almacenamiento nativo PCU de `QueueWithBuffer` contabiliza `vehQueue`;
el buffer mantiene aparte sus grants. `removeVehicleFromQueue()` descuenta PCU
al pasar al buffer, antes del cruce entre enlaces. Por eso un load PCU de cero
puede coexistir con un cuerpo detenido en el buffer: no es por sí solo una
desincronización. El ledger sigue reteniendo la huella completa.

`addFromUpstream()` registra entrada nativa y ocupación. El traslado entre colas
del mismo dominio conserva la reserva y su ordinal; el cambio de dominio retira
la ocupación anterior y registra la nueva. La reserva de paso mantiene los locks
hasta cumplirse tiempo mínimo **y** despeje conservador de carrocería. No se
modificaron esos hooks ni sus condiciones. Las nuevas pruebas comprueban PCU,
huella métrica, referencias nativas y eventos por separado.

Los semáforos se ejercitan con rojo/verde explícitos únicamente en la fixture.
Verde con recepción llena debe esperar; verde con espacio debe avanzar. No se
modifica ningún plan real ni se interpreta un snapshot horario repetido como
rojo permanente: un ciclo de 80 s puede coincidir con el muestreo de 3600 s.

## Regresiones nuevas, sin ejecutar

Archivos nuevos en `src/test/java/org/matsim/core/mobsim/qsim/qnetsimengine/`:

- `SimZ1StorageFixture.java`: soporte compartido, sin `main`; red pequeña en
  memoria, colas y nodos nativos reales, drivers controlados y ledger real.
- `SimZ1DownstreamStorageCheck.java`: perfiles de los cinco receptores,
  continuidad, reservas, prioridad y dos corredores ocupados.
- `SimZ1IndependentLaneDischargeCheck.java`: regresión del defecto, deuda,
  FIFO, descarga y almacenamiento nativos, referencias y semáforo.

Las fixtures compuestas reproducen longitudes de dominio, subdivisiones,
número de carriles y capacidad útil indicada; no son copias GIS del barrio ni
replays completos de rutas históricas. Los cruces sintéticos reproducen los
márgenes geométricos. No se ensanchó ningún archivo de la red real.

| Requisito | Caso preparado |
|---|---|
| 1–2. Receptor lleno / disponible | `realStorageProfiles`, `nativeFullReceiver` |
| 3–4. Conector con / sin continuidad | `passageLifecycle`, `noContinuity`, receptor posterior ocupado |
| 5. Carriles independientes | `discharge`: terminal 0 lleno, slot 1 disponible |
| 6. FIFO del mismo carril | `sameLaneFifo`, rechazo de extracción de un no-head |
| 7. Liberación nativa y reintento | `nativeFullReceiver`, `sameLaneFifo` |
| 8. Transferencia actualiza ocupación | `discharge`: original → terminal → otro dominio |
| 9–10. Reserva activa / despejada | `passageLifecycle`: ambos locks, deadline sin avance, liberación única |
| 11–12. Avenida viable / competidor sin recepción | `prioritiesAndTwoCorridors` con prioridad real |
| 13–14. Verde con espacio / lleno | `greenStillNeedsStorage`, incluyendo rojo de control |
| 15–16. Dos corredores y congestión auténtica | `prioritiesAndTwoCorridors`: ambos bloqueados; luego B libera espacio nativamente mientras A sigue ocupado |
| 17. Separación y no adelantamiento | huella cuerpo + 0.10 m, orden/cotas de reservas, mismo slot y edad; `sameLaneFifo` |
| 18. Sin movimientos/llegadas fabricados | correspondencia de LinkLeave/LinkEnter con notifyMoveOverNode, rechazo de arrival/abort/FORCE |

`discharge` cubre moto 2.1 m, carro 4.5 m, camión compacto 8 m y Transmetro
13.5 m; sus PCU son 0.25, 1, 3.5 y 3. La prueba del defecto usa actualizaciones
rápida y lenta, tanto paso de 1 s como de 0.1 s, y comprueba primero que la deuda
impide el avance prematuro. `withoutLedgerKeepsNativeRule` comprueba el alcance
optativo del cambio. No se invoca ningún `main` de las nueve regresiones anteriores.

## Warning de ampliación automática

No se modificó la fixture antigua de la Corrección 3 ni su resultado manual.
Su warning indica un ajuste interno de almacenamiento, no capacidad geométrica
adicional acreditada. En las nuevas fixtures se exige, cola por cola:

`storageCapacity == longitudDeCola * carrilesRepresentados / 7.5`

con factores de almacenamiento y flujo iguales a 1, y se rechaza el atributo
`storageCapacityUsedInQsim`. Así también falla un aumento silencioso por el
mínimo `max(storage, flowCapacityPerTimeStep)`, aunque no imprima warning.

El caso nativo central de 57.2448577699 m usa 6000 veh/h, 2000 por terminal y
paso de 1 s: sus colas ya tienen capacidad geométrica suficiente. No necesita
ampliación. La variante de 0.1 s prueba el mismo débito con otra discretización.
Las fixtures con los conectores muy cortos usan 0.1 s para que su cola original
no sea aumentada por el mínimo de flujo de un paso. Se conservan longitudes,
carriles, capacidades horarias, cell size y dimensiones; esto no cambia el
paso de producción ni los ciclos semafóricos reales.

Dos casos aíslan un rechazo nativo instalando temporalmente un **load lleno**
en una cola receptora, nunca una capacidad mayor. Restauran exactamente el load
anterior en `finally`. Es un snapshot controlado de la rama de rechazo: no
demuestra cómo se formó esa cola. Los otros casos de ocupación usan vehículos
nativos reales y conservan su ledger.

No se acepta ninguna ampliación para obtener PASS. Si aparece una, la fixture
debe fallar. Los conectores cortos a paso de producción de 1 s y la reproducción
integral de la congestión histórica quedan fuera de la cobertura nativa de
estas fixtures; no se sustituye esa cobertura por almacenamiento inflado.

## Ejecución manual exacta

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& .\scripts\check_simz1_downstream_storage.ps1
```

El script crea `target/correction4-<UUID>`, compila las fuentes con `test-compile`
y `-DskipTests`, y ejecuta únicamente los dos nuevos `main`, con classpath de
pruebas. No reemplaza builds anteriores ni ejecuta Validate, Run1000, suites
previas, benchmarks o escenarios. No se registraron las pruebas en otro workflow.

## Conservación y verificación de esta entrega

La comparación de hashes contra el inicio de esta fase conserva las fuentes,
regresiones y script de las Correcciones 1–3. `originalSlot()` de la Corrección
3, los predicados de liberación de reservas, la consulta pura de recepción, el
reruteo y la tolerancia `1e-8` permanecen intactos. El único cambio nuevo de
producción es el descrito en `QueueWithBuffer`.

Se realizaron lecturas, edición y revisión textual. No se ejecutaron Maven,
compiladores, Java, Python, pruebas, MATSim, Validate, Run1000, benchmarks ni
simulaciones. No se abrieron subagentes. No se alteraron resultados históricos,
geometría OSM, capacidad física, carriles, dimensiones, demanda, horarios,
rutas exclusivas, semáforos, controles de colisión ni validaciones físicas.
`removeStuckVehicles` permanece desactivado en todas las nuevas fixtures.
