# Verificación de ocupación de SimZ1 — 2026-10-27

Actualización: 28 de octubre de 2026. Estado: implementación y verificación
funcional cerradas, con cobertura visual muestreada y límites explícitos.
V8, con 100 privados y la última corrección nativa, terminó `completed/valid`,
con análisis, entregables y replay completos. La auditoría final de 100
fotogramas en Chrome aprobó los cuerpos reconstruidos; 100 instancias de
marcadores sin movimiento inferible quedaron fuera de esa cobertura.
No se certifican coordenadas microscópicas ni rendimiento masivo. Se conservan
V7 y los intentos visuales rechazados, sin presentarlos como resultados aprobados.

## Diagnóstico y cambios

El defecto era mixto. QSim admitía vehículos por disponibilidad PCU sin exigir
longitud completa, y las paradas no bloqueantes permitían pasar durante el dwell.
El replay trataba algunos extremos de cola como centros de carrocería y no
compartía un ancla entre aproximación, parada y salida. `useLanes=true` no implica
seguimiento microscópico ni posiciones laterales medidas.

La reserva nativa nueva suma longitud del vehículo y 0.10 m en un carril modelado.
Agrupa subdivisiones OSM compatibles; los conectores cortos entre cruces necesitan
reserva del receptor y exclusión de los nodos hasta despejar el cuerpo. Conserva
el cálculo de flujo PCU, los eventos originales y el WAIT cuando falta espacio.
Las paradas de pasajeros bloquean su cola; la división de colas se prepara solo
en el snapshot nuevo, con hashes y cambios geométricos explícitos.

El replay usa el frente y la longitud del líder para representar cada cuerpo
completo. El contexto de SQLite consulta los intervalos activos y sus vecinos
necesarios. La proyección, el carril modelado y las cotas nativas permanecen
inspeccionables; no son coordenadas microscópicas observadas.

La carga conserva independencia del número de privados y comparte dimensiones
físicas y visuales de 12 × 2.5 m con TuBus. Su ventana nocturna termina a las
05:00 del día siguiente, sin agregar salidas del día siguiente. Los servicios y
configuraciones históricos conservan sus contratos archivados.

## Evidencia aislada

- [Batería Node final del 28 de octubre](../evidence/documentation/simz1-20261027/node-suites-20261028-final.json):
  **50/50 suites aprobadas**, con huellas del código y logs por suite.
  Incluye las regresiones de curvas, fronteras y parada tras un líder girando.
  La batería anterior de ese día detectó dos regresiones; ambas se corrigieron
  y se conservaron los logs de `runtime/validation/occupancy-20261028-node-lane-body-final/`.
- [Cuerpo completo sobre carriles registrados](../evidence/documentation/simz1-20261027/lane-body-fixtures.json):
  128 fotogramas de giros y transición de dos a cuatro carriles, SAT independiente
  de cuerpo y separación longitudinal de 0.10 m, continuidad y reproducción
  a 1x/120x. Conserva longitud, ancho, eventos y horarios; declara los conectores
  geométricos estimados. Las advertencias de holgura lateral adicional se distinguen
  de contactos físicos y de invasión del margen longitudinal.
- [Pruebas Node](../evidence/documentation/simz1-20261027/node-suites.json):
  batería inicial de 48 suites; los 27 casos del corredor incluyen cuatro familias, bus/camión
  detenidos, cola semafórica, curvas, enlaces cortos, salida y seek continuo.
- [Contrato físico y validación](../evidence/documentation/simz1-20261027/physical-contract-verification-index.json):
  comandos, hashes y pruebas Python de identidad, dimensiones, horarios,
  cuotas, posiciones de paradas y rechazos de datos inconsistentes.
- [Verificación Java](../evidence/documentation/simz1-20261027/native-occupancy-verification.json):
  compilación Java 17 aislada, comandos, huellas y fixtures con QSim real.
- La prueba QSim de parada utiliza un bus de 13.5 m, carro y moto. El dwell es
  18–58 s; los seguidores entran a 19/29 s. A 38 s los frentes modelados son
  96.5, 82.9 y 78.3 m: separaciones de 0.10 m, con tolerancia numérica.
  La línea de parada es 96.5 m; las salidas ocurren a 100/111/122 s después
  del verde a 100 s. Evidencia:
  [geometría de parada](../evidence/documentation/simz1-20261027/blocking-stop-geometry-evidence.json).
