# Ocupacion de colas y limites fisicos de SimZ1

## Diagnostico

El problema es mixto. MATSim 15 QSim es un modelo de colas: `useLanes=true`
activa subdivisiones seriales y colas terminales, no seguimiento microscopico ni
coordenadas continuas de carrocerias. `SimZ1LanePolicy` es un contrato de decisiones
para un futuro adaptador; no desplaza vehiculos en el QSim instalado.

Las paradas weekday anteriores eran `nonblocking_proxy`: el bus salia de la
cola durante el dwell y los otros vehiculos podian pasar. Dibujar ese bus en el
centro del carril daba una impresion de bloqueo que la simulacion no aplicaba.
Los eventos de parada localizan el servicio en un extremo de cola, no miden el
centro geometrico de una carroceria. El render anterior preservaba ese punto
como centro y excluia el bus de la redistribucion de colas. Su frente podia
invadir la interseccion y coincidir con otros cuerpos.

La admision `strict-receiver-v1` existente conserva WAIT antes del nodo si el
receptor rechaza, incluso despues de stuckTime. No se cambia WAIT por FORCE.
Sin embargo, la prueba nativa `isAcceptingFromUpstream()` comprueba que quede
alguna capacidad, no que quepa toda la siguiente carroceria.

## Cambios activos

- `service.json` declara `stop_occupancy_policy=blocking_queue_v1`. Las paradas
  de pasajeros bloquean su cola QSim durante el dwell. En una cola original
  agregada esto es un supuesto conservador de bloqueo, no una bahia verificada
  ni una asignacion lateral microscopica. Los gateways mantienen dwell cero.
- El generador y el validador Java exigen la procedencia explicita del bloqueo
  agregado. Los snapshots historicos sin esta politica conservan su semantica.
- El margen longitudinal del replay no puede bajarse de 0.10 m (por defecto
  0.10 m con el contrato nuevo; 2 m en historicos). Se utiliza la suma de semilongitudes y el margen para
  limitar el centro del seguidor. El cuerpo mantiene longitud, anchura y escala.
- En una parada bloqueante con un solo carril identificable se estima la huella
  detras del extremo de servicio, antes del limite de conflicto. El bus participa
  en el FIFO de los demas cuerpos. Se conserva el punto nativo por separado en
  `facility_footprint_projection`; no se alteran eventos, tiempos ni Motion_Plan.
- `simz1_blocking_occupancy.py` comprueba salidas de seguidores de la misma cola
  durante un dwell bloqueante. Distingue colas paralelas, vehiculos anteriores,
  empates de tiempo sin orden demostrado e intervalos sin localizacion. La
  validacion nueva incluye `blocking_stop_occupancy` y rechaza una violacion.

La politica nueva `body_before_conflict_proxy_v1` coloca el punto de servicio
nativo en un segmento de la ruta que admite el cuerpo y los margenes de entrada
y salida del cruce. La politica de colas del servicio mueve la subdivision
original/terminal en el snapshot nuevo, para que el extremo de servicio quede
antes del conflicto. Conserva IDs de carriles, movimientos permitidos, carriles
representados, longitud de links y flujo. El preflight weekday registra 46 links
ajustados y 29 de 62 proxies reubicados: 11 interiores por falta de longitud
util y 18 en gateways de entrada/salida sin parada (dos de estos tampoco tienen
longitud suficiente); preserva IDs
de paradas, coordenadas originales y orden. `stop_queue_summary` registra los
cambios y hashes; `simz1:stopProxy` y `stops.json` explican cada traslado. Son
puntos aproximados del modelo, no ubicaciones GIS verificadas. Los snapshots
anteriores conservan su geometria y politica original.

## Reserva nativa por longitud (revision 2026-10-27)

El flujo `run_simz1_with_analysis.ps1` solicita `wholeVehicleReservation=true`
y un hilo QSim. `-LegacyPcuStorage` conserva la comparacion PCU anterior.
Los snapshots existentes no adquieren la politica nueva al abrir el visor.

`SimZ1CorridorOccupancy` agrupa subdivisiones OSM consecutivas sin cruce,
control, cambio de carriles o cambio de nivel. Reserva longitud nativa + 0.10 m
por slot modelado, incluyendo inserciones desde actividades, colas internas,
buffers y paradas. La politica mantiene el FIFO y el calculo de flujo PCU de
MATSim. Los slots no son mediciones laterales. Las fuentes adaptadas de
MATSim 15 `QueueWithBuffer` y `QLinkLanesImpl` conservan su licencia y tienen
hooks sincronos; no se instalan para laboratorios anteriores.

