# SimZ1: guía técnica integrada

## Composición vigente para corridas nuevas — 2026-10-29

Los lanzadores usan ahora **N no público = carros + motos + pesados**, con rango
masivo predeterminado **180000–220000**. Pesos normalizados: carros **16/37**,
motos **20/37**, pesados **1/37**. El transporte público mantiene su flota fija
**176 Transmetro + 93 TuBus = 269**, adicional a N, con
`transit/weekday-v2/service-fleet-176-93-v1.json`. El histórico `service.json`
conserva 80/40. No añadir `-FreightVehicles 12`.
N=1000 da 973 particulares, 27 camiones y 269 buses: **1269 vehículos**.
Los bloques históricos que esperan 120/1120 deben actualizarse para nuevas
corridas; sus resultados guardados conservan la flota de su propio servicio.

El catálogo nuevo es `agent-types-nonpublic-v1.json`; los catálogos anteriores
conservan su significado histórico. N=0 deja únicamente el servicio público.
Consulta [contrato, límites y comandos manuales](simz1-composicion-vehicular.md) antes de usar los
comandos históricos de esta página: aquellos que indican N privado/carga
adicional no describen el nuevo predeterminado. Ajuste de escenario sintético,
no calibración empírica. Esta entrega no ejecutó pruebas ni simulaciones.

---

La [verificación de ocupación y separación](simz1-verification-20261027.md)
documenta las reservas por longitud, las colas de buses/camiones y la coordinación
explícita de semáforos en enlaces cortos. Incluye evidencia y resultados de V7/V8.
V8 validó 100/100 viajes privados, 12/12 de carga y 5200 expediciones públicas
iniciadas y completadas; el análisis y empaquetado terminaron. Pasan 50 suites
JavaScript y la auditoría de 100 fotogramas en Chrome, con cero contactos entre
cuerpos visibles. La cobertura es parcial por poses `motion_unavailable` y no
certifica rendimiento masivo. Las próximas simulaciones de prueba del agente
usarán 100 privados y flotas adicionales; el control previo `Run1000` del flujo
masivo se conserva para la ejecución posterior del usuario.

La [jornada continua entre semana](#jornada-continua-20261025) registra la intervención
actual. La [corrección del replay masivo](#replay-masiva-20261025), la
[comprobación de paradas y corrida de 100](#paradas-replay-20261024) y
la [integración de los prompts 1–8](#integracion-prompts-1-8), sobre `7a366aa`,
conserva los resultados anteriores. Complementa la
[consolidación operativa](#contrato-consolidado), cuya matriz conserva el estado
anterior a estas ejecuciones. La masiva existente se conserva íntegra. La intervención
temporal autoriza una prueba nueva de 1000 particulares, una iteración y transporte
público separado; no autoriza ejecutar otra masiva ni borrar corridas.
Las secciones fechadas conservan evidencia histórica; sus resultados no validan
automáticamente código posterior. Los ejemplos antiguos `--paged` describen el
flujo legado: para nuevas exportaciones usar exclusivamente el procedimiento
SQLite directo consolidado. No regenerar las corridas históricas.
Los comandos que mencionan corridas anteriores o `runtime/simz1-227187-direct`
son registros históricos, no rutas de reapertura vigentes. Las 35 corridas
listadas en el inventario y ese derivado de runtime fueron eliminados mediante
limpieza selectiva; los destinos ambiguos se conservaron. Para abrir la corrida conservada usa únicamente
el [flujo explícito de la masiva, iteración 9](#replay-masiva-20261025). Su identidad
correcta no demuestra que el replay histórico represente todas las colas activas;
el diagnóstico temporal posterior cuantifica esa limitación sin modificar la fuente.

Esta es la referencia técnica canónica de SimZ1. Consolida los veinte informes de la raíz, las nueve guías
temáticas y la guía de instalación, contrastados por lectura con el código actual. La reorganización documental
del 16 de octubre de 2026 no ejecutó suites de pruebas,
generadores, simulaciones, exportaciones, servidores ni navegadores. Los resultados anteriores se conservan
como evidencia histórica y no constituyen un nuevo `PASS`.

La [validación integral del 19 de octubre de 2026](#validacion-integral) añade
pruebas acotadas y una revisión de red en lectura. No ejecutó MATSim, servidores,
navegadores ni reprocesó corridas. Distingue fixtures aprobados, un fallo pendiente
del HUD y la validación física todavía pendiente.

El [README principal](../README.md) contiene instalación, comandos operativos y la secuencia pequeña de preparación,
ejecución, análisis y apertura del visor. Aquí se explica qué representa cada producto, cómo se relaciona con el motor
y qué límites deben conservarse al interpretar sus resultados.

<a id="jornada-continua-20261025"></a>
## Demanda, observación y jornada continua: 25 de octubre de 2026

### Alcance y diagnóstico de la referencia

La referencia permanece `simz1-eb9c02f113544d93a82c0954f38dd381`, iteraciones
**0..9**, con diagnóstico detallado de **9**. No se modifican sus eventos, planes,
marcas de tiempo, manifiestos, bases SQLite ni paquetes. Las correcciones de demanda
y ventanas crean otro escenario y otra carpeta. No hubo limpieza en esta intervención.
La evidencia externa se guarda en `runtime/maintenance/temporal-weekday-20261025/`.

El generador histórico aplicó los pesos horarios del catálogo de agentes, aunque
`temporal_demand.hourly_weights` y `hourly_probabilities` globales fueran `null`.
La distribución efectiva **no era uniforme ni carecía de pico vespertino**. En it.9:

| Hora | Salidas planificadas | Salidas seleccionadas por hora efectiva | Llegadas válidas de esa cohorte efectiva |
| --- | ---: | ---: | ---: |
| 00 | 1949 | 1948 | 1948 |
| 06 | 11376 | 11376 | 8124 |
| 07 | 17167 | 17166 | 1424 |
| 17 | 17118 | 17119 | 10 |
| 18 | 15246 | 15243 | 12 |
| 23 | 1928 | 1928 | 2 |

La tabla completa contiene **183154 filas, 20611 llegadas válidas y 162543
censurados**. El filtro diario heredado `[0,86400)` por salida efectiva seleccionó
**183153 filas y 162542 censurados**, aproximadamente **11,2534 %** de completitud.
La persona rastreada es **`z1_113558`**: salida planificada **86399,22081455277 s**,
actividad serializada por MATSim **86399 s**, `PersonDepartureEvent` **86400 s** y
cierre censurado **86401 s**. No falta un agente en la población: la selección
excluyó su salida efectiva en el extremo derecho. La revisión de las **183154**
personas encontró `floor(planificado)` en el XML de salida y `ceil(planificado)`
en el evento de salida, sin excepciones. Las estrategias efectivas eran
`ChangeExpBeta` y `ReRoute`, sin mutador de tiempos de actividad.

Los censurados se desglosan en **95507 `boarded_without_traffic_entry`** y
**67036 `entered_traffic_without_arrival`**. Abordar o emitir `PersonDepartureEvent`
no acredita entrada efectiva a la red. El contador nativo registra **67141 activos
antes de la limpieza de cierre**, a **86401 s**: **67036 particulares + 105 buses**.
No se convierten las retiradas técnicas de cierre en llegadas. La acumulación
ya es visible al final de las horas 06 y 07 (**4128 y 17413 activos**), frente a
**61862** al final de la hora 17. Todas las iteraciones mantienen `review_required`;
las llegadas particulares van de **18653** en it.5 a **20611** en it.9. El aprendizaje
entre iteraciones no constituye continuidad física entre días.

`waitStorage=5550` en el último registro significa **5550 eventos de decisión de
espera de espacio receptor desde el informe anterior**. Puede contar varios intentos
del mismo vehículo; no son vehículos únicos ni segundos acumulados. `linkTransitions`
cuenta eventos `LinkEnterEvent`, y `activeVehicles` es el saldo de entradas/salidas
nativas al tráfico, incluyendo buses. Las instantáneas de progreso intermedias
pueden quedar ligeramente desfasadas respecto de eventos paralelos; el estado final
se identifica explícitamente como `before_cleanup`.

Un caso concreto de espera es **`z1_102520`**, en
`osm_1057486080_1_forward`: permanencia observada **24436..28891 s**; dentro de
ella hay **492 decisiones de espera de almacenamiento entre 28399 y 28890 s**.
Los 4455 segundos de permanencia no se atribuyen íntegramente a ese motivo sin
evidencia. Las salidas se distribuyen entre **5195 enlaces de origen**, con máximo
de 81 en un enlace durante el día; esto descarta una única entrada concentrando
toda la demanda, no descarta cuellos de botella posteriores. La revisión no demostró
un defecto de liberación de reservas de `strict-receiver-v1`. No se cambiaron PCU,
capacidades, longitudes, restricciones ni señales para hacer pasar la demanda.
La compatibilidad de N=183154 con la red y la propagación de bloqueos siguen
requiriendo diagnóstico y calibración; ausencia de deadlock de hilos Java no prueba
ausencia de bloqueo vial circular.

En transporte público hubo **6915 expediciones programadas, 820 iniciadas y 700
llegadas**, más **120 iniciadas censuradas**. De estas, **15** no entraron al tráfico
y **105** permanecían activas. Las **6095 no iniciadas** estaban asignadas a buses
cuyo último servicio quedó censurado; no hay eventos explícitos de cancelación que
permitan etiquetarlas todas como canceladas. **809** inicios tuvieron retraso positivo,
mediana **386,97 s** y máximo **4677,17 s**. Este resultado no se atribuye únicamente
al generador de horarios ni se corrige forzando expediciones.

La omisión visual es un problema adicional comprobado. A **25200 s** la fuente
histórica solo contiene **1584 vehículos con segmentos representables**, mientras
el registro nativo ya acumula miles más. Para **`z1_24921`**, el último segmento
cerrado termina a **25383 s**; entra al siguiente carril a **25385 s** y continúa
censurado hasta **86401 s**, pero desaparece del replay porque no hubo cierre del
tramo. La comparación está en `historical-occupancy-vs-replay.json`.
La SQLite histórica se conserva intacta: **su caída de marcadores no acredita
descongestión**. En exportaciones nuevas se conserva un tramo abierto solo donde
un evento nativo de espera prueba la posición de cabeza de cola. Los seguidores
sin posición demostrada se contabilizan como geometría no disponible; no se colocan
vehículos ficticios ni se altera la ocupación nativa. El cliente diferencia datos
cargados, representables y dentro de cámara; este último recorte usa los centros de
los marcadores, no un cálculo de oclusión. Al llegar al fin de observación histórico
el visor informa que no existe continuación y no reinicia la jornada automáticamente.

Los archivos `historical-native-diagnosis.json`, `historical-departure-boundaries.json`
y `historical-occupancy-vs-replay.json` conservan estos contrastes. La comprobación
de identidad del replay documentada más abajo sigue siendo válida como identidad,
pero no se amplía retrospectivamente a una validación completa de ocupación.

### Contrato temporal nuevo

La configuración única es
[`scenarios/zona1/temporal/weekday-continuous-v1.json`](../scenarios/zona1/temporal/weekday-continuous-v1.json),
`schema_version=simz1-weekday-continuous-v1`, escenario
`simz1-weekday-continuous-v1-synthetic-20261028`. Generador, preflight, manifiesto
y análisis usan la misma política compilada y `policy_sha256`. Para la configuración
comprobada con semilla temporal **20261028**, la huella es
`337a3be384a1a05d208509dbfa8ad6f3cfe793f2e29dfd95e666a37e8ac28e32`.
El catálogo continúa definiendo los seis perfiles, sus proporciones y atributos;
la política nueva sustituye explícitamente su elección horaria, no la población.
Sin esa política se conserva el contrato histórico.

Hay **97 nodos cada 900 s**, incluido el extremo del día, con interpolación lineal
continua y primer/último valor iguales. La intensidad es finita y no negativa,
tiene integral positiva y mínimo relativo **0,12**. Sus componentes sintéticos
son mínimo 0,12, componente diurna 0,6 y dos aumentos de 1,8. Los nodos aproximan
rampas cosenoidales; el muestreo usa **la integral exacta de los segmentos lineales**,
normalizada por las duraciones reales, y su inversa dentro de cada segmento.
No se redondean salidas al minuto ni se fuerza una cantidad observada por hora.

La mañana asciende de **04:45 a 06:30**, mantiene el máximo hasta **07:45** y
desciende hasta **10:00**; la tarde asciende de **15:00 a 17:30**, mantiene el máximo
hasta **19:00** y desciende hasta **23:30**. La componente diurna asciende
**04:15–05:30** y desciende **20:30–23:30**. Estas elecciones rodean las franjas de
referencia **05:30–08:45** y **16:30–20:30**; son supuestos ajustables, no aforos
oficiales. El valor esperado es continuo en medianoche, sin exigir conteos enteros
idénticos a cada lado. Por defecto los seis perfiles comparten la curva;
`profile_multipliers` permite nodos periódicos explícitos por perfil sin alterar
su reparto. Los validadores rechazan intensidades inválidas y perfiles desconocidos.

`-Seed` conserva la selección de N, perfiles y OD. `-TemporalSeed` utiliza un flujo
reproducible independiente por persona/cohorte; los auxiliares tienen además su
propio flujo espacial. Cambiar únicamente esa semilla no altera la identidad,
perfil ni OD de los principales. Se conserva N exacto por asignación determinista
de perfiles. Las cantidades auxiliares resultan de integrar la misma tasa de la
cohorte principal en cada ventana de contexto y asignar enteros por restos mayores.
No se oculta una población adicional dentro de N.

Para N=1000 y la política publicada:

| Población | Cantidad | Contrato |
| --- | ---: | --- |
| Principal | 1000 | `principal_cohort_persons`; seis perfiles originales |
| Contexto anterior | 320 | `warmup_context_persons` |
| Contexto posterior | 76 | `post_context_persons` |
| Total particular en XML | 1396 | `planned_persons` y `all_private_persons` |
| Buses configurados | 120 | 80 Transmetro + 40 TuBus, fuera de las personas particulares |

Cada persona lleva `simz1PopulationCohort` (`main`, `warmup_context`, `post_context`),
`simz1StudyStartSeconds`, `simz1PlannedDepartureSeconds` y `simz1TemporalPolicySha256`.
La salida planificada fraccionaria es inmutable en ese atributo/ledger. Con
`departure_adaptation=fixed` se rechazan estrategias que mutan los tiempos; se
permite aprender rutas. El validador distingue el redondeo de serialización de
MATSim 15 y su tick efectivo de una adaptación de horario. La cohorte diaria se
selecciona por salida planificada, de modo que un evento redondeado al extremo
derecho no elimina a su persona del denominador.

El calendario es **America/Guatemala, UTC−06:00**, jornada del miércoles
**2026-10-28**. El origen técnico es **martes 2026-10-27 a las 18:00 locales**
(miércoles 00:00 UTC). Las ventanas son:

| Fase | Intervalo técnico | Duración | Interpretación |
| --- | --- | ---: | --- |
| Calentamiento | `[0,21600)` | 6 h | Demanda auxiliar real; estado físico previo |
| Estudio | `[21600,108000)` | 24 h | Cohorte principal del miércoles |
| Extensión con demanda | `[108000,129600)` | 6 h | Nuevas salidas del jueves y continuidad de viajes |
| Drenaje | `[129600,136800]` | 2 h | Sin nueva demanda programada; observación de viajes e inserciones pendientes |

No se requieren tiempos negativos. Eventos, duraciones e identificadores usan
tiempo absoluto monótono; solo la evaluación periódica de la intensidad y la
presentación de hora civil usan la fase del día. Un viaje anterior al estudio
puede seguir activo al inicio; uno de las 23:59 puede llegar después de medianoche
sin cambiar identidad ni cohorte. La flota pública se agenda por fecha con IDs de
expedición diferentes y los mismos vehículos, respetando turnos y cierre de servicio.
La continuación de un servicio previo no se convierte en una nueva expedición
programada durante el drenaje. Salida programada e inicio efectivo atrasado siguen
siendo campos distintos. Los vehículos que no terminan al cierre técnico siguen censurados.

Las **6+6+2 horas son parámetros de experimento**, no prueba de equilibrio.
`--sensitivity-hours 3,6,12` comprueba cómo cambian las integrales y cantidades
auxiliares, sin ejecutar QSim. La sensibilidad de congestión, sesgo inicial y censura
debe medirse con simulaciones comparables; no la acredita una curva visual suave.

### Métricas, productos y comprobaciones

Se mantienen separados: salida planificada; `PersonDepartureEvent`; entrada
`VehicleEntersTraffic`; presencia nativa dentro del dominio; llegada válida;
salida `VehicleLeavesTraffic`; retirada explícita y censura. La salida del dominio
no se convierte automáticamente en llegada al destino. El balance contabiliza
entrada y salida/retirada una sola vez, sin sumar otra salida por `PersonArrival`.
Los intervalos usan eventos nativos incrementales y memoria acotada. Los auxiliares
y buses conservan grupos separados de la cohorte principal.

Se añaden `flujo_ocupacion_15min.csv`, `cohortes_temporales.csv` y
`metricas_temporales.json`. Las columnas `active_end_<grupo>`/`pending_end_<grupo>`
son fotografías inmediatamente antes de los límites interiores; la última incluye
los eventos nativos exactamente en el fin técnico. `active_mean_<grupo>` y
`pending_mean_<grupo>` integran el estado por tiempo y dividen por la duración
del intervalo. **Sumar fotografías no produce vehículos
únicos**. Los pendientes emitieron salida sin entrada efectiva; no se mezclan con
quienes ya circulan. Se publican las gráficas `demanda_salida_insercion.png`,
`ocupacion_y_pendientes.png`, `llegadas_y_salidas.png` y `cohortes_y_censura.png`,
además de las actuales con tres perfiles de carro juntos y tres de moto juntos.
Medias, medianas y percentiles de duración usan solo llegadas válidas y se acompañan
de tamaño de muestra y completitud. Los censurados no reciben duración cero.

Los paquetes por corrida/iteración conservan **CSV/JSON en `docs/` y PNG en
`graficas/`**. `-AnalysisOnly` reutiliza análisis compatibles o prepara los faltantes;
`-PackageOnly` recupera el paquete sin repetir análisis ni MATSim. El código de
salida **3** conserva el significado de `review_required`; no se imprime una
aprobación de calidad después de ese resultado. La identidad de corrida, iteración,
ventana y procedencia sigue siendo obligatoria entre manifiesto, SQLite, API y DOM.

La validación de política y el preflight comprobados están en el
[archivo del README operativo](readme-historico-20261030.md#jornada-continua-entre-semana-2026-10-25).
Dentro de la validación consolidada, las regresiones de generación temporal suman **40 pruebas aprobadas**:
13 nuevas de política continua, 6 temporales legadas, 6 de demanda por agente,
6 de perfiles viales y 9 de generación. Incluyen N de hasta **250000 sin MATSim**,
reproducibilidad, aislamiento de semillas, fracciones, integral/medianoche, entradas
inválidas, atributos de cohorte y conservación del comportamiento legado. La prueba
de generación con flota usa XML pequeño y no demuestra circulación nativa.
El preflight publica `temporal_demand` efectivo y conserva los pesos reemplazados
en `catalog_temporal_demand`; si N es un rango, muestra las mezclas de sus extremos
y las probabilidades por perfil, sin fingir que ya seleccionó N.
Sus logs, `temporal-policy-validation.json` y `temporal-policy-implementation.json`
están en la carpeta de evidencia externa indicada arriba.

### Resultado nativo de la prueba funcional de 1000

La corrida nueva es **`simz1-ca9b7469f9bb480fb8764daf6a582455`**, iteración **0**,
carpeta `run-weekday-continuous-1000-20261028-95e674aa5f20`. Los registros
`small-native-review.json` y `small-public-readiness-review.json` acreditan:

| Magnitud | Resultado observado |
| --- | --- |
| Cohorte principal | 1000 salidas, 1000 llegadas válidas |
| Contexto previo/posterior | 320 + 76 salidas y llegadas válidas |
| Particular total | 1396 viajes completados, sin abortos ni censura |
| Flota pública configurada | 120 vehículos, separados de las personas particulares |
| Expediciones públicas | 8565 programadas; 7168 iniciadas y llegadas |
| Expediciones canceladas explícitamente | 1397: 1324 por cierre civil y 73 por corte del experimento |
| Expediciones no iniciadas sin clasificación | 0 |
| Máximo de activos en fotografías de progreso | 65, incluyendo buses |
| Activos al comenzar el drenaje, 129600 s | 48: 7 particulares y 41 buses |
| Activos antes de la limpieza técnica final, 136801 s | 0 |

El vehículo **`ctx_pre_00311`**, perfil Tortuga, sale a **21219 s** y llega a
**21625 s**: sus **406 s** de viaje atraviesan el comienzo de la jornada sin reinicio
de identidad ni trayectoria. Su plan original conserva **21218,15561145134 s**.
Siete particulares de contexto posterior llegan después de **129600 s**; por
ejemplo `ctx_post_00042` va de **129194 a 129620 s**. El estado activo no se vacía
al cambiar de fase. En la segunda medianoche, **108000 s**, esta realización
pequeña no tenía particulares activos ni un viaje privado cruzando el instante;
eso es compatible con intensidad baja positiva y no demuestra una imposición de cero.

Todas las salidas particulares efectivas coinciden con el `ceil` de sus horarios
planificados y ocurren antes del drenaje. El máximo **65** procede de fotografías
de progreso cada 60 s: no es un conteo de personas únicas ni garantiza que no haya
un máximo mayor entre fotografías. Hubo **666 intentos de espera de almacenamiento**,
sin inserciones forzadas ni retiros forzados por atasco; el contador no equivale a
666 vehículos. La comprobación final es anterior a la limpieza técnica, de modo
que el cero final no se obtiene borrando colas para aprobar.

El resultado privado tiene `screening_pass` bajo el criterio del proyecto. **No
significa que el transporte público cumpla su calendario.** De sus 7168 inicios,
**6827** se atrasan más que el redondeo del reloj; la mediana del retraso es
**2606,5 s**, percentil 95 **11785 s** y máximo **14108 s**, descontando ese redondeo.
Las 1397 expediciones sin inicio se reconciliaron con eventos explícitos de
cancelación, no con una suposición sobre ausencia de eventos.

El caso reproducible **`ptbus_transmetro_L1_001`**, servicio del **2026-10-28**,
tiene **91** expediciones programadas y **68** iniciadas. Su primera expedición
inicia a **39600 s** y termina a **40246 s**: duración nativa **646 s**, frente a
aproximadamente **395,28 s** programados. El último inicio observado es **93226 s**,
frente a **79117,337193 s** programados. El exceso acumulado de duración de sus
servicios previos explica **14108,662807 s** de atraso. La auditoría de los 7168
inicios no encontró discrepancias con la regla
`max(ceil(salida_programada), ceil(disponibilidad_real_anterior))`.
No se duplicó el bus para recuperar el horario ni se forzaron servicios vencidos:
la disponibilidad física propagó el atraso y el cierre canceló los turnos restantes.
Se deben calibrar tiempos de recorrido, permanencia y terminal del calendario
sintético antes de interpretar puntualidad o capacidad de servicio.

La comparación con la referencia separa escalas y ventanas:

| Magnitud | Referencia histórica, it.9 | Prueba nueva, it.0 |
| --- | --- | --- |
| Principal N | 183154 | 1000 |
| Contexto privado adicional | 0 | 396 |
| Simulación / jornada | 24 h / 24 h | 38 h / 24 h |
| Llegadas particulares | 20611 de 183154 | 1396 de 1396, incluidos 1000 principales |
| Activos antes de limpieza final | 67141 | 0 |
| Estado privado del proyecto | `review_required` | `screening_pass` |

**No es una comparación controlada del efecto sobre la congestión masiva**:
cambiaron N, demanda temporal y ventanas. La prueba acredita funcionamiento
temporal y reconciliación en esa escala, no que 183154 puedan circular correctamente.
La aptitud de una futura intermedia o masiva requiere recursos, conservación,
completitud, análisis de colas y calibración; no se deduce de la forma de las curvas.

`protected-preservation-check.json` compara la referencia con el baseline de esta
intervención: **539 archivos**, **487 hashes de archivos pequeños**, ningún cambio
ni archivo añadido. Para los archivos grandes compara tamaño, fecha de escritura
e identidad de archivo, conservando los manifiestos nativos de integridad sin
recalcular redundantemente todos sus hashes. Permanecen las diez iteraciones y sus
paquetes. No se borraron corridas. La publicación visual nueva y la verificación
final de API/navegador, descritas más abajo, se comprobaron por separado del resultado nativo.

La primera comprobación visual detectó un defecto adicional del desglose de flota:
el agregado por servicios fechados sumaba tres veces los mismos buses y presentaba
**240 Transmetro + 120 TuBus**, aunque la flota física validada tiene **120 IDs**.
`distinct_fleet_by_system` cuenta IDs distintos por sistema; `checked_hud` deriva
**80 Transmetro + 40 TuBus** de `configured_vehicle_ids` y conserva el desglose
original en `declared_fleet_by_system`, junto con `fleet_counting_basis`. Rechaza
incompatibilidades entre el total y sus IDs. El arreglo también corrige el agregado
para generaciones futuras. **No reescribe el manifiesto publicado, los eventos ni
SQLite**, y no cambia las cifras observadas de expediciones. Pasaron **10 pruebas
de contabilidad pública y 7 del HUD** relacionadas con esta corrección.

La comparación fuente/cliente identificó otra causa de vehículos omitidos:
**siete buses detenidos en paradas interiores** tenían segmentos `[P,P]` con
posición nativa válida, pero el renderizador rechazaba el trazado de longitud cero.
La corrección en `simz1_visual_lanes` y colas visuales utiliza el centro exacto,
valida el carril nativo y la instalación de parada, y obtiene la orientación de
la geometría efectiva. No inventa un carril para hacer visible el bus ni desplaza
su posición para evitar conflictos. En el fixture determinista de **48000 s**,
con segmentos HTTP, carriles y geometría reales, aparecen **56 de 56 posiciones
representables: 9 particulares y 47 buses**. Son las **07:20 locales**; el encuadre
revisado contiene **53 centros de marcador y deja 3 fuera de cámara**. La diferencia
entre representables y dentro de cámara no equivale a vehículos omitidos por el
renderizador. `morning-renderer-corrected.json`
conserva la identidad original y declara la sustitución de identidad que realiza
el arnés de prueba; **no constituye por sí solo una verificación del navegador
real**. Tras completar también la corrección de los tramos parciales descrita
a continuación, aprobaron **16 suites JavaScript**, incluido el fixture real
`test_simz1_boundary_paths.cjs`.

El mismo diagnóstico sigue reportando **tres cuerpos que exceden el soporte de
su enlace y tres solapamientos visuales**. No quedaron resueltos ni se interpretan
automáticamente como colisiones físicas de QSim. Ocultarlos o ajustar sus centros
sin evidencia no sería una corrección de la simulación.

El barrido de tarde y drenaje encontró **otras tres omisiones del renderizador con
fuente suficiente**, inicialmente informadas como `geometry_or_lane_unavailable`.
A **90000 s**, `z1_00607` tenía una posición fija de espera nativa válida al final
del enlace; `ptbus_transmetro_L12_017` tenía movimiento parcial desde una parada,
fracción **0,2..1**, con geometría y plan de movimiento válidos. A **129600 s**,
`ptbus_tubus_802_006` tenía el mismo caso de tramo parcial desde parada. Los dos
enlaces públicos tienen varios carriles, pero no había base para asignarles un
desplazamiento lateral concreto. La corrección conserva el centro de la fuente
y estima la orientación sin inventar ese desplazamiento ni declarar una cola
físicamente validada. Las dos posiciones interiores de bus siguen siendo
interpolaciones, no observaciones continuas medidas.

Después de esas correcciones, `twelve-renderer-frames-final.json` compara eventos
nativos, API y posiciones representables en **12 instantes**, sin omisiones en las muestras:

| Segundos técnicos | Activos nativos = fuente API = representables |
| ---: | ---: |
| 21599 | 1 |
| 21600 | 1 |
| 21624 | 1 |
| 21625 | 0 |
| 48000 | 56 |
| 86399 | 45 |
| 86400 | 45 |
| 90000 | 57 |
| 107999 | 0 |
| 108000 | 0 |
| 129600 | 48 |
| 136800 | 0 |

Este barrido no certifica geometría continua para todos los tiempos: el estado
lateral y la colocación de colas desconocidos siguen explícitos. Se reportan
**3 solapamientos a 48000 s, 7 a 90000 s y 3 a 129600 s**, sin ocultar cuerpos
para hacer coincidir cantidades. La comprobación final del navegador real se
documenta por separado del barrido de datos y renderizado.

Un caso distinto es el tramo final de **`ctx_pre_00311`, 21624..21625 s**.
`small-carryover-motion-diagnosis.json` contrasta la SQLite en solo lectura con
la cola nativa: el segmento había interpretado la llegada como recorrido de todo
el enlace, unos **38,33 m en 1 s**, incompatible con el límite configurado.
La llegada real ocurre desde la cola original; incluso su tramo de aproximadamente
**7,67 m** conserva una incompatibilidad de interpolación con el tick discreto.
No se aumentan velocidades ni se modifican tiempos o llegadas. A **21624 s**
existe una posición de entrada nativa exacta y el cliente la muestra con **velocidad
desconocida**. A **21624,5 s**, dentro del intervalo fraccionario y sin posición continua observada,
la ubicación se declara no disponible en vez de inventar una trayectoria; tampoco
se etiqueta esa ausencia como recorte de cámara. La regresión
`test_simz1_observed_position.cjs` comprueba la distinción. La fuente publicada
y los eventos permanecen intactos.

La reapertura de esta prueba usa **8799**, con la misma fuente publicada. La
detención del servidor anterior de 8794, PID **41680**, fue rechazada por la revisión
automática de aprobación sin indicar un motivo específico; no se reintentó. Ese
PID registra la sesión, no es una instrucción para detener procesos posteriormente.
Los servidores anteriores conservaban versiones de cliente ya cargadas; la nueva
publicación se abre en el puerto seleccionado sin sustituir sus fuentes activas.
### Comprobación final de HTTP, fuente y navegador

La URL comprobada es **http://127.0.0.1:8799/index.html**. El propietario TCP
registrado es **python.exe, PID 19452**, iniciado el
**2026-10-25T23:09:26.9507910Z**. Su comando selecciona explícitamente la carpeta
de la prueba nueva, **iteración 0** y `webgl-continuo`. La evidencia está en
`final-owner-and-http-8799.json` y su copia consolidada `final-owner-and-http.json`.
El PID es un dato de esa comprobación, no una identidad permanente de proceso.

`/api/config`, `/api/hud`, el manifiesto fuente y el estado del navegador coinciden
en **`simz1-ca9b7469f9bb480fb8764daf6a582455`, iteración 0**. El HUD distingue
**1000 principales, 396 auxiliares y 120 buses, 80 Transmetro + 40 TuBus**.
El total de personas particulares del XML es **1396**, no 1516: los 120 buses no
se suman a las personas. El horizonte/replay es **0..136800 s** y la jornada
**[21600,108000)**; las métricas de cierre incluyen la observación nativa final
a **136801 s**, sin ampliar artificialmente la reproducción.

La fuente servida es **`webgl-source/replay.sqlite`**, **1869541376 bytes** y
**609031 segmentos**, `sample_rate=1.0`. Su SHA256 es
`38f76496c6ab2e72b0655946205361c21e0703e99bdda74c781fb2f1a578024f`.
La versión del manifiesto fuente es
`1caa14e1c5e122ff56acbcdcc31b4b3b592499c202c147352bcf0b2537c4bf5e`,
ligada al manifiesto nativo
`70310596a9d782d365467f1994a112add89a65f813a76c1d2009e6e87a55b28a`.
El contrato de `/api/hud` se comprobó con esa identidad, versión de fuente y
ventana completa; no se aceptó únicamente un HTTP 200.

El HTML efectivamente recibido tiene SHA256
`f9bef37585a5fdf98e7021f4e03fbc0b703dfb9b01f190d524e71a226766275d`,
igual al cliente final generado desde el código actual. HTML/configuración usan
`Cache-Control: no-store`. `final-8799-client-inspection.json` registra la
comprobación; se distingue de las pruebas anteriores de servidores con cliente
cargado antes de las correcciones.

El navegador real confirmó:

| Instante técnico / hora civil | Fuente cargada | Representables | Centros en cámara | Fuera de cámara |
| --- | ---: | ---: | ---: | ---: |
| 21602 / miércoles 00:00:02 | 1 | 1 | 1 | 0 |
| 21624 / miércoles 00:00:24, entrada exacta | 1 | 1 | 1 | 0 |
| 48000 / miércoles 07:20 | 56 | 56 | 53 | 3 |
| 90000 / miércoles 19:00 | 57 | 57 | 54 | 3 |
| 129600 / jueves 06:00, comienzo de drenaje | 48 | 48 | 44 | 4 |
| 136800 / jueves 08:00, fin de observación | 0 | 0 | 0 | 0 |

La reproducción **1x** cruzó **21599→21602 s** manteniendo el mismo vehículo y
permitió pausarlo después de medianoche. Seek cargó las ventanas de mañana,
tarde, drenaje y cierre. A **21624 s** el marcador conserva la entrada nativa
exacta con velocidad desconocida; a **21624,5 s** sigue sin inventarse la posición
interior, según su regresión específica. A **136800 s** se muestra «fin de observación» y no se reinicia la
jornada. Los conteos dentro de cámara son de centros, sin afirmar oclusión; no
suprimen las incompatibilidades de cuerpos y colas descritas arriba.

`browser-checks.json` conserva las verificaciones con etiquetas **`final-8799-*`**
y también registros anteriores de diagnóstico, que no deben confundirse con el
resultado final. `browser-final-8799-evening.png` guarda la captura vespertina.
La misma identidad sigue visible en el DOM y en la fuente consultada. Este
resultado acredita las ventanas y controles probados, no posiciones continuas
medidas donde la simulación solo registra eventos de frontera.

La comprobación final también ejecutó **reproducción 120x, pausa, retroceso de
60 s y seek a 48000 s**. Seleccionó **TuBus 802_004**, consultó su recorrido
observado y posterior, y conservó la **tarjeta de seis campos**. La pestaña final
queda con ese recorrido; `browser-final-8799-public-route.png` y su archivo `.txt`
guardan la captura y el contenido comprobado. La reapertura del mismo flujo
PowerShell con **`-NoBrowser` y puerto 8799** terminó con **código 0** y reutilizó
el mismo servidor y fuente, sin nueva extracción de eventos, modificación de
nativos ni reinicio de servidor. `final-8799-reuse.log` conserva esa ejecución.

La validación consolidada aprobó **271 pruebas Python en 25 suites**, **22 suites
Node**, incluidas las **16 de renderizado**, **4 comprobaciones nativas** y
**5 micropruebas QSim**. Las 40 pruebas temporales anteriores son parte de ese
total, no se suman otra vez. Las fallas intermedias de diagnóstico conservan su
evidencia; las regresiones finales correspondientes pasan. La integridad de la
referencia volvió a comprobarse: **539 archivos y 487 hashes pequeños sin cambios**.
Ni estas pruebas ni `screening_pass` privado acreditan la capacidad masiva o la
puntualidad del calendario público sintético.

<a id="comandos-jornada-continua"></a>
### Comandos operativos de la política nueva

Todos los bloques se ejecutan desde PowerShell. N indica **cohorte principal**;
los auxiliares se calculan por separado. Las semillas de demanda/MATSim son
**20261023** y la temporal es **20261028**. No se activan accidentes ni cambios
de carril. La validación de política está en el README principal; el lanzador
realiza además preflight de red, calendario y espacio disponible. Un mínimo de
espacio libre es un umbral preventivo, no una estimación garantizada del tamaño
final de eventos/SQLite. El presupuesto de exportación del replay se comprueba
aparte antes de publicarlo.

La selección de la prueba funcional nueva es
`run-weekday-continuous-1000-20261028-95e674aa5f20`,
`run_id=simz1-ca9b7469f9bb480fb8764daf6a582455`, iteración **0**.
Para generar o reutilizar su análisis y publicar el paquete, sin MATSim:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
    $run = 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala\scenarios\zona1\montecarlo\run-weekday-continuous-1000-20261028-95e674aa5f20'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_with_analysis.ps1 `
        -AnalysisOnly -RunDir $run -ExpectedRunId 'simz1-ca9b7469f9bb480fb8764daf6a582455'
    $code = $LASTEXITCODE
    if ($code -eq 3) { throw 'Analisis conservado con review_required; revisar censura y calidad antes de escalar.' }
    if ($code -ne 0) { throw "Fallo de analisis/empaquetado: codigo $code. Conservar la corrida." }
}
```

Si el análisis está completo y solo falta recuperar el paquete, sustituir
`-AnalysisOnly` por `-PackageOnly`; se mantiene la identidad esperada y el manejo
del código 3. Para abrir **esa misma corrida**, con preparación visual compatible
o reutilización de su publicación existente:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
    $run = 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala\scenarios\zona1\montecarlo\run-weekday-continuous-1000-20261028-95e674aa5f20'
    $manifest = Get-Content -LiteralPath (Join-Path $run 'run-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.run_id -cne 'simz1-ca9b7469f9bb480fb8764daf6a582455') { throw 'Identidad de corrida inesperada.' }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\simz1_workflow.ps1 `
        -Action View -RunDir $run -Iteration 0 -Port 8799
    if ($LASTEXITCODE -ne 0) { throw 'No se verifico el replay solicitado; revisar API y fuente, conservando parciales.' }
}
```

**Prueba intermedia futura, 10000 principales y una iteración.** El contrato de
parámetros se comprueba mediante `-DryRun`; la ejecución MATSim de este tamaño
no forma parte de la prueba funcional autorizada. Ejecutar este bloque solo tras
revisar recursos, conservación, calidad y colas de la pequeña; no quitar agentes
ni alterar capacidad para obtener una aprobación:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
    $run = '.\scenarios\zona1\montecarlo\run-weekday-intermediate-10000-' + [guid]::NewGuid().ToString('N')
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_with_analysis.ps1 `
        -MinAgents 10000 -MaxAgents 10000 -Seed 20261023 -Iterations 1 `
        -TemporalPolicy .\scenarios\zona1\temporal\weekday-continuous-v1.json `
        -TemporalSeed 20261028 -ServiceDate 2026-10-28 `
        -TransitService .\scenarios\zona1\transit\weekday-v2\service.json `
        -AcceptTransitRouteAssumptions -StoragePolicy strict-receiver-v1 `
        -MinCompletionRate 0.90 -MinFreeGiB 20 -NewRunDir $run
    $code = $LASTEXITCODE
    if ($code -eq 3) { throw "Resultados conservados con review_required: $run. No escalar sin diagnosticar." }
    if ($code -ne 0) { throw "Corrida intermedia detenida con codigo $code; conservar $run." }
}
```

**Masiva futura, 183154 principales y una sola iteración.** No sustituye ni
sobrescribe la referencia de diez iteraciones. Su contrato de parámetros se
comprueba únicamente en `-DryRun`; el bloque siguiente ejecuta MATSim y requiere
haber evaluado primero la prueba intermedia. `screening_pass` es un criterio del
proyecto, no calibración ni garantía de que la escala mayor sea viable:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
    $run = '.\scenarios\zona1\montecarlo\run-weekday-massive-183154-' + [guid]::NewGuid().ToString('N')
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_with_analysis.ps1 `
        -MinAgents 183154 -MaxAgents 183154 -Seed 20261023 -Iterations 1 `
        -TemporalPolicy .\scenarios\zona1\temporal\weekday-continuous-v1.json `
        -TemporalSeed 20261028 -ServiceDate 2026-10-28 `
        -TransitService .\scenarios\zona1\transit\weekday-v2\service.json `
        -AcceptTransitRouteAssumptions -StoragePolicy strict-receiver-v1 `
        -MinCompletionRate 0.90 -MinFreeGiB 60 -NewRunDir $run
    $code = $LASTEXITCODE
    if ($code -eq 3) { throw "Resultados conservados con review_required: $run. No declarar resuelta la congestion masiva." }
    if ($code -ne 0) { throw "Corrida masiva detenida con codigo $code; conservar $run." }
}
```

<a id="replay-masiva-20261025"></a>
## Identidad y apertura del replay masivo: 25 de octubre de 2026

Selección explícita: `run-massive-10it-e0ea36d7601a4548af18c252d4bf5e7e`,
`simz1-eb9c02f113544d93a82c0954f38dd381`, iteración **9**, horizonte visible
**0..86400 s**, conservando las diez iteraciones nativas **0..9**. Manifiesto
nativo SHA256 `a327e89645ed035a31c74801531ad025dbed5fe5d2ab2417178d4cca1f8ef1db`.
Población particular: **183154**; flota XML efectiva: **80 Transmetro + 40 TuBus**.
Los conductores públicos internos no se suman a esa población. Los análisis de
las diez iteraciones mantienen `review_required`. El conteo nativo de it.9 registra 20611 viajes
particulares completados y 162543 censurados; la selección analítica de 183153
filas no redefine la población generada. La corrección del visor no inventa
llegadas ni modifica ese screening.

La causa observada fue un servidor anterior todavía activo en 8793, PID 43932
(inicio registrado en `before-processes.json`), sirviendo
`run-100-transit-stop-20261024-a7d9f2c6/webgl-continuo`. Tanto `/api/config`
como `/api/hud` y el DOM del navegador mostraban
`simz1-f9261a9936d64d1a86ee65d6e8075cf5`, iteración 0, población 100.
Al mismo tiempo seguía activo el exportador de la masiva, PID 13036, bajo el
workflow anterior. No era un error deducido de «Visibles 0» ni un spool terminado.
Ese proceso terminó posteriormente sin publicar manifiesto fuente ni checkpoint
finalizado; su parcial se conservó íntegro. La recuperación visual de **it.9**
se completó en una carpeta separada, sin ejecutar MATSim ni regenerar análisis
o entregables. No se atribuye la terminación inicial a una causa que el registro
disponible no demuestra.

El replay `webgl-continuo/continuous-manifest.json` está `complete`, sin muestreo,
y referencia `webgl-source-recovery-f9d0824baf294c4596fb61081d74ccb9/sqlite-source`.
Su SQLite es
`webgl-source-recovery-f9d0824baf294c4596fb61081d74ccb9/replay.sqlite`, **6318256128 bytes**;
el parcial original de `webgl-source` no es la fuente servida. La publicación
contiene **720 ventanas de 120 s**. La versión de fuente validada es
`4d124c4abd03487e748faa09c04698eebf2cd313128689475635a7d7c8291cae`.
Las respuestas HTTP guardadas en `after-api-config.json` y `after-api-hud.json`
confirman la corrida masiva, iteración 9 y **183154 personas**. El propietario
registrado en `after-server-process.json` es **PID 32400**, en
`http://127.0.0.1:8793/index.html`; ese PID es evidencia fechada, no un comando
para detener procesos posteriormente.

El flujo corregido propaga `-RunDir` y `-Iteration`. `prepare_replay.py` utiliza
un bloqueo del sistema operativo y comprueba exportadores existentes; valida
fuentes completas y reanuda únicamente checkpoints/parciales compatibles.
Para reabrir un replay completo toma su `source_directory` validado antes de
examinar la ubicación canónica. Así reutiliza la fuente publicada y conserva el
parcial original sin volver a exportarlo. Sin replay publicado, un SQLite sin
checkpoint finalizado se rechaza antes de releer los archivos nativos grandes.
El lanzador contrasta identidad, horizonte, población, SHA256 del manifiesto
nativo/fuente/replay y recibo de integridad de SQLite antes de abrir el navegador.
`/api/hud` exige la triple `run_id`, `iteration`, `run_manifest_sha256` y la
ventana **completa** `start_seconds=0&end_seconds=86400`, además de la versión
fuente para el cliente actual. No recibe la ventana de 120 s como horizonte HUD.

`source_version` es el SHA256 del manifiesto fuente: configura el cliente y
acompaña ventanas y recorridos. Las respuestas tardías de una fuente diferente
se rechazan. Configuración y recorridos usan `no-store`; la caché de ventanas
queda ligada a la sesión. La identidad servida aparece en el panel fijo y la
tarjeta del vehículo conserva sus seis campos. Personas generadas, marcadores
visibles y flota pública configurada siguen siendo magnitudes distintas.

Comando de apertura, sin MATSim ni análisis:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
    $run = 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala\scenarios\zona1\montecarlo\run-massive-10it-e0ea36d7601a4548af18c252d4bf5e7e'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\simz1_workflow.ps1 `
        -Action View -RunDir $run -Iteration 9 -Port 8793
    if ($LASTEXITCODE -ne 0) { throw 'No se verifico la identidad solicitada; conservar los parciales.' }
}
```

La protección del escritor se comprobó con ese flujo real y `-NoBrowser`:
detectó los dos procesos del exportador existente y salió antes de escribir.
Las regresiones usan fixtures, sin nuevas simulaciones. Los resultados, HTTP,
DOM y capturas se guardan en `runtime/maintenance/massive-replay-verification/`.
La verificación real del navegador aprobó las ventanas de **04:15, 06:00,
06:02 y 07:48**, reproducción, pausa, avance, retroceso y consultas de recorridos.
La identidad y las **183154 personas** coincidieron con la API y la fuente.
Se comprobó el particular `z1_143976` a **10,8 km/h** y el bus público `L18_002`:
detenido a **21680 s**, velocidad cero, y reinicio a **21700 s**, **30 km/h**,
con recorrido y tarjeta de seis campos. Las cuatro ventanas HTTP se contrastaron
con los datos nativos. Esto verifica actividad real de la fuente sin exigir que
toda la población aparezca simultáneamente.

El bloque PowerShell de apertura se ejecutó de nuevo: `reopen-tested.log`
registra reutilización del **PID 32400**, con fuente y procedencia idénticas
antes y después, sin exportar ni ejecutar MATSim o análisis. Las regresiones
de esta intervención suman **149 pruebas Python: 147 aprobadas y dos omitidas**
por falta de permiso para crear symlinks reales en Windows, más **seis suites
CJS aprobadas**. Los controles de reparse points también tienen fixtures que
no requieren ese permiso.

La limpieza selectiva finalizó: **36 carpetas eliminadas**, correspondientes
a **35 corridas anteriores** —incluida la de 100 personas— y
`runtime/simz1-227187-direct`. Se eliminaron **31802740172 bytes lógicos
(29,62 GiB)**; el aumento medido de espacio libre fue **31767633920 bytes
(29,59 GiB)**. La lista absoluta de destinos, sus identidades y el resultado
están en `selective-cleanup-compact-20261025/result.json`, dentro de la carpeta
de evidencia. Se conservaron **238 respaldos pequeños de metadatos**.
Un primer intento de respaldo excedió `MAX_PATH` **antes de borrar archivos**;
su journal se conservó y se completó el proceso con nombres compactos de respaldo.

Se excluyeron y conservaron `output/labs`, `output/simz1-cycle2`,
`output/simz1-incidents`, `output/simz1-master` y `output/simz1-review`, por no
acreditar una pertenencia eliminable mediante manifiesto, y las carpetas pequeñas
`verified-092051b4398d470ca4cf3a23a9777425` y
`verified-d2ea122d4d884393a4b586ef48630ac5` de evidencia de lanzamiento. El inventario guarda sus
rutas explícitas; no se aplicó un borrado por comodines. `latest-successful.json`
y `latest-attempt.json` permanecieron idénticos, apuntando a la masiva.
`runtime/workflow/trial.json` se archivó e invalidó al eliminar su corrida de
1000 personas; no se convirtió `review_required` en una aprobación de calidad.

`independent-postcleanup.json` terminó **passed**: conserva los **530 archivos**
del baseline, contrasta **79 recibos nativos de integridad** y verifica los
hashes de **170 artefactos de los diez paquetes**. Para nativos grandes compara
tamaño, fecha de escritura e identidad de archivo con la línea base y mantiene
sus recibos existentes; no relee redundantemente todas las iteraciones.
La fuente publicada, el parcial original y todas las iteraciones **0..9**
permanecen protegidos. La API y el navegador conservaron la misma identidad
después de la limpieza. `browser-final.jpg` y `browser-after-cleanup.txt`
registran el visor pausado a **06:00:00**, **446 vehículos visibles** y
**183154 personas**, iteración 9. La reapertura conservó los manifiestos de
fuente/SQLite; el parcial original mantuvo tamaño y fecha de escritura.

<a id="paradas-replay-20261024"></a>
## Paradas nativas y corrida de 100: 24 de octubre de 2026

**Registro histórico; no es la selección vigente.** La reapertura actual está
en [masiva, iteración 9](#replay-masiva-20261025). La comprobación de esta sección usó exclusivamente
`scenarios/zona1/montecarlo/run-100-transit-stop-20261024-a7d9f2c6`,
`run_id=simz1-f9261a9936d64d1a86ee65d6e8075cf5`, iteración 0, semillas de demanda y
MATSim 20261023, servicio 2026-10-23, cuatro hilos, 0..86400 segundos. No se
regeneró ni modificó el histórico `run-1000-82b4a17c2d11427a9bc58094e68cacc0`.
Los comandos reproducibles están en la sección 3 del README principal.

**Causa confirmada.** A los 16308 s del histórico, el bus
`ptbus_transmetro_L12_001`, conductor
`pt_ptbus_transmetro_L12_001_Transmetro_RigidProxy`, expedición
`ptbus_transmetro_L12_001_d0001`, llega a
`gis_station_76_L12_906046_part1` en `transit_osm_1274975829_0_forward`.
La fracción anterior era 0, sin `lane_id` ni asignación detallada para el enlace.
MATSim 15 (`QLanesNetworkFactory.createNetsimLink`, fuentes del JAR local) delega
estos enlaces a `QLinkImpl`; `QueueWithBuffer` atiende la parada en el extremo de
esa cola única. La configuración global no acredita carriles detallados locales.

`load_transit()` diferencia enlaces con asignación del complemento verificado
red/carriles. `stop_fraction()` usa ese contrato nativo y registra
`MATSim15_QLinkImpl_single_queue_exit_verified_no_lane_assignment`; las coordenadas
de la instalación no son evidencia longitudinal. En enlaces detallados exige
pertenencia observada y el extremo calculado desde `startsAt` de los destinos de
carril. La lectura admite namespaces. `TransitDriverStarts` limpia la pertenencia
anterior. No se retiene un carril después de `left lane` para adivinar una parada:
ese caso sigue rechazándose. La secuencia nativa observada coloca las paradas antes
de abandonar la cola; se conserva el orden de eventos con igual tiempo. Los
intervalos de espera y la salida nativa del dominio se mantienen separados de la
llegada del viaje. No fue necesaria instrumentación Java ni acceso a colas concurrentes.

**Pruebas ejecutadas.** Compilación limpia y verificador: 197 clases con major 61;
ocho comprobaciones Java y QSim sintético N=3/B=2 aprobados. Pasaron 152 pruebas
Python existentes de replay/integración, eventos/XML, prioridades, revalidación,
movimiento, SQLite, continuo y servicio, más ocho regresiones nuevas. Incluyen un
extracto comprimido de 412 eventos nativos sin cambiar atributos/tiempos, cola
implícita bus-only y compartida, extremos original/intermedio/terminal, ambigüedad,
espera/salida, reutilización, XML de producción y publicación SQLite real con
fallo/reintento sin mocks del lector o exportador. La integración nueva falló
antes de corregir exactamente con el error reportado.

La exportación completa reveló además que `check_config()` no reconocía el
`output_lanes.xml.gz` ya validado en
`effective_lane_configuration_validation.loaded_artifacts.lanes`. Se admite ese
registro exacto y se rechaza cualquier ruta/hash distinto; no se elimina la
validación de procedencia. La regresión de integración ahora usa salida efectiva
comprimida, distinta de la entrada, e incluye falsificación de hash rechazada.
Tras esta corrección pasaron 61 pruebas de publicación, recuperación, SQLite y
paradas. La corrida real se reanudó desde `spool-ready.json.gz`: la base de
1.296.633.856 bytes conservó SHA256
`10b322360411f1324f6ab0a299b3618718f6db72541961c546a0d8c2c5881a74`.
No se repitieron MATSim ni la extracción/cinemática.

Pasaron las suites Node `transit_replay`, `continuous_replay`, `vehicle_card`,
`continuous_bootstrap` y `transit_stops`. Se actualizó una aserción obsoleta del HUD
para incluir su fila ya existente de flota pública. La suite adicional
`test_simz1_render_performance.cjs` detecta un fallo previo en conservación de la
identidad de la capa estacionaria; no se alteró el renderizador para ocultarlo.

**Resultado nativo y análisis.** Proceso cerrado con exit code 0, `completed/valid`,
100/100 particulares llegados, cero abortados/censurados, cero transiciones físicas
inválidas. Perfiles: Normal 47, Tortuga 12, Liebre 12, Motociclista 15,
MotocicletaLenta 7, MotocicletaRapida 7. Flota fija adicional 80+40, 120 conductores
internos, 5.779 expediciones iniciadas/completadas; máximo observado 54 buses en red,
cero al cierre. El roster contiene 6.915 expediciones programadas; no equivale a
expediciones efectivamente despachadas antes del cierre del servicio.

Los seis PNG se abrieron e inspeccionaron. Se recalcularon las 144 cohortes de
perfil/hora desde `0.simz1-trips.csv.gz`; 89 celdas sin observaciones conservan media
nula, no cero. Se comprobaron hashes de los 17 archivos empaquetados y su identidad.
`screening_pass` conserva el umbral 0.90. La integridad técnica y el cumplimiento
de ese criterio no constituyen validación empírica ni autorizan una corrida masiva.

**SQLite y navegador.** Fuente y manifiesto continuo publicados, 422.171 tramos,
220 vehículos distintos, 5.879 viajes y 24.939 esperas nativas cerradas con
procedencia de posición. De ellas, 6.799 se resuelven por cola única verificada,
12.361 por pertenencia/extremo de carril observado y 5.779 por entrada nativa al
extremo. Se publicaron 720 ventanas de 120 s, sin HTML masivos. Los hashes de
corrida, análisis y replay coinciden. El verificador HTTP comparó seis tiempos y
un recorrido completo con la SQLite local.

Chrome real con WebGL 2 / ANGLE Intel UHD pasó 51 comprobaciones. Capturas e
inspección: carro `z1_00037` a 6193 s, moto `z1_00075` a 15325,5 s y bus
`ptbus_transmetro_L12_001` a 16320,5 s. El bus espera 16308..16333 s, continúa a
16335 s y sale a 16590 s; no se prolonga fuera del dominio. Cuerpos renderizados:
carro 4,5×1,8 m, moto 2,1×0,8 m, bus 13,5×2,5 m. Hover/clic real, seis campos,
recorrido, pausa, retroceso, 1x y 120x cruzando ventanas aprobados. La selección
conservó sus 55 tramos al cruzar ventanas. Los PNG prueban verde Transmetro y azul
para otros buses. Sin excepciones JavaScript, errores de consola o solicitudes
de red fallidas; el único HTTP no exitoso fue `/favicon.ico` (403), una petición
opcional ajena a los recursos/API del visor. Los primeros intentos del comprobador
se conservan: fallaban en selectores del panel antiguo o en asumir que el atlas
GPU seguía siendo una URL; no fueron fallos del renderizado de la aplicación.

Servidor histórico comprobado al cierre de aquella prueba:
`http://127.0.0.1:8793/index.html`, PID `43932`. Este dato no identifica al
propietario actual y no debe usarse para detener procesos. El lanzador entonces
verificó y reutilizó la identidad de 100 personas; la reapertura vigente usa
el [flujo de la masiva](#replay-masiva-20261025).

Comandos históricos de aquella comprobación; la carpeta de 100 personas fue
eliminada y estos comandos no comprueban el replay masivo actual:

```powershell
$run = '.\scenarios\zona1\montecarlo\run-100-transit-stop-20261024-a7d9f2c6'
$evidence = '.\runtime\validation\transit-stop-fix-20261024'
.\.venv\Scripts\python.exe -B .\scripts\validation\sample_simz1_transit_replay.py --run-dir $run --output "$evidence\native-browser-samples.json"
node .\scripts\validation\check_simz1_transit_browser.cjs http://127.0.0.1:8793 "$evidence\browser-review" "$evidence\native-browser-samples.json"
```

Evidencia en `runtime/validation/transit-stop-fix-20261024/`:
`historical-reproduction/` (traceback y caso), `compile-and-java-checks.log`,
`python-suites.log`, `new-regressions.log`, `run100-launcher.log`,
`run100-exit-code.txt`, `analysis-verification.json`, `sqlite-verification.json`,
`http-native-verification.json`, `server.json`, registros `view-*` y
`browser-final/` (capturas, informe, consola, solicitudes y revisión de píxeles).
Entregable histórico: `<run>/entregables/run-100-transit-stop-20261024-a7d9f2c6/docs/`
y `graficas/`; los artefactos nativos estaban en `output/` e `inputs/`. Esta
carpeta se eliminó tras comprobar el replay masivo, conservando evidencia pequeña.

<a id="indice"></a>
## Índice

- [Integración actual: pruebas, bloqueos y autorización de escala](#integracion-prompts-1-8)
- [Contrato consolidado y procedimientos](#contrato-consolidado)
- [Arquitectura y procedencia](#arquitectura)
- [Ejecución, identidad e integridad](#ejecucion)
- [Red OSM y parámetros viales](#red)
- [Instalación y regeneración aislada](#regeneracion)
- [Demanda y distribución temporal](#demanda)
- [Agentes, perfiles e interpretación histórica](#perfiles)
- [Configuración objetivo de seis categorías](#seis-categorias)
- [Verificación de composición y archivos efectivos](#composicion-agentes)
- [Regresiones de perfiles y visor de 229629 personas](#pruebas-perfiles)
- [Enrutamiento y reruteo](#enrutamiento)
- [Carriles, capacidad y almacenamiento](#carriles)
- [Semáforos y offsets](#semaforos)
- [Prioridad sin semáforo](#prioridad)
- [Gateways y dominio espacial](#gateways)
- [Validación integral: resultados y pendientes](#validacion-integral)
- [Corridas manuales de 10, 100 y 1000 personas](#corridas-pequenas)
- [Condiciones para autorizar escala masiva](#autorizar-masivo)
- [Reconstrucción de movimiento](#movimiento)
- [Carriles visuales, colas y selección](#colas)
- [Visor, API y SQLite](#visor)
- [Métricas, distribuciones y censura](#metricas)
- [Análisis automático por corrida y reintentos](#analisis-automatico)
- [Validación y rendimiento](#validacion)
- [Diagnóstico nativo y fallos](#diagnostico)
- [Opciones avanzadas](#opciones)
- [Limitaciones e historia conservada](#historia)
- [Conservación de documentación y evidencia](#conservacion)
- [Laboratorios históricos](#laboratorios)

<a id="arquitectura"></a>
## Arquitectura y procedencia

SimZ1 importa OSM y ejecuta tráfico sintético sobre una red dirigida MATSim. Es independiente de los laboratorios
históricos y de `Zona1BaseNetwork`. [AGENTS.md](../AGENTS.md) conserva esa separación: Lab08 y posteriores usan
su generador compartido; SimZ1 usa `map.osm`. Ninguna geometría aproximada de los laboratorios debe describirse
como cartografía GIS verificada.

| Etapa | Implementación | Producto y responsabilidad |
|---|---|---|
| Red | [prepare_simz1.py](../python/prepare_simz1.py) | Red, instalaciones, parámetros y procedencia OSM. |
| Demanda | [generate_montecarlo_z1.py](../python/generate_montecarlo_z1.py) | Personas, viajes, vehículos, configuración y manifiesto preparado. |
| Motor | [RunZona1Simulation.java](../src/main/java/gt/edu/uvg/sim/zona1/RunZona1Simulation.java) | QSim, eventos, señales, prioridad, incidentes y rutas. |
| Lanzamiento | [ejecutar_simz1.py](../python/ejecutar_simz1.py) | Carpeta nueva, ejecución, publicación validada y análisis automático por iteración. |
| Integridad | [simz1_run.py](../python/simz1_run.py) | Identidad, hashes, entradas efectivas, iteración y productos. |
| Análisis | [simz1_analysis.py](../python/simz1_analysis.py), [simz1_trip_table.py](../python/simz1_trip_table.py) | Postproceso verificable e idempotente; viajes observados, estados y duración con procedencia. |
| Reconstrucción | [simz1_motion.py](../python/simz1_motion.py) | Intervalos y movimiento visual derivados de evidencia. |
| Servicio visual | [simz1_continuous_replay.py](../python/simz1_continuous_replay.py) | Consulta de export existente, SQLite y ventana diaria. |

Los eventos nativos describen hechos discretos del motor. El análisis deriva medidas y el visor reconstruye posiciones;
ninguna de esas etapas convierte supuestos de demanda, velocidades o geometría lateral en observaciones de campo.

<a id="ejecucion"></a>
## Ejecución, identidad e integridad

El proyecto declara JDK 25, MATSim 15.0 y Maven 3.9.6 en [pom.xml](../pom.xml)
y el [wrapper](../.mvn/wrapper/maven-wrapper.properties). Python y sus dependencias
se describen en el README principal y [requirements.txt](../requirements.txt).
Los rangos de dependencias no constituyen un entorno completamente fijado.

Cada corrida usa una carpeta exclusiva con `run-manifest.json`, entradas efectivas, planes, vehículos, logs y productos
por iteración. Una ruta existente no se vacía para reutilizarla. `run_id` identifica la corrida; su nombre de carpeta
no determina población, horizonte, estado ni configuración.

Preparar demanda produce `prepared` con validación de resultados pendiente. El lanzador genera una nueva carpeta
y luego ejecuta MATSim; no reanuda por defecto la carpeta preparada antes. `ITERATION ENDS` y `BUILD SUCCESS`
no bastan: publicar `completed/valid` exige cierre e integridad de resultados. Un fallo conserva su evidencia
y no reemplaza `latest-successful`.

La jornada normal tiene demanda `[0,86400)`, QSim hasta `86400` y drenaje `0`. `24:00:00` cierra el día.
El maestro conserva iteraciones `0..49`; por ello los comandos pequeños fijan `--iterations 1`. Una prueba de diez
o cien personas no acredita comportamiento masivo. Los procedimientos están en [inicio](../README.md).

La carpeta se reserva con creación exclusiva y UUID; la semilla no determina su nombre. Los estados de
preparación, ejecución y validación son distintos. `execution-status.json`, `run-manifest.json` y `matsim-run.log`
conservan fase, código de salida y causa primaria, incluidos fallos de cierre. Una interrupción no autoriza
a reutilizar resultados parciales. El lanzador gestiona el proceso hijo y el heap; la selección automática
de 8/12 GiB según memoria detectada (umbral 16 GiB) no garantiza suficiencia para una población masiva.

El maestro declara 12 hilos globales, cuatro QSim, bins de tiempos de viaje de 60 s hasta 86400,
factores de flujo/storage 1, `useLanes=true` y `usingFastCapacityUpdate=false`. Señales, prioridad y reruteo
están activos. Los incidentes heredan su configuración/default del motor. Las opciones omitidas no deben
interpretarse como desactivaciones: inspeccionar siempre el XML efectivo y el manifiesto de la corrida.

<a id="red"></a>
## Red OSM y parámetros viales

[prepare_simz1.py](../python/prepare_simz1.py) transforma WGS84 a `EPSG:32615`, conservando IDs, etiquetas
y segmentos de los ways admitidos. Respeta sentidos, accesos y barreras modelados, y reporta exclusiones.
No une nodos por proximidad ni elimina todos los componentes distintos del componente dirigido principal.
El extracto vial, su bbox y el límite administrativo son objetos diferentes.

### Snapshot disponible y procedencia verificable

El insumo versionado es [map.osm](../scenarios/zona1/map.osm), con registro en
[osm-source.json](../scenarios/zona1/osm-source.json). No hace falta descargar otro mapa para comenzar.

| Dato | Valor del snapshot |
|---|---|
| Formato / generador | OSM 0.6 / `openstreetmap-cgimap 2.1.0` |
| Commit que conserva el snapshot | `28a9ffded286077d02f251da29ea9d998d732396` |
| SHA-256 con CRLF convertido a LF, sin reserializar XML | `f18296d0479d0efd095a5b6534f9685928fbd2be9d90705b9200864b3a697a0a` |
| Contenido XML | 14558 nodos, 3174 ways, 93 relaciones |
| Rectángulo suministrado | latitud 14.625..14.646; longitud −90.522..−90.505 |
| Último timestamp de elemento | `2026-09-27T14:50:41Z`; no es fecha de descarga |
| Fecha y URL originales de adquisición | No registradas |

La normalización de finales de línea explica hashes distintos entre Git y una copia Windows; no prueba
un cambio cartográfico. El diagnóstico verifica el hash normalizado y XML; los conteos constan en el registro
de procedencia. Para recuperar este
snapshot, obtener el archivo del mismo commit de Git y volver a validar; no sustituirlo silenciosamente
por datos actuales. La [API OSM documenta la consulta por bbox](https://wiki.openstreetmap.org/wiki/API_v0.6#Retrieving_map_data_by_bounding_box:_GET_/api/0.6/map).
La [consulta correspondiente al rectángulo registrado](https://api.openstreetmap.org/api/0.6/map?bbox=-90.522,14.625,-90.505,14.646)
devuelve datos **actuales**, no una descarga histórica reproducible. Una actualización requiere conservar
su fecha, respuesta, hash, conteos y nuevo reporte, revisar diferencias y regenerar en otra carpeta.
Conservar atribución a [OpenStreetMap](https://www.openstreetmap.org/copyright) y licencia ODbL.

La relación OSM `9283360`, versión 34, timestamp `2026-08-29T14:55:45Z`, se denomina Zona 1
y declara `boundary=administrative`, `admin_level=8`. De sus 59 ways exteriores solo 16 están presentes
en el extracto; faltan 43. No permite reconstruir aquí un límite administrativo completo. El filtro de
vías vehiculares tampoco recupera esa geometría. **Obligatorio para las cuatro clases OD:** para `--zone-boundary`, aportar
un Polygon GeoJSON revisado con fuente/versión y validación geométrica; no hay un archivo aprobado
incluido ni una ruta obligatoria implícita. El modo `network` del inicio rápido no lo necesita.

[simz1_road_parameters.py](../python/simz1_road_parameters.py) aplica:

```text
C = 2000 · n · f                  [veh/h], 0 < f ≤ 1
freespeed = velocidad_kmh / 3.6   [m/s]
```

`n` es el número modelado de carriles por sentido. Los 2000 veh/h/carril y `f=1` son una base ideal solicitada,
sin calibración empírica. Los carriles direccionales siguen la orientación original OSM, incluso con `oneway=-1`;
se descuentan `lanes:both_ways` y se rechazan repartos contradictorios. `maxspeed` direccional prevalece sobre
el general; se admite conversión de mph. Datos ausentes/no interpretables usan defaults etiquetados por jerarquía.

El [reporte de importación](../scenarios/zona1/processing-report.json) conserva un snapshot de 4214 nodos,
6183 enlaces y 3470 nodos en el componente dirigido mayor. Registra fuentes de carriles/velocidad, hash OSM
y 19 relaciones de giro no incorporadas. La revisión en lectura del 19/10/2026
recalculó los conteos topológicos indicados abajo, sin regenerar la red.
No se presume que cualquier red regenerada tenga esos conteos o restricciones.

Para futuras importaciones, `prepare_simz1.validate_turn_restrictions` rechaza relaciones OSM
`type=restriction` no eliminadas antes de construir o escribir productos. El `map.osm` actual queda
bloqueado por sus 19 relaciones: todavía falta implementar su traducción a restricciones nativas de
carril/enrutamiento, incluidas las relaciones vía-way e incompletas. Este control no cambia redes ni
resultados existentes y no afirma que los giros estén corregidos en la corrida protegida.

La revisión de solo lectura de `simz1-3dd8683a7d5e44c0944587feff4fe0c8` contrastó el SHA-256 de su red
efectiva con el manifiesto: 6183 enlaces, con 5013/1007/160/3 enlaces de 1/2/3/4 carriles respectivamente.
No hubo discrepancias de sentido o conteo respecto a OSM y las reglas del importador; 4876 enlaces usan
`assumed:one_lane` y 52 `assumed:equal_direction_split`. No hay `oneway=-1`, `lanes:forward` ni
`lanes:backward` en las vías del extracto; esos casos se cubren con fixtures. La red conserva 25 enlaces
con `bridge=yes`, 26 con `tunnel=building_passage` y 37 con `layer` explícito. No se infieren alturas.
Diez restricciones OSM mapeables siguen admitidas por las colas efectivas (por ejemplo, relación
`6008781`: `osm_1308544716_0_forward` → `osm_400252217_0_forward`); seis no tienen representación
dirigida completa en esta red, una requiere vía-way y dos tienen miembros incompletos.

### Conectividad comprobada el 19/10/2026

Se contrastaron `network.xml`, `lanes.xml` y `map.osm` en memoria. La red maestra
coincide por SHA-256 con las entradas de las corridas de 100000 y 229629 personas.
No se escribieron productos cartográficos ni se procesaron sus eventos.

| Medida dirigida para `car` | Resultado |
|---|---:|
| Nodos / enlaces | 4214 / 6183 |
| Componentes fuertemente conectados por nodos | 514 |
| Componente fuerte mayor: nodos / enlaces interiores al componente | 3470 / 5195 |
| Componentes débilmente conectados | 9 |
| Componente débil mayor: nodos / enlaces | 4050 / 5936 |
| Ocho componentes débiles separados: enlaces | 247 |
| Componentes fuertes del grafo de movimientos entre enlaces | 547; mayor de 5195 enlaces |
| Enlaces sin sucesor / sin predecesor | 35 / 40 |
| Nodos terminales, ignorando sentido | 374 |
| Terminales dentro / fuera del bbox de descarga | 281 / 93 |
| Terminales con etiqueta OSM `noexit=yes` | 17 |
| Enlaces de 1 / 2 / 3 / 4 carriles | 5013 / 1007 / 160 / 3 |
| Asignaciones de carril / exclusiones respecto a movimientos `car` adyacentes | 6148 / 0 |
| Enlaces `bridge=yes` / `tunnel=building_passage` | 25 / 26 |

Los 988 enlaces fuera del componente fuerte mayor **no son todos vías desconectadas**:
el sentido único puede impedir el regreso sin romper la conexión débil. Tampoco los
281 terminales dentro del bbox son automáticamente errores interiores de Zona 1;
el bbox no clasifica su perímetro administrativo. Los ways completos importados se
extienden fuera del rectángulo descargado. Un cruce visual no demuestra un nodo común.

La reconstrucción en memoria de las reglas actuales produjo exactamente los 6183
IDs dirigidos: cero diferencias de extremos, carriles, capacidad o velocidad frente
al XML. Confirma la conversión implementada, no exactitud municipal ni calibración.
Se excluyen 2226 ways de áreas/jerarquías no vehiculares, 39 por acceso y 21 segmentos
por nodos bloqueados; no deben habilitarse para aumentar conectividad.

| Causa o sospecha | Evidencia y tratamiento |
|---|---|
| A. Callejón real según OSM | Nodo `10032751965`, lon/lat `[-90.5087828,14.6402496]`, `noexit=yes`, enlaces `osm_1095551802_1_forward/backward`. Conservar; no es verificación de campo. |
| B. Sentido único | La accesibilidad es dirigida. No crear retornos para unir componentes fuertes. |
| C. Recorte | Clasificación administrativa pendiente del polígono completo; no confundir bbox con límite físico. |
| D. Sin acceso `car` | Exclusiones de acceso, barreras y vías no vehiculares conservadas. |
| E. Topología/importación sospechosa | Isla de 45 nodos/79 enlaces, nodo `11287571473`, `[-90.5108994,14.626687]`; isla de 2 nodos/1 enlace, nodo `11103905172`, `[-90.5164514,14.6258972]`. Ambas dentro del bbox; requieren revisión de OSM, sin unión por cercanía. |
| F. Separación visual | El visor solo interpola sucesores con nodo y movimiento compatibles. Fixtures cubren enlaces cortos y desniveles; una discontinuidad concreta requiere diagnóstico de IDs/eventos, no una conexión nueva. |

Las otras seis islas tienen 50, 44, 19, 26, 24 y 4 enlaces. No se ha demostrado que
todas deban incorporarse al componente mayor. Los tags de puente/túnel y los IDs de
nodo se conservan; no se infieren alturas ni se unen pasos a distinto nivel.

Las **19 relaciones de restricción siguen sin importar**. El control previo OD
rechaza 12 casos relevantes o incompletos: `6008781`, `6016436`, `17146405`,
`17146406`, `17373677`, `17475192`, `17478998`, `17502672`, `17884471`,
`17947071`, `20224530`, `20224531`. Son diez prohibiciones vía-node admitidas,
una vía-way admitida y la relación incompleta `17884471` que exige revisión.
Las otras siete relaciones tampoco se consideran importadas por quedar fuera de
ese control efectivo. Ejemplos verificables:

- `6008781`: `osm_1308544716_0_forward` → `osm_400252217_0_forward`,
  nodo vía `631824824`, lon/lat `[-90.5158838,14.628556]`.
- `17478998`: `osm_1273145789_0_forward` → `osm_1270930401_0_forward` →
  `osm_1273145790_0_forward`. Requiere conservar la semántica de la secuencia vía-way.
- `17884471`: solo está presente el miembro destino `34993910`; no inventar el faltante.

Hace falta una versión nueva del escenario para traducir las restricciones, revisar
las islas y aprobar accesos con el polígono real. No basta con regenerar usando el
importador actual: este rechaza las 19 relaciones antes de escribir. Conservar OSM,
hashes y procedencia de cualquier futura corrección sin sobrescribir los maestros
que utilizan las corridas históricas. Ningún buffer se justifica solo por proximidad.

<a id="regeneracion"></a>
## Instalación y regeneración aislada

Los requisitos y el inicio rápido están en el [README principal](../README.md#requisitos). El manifiesto
[simz1-required-files.json](../scripts/installation/simz1-required-files.json) enumera los archivos indispensables;
[check_simz1_install.py](../python/check_simz1_install.py) comprueba su presencia sin escribir, descargar ni
generar. `--git` distingue archivos presentes de archivos publicados en HEAD; `--tests` incluye pytest/Node.
Un clon no recupera módulos locales sin seguimiento. Deben incorporarse al repositorio junto con los cambios
antes de considerar entregable la instalación desde GitHub. No se hizo commit ni push en esta reorganización.

### Dependencias y comprobaciones anteriores

El POM declara MATSim/signals/OTFVis 15.0, Guava 31.1-jre, Log4j 2.20.0, compiler plugin 3.11.0
y exec plugin 3.6.3. Resuelve desde Central y `https://repo.matsim.org/repository/matsim/`, además de
repositorios transitivos. El wrapper descarga Maven 3.9.6 y su JAR 3.2.0 con SHA-256 declarado; Windows
requiere PowerShell y Unix wget/curl para descargar el JAR ausente. Maven instalado es la alternativa.

Python requiere >=3.10. [requirements.txt](../requirements.txt) contiene las dependencias de ejecución,
incluido Pillow (`PIL`); [requirements-test.txt](../requirements-test.txt) lo incluye y añade pytest.
Monte Carlo, `random` y SQLite no necesitan paquetes separados. Node >=22 se usa para pruebas JS,
no para servir el visor. No hay `package.json` ni paso `npm install`: el navegador requiere WebGL y
carga [deck.gl 9.1.14](https://cdn.jsdelivr.net/npm/deck.gl@9.1.14/dist.min.js) por CDN. Sin acceso al CDN,
el visor no está preparado para funcionar completamente sin conexión.

La revisión de instalación anterior verificó el bootstrap sin JAR/caché, Maven 3.9.6/JDK 25.0.4.1,
un venv nuevo Python 3.10.11 con `pip check` satisfactorio, pytest 9.1.1 y Node 22.12.0. Compiló 33 fuentes
desde un repositorio Maven inicialmente vacío; un `Connection reset` de commons-io se resolvió al reintentar
con `-U`. Nueve CLI cargaron `--help` en una copia con solo archivos requeridos. No se ejecutaron sus
simulaciones ni servidores. Esto acredita instalación/compilación de esa revisión, no resultados científicos,
render actual ni ejecución de suites. Los rangos Python y la resolución transitiva no fijan todo el entorno.

### Recuperar derivados sin sustituir maestros

Los maestros de `scenarios/zona1/` están incluidos. Para revisar o recuperar su generación, usar el siguiente
bloque **opcional**, después de instalar/compilar y definir `$simz1Python`/`$simz1Maven` como en el inicio.
No se ejecutó durante esta reorganización. `prepare_simz1.py` produce red, facilities, población smoke,
parámetros viales y reporte; no genera vehículos, carriles ni señales. Primero se copia el config revisado:
el scaffold de una carpeta vacía no equivale a ese maestro. La regeneración puede diferir de derivados
históricos por evolución del código; revisar antes de adoptar el resultado.

```powershell
$simz1Prepared = Join-Path (Get-Location).Path ('runtime\simz1-prepared-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $simz1Prepared -ErrorAction Stop | Out-Null
Copy-Item -LiteralPath .\scenarios\zona1\config-simz1.xml -Destination $simz1Prepared
Copy-Item -LiteralPath .\scenarios\zona1\plans.xml -Destination $simz1Prepared
& $simz1Python .\python\prepare_simz1.py --input .\scenarios\zona1\map.osm --output-dir $simz1Prepared
if ($LASTEXITCODE -ne 0) { throw 'Falló importación OSM.' }
$simz1Network = Join-Path $simz1Prepared 'network.xml'
& $simz1Maven --batch-mode --no-transfer-progress '-Dexec.mainClass=gt.edu.uvg.sim.zona1.LanesGenerator' "-Dexec.args='$simz1Network' '$simz1Prepared'" exec:java
if ($LASTEXITCODE -ne 0) { throw 'Falló generación de carriles/señales.' }
$simz1Vehicles = Join-Path $simz1Prepared 'vehicle-types.xml'
& $simz1Maven --batch-mode --no-transfer-progress '-Dexec.mainClass=gt.edu.uvg.sim.zona1.DrivingProfiles' "-Dexec.args='$simz1Vehicles'" exec:java
if ($LASTEXITCODE -ne 0) { throw 'Falló generación de tipos de vehículo.' }
& $simz1Python -B .\python\simz1_lane_validation.py --config (Join-Path $simz1Prepared 'config-simz1.xml')
if ($LASTEXITCODE -ne 0) { throw 'La copia no pasó validación de carriles/configuración.' }
& $simz1Python .\python\simz1_priority_classification.py --network $simz1Network --signals (Join-Path $simz1Prepared 'signalSystems.xml') --output-dir (Join-Path $simz1Prepared 'priority')
if ($LASTEXITCODE -ne 0) { throw 'Falló catálogo de prioridad.' }
```

`LanesGenerator` ya llama a `TrafficLightsGenerator`. Las comillas simples internas en `exec.args`
conservan espacios al atravesar PowerShell y `mvn.cmd`; usar una ruta sin apóstrofos para este bloque.
Para probar la copia, pasar su config a `ejecutar_simz1.py`, con otra carpeta nueva, diez agentes y una
iteración. No se descarga OSM ni se recurre a `Zona1BaseNetwork`.

<a id="demanda"></a>
## Demanda y distribución temporal

[simz1_population.py](../python/simz1_population.py) distingue cantidad fija,
rango entero inclusivo y modos de población. `--agents` cuenta personas.

| Selección | Contrato |
|---|---|
| `montecarlo` sin cantidad ni `--massive` | Diez personas. |
| `--agents N` | N fijo; incompatible con rango. |
| `--min-agents A --max-agents B` | Sorteo inclusivo; exige ambos límites. |
| `--massive` sin cantidad | Sorteo 150000..250000 para nuevas corridas; etapa separada. |
| N fijo o máximo de rango ≥150000 | Requiere `--massive`, solo en montecarlo. |
| `historical` / `debug` | Nueva demanda sintética de 10000 / una persona con OD y horario fijos. |

La semilla de demanda omitida se resuelve una vez con `secrets.randbits(53)`. `--matsim-seed` es independiente;
omitida, hereda el XML. Repetir semillas solo es reproducible con las mismas entradas, opciones y código.
Fijar N y sortear ese mismo N consumen el RNG de forma diferente. Los hashes permiten contrastar artefactos;
una búsqueda sin coincidencias no prueba unicidad universal.

Para `full-day`, [simz1_temporal.py](../python/simz1_temporal.py) normaliza 24
pesos sintéticos, sortea la hora y luego un instante uniforme dentro de ella:

```text
P(h) = w_h / Σ w_j
E_h = T · P(h)
σ_h = sqrt(T · P(h) · (1−P(h)))
tolerancia descriptiva por hora = 6σ_h + 1
```

`T` es el número de salidas planificadas. Los pesos no son aforos ni cuotas exactas; una población pequeña puede
no cubrir las 24 horas. K viajes por persona producen N·K viajes planificados, conectados desde el destino previo,
con horarios crecientes; QSim puede retrasar salidas por el viaje precedente. El registro `simz1Trips` conserva
planificación sin fabricar salidas observadas.

Los pesos de las horas 00..23 son `(1,0.7,0.5,0.5,0.8,2,6,9,8,5,4,5,6,5,4,4,6,9,8,4,3,2,1.5,1)`
(suma 96). El RNG temporal se separa mediante `SimZ1-temporal-v1:<seed>`; los tiempos por persona
se ordenan y hacen únicos. `peaks` conserva ventanas 06:00..08:30 y 17:00..19:30, inicio QSim 05:30
y fin diario; no admite pesos horarios ni K>1. El antiguo drenaje predeterminado de 3600 s ya no es
el default: hoy es 0. N personas conservan un vehículo cada una; K no multiplica vehículos.
Los IDs planificados en atributos pueden no sobrevivir al replanning de MATSim: el ordinal observado
de la etapa no debe presentarse como un ID nativo garantizado del viaje planificado.

En modo `network`, los destinos usan pesos de atracción `w(n)=0.15+Σ a_c·exp(−d(n,c)²/(2r_c²))`, con hasta tres
centros sintéticos, radios 180..450 m y fuerzas 0.5..2. Un peso 0.7 selecciona corredores disponibles; el resto usa
perímetro geométrico. `fail` rechaza corredores ausentes y `redistribute` acepta redistribuirlos.
No se inventan vías para cumplir cuotas.

La cuota de corredor se aplica al primer origen; Elena está disponible en el snapshot, Asunción/Martí no.
No es un aforo, y 70% es probabilidad, no cantidad exacta. La semilla MATSim heredada del maestro es `20261002`;
los ejemplos fijan ambas semillas explícitamente para que esa herencia no pase inadvertida.

<a id="perfiles"></a>
## Agentes, perfiles e interpretación histórica

En la demanda de SimZ1, un **agente** representa una persona sintética MATSim (`Person`),
con identidad persistente y un plan de actividades y desplazamientos. No representa una persona
identificada mediante observación de campo. Cuando conduce, QSim desplaza su vehículo por la red;
el marcador WebGL representa ese vehículo reconstruido a partir de eventos. Por ello, «personas
generadas», «viajes planificados» y «vehículos visibles» no son cantidades intercambiables.

| Concepto | Unidad y correspondencia actual |
|---|---|
| Persona | Unidad del Monte Carlo y del denominador de composición. Se cuenta una vez, aunque viaje varias veces. |
| Vehículo | Recurso con `vehicle_id` y `VehicleType`: PCU y máximo vehicular. En los cuatro perfiles viales admitidos, `DrivingProfiles.configure()` asigna un vehículo `car` por persona; compartir texto de ID no convierte ambos conceptos en la misma entidad. |
| Viaje | En los generadores actuales, un `leg` entre actividades, identificado en el replay mediante `Trip_ID` y eventos de salida/llegada. K viajes por persona producen N×K viajes planificados, no N×K personas o vehículos. Un futuro viaje PT con transbordos requerirá distinguir viaje completo de etapas. |
| Tipo de agente | Categoría persistente de la persona (`simz1AgentType` con esquema explícito); no equivale automáticamente al tipo del vehículo. El pasajero `TransportePublico` y el vehículo de servicio `TransitBus` son entidades distintas. |

### Camino histórico: tres perfiles

[DrivingProfiles.java](../src/main/java/gt/edu/uvg/sim/zona1/DrivingProfiles.java)
y el generador **sin catálogo nuevo** mantienen tres perfiles sintéticos. Sus probabilidades
son parámetros de muestreo, no cuotas exactas ni una distribución observada de conductores de Zona 1.

| Perfil | Probabilidad | Techo de velocidad | Aceleración en metadatos del vehículo |
|---|---:|---:|---:|
| Tortuga | 0.25 | 20 km/h | 0.8 m/s² |
| Normal | 0.60 | 50 km/h | 2.0 m/s² |
| Liebre | 0.15 | 90 km/h | 3.0 m/s² |

Los vehículos tienen 1 PCU y dimensiones nominales 4.5×1.8 m. QSim estándar no integra esas aceleraciones.
Los techos de perfil no elevan `freespeed` y son distintos de las tasas usadas para interpolar movimiento del visor.

Los reportes `montecarlo-report.json`, referenciados con hash por `inputs.demand_report` en cada
`run-manifest.json`, conservan estos conteos en `driving_profiles`:

| Corrida histórica | Normal | Liebre | Tortuga | Total de personas |
|---|---:|---:|---:|---:|
| `run-052734f90d154b23bb8899cd0bbc3ef4` | 59946 | 14922 | 25132 | 100000 |
| `run-night-20261017-012651-6a8d9ac3` | 137912 | 34362 | 57355 | 229629 |

Son conteos de personas generadas, no de vehículos que llegaron ni de marcadores visibles. Ambos manifiestos
carecen de `agent_configuration`; no se les atribuyen el nuevo reparto 40/25/10/10/10/5 ni Tortuga=25 km/h.
La pertenencia y los parámetros de una corrida se verifican en sus archivos conservados, no en los defaults
actuales del repositorio. El [historial](#historia) mantiene también sus horizontes y limitaciones originales.

<a id="seis-categorias"></a>
### Configuración objetivo de seis categorías (opt-in)

El catálogo [agent-types-v2.json](../scenarios/zona1/agent-types-v2.json), esquema
`simz1-six-v1`, prepara una propuesta nueva. Sin `--agent-catalog`, el generador
conserva el muestreo histórico 60/15/25 y Tortuga=20 km/h descritos arriba.
No se modifican ni reclasifican las corridas de 100000 o 229629 personas.

La tabla describe **objetivos sintéticos**, no una composición ya simulada con seis tipos. «Integrado» significa
que existen generación, serialización y carga compatibles para entradas nuevas; no equivale a calibración física.

| Categoría / tipo canónico | % objetivo de personas | PCU vehicular propuesto | Máximo vehicular propuesto | Horario de salidas planificadas | Implementación efectiva |
|---|---:|---:|---:|---|---|
| `Normal` | 40 | 1 | 50 km/h | 24 h; densidad ×4 en 06:00–08:30 y 17:00–19:30 | Integrado para nuevas entradas v2 |
| `Motociclista` | 25 | 0.25 | 60 km/h | 24 h, uniforme | Integrado como tráfico `car` FIFO; sin filtrado |
| `Liebre` | 10 | 1 | 90 km/h | 24 h, uniforme | Integrado; techo de perfil sujeto al enlace |
| `Tortuga` | 10 | 1 | 25 km/h | 24 h; densidad ×4 entre 06:00 y 18:00 | Integrado para v2; legado sigue en 20 |
| Transporte público / `TransportePublico` | 10 | Pasajero: no aplica; bus: rango 2.5–3.0, catálogo 3.0 | Sin definir para el bus (`null`) | 05:00–21:00 propuesto | Parcial: asignación; servicio no implementado |
| Transporte pesado / `TransportePesado` | 5 | Rango 3.0–4.0; catálogo 3.5 | Sin definir (`null`) | 00:00–05:00, 09:00–16:30 y 21:00–24:00 | Parcial: asignación; ejecución bloqueada |

Normal, Liebre y Tortuga reutilizan sus nombres; Motociclista es un tipo vial adicional. El esquema
`simz1-six-v1` evita confundir los valores nuevos con los históricos. El archivo se llama `agent-types-v2.json`, pero su identificador de esquema efectivo es
`simz1-six-v1`. PCU es un equivalente de automóvil para el modelo de colas, no una unidad de pasajeros.

#### Denominador, redondeo y reproducibilidad

Los porcentajes suman 100 **de personas**. Los cuatro perfiles generales y pesado
representan conductores; `TransportePublico` representa pasajeros. Un autobús de
servicio no se crea por pasajero ni cuenta como una persona adicional de Monte Carlo.
La flota, ocupación y capacidad de pasajeros permanecen sin definir. K viajes por
persona conserva N personas y sus tipos; no multiplica automáticamente vehículos.

Por ejemplo, **20 personas** se asignan como 8 Normal, 5 Motociclista, 2 Liebre, 2 Tortuga,
2 pasajeros públicos y 1 conductor pesado. Con K=2, la asignación propone 40 viajes, incluidos 4 de pasajeros;
esto no crea planes PT ejecutables y el número de buses sigue desconocido. Las cuotas por viaje solo coincidirían con las de personas si K fuera
igual para todas. No puede inferirse una cuota de vehículos de transporte público a partir del 10 % de pasajeros.

[allocation_counts() y allocate_types()](../python/simz1_agent_types.py) usan restos
mayores con aritmética entera, desempate por orden canónico y una permutación con
semilla independiente. Las cuotas exactas solo son posibles cuando N lo permite;
el redondeo siempre conserva N. Formalmente, se asigna primero `floor(N × porcentaje / 100)` y se
reparten las plazas restantes por residuo descendente; empates: orden canónico de la tabla. Cambiar la
semilla no cambia esos conteos, pero sí la asignación individual. Para reproducir el resultado deben
conservarse N, semilla, catálogo, versión del código y entorno. `sample_departures()` usa otro flujo reproducible
por persona/tipo y densidades por segundo sobre intervalos `[inicio, fin)`.

#### Distribución temporal y alcance de las restricciones

La probabilidad de elegir una franja es proporcional a `peso × duración`; dentro de ella se muestrea
uniformemente y se ordenan salidas únicas por persona. Para Normal, las cinco horas pico tienen peso 4
frente a 1 en las otras 19: reúnen `20/39 ≈ 51.28 %` de sus salidas **en esperanza**, no una cuota garantizada.
Para Tortuga, las 12 horas diurnas reúnen el 80 % esperado. Motociclista y Liebre son uniformes: no existe
un patrón laboral o de entregas específico implementado para la moto. El intervalo nocturno de pesado
21:00–05:00 se divide en dos franjas para no introducir salidas más allá de las 24 h.

Los factores ×4 y todas las franjas son **supuestos sintéticos parametrizables**,
sin una verificación municipal PMT. Son horarios de salida planificada, no
restricciones de circulación ya aplicadas: retrasos de QSim pueden mover una salida
real, y una salida dentro de la ventana no garantiza terminar el viaje dentro de ella.
No se programan salidas fuera de `[0,86400)` ni se borran vehículos para cumplir horarios.

No se proporcionó una fuente oficial PMT que permita tratar estas franjas como legislación vigente.
Para elevarlas de supuesto a restricción municipal se necesita identificar autoridad, instrumento,
vigencia, vías, categorías y excepciones aplicables. El campo `municipal_status='verified_source'` exige
una referencia en el validador, pero esa comprobación informática no autentica ni verifica jurídicamente la fuente.

#### Implementación efectiva y activación

Para preparar únicamente la asignación completa, en una **carpeta nueva**:

```powershell
.\.venv\Scripts\python.exe -B .\python\prepare_simz1_agents.py --catalog .\scenarios\zona1\agent-types-v2.json --agents 20 --seed 17 --output-dir .\runtime\six-type-proposal-20
```

Este comando no ejecuta MATSim ni crea `plans.xml`. Escribe catálogo congelado,
`agent-types.jsonl` con exactamente N identidades y horarios, y
`agent-plan-manifest.json` con hashes, conteos y motivos del bloqueo. `runnable=false`
es deliberado: no se sustituye PT/pesado por coches, no se omiten esas personas y
no se renormaliza el 85 % soportado. Los IDs de vehículo efectivo quedan nulos en
esta asignación, porque aún no existen vehículos de una corrida.

El generador y el lanzador aceptan `--agent-catalog RUTA`. La mezcla objetivo
completa falla antes de crear una corrida, incluso si una N pequeña redondea las
categorías pendientes a cero. Una variante **explícita**, con participaciones PT y
pesado cero y otras participaciones enteras que sumen 100, permite generar los
cuatro perfiles soportados. No es la mezcla de seis ni se produce automáticamente.
El catálogo no se combina con `historical`, `debug`, pesos horarios globales,
`--temporal-profile` o drenaje distinto de cero; exige `fastest-time`.

La exigencia `fastest-time` se aplica a **los cuatro tipos viales**, no únicamente a Liebre. Su coste de
ruteo es tiempo esperado; no se implementó una función de scoring distinta por categoría ni una preferencia
calibrada de riesgo, distancia o comodidad. `DrivingProfiles.freeFlowTime()` limita la velocidad por el mínimo
de `freespeed(t)`, máximo del perfil y máximo de `VehicleType`; `expectedTime()` incorpora tiempo observado
cuando existe, sin bajar de ese límite de flujo libre. En un enlace de 50 km/h, Liebre no adquiere permiso
para viajar a 90 km/h. Semáforos, colas y prioridades pueden aumentar la demora. El nombre «Liebre» no
autoriza cruzar rojo ni infringir restricciones. Véase [ruteo y scoring](#enrutamiento).

[typed_people()](../python/simz1_agent_demand.py) conserva el muestreo espacial y
los archivos de red/carriles/señales. Congela únicamente tipos y horarios nuevos
en los inputs privados de la corrida. Las restricciones específicas `motorcycle`
no soportadas provocan rechazo del preflight; no se ignoran para reutilizar la red
`car`. Esto no acredita integridad legal de OSM ni corrige las 19 relaciones de giro
pendientes descritas en la sección de importación.
[DrivingProfiles.configure()](../src/main/java/gt/edu/uvg/sim/zona1/DrivingProfiles.java)
valida versión, correspondencia persona/vehículo, PCU y velocidad cargados; rechaza
mezclas legacy/v2 y categorías no activables. No cambia sentidos, movimientos de
carril, señales ni prioridades. El máximo vehicular nunca aumenta `freespeed`.
PCU afecta a flujo/almacenamiento nativos, no prueba un tamaño físico ni filtrado.
Las dimensiones nominales comunes del XML y del visor no se presentan como medidas
de motocicletas. No se añadió integración de aceleración física.

La red efectiva y `SimZ1RouteSafety`/`SimZ1TurnRouter` conservan sentidos y movimientos permitidos;
las señales y prioridades siguen dependiendo de su configuración efectiva. Esta integración no añade
autorizaciones municipales ni completa etiquetas OSM ausentes. `vehicle_types_xml()` escribe
`maximumVelocity` en m/s y `passengerCarEquivalents pce`; Java valida ambos y utiliza
`QSimConfigGroup.VehiclesSource.fromVehiclesData`, por lo que no son solo nombres de color en el visor.

#### Componentes pendientes y validación física

**Transporte público pendiente.** MATSim 15 ofrece `TransitSchedule`, `TransitRoute`
con `NetworkRoute`, paradas ordenadas y salidas finitas asociadas a vehículos. Falta
aportar fuentes de líneas/paradas, horarios, capacidad de pasajeros, flota y su
asignación sin solapamientos; integrar planes de pasajeros y validar accesos,
conexiones y traslados entre servicios. `TransitScheduleValidator.validateAll()`
comprueba coherencia estructural, no autorización municipal ni cobertura de toda
esa operación. La terminación nativa ocurre tras la última parada y servicio; una
hora de cierre no debe eliminar un bus en circulación. Deben definirse última
llegada, retorno/depósito y política ante retrasos. El catálogo no inventa rutas,
frecuencias, bucles, traslados ni una velocidad de bus que no se proporcionó.
**No hay líneas de Transmetro implementadas ni un servicio PT de viajes OD equivalente a esas líneas.**
El preparador solo registra personas pasajeras y horas; no produce sus planes operativos ni buses. Tener
soporte de tránsito en la biblioteca MATSim no significa que SimZ1 lo haya configurado e integrado.

**Pesado pendiente.** Se necesitan velocidad máxima explícita, enlaces/rutas
autorizados con procedencia y aplicación del acceso durante ruteo, reruteo y
circulación real. `allows_link()` solo comprueba un requisito estático; no instala
esa política en QSim. Los horarios de salida propuestos no impiden por sí solos
entrar o permanecer en una vía fuera de la franja. Por eso pesado sigue bloqueado,
incluso al rellenar una allowlist, hasta implementar y validar ese comportamiento.

| Nivel de evidencia | Qué permite afirmar | Qué sigue pendiente |
|---|---|---|
| Configuración objetivo | Seis nombres, suma 100 % de personas, parámetros y horarios explícitos. | Calibración con demanda y flota observadas; procedencia municipal de restricciones. |
| Integración implementada | Asignación exacta de seis categorías; cuatro tipos viales con XML, PCU, máximo, ruteo y metadatos. | Ejecutar y validar una nueva corrida autorizada para los cambios físicos; no trasladar resultados a históricos. |
| Preparación parcial | PT y pesado tienen roles, porcentajes y bloqueos verificables. | Servicio PT fijo completo; acceso espacial y temporal efectivo de pesados. |
| Representación visual | Posición/velocidad reconstruidas desde eventos y `Motion_Plan`, con procedencia. | No acredita aceleración QSim, filtrado de motos, cambios laterales observados ni interacción vehicular continua. |

Las dimensiones nominales 4.5×1.8 m y las tasas históricas de aceleración son metadatos o parámetros
de representación, no mediciones de campo. Los porcentajes, PCU y máximos propuestos tampoco son una
calibración empírica. Las pruebas de configuración y ruteo demuestran contratos de software; para evaluar
flujo, almacenamiento, colas o tiempos bajo la nueva mezcla harían falta corridas nuevas y validación
con observaciones pertinentes. No se afirma que el modelo reproduzca físicamente seis clases de tráfico.

<a id="composicion-agentes"></a>
### Verificar composición, manifiestos y archivos efectivos

Las entradas nuevas conservan `simz1AgentSchema`,
`simz1AgentType`, `drivingProfile`, `effectiveVehicleType` y techo de velocidad por
persona. El manifiesto de corrida incluye catálogo, conteos realizados y referencia
con SHA-256 al ledger individual; ambos archivos también pertenecen a `inputs`.
Tras simular, el XML efectivo de vehículos continúa siendo la evidencia de QSim.
El export conserva `Agent_Type`, `Agent_Schema`, `Vehicle_Type`, fuente y
`Vehicle_PCU`; el visor los consulta sin derivar nuevas categorías de perfiles
históricos, ni usar PCU para geometría. Las tasas de suavizado para perfiles sin
referencia específica usan un respaldo visual declarado, no aceleración física.
Los exports existentes no se modifican ni adquieren metadatos nuevos retroactivamente.

La verificación separa los siguientes productos:

| Producto | Evidencia que debe comprobarse |
|---|---|
| Asignación sin corrida | `agent-plan-manifest.json`: `artifact_kind=simz1-agent-allocation-not-a-run`, `allocated_persons`, `person_counts`, `passenger_persons`, `runnable=false`, `instantiated_vehicles=0`; flota PT `null`. `artifacts.catalog` y `artifacts.person_types` contienen rutas y hashes. No es un manifiesto de resultados. |
| Nueva población vial admitida | `run-manifest.json.agent_configuration`: `denominator=persons`, catálogo congelado, `realized_person_counts`, `allocation_method`, `catalog_artifact` y `person_type_artifact`. Contrastar con `montecarlo-report.json.agent_type_counts` y `counts.planned_persons`. |
| Personas y planes de entrada | `inputs.plans` referencia `plans.xml`; `verify_type_ledger()` contrasta cada persona, tipo, máximo y salida con `inputs/agent-types.jsonl`. No usar el orden o prefijo del ID para deducir tipo. |
| Configuración realmente ejecutada | En una corrida completada, `effective_config` y `effective_vehicles` referencian los XML de salida y sus hashes; comprobar `VehicleType`, PCU, máximo y asignación vehículo→tipo. Los planes de `results[iteración].plans` conservan atributos de personas; los eventos acreditan lo que circuló. |
| Corrida histórica | Si falta `agent_configuration`, consultar `inputs.demand_report`, `driving_profiles`, `driving_profile_probabilities`, atributos `drivingProfile` y vehículos efectivos propios. Ausencia de esquema nuevo no autoriza reconstruirlo por porcentajes. |
| Export WebGL | `run_id`, iteración y `run_manifest_sha256` deben corresponder a la corrida; contrastar `Agent_Type`, `Agent_Schema`, `Vehicle_Type`, `Vehicle_Type_Source` y `Vehicle_PCU` cuando existen. Un manifiesto de export por sí solo no sustituye el ledger individual. |

La siguiente consulta es de **solo lectura**, desde la raíz. Usa la corrida histórica explícita de 229629;
para una futura corrida v2, cambiar únicamente `$simz1Run`. Verifica hashes y composición de entrada;
la lectura del XML efectivo de vehículos puede tardar, pero no procesa eventos ni crea exports:

```powershell
$simz1Python = (Resolve-Path '.\.venv\Scripts\python.exe').Path
$simz1Run = (Resolve-Path '.\scenarios\zona1\montecarlo\run-night-20261017-012651-6a8d9ac3').Path
@'
import json, sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, 'python')
from simz1_run import checked_path
from simz1_agent_types import load_catalog, catalog_manifest
from simz1_agent_demand import verify_type_ledger
from simz1_motion import read_vehicle_definitions
run = Path(sys.argv[1])
m = json.loads((run / 'run-manifest.json').read_text(encoding='utf-8'))
report = json.loads(checked_path(run, m['inputs']['demand_report']).read_text(encoding='utf-8'))
cfg = m.get('agent_configuration')
if cfg:
    catalog = load_catalog(checked_path(run, cfg['catalog_artifact']))
    assert catalog_manifest(catalog)['sha256'] == cfg['sha256']
    assert catalog == cfg['catalog']
    ledger = checked_path(run, cfg['person_type_artifact'])
    counts = verify_type_ledger(checked_path(run, m['inputs']['plans']), ledger, catalog)
    assert counts == cfg['realized_person_counts'] == report['agent_type_counts']
else:
    counts = report['driving_profiles']
    print('Perfiles historicos; no existe asignacion de seis categorias.')
assert sum(counts.values()) == m['counts']['planned_persons']
print(json.dumps({'run_id': m['run_id'], 'status': m['status'],
                  'persons': counts, 'planned': m['counts']}, indent=2))
if m.get('effective_vehicles'):
    types, vehicles = read_vehicle_definitions(checked_path(run, m['effective_vehicles']))
    print(json.dumps({'effective_vehicle_types': types,
                      'vehicles_by_type': dict(Counter(vehicles.values()))}, indent=2))
else:
    print('Sin vehiculos efectivos de salida: configuracion preparada, no validacion QSim.')
if m.get('effective_config'):
    print('Configuracion efectiva:', checked_path(run, m['effective_config']))
'@ | & $simz1Python -B - $simz1Run
if ($LASTEXITCODE -ne 0) { throw 'Fallo la verificacion de composicion o integridad.' }
```

La lectura histórica verifica conteos declarados y hashes, sin volver a contar personas en planes de salida.
`maximum_velocity_mps` se convierte a km/h multiplicando por 3.6. Un tipo definido en XML puede tener cero
vehículos asignados; definirlo no demuestra su participación. Los conteos de vehículos efectivos tampoco
demuestran cuántos circularon o llegaron: eso requiere eventos/métricas de la misma iteración y horizonte.

### Identificar el tipo en la tarjeta contextual WebGL

Hover muestra la tarjeta; clic fija el vehículo. «Tipo de agente» utiliza `Agent_Type` explícito, luego
`Vehicle_Type` canónico y, para los históricos, `Profile` registrado Normal/Liebre/Tortuga. Si falta respaldo,
muestra **«No registrado»**. Que aparezca «Tortuga» en ambas versiones no cambia su máximo: si los metadatos
vehiculares históricos registran 20 km/h, la tarjeta muestra 20; si faltan, muestra «—». No toma 25 del catálogo nuevo.
Admitir etiquetas PT/pesado en el export y en pruebas con fixtures no demuestra que exista un servicio ejecutado.
La tarjeta contiene solo identidad, tipo, velocidad actual, máxima, tiempo transcurrido y duración estimada;
las fuentes exactas y la ausencia de una predicción registrada se detallan en [el visor](#visor).

<a id="pruebas-perfiles"></a>
### Regresiones de perfiles y apertura del visor existente

Desde la raíz, estas pruebas focales usan fixtures pequeños, sin MATSim, servidor o navegador.
Algunas escriben XML/JSON temporales de hasta 20 personas; no alteran corridas guardadas:

```powershell
$simz1Python = (Resolve-Path '.\.venv\Scripts\python.exe').Path
foreach ($testName in @('agent_types', 'agent_demand', 'agent_metadata')) {
  & $simz1Python -B -m unittest discover -s .\python -p "test_simz1_$testName.py" -v
  if ($LASTEXITCODE -ne 0) { throw "Fallo Python: $testName" }
}
$simz1ProfileJsTests = @('simz1_agent_metadata', 'simz1_vehicle_card', 'simz1_continuous_replay',
  'visualizador_z1_selection', 'visualizador_z1_controls', 'visualizador_z1_paged',
  'visualizador_z1_motion', 'simz1_vehicle_picking', 'simz1_render_performance')
foreach ($testName in $simz1ProfileJsTests) {
  node ".\python\test_$testName.cjs"
  if ($LASTEXITCODE -ne 0) { throw "Fallo JavaScript: $testName" }
}
```

Para el contrato Java, con el JDK y Maven del proyecto configurados, compilar y ejecutar únicamente
[SixTypeProfilesCheck](../src/test/java/gt/edu/uvg/sim/zona1/SixTypeProfilesCheck.java):

```powershell
.\mvnw.cmd --batch-mode --no-transfer-progress -DskipTests test-compile
if ($LASTEXITCODE -ne 0) { throw 'Fallo la compilacion de checks Java.' }
.\mvnw.cmd --batch-mode --no-transfer-progress '-Dexec.classpathScope=test' '-Dexec.mainClass=gt.edu.uvg.sim.zona1.SixTypeProfilesCheck' exec:java
if ($LASTEXITCODE -ne 0) { throw 'Fallo SixTypeProfilesCheck.' }
```

`SixTypeProfilesCheck` valida carga y ruteo Java usando clases MATSim en memoria, sin arrancar QSim. Las pruebas de
PT verifican el bloqueo por falta de servicio, no un servicio ficticio. Los cambios
de PCU, composición y horarios necesitan **una nueva corrida autorizada** para
medir flujo, colas y tiempos; estas pruebas no certifican realismo ni estabilidad.
Las regresiones de metadatos usan valores de prueba para PT/pesado; no son propuestas de velocidad,
capacidad o flota. No ejecutar indiscriminadamente toda la suite Python bajo una restricción de «sin
servidores»: otros tests sí levantan servidores efímeros. Estos comandos de comprobación se ofrecen para
ejecución manual; esta revisión documental no vuelve a ejecutar simulaciones ni las suites.

Para abrir el export histórico de 229629 en **localhost:8793**, usar el [comando exacto del visor](#abrir-229629)
tras detener con Ctrl+C un servidor previo en ese puerto. No usar selección automática `latest-successful`
para reproducir una corrida histórica concreta. El servidor sirve el código actual de interfaz y conserva
SQLite, los 96 bloques y Motion_Plan existentes; no hay que regenerarlos.

<a id="enrutamiento"></a>
## Enrutamiento y reruteo

La política vigente es `zona1WithinDayRouting.routingPolicy=fastest-time`.
Todos los perfiles minimizan segundos estimados, sujetos a sus techos:

```text
v* = min(freespeed(t), techo_perfil, techo_vehículo si existe)
τ_ff = longitud / v*
τ_estimado = τ_ff si falta observación; max(τ_ff, τ_observado) en otro caso
costo_fastest-time = τ_estimado
```

`NaN` representa observación ausente; valores negativos o infinitos fallan.
[ExperiencedTimeRouting](../src/main/java/gt/edu/uvg/sim/zona1/ExperiencedTimeRouting.java) usa bins de 60 s.
El tiempo link-to-link ya incluye recorrer FROM y su demora de salida; no se suma otra vez ese enlace ni una
penalización inventada de cruce. Los tiempos estimados no son conocimiento perfecto de condiciones futuras.
Sin observaciones, el ruteo inicial usa flujo libre limitado por perfil. `ReRoute` aprende entre iteraciones
con tiempos experimentados; el maestro combina `ChangeExpBeta=0.8`, `ReRoute=0.2`, memoria de cinco planes
y fracción 0.8 para desactivar innovación. Ese aprendizaje no reemplaza el reruteo durante el viaje.

La alternativa explícita `legacy-generalized-experimental` conserva `costo=α·duración+0.02·longitud`,
con α=0/1/3 para Tortuga/Normal/Liebre. Es experimental, no calibrada. No existe flag CLI `--routing-policy`;
la política se declara en el XML de una configuración nueva.

[CongestionAwareRerouting](../src/main/java/gt/edu/uvg/sim/zona1/CongestionAwareRerouting.java)
evalúa cada 60 s, con enfriamiento de 300 s y observaciones de hasta 300 s. Dispara si
`(estimado≥3·nominal y estimado−nominal≥60 s)` o si `capacidad_actual≤0.5·capacidad_base`.
La candidata debe mejorar estrictamente el costo y superar validación; descuenta lo ya recorrido del enlace actual.
Sin giro reciente usa respaldo por enlace, sin sumar ambas demoras.

La participación predeterminada es 0.5 y el presupuesto 100 cálculos por paso.
`enabled=false` impide cálculos e instalaciones; el presupuesto no lo activa.
[SimZ1RouteSafety](../src/main/java/gt/edu/uvg/sim/zona1/SimZ1RouteSafety.java)
valida continuidad, modo, nodos, carriles, prefijo recorrido, destino y aparición actual de enlaces repetidos.
La instalación es secuencial antes del paso QSim, con restauración ante fallo. `changed` acredita instalación;
recalcular no basta.

La ruta física se interpreta como `[initial, inner..., end]` y el índice final como `m+1`; si inicio=fin
y no hay enlaces internos es un único enlace físico, mientras que una ruta con interiores puede ser un loop.
Se valida la **aparición** actual, no solo el ID. La regresión histórica `[a,b,c,a,d,e]` en índice 3 podía
perder la segunda `a` al editar y producir una conexión inválida; demostrar esa regresión no identifica
la causa de seis fallos antiguos sin rutas completas. Antes de instalar se contrasta también `nextLinks`
del carril actual. La política compartida se aplica al ruteo inicial y al `ReRoute` entre iteraciones.

`zona1WithinDayReroute`, `zona1RerouteRejected` y `zona1InvalidCurrentRoute` separan instalación, rechazo
y ruta ya inválida. `candidateDiffers` no equivale a `changed`. `zona1RerouteStep` registra cálculos, rechazos
y tiempos; CPU `-1` significa no disponible y 0 puede ser resolución insuficiente. El presupuesto selecciona
IDs ordenados de forma cíclica; no depende de cuánto tiempo de pared haya consumido la máquina.

<a id="carriles"></a>
## Carriles, capacidad y almacenamiento

[LanesGenerator](../src/main/java/gt/edu/uvg/sim/zona1/LanesGenerator.java)
divide un enlace de longitud L y n carriles en una sección compartida y n colas terminales. Todas permiten
las salidas car existentes, incluidos retornos; no son bahías de giro observadas. Sin asignación válida queda cola estándar.

```text
q = min(100 m, 0.8·L)
longitud original efectiva = L−q; longitud terminal = q
longitud por camino original→terminal = L
Σ(longitud efectiva · carriles representados) = n·L
C_h = C_enlace · 3600 / período_capacidad
C_terminal = C_h/n; Σ C_terminal = C_h
```

Original y terminales están en serie: sumar ambas capacidades duplica el flujo.
La auditoría de fuentes MATSim 15 conservada en el [archivo documental](#conservacion) describe,
para `trafficDynamics=queue`, el umbral por cola sin su buffer separado:

```text
G = longitud_efectiva · carriles_representados / tamaño_celda · factor_storage
F = C_h/3600 · factor_flujo · duración_paso
V = longitud_efectiva/velocidad_libre · C_h/3600 · factor_flujo
umbral_cola = max(G,F,V)
```

Para vehículos de 1 PCU y cola inicialmente vacía, `ceil(umbral)` es un cálculo analítico de admisión;
no son plazas físicas garantizadas ni capacidad sostenible. Buffers, PCU, redondeos por paso y dinámica importan.
Conservar n·L y capacidad nominal no conserva exactamente el tiempo o almacenamiento de una sola cola.

En `withHoles`/`kinematicWaves` intervienen propagación de huecos y mínimos adicionales; no extrapolar
el cálculo `queue`. Los carriles intermedios se procesan antes que las colas; la discretización temporal
puede cambiar tiempos respecto a un enlace sin división. La auditoría estática histórica conservó:

| Magnitud del snapshot auditado | Sin división / con carriles |
|---|---|
| Asignaciones / enlaces estándar | 6148 / 35 |
| Terminales / colas totales con división | 7468 / 13616 |
| Enlaces <7.5 m / carriles señalizados / referencias de retorno | 2446 / 484 / 3008 |
| PCU geométricos | 25337.394319 / 25337.394319 |
| Suma de umbrales nativos | 25559.090679 / 27349.631627 |
| Suma de techos enteros, 1 PCU | 28442 / 33721 |
| Suma analítica de buffers separados | 4148.888889 / 8297.777778 |

Son resultados analíticos del snapshot del informe `SIMZ1_LANES.md`, no una nueva medición ni una
garantía de capacidad. El archivo preserva derivaciones, comparaciones y fuentes de cada columna.

<a id="semaforos"></a>
## Semáforos y offsets

[TrafficLightsGenerator](../src/main/java/gt/edu/uvg/sim/zona1/TrafficLightsGenerator.java)
usa marcas OSM `traffic_signals` y accesos car. Agrupa por eje geométrico, con
`|dy|≥|dx|` como avenida, y genera planes sintéticos de ciclo C=80 s.
[Zona1FixedTimeController](../src/main/java/gt/edu/uvg/sim/zona1/Zona1FixedTimeController.java)
restaura la fase al iniciar a mitad de ciclo: `φ=((t−offset)%C+C)%C`.

| Fase del ciclo | Avenida | Calle |
|---|---|---|
| 0..43 / 43..47 | Verde / ámbar | Rojo |
| 47..49 | Rojo | Rojo |
| 49..74 / 74..78 | Rojo | Verde / ámbar |
| 78..80 | Rojo | Rojo |

Los intervalos incluyen el inicio y excluyen el final. `dropping` marca rojo; el controlador solicita ámbar 4 s antes.
La política Python de offsets es `preserve` por defecto; `zero` fija cero y `hash` aplica
`unsigned(SHA256(UTF8("SimZ1-offset-v1:seed:systemId"))) mod C`.
La [implementación](../python/simz1_signal_offsets.py) persiste la decisión.
No acredita tiempos levantados ni coordinación de onda verde.

GREEN, YELLOW y OFF permiten paso nativo; RED y REDYELLOW lo impiden. Ámbar no demuestra por sí solo una infracción.
El color procede de eventos y permiso nativo; si no concuerdan se declara no disponible. GO no garantiza cruce:
puede seguir una espera por almacenamiento. El replay no fabrica estados previos al primer evento
ni sustituye evidencia por el horario dibujado.

La semilla de offsets es un entero firmado de 64 bits; `hash` usa por defecto la semilla de demanda,
sin consumir su RNG. Ejemplo conservado: sistema `2`, semilla `20261015`, C=80 produce offset 8.
Se copia el control efectivo a `inputs/signalsystems-signalcontrol.xml`; se validan offsets enteros
en `[0,C)` y el plan diario esperado. `preserve` conserva el control de entrada.
Los eventos `signalgroupstatechanged` se ordenan conservando el orden original en timestamps iguales:
la consulta usa el último estado con tiempo ≤t, sin extrapolar el futuro. Duplicados de grupo/tiempo/estado
se rechazan; antes del primer evento el estado es desconocido.

`QSignalsNetworkFactory` admite señales con o sin carriles; no se fuerzan carriles por encender señales.
Se rechazan tiempos link-to-link con `removeStuckVehicles=true`, ruteo link-to-link sin su calculador
y tiempos link-to-link con `separateModes=true`. Si este último parámetro falta se deriva `false`
y queda registrado; un `true` explícito falla. `usingFastCapacityUpdate` altera acumulación de capacidad,
pero no elimina la aceptación nativa de giro ni convierte rojo en permiso.

<a id="prioridad"></a>
## Prioridad sin semáforo

[UnsignalizedPriority](../src/main/java/gt/edu/uvg/sim/zona1/UnsignalizedPriority.java)
actúa en nodos con accesos calle/avenida, sin señales nativas ni marca `traffic_signals`. Defaults: activo,
`stopSeconds=5`, `maxYieldSeconds=30`, `classification=osm-hierarchy`, `conflicts=geometric`.
Apagar señales no convierte automáticamente sus nodos en cruces elegibles de prioridad.

La clasificación combina atributo explícito, jerarquía OSM, nombre y fallback de orientación identificado.
`service` sigue secundario aunque se llame Avenida; `primary` sigue prioritario aunque se llame Calle.
Son reglas reproducibles, no un levantamiento de señales de Alto. La avenida no tiene parada obligatoria.

Para calle `stop`, `t_ready=t_cabecera+max(5,stopSeconds)`; `yield` no añade parada. El reloj de visita no reinicia
durante cesión o almacenamiento. Tras 30 s desde ready puede reservarse un cruce seguro por equidad;
cero desactiva esa reserva. Se consulta cabecera ofrecida, siguiente movimiento, permiso y almacenamiento:
una avenida bloqueada no reserva por presencia. GO y CROSS son hechos distintos. Los conflictos geométricos
no simulan carrocerías barridas ni peatones.

Los modos de clasificación `osm-hierarchy`, `osm-name-orientation`, `orientation` y `explicit`, junto con
sus fuentes, quedan en el catálogo. La política de conflictos `verified-node-table` usa el atributo
`simz1:nonConflictingMovements`, con pares `in>out|in>out` separados por `;` y geometría validada;
no es una tabla CSV externa de movimientos. La ambigüedad conserva conflicto, en lugar de declarar
seguridad. Los overrides viales sí usan CSV con columnas `link_id,to_node,priority_role,priority_control,source,rationale`:
`prepare_simz1.py --priority-overrides` los importa y el clasificador acepta `--overrides`.
Una plantilla vacía/fixture no acredita señales de campo. CROSS exige evidencia del movimiento nativo
con ambos enlaces; una decisión GO puede terminar esperando storage.

El cambio histórico a `osm-hierarchy` redujo nodos elegibles 853→429, accesos stop 913→451,
accesos prioritarios 954→463 y decisiones de orientación 3137→0, conservando 163 nodos señalizados.
No es una comparación controlada de rendimiento. De 19 restricciones OSM ignoradas, diez eran mapeables
y seguían permitidas en carriles, seis estaban fuera, una usaba via-way y dos eran incompletas.
Es una limitación estática; no equivale a diez infracciones observadas en una corrida.

<a id="gateways"></a>
## Gateways y dominio espacial

`network` no requiere polígono. `gateway-od`/`through-traffic` requiere un Polygon GeoJSON RFC 7946 WGS84
validado para el estudio, con fuente, versión y aprobación. El hash verifica el archivo, no su aprobación municipal.
No se sustituye por bbox OSM, perímetro vial o relación administrativa incompleta. Se admite Polygon directo,
Feature o FeatureCollection de un elemento, no MultiPolygon. Cada posición debe ser exactamente `[lon,lat]`,
finita, sin booleanos ni Z, dentro de rangos geográficos; `crs` debe estar ausente o ser null.
Los anillos tienen al menos cuatro posiciones, cierre exacto, área no nula y sin repeticiones intermedias
ni autointersecciones. Se admiten concavidades y huecos interiores disjuntos, sin contactos, solapes o anidación;
no se exige orientación. La red requiere `EPSG:32615` explícito y se transforma a WGS84 con `always_xy`.

[simz1_gateway_od.py](../python/simz1_gateway_od.py) selecciona enlaces interiores
existentes adyacentes a frontera o a cruces verificados. Los enlaces que cruzan
el límite quedan fuera del dominio; los gateways son aproximaciones interiores.
La whitelist de `zona1SpatialRouting.allowedLinks` limita el ruteo efectivo,
sin crear red exterior ni suplir relaciones OSM de giro no importadas.

El contrato [simz1-four-od-v2](../python/simz1_od_policy.py) añade clases explícitas
y conserva `od_type` por compatibilidad con artefactos anteriores:

| `od_class` | Origen → destino | Condición |
|---|---|---|
| `INTERNAL_INTERNAL` | Interior → interior | Enlaces distintos alcanzables respetando movimientos habilitados. |
| `INTERNAL_EXTERNAL` | Interior → salida | Gateway dirigido de salida real, representado por su enlace interior. |
| `EXTERNAL_INTERNAL` | Entrada → interior | Gateway dirigido de entrada real, representado por su enlace interior. |
| `EXTERNAL_EXTERNAL_THROUGH` | Entrada → salida | Accesos con nodos distintos y paso obligatorio por un enlace interior no gateway. |

Para tránsito de paso se descarta un par si existe una ruta permitida hecha solo
de gateways. Es una selección conservadora que preserva el paso interior durante
reruteo sin crear waypoints, vías externas ni modificar la física. El grafo de
movimientos se precalcula por componentes y reutiliza accesibilidad; no se explora
toda la red de nuevo por cada persona.

`--od-mix` recibe JSON con las cuatro claves canónicas y pesos no negativos.
Alternativamente, `--od-shares` conserva el orden **EE, EI, IE, II**; no usar ambos.
El default `1,0,0,0` es tránsito de paso sintético; `1,1,1,1` es una mezcla de prueba
equiponderada, no un aforo municipal. El redondeo por restos mayores desempata en
orden **II, IE, EI, EE**, seguido de barajado con semilla: para N=10 produce 3/3/2/2;
para 100 y 1000, 25 y 250 por clase. N nunca disminuye por falta de pares o capacidad:
la preparación falla si no puede cumplir la demanda.

Requiere `full-day`, horizonte 00:00–24:00, un viaje por persona, drenaje cero y
link-to-link routing activo. No admite debug, perfil global `peaks`,
`corridor-policy` ni cadenas exteriores. `--od-hourly-profiles RUTA.json` permite
24 pesos por cada clase en un objeto `{"source":"synthetic","profiles":{...}}`.
Estos pesos se combinan con las ventanas de la categoría cuando hay catálogo;
no pasar simultáneamente `--temporal-profile` ni pesos horarios globales al catálogo.
La opción actual identifica los perfiles como sintéticos; no acredita mediciones.

La selección uniforme entre accesos factibles evita imponer el 70 % histórico a
Elena. Esa distribución debe medirse en cada población: uniformidad entre enlaces
no implica aforos uniformes entre avenidas. Se excluyen accesos sin permiso `car`,
capacidad, carriles o velocidad válidos. El presupuesto horario usa PCU del perfil
y recursos de cruce compartidos, con rechazo acotado; limita cohortes programadas.
**No predice la hora real de salida ni garantiza caudal dinámico sin congestión**:
QSim mantiene sus capacidades y colas. Un bloqueo de acceso no autoriza inflar capacidad.

`--od-osm` aporta la fuente comprobable de giros. El control previo rechaza la red
actual antes de publicar demanda OD. `spatial_demand` registra `od_contract`, mezcla,
conteos objetivo/realizados, `departures_by_class_hour`, probabilidades horarias,
política de paso, presupuesto de gateways y `restriction_preflight`. Las entradas
conservan OSM/polígono/perfiles y hashes; `simz1SpatialOD` indexa los viajes y se
reconcilia con `simz1Trips`. Esto documenta **demanda preparada**, no viajes cumplidos.

El dominio son enlaces completos interiores autorizados, no toda Guatemala.
Los accesos son proxies interiores de cruces reales; la observación no termina
exactamente en la intersección geométrica del polígono. `System_Entry` y `System_Exit`
proceden de `vehicle enters/leaves traffic`; `Observed_Duration_Seconds` mide su
diferencia. La salida programada puede preceder a la admisión y la llegada de la
actividad puede ser posterior al egreso. Sin egreso observado, la duración queda
desconocida. `door_to_door_seconds` permanece null: no se inventa tiempo exterior.
El replay conserva estos metadatos y solo dibuja geometría admitida por el dominio.

<a id="movimiento"></a>
## Reconstrucción de movimiento

[simz1_visual_motion.py](../python/simz1_visual_motion.py) construye `Motion_Plan`
con fases `[t0,t1,s0,v0,a]` y tiempo absoluto, independiente del FPS:

```text
Δt=t−t0; s(t)=s0+v0·Δt+0.5·a·Δt²; v(t)=max(0,v0+a·Δt)
```

| Perfil | Aceleración visual de referencia | Desaceleración visual de referencia |
|---|---:|---:|
| Tortuga | 1 m/s² | 1.5 m/s² |
| Normal | 1.5 m/s² | 2.5 m/s² |
| Liebre | 2 m/s² | 3.5 m/s² |

Estas tasas pertenecen al interpolador, no al motor QSim. El solucionador conserva distancias, intervalos y techos,
registra ajustes y usa respaldos explícitos cuando un intervalo no admite la solución. No desplaza timestamps
nativos para suavizarlo ni inventa llegada o movimiento donde falta evidencia. Un WAIT de salida/cabecera
puede respaldar parada; demora residual o señal roja sin esa evidencia no demuestra una posición física detenida.

Los límites del ajuste visual son `max_rate_multiplier=4.0` y `minimum_ramp_seconds=0.15`.
Desactivar rampas no desactiva WAIT. El techo procede del XML de vehículos efectivo, no del nombre del perfil,
y se conserva el límite más restrictivo del intervalo. Un respaldo puede combinar avance uniforme y parada
con discontinuidad declarada. Si distancia/tiempo/techo no admiten representación, se omite el marcador
y se conserva el registro con su causa. No se dibuja un vehículo a 10 km/h como si estuviera detenido.

Los extremos parciales usan `relativePosition` y distancia de eventos cuando están disponibles; una
inferencia se etiqueta. La ausencia de velocidad fuente no se convierte en pausa. WAIT nativo de cabecera
tiene precedencia sobre una observación duplicada de prioridad; una demora post-step sin posición conocida
no se convierte en una parada exacta. `effective_vehicles` identifica/hash el archivo de salida efectivo;
el respaldo antiguo `verified_input_vehicles_legacy` exige verificación explícita, no cualquier XML local.

<a id="colas"></a>
## Carriles visuales, colas y selección

[simz1_visual_lanes.js](../python/simz1_visual_lanes.js) usa offsets paralelos en un único plano métrico local.
No reduce el offset en extremos/vértices ni el ancho por longitud de enlace. Conserva las polilíneas
efectivas y une sus paralelas mediante intersecciones de rectas acotadas, sin ajustar arcos artificiales.
`native` exige pertenencia y mapa de terminal validados; identifica cola, no posición lateral medida.
`estimated` conserva la asignación entre subdivisiones compatibles de una misma vía; geometría ambigua conserva `centerline`.
Un par opuesto 1+1 conserva un carril por sentido y no se inventan rebases.

Los metadatos de [simz1_visual_lanes.py](../python/simz1_visual_lanes.py) usan `permlanes` efectivo
por enlace automovilístico; no suman las colas terminales y la cola compartida aguas arriba.
`osm_tags`, `missing_osm_tags` y `lane_import_source` conservan atributos y ausencias sin completar
datos por nombre u orientación. Solo se emparejan ejes inversos con los mismos nodos, origen,
geometría y atributos de puente/túnel/nivel compatibles; enlaces no `car` no intervienen.
Las calzadas separadas conservan sus propios ejes. Un cruce XY no crea nodos ni conectores y `layer`
no se convierte en una elevación inventada. Las terminales con giros distintos conservan sus índices
y `to_links`/`to_lanes` nativos; el visor no impone restricciones OSM ausentes en la corrida.

La continuidad exige `source_way`, nodos compartidos, sección/nivel compatibles, sucesor y predecesor
únicos y permisos efectivos. No se decide por nombres de calles ni por el cruce de dos líneas.
La caché derivada **v3** contiene ejes desplazados, calles y conectores únicamente en memoria; se
descarta al recargar y no escribe SQLite, manifiestos, geometrías nativas o `Motion_Plan`.
Si un offset o sus bordes invierten un tramo o se autointersectan, se conserva la curva del eje
original y se registra el caso; no se comprime el ancho para hacerlo caber. La comprobación incluye
la cadena completa de subdivisiones unidas, no solo cada enlace; un circuito cerrado real conserva
su unión de cierre. La compatibilidad de un tramo exige que sus extremos correspondan mejor en el
orden nativo que al revés: la tolerancia de 25 cm no autoriza invertir enlaces más cortos.

Los conectores son segmentos esquemáticos separados del movimiento de vehículos, únicamente para
destinos permitidos por la configuración efectiva. No agregan tiempos ni rutas al replay. Cuando
`toLink` no identifica el carril receptor, los niveles no son compatibles o el conector requeriría
retroceder, no se inventa una unión. Los giros OSM omitidos por la importación siguen siendo una
limitación de la corrida protegida. La API existente expone la caché y sus excepciones en
`window.simz1Continuous.getState().visualLanes.geometry`.

Los [comandos de integración](#revision-integracion) reúnen los fixtures y la comprobación manual
en 8793 sin regenerar el export. Cubren también cuatro accesos, giros prohibidos, desniveles,
tramos de 20 cm invertidos, auto-intersecciones entre subdivisiones y circuitos cerrados.

[simz1_visual_queues.js](../python/simz1_visual_queues.js) usa cuerpos 4.5×1.8 m,
gap predeterminado 2 m configurable 0..10 m, setback 2 m y liberación 2 s.
Formación/liberación se evalúan con tiempo absoluto y `smoothstep(u)=u²(3−2u)`,
con u limitado a `[0,1]`. Requiere WAIT compatible y fase estacionaria del plan;
el orden procede de entrada nativa validada o de entrada de enlace estimada.

El cuerpo mantiene 4.5×1.8 m, dos extremos rectos y opacidad constante: no se dobla, estrecha ni recorta
al cruzar un nodo. La orientación interpola el ángulo más corto (incluido 359°→0°), por distancia absoluta,
con el mismo resultado en pausa, seek, 1x y 120x. La pose lateral en una transición es estimada y se une
solo con eventos contiguos del mismo vehículo/viaje, nodo, nivel y movimiento permitido. Sin ese respaldo
no se interpola entre enlaces. La huella rígida puede abarcar ambos enlaces; no es una trayectoria nueva.
No se alteran las fases de aceleración/frenado, las esperas, los tiempos ni los colores de velocidad.

La fila inferida respeta el almacenamiento disponible. Si falta espacio, se conserva el centro del plan
interpolado, sin redistribuirlo a otro enlace, y se informa `storage_exceeded`. Las liberaciones simultáneas
pueden solaparse: se contabilizan sin borrar identidades ni encoger cuerpos. Un filtro espacial evalúa el
centro y enlace autorizados; no recorta la huella. La [selección](../python/simz1_vehicle_picking.js)
prioriza el área del cuerpo proyectado sobre la tolerancia de proximidad; los empates
se resuelven de forma estable. Conserva `vehicle_id`, `person_id` y viaje por separado.
El contorno celeste con halo sigue la pose rígida final del vehículo fijado por clic,
sin cambiar su centro, carril, orientación ni color de velocidad. Hover usa amarillo;
la ruta usa violeta. Seleccionar otro cuerpo retira el contorno anterior y cerrar
la tarjeta lo elimina sin detener el reloj. Una respuesta tardía no restaura otra selección.

Las [regresiones de foco](../python/test_simz1_vehicle_focus.cjs) comprueban identidad
exacta incluso cuando persona y vehículo difieren, dos cuerpos paralelos, giro,
espera, pausa, seek hacia atrás, ventanas y rotación. El foco usa la geometría final
ya calculada; conserva capas estáticas y no inicia consultas SQLite periódicas.
Si el cuerpo no está presente, el ID seleccionado persiste sin marcar otro vehículo.
Esto acredita coincidencia en fixtures, pendiente de observación GPU con la corrida
real. Un carril visual incompatible debe diagnosticarse con eventos/carril/pose;
el resaltado no lo corrige trasladándolo al eje de la calle.

La tarjeta conserva sus seis campos: nombre, tipo de agente, velocidad actual,
velocidad máxima, tiempo transcurrido y duración total estimada. Los datos ausentes
permanecen desconocidos; para OD externo una estimación del tramo observado no es
la duración total real fuera del sistema. No se añade otra tarjeta paralela.

`/api/window` añade `context_segments` (como máximo un predecesor y un sucesor por viaje) y
`context_lane_events`, sin cambiar `segments` ni `lane_replay.events`. Son lecturas por índices del SQLite;
no reconstruyen `Motion_Plan` ni escriben archivos. El contexto no crea agentes activos. Durante carga o
error se conserva el último fotograma validado y su hora, con estado de espera visible.

`window.simz1Continuous.diagnoseVehicle('z1_19635')` devuelve corrida, persona, vehículo, viaje, instante,
enlaces anterior/actual/siguiente, carril, posición dibujada, orientación y motivo. Distingue
`window_not_loaded`, `unknown_interval`, `overlapping_intervals`, `motion_unavailable`, `geometry_unavailable`
y `spatial_filter`; además indica enlace corto, almacenamiento y solapamiento de cola. Una posición
desconocida permanece `null`. La consulta de representación corresponde al fotograma actual.

Evidencia de lectura limitada del SQLite protegido, corrida `simz1-3dd8683a7d5e44c0944587feff4fe0c8`:

| Persona = vehículo / viaje | Instante | Anterior → actual → siguiente | Carril registrado | Posición del eje / causa identificada en el código anterior |
|---|---:|---|---|---|
| `z1_19635` / `z1_19635:trip:0001` | 8 s | `osm_34979717_4_forward` → `osm_34979717_5_forward` → `osm_34979717_6_forward` | `osm_34979717_5_forward.original` | `[-90.52041720000418,14.626274400001307]`; enlace de 0.813 m, cuerpo con opacidad cero al entrar. |
| `z1_15887` / `z1_15887:trip:0001` | 15.9 s | `osm_1305763181_1_backward` → `osm_1305763181_0_backward` → `osm_1057416056_1_forward` | `osm_1305763181_0_backward.lane.0` | `[-90.52158180000193,14.625537800001165]`; WAIT 11..16 s, la liberación visual acercaba el cuerpo al extremo y `boundary_transition` lo omitía. |
| `z1_15887` / `z1_15887:trip:0001` | 120 s | `osm_1521208741_3_forward` → `osm_559513165_0_forward` → `osm_559513165_1_forward` | `osm_559513165_0_forward.lane.0` | Eje interpolado `[-90.518585228473,14.628855010546499]`; intervalo `[117,121)` con fases válidas: no hay hueco de datos en la frontera de ventana. |

Estos casos se identificaron leyendo registros y código; las pruebas y la comprobación visual quedan
para el usuario. Para reproducir: pausar, `window.simz1Continuous.seek(8)` y consultar el primer vehículo;
repetir con 15.9/120 y el segundo. Los cuerpos de tamaño constante son una representación nominal,
no dimensiones medidas; la pertenencia a cola no proporciona una trayectoria lateral observada.

La vida del viaje incluye departure y excluye arrival/abort. Un censurado conserva su última observación
individual inclusiva, pero el horizonte sigue siendo exclusivo. Un hueco entre intervalos del mismo viaje
se muestra desconocido; no se une artificialmente. La selección puede conservarse internamente al buscar
otra hora y reaparecer al volver a un instante válido. Historial, futuro, origen/destino y panel se limpian
juntos cuando corresponde; el hover no se mantiene por una petición tardía. El futuro dibujado es geometría
ya registrada en el replay, no una predicción del motor. La caché de detalle está acotada a un viaje.

<a id="visor"></a>
## Visor, API y SQLite

El visor continuo presenta una sola página de 00:00:00 a 24:00:00, con ventanas de carga internas, pausa,
1x/120x, seek, cámara y selección. El reloj 12/24 h no abre una hora 25. Colores: verde >40, amarillo 15..40,
rojo <15 km/h y blanco ≤0.0001 km/h; representan velocidad visual estimada. Desconocido no es cero.

**HUD simplificado, tarea 3 (2026-10-29; regresiones no ejecutadas).** La esquina
inferior derecha contiene únicamente `Vehículos particulares: N · Transporte público: B`.
Con política temporal, N excluye calentamiento y contexto posterior y usa la
cohorte principal; sin ella, cuenta particulares configurados. No se convierte
`planned_persons` por un cambio de etiqueta: `checked_hud` exige el reporte
`population_generation.verified`, cuyo verificador XML comprueba IDs únicos,
igualdad de conjuntos de personas/vehículos y asignación `PersonVehicles` exacta
uno a uno. Ese reporte se genera antes de añadir carga. Los conteos de cohorte
también deben coincidir con el reporte verificado. Si falta esa evidencia,
N es `—`; si es contradictoria, se muestra error y se limpian los totales.

B procede de `fleet_vehicle_ids` únicos y su total configurado validado. Un bus
reutilizado entre expediciones/fechas se cuenta una vez. Sin IDs suficientes se
muestra `—`; una desactivación explícita admite cero. No se usan buses visibles,
expediciones, camiones ni vecinos de contexto para completar cifras ausentes.
La información de corrida/iteración, semillas, fecha, fuentes, contexto temporal,
Transmetro/TuBus, carga y expediciones está en Ayuda. Reloj, Visibles, controles,
cámara, rutas y selección conservan sus funciones. Los errores/reintentos de
metadatos quedan fuera de Ayuda, que normalmente está cerrada.

La tarjeta conserva sus seis campos. Su nombre visible prioriza `vehicle` y,
si falta, usa la identidad de persona ya disponible, siempre con etiqueta
`Vehículo`; sin ninguna identidad muestra `Vehículo —`. No cambia `person_id`,
`vehicle_id`, `trip_id`, XML, SQLite ni las claves de conteos históricos. El
endpoint existente conserva su esquema y campos; añade metadatos opcionales
de presentación `vehicle_summary` y `run_details`. Un cliente nuevo ante una
respuesta histórica sin esa evidencia muestra `—`. La solicitud sigue siendo
una por carga/reintento, con invalidación inmediata y rechazo de respuestas
obsoletas por identidad. No se consulta ni reconstruye nada adicional por frame.

Para actualizar únicamente el cliente ligero, el operador debe reiniciar
manualmente el servidor continuo con **la misma carpeta, identidad, iteración y
puerto**, y después recargar la página sin caché. `handler_for` ensambla las fuentes
JS/HTML actuales al iniciar y sirve el HTML desde memoria; recargar una pestaña
contra un proceso anterior no cambia ese código. El manifiesto/SQLite existente
se conserva en lectura. No ejecutar generación, exportación SQLite ni preparación
de demanda para este cambio. `refresh_application(directory)` solo actualiza el
shell guardado y su tamaño de aplicación; no actualiza un servidor ya iniciado
y no es necesario para la ruta HTTP que ensambla el cliente. En esta tarea no se
reinició ningún proceso ni se abrió navegador. Comandos completos: tarea 4.

Regresiones preparadas en `test_simz1_continuous_hud.py`/`.cjs`,
`test_simz1_continuous_replay.cjs`, `test_simz1_continuous_bootstrap.cjs`,
`test_simz1_midnight_replay.cjs`, `test_simz1_vehicle_card.cjs` y
`test_visualizador_z1_controls.cjs`: procedencia, ausencia, cero, flota reutilizada,
cohorte/contexto, cambio de identidad, errores, cámara, selección y tarjeta.
Pendientes su ejecución y la inspección visual posterior del cliente actualizado.

El [servidor](../python/serve_simz1_continuous.py) sirve en loopback y abre
SQLite con `mode=ro` y `PRAGMA query_only=ON`. El [launcher de compatibilidad](../open_simz1_continuous.ps1)
delega al [launcher genérico](../scripts/replay/start_replay.ps1), sin fijar 100k.
Los comandos de selección/apertura están en el [README principal](../README.md).
Se requieren WebGL, API HTTP y deck.gl versionado; `file://` no aporta la API.

| Endpoint | Contrato |
|---|---|
| `/api/config` | Configuración, dominio, ventana e identidad del continuo. |
| `/api/window` | Ventana por `index`, con segmentos y metadata de viajes. |
| `/api/journey` | Viaje por `key` SHA-256 de 64 caracteres hexadecimales minúsculos. |
| `/api/hud` | Conteos fuente; exige `start_seconds`/`end_seconds` iguales a la ventana visible completa. |
| `/api/metrics` | Caché y consultas del servicio, no FPS del navegador. |

Tras config, las consultas validan `run_id`, `iteration` y `run_manifest_sha256`. Se conservan manifiestos,
artefactos nativos, `webgl/export-manifest.json`, `replay.sqlite`, `blocks/*.html` y los productos continuos:
config, temporales y manifiesto. El continuo aún valida dependencias del export paginado aunque no navegue
por páginas; no eliminarlas por ese motivo.

El HUD obtiene población y viajes del manifiesto nativo validado y contrasta conteos derivados con su procedencia.
El panel inferior muestra únicamente `Personas generadas: N` (sin separadores; `—` si no hay dato validado).
Viajes, identidad, horizontes, errores y diagnósticos de cola permanecen en «Ayuda» y las APIs.
«Ocultar barra» conserva un botón «Mostrar barra», sin una capa transparente sobre el mapa; la preferencia
se guarda en `sessionStorage`. La población ocupa su overlay independiente; la tarjeta del vehículo flota
sin reservar una celda ni dejar un panel vacío.
Sus totales fuente no cambian al mover el reloj. Activos nativos instantáneos permanecen `null`/N/D sin una serie
que los respalde; visibles cuenta únicamente marcadores. Una fuente de 25 h conserva métricas etiquetadas con
ese horizonte aunque la vista termine a 86400. Censurar la vista diaria no reescribe eventos, SQLite o manifiestos
ni crea una llegada a medianoche. Una fuente parcial tampoco acredita datos de las horas ausentes.

La tarjeta contextual aparece en hover y se fija con clic. X, Escape o clic simple en fondo cierran la
selección. Un agente fijado tiene prioridad sobre el hover; conserva identidad en pausa, buffering, seek,
zoom, rotación, cambio de ventana y tras la llegada. En hover se limita a la pantalla; fijada permanece
en la esquina superior derecha del mapa. La telemetría extensa seguía dentro de «Ayuda»: ese traslado,
junto con ocultarla cuando el viaje dejaba de ser visible, había eliminado la tarjeta flotante.

Sus únicos seis campos se obtienen así:

| Campo | Fuente y criterio |
|---|---|
| Nombre | `Agent_ID` / `Trip.Person_ID`; si faltan, `vehicle`. Prefijo legible sin inventar identidad. |
| Tipo | `Agent_Type` efectivo, `Vehicle_Type` canónico o `Profile` histórico Normal/Liebre/Tortuga. Sin respaldo: `No registrado`; nunca por ID, velocidad o porcentajes. |
| Velocidad actual | `motionAt(segmento, reloj)` evalúa `Motion_Plan` válido; respaldo de movimiento registrado del segmento. No usa desplazamientos de dibujo. Espera respaldada: 0; datos ausentes: `—`; movimiento menor de 0,05 km/h: `<0.1 km/h`. |
| Velocidad máxima | `Motion_Provenance.vehicle_limit_mps × 3.6`, procedente del límite vehicular exportado; ausente: `—`. No usa límite de calle, `cap_mps` ni máximo observado `Max_Speed_kmh`. |
| Tiempo transcurrido | Reloj simulado menos `Trip.Departure`; antes de la salida o sin salida registrada: `—`. Se limita por llegada/aborto ya alcanzado o evidencia/corte individual si censurado. Minutos completos: `15 min simulados`, `1 h 20 min simulados`. |
| Duración total estimada | `—`: los exports actuales no registran una predicción previa al viaje. No se usa `Arrival - Departure` ni la trayectoria futura grabada. |

La tarjeta reutiliza picking y registros en memoria. Hover actualiza solo DOM; clic solicita `/api/journey`
con identidad de corrida/viaje/vehículo, cancelación y protección contra respuestas obsoletas. Repetir clic
en el mismo agente, reproducir o hacer seek no repite la consulta del viaje seleccionado. No añade índices,
consultas por frame ni cambios a Motion_Plan, física, trayectorias o resultados históricos.

Regresiones sin servidor, navegador ni simulación:

```powershell
$simz1CardTests = @('simz1_vehicle_card', 'simz1_continuous_replay', 'visualizador_z1_selection',
  'visualizador_z1_controls', 'visualizador_z1_paged', 'visualizador_z1_motion',
  'simz1_vehicle_picking', 'simz1_render_performance', 'simz1_agent_metadata')
foreach ($testName in $simz1CardTests) {
  node ".\python\test_$testName.cjs"
  if ($LASTEXITCODE -ne 0) { throw "Falló JavaScript: $testName" }
}
```

<a id="abrir-229629"></a>

Para servir el código actual sobre el export existente de 229629 personas, detener primero el servidor
anterior con Ctrl+C y ejecutar desde la raíz (no regenera bloques, SQLite ni Motion_Plan):

```powershell
.\.venv\Scripts\python.exe -B .\python\serve_simz1_continuous.py --directory .\scenarios\zona1\montecarlo\run-night-20261017-012651-6a8d9ac3\webgl-continuo --port 8793
```

El servidor ensambla la aplicación actual en memoria. En **otra consola PowerShell**, abrir el navegador
manualmente con el siguiente comando, o recargar esa dirección si ya está abierta:

```powershell
Start-Process 'http://localhost:8793/index.html'
```

Son instrucciones para ejecución manual; no se ejecutaron al documentarlas. Las pruebas DOM verifican el
contrato, pero no acreditan render GPU ni gestos en un navegador real.

La cámara usa `MapController` de deck.gl **9.1.14** y `viewState` controlado en la misma instancia de `Deck`.
DESPLAZAR usa cursor de mano y arrastre izquierdo; ROTAR usa cursor de cruz y arrastre para giro/inclinación
(0–60°). Doble clic solo en fondo activa ROTAR, sin zoom; clic simple en fondo o Escape vuelve a DESPLAZAR
sin restablecer orientación. La rueda conserva zoom en ambos modos. Los reconocedores de deck.gl resuelven
clic/doble clic sin listeners DOM paralelos; el arrastre no selecciona vehículos. Seek, ventanas, pausa,
reproducción y ocultación del HUD no escriben el estado de cámara. Se consulta en `getState().camera`.

El [loader](../python/simz1_continuous_loader.js) limita a tres ventanas y dos peticiones. Su fallback es 64 MiB
contados como JSON UTF-8, pero acepta el presupuesto persistido: el exportador escribe 128 MiB.
Consultar `cacheByteBudget` efectivo; una ventana activa sobredimensionada se declara, no se recorta.
El backend usa hasta ocho entradas/64 MiB gzip y dos consultas simultáneas. Estos presupuestos no miden heap
JavaScript, working set, memoria SQLite o GPU.

El cliente prepara primero la ventana solicitada y precarga la siguiente solo
durante la reproducción. Estando pausado no inicia nuevas consultas especulativas;
las ya iniciadas pueden terminar. Esto evita que la precarga compita desde el
principio con una búsqueda del usuario, pero no promete una latencia fija.
Los errores y reintentos siguen visibles. La [verificación de esta política](../evidence/documentation/simz1-20261027/prefetch-policy-verification.md)
incluye el cruce de medianoche, pausa/reanudación e identidad de ventanas.

La fuente se construye recorriendo eventos una vez, guardando segmentos comprimidos y finalizando el viaje
antes de cortarlo en ventanas; así las rampas no se recalculan con otra forma al cambiar de bloque.
Mapas se cargan una vez; señales/incidentes aún se extraen de los HTML fuente. No mover únicamente el
directorio continuo a otra máquina: manifiestos y rutas de procedencia pueden ser absolutos. Para una
instalación nueva, regenerar desde su propia corrida como indica el inicio rápido.

La API no ofrece SQL arbitrario ni descarga libre de SQLite. Una respuesta 503 usa `Retry-After` y hasta
siete reintentos cancelables; una petición obsoleta no modifica la selección. Durante espera de datos se
conserva el último frame y no se añade al reloj todo el tiempo de pared transcurrido. Los presupuestos de
caché no autorizan muestreo de agentes ni truncamiento silencioso de una ventana grande.

<a id="revision-integracion"></a>
### Verificación de integración sobre la corrida protegida

Revisión estática: red efectiva y carriles → metadatos con identidad → paralelas en metros →
`markerAt`/`Motion_Plan` → colas longitudinales/cuerpo rígido → filtros espaciales → capa y selección.
El contexto temporal aporta vecinos, no agentes activos; cámara y HUD conservan sus estados independientes.
No se reescribieron estos módulos en esta revisión. Se añadió únicamente una regresión del handler real,
sin socket, para servir los siete módulos actuales una sola vez conservando el HTML histórico, manifiestos y SQLite.

| Cobertura existente | Fixtures principales en `python/` |
|---|---|
| Rectas, curvas, uno/dos carriles y sentidos, calzadas, cruces y desniveles | `test_simz1_road_semantics.py`, `test_simz1_visual_lanes.py`, `test_simz1_parallel_geometry.cjs` |
| Motion_Plan/eventos, giro, enlace corto, cuerpo rígido, datos insuficientes | `test_simz1_visual_motion_integration.py`, `test_simz1_rigid_vehicles.cjs`, `test_visualizador_z1_motion.cjs` |
| Colas, desbordes, permanencia y selección de marcadores | `test_simz1_visual_queues.cjs`, `test_simz1_vehicle_picking.cjs`, `test_visualizador_z1_selection.cjs` |
| Ventanas, desapariciones, contexto, seek, 1x/120x, identidad y recursos actuales | `test_simz1_transition_context.py`, `test_simz1_continuous_replay.py` y `.cjs` |
| Población dinámica/ausente, cambio de corrida, HUD y cámara | `test_simz1_continuous_hud.py` y `.cjs`, `test_simz1_continuous_replay.cjs` |

**Estado de comprobación:** los tests no se ejecutaron en esta revisión. La lectura comprobó 30 hashes
registrados (27 artefactos nativos, manifiesto de corrida, export fuente y config) y 301 hashes/identidades
temporales. Manifiestos, SQLite y 6183 enlaces de geometría derivada corresponden a
`simz1-3dd8683a7d5e44c0944587feff4fe0c8`, iteración 0; HUD: 100000.
SHA-256 del manifiesto: `a1a64936c5fe8f9115de85c850bca04953a5fb026c12c1d6986c18a8528ee03d`.
SQLite conserva tamaño/mtime declarados e identidad interna, pero no hay SHA-256 histórico de todo SQLite
en estos manifiestos; esto no certifica todos sus bytes ni cada Motion_Plan. No se modificó ninguno.
Los scripts son comunes a las corridas: se ensambla código actual y se valida la identidad de sus datos,
no se atribuye a los scripts un `run_id` propio.

Desde la raíz, usar el Python del proyecto (el Python global revisado no tiene `pyproj`):

```powershell
$simz1Python = (Resolve-Path '.\.venv\Scripts\python.exe').Path
$simz1Protected = (Resolve-Path '.\scenarios\zona1\montecarlo\run-052734f90d154b23bb8899cd0bbc3ef4').Path
$simz1Replay = Join-Path $simz1Protected 'webgl-continuo'
$simz1PythonTests = @(
  'road_semantics', 'visual_lanes', 'visual_motion_integration', 'transition_context',
  'continuous_replay', 'continuous_hud', 'daily_window', 'spatial_replay', 'lane_replay'
)
foreach ($testName in $simz1PythonTests) {
  & $simz1Python -B -m unittest discover -s .\python -p "test_simz1_$testName.py" -v
  if ($LASTEXITCODE -ne 0) { throw "Falló Python: $testName" }
}
$simz1JsTests = @(
  'simz1_visual_lanes', 'simz1_parallel_geometry', 'simz1_rigid_vehicles', 'simz1_visual_queues',
  'visualizador_z1_motion', 'simz1_vehicle_picking', 'simz1_spatial_view',
  'simz1_continuous_hud', 'simz1_continuous_replay', 'visualizador_z1_selection',
  'visualizador_z1_controls', 'visualizador_z1_paged'
)
foreach ($testName in $simz1JsTests) {
  node ".\python\test_$testName.cjs"
  if ($LASTEXITCODE -ne 0) { throw "Falló JavaScript: $testName" }
}
```

Son fixtures pequeños, no simulaciones ni exportaciones de la corrida protegida. La suite Python del
continuo incluye pruebas HTTP con servidores efímeros locales; solo se ejecutan cuando el usuario lanza la suite.
Los fixtures JS no abren navegador ni GPU y no acreditan por sí solos el render o los gestos reales de deck.gl.

Verificar recursos e identidad sin servidor, recibos ni escrituras (lee hashes; no recorre eventos ni viajes):

```powershell
@'
import gzip, json, sys
from pathlib import Path
sys.path.insert(0, 'python')
from simz1_continuous_replay import ContinuousReplay, application_html, digest, identity
from simz1_run import checked_path
r = ContinuousReplay(sys.argv[1])
assert r.identity['run_id'] == 'simz1-3dd8683a7d5e44c0944587feff4fe0c8'
assert r.identity['run_manifest_sha256'] == 'a1a64936c5fe8f9115de85c850bca04953a5fb026c12c1d6986c18a8528ee03d'
def verify_native(value):
    if isinstance(value, dict):
        if 'path' in value and 'sha256' in value:
            checked_path(Path(r.source_manifest['run_directory']), value)
        else:
            for item in value.values(): verify_native(item)
    elif isinstance(value, list):
        for item in value: verify_native(item)
verify_native(r.native_run)
for index, entry in enumerate(r.manifest['temporal_files']):
    path = r.root / 'temporal' / entry['file']
    assert digest(path) == entry['sha256'], path
    payload = json.loads(gzip.decompress(path.read_bytes()))
    assert identity(payload) == r.identity and payload['index'] == index, path
connection = r.connection()
connection.close()
geometry = r.config['visual_lanes']
assert geometry['available'] and geometry['identity'] == r.identity, geometry.get('reason')
html = application_html()
for name in ['CONTROLS', 'LOADER', 'HUD', 'VISUAL_LANES', 'VISUAL_QUEUES', 'VEHICLE_PICKING', 'SPATIAL_VIEW']:
    assert '__' + name + '__' not in html
query = {key: [str(value)] for key, value in r.identity.items()}
query.update(start_seconds=['0'], end_seconds=['86400'])
assert r.hud(query)['counts']['persons_generated'] == 100000
print('OK: identidad, hashes registrados, recursos actuales y HUD; SQLite abierto en lectura.')
'@ | & $simz1Python -B - $simz1Replay
if ($LASTEXITCODE -ne 0) { throw 'Falló la verificación de recursos.' }
```

**Cachés:** no hay preparación pendiente. La geometría v3 y las cachés HTTP/ventanas se crean en memoria
al usar el visor. No llamar `refresh_application`, regenerar exports ni reconstruir Motion_Plan para esta revisión.

Levantar manualmente, después de las verificaciones, sin apertura automática del navegador:

```powershell
& $simz1Python -B .\python\serve_simz1_continuous.py --directory $simz1Replay --port 8793
```

Abrir manualmente `http://127.0.0.1:8793/index.html` y recargar sin caché. Ctrl+C detiene ese servidor.
La validación visual pendiente es:

| Caso | Referencia leída de la red efectiva / acción | Resultado esperado, por confirmar |
|---|---|---|
| Avenida | 6a Avenida, `osm_1057486080_1_forward`, centro aprox. lon −90.515929, lat 14.627261 | Tres carriles dirigidos, paralelos y sin apertura/cierre en cada nodo. |
| Calle | 3a Calle, `osm_1051440043_1_forward`, centro aprox. lon −90.511513, lat 14.645565 | Un carril dirigido; no duplicarlo como doble vía. |
| Transición | `z1_15887`, 15.9 s y 120 s; `z1_19635`, 8 s, referencias anteriores | Cuerpo rígido; consultar motivos si no hay marcador, sin rellenar datos desconocidos. |
| Replay | Pausa, seek atrás/adelante, 1x/120x, cruce de ventana | Sin perder selección; la espera de carga conserva el último frame. |
| Cámara/HUD | Arrastres, rueda, doble clic en fondo, clic simple, Escape, ocultar/mostrar; ancho 360 px | Orientación conservada, sin zoom por doble clic, población 100000 y paneles sin solaparse. |

Para centrar esas referencias sin buscar por nombre, en la **consola del navegador** (solo cámara):

```javascript
const replay = window.simz1Continuous;
const centrar = (longitude, latitude) => replay.deck.props.onViewStateChange({
  viewState: {...replay.getState().camera.viewState, longitude, latitude, zoom: 19}
});
centrar(-90.515929, 14.627261); // Avenida; después centrar(-90.511513, 14.645565)
replay.pause(); replay.seek(15.9); // Esperar a getState().buffering === false
// Para observar este vehículo, centrar(-90.521582, 14.625538).
replay.diagnoseVehicle('z1_15887'); // Repetir a 120 s, cerca de (-90.518585, 14.628855).
replay.getState().visualLanes.geometry; // version: 3, persistence: "memory_only"
```

Las limitaciones permanecen: geometría/anchos nominales cuando faltan atributos, pose y espaciado estimados,
restricciones OSM ausentes en la corrida, intervalos genuinamente desconocidos y solapamientos de liberación.
Las coordenadas anteriores sirven para inspeccionar el modelo, no acreditan cartografía GIS verificada.
No se declara resuelto un defecto visual hasta completar estas comprobaciones.

<a id="metricas"></a>
## Métricas, distribuciones y censura

La unidad de `analysis/it.N/trips.csv.gz` es `departure_arrival_leg`, identificada por
`(run_id,iteration,person_id,trip_index)`. Duración exige llegada observada; censura y aborto temprano mantienen
llegada/duración vacías. Una salida ausente no genera un viaje observado ficticio. `--mode car` calcula distribuciones
de etapas completas car y declara excluidos; `--mode all` mezcla modos explícitamente.
[simz1_trip_distributions.py](../python/simz1_trip_distributions.py) separa
duraciones de puntajes y conserva perfiles, cohortes horarias y percentiles.

| Magnitud | Interpretación |
|---|---|
| Personas / viajes planificados | N y N·K de artefactos, no marcadores. |
| Completados / pendientes / sin iniciar | Estados distintos al corte declarado. |
| Activos nativos / visibles | Presencia QSim / representación dibujable. |
| WAIT | Intentos; no personas ni segundos sumables de demora. |
| Ocupación de enlace | Vehículos y vehículo-segundos; no storage de carril en PCU. |
| Caudal de corredor | Cruces del corte; no suma repetida de enlaces seriales. |
| Forzados/retiros | Intervenciones del motor; no capacidad vial servida. |
| N/D | Dato ausente; no cero. |

La capacidad nominal `capacity·3600/capperiod·flowCapacityFactor` ya incluye carriles. No multiplicarla otra vez por n.
Comparar demanda/capacidad supone PCU y no incorpora automáticamente verde, conflictos o colas aguas abajo.
Los cuantiles de duración excluyen censurados y deben declarar ese sesgo.

[TripTableExporter](../src/main/java/gt/edu/uvg/sim/zona1/TripTableExporter.java) publica por iteración
la tabla gzip y su resumen de forma atómica; `.tmp`
no es salida válida. Los eventos XML pueden seguir un intervalo de escritura de diez iteraciones,
mientras las tablas se generan en cada iteración. `SIMZ1_RUN_ID` enlaza el proceso al manifiesto;
una ejecución Java directa sin gestión de corrida no publica automáticamente `latest-successful`.
El respaldo antiguo por eventos exige la misma iteración e identidad verificadas. No sustituir
esta tabla por legs nativos de otro formato ni deducir llegadas de scores.

El ordinal de etapa incluye todos los modos. La duración departure→arrival incluye la espera para entrar
al tráfico. Los pares de aborto duplicados se unifican; etapas solapadas o modos incompatibles fallan.
La evolución individual se interrumpe ante resultados incompletos: OD y modo pueden cambiar entre
iteraciones. La ECDF exacta requiere memoria proporcional a viajes completos; los percentiles usan
interpolación lineal (p05/p25/p50/p75/p95): para datos ordenados, `i=(n−1)q` y se interpola entre
`floor(i)` y `ceil(i)`. La ECDF es `F_n(t)=#{duraciones≤t}/n`; la caja usa p25..p75 y los bigotes p05..p95.
CSV se escribe por streaming. Excel es opcional y su límite predeterminado de 100000 filas rechaza el
exceso, sin truncar silenciosamente. La fracción completados/observados usa el modo seleccionado;
sin salidas su denominador produce N/D, no cero ni el tamaño de población.

<a id="analisis-automatico"></a>
### Análisis automático por corrida y reintentos — 22/10/2026

El flujo oficial de [ejecutar_simz1.py](../python/ejecutar_simz1.py) espera la
terminación del proceso MATSim, valida sus resultados y publica
`status=completed`, `validation.status=valid` y `latest-successful.json`.
Solo después ejecuta el análisis por perfiles para **todas las iteraciones
completadas**, mediante [simz1_analysis.py](../python/simz1_analysis.py), el mismo
servicio que usa [generar_graficas_z1.py](../python/generar_graficas_z1.py). Una corrida fallida
no dispara este postproceso. `--iterations 1` produce `it.0`;
`--iterations 2` produce `it.0` e `it.1`, con fuentes y conteos independientes.

Se reutilizan [procesar_eventos_z1.py](../python/procesar_eventos_z1.py),
[simz1_trip_table.py](../python/simz1_trip_table.py) y
[simz1_trip_distributions.py](../python/simz1_trip_distributions.py).
La fuente preferida es la tabla canónica compacta identificada y validada;
el respaldo por eventos se usa cuando corresponde a esa misma corrida e
iteración. El CSV gzip se lee por streaming. No se recorren segmentos de
Motion_Plan para medir duraciones, ni se construyen WebGL, SQLite visual,
96 HTML o imágenes por persona.

La métrica es `(PersonArrivalEvent.time − PersonDepartureEvent.time) / 60`,
en minutos simulados y únicamente con llegada válida. Las 24 cohortes usan
la hora de **salida**, aun si el viaje termina en otra hora. Las medias de
familia y globales se obtienen de los viajes individuales: no son promedios
simples de medias de subtipos. Los CSV incluyen media, mediana, P95,
completados, excluidos y estados de completitud; las tasas usan su denominador
declarado. Sin observaciones se registra «sin datos» y las duraciones excluidas
no se convierten en cero. `--min-sample 30` marca muestras pequeñas; es un
umbral descriptivo, no una prueba de significancia.

`person_id`, `vehicle_id`, `trip_index`, perfil, familia y modo MATSim se
conservan como identidades distintas. Normal, Tortuga y Liebre corresponden
a Carro, Carro Tortuga y Carro liebre. Moto, Moto tortuga y Moto Liebre se
identifican por el tipo efectivo de las entradas; la rapidez observada no
clasifica motocicletas. Se incluyen los modos registrados de cada perfil,
sin imponer `car` a todos. Una corrida histórica sin motos conserva la figura
de motos con la ausencia explícita. Los viajes de pesados y otras categorías
observadas se reportan en CSV separados. La contabilidad auditada de flota
pública fija se conserva en `resumen_perfiles.json/provenance`; cuando el
compacto nativo excluye sus conductores internos, no se inventan sus viajes
en el CSV. Ninguno de esos conductores incrementa la población Monte Carlo.
Esto no habilita capacidades de flota o pesados pendientes en el lanzador.

Cada corrida escribe exclusivamente sus productos analíticos bajo
`analysis/it.N/`; sus entradas, eventos, manifiesto de simulación y resultados
científicos se mantienen intactos. Las salidas principales son:

| Ruta relativa a `analysis/it.N/` | Contenido |
|---|---|
| `trips.csv.gz` y su procedencia | Viajes canónicos, identificados por corrida e iteración. |
| `analysis-status.json` | Estado del análisis y diagnóstico del último intento registrado. |
| `analysis-manifest.json` | Identidad, fecha UTC, fuentes, parámetros, código y hashes de productos verificados. |
| `graficas_perfiles/carros_por_hora.png` | Tres perfiles de carros, 24 horas de salida. |
| `graficas_perfiles/motos_por_hora.png` | Tres perfiles de motos, con ausencias explícitas. |
| `graficas_perfiles/comparacion_familias_por_hora.png` | Medias por hora ponderadas por los viajes de cada familia. |
| `graficas_perfiles/comparacion_global_perfiles.png` | Media de jornada y N completos por perfil. |
| `graficas_perfiles/completitud_por_hora.png` | Completados, abortados y censurados por perfil y hora. |
| `graficas_perfiles/duration_distribution.png` | Histograma de duraciones individuales, mediana, P95 y ECDF. |
| `graficas_perfiles/estadisticas_por_perfil_hora.csv` | Estadísticas, tamaños de muestra, exclusiones y tasas por perfil/hora. |
| `graficas_perfiles/estadisticas_por_familia_hora.csv`, `estadisticas_globales.csv` | Agregaciones desde viajes individuales. |
| `graficas_perfiles/categorias_separadas.csv`, `categorias_separadas_por_hora.csv` | Viajes observados de pesados y categorías fuera de las seis comparadas. |
| `graficas_perfiles/resumen_perfiles.json` | Métrica, filtros, identidad, población y estadísticas con procedencia. |

Las figuras incluyen `run_id`, iteración y metadatos de métrica/filtros.
El estado analítico es independiente del cierre MATSim: si únicamente falla
el análisis, se registra `analysis_failed` y el CLI devuelve **2**; la corrida
sigue `completed/valid` y `latest-successful` conserva su identidad.
Si el fallo ocurre antes de seleccionar una iteración, el diagnóstico de
respaldo queda en `analysis/analysis-status.json`. Un fallo de MATSim sigue
siendo un fallo de simulación, no se reclasifica como analítico.

Un bloqueo por iteración evita análisis simultáneos. Se comprueba espacio
libre y se preparan productos temporales antes de publicar resultados
completos. Si falta espacio, se informa la ruta y el problema; no se reemplazan
resultados científicos ni se publican figuras parciales como válidas.
El mismo comando permite reintentar tras interrupción. Si coinciden fuentes,
opciones, código y hashes de las salidas, se reutiliza el resultado validado.
Cuando cambia el análisis, se prepara una nueva revisión y la anterior se
conserva en `analysis/it.N/.rev/`, con recuperación de una
publicación interrumpida. En Windows, el análisis emplea carpetas `analysis/it.N/.stg/` para preparación, `.rev/` para revisiones y `.abn/` para respaldos abandonados, con identificadores cortos y verificación preventiva de longitud de rutas; el cambio no borra revisiones históricas con los nombres anteriores. También se puede usar otra raíz `--analysis-dir`
para mantener la revisión fuera de la corrida. Si el volumen ya no permite
escribir ni el estado del fallo, el diagnóstico se conserva en la salida de
error del comando.

Desde PowerShell en la raíz del proyecto, analizar una corrida existente o
reintentar después de `analysis_failed`; elegir la carpeta que contiene
`run-manifest.json`:

```powershell
$simz1Python = (Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe').Path
$simz1Run = (Resolve-Path -LiteralPath (Read-Host 'Carpeta de la corrida SimZ1 completed/valid')).Path
& $simz1Python -B .\python\generar_graficas_z1.py --run-dir $simz1Run --profiles-only --all-iterations
if ($LASTEXITCODE -ne 0) { throw "Revisar analysis-status.json bajo $simz1Run\analysis; MATSim conserva su estado." }
```

Para una sola iteración usar `--iteration 0` en lugar de `--all-iterations`.
Para una revisión externa que no escriba en una corrida histórica, conservar
`--run-dir` y añadir `--analysis-dir .\runtime\simz1-revision\analysis`:
se crean allí las mismas carpetas `it.N`, estados y manifiestos. Repetir
exactamente el comando reutiliza resultados compatibles. El parámetro
`--all-iterations` se limita al entregable por perfiles; no genera seguimiento
individual, puntajes ni productos opcionales antiguos.

Abrir las imágenes de una iteración en Windows, sin servidor ni navegador:

```powershell
$simz1Iteration = 0
$simz1Images = Join-Path $simz1Run "analysis\it.$simz1Iteration\graficas_perfiles"
Get-ChildItem -LiteralPath $simz1Images -File -Filter '*.png' | ForEach-Object { Invoke-Item -LiteralPath $_.FullName }
```

Si se usó `--analysis-dir`, construir `$simz1Images` desde esa raíz alternativa.
El [ejemplo histórico de corrida de 150000–250000 personas](readme-historico-20261030.md#uso-directo-del-lanzador-de-análisis)
utiliza este análisis automáticamente. La integración no ejecutó ese comando,
MATSim ni servidores, y no acredita capacidad, calibración o nuevas rutas OD.

Pruebas focales con fixtures, sin ejecutar MATSim ni abrir servidores:

```powershell
$simz1Python = (Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe').Path
$simz1OldPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = (Resolve-Path -LiteralPath '.\python').Path
    & $simz1Python -B -m unittest test_simz1_analysis test_simz1_profile_statistics test_simz1_profile_identity_cache test_simz1_trip_table test_procesar_eventos_z1 test_generar_graficas_z1 -v
    if ($LASTEXITCODE -ne 0) { throw 'Fallaron pruebas del análisis SimZ1.' }
} finally { $env:PYTHONPATH = $simz1OldPythonPath }
```

Los casos cubren corrida validada/fallida, interrupción y reintento, ausencia de
motos, seis perfiles, repetición, dos iteraciones y errores de disco. Las suites
estadísticas conservan cruces de hora, múltiples viajes por persona, exclusiones
y ponderación por viajes.

Validación de esta integración: 18 pruebas nuevas correctas y 49 regresiones
correctas; una prueba de contrato Java omitida por ausencia de su fixture
preexistente. El cierre de procesos temporales de Windows se comprobó fuera
del sandbox después de que este denegara `taskkill`. No se ejecutaron MATSim,
servidores ni poblaciones masivas; las ejecuciones del launcher usaron mocks.

<a id="validacion-integral"></a>
## Validación integral del 19/10/2026

Alcance: revisión de cambios existentes, fixtures y lectura de red; solo se actualizan
los dos README. No se ejecutaron MATSim, servidores, navegadores, regeneraciones
masivas ni exportaciones de SQLite/Motion_Plan. No se modificaron corridas históricas.
La comparación antes/después conservó los SHA-256 de los 20 archivos de código
previamente cambiados y tamaños/fechas de modificación de 945 archivos de las dos
corridas protegidas. Los enlaces locales de ambos README y la sintaxis de sus 37
bloques PowerShell se comprobaron sin ejecutar esos bloques; `git diff --check` pasó.

| Área | Evidencia ejecutada | Pendiente |
|---|---|---|
| Python | **111 pruebas aprobadas**, 13 módulos acotados, unittest; incluye OD, red, eventos, perfiles y diagnósticos. | Eventos de QSim sobre una red corregida. |
| JavaScript | **15 de 16 suites aprobadas**, Node 22.12.0, DOM/deck/fetch simulados en memoria. | Fixture HUD y representación GPU real. |
| Selección | Cuerpo resaltado coincide con `vehicle_id`/`person_id` en `test_simz1_vehicle_focus.cjs`; color original, paralelos, giro, espera, hover/clic, cierre, ventanas, seek, cámara y ausencia. | Confirmación visual en el replay real; no se abrió navegador. |
| Continuidad/rendimiento | Pasan bootstrap, replay, carga de ventanas, cuerpos rígidos, carriles/colas y `render_performance`; foco reutiliza capas y no sondea SQLite. | FPS, memoria GPU y carga reales no medidos en esta revisión. |
| Red | [Conteos y sentidos contrastados](#red); giros pendientes detectados, sin conexiones por proximidad. | Restricciones nativas, polígono, revisión de islas y catálogo real de accesos. |
| OD | Cuatro clases, pares alcanzables, paso interior, un sentido, giro prohibido, desnivel, callejón, componente separado y gateway inválido cubiertos por fixtures. | Rutas y eventos observados para cada clase en Zona 1. |
| Categorías × OD | Comprobación adicional en memoria: 160 personas, semilla 17, dos repeticiones idénticas por horario; cubre las 16 combinaciones viales ejecutables. | Público/pesado bloqueados; no se atribuye validación a seis perfiles. |
| Pico/valle | Fixtures concentran por clase en 02/07/17/23 h; comprobación cruzada adicional a las 07 y 02 h. | Distribución y congestión observadas; no son aforos reales. |

La suite original `test_simz1_continuous_hud.cjs` falla en la línea 106:
tras un solo `await Promise.resolve()`, `finishJson` sigue `undefined`. Una ejecución
diagnóstica del mismo fixture en memoria, cambiando únicamente esa espera por
`setImmediate`, aprobó el resto, incluido rechazo de respuestas obsoletas. La evidencia
apunta a sincronización de promesas entre contextos VM. **No se editó el test ni el
HUD; la suite original sigue fallando** y no se declara la batería completa verde.

La comprobación cruzada adicional usó `road_catalog()` de los fixtures: Normal 40 %,
Motociclista 40 %, Liebre 10 %, Tortuga 10 %, público/pesado 0 %. Es una alternativa
solo de prueba, no modifica el catálogo objetivo 40/25/10/10/10/5. Para cada horario
se obtuvo la misma matriz, mismos planes/ledger y 40 personas por clase OD:

| OD | Normal | Motociclista | Liebre | Tortuga |
|---|---:|---:|---:|---:|
| `INTERNAL_INTERNAL` | 19 | 15 | 4 | 2 |
| `INTERNAL_EXTERNAL` | 11 | 23 | 2 | 4 |
| `EXTERNAL_INTERNAL` | 19 | 12 | 2 | 7 |
| `EXTERNAL_EXTERNAL_THROUGH` | 15 | 14 | 8 | 3 |

Son asignaciones marginales exactas con barajado reproducible; no hay cuotas exactas
por cada celda conjunta. Diez agentes no garantizan cubrir las 16 combinaciones.
La implementación real de las [seis categorías](#seis-categorias) sigue separada:
cuatro tipos viales ejecutables y dos bloqueados. Sin catálogo explícito se usan
los tres perfiles históricos; no se presentan como prueba del catálogo de seis.

También se pasaron cuatro secuencias sintéticas con formato de eventos nativos por
`MovementAudit` y `extract`, usando el grafo de fixtures y persona `p`/vehículo `v`.
La admisión ocurre a 3 s, después de la salida programada a 0 s; la llegada de
actividad ocurre 2 s después del egreso. No hubo transiciones inválidas y se conservó
la identidad y la clase. Estos eventos se construyeron en memoria, **no salieron de QSim**:

| Clase | Secuencia de enlaces del fixture | Entrada / salida / duración observada (s) |
|---|---|---|
| II | `middle1 → middle2` | 3 / 23 / 20 |
| IE | `middle2 → exit` | 3 / 23 / 20 |
| EI | `entry → middle1 → middle2` | 3 / 33 / 30 |
| EE_THROUGH | `entry → middle1 → middle2 → exit` | 3 / 43 / 40 |

El último atraviesa dos enlaces interiores y usa accesos distintos. En los cuatro,
`door_to_door_seconds` permanece null. Estas comprobaciones adicionales no añaden
archivos de tests ni reemplazan las regresiones existentes.

### Repetir la batería acotada sin motor ni navegador

Desde la raíz, con dependencias instaladas. No usar descubrimiento de todos los tests
Python: otras suites arrancan servidores o QSim.

```powershell
$simz1Python = (Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe').Path
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:MPLBACKEND = 'Agg'
Push-Location .\python
try {
    & $simz1Python -B -m unittest test_simz1_four_od test_simz1_gateway_od test_simz1_gateway_generation test_simz1_spatial_replay test_simz1_agent_types test_simz1_agent_demand test_simz1_agent_metadata test_simz1_event_validation test_simz1_lane_validation test_simz1_osm_turn_audit test_simz1_storage_diagnostics test_simz1_operational_report test_simz1_capacity_diagnostics
    if ($LASTEXITCODE -ne 0) { throw 'Falló la batería Python acotada.' }
} finally { Pop-Location }
$simz1JsFailures = @()
$simz1JsTests = @(Get-ChildItem -LiteralPath .\python -Filter 'test_simz1*.cjs' | Sort-Object Name)
foreach ($simz1Test in $simz1JsTests) {
    & node $simz1Test.FullName
    if ($LASTEXITCODE -ne 0) { $simz1JsFailures += $simz1Test.Name }
}
if ($simz1JsFailures.Count) { throw ('Suites JS fallidas: ' + ($simz1JsFailures -join ', ')) }
```

En este árbol son 16 suites JS; el bloque conserva y reporta el fallo conocido del
HUD. `check_simz1_vehicle_focus_browser.cjs` es una prueba aparte de navegador,
no ejecutada. Para revisión visual posterior usar la [corrida existente en 8793](#pruebas-perfiles),
sin regenerarla: comparar ID seleccionado con `diagnoseVehicle`, cuerpo, carril y
orientación antes/después del giro, pausa, ventana y seek; revisar dos vehículos
paralelos y colores distintos. Una línea de ruta o el nombre de la tarjeta solos
no acreditan que esté resaltado el vehículo correcto.

<a id="corridas-pequenas"></a>
## Corridas manuales de 10, 100 y 1000 personas

**Comandos preparados, no ejecutados.** No están listos con la red actual: requieren
una nueva versión con giros importados y verificados, polígono aprobado, OSM trazable
y accesos dirigidos revisados. Las rutas `versions/od-v2` de abajo son un destino
propuesto todavía inexistente, no evidencia de una versión generada. No sustituir
el polígono por bbox ni quitar relaciones OSM para eludir el control previo.

Tras clonar desde GitHub y preparar el entorno según los [requisitos](../README.md#requisitos), registrar
revisión y estado. Los archivos locales nuevos no estarán en otro clon hasta que
el responsable publique la implementación; esta entrega no hace commit ni push.

```powershell
git rev-parse HEAD
git status --short
git ls-files --error-unmatch python/simz1_od_policy.py python/test_simz1_four_od.py python/test_simz1_vehicle_focus.cjs
if ($LASTEXITCODE -ne 0) { throw 'Falta publicar parte del contrato OD/selección; este clon no reproduce la entrega.' }
```

Conservar el commit, hashes de entradas, versiones instaladas, semillas, manifiesto
y configuración efectiva junto con cada corrida nueva. La misma semilla reproduce
demanda con los mismos insumos; no prueba por sí sola identidad de todos los eventos
de un motor multihilo. Compilar y ejecutar las regresiones antes de los ensayos.

Definir esta función en la consola de la raíz **solo después de preparar y revisar
esa versión del escenario**. Genera y ejecuta una carpeta nueva; no reanuda otra.
Preserva carriles/señales/prioridad/reruteo del config versionado. No cambia capacidad
ni velocidad para obtener llegadas. Sin `-Catalog` valida los tres perfiles históricos;
para cubrir Motociclista se requiere una copia de catálogo vial explícita y revisada,
con público/pesado en cero y porcentajes sintéticos que sumen 100. El catálogo completo
de seis categorías sigue rechazado, incluso si el redondeo pequeño daría cero bloqueados.

```powershell
$ErrorActionPreference = 'Stop'
$simz1Python = (Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe').Path
$simz1Maven = (Resolve-Path -LiteralPath '.\mvnw.cmd').Path
$simz1Version = Join-Path (Get-Location).Path 'scenarios\zona1\versions\od-v2'

function Invoke-SimZ1Small {
    param(
        [Parameter(Mandatory=$true)][ValidateSet(10,100,1000)][int]$Agents,
        [ValidateSet('MIX','INTERNAL_INTERNAL','INTERNAL_EXTERNAL','EXTERNAL_INTERNAL','EXTERNAL_EXTERNAL_THROUGH')][string]$OD = 'MIX',
        [int]$Seed = 20261019,
        [string]$Catalog,
        [string]$HourlyOD
    )
    $simz1Config = Join-Path $simz1Version 'config-simz1.xml'
    $simz1Boundary = Join-Path $simz1Version 'zone-boundary.geojson'
    $simz1Osm = Join-Path $simz1Version 'map.osm'
    foreach ($simz1Input in @($simz1Config,$simz1Boundary,$simz1Osm)) {
        if (-not (Test-Path -LiteralPath $simz1Input -PathType Leaf)) {
            throw "Falta la entrada revisada de la nueva versión: $simz1Input"
        }
    }
    # Orden legacy de --od-shares: EE, EI, IE, II.
    $simz1Weights = @{
        MIX='1,1,1,1'; INTERNAL_INTERNAL='0,0,0,1'; INTERNAL_EXTERNAL='0,0,1,0'
        EXTERNAL_INTERNAL='0,1,0,0'; EXTERNAL_EXTERNAL_THROUGH='1,0,0,0'
    }
    $simz1Run = Join-Path (Get-Location).Path ('scenarios\zona1\montecarlo\run-check-' + $Agents + '-' + $OD + '-' + [guid]::NewGuid().ToString('N'))
    $simz1Options = @(
        '.\python\ejecutar_simz1.py', '--config', $simz1Config, '--maven', $simz1Maven,
        '--run-dir', $simz1Run, '--mode', 'montecarlo', '--agents', "$Agents",
        '--seed', "$Seed", '--matsim-seed', "$Seed", '--iterations', '1',
        '--od-mode', 'gateway-od', '--zone-boundary', $simz1Boundary, '--od-osm', $simz1Osm,
        '--od-shares', $simz1Weights[$OD], '--trips-per-person', '1', '--drain-seconds', '0',
        '--signal-offset-policy', 'preserve'
    )
    foreach ($simz1Optional in @(@('--agent-catalog',$Catalog),@('--od-hourly-profiles',$HourlyOD))) {
        if ($simz1Optional[1]) {
            if (-not (Test-Path -LiteralPath $simz1Optional[1] -PathType Leaf)) { throw "Falta $($simz1Optional[1])" }
            $simz1Options += $simz1Optional
        }
    }
    & $simz1Python @simz1Options | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Fallo; conservar $simz1Run y su log." }
    $simz1State = Get-Content -LiteralPath (Join-Path $simz1Run 'run-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($simz1State.status -ne 'completed' -or $simz1State.validation.status -ne 'valid') { throw 'Cierre o integridad pendientes.' }
    if ($simz1State.counts.planned_persons -ne $Agents -or $simz1State.counts.planned_trips -ne $Agents) { throw 'N personas/viajes no coincide.' }
    if ($simz1State.time_horizon.start_seconds -ne 0 -or $simz1State.time_horizon.end_seconds -ne 86400) { throw 'Horizonte distinto de 24 h.' }
    return $simz1Run
}
```

Seleccionar un umbral experimental de censura **antes** del ensayo; no hay un valor
municipal validado. La siguiente función audita solo la corrida nueva y hasta 1000
personas. Guarda un JSON nuevo y exige resultado `screening_pass`; un código de
proceso cero también puede acompañar un diagnóstico `incomplete`.

```powershell
function Test-SimZ1Small {
    param(
        [Parameter(Mandatory=$true)][string]$Run,
        [Parameter(Mandatory=$true)][ValidateRange(0.0,1.0)][double]$MaxCensoredFraction
    )
    $simz1Check = Join-Path $Run ('capacity-check-' + [guid]::NewGuid().ToString('N') + '.json')
    $simz1Limit = $MaxCensoredFraction.ToString([Globalization.CultureInfo]::InvariantCulture)
    & $simz1Python .\python\simz1_capacity_diagnostics.py --run-dir $Run --iteration 0 --events --max-censored-fraction $simz1Limit --output $simz1Check
    if ($LASTEXITCODE -ne 0) { throw "Diagnóstico rechazado; revisar $simz1Check." }
    $simz1Result = Get-Content -LiteralPath $simz1Check -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($simz1Result.acceptance.status -ne 'screening_pass') { throw "Evidencia incompleta: $simz1Check" }
    & $simz1Python .\python\simz1_operational_report.py --run-dir $Run --iteration 0 --no-plots
    if ($LASTEXITCODE -ne 0) { throw 'Falló el informe operacional.' }
}
$simz1LimitText = Read-Host 'Umbral experimental previo de censura entre 0 y 1 (punto decimal)'
$simz1MaxCensored = [double]::Parse($simz1LimitText, [Globalization.CultureInfo]::InvariantCulture)
if ([double]::IsNaN($simz1MaxCensored) -or $simz1MaxCensored -lt 0 -or $simz1MaxCensored -gt 1) { throw 'Umbral inválido.' }
```

Ejecutar primero cada clase pura con N=10, usando sucesivamente los cuatro valores
de `-OD` de la tabla anterior. Revisar eventos antes de la siguiente. Luego mezcla:

```powershell
# Repetir manualmente para las otras tres clases, revisando cada resultado.
$simz1Pure = Invoke-SimZ1Small -Agents 10 -OD INTERNAL_INTERNAL
Test-SimZ1Small -Run $simz1Pure -MaxCensoredFraction $simz1MaxCensored
```

```powershell
$simz1Run10 = Invoke-SimZ1Small -Agents 10 -OD MIX
Test-SimZ1Small -Run $simz1Run10 -MaxCensoredFraction $simz1MaxCensored
```

**Solo tras revisar las clases puras y la mezcla de diez:**

```powershell
$simz1Run100 = Invoke-SimZ1Small -Agents 100 -OD MIX
Test-SimZ1Small -Run $simz1Run100 -MaxCensoredFraction $simz1MaxCensored
```

**Solo tras revisar cien, incluido el cruce OD × categorías:**

```powershell
$simz1Run1000 = Invoke-SimZ1Small -Agents 1000 -OD MIX
Test-SimZ1Small -Run $simz1Run1000 -MaxCensoredFraction $simz1MaxCensored
```

Agregar `-Catalog RUTA` a cada llamada para probar el catálogo vial revisado y
`-HourlyOD RUTA` para perfiles por clase. Ejemplo de diseño sintético a registrar en
el JSON: peso 4 en horas 07,08,17,18 y 1 en las otras veinte, para cada clase canónica;
comparar con 24 pesos iguales. La suma se normaliza y se intersecta con ventanas del
agente. Conservar la misma N/semilla/catálogo/red al comparar pico/valle; exigir presencia
de celdas relevantes en la muestra efectiva, sin forzar porcentajes exactos por hora.
El horizonte continúa siendo 24 h. El perfil completo usa `source="synthetic"` y las
cuatro claves, cada una con exactamente 24 pesos. No se crea aquí ese archivo.

`scripts/validation/validate_small_run.ps1` conserva su ensayo histórico de diez
personas en modo `network`; no implementa esta matriz OD ni sustituye estos comandos.
Los diagnósticos de arriba no producen SQLite, Motion_Plan ni replay.

### Evidencia que revisar en cada corrida

| Medida | Criterio y fuente |
|---|---|
| Configuración propuesta/efectiva | Manifest `spatial_demand`, `agent_configuration`, perfiles temporales y XML efectivo; mismos hashes y semillas al repetir. |
| Población | N personas y N viajes únicos; suma de clases=N; entrada/salida no duplica persona ni viaje. Conteos realizados de planes no se llaman llegadas. |
| Identidades | Unir `simz1Trips`/`simz1SpatialOD` por `trip_id` y catálogo por `person_id`; enlazar `vehicle_id` desde eventos de tráfico, sin asumir igualdad persona/vehículo. |
| Cuatro OD observados | II interior/interior; IE final en gateway de salida; EI primero en gateway de entrada; EE accesos distintos y al menos un enlace interior no gateway realmente recorrido. |
| Física | Cero transiciones inválidas, enlaces desconocidos, giros prohibidos, discontinuidades o teletransportes silenciosos. La ruta instalada y cada transición observada deben ser compatibles con red y carriles efectivos. |
| Intervenciones | Cero `forced_storage_moves` y `storage_stuck_removals`; telemetría presente. Contadores son decisiones/eventos, no vehículos únicos. |
| Balance temporal | Llegados, pendientes al corte, sin iniciar y abortados antes de 86400 por separado; horario de admisión/egreso distinto de salida/llegada de actividad. |
| Congestión | Ocupación, caudal por enlace/hora, WAIT por causa, recurrencia de esperas y progreso nativo. WAIT son intentos, no segundos ni longitud de cola; activos de red no equivalen a viajes pendientes. |
| Distribución | Tabla OD × categoría × hora, gateways efectivos y concentración en Elena; confrontar probabilidades propuestas con conteos realizados, sin exigir distribución municipal desconocida. |
| Rendimiento | Tiempo total, CPU/working set, heap, progreso QSim y costo del reruteo; no deducir deadlock JVM de congestión vial. |

El lanzador y los diagnósticos existentes validan integridad, transiciones y métricas
nativas. **No hay todavía un informe automático completo OD × categoría × hora ni
una certificación conjunta de primer/último gateway e interior recorrido a partir
de eventos reales.** Esas reconciliaciones siguen pendientes de la revisión de las
corridas nuevas. `simz1_operational_report` agrega perfiles/horas; no sustituye el
cruce con `simz1SpatialOD`. `extract` conserva entrada/egreso nativos, pero sus fixtures
no constituyen observación física de Zona 1. No llenar ausencias con cero.

<a id="autorizar-masivo"></a>
## Condiciones para autorizar 150000–250000 agentes

La autorización continúa pendiente. Deben cumplirse conjuntamente:

1. Red nueva trazable, restricciones OSM traducidas y verificadas también durante
   reruteo, relación incompleta resuelta, polígono aprobado y accesos/islas revisados;
   conservar callejones, peatones, sentidos y desniveles sin enlaces por proximidad.
2. Batería acotada original completamente verde, incluido el fixture HUD pendiente;
   revisión visual confirma identidad/carril/pose y continuidad con el replay existente.
3. Corridas nuevas de 10, 100 y 1000, una iteración: cuatro clases puras y mezcla,
   categorías realmente ejecutables, pico/valle, semillas repetibles y reconciliación
   de rutas/eventos/gateways. Público/pesado no entran como si ya estuvieran implementados.
4. Cero transiciones inválidas, teletransportes silenciosos, movimientos forzados,
   retiros por storage y abortos tempranos; instrumentación completa y sin deadlocks
   observados. Censura dentro del umbral previo, colas/progreso y distribución de accesos
   explicados. El cierre a 24 h no se confunde con retiro por storage.
5. Presupuesto de recursos sustentado por mediciones, sin alterar velocidad/capacidad
   para pasar criterios. Superar 1000 es necesario pero no demuestra que 250000 sea viable;
   cualquier escalamiento requiere revisión y una carpeta nueva con todos los parámetros.

Ni `BUILD SUCCESS` ni `completed/valid` sustituyen estos criterios. Mantener una
iteración inicialmente; no proponer 50 hasta validar conectividad, OD e intervenciones
nativas en pequeño. Esta revisión no ejecuta ni autoriza por sí sola ese escalamiento.

<a id="validacion"></a>
## Validación y rendimiento

Cada resultado debe identificar corrida, iteración, semillas, configuración, modo, denominador y horizonte.
El flujo manual pequeño del README requiere revisar cada etapa antes de continuar. Esta guía no acredita su ejecución.
Los validadores contrastan hashes, XML, rutas, movimientos, viajes y productos; `completed/valid` acredita
su contrato, no calibración ni estabilidad física.

La [matriz de contratos](maintenance/simz1-test-contracts.csv) registra 93 archivos por lectura estática,
con fuentes, dependencias, efectos y selección; no es un reporte de pruebas aprobadas:

| Selección conservada | Archivos | Alcance |
|---|---:|---|
| `pytest_simz1` | 43 | Suite Python acotada por [pytest-simz1.ini](../pytest-simz1.ini). |
| `node_simz1` | 11 | Contratos JavaScript; no acreditan píxeles WebGL o FPS. |
| `java_check` | 11 | Comprobaciones Java seleccionadas. |
| `java_qsim_optin` | 10 | Simulaciones pequeñas, separadas y de ejecución explícita. |
| `java_historico_no_default` | 1 | `ValidateDemandZ1`, validador histórico, no generador de población. |
| `laboratorio_protegido` | 17 | Quince Python y dos Java de laboratorios independientes. |

No se fusionan suites ni se incorporan laboratorios al conjunto SimZ1. El árbol inspeccionado no contiene
un workflow de CI que permita afirmar ejecución automática. Los comandos manuales están en el README principal.

La configuración rechaza tiempos link-to-link con `removeStuckVehicles=true` o `separateModes=true`,
y ruteo entre enlaces sin calcular esos tiempos. Desactivar retirada de atascados no elimina todos los movimientos
forzados por almacenamiento. WAIT persistente puede ser congestión; un deadlock JVM exige evidencia de ciclo de hilos,
no únicamente lentitud o ausencia temporal de llegadas.

Comparaciones off/on requieren mismas entradas y criterios. Semilla compartida no fija incidentes dependientes
de ocupación, que pueden divergir. Un umbral de censura debe decidirse antes del ensayo.
No extrapolar fixtures pequeñas a 150k–200k, ni datos de otra iteración para rellenar ausencias.

[simz1_capacity_diagnostics.py](../python/simz1_capacity_diagnostics.py) separa `reject` (algún criterio falso),
`incomplete` (falta evidencia o umbral) y `screening_pass` (todos los criterios satisfechos). Exige horizonte diario,
integridad, cero movimientos forzados/retiros por storage, cero abortos tempranos y ausencia observada de deadlocks JVM con telemetría.
El criterio de censura incluye viajes sin iniciar y requiere `--max-censored-fraction` explícito:

```text
sin_iniciar = viajes_planificados − salidas_observadas ≥ 0
(pendientes_al_corte + sin_iniciar) / viajes_planificados ≤ umbral
```

Falta de información no equivale a cero forzados o cero deadlocks. Un `screening_pass` no demuestra calibración,
realismo ni rendimiento masivo; un rechazo de criterios tampoco es lo mismo que un error al leer/procesar entradas.

La latencia backend, JSON recibido, heap, working set, GPU y FPS son medidas distintas. `lastLoadMs` integra carga;
no separa SQL, JSON y render. RAF/s no certifica FPS sostenidos. Los benchmarks históricos no prometen rendimiento
actual y esta revisión no ejecutó benchmarks ni inspección visual nueva.
El informe local `evidence/replay/RENDIMIENTO_HISTORICO.md` conserva instrumentos,
correcciones y resultados anteriores. Sus cifras y pruebas de navegador no se atribuyen al código actual.

<a id="diagnostico"></a>
## Diagnóstico nativo y fallos

El observador de decisiones mantiene una copia instrumentada de `QNodeImpl` de MATSim 15 como
`Zona1QNodeImpl`, con licencia y referencia a la fuente. El SHA-256 histórico de la fuente nativa auditada
es `3ad926638abb34a8116e660e70ee9eca998eb8fe9001861e2a60f6f36bcf0118`.
Actualizar MATSim obliga a revisar esa paridad; los resultados del informe antiguo no prueban paridad
con otra versión. La instrumentación observa aceptación, almacenamiento y cruce, sin reemplazar la física.

| Decisión / causa | Interpretación |
|---|---|
| `turn_abort_null_route`, `turn_abort_missing_link`, `turn_abort_disconnected` | Ruta inválida; ABORT temprano, no congestión ordinaria. |
| `signal_red`, `signal_redyellow`, `signal_not_green` | El permiso nativo bloquea el intento. |
| `priority_stop`, `priority_yield`, `intersection_conflict` | Espera de prioridad/conflicto; no cruce consumado. |
| `turn_go` seguido de `storage_wait` | Giro permitido, receptor sin almacenamiento. |
| `storage_forced_move`, `storage_stuck_removal` | Intervención nativa; no capacidad vial servida. |

WAIT cuenta intentos, no duración acumulable. El reloj de cabecera nativo
`getLastMovementTimeOfFirstVehicle` y el reloj mínimo de salida post-step representan condiciones
distintas. El color no disponible no se sustituye por el plan si falta `nativeHasGreen` compatible.
Con `stuckTime=10` y retirada desactivada, MATSim todavía puede forzar un movimiento tras rechazo de
storage y edad >10 s; el WAIT rojo retorna antes de esa rama, por lo que no prueba paso forzado en rojo.
Cambiar esas condiciones sería otro experimento y requiere una configuración nueva.

### Caso 229,629: origen de las 696,657 intervenciones

Revisión estática del 18-10-2026: se leyeron fuentes MATSim 15 locales, código SimZ1,
configuración efectiva y resúmenes existentes. No se ejecutó QSim, no se recorrieron los
eventos masivos y no se revalidaron ni reescribieron las corridas históricas.
La evidencia registrada está en
[run-manifest.json](../scenarios/zona1/montecarlo/run-night-20261017-012651-6a8d9ac3/run-manifest.json),
run ID `simz1-812280b2645343f589d738532178b1bf`, iteración 0, bajo `results.0.native_qsim`:

| Contador registrado | Valor | Unidad / alcance |
|---|---:|---|
| `reasons.storage_forced_move` | 696657 | Inserciones forzadas; un vehículo puede aparecer muchas veces. |
| `storage_stuck_removals` | 0 | Retiros en la rama de almacenamiento. |
| `reasons.storage_wait` | 12019826 | Intentos bloqueados aguas abajo, no segundos ni vehículos únicos. |
| `wait_categories.signal` | 6009004 | Observaciones de espera por señal, incluidas las de cola post-step. |
| `wait_categories.mandatory_stop` / `yield` | 2025029 / 91986 | Esperas de parada / conflicto o cesión. |
| `reasons.congestion_queue` | 335079 | Cabecera elegible aún no ofrecida por la cola. |
| `progress.link_transitions` / `reasons.turn_go` | 9059243 / 21079069 | Cruces observados / permisos de giro; son medidas distintas. |

El mensaje antiguo sumaba forzados y retiros en `simz1_run.validate_outputs` y los mostraba
con una sola frase en `ejecutar_simz1.ejecutar`. **No significa 696657 vehículos distintos
desaparecidos.** Los 90434 viajes pendientes al horizonte, 139195 completados y cero abortos
antes del horizonte están en `results.0.temporal_events`; los abortos de cierre no son
`storage_stuck_removal`. Tampoco deben sumarse todos los eventos de aborto como personas:
el resumen temporal conserva anomalías de terminal duplicado y aborto sin asociación de vehículo.

La configuración efectiva archivada (`output/output_config.xml`) usa `stuckTime=10`,
`removeStuckVehicles=false`, `trafficDynamics=queue`, `linkDynamics=FIFO`, `useLanes=true`,
paso 1 s, factores de flujo/almacenamiento 1, cuatro hilos y `usingFastCapacityUpdate=false`.
La cadena causal inmediata está demostrada por
[Zona1QNodeImpl.moveVehicleOverNode](../src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/Zona1QNodeImpl.java):

1. Una restricción de carril inválida produce `turn_restriction/ABORT`. Después, la lógica
   nativa de giro puede devolver ABORT por ruta inválida o WAIT por señal/prioridad.
   Ambos retornan antes de consultar almacenamiento. Un rojo no se salta por timeout.
2. Con GO, consulta `nextQueueLink.getAcceptingQLane().isAcceptingFromUpstream()`.
   En `QLinkLanesImpl` esta es la sección original compartida del receptor, no la suma
   del almacenamiento de todo el enlace ni una terminal de giro libre a elección.
3. `QueueWithBuffer.isAcceptingFromUpstream`, para `queue`, exige
   `usedStorageCapacity < storageCapacity`. Su `getLoadIndicator()` mide PCU de la cola,
   excluyendo el buffer separado. Un rechazo no es una transición geométricamente inválida.
4. Si rechaza, `vehicleIsStuck` compara estrictamente
   `now - fromLane.getLastMovementTimeOfFirstVehicle() > stuckTime`.
   Antes del umbral registra `storage_wait`; después registra `storage_forced_move/FORCE`
   y ejecuta pop, LinkLeave, cambio de enlace del conductor, LinkEnter e inserción, aun sin espacio.
   Solo con `removeStuckVehicles=true` registra `storage_stuck_removal/ABORT`, extrae y
   aborta conductor/pasajeros sin LinkEnter al receptor.

El reloj de `QueueWithBuffer` se establece al entrar el primero al buffer y al extraer una
cabecera. **No mide espera continua por almacenamiento:** puede incluir rojo, parada o cesión
anteriores. Por eso un primer intento en verde con receptor lleno puede forzarse de inmediato
si la cabecera ya supera 10 s. Es el comportamiento nativo conservado, no un defecto del visor.
`UnsignalizedPriority.StopAndYield.crossed` describe el mismo cruce en `simz1Priority`; no es
otra intervención. `SimZ1Diagnostics.report` publica deltas, que tampoco se suman otra vez.
El contador canónico procede de `Zona1NativeDiagnostics.storage` → `simz1NativeDecision` →
[NativeDecisionAudit.consume](../python/simz1_native_validation.py).

Hay otros bloqueos que no deben atribuirse a esta rama: `QueueWithBuffer.moveQueueToBuffer`
comprueba tiempo mínimo, llegada/tránsito y disponibilidad de flujo; `congestion_queue` es
una observación post-step, no una medición directa de flujo agotado. La transferencia interna
`QLinkLanesImpl.moveBufferToNextLane` espera cuando su terminal rechaza espacio; no usa este
timeout de QNode. La inserción de una salida de actividad pasa por `isAcceptingFromWait`
y control de flujo; no se cuenta como `storage_forced_move`. Una excepción de inserción o un
`toQueues` inválido requiere su log/stack propio, no se deduce de estos 696657 registros.

| Factor | Evidencia y conclusión conservadora |
|---|---|
| Almacenamiento / timeout nativo | Confirmado como mecanismo inmediato de las 696657 decisiones. Falta localizar receptores dominantes en una corrida pequeña instrumentada. |
| Demanda concentrada | `montecarlo-report.json` registra cuota 0.7 redistribuida a Avenida Elena porque Bulevar Asunción y Calle Martí no están disponibles: 160987 orígenes de esa rama y 162066 orígenes físicos sobre Elena (70.58%). Es un candidato fuerte a presión local; orígenes no equivalen a caudal de entrada administrativa ni prueban dónde ocurrieron los forzados. |
| Geometría / colas terminales | La validación efectiva registra 2446 enlaces <7.5 m y 8367 colas detalladas bajo una celda. `prepare` crea segmentos entre pares de nodos OSM; `LanesGenerator.build` subdivide incluso enlaces cortos en original + terminales. Hay discretización serial y receptores pequeños; requiere inspección local. No se ha probado un error topológico dominante. |
| Capacidad demasiado baja | No demostrada. `road_parameters` usa una base ideal explícita de 2000 por carril y hora, no aforos; capacidad del enlace ya agrega carriles. Los PCU geométricos se conservan (25337.394319); los umbrales sumados aumentan de 25559.090679 a 27349.631627 con la división. Más almacenamiento agregado no garantiza descarga local. |
| Señales / prioridades | Sus esperas están registradas y pueden reducir descarga o preceder al timeout. Planes de señales sintéticos y prioridad geométrica/jerárquica con parada 5 s y equidad 30 s requieren calibración. `canCompete` exige espacio y permiso; equidad no autoriza rojo ni espacio inexistente. Los totales no permiten repartir los forzados por causa raíz. |
| Within-day routing | Se registran 1831 cálculos y cero transiciones físicas inválidas. No es condición necesaria: la corrida protegida 100000 registra 250453 forzados y cero cálculos; otra de 167484 registra 633873 y cero cálculos. Son cargas/horizontes distintos, no un experimento causal pareado. |
| Representación visual | Offsets, hitbox, orientación y colas WebGL no intervienen en QNode. Corregirlos no reduce estos contadores ni valida el modelo físico. |

Cambios preparados para **futuras** corridas, sin modificar decisiones ni parámetros físicos:

- `Zona1NativeDiagnostics.storage` conserva el rechazo real y añade ID de cola receptora.
  Toma una lectura por intervención y, para WAIT, como máximo una por receptor cada 60 s:
  carga, umbral PCU, flujo por paso y presión de sus salidas. La versión 2 indica
  disponibilidad de cabeceras explícita: con QSim paralelo no consulta su primer
  vehículo y registra el conteo de bloqueos por señal como `unknown`. Son lecturas
  no atómicas en ejecución paralela; no consulta getters de flujo que acumulen capacidad
  ni enumera todos los vehículos. En otras implementaciones de cola no presupone que
  `getLoadIndicator` sea PCU. El muestreo WAIT no permite estimar porcentajes temporales.
- [StorageAudit](../python/simz1_storage_diagnostics.py) separa WAIT/FORCE/retiro, vehículos
  identificados por iteración, cobertura de observaciones, horas y 20 movimientos principales.
  Un ID ausente produce conteo único desconocido. En eventos antiguos la ocupación queda
  sin evidencia, no en cero. Carga bajo umbral tras un rechazo se conserva como observación
  compatible con lectura concurrente, no se declara un fallo físico automáticamente.
- [audit_configuration](../python/simz1_lane_validation.py) incorpora `storage_screening`
  de colas activas: original receptora, terminal y enlace sin división. Señala umbrales
  menores a 1 PCU, tiempos libres menores a un paso e intervalo nominal por PCU mayor que
  `stuckTime`. Son candidatos de revisión, no autorización para ensanchar o aumentar capacidades.
- El manifiesto futuro, consola y progreso separan movimientos forzados y retiros.
  No se migra ni se vuelve a publicar ningún manifiesto histórico.

Antes de otra masiva: ejecutar los fixtures de abajo; después diseñar un experimento pequeño
pareado con misma demanda, semilla y horizonte, variando un factor cada vez. Priorizar los
receptores con más intervenciones y contrastar señal, prioridad, terminales, accesos y demanda
con su fuente. Revisar consolidación de nodos OSM meramente geométricos solo si preserva
longitud, salidas, controles y restricciones; no alargar enlaces cortos artificialmente.
Comparar alternativas de colas y sensibilidad a `stuckTime` como experimentos explícitos:
elevar el timeout puede reducir el contador ocultando más espera, no crear capacidad.
No activar retiros para vaciar la red (además, son incompatibles con el cálculo link-to-link
habilitado). Corregir capacidades o reparto de demanda solo con evidencia y una configuración
nueva. Medir también pendientes, tiempos, descarga, bloqueo recurrente y coste de la nueva
instrumentación; terminar la ejecución o tener cero forzados no acredita realismo.

Fixtures de almacenamiento. La revisión original solo los preparó; la corrección
concurrente descrita abajo ejecutó cuatro checks Java y 37 pruebas Python de
almacenamiento/capacidad/informe operacional. PowerShell desde la raíz, con Python
y el JDK 25 del proyecto; no abren corridas históricas ni lanzan QSim:

```powershell
python -m unittest discover -s .\python -p test_simz1_storage_diagnostics.py -v
Push-Location .\python
try {
    python -m unittest -v test_simz1_lane_validation.LaneInputTests.test_storage_screening_uses_active_queues_and_serialized_zero_timeout test_simz1_signals_config.SignalsConfigurationTests.test_native_waits_forcing_and_route_abort_are_distinct test_simz1_capacity_diagnostics.CapacityEventsTests
} finally { Pop-Location }
.\mvnw.cmd '-DskipTests' test-compile
if ($LASTEXITCODE -ne 0) { throw 'Fallo test-compile' }
$storageChecks = @('SimZ1StorageObservationCheck', 'SimZ1StorageBranchCheck', 'Zona1NativeDecisionCheck', 'PriorityBlockedRegression')
foreach ($storageCheck in $storageChecks) {
    .\mvnw.cmd '-q' '-Dexec.classpathScope=test' "-Dexec.mainClass=org.matsim.core.mobsim.qsim.qnetsimengine.$storageCheck" exec:java
    if ($LASTEXITCODE -ne 0) { throw "Fallo $storageCheck" }
}
```

Resultado esperado: Python `OK` y Java `PASS`. `SimZ1StorageBranchCheck` llama la rama real de
`Zona1QNodeImpl` con colas controladas: rechazo antes/al umbral, fuerza después, retiro separado,
verde con espacio, rojo prolongado seguido de verde, receptor original distinto de terminal y
muestreo acotado/reiniciado entre iteraciones. Las colas son dobles de prueba: no validan
descarga calibrada de `QueueWithBuffer` ni estabilidad de una red completa. La regresión de
integración del mensaje/manifiesto se puede ejecutar aparte con
`python -m unittest -v test_simz1_run.RunContractTests.test_forced_storage_moves_are_valid_results_without_stability_certificate`
desde `python`; usa demanda diminuta temporal y sustituye Maven, no ejecuta MATSim.

### Corrección de observación concurrente del receptor — 19/10/2026

La corrida `run-mc-150k-250k-3a31d724f15d4aa2adaed8f0e2ebfc13` se inspeccionó
solo en lectura: 227187 personas/viajes, semillas de demanda y MATSim `20261019`,
Monte Carlo `network`, `redistribute` con cuota 0.7, horizonte 24 h, cuatro hilos
QSim, una iteración solicitada y ninguna completada. No contiene `spatial_demand`
ni valida cuatro clases OD. Conserva `status=failed`, `validation.status=invalid`,
`phase=failure_phase=shutdown` y `failure_category=runtime_exception`.
El último progreso es 25479 s (07:04:39): 4820 vehículos activos y, en el último
intervalo de 39 s, 90 llegadas, 382 decisiones forzadas, 5877 esperas por storage
y cero retiros. Son un snapshot y deltas, no totales de la población.

El manifiesto identifica como primer error impreso la gestión paralela de eventos
(línea 2691 del log, orden cronológico inválido). El stack de QSim muestra el NPE
de `QueueWithBuffer.getFirstVehicle:904` → `Zona1NativeDiagnostics.storage:182`
→ `Zona1QNodeImpl.moveVehicleOverNode:446`. El manifiesto histórico no se reescribe.
La investigación del cierre, descrita abajo, distingue el primer error impreso de
la excepción que inició el cierre. Todavía se requiere una corrida pequeña completa.

Se revisó el JAR/fuente local de **MATSim 15.0** utilizado. `getFirstVehicle()`
comprueba `buffer.isEmpty()` y luego llama `buffer.peek().getKey()` sin bloqueo;
otro nodo puede retirar el último vehículo entre esas lecturas. El buffer de salida
puede estar vacío legítimamente aunque la cola receptora esté llena. Un guard externo,
`getAllVehicles()` o un lock solo del observador no ofrecen un snapshot seguro.
La consulta era exclusivamente para contar cabeceras bloqueadas por señal; no decide
la admisión, que ya había sido rechazada por la lógica nativa.

El cambio acotado evita esa consulta ajena durante QSim paralelo, conserva las demás
mediciones y todos los eventos WAIT/FORCE/ABORT, y registra
`storageObservationVersion=2`, `receiverExitHeadObservation=unavailable_parallel_qsim`
y `receiverExitHeadsSignalBlocked=unknown`. En ejecución serial conserva la lectura;
si faltan vehículo/conductor/destino marca `unavailable_head`. El lector Python acepta
v1/v2 y separa datos ausentes de cero bloqueos. No atribuye el vehículo receptor al
evento: la identidad sigue siendo la del vehículo de la decisión nativa.

La otra lectura diagnóstica, post-step, ocurre después de que los workers del motor
terminan y admite cola vacía/null. Las lecturas de cabecera en QNode y prioridad
operan sobre colas entrantes propiedad del mismo nodo y forman parte de la lógica
física; no se modificaron. Tampoco se cambia MATSim, FIFO, capacidad, rutas o timeout,
ni se capturan excepciones físicas para continuar.

`SimZ1StorageObservationCheck` reprodujo primero el NPE original con el getter real
y un vaciado intercalado determinista. Tras el cambio comprueba colas vacías, con uno
y varios vehículos, receptora/terminal, inmutabilidad de ambas colas, datos ausentes,
identidad, admisión normal, WAIT, fuerza y retiro. Compara decisiones y eventos físicos
con/sin enriquecimiento del receptor y verifica propagación de errores físicos.
Incluye entrega por `SimStepParallelEventsManagerImpl` con dos hilos y dos handlers;
**no ejecuta QSim**. El constructor de comparación es interno a pruebas; la inyección
normal conserva el diagnóstico activo. No es una garantía de una simulación masiva.

Los cuatro checks de almacenamiento y el check cronológico pasaron con
`javac --release 25` en una carpeta aislada, además de las 37 pruebas Python.
El `target` compartido presentó clases
inconsistentes y su limpieza Maven encontró archivos bloqueados; no se detuvieron
procesos ajenos. Para repetir la compilación aislada sin depender de esas clases:

```powershell
$ErrorActionPreference = 'Stop'
.\mvnw.cmd --batch-mode --no-transfer-progress dependency:build-classpath '-Dmdep.outputFile=target/simz1-storage-classpath.txt'
if ($LASTEXITCODE -ne 0) { throw 'No se pudo obtener el classpath.' }
$simz1Deps = (Get-Content -LiteralPath .\target\simz1-storage-classpath.txt -Raw).Trim()
$simz1Build = Join-Path (Get-Location).Path ('target\simz1-storage-check-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $simz1Build | Out-Null
$simz1Checks = @('SimZ1StorageObservationCheck','SimZ1StorageBranchCheck','Zona1NativeDecisionCheck','PriorityBlockedRegression')
$simz1Sources = @(Get-ChildItem -LiteralPath .\src\main\java -Recurse -Filter '*.java' | ForEach-Object { $_.FullName })
foreach ($simz1Name in $simz1Checks) {
    $simz1Sources += (Resolve-Path -LiteralPath ('.\src\test\java\org\matsim\core\mobsim\qsim\qnetsimengine\' + $simz1Name + '.java')).Path
}
$simz1Sources += (Resolve-Path -LiteralPath '.\src\test\java\gt\edu\uvg\sim\zona1\SimZ1EventChronologyCheck.java').Path
$simz1Args = @('--release','25','-encoding','UTF-8','-cp',('"' + $simz1Deps.Replace('\','/') + '"'),'-d',('"' + $simz1Build.Replace('\','/') + '"'))
$simz1Args += @($simz1Sources | ForEach-Object { '"' + $_.Replace('\','/') + '"' })
$simz1ArgFile = Join-Path $simz1Build 'javac.args'
[IO.File]::WriteAllLines($simz1ArgFile, $simz1Args, [Text.UTF8Encoding]::new($false))
& javac.exe ('@' + $simz1ArgFile)
if ($LASTEXITCODE -ne 0) { throw 'Falló javac.' }
foreach ($simz1Name in $simz1Checks) {
    & java.exe -cp ($simz1Build + ';' + $simz1Deps) ('org.matsim.core.mobsim.qsim.qnetsimengine.' + $simz1Name)
    if ($LASTEXITCODE -ne 0) { throw "Falló $simz1Name" }
}
& java.exe -cp ($simz1Build + ';' + $simz1Deps) gt.edu.uvg.sim.zona1.SimZ1EventChronologyCheck
if ($LASTEXITCODE -ne 0) { throw 'Falló SimZ1EventChronologyCheck.' }
Push-Location .\python
try {
    ..\.venv\Scripts\python.exe -B -m unittest test_simz1_storage_diagnostics test_simz1_capacity_diagnostics test_simz1_operational_report
    if ($LASTEXITCODE -ne 0) { throw 'Fallaron las regresiones Python.' }
} finally { Pop-Location }
```

Para la prueba manual de 10 y luego 100, usar `ejecutar_simz1.py` en carpetas nuevas,
`--agents 10` o `--agents 100`, semillas `20261019`, `--iterations 1`,
`--qsim-threads 4`, `--od-mode network --corridor-policy redistribute`,
`--temporal-profile full-day --trips-per-person 1 --drain-seconds 0`.
Esto comprueba la corrección con el modo del fallo; no el escenario futuro gateway.
Revisar cierre, cronología de eventos, contadores, transiciones y censura antes de
escalar. Corregir el NPE no elimina los movimientos forzados ni autoriza otra masiva.

### Cronología del cierre interrumpido — 19/10/2026

En esa corrida, `qsim.numberOfThreads=4` y `global.numberOfThreads=12` no significan
cuatro o doce handlers paralelos: el log (línea 119) confirma
`SimStepParallelEventsManagerImpl number of threads=1`. No se configuró
`parallelEventHandling`; MATSim 15 usa por defecto un worker asíncrono,
`synchronizeOnSimSteps=true` y `oneThreadPerHandler=false`. QSim invoca
`events.afterSimStep(now)` después de los motores. Los handlers de tiempos de viaje,
reruteo, señales, diagnósticos, viajes y XML reciben la secuencia del gestor. Los
registros dobles de alta de handlers corresponden al delegado serial y al worker;
no implican doble entrega. El watchdog de SimZ1 solo escribe al log.

Evidencia leída sin modificar la corrida:

- Línea 2690, `18:38:28,592`: informe final `simz1Progress` con tiempo **25479**,
  fuera de la cadencia de 60 s. `simulatedTime` conservaba el último paso completado.
- Líneas 2691–2694, `18:38:28,597`: primer error cronológico impreso,
  `Events in the queue are not ordered chronologically`, en
  `SimStepParallelEventsManagerImpl$ProcessEventsRunnable.run:292` → `Thread.run`.
- Línea 2695: QSim avisa de una excepción secundaria en su `finally`; el stack
  pasa por `finishProcessing:221` y `cleanupSim:366`.
- Líneas 2723–2761: se imprime la excepción original del motor, el NPE de storage.
  `QSim.run:261–276` propaga esa excepción después de ejecutar el cierre, por lo
  que el orden de impresión no es el orden causal.
- Lectura secuencial del gzip: **14346189 eventos**, cero retrocesos escritos y
  último tiempo **25480**. Hay eventos físicos del paso parcialmente ejecutado;
  25479 era el último paso completado, no el último tiempo emitido.

La ruta causal reproducida es NPE durante el paso 25480 → cierre → diagnóstico
con el tiempo almacenado 25479 → rechazo cronológico. El gestor verifica
`event.time < lastEventTime` **antes** de entregar a handlers/escritor; acepta
empates. El evento rechazado y su predecesor no se identifican en el stack histórico,
pero el informe de cierre, el prefijo XML y la regresión reproducen ese defecto
concreto. No hay evidencia de una causa física independiente, de una alteración
del orden por entrega asíncrona ni de un fallo del escritor/lector. El validador
Python también permite tiempos iguales; no intervino en esta excepción Java.

`SimZ1Diagnostics.notifyMobsimBeforeCleanup` toma ahora el reloj actual de QSim
para fechar **la observación de cierre**, conservando `lastCompletedStepTime` y
`observationPhase=before_cleanup`. Los informes periódicos llevan `after_step`.
No se cambia el reloj, ningún evento físico, la cadencia, FIFO, rutas, decisiones
ni MATSim; tampoco se ordenan eventos, se relaja el validador o se captura el fallo
para continuar. Los contadores del cierre siguen siendo observaciones recibidas
hasta ese momento: con handlers pendientes no son totales finales certificados.

`SimZ1EventChronologyCheck` falló primero con el stack original sobre el código
anterior. Tras la corrección pasan cuatro productores concurrentes, uno/dos workers
de eventos, tiempos iguales, cierre normal/interrumpido, handlers retenidos con
latches, identidad persona/vehículo, orden por vehículo, contadores de llegada,
transición, WAIT/FORCE/retiro y cierre repetido sin duplicados. Un evento realmente
atrasado sigue fallando (ese caso negativo imprime un ERROR esperado). Construye
solo un portador de reloj y eventos, sin motores, población, `QSim.run` o Controller.

Antes de autorizar 150000–250000 agentes, ejecutar manualmente nuevas carpetas de
10, 100 y 1000 agentes, una iteración y cuatro hilos QSim; contrastar además con un
hilo y semillas registradas. Exigir cierre completo y validación de cronología,
identidades, transiciones físicas, entradas/salidas y balance de llegados,
pendientes y retirados. Medir movimientos forzados y congestión sin confundirlos
con éxito de compilación. Estas regresiones no certifican estabilidad masiva ni
validan las cuatro clases OD de una corrida que no las utilizaba.

[SimZ1Diagnostics](../src/main/java/gt/edu/uvg/sim/zona1/SimZ1Diagnostics.java) publica progreso cada
60 s simulados y usa watchdog de 5 s de pared por defecto. Distingue avance, CPU, llegadas, activos,
esperas y causas. `findDeadlockedThreads` aporta evidencia de ciclos JVM; silencio de consola,
lentitud o colas persistentes no bastan para diagnosticar deadlock. Conservar primera excepción y fase:
un error secundario de shutdown no reemplaza la causa primaria.

La revisión histórica de nueve fallos distinguió seis excepciones relacionadas con `toQueues` sin
evidencia suficiente para atribuirlas a un único mecanismo y tres incompatibilidades de configuración.
`run-780058964` fue interrumpida por `KeyboardInterrupt`; el gzip truncado de su iteración incompleta
no demuestra que un EOF originara la interrupción. Los logs originales se preservan, con sus rutas,
en los documentos archivados. No se declara resuelta retrospectivamente una causa no demostrada.

<a id="opciones"></a>
## Opciones avanzadas

Opciones verificadas en [add_generation_options](../python/generate_montecarlo_z1.py).
Omitir interruptores de física conserva valores explícitos del XML de entrada.

| Grupo | Flags / elección |
|---|---|
| Temporal | `--temporal-profile`, `--hourly-weights`, `--trips-per-person`, `--drain-seconds`. |
| Señales/carriles | `--signals`/`--no-signals`, `--use-lanes`/`--no-use-lanes`, `--qsim-threads`. |
| Offsets | `--signal-offset-policy preserve\|zero\|hash`, `--signal-offset-seed`. |
| Prioridad | `--unsignalized-priority`/`--no-unsignalized-priority`, `--priority-stop-seconds`, `--priority-max-yield-seconds`, `--priority-classification`, `--priority-conflicts`. |
| Reruteo | `--within-day-routing`/`--no-within-day-routing`, `--routing-share`, `--reroute-budget`. |
| Incidentes | `--incidents`/`--no-incidents`; conservar calendario/semilla al comparar tratamientos. |
| Espacial | `--od-mode`, `--zone-boundary`, `--od-osm`, `--od-mix` o `--od-shares`, `--od-hourly-profiles`; restricciones en [gateways](#gateways). |

<a id="historia"></a>
## Limitaciones e historia conservada

Demanda, capacidad ideal, planes semafóricos, perfiles, prioridades y movimiento visual contienen supuestos
sin calibración de campo. Señales/carriles configurados no completan restricciones OSM omitidas. Gateway no modela
viaje exterior y una cola dibujada no demuestra posición física, rebase o capacidad sostenible.

La corrida histórica 100k tiene horizonte configurado 90000 s (25 h) y último evento 90001 s.
Su carpeta protegida es `scenarios/zona1/montecarlo/run-052734f90d154b23bb8899cd0bbc3ef4`,
identidad `simz1-3dd8683a7d5e44c0944587feff4fe0c8`. Usó semillas 20261016, `full-day`, drenaje 3600 s,
incidentes y reruteo apagados. El informe `SIMZ1_100K_RUN.md` se conserva completo en el [archivo](#conservacion).
Sus cortes publicados conservan denominadores y tiempos distintos:

| Corte de la misma corrida histórica | Llegadas acumuladas | Activos/pendientes según el corte | Movimientos forzados acumulados |
|---|---:|---:|---:|
| 86400 s, dentro del experimento de 25 h | 85674 | 14326 activos | 249104 |
| 90000 s, fin configurado | 87405 | 12595 activos | 250453 |
| 90001 s, cierre del archivo | 87407 | 12593 pendientes finales | 250453 |

La vista diaria 0..86400 no convierte el experimento en una nueva corrida de 24 h ni inventa llegadas a medianoche.
El HUD declara horizonte fuente. La evidencia local `evidence/100k-historical/` permanece separada de resultados
nuevos; no se reejecutó ni reprocesó al redactar este documento.

Los 250453 forzados impiden presentar ese cierre como demostración de estabilidad física. El conteo
167484 de una etapa previa usaba otra clasificación de prioridad: no es un control comparable. La matriz
histórica de señales ensayó 32 combinaciones de señales/carriles/reruteo/incidentes/hilos 1 o 4 más cuatro
controles: 36 controladores, 72 iteraciones, ocho personas, semilla 20261004, horizonte 43..500 s.
Acumuló 504 llegadas, 72 pendientes, 120 forzados y 36 pasos en ámbar; no informó abortos tempranos
ni rutas desconectadas. Su incidente exógeno cambió 0.05→10 m/s entre 43 y 180 s. Son resultados
de fixtures antiguas, no una prueba ejecutada por esta reorganización ni validación de tráfico masivo.

Los defaults antiguos de 150000..250000 personas, drenaje 3600 s, escenarios 09..15 y clasificación
`osm-name-orientation/conservative` son antecedentes, no las instrucciones actuales. Lo mismo aplica
a referencias personales de Maven, carpetas de corrida y encabezados antiguos que decían “vigente”.

<a id="conservacion"></a>
## Conservación de documentación y evidencia

Solo [README.md](../README.md) y este documento son las guías principales de SimZ1. Los informes
retirados se preservaron **antes de retirarlos**, incluidos los archivos sin seguimiento, en
[pre-consolidation-20261016.zip](../evidence/documentation/pre-consolidation-20261016.zip).
El [manifiesto](../evidence/documentation/manifest-20261016.json) registra ruta original, condición Git,
tamaño y SHA-256 de cada uno de los 41 Markdown respaldados. El ZIP conserva los bytes y rutas originales;
también incluye el manifiesto. No depende del reflog ni de que los archivos hubieran estado versionados.
La excepción específica en `.gitignore` permite incorporar `evidence/documentation/` al repositorio;
los demás resultados generados siguen excluidos. El archivo debe publicarse junto con esta documentación.

La [matriz de consolidación](../evidence/documentation/consolidation-20261016.json) relaciona cada
documento con sus secciones actuales o su destino histórico. Se conservaron en la guía los contratos,
fórmulas, defaults, decisiones y límites científicos. Las tablas extensas de experimentos, IDs, hashes,
logs, mediciones y anexos literales repetidos quedan íntegros en el ZIP, sin copiarse como nuevas guías.
Para consultar un original, extraer a una carpeta nueva fuera de la documentación activa y verificar
su SHA-256 con `Get-FileHash -Algorithm SHA256`. Sus enlaces relativos se interpretan desde su ruta original;
sus comandos no sustituyen los del README actual.

| Documentos retirados (nombres dentro del ZIP) | Referencia vigente |
|---|---|
| `SIMZ1_RUNS`, `SIMZ1_RUN_DIRECTORIES`; `docs/arquitectura`, `docs/ejecucion`, `docs/SIMZ1_INSTALL` | [Arquitectura](#arquitectura), [ejecución](#ejecucion), [instalación](#regeneracion), [diagnóstico](#diagnostico). |
| `SIMZ1_DEMAND`, `SIMZ1_TEMPORAL`; `docs/demanda` | [Demanda](#demanda), [gateways](#gateways). |
| `SIMZ1_REROUTING`, `SIMZ1_REROUTING_HISTORY`; `docs/enrutamiento` | [Enrutamiento](#enrutamiento), [diagnóstico](#diagnostico). |
| `SIMZ1_LANES`; `docs/carriles` | [Carriles y capacidad](#carriles). |
| `SIMZ1_SIGNALS`, `SIMZ1_SIGNALS_MATRIX`, `SIMZ1_OFFSETS_REPLAY`; `docs/semaforos` | [Semáforos](#semaforos), [validación](#validacion), [historia](#historia). |
| `SIMZ1_PRIORITY`, `SIMZ1_PRIORITY_REALISTIC`; `docs/prioridades` | [Prioridad](#prioridad). |
| `SIMZ1_REPLAY_MOTION`, `SIMZ1_PROGRESSIVE_MOTION` | [Movimiento](#movimiento), [colas](#colas). |
| `SIMZ1_PAGED_REPLAY`, `SIMZ1_CONTINUOUS_REPLAY`, `SIMZ1_COMPACT_UI`, `SIMZ1_SELECTION`; `docs/visualizacion` | [Visor/API](#visor), [colas y selección](#colas). |
| `SIMZ1_TRIP_DISTRIBUTIONS`, `SIMZ1_100K_RUN`; `docs/metricas` | [Métricas](#metricas), [validación](#validacion), [historia](#historia). |
| `scenarios/zona1/ESCENARIO_HISTORICO` | [Red](#red), [historia](#historia); etapas antiguas conservadas en el archivo. |

Todos los nombres de la primera columna tienen extensión `.md`. Los README anteriores también están
respaldados. Los ocho documentos de laboratorios se trasladaron como documentos históricos independientes.
La consolidación no recalculó inventarios ni reemplazó evidencia científica: `docs/maintenance/` conserva
la matriz de pruebas y el inventario anterior como snapshots, no como descripción automática del árbol futuro.

La evidencia local `evidence/100k-historical/` y `evidence/replay/RENDIMIENTO_HISTORICO.md`
se conserva sin alteraciones. Está excluida de Git por las reglas generales y **no es necesaria para el inicio rápido**;
el ZIP conserva los informes que describen sus resultados. Los artefactos crudos referenciados en esos informes
pueden no acompañar un clon: para replicar una auditoría histórica hay que solicitar al custodio la carpeta de
corrida y los archivos exactos citados, verificar sus hashes y mantener su procedencia. No se descargan ni
reconstruyen a partir del informe. El respaldo previo `evidence/maintenance/readme-before-consolidation.json`
y los benchmarks en `audits/continuous-replay/` siguen en su ubicación original, también local.

<a id="laboratorios"></a>
## Laboratorios históricos

Estos documentos conservan sus experimentos y comandos históricos; no son pasos de instalación de SimZ1.
Las rutas de comandos se interpretan desde la raíz del repositorio. Los nombres antiguos emitidos por
comentarios/atributos de los laboratorios se encuentran ahora en esta carpeta; no se modificó su código.

| Documento | Alcance independiente |
|---|---|
| [LAB05_MINI_CITY.md](laboratorios/LAB05_MINI_CITY.md) | Mini-ciudad y experimento Lab05. |
| [LAB06_ZONA1.md](laboratorios/LAB06_ZONA1.md) | Escenario histórico Lab06. |
| [LAB07_CALIBRATION.md](laboratorios/LAB07_CALIBRATION.md) | Calibración experimental Lab07. |
| [LAB07_MULTILANE.md](laboratorios/LAB07_MULTILANE.md) | Carriles del experimento Lab07. |
| [LAB08_FOCAL_AGENT.md](laboratorios/LAB08_FOCAL_AGENT.md) | Agente focal Lab08. |
| [ZONA1_NETWORK.md](laboratorios/ZONA1_NETWORK.md) | Generación geométrica histórica; no OSM SimZ1. |
| [TRAFFIC_PERFORMANCE_REPORT.md](laboratorios/TRAFFIC_PERFORMANCE_REPORT.md) | Medidas de rendimiento de laboratorio. |
| [TRAFFIC_VISUALIZATION.md](laboratorios/TRAFFIC_VISUALIZATION.md) | Visualización histórica de laboratorio. |

[AGENTS.md](../AGENTS.md) se conserva en la raíz y rige la separación de escenarios.

<a id="diagnostico-visibilidad-20261021"></a>
## Diagnóstico acotado de visibilidad — 21/10/2026

Esta inspección aplica únicamente a SimZ1. No ejecutó MATSim, poblaciones, servidores,
navegadores ni exportaciones de replay. No modificó corridas ni física, geometría de producción,
algoritmo de colas, almacenamiento concurrente o cronología de eventos. Las pruebas descritas
abajo están **preparadas, no ejecutadas**. No se atribuyen los casos a las capturas del usuario.

### Identidad y cliente

La fuente local inspeccionada es `runtime/simz1-227187-direct/webgl-continuo`,
`run_id=simz1-0dd152dabbc24d1d84d9b738c449cc35`, iteración **0**, **227187** personas,
fuente **sqlite-direct-v1**. Huellas verificadas leyendo metadata:

| Artefacto | SHA-256 |
|---|---|
| Manifiesto nativo | `2d93aa7cd197200761917e6cf0c1c7d2848aaeb5102b502e744799bd8814f456` |
| Manifiesto continuo | `2d0c323fc2505628c4f51cb94d393c4b953b9644bd5ef24c49a7d7b72487780b` |
| Manifiesto SQLite directo | `d61ba3a0bb1a7f586a4180b4396097d770b6afeecf7ee83f9099278a741ba17b` |

No se recalcularon hashes del SQLite de 24.9 GB ni de eventos/planes. El extractor verificó
identidad SQLite, tamaño/mtime y hashes de red/carriles efectivos pequeños. La plantilla fija
deck.gl **9.1.14**. MATSim declarado/classpath local: **15.0**, compilación objetivo Java **25**.

La URL indicada por el usuario es `http://127.0.0.1:8793/index.html`; la consulta HTTP desde
el entorno del agente no conectó. Por tanto, corrida, fuente y JavaScript de esa pestaña siguen
**sin verificar**. Antes de los cambios de diagnóstico, el HTML local almacenado coincidía con
la aplicación ensamblada desde HEAD al normalizar CRLF a LF: SHA-256
`0465565035c81bf0a338848f8fc7f390c51116128ed43641be483a3bc9ec27d2`.
Eso descarta un desfase de ese archivo local respecto del código inicial; no identifica la pestaña.

`serve_simz1_continuous.handler_for()` ensambla `application_html()` una vez al crear el handler,
sirve esa copia con `Cache-Control: no-store` y no lee el antiguo `index.html` para responder.
Un servidor iniciado antes de editar conserva su copia. Recargar la pestaña no actualiza ese proceso.
El nuevo `window.simz1ClientBuild.source_sha256` identifica las ocho fuentes cargadas; el contrato
`replay_source` se añade en memoria después de validar la configuración histórica. Ningún manifiesto
histórico se reescribe. Un fingerprint ausente significa versión no identificada, no una coincidencia.

### Casos y clasificación

[Fixture histórico](../python/fixtures/simz1-visibility-history.json): **3 vehículos**, **7 segmentos**,
**15 eventos de carril**, **16 observaciones** antes/durante/después. Conserva `person_id`, `trip_id`,
identidad de corrida, enlaces, carriles, tiempos, posiciones centrales y procedencia. Las posiciones
son evaluaciones del `Motion_Plan` almacenado, no observaciones de una carrocería WebGL.
Las dimensiones **4.5 × 1.8 m** son la referencia visual actual; dimensiones físicas no leídas quedan
`null`. Posición renderizada y visibilidad de navegador permanecen explícitamente desconocidas.

| Caso | Evidencia y clasificación | Consecuencia / corrección pendiente |
|---|---|---|
| `z1_43360`, viaje `z1_43360:trip:0001` | A 123.999 s hay posición en `osm_58692343_35_forward`. Segmento SQLite 939, enlace `osm_58692343_36_forward`, `[124,125)`, carril `.original`, tiene `Motion_Plan.status=unavailable`, `distance_exceeds_speed_cap`: 61.3095 m frente a 8.333 m/s. | **Intervalo cerrado con posición desconocida**: `motionAt()` lo rechaza; puede desaparecer un segundo antes de Arrival=125. No es una llegada adelantada ni evidencia de movimiento forzado. No rellenar ni modificar su plan histórico. |
| `z1_38616`, viaje `z1_38616:trip:0001` | Antes: 38.999 s en `osm_390137502_7_forward`; durante `[39,46)` en `_8_forward`, 2.651 m, espera `priority_stop` registrada 41–45; después: 46 s en `osm_404273844_0_forward`. | **Candidato a desborde/colocación**. La pertenencia nativa es conocida. Falta el roster completo de vecinos para afirmar omisión o posición final; el enlace anterior podría aportar soporte. |
| `z1_167074`, viaje `z1_167074:trip:0001` | Posición a 168.999 s en `osm_58692343_4_forward`; segmento 1684 en `osm_420120096_27_forward` tiene `[169,169]` y `zero_duration_positive_distance`; Arrival=169, completed. | **Llegada real**. No es desaparición interior ni intervalo que deba alargarse. El diagnóstico ahora distingue `arrived` de `unknown_interval`. |
| Espera en enlace sintético de 2 m | [Fixture short-hold](../python/fixtures/simz1-visibility-geometry-short-hold.json), intervalo positivo `[10,12)`; cuerpo 4.5 m, sin soporte previo compatible. | **Ocultación por desborde**: `storage_exceeded` conserva identidad omitida; no llegada. Solución de representación pendiente, sin alterar cola. |
| Dos movimientos libres que se cruzan | [Fixture free-crossing](../python/fixtures/simz1-visibility-geometry-free-crossing.json); `envelopesOverlap` y `Visual_Unresolved_Conflicts`. | **Solapamiento de colocación**: se conservan ambos cuerpos cuando no hay apoyo para moverlos. No confirma choque ni incompatibilidad física QSim. |
| Centro visual desplazado fuera del dominio | [Fixture spatial-offset](../python/fixtures/simz1-visibility-geometry-spatial-offset.json): eje dentro, offset lateral fuera. | **Colocación/recorte espacial**, `spatial_filter`; no equivale a una salida real. Diagnóstico compara centro nativo y desplazado. |
| Falta el líder que ya salió de la ventana | [Fixture window-roster](../python/fixtures/simz1-visibility-geometry-window-roster.json): mismo seguidor detenido a t=30, estación 89 m con líder histórico y 95.5 m sin él. | **Contexto de cola no cargado**, diferencia algebraica 6.5 m. `queueRoster()` reconstruye anclas con vecinos disponibles; SQL aporta vecinos del mismo viaje, no todos los otros vehículos del hold. Explica un posible salto/hueco; no atribuido a captura. |

La búsqueda inicial se limitó a PK **1..2048**, unos **2.05 MB comprimidos**: dos planes
unavailable positivos terminales, cuatro instantáneos terminales y dieciocho holds en enlaces
menores de 4.5 m. No encontró un unavailable intermedio con reaparición. No autoriza extrapolar
tasas al resto de la corrida. Los cuatro fixtures sintéticos prueban rutas específicas del código;
su reproducción ejecutable está pendiente.

En el fixture de roster, el líder ya salió a t=20 pero el seguidor conserva el ancla de su
hold hasta su salida nativa. Queda un hueco de 6.5 m aunque esté detenido. Esta fijación evita
inventar avances dentro de la cola; al perder ese líder del contexto de otra ventana, el ancla
se recalcula y puede saltar. Son dos efectos distintos de la misma información incompleta:
la falta de trayectoria nativa dentro de la cola y la dependencia del contexto cargado.

**Bordes temporales:** los intervalos activos usan `[start,end)`, las ventanas se reemplazan,
el contexto no entra al índice activo y SQL selecciona por PK. No se confirmó identidad duplicada
entre ventanas. Mientras falta la siguiente, el reloj conserva el frame anterior. El
[control temporal](../python/fixtures/simz1-visibility-temporal-controls.json) separa ese buffering,
el borde 120 s y un hueco real sin inventar una llegada. Un intervalo cero entre dos enlaces puede
limitar `observedConnection`; no hay atribución histórica comprobada en esta muestra.

**Zoom y cuerpos:** la capa usa `Visual_Body_Path` rígido, ancho en metros y `widthMinPixels:0`.
No se encontró evidencia de inflación de carrocerías por un mínimo en píxeles. Los contornos de
selección sí usan píxeles y no constituyen carrocerías. Aumentar hitbox no corrige estos mecanismos.
**Movimiento forzado QSim:** no confirmado; ni espera, cero duración, velocidad imposible ni
`unresolved` sustituyen un evento nativo explícito de movimiento forzado.

### Cambios aplicados y comprobaciones pendientes

| Cambio | Archivo | Alcance |
|---|---|---|
| Huella del cliente y fuente servida | `python/simz1_continuous_replay.py` | Metadata en memoria; conserva manifiestos/config originales. |
| Iteración, fuente, build y evidencia espacial en diagnóstico; llegada explícita; `traceSelectedVehicle()` | `python/visualizador_z1_controls.js` | Solo diagnóstico; no fetch/seek desde trazas. |
| Filtro diagnóstico usa enlace permitido y centro, igual que render | mismo archivo | Coherencia defensiva. El loader ya rechaza enlaces no permitidos; no se presenta como causa histórica confirmada. |
| Inspectores de cliente/muestra y fixtures/pruebas | `python/inspect_simz1_*.py`, `python/test_simz1_visibility_*.cjs`, `python/test_simz1_client_identity.py`, `python/fixtures/simz1-visibility-*.json` | Lecturas limitadas o datos pequeños; sin regenerar replay. |

Ejecutado: lecturas, comparación de fuentes/manifiestos, extracción acotada y comprobaciones de
sintaxis/diff. **Ninguna suite nueva ejecutada**. Los comandos siguientes son para ejecución manual;
no arrancan servidor ni navegador y no usan corridas para generar poblaciones. Las pruebas Node
usan VM y dobles en memoria, no GPU/WebGL. Los controles positivos mantienen las omisiones y
solapamientos explícitos; un `PASS` no significaría que quedaron corregidos.

```powershell
Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Stop'
$simz1Python = Join-Path (Get-Location).Path '.venv\Scripts\python.exe'
& $simz1Python -B .\python\test_simz1_client_identity.py
if ($LASTEXITCODE -ne 0) { throw 'Fallaron contratos de identidad del cliente.' }
foreach ($simz1Test in @(
    'python/test_simz1_visibility_geometry.cjs',
    'python/test_simz1_visibility_temporal.cjs',
    'python/test_simz1_visibility_diagnostics.cjs',
    'python/test_simz1_visibility_history.cjs',
    'python/test_simz1_continuous_bootstrap.cjs'
)) {
    node $simz1Test
    if ($LASTEXITCODE -ne 0) { throw "Falló $simz1Test" }
}
```

Esperado: pruebas Python `OK`, suites Node sin error/código 0. Para ver trazas sintéticas completas:

```powershell
Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
node .\python\test_simz1_visibility_geometry.cjs --evidence
if ($LASTEXITCODE -ne 0) { throw 'Falló reproducción geométrica.' }
Get-Content .\python\fixtures\simz1-visibility-history.json -Raw
```

Comprobar **el servidor ya abierto** frente al candidato local. Si reporta otra identidad,
esa identidad es la del endpoint consultado; no se reemplaza ni se asume esta corrida:

```powershell
Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
.\.venv\Scripts\python.exe -B .\python\inspect_simz1_client.py `
  --replay-dir .\runtime\simz1-227187-direct\webgl-continuo `
  --url http://127.0.0.1:8793/index.html
if ($LASTEXITCODE -eq 2) { Write-Warning 'HTTP/cliente/fuente aún no coinciden o no pudieron verificarse; revisar JSON.' }
elseif ($LASTEXITCODE -ne 0) { throw 'Falló validación de metadata local.' }
```

Esperado, solo si ese endpoint corresponde al candidato y ejecuta estas fuentes: `identity_matches`,
`application_matches_current`, `source_matches` verdaderos y código 0. Un servidor anterior a estos
cambios necesita reinicio manual por su propietario para incorporar el diagnóstico; no se inició
ni detuvo ningún proceso aquí. La comparación HTTP no prueba qué documento cargó una pestaña vieja.

### Clic y copia desde la consola del navegador

En el visor ya abierto, pausar y hacer clic en el vehículo. En DevTools ejecutar lo siguiente;
`copy()` pertenece a la consola del navegador. Funciona con los métodos anteriores y añade
proveniencia cuando está disponible. No mueve el reloj ni carga ventanas para completar huecos.

```javascript
var apiZ1 = window.simz1Continuous;
apiZ1.pause();
var stateZ1 = apiZ1.getState();
var vehicleZ1 = stateZ1.selectedVehicleId;
if (!vehicleZ1) throw new Error('Haz clic en un vehículo antes de copiar.');
var nowZ1 = apiZ1.diagnoseVehicle(vehicleZ1, stateZ1.current);
var intervalZ1 = nowZ1.interval || [stateZ1.current, stateZ1.current];
var timesZ1 = [...new Set([intervalZ1[0] - .001, intervalZ1[0], stateZ1.current,
  intervalZ1[1] - .001, intervalZ1[1], intervalZ1[1] + .001])].sort((a,b) => a-b);
copy(JSON.stringify({url:location.href,loaded_client:window.simz1ClientBuild ?? null,
  deck_gl_version:window.deck?.VERSION ?? null,run_id:stateZ1.run_id,iteration:stateZ1.iteration,
  displayed_time:stateZ1.current,vehicle_id:vehicleZ1,
  trace:apiZ1.traceVehicle(vehicleZ1,timesZ1)}, null, 2));
```

Para obtener hasta cinco afectados sin conocer IDs (incluidos omitidos que no se pueden clicar):

```javascript
var apiZ1 = window.simz1Continuous;
apiZ1.pause();
var frameZ1 = apiZ1.getVisualDiagnostics();
var idsZ1 = [...new Set([
  ...frameZ1.records.filter(r => !r.visible).map(r => r.vehicle_id),
  ...frameZ1.collisions.filter(c => c.resolution !== 'resolved_spacing')
    .flatMap(c => c.vehicles.map(v => v.vehicle_id))
])].slice(0,5);
copy(JSON.stringify({url:location.href,loaded_client:window.simz1ClientBuild ?? null,
  run_id:frameZ1.run_id,iteration:frameZ1.iteration,time:frameZ1.time,
  replay_source:frameZ1.replay_source,counts:frameZ1.counts,
  traces:idsZ1.map(id => apiZ1.traceVehicle(id,[frameZ1.time-.1,frameZ1.time,frameZ1.time+.1]))},null,2));
```

Verificar además que la pestaña cargó el mismo build que sirve ahora HTTP, sin abrir otro navegador:

```javascript
var htmlZ1 = await (await fetch('/index.html',{cache:'no-store'})).text();
var matchZ1 = htmlZ1.match(/window\.simz1ClientBuild=Object\.freeze\((\{[^\n]*?\})\);<\/script>/);
var servedZ1 = matchZ1 ? JSON.parse(matchZ1[1]) : null;
var configZ1 = await (await fetch('/api/config',{cache:'no-store'})).json();
copy(JSON.stringify({url:location.href,loaded:window.simz1ClientBuild ?? null,served:servedZ1,
  loaded_matches_served:!!servedZ1 && !!window.simz1ClientBuild &&
    servedZ1.source_sha256 === window.simz1ClientBuild.source_sha256,
  server_identity:configZ1.continuous,replay_source:configZ1.replay_source ?? null},null,2));
```

Pendientes específicos: confirmar endpoint/pestaña contra estas huellas; ejecutar fixtures;
capturar roster real de un conflicto o reaparición interior. `window_not_loaded` no debe convertirse
en llegada, `spatial_filter` no demuestra salida del dominio y `unknown_interval` no autoriza
extrapolación. No se modifica física ni algoritmo de cola para hacer desaparecer estos diagnósticos.

<a id="catalogo-visual-vehiculos"></a>
## Catálogo visual de nombres y dimensiones — 21/10/2026

`SimZ1VehicleCatalog`, en [simz1_visual_lanes.js](../python/simz1_visual_lanes.js), es la fuente
compartida de etiquetas y dimensiones para cuerpo rígido, colocación, envolvente, tarjeta y diagnóstico.
Viaja en el módulo de geometría ya embebido por el visor continuo: no añade peticiones HTTP ni requiere
regenerar HTML/SQLite. Su versión es `simz1-vehicle-presentation-v1`; el fingerprint del cliente incluye
el módulo. Se conserva el trabajo diagnóstico anterior.

La evidencia que motivó el cambio está en `simz1_visual_queues.js`: todas las carrocerías y distancias
entre centros usaban 4.5 × 1.8 m. Además, `simz1_agent_types.vehicle_types_xml()` escribe esos mismos
defaults QSim para varios tipos y los marca como no medidos. No se modifica ese generador, sus tipos,
PCU, perfiles, capacidad ni ninguna corrida. Las dimensiones aquí son **representación visual**,
independiente de las dimensiones/configuración físicas del escenario. Cambiar estas últimas requiere
otra versión del escenario.

| Identificación registrada / alias de presentación | Familia | Perfil | Etiqueta exacta |
|---|---|---|---|
| `Normal` | automóvil | Normal | Carro |
| `Liebre` | automóvil | Liebre | Carro liebre |
| `Tortuga` | automóvil | Tortuga | Carro Tortuga |
| `Motocicleta lenta` o `Motociclista` con perfil Tortuga | motocicleta | Tortuga | Moto tortuga |
| `Motocicleta normal` o `Motociclista` | motocicleta | Normal | Moto |
| `Motocicleta rápida` o `Motociclista` con perfil Liebre | motocicleta | Liebre | Moto Liebre |
| `TransportePesado` / `Transporte pesado` | camión | registrado, si existe | Transporte pesado |
| `TransitBus` o tipo vehicular explícito `Transporte público` | bus | registrado, si existe | Transporte público |

Se normalizan acentos, espacios y mayúsculas exclusivamente para buscar alias. Ningún `person_id`,
`vehicle_id`, `trip_id`, `Agent_Type`, `Vehicle_Type`, `Profile` ni `Motion_Plan` se reescribe.
`Driving_Profile` explícito puede separar el estilo de un tipo histórico compuesto. El tipo vehicular
registrado tiene prioridad sobre la categoría personal; un tipo desconocido conserva su etiqueta cruda,
familia `unknown` y dimensiones asumidas identificadas como tales. IDs, PCU y velocidades nunca infieren
una moto o un bus; `Motion_Plan.profile` tampoco se usa para clasificar personas.
El diagnóstico conserva el perfil crudo e indica si el perfil de presentación procede de
`Driving_Profile`, `Profile`, un alias o un default de presentación; este último no se declara observado.

`Agent_Type=TransportePublico` sin tipo vehicular identifica un **pasajero**, no `TransitBus`; su catálogo
no produce dimensiones de bus ni crea vehículos. Si ya existe un movimiento con `vehicle` registrado,
se conserva esa identidad con geometría desconocida de referencia, sin ocultarla por la etiqueta personal.
Una corrida histórica con tres perfiles de automóvil
sigue teniendo los mismos vehículos. `Transit_Operator`/`Operator`/`operator` y
`Transit_Service`/`Service`/`service` se conservan como metadatos, sin añadir texto a la etiqueta exacta
ni campos a la tarjeta.

### Magnitudes independientes

| Familia | Longitud × ancho asumidos | Procedencia |
|---|---|---|
| Automóvil | 4.5 × 1.8 m | `assumed:simz1-vehicle-presentation-v1:car` |
| Motocicleta | 2.1 × 0.8 m | `assumed:simz1-vehicle-presentation-v1:motorcycle` |
| Camión | 10 × 2.5 m | `assumed:simz1-vehicle-presentation-v1:truck` |
| Bus rígido | 12 × 2.5 m | `assumed:simz1-vehicle-presentation-v1:bus` |
| Desconocido | 4.5 × 1.8 m, sin reclasificarlo | `assumed:simz1-vehicle-presentation-v1:unknown` |

Son supuestos explícitos del catálogo, **no medidas de campo ni valores derivados de PCU**. Si un registro
ya aporta `Vehicle_Dimensions={length_m,width_m,source,...}`, se usan sus valores positivos finitos y su
procedencia. `assumed:true` identifica una dimensión suministrada como supuesto; una dimensión registrada
de un modelo tampoco acredita medición real. Campos incompletos, no positivos o sin `source` se rechazan.
No se leen nuevamente archivos masivos para completar dimensiones históricas ausentes y no se reexportan
sus segmentos. Las dimensiones genéricas del generador no se presentan como geometría medida de motos.

1. **Cuerpo:** longitud/ancho anteriores o valores explícitos del registro. Eje rígido de dos puntos,
   sin deformarlo en giros. El contorno de selección se obtiene de ese mismo eje y ancho.
2. **Representación:** `gap_m=2` longitudinal total y `lateral_clearance_m=0.1` por lado, separados
   del cuerpo. Envolvente: `L + gap`, `W + 2*lateral`. Para dos vehículos, separación entre centros:
   `(L_delantero + L_trasero)/2 + gap`. Las reservas, soporte y caché usan ahora las dimensiones
   de cada vehículo, manteniendo orden nativo y reglas de espera. El ajuste de márgenes no acepta
   `car_length_m`/`car_width_m` como si fueran separaciones.
3. **Selección:** 8 píxeles CSS para mouse y 18 para touch alrededor del contorno. Una moto pequeña
   puede seleccionarse sin aumentar su longitud, ancho, envolvente o espacio reservado.
4. **Física:** PCU, límites, capacidad, planes y tiempos siguen siendo datos originales, independientes.

La comprobación de ancho usa `ancho + 2*margen_lateral <= ancho_del_carril`. Sustituye el porcentaje
decorativo `0.82` usado antes como umbral de cuerpo: no concede almacenamiento ni cambia validaciones
nativas. Un bus de 2.5 m con dos márgenes de 0.1 m cabe en un carril visual de 3 m; no cabe en uno de
2.6 m y conserva el diagnóstico de geometría insuficiente. El SAT de conflictos recibe las dimensiones
reales del **modelo visual**, no un automóvil uniforme.

La capa de carrocerías continúa con `widthUnits:'meters'` y `widthMinPixels:0`; zoom y contornos en
píxeles no cambian el espacio de colocación. La prueba proyecta la misma moto a tres escalas; la
comprobación GPU a zoom máximo sigue pendiente de ejecución manual.

**Articulados:** con `Vehicle_Type=TransitBus` y `Vehicle_Articulated=true` (o
`Vehicle_Dimensions.articulated=true`), se distingue `rigid_total_envelope_articulation_unknown`.
Sin datos de articulación se conserva una envolvente total rígida, 18 × 2.5 m asumidos o dimensiones
explícitas, con limitación diagnóstica. No se finge reconstrucción de articulaciones ni se dibujan
buses como cintas. Un modelo fiel de módulos y bisagras queda pendiente de esas poses; la aproximación
no representa su barrido real de giro.

### Tarjeta, diagnóstico y pruebas preparadas

Se mantienen los seis campos: nombre, tipo visible, velocidad actual, velocidad máxima, tiempo
transcurrido y duración estimada; también `Personas generadas: N`. Catálogo y detalles de dimensiones
quedan en `simz1Continuous.getVehicleCatalog()` y `diagnoseVehicle(...).vehicle_presentation`, con la
envolvente en `representation_envelope`; no se añaden campos técnicos a la tarjeta.

Archivos de esta entrega: `python/simz1_visual_lanes.js`, `python/simz1_visual_queues.js`,
`python/visualizador_z1_controls.js`, `python/test_simz1_vehicle_card.cjs`,
[test_simz1_vehicle_presentation.cjs](../python/test_simz1_vehicle_presentation.cjs),
[fixture del catálogo](../python/fixtures/simz1-vehicle-presentation.json), `README.md` y este documento.
El fixture es sintético, no una población nueva. Pruebas preparadas: alias, tipo desconocido, PCU
independiente, dimensiones explícitas inválidas, cola mixta sin ocultar sus cuatro vehículos,
cuerpo/contorno/envolvente, moto seleccionable en tres escalas, carril estrecho, metadatos de servicio,
pasajero sin bus, envolvente articulada explícita y preservación de IDs. La prueba existente de tarjeta
se actualiza solo en las etiquetas esperadas; conserva seis campos y contador.

Ejecutado: lectura de código y configuración, validación de sintaxis JS/JSON y `git diff --check`.
**No se ejecutaron suites, simulaciones, servidores, navegadores ni exportaciones.**

```powershell
Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Stop'
foreach ($simz1Test in @(
    'python/test_simz1_vehicle_presentation.cjs',
    'python/test_simz1_vehicle_card.cjs',
    'python/test_simz1_visual_queues.cjs',
    'python/test_simz1_queue_safety.cjs',
    'python/test_simz1_rigid_vehicles.cjs',
    'python/test_simz1_vehicle_picking.cjs',
    'python/test_simz1_vehicle_focus.cjs',
    'python/test_simz1_continuous_bootstrap.cjs'
)) {
    node $simz1Test
    if ($LASTEXITCODE -ne 0) { throw "Falló $simz1Test" }
}
git diff --check
```

Esperado: cada suite termina sin error/código 0; cola mixta con cuatro cuerpos visibles y espacio
de paragolpes de 2 m, sin cambios en PCU/identidades; tarjeta de seis campos y contador intactos.
Es una expectativa pendiente, no un resultado aprobado. Para comprobar cliente y corrida servidos,
usar el inspector y las huellas del [diagnóstico anterior](#diagnostico-visibilidad-20261021).
No se presupone qué corrida muestra una captura ni se inicia/reinicia aquí ningún servidor.

El [diseño posterior de incidentes sintéticos (Prompt 7)](SIMZ1_INCIDENT_DESIGN.md)
incluye auditoría nativa, candidatos pendientes, contrato, semilla independiente
y pruebas puras. No activa un detector real ni cambia carriles, física o históricos.
La [revisión de consecuencias del Prompt 8](SIMZ1_INCIDENT_CONSEQUENCES.md)
incluye contrato Java/Python/visor y pruebas aisladas. Conserva la función
deshabilitada: el cierre por carril requiere un adaptador nativo completo;
un bloqueo solo en el nodo no preservaría la inmovilización ni las llegadas.

<a id="dimensiones-cuerpos-simz1"></a>
## SimZ1: dimensiones, separación y selección de carrocerías (22/10/2026, Prompt 6)

La revisión conserva las poses, dimensiones correctas y políticas de admisión de
la [revisión anterior](#admision-colas-simz1). Corrige la pérdida de procedencia
de dimensiones XML legadas y la selección de cuerpos dibujados. No aumenta todos
los vehículos, cambia capacidades ni interpreta PCU como metros.

### Dimensiones y procedencia

El orden de selección es **dimensión visual registrada válida
(`Vehicle_Dimensions`) → dimensión configurada válida del XML
(`Vehicle_Physical_Dimensions`) → supuesto explícito de familia**. Los campos
`length_m` y `width_m` están en metros. Una dimensión registrada tiene prioridad
sobre esta tabla; su presencia en `VehicleType` no demuestra medición de campo.

| Familia visual | Longitud × ancho de respaldo | Condición |
|---|---:|---|
| Carro, incluido liebre/tortuga | 4,5 × 1,8 m | Supuesto de familia |
| Moto, incluidos sus tres perfiles | 2,1 × 0,8 m | Supuesto de familia |
| Camión / transporte pesado | 10 × 2,5 m | Supuesto de familia; no autoriza accesos |
| Bus rígido | 12 × 2,5 m | Supuesto de familia; no crea vehículos de servicio |
| Bus articulado | 18 × 2,5 m | Solo con indicador explícito de articulación; envolvente rígida aproximada |

El indicador articulado es `Vehicle_Articulated=true` o `articulated=true` en
la dimensión registrada seleccionada, para un vehículo identificado como bus.
Sin poses de módulos y articulaciones se conserva la limitación
`rigid_total_envelope_articulation_unknown`; no se reconstruye su barrido real.
Un pasajero de transporte público no se convierte en bus por tener dimensiones.

`simz1_motion.py` antes leía longitud/ancho para el contrato visual únicamente
en perfiles `simz1-road-profiles-v1` o flotas públicas verificadas. Ahora conserva
también las dimensiones válidas del XML estándar legado en un campo separado:

- `source=MATSim_VehicleType_XML`, `nature=configured` y
  `measurement_status=not_established_by_vehicle_type`.
- `assumed` conserva la declaración disponible; `null` significa que no consta.
- `provenance` incluye `vehicle_type`, `artifact_source`, `artifact_path` y
  `artifact_sha256`, procedentes del artefacto comprobado.

Los valores XML ausentes, ambiguos, no finitos o no positivos no producen una
dimensión física inventada. Los metadatos opcionales inválidos del catálogo
visual generan diagnóstico y permiten usar la siguiente fuente válida sin
abortar todo el frame. Se mantienen las validaciones de los escenarios
versionados al cargar sus entradas. La evidencia física se comparte por tipo
en memoria; JSON y SQLite conservan el campo recibido sin migrar el esquema.

En el histórico de **227187 personas**, `simz1-0dd152dabbc24d1d84d9b738c449cc35`,
iteración 0, el XML efectivo contiene los tipos `Liebre`, `Normal` y `Tortuga`,
todos de **4,5 × 1,8 m y PCU 1**, sin buses configurados. El artefacto es
`output/output_vehicles.xml.gz`, SHA-256
`fdbcc0943589697a97e762394cb45b21c71aa954502b941fb99c3b2378c54d7d`.
El SQLite ya exportado no tenía esas dimensiones: por ejemplo, el segmento 1
de `z1_33759` conserva `Vehicle_Type=Normal` y `Vehicle_PCU=1`.
**No se regeneró ni modificó el SQLite histórico.** Sus cuerpos de respaldo
coinciden con los 4,5 × 1,8 m del XML; los exportadores nuevos conservarán además
la procedencia. No se atribuye retrospectivamente una flota de motos o buses.

### Cuatro magnitudes independientes

| Magnitud | Contrato |
|---|---|
| Dimensión física configurada | Longitud/ancho de `VehicleType`, con artefacto y SHA-256; no acredita medidas observadas de carrocería |
| Cuerpo dibujado | Longitud/ancho métricos, eje rígido y contorno derivados de la misma pose; el zoom no cambia sus metros |
| Separación visual | Distancia entre centros `(L1 + L2)/2 + gap_m`; `gap_m=2` m, configurable de 0 a 10 m |
| Envolvente lateral | `lateral_clearance_m=0.1` m por lado, configurable de 0 a 1 m; ancho de envolvente `W + 2*lateral_clearance_m` |
| Tolerancia de selección | 8 píxeles CSS para mouse y 18 para touch, medidos desde el contorno proyectado del cuerpo |
| PCU | Carga nativa en equivalentes de automóvil; independiente de longitud, ancho, envolvente y picking |

La envolvente longitudinal mide `L + gap_m`. Ni esa envolvente ni el área de
selección aumentan la carrocería. PCU y almacenamiento nativo siguen separados:
QSim usa equivalentes de automóvil para la carga de cola, no estos rectángulos.
El **margen geométrico de parada de 2 m de Prompt 5** es otra magnitud: referencia
el plano inferido antes del cruce y no se suma como tolerancia de picking.
`simz1Continuous.getVehicleCatalog()` y `diagnoseVehicle(...)` exponen dimensiones,
fuentes, envolvente y estos contratos sin añadir campos técnicos a la tarjeta.

La selección usa el cuerpo final mostrado. Un cuerpo declarado con eje o ancho
inválido no se convierte silenciosamente en un punto seleccionable; los registros
legados que solo tienen un punto conservan su contrato anterior. Tras un seek,
el hover vuelve a comparar **todos los cuerpos actuales**: no retiene el vehículo
anterior cuando otro queda bajo el cursor inmóvil. En pausa se reutiliza el
resultado mientras no cambian el frame, la cámara o el puntero. Mouse y touch
conservan su `pointerType` y tolerancia correctos.
También se revalida la identidad/visibilidad del candidato antes de conservar
la tarjeta. La búsqueda durante reproducción con hover activo es lineal en los
cuerpos visibles; la caché evita repetirla en pausa, pero no certifica FPS de GPU.

Una curva amplia del fixture admite el cuerpo completo de un bus rígido. La
esquina estrecha de 90° no acredita el barrido físico de un vehículo largo:
se conservan dimensión, centro y diagnóstico de soporte estimado. No se encoge,
oculta ni desplaza el cuerpo para inventar espacio. Cuando una cola no cabe,
se conserva el diagnóstico de espacio insuficiente; los fixtures válidos sí
exigen separación completa, orden e identidades estables.

### Revisión de dimensiones y almacenamiento para futuras corridas

`RoadVehicleProfiles` valida las dimensiones efectivas y su correspondencia
con metadatos de personas. El catálogo futuro mantiene carros de 4,5 × 1,8 m
y PCU 1; motos de 2,1 × 0,8 m y PCU 0,25; pesado de 10 × 2,5 m y PCU 3,5.
Son supuestos de escenario, no una calibración demostrada. Se conserva el
bloqueo de acceso de transporte pesado y no se configura una flota de buses.

La fuente local de MATSim 15 confirma que `QVehicleImpl.getSizeInEquivalents()`
devuelve PCU, no largo/ancho. En `QueueWithBuffer`, para la dinámica `queue`
inspeccionada, el almacenamiento efectivo es el máximo de
`L*n/cell*storageFactor`, `q*dt*flowFactor` y `L/freeSpeed*q*flowFactor`.
`L` corresponde a esa cola, que puede ser una subdivisión del enlace, y `q`
es capacidad por segundo. No basta dividir la longitud de la vía entre 4,5 m.

La admisión nativa compara `usedStorageCapacity < storageCapacity` antes de
añadir PCU. Una capacidad fraccionaria positiva admite un primer vehículo;
no equivale a comprobar el espacio completo de su carrocería. El indicador
de carga de esa cola excluye su búfer. Para una futura validación hay que
comparar PCU, longitudes de colas/carriles, factores y límites de búfer, además
de las dimensiones registradas. Esta revisión **no cambia** PCU, capacidad,
admisión ni políticas de circulación para hacer coincidir esos contratos.
La evidencia enlazada abajo registra el jar fuente y las líneas comprobadas.

### Archivos y regresión de esta revisión

| Área | Archivos modificados o añadidos en Prompt 6 |
|---|---|
| Dimensiones XML y flota | `python/simz1_motion.py`, `python/simz1_transit_replay.py` |
| Catálogo, diagnóstico y selección | `python/simz1_visual_lanes.js`, `python/simz1_visual_queues.js`, `python/simz1_vehicle_picking.js`, `python/visualizador_z1_controls.js` |
| Pruebas Python | Nuevo `python/test_simz1_physical_dimensions.py`; ampliado `python/test_simz1_replay_integration.py` |
| Pruebas visuales | Nuevos `python/test_simz1_vehicle_dimensions.cjs`, `python/test_simz1_vehicle_picking_dimensions.cjs`, `python/test_simz1_body_spacing.cjs`; ampliado `python/test_simz1_vehicle_presentation.cjs` |
| Ejecución y documentación | Nuevo `check_simz1_vehicle_bodies.ps1`, `README.md` y este documento |
| Evidencia | Nuevo `scenarios/zona1/versions/vehicle-bodies-2026-10-22/validation.json` |

Desde la raíz, con Node y el entorno Python del proyecto:

```powershell
powershell -ExecutionPolicy Bypass -File .\check_simz1_vehicle_bodies.ps1
```

La regresión preparada cubre XML estándar y gzip, procedencia y hash, ausencia
o invalidez de dimensiones, bus configurado, preservación JSON/SQLite e
independencia de PCU. Los fixtures de carro-carro, moto-carro y carro-bus incluyen
una cola mixta de cuatro vehículos, dimensiones registradas, pausa, seek directo
e inverso, tres ventanas y espacio insuficiente.

El picking prueba **120 combinaciones** de cinco cuerpos, tres escalas,
rotaciones 0/90/180/270 y cámara cenital/inclinada, con tolerancias mouse/touch,
extremos de buses largos y selección tras seek. Son proyecciones matemáticas
y adaptadores en memoria; no ejecutan Deck en GPU ni sustituyen inspección
manual WebGL a zoom máximo. El comando no ejecuta simulaciones, servidores,
navegadores ni regeneración masiva.

**Resultado ejecutado: 41 pruebas Python y 21 suites Node aprobadas.** Los
fixtures válidos mantienen cero solapamientos pendientes; el enlace corto
conserva los cuatro cuerpos y su incompatibilidad explícita. El fixture de zoom
máximo comprueba la separación métrica proyectada, sin afirmar un render GPU.

Se volvió a evaluar el frame completo de **08:03:07** desde la entrada SQLite
ya capturada por el inspector anterior, sin escanear ni modificar eventos:
**9996 intervalos activos únicos y 9912 cuerpos visibles únicos**. Las 84
omisiones anteriores (2 de movimiento y 82 de geometría/carril) y los conflictos
históricos permanecen iguales. La huella de poses, dimensiones y colores coincide
exactamente con Prompt 5:
`1d92464e93df7c8106e293b8900a65b69fbd07be64829cad270869b97fcdb270`.
Esto comprueba conservación, no la desaparición de la sobrecarga nativa histórica.
No se redujeron cuerpos ni se ocultaron vehículos para disminuir ese diagnóstico.
La [evidencia de esta revisión](../scenarios/zona1/versions/vehicle-bodies-2026-10-22/validation.json)
incluye fuentes, pruebas, comparación e integridad histórica comprobada.

Para repetir únicamente la inspección del frame con los insumos locales ya
existentes, elegir una salida nueva (el inspector rechaza sobrescribir archivos):

```powershell
node python/inspect_simz1_frame.cjs --input runtime/simz1-conflict-inspection-2026-10-22/frame-input.json --times 28987 --output-new runtime/simz1-conflict-inspection-2026-10-22/frame-report-body-recheck.json
```

<a id="admision-colas-simz1"></a>
## SimZ1: espera antes del cruce y admisión futura (22/10/2026, Prompt 5)

Esta revisión usa el [diagnóstico confirmado de Elena](#conflictos-elena-080307).
No modifica red, carriles, señales, prioridades configuradas, capacidades, población,
SQLite ni eventos de la corrida histórica. **La seguridad de una transición entre
enlaces y la separación de carrocerías dibujadas son contratos distintos.** QSim
no proporciona automáticamente distancias continuas exactas entre carrocerías.

### Límite de parada y cola visual

`simz1_visual_lanes.js` calcula `stopBoundary(link,lane)`: un plano perpendicular
al acceso, derivado de las franjas viales conectadas al mismo nodo y nivel, con
el margen visual configurable de **2 m** existente. No hay líneas de parada
levantadas en campo en estos metadatos: `explicit=false` y
`source=inferred_road_strip_and_visual_setback` lo declaran. La zona de cruce es
una aproximación geométrica; no se presenta como polígono GIS verificado.

El solver comprueba el rectángulo orientado completo contra ese plano. En curvas
usa la orientación real del cuerpo: descontar solamente media longitud podía
dejar una esquina dentro del cruce. Los seguidores se ordenan longitudinalmente
por tiempo/identidad, longitud, ancho y separación, dentro de su enlace y del
dominio nativo demostrado. La comprobación de ancho compara carrocería con carril;
las envolventes laterales se resuelven con separación longitudinal. Antes,
contabilizar dos veces el margen lateral descartaba colas que sí cabían.

El estado del semáforo se asocia al enlace/carril/movimiento observado. Cuando
falta evidencia para un carril, queda desconocido; no se toma el carril visual
estimado como observación física. No se alteran tiempos de entrada/salida ni
se desplaza una cola a otro enlace para hacerla caber. Un desbordamiento nativo
o una ventana incompleta conserva vehículos y diagnósticos: la cantidad de
solapamientos históricos no se convierte artificialmente en cero.

Cuando falta el cierre completo de predecesores, se permite una corrección
independiente solo para una cabecera probada por WAIT de QNode, en el carril
terminal observado, con intervalo no ambiguo. La preparación empieza en su pose
terminal existente, avanza monótonamente por la misma arista y alcanza el ancla
antes del WAIT registrado. Una entrada que ya rebasó el ancla se rechaza.
Las contradicciones conocidas del contexto se evalúan en sus intervalos completos:
la salida de otro vehículo no activa un ancla a mitad de una espera ni provoca
un retroceso del vehículo detenido. El resultado es reproducible al hacer seek.
La continuidad entre `.original` y el carril terminal queda desconocida cuando
falta historia lateral. Esta corrección conserva `queue_context_incomplete` y
el cómputo de conflictos; no certifica separación frente a seguidores desconocidos.

La reproducción final de 28987 s conserva **9996 activos únicos / 9912 visibles
únicos / 84 omisiones anteriores**. Se respaldan 945 trayectorias terminales:
183 cabeceras ya detenidas y 762 aproximaciones al WAIT posterior registrado;
930 poses cambian efectivamente. `z1_45095`, `z1_01464` y `z1_65245` tienen holguras
completas de 0.422/0.174/0.173 m antes del plano. `z1_225775` se rechaza por
`entry_pose_beyond_supported_stop_anchor` y conserva su pose. No hay centros fuera
del dominio nativo demostrado ni desplazados a otro enlace. Permanecen 1737649
parejas de cuerpos solapados y 102045 de solo envolvente: el histórico está
sobresaturado y no puede corregirse fingiendo espacio. El harness completo tarda
26.146 s CPU; este valor no es rendimiento GPU ni FPS. La evidencia compacta de
esta revisión se conserva en
[`admission-queues-2026-10-22/validation.json`](../scenarios/zona1/versions/admission-queues-2026-10-22/validation.json).

### Defectos y contratos nativos probados

| Caso demostrado | Antes | Política `strict-receiver-v1` |
|---|---|---|
| Receptor rechaza, `now-lastMovementOfHead > stuckTime`, `removeStuckVehicles=false` | `FORCE`, extracción e inserción aunque el receptor rechaza | `WAIT`; conserva vehículo, conductor y cola, sin inserción |
| Dos trayectorias incompatibles verdes, mismo nodo/paso, `intersectionLogic=NONE` | Ambas podían cruzar | La primera insertada reserva su movimiento durante el paso; la segunda espera |
| Verde con giro prohibido | La validación de ruta ya rechazaba el giro | Se conserva y se prueba en ambas políticas; verde no lo habilita |
| Candidato bloqueado por almacenamiento | La rama previa notificaba `crossed` después de insertar | Se conserva: WAIT no registra movimiento ejecutado; otro candidato admisible puede avanzar |

La secuencia estricta es: ruta/carril permitido → aceptación de giro, señal y
prioridad → conflicto con movimientos ya ejecutados en el nodo/paso → aceptación
nativa del receptor → inserción → registro del movimiento y comprobante.
Se reutiliza `PriorityMovements`, con su tabla o geometría configurada; las
ambigüedades conservan tratamiento conservador. No se cambia la programación
semafórica ni se afirma una duración física exacta del cruce entre pasos.

`stuckTime` sigue registrado y permite diagnosticar esperas prolongadas; ya no
autoriza FORCE bajo la política estricta. El preflight rechaza
`strict-receiver-v1` junto con `removeStuckVehicles=true`, sin reparar el XML en
silencio. La rama se protege también defensivamente si una prueba omite ese
preflight. No se añaden teletransportes ni eliminaciones para resolver el bloqueo.

Se conserva el contrato nativo `isAcceptingFromUpstream()`, incluido su umbral
de carga actual. **No** se sustituye por `load + PCU <= capacity`: las colas
originales históricas de capacidad fraccionaria 0.5556/0.7730 PCU deben poder
admitir el primer vehículo estando vacías. Cambiar ese umbral sin rediseñar la
red bloquearía incluso una cola vacía. Tampoco se aumentan capacidades.

La reserva es local a cada nodo y se limpia al siguiente instante. En MATSim 15
el nodo y sus enlaces salientes tienen un único actor propietario; cada receptor
tiene un único nodo de origen, y las fases de nodos/enlaces tienen barrera.
No hay bloqueo global ni lectura de la cabecera del receptor aguas abajo.
Esto evita una carrera entre comprobar y añadir en el camino inspeccionado.
Las pruebas de cuatro workers verifican este contrato, **no sustituyen una
corrida del scheduler real de QSim**.

Eliminar FORCE puede conservar una congestión o un gridlock que antes se
disimulaba con sobrellenado. Los fixtures verifican liberación al volver a aceptar
el receptor y ausencia de interbloqueos de software en esos casos; no demuestran vaciado de
toda la red urbana. El agotamiento del horizonte sigue siendo un diagnóstico,
no un viaje completado ni una desaparición que esta corrección deba ocultar.

### Política, evidencia y compatibilidad histórica

Solo la entrada `SimZ1` y sus preparadores nuevos adoptan por defecto
`simz1Admission.storagePolicy=strict-receiver-v1`. El grupo compartido conserva
`matsim15-native` por defecto para otros escenarios. Una política explícita en
el XML se conserva para comparaciones deliberadas. Los auditores interpretan
la ausencia del módulo en archivos históricos como legado; no los reclasifican
como corridas estrictas. No se editó el XML maestro ni el histórico.

### Launcher, carriles físicos y detención: revisión 2026-10-22

El launcher `python/ejecutar_simz1.py` ejecuta **RunZona1Simulation**, no
`SimZ1.main`. El generador ya escribía `strict-receiver-v1` cuando faltaba la
política en el XML. Ahora `--storage-policy strict-receiver-v1|matsim15-native`
permite elegirla explícitamente; se registra su procedencia en
`admission_policy_selection`. Sin el argumento se conserva una política XML
explícita; sin ambas se adopta strict. `--qsim-threads` conserva el valor del XML
si se omite (el maestro actual contiene **4**; fallback del generador: 1).

`RunZona1Simulation.loadConfiguration()` carga el grupo tipado y tiene una prueba
que lee strict + cuatro hilos + carriles, con señales activadas y desactivadas,
sin construir QSim. Su default compartido sigue siendo `matsim15-native` cuando
falta el módulo, para preservar laboratorios anteriores. El launcher de una
corrida nueva exige que la política esté materializada. No reescribe entradas
históricas ni modifica una corrida ya iniciada.

`run-manifest.json/admission_execution` registra entrada Java, política, hilos,
`removeStuckVehicles` y `stuckTime`. Antes de ejecutar indica
`requested_config_only`; después exige coincidencia con `output_config.xml` y
marca `effective_config_matches`. Una divergencia impide validar la corrida.
El mensaje nativo `SIMZ1_CONFIG` también registra `admissionPolicy`; el launcher
lo muestra sin eliminar el log completo. Comparar XML no demuestra ejecución de
transferencias: `native_execution_proven=false` queda explícito y los recibos
`results[iteración].native_qsim.admission_diagnostics` conservan esa evidencia
por separado. No se inició una corrida real durante esta revisión.

| Capa | Lo que hace | Límite verificable |
|---|---|---|
| Admisión nativa | QNode mantiene WAIT si el receptor rechaza; no FORCE ni remoción por almacenamiento al superar 10 s bajo strict | `isAcceptingFromUpstream()` compara carga actual con capacidad; no reserva `carga + PCU del candidato` ni longitud de carrocería |
| Eventos nativos | Enlace, pertenencia a cola/carril, tiempos, señal, WAIT, transferencia y aborto | No dan seguimiento longitudinal/lateral continuo ni barrido de una maniobra |
| Representación | Coloca cuerpo orientado completo detrás del plano de parada y separa la cola aguas arriba | El plano y posiciones son estimaciones geométricas; no crean espacio nativo ni cambios de carril |

La fábrica modificada se instala con señales ON/OFF y con prioridad ON/OFF.
Las transferencias internas de `QLinkLanesImpl` siguen sus colas legales y eligen
la cola menos cargada; eso no implementa «derecha lenta/izquierda rápida».
Las salidas desde actividades usan `isAcceptingFromWait()`, basado en flujo;
**strict-v1 no intercepta esa admisión ni añade seguimiento microscópico**.
En colas de capacidad fraccionaria, el predicado nativo puede aceptar un vehículo
estando vacío aunque su PCU/longitud supere el espacio restante.

No se arregla un enlace corto inflando capacidad o escondiendo vehículos.
El screening `lane_configuration_validation.storage_screening` informa capacidad
geométrica/umbral y enlaces cortos; no conoce por sí solo el espacio de cada bus.
Si la colocación visual respaldada es imposible, conserva identidad y conflicto.
La política física aislada descrita abajo rechaza longitud o espacio insuficiente;
su ejecución productiva permanece bloqueada hasta disponer de un adaptador que
mantenga la cola aguas arriba y reserve el cuerpo completo, incluso en salidas
desde actividades y transferencias internas. Una corrida strict actual puede
quedar congestionada; no se promete contacto cero ni ausencia global de gridlock.

#### Componente aislado de preferencia de carril

`SimZ1LanePolicy` no toca QVehicle, colas, eventos ni WebGL. Devuelve
`DISABLED`, `KEEP` o **REQUEST_CHANGE**, nunca una transferencia ya ejecutada.
Exige reglas explícitas del escenario: sentido y enlace iguales, frontera
adyacente transitable, modo/clase permitidos, salida compatible con el giro,
almacenamiento por vehículo y evidencia completa de ocupación durante la maniobra.
Una prohibición local o un carril exclusivo prevalecen sobre la preferencia.
Separa el beneficio esperado de la envolvente conservadora del vehículo durante
toda la maniobra, incluida su orientación; no usa interpolación del visor.

| Parámetro `simz1LanePolicy` | Default | Significado en el componente aislado |
|---|---:|---|
| `enabled` | `false` | `true` falla antes de QSim con `LANE_POLICY_UNAVAILABLE` |
| `minimumAdvanceM` | 8 m | Ganancia mínima esperada sobre permanecer en el carril |
| `minimumGapM` | 2 m | Separación longitudinal mínima de la envolvente barrida |
| `slowSpeedMps` | 8.33 m/s | Umbral de preferencia derecha; es una hipótesis de escenario, no norma vial |
| `lookaheadSeconds` | 5 s | Horizonte común de avance y ocupación aportado por el adaptador |

Lento prefiere derecha y rápido izquierda solo con ganancia suficiente. El módulo
desactivado retorna antes de exigir datos físicos nuevos. Sus pruebas comprueban
equivalencia del bypass, no equivalencia estadística de corridas completas.

Faltan para activar cambios reales: importación de reglas/anchos/fronteras físicas
por carril; estado nativo continuo de posición, orientación, velocidad y longitud;
almacenamiento por vehículo con spillback; reserva/revalidación/transferencia
lateral atómica por el propietario QSim; eventos de cambios comprometidos y
posiciones verificables. Los carriles generados actualmente son colas terminales,
no un catálogo comprobado de todos esos permisos. Python y Java rechazan
`simz1LanePolicy.enabled=true`; no hay un flag que finja habilitarlo.

#### Pruebas sin ejecutar MATSim

El runner nuevo compila fuentes actuales con JDK 25 en un directorio nuevo y
usa copias locales verificadas por SHA-256 de los JAR disponibles. Ejecuta solo
una lista explícita de fixtures; no llama `Controler.run()` ni al scheduler QSim.
Conserva hashes y `simulation_executed=false` en `target/simz1-lane-policy-*/checked-sources.json`.

Resultado de esta revisión: **37 pruebas Python, 7 suites JavaScript y 10
ejecutables Java aprobados**, con compilación nueva de las fuentes. Evidencia:
`target/simz1-lane-policy-verified.log` y
`target/simz1-lane-policy-9e96664a86154c1988b00b5f7cf9075d/checked-sources.json`.
El sandbox de Windows rechazó el cierre ZipFS de JAR por javac; el mismo
verificador terminó correctamente con ejecución autorizada fuera del sandbox,
sin cambiar permisos ni ejecutar una simulación. Una suite adicional del launcher
obtuvo 36/37: `test_live_interrupt_stops_process_tree` falló por acceso denegado
de Windows al detener su proceso falso. Ese ensayo no forma parte del runner
aislado; sus procesos terminaron y no se presenta como una prueba aprobada.

```powershell
# Solo si falta el archivo de dependencias; no ejecuta una simulación.
.\mvnw.cmd -o -q dependency:build-classpath '-Dmdep.outputFile=target/simz1-storage-classpath.txt'
if ($LASTEXITCODE -ne 0) { throw 'Faltan dependencias Maven locales.' }
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\check_simz1_lane_policy.ps1
if ($LASTEXITCODE -ne 0) { throw 'Falló el contrato de carriles/admisión.' }
git diff --check
```

Cobertura: rojo, receptor lleno antes/después de 10 s, almacenamiento insuficiente,
giros prohibidos, admisión histórica explícita, colas 2/5/10, bus de 18 × 2.5 m y
camión de 16.5 × 2.55 m detrás de parada, permisos de cambio/exclusividad, barrido
ocupado y longitudes incompatibles. La prueba nativa usa cuatro propietarios de
nodo concurrentes y 400 transferencias; conserva además dos propietarios más dos
lectores con 200 transferencias. La fuente MATSim 15 asigna nodo y enlaces
salientes al mismo runner y separa fases con barreras. Esto respalda el contrato
paralelo, pero **no sustituye ejecutar y observar la corrida real de cuatro hilos**.
Se mantienen los contadores de espera, congestión, transferencias y abortos, y la
distinción entre bloqueo de tráfico y un ciclo de locks detectado por la JVM.

#### Comando exacto para una corrida futura

Este comando **sí ejecutará MATSim cuando lo lance el usuario**. No se ejecutó en
esta revisión. Crea un directorio nuevo para 10 personas y una iteración, usa
strict con cuatro hilos y desactiva incidentes. El launcher vial actual no instala
la flota pública de `SimZ1.main`; los buses/camiones de los fixtures no acreditan
una corrida pública integrada. El componente microscópico permanece desactivado.

```powershell
$simz1Run = Join-Path $PWD.Path ('scenarios\zona1\montecarlo\run-strict-4t-' + [guid]::NewGuid().ToString('N'))
& .\.venv\Scripts\python.exe -B .\python\ejecutar_simz1.py `
  --config .\scenarios\zona1\config-simz1.xml --maven .\mvnw.cmd --offline `
  --run-dir $simz1Run --mode montecarlo --agents 10 --corridor-policy redistribute `
  --seed 20261022 --matsim-seed 20261022 --iterations 1 --qsim-threads 4 `
  --storage-policy strict-receiver-v1 --use-lanes --signals --unsignalized-priority `
  --no-incidents --signal-offset-policy preserve --temporal-profile full-day `
  --trips-per-person 1 --drain-seconds 0
if ($LASTEXITCODE -ne 0) { throw 'Corrida no validada; revisar su manifiesto y log.' }
$simz1Manifest = Get-Content -LiteralPath (Join-Path $simz1Run 'run-manifest.json') -Raw | ConvertFrom-Json
$simz1Admission = $simz1Manifest.admission_execution
if ($simz1Manifest.status -ne 'completed' -or $simz1Admission.verification -ne 'effective_config_matches' -or
    $simz1Admission.storage_policy -ne 'strict-receiver-v1' -or $simz1Admission.qsim_threads -ne 4 -or
    $simz1Admission.remove_stuck_vehicles -ne $false -or $simz1Admission.force_after_stuck_time -ne $false) {
    throw 'La configuración efectiva no acredita el contrato solicitado.'
}
$simz1Manifest.results.'0'.native_qsim.admission_diagnostics | ConvertTo-Json -Depth 8
$simz1Manifest.results.'0'.counts | ConvertTo-Json -Depth 8
```

Para una comparación futura con admisión histórica, usar **otro directorio nuevo**
y `--storage-policy matsim15-native`, manteniendo semillas y entradas. Eso permite
FORCE histórico después de `stuckTime`; no es la configuración recomendada para
receptor bloqueado. Apagar `simz1LanePolicy` por sí solo no revierte strict.

Cada decisión nueva registra política y versión. `turn_go` indica permiso de
giro, **no prueba de transferencia**. El evento separado `simz1Admission`, emitido
después de `addFromUpstream`, registra vehículo, persona, nodo, enlaces, carriles
y `receiverAcceptedAtDecision=true`. No infla el contador de decisiones nativas.
`admission_conflict_executed` identifica un WAIT por cruce ya ejecutado;
`storageTimeoutExceeded` distingue espera prolongada del FORCE legado.
El exportador conserva esos WAIT y su evidencia de cabecera de cola.

El auditor Python rechaza FORCE/remoción de almacenamiento bajo política
estricta, discrepancias de versión/configuración y comprobantes sin receptor
aceptado o identidad completa. Mantiene por separado admisiones confirmadas,
intentos de espera y estabilidad física no demostrada. El comprobante no mide
distancias continuas ni convierte un conflicto gráfico en accidente.

La corrida `simz1-0dd152dabbc24d1d84d9b738c449cc35`, iteración 0, conserva los
**698853 FORCE** diagnosticados. Ejemplos preservados: `z1_218470` a 28981 s,
receptor `osm_406843605_2_forward.original`, carga 1215 PCU/capacidad 0.5556;
`z1_44455` a 28985 s, receptor `osm_406843605_6_forward.original`, 711/0.7730;
`z1_45095` WAIT a 28987 s y FORCE a 28988 s. Los IDs completos y eventos están en
[`replay-conflicts-2026-10-22`](../scenarios/zona1/versions/replay-conflicts-2026-10-22/).
La nueva política no reescribe esas transiciones.

### Archivos de esta revisión

| Área | Archivos |
|---|---|
| Dibujo y evidencia visual | `python/simz1_visual_lanes.js`, `simz1_visual_queues.js`, `visualizador_z1_controls.js`; nuevos `test_simz1_queue_stoplines.cjs`, `test_simz1_queue_head_fallback.cjs` |
| Admisión de QSim | `Zona1QNodeImpl.java`, `Zona1PriorityNetworkFactory.java`, `Zona1NativeDiagnostics.java` en `src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/` |
| Entrada/configuración SimZ1 | Nuevo `SimZ1AdmissionConfigGroup.java`; `SimZ1.java`, `SimZ1Configuration.java`, `SimZ1Diagnostics.java` en `src/main/java/gt/edu/uvg/sim/zona1/` |
| Preparación y validación | `python/prepare_simz1.py`, `generate_montecarlo_z1.py`, `generate_test_agent.py`, `simz1_config_validation.py`, `simz1_run.py`; nuevo `simz1_admission_validation.py` |
| Lectura de eventos e informes | `python/simz1_native_validation.py`, `simz1_priority_audit.py`, `simz1_trajectories.py`, `simz1_visual_motion.py`, `simz1_capacity_diagnostics.py`, `simz1_operational_report.py` |
| Reproducción offline | `python/inspect_simz1_frame.cjs`: contadores y muestras de anclas respaldadas/rechazadas |
| Pruebas | Nuevos `SimZ1AdmissionCheck.java`, `SimZ1AdmissionConcurrencyCheck.java`, `python/test_simz1_admission.py`, `check_simz1_admission.ps1`; ampliados `PriorityRestrictionCheck.java`, `SimZ1StorageBranchCheck.java`, `SimZ1ConfigurationCheck.java`, `python/test_simz1_run.py` |

### Prueba pequeña sin simulación

Desde la raíz, con JDK 25, Node y dependencias Maven ya almacenadas:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\check_simz1_admission.ps1
```

El script compila y llama expresamente nueve programas de prueba `main()`;
`mvn test` por sí solo no los ejecuta. Ejecuta además fixtures Python y catorce
suites Node. **No contiene una opción de ejecutar MATSim, QSim, servidor ni
navegador.** Los preparadores usados por los tests crean carpetas temporales
con una persona; no regeneran la demanda masiva.

Para reutilizar la compilación comprobada en esta revisión:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\check_simz1_admission.ps1 `
  -CompiledClasspathFile .\target\simz1-admission-java-d95c9d7150ef402292d9d11b9010c858\classpath.txt `
  -JavaExecutable 'C:\Program Files\Eclipse Adoptium\jdk-25.0.4.101-hotspot\bin\java.exe'
```

Se comparan SHA-256 de fuentes, clases y classpath antes de reutilizarlos;
cualquier cambio obliga a recompilar. `target` es local y no se versiona.

Para repetir solo el frame desde la extracción SQLite ya conservada, sin leer
otra vez la base ni sobrescribir evidencia:

```powershell
$simz1Frame = '.\runtime\simz1-conflict-inspection-2026-10-22\prompt5-recheck-' + [Guid]::NewGuid().ToString('N') + '.json'
node .\python\inspect_simz1_frame.cjs `
  --input .\runtime\simz1-conflict-inspection-2026-10-22\frame-input.json `
  --times 28987 --output-new $simz1Frame
```

Los checks nativos cubren rojo/verde por carril, giro prohibido con verde,
conflictos ejecutados, receptor lleno a 5/10/11/60/3600 s, liberación posterior,
capacidad fraccionaria, conservación de identidad, rama FORCE/ABORT legada y
dos nodos con cuatro workers. Las 200 transferencias concurrentes conservan
una inserción y un comprobante por identidad, sin FORCE, ABORT ni duplicaciones.
Los fixtures visuales válidos de 2/5/10 cuerpos, cola prolongada, curva y carriles
paralelos exigen cero solapamientos solucionables, sin ocultar cuerpos; se
comprueban entrada/salida, reordenación y seek.

Validación adicional: 17 contratos de corrida con proceso MATSim **simulado por
mock**, 10 de configuración de señales y el generador de un agente aprobaron.
La preparación sintética OSM aprobó; el test antiguo `test_cycle2_config` sigue
esperando 07:59–15:00 frente al XML ya versionado de 00:00–24:00. No se cambió
ese horario. Continúan registrados los fallos previos de `continuous_replay`
(cierre de ruta futura) y `render_performance` (identidad de capa estacionaria),
ajenos al cambio de admisión. No se afirma una validación GPU ni de una corrida
urbana con cuatro hilos: no se ejecutaron simulaciones, servidores o navegadores.

<a id="conflictos-elena-080307"></a>
## Avenida Elena / 15 Calle: diagnóstico reproducido del 22/10/2026

Se reprodujo **08:03:07 (28987 s)** de `simz1-0dd152dabbc24d1d84d9b738c449cc35`,
iteración 0, 227187 personas, con SQLite directo y el código real de loader, controles,
geometría y colas ejecutado en Node. DOM/Deck son adaptadores en memoria: no se abrió
navegador, servidor ni GPU. La ventana 241 completa es `[28920,29040)`; el foco no
filtra el roster antes de calcular posiciones/conflictos.

**Reproducción inicial exacta:** 9996 vehículos únicos activos y **9912 visibles**.
Las 84 omisiones existentes son dos `motion_unavailable` y 82
`geometry_or_lane_unavailable`; no hay duplicación activa. El frame inicial detecta
1199068 parejas de envolventes, 310 resueltas por separación y 1198758 sin resolver.
Una envolvente incluye márgenes: su solapamiento no implica necesariamente contacto
entre carrocerías. Ninguna de estas cifras es un conteo de accidentes.

La fuente contiene una concentración que no cabe como cuerpos continuos:

| Enlace | Longitud | Vehículos activos | En `.original` | Dominio original modelado | Centros fuente fuera del dominio |
|---|---:|---:|---:|---|---:|
| `osm_406843605_2_forward`, 15 Calle | 10,586 m | 1220 | 1217 | `[0;2,117] m` | 770 |
| `osm_406843605_6_forward`, 15 Calle | 28,987 m | 718 | 713 | `[0;5,797] m` | 474 |
| `osm_381667651_15_forward`, Elena | 75,936 m | 39 | 9 | Derivado de carriles efectivos | 3 |
| `osm_381667651_16_forward`, Elena | 63,929 m | 32 | 8 | `[0;12,786] m` | 3 |

El foco de 100 m alrededor del nodo OSM `579747165` abarca 2055 intervalos activos
y 1253 centros de `Motion_Plan` fuera del dominio longitudinal de la cola observada.
Esto **no significa fuera del enlace MATSim**. `.original` es una cola serial aguas
arriba, no otro carril lateral. MATSim 15 `LanesUtils` calcula su longitud restando
el inicio de la siguiente cola; `QLinkLanesImpl` utiliza esa longitud al crearla.
Los eventos de carril y las definiciones nativas acotan el tramo, pero no miden
una posición continua dentro de él.

| Categoría solicitada | Resultado y alcance |
|---|---|
| A — solapamiento visual | Confirmado en el renderer. La interpolación comprime estancias largas en enlaces muy cortos y faltan posiciones continuas; no se puede atribuir todo únicamente al dibujo porque también hay FORCE nativos. |
| B — carril incorrecto | Confirmado el desajuste longitudinal de cola serial. No se acredita que `.original` sea un carril paralelo ni se inventa una asignación lateral. |
| C — fuera del enlace | El fallo medido es dentro del enlace, pero fuera del tramo de la cola observada. No se interpreta la extensión del cuerpo rígido sobre un nodo como extrapolación de su centro. |
| D — transición físicamente incompatible | Los controles nativos de adyacencia/carriles no registran transiciones inválidas. La sobreocupación de colas está acreditada; una colisión continua no es observable con estos eventos de QSim. |
| E — permanencia dentro del cruce | No confirmada como estado físico. QSim transfiere entre enlaces instantáneamente y no registra un cuerpo que reserve persistentemente el interior del cruce. |
| F — forzado por almacenamiento | Confirmado con decisiones `simz1NativeDecision/FORCE`, rechazo receptor y eventos LinkEnter/LaneEnter de los mismos vehículos. |
| G — tamaño excesivo | Normal/Liebre/Tortuga nativos y catálogo visual coinciden en 4,5 × 1,8 m, PCU 1. No hay inflación por zoom; algunas colas son más cortas que un cuerpo y la cantidad acumulada es incompatible con su representación geométrica. |
| H — identidad/duplicación/ventana | 9996 IDs activos únicos, identidad del manifiesto y fuente comprobadas. Las omisiones quedan explicadas y no se eliminan vehículos para bajar conflictos. |

Todas las 13746 solicitudes de cierre de contexto de esta ventana alcanzan
`row_limit` (4097 filas frente al límite de 4096). En el frame inicial hay 8399
`queue_context_incomplete` y 636 `storage_exceeded`. La elegibilidad de una cola
incluye su formación anterior al hold: un cuerpo rojo con ese diagnóstico no prueba
que ya esté detenido. Rojo representa velocidad visual baja y blanco detención.

Se hizo **una sola pasada** del prefijo de eventos gzip: 22245814 eventos hasta
el primero excluido a 29041 s, 2035 registros retenidos. Se verificó cronología
del prefijo, hash del manifiesto, tamaño y estabilidad del archivo; no se recalculó
el hash completo del gzip ni se volvió a procesar la simulación.

| Vehículo / persona | Instante | Evidencia nativa |
|---|---|---|
| `z1_225775` | 24481 s, 06:48:01 | Entrada FORCE a `osm_406843605_2_forward.original`, carga receptora 496 PCU; sigue activo en ese enlace a 28987 s. |
| `z1_218470` | 28981 s, 08:03:01 | FORCE a `_2.original`, rechazo receptor, carga 1215 PCU / umbral 0,5556; LinkEnter/LaneEnter en el mismo segundo. |
| `z1_44455` | 28985 s, 08:03:05 | FORCE a `_6.original`, carga 711 PCU / umbral 0,7730; LinkEnter/LaneEnter coincidentes. |
| `z1_45095` | 28987 y 28988 s | WAIT a 08:03:07; FORCE al segundo siguiente hacia `_2.original`, carga 1216 PCU. |
| `z1_65245` | 28988 s | Salida normal de `_3` a `_4`; ningún FORCE de este vehículo en la ventana inspeccionada. |

Los sufijos `_2/_3/_4/_6` de esta tabla pertenecen a `osm_406843605_*_forward`.
En `28970–29010`, inclusivo, se registran 725 FORCE y 10777 `storage_wait` globales:
son decisiones/intentos, no vehículos únicos ni duración. La muestra seleccionada
contiene 34 FORCE de nueve de sus diez vehículos. La fuente SQLite conserva WAIT
agregado y eventos de carril, pero descarta FORCE; por eso la atribución física
requiere el extracto nativo separado.

`Zona1QNodeImpl` resuelve primero giro/señal/prioridad. Después consulta almacenamiento.
Si el receptor rechaza y `now-lastMovementHead > stuckTime`, con `stuckTime=10` y
`removeStuckVehicles=false`, fuerza la entrada. Los ejemplos recientes registran
11 s frente a 10 s. Ese reloj puede incluir espera previa por rojo o prioridad:
no mide diez segundos consecutivos de rechazo de almacenamiento. No se cambiaron
estas políticas. La señal de la cabecera receptora es desconocida en los snapshots
de esta corrida con QSim paralelo; no se atribuye el rechazo a un rojo receptor.

Como contraste, **toda la iteración histórica** registra en `run-manifest.json`
20857667 WAIT (11465233 por almacenamiento), 698853 FORCE y cero
`storage_stuck_removals`. No hay total ABORT explícito: el residual de decisiones
menos WAIT, FORCE y `turn_go` es cero. Los 72800 abortos al horizonte son otra
categoría. `counts.invalid_physical_transitions=0` valida transiciones discretas;
el propio manifiesto mantiene `physical_stability.status=not_demonstrated` y
`validation.physical_stability.proven=false`. No acredita separación entre cuerpos.

Los cruces dibujados usan franjas de carretera y conectores esquemáticos inferidos,
no polígonos GIS verificados de intersección. No hay enlaces MATSim ficticios añadidos.
Los cuerpos pueden estimar una transición cuando existen eventos contiguos y un
movimiento permitido; esas poses se etiquetan como estimadas, no observadas.

La corrección limita el **centro estimado** al dominio de la cola cuya entrada está
respaldada por vehículo, enlace, carril e intervalo. No modifica `Motion_Plan`,
eventos, velocidades, colores ni dimensiones. Una `.original` compartida conserva
`visual_lane=null`; el eje es una estimación lateral, no una medición. Los dominios
ambiguos y las geometrías parciales quedan explícitamente desconocidos. El solver
y los conectores no pueden sacar el centro de ese dominio ni trasladarlo a otro enlace.

| Resultado a 28987 s | Antes | Después |
|---|---:|---:|
| Activos únicos / visibles únicos | 9996 / 9912 | 9996 / 9912 |
| Omisiones explicadas | 84 | 84 |
| Parejas de cuerpos dibujados solapados | 944575 | 1744960 |
| Parejas con solo envolvente de seguridad solapada | 254183 | 105352 |
| Parejas resueltas por espaciado | 310 | 82 |

Hay 9904 cuerpos con dominio comprobable y ocho sin él; **5207 centros proyectados**,
1249 en el foco. Ningún centro con dominio disponible quedó fuera ni cambió de enlace.
Los 1253 desajustes del resumen fuente no equivalen a correcciones aplicables:
ese resumen selecciona geometrías de enlaces, mientras el foco renderizado selecciona
centros fuente/dibujados y exige cuerpos representables. No se redujo el número de
vehículos ni su tamaño para obtener cero solapamientos. Acotar una sobreocupación
nativa aumenta la concentración visible y conserva el problema para inspeccionarlo.

Ejemplos a **08:03:07**, todos de 4,5 × 1,8 m y con `person_id=vehicle_id`:

| ID | Cola observada | Estación fuente → acotada, metros nativos | Resultado |
|---|---|---|---|
| `z1_153530` | `osm_406843605_2_forward.original` | 10,525 → 2,117 | Contexto incompleto; 1220 vecinos conflictivos, muestra acotada |
| `z1_133348` | `osm_406843605_6_forward.original` | 28,636 → 5,797 | Contexto incompleto; 712 vecinos conflictivos |
| `z1_20429` | `osm_381667651_16_forward.original` | 18,153 → 12,786 | Contexto incompleto; cuatro vecinos conflictivos |

Los inspectores reales `getVisualDiagnostics()`, `diagnoseVehicle()` y `traceVehicle()`
ahora distinguen contacto entre cuerpos dibujados, solo margen de seguridad y estado
físico desconocido. `summarizeCollisions()` cuenta todas las parejas;
`sampleCollisions({vehicle_ids:[id],limit:100})` filtra por identidad **antes** de
limitar la muestra. `collisions` devuelve hasta 100 registros con metadata de truncado;
no se debe usar su longitud como total. La evidencia de FORCE permanece separada:
un conflicto del renderer no prueba esa decisión ni un accidente.

La evidencia conservada está en
[`replay-conflicts-2026-10-22`](../scenarios/zona1/versions/replay-conflicts-2026-10-22/):
`frame-evidence.json` contiene nueve trazas antes/después, cuerpos, origen de posición,
vecinos muestreados con su total, hashes y resultados de pruebas;
`native-summary.json` conserva densidades y dimensiones, y `native-events.json`
los 2035 eventos seleccionados con WAIT/FORCE y cambios de pertenencia.
Los reportes detallados y el input completo permanecen en `runtime`, sin copiar la
ventana de 151 MB al árbol versionable. El baseline contiene instrumentación diagnóstica
nueva sobre las posiciones anteriores; no se presenta como HEAD sin modificaciones.
El extractor nuevo exporta `mtime_ns` como texto decimal para preservar nanosegundos
al pasar por JavaScript. Los reportes iniciales redondeaban ese metadato numérico;
se comprobó la fuente intacta con el entero Python y se conservaron ambos valores
en `metadata_precision`, sin atribuir ese redondeo a eventos o identidades vehiculares.

Archivos productivos: `python/simz1_visual_lanes.js`, `python/simz1_visual_queues.js`
y `python/visualizador_z1_controls.js`. Inspectores nuevos:
`python/inspect_simz1_conflicts.py`, `python/inspect_simz1_frame.cjs` y
`python/inspect_simz1_native_sample.py`. Pruebas nuevas:
`python/test_simz1_conflict_diagnostics.cjs`, `python/test_simz1_native_queue_extent.cjs`,
`python/test_inspect_simz1_conflicts.py`, `python/test_inspect_simz1_native_sample.py`.
También cambian `python/test_simz1_render_performance.cjs`, ambos README y la carpeta
de evidencia anterior. No cambian Java, red, señales ni datos históricos.

**Pruebas realizadas:** once suites Node pasan: geometría de carriles, colas,
contrato/contexto/continuidad de colas, cuerpos rígidos, recorte espacial, selección,
bootstrap y las dos nuevas pruebas de conflictos/dominios. Incluyen dos movimientos
cruzados, cola roja, 2/5/10 vehículos, carriles paralelos, curva, evidencia FORCE,
diagnóstico fuera del instante mostrado y seek. Las pruebas Python de ambos
inspectores pasan. La secuencia real `28986.9 → 28987 → 28987.1 → 28987` vuelve a la
misma huella de poses; la guardia final de dominio produce esa misma huella.

Tres fallas se reprodujeron también cargando módulos HEAD anteriores en memoria:
`test_simz1_queue_safety.cjs:91` (margen lateral 0,7 m),
`test_simz1_continuous_replay.cjs:277` (ruta futura al cierre) y
`test_simz1_render_performance.cjs:12` (identidad de capa estacionaria).
No se debilitaron esas aserciones. La única adaptación de la prueba de rendimiento
comprueba que la muestra diagnóstica truncada conserva el total de parejas.

El harness completo con diagnóstico tarda aproximadamente 13,4 s antes y 21,1 s
después en la secuencia; la verificación final fría tarda 24,0 s. No es una medida
de FPS/GPU ni un benchmark controlado. La mayor densidad aumenta las parejas que
se examinan; queda pendiente optimizar ese coste preservando conteos y evidencia.

Para repetir las pruebas nuevas, sin sockets ni simulaciones:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s python -p test_inspect_simz1_conflicts.py -v
.\.venv\Scripts\python.exe -B -m unittest discover -s python -p test_inspect_simz1_native_sample.py -v
node .\python\test_simz1_conflict_diagnostics.cjs
node .\python\test_simz1_native_queue_extent.cjs
```

Para ejecutar el renderer actual sobre la **ventana ya extraída**, sin leer de nuevo
SQLite ni los eventos, el destino debe ser un archivo nuevo:

```powershell
node .\python\inspect_simz1_frame.cjs `
  --input .\runtime\simz1-conflict-inspection-2026-10-22\frame-input.json `
  --times 28986.9,28987,28987.1,28987 `
  --vehicles z1_153530,z1_133348,z1_20429,z1_218470,z1_44455,z1_225775,z1_45095,z1_01464,z1_65245 `
  --limit 9 --output-new .\runtime\simz1-elena-frame-recheck.json
```

Si falta ese input local, extraer una sola ventana con consultas indexadas de solo
lectura; el directorio de salida debe ser nuevo:

```powershell
.\.venv\Scripts\python.exe -B .\python\inspect_simz1_conflicts.py `
  --replay-dir .\runtime\simz1-227187-direct\webgl-continuo `
  --window 241 --time 28986.9 --time 28987 --time 28987.1 `
  --output-new .\runtime\simz1-elena-window-recheck
```

El inspector nativo permite repetir una lectura acotada del gzip, pero no es
necesario hacerlo para consultar la evidencia entregada. Ejemplo con dos vehículos
y ventana de decisiones globales, sin reescribir el histórico:

```powershell
.\.venv\Scripts\python.exe -B .\python\inspect_simz1_native_sample.py `
  --run-dir .\scenarios\zona1\montecarlo\run-massive-fixed-97e840b02c044fc39497debc91300a6d `
  --run-id simz1-0dd152dabbc24d1d84d9b738c449cc35 --iteration 0 `
  --manifest-sha256 2d93aa7cd197200761917e6cf0c1c7d2848aaeb5102b502e744799bd8814f456 `
  --events-bytes 2381262395 --vehicle z1_218470 --vehicle z1_44455 `
  --start 28970 --end 29010 --global-window 28970 29010 `
  --output-new .\runtime\simz1-elena-native-recheck
```

No se ejecutó MATSim, servidor, navegador ni regeneración masiva. Los cambios de
cliente se incorporan cuando el usuario reinicie el servidor continuo existente;
no requieren refrescar manifiestos históricos ni reexportar SQLite. Esta revisión
no acredita la versión de una pestaña o servidor actualmente abiertos.

Para el siguiente encargo, priorizar:

1. Diseñar y probar **en una versión futura** la admisión con receptor bloqueado y
   el reloj de FORCE; comparar WAIT/FORCE/ABORT con casos pequeños antes de una corrida
   masiva. No sustituir la física con ajustes del renderer.
2. Revisar almacenamiento y subdivisión serial de enlaces cortos de Elena/15 Calle
   con evidencia de red y demanda; preservar los cuatro casos OD y gateways dirigidos.
3. Completar contexto de colas mediante consultas indexadas y optimizar la detección
   masiva sin ocultar cuerpos. Mantener un registro compacto de FORCE ligado a
   corrida/vehículo/instante, separado de las posiciones estimadas.

<a id="colas-continuidad-20261021"></a>
## Colas y continuidad: correcciones del 21/10/2026

Esta sección actualiza el diagnóstico anterior; sus fixtures conservan la evidencia previa.
Corrida inspeccionada por manifiestos: `simz1-0dd152dabbc24d1d84d9b738c449cc35`, iteración 0,
227187 personas, `sqlite-direct-v1`. No se atribuye a las capturas. MATSim 15.0, deck.gl 9.1.14;
generadores y servidor continuo existentes conservados. Los manifiestos históricos no cambiaron.
La consulta HTTP de esta entrega a `127.0.0.1:8793` recibió `WinError 10061` (conexión rechazada):
cliente de pestaña no observado. Huella local de fuentes al cierre de esta edición:
`15ddaa32dd8e0276c82316b543fe8fe3ad6cd0f0683c9deb30bf7ac4c87f0835`.

| Causa/evidencia | Corrección visual | Límite conservado |
|---|---|---|
| Líder salido ausente: mismo instante, anclas distintas según ventana | Cierre de esperas consultado por índices SQLite, independiente de la ventana y del orden de seek | Presupuesto agotado: cuerpo fuente visible, `queue_context_incomplete`; no se usa un roster parcial |
| `z1_38616`, 41–45 s: carril terminal de 2.120776 m frente a media carrocería de 2.25 m | Retener cuerpo conocido e informar incompatibilidad | No inventar almacenamiento aguas arriba ni declarar resuelto el espacio |
| `fraction*(longitud_enlace-head)` negativo en enlace corto | Conservar pose del Motion_Plan durante todo el intervalo incompatible | No dibujar marcha atrás ni fabricar aproximación previa |
| Formación confundida con parada al entrar en giro | Compartir posición/rumbo sólo durante transición móvil contigua y permitida | Una espera efectiva conserva alineación del carril |
| Offset de carril sale del polígono con eje fuente dentro | Dominio evaluado mediante eje fuente y enlace permitido | Cuerpo rígido completo; eje realmente exterior sigue fuera |
| Registro idéntico repetido en segmentos/contexto | Deduplicar igualdad completa en índices | Planes distintos e intervalos contradictorios siguen siendo conflictos |

La línea inferida es `longitud_enlace - setback_geométrico - stop_line_setback_m`; el centro del
primero resta su propia semilongitud. No se reduce el margen para acomodar cuerpos. FIFO usa entrada
nativa de carril o entrada de enlace; empates siguen identificados como ambiguos. Se comprueba
`s_delantero-s_trasero >= (L_delantero+L_trasero)/2 + gap_m` y SAT de envolventes orientadas mediante
índice espacial métrico. Los conflictos se asignan a ambos vehículos. Zoom no interviene.

`simz1_queue_context.py` usa como máximo, por semilla, 4 bloques, 4096 filas, 128 esperas,
profundidad 8, 16 MiB comprimidos y 32 MiB decodificados; caché compartida acotada a 32 MiB.
Una semilla fría y otra cacheada reciben el mismo presupuesto lógico. El costo total de ventana
suma semillas: **rendimiento y frecuencia de contextos incompletos en corridas densas pendientes**.
La cronología de eventos con igual timestamp conserva el orden de la serie nativa completa.
Los cuerpos conservados sin separación válida aparecen en `incompatiblePosition`, `warningReasons`
y `diagnoseVehicle().spacing_compatible`; su posición es reconstruida, no una medición física.

**Pendientes que no se ocultan:** liberación discreta de cola sin trayectoria subpaso
(`queue_exit_has_no_substep_trajectory`), huecos tras líderes que salen mientras el seguidor sigue
registrado como parado, geometría desconocida y Motion_Plan no disponible. `z1_43360` mantiene el
intervalo desconocido 124–125; `z1_167074` conserva Arrival169. Ninguno acredita movimiento forzado:
eso exige evento `simz1NativeDecision`, `decision=FORCE`, con identidad/tiempo coincidentes; SQLite
no conserva esa decisión en los segmentos inspeccionados. No se cambió física, tiempos ni FIFO.

Archivos: `simz1_visual_queues.js`, `simz1_visual_lanes.js`, `simz1_spatial_view.js`,
`visualizador_z1_controls.js`, `simz1_continuous_loader.js`, `simz1_continuous_replay.py`, nuevo
`simz1_queue_context.py`; pruebas indicadas abajo; inspector y fixture histórico completados para
leer namespaces de carriles; `README.md` y este documento. Tarjeta de seis campos y
`Personas generadas: N` conservados. Sin cambios en corridas ni reexportaciones.

Ejecutado: revisión, lectura histórica acotada, inspector de manifiestos, sintaxis JS/Python y
`git diff --check`. **Suites y navegador no ejecutados.** Preparadas pruebas 2/5/10, tipos mixtos,
semáforo, curvas, enlaces cortos, distinto nivel, extremos, ventanas, pausa, seek inverso,
separación longitudinal y polígonos; presupuestos, contradicciones y cronología.

```powershell
Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Stop'
foreach ($simz1Test in @(
    'python/test_simz1_queue_contract.cjs',
    'python/test_simz1_queue_continuity.cjs',
    'python/test_simz1_queue_window_controls.cjs',
    'python/test_simz1_window_identity.cjs',
    'python/test_simz1_visual_queues.cjs',
    'python/test_simz1_queue_safety.cjs',
    'python/test_simz1_visibility_geometry.cjs',
    'python/test_simz1_visibility_temporal.cjs',
    'python/test_simz1_visibility_diagnostics.cjs',
    'python/test_simz1_visibility_history.cjs',
    'python/test_simz1_vehicle_presentation.cjs',
    'python/test_simz1_vehicle_card.cjs',
    'python/test_simz1_rigid_vehicles.cjs'
)) {
    node $simz1Test
    if ($LASTEXITCODE -ne 0) { throw "Falló $simz1Test" }
}
python -B .\python\test_simz1_queue_context.py
if ($LASTEXITCODE -ne 0) { throw 'Falló contexto SQLite sintético.' }
python -B .\python\test_simz1_client_identity.py
if ($LASTEXITCODE -ne 0) { throw 'Falló identidad de cliente.' }
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'Revisar el diff.' }
```

Esperado: salida 0; casos que caben conservan todos los cuerpos separados, casos incompatibles
conservan cuerpo/identidad y aviso, misma semilla mantiene ancla entre ventanas. No certifica GPU/FPS.
Los SQLite temporales de prueba son pequeños; no utilizan corridas históricas.

### Comprobar cliente servido y revisar los mismos vehículos

El servidor captura el HTML ensamblado al arrancar. Recargar la pestaña de un proceso anterior
no incorpora cambios. Tras detener **manualmente su propia terminal del servidor**, el usuario
puede arrancar el mismo replay con fuentes actuales, sin recrear HTML ni SQLite:

```powershell
Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
python -B .\python\serve_simz1_continuous.py --directory .\runtime\simz1-227187-direct\webgl-continuo --port 8793
```

En otra terminal, el inspector comprueba la respuesta HTTP existente. Una salida distinta de 0
indica diferencia o imposibilidad de verificar; no es una prueba aprobada. Después recargar la pestaña existente:

```powershell
Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
python -B .\python\inspect_simz1_client.py --replay-dir .\runtime\simz1-227187-direct\webgl-continuo --url http://127.0.0.1:8793/index.html
if ($LASTEXITCODE -ne 0) { throw 'La respuesta servida no acredita el cliente y replay esperados.' }
```

Este comando copia a portapapeles un procedimiento para pegar **en la consola de esa pestaña**.
Primero comprueba corrida, iteración, manifiesto y huella del cliente cargado; espera cada ventana
antes de inspeccionar los tres vehículos. No confunde una respuesta HTTP con una pestaña recargada.

```powershell
Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$simz1Json = & python -B .\python\inspect_simz1_client.py --replay-dir .\runtime\simz1-227187-direct\webgl-continuo
if ($LASTEXITCODE -ne 0) { throw 'No se pudo identificar el replay local.' }
$simz1Metadata = ($simz1Json -join "`n") | ConvertFrom-Json
$simz1Expected = [ordered]@{
    run_id = $simz1Metadata.run_id
    iteration = $simz1Metadata.iteration
    manifest = $simz1Metadata.run_manifest_sha256
    client = $simz1Metadata.current_client_build.source_sha256
}
$simz1Console = @'
(async () => {
  const expected = __EXPECTED__;
  const api = window.simz1Continuous;
  if (!api) throw new Error('La pestaña no tiene la API continua actual');
  api.pause();
  const provenance = api.getVisualDiagnostics();
  if (provenance.run_id !== expected.run_id || provenance.iteration !== expected.iteration ||
      provenance.run_manifest_sha256 !== expected.manifest ||
      window.simz1ClientBuild?.source_sha256 !== expected.client) {
    throw new Error('Otra corrida o versión: no atribuir estas trazas a la captura');
  }
  const records = [];
  for (const [vehicle, at, times] of [
    ['z1_43360', 124, [123.999,124,124.5,124.999,125,125.001]],
    ['z1_38616', 41, [38.999,39,40.999,41,45.999,46,46.001]],
    ['z1_167074', 169, [168.999,169,169.001]]
  ]) {
    api.seek(at);
    const deadline = Date.now() + 60000;
    while (api.getState().buffering && Date.now() < deadline) {
      if (api.getState().error) throw new Error(api.getState().error);
      await new Promise(resolve => setTimeout(resolve,100));
    }
    if (api.getState().buffering || api.getState().current !== at) throw new Error('Ventana pendiente');
    records.push(...api.traceVehicle(vehicle,times));
  }
  window.simz1LastQueueTrace = {expected, records};
  console.table(records.map(r => ({vehicle:r.vehicle_id,time:r.time,link:r.current_link,
    lane:r.visual_lane,visible:r.visible,reason:r.reason,spacing:r.spacing_compatible})));
  copy(JSON.stringify(window.simz1LastQueueTrace,null,2));
})();
'@
Set-Clipboard -Value $simz1Console.Replace('__EXPECTED__', ($simz1Expected | ConvertTo-Json -Compress))
```

Para cualquier otro vehículo: pausar, hacer clic y pegar lo siguiente en la consola. Al acercar
la cámara, comprobar cuerpo y contorno con las dimensiones del diagnóstico; una incompatibilidad
puede seguir mostrando solapamiento y no constituye una solución física.

```javascript
copy(JSON.stringify(simz1Continuous.traceSelectedVehicle(), null, 2));
```

<a id="ruta-seleccionada"></a>
### Ruta seleccionada: evidencia y comprobación (2026-10-21)

| Causa comprobada en código | Corrección visual |
| --- | --- |
| `path[1]` truncaba curvas al dividir el tramo activo | Recorte por longitud acumulada, conservando vértices y apariciones repetidas. |
| Trazo de 1.5 px con alfa 110/140 | Observado violeta 4 px; posterior registrado claro 2 px; fondos de 6/4 px. No es predicción. |
| `/api/journey` omitía carriles | Lectura indexada del viaje y predecesor, orden `(time,seq)`, misma caché HTTP. Sin evidencia, eje del enlace. |

Cuerpos/halo y color de velocidad se conservan. Ruta sobre carretera y bajo vehículos;
sin conexiones inventadas entre huecos. Carril identificado permite posición lateral aproximada,
limitada a su extensión nativa. Llegada limpia capas; seek inverso restaura la selección.

MATSim 15.0, Java 25 y deck.gl 9.1.14, según fuentes locales. Generadores, física y corridas intactos.
Candidata: `simz1-0dd152dabbc24d1d84d9b738c449cc35`, iteración 0, `sqlite-direct-v1`, 227187 personas.
HTTP 8793 rechazó conexión; navegador/capturas no identificados. Sintaxis JS/AST y diff comprobados;
fixtures y WebGL pendientes. La compilación del HTML ensamblado requirió transporte JSON ASCII por
la codificación cp1252 de PowerShell; no ejecutó el cliente.

Pruebas preparadas, sin servidores ni corridas:

```powershell
Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
foreach ($simz1RouteTest in @(
    'python/test_simz1_selected_route.cjs',
    'python/test_simz1_continuous_bootstrap.cjs',
    'python/test_simz1_continuous_replay.cjs',
    'python/test_simz1_vehicle_focus.cjs',
    'python/test_visualizador_z1_selection.cjs',
    'python/test_simz1_spatial_view.cjs'
)) {
    node $simz1RouteTest
    if ($LASTEXITCODE -ne 0) { throw "Falló $simz1RouteTest" }
}
python -B .\python\test_simz1_journey_lanes.py
if ($LASTEXITCODE -ne 0) { throw 'Falló el fixture SQLite temporal de carriles' }
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'Revisar diff' }
```

Esperado: salida 0, curvas/giro, enlaces repetidos, huecos, carriles nativos, vehículos paralelos,
selección, pausa/cámara/ventanas, llegada y limpieza. No certifica GPU.

Tras detener manualmente su propio servidor, en su terminal:

```powershell
Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
python -B .\python\serve_simz1_continuous.py --directory .\runtime\simz1-227187-direct\webgl-continuo --port 8793
```

En otra terminal, verificar fuentes actuales. Recargar la pestaña, pausar, seleccionar y pegar
el portapapeles en consola. Acercar/rotar, buscar hacia atrás y llegar; ruta limpia y halo preciso.

```powershell
Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$simz1RouteReportRaw = python -B .\python\inspect_simz1_client.py --replay-dir .\runtime\simz1-227187-direct\webgl-continuo --url http://127.0.0.1:8793/index.html
if ($LASTEXITCODE -ne 0) { throw 'Corrida/fuentes HTTP sin verificar; no atribuir capturas' }
$simz1RouteReport = ($simz1RouteReportRaw -join "`n") | ConvertFrom-Json
$simz1RouteExpected = @{
    run_id = $simz1RouteReport.run_id
    iteration = $simz1RouteReport.iteration
    manifest = $simz1RouteReport.run_manifest_sha256
    client = $simz1RouteReport.current_client_build.source_sha256
    source = $simz1RouteReport.source_manifest_sha256
}
$simz1RouteConsole = @'
(async () => {
  const expected = __EXPECTED__, api = window.simz1Continuous;
  api.pause();
  const initial = api.traceSelectedVehicle();
  if (initial.run_id !== expected.run_id || initial.iteration !== expected.iteration ||
      initial.run_manifest_sha256 !== expected.manifest ||
      initial.replay_source?.source_manifest_sha256 !== expected.source ||
      window.simz1ClientBuild?.source_sha256 !== expected.client) {
    throw new Error('Otra corrida, fuente o cliente: recargar y verificar');
  }
  const selected = api.getState().selectedKey;
  if (!selected) throw new Error('Hacer clic sobre un vehículo primero');
  const deadline = Date.now() + 60000;
  while (api.getState().selectedJourneyStatus === 'loading' && Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  if (api.getState().selectedKey !== selected) throw new Error('Cambió la selección');
  if (api.getState().selectedJourneyStatus === 'unavailable') throw new Error(api.getState().selectedJourneyError);
  if (api.getState().selectedJourneyStatus === 'loading') throw new Error('Viaje aún no cargado');
  const route = ['selected-history', 'selected-future'].flatMap(id =>
    (api.layers.find(layer => layer.id === id)?.props.data || []).map(row => ({style:id,...row})));
  window.simz1SelectedRouteReview = {
    expected, trace:api.traceSelectedVehicle(), state:api.getState(), route
  };
  console.table(route.map(row => ({style:row.style,vehicle:row.vehicle,link:row.Link_ID,
    interval:row.timestamps.join('..'),lane:row.lane,evidence:row.position_evidence,vertices:row.path.length})));
  copy(JSON.stringify(window.simz1SelectedRouteReview, null, 2));
})();
'@
Set-Clipboard -Value $simz1RouteConsole.Replace('__EXPECTED__', ($simz1RouteExpected | ConvertTo-Json -Compress))
```

<a id="semaforos-verticales"></a>
### Semáforos verticales (2026-10-21)

Evidencia: el generador asignaba ángulos 0/90 y `IconLayer(billboard=True)`;
la candidata local contiene 312 señales con esos ángulos. El servidor incorpora
la geometría efectiva al arrancar; no está en su `config.json` histórico.

El continuo usa cuatro capas constantes: cabeza/poste instanciados, postes sin rumbo,
luces instanciadas y etiquetas. Compatible con
[SimpleMeshLayer 9.1.14](https://github.com/visgl/deck.gl/blob/v9.1.14/modules/mesh-layers/src/simple-mesh-layer/simple-mesh-layer.ts),
sin modelos externos. [La matriz por instancia](https://github.com/visgl/deck.gl/blob/v9.1.14/modules/mesh-layers/src/utils/matrix.ts)
no contiene cámara: mundo X=este, Y=norte, Z=arriba; malla frente=+Y.
Tangente terminal dirigida `u`; frente `f=-u`; derecha `(f.y,-f.x)`.
Rumbo entrante `atan2(u.x,u.y)`, desde norte en sentido horario.
Curvas usan su último segmento no degenerado, conservando ancla y carriles originales.

Altura 3.9 m, cabeza 0.65×1.3×0.36 m: **supuestos visuales**, no medidas reales.
Etiqueta R/A/V, R+A, OFF o ? legible desde arriba; no representa orientación física.
Sin rumbo verificable: poste/etiqueta y motivo explícito, sin inventar cabeza.
Estados/tiempos/grupos intactos. La revisión de
[updateTriggers](https://deck.gl/docs/api-reference/core/layer#updatetriggers)
permite actualizar estado al cargar una ventana manteniendo el mismo tiempo pausado.

Ejecutado: sintaxis JS/HTML ensamblado, AST Python y diff. Fixtures/GPU pendientes.
HTTP 8793 rechazado; navegador no identificado. Corrida candidata y manifiesto: sección anterior.

```powershell
Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
foreach ($simz1SignalTest in @(
    'python/test_simz1_signal_geometry.cjs',
    'python/test_simz1_continuous_bootstrap.cjs',
    'python/test_simz1_continuous_replay.cjs',
    'python/test_visualizador_z1_controls.cjs'
)) {
    node $simz1SignalTest
    if ($LASTEXITCODE -ne 0) { throw "Falló $simz1SignalTest" }
}
python -B .\python\test_simz1_client_identity.py
if ($LASTEXITCODE -ne 0) { throw 'Falló identidad de cliente' }
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'Revisar diff' }
```

Esperado: salida 0; matrices/anclas/IDs invariantes a 0/90/180/270° y pitch 0/30/45/60°;
curvas, opuestos, carriles, capas vacías, cronología, pausa/seek/ventanas y carga inicial.
En la revisión visual, el frente debe mirar hacia el acceso y el dorso mostrar carcasa.

Tras detener manualmente su propio servidor, arrancar en su terminal:

```powershell
Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
python -B .\python\serve_simz1_continuous.py --directory .\runtime\simz1-227187-direct\webgl-continuo --port 8793
```

En otra terminal, verificar y preparar consola; recargar la pestaña y pegar:

```powershell
Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$simz1SignalRaw = python -B .\python\inspect_simz1_client.py --replay-dir .\runtime\simz1-227187-direct\webgl-continuo --url http://127.0.0.1:8793/index.html
if ($LASTEXITCODE -ne 0) { throw 'Corrida/fuentes HTTP sin verificar' }
$simz1SignalReport = ($simz1SignalRaw -join "`n") | ConvertFrom-Json
$simz1SignalExpected = @{
    run_id=$simz1SignalReport.run_id
    iteration=$simz1SignalReport.iteration
    manifest=$simz1SignalReport.run_manifest_sha256
    source=$simz1SignalReport.source_manifest_sha256
    client=$simz1SignalReport.current_client_build.source_sha256
}
$simz1SignalConsole = @'
(async () => {
  const api=window.simz1Continuous, expected=__EXPECTED__;
  if (!api?.deck?.isInitialized) throw new Error('Esperar inicialización de Deck');
  api.pause();
  const before=api.getSignalDiagnostics();
  if (before.run_id!==expected.run_id || before.iteration!==expected.iteration ||
      before.run_manifest_sha256!==expected.manifest ||
      before.replay_source?.source_manifest_sha256!==expected.source ||
      window.simz1ClientBuild?.source_sha256!==expected.client) throw new Error('Otra corrida, fuente o cliente');
  if (api.getState().buffering) throw new Error('Esperar la ventana antes de comparar estados');
  console.table(before.issues);
  if (!before.oriented) throw new Error('Sin geometría dirigida verificable: revisar diagnóstico');
  const initialCamera={...api.getState().camera.viewState}, poses=JSON.stringify(before.records), views=[];
  try {
    for (const bearing of [0,90,180,270]) for (const pitch of [0,30,60]) {
      api.deck.props.onViewStateChange({viewState:{...initialCamera,bearing,pitch}});
      await new Promise(resolve=>setTimeout(resolve,1000));
      const after=api.getSignalDiagnostics();
      if (JSON.stringify(after.records)!==poses) throw new Error('Cambió ancla, acceso o pose con la cámara');
      if (JSON.stringify(after.states)!==JSON.stringify(before.states)) throw new Error('Cambió el estado estando pausado');
      views.push({bearing,pitch,oriented:after.oriented,time:after.time});
    }
  } finally {
    api.deck.props.onViewStateChange({viewState:initialCamera});
  }
  window.simz1SignalReview={expected,diagnostics:before,views};
  console.table(views);
  copy(JSON.stringify(window.simz1SignalReview,null,2));
})();
'@
Set-Clipboard -Value $simz1SignalConsole.Replace('__EXPECTED__', ($simz1SignalExpected | ConvertTo-Json -Compress))
```

<a id="aviso-llegada"></a>
## Aviso de llegada: cinco segundos reales

Evidencia: `simz1_trajectories.py` confirma `Trip.Arrival` mediante llegada nativa;
`System_Exit` solo acredita salida. El RAF anterior no redibujaba durante pausa.
MATSim 15.0, deck.gl 9.1.14; generadores y servidor continuo sin cambios.

| Condición | Tratamiento visual |
|---|---|
| Llegada confirmada atravesada entre frames | Anotación en `Destination_Position`, 5000 ms de `performance.now()` |
| Pausa/buffering/120x | Un gestor y RAF compartidos; duración real constante |
| Seek/cambio de corrida | Limpieza; sin avisos retrospectivos |
| Aborto/censura/salida exterior/parada de bus | Sin aviso de llegada |
| Posición desconocida/fin de servicio no registrado | Exclusión explícita en diagnóstico |

La anotación circular conserva el color disponible del agente y pulsa hacia blanco;
no prolonga su carrocería ni participa en colas, colisiones o conteos. Hay alternativa
sin alternancia. Un frame lento que saltaría ventanas completas visita primero la
siguiente; los cruces normales mantienen su tiempo fraccional.

Archivos: `simz1_arrival_effects.js`, controles, plantilla, ensamblador y cuatro fixtures
(llegadas, replay, bootstrap, identidad). Solo documentación en ambos README.
Ejecutado: sintaxis JS/HTML ensamblado, AST Python, diff e identidad por metadatos.
Pendiente: pruebas funcionales y GPU. La corrida candidata 227187/iteración 0/SQLite
directo conserva sus manifiestos; la pestaña no está identificada. El HTML histórico
difiere de las fuentes actuales.

Identidad inspeccionada: `simz1-0dd152dabbc24d1d84d9b738c449cc35`, iteración 0;
manifiesto nativo SHA-256 `2d93aa7cd197200761917e6cf0c1c7d2848aaeb5102b502e744799bd8814f456`.
Cliente preparado SHA-256 `f67edb1d81b6dcd56e8a3d5931ec16a69a89b72ce314fcb1ca5fb43c90d5f89e`.
La lectura HTTP de 8793 fue rechazada (`WinError 10061`); no acredita tus capturas.

Pruebas preparadas; resultado esperado: salida 0, vencimiento exacto del gestor,
limpieza al primer RAF vencido, sin alterar eventos ni conteos:

```powershell
Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
foreach ($simz1ArrivalTest in @(
    'python/test_simz1_arrival_effects.cjs',
    'python/test_simz1_continuous_replay.cjs',
    'python/test_simz1_continuous_bootstrap.cjs',
    'python/test_visualizador_z1_controls.cjs'
)) {
    node $simz1ArrivalTest
    if ($LASTEXITCODE -ne 0) { throw "Falló $simz1ArrivalTest" }
}
python -B .\python\test_simz1_client_identity.py
if ($LASTEXITCODE -ne 0) { throw 'Falló identidad de cliente' }
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'Revisar diff' }
```

Tras detener manualmente **su propio servidor**, reiniciarlo sin reexportar:

```powershell
Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
python -B .\python\serve_simz1_continuous.py --directory .\runtime\simz1-227187-direct\webgl-continuo --port 8793
```

En otra terminal, verificar fuentes y copiar revisión a consola; recargar la pestaña:

```powershell
Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$simz1ArrivalRaw = python -B .\python\inspect_simz1_client.py --replay-dir .\runtime\simz1-227187-direct\webgl-continuo --url http://127.0.0.1:8793/index.html
if ($LASTEXITCODE -ne 0) { throw 'Corrida/fuentes HTTP sin verificar' }
$simz1ArrivalReport = ($simz1ArrivalRaw -join "`n") | ConvertFrom-Json
$simz1ArrivalExpected = @{
    run_id=$simz1ArrivalReport.run_id
    iteration=$simz1ArrivalReport.iteration
    manifest=$simz1ArrivalReport.run_manifest_sha256
    source=$simz1ArrivalReport.source_manifest_sha256
    client=$simz1ArrivalReport.current_client_build.source_sha256
}
$simz1ArrivalConsole = @'
window.reviewSimZ1Arrival=async (speed=120) => {
  const api=window.simz1Continuous, expected=__EXPECTED__;
  if (!api?.deck?.isInitialized) throw new Error('Esperar Deck');
  api.pause();
  const diagnostic=api.getArrivalDiagnostics();
  if (diagnostic.run_id!==expected.run_id || diagnostic.iteration!==expected.iteration ||
      diagnostic.run_manifest_sha256!==expected.manifest ||
      diagnostic.replay_source?.source_manifest_sha256!==expected.source ||
      window.simz1ClientBuild?.source_sha256!==expected.client) throw new Error('Otra corrida/fuente/cliente');
  const candidate=window.simz1ArrivalReview?.candidate ?? diagnostic.upcoming.find(row=>
    row.arrival>api.getState().current && row.arrival-row.observed_through<=2);
  if (!candidate) {
    console.table(diagnostic.excluded_examples);
    throw new Error('Sin llegada cercana acreditada en esta ventana; reproducir otro tramo y repetir. No se inventan llegadas.');
  }
  const same=row=>row.vehicle_id===candidate.vehicle_id && row.trip_id===candidate.trip_id;
  const frame=()=>new Promise(requestAnimationFrame);
  const waitUntil=async condition=>{
    const deadline=performance.now()+60000;
    while(!condition()) {
      if(performance.now()>=deadline) throw new Error('No llegó la ventana/aviso en 60 s; revisar buffering y evidencia');
      await frame();
    }
  };
  api.seek(Math.max(0,Math.min(candidate.arrival-.1,candidate.observed_through-.1)));
  await waitUntil(()=>!api.getState().buffering);
  if(!api.getArrivalDiagnostics().upcoming.some(same))
    throw new Error('La ventana del seek no contiene evidencia de esta llegada; revisar el diagnóstico, sin forzar el aviso');
  api.setArrivalStyle('soft_pulse'); // Alternativa: 'steady_tint_and_fade'.
  api.setSpeed(speed);api.play();
  let effect;
  await waitUntil(()=>Boolean(effect=api.getArrivalDiagnostics().active.find(same)));
  api.pause(); // El aviso debe seguir venciendo con el reloj simulado detenido.
  const paused=api.getState(),samples=[];
  while(performance.now()<effect.expires_ms+100) {
    const state=api.getState(),row=api.getArrivalDiagnostics().active.find(same);
    if(state.current!==paused.current) throw new Error('El replay avanzó estando pausado');
    samples.push({real_elapsed_ms:performance.now()-effect.started_ms,
      simulated_time:state.current,remaining_ms:row?.remaining_ms ?? 0,
      color:row?.color ?? null,active_agents:state.activeAgents,visible_vehicles:state.visibleMarkers});
    await frame();
  }
  if(api.getArrivalDiagnostics().active.some(same) ||
      api.layers.find(layer=>layer.id==='arrival-annotations').props.data.some(same))
    throw new Error('Marcador no retirado');
  if(effect.expires_ms-effect.started_ms!==5000) throw new Error('Duración incorrecta');
  window.simz1ArrivalReview={expected,candidate,speed,effect,paused,samples};
  console.table(samples.filter((row,index)=>index%30===0));
  copy(JSON.stringify(window.simz1ArrivalReview,null,2));
};
await window.reviewSimZ1Arrival(120);
// Repetir los mismos IDs con: await window.reviewSimZ1Arrival(1);
// El getter explica también censura, buses sin fin de servicio y salidas exteriores:
// console.table(window.simz1Continuous.getArrivalDiagnostics().excluded_examples);
'@
Set-Clipboard -Value $simz1ArrivalConsole.Replace('__EXPECTED__', ($simz1ArrivalExpected | ConvertTo-Json -Compress))
```

<a id="conectividad-19-20"></a>
## Revisión focal: 19/20 Avenida y calles 21–23

### Comprobación actual del 22/10/2026

El [informe reproducible](../scenarios/zona1/versions/connectivity-inspection-2026-10-22/connectivity-inspection.json)
contrasta OSM local, red base, red/carriles efectivos de 227187 personas y geometrías
calculadas por el renderer. Conserva hashes, IDs, componentes y diez rutas testigo.
El manifiesto histórico no fija el OSM original: la comparación corresponde a la
fuente local actual. No es una verificación GIS de campo.

**Resultado:** 1385 vías highway, 909 admisibles, 6183 segmentos dirigidos esperados
y 6183 enlaces `car`. Cero segmentos admisibles ausentes, discrepancias de
fuente/acceso/sentido o duplicados. La red base y la salida histórica tienen la misma
topología y parámetros normalizados. No se demostró un defecto de importación que
justifique otra red física; XML, escenarios históricos y renderer permanecen intactos.

Los 4214 nodos conservan su ID y posición OSM transformada a EPSG:32615: error máximo
`6,956e-7 m`, inferior a la tolerancia explícita `1e-4 m`; ninguna referencia highway
carece de nodo. Se verifican CRS, carriles y enrutamiento enlace–enlace activados,
rutas configuradas y equivalencia de movimientos entre carriles de entrada y salida
histórica. Las configuraciones incompatibles se rechazan antes de certificar un grafo.

Sí se corrigió el **auditor**: la salida nativa comprimida guarda `origid` como
atributo XML anidado. Ahora se leen ambos formatos y namespaces sin deducir
procedencia por el nombre del enlace. Así se evitan falsos diagnósticos de enlaces
sin procedencia al revisar una corrida real.

El grafo efectivo por carril contiene 10385 transiciones, diez componentes débiles
y 547 fuertes. El mayor débil contiene 5930 enlaces; el mayor fuerte, 5195.
Los 76 enlaces focales pertenecen a dos componentes débiles separados del principal:
`car:weak:a1101e07ddd7289e` (50) y `car:weak:7287c0d7fdd2b59f` (26). No se elimina
ninguna isla. Estos permisos configurados no certifican legalidad de giros OSM.

Los tres conectores corregidos el 21/10, identificados en la tabla del antecedente
inferior, **siguen presentes**; no se volvió a modificar su dibujo. Hay 118 movimientos
focales y cero movimientos no reversos sin representación geométrica. La corrida
tiene `spatial_demand=null`: no hay recorte por polígono activo que explique los extremos.

La revisión global calcula 7519 franjas, 1929 conectores y 298 curvas esquemáticas.
Los 35 avisos `unsafe_joint_not_stitched` no demuestran cortes nuevos: 29 pares
`service` tienen centros separados 0,321–2,187 m pero franjas de 2,46 m solapadas;
dos pares de `osm_1107835856` coinciden y cuatro conservan su eje nativo.
Las cuatro cadenas con fallback son ways `1190085138` (7 enlaces), `1271322490` (10),
`1305258455` (10) y `406701907` (13); sus nodos consecutivos coinciden.
`visual.global_geometry_issues` conserva los 39 registros y IDs, sin truncamiento.
La prueba de solapamiento es geométrica 2D, **no inspección GPU/píxel**. Los 770
destinos de carril ambiguos y 2905 retornos sin curva no autorizan a añadir giros.

La tabla del antecedente conserva los IDs focales y las decisiones de no unir por
proximidad. Se amplía con evidencia concreta fuera del sector:

| Enlaces/fuente | Evidencia y decisión |
|---|---|
| Way `30262983`, 9a Avenida, nodos `410439772→12089068111` | `access=private`, cero enlaces `car`; no abrir. |
| `osm_42841172_0..5_forward`, `osm_1208184514_0..3_forward`, 19 Calle | `bridge=yes`, `layer=1`; no unir a calzadas de otro nivel. |
| Ways `1392432599/1392432600` | `service`, `tunnel=building_passage`, `layer=-1`, sentido único; conservar nivel. |
| Ways `1392432604/1392432605/1392432607` | `tunnel=building_passage`, sin `layer` explícito; no inventar nivel ni conexión. Las dos primeras son unidireccionales. |
| `osm_64401506_0_forward/backward`; `osm_30279775_0..4_forward/backward` | Nodos terminales `9484261160` (11 Avenida) y `333720739` (4a Calle A) con `noexit=yes`: callejones declarados por OSM, sin apertura artificial. Hay 19 nodos `noexit=yes`, ninguno focal. |
| Way `35137628`, 21 Calle; way `35137622`, 23 Calle | Extremos exteriores `792485109` y `412163034`: continuación desconocida, no callejón certificado. |

Las **19 restricciones pendientes** dan filas idénticas en red base y salida histórica:

| Relaciones OSM | Estado actual |
|---|---|
| `6008781`, `6016436`, `17146405`, `17146406`, `17373677`, `17475192`, `17502672`, `17947071`, `20224530`, `20224531` | Diez via-node mapeables: carriles nativos todavía admiten el movimiento prohibido. |
| `17478998` | Via-way: secuencia completa admitida; requiere memoria de recorrido, no prohibición global del último giro. |
| `14106857` | Destino way `1057416031`, `access=no,bus=designated`: correctamente fuera de `car`. |
| `20739983` | Destino way `1521207433`, `highway=busway,access=no`: correctamente fuera de `car`. |
| `17275374`, `17354173`, `20739957`, `20739958` | Vías miembro ausentes de la fuente local; IDs en `restrictions.rows`. No es prueba de omisión del importador. |
| `17884471`, `20224473` | Estructuras incompletas: faltan from/via o from, respectivamente. |

La propuesta anterior permanece intacta, `review_only_blocked`, no aplicada ni
ejecutable. El importador rechaza restricciones activas antes de escribir. El
validador físico actual exige todas las salidas adyacentes; su contrato también
debe revisarse antes de aplicar prohibiciones de giro. No se genera una supuesta
red corregida mientras falten semántica via-way, fuente completa y contrato nativo.

| Testigo | Nodo origen → destino | Resultado configurado |
|---|---|---|
| W01 | `412162798 → 412162814` | Ruta de 8 enlaces |
| W02 | `412162798 → 7295814876` | Ruta de 8 enlaces |
| W03 | `412162909 → 412162813` | Búsqueda agotada, sin ruta |
| W04 | `412162813 → 412162909` | Búsqueda agotada, sin ruta |
| W05 | `412162814 → 7295814876` | Búsqueda agotada, sin ruta |
| W06 | `412160765 → 412162814` | Ruta de 2 enlaces |
| W07 | `333831813 → 412162814` | Búsqueda agotada, sin ruta |
| W08 | `412162814 → 333831813` | Búsqueda agotada, sin ruta |
| W09 | `412162798 → 412163034` | Ruta de 11 enlaces |
| W10 | `412163034 → 412162798` | Sin enlace de salida, sin ruta |

Las secuencias completas están en `base.witness_routes` y
`historical.review.witness_routes`. Son búsquedas estáticas, no viajes observados
del replay. Se buscan secuencias prohibidas contiguas completas; ninguna búsqueda
se cortó por límite. Con relaciones pendientes, ninguna ruta se certifica legal.

Para una **futura corrida** hace falta ampliar la fuente exterior para investigar
cómo conectar los componentes al principal: vías completas, nodos, miembros de
restricciones, accesos y niveles. Ningún buffer fijo garantiza completitud. Los
extremos del extracto no acreditan callejones y el rectángulo de inspección no es
una frontera administrativa. Se conservan las cuatro clases OD y gateways
dirigidos; no se exige que todo punto permita todos los movimientos.

Inspección offline del mapa actual y su salida histórica, solo lectura/stdout.
No abre SQLite, planes ni eventos; no necesita servidor. Usar el entorno existente
con `pyproj` y Node:

```powershell
Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$simz1AuditRaw = & .\.venv\Scripts\python.exe -B .\python\inspect_simz1_connectivity.py --run-dir .\scenarios\zona1\montecarlo\run-massive-fixed-97e840b02c044fc39497debc91300a6d
if ($LASTEXITCODE -ne 0) { throw 'Falló la inspección offline' }
$simz1Audit = ($simz1AuditRaw -join "`n") | ConvertFrom-Json
$simz1Audit.base.summary
$simz1Audit.base.witness_routes | Select-Object from_node,to_node,status,links | Format-Table -Wrap
$simz1Audit.visual.summary
$simz1Audit.restrictions.rows | Select-Object relation_id,status,admitting_movements,path_status | Format-Table -Wrap
# Alternativa: leer directamente la evidencia entregada.
$simz1Audit = Get-Content -Encoding UTF8 -Raw .\scenarios\zona1\versions\connectivity-inspection-2026-10-22\connectivity-inspection.json | ConvertFrom-Json
```

Para una red futura **ya preparada en otra carpeta**, sustituir las rutas de ejemplo.
El inspector comprueba fuente, configuración, nodos, segmentos y testigos; el límite
de gateways debe ser un GeoJSON explícito aprobado, nunca el bbox de descarga.
Son comprobaciones estáticas; no arrancan simulaciones ni cambian la candidata:

```powershell
$simz1Candidate = '.\scenarios\zona1\versions\VERSION_REVISADA'
$simz1Boundary = '.\scenarios\zona1\LIMITE_APROBADO.geojson'
& .\.venv\Scripts\python.exe -B .\python\inspect_simz1_connectivity.py --scenario $simz1Candidate --approved-boundary $simz1Boundary --strict
# Código 2 = bloqueos explícitos. No promover ni ejecutar una red bloqueada.
& .\.venv\Scripts\python.exe -B .\python\simz1_lane_validation.py --config "$simz1Candidate\config-simz1.xml"
# El éxito estático no certifica estabilidad física ni sustituye validación nativa futura.
```

`--output-new CARPETA_NUEVA` guarda solo evidencia JSON y rechaza carpetas existentes.
No usar una corrida como destino. En la red actual `--strict` devuelve 2 por el
contrato de restricciones pendiente y la falta de límite aprobado. Las pruebas
actuales incluyen los fixtures del antecedente, `test_inspect_simz1_connectivity.py`,
`test_simz1_four_od.py`, `test_simz1_gateway_od.py`, `test_simz1_transit_stops.cjs` y
`test_simz1_signal_geometry.cjs`; se ejecutaron sin servidores, navegador ni MATSim.
Resultado: **56 pruebas Python y siete suites Node aprobadas**; `git diff --check`
sin errores. El CLI estricto se comprobó y devuelve 2 con los dos bloqueos descritos.
Los fixtures de demanda son mínimos y temporales. La inspección visual de cámara
y zoom queda preparada en los comandos manuales del antecedente.

### Antecedente conservado del 21/10/2026

Inspección del 21/10/2026 sobre OSM/red/carriles actuales: 11 vías, 76 enlaces,
ningún segmento dirigido admisible ausente. El grafo contiene 6183 enlaces `car`;
no acredita rutas nativas `walk`, `bike` o `pt`. No se elimina ningún componente.
La geometría local no es cartografía GIS verificada.

La [propuesta de versión](../scenarios/zona1/versions/connectivity-review-v1/scenario-revision.json)
contiene `sector_review.links`: clasificación **por cada ID**, movimientos por modo/carril,
extremos, rutas testigo, hashes raw/LF y limitaciones. Es un paquete JSON pequeño,
**no ejecutable**, sin red/demanda nueva generada. El [parche declarativo](../scenarios/zona1/versions/connectivity-review-v1/lane-movement-proposal.json)
no está aplicado a ningún escenario.

| Enlaces/fuente | Clasificación y decisión |
|---|---|
| `osm_35137582_0..5_forward`, 19 Avenida | Sentido sur; extremo `412144684` fuera del extracto. Continuación exterior desconocida, no callejón certificado. |
| `osm_35137583_0..6_forward`, 20 Avenida | Sentido norte; inicio `412162798` exterior. No crear el reverso. |
| `osm_375611743_16_forward`, 22 Calle | Conecta 20→19 Avenida. El reverso falta por `oneway=yes`, no por importación. |
| `osm_400885349_0_forward/backward` y `osm_35137628_0_forward/backward` | Extremos `412162814` y `7295814876`, separados aproximadamente 10,86 m, sin nodo compartido en OSM. Causa física pendiente; no unir. |
| `osm_35137622_0..5_forward`, 23 Calle | Conexión real con 20 Avenida en `412163018`; continuación exterior desconocida. |
| `osm_35137290_*`, 18 Avenida A | Extremos interiores `412160764/412160766` sin otras vías OSM. Causa pendiente; no declarar callejón real. |
| Ways `1307272542`, `45683062` | Peatonales, excluidas del grafo `car`; no habilitarlas como calles vehiculares. |
| Recorte, accesos privados y desniveles | Candidata sin `spatial_demand`: no explica recorte. Sin caso local demostrado de privado/desnivel; fixtures conservan sus exclusiones. No conectar puentes/túneles por intersección geométrica. |

El renderer rechazaba conectores cuando los extremos desplazados de carril retrocedían
respecto de la tangente. Se corrige únicamente el dibujo de estos movimientos ya admitidos:

| Entrada → salida (IDs con prefijo `osm_`) | Nodo |
|---|---|
| `1059594347_0_backward` → `35137582_0_forward` | `412162813` |
| `35137583_6_forward` → `35137628_1_forward` | `412162909` |
| `375611743_16_forward` → `400885349_0_forward` | `412162813` |

La curva esquemática exige mismo nodo/nivel, permiso y un carril inequívoco por lado.
Su retroceso de 3,5 m en estos casos está marcado `inferred_visual_only`; no interviene
en cuerpos, colas o física. Falta de espacio, giro U y carril ambiguo siguen diagnosticados.

Restricciones recalculadas: **19 activas**; diez via-node admitidas, una via-way admitida,
seis sin representación `car` y dos estructuras incompletas. `17478998` conserva la secuencia
`osm_1273145789_0_forward` → `osm_1270930401_0_forward` → `osm_1273145790_0_forward`;
no se transforma en una prohibición global del último giro. De las seis fuera de `car`,
`14106857` y `20739983` llevan a accesos de bus excluidos correctamente; las otras cuatro
tienen vías ausentes. No se confunde falta de fuente con error de importación.

Versión `simz1-connectivity-review-v1-234d148bb22c`: 22 eliminaciones propuestas de destinos
de carril, diez relaciones, 21 IDs de carril conservados y 16 referencias semafóricas
preservadas; ningún terminal quedaría vacío. `combined_lane_targets` combina restricciones
del mismo carril sin reintroducir giros. IDs de nodos/enlaces/carriles/señales permanecen
idénticos; grupos, ciclos, offsets y parámetros físicos no cambian.
**Bloqueos explícitos:** semántica via-way con memoria, fuentes incompletas, contrato OSM
de validación/enrutamiento y límite aprobado. El validador actual exige todas las salidas
adyacentes: no se relajó para aceptar la propuesta. Se mantienen las cuatro clases OD;
ninguno de los rectángulos utilizados constituye frontera administrativa aprobada.

Candidata del visor: `simz1-0dd152dabbc24d1d84d9b738c449cc35`, iteración 0, `sqlite-direct-v1`;
manifiesto nativo `2d93aa7cd197200761917e6cf0c1c7d2848aaeb5102b502e744799bd8814f456`.
Cliente preparado `5c4c00a3672d1b64ebc4b1f042de41fd79381755b0fa352da62b05d7ffe8e92b`.
HTTP 8793 rechazó la conexión; pestaña/capturas no identificadas. MATSim 15.0/deck.gl 9.1.14;
generadores productivos y servidor continuo inspeccionados, sin modificación.

Archivos: `simz1_visual_lanes.js`, `simz1_osm_turn_audit.py`,
`simz1_connectivity_review.py`, `prepare_simz1_connectivity_revision.py`, sus cuatro fixtures,
los dos JSON nuevos y ambos README. Ejecutado: inspecciones acotadas, propuesta JSON,
AST, sintaxis JS y diff. Pruebas funcionales/GPU **no ejecutadas**.

Comandos de lectura: muestran clasificación y rutas testigo conservadas en el paquete.
La ruta `412160765→412162814` usa `osm_1059594347_0_backward`, `osm_400885349_0_forward`.
Las búsquedas `412162813↔412162909` y `412162814↔333831813` se agotaron sin ruta configurada;
son resultados del grafo/carriles actuales, no certificación legal de todos los giros OSM.

```powershell
Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$simz1Connectivity = Get-Content -LiteralPath .\scenarios\zona1\versions\connectivity-review-v1\scenario-revision.json -Raw | ConvertFrom-Json
$simz1Connectivity | Select-Object version_id,status,runnable
$simz1Connectivity.sector_review.links | Select-Object id,name,from,to,@{N='clasificacion';E={$_.classification -join '; '}} | Format-Table -Wrap
$simz1Connectivity.sector_review.witness_routes | Select-Object from_node,to_node,mode,status,@{N='enlaces';E={$_.links -join ' > '}} | Format-Table -Wrap
$simz1Connectivity.blockers | ConvertTo-Json -Depth 30
# Inspección focal actual, solo lectura/stdout; no genera XML ni población.
python -B .\python\simz1_connectivity_review.py
if ($LASTEXITCODE -ne 0) { throw 'Falló inspección de conectividad' }
# Reconstruye la propuesta solo EN MEMORIA: omitir --output-new no escribe nada.
python -B .\python\prepare_simz1_connectivity_revision.py --scenario .\scenarios\zona1
if ($LASTEXITCODE -ne 0) { throw 'Falló revisión de procedencia/restricciones' }
```

Fixtures preparados: salida esperada 0, tres conectores esquemáticos compatibles, ningún
enlace nuevo, acceso/sentido/nivel preservados, secuencia via-way completa y propuesta
rechazada como escenario ejecutable. No ejecutar MATSim para estas comprobaciones:

```powershell
Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
foreach ($simz1ConnectivityTest in @(
    'python/test_simz1_connectivity_review.py',
    'python/test_simz1_osm_turn_audit.py',
    'python/test_inspect_simz1_connectivity.py',
    'python/test_simz1_connectivity_revision.py',
    'python/test_simz1_road_semantics.py',
    'python/test_simz1_four_od.py',
    'python/test_simz1_gateway_od.py'
)) {
    & .\.venv\Scripts\python.exe -B $simz1ConnectivityTest
    if ($LASTEXITCODE -ne 0) { throw "Falló $simz1ConnectivityTest" }
}
foreach ($simz1ConnectivityTest in @(
    'python/test_simz1_visual_connectivity.cjs',
    'python/test_simz1_parallel_geometry.cjs',
    'python/test_simz1_visual_lanes.cjs',
    'python/test_simz1_spatial_view.cjs',
    'python/test_simz1_continuous_bootstrap.cjs',
    'python/test_simz1_transit_stops.cjs',
    'python/test_simz1_signal_geometry.cjs'
)) {
    node $simz1ConnectivityTest
    if ($LASTEXITCODE -ne 0) { throw "Falló $simz1ConnectivityTest" }
}
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'Revisar diff' }
```

Para revisar el dibujo histórico con fuentes actuales, detener manualmente el servidor
propio si existe y arrancarlo en su terminal; no reexportar ni sustituir SQLite:

```powershell
Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
python -B .\python\serve_simz1_continuous.py --directory .\runtime\simz1-227187-direct\webgl-continuo --port 8793
```

En otra terminal, verificar identidad/fuentes y copiar a consola de la pestaña recargada:

```powershell
Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$simz1ConnectivityRaw = python -B .\python\inspect_simz1_client.py --replay-dir .\runtime\simz1-227187-direct\webgl-continuo --url http://127.0.0.1:8793/index.html
if ($LASTEXITCODE -ne 0) { throw 'Corrida o fuentes HTTP sin verificar' }
$simz1ConnectivityClient = ($simz1ConnectivityRaw -join "`n") | ConvertFrom-Json
$simz1ConnectivityExpected = @{
    run_id=$simz1ConnectivityClient.run_id; iteration=$simz1ConnectivityClient.iteration
    manifest=$simz1ConnectivityClient.run_manifest_sha256
    source=$simz1ConnectivityClient.source_manifest_sha256
    client=$simz1ConnectivityClient.current_client_build.source_sha256
}
$simz1ConnectivityConsole = @'
(() => {
  const api=window.simz1Continuous, expected=__EXPECTED__;
  if(!api?.deck?.isInitialized) throw new Error('Esperar Deck');
  api.pause();
  const provenance=api.getVisualDiagnostics();
  if(provenance.run_id!==expected.run_id || provenance.iteration!==expected.iteration ||
     provenance.run_manifest_sha256!==expected.manifest ||
     provenance.replay_source?.source_manifest_sha256!==expected.source ||
     window.simz1ClientBuild?.source_sha256!==expected.client) throw new Error('Otra corrida/fuente/cliente');
  const pairs=[['osm_1059594347_0_backward','osm_35137582_0_forward'],
    ['osm_35137583_6_forward','osm_35137628_1_forward'],
    ['osm_375611743_16_forward','osm_400885349_0_forward']];
  const connectors=api.layers.find(layer=>layer.id==='visual-turn-connectors')?.props.data || [];
  const result=pairs.map(([from,to])=>({from,to,rows:connectors.filter(row=>row.Link_ID===from && row.To_Link_ID===to)}));
  console.table(result.map(row=>({from:row.from,to:row.to,count:row.rows.length,
    source:row.rows[0]?.source,setback_m:row.rows[0]?.setback_m})));
  const original={...api.getState().camera.viewState};
  api.deck.props.onViewStateChange({viewState:{...original,longitude:-90.50515,latitude:14.6267,zoom:18,pitch:35}});
  window.simz1ConnectivityReview={expected,result,originalCamera:original,
    geometry:api.getState().visualLanes.geometry};
  copy(JSON.stringify(window.simz1ConnectivityReview,null,2));
  // Restaurar: api.deck.props.onViewStateChange({viewState:window.simz1ConnectivityReview.originalCamera});
})();
'@
Set-Clipboard -Value $simz1ConnectivityConsole.Replace('__EXPECTED__', ($simz1ConnectivityExpected | ConvertTo-Json -Compress))
```

<a id="motos-futuras"></a>
### Motos y parámetros de pesados: escenario futuro versionado

Evidencia inspeccionada: `pom.xml` y el JAR de fuentes local corresponden a
MATSim 15.0; Java objetivo 25. `vehicle-types.xml` maestro solo define carros
Normal/Liebre/Tortuga, 4,5 × 1,8 m, PCU 1 y techos 50/90/20 km/h.
`agent-types-v2.json` era otra propuesta: seis categorías, Motociclista a
60 km/h, Tortuga a 25 km/h, PT 10 % y pesados con velocidad sin definir.
Ambos archivos permanecen intactos. Los generadores revisados son
`prepare_simz1.py`, `generate_montecarlo_z1.py` y `prepare_simz1_agents.py`.
El cliente continuo sigue fijado a deck.gl 9.1.14 y el servidor conserva
`serve_simz1_continuous.py`, cachés concurrentes y SQLite directo. No se inició
ninguno ni se comprobó una sesión del navegador.

El nuevo `scenarios/zona1/agent-types-road-v1.json` es una configuración
**sintética, no observada**, con esquema `simz1-road-profiles-v1` y versión
`simz1-road-profiles-v1-synthetic-example`. Solo entra mediante `--agent-catalog`
en una carpeta de corrida nueva. Omitir la opción conserva el generador
histórico de `generate_montecarlo_z1.py`. El preparador de asignaciones
`prepare_simz1_agents.py` usa ahora el catálogo vial nuevo por defecto; reproducir
la propuesta antigua de seis tipos exige su ruta explícita y no habilita PT
en una simulación. No se renombran personas, vehículos o viajes. `Motociclista` se
reutiliza como identificador del tipo normal; las dos variantes emplean los
alias existentes `MotocicletaLenta` y `MotocicletaRapida`. La familia y el perfil
son atributos separados; las etiquetas no crean vehículos.

| Tipos del ejemplo | Familia / perfil | Etiqueta | Longitud × ancho asumidos | PCU | Máximo configurado |
|---|---|---|---|---|---|
| Normal | carro / normal | Carro | 4,5 × 1,8 m | 1 | 50 km/h |
| Liebre | carro / liebre | Carro liebre | 4,5 × 1,8 m | 1 | 90 km/h |
| Tortuga | carro / tortuga | Carro Tortuga | 4,5 × 1,8 m | 1 | 25 km/h |
| MotocicletaLenta | moto / tortuga | Moto tortuga | 2,1 × 0,8 m | 0,25 | 30 km/h |
| Motociclista | moto / normal | Moto | 2,1 × 0,8 m | 0,25 | 50 km/h |
| MotocicletaRapida | moto / liebre | Moto Liebre | 2,1 × 0,8 m | 0,25 | 70 km/h |
| TransportePesado | pesado / normal | Transporte pesado | 10 × 2,5 m | 3,5 | 50 km/h, propuesta bloqueada |

Son parámetros de entrada propuestos, **no parámetros efectivos de una nueva
simulación ejecutada**. Las dimensiones pasan al XML y, al exportar un replay
futuro, a `Vehicle_Dimensions` con fuente, bandera `assumed` y SHA del artefacto
verificado. No se reconstruye ningún SQLite histórico. PCU no escala cuerpos,
márgenes o tolerancia del mouse. Permanecen los cuerpos rígidos, la tarjeta de
seis campos y «Personas generadas: N».

Cada perfil permite `maximum_speed_kmh` y `routing_preference` (`fastest-time`
o `shortest-distance`). Se exige lento < normal < rápido. El costo usa segundos
o metros, respectivamente; la estimación temporal siempre conserva el mínimo
físico de enlace/vehículo y las demoras observadas. La política se aplica al
ruteo inicial y al ruteo durante la simulación, cuyas evidencias registran la
unidad del costo. El ruteo global sigue en `fastest-time`; la elección individual
es explícita. Una ruta más corta puede tardar más. Ninguna política concede
acceso, suprime giros/carriles o abre un semáforo. Las restricciones específicas
`motorcycle` no soportadas bloquean el preflight en Python y Java.

La fuente local `DefaultLinkSpeedCalculator.getMaximumVelocity` usa
`min(vehicle.maximumVelocity, link.freespeed(time))`. `QueueWithBuffer` calcula
salida de cola con tiempo discretizado; no integra una aceleración física.
`QSimConfigGroup` declara por defecto `trafficDynamics=queue` y
`linkDynamics=FIFO`, omitidos en el XML maestro; estos valores son requisito del
catálogo nuevo. `FIFOVehicleQ` conserva orden. MATSim también ofrece `PassingQ`
(prioridad por salida más temprana) y `SeepageQ`, pero no se activan aquí: no
constituyen evidencia de filtrado lateral de motos entre carrocerías.
`QVehicleImpl.getSizeInEquivalents` usa PCU para la cola; es distinto de longitud
y ancho. La interpolación visual existente sigue marcada como estimada, sin
cambiar timestamps, acelerar la animación o convertirla en aceleración QSim.
El perfil rápido solo permite mayor velocidad donde el enlace y la cola lo
permitan; no se promete que llegue primero.

La exclusión de PT es explícita: los pesos anteriores
40/25/10/10/**10 PT**/5 pasan a 40/25/10/10/5, total **90**:

| Categoría restante | Fracción de N | Porcentaje aproximado |
|---|---|---|
| Carro normal | 40/90 = 4/9 | 44,444444 % |
| Motos, total | 25/90 = 5/18 | 27,777778 % |
| Carro liebre | 10/90 = 1/9 | 11,111111 % |
| Carro tortuga | 10/90 = 1/9 | 11,111111 % |
| Pesados | 5/90 = 1/18 | 5,555556 % |

Primero se adjudican estas cinco cuotas mediante restos mayores exactos;
después, **solo la cuota de motos** se divide por `motorcycle_weights`.
El ejemplo 1:2:1 equivale a 25/50/25 % de las motos, no a una estimación de campo.
Empates usan orden canónico; la semilla baraja las identidades sin cambiar
cuotas. Para N=360: 160 carros normales, 25/50/25 motos, 40 carros liebre,
40 carros tortuga y 20 pesados. `normalized_weights` guarda las fracciones en
el manifiesto; el SHA identifica todos los parámetros. Cambiar pesos o límites
requiere otra versión y otra carpeta, nunca editar los insumos de una corrida.
PT queda fuera de perfiles y de N: requiere un servicio separado con rutas,
paradas, flota y horarios. Su metadata de operador/servicio sigue independiente.

**Bloqueos concretos:** activar pesados sigue rechazado, incluso con N tan
pequeño que su cuota redondee a cero: falta implementar y sustentar su política
de acceso. No se inventan horarios municipales ni dinámica de arranque.
El catálogo completo permite preparar una asignación, no una corrida ejecutable.
Una configuración explícita con peso de pesados cero permite ensayar las motos
en una red apta: el denominador entonces es **85**, no 90, y se registra ese
cambio. Esto no resuelve las restricciones de red pendientes de la
[revisión de conectividad](#conectividad-19-20), ni sustituye un límite aprobado
para los cuatro casos OD. Sus validaciones permanecen vigentes.

Archivos: `simz1_road_catalog.py` y el JSON agregan el contrato; `simz1_agent_types.py`,
`simz1_agent_demand.py`, `simz1_population.py`, `simz1_od_policy.py`,
`generate_montecarlo_z1.py` y `prepare_simz1_agents.py` lo integran sin cambiar
las ramas históricas. `RoadVehicleProfiles.java`, `DrivingProfiles.java` y
`CongestionAwareRerouting.java` aplican y registran parámetros/políticas;
`simz1_motion.py` conserva dimensiones con procedencia. Las pruebas nuevas son
`test_simz1_road_profiles.py`, `test_simz1_road_presentation.cjs` y
`RoadVehicleProfilesCheck.java`; `test_simz1_agent_demand.py` selecciona
explícitamente el catálogo antiguo en su caso de compatibilidad de seis tipos.
El lanzador es `check_simz1_road_profiles.ps1`.

Verificación realizada durante esta entrega: análisis de sintaxis Python/JSON,
`node --check`, parseo de PowerShell y `git diff --check`. No se ejecutaron suites,
compilación Java, generadores de población, MATSim, servidores o navegadores.
La siguiente orden **es para el usuario**. Requiere Python con dependencias del
proyecto, Node, JDK 25 y dependencias Maven ya disponibles (usa `-o`). Crea solo
fixtures pequeños de pruebas; conserva su XML en una carpeta UUID nueva de
`runtime/validation`, sin borrar nada:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& .\check_simz1_road_profiles.ps1
if (-not $?) { throw 'Revisar el primer error; no ejecutar una simulacion' }
```

Resultado esperado, aún pendiente de ejecutar: cuotas exactas, semilla estable,
rechazo de tipos/desacuerdos/velocidades inválidas, ninguna asignación de bus,
XML leído por MATSim con dimensiones y límites correctos, políticas de ruteo
distintas en un grafo pequeño sin saltarse modos/sentidos, demoras conservadas,
selección/contorno/envolvente coherentes y compatibilidad histórica. El caso
de pesados debe **rechazarse**, no imprimirse como simulación aprobada. Los
checks Java construyen objetos en memoria; no crean `Controler` ni ejecutan
QSim. La comprobación nativa de una corrida nueva y la inspección visual del
usuario siguen pendientes.

<a id="transit-evidence"></a>

## SimZ1: catálogo de evidencia de transporte público, revisión 2026-10-22

La revisión está en
[`scenarios/zona1/transit/review-2026-10-22`](../scenarios/zona1/transit/review-2026-10-22).
Contiene **23 entradas candidatas, no 23 servicios operativos confirmados**.
Todas tienen `production_enabled:false`. No se importan automáticamente en
los generadores ni en corridas existentes. Los horarios de atención, intervalos
de apertura y menciones genéricas de frecuencia no se convierten en salidas.

| Archivo | Contenido y alcance |
|---|---|
| `catalog.json` | Operador, línea, variante, sentido, secuencias, coordenadas, recorrido, calendario, horarios, fuentes, fecha, licencia y estado por campo; conflictos y bloqueos explícitos. |
| `sources.json` | 37 referencias con URL, tipo, fecha de consulta/publicación cuando consta, licencia y limitaciones. |
| `municipal-gis.json` | Consulta acotada de las tres capas municipales: 11 geometrías Transmetro, 4 TuBus y 52 registros de estaciones. URL exacta de consulta, CRS y hashes de respuestas. |
| `osm-evidence.json` | 18 relaciones del extracto local, 139 referencias/registros de paradas; 52 con coordenadas y 87 ausentes, conservadas como `null`. IDs, versiones, timestamps y miembros faltantes. |

Los cuatro JSON suman aproximadamente 633 kB. `catalog.artifacts` registra
tamaño y SHA-256 de los dos archivos de evidencia. Los índices de geometría
remiten al `source_id` de la capa y su `FID`; los de OSM, al ID original.
No se deduplican estaciones por nombre ni se ordenan visitas por FID o número
de parada. Las visitas repetidas y los huecos permanecen identificables.

`verified` significa **verificado en la fuente citada y dentro de `scope`**,
no operación vigente certificada. `pending` deja el campo canónico en `null`;
las afirmaciones fechadas permanecen en `evidence_claims`, y sus desacuerdos en
`conflicts`. `scenario_assumption` exige marca sintética y motivo. Los fixtures
de desarrollo usan nombres y fuentes ficticios en
[`test_simz1_transit_catalog.py`](../python/test_simz1_transit_catalog.py),
separados del catálogo real; no agregan buses a N.

### Dominio y geometría

No se encontró un polígono aprobado del dominio. El rectángulo de descarga
`[-90.522,14.625,-90.505,14.646]` se usó **solo para filtrar consultas**.
La relación OSM `9283360`, versión 34, referencia 59 vías exteriores y faltan
43 en el extracto: no permite reconstruir aquí un límite completo ni aprobarlo.
Por ello cada `domain_intersection` queda bloqueada, con `parts:null`.
No se afirma qué porción de cada servicio pertenece al dominio aprobado.

Los resultados municipales son geometrías completas que intersectan ese
rectángulo, sin recortarlas ni asignarles sentido operacional. Las capas
[Transmetro](https://gis2.muniguate.com/datos/dataset/rutas-sistema-transmetro-2025),
[estaciones](https://gis2.muniguate.com/datos/dataset/estaciones-transmetro-2025)
y [TuBus](https://gis2.muniguate.com/datos/dataset/rutas-sistema-tubus-2025)
publican licencia **CC BY 4.0**, atribución Municipalidad de Guatemala/DMU/DIGM.
El portal declara EPSG:32615, mientras el servicio declara 102100/3857;
la consulta pidió explícitamente `outSR=4326`. Se conservan ambas declaraciones,
sin interpretar coordenadas de un sistema como otro. La licencia no equivale
a permiso de circulación. OSM conserva atribución y **ODbL 1.0**, por separado.
No se extiende la licencia GIS a mapas PDF, artículos o Moovit.

### Hallazgos por grupo

| Candidatas | Evidencia disponible; diferencia o pendiente |
|---|---|
| L1 / L2 | GIS y relaciones OSM; artículos municipales y contraste difieren en horarios. L2 también presenta orden distinto de estaciones. |
| L6 | GIS, relaciones y sentidos descritos en artículo municipal; dirección de Centro Zona 6 difiere entre artículo y mapa/GIS. |
| L7 | Extremos Merced–USAC en versión municipal 2019; contraste titula el circuito Colón. No se fusionan versiones automáticamente. |
| L12 y expresos | Horario regular publicado y ventanas expresas separadas. Los FID 4/10/11 tienen geometría idéntica: eso no determina sus patrones de parada. Domingo del expreso sigue en conflicto. |
| L13 y extensión | Memoria 2021, mapa NOV23, FEB24 y contraste conservados como versiones distintas. Hangares, Plaza Argentina y Plaza Berlín no se convierten en un único servicio. La extensión no fue devuelta por el filtro rectangular; su relación con el dominio aprobado sigue desconocida. |
| L18 y expresos | Atlántida–FEGUA documentado; Portales y variantes pendientes. FID 9/12 comparten geometría, sin acreditar mismas paradas. |
| TuBus 104 / 5 / 802 / 105 | Cuatro geometrías municipales. 802 y 105 incluyen fragmentos ordenados de ruteros, sin inventar etiquetas ida/regreso ni coordenadas. Artículo y PDF de 105 discrepan en extremos, horario y estado «en prueba». |
| Transurbano 282 / 285 / 287 | Candidatas del contraste; operador y vigencia pendientes ante información de transición de 2026. Los servicios previstos para enero de 2027 no se tratan como actuales. |
| Extraurbanos / urbanos | Litegua y Fuente del Norte son pistas de agencia/estación, no rutas verificadas. TMB describe un transbordo específico. Otros urbanos siguen sin línea/operador/trazado confirmados. |

`location_checks` distingue la agencia
[Litegua, 15 Calle 10-40](https://sistemas.litegua.com/LiteguaWeb/Home/Agencias),
el [transbordo TMB, 8.ª Avenida 15-16](https://www.tmb.com.gt/ayuda.html)
y la [estación Fuente del Norte, 17 Calle 8-46](https://transportesfuentedelnorte.com/estacion).
TMB acredita abordaje de su coaster con boleto pagado; no acredita un recorrido
Pullman por Zona 1. La disposición municipal que menciona el operador no fue
verificada como norma. Tampoco se confunden El Amate de Transmetro
(18 Calle/4.ª Avenida), la parada TuBus 105 n.º 167 (20 Calle/4.ª Avenida)
y TuBus 802 n.º 121 (19 Calle/4.ª Avenida). No hay prueba suficiente para
atribuir a Litegua un recorrido por 18 Calle ni para completar por proximidad
servicios sobre 4.ª/5.ª u 8.ª/9.ª Avenida.

Pendientes: límite aprobado con procedencia; versión operativa y secuencias
reconciliadas con operador; ubicación de paradas y correspondencia con enlaces
dirigidos; calendario con excepciones, salidas, flota y tiempos exteriores;
licencias de reutilización donde no constan. El mapa municipal de noviembre
de 2024 solo se identificó por enlace/metadatos: falta inspección visual de su
contenido. Los mapas esquemáticos no aportan por sí solos geometría exacta.

### Comprobaciones preparadas, no ejecutadas

Se consultaron fuentes públicas, se extrajo evidencia pequeña en lectura y
se revisó sintaxis Python/JSON y el diff. **No se ejecutaron el validador ni la
suite**. El código actual declara MATSim 15.0, compilación Java 25 y deck.gl
9.1.14; `prepare_simz1.py`, `generate_montecarlo_z1.py` y el servidor continuo
`serve_simz1_continuous.py` permanecen intactos. El replay SQLite sigue usando
`mode=ro` y `query_only`. No se comprobó un cliente en ejecución ni se inició
MATSim, generadores, servidores o navegadores.

Para ejecutar únicamente las comprobaciones de este catálogo:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
python -B -m unittest discover -s python -p 'test_simz1_transit_catalog.py' -v
if ($LASTEXITCODE -ne 0) { throw 'Fallaron las pruebas del catalogo' }
python -B python/simz1_transit_catalog.py
if ($LASTEXITCODE -ne 0) { throw 'Catalogo, citas o artefactos invalidos' }
python -B python/simz1_transit_catalog.py --strict-production
if ($LASTEXITCODE -ne 2) { throw 'Se esperaba bloqueo de produccion con codigo 2' }
```

Resultado esperado, todavía no observado: pruebas satisfactorias; resumen
`structure_and_citations_valid`, 23 entradas, 37 fuentes y dos verificaciones
de integridad; `operational_validation:not_performed` y
`production_status:blocked`. El modo estricto devuelve **2 incluso con datos
de revisión válidos**; no es aprobación para simular. Las pruebas cubren
identidades/citas, campos pendientes, supuestos explícitos, visitas repetidas,
horarios de oficina, bloqueo sin dominio y hashes/rutas de los artefactos.
Solo usan fixtures pequeños; el catálogo y las corridas históricas se leen
sin modificarse.

<a id="fixed-transit-fleet"></a>

## SimZ1: flota pública fija y contadores separados

**Estado:** implementación opt-in y pruebas preparadas; ninguna ejecución nativa
validada en esta entrega. El catálogo de la revisión anterior tiene **cero
servicios habilitados**. El preparador rechaza una configuración de producción
antes de crear archivos si el catálogo, dominio o servicio no están habilitados.
No se cambió ese catálogo ni se incorporaron buses reales a las corridas.

| Concepto | Definición |
|---|---|
| N | Personas de demanda vial Monte Carlo. El rango masivo predeterminado nuevo es 150000..250000 inclusivos; sin `--massive` se conserva el ejemplo de 10. |
| B | IDs únicos de vehículos de transporte público configurados, incluidos los de reserva. No se suman a N. |
| Expediciones | Salidas de rutas dirigidas para la fecha de servicio seleccionada. Varias pueden reutilizar el mismo bus. |
| Conductores internos | Actores creados por MATSim e identificados por `TransitDriverStarts`; no personas nuevas de Monte Carlo. |
| Buses activos en dominio | Observación de eventos nativos sobre enlaces dirigidos del dominio explícito; varía con el tiempo. Sin dominio o ubicación conocida se informa `unknown`. No equivale a B ni al horario previsto. |

Las corridas nuevas añaden `public_transport` y los contadores
`road_demand_persons`, `public_transport_vehicles_configured`,
`public_transport_departures_scheduled` y `transit_drivers_added_to_demand`
al manifiesto. `planned_persons` conserva su significado; «Personas generadas:
N» no incorpora B. Los manifiestos históricos no se reescriben. La flota no
consume el generador aleatorio de demanda ni crea un bus por vuelta; cambiar
B no cambia N. El rango explícito anterior 150000..200000 sigue disponible
para reproducir su sorteo, sin alterar semillas ni planes históricos.

### Configuración y APIs nativas

[`simz1_transit_fleet.py`](../python/simz1_transit_fleet.py) valida el contrato
`simz1-transit-fleet-v1`: versión del escenario, fecha/calendario con excepciones,
operador/servicio, tipos con dimensiones y PCU independientes, IDs de buses,
rutas dirigidas, paradas en enlaces y sentido, offsets, salidas y asignaciones.
No inventa horarios, cantidades o coordenadas. La procedencia de flota,
dimensiones y parámetros es obligatoria; sin pasajeros, la estancia se declara
supuesto de escenario. El ejemplo tiene cuerpo rígido, no bus articulado.
Los tiempos se serializan en segundos numéricos aceptados por `Time.parseTime`
de MATSim 15, conservando la precisión declarada; no se redondean a milisegundos.

El preparador escribe exclusivamente en una carpeta **nueva**: `transitSchedule.xml`,
`transitVehicles.xml`, `roster.json`, `fleet-config.json` y
`transit-fleet-manifest.json` con hashes. Solo el fixture añade su pequeña red
sintética. Una fecha sin ninguna expedición activa no genera una configuración
ejecutable. Cada servicio declara sus `vehicle_ids`, incluidas reservas;
compartir un bus exige asignación explícita y disponibilidad global. B es la
unión de IDs, no la suma de los conteos por servicio. Una línea inactiva conserva
su flota configurada sin generar salidas. Los mismos IDs pueden conservarse entre futuras corridas;
la fecha, versión, N efectivo y asignaciones deben quedar registrados por corrida.

[`SimZ1TransitFleet.java`](../src/main/java/gt/edu/uvg/sim/zona1/SimZ1TransitFleet.java)
usa `TransitSchedule`, `TransitLine`, `TransitRoute`, `Departure.setVehicleId`
y `scenario.getTransitVehicles()` de **MATSim 15.0**. La lectura de su JAR de
fuentes mostró que `ReconstructingUmlaufBuilder`/`UmlaufInterpolator` pueden
añadir recorridos automáticos entre servicios. La implementación opt-in crea
un `Umlauf` por bus utilizado, compuesto solo por las expediciones declaradas.
No aplica el ruteo genérico de carros ni sus observaciones de congestión a la
flota. Una desviación necesitaría otra política explícita y versionada.

Se rechazan rutas desconectadas, enlaces sin acceso bus, movimientos de carril
incompatibles, IDs duplicados, flota insuficiente y solapamientos de asignación.
Para reutilizar un bus, el siguiente inicio debe respetar el fin de la
expedición anterior más terminal y retorno configurados. Los enlaces de
terminal deben ser compatibles: no se fuerza un circuito a una línea de
ida/vuelta ni se añade una conexión corta automáticamente.

La validación programada no garantiza puntualidad. El guard nativo observa
fin real y partida: ante incumplimiento del mínimo de terminal/retorno, la
política `reject_on_actual_violation` **falla antes del siguiente movimiento**.
No reescribe timestamps ni inventa un vehículo sustituto. Sin pasajeros, un
handler de parada impone la estancia mínima asumida, además de la espera
programada; no la atribuye a abordajes medidos.

El guard se ejecuta mediante hooks síncronos del motor/conductor nativo, antes
de publicar la partida. Un listener de eventos paralelos no garantiza impedir
el movimiento a tiempo. Se conserva el gestor concurrente de eventos existente.
Para producción, Java vuelve a leer el snapshot `enabled-catalog.json`, acotado
y con SHA-256, exige dominio/enlaces coincidentes y servicios habilitados,
verificados y sin bloqueos. No basta escribir `productionEnabled=true` en XML.

### Carriles, paradas y exterior

`runningWay=mixed|segregated` es explícito. La segregación requiere enlaces
dedicados con acceso bus y sin acceso carro; una etiqueta no convierte una vía
mixta en segregada. `isBlocking=false` usa la cola nativa de parada como bahía;
no crea una bahía geométrica ni un carril nuevo. `isBlocking=true` retiene el
bus en la cola asociada: con `QLinkImpl`, un enlace de varios carriles puede
tener una sola cola agregada. Se rechaza ese caso para una parada en carril
sin una representación selectiva validada; no se afirma que bloquee solo un
carril físico. Los tiempos semafóricos y la red existente permanecen intactos.

En QSim 15, la coordenada de la parada no fija por sí sola una posición
longitudinal física: la atención se produce en el extremo de la cola/enlace.
Una parada real interior puede necesitar segmentar la red en una versión nueva
con evidencia; no se trasladan silenciosamente sus coordenadas GIS al extremo
de un enlace. Tampoco existe `laneRefId` en `TransitStopFacility` para imponer
una parada selectiva en un carril concreto.

**Retorno exterior pendiente:** el ledger permite conservar vehículo,
expediciones, duración y procedencia verificable o sintética explícita; valida
identidad y tiempo disponible. Pero el preparador y el preflight nativo bloquean
su ejecución con `blocked_exterior_runtime_not_implemented`. También bloquean
rutas fuera del dominio declarado. Falta implementar y validar la ausencia y
reentrada por portales sin conexiones automáticas. No se teletransporta un bus
ni se simula toda Guatemala. El supuesto sintético por sí solo no elimina ese
bloqueo. Los servicios reales siguen además pendientes del catálogo y dominio.

Los diagnósticos nativos emiten `simz1TransitCounters` y
`SIMZ1_TRANSIT_COUNTERS`. Separan flota, partidas observadas, conductores y
actividad; conservan evidencia de duplicados y ubicación desconocida. La tabla
compacta de viajes viales excluye únicamente conductores identificados por
evento nativo y flota registrada, con contadores propios. Los actores viales
desconocidos siguen siendo errores; los eventos originales no se alteran.
Los snapshots identifican su base de eventos procesados y la sincronización
configurada. Con sincronización deshabilitada o durante cleanup, el conteo
puede ir detrás del reloj nativo; se etiqueta esa condición y no se afirma
que el observador haya vaciado la cola de eventos.

### Pruebas para ejecutar por el usuario

Fixture independiente:
[`simz1-transit-fleet-synthetic.json`](../python/fixtures/simz1-transit-fleet-synthetic.json).
Declara N=3, B=2 y cuatro expediciones de ida/vuelta. Su red pequeña y sus tiempos
son sintéticos, no cartografía de Zona 1 ni servicios del catálogo real. El
script conserva la flota preparada y la salida opcional de QSim en una carpeta
UUID bajo `runtime/validation`; las pruebas unitarias usan también sus carpetas
temporales y `target`. No sobrescribe ni borra resultados históricos.

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
# Pruebas pequeñas, preparación y lectura de XML nativo; NO ejecuta QSim.
& .\check_simz1_transit_fleet.ps1
if (-not $?) { throw 'Revisar el primer fallo de flota; no escalar' }
```

Solo cuando el usuario decida ejecutar la simulación sintética pequeña:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
# Ejecuta QSim exclusivamente para el fixture N=3/B=2, en otra carpeta nueva.
& .\check_simz1_transit_fleet.ps1 -RunSyntheticSimulation
if (-not $?) { throw 'Revisar eventos y diagnosticos conservados; no escalar' }
```

Ambos comandos requieren Python, JDK 25 y dependencias Maven locales (`-o`).
Resultado esperado, **no observado aún**: N=3 constante, dos buses reutilizados
en cuatro expediciones, ninguna quinta salida ni bus creado por vuelta,
conteos internos separados, estancias y disponibilidad respetadas. Las pruebas
preparadas incluyen calendarios/fin de servicio, reservas, cambios de B,
conflictos entre servicios, retorno exterior, flota insuficiente, acceso y
sentido, paradas y actores desconocidos. Un retorno exterior debe ser rechazado,
no presentado como prueba de circulación resuelta.
Con `-RunSyntheticSimulation`, el harness comprueba después del retorno normal
de QSim cuatro partidas, dos conductores, cero buses activos/abortos/anomalías,
los mismos IDs y tres viajes viales completados. Solo tras esas comprobaciones
escribe `synthetic-fleet-result.json`; ese resultado aún no se ha generado.

Durante esta entrega solo se inspeccionaron código/fuentes locales y sintaxis.
Se analizaron con `ast.parse` los once archivos Python cambiados, el JSON
del fixture y la sintaxis de PowerShell; `git diff --check` no detectó errores.
No se ejecutaron pruebas funcionales, compilación, preparador, población,
MATSim, servidor, navegador ni exportaciones. Se revisaron los generadores
actuales y el servidor continuo: deck.gl sigue en 9.1.14, SQLite directo conserva
`mode=ro`/`query_only` y no se modificaron las correcciones de concurrencia o
cronología. La compilación, ejecución del fixture y validación de circulación
real quedan pendientes; no se acredita capacidad masiva.

### Archivos de esta entrega

| Componente | Archivos nuevos o modificados |
|---|---|
| Contrato y preparación | `python/simz1_transit_fleet.py`, `python/simz1_transit_accounting.py`, `python/fixtures/simz1-transit-fleet-synthetic.json` |
| Integración y contadores | `python/simz1_run.py`, `python/simz1_transit_events.py`, `python/simz1_event_validation.py`; en `src/main/java/gt/edu/uvg/sim/zona1/`: `SimZ1TransitFleet.java`, `SimZ1TransitDiagnostics.java`, `SimZ1.java`, `TripTableExporter.java`, `CongestionAwareRerouting.java` |
| Rango de demanda futuro | `python/simz1_population.py`, `python/generate_montecarlo_z1.py` |
| Pruebas preparadas | `check_simz1_transit_fleet.ps1`; en `python/`: `test_simz1_transit_fleet.py`, `test_simz1_transit_accounting.py`, `test_simz1_transit_events.py`, `test_simz1_massive_demand.py`; en `src/test/java/gt/edu/uvg/sim/zona1/`: `SimZ1TransitFleetCheck.java`, `SimZ1TransitDiagnosticsCheck.java`, `SimZ1TransitFixture.java` |
| Documentación | `README.md`, `docs/README.md` |
<a id="stop-signs"></a>
## Paradas verdes y azules del visor continuo

La señalización es una anotación del catálogo, independiente de la circulación
de buses y del reloj del replay. No modifica N, B, rutas, paradas nativas,
señales, redes, ventanas o corridas históricas. TuBus se clasifica por servicio,
nunca por el nombre de su operador. Transmetro usa verde; TuBus, Transurbano,
urbanos y extraurbanos verificados usan azul. Un andén compartido puede tener
ambos colores, conservando servicios y líneas separados en la información.

**Diagnóstico del 2026-10-22:** ya existían catálogos, cargador, atlas y las tres
capas WebGL, integradas en `visualizador_z1_continuous.html`. La ausencia tenía
dos causas: `load_stop_display()` devolvía cero registros por faltar el mapeo
parada–enlace–sentido y el dominio de transporte aprobado; `setZoom()` ocultaba
todas las paradas bajo zoom 15.5. No faltaba implementar el pictograma, ni era
una capa con `visible: false`. No se inspeccionó un navegador ni un servidor
en ejecución: la versión cargada en una pestaña anterior no está comprobada.

El catálogo contiene 52 registros municipales, no 52 plataformas distintas.
Se añadió `scenarios/zona1/transit/review-2026-10-22/catalog-display.json` como
contrato separado de anotaciones. Acepta **10 plataformas**: nueve verdes de
L1 (San Sebastián, Parque Centenario, Correos, San Agustín, Gómez Carrillo,
Mercado Central, Paseo de las Letras, Centro Cívico y Sur 2) y una azul de
TuBus 5, Parque Colón. San Sebastián incluye L1/L2 y un solo marcador de
transbordo, con ambos servicios y sus sentidos en el tooltip.

La configuración efectiva, verificada por SHA-256, de la corrida
`simz1-0dd152dabbc24d1d84d9b738c449cc35` (227187 personas) declara
`transit.useTransit=false`. Estas anotaciones no significan buses circulando
ni paradas utilizadas por esa corrida. El cargador no lee eventos, SQLite,
vehículos o demanda para producirlas. Si no puede verificar la configuración,
informa uso desconocido; `useTransit=true` tampoco acredita uso de una parada.

### Fuentes, fechas y pendientes

Revisión consultada el **2026-10-22**. Las publicaciones municipales confirman
identidades y lugares en sus fechas; no ofrecen un intervalo que certifique
vigencia operativa para cualquier fecha del replay:

| Evidencia | Fecha publicada | Uso en la anotación |
|---|---|---|
| [Estaciones Transmetro 2025](https://gis2.muniguate.com/datos/dataset/estaciones-transmetro-2025) | 2025-12-17; modificación 2025-12-18 | Corroboración espacial municipal, no asignación de carril |
| [L1 municipal](https://muniguatealfrente.com/linea1yfestivalcentrohistorico/) | 2025-10-01 | Estaciones y transbordo San Sebastián |
| [L2 municipal](https://muniguatealfrente.com/linea2transmetro/) | 2025-11-07 | San Sebastián comparte L1/L2; no se deduce sentido por orden del artículo |
| [TuBus municipal](https://muniguatealfrente.com/tubus-transporte-municipal-que-conecta-distintas-zonas/) | 2025-09-05 | Parque Colón es extremo de la ruta 5; no acredita una coordenada oficial |
| [L6 municipal](https://muniguatealfrente.com/linea6transmetro/) / [L12 municipal](https://muniguatealfrente.com/linea-12-del-transmetro/) | 2025-10-24 / 2025-09-05 | Candidatos documentados; no certifican plataformas dirigidas en la red MATSim |
| [L7 municipal](https://www.muniguate.com/blog/2019/10/01/inauguracion-de-la-linea-7-del-transmetro/) | 2019-10-01 | Versión inaugural; no se adopta como operación actual |
| [L13 municipal](https://www.muniguate.com/movilidadurbana/linea-13/) / [L18 municipal](https://www.muniguate.com/movilidadurbana/linea-18/) | Sin fecha explícita | Páginas de rutas; vigencia y revisión espacial pendientes |
| `osm-evidence.json`, snapshot local | Descarga desconocida; timestamps individuales conservados | Puntos exactos de plataformas y sentidos de relaciones OSM, sin reconstruir recorridos faltantes |

Las asociaciones son explícitas por plataforma/servicio y conservan versiones
y fechas. Transmetro exige además coincidencia nominal revisada con un punto
municipal cuya separación no exceda 25 m: ese límite rechaza discrepancias,
no crea correspondencias por proximidad ni mueve puntos. La posición dibujada
es exactamente la del nodo OSM; no es cartografía levantada ni GIS verificada.
Parque Colón usa el nodo `4735676221`, asociado a las relaciones `18672965` y
`18672966`; el catálogo distingue la denominación municipal `5` de OSM `R5`.
Attribution: Municipalidad de Guatemala, DMU/DIGM (CC BY 4.0), y colaboradores
de OpenStreetMap (ODbL 1.0), según las licencias conservadas en `sources.json`.

**Pendientes:** Beatas de Belén tiene unos 62 m de diferencia GIS/OSM y
direcciones postales discordantes; se excluye. El resto de L2 y TuBus 5 tiene
nodos de parada ausentes en el extracto. L6, L7, L12, L13, L18 y sus variantes
siguen como candidatos, pendientes de reconciliar plataforma, sentido y versión
operativa; no se activa una línea completa por tener una geometría GIS.
TuBus 104/802/105 requiere sus propias plataformas revisadas; el artículo de
105 presenta una contradicción entre encabezado y descripción. Transurbano,
urbanos y extraurbanos requieren evidencia espacial y de servicio suficiente:
una agencia comercial o dirección postal no constituye por sí sola una parada.
`catalog-display.json.pending` conserva motivos, candidatos y fuentes; no añade
coordenadas a los faltantes. Ningún servicio se habilitó para producción.

### Representación

Se reutiliza un atlas SVG de pictogramas rectangulares de bus, distinto de las
luces semafóricas. Tres capas compartidas representan signos, flechas de acceso
y nombres, siempre antes de los cuerpos vehiculares. `IconLayer` de la versión
fijada **deck.gl 9.1.14** admite atlas, anclajes y tamaños en píxeles mediante
instancias; se revisó su [fuente oficial de esa versión](https://github.com/visgl/deck.gl/blob/v9.1.14/modules/layers/src/icon-layer/icon-layer.ts).
El atlas compartido tiene 27 variantes en 864×216 píxeles; no se crea una capa
por parada. El pictograma rectangular contiene un autobús, nunca letras sueltas.

La cruz al final del trazo conserva la coordenada exacta de la fuente. Solo
pares enfrentados documentados y recíprocos reciben rótulos a izquierda/derecha
en pantalla, unidos a esa cruz: desplazar el rótulo no cambia el andén, el
enlace o sus coordenadas. Las flechas de sentido se construyen en coordenadas
del mundo desde un segmento dirigido revisado. Los signos y nombres miran a
la cámara para ser legibles; no representan la cabeza física de un semáforo.
Al alejarse se agrupan anotaciones en celdas de 64 píxeles del mundo Mercator,
según zoom entero. Cada grupo se ancla a una plataforma real de sus miembros,
nunca a un centroide; su tooltip dice «Agrupación visual», enumera miembros y
no afirma que exista una nueva parada o transbordo. Las placas apiladas indican
grupo; la doble flecha requiere evidencia de transbordo. Los transbordos se
conservan individualmente a cualquier zoom. Al acercarse reaparecen todas las
plataformas originales, incluidos andenes opuestos.

| Elemento | Aparece al acercar | Desaparece al alejar |
|---|---:|---:|
| Transbordos documentados | Siempre | No se ocultan por zoom |
| Plataformas individuales | zoom ≥16 | zoom <15.7: agrupación visual |
| Nombres | zoom ≥18 | zoom <17.7 |

Estos umbrales con histéresis evitan alternancia al oscilar alrededor del
límite. Tamaño del atlas por instancia: 46 píxeles, 50 para transbordos y 44
para grupos, con tope 50 (incluye margen transparente y trazo de anclaje).
La anchura física de cuerpos y colas no depende de estas ayudas. Los
vehículos se dibujan encima y conservan su selección; señalar una parada muestra
nombre, operador, servicio, línea, sentidos, fuente, fecha y uso en la corrida.
Una anotación sin mapeo indica «enlace/carril MATSim sin asociar» y no dibuja
flechas de acceso: extremos de una relación OSM no son una orientación de carril.
Hacer clic en ella
no sustituye la tarjeta de seis campos ni consulta `/api/journey`. El HUD sigue
mostrando «Personas generadas: N»; la explicación queda en la ayuda desplegable.

### Contrato de datos y bloqueos

`simz1_transit_stops.py` lee el catálogo del Prompt 9 al construir el servidor
continuo y añade el resultado solo a su configuración en memoria. No modifica
el `config.json` histórico. `catalog-display.json` exige hashes del catálogo y
registro de fuentes, fecha, plataforma existente, confirmación municipal del
servicio/parada y pertenencia a relaciones con sentido explícito. El cargador
verifica los hashes de los artefactos originales. No cambia `catalog.json`,
`sources.json`, los snapshots GIS/OSM ni el dominio aprobado. El cliente filtra
por el polígono del replay, si existe, pero no inventa un `Link_ID`.

La lectura completa de la red efectiva solo se
realiza si existe una correspondencia revisada y un dominio aprobado. Incluye
enlaces exclusivos de bus, aunque el renderizador de cuerpos viales los omita.

El archivo opcional `stop-display.json`, junto a `catalog.json`, usa
`schema_version: simz1-stop-display-v1`, `synthetic: false`, fecha de revisión,
SHA-256 del catálogo, `source_registry_sha256` de `sources.json` y SHA-256 de la
red efectiva. No se creó ese archivo con
datos inventados. Para futuros datos revisados, cada registro `stops` necesita:

- `stop_id`, nombre y servicios identificados por `service_id`; línea verificada
  en el catálogo, relación de parada/sentido con `status: verified` y fuentes
  registradas. Los sistemas conocidos se derivan de su ID de servicio; para
  urbanos/extraurbanos se requiere `service_system` explícito, nunca operador.
- `coordinate_evidence`: artefacto, fuente y `feature_id` municipal o `stop_id`
  OSM. Debe estar vinculado al servicio en el catálogo. Se conservan las
  coordenadas publicadas; no se obtienen centroides ni se hace geocodificación.
  Los artefactos se verifican contra sus hashes y se conserva la licencia.
- `access`: `link_id`, `from_node`, `to_node`, sentido, `path_segment_index`,
  fuentes, estado verificado y ubicación revisada (`roadside_platform`,
  `median_platform` o `terminal_bay`). Los extremos deben coincidir con la red
  de esa corrida; una red distinta invalida la correspondencia completa.
- Opcionalmente `transfer` con ID, nombre y evidencia; `opposed_stop_ids` y
  `opposed_evidence` para paradas enfrentadas. No se fusionan coordenadas
  distintas aunque los nombres coincidan.

El dominio debe aportar `approved: true`, Polygon válido en `EPSG:4326` y
`link_ids` dirigidos explícitos. Se excluyen puntos exteriores y enlaces fuera
del dominio; un replay con otro límite validado vuelve a filtrar la anotación.
Errores y ausencias permanecen en `getStopDiagnostics()`. Esto no habilita
servicios de producción ni afirma operación durante una corrida histórica.

### Comandos y comprobación manual

Ejecutadas satisfactoriamente las pruebas de paradas Python/Node, bootstrap
completo en memoria, identidad del cliente, tarjeta vehicular y geometría de
semáforos. Las pruebas de paradas incluyen el catálogo real y rechazos por
fuente/coordenada/sentido/hash ausentes, transferencias sin duplicación, colores
con operador compartido, agrupación de 600 instancias y reutilización de datos.
El bootstrap cubre cámaras inclinadas y rotaciones, y un replay sin transporte
público configurado sin agregar vehículos. No se inició MATSim, servidor,
navegador, población o exportación. No se midió FPS/GPU ni se observó WebGL real.

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
python -B -m unittest discover -s python -p test_simz1_transit_stops.py -v
node .\python\test_simz1_transit_stops.cjs
node .\python\test_simz1_continuous_bootstrap.cjs
```

Estos comandos usan Python y Node, fixtures pequeños, DOM/Deck simulado en
memoria y lectura de los catálogos locales. No abren sockets ni ventanas. El fixture separado
`python/fixtures/simz1-stop-signs-synthetic.json` contiene dos andenes opuestos
y un intercambio ficticio; nunca se carga como catálogo del servidor.

Para comprobar únicamente por HTTP qué cliente ofrece el **servidor ya iniciado
por el usuario**, además de las mismas pruebas:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& .\check_simz1_transit_stops.ps1 -InspectRunningViewer
if (-not $?) { throw 'Revisar identidad, version servida y diagnosticos; no reexportar' }
```

Se imprimen run_id, iteración, hash del manifiesto, fuente de replay y hash del
cliente actual. El servidor construye HTML/configuración al iniciarse: si aún
sirve fuentes anteriores, el usuario debe reiniciar ese mismo servidor; una
exportación masiva no es necesaria. La respuesta HTTP no demuestra la versión
ya cargada en una pestaña. En la consola de tu visor, tras recargar:

```javascript
copy(JSON.stringify({
  client: window.simz1ClientBuild,
  stops: window.simz1Continuous?.getStopDiagnostics?.() || {status: 'cliente_anterior'}
}, null, 2));
```

Resultado esperado: `version=simz1-stop-signs-v2`, `accepted=10` y
`simulation_usage.status=not_configured` en la corrida de 227187. El número
`visible` puede ser menor por agrupación; `represented` debe conservar 10.
Los motivos `approved_domain_missing` / `reviewed_stop_access_mapping_missing`
quedan bajo `native_mapping_issues`; no bloquean referencias del catálogo.

Revisión visual **preparada, pendiente de ejecución por el usuario**: zoom
14/16.5/22, inclinación 0/30/60 y rotación 0/90/180/270. Verificar bus verde en
Correos, azul en Parque Colón, un único San Sebastián L1/L2 y su tooltip con
operador/sentidos. Comprobar agrupaciones, anclajes, tamaño acotado y separación
de las luces semafóricas; pausar, hacer seek y reproducir no cambia las paradas
ni inventa buses. La comprobación sintética de 600 instancias mantiene tres
capas y no reconstruye buffers al girar la cámara; queda pendiente medir GPU.
No se afirma haber observado esta interfaz en `127.0.0.1:8793` ni se atribuye
una corrida a las capturas anteriores.

Para cargar el código y catálogo actuales, reiniciar manualmente el mismo
servidor SQLite directo y recargar la pestaña; **no regenerar datos**:

```powershell
& .\.venv\Scripts\python.exe -B .\python\serve_simz1_continuous.py --directory .\runtime\simz1-227187-direct\webgl-continuo --port 8793
```

Comando preparado, no ejecutado en esta revisión. Archivos de esta corrección:
`python/simz1_transit_stops.py`, `python/simz1_transit_stops.js`,
`python/visualizador_z1_controls.js`, `python/test_simz1_transit_stops.py`,
`python/test_simz1_transit_stops.cjs`, `python/test_simz1_continuous_bootstrap.cjs`,
el nuevo `catalog-display.json`, `README.md` y `docs/README.md`.

<a id="replay-integration"></a>
## Integración de eventos, replay y medición

Revisión del código para Prompt 12: MATSim **15.0**, Java release **25** en
`pom.xml`; deck.gl **9.1.14** fijado en el HTML continuo. El flujo conserva
`prepare_simz1.py`/generadores de demanda → configuración y flota versionadas →
`SimZ1`/`SimZ1TransitFleet` → eventos nativos → `simz1_trajectories.extract` →
`SqliteTrajectorySink`/`export_sqlite_selected` → `ContinuousReplay` → API →
loader/worker → WebGL. No se ejecutó ninguna de esas etapas de simulación o
exportación durante esta entrega. La lectura acotada de `127.0.0.1:8793`
devolvió conexión rechazada el 2026-10-22: corrida, iteración y cliente de las
capturas siguen **sin identificar**. No se abrió navegador ni servidor.

| Causa confirmada en código | Corrección y evidencia preparada |
|---|---|
| Los viajes requerían persona/OD privado; los vehículos públicos no estaban en `MotionContext`. | Carga de schedule/fleet con hashes del manifiesto y contrato `simz1-transit-replay-v1`; fixture de un bus reutilizado en dos expediciones. |
| La geometría visual filtraba exclusivamente modo `car`. | `bus` se incorpora solo con flota habilitada; las conexiones requieren modo común y topología dirigida. Fixture de acceso exclusivo sin conexión artificial a `car`. |
| Las paradas no delimitaban intervalos del replay. | Pares nativos `VehicleArrivesAtFacility`/`VehicleDepartsAtFacility`; posición en salida de cola según MATSim 15. Con carriles internos se exige pertenencia nativa y extremo de carril verificado, nunca asumir el extremo del enlace. |
| La consulta HTTP podía verificar sin validar el cierre local de exportación. | `ContinuousReplay` valida primero estado completo, config/fuente e identidad; probes vacíos/no finitos rechazados. Fixture de export incompleto aun con HTTP disponible. |
| La sonda temporal de ACL precedía el presupuesto de espacio. | Ruta, volumen, límite de archivo y espacio comprobados antes de crear incluso esa sonda. |
| El viaje completo anterior seguía retenido tras limpiar/cambiar selección. | Liberación explícita; contadores y tiempos de solicitudes, cancelaciones, respuestas tardías y reutilización. |

La persona vial conserva sus IDs. Para una expedición pública, `Agent_ID` y
`Trip.Person_ID` son `null`; `Driver_ID` identifica al conductor interno y
`vehicle` conserva el ID fijo del bus. `Trip_ID` deriva de vehículo, línea,
ruta y salida; run/iteración/hash siguen en el contrato exterior del replay.
`Trip.Transit` conserva operador, servicio, ruta dirigida, intervalos de parada
y terminal y hashes de schedule/fleet. PCU, dimensiones y velocidad máxima
proceden de campos independientes del XML verificado; las dimensiones asumidas
siguen marcadas como tales. No cambia el formato SQLite ni se migra una base
existente: solo futuras extracciones incorporan estos metadatos opcionales.

Las actividades conservan además colocación `bay`/`in_lane`, bloqueo nativo y
base de estancia. La posición longitudinal de QSim no aporta una trayectoria
lateral medida hacia una bahía; esa precisión continúa desconocida y no se
añaden desvíos geométricos para ocultar posibles conflictos de representación.

Una llegada del conductor cierra su expedición, después de salir del tráfico;
una parada intermedia nunca la cierra. Solo completar todas las expediciones
configuradas del bus permite marcar `service_end_confirmed`. Aborto/censura
no activan avisos. Entre servicios se conserva evidencia de terminal sin crear
un cuerpo activo, movimiento ni tiempo exterior. Las anotaciones de llegada
siguen fuera de colas y conteos físicos. El HUD mantiene **Personas generadas: N**
y seis campos; `/api/hud.public_transport` y `getTransitDiagnostics()` exponen
B, expediciones y conductores separadamente. El contador visual público mide
intervalos activos cargados, no un nuevo contador nativo QSim.

`transit_stop_position_unknown` detiene una futura exportación cuando la
posición de la parada no tiene respaldo: conserva la evidencia incompleta y
no publica éxito. Los servicios reales deshabilitados y los retornos exteriores
sin soporte conservan sus bloqueos. No se altera física, FIFO, eventos,
concurrencia, cachés del servidor ni los resultados de 100000/229629/227187.

Pruebas **preparadas, no ejecutadas**: eventos sintéticos → SQLite minúsculo →
`/api/journey`, identidad entre expediciones/ventanas, parada/terminal/aborto,
posición con carriles, dimensiones efectivas, accesos por modo, N independiente,
tarjeta, selección y liberación del loader. Ejecutado únicamente: lectura de
código/fuentes Java del JAR 15.0, comprobaciones de sintaxis Python/JS/PowerShell
y `git diff --check`. No constituye aprobación funcional ni medición de FPS.

Desde PowerShell, en la raíz del repositorio:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
.\check_simz1_replay_integration.ps1 -CpuBenchmark -CopyBrowserBenchmark
```

El comando comprueba rutas/espacio, ejecuta fixtures pequeños y escribe un
informe CPU nuevo bajo `runtime/replay-benchmark-<UUID>`. No reemplaza archivos.
Compara N=100/1000 personas, curvas/colas densas y flota sintética B=0 frente a
B=N/5 (100/120 y 1000/1200 cuerpos respectivamente), manteniendo N invariable,
con seguridad y cantidad de cuerpos conservadas; los muestreos CPU usan los
mismos tiempos absolutos a ambos factores. No mide FPS WebGL. La mezcla es
exclusivamente un fixture de rendimiento, no una proporción observada ni N real.

Si 8793 continúa cerrado, este comando opcional inicia, **solo al ejecutarlo tú**,
el servidor actual sobre un visor continuo existente. Exige su ruta real y no
regenera HTML, fuentes ni SQLite. Mantener esta consola abierta; ejecutar el
benchmark desde la pestaña correspondiente en otra consola del navegador.

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$simz1Replay = (Resolve-Path -LiteralPath (Read-Host 'Ruta del visor continuo existente de SimZ1')).Path
if (-not (Test-Path -LiteralPath (Join-Path $simz1Replay 'continuous-manifest.json') -PathType Leaf)) {
    throw 'La ruta no contiene un manifiesto continuo existente'
}
$simz1Python = Join-Path $PWD '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $simz1Python -PathType Leaf)) { $simz1Python = 'python' }
& $simz1Python -B python/serve_simz1_continuous.py --directory $simz1Replay --port 8793
```

Para medir playback real 1x/120x, pegar el portapapeles en la consola del visor
**ya abierto con fuentes actuales**. El script comprueba el hash del cliente,
registra run/iteración/manifiesto/fuente, carga/activación, frames CPU/RAF,
`queueProfile` (colisiones, anclas, colocación), memoria cuando el navegador la
expone, selección y costos de geometría/capas de señales/paradas. Los tiempos
07:48/12:00/18:00 son candidatos: el informe registra su densidad, no la supone.
Pausa, seek inverso, buffering observado y 24:00 quedan separados. No fuerza
fallas de red ni desactiva cachés; si no ocurre buffering, no declara medido ese
caso. Se limpia la selección y se restaura reloj/velocidad/pausa; no se cierra
la pestaña del usuario. El cierre de recursos propios del loader se prueba en
el fixture CPU, no se presenta como medición de cierre completo del navegador.

```javascript
copy(JSON.stringify(window.simz1IntegrationBenchmark, null, 2));
// Diagnóstico sobre un bus seleccionado, sin consultar cada frame:
copy(JSON.stringify({client: window.simz1ClientBuild,
  transit: simz1Continuous.getTransitDiagnostics(),
  trace: simz1Continuous.traceSelectedVehicle()}, null, 2));
```

Sin buses/paradas habilitados, su costo real incremental queda pendiente;
las cifras CPU de fixtures no lo sustituyen. Los tiempos de callbacks Deck
miden CPU y no GPU. Comparar informes exige mismo cliente, run, iteración,
ventanas, cámara, hardware y condición de caché, identificados por el informe.

Archivos nuevos: `simz1_transit_replay.py`, `test_simz1_replay_integration.py`,
`test_simz1_transit_replay.cjs` (en `python`),
`check_simz1_replay_integration.ps1` y ambos `scripts/validation/benchmark_simz1_*`
de integración/pestaña. Cambios: `simz1_motion.py`, `simz1_trajectories.py`,
`simz1_continuous_replay.py`, `simz1_continuous_loader.js`,
`simz1_visual_lanes.py/.js`, `simz1_spatial_view.js`, `simz1_arrival_effects.js`,
`simz1_recovery_io.py`, `verify_simz1_continuous_data.py`,
`simz1_render_fixtures.cjs`, HTML/controles continuos y estos dos README.

<a id="contrato-consolidado"></a>
## Contrato consolidado y operación manual — 22/10/2026

Esta revisión modifica únicamente los dos README. Se leyeron `AGENTS.md`, el
estado Git inicialmente limpio, `pom.xml`, entradas Java, parsers Python,
scripts PowerShell y fixtures. Versiones declaradas efectivas: MATSim **15.0**,
Java **25**, deck.gl **9.1.14**. Generadores: `prepare_simz1.py`,
`generate_montecarlo_z1.py`, `prepare_simz1_agents.py`; servidor:
`serve_simz1_continuous.py`. No se compilaron fuentes ni se ejecutaron regresiones,
generadores, MATSim, exportaciones, servidores o navegadores en esta revisión.
Los comandos siguientes son para ejecución manual, conservan fallos y salidas,
y no contienen borrados, commits, 50 iteraciones ni unidades supuestas.

**Estado que impide declarar completo el flujo público:** el CLI
`ejecutar_simz1.py` invoca `RunZona1Simulation`, cuya función `main` no llama
`SimZ1TransitFleet.validate/install` ni instala sus diagnósticos. `SimZ1.main`
sí lo hace, pero el CLI no ofrece un selector de esa clase ni `--transit-fleet`
o `--buses`. El harness `SimZ1TransitFixture` acepta exclusivamente N=3/B=2,
cuatro enlaces inventados y cuatro expediciones; no admite añadir los tres
perfiles de moto. Tampoco produce el `run-manifest.json` requerido por el
exportador productivo. No suplirlo creando un manifiesto artificial.
La prueba conjunta de todos los perfiles habilitados y un servicio público
requiere integrar ese punto de entrada y ampliar el harness en otro cambio
de código. Las pruebas separadas de abajo **no satisfacen ese criterio conjunto**.

Comprobaciones ejecutadas de esta documentación: parser PowerShell sobre sus
12 bloques nuevos, AST de seis fragmentos Python, sintaxis del fragmento JS
sin ejecutarlo, cotejo estático de 11 invocaciones Python con sus opciones CLI,
existencia de los tests nombrados, enlaces internos y `git diff --check`.
La lectura JSON confirmó 23 candidatas/0 habilitadas y 37 fuentes. Ninguna de
estas comprobaciones acredita resultados funcionales o compilación Java.

### Catálogo e interpretación

La tabla de [dimensiones y alias](#catalogo-visual-vehiculos) es el contrato de
presentación; la de [motos futuras](#motos-futuras) describe parámetros de una
nueva versión, no una reclasificación histórica. Resumen vigente:

| Tipo / perfil | Etiqueta exacta | Cuerpo asumido L × W | Parámetro futuro, no calibrado |
|---|---|---|---|
| Normal / normal | Carro | 4,5 × 1,8 m | PCU 1; 50 km/h |
| Liebre / liebre | Carro liebre | 4,5 × 1,8 m | PCU 1; 90 km/h |
| Tortuga / tortuga | Carro Tortuga | 4,5 × 1,8 m | PCU 1; 25 km/h; histórico maestro 20 |
| MotocicletaLenta / tortuga | Moto tortuga | 2,1 × 0,8 m | PCU 0,25; 30 km/h |
| Motociclista / normal | Moto | 2,1 × 0,8 m | PCU 0,25; 50 km/h |
| MotocicletaRapida / liebre | Moto Liebre | 2,1 × 0,8 m | PCU 0,25; 70 km/h |
| TransportePesado / normal | Transporte pesado | 10 × 2,5 m | PCU 3,5; 50 km/h; acceso bloqueado |
| Bus con servicio explícito | Transporte público | 12 × 2,5 m de referencia | XML efectivo por servicio; operador separado |
| Tipo desconocido | Etiqueta cruda | 4,5 × 1,8 m de referencia | Familia desconocida; no inferir de PCU/ID |

Dimensiones registradas válidas prevalecen sobre esos supuestos. Un XML
configurado no acredita dimensiones medidas. Cuerpo y contorno usan el mismo
eje rígido; un articulado conserva una envolvente rígida declarada como
articulación desconocida, no una cinta ni un modelo articulado validado.
El margen longitudinal visual es configurable (`gap_m=2` m por defecto),
el lateral es 0,1 m por lado. Se exige
`s_delantero - s_trasero >= (L_delantero + L_trasero)/2 + gap` y se comprueban
polígonos orientados con búsqueda espacial acotada. No inventar espacio ni
ocultar cuerpos cuando no caben. Picking: 8 px CSS mouse / 18 touch; no altera
cuerpo, cola, PCU o capacidad. El zoom tampoco modifica el espacio métrico.

El catálogo vial retira explícitamente PT 10/100: pesos 40/25/10/10/5 sobre
**90**, con motos 1:2:1 dentro de su cuota; son ejemplos sintéticos reproducibles.
Políticas `fastest-time`/`shortest-distance` configurables, velocidad acotada
por vehículo/enlace, semáforos y FIFO. PCU reducido no implementa filtrado;
QSim de colas no integra aceleración continua. Ni pesados ni ventanas horarias
constituyen reglas municipales verificadas. Una corrida sin motos/buses no los
adquiere por cambiar etiquetas. Se preservan IDs, tarjeta de seis campos y
**Personas generadas: N**.

### Red, servicio y representación

La [revisión focal por enlace](#conectividad-19-20) conserva 19 restricciones
activas en el snapshot: 10 via-node y 1 via-way admisibles, 6 fuera de `car`,
2 incompletas. Admisible no significa importada. La propuesta JSON no es un
escenario ejecutable: faltan memoria via-way, fuentes y compatibilidad del
validador. Solo se corrigieron tres conectores visuales topológicamente
permitidos. Sentidos, accesos, desniveles y extremos del extracto no se unen
por proximidad ni se eliminan por quedar fuera del componente principal.
Se conservan INTERNAL_INTERNAL, INTERNAL_EXTERNAL, EXTERNAL_INTERNAL y
EXTERNAL_EXTERNAL_THROUGH. Falta polígono aprobado; el rectángulo OSM no es
frontera administrativa. Red/perfiles/física/PT requieren versión nueva.

El [catálogo de fuentes fechado 22/10/2026](#transit-evidence) contiene 23
candidatas y 37 referencias: L1/L2/L6/L7/L12/L13/L18 y variantes, TuBus,
Transurbano y pistas de urbanos/extraurbanos. Conserva conflictos 2019–2026,
fuentes municipales/operadores y contraste Moovit identificado. GIS municipal:
CC BY 4.0; OSM: ODbL; no extender esas licencias a otras fuentes. Agencia Litegua
no prueba parada pública ni recorrido; El Amate y paradas TuBus son registros
distintos. Las secuencias, sentidos, horarios, flota, tiempos exteriores,
intersección con dominio y correspondencia parada→enlace siguen pendientes
donde el catálogo los deja en `null`. **Cero servicios habilitados para producción**.
Las afirmaciones de esa revisión no se vuelven a certificar como vigentes aquí.

B es el número de vehículos configurados, distinto del número de expediciones
y de buses activos; conductores internos no aumentan N. La implementación de
flota reutiliza IDs y valida disponibilidad, terminal y retorno; los retornos
exteriores sin runtime soportado siguen bloqueados. Estancia sintética sin
pasajeros no es tiempo observado de abordaje. Los fixtures públicos representan
servicios inventados en una red inventada, nunca rutas reales de Zona 1.

Las [paradas](#stop-signs) son verdes por servicio Transmetro y azules por
TuBus/Transurbano/urbano/extraurbano verificado, incluso si comparten operador.
Iconos distintos de luces, atlas compartido, sentido y transbordo explícitos;
52 registros municipales no equivalen a 52 plataformas: se dibujan 10
referencias documentadas del catálogo, todavía sin dominio/acceso nativo
revisado ni uso simulado atribuido. Los [semáforos](#semaforos-verticales)
usan geometría instanciada con ejes este/norte/arriba; frente local -Y hacia
el acceso entrante, independiente de rotación de cámara y etiqueta legible.
No cambian grupos, estados, ciclos u offsets. Verificación GPU pendiente.

La ruta seleccionada conserva halo del cuerpo y color de velocidad; recorrido
observado y posterior registrado tienen estilos distintos, sin predicción,
rectas sobre huecos ni consultas completas cada frame. El aviso de llegada usa
gestor compartido y reloj monotónico: **5000 ms reales**, incluso pausado o a
120x; pulso suave, retirada al RAF vencido y limpieza al seek/cambio de corrida.
Solo llegada confirmada con posición sustentada; aborto, censura, salida del
dominio y parada intermedia no son llegada final. Anotaciones fuera de colas,
colisiones y conteos físicos. No se añaden segundos a MATSim.

| Procedencia | Qué permite afirmar |
|---|---|
| Observado en eventos del modelo | Identidad, enlace, tiempos, carril si existe evento, llegada/aborto y movimiento forzado registrados. No es observación del tráfico real. |
| Interpolado/inferido | Posición/orientación entre eventos, cola visual, línea de parada y conectores esquemáticos. No cambia timestamps, FIFO ni velocidades nativas. |
| Supuesto explícito | Dimensiones de referencia, pesos, velocidades propuestas, estancia y servicio sintético. Debe conservar versión y fuente del supuesto. |
| Desconocido/pendiente | Ventana no cargada, intervalo abierto, posición de parada sin respaldo, tramo exterior o dato sin fuente. No equivale a cero ni a llegada. |

<a id="operacion-compilar"></a>
### 1. Compilación aislada y regresiones

Ejecutar los bloques numerados en la misma PowerShell desde la raíz; las
terminales adicionales del servidor se indican expresamente. Requiere JDK 25,
Node 22+, Python del proyecto y dependencias Maven disponibles. No usar `clean`.
La copia de POM cambia solo rutas de compilación/recursos y salida; las fuentes
siguen siendo las actuales del repositorio, incluidos los overrides de QSim.
El classpath solo contiene clases de una carpeta UUID nueva y JAR de dependencias.

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Stop'
$simz1Root = $PWD.Path
$simz1Python = Join-Path $simz1Root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $simz1Python -PathType Leaf)) { throw 'Preparar primero .venv del proyecto.' }
Get-Content -LiteralPath .\AGENTS.md -Encoding UTF8
git status --short
java -version
javac -version
node --version
@'
import sys, tempfile
from pathlib import Path
sys.path.insert(0, 'python')
from simz1_recovery_io import preflight_storage
for path in (Path.cwd(), Path(tempfile.gettempdir())):
    print(preflight_storage(path, required_bytes=1024**3, reserve_bytes=2*1024**3, probe_write=False))
'@ | & $simz1Python -B -
if ($LASTEXITCODE -ne 0) { throw 'Preflight de rutas/espacio fallido.' }
$simz1Work = Join-Path $simz1Root ('runtime\validation\manual-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $simz1Work -ErrorAction Stop | Out-Null
$simz1Build = Join-Path $simz1Work 'build'
$simz1Pom = Join-Path $simz1Work 'pom.xml'
[xml]$simz1PomXml = Get-Content -LiteralPath .\pom.xml -Raw -Encoding UTF8
$simz1Ns = $simz1PomXml.DocumentElement.NamespaceURI
function Add-SimZ1PomNode($Parent, [string]$Name, [string]$Value) {
    $node = $simz1PomXml.CreateElement($Name, $simz1Ns)
    $node.InnerText = $Value
    [void]$Parent.AppendChild($node)
}
$simz1BuildNode = $simz1PomXml.project.build
Add-SimZ1PomNode $simz1BuildNode 'directory' $simz1Build
Add-SimZ1PomNode $simz1BuildNode 'sourceDirectory' (Join-Path $simz1Root 'src\main\java')
Add-SimZ1PomNode $simz1BuildNode 'testSourceDirectory' (Join-Path $simz1Root 'src\test\java')
foreach ($entry in @(@('resources','resource','src\main\resources'), @('testResources','testResource','src\test\resources'))) {
    $group = $simz1PomXml.CreateElement($entry[0], $simz1Ns)
    $resource = $simz1PomXml.CreateElement($entry[1], $simz1Ns)
    Add-SimZ1PomNode $resource 'directory' (Join-Path $simz1Root $entry[2])
    [void]$group.AppendChild($resource)
    [void]$simz1BuildNode.AppendChild($group)
}
$simz1PomXml.Save($simz1Pom)
function Get-SimZ1SourceStamp {
    $paths = @('pom.xml') + @(rg --files src -g '*.java')
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron enumerar fuentes.' }
    return (($paths | Sort-Object | ForEach-Object { $_ + ' ' + (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash }) -join "`n")
}
$simz1SourceStamp = Get-SimZ1SourceStamp
$simz1SourceStamp | Set-Content -LiteralPath (Join-Path $simz1Work 'compiled-sources.txt') -Encoding UTF8
$simz1Deps = Join-Path $simz1Work 'dependencies.txt'
& .\mvnw.cmd -f $simz1Pom --batch-mode --no-transfer-progress test-compile dependency:build-classpath '-DskipTests' "-Dmdep.outputFile=$simz1Deps"
if ($LASTEXITCODE -ne 0) { throw "Compilacion fallida; conservar $simz1Work." }
if ((Get-SimZ1SourceStamp) -ne $simz1SourceStamp) { throw 'Fuentes cambiaron durante compilacion; comenzar otro bloque 1.' }
$simz1DependencyPath = (Get-Content -LiteralPath $simz1Deps -Raw).Trim()
foreach ($jar in $simz1DependencyPath.Split(';')) {
    if (-not $jar.EndsWith('.jar') -or -not (Test-Path -LiteralPath $jar -PathType Leaf)) { throw "Dependencia invalida: $jar" }
}
$simz1ClassPath = (Join-Path $simz1Build 'test-classes') + ';' + (Join-Path $simz1Build 'classes') + ';' + $simz1DependencyPath
function Invoke-SimZ1FreshJava([string]$Class, [string[]]$MainArgs = @()) {
    if ((Get-SimZ1SourceStamp) -ne $simz1SourceStamp) { throw 'Recompilar fuentes modificadas en otro UUID.' }
    $log = Join-Path $simz1Work ($Class.Split('.')[-1] + '-' + [guid]::NewGuid().ToString('N') + '.log')
    & java '-Xlog:class+load=info' -cp $simz1ClassPath $Class @MainArgs *> $log
    $code = $LASTEXITCODE
    $pattern = [regex]::Escape($Class) + ' source: (.+)$'
    $loaded = @(Select-String -LiteralPath $log -Pattern $pattern)
    if ($loaded.Count -ne 1) { throw "No se acredita origen de clase; revisar $log" }
    $location = [uri]($loaded[0].Matches[0].Groups[1].Value)
    $expected = Join-Path $simz1Build 'test-classes'
    if ($location.LocalPath.TrimEnd('\','/') -ne $expected.TrimEnd('\','/')) { throw "Clase ajena al build nuevo: $location" }
    Write-Host ($loaded[0].Line)
    if ($code -ne 0) { throw "Fallo Java ($code); conservar $log" }
    Write-Host "Resultado Java y procedencia: $log"
}
$simz1VehicleTypes = Join-Path $simz1Work 'vehicle-types.xml'
@'
import sys, xml.etree.ElementTree as ET
sys.path.insert(0, 'python')
from simz1_agent_types import load_catalog, vehicle_types_xml
with open(sys.argv[1], 'xb') as stream:
    ET.ElementTree(vehicle_types_xml(load_catalog('scenarios/zona1/agent-types-road-v1.json'))).write(stream, encoding='utf-8', xml_declaration=True)
'@ | & $simz1Python -B - $simz1VehicleTypes
if ($LASTEXITCODE -ne 0) { throw 'XML de contrato no preparado.' }
Invoke-SimZ1FreshJava 'gt.edu.uvg.sim.zona1.RoadVehicleProfilesCheck' @($simz1VehicleTypes)
foreach ($name in @('SixTypeProfilesCheck','SimZ1TransitFleetCheck','SimZ1TransitDiagnosticsCheck')) {
    Invoke-SimZ1FreshJava ('gt.edu.uvg.sim.zona1.' + $name)
}
# Las regresiones sin servidores están en integracion-prompts-1-8.
# check_simz1_replay_integration.ps1 incluye tests que abren servidores HTTP;
# no usarlo bajo la restricción de este prompt.
foreach ($test in @('test_simz1_agent_demand.py','test_simz1_transit_fleet.py','test_simz1_transit_accounting.py','test_simz1_transit_catalog.py','test_simz1_transit_stops.py','test_simz1_connectivity_review.py','test_simz1_connectivity_revision.py','test_simz1_osm_turn_audit.py','test_simz1_four_od.py','test_simz1_sqlite_export.py','test_simz1_storage_diagnostics.py','test_simz1_event_validation.py')) {
    & $simz1Python -B -m unittest discover -s python -p $test -v
    if ($LASTEXITCODE -ne 0) { throw "Fallo: $test" }
}
```

Resultado esperado: compilación y checks terminan con código 0, registro de
carga apunta al UUID, no a `target`; las pruebas de bloqueo rechazan pesados
y catálogos incompletos como corresponde. `test-compile` no ejecuta estos
`main`; por eso se invocan explícitamente. Este procedimiento Maven completo
sigue pendiente; la compilación javac acotada y los cinco checks del Prompt 9
sí se ejecutaron, con el alcance descrito en la matriz actual.

### 2. Abrir la corrida histórica seleccionada sin regenerar

Inspección local realmente ejecutada en esta revisión: N=227187,
`run_id=simz1-0dd152dabbc24d1d84d9b738c449cc35`, iteración 0,
`sqlite-direct-v1`; manifiesto nativo
`2d93aa7cd197200761917e6cf0c1c7d2848aaeb5102b502e744799bd8814f456`.
SHA de fuentes del cliente actual:
`1c741407c123865196cd0f19e31a26743d724b92c6f3ea9b53b2151bf3d5a0fe`.
El HTML guardado **difiere** de las fuentes actuales. Eso no prueba qué sirve
8793 ni qué cargó la pestaña: ambas verificaciones quedan para los comandos
siguientes. El inspector solo validó metadatos/hashes, no todo SQLite/eventos.

```powershell
$simz1Historical = (Resolve-Path -LiteralPath '.\runtime\simz1-227187-direct\webgl-continuo').Path
$simz1Raw = & $simz1Python -B .\python\inspect_simz1_client.py --replay-dir $simz1Historical
if ($LASTEXITCODE -ne 0) { throw 'Identidad local no verificada.' }
$simz1Identity = ($simz1Raw -join "`n") | ConvertFrom-Json
if ($simz1Identity.run_id -ne 'simz1-0dd152dabbc24d1d84d9b738c449cc35' -or $simz1Identity.iteration -ne 0) { throw 'Otra corrida; no continuar con estos IDs testigo.' }
$simz1SourceManifest = Get-Content -LiteralPath (Join-Path $simz1Identity.source_directory 'sqlite-source-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
& .\scripts\replay\start_replay.ps1 -RunDir $simz1SourceManifest.run_directory -Iteration 0 -ReplayDir $simz1Historical -Port 8793 -CheckOnly
if (-not $?) { throw 'Validacion del replay fallida; no regenerar para ocultarla.' }
$simz1Identity | Select-Object run_id,iteration,planned_persons,source_type,run_manifest_sha256,source_manifest_sha256,current_client_build | Format-List
```

En **otra PowerShell**, detener con Ctrl+C únicamente el servidor propio anterior
si aún sirve código viejo; iniciar manualmente este y abrir/recargar
`http://127.0.0.1:8793/index.html`. No abrir el `index.html` guardado con `file://`.

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& .\.venv\Scripts\python.exe -B .\python\serve_simz1_continuous.py --directory .\runtime\simz1-227187-direct\webgl-continuo --port 8793
if ($LASTEXITCODE -ne 0) { throw 'Servidor no iniciado; revisar puerto y manifiesto.' }
```

En la consola de trabajo original, verificar la respuesta ya servida:

```powershell
$simz1Raw = & $simz1Python -B .\python\inspect_simz1_client.py --replay-dir $simz1Historical --url http://127.0.0.1:8793/index.html
if ($LASTEXITCODE -ne 0) { throw 'HTTP no acredita misma identidad/fuente/cliente.' }
$simz1Identity = ($simz1Raw -join "`n") | ConvertFrom-Json
$simz1Identity.http | Format-List
```

### 3. Colas, trayectoria, selección y cámara

```powershell
foreach ($test in @('test_simz1_vehicle_presentation.cjs','test_simz1_vehicle_picking.cjs','test_simz1_rigid_vehicles.cjs','test_simz1_visual_queues.cjs','test_simz1_queue_safety.cjs','test_simz1_queue_continuity.cjs','test_simz1_queue_contract.cjs','test_simz1_queue_window_controls.cjs','test_simz1_selected_route.cjs','test_simz1_signal_geometry.cjs','test_simz1_transit_stops.cjs','test_simz1_visibility_geometry.cjs','test_simz1_visibility_temporal.cjs','test_simz1_window_identity.cjs','test_simz1_window_loading.cjs')) {
    & node (Join-Path 'python' $test)
    if ($LASTEXITCODE -ne 0) { throw "Fallo: $test" }
}
$simz1Console = @'
const expected=__EXPECTED__, api=window.simz1Continuous;
if (!api?.deck?.isInitialized) throw Error('Esperar inicializacion de Deck');
const actual=api.getVisualDiagnostics();
if (actual.run_id!==expected.run_id || actual.iteration!==expected.iteration ||
    actual.run_manifest_sha256!==expected.run_manifest_sha256 ||
    actual.replay_source?.source_manifest_sha256!==expected.source_manifest_sha256 ||
    window.simz1ClientBuild?.source_sha256!==expected.current_client_build.source_sha256)
  throw Error('Pestana distinta: no atribuir trazas a las capturas');
api.pause();
window.reviewSimZ1Camera=(bearing,pitch)=>api.deck.props.onViewStateChange({
  viewState:{...api.getState().camera.viewState,bearing,pitch}});
window.copySimZ1Selected=()=>copy(JSON.stringify({client:window.simz1ClientBuild,
  diagnostic:api.getVisualDiagnostics(),trace:api.traceSelectedVehicle()},null,2));
const traces=[];
for(const [id,t,times] of [
 ['z1_43360',124,[123.999,124,124.5,124.999,125,125.001]],
 ['z1_38616',41,[38.999,39,40.999,41,45.999,46,46.001]],
 ['z1_167074',169,[168.999,169,169.001]]]) {
  api.seek(t);
  const deadline=performance.now()+60000;
  while(api.getState().buffering && performance.now()<deadline) {
    if(api.getState().error) throw Error(api.getState().error);
    await new Promise(requestAnimationFrame);
  }
  if(api.getState().buffering || api.getState().current!==t) throw Error('Ventana pendiente');
  traces.push(...api.traceVehicle(id,times));
}
window.simz1ManualTrace={expected,traces};
copy(JSON.stringify(window.simz1ManualTrace,null,2));
// Clic en un vehiculo y ejecutar: copySimZ1Selected();
// Revisar cada combinacion por separado, por ejemplo reviewSimZ1Camera(90,45).
'@
Set-Clipboard -Value $simz1Console.Replace('__EXPECTED__', ($simz1Identity | ConvertTo-Json -Depth 20 -Compress))
```

Pegar en consola del visor ya abierto. Son los mismos IDs de la muestra local,
no IDs atribuidos a las capturas. Revisar rumbos 0/90/180/270 con inclinaciones
0/30/60, máximo zoom, pausa y seek inverso. Hacer clic y `copySimZ1Selected()`
conserva run/iteración/persona/vehículo/viaje/tiempo/enlace/carril/cuerpo/motivo.
Comparar 2/5/10 vehículos y longitudes mixtas mediante fixtures; si el replay
histórico no contiene un caso, registrarlo como no observado. La separación
longitudinal y SAT no permiten declarar resuelta una incompatibilidad de espacio.
Revisar ruta con curvas, enlaces repetidos, huecos, cambio de selección y limpieza
al llegar; halo sobre cuerpo, color de velocidad y posterior registrado sin
interpretarlo como predicción. La ruta no debe unir segmentos desconocidos.

### 4. Llegada: reloj real y pausa

```powershell
& node .\python\test_simz1_arrival_effects.cjs
if ($LASTEXITCODE -ne 0) { throw 'Contrato de llegada fallido.' }
& node .\python\test_simz1_transit_replay.cjs
if ($LASTEXITCODE -ne 0) { throw 'Fin de servicio/expediciones fallido.' }
```

Para medir en la pestaña, ejecutar el bloque PowerShell completo de
[aviso de llegada](#aviso-llegada), que inspecciona identidad HTTP y copia
`reviewSimZ1Arrival` al portapapeles. Tras pegarlo, ejecuta 120x; repetir
`await reviewSimZ1Arrival(1)` sobre el mismo vehículo/viaje. Usa `performance.now`,
pausa al aparecer el aviso y guarda muestras hasta vencer 5000 ms. Sin candidato
confirmado informa el bloqueo y no fabrica una llegada. Esperado: misma duración
real a ambas velocidades, pausa conservada, anotación retirada al siguiente
RAF y ningún cambio en conteos físicos. Los fixtures cubren buffering, censura,
aborto, seek, varias llegadas/viajes, parada intermedia y 24:00. No se ha medido
todavía ese comportamiento en GPU ni en una sesión real.

### 5. Preparar pruebas pequeñas con N y B explícitos

Dos pruebas **separadas**, ambas sintéticas. La vial habilita seis perfiles con
N=7: Normal/Liebre/Tortuga 1 cada uno, motos lenta/normal/rápida 1/2/1.
Pesado queda explícitamente en peso 0, porque su ejecución no está soportada;
no es una validación de pesados ni una redistribución silenciosa de la mezcla.
Se conserva el catálogo original: esta copia tiene otra versión y pesos
1/4/1/1/0 sobre 7. No se cambian horarios municipales ni datos históricos.
La pública usa el servicio inventado N=3/B=2/cuatro expediciones del fixture.

```powershell
$simz1SmallCatalog = Join-Path $simz1Work 'road-six-enabled-synthetic.json'
@'
import json,sys
from pathlib import Path
sys.path.insert(0,'python')
from simz1_agent_types import validate_catalog, allocation_counts
from simz1_agent_demand import generation_catalog
c=json.loads(Path('scenarios/zona1/agent-types-road-v1.json').read_text(encoding='utf-8'))
c['scenario_version']='manual-six-road-profiles-synthetic-v1'
c['description']='Separate synthetic N=7 road test; weights 1/4/1/1/0, heavy explicitly disabled. No public service.'
c['allocation']['road_weights']={'Normal':1,'Motociclista':4,'Liebre':1,'Tortuga':1,'TransportePesado':0}
validate_catalog(c)
with open(sys.argv[1],'x',encoding='utf-8') as f: json.dump(c,f,ensure_ascii=False,indent=2)
generation_catalog(Path(sys.argv[1]),mode='montecarlo',temporal_profile=None,hourly_weights=None,drain_seconds=None)
counts=allocation_counts(7,c)
assert counts=={'Normal':1,'MotocicletaLenta':1,'Motociclista':2,'MotocicletaRapida':1,'Liebre':1,'Tortuga':1,'TransportePesado':0},counts
print(counts)
'@ | & $simz1Python -B - $simz1SmallCatalog
if ($LASTEXITCODE -ne 0) { throw 'Catalogo pequeno rechazado.' }
$simz1Allocation = Join-Path $simz1Work 'road-allocation'
& $simz1Python -B .\python\prepare_simz1_agents.py --output-dir $simz1Allocation --agents 7 --seed 20261022 --catalog $simz1SmallCatalog --trips-per-person 1
if ($LASTEXITCODE -ne 0) { throw 'Asignacion no preparada.' }
Get-Content -LiteralPath (Join-Path $simz1Allocation 'agent-plan-manifest.json') -Raw -Encoding UTF8
$simz1Fleet = Join-Path $simz1Work 'public-synthetic'
& $simz1Python -B .\python\simz1_transit_fleet.py --config .\python\fixtures\simz1-transit-fleet-synthetic.json --output $simz1Fleet
if ($LASTEXITCODE -ne 0) { throw 'Flota sintetica rechazada.' }
Invoke-SimZ1FreshJava 'gt.edu.uvg.sim.zona1.SimZ1TransitFixture' @($simz1Fleet)
Get-Content -LiteralPath (Join-Path $simz1Fleet 'transit-fleet-manifest.json') -Raw -Encoding UTF8
```

Esperado: asignación `allocation_ready` pero `runnable:false` (no es corrida),
XML de flota validado sin QSim. No cambiar estos estados a mano. La prueba
conjunta N=7/B>0 continúa bloqueada por el punto de entrada/harness descrito.

### 6. Ejecutar manualmente una iteración y revisar evidencia

**Este bloque sí ejecuta MATSim al invocarlo el usuario.** Primero la prueba
vial N=7/B=0 en una carpeta nueva, iteración 0. El adaptador Maven pasa el POM
aislado al CLI existente; no modifica el lanzador ni reutiliza `target`.
La traza de carga acredita también la clase de entrada realmente ejecutada.

```powershell
$simz1MavenFresh = Join-Path $simz1Work 'maven-fresh.cmd'
@('@echo off', ('call "' + (Join-Path $simz1Root 'mvnw.cmd') + '" -f "' + $simz1Pom + '" %*'), 'exit /b %ERRORLEVEL%') | Set-Content -LiteralPath $simz1MavenFresh -Encoding Ascii
$simz1Run = Join-Path $simz1Root ('scenarios\zona1\montecarlo\run-manual-seven-' + [guid]::NewGuid().ToString('N'))
function Assert-SimZ1LauncherClass([string]$RunDir) {
    $log = Join-Path $RunDir 'matsim-run.log'
    $rows = @(Select-String -LiteralPath $log -Pattern 'gt\.edu\.uvg\.sim\.zona1\.RunZona1Simulation source: (.+)$')
    if ($rows.Count -ne 1) { throw "Falta procedencia de clase: $log" }
    $uri = [uri]($rows[0].Matches[0].Groups[1].Value)
    if ($uri.LocalPath.TrimEnd('\','/') -ne (Join-Path $simz1Build 'classes').TrimEnd('\','/')) { throw "Se ejecutaron clases ajenas: $uri" }
    Write-Host $rows[0].Line
}
if ((Get-SimZ1SourceStamp) -ne $simz1SourceStamp) { throw 'Repetir compilacion aislada por cambio de fuentes.' }
$simz1OldJavaOptions = $env:JAVA_TOOL_OPTIONS
try {
    $env:JAVA_TOOL_OPTIONS = ($simz1OldJavaOptions + ' -Xlog:class+load=info').Trim()
    & $simz1Python -B .\python\ejecutar_simz1.py --config .\scenarios\zona1\config-simz1.xml --maven $simz1MavenFresh --run-dir $simz1Run --mode montecarlo --agents 7 --agent-catalog $simz1SmallCatalog --seed 20261022 --matsim-seed 20261022 --iterations 1 --no-incidents --qsim-threads 4 --corridor-policy redistribute --trips-per-person 1
    $simz1Exit = $LASTEXITCODE
} finally { $env:JAVA_TOOL_OPTIONS = $simz1OldJavaOptions }
if ($simz1Exit -ne 0) { throw "Corrida fallida; conservar $simz1Run." }
Assert-SimZ1LauncherClass $simz1Run
$simz1Manifest = Get-Content -LiteralPath (Join-Path $simz1Run 'run-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($simz1Manifest.status -ne 'completed' -or $simz1Manifest.validation.status -ne 'valid') { throw 'Cierre no validado.' }
if ($simz1Manifest.iterations.first -ne 0 -or $simz1Manifest.iterations.last -ne 0) { throw 'No fue una sola iteracion.' }
if ($simz1Manifest.counts.planned_persons -ne 7 -or $simz1Manifest.counts.road_demand_persons -ne 7 -or $simz1Manifest.counts.public_transport_vehicles_configured -ne 0 -or $simz1Manifest.counts.transit_drivers_added_to_demand -ne 0) { throw 'N/B/conductores incompatibles.' }
$simz1Manifest | Select-Object run_id,status,counts,iterations,public_transport,agent_configuration | ConvertTo-Json -Depth 30
$simz1Manifest.results.'0' | Select-Object events,counts,native_qsim,temporal_events,lane_events,public_transport_events | ConvertTo-Json -Depth 40
@'
import sys,gzip,json,collections,xml.etree.ElementTree as ET
from pathlib import Path
sys.path.insert(0,'python')
from simz1_run import checked_path
root=Path(sys.argv[1]); m=json.loads((root/'run-manifest.json').read_text(encoding='utf-8'))
events=checked_path(root,m['results']['0']['events'])
counts=collections.Counter(); first=[]; previous=-float('inf')
with gzip.open(events,'rb') if str(events).endswith('.gz') else open(events,'rb') as stream:
    for _,element in ET.iterparse(stream,events=('end',)):
        if element.tag=='event':
            t=float(element.attrib['time'])
            assert t>=previous, (previous,t)
            previous=t; counts[element.get('type')]+=1
            if len(first)<8: first.append(dict(element.attrib))
        element.clear()
print(json.dumps({'events':str(events),'types':dict(counts),'first_events':first,'last_time':previous},indent=2))
'@ | & $simz1Python -B - $simz1Run
if ($LASTEXITCODE -ne 0) { throw 'Revision de eventos fallida.' }
& $simz1Python -B .\python\simz1_operational_report.py --run-dir $simz1Run --iteration 0 --no-plots
if ($LASTEXITCODE -ne 0) { throw 'Informe operativo fallido.' }
```

`redistribute` es el supuesto explícito de corredores disponibles del generador;
no certifica cuatro OD ni giros pendientes. Revisar tipos efectivos, arribos,
censura, abortos e intervenciones `storage_forced_move` por separado.
`completed/valid` no significa física calibrada ni ausencia de intervenciones.
Los históricos conservan sus correcciones de concurrencia/cronología.

Para ejecutar **separadamente** el fixture público, también una iteración 0
(600 s simulados; no 24 horas), con las clases recién compiladas:

```powershell
Invoke-SimZ1FreshJava 'gt.edu.uvg.sim.zona1.SimZ1TransitFixture' @($simz1Fleet,'--simulate')
$simz1FleetRuns = @(Get-ChildItem -LiteralPath $simz1Fleet -Directory -Filter 'simulation-*')
foreach ($simz1FleetRun in $simz1FleetRuns) {
    $simz1Result = Join-Path $simz1FleetRun.FullName 'synthetic-fleet-result.json'
    if (-not (Test-Path -LiteralPath $simz1Result)) { throw "Fixture incompleto: $($simz1FleetRun.FullName)" }
    Get-Content -LiteralPath $simz1Result -Raw -Encoding UTF8
    Get-ChildItem -LiteralPath $simz1FleetRun.FullName -Recurse -File | Where-Object { $_.Name -match 'events\.xml|simz1-trip-summary\.json' } | Select-Object FullName,Length
}
```

Esperado solo después de ejecución real: N=3, B=2, cuatro salidas con buses
reutilizados, dos conductores internos, tres viajes viales completados y cero
anomalías según assertions del harness. No sumar sus resultados a N=7 ni llamar
a esta red un servicio verificado. Si falta el JSON final, conservar el fallo.

### 7. Exportar la corrida nueva y abrir replay SQLite directo

Solo la corrida vial nueva `$simz1Run`, tras cierre validado. No ejecutar sobre
100000/229629/227187 ni sobre la salida del harness público sin manifiesto
productivo. Budgets de 1 GiB SQLite + 1 GiB scratch y reserva de 2 GiB para esta
prueba; son límites, no estimaciones de tamaño. Mantener ambas carpetas porque
el continuo referencia su fuente. No copiar decenas de GB ni invocar `--paged`.

```powershell
$simz1Source = Join-Path $simz1Run 'webgl-source'
$simz1Continuous = Join-Path $simz1Run 'webgl-continuo'
$simz1Scratch = Join-Path $simz1Work 'export-scratch'
@'
import sys
from pathlib import Path
sys.path.insert(0,'python')
from simz1_recovery_io import preflight_storage
for p in sys.argv[1:]:
    print(preflight_storage(Path(p),required_bytes=2*1024**3,reserve_bytes=2*1024**3,probe_write=False))
'@ | & $simz1Python -B - $simz1Run $simz1Work
if ($LASTEXITCODE -ne 0) { throw 'Disco/rutas insuficientes antes de temporales.' }
New-Item -ItemType Directory -Path $simz1Scratch -ErrorAction Stop | Out-Null
& $simz1Python -B .\python\visualizador_z1.py --run-dir $simz1Run --iteration 0 --sqlite-direct --output (Join-Path $simz1Source 'index.html') --temp-dir $simz1Scratch --sqlite-budget-gib 1 --scratch-budget-gib 1 --window-seconds 900 --replay-start 0 --replay-end 86400
if ($LASTEXITCODE -ne 0) { throw 'Exportacion incompleta; conservar evidencia y no declarar verificacion final.' }
& $simz1Python -B .\python\simz1_continuous_replay.py --source $simz1Source --output $simz1Continuous --sqlite-direct --run-dir $simz1Run --iteration 0 --temp-dir $simz1Scratch --window-seconds 120 --start 0 --end 86400
if ($LASTEXITCODE -ne 0) { throw 'Preparacion continua incompleta.' }
& $simz1Python -B .\python\verify_simz1_continuous_data.py --directory $simz1Continuous --offline --times 0 43200 86399
if ($LASTEXITCODE -ne 0) { throw 'Verificacion acotada de ventanas fallida.' }
& .\scripts\replay\start_replay.ps1 -RunDir $simz1Run -Iteration 0 -ReplayDir $simz1Continuous -Port 8794 -CheckOnly
if (-not $?) { throw 'Identidad/integridad no aprobadas.' }
Get-Content -LiteralPath (Join-Path $simz1Source 'sqlite-source-manifest.json') -Raw -Encoding UTF8
Get-Content -LiteralPath (Join-Path $simz1Continuous 'continuous-manifest.json') -Raw -Encoding UTF8
& .\scripts\replay\start_replay.ps1 -RunDir $simz1Run -Iteration 0 -ReplayDir $simz1Continuous -Port 8794 -NoBrowser
```

La última orden ocupa la terminal; abrir manualmente
`http://127.0.0.1:8794/index.html`. Ctrl+C cierra ese servidor. Usar otra consola
para medir. El nombre lógico `index.html` de `--output` no genera HTML fuente;
solo se genera la interfaz continua pequeña. La verificación acotada no mide
FPS ni certifica todos los viajes. Una exportación parcial no es éxito.

### 8. Medir rendimiento y disco

Primero medir el histórico identificado para ventanas densas; repetir con la
corrida nueva para coherencia. N=7 no representa una ventana densa ni mide el
costo real de buses/paradas. No usar `benchmark_simz1_continuous.py` sobre una
fuente directa: su `read_context` exige el contrato legado paginado. El harness
de integración y la sonda de pestaña sí corresponden al flujo actual.

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& .\check_simz1_replay_integration.ps1 -CpuBenchmark -CopyBrowserBenchmark
if (-not $?) { throw 'Benchmark/fixtures fallidos; conservar informe.' }
$simz1MeasureRoot = (Resolve-Path -LiteralPath (Read-Host 'Directorio de corrida o replay a medir, ya existente')).Path
if (-not $simz1MeasureRoot.StartsWith($PWD.Path.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Elegir una corrida/replay dentro de este proyecto SimZ1.' }
if ((Get-Item -LiteralPath $simz1MeasureRoot).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Resolver primero la ruta real; no medir un enlace de directorio.' }
$simz1Files = Get-ChildItem -LiteralPath $simz1MeasureRoot -File -Recurse -Force -ErrorAction Stop
$simz1Bytes = ($simz1Files | Measure-Object -Property Length -Sum).Sum
[pscustomobject]@{Path=$simz1MeasureRoot;Files=$simz1Files.Count;Bytes=$simz1Bytes;GiB=$simz1Bytes/1GB;MeasuredAt=(Get-Date).ToString('o')}
$simz1Files | Where-Object { $_.Extension -in '.sqlite','.html','.gz','.log' } | Sort-Object Length -Descending | Select-Object -First 15 FullName,Length
Get-PSDrive -PSProvider FileSystem | Select-Object Name,Root,Used,Free
```

Pegar el portapapeles en la consola del visor ya abierto: mide 1x/120x, seek,
carga/activación, frame CPU/RAF, colas/SAT, selección, memoria disponible y
costos de señales/paradas; después copiar
`copy(JSON.stringify(window.simz1IntegrationBenchmark,null,2))`.
Registrar mismo run/iteración/hash/cámara/equipo y caché para comparar.
La sonda restaura reloj/velocidad/pausa, pero limpia selección. Solo declara
buffering si ocurrió; cierre de loader en fixture no es cierre del navegador.
CPU sintética no es FPS ni GPU; memoria no expuesta queda desconocida.
Sumar `Length` mide tamaño lógico bajo esa carpeta, no bloques físicos ocupados,
archivos compartidos externos ni RAM. No sigue ni copia SQLite fuera del árbol;
si la fuente está fuera, medir también su ruta verificada, sin sumarla dos veces.

### Escala futura: bloque separado, actualmente detenido

No ejecutar hasta resolver red/via-way/dominio, validar las cuatro OD con rutas
testigo, prueba conjunta de perfiles/flota, 10/100/1000 personas, intervenciones,
censura, recursos y mediciones 1x/120x. El catálogo completo actual de pesados
no es ejecutable; tampoco los servicios públicos reales. El comando siguiente
es una plantilla **vial B=0**, con pesos OD iguales explícitamente sintéticos,
no un lanzamiento público listo. No ofrece un parámetro ficticio para B.
`--massive` con rango sortea N inclusivo, una sola iteración. No es autorización
ni prueba de capacidad: el guard permanece falso en la documentación.

```powershell
$simz1ScaleReviewed = $false
if (-not $simz1ScaleReviewed) { throw 'Escala detenida: resolver y revisar primero los pendientes de la matriz.' }
$simz1ApprovedConfig = (Resolve-Path -LiteralPath (Read-Host 'Config de NUEVA version revisada, con transit.useTransit=false')).Path
$simz1ApprovedCatalog = (Resolve-Path -LiteralPath (Read-Host 'Catalogo vial revisado y ejecutable')).Path
$simz1ApprovedBoundary = (Resolve-Path -LiteralPath (Read-Host 'GeoJSON del dominio aprobado con procedencia')).Path
$simz1ApprovedOsm = (Resolve-Path -LiteralPath (Read-Host 'OSM correspondiente a esa nueva red auditada')).Path
@'
import sys,xml.etree.ElementTree as ET
from pathlib import Path
sys.path.insert(0,'python')
from simz1_config_validation import validate_configuration
from simz1_lane_validation import audit_configuration
from simz1_agent_demand import generation_catalog
p=Path(sys.argv[1]); root=ET.parse(p).getroot()
flag=root.find("module[@name='transit']/param[@name='useTransit']")
assert flag is None or flag.get('value','false').lower()=='false','CLI publico aun no integrado'
print(validate_configuration(p)); print(audit_configuration(p))
generation_catalog(Path(sys.argv[2]),mode='montecarlo',temporal_profile=None,hourly_weights=None,drain_seconds=None)
'@ | & $simz1Python -B - $simz1ApprovedConfig $simz1ApprovedCatalog
if ($LASTEXITCODE -ne 0) { throw 'Preflight de configuracion/catalogo fallido.' }
if ((Get-SimZ1SourceStamp) -ne $simz1SourceStamp) { throw 'Recompilar y repetir regresiones antes de escala.' }
$simz1MassiveRun = Join-Path $simz1Root ('scenarios\zona1\montecarlo\run-future-massive-' + [guid]::NewGuid().ToString('N'))
$simz1OldJavaOptions = $env:JAVA_TOOL_OPTIONS
try {
    $env:JAVA_TOOL_OPTIONS = ($simz1OldJavaOptions + ' -Xlog:class+load=info').Trim()
    & $simz1Python -B .\python\ejecutar_simz1.py --config $simz1ApprovedConfig --maven $simz1MavenFresh --run-dir $simz1MassiveRun --mode montecarlo --massive --min-agents 150000 --max-agents 250000 --agent-catalog $simz1ApprovedCatalog --od-mode gateway-od --zone-boundary $simz1ApprovedBoundary --od-osm $simz1ApprovedOsm --od-shares '1,1,1,1' --seed 20261022 --matsim-seed 20261022 --iterations 1 --trips-per-person 1 --no-incidents --qsim-threads 4 --use-lanes --signals --unsignalized-priority --signal-offset-policy preserve
    $simz1Exit = $LASTEXITCODE
} finally { $env:JAVA_TOOL_OPTIONS = $simz1OldJavaOptions }
if ($simz1Exit -ne 0) { throw "Fallo: conservar $simz1MassiveRun y revisar primera causa." }
Assert-SimZ1LauncherClass $simz1MassiveRun
Get-Content -LiteralPath (Join-Path $simz1MassiveRun 'run-manifest.json') -Raw -Encoding UTF8
```

`gateway-od` rechaza `--corridor-policy`; por eso esta plantilla usa únicamente
los pesos OD. `--no-incidents` desactiva también el mecanismo legado de
perturbaciones de enlace; no basta con dejar apagado el módulo nuevo.
El preflight estructural y el guard manual no sustituyen las validaciones
físicas previas. El generador conserva sus bloqueos OSM/acceso; no retirarlos
para conseguir ejecutar la plantilla. Los presupuestos de exportación pequeña
no son presupuestos aprobados para esta escala.

<a id="matriz-consolidada"></a>
### Matriz anterior a la ejecución de integración

«No ejecutada» se refiere a esta consolidación y a los nuevos contratos de la
secuencia, salvo evidencia histórica expresamente fechada. Los resultados del
19/10 no se trasladan a cambios posteriores. Consultar la
[matriz actual](#integracion-prompts-1-8) para los resultados nuevos.
No hay calibración ni FPS certificados.

| Requisito | Implementación | Prueba disponible | Resultado ejecutado | Pendiente |
|---|---|---|---|---|
| Clases actuales | POM aislado, hashes y traza de carga en comandos | Bloque 1; checks Java existentes | Parsers/documentación revisados; compilación no ejecutada | Compilar, acreditar CodeSource y correr regresiones |
| Nombres/dimensiones/PCU/picking | Catálogo compartido; dimensiones por procedencia | `test_simz1_vehicle_presentation.cjs`, `test_simz1_vehicle_picking.cjs`, `RoadVehicleProfilesCheck` | No ejecutada | GPU a máximo zoom; articulación específica |
| Motos/pesados | Tres perfiles sintéticos; pesados bloqueados | `test_simz1_road_profiles.py`, bloque 5 | No ejecutada | Ensayo físico perfiles; accesos de pesados |
| Desapariciones/colas | Contexto temporal, identidad, cuerpos rígidos y SAT | Suites de bloque 3; tres IDs testigo | Identidad local/hashes verificados; no replay ejecutado | Reproducir casos, registrar incompatibilidades sin ocultar |
| Ruta/selección | `/api/journey`, caché, estilos y limpieza | `test_simz1_selected_route.cjs` | No ejecutada | Cámara, curvas/huecos y llegada en WebGL |
| Red/cuatro OD | OSM dirigido, revisión por enlace; propuesta no aplicada | `test_simz1_connectivity_review.py`, `test_simz1_osm_turn_audit.py`, `test_simz1_four_od.py` | Snapshot documental revisado | Via-way, fuentes, dominio y nueva red validada |
| Fuentes/PT real | 23 candidatas desactivadas, procedencia/conflictos | `test_simz1_transit_catalog.py` | JSON/documentación consultados; operación no verificada | Secuencias, calendario, accesos, flota, exterior y licencias pendientes |
| N/B/expediciones | API nativa y contadores separados; CLI general incompleto | `SimZ1TransitFixture`, `test_simz1_transit_accounting.py` | No ejecutada | Integrar entrada general; prueba conjunta seis perfiles + servicio |
| Paradas verdes/azules | Clase de servicio, atlas y sentido | `test_simz1_transit_stops.cjs/.py` | Actualización: 10 marcadores de catálogo elegibles; suites aprobadas en Prompt 9 | Uso por simulación y visualización real no acreditados |
| Semáforos verticales | Geometría instanciada en mundo | `test_simz1_signal_geometry.cjs` | No ejecutada | Giro 0/90/180/270, inclinaciones y carga GPU |
| Llegada 5000 ms | Reloj monotónico, gestor compartido, anotación | `test_simz1_arrival_effects.cjs`; `reviewSimZ1Arrival` | No ejecutada | Medición real 1x/120x, pausa y retiro |
| Replay público/SQLite | Metadatos futuros y export directo; históricos intactos | `test_simz1_replay_integration.py`, `test_simz1_sqlite_export.py` | Inspección acotada del histórico; export no ejecutado | Manifest productivo público y recorrido extremo a extremo |
| Rendimiento/disco | Harness CPU y sonda de pestaña; inventario lógico | Bloque 8 | Sin medición nueva | Densidad, caché, hardware, buses/paradas reales y cierre |
| Escala 150000–250000 | CLI `--massive`, guard manual separado | Preflights y regresiones acotadas | No ejecutada | Todos los bloqueos anteriores; decisión del usuario |

<a id="integracion-prompts-1-8"></a>
## Integración de los prompts 1–8: verificación del 22/10/2026

**No autorizar todavía 150000–250000 agentes.** Se leyó `AGENTS.md`, se revisaron
los cambios anteriores y se partió del árbol limpio en `7a366aa`. Esta revisión
solo cambia `README.md` y `docs/README.md`; conserva implementaciones, configuración,
red y corridas anteriores. No ejecutó MATSim/QSim, servidores ni navegadores.
Los temporales de pruebas están en `runtime/` y la compilación aislada en `target/`.
Ningún resultado siguiente acredita una corrida física ni una inspección GPU.

### Matriz actual y resultados ejecutados

| Funcionalidad | Resultado observado en esta revisión | Pendiente para aceptación |
|---|---|---|
| Semáforos | Suites de geometría, configuración y replay aprobadas: cuerpo, luces, orientación en mundo y tamaño acotado; sin sustitución R/V | Inspección WebGL lejos/medio/máximo, cenital/inclinada y giros 0/90/180/270; accesos opuestos y estados rojo/amarillo/verde |
| Paradas | Python 15 pruebas y suite JS aprobadas; catálogo con 9 marcadores verdes Transmetro y 1 azul TuBus, agrupados sin duplicar transbordo | Confirmar visualización y vigencia espacial/operativa; un marcador de catálogo no demuestra uso por QSim |
| Colas y cuerpos | Suites de línea de parada, cola, continuidad, geometría rígida, SAT y dimensiones aprobadas; conservan diagnóstico cuando no cabe la cola | Máximo zoom, curva y cola aguas arriba con datos reales; cero solapamientos solucionables en fixtures válidos no significa cero conflictos en el histórico |
| Selección | Picking por cuerpo, halo/foco, ruta y tarjeta de seis campos aprobados en fixtures | Cámara real, vehículos vecinos y selección durante cambios de ventana |
| Ventanas y llegadas | Identidad/carga JS aprobadas, pero fallan integración SQLite, cierre de ruta diaria y anotación de llegada | Resolver los fallos enumerados abajo; no se acredita ausencia general de desapariciones |
| Admisión nativa | Cinco checks Java aprobados; receptor, rojo/verde, espera prolongada, admisión estricta y concurrencia aislada | Corridas pequeñas reales con 1/4 hilos; cero transiciones inválidas, errores cronológicos o NPE de diagnóstico |
| Red | Auditoría en lectura: 11 vías/76 enlaces del sector, 0 segmentos dirigidos admisibles faltantes y 0 destinos de carril inválidos; sin cambios físicos | 19 relaciones OSM pendientes, límite aprobado y gateways dirigidos; las 10 rutas testigo incluyen casos sin camino, no todos los movimientos son legales |
| Accidentes | Contrato Java/Python de dos eventos y dos vehículos con duración exacta de 1800 s aprobado; 67 assertions del coordinador aislado | Adaptador físico por carril y observador nativo pendientes; habilitación productiva rechazada, no hay cierre/reapertura real validados |
| FPS/memoria | Benchmark CPU de 16 casos completado, con cierre de recursos del loader; falla la suite de reutilización de capa | Medición WebGL y comparación contra referencia en el mismo equipo; no se acredita ausencia de regresión ni de fuga |

Ejecuciones sin simulación:

- **JDK 25.0.4.1:** compilación fresca de fuentes SimZ1 y overrides QSim;
  `SimZ1IncidentLaneCheck`, `SimZ1ConfigurationCheck`, `SimZ1AdmissionCheck`,
  `SimZ1AdmissionConcurrencyCheck` y `SimZ1StorageBranchCheck` aprobados.
  El check de admisión concurrente usa dos propietarios de nodo y dos lectores
  de eventos, con 200 transferencias únicas. No equivale a cuatro hilos QSim.
  El script también repitió 55 pruebas Python y cuatro suites JS aprobadas;
  están incluidas en los conjuntos siguientes, no son cobertura adicional.
- **Python:** 255 pruebas en 24 suites; 21 suites aprobadas, tres con errores
  o fallos (un fallo de assertion y cuatro errores, incluidos subtests).
- **Node 22.12.0:** 29 de 32 suites aprobadas. Sintaxis: 139 archivos Python
  analizados mediante AST y 59 JS/CJS mediante `node --check`, sin errores.
- **CPU sintética:** 16 casos, cinco muestras por caso, N=100/1000,
  B=0/N÷5, recta densa/curva y 1x/120x. p95 de seek+dibujo entre 11,80–51,78 ms
  para N=100 y 91,88–458,99 ms para N=1000. Son mediciones del harness con Deck
  simulado, no FPS; pocas muestras y sin referencia previa. Los 16 loaders
  terminan sin ventanas/peticiones/bytes retenidos. El harness conserva otras
  referencias: esto no demuestra liberación total de heap ni estabilidad GPU.
- **Red:** preflight `blocked`: importación de restricciones y aprobación del
  dominio/gateways pendientes. Clasificación de las 19 relaciones: 10 mapeables,
  6 no representadas en esta red, 1 via-way no soportada y 2 incompletas/no
  soportadas. De las 10 rutas testigo, cuatro tienen camino configurado y seis
  no; ninguna se certifica legal mientras falte resolver las restricciones.
  No se aplicó la propuesta de nueva red ni se unieron extremos.

Evidencia local de esta ejecución (directorios ignorados por Git; no son datos
de una nueva corrida): `runtime/integration-prompt9-python-1792704103672109300/`,
`runtime/integration-prompt9-node-1792704104224349200/`,
`runtime/integration-prompt9-java-cf63cd9b62244008acd0d9c17768c1da/`,
`runtime/integration-prompt9-network-9de9803aee474206ace86b4a423f9e9b/` y
`runtime/integration-prompt9-benchmark-a937530a05424a9aacfa1c0df1be29d0/`.
Build nuevo: `target/simz1-incident-consequences-0893061ade6c40e0b96690a108d1a010/`;
incluye hashes de fuentes, classpath y XML de fixture. Se comprobaron tamaño/mtime
de SQLite y eventos históricos y SHA256 del manifiesto y vehículos contra la
evidencia del Prompt 8: coinciden. No se volvió a hashear la base de 24,9 GB.

### Fallos que impiden declarar integración aprobada

| Suite | Evidencia reproducida | Tratamiento necesario |
|---|---|---|
| `test_simz1_client_identity.py` | `test_build_hashes_actual_sources_and_changes_with_controls`: la lista esperada no incluye `incident_effects` | Revisar/actualizar el contrato de componentes sin debilitar la verificación de hashes |
| `test_simz1_sqlite_source.py` | `test_direct_daily_windows_and_seek_preserve_original_trajectories_trips_lanes_and_signals`: `ValueError: Evento de carril incompatible con el viaje` en `journey()` | Resolver compatibilidad de viaje/carril y fixture; conservar rechazo de evidencia inválida |
| `test_simz1_transit_events.py` | Dos métodos, tres errores contando subtests: `KeyError: admission_policy` al entrar en `NativeDecisionAudit` | Completar el manifiesto de fixtures y verificar validación extremo a extremo; los errores anticipados no prueban cronología ni flota correctas |
| `test_simz1_continuous_replay.cjs` | `future route stops at day closure`, esperado 1, obtenido 0 | Revisar cierre diario/ruta sin inventar llegadas |
| `test_simz1_render_performance.cjs` | `stationary rows do not invalidate GPU attributes` | Revisar identidad/reutilización de capas y medir el efecto real; fallo de contrato, no medida GPU |
| `test_simz1_arrival_effects.cjs` | Falta la anotación esperada al cruzar una llegada junto al límite de ventana | Revisar ciclo de llegada/ventana y repetir seek/pausa/1x/120x |

No se corrigieron estos archivos porque este prompt limita los cambios a los dos
README. Un fixture desactualizado tampoco se convierte automáticamente en PASS:
primero hay que contrastarlo con el contrato actual y repetirlo.

### Datos, supuestos y eventos sintéticos

Las coordenadas y relaciones del extracto OSM y los eventos MATSim son evidencia
de sus respectivas fuentes, no observaciones continuas del tráfico real.
Los 10 marcadores de parada proceden del catálogo revisado en el Prompt 2;
L1/L2 comparten San Sebastián y la plataforma azul corresponde a TuBus 5,
Parque Colón. L6/L7/L12/L13/L18 y otros candidatos sin evidencia suficiente no
se convierten en paradas nuevas. Esta revisión no recertifica vigencia oficial.
El histórico de 227187 personas no demuestra servicio público configurado.

Se mantienen dimensiones visuales asumidas: **carro 4,5×1,8 m, moto 2,1×0,8 m,
camión 10×2,5 m y bus 12×2,5 m**. Datos registrados válidos y su procedencia
tienen prioridad. Separación longitudinal visual de referencia 2 m,
envolvente 0,1 m y tolerancia de picking 8 px mouse/18 px táctil son conceptos
distintos de VehicleType y PCU. Línea de parada inferida y posición interpolada
deben identificarse como tales. QSim no garantiza distancia continua exacta
entre carrocerías; el visor no debe transformar un solapamiento en accidente.

La política futura `strict-receiver-v1` cambia explícitamente admisión/espera
respecto de la rama histórica: no usar la diferencia frente al histórico como
prueba de efecto de incidentes. WAIT/FORCE/ABORT y pendientes se conservan como
diagnósticos separados. El nuevo módulo sintético sigue apagado y falla cerrado
si se solicita activarlo. El mecanismo legado `StochasticCrashEvent` es otra
función: **todos los comandos nuevos de corrida deben incluir `--no-incidents`**.
Ni la probabilidad sintética de referencia ni un objetivo de 0–5 diarios son
estadísticas verificadas de Guatemala.

El CLI `ejecutar_simz1.py` invoca `RunZona1Simulation`; esta entrada no instala
la flota pública como `SimZ1.main`. No sustituir silenciosamente la clase en un
wrapper, ni declarar validada una corrida conjunta de todos los tipos con buses.
Los siguientes smoke tests viales tienen B=0 y perfiles históricos; el catálogo
completo continúa sujeto a accesos de pesados y a integración pública pendiente.

### Comandos repetibles sin MATSim, servidor ni navegador

Desde la raíz, con JDK 25 activo. La compilación acotada usa únicamente JAR de
dependencias y un directorio nuevo; no reutiliza bytecode antiguo. No ejecutar
`mvn test` indiscriminadamente: algunos checks del repositorio sí arrancan QSim.

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$ErrorActionPreference = 'Stop'
$simz1Python = (Resolve-Path .\.venv\Scripts\python.exe).Path
Get-Content .\AGENTS.md -Encoding UTF8
git status --short
java -version
$simz1JavacVersion = & javac -version 2>&1
if ($LASTEXITCODE -ne 0 -or "$simz1JavacVersion" -notmatch '^javac 25[.\s]') { throw 'Activar JDK 25 en JAVA_HOME y PATH.' }
$simz1CheckWork = Join-Path $PWD.Path ('runtime\integration-manual-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $simz1CheckWork | Out-Null
$simz1DepsFile = Join-Path $simz1CheckWork 'dependencies.txt'
& .\mvnw.cmd --offline --batch-mode --no-transfer-progress dependency:build-classpath "-Dmdep.outputFile=$simz1DepsFile"
if ($LASTEXITCODE -ne 0) { throw 'Faltan dependencias Maven; no continuar con clases antiguas.' }
& .\check_simz1_incident_consequences.ps1 -DependencyClasspathFile $simz1DepsFile
if (-not $?) { throw 'Contrato Java/Python/JS fallido.' }
```

Este último comando prueba **el contrato de 1800 s**, identidad, dos afectados,
un carril independiente frente a sus vecinos, resolución, cierre censurado del
horizonte y cuatro productores. `native_adapter_installed=false` y
`simulation_executed=false` son resultados esperados. No hay actualmente un
comando válido que demuestre inmovilización física de 1800 s en QSim. Falta
interceptar de forma segura salida, llegada, buffers y transferencias internas
de carril; `NetworkChangeEvent` de enlace no acredita cierre exclusivo de carril.
No habilitar naranja/emergencia productivos a partir de fixtures o FORCE.

La selección explícita siguiente evita suites que abren servidores HTTP.
Continúa tras cada suite para registrar todos los fallos, y falla al final.

```powershell
$simz1PythonSuites = @(
 'physical_dimensions','agent_metadata','motion','road_profiles','replay_integration',
 'transit_stops','client_identity','signals_config','signals_replay','admission',
 'storage_diagnostics','connectivity_review','connectivity_revision','event_validation',
 'temporal','lane_validation','incident_configuration','incident_design','incident_replay',
 'sqlite_source','priority','visual_motion','queue_context','transit_events')
$simz1JsSuites = @(
 'signal_geometry','transit_stops','visual_lanes','visual_queues','vehicle_presentation',
 'vehicle_dimensions','road_presentation','rigid_vehicles','body_spacing','vehicle_picking',
 'vehicle_picking_dimensions','vehicle_focus','vehicle_card','queue_contract','queue_safety',
 'queue_window_controls','queue_continuity','native_queue_extent','queue_stoplines',
 'queue_head_fallback','conflict_diagnostics','spatial_view','continuous_bootstrap',
 'incident_effects','visual_connectivity','selected_route','continuous_replay',
 'render_performance','arrival_effects','window_identity','window_loading','transit_replay')
$simz1Failures = @()
foreach ($suite in $simz1PythonSuites) {
    & $simz1Python -B -m unittest discover -s python -p "test_simz1_$suite.py" -v
    if ($LASTEXITCODE -ne 0) { $simz1Failures += "Python:$suite" }
}
foreach ($suite in $simz1JsSuites) {
    & node (Join-Path 'python' "test_simz1_$suite.cjs")
    if ($LASTEXITCODE -ne 0) { $simz1Failures += "JS:$suite" }
}
if ($simz1Failures.Count) { throw ('Suites fallidas: ' + ($simz1Failures -join ', ')) }
```

Sintaxis y benchmark CPU, independientes del resultado de las suites:

```powershell
@'
import ast, subprocess
from pathlib import Path
r=Path('.')
py=sorted(set(r.glob('python/*simz1*.py'))|set(r.glob('python/*visualizador*z1*.py')))
for p in py: ast.parse(p.read_text(encoding='utf-8-sig'), filename=str(p))
js=sorted(set(r.glob('python/*simz1*.js'))|set(r.glob('python/*simz1*.cjs'))|set(r.glob('scripts/validation/*simz1*.cjs')))
for p in js: subprocess.run(['node','--check',str(p)],check=True)
print({'python_ast':len(py),'js_syntax':len(js)})
'@ | & $simz1Python -B -
if ($LASTEXITCODE -ne 0) { throw 'Sintaxis invalida.' }
& node --expose-gc .\scripts\validation\benchmark_simz1_integration.cjs --frames 5 --output (Join-Path $simz1CheckWork 'cpu.json')
if ($LASTEXITCODE -ne 0) { throw 'Benchmark CPU incompleto.' }
$simz1AuditDir = Join-Path $simz1CheckWork 'network'
& $simz1Python -B .\python\inspect_simz1_connectivity.py --scenario .\scenarios\zona1 --strict --output-new $simz1AuditDir
if ($LASTEXITCODE -ne 0) { throw "Preflight bloqueado; revisar $simz1AuditDir, no cambiar la red historica." }
```

### Corridas manuales de 10, 100 y 1000: una iteración, 4/1 hilos

**Comandos preparados, no ejecutados.** Primero resolver las seis suites fallidas.
Para preparar el Maven aislado, ejecutar el [bloque de compilación](#operacion-compilar)
en la misma PowerShell: define `$simz1Root`, `$simz1Work`, `$simz1Pom`,
`$simz1Build`, `$simz1SourceStamp` y `Get-SimZ1SourceStamp`.
No usar el bloque de siete personas como requisito de estos smoke tests.
La siguiente función reutiliza ese POM, verifica la clase cargada y conserva
cada intento en una carpeta nueva. No altera el histórico; una corrida válida
puede actualizar el puntero `latest-successful`, que no identifica al histórico.

```powershell
$simz1SmallRunsReviewed = $false
if (-not $simz1SmallRunsReviewed) { throw 'Revisar regresiones y autorizar pruebas pequenas antes de ejecutar.' }
$simz1MavenFresh = Join-Path $simz1Work 'maven-fresh.cmd'
@('@echo off', ('call "' + (Join-Path $simz1Root 'mvnw.cmd') + '" -f "' + $simz1Pom + '" %*'), 'exit /b %ERRORLEVEL%') | Set-Content -LiteralPath $simz1MavenFresh -Encoding Ascii
function Invoke-SimZ1IntegrationSmall([ValidateSet(10,100,1000)][int]$N, [ValidateSet(1,4)][int]$Threads) {
    if ((Get-SimZ1SourceStamp) -ne $simz1SourceStamp) { throw 'Recompilar fuentes cambiadas.' }
    $dir = Join-Path $simz1Root ("scenarios\zona1\montecarlo\run-integration-n$N-t$Threads-" + [guid]::NewGuid().ToString('N'))
    $previousOptions = $env:JAVA_TOOL_OPTIONS
    try {
        $env:JAVA_TOOL_OPTIONS = ($previousOptions + ' -Xlog:class+load=info').Trim()
        & $simz1Python -B .\python\ejecutar_simz1.py --config .\scenarios\zona1\config-simz1.xml --maven $simz1MavenFresh --run-dir $dir --mode montecarlo --agents $N --seed 20261022 --matsim-seed 20261022 --iterations 1 --qsim-threads $Threads --no-incidents --use-lanes --signals --unsignalized-priority --signal-offset-policy preserve --od-mode network --corridor-policy redistribute --temporal-profile full-day --trips-per-person 1 --drain-seconds 0 | Out-Host
        $code = $LASTEXITCODE
    } finally { $env:JAVA_TOOL_OPTIONS = $previousOptions }
    if ($code -ne 0) { throw "Corrida fallida; conservar $dir." }
    $loaded = @(Select-String -LiteralPath (Join-Path $dir 'matsim-run.log') -Pattern 'gt\.edu\.uvg\.sim\.zona1\.RunZona1Simulation source: (.+)$')
    if ($loaded.Count -ne 1) { throw 'Falta procedencia de la clase de entrada.' }
    $uri = [uri]$loaded[0].Matches[0].Groups[1].Value
    if ($uri.LocalPath.TrimEnd('\','/') -ne (Join-Path $simz1Build 'classes').TrimEnd('\','/')) { throw 'Clase ajena al build aislado.' }
    $m = Get-Content -LiteralPath (Join-Path $dir 'run-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($m.status -ne 'completed' -or $m.validation.status -ne 'valid' -or $m.iterations.first -ne 0 -or $m.iterations.last -ne 0 -or $m.counts.planned_persons -ne $N) { throw 'Identidad/cierre/iteracion no validados.' }
    $effective = $m.effective_configuration_validation
    if ($effective.admission_policy -ne 'strict-receiver-v1' -or $effective.qsim_threads -ne $Threads -or $effective.remove_stuck_vehicles -ne $false -or $effective.incidents_enabled -ne $false -or $effective.incident_consequences.requested_enabled -ne $false -or $effective.incident_consequences.installed -ne $false -or $m.counts.public_transport_vehicles_configured -ne 0) { throw 'Configuracion efectiva distinta del contrato vial sin incidentes.' }
    $m | Select-Object run_id,counts,effective_configuration_validation | ConvertTo-Json -Depth 30 | Write-Host
    $m.results.'0' | Select-Object counts,native_qsim,temporal_events,lane_events,public_transport_events | ConvertTo-Json -Depth 40 | Write-Host
    return $dir
}
```

Ejecutar **una línea cada vez**, inspeccionar y conservar resultados antes de
pasar al siguiente tamaño. `redistribute` es un supuesto de demanda de la prueba
técnica; no certifica cuatro OD, restricciones OSM pendientes ni acceso de pesados.

```powershell
$simz1Run10T4 = Invoke-SimZ1IntegrationSmall 10 4
$simz1Run10T1 = Invoke-SimZ1IntegrationSmall 10 1
$simz1Run100T4 = Invoke-SimZ1IntegrationSmall 100 4
$simz1Run100T1 = Invoke-SimZ1IntegrationSmall 100 1
$simz1Run1000T4 = Invoke-SimZ1IntegrationSmall 1000 4
$simz1Run1000T1 = Invoke-SimZ1IntegrationSmall 1000 1
```

Para comparar, conservar semillas, población/rutas iniciales, versiones de red,
señales, prioridades, perfiles y horizonte; verificar hashes de las entradas
correspondientes. El número de hilos es la única diferencia experimental.
No exigir igualdad byte a byte de logs o de eventos empatados entre hilos;
exigir las mismas invariantes de legalidad, IDs, cronología y contabilidad, y
explicar diferencias de tiempos/rutas. La equivalencia de incidentes apagados
se compara con la **misma versión y los mismos hilos**: configuración omitida
frente a `enabled=false`, sin activar `StochasticCrashEvent`. Solo hay evidencia
de esa equivalencia en fixtures, aún no en dos corridas nativas.

Después de cada corrida elegida, inspeccionar el XML efectivo y manifiesto:
`strict-receiver-v1`, `removeStuckVehicles=false`, hilos solicitados, incidentes
apagados y `VehicleType` realmente cargados. Exigir cero transiciones inválidas,
cero errores cronológicos, cero NPE y cero FORCE por almacenamiento en modo
estricto. Contabilizar WAIT, arribos, abortos, viajes no iniciados y pendientes
al horizonte por separado; un pendiente no es una llegada ni un teletransporte.

```powershell
$simz1Run = $simz1Run10T4 # luego elegir cada otro intento, sin sobreescribirlo
$simz1CensoredLimit = [double](Read-Host 'Umbral de censura acordado antes de comparar, entre 0 y 1')
if ($simz1CensoredLimit -lt 0 -or $simz1CensoredLimit -gt 1 -or [double]::IsNaN($simz1CensoredLimit)) { throw 'Umbral invalido.' }
$simz1Capacity = Join-Path $simz1Run ('capacity-' + [guid]::NewGuid().ToString('N') + '.json')
$simz1LimitText = $simz1CensoredLimit.ToString([Globalization.CultureInfo]::InvariantCulture)
& $simz1Python -B .\python\simz1_capacity_diagnostics.py --run-dir $simz1Run --iteration 0 --events --max-censored-fraction $simz1LimitText --output $simz1Capacity
if ($LASTEXITCODE -ne 0) { throw 'Auditoria de capacidad rechazada.' }
$simz1Report = Get-Content -LiteralPath $simz1Capacity -Raw -Encoding UTF8 | ConvertFrom-Json
if ($simz1Report.acceptance.status -ne 'screening_pass') { throw 'Criterios incompletos o rechazados.' }
& $simz1Python -B .\python\simz1_operational_report.py --run-dir $simz1Run --iteration 0 --no-plots
if ($LASTEXITCODE -ne 0) { throw 'Informe operativo fallido.' }
```

La prueba conjunta de tamaños, buses y pesados necesita además resolver el
lanzador público y los accesos. Los fixtures `vehicle_dimensions`, `body_spacing`,
`vehicle_picking_dimensions`, `queue_stoplines` y los checks Java cubren cuerpos,
colas 2/5/10, carriles paralelos, rojo/verde, receptor lleno y movimientos
conflictivos sin simular. No sustituirlos por coches para declarar probado un bus.

### Replay SQLite directo y revisión manual de WebGL

Para el histórico `simz1-0dd152dabbc24d1d84d9b738c449cc35`, iteración 0,
reiniciar manualmente el servidor propio con el comando siguiente. **No se
ejecutó aquí.** Usa la fuente existente y el cliente actual; no genera 96 HTML.

```powershell
& .\.venv\Scripts\python.exe -B .\python\serve_simz1_continuous.py --directory .\runtime\simz1-227187-direct\webgl-continuo --port 8793
```

Abrir manualmente `http://127.0.0.1:8793/index.html` y verificar identidad con
`inspect_simz1_client.py --replay-dir .\runtime\simz1-227187-direct\webgl-continuo
--url http://127.0.0.1:8793/index.html` (en una sola línea, usando el Python del
proyecto). Para una corrida pequeña nueva, seguir el bloque 7 de SQLite directo
del procedimiento consolidado, con `$simz1Run` y carpetas nuevas. No reexportar
el histórico para reparar los fallos de fixtures.

La lista manual debe incluir: semáforos y paradas a tres niveles de zoom;
cámara cenital/inclinada y cuatro rotaciones; primer cuerpo antes del cruce;
carro/moto/bus/camión, curva y carriles opuestos; seis campos, halo y ruta;
pausa, seek adelante/atrás, límite de ventana y fin de día. En Avenida Elena/15
Calle usar 28987 s (08:03:07), `getVisualDiagnostics()`, `diagnoseVehicle()` y
`traceVehicle()` conservando IDs, carril, origen de posición y causa. No exigir
cero conflictos históricos ni esconder vehículos para obtener ese número.

Para medir en la pestaña ya abierta, copiar el harness y su llamada desde
PowerShell. El hash esperado procede del inspector de fuentes/HTTP, no del
objeto de la propia pestaña que se quiere verificar:

```powershell
$simz1IdentityRaw = & $simz1Python -B .\python\inspect_simz1_client.py --replay-dir .\runtime\simz1-227187-direct\webgl-continuo --url http://127.0.0.1:8793/index.html
if ($LASTEXITCODE -ne 0) { throw 'Identidad HTTP/fuentes no verificada.' }
$simz1Identity = ($simz1IdentityRaw -join "`n") | ConvertFrom-Json
$simz1BenchmarkArgs = @{expectedBuild=$simz1Identity.current_client_build.source_sha256;times=@(28987,43200,86390);seconds=10} | ConvertTo-Json -Compress
$simz1BenchmarkScript = Get-Content .\scripts\validation\benchmark_simz1_tab.js -Raw -Encoding UTF8
Set-Clipboard ($simz1BenchmarkScript + "`nawait runSimZ1IntegrationBenchmark(" + $simz1BenchmarkArgs + ');')
```

Pegarlo en DevTools, esperar a que termine y copiar los resultados:

```javascript
copy(JSON.stringify(window.simz1IntegrationBenchmark,null,2));
```

Registrar cadencia RAF/FPS y p95 de CPU, render/GPU en Performance, heap, caché,
peticiones pendientes y memoria de proceso. Repetir el mismo recorrido de
ventanas al menos tres veces, con el mismo equipo, resolución, cámara, fuente
y caché; comprobar estabilización después de volver al punto inicial. Comparar
contra una referencia identificada por hash antes de afirmar «sin regresión».
La sonda registra CPU/RAF y memoria disponible, no mide por sí sola tiempo GPU;
ausencia de memoria expuesta significa desconocido. No desactivar capas para
mejorar la comparación. Incidentes apagados no deben producir naranja ni símbolos.

### Criterios para autorizar otra corrida masiva

1. Corregir y repetir las seis suites fallidas, conservando rechazo de datos
   inválidos; compilación y checks del mismo hash de fuentes que se ejecutará.
2. Aprobar una versión nueva de red, restricciones (incluido via-way), contexto
   exterior y gateways; validar cuatro OD dirigidas y 10 rutas testigo, incluidos
   los casos legítimamente imposibles. No modificar red/corridas históricas.
3. Aprobar 10/100/1000 a una iteración y 4/1 hilos con cero transiciones inválidas,
   errores cronológicos, NPE o teletransportes silenciosos; explicar abortos y
   censura con límites acordados, sin FORCE por almacenamiento en modo estricto.
4. Aprobar WebGL real, conteos/identidad/selección y rendimiento con baseline;
   cerrar los fallos de ventana, llegada y reutilización antes de escalar.
5. Validar los tipos/servicios que realmente se incluirán. Una corrida vial B=0
   no certifica transporte público ni el catálogo completo de pesados.
6. Mantener ambos mecanismos de incidentes apagados. La futura autorización de
   accidentes requiere adapter nativo probado: carril único/múltiple, dos IDs,
   tráfico posterior, FIFO/prioridades/señales/restricciones, 1800 s exactos,
   horizonte, 4 hilos, seek y equivalencia apagado. Hoy no está disponible.
7. Revisar recursos y manifest final y obtener autorización explícita del usuario.
   El comando **150000–250000 permanece exclusivamente en el bloque separado
   «Escala futura»**, con guard falso y `--no-incidents`; no es parte de los
   comandos pequeños ni se ejecuta automáticamente.


## Entregables separados para cada corrida (CSV/JSON y PNG)

El empaquetador `python/simz1_report_package.py` usa **exclusivamente** análisis
`completed` de corridas `completed/valid`. No ejecuta MATSim, no reexporta
trayectorias, no mueve las fuentes ni copia los eventos gigantes.

```text
scenarios/zona1/montecarlo/run-mc-verified-<GUID>/
├─ output/                               DATOS CIENTIFICOS NATIVOS (intactos)
├─ run-manifest.json
├─ analysis/it.0/                        ANALISIS CANONICO (intacto)
│  ├─ analysis-manifest.json
│  ├─ analysis-status.json
│  ├─ trips.csv.gz
│  └─ graficas_perfiles/
└─ entregables/
   └─ run-mc-verified-<GUID>/
      ├─ docs/                           CSV, JSON y hashes
      │  ├─ estadisticas_por_perfil_hora.csv
      │  ├─ estadisticas_por_familia_hora.csv
      │  ├─ estadisticas_globales.csv
      │  ├─ categorias_separadas.csv
      │  ├─ categorias_separadas_por_hora.csv
      │  ├─ resumen_perfiles.json
      │  ├─ run-manifest.json
      │  ├─ analysis-manifest.json
      │  ├─ analysis-status.json
      │  ├─ trips.csv.provenance.json
      │  └─ reporte-manifest.json
      └─ graficas/                       PNG
         ├─ carros_por_hora.png
         ├─ motos_por_hora.png
         ├─ comparacion_familias_por_hora.png
         ├─ comparacion_global_perfiles.png
         ├─ completitud_por_hora.png
         └─ duration_distribution.png
```

`run-mc-verified-<GUID>` es un marcador de estructura, no una corrida real.
Para iteraciones posteriores el paquete se llama `<nombre-de-corrida>-it.N`.
El nombre sin sufijo corresponde a la iteración 0, confirmado también en su
`docs/reporte-manifest.json`. La reutilización verifica `run_id`, iteración,
versión compatible del empaquetador, manifiestos, huellas de fuentes y cada archivo
copiado. Un paquete v1 completo se conserva si satisface ese contrato y coincide
byte por byte con las fuentes vigentes; la mera existencia de la carpeta no basta.

La publicación usa staging único por intento y un bloqueo del sistema operativo
por iteración. No elimina bloqueos ajenos ni espera indefinidamente. Antes de
publicar cierra los archivos propios y verifica la copia. Una sustitución conserva
la versión anterior mientras prepara la nueva; un journal permite restaurarla si
falla el renombrado o reanudar si también falla el rollback. Esta secuencia de
renombrados **no es una única operación atómica**. Los errores transitorios de
acceso tienen cuatro intentos como máximo, con esperas de 0,2/0,4/0,8 segundos y
diagnóstico; un destino incompatible no se resuelve repitiendo un reemplazo sobre
un directorio no vacío. Temporales `.pkg-*`, respaldos y diagnósticos se conservan
para investigar los fallos. No borrarlos para forzar una ejecución.

**Empaquetar una corrida explícita sin repetir análisis ni MATSim:**

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
    $run = 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala\scenarios\zona1\montecarlo\run-massive-10it-e0ea36d7601a4548af18c252d4bf5e7e'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_with_analysis.ps1 `
        -PackageOnly -RunDir $run -ExpectedRunId 'simz1-eb9c02f113544d93a82c0954f38dd381'
    $code = $LASTEXITCODE
    if ($code -eq 3) { Write-Warning 'Empaquetado completo; screening review_required.' }
    elseif ($code -ne 0) { throw "Empaquetado incompleto (codigo $code); conservar fuentes y evidencia." }
    else { Write-Host 'Empaquetado completo; screening_pass.' }
}
```

El lanzador `scripts/run_simz1_with_analysis.ps1` empaqueta automáticamente tras
terminar o reutilizar el análisis. `-AnalysisOnly` también crea el paquete.
`-PackageOnly` se limita a validar/copiar los análisis existentes y ejecutar el
screening: no invoca el analizador, Maven, MATSim, exportadores ni el visor.
Requiere `-RunDir`; `-ExpectedRunId` permite comprobar la identidad esperada antes
de escribir. No usa `latest-successful`. Devuelve 0 si todo está completo y pasa
screening, 3 si los paquetes están completos pero la calidad requiere revisión,
y 1 ante un fallo. No modifica `run-manifest.json` para guardar progreso derivado.
En caso de fallo de empaquetado, la corrida MATSim y `analysis/it.N` siguen
intactos. La salida inmediata identifica fase, corrida, iteración y destino;
los fallos conservan tipo de excepción, errno/winerror, traceback, estado del
destino y rutas para reanudar. El resumen separa publicados, reutilizados y
fallidos; falta de cualquier paquete produce un código distinto de cero.
No modificar los archivos del paquete manualmente si se quiere conservar su
verificación de integridad.

En la corrida de diez iteraciones citada, la evidencia inicial conserva el paquete
sin sufijo de la iteración 0 y `.pkg-65facac82cc5` de la iteración 1, ambos con
`run_id=simz1-eb9c02f113544d93a82c0954f38dd381`. El destino `-it.1` no existía
al inspeccionarlo. El fallo original procede de `stage.rename(final)` en
`pack()`, no del `throw` del lanzador; el registro histórico no identifica qué
causó el rechazo de Windows. No hay evidencia para atribuirlo a un destino no
vacío, antivirus o permisos permanentes. Las diez iteraciones tienen
`review_required` por finalización inferior al umbral 0,90; recuperar paquetes
no modifica ese resultado.

Recuperación comprobada el 2026-10-25 en Windows con el entorno `.venv`:
primera ejecución, 9 publicados / 1 reutilizado / 0 fallidos; segunda, 0 publicados /
10 reutilizados / 0 fallidos. Ambas finalizaron con código 3 exclusivamente por
screening. Se ejecutaron 23 regresiones del empaquetador (incluido WinError 5 real
mediante un handle sin permiso de compartir borrado, concurrencia y rollback) y
41 del lanzador, análisis y reparación: todas aprobadas. La comparación completa
antes/después conservó SHA256, tamaño y `mtime_ns` de los 312 archivos nativos y
analíticos, 66.384.928.242 bytes; se leyeron 50 CSV, 70 JSON y 60 PNG de los diez
paquetes. El paquete original de iteración 0 y el staging histórico de iteración 1
quedaron intactos. Evidencia local: `runtime/package-recovery/` contiene
`reproduction.json`, `native-before.json`, `recovery-first.log`,
`recovery-second.log`, `recovery-verification.json` y
`retained-stage-verification.json`. La reproducción confirma la falta de
recuperación ante esa denegación; no identifica el origen del bloqueo histórico.

**Moto ausente:** los PNG sin datos son correctos si la corrida no contiene
identidades efectivas de las tres familias de motocicletas. Las identidades del
catálogo visual no equivalen a generar demanda de motos. El caso de 183154
personas mostrado el 2026-10-23 contiene `38842` etapas completadas y `144312`
censuradas. El promedio de las completadas no representa la duración media de
toda la población. Su resumen nativo menciona 135172 abortos de vehículo sin
atribución a una etapa; estudiar los eventos antes de equipararlos a llegadas,
abortos individuales o censura de horizonte.


<a id="correccion-carro-moto-y-censura-20261023"></a>
## Corrección Carro/Moto y diagnóstico de censura — 2026-10-23

Esta revisión conserva la corrida histórica `simz1-908492b534e641b089028dd893a91bff`.
Sus 183154 etapas, 38842 llegadas y 144312 censuras no se reclasifican a partir
solo del resumen. Los 135172 `unmapped_vehicle_abort` y 9140
`duplicate_terminal_events` suman 144312, pero esa igualdad **no demuestra**
por sí sola la identidad, causa o instante de cada retirada. No se afirma que
se eliminó el 78.8 % de censura ni que los datos nuevos sean calibrados.

### Catálogo y origen explícitos para las próximas corridas

El lanzador anterior omitía `--agent-catalog` y usaba los tres perfiles históricos
Normal/Tortuga/Liebre. Crear las categorías de motos en las gráficas no generaba
motocicletas. El catálogo `agent-types-road-v1.json` permanece intacto: incluye
un perfil pesado cuya restricción de acceso todavía bloquea su ejecución.

El nuevo `agent-types-car-moto-v1.json` habilita únicamente los seis tipos
soportados. Conserva los pesos relativos originales 40/25/10/10, deja el pesado
en cero y excluye el transporte público, ya separado de la demanda. El
normalizador declara denominador 85; **no son porcentajes medidos**:

| Tipo efectivo | Fracción sintética del experimento |
|---|---:|
| Normal / Carro | 47.0588 % |
| Tortuga / Carro Tortuga | 11.7647 % |
| Liebre / Carro liebre | 11.7647 % |
| MotocicletaLenta / Moto tortuga | 7.3529 % |
| Motociclista / Moto | 14.7059 % |
| MotocicletaRapida / Moto Liebre | 7.3529 % |

La suma se conserva mediante el asignador de cuotas determinista existente.
El reparto de motos es 1:2:1. El preflight verifica los seis perfiles, capacidades
de ejecución, permisos de red y presencia de al menos uno por tipo en los
extremos de N. El pequeño fixture de 120 verifica los XML de población/vehículos;
no equivale a una ejecución QSim. Los tipos efectivos, dimensiones, PCU y máximos
no se deducen de colores ni velocidades observadas. En esta implementación las
motos utilizan el modo vial `car` con sus tipos propios; FIFO **no** implementa
filtrado entre coches ni cambios de carril microscópicos.

`temporal_demand.hourly_weights` configura densidades sintéticas por hora,
intersectadas con los horarios permitidos de cada perfil. No se pasa simultáneamente
`--temporal-profile full-day`, que contradecía el contrato del catálogo. La
semilla fijada reproduce el muestreo; omitida en el lanzador, se imprime una nueva.

`uniform-nodes-v1` selecciona un nodo de origen elegible del SCC dirigido para
carros y un enlace saliente. Conserva el muestreador de destinos alcanzables,
concentraciones sintéticas y las restricciones existentes. Evita **la regla**
que redistribuía el 70 % entre un único corredor disponible, sin asegurar que
ningún enlace se sature. Registra conteos por enlace y su fracción máxima.
`legacy-corridors` conserva el comportamiento y RNG históricos. La nueva
política solo es válida para Monte Carlo/OD network: no acredita gateways,
las cuatro clases de tránsito externo ni conectividad cartográfica real.

No se alteraron `Zona1QNodeImpl`, capacidades, señales, rutas históricas,
`stuckTime`, orden FIFO o política de admisión para reducir artificialmente
censuras. `strict-receiver-v1` conserva las esperas cuando el receptor rechaza;
no se cambia a inserciones forzadas ni se activan accidentes. El escenario
nuevo cambia composición y origen: no atribuir su diferencia global a una
sola variable sin un diseño controlado.

### Reconciliación terminal en Java y Python

MATSim 15 emite `PersonEntersVehicle` al abordar, antes de que
`vehicle enters traffic` confirme la entrada desde la cola de espera a la vía.
El exportador antiguo solo registraba la segunda relación. Ahora los
conductores viales se asocian mediante la identidad explícita de abordaje,
incluyendo quienes nunca lograron incorporarse; no se supone que person_id y
vehicle_id coincidan. Los pasajeros de transporte público no reemplazan al
conductor. Dos conductores simultáneos para un vehículo se rechazan.

La limpieza nativa puede emitir `vehicle aborts` y `stuckAndAbort` para la
**misma** etapa e instante. La pareja se registra una vez en
`terminal_reconciliation.paired_terminal_events`. Repetir el mismo tipo sigue
siendo una anomalía; un aborto después de llegada, una llegada después de aborto
y un vehículo sin identidad no se ocultan. La observación es sincronizada en
Java. No se añade una llegada, no se ordenan eventos y no cambian decisiones QSim.

El aborto anterior al horizonte sigue siendo `aborted`; al corte es `censored`.
El esquema CSV de 16 columnas se conserva. El resumen incluye
`terminal_reconciliation_version=2`, la reconciliación y `censoring_breakdown`:
`boarded_without_traffic_entry`, `entered_traffic_without_arrival`,
`left_traffic_without_arrival` y `no_traffic_entry_evidence`. Esta distinción
mejora el diagnóstico pero **no convierte censurados en completados**.

Fuentes primarias inspeccionadas, fijadas a MATSim 15.0:
[AbstractQLink](https://github.com/matsim-org/matsim-libs/blob/15.0/matsim/src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/AbstractQLink.java),
[QLinkImpl](https://github.com/matsim-org/matsim-libs/blob/15.0/matsim/src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/QLinkImpl.java),
[QueueWithBuffer](https://github.com/matsim-org/matsim-libs/blob/15.0/matsim/src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/QueueWithBuffer.java).

### Diagnóstico no destructivo de la corrida existente

`simz1_congestion_audit.py --events` exige una corrida verificada y lee eventos
en streaming. Produce un derivado nuevo con UUID en
`analysis/it.N/diagnostico_trafico/`. Conserva fuentes, contadores históricos y
paquetes ya publicados. Compara conteos reconciliados frente al resumen compacto;
las diferencias quedan explícitas y no sobrescriben las estadísticas originales.

Reporta entradas/salidas por hora, últimas llegadas, orígenes más frecuentes,
pendientes antes del cierre, ocupación observada por enlace, esperas por receptor,
muestras de `StorageAudit` y ciclos candidatos en el grafo de esperas recientes.
Las sondas horarias usan eventos anteriores al límite; el corte se captura antes
de la limpieza. Las lecturas de almacenamiento paralelas conservan el estado
`unknown`; no se vuelven cero ni se vuelve a inspeccionar la cabeza de otra cola.

Los WAIT son intentos, no segundos ni personas distintas. La ocupación por eventos
es número de vehículos, no PCU ni capacidad de almacenamiento. Los ciclos de
espera son candidatos con antigüedad explícita, **no prueba de deadlock**.
Para confirmar saturación física hacen falta sus muestras, configuración,
rutas y persistencia, no solo la existencia de un ciclo o un PNG rojo.

El bloque siguiente conserva el diagnóstico histórico de `run-mc-verified`;
su ruta fue eliminada y no es una instrucción vigente de reapertura
o regeneración. El flujo actual está en [masiva, iteración 9](#replay-masiva-20261025).

```powershell
& {
    Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
    $ErrorActionPreference = 'Stop'
    $run = '.\scenarios\zona1\montecarlo\run-mc-verified-d8fc4f9da2c348f09d5536d63e639b8e'
    & .\.venv\Scripts\python.exe -B .\python\simz1_congestion_audit.py --run-dir $run --iteration 0 --events
    if ($LASTEXITCODE -ne 0) { throw 'Falló el diagnóstico; no modificar las fuentes.' }
    explorer.exe (Join-Path (Resolve-Path $run).Path 'analysis\it.0\diagnostico_trafico')
}
```

### Calidad, gráficas y validación

`completed/valid` acredita integridad nativa, no realismo. El analizador añade
`calidad_resultados.json` y una advertencia a las figuras de perfiles. Los CSV y
medias siguen usando solamente llegadas observadas y no imputan ceros.
El paquete copia este JSON a `docs/` automáticamente, manteniendo los PNG en
`graficas/`. El umbral estándar del informe es 0.90, un criterio de revisión
explícito. El lanzador puede evaluar otro con `-MinCompletionRate`, sin cambiar
la base de ese informe ni suprimir anomalías.

El lanzador conserva todos los resultados antes de exigir `screening_pass`:
seis perfiles efectivos, tasa sobre el umbral y sin anomalías terminales
pendientes. El código 3 de `simz1_result_quality.py --check` significa
`review_required`, **no un fallo de MATSim**. No repetir una masiva para borrar
esta advertencia. Un paquete histórico cuyo fingerprint cambió no se reemplaza
silenciosamente: conserva el paquete y usa el diagnóstico separado.

Pruebas Python de lógica y generación pequeña, sin QSim:

```powershell
& {
    Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
    $ErrorActionPreference = 'Stop'
    Push-Location .\python
    try {
        & ..\.venv\Scripts\python.exe -B -m unittest test_simz1_experiment_repair test_simz1_road_profiles test_simz1_agent_demand test_simz1_profile_statistics test_simz1_report_package
        if ($LASTEXITCODE -ne 0) { throw 'Falló una regresión Python.' }
    } finally { Pop-Location }
}
```

Regresión Java **solo de eventos, sin simulación**; ejecutar localmente con JDK25.
Este procedimiento compila el código del proyecto, no usa una clase anterior
para afirmar validación. Si aparecen clases inconsistentes en `target`, detenerse
y resolver el build antes de simular; no ignorar `NoClassDefFoundError`.

```powershell
& {
    Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
    $ErrorActionPreference = 'Stop'
    & .\mvnw.cmd --batch-mode --no-transfer-progress '-DskipTests' test-compile
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo compilar con JDK25.' }
    & .\mvnw.cmd '-Dexec.classpathScope=test' '-Dexec.mainClass=gt.edu.uvg.sim.zona1.TripReconciliationCheck' exec:java
    if ($LASTEXITCODE -ne 0) { throw 'Falló reconciliación Java.' }
}
```

La regresión alimenta eventos de seis perfiles; cubre abordaje sin entrada,
parejas en ambos órdenes, repetición real, aborto temprano y censura al corte.
No ejecuta `TripTableCheck.main`, que sí incluye iteraciones QSim. La prueba del
navegador, PowerShell y QSim masivo no se da por realizada por estas unidades.
Después de las comprobaciones, ejecutar 120 y 1000 personas en carpetas nuevas,
revisar calidad y solo entonces escalar 150000–250000 con una iteración.


<a id="flota-publica-entre-semana-v2"></a>
## Flota pública entre semana v2 — N vial independiente y tránsito exterior

Esta sección es el contrato vigente del **nuevo escenario experimental**, no una
certificación de las rutas históricas ni de los horarios actuales de operadores.
Los experimentos de seis perfiles sin flota descritos antes permanecen históricos.
No se modifican los resultados de ninguna corrida existente.

### Configuración y cantidades

`scenarios/zona1/transit/weekday-v2/service.json` declara B=120: **80 Transmetro y
40 TuBus**, separados de las N personas Monte Carlo. B no cambia con N=1, N=120 o
N=250000. Los conductores nativos internos tampoco se añaden a N. Una expedición
no es un bus nuevo; el mismo `vehicle_id` reaparece al regresar al dominio.

| Servicio | Buses fijos del escenario | Ventana entre semana |
|---|---:|---|
| Transmetro L1 | 8 | 05:00–20:00 |
| Transmetro L2 | 5 | 05:30–20:00 |
| Transmetro L6 | 12 | 05:00–21:00 |
| Transmetro L7 | 12 | 05:00–21:00 |
| Transmetro L12 | 20 | 04:30–22:00 |
| Transmetro L13 | 10 | 05:00–21:00 |
| Transmetro L18 | 13 | 05:00–21:00 |
| TuBus 104 | 12 | 05:30–19:00 |
| TuBus 105 | 8 | 05:30–19:00 |
| TuBus 802 | 12 | 05:30–19:00 |
| TuBus Ruta 5 | 8 | 05:30–19:00 |

El total y el reparto por línea son **supuestos del experimento**, no mediciones
por línea ni flota simultánea en Zona 1. Se eligieron 80 y 40 dentro de los rangos
aportados. L1/L12/L18 y TuBus siguen las ventanas solicitadas por el usuario;
L2/L6/L7/L13 usan una selección del catálogo fechado existente. Las fuentes públicas
no son concordantes: L12 cierra a 21:00 en el horario secundario consultado,
pero se conserva **22:00 como decisión de escenario**, no como dato reconciliado.
`ServiceDate` es el día modelado; predeterminado viernes 2026-10-23. Rechaza
sábado/domingo; no incluye calendario de festivos ni sugiere que un festivo opere
como día laboral. Cambiar B requiere mantener suma por sistema y servicios coherente.

Las envolventes rígidas asumidas son Transmetro **13.5 × 2.5 m, PCU 3** y TuBus
**12 × 2.5 m, PCU 2.5**; no mediciones de unidades, ni articulación simulada. PCU,
carrocería, separación visual y tolerancia del clic son conceptos distintos. No se
modela demanda de pasajeros: asientos/capacidad son atributos de vehículo, no
pasajeros añadidos a N. Dwell de 25 s es un supuesto de parada.

### Recorridos y cobertura: limitaciones que no se ocultan

`route-bundle.json` conserva orden y procedencia de las relaciones OSM locales
(Transmetro y TuBus R5) y map matching dirigido acotado de trazados municipales
(TuBus 104/105/802). Para 802 se utiliza el orden invertido de vértices congruente
con sentidos y secuencia de paradas del material local. Hay **57 enlaces bus-only
nuevos y 43 nodos de fuente**, escritos solo en la red de cada nueva corrida.
No se cambian capacidad, geometría o velocidad de los enlaces de carro existentes.
Los parámetros de los nuevos enlaces son supuestos declarados, no calibración.

Cuatro sentidos de relaciones contradicen oneway genérico en tres vías OSM:
L6 / way 1056144033; L12 y L13 / way 384746799; R5 / way 1358273948. Sus direcciones
bus-only son **hipótesis explícitas**. La opción `-AcceptTransitRouteAssumptions`
reconoce estas limitaciones, no las convierte en evidencia legal. Sin esa opción
el preflight se detiene antes de generar población. No se cambia `production_enabled`
a true en los catálogos antiguos. El chequeo de giros contempla restricciones
via-node disponibles; no certifica todas las restricciones via-way o datos ausentes.

**El dominio es la red computacional disponible, no un polígono administrativo
aprobado de Zona 1.** No se afirma fidelidad completa del sistema urbano. La ruta
305 se omite porque no hay trazado respaldado en este dominio. Se muestran 62
instancias de paradas de pasajeros respaldadas por fuente (47 Transmetro y 15
TuBus); no se deducen paradas de cada intersección. La 104 no tiene paradas locales
resueltas: puede circular, pero no inventa puntos de abordaje. Las facilidades de
entrada/salida se excluyen de las señales de paradas. Posiciones nativas de dwell
pueden ser proxies en extremos de enlace; no representan bahías verificadas ni
bloqueo de un carril específico. El display conserva la coordenada de fuente y
su procedencia, separada de ese proxy nativo.

Fuentes para contraste (no sustituyen los snapshots locales):
- https://transmetroguatemala.com/horario/ — página secundaria independiente;
  discrepancia L12 indicada arriba.
- https://www.ojoconmipisto.com/transmetro-ubus-rutas-horarios-tarifas/ — cifras de
  flota del sistema completo; no validan cantidades simultáneas dentro de Zona 1.
- https://muniguatealfrente.com/tubus-transporte-municipal-que-conecta-distintas-zonas/
  — material municipal fechado sobre servicios; no programa GTFS exhaustivo.
Los hashes de mapa, red, catálogo y GIS utilizados se fijan en el bundle.

### Entradas, salidas y disponibilidad nativa

El preparador crea `inputs/transit-weekday/` en una carpeta nueva de corrida:
red/carriles derivados, `transitSchedule.xml`, `transitVehicles.xml`, roster,
paradas, política, bundle y manifiesto de flota. `run-manifest.json` incluye hashes
recursivos; el lector rechaza alteraciones e identidades incompatibles.

`SimZ1BoundaryTransitDriver` usa rutas/colas/paradas nativas MATSim 15 dentro de
la red. Entre fragmentos exteriores el bus permanece **fuera del tráfico** durante
1800 s supuestos, o 180 s de giro/terminal local. Son actividades temporales
abstractas: no un recorrido externo puerta a puerta. Se relocaliza únicamente el
vehículo aparcado tras el intervalo; nunca se extrae de una cola activa ni se crea
una segunda unidad para cumplir la frecuencia. No hay LinkEnter/LinkLeave exteriores
ficticios. Para cada salida se usa `max(hora_programada, llegada_real + transferencia)`.
Los retrasos se propagan. Cada nueva expedición debe iniciar antes del cierre;
las que ya circulan pueden terminar después del cierre. Si alcanzan el horizonte
sin terminar, se registran pendientes, no se declaran llegadas.

Los eventos `simz1TransitBoundary` documentan entry, outside_start, terminal_start,
service_finished y cancelación de salidas restantes. Replay y auditoría no dibujan
ni extrapolan posiciones durante las actividades exteriores. Los contadores separan
B configurados, expediciones y buses nativos activos por instante. B permanece visible
fuera del horario sin presentar buses circulando. El total previsto por este bundle
es 6915 pasajes por el dominio, **no 6915 vehículos y no una frecuencia observada**.

### Integración, comandos y pruebas locales

El lanzador principal `scripts/run_simz1_with_analysis.ps1` incorpora el servicio
por defecto y requiere aceptar sus supuestos. `-NoPublicTransport` es únicamente
un control sin buses. Los lanzadores históricos, incluyendo el verificador masivo
anterior, no sustituyen este flujo ni activan flota de forma retroactiva.
`ejecutar_simz1.py` propaga opciones reales del generador; no agregar población
pública al XML de personas Monte Carlo. Las gráficas de carros/motos siguen con N
vial; los documentos conservan metadatos públicos separados.

```powershell
& {
    Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
    $ErrorActionPreference = 'Stop'
    .\.venv\Scripts\python.exe -B -m unittest discover -s .\python -p 'test_simz1_transit_*.py'
    if ($LASTEXITCODE -ne 0) { throw 'Fallo contrato de transporte.' }
    .\.venv\Scripts\python.exe -B -m unittest discover -s .\python -p 'test_simz1_weekday_transit.py'
    if ($LASTEXITCODE -ne 0) { throw 'Fallo flota entre semana.' }
    foreach ($test in @('test_simz1_transit_replay.cjs','test_simz1_transit_stops.cjs',
        'test_simz1_continuous_hud.cjs','test_simz1_continuous_bootstrap.cjs','test_simz1_vehicle_card.cjs')) {
        node (Join-Path '.\python' $test)
        if ($LASTEXITCODE -ne 0) { throw "Fallo $test" }
    }
    .\mvnw.cmd --batch-mode --no-transfer-progress '-DskipTests' test-compile
    if ($LASTEXITCODE -ne 0) { throw 'Fallo compilacion Java (destino bytecode 17); no iniciar QSim.' }
    .\mvnw.cmd '-Dexec.classpathScope=test' '-Dexec.mainClass=gt.edu.uvg.sim.zona1.SimZ1TransitTimingCheck' exec:java
    if ($LASTEXITCODE -ne 0) { throw 'Fallo politica temporal.' }
}
```

Preparación sin QSim: las pruebas usan fixtures y una población temporal mínima,
no corridas masivas. Para comprobar el comando:

```powershell
& {
    Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_with_analysis.ps1 `
        -MinAgents 1 -MaxAgents 1 -Seed 20261023 -Iterations 1 -MinFreeGiB 10 `
        -ServiceDate 2026-10-23 -AcceptTransitRouteAssumptions -DryRun
    if ($LASTEXITCODE -ne 0) { throw 'Preflight fallido.' }
}
```

Solo después de aprobar la compilación, el usuario ejecuta el mismo comando sin
`-DryRun`: N=1 + B=120. Verificar con eventos primer ingreso >= apertura, retorno
sin duplicar ID, paradas nativas, salida y transferencia mínima, cancelaciones
por retraso/cierre y contadores separados. Luego N=120 (seis perfiles) y mayor carga.
No declarar aprobada la flota solo porque su preparación cuenta 120. La compilación
completa Java25, QSim y WebGL en Windows **no se ejecutaron en el entorno de edición**;
la verificación de temporización Java aislada no sustituye esas comprobaciones.
El replay de una corrida anterior no incorpora los buses nuevos: necesita eventos
nuevos y usa el flujo SQLite directo del README principal, fuente `webgl-source/sqlite-source`.


## Arranque y reinicio controlado

Corrección sobre `matsim-guatemala-main(8).zip`, revisión 2026-10-24. No modifica la
red fuente, planes históricos, capacidades, señales, horarios ni tamaño de la flota.

### Causas y correcciones

1. El POM producía major 69 (Java 25); MATSim 15 utiliza Guice 5.1 con ASM 9.2
   embebido. Cambiar una dependencia ASM externa no actualiza la copia reubicada.
   Se compila a Java 17 (major 61), como el destino de MATSim 15. Las llamadas
   `List.getFirst/getLast` y `Thread.threadId` se sustituyeron por accesos equivalentes
   disponibles en 17, sin modificar geometría ni decisiones. El JDK 25 puede compilar
   esos fuentes con `--release 17`; una ejecución completa sigue requiriendo prueba.
2. `ejecutar_simz1.py` invoca `RunZona1Simulation`, pero la instalación de flota fija
   estaba solo en la otra entrada `SimZ1`. Ambas usan ahora `installTransit` común.
   La prueba sintética utiliza ese mismo instalador. Se imprime
   `SIMZ1_TRANSIT_INSTALLED` con N, B, expediciones y motor.
3. `SimZ1RouteSafety.collectExits` rechazaba destinos solo `bus` de los carriles
   preparados, y la admisión utilizaba siempre permisos de carro. La estructura
   admite un modo vial compartido, pero conserva permisos separados: el ruteador
   vial no obtiene salidas de bus. En admisión, únicamente IDs del registro de
   vehículos públicos usan el grafo bus. Prioridad considera accesos bus-only sin
   permitir ignorar rojo, carril, espacio receptor ni conectividad.
4. `exec:exec@simz1-fork` inicia una JVM independiente con classpath del proyecto y
   heap explícito. Evita alojar los hilos de MATSim en el realm del plugin Maven.
   No se interpreta esto como prueba de que toda advertencia Log4j desaparezca.
   `SimZ1FailureReport` conserva causas y mensajes SPI de Guice directamente en
   stderr, incluso cuando falla el formateo de la excepción. La falla se relanza.

Los cambios de admisión por modo son correcciones para nuevas corridas; no alteran
replays históricos. El catálogo y sus supuestos de rutas/intervalos exteriores no
se convierten en evidencia municipal por superar la prueba.

### Flujo y controles

`scripts/simz1_workflow.ps1` ofrece Validate/Clean/Run1000/RunMassive/View.
`Validate` compila clases principales y de pruebas desde cero en target/classes y
target/test-classes, comprueba bytecode/dependencias, ejecuta comprobaciones Java y
un QSim sintético de 600 s. Solo un éxito genera la marca de revisión aprobada.
No borra corridas. La prueba real posterior usa 1000 personas y B=120 separados.

El borrado exige inventario previo, proceso inactivo, raíces permitidas, manifiesto,
ausencia de archivos Git rastreados/fuentes y confirmación. Un cambio entre inventario
y aplicación cancela. No hay borrado recursivo genérico de runtime/output ni borrado
fuera del proyecto. El diario y manifiestos quedan en runtime/maintenance. Los datos
eliminados no se recuperan con ese respaldo mínimo. Las carpetas omitidas se reportan.

**Limpieza y espacio, tarea 2 (2026-10-29; preparada, no ejecutada).**
Se amplía `scripts/maintenance/reset_simz1_runs.py`, reutilizando de
`prune_simz1_runs.py` la validación de rutas/reparse points, archivos rastreados,
procesos y handles de archivos en uso. No se sustituye la prueba de replay que
exige el limpiador selectivo antiguo ni se fabrica una aprobación de 1000.
El plan v2 contiene rutas absolutas, identidad/estado, tamaño lógico, snapshots,
huellas de metadatos, dependencias, exclusiones y decisiones con motivos. No borra.
Aplicar exige el archivo exacto revisado, su SHA256 y `BORRAR CORRIDAS SIMZ1`.
`Clean` conserva ese hash entre revisión y aplicación; un plan v1 se rechaza.

La exclusión obligatoria es
`scenarios/zona1/montecarlo/run-massive-50it-ee85beafe608490b9c184b7b148b86e7`,
identidad `simz1-2f55639a0aee4fa0a70f657aa6b7ec9a`. No existe una opción para
retirarla. Si falta o no coincide su manifiesto, no se permite el reset global.
`--exclude` agrega exclusiones al generar el plan; no permite cambiarlas al aplicar.
Se conserva el cierre transitivo de referencias desde corridas omitidas y
metadatos retenidos. La lectura futura de dependencias queda acotada a JSON/JSONL
y configuraciones nativas de `scenarios/zona1`, `runtime`, `output`, `entregables`,
`docs` y exclusiones explícitas; no decodifica eventos ni SQLite. Los recibos de
`runtime/maintenance` son procedencia histórica, no punteros operativos, y nunca
son candidatos. Metadatos inaccesibles, demasiado grandes, enlaces peligrosos o
identidades duplicadas impiden comprobar seguridad y detienen el plan.

Solo se retiran árboles `run-*` concretos bajo las tres bases permitidas.
Nunca se eliminan las raíces `runtime`, `output`, `scenarios`, escenarios base,
`.git`, `.venv`, fuentes, catálogos o directorios de fixtures/evidencia. Los
derivados externos permanecen y, si necesitan una corrida, la protegen. Un `.js`
solo es candidato dentro de `webgl-source`/`webgl-continuo` con manifiesto completo,
misma identidad, hash del manifiesto nativo y registro explícito del archivo con
SHA256 coincidente. Sin esa prueba se conserva; no se quita la protección global
de extensiones. Clases/JAR y otros archivos fuente siguen excluidos.

Antes de modificar archivos se vuelve a comparar el inventario, exclusiones,
metadatos de dependencias y lista Git; se comprueban procesos y archivos en uso.
Locks, WAL/SHM, rutas ambiguas, enlaces, junctions, hardlinks o comprobaciones
inconclusas impiden eliminar sus candidatos; no se mata ningún proceso. No hay
`rmtree` ni borrado recursivo genérico: cada archivo debe figurar en el snapshot,
y un archivo nuevo impide eliminar su directorio. Los procesos, snapshots del
candidato y dependencias conservadas vuelven a comprobarse durante la aplicación.

Los `latest-*.json` afectados, incluido un puntero de replay, y
`runtime/workflow/trial.json` se respaldan e invalidan **antes** de retirar datos.
Un puntero rastreado o ambiguo conserva su dependencia. Un manifiesto de replay
externo conservado también protege su fuente; no se deja apuntando a datos borrados.
No se elige una corrida alternativa. El diario registra operaciones pendientes,
archivos realmente retirados, candidatos completados, omitidos y `stopped_partial`
con error si algo falla. No reanudar el plan parcialmente aplicado: revisar el
diario y preparar otro inventario. `file-operations.jsonl` conserva intentos y
finalizaciones sin reescribir una lista creciente por cada archivo. Los bytes lógicos eliminados y la diferencia
medida de espacio libre del volumen son campos distintos; escrituras concurrentes,
compresión y el propio diario impiden atribuir exactamente toda diferencia al reset.
Los manifiestos respaldados **no reconstruyen eventos, SQLite ni simulaciones**.

Evidencia del fallo a extraer manualmente, siempre a una carpeta nueva fuera de
los candidatos, sin retirar la protección de los originales:

- Copiar únicamente manifiesto, configuración de la corrida y
  `inputs/freight-weekday/{service,roster,routes}.json`. Registrar ruta original,
  identidad, tamaño, mtime y SHA256 de cada archivo pequeño; fijar un límite total
  de 32 MiB para estas copias y detenerse si se supera.
- De `matsim-run.log` y logs nativos, conservar extractos acotados del primer
  `FREIGHT_RESTRICTED_WINDOW`, su cadena y el cierre, más contexto de inicio/final.
  Limitar cada extracto a 2 MiB y el conjunto a 8 MiB. Guardar límites de líneas o
  bytes, tamaño/mtime del original y hash del extracto; no presentarlo como log
  completo ni atribuirle un hash del original que no se haya calculado.
- Preparar la traza con `inspect_simz1_native_sample.py --failed-diagnostic`,
  vehículo/persona `freight_000005`, ventana inicial 34320–34500, máximo 2000000
  eventos leídos de prefijo y 2000 retenidos. Conservar la procedencia y límites
  que emite; la ampliación a bloqueantes requiere evidencia del enlace/carril
  observado. No copiar el gzip masivo. Esta muestra no sustituye el flujo original
  necesario para estudiar congestión o cierre: la fallida sigue protegida.

Comprobación **manual previa** para 50 iteraciones (0–49), pendiente de medición:

| Componente | Ocupación que debe medirse | Estimación adicional y presupuesto separado |
| --- | --- | --- |
| Salidas nativas | Bytes de eventos, planes, viajes y métricas por iteración comparable; copias finales separadas | Suma para las 50 retenidas más copias finales e inputs; registrar cadencia real de escritura. Una iteración 0 fallida no acredita el tamaño de las otras 49. |
| Análisis | Productos por cada iteración seleccionada | Cantidad de iteraciones analizadas por tamaño comparable, más temporales. No asumir que solo se analiza la 49. |
| Entregables | PNG/CSV/JSON y documentos publicados | Contar las copias físicas adicionales aunque procedan del análisis. |
| SQLite de la 49 | Base final, índices y archivos auxiliares de una exportación comparable | Estimar su tamaño; comparar aparte con `SQLiteBudgetGiB`. Ese límite no es una medida ni una estimación. |
| Staging | Temporales, WAL/SHM y convivencia de versiones durante publicación | Pico simultáneo esperado, contrastado aparte con `ScratchBudgetGiB`; no sumarlo otra vez si ya está incluido en otra estimación. |
| Reserva | Espacio disponible del volumen real de cada destino | Reserva adicional para SO/logs/incertidumbre, explícita y sin contar espacio que una futura limpieza todavía no recuperó. |

Registrar fuente, fecha, corrida, N, iteraciones, cadencia y método de cada dato;
separar tamaño lógico de archivos, ocupación del volumen y bytes disponibles al
usuario. Agrupar destinos por volumen real y exigir, en cada uno, espacio libre
actual mayor o igual que el pico **adicional** estimado más la reserva. La ocupación
existente ya está descontada del libre: no restarla de nuevo. Si faltan tamaños
comparables, declarar `estimación pendiente` y no aprobar capacidad para 50.
No hay base medida en esta tarea para afirmar que 30 GiB basten. Los umbrales
existentes de los lanzadores siguen rechazando insuficiencia; superar uno no
aprueba esta estimación. No se agrega limpieza automática durante la simulación.

Regresiones preparadas en `test_simz1_reset_plan.py` y adaptaciones de limpieza en
`test_simz1_runtime_restart.py`: plan/aplicación, exclusiones, dependencias transitivas,
identidad/snapshot, procesos/locks, rutas peligrosas, pertenencia JS, punteros,
trial y fallo parcial. Sus datos modificables son exclusivamente temporales;
no se ejecutaron. Tampoco se generó un plan, midió espacio, extrajo evidencia ni
eliminó archivo alguno. Los comandos completos se consolidarán en la tarea 4.

La aceptación de 1000 se liga a hashes de fuentes, configuración, manifiesto y calidad.
Exige todos los buses observados, expediciones y evidencia de circulación; solo tener
120 vehículos configurados no basta. No exige completar las 6915 salidas programadas,
pues retrasos y cierres pueden cancelar servicios. La prueba no demuestra capacidad
para 250000 ni calibración empírica. Los presupuestos de disco conservan los guardas
existentes. Un error del análisis no convierte resultados nativos inválidos en válidos.

El modo View utiliza `<run>/webgl-source/sqlite-source`, nunca una selección implícita
por fecha; verifica identidad antes de servir. No reprocesa MATSim ni exporta los 96
HTML históricos. Si quedan parciales, se detiene y los conserva.

### Verificación en el entorno de edición

Se ejecutaron regresiones Python nuevas de bytecode, limpieza segura y control del
escalado; pruebas de preparación weekday y del experimento; tres pruebas de lanzador
con Maven sustituido; comprobaciones Java independientes (temporización y reporte
de causas). La suite histórica de paradas sigue teniendo hashes de catálogo
inconsistentes: no se rebajó esa validación ni se cambiaron fuentes para hacerla pasar.
La compilación Maven completa y QSim NO pudieron ejecutarse aquí: no había caché de
dependencias y la descarga del wrapper falló con UnknownHostException. PowerShell y
WebGL en Windows también requieren comprobación local. Los números y salidas exactas
están en el registro de verificación distribuido con la entrega.

Los lanzadores históricos que exigen JDK 25 o producen HTML paginado se conservan
para trazabilidad, pero no son el flujo recomendado anterior. No combinar sus
opciones de compilación aislada `--release 25` con esta revisión.


<a id="precision-de-turnos-publicos-20261024"></a>
## Precisión de turnos públicos — 2026-10-24

### Causa reproducida

El caso sintético de N=3/B=2 terminó correctamente, pero la preparación del caso
weekday completo fue rechazada por `SimZ1TransitFleet.validate` antes de QSim:
`TRANSIT_INVALID: overlapping duty or insufficient terminal/return time:
ptbus_transmetro_L12_011`.

El generador acumulaba tiempos `float` sin redondear y luego redondeaba cada
salida por separado a seis decimales. El XML recalculaba el final desde la salida
redondeada más el último offset. El siguiente turno todavía provenía del acumulador
sin redondear. En las expediciones d0055/d0056 de ese bus se reproducía:

| Valor del XML anterior | Segundos simulados |
|---|---:|
| Salida d0055 | 40507.638383 |
| Último offset de ruta | 292.473258 |
| Tiempo mínimo de terminal | 180 |
| Disponibilidad después de d0055 | aproximadamente 40980.111641 |
| Salida d0056 | 40980.111640 |
| Diferencia incompatible | aproximadamente 0.000001 |

El validador Java conserva EPS=1e-7. Una prueba Python anterior usaba 1e-5 y por eso
no detectaba el defecto. Reproduciendo el horario del catálogo distribuido se
hallaron 18 pares incompatibles en 9 buses; no eran 18 accidentes ni prueba de
congestión de la red. La prueba independiente en Java con el mismo cálculo `double`
reprodujo el primer bus/pareja y las 18 discrepancias.

### Corrección acotada

- El generador conserva la precisión de seis decimales, con acumulación en
  microsegundos enteros. Las fases iniciales fraccionarias se redondean hacia arriba
  como máximo un microsegundo; los mínimos de transferencia nunca se reducen.
- Roster y XML derivan la llegada programada de la misma suma entera.
- `validate_serialized_timetable` revisa el XML emitido: ventanas de servicio,
  consistencia de llegada y separación de turnos por bus usando EPS=1e-7, igual
  que Java. No modifica los datos recibidos para conseguir que pasen.
- `preflight` serializa en memoria y verifica los 6,915 turnos antes de devolver
  éxito. `attach` repite esa validación antes de publicar los archivos nuevos.
- No se cambia el validador Java, su tolerancia, las rutas, paradas, apertura/cierre,
  flota de 80 Transmetro/40 TuBus, dimensiones, PCU, tiempos mínimos, velocidades
  o política de admisión. No se editan corridas antiguas. La disponibilidad nativa
  sigue dependiendo de la llegada real más su transferencia, no de una llegada
  artificial creada para cumplir el calendario.

Para este catálogo se conservan los 120 buses, 6,915 expediciones e identidades.
El cambio máximo de salida programada respecto a la versión anterior es
aproximadamente un microsegundo. Es una corrección de representación numérica de
una nueva entrada, no una modificación de timestamps de eventos históricos.

### Regresiones y ejecución local

Dos regresiones fallaron antes y pasaron después: comparación de todos los turnos
serializados con el criterio Java y coherencia exacta del final XML/roster. Se
agregan casos de varias fechas entre semana, independencia de N, transferencias
fraccionarias, rechazo de solapamientos de 1 microsegundo/1 milisegundo/1 segundo,
manipulación del final y cierre, y rechazo en preflight/attach sin publicar parciales.
La prueba de roster anterior ahora también utiliza 1e-7, sin ampliar tolerancias.

```powershell
# Prueba focalizada, sin QSim: 26 tests en esta revisión.
.\.venv\Scripts\python.exe -B -m unittest discover -s .\python -p test_simz1_weekday_transit.py -v

# Validate vuelve a registrar el fingerprint de los fuentes actualizados.
# Incluye su caso sintético QSim; no borra corridas.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\simz1_workflow.ps1 -Action Validate

# Solo si Validate pasa; crea una carpeta nueva con N=1000 y B=120.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\simz1_workflow.ps1 -Action Run1000 -Seed 20261023 -ServiceDate 2026-10-23 -AcceptTransitRouteAssumptions
```

No repetir `Clean` para corregir un horario. Conservar `run-1000-746ffdc6187b4487aca3554a364b9dc8`
como intento fallido. Las carpetas que la limpieza omitió por falta de manifiesto
o por `.analysis.lock` no causan este fallo; no se relajan las reglas de borrado.
`RunMassive` continúa bloqueado hasta aprobar la corrida real de 1000 en esta revisión.

En el entorno de edición pasaron 57 pruebas Python focalizadas: 26 weekday, 18 de
arranque/limpieza y 13 del experimento. También se ejecutó una comprobación Java
independiente sobre el XML anterior y corregido (18 discrepancias antes, cero
después). Esa comprobación no carga MATSim ni acredita la circulación real. No se
repitieron Maven completo, QSim, PowerShell ni WebGL aquí; deben verificarse localmente.


<a id="revalidacion-xml-transporte-20261024"></a>
## Revalidación de eventos XML del transporte público — 2026-10-24

### Causa y alcance

La corrida `run-1000-82b4a17c2d11427a9bc58094e68cacc0` alcanzó el final de
la iteración 0 y Maven terminó con código 0. La validación posterior falló en
`TransitEventAudit.consume`: intentaba leer `event['time']` y `event['readyAt']`.
El lector de producción `simz1_run.xml_elements` entrega objetos
`xml.etree.ElementTree.Element`, no diccionarios. En un elemento XML, el índice
selecciona hijos y no atributos. La rama `TransitDriverStarts` con horarios tenía
el mismo defecto. Los anteriores casos de frontera usaban diccionarios y no
reproducían esa entrada de producción.

La función `_event_seconds` ahora usa `event.get(...)`, compatible con ambos
formatos, y rechaza atributos ausentes, no numéricos, negativos o no finitos.
No utiliza valores por defecto que puedan simular una hora real. Permanecen los
controles de identidad, flota separada de N, horarios, disponibilidad exterior,
retirada y secuencia de enlaces. No cambian Java, rutas, turnos, capacidades ni
la física de QSim. Se mantiene la corrección anterior de microsegundos enteros.

### Recuperación controlada, sin ejecutar MATSim

`python/revalidar_simz1.py` acepta una carpeta explícita. Para un manifiesto fallido
exige el error específico de lectura XML, fase `validating`, categoría
`output_validation_error`, `TypeError` y salida natural de proceso con código 0.
No certifica corridas que fallaron durante ejecución o quedaron interrumpidas.

Ejecuta el `validate_outputs` completo sobre una copia en memoria del manifiesto:
identidad y hashes de entradas, XML íntegro, iteraciones finalizadas,
configuración efectiva, red/carriles/señales, eventos, recorridos, viajes y
contadores. Compara hashes de las entradas y todas las salidas nativas antes y
después; un cambio impide publicar. No basta con encontrar `BUILD SUCCESS`.

Sin `--apply` es solo lectura. Con `--apply`, un bloqueo exclusivo evita dos
recuperaciones simultáneas y se guarda una copia exacta del manifiesto en
`validation-history/run-manifest.before-<hash-corto>.json`; la huella completa
se registra en la nueva metadata. Solo después del éxito completo se escribe
atómicamente el manifiesto `completed/valid`, conservando tiempos de ejecución,
semillas y resultado del proceso original. La falla anterior queda respaldada y
descrita en `revalidation`. Si aparece otro defecto real de los datos, no se
omiten verificaciones ni se fuerza el estado a válido. Una segunda aplicación
revalida, sin volver a cambiar el manifiesto ya válido.

No se tocan los punteros `latest-successful`, `latest-attempt` ni el registro de
la prueba de carga. Usa siempre `--run-dir` / `-RunDir` con esta carpeta. La
integridad recuperada no reemplaza el control de calidad del análisis ni el
control previo a una masiva.

### Comandos para este intento existente

Cierra cualquier proceso que todavía escriba en esta carpeta. Copia únicamente
el contenido del bloque, no los prefijos `PS ...>` o `>>` de una consola.

```powershell
& {
    Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
    $ErrorActionPreference = 'Stop'
    $python = (Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe').Path
    $run = (Resolve-Path -LiteralPath '.\scenarios\zona1\montecarlo\run-1000-82b4a17c2d11427a9bc58094e68cacc0').Path

    foreach ($suite in @('test_simz1_transit_events.py', 'test_simz1_transit_xml.py', 'test_simz1_revalidate.py')) {
        & $python -B -m unittest discover -s .\python -p $suite -v
        if ($LASTEXITCODE -ne 0) { throw "Fallo la prueba $suite; no se modifica el manifiesto." }
    }

    & $python -B .\python\revalidar_simz1.py --run-dir $run --apply
    if ($LASTEXITCODE -ne 0) { throw 'Revalidacion detenida. Conserva la carpeta y el traceback completo.' }

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_with_analysis.ps1 -AnalysisOnly -RunDir $run
    if ($LASTEXITCODE -ne 0) { throw 'Revisar analisis/calidad; no volver a ejecutar MATSim para generar graficas.' }

    Write-Host 'CORRIDA EXISTENTE REVALIDADA Y ANALIZADA; MATSIM NO SE REPITIO' -ForegroundColor Green
}
```

Apertura histórica posterior a aquella revalidación. La corrida de 1000 fue
eliminada; para la selección vigente usa [masiva, iteración 9](#replay-masiva-20261025):

```powershell
& {
    Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
    $ErrorActionPreference = 'Stop'
    $run = (Resolve-Path -LiteralPath '.\scenarios\zona1\montecarlo\run-1000-82b4a17c2d11427a9bc58094e68cacc0').Path
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\simz1_workflow.ps1 -Action View -RunDir $run
    if ($LASTEXITCODE -ne 0) { throw 'Fallo la preparacion/apertura del visor; conservar el mensaje completo.' }
}
```

El visor prepara SQLite si falta: eso es procesamiento de los resultados ya
existentes, no una nueva simulación. La publicación de CSV/JSON y PNG conserva
la estructura `entregables/<nombre-de-corrida>/{docs,graficas}`.

### Regresiones

- `test_simz1_transit_xml.py`: XML real de frontera y despacho, equivalencia con
  diccionarios y mappings de solo lectura, reutilización del bus, lectura gzip
  incremental, inmutabilidad, rechazo de datos temporales inválidos y ejecución
  del bucle real de `validate_outputs` con un fixture de eventos públicos.
- `test_simz1_revalidate.py`: recuperación y respaldo exacto, modo lectura,
  idempotencia, bloqueo, salida de proceso inválida, hash cambiado, XML truncado,
  iteraciones incompletas, eventos atrasados y fallo de publicación.
- `Validate` incluye ahora ambos archivos y las regresiones existentes de
  `test_simz1_transit_events.py`, además de las comprobaciones anteriores.

Los fixtures aíslan las comprobaciones de configuración ajenas a su red mínima;
no sustituyen `TransitEventAudit`, el lector XML ni los controles cronológicos y
de movimiento. No constituyen una nueva corrida QSim de Zona 1. La validación de
los eventos reales del usuario se efectúa al ejecutar el comando sobre su disco.


<a id="prioridades-bus-only-20261024"></a>
## Prioridades en enlaces exclusivos de buses: registro y revalidación (2026-10-24)

### Causa y alcance

En el código anterior `UnsignalizedPriority.roadLink` incluía `car` y `bus` para
clasificar aproximaciones y emitir `HEAD/WAIT/GO/CROSS`. Sin embargo,
`Zona1PriorityNetworkFactory.createNetsimNode` emitía la política inicial solo para
`car`. Por eso `PriorityAudit` podía encontrar una decisión válida de un bus sin
su política registrada y rechazarla como si el cruce no fuera elegible.

Caso comunicado: bus `ptbus_transmetro_L12_001`, nodo `410439024`, enlace
`transit_osm_1274975825_0_forward`, siguiente
`transit_osm_1057416031_0_forward`, `HEAD` a 16361 y `readyTime` 16366.
La regresión reproduce el rechazo con el auditor original. Otra comprobación usa
esos IDs y el evento comunicado junto con la red preparada desde el bundle incluido;
esto no equivale a revalidar todos los eventos de la computadora del usuario.

### Corrección sin modificar la física ni los resultados existentes

El emisor Java comparte ahora el predicado `roadLink` y publica políticas tanto
para `car` como para `bus`; identifica la cobertura completa mediante
`policyCoverage=car-bus-v2`. No cambia decisiones, rutas, señales, capacidades,
FIFO, timestamps ni duración de las paradas. Debe recompilarse antes de corridas nuevas.

La compatibilidad histórica reside en `simz1_priority_context.py`. Utiliza entradas
con hash verificado y comprueba que coordenadas, topología, modos y atributos de
prioridad cargados en `output_network.xml.gz` coincidan con la red congelada.
Lee los parámetros efectivos y señales de esa corrida, no el escenario actual.
Reutiliza el clasificador existente y reproduce la elegibilidad car/bus del motor.

La reconstrucción requiere un bus de la flota validada, identificado mediante
`TransitDriverStarts` y el auditor de servicio, y un enlace exclusivo de buses
incluido en su dominio. No sirve para reparar políticas ausentes de carros,
enlaces compartidos o actores reconocidos solo por un prefijo. Tampoco reemplaza
una política emitida contradictoria. Si el emisor declara `car-bus-v2`, una política
faltante se rechaza: no se oculta una nueva regresión como compatibilidad histórica.

Los datos derivados solo existen dentro de la auditoría. No se añaden eventos al
XML. `HEAD`, parada mínima, `GO`, transiciones nativas y `CROSS` conservan todas
sus comprobaciones. La exportación de prioridades usa el mismo contexto; su tabla
incluye `audit_policy_source=native_event` o `verified_run_inputs`.

La salida muestra `native_policy_links`, `reconstructed_bus_policy_links` y
`policy_reconstruction` con hashes de procedencia. Estos conteos son de enlaces,
no de buses ni de viajes. La regla de recuperación de manifiestos sigue limitada
al fallo posterior de lectura XML ya soportado, con proceso terminado naturalmente
con código 0. El fallo de una revalidación no cambia el manifiesto.

### Pruebas

`test_simz1_priority_transit.py` cubre 20 casos: rechazo histórico, coincidencia del
evento L12 con la red del bundle, productor nuevo, actores desconocidos, enlaces
compartidos, nodo incorrecto, señales nativas/OSM, prioridad desactivada, falta de
mezcla calle/avenida, políticas contradictorias, cambios de tiempos/roles,
GO prematuro, ausencia de HEAD/CROSS, hashes alterados y atributos de salida
incompatibles. Incluye el lector gzip/XML y `validate_outputs`, exportación y
revalidación con respaldo exacto y conservación de archivos. Los fixtures de
integración aíslan las verificaciones de escenario ajenas a esta regresión; no
sustituyen el lector de eventos ni las auditorías de prioridad, flota o movimiento.

Se añade una comprobación car/bus/bike al check Java `PriorityContractCheck` y al
lanzador de preparación. La prueba Python del productor comprueba su conexión al
predicado compartido; no acredita ejecución Java/WebGL.

Verificación en el entorno de corrección: 200 pruebas Python focalizadas aprobadas
(12 suites). Una batería ampliada adicional alcanzó el límite de ejecución al
entrar en `test_simz1_run`; esa suite general no se acredita como completada.
No se ejecutaron MATSim, compilación Java, servidores ni una revalidación de los
archivos completos del usuario en este entorno.

### Recuperar la misma corrida sin simular de nuevo

Después de copiar todos los archivos corregidos en el repositorio, pegar este
bloque completo (sin copiar prefijos `PS ...>` ni `>>`):

```powershell
& {
    Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
    $ErrorActionPreference = 'Stop'
    $python = (Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe').Path
    $run = (Resolve-Path -LiteralPath '.\scenarios\zona1\montecarlo\run-1000-82b4a17c2d11427a9bc58094e68cacc0').Path

    foreach ($suite in @('test_simz1_transit_events.py', 'test_simz1_transit_xml.py',
                          'test_simz1_priority.py', 'test_simz1_priority_transit.py',
                          'test_simz1_revalidate.py')) {
        & $python -B -m unittest discover -s .\python -p $suite -v
        if ($LASTEXITCODE -ne 0) { throw "Fallo $suite. No se revalida ni simula." }
    }
    & $python -B .\python\revalidar_simz1.py --run-dir $run --apply
    if ($LASTEXITCODE -ne 0) { throw 'Fallo la revalidacion completa; conservar todos los archivos.' }
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_with_analysis.ps1 -AnalysisOnly -RunDir $run
    if ($LASTEXITCODE -ne 0) { throw 'El analisis o su calidad requieren revision; no repetir MATSim.' }
    Write-Host 'CORRIDA EXISTENTE REVALIDADA Y ANALIZADA' -ForegroundColor Green
}
```

Esperado: pruebas `OK`, `completed_valid_revalidated` o
`already_valid_rechecked_no_metadata_change`, y análisis finalizado solo si su
revisión de calidad también pasa. La publicación respalda el manifiesto anterior.
No cambia `latest-successful` ni autoriza automáticamente una masiva.

Apertura histórica de esa corrida tras su revalidación; la carpeta de 1000
fue eliminada. Para la selección vigente usa [masiva, iteración 9](#replay-masiva-20261025):

```powershell
& {
    Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
    $ErrorActionPreference = 'Stop'
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\simz1_workflow.ps1 -Action View -RunDir '.\scenarios\zona1\montecarlo\run-1000-82b4a17c2d11427a9bc58094e68cacc0' -Port 8793
    if ($LASTEXITCODE -ne 0) { throw 'El visor no pudo abrirse; conservar el mensaje completo.' }
}
```

No hace falta recompilar Java para leer esta corrida ya terminada. Antes de
corridas nuevas, ejecutar `-Action Validate` para compilar el emisor corregido y
sus checks. No ejecutar `Clean` para solucionar un fallo de validación.

# Servicio de carga SimZ1

[Transporte pesado independiente](simz1-freight.md): configuración weekday,
rutas de entrada/salida, conteos separados, validación y replay continuo.
Este servicio nuevo no activa el porcentaje de pesados de las propuestas
históricas descritas arriba: esos catálogos conservan sus bloqueos. Las ventanas
del servicio actual terminan a las 16:00, no a las 16:30 de la propuesta anterior.

**Cierre de carga, tarea 1 (2026-10-29; pruebas no ejecutadas).**
`SimZ1Freight` y `FreightAudit` versión de auditoría 2 distinguen `departure`
(espera de inserción) de `vehicle enters traffic` (inicio de residencia).
`vehicle leaves traffic` termina esa residencia; `arrival` acredita finalización
de ruta y los abortos acreditan un viaje incompleto. Si no hubo salida de tráfico,
un terminal permite comprobar el intervalo desde la entrada, marcado como
`terminal_residence`; no demuestra movimiento físico en ese instante. Sin terminal
ni salida observada, el viaje permanece activo/censurado, nunca se inventa su cierre.
Los límites de ventanas siguen siendo semiabiertos. Un nocturno puede cruzar
medianoche; un diurno retenido desde las 09:32 hasta 86401 atraviesa una restricción.

Las incidencias se conservan por vehículo con primera evidencia, entrada y política;
ni `arrival` ni abortos las borran. La pareja persona/vehículo de aborto al mismo
instante se concilia sin duplicar el viaje; terminales contradictorios, rutas,
identidades o cronologías inválidas siguen produciendo errores estructurales.
El reinicio limpia idempotentemente todos los estados por iteración. Un evento
de actividad posterior no prolonga la residencia de un viaje ya terminado.

Java escribe `ITERS/it.N/N.simz1-freight-audit.csv` y exige aprobación desde
`IterationEnds`, después de `QSim.cleanupSim`/`finishProcessing`, fuera del worker
de eventos. Una infracción o servicio incompleto causa `FREIGHT_NOT_APPROVED` y
salida fallida; no equivale a éxito técnico de toda la corrida. El informe separa
integridad del flujo procesado, cumplimiento horario y resultado del viaje.
En validación Python se retienen resúmenes e incidencias en `results` y
`freight_validation` antes de rechazar el servicio. El runner no publica
`latest-successful` para estos resultados. Los errores estructurales siguen
interrumpiendo la validación estrictamente.

Compatibilidad histórica: las políticas `weekday_overnight_until_05_v2` y
`legacy_horizon_clip_v1` conservan sus ventanas hasta 104400 y 86400,
respectivamente. La nueva auditoría declara su base de residencia en tráfico;
no reescribe snapshots ni atribuye esa semántica a resúmenes históricos sin versión.
La corrida protegida
`run-massive-50it-ee85beafe608490b9c184b7b148b86e7` permanece intacta. Su
`inputs/freight-weekday/roster.json` confirma `freight_000005`, salida planificada
34320 (09:32), ruta `west-east`, entrada `osm_65792798_0_forward`; `service.json`
confirma política nocturna v2. **No se han leído sus eventos masivos**: entrada real,
último movimiento, naturaleza del terminal y bloqueantes siguen pendientes. Los
17664 activos y períodos sin transiciones reportados no quedan resueltos por este cambio.

Regresiones preparadas: `test_simz1_freight_closure.py`, actualización de
`test_simz1_freight.py`/`test_simz1_freight_midnight.py`,
`SimZ1FreightClosureCheck` (handler y gestor paralelo real, dos iteraciones) y
`SimZ1FreightCongestionCheck` (ocho camiones, cuello de botella sintético, cierre
QSim real y rechazo posterior). Incluyen diurno válido/retenido, noche, límites,
espera de inserción, salida de tráfico anterior al terminal, llegada/abortos,
conservación de infracciones, estructuras inválidas y reinicio. El microcaso exige
una carpeta nueva y no usa ni modifica la red productiva. Ninguna regresión fue ejecutada.

Extracción manual preparada reutilizando `inspect_simz1_native_sample.py`:
su modo `--failed-diagnostic` acepta exclusivamente una corrida `failed`, exige
identidad/hash del manifiesto y tamaño comprimido fijados por el operador, y
mantiene procedencia diagnóstica sin afirmar validación del gzip ni de su sufijo.
Para el primer intento: iteración 0, vehículo y persona `freight_000005`, ventana
34320–34500, máximo 2000000 eventos de prefijo y 2000 registros retenidos. La
lectura gzip comienza desde el inicio; esos límites pueden impedir alcanzar la
ventana, en cuyo caso no se publica un resultado parcial. No ampliarlos automáticamente.
Con la entrada/último enlace realmente observado, preparar una segunda ventana
corta usando `--context-link` (máximo 16 enlaces) o IDs explícitos de candidatos;
contrastar cola/carril y rechazo receptor para atribuir un bloqueante. Compartir
enlace no prueba bloqueo. El modo incorpora `--person` para conservar `departure`
anterior a la inserción. Salida siempre en carpeta nueva fuera de la corrida
protegida; ninguna modificación de su manifiesto. `test_inspect_simz1_native_sample.py`
prepara cobertura de identidad, límites, contexto y rechazo de salida dentro del origen.
La lectura histórica, el cierre real y la congestión siguen pendientes; los comandos
completos se consolidarán en la tarea 4.

[Ocupacion de colas, paradas y limites fisicos](simz1-occupancy.md) documenta
las correcciones mixtas, pruebas, procedencia de posiciones y la reserva
nativa por longitud en corredores y pasos cortos. No interpreta `useLanes` como
seguimiento microscopico ni afirma que el criterio global ya este cumplido.