- La parada terminal del replay reproducía saltos de 3.435 m. El fixture
  comprueba ahora continuidad en aproximación → dwell → liberación → siguiente
  enlace, sin modificar los eventos, los tiempos ni `Motion_Plan`.
- La selección nativa de carril comparaba un giro interior contra los permisos
  del extremo no visitado del corredor. Ahora intersecta los movimientos que
  la ruta realmente recorre. La nueva prueba QSim de dos carriles completa los
  cuatro tipos de vehículo por el carril permitido y rechaza una ruta que
  necesitaría un cambio de carril no modelado. Pasan también las regresiones
  de rutas y 16 casos de colas, de dos iteraciones cada uno:
  [comandos y huellas](../evidence/documentation/simz1-20261027/interior-turn-slots-verification.json),
  [auditoría nativa](../evidence/documentation/simz1-20261027/interior-turn-slots-native-audit.json).
- La admisión desde actividad contaba el recorrido de la cola original aunque
  `addFromWait` inserta directamente en su buffer. Solo ese recorrido se omite
  ahora, usando el ID explícito de la cola; se conservan las comprobaciones de
  vacío, deuda de flujo y dos pasos de margen. El fixture de cuatro conectores
  reproduce el presupuesto anterior de 25 s frente a un verde máximo de 25 s:
  con las clases anteriores no entra ningún vehículo; con el presupuesto
  corregido de 24 s llegan Normal y Tortuga a 144/228 s, sin pasar rojo.
  Pasan los 13 fixtures de corredor, la parada bloqueante y la auditoría del
  ledger, con cero reservas restantes y cero violaciones:
  [verificación y comandos](../evidence/documentation/simz1-20261027/activity-buffer-verification.json),
  [eventos y auditoría](../evidence/documentation/simz1-20261027/activity-buffer-native-audit.json).
- La regresión de fronteras incorpora los contactos reales de V7 en 29,711 y
  51,339.5 s, conservando los registros nativos y la geometría suministrada.
  Detectó además un salto de 4.856 m en 51,362 s: al cambiar de enlace dentro
  del mismo corredor, el cuerpo usaba el predecesor inmediato como si fuera
  exterior al corredor. La corrección rastrea la frontera original y reconstruye
  la parte trasera sobre la secuencia registrada. Pasan cuatro fixtures y 57
  muestras, con dos actores visibles en los casos nuevos, SAT independiente
  para 0.10 m, cold/reverse seek y reproducción a 1x/120x. En los siete límites
  nuevos, las diferencias a ±1 microsegundo son menores que 0.000008 m; no se
  cambian `Motion_Plan`, tiempos, reservas ni dimensiones. La normalización
  visual de una parada conserva explícitamente su punto nativo. El SAT usa el
  sistema métrico común del visualizador y tolerancia de 0.000001 m; cambiar a
  una latitud diferente por pareja introducía discrepancias de micrómetros.
  [Resultado y hashes](../evidence/documentation/simz1-20261027/corridor-boundary-v7-regression.json),
  [fidelidad de los fixtures](../evidence/documentation/simz1-20261027/corridor-boundary-v7-fixture-provenance.json)
  y [fallo anterior conservado](../evidence/documentation/simz1-20261027/corridor-boundary-v7-failure-51362.json).
  Son pruebas de actores aislados; no reemplazan una auditoría del día completo.
- El giro del primer fixture también se revisa entre 24,302 y 24,312 s cada
  0.1 s, con cold/reverse seek en los 101 instantes. El seguidor mantiene la
  misma posición durante toda la espera. Hay 82 cuadros con ambos cuerpos
  visibles y SAT de 0.10 m aprobado; en los otros 19, el movimiento original
  del líder está marcado `distance_exceeds_speed_cap` (32.064 m en 2 s frente
  a un límite de 11.111 m/s). Esos cuadros exigen la omisión explícita y no
  acreditan geometría de la pareja. La [limitación de fuente](../evidence/documentation/simz1-20261027/corridor-turn-sweep-source-limitation.json)
  permanece pendiente; no se inventaron posiciones ni se modificó el fixture.
  El [control negativo aislado](../evidence/documentation/simz1-20261027/corridor-turn-bound-negative-control.json)
  desactiva únicamente la cota de giro en una copia del renderer y reproduce
  contacto real de los cuerpos en 24,307.999 s. No es una versión histórica
  archivada ni una modificación de la corrida.