El receptor debe tener espacio para el cuerpo completo antes de admitirlo.
Los movimientos interiores validan los slots contra cada movimiento recorrido,
sin aplicar prematuramente los permisos de salida del final del corredor.
En conexiones demasiado cortas entre cruces, un paso anticipado debe reservar
un receptor suficiente y los nodos intermedios antes de entrar. Se registran
los conectores reales y sus slots; no se amplia la capacidad del enlace corto.
Los bloqueos de cruce conservan tiempo de despeje y evidencia de avance del
cuerpo modelado. No se usa FORCE para superar una restriccion de espacio.
El receptor de un paso corto debe ofrecer un intervalo libre suficiente para
que la parte trasera despeje la zona de conflicto, ademas del cuerpo y la
separacion. Se calcula a partir de la cota del lider y su longitud; no exige
vaciar una calle que todavia tiene espacio. Un fixture de tres buses en un
anillo reproduce y evita el bloqueo artificial de esa condicion anterior.
Una salida de trafico por conectores cortos mantiene la cuota del corredor
anterior hasta el evento nativo de retiro; su geometria no agrega capacidad.
`boundary_exit` identifica fin de presencia en trafico, no prueba por si solo
que una persona haya salido del poligono de Zona 1.

`simz1OccupancyDomain`, `simz1OccupancyReservation`, `simz1OccupancyProgress`
y `simz1OccupancyPassage` identifican la geometria, cuotas y transacciones.
`simz1_occupancy_audit.py` contrasta cuerpos configurados, pertenencia, capacidad,
orden, liberaciones y cobertura de entradas nativas. El resultado por iteracion
`corridor_occupancy` alimenta el replay y el resumen analitico empaquetado.
La ausencia de eventos esperados es un error, no una validacion aprobada.

El paso anticipado exige verde suficiente para recorrer sus colas y despejar
el conflicto. La cota conserva deuda de flujo y dos pasos por cola. Al iniciar
desde actividad, `addFromWait` inserta directamente en el buffer: solo esa cola
inicial identificada explicitamente descuenta su recorrido ya omitido por
MATSim. El fixture de cuatro conectores reproduce una cota imposible de 25 s
ante un verde de 25 s; con la cota correcta de 24 s llegan ambos vehiculos.

`-ShortLinkSignalCoordination derive` deriva offsets para las conexiones cortas
del snapshot nuevo. Mantiene grupos, ciclo y duraciones; registra restricciones,
resultados y hashes en `inputs/signal-coordination.json`, y conserva el control
original en `inputs/signal-control-before-coordination.xml`. Preflight/generacion
y validacion rechazan restricciones no soportadas o un reporte inconsistente.
Es coordinacion sintetica explicita, sin atribuir calibracion empirica; la
admision nativa sigue comprobando deuda y verde en cada paso. `none` conserva
los offsets recibidos. Los dos archivos se incluyen en los entregables.

El replay conserva los eventos y `Motion_Plan`. Con una reserva verificada usa
el frente como referencia para construir el cuerpo, aplica la longitud del
lider + separacion y permite que la parte trasera ocupe una subdivision anterior
del mismo corredor. La salida desde una linea de parada tiene una proyeccion
explicita estimada; no se rotula como coordenada medida. Las posiciones pueden
inspeccionarse junto con `Native_Occupancy`, el enlace nativo y el enlace donde
se dibuja el centro. El margen predeterminado nuevo es 0.10 m; en historicos
permanece 2 m. El contrato de carga nuevo comparte cuerpo fisico/visual de
12 x 2.5 m con TuBus; los archivos historicos mantienen sus dimensiones.

La aproximacion y salida de una parada bloqueante comparten el ancla frontal
estimada del dwell. `facility_boundary_projection` conserva el extremo nativo
verificado y declara la proyeccion. Esto corrige el salto reproducido de
3.435 m en el fixture de parada terminal, sin cambiar tiempos ni posiciones
nativas del archivo. La continuidad hacia el link siguiente exige eventos
contiguos, topologia compatible y fracciones de limite verificadas.

El ancla de un seguidor considera al lider en el instante absoluto en que
empieza su parada, incluso si el lider acaba de terminar el servicio y ya
esta moviendose. La salida conserva el ancla historica del dwell, evitando
saltos al endpoint nominal. Un cambio de corredor conserva la precedencia
demostrada por la transicion nativa mientras la parte trasera sigue ocupando
el anterior; los ordinales de corredores diferentes no ordenan vehiculos
entre si. Las proyecciones declaran su procedencia y conservan Motion_Plan.

Un intervalo auxiliar para reconstruir una transicion no certifica su propia
ancla de espera. El cliente solo marca `resolved_anchor` cuando el intervalo
pertenece a un cierre completo; los otros conservan el rol
`auxiliary_transition`. La interpolacion offline puede depender de una ancla
posterior ya registrada para preservar continuidad: el productor debe resolver
todas esas dependencias, sin confundir el instante de la consulta con el de
la ancla. La prueba conjunta de productor y cliente cubre ambos roles.