## Corridas conservadas

V1–V7 usan 1,000 privados; V8 usa 100 por la preferencia posterior del usuario.
Todas conservan semilla 20261027, servicio weekday público y 12 vehículos de
carga adicionales. Directorio base: `scenarios/zona1/montecarlo/`.

| Carpeta | Resultado y causa |
| --- | --- |
| `run-occupancy-20261027-v1` | Rechazada: camión bloqueado por conector de 8.52 m entre conflictos; motivó el paso anticipado. |
| `run-occupancy-20261027-v2` | Rechazada: faltaba espacio para despejar la parte trasera y había problemas con salidas cortas. |
| `run-occupancy-20261027-v3` | Rechazada: exigir receptor vacío introducía bloqueo artificial; sustituido por intervalo libre suficiente. |
| `run-occupancy-20261027-v4` | QSim terminó; validación rechazada porque el paso anticipado omitía GO/CROSS tras una cabecera real. La auditoría independiente encontró además un dominio repetido en prefijo y receptor. |
| `run-occupancy-20261027-v5` | QSim terminó; validación rechazada por paso sobre rojo después de una autorización adquirida en verde. La admisión debe comprobar la ventana disponible para completar el paso. |
| `run-occupancy-20261027-v6` | Integridad `completed/valid` después de revalidar los eventos originales. Terminaron 720/1,000 privados: screening `review_required`. La primera auditoría de 100 cuadros del navegador rechazó la ocupación visual. |
| `run-occupancy-20261028-v7` | Integridad `completed/valid`, 994/1,000 privados y 12/12 carga llegados; análisis y entregables generados, `screening_pass`. La auditoría de 100 cuadros durante todo el día falló: 18 contactos y 51 contextos incompletos. Dos censurados revelaron además el defecto de ingreso desde actividad, corregido después de esta corrida. |
| `run-occupancy-20261028-v8` | `completed/valid`: 100/100 privados, 12/12 carga y 5,200/5,200 expediciones públicas iniciadas completadas. Análisis y entregables completos; `screening_pass`. Replay en preparación y aceptación visual pendiente. |

La corrida V4 tiene identidad `simz1-798cf5ae484144e58684ff331bf20578`.
Sus eventos finales se conservan para reproducir ambos fallos. No se modifica
su manifiesto a mano ni se rebajan las reglas de validación para aceptarla.
La auditoría independiente de 11,501,347 eventos sí confirmó las 12 expediciones
de carga completas, con duraciones de 304–548 s y sin infracciones horarias;
ese resultado parcial no sustituye la validación integral.

## Comprobación del 28 de octubre

V6 tiene identidad `simz1-44964b119ff2473397362d418226829b`. Sus análisis y
entregables están generados, pero el 72 % de terminación privada incumple el
objetivo declarado del 90 %. Los 313 abortos suceden al cierre del horizonte;
no hubo expulsiones durante la circulación ni reservas filtradas después de la
limpieza. Sí existe un bloqueo persistente verificable: un bus de 13.5 m necesita
atravesar un conector de 7.421 m cuyas señales de entrada y salida nunca tienen
verde simultáneo con los offsets anteriores.
El [diagnóstico de V6](../evidence/documentation/simz1-20261027/v6-completion-diagnosis.md)
conserva las identidades, los tiempos y los límites de esa conclusión.

La coordinación explícita `short_body_passage_offsets_v1` deriva offsets en el
snapshot nuevo. En este escenario son cinco cambios para 18 restricciones;
seis restricciones no tenían una ventana inicial. Mantiene grupos, duraciones
y ámbar, y deja trazabilidad del control anterior y del nuevo. Es un supuesto
sintético con factibilidad para colas vacías; la admisión nativa sigue
comprobando verde, deuda de flujo, espacio y conflictos. Pasan 13 pruebas del
módulo. La [verificación de una copia aislada](../evidence/documentation/simz1-20261027/v6-signal-coordination-clone-verification.json)
confirma que no se modificó el control original de V6.

La primera auditoría WebGL de V6 sí mostró las cuatro familias, el HUD de carga
y las dimensiones compartidas de 12 × 2.5 m, pero encontró 41 superposiciones de
cuerpo y 196 contextos de espera incompletos en 100 cuadros. Registró cero
invasiones de línea de parada entre los vehículos detenidos examinados. La
[evidencia inicial](../evidence/documentation/simz1-20261027/v6-initial-browser-summary.json)
conserva ese rechazo; no permite afirmar que el replay estaba corregido.

Las correcciones posteriores incorporan intervalos quietos después de paradas,
predecesores en movimiento y vecinos de colas largas con límites explícitos de
consulta. Las comprobaciones puntuales que dieron cero contactos no bastaron:
la auditoría posterior del día completo de V7 todavía encontró defectos, descritos
abajo. El [índice de contexto](../evidence/documentation/simz1-20261027/queue-context-20261028-index.json)
distingue pruebas aprobadas de integración pendiente. El servidor de esa revisión
de V6 usa `http://127.0.0.1:8799`; su identidad no acredita V7 ni V8.

V7 tiene identidad `simz1-212ba9f56dc34781b75428b978b8244d`. La ejecución cargó
`simz1_signal_coordination` antes de que estuviera disponible `validate_report`.
QSim concluyó correctamente, pero la fase de validación lanzó exactamente
`ImportError: cannot import name 'validate_report' from 'simz1_signal_coordination'`.
La revalidación admitida exige ese símbolo, módulo y sitio de importación,
fase `validating` y salida natural 0. Ejecuta nuevamente **todo** el validador,
compara los hashes de inputs y outputs, y solo entonces respalda y publica el
manifiesto. No repite MATSim ni modifica los eventos. Sus 18 pruebas pasan.
La revalidación completa terminó con código 0 y estado `completed/valid`:
[resultado, comandos y hashes](../evidence/documentation/simz1-20261027/v7-revalidation-summary.json).

Los resultados oficiales de V7 son 994 privados llegados y seis pendientes al
horizonte, sin abortos privados anteriores al cierre. Las 12 expediciones de
carga llegaron y no violaron sus ventanas horarias. El servicio público inició
y completó 5,227 expediciones de las 6,915 programadas; 1,688 quedaron canceladas
por cierre del servicio. No se deben confundir salidas programadas con viajes
ejecutados. No hubo transiciones físicas inválidas ni intervenciones para forzar
espacio. El manifiesto conserva `physical_stability.proven=false`: ausencia de
intervenciones no equivale a una prueba microscópica de estabilidad.

El análisis y el empaquetado de V7 finalizaron correctamente y el screening
declarado pasó con 99.4 % de terminación privada. Se conservan seis viajes
censurados: dos abordaron sin entrar al tráfico y cuatro entraron sin llegar
dentro del horizonte. Los entregables están en
`scenarios/zona1/montecarlo/run-occupancy-20261028-v7/entregables/run-occupancy-20261028-v7`.
El log de esa etapa es `runtime/validation/occupancy-20261028-v7-analysis.log`.
La fuente SQLite y el replay de V7 ya están preparados. Su auditoría con Chrome
real evaluó 100 cuadros desde 0 hasta casi 86,400 s y rechazó la ocupación:
**18 superposiciones de cuerpo y 51 contextos de espera incompletos**. Hubo cero
invasiones de línea de parada en las 854 comprobaciones de distancia al cruce
para cuerpos detenidos. Estos son resultados de una muestra, no un certificado
de todos los instantes. Las cuatro familias y sus dimensiones/HUD sí pasaron.

Además, el auditor registró 134 instancias de marcadores omitidas: 38 por cuerpo
no representable y 96 por movimiento no disponible. Esas proyecciones no están
certificadas; no se cuentan como vehículos sin contacto. El mínimo de separación
modelada observado fue negativo. La aceptación visual sigue fallida.
Evidencia local completa:
[auditoría V7](../runtime/validation/occupancy-20261028-v7-browser-full-day/browser-results.json).
El servidor auditado fue `http://127.0.0.1:8800` y el replay está en
`scenarios/zona1/montecarlo/run-occupancy-20261028-v7/webgl-continuo`.