Cuando ese lider gira, una separacion valida al inicio del HOLD puede dejar
su esquina trasera invadiendo al seguidor durante el giro. El ancla incorpora
una cota conservadora de la carroceria completa: proyeccion minima del frente
sobre su curva de carril respaldada, menos el radio que contiene toda esquina
trasera, incluidos los margenes configurados. Se calcula antes de dibujar la
espera y permanece fija; no desplaza al seguidor a mitad del HOLD para evitar
un contacto. Solo se aplica con precedencia nativa entre corredores y giro
demostrado. `Visual_Queue_Turn_Clearance` conserva lider, intervalo, recorrido,
radio y procedencia. Es una reconstruccion visual conservadora, no una medicion
de posiciones ni un cambio de eventos, horarios o capacidad QSim.

El contexto SQLite consulta primero los intervalos activos en el instante
solicitado y limita el cierre a dominios viales relacionados. Su cache incluye
instante, topologia y politica de dependencias. Conserva lideres moviendose y
las esperas anteriores necesarias para reconstruir su salida. La interpolacion
tambien puede usar el ancla posterior conocida del mismo intervalo; su cierre
incluye las dependencias registradas de esa ancla. Un intervalo auxiliar no
certifica por si solo una espera. El presupuesto actual permite 512 registros
primarios, 255 enlaces de dependencia, 256 bloques, 16,384 lecturas logicas,
32 MiB comprimidos y 64 MiB decodificados; cada registro
mantiene su limite de 1 MiB. Son limites de recursos, no parametros fisicos.
Las ventanas V8 247 y 337 necesitaron hasta 305 y 393 registros, respectivamente;
la mayor alcanzo 12,568 lecturas, 18.28 MB comprimidos y 51.16 MB decodificados.
Los presupuestos anteriores de 128/256 registros truncaban historia necesaria.
Con los limites actuales, la consulta directa offline de esas ventanas completo
todos los contextos con tiempos de espera validos en 84.68 y 70.05 s en frio,
respectivamente. En el navegador final, la carga HTTP fria de esas mismas
ventanas tomo 194.68 y 186.15 s; el seek mas lento tardo 195.66 s. El probe
posterior a la precarga tomo 1.32 y 1.02 s para sus primeros frames respectivos.
Estas latencias locales no garantizan rendimiento a otra escala.
Un limite excedido o un intervalo invalido conserva su diagnostico y nunca
devuelve una lista parcial marcada como completa. Los costes quedan en
`queue_context.metrics` y en el registro de verificacion; una muestra anterior
no certifica todo el dia.

### Reconstruccion del cuerpo entre carriles y enlaces cortos

La revision del 28 de octubre corrige una aproximacion del replay: el centro
se situaba en un enlace y la orientacion promediaba los ejes vecinos. La cola
de un bus de 13.5 m podia invadir otra aproximacion aunque el recorrido
registrado pasara por un ramal distinto. Ademas, un cambio de dos a cuatro
carriles saltaba entre dos offsets de slot 0 separados 3.108 m.

Ahora el frente estimado conserva su estacion longitudinal y su instante.
La cola se obtiene recorriendo hacia atras las curvas de los carriles y los
enlaces contiguos de la misma expedicion, hasta completar la longitud rigida
configurada. El cuerpo usa la cuerda entre ambos extremos y su punto medio;
no se acorta ni se estrecha. El recorrido puede consultar intervalos anteriores
del cierre validado aunque el frente ya haya cruzado varios enlaces del nuevo
corredor. La estacion longitudinal reportada sigue siendo la referencia
frontal menos media longitud; no equivale a una coordenada central medida.

Cuando dos slots nativos prueban una transicion y sus offsets no coinciden,
una union local comparte el extremo entre ambos. Su extension deriva de la
separacion entre offsets y se limita a la mitad de cada arista disponible.
El conector declara `recorded_native_slot_pair_estimated_lane_join`, los
enlaces, slots, separacion y extensiones; mantiene el ancho vial original.
No se extrapolan un giro en U ni una union que retroceda sobre sus aristas.
`Visual_Body_Reconstruction` conserva el frente, la cola, enlaces, slots y
uniones usados, con `positions_observed: false` y dimensiones conservadas.
Los slots de eventos nativos, las reservas y el caso de un unico carril
efectivo tienen procedencias distintas. Un indice estimado en una via de
varios carriles no se acepta como prueba nativa de la union.
Estas son reconstrucciones geometricas, no nuevas posiciones microscopicas
de QSim. Los eventos, `Native_Occupancy` y `Motion_Plan` permanecen intactos.