El [diagnóstico de los seis privados censurados](../evidence/documentation/simz1-20261027/v7-completion-diagnosis.json)
leyó una vez los 8,499,552 eventos nativos y conservó evidencia de esos actores.
Cuatro partieron cerca del fin del día y siguieron cruzando enlaces hasta
86,398–86,400 s. Los otros dos quedaron en la cola de actividad desde 09:51 y
16:08, respectivamente: su cabecera nunca podía satisfacer el presupuesto de
25 s frente al verde máximo de 25 s. Ninguna de las seis rutas repite enlaces.
Por tanto, los seis censurados no pueden atribuirse solamente al fin del horizonte.

La corrección nativa de ese presupuesto pertenece a una versión posterior a V7.
V7 conserva sus eventos, resultados y hashes originales. La corrida V8,
`simz1-2376bfb80e714248be9245f7b5323a27`, terminó con exactamente 100 privados:
los 100 llegaron, sin viajes pendientes ni abortos. Las 12 expediciones pesadas
llegaron sin infracciones de las ventanas weekday. El servicio público completó
sus 5,200 expediciones iniciadas; las 6,915 programadas se reconcilian con esas
5,200 más 1,715 canceladas al cierre del servicio. Los 120 vehículos públicos y
los 12 pesados son adicionales a los privados.

El ledger de V8 terminó sin reservas ni bloqueos de paso pendientes, y con cero
violaciones. La comprobación de paradas no encontró salidas ilegales de
seguidores en 1,244 exposiciones; registró 17,080 intervalos de parada y 4,938
intervalos sin ubicación verificable. Esa limitación se conserva, y el ledger
no acredita distancias físicas continuas medidas. Tampoco hubo intervenciones
para forzar espacio; `physical_stability.proven` continúa siendo `false`.

La validación, el análisis y el empaquetado terminaron; el screening es
`screening_pass`. Los entregables están en
`scenarios/zona1/montecarlo/run-occupancy-20261028-v8/entregables/run-occupancy-20261028-v8`.
El [resumen V8](../evidence/documentation/simz1-20261027/v8-run-summary.json)
conserva identidad, hashes, reconciliación y comandos; el log es
`runtime/validation/occupancy-20261028-v8-run.log`. La preparación del replay
terminó. El servidor de la misma identidad queda en `http://127.0.0.1:8801`.

### Auditoría final del visualizador V8

El [resumen final y las capturas](../evidence/documentation/simz1-20261027/v8-final-browser-summary.json)
corresponden a Chrome real, sin DOM simulado, y a los componentes JavaScript
servidos por HTTP y cotejados con los archivos al inicio y al cierre. Se
examinaron 96 búsquedas y cuatro fotogramas de reproducción real a 1x/120x,
entre 00:00 y 23:59:59. El resultado incluye:

- Cuatro familias visibles y HUD de carga con 12 configurados/12 observados.
- 52,457 pares examinados con SAT independiente; cero contactos de cuerpos y
  cero invasiones de la separación longitudinal de 0.10 m.
- Cero contextos incompletos y cero invasiones de línea de parada en 777
  comprobaciones con geometría disponible, entre 1,240 cuerpos detenidos.
  Hubo 45 instancias de camión detenido; no equivalen a 45 camiones distintos.
- Reproducción a 1x/120x aprobada; el tramo a 120x cruzó una ventana y examinó
  756 pares. El tramo de camión aislado a 1x no acredita separación entre pares.
- 2,792 cuerpos visibles de 2,892 instancias de marcador muestreadas. Las
  otras 100 tienen `motion_unavailable`: se conservan como omisiones explícitas,
  sin inventar trayectoria ni certificarlas como libres de contactos. Hay siete
  advertencias de posición nativa de entrada, y tolerancia numérica en distancias.
- Cero errores JavaScript, peticiones fallidas o reintentos 503 en esta ejecución.
  La única respuesta HTTP ajena al replay fue el 403 de `/favicon.ico`.

Los tres contactos del intento anterior de V8 desaparecieron tras reconstruir
el contexto completo; su [resumen fallido](../evidence/documentation/simz1-20261027/v8-initial-browser-summary.json)
permanece disponible. Dos ventanas necesitaban hasta 305/393 registros; el
límite anterior de 256 era insuficiente. El presupuesto actual es 512 registros,
32 MiB comprimidos y 64 MiB decodificados, con límites de filas/profundidad y
rechazo explícito si se exceden. No se recorta un roster para aprobarlo.

La búsqueda más lenta en Chrome tardó 195.658 s en frío. La precarga nueva
prioriza la ventana solicitada y no inicia especulación estando pausado, pero
esta evidencia no acredita baja latencia ni escalabilidad a 250,000 privados.
La [lista de archivos](../evidence/documentation/simz1-20261027/working-tree-files.json)
registra los cambios; los resultados grandes de las corridas permanecen locales.

## Comandos de reproducción

Por preferencia posterior del usuario, las próximas simulaciones de prueba
deben usar **100 privados**. V7 ya había terminado con 1,000; se conserva su
evidencia y no hace falta repetirla para terminar análisis, empaquetado y replay.
Las flotas pública y pesada siguen siendo adicionales e independientes de N.

Desde la raíz del repositorio, para una prueba futura y eligiendo una carpeta nueva:

```powershell
$env:JAVA_HOME='C:\Program Files\Java\jdk-17'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/run_simz1_with_analysis.ps1 -MinAgents 100 -MaxAgents 100 -Seed 20261027 -Iterations 1 -ServiceDate '2026-10-23' -AcceptTransitRouteAssumptions -FreightVehicles 12 -ShortLinkSignalCoordination derive -NewRunDir 'scenarios\zona1\montecarlo\run-occupancy-review' -MinFreeGiB 1
```

El flujo genera análisis y entregables únicamente después de validar los
outputs. La aceptación de supuestos se refiere a rutas aproximadas del escenario;
no convierte la geometría en cartografía verificada ni las cantidades en aforos.
`-ShortLinkSignalCoordination derive` es el valor predeterminado del flujo nuevo;
`none` conserva los offsets archivados. Con `-LegacyPcuStorage` el wrapper usa
`none` si no se eligió otra política explícitamente.

Comando reproducible de V7, conservado como registro; la carpeta ya existe y
no debe reutilizarse para lanzar otra simulación:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/run_simz1_with_analysis.ps1 -MinAgents 1000 -MaxAgents 1000 -Seed 20261027 -Iterations 1 -ServiceDate '2026-10-23' -AcceptTransitRouteAssumptions -FreightVehicles 12 -ShortLinkSignalCoordination derive -NewRunDir 'scenarios\zona1\montecarlo\run-occupancy-20261028-v7' -MinFreeGiB 1
```

El comando de recuperación de validación ejecutado fue:

```powershell
.venv\Scripts\python.exe -B python/revalidar_simz1.py --run-dir scenarios/zona1/montecarlo/run-occupancy-20261028-v7 --apply
```

Comando de V8 con la corrección nativa y 100 privados; es registro de una corrida
ya lanzada, no una instrucción para sobrescribirla:

```powershell
$env:JAVA_HOME='C:\Program Files\Java\jdk-17'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/run_simz1_with_analysis.ps1 -MinAgents 100 -MaxAgents 100 -Seed 20261027 -Iterations 1 -ServiceDate '2026-10-23' -AcceptTransitRouteAssumptions -FreightVehicles 12 -ShortLinkSignalCoordination derive -NewRunDir 'scenarios\zona1\montecarlo\run-occupancy-20261028-v8' -MinFreeGiB 1
```

```powershell
$env:PYTHONPATH='python'
.venv\Scripts\python.exe -B -m unittest test_simz1_occupancy_replay test_simz1_occupancy_audit test_simz1_occupancy_reporting test_simz1_freight_midnight test_simz1_stop_proxy test_simz1_stop_queue_refinement -v
.venv\Scripts\python.exe -B -m unittest test_simz1_signal_coordination test_simz1_revalidate -v
node python/test_simz1_corridor_occupancy.cjs
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/prepare_simz1_runtime.ps1
```

Comando ejecutado para las cuatro regresiones de fronteras y paradas:

```powershell
$env:SIMZ1_BOUNDARY_EVIDENCE='evidence/documentation/simz1-20261027/corridor-boundary-v7-regression.json'
node python/test_simz1_corridor_boundary.cjs 2>&1 | Tee-Object -FilePath runtime/validation/corridor-boundary-v7-regression.log
```

Solo para una corrida `completed/valid`:

```powershell
.venv\Scripts\python.exe -B scripts/replay/prepare_replay.py --run-dir scenarios/zona1/montecarlo/run-occupancy-review --iteration 0
.venv\Scripts\python.exe -B scripts/replay/start_replay.py --run-dir scenarios/zona1/montecarlo/run-occupancy-review --iteration 0 --port 8797 --no-browser
```

## Antes de una corrida masiva

La comprobación funcional y visual muestreada de V8 está cerrada. No equivale
a una validación de capacidad masiva: la reserva exige QSim de un hilo y el
flujo conserva el control de 1,000 privados antes de escalar. Revisar recursos,
rendimiento, las poses sin reconstrucción, los supuestos de
flotas, las paradas aproximadas y las tasas de terminación. No extrapolar las
medias de vehículos llegados cuando existen expediciones pendientes.

## Comandos para prueba visual y ejecución posterior del usuario

La prueba V8 ya existe. Este comando abre esa identidad y prepara/reutiliza su
SQLite; no vuelve a ejecutar MATSim:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\simz1_workflow.ps1 -Action View -RunDir '.\scenarios\zona1\montecarlo\run-occupancy-20261028-v8' -Iteration 0 -Port 8801
```