`occupancyFrontPath` expone los mismos puntos, vertices y uniones del frente
entre dos estaciones, con procedencia; devuelve `null` si falta soporte.
Permite calcular margenes conservadores del barrido de un lider girando sin
modificar sus tiempos ni desplazar al seguidor a mitad de una espera.

La zona de conflicto usa todo el ancho del carril (`width * 0.5` a cada lado),
igual que el margen nativo. El factor decorativo 0.82 del dibujo de calzadas
ya no reduce esa zona. Esta diferencia causaba un contacto de aproximadamente
6.8 cm en el fixture del giro de L12 junto a L13 detenido.

`node python/test_simz1_lane_body.cjs` comprueba 128 fotogramas de dos pares
reales V7, cambios de enlace a ambos lados de un microsegundo, seek inverso y
en frio y reproduccion a 1x/120x. SAT independiente detecta los contactos
historicos y verifica cero contactos de cuerpos completos y de sus envolventes
longitudinales de 0.10 m en esas muestras. Se preservan las advertencias de
holgura lateral adicional en 34336.8 y alrededor de 72881; no son contactos
fisicos ni incumplimiento de la envolvente longitudinal de 0.10 m. El resultado
acotado y sus coordenadas estan en
`evidence/documentation/simz1-20261027/lane-body-fixtures.json`.

## Alcance de la evidencia

Estas correcciones NO demuestran que todos los cuerpos del escenario mantengan
10 cm en todo instante. El replay mantiene visibles y diagnosticadas las
posiciones incompatibles con cuerpo representable. Los intervalos sin movimiento
o geometria suficiente pueden carecer de cuerpo dibujado: se cuentan como
omisiones y quedan fuera de la cobertura certificada. No se reducen carrocerias
ni se fabrica un carril observado para hacer pasar una prueba.

La reserva por receptor aislado de la revision anterior era experimental.
La revision actual la sustituye por el contrato de corredores anterior. El
valor Java ausente sigue siendo false para conservar configuraciones historicas.

La corrida de diagnostico encontro un receptor vacio de aproximadamente 6.20 m
(`osm_65786237_1_forward`) en una ruta de carga. Una reserva que exige contener
todo el camion en ese dominio impide avanzar. La auditoria detuvo el intento a
las 05:00 con `FREIGHT_RESTRICTED_WINDOW`; sus archivos se conservan. No se
resolvio aumentando capacidad ficticia ni desactivando el control horario.

La primera prueba de esta revision, `run-occupancy-20261027-v1`, encontro otro
caso: `osm_734011350_2_forward` mide 8.52 m y conecta dos conflictos distintos.
No es una subdivision que pueda fusionarse sin control. El fallo de horario
de `freight_000004` se conserva como evidencia; motivo del paso anticipado.
Una corrida fallida y unos fixtures aprobados no acreditan aceptacion global.
El intento `run-occupancy-20261027-v2` llego al cierre del dia con bloqueos
permanentes y un camion pendiente. El control lo rechazo a los 86400 s. Se
conservaron sus eventos; no se publico como corrida valida ni se flexibilizo
la validacion para aceptarlo.
`run-occupancy-20261027-v3` mejoro el flujo, pero tambien dejo un camion
pendiente al horizonte. Ese resultado motivo la comprobacion del intervalo
libre del receptor y se conserva como intento fallido.

## Verificacion reproducible

```powershell
node python/test_simz1_blocking_occupancy.cjs
node python/test_simz1_body_spacing.cjs
node python/test_simz1_queue_stoplines.cjs
node python/test_simz1_facility_positions.cjs
node python/test_simz1_corridor_occupancy.cjs
$env:PYTHONPATH='python'
.\.venv\Scripts\python.exe -B -m unittest test_simz1_blocking_occupancy test_simz1_weekday_transit test_simz1_admission -v
.\.venv\Scripts\python.exe -B -m unittest test_simz1_occupancy_audit test_simz1_occupancy_reporting test_simz1_occupancy_replay test_simz1_physical_contract_20261027 -v
.\.venv\Scripts\python.exe -B python/simz1_blocking_occupancy.py --run-dir scenarios/zona1/montecarlo/run-occupancy-freight-20261026-v3 --output runtime/validation/occupancy-native.json
```

Los fixtures geometricos cubren bus/camion detenido con carro y moto detras,
semaforo, receptor bloqueado, perfil lento, margen minimo y seek repetido.
Los tests existentes cubren varias ventanas de replay continuo, curvas,
contexto incompleto, enlaces cortos y cuerpos no representables. Una prueba
de fixtures no sustituye una medicion microscopica de toda la corrida real.

La implementacion y los comandos del flujo de carga estan en
[simz1-freight.md](simz1-freight.md). La evidencia de esta sesion se registra en
[simz1-verification-20261027.md](simz1-verification-20261027.md).