Para la masiva se conserva el control existente: `Validate` seguido de una
prueba `Run1000` aceptada para los mismos hashes, y después `RunMassive`.
La V8 de 100 privados es una prueba funcional y no sustituye ese control.
Estos comandos quedan para el usuario; el agente no ejecutó ninguna masiva.
No editar código/configuración entre `Run1000` y `RunMassive`.

```powershell
$env:JAVA_HOME='C:\Program Files\Java\jdk-17'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\simz1_workflow.ps1 -Action Validate
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\simz1_workflow.ps1 -Action Run1000 -Seed 20261027 -ServiceDate '2026-10-23' -AcceptTransitRouteAssumptions -FreightVehicles 12 -ShortLinkSignalCoordination derive
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\simz1_workflow.ps1 -Action RunMassive -Seed 20261027 -ServiceDate '2026-10-23' -AcceptTransitRouteAssumptions -FreightVehicles 12 -ShortLinkSignalCoordination derive
```

`RunMassive` fija internamente `MinAgents=150000`, `MaxAgents=250000`, una
iteración y QSim de un hilo. Genera una cantidad privada reproducible dentro
del rango; las flotas pública (120 vehículos) y pesada (12) son adicionales.
El flujo incluye preflight, simulación, validación, gráficas y empaquetado.
Imprime la carpeta exacta `run-massive-…`; conservarla, sin elegir otra por fecha.
La guarda de 30 GiB libres no demuestra capacidad ni rendimiento para 250,000.

Si hace falta regenerar solamente gráficas y entregables, copiar la carpeta
impresa en `$runMasivo`; este comando no repite MATSim:

```powershell
$runMasivo='C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala\scenarios\zona1\montecarlo\run-massive-REEMPLAZAR'
$runId=(Get-Content -LiteralPath (Join-Path $runMasivo 'run-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json).run_id
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_with_analysis.ps1 -AnalysisOnly -RunDir $runMasivo -ExpectedRunId $runId
```

Para abrir después el resultado masivo:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\simz1_workflow.ps1 -Action View -RunDir $runMasivo -Iteration 0 -Port 8802 -SQLiteBudgetGiB 64 -ScratchBudgetGiB 16
```

Los presupuestos SQLite/scratch son máximos permitidos, no espacio reservado ni
una promesa de que el disco alcance. Si la exportación se detiene por presupuesto
o espacio, conservar la corrida y reanudar la preparación visual con recursos
suficientes; no repetir la simulación para reconstruir el visor.
