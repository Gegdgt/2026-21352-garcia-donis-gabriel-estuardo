# Laboratorio 8: Zona 1 ampliada y agente persistente

## Estado vigente: deformacion parametrica continua

Zona1BaseNetwork.coordinate(avenue,street) usa u=avenue-2 y v=street-4.
Coordenadas preliminares en metros:

- E=(112*u+1.2*u^2)*(1+0.025*v/14): separacion creciente al este y 2.5% al sur.
- N=-120*v+22*sin(pi*u/10)*exp(-((v-4.5)/2)^2): curvatura suave de hasta 22 m
  concentrada cerca de C8/C9 y las avenidas centrales.

Se rotan E,N -9 grados, luego se convierten a incrementos lon/lat sobre
(-90.5180,14.6460), con escala longitudinal corregida por cos(latitud del pivote).
El pivote permanece fijo. Las funciones son deterministas, sin archivos externos,
arreglos de esquinas, interpolacion bilineal ni tablas STREET_SHIFT/AVENUE_SHIFT.
Se elimino config/zona1-corners.properties.example por obsoleto.

La transformacion MATSim EPSG:4326 -> EPSG:32615 se crea una sola vez por red;
Python sigue usando EPSG:32615 -> EPSG:3857 sin deformacion adicional.
Se mantienen cortes, prioridad, semaforos, pasajes, 166 nodos y 345 enlaces.
Los enlaces entre intersecciones son segmentos rectos que aproximan las curvas
parametricas; no son arcos continuos dentro de cada enlace. La aproximacion
a lon/lat y los parametros de curvatura son de modelado, no una calibracion GIS.

```powershell
.\mvnw.cmd compile exec:java '-Dexec.mainClass=gt.edu.uvg.sim.labs.Lab08Zona1Network'
.\.venv\Scripts\python.exe python/visualize_network.py --lab 8
```

Salida vigente: output/labs/08-zona1-warped. Para repetir, use --output con una
carpeta nueva y --output-dir al visualizarla. Las vias siguen siendo lightgray,
alpha=0.5. Las secciones posteriores son historial, no configuracion vigente.

## Red

Lab08Zona1Network (alias Lab08FocalAgent) delega su mapa a `Zona1BaseNetwork.build(network)`, base obligatoria
para los laboratorios siguientes (ver AGENTS.md). No modifica los mapas anteriores.
Limites: avenidas 2..12 y calles 4..18, inclusive. 166 nodos y 345 enlaces, incluidos
dos pasajes peatonales sin salida. El nucleo vehicular es fuertemente conexo.

La geometria utiliza intervalos desiguales entre avenidas y calles, y desfases
menores. Sigue el mapeo verbal solicitado; no es cartografia GIS verificada.
Se elimina el cruce A7/C7; la calle 7 se corta entre A5 y A9 y la avenida 7 no
atraviesa el nucleo Palacio/Plaza (C5..C8). Se interrumpen ademas C13/A7..A8 y
C14/A8..A9. Los dos pasajes terminales son peatonales, `routingEligible=false`:
no se envian vehiculos persistentes a un nodo sin salida.

Poligonos y marcadores se exportan en los atributos XML `visualArea.*` y
`visualPoi.*`, que Python renderiza automaticamente:

- Palacio Nacional: A6..A8, C5..C6, amarillo institucional.
- Plaza de la Constitucion / Catedral: A6..A8, C6..C8, verde translucido,
  con marcador de Catedral sobre el costado oriental.
- Hospital San Juan de Dios: referencia occidental en A2/C10.
- Parque Colon: bloque representativo oriental A11..A12, C8..C9.

Avenidas 6..9: cuatro carriles, 45 km/h nominales y 3200 veh/h. Otras avenidas:
dos carriles. Calles 9 y 12: tres; las demas: dos. Carriles de 3.8 m y velocidades
locales de 8.33 m/s. Retornos perimetrales garantizan continuidad, con separacion
lateral de sentidos en el dibujo. Los pasajes se dibujan con ancho de 2 m.

Prelacion microscopica: calles transversales paran antes del borde de la avenida
(al menos 1 segundo); la separacion al nodo es semiancho de avenida + 3.25 m, comprueban aproximaciones prioritarias y espacio receptor,
y luego continuan. Las avenidas principales no tienen parada obligatoria en las
esquinas comunes; conservan frenado de seguridad, reduccion por giro y controles
de espacio. Son reglas Python y atributos de red: QSim no interpreta por si solo
estos atributos como semaforos o prioridades. La prueba focal no valida conflictos
simultaneos de una poblacion de multiples agentes.

## Persistencia excepcional

Un agente focal conserva ID, perfil, reloj, distancia y extremos de velocidad.
Java selecciona origen y destino teorico alcanzable, guarda este ultimo como
`theoreticalDestination` y construye una ruta ciclica conectada que pasa por el.
La ruta excede las 24 horas del horizonte QSim: llegar al destino teorico no
termina el viaje ni crea una actividad intermedia que retire el vehiculo.

QSim sigue siendo una simulacion finita: a las 86400 s registra `stuckAndAbort`
al cerrar el viaje activo. En la corrida verificada ocurre exactamente al cierre,
no antes. No debe interpretarse como una llegada ni como un atasco durante el dia.
El ultimo tramo XML incompleto puede producir una advertencia al leer los eventos.

Python normaliza los tramos del recorrido para mantener continuidad y conserva
el mismo vehiculo. Al agotar los tramos, selecciona otro enlace saliente conectado
y libre de los obstaculos declarados. Nunca reinicia sus metricas ni crea otra
cohorte. Si no existe continuacion segura, falla explicitamente; no atraviesa un
obstaculo para aparentar persistencia.

La cache focal avanza la fisica bajo demanda y conserva el historial para volver
atras. No se reinicia ni se pausa a medianoche. Reloj base: 120 segundos simulados
por segundo real (1 hora en 30 segundos), modificable con controles multimedia.
Los saltos temporales hacia zonas aun no calculadas requieren computo. La memoria
del historial crece con el tiempo explorado; no se promete almacenamiento infinito
acotado. La resolucion de consulta es el paso fisico, 0.5 s por defecto.

## Perfiles, fisica y telemetria

Java y Python sortean independientemente Normal, Tortuga o Liebre con probabilidad
1/3 mediante SecureRandom/SystemRandom. El perfil no cambia al continuar el viaje.
Se sortea tambien un factor gaussiano N(1, 0.05), truncado por rechazo a [0.8,1.2].
Multiplica el objetivo nominal (Normal), 1.5 veces el nominal (Liebre) o 3 m/s
constantes respecto de via/horario (Tortuga). No hay garantia matematica de valores
siempre distintos, y todos pueden detenerse a 0 m/s.

Dimensiones: 4.5 x 1.8 m. Python muestra la caja orientada y conserva separacion
longitudinal, frenado y comprobacion conservadora del volumen barrido frente a
objetos estaticos declarados. QSim exporta el tipo fisico pero no ejecuta colisiones
geometricas. No hay otros agentes en este escenario.

Hover: velocidad actual, maxima acumulada, minima acumulada, promedio y tiempo
HH:MM:SS. La cache recupera las metricas del instante seleccionado al retroceder.

Para declarar obstaculos, use un JSON como `[[100,200,105,205]]`, donde cada caja
es [xmin,ymin,xmax,ymax] en metros, y pase `--obstacles archivo.json` a Python.
La ruta se rechaza si su envolvente conservadora intersecta una caja; tambien se
comprueba cada continuacion. No se garantiza proteccion frente a objetos ausentes
del mapa, ni se consideran los sombreados urbanos hitboxes automaticamente.

## Ejecucion

```powershell
.\mvnw.cmd compile exec:java '-Dexec.mainClass=gt.edu.uvg.sim.labs.Lab08FocalAgent'
.\.venv\Scripts\python.exe python/visualize_network.py --lab 8
.\.venv\Scripts\python.exe python/visualize_network.py --lab 8 --check
.\.venv\Scripts\python.exe -m unittest discover -s python -p test_focal_agent.py -v
```

Salida predeterminada: `output/labs/08-zona1-historic`. Para repetir Java use
`--output` con una carpeta nueva; Python acepta `--output-dir` para seleccionarla.
El modo replay reproduce los eventos finitos de Java; la persistencia sin horizonte
se implementa en el modo microscopico predeterminado.

## Validacion

- Java compilo y ejecuto la nueva red; no hubo abortos anteriores al corte de 24 h.
- Python verifico 172801 cuadros hasta 86400 s, con el mismo agente visible y
  activo. Cero viajes terminados es ahora el comportamiento esperado.
- Ocho pruebas focales pasaron: limites/carriles, exportacion, GUI, perfiles,
  dimensiones, obstaculos, metricas y persistencia a ambos lados de medianoche.
- El caso de medianoche verifica cada cuadro, conserva ID, incrementa distancia
  y tiempo, y recupera el estado inicial al retroceder sin regenerar el agente.
- Quince regresiones multicarril existentes pasaron.

## Verificacion del mapa historico (23 de septiembre de 2026)

Compilacion y corrida Java completas. Ocho pruebas focales pasan, incluida la
interfaz, cortes, limites, carriles e hitos. Una prueba adicional verifica parada
obligatoria en calles y ausencia de esa parada en avenidas prioritarias. Chequeo
Python de 172801 cuadros: mismo agente presente hasta las 24 horas; su parada
reglamentaria no se confunde con desaparicion. Vista estatica: target/lab08-historic-map.png.

## Prelacion reforzada (23 de septiembre de 2026)

Salida final validada: `output/labs/08-zona1-right-of-way`. `--lab 8` prioriza
esta carpeta; `--output-dir` sigue permitiendo seleccionar otra corrida.

Calles: frenado hasta la linea situada antes del borde de la avenida, parada
minima de un segundo y comprobacion frontal/lateral. En avenidas de cuatro
carriles el centro se detiene a 10.85 m del nodo (7.6 m de semiancho, 2.25 m de
medio vehiculo y 1 m de margen). No se impone parada donde los cortes del mapa
han eliminado el cruce con la avenida. Durante la aproximacion final no se
cambia de carril, para conservar el carril de salida cuya disponibilidad se evalua.

La liberacion comprueba carril receptor, ocupacion de la zona de interseccion
y aproximaciones prioritarias, incluyendo su posible aceleracion durante el
intervalo necesario para cruzar desde reposo. Es un modelo conservador de zona
nodal, no trayectorias de interseccion calibradas. Una avenida prioritaria no
tiene parada reglamentaria, pero mantiene restricciones fisicas de seguridad.

Verificacion: tres pruebas de prelacion, ocho focales y quince regresiones
multicarril pasaron. La exportacion final completo el chequeo de 172801 cuadros
hasta 86400 s, conservando siempre el unico agente. Las situaciones con otro
vehiculo se ejercitan como pruebas controladas de la comprobacion de conflictos;
no se presentan como validacion de una simulacion urbana multiagente completa.

## Seguimiento y maniobras focales

El controlador longitudinal usa parametros por perfil:

| Perfil | Aceleracion maxima m/s2 | Frenado confortable m/s2 | Separacion temporal s |
|---|---:|---:|---:|
| Normal | 2.0 | 4.0 | 1.5 |
| Tortuga | 0.8 | 3.0 | 2.0 |
| Liebre | 3.0 | 5.0 | 1.0 |

Ante un precedente mas lento, calcula frenado requerido a partir de las velocidades
y distancia libre. Si excede el frenado confortable, aplica frenado de emergencia
proporcional hasta 12 m/s2. Si aun no basta, el limite de desplazamiento espacial
conserva GAP y prevalece sobre ese limite dinamico. Esto evita solapamientos
longitudinales en el modelo, pero puede representar frenado fisicamente extremo;
no es una garantia absoluta de colisiones geometricas en una ciudad real.

Rebase: decision entre carriles adyacentes, margen delantero y trasero con distancia
de frenado, reserva secuencial del hueco y espera minima entre cambios. Umbrales
de ganancia: Normal 1.5, Tortuga 2.0, Liebre 0.8 m/s. Se conserva la prohibicion
durante parking y al aproximarse al cruce. Con un solo agente libre no se fabrica
un rebase innecesario; los conflictos de seguimiento se verifican en pruebas con
vehiculos adicionales controlados.

Parking focal: en entradas elegibles a calles/locales (cada cuarta entrada,
comenzando por la primera), se programa una parada al 55% del enlace si mide al
menos 60 m. El vehiculo conserva su carril y ocupacion, frena antes del punto,
permanece exactamente 3 s en estado parking blanco y vuelve a acelerar sujeto
al espacio delantero. Es estacionamiento sobre el carril, no una bahia lateral
con una maniobra geometrica de entrada/salida. Los giros siguen sujetos a la
prelacion, espacio receptor y velocidad reducida de curva.

Verificacion: tres pruebas nuevas de cinematica, ocho focales, quince multicarril
y tres de prelacion pasan. La comprobacion de 24 h mantiene al agente visible,
con paradas y salidas; target/lab08-kinematics-check.log contiene los resultados.

## Semaforos de tiempo fijo: ciclo aprobado de 80 segundos

La propuesta original sumaba 82 s. El usuario aprobo reducir el verde de calles
a 25 s, conservando verde de avenidas 43 s, amarillos de 4 s y DOS despejes de
2 s. El plan es:

| Intervalo del ciclo | Avenidas | Calles |
|---|---|---|
| [0,43) | Verde | Rojo |
| [43,47) | Amarillo | Rojo |
| [47,49) | Rojo | Rojo |
| [49,74) | Rojo | Verde |
| [74,78) | Rojo | Amarillo |
| [78,80) | Rojo | Rojo |

Rojo total: avenidas 33 s; calles 51 s (incluye los despejes).
Se semaforizan los nodos con aproximaciones vehiculares de ambos ejes, respetando
los cortes existentes. Todos comienzan sincronizados con offset=0; cada enlace
exporta el plan y su grupo, con linea de parada anterior al ancho fisico del cruce.
No se inventan semaforos en pasajes peatonales o nodos sin cruce perpendicular.

El motor Python frena ante rojo/amarillo si aun no ha rebasado la linea. Quien
cruzo la linea en verde conserva permiso para despejar la interseccion. Se mantiene
el espacio receptor y la parada reglamentaria anterior de calles. Los vehiculos
prioritarios que esperan en rojo no anulan el verde perpendicular. Los dos segundos
de despeje son fijos: no constituyen deteccion dinamica de ocupacion ni garantizan
que cualquier vehiculo excepcionalmente lento despeje en dos segundos.

Cuadrados de color muestran las luces por acceso y se recalculan con la misma hora
simulada que vehiculo, hover y reloj, incluso al retroceder. El estado `signal`
identifica la espera ante el semaforo. El ciclo no depende del FPS ni del tiempo
real de preparacion. La escala predeterminada es 120x: un ciclo de 80 s equivale a 0.67 s
reales. La pausa y el deslizador permiten inspeccionar el historial.

Salida validada: `output/labs/08-zona1-signals`, seleccionada primero por `--lab 8`.
Java exporta los atributos del controlador; las detenciones semaforicas se ejecutan
en Python. Esto NO instala el modulo signals de MATSim ni modifica los eventos
QSim mediante un controlador de semaforos nativo. El modo replay conserva los
eventos Java y por tanto no sirve para verificar obediencia semaforica.

```powershell
.\mvnw.cmd compile exec:java '-Dexec.mainClass=gt.edu.uvg.sim.labs.Lab08FocalAgent' '-Dexec.args=--output output/labs/08-zona1-signals'
.\.venv\Scripts\python.exe python/visualize_network.py --lab 8
.\.venv\Scripts\python.exe -m unittest discover -s python -p test_traffic_signals.py -v
```

Verificado: compilacion/exportacion Java, siete pruebas de semaforos (fronteras,
despejes, ausencia de verdes simultaneos, detencion/liberacion, prioridad con rojo,
exportacion y GUI con busquedas temporales) y chequeo de 172801 cuadros hasta
86400 s manteniendo un unico agente visible. Evidencia en target/lab08-signals-*.

## Distribucion GUI vigente (24 de septiembre de 2026)

Leyenda a la izquierda y seis botones debajo: pausa/reanudar, Tiempo real,
1h = 10 min, 1h = 1 min, 1h = 30 s y 2x. El mapa ocupa el centro y la
telemetria por hover el margen derecho. El deslizador queda debajo del mapa
con exactamente su ancho visible, incluso al redimensionar la ventana.
Se conservan las etiquetas de hitos historicos sin cabeceras flotantes.

Las escalas absolutas son 1, 6, 60 y 120 segundos simulados por segundo real.
La predeterminada es 120x. El boton 2x duplica la escala seleccionada (2, 12,
120 o 240x); es un toggle, no acumula duplicaciones. Cambiar de escala conserva
el estado de pausa y liquida el tiempo anterior sin saltos de reloj.

El dt fisico sigue expresado en segundos simulados y no cambia: aceleraciones,
paradas de tres segundos y ciclos semaforicos mantienen su duracion simulada.
Reloj, luces, posiciones y hover consultan la misma linea temporal. Se interpolan
posicion y velocidad entre muestras del mismo enlace/carril/estado para observar
movimientos fluidos a 1x; en transiciones discretas se conserva la muestra previa.
La velocidad real alcanzable depende de la capacidad de calculo y renderizado.

Validacion automatizada con backend Agg: clicks, pausa, escalas, busquedas,
interpolacion y layout en ventanas de 16x12 y 9x7 pulgadas. No sustituye una
prueba manual del backend grafico de escritorio. Capturas en
`target/lab08-ui-layout.png` y `target/lab08-ui-layout-small.png`.

## Agente y semaforos: revision visual

Marcador focal de 100 puntos cuadrados; vias ensanchadas solo en el dibujo.
La hitbox fisica conserva 4.5 x 1.8 m. El color depende siempre de la velocidad:
cero blanco (incluido parking), hasta 30 naranja, 60 cyan, 100 morado, menos
 de 150 rojo; desde 150 alterna rojo/amarillo por cuadro mostrado.
Los semaforos usan cuatro colecciones compartidas: caja oscura y tres luces
verticales, una activa y dos grises. Su fase usa el mismo reloj del slider.
No se crean nuevos artistas en cada actualizacion.

Medicion local Agg: 292 accesos, 2000 actualizaciones de luces, 0.96 ms promedio
por actualizacion (no incluye renderizado completo ni garantiza FPS de escritorio).
Captura: target/lab08-visual-signals.png.

## Reloj continuo a 120x

Al iniciar Lab08, 30 segundos reales representan 3600 segundos simulados y
720 segundos reales representan un dia completo. La escala usa tiempo de pared,
no el numero de cuadros. Pausa o escalas elegidas manualmente alteran esa relacion.
El panel superior izquierdo, fuera del mapa, muestra Hora: HH:MM:SS y el dia.
El reloj absoluto y la cache persistente no se reinician al cruzar medianoche:
solo la representacion de hora usa modulo 86400. El agente conserva identidad,
trayectoria y metricas; al terminar una ruta continua hacia un nuevo destino.

Validacion: 27 pruebas de reloj, controles, demanda diaria, agente focal y
semaforos; incluye persistencia antes/despues de 86400 s y equivalencia 30 s/h.
La duracion indicada excluye preparacion y pausas; el FPS depende del equipo.

## Preparacion GIS (1 de octubre de 2026)

`visualize_network.py` importa contextily como ctx y Transformer de pyproj.
Las dependencias estan declaradas en requirements.txt. Lab08 configura la
proyeccion antes de dibujar; los laboratorios previos conservan coordenadas locales.

`map_to_web_mercator(points, local_bounds)` recibe pares XY o matrices (..., 2)
y limites locales (xmin, ymin, xmax, ymax). El rectangulo se calcula una sola vez
con TODOS los nodos y se ajusta a oeste -90.518, este -90.506, sur 14.634,
norte 14.646, proyectados con EPSG:4326 -> EPSG:3857 y always_xy=True.
Se asume norte = +Y, como en Zona1BaseNetwork. Rechaza valores no finitos y
rectangulos degenerados. No recorta offsets de aceras o carriles.

Vias, agentes, hitboxes, obstaculos, semaforos y referencias pasan por la misma
funcion al dibujar. La fisica, rutas y distancias originales no se modifican.
Esto es un ajuste afin aproximado al bounding box solicitado, no una conversion
geodesica de un CRS local conocido ni una alineacion topografica verificada.
No debe reaplicarse a datos que ya esten en EPSG:3857.

Para incorporar teselas o un raster local, tras dibujar las capas y antes de
iniciar la animacion, llamar una sola vez a `add_zona1_basemap(ax, source=...)`.
El helper exige ejes proyectados, conserva su extension y usa zorder=-10.
No descarga teselas automaticamente ni las solicita en cada cuadro.
Documentacion: https://contextily.readthedocs.io/en/latest/reference.html

Validacion: 40 pruebas aprobadas, incluyendo esquinas, centro, orientacion,
valores invalidos, capas, hover, controles, semaforos y agente persistente.
La llamada al proveedor se verifico con mock; no se descargaron teselas reales.

## Fondo CartoDB DarkMatter

Lab08 llama a add_zona1_basemap durante el dibujo inicial, con el proveedor
ctx.providers.CartoDB.DarkMatter, zoom 16 y zorder 0. Poligonos: zorder 1,
alpha 0.4; vias grises translucidas: 2; semaforos: 3; agente: 4.
Se conservan los limites del mapa y los ejes de controles, slider y telemetria.
No se descargan teselas durante las actualizaciones temporales.

CARTO requiere una clave propia: https://carto.com/basemaps/apikey/ .
Configurar CARTO_API_KEY en el entorno antes de ejecutar el visualizador.
Sin clave o ante fallo de red, permanece el fondo oscuro local y los controles
siguen disponibles. La clave no se guarda en el repositorio ni se imprime.

La prueba de descarga sin clave devolvio imagenes API KEY REQUIRED, no cartografia.
Por ello la integracion autenticada esta pendiente de una clave del usuario.
Las pruebas automatizadas verifican proveedor, zoom, capas, limites, fallos de red
y preservacion de los controles sin depender de teselas en Internet.

## URL publica y escala uniforme (revision vigente)

Se usa exactamente https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png,
con respaldo https://tile.openstreetmap.org/{z}/{x}/{y}.png. Ya no se consulta
CARTO_API_KEY ni ctx.providers.CartoDB.DarkMatter. La URL directa devuelve una
imagen API KEY REQUIRED con HTTP 200: se identifica la huella RGB de esa imagen
verificada y se descarta antes de cargar OSM. La huella solo reconoce esa version
del aviso. Se conservan atribucion, User-Agent propio y cache local persistente
(target/map-tile-cache), sin descargas durante cada frame.

Descarga verificada: OpenStreetMap mostro cartografia real, sin aviso de API.
La imagen Carto no es cartografia y no se considera una descarga exitosa de mapa.

El generador tiene A2_C4=(0,1765) y A2_C18=(0,0). El ancla norte es A2_C4,
no el origen sur. Se aplica scale_x=scale_y=min(ancho destino/ancho local,
alto destino/alto local), conservando proporciones y direcciones originales.
El ancla se ubica exactamente en (-90.518,14.646), coordenada aproximada provista.
Esto deja margen en uno de los ejes: no deforma la red para llenar el rectangulo.

La captura confirma que la red sintetica NO coincide exactamente con las calles
reales, que ademas tienen otra orientacion y distancias. No se afirma calibracion
GIS precisa: requiere coordenadas verificadas de intersecciones y ajuste del mapa
base comun, no solo un bounding box. La fisica y la topologia siguen intactas.

Validacion: py_compile, 25 pruebas (proyeccion, fallback HTTP/imagen de error,
controles, agente persistente, semaforos) y descarga real con revision de captura.
Captura target/lab08-darkmatter.png contiene el respaldo OSM, no DarkMatter.
Politica de identificacion/cache: https://operations.osmfoundation.org/policies/tiles/

## Ejecutable unificado y geometria irregular v2

El punto de entrada es `gt.edu.uvg.sim.labs.Lab08Zona1Network`.
Lab08FocalAgent queda como alias compatible. Antes no existia una clase con
el nombre Lab08Zona1Network. El main construye mediante Zona1BaseNetwork,
verifica enlaces vehiculares disponibles y diagnostica extremos ausentes.
Las rutas del agente excluyen pasajes peatonales.

Zona1BaseNetwork v2 conserva A2..12/C4..18, interrupciones y semaforos. Aplica
rotacion -9 grados, cizallamiento 0.012 y offsets explicitos por calle/avenida,
ademas de las distancias desiguales originales. Hitos y pasajes reciben la misma
orientacion. Son parametros aproximados de modelado, no puntos GIS levantados.

El XML exporta visualProjection=local-metric-north-up y origen local/geografico.
Python lee esos metadatos: map_to_web_mercator conserva angulos y longitudes
relativas usando una escala Mercator local uniforme (1/cos(latitud)). No vuelve
a encajar ni rotar la red segun su bounding box. Exportaciones antiguas conservan
el mecanismo previo. La alineacion precisa con todas las calles reales sigue
requiriendo puntos de control geograficos verificados.

Verificado: Maven compile y ejecucion real de Lab08Zona1Network hasta 86400 s
(una iteracion, 0, sin cambiar la configuracion anterior), XML de red/eventos,
26 pruebas Python y captura sobre OSM. Salida: output/labs/08-zona1-irregular,
seleccionada primero por --lab 8. Log: target/lab08-irregular-run.log.
Capturas: target/lab08-irregular.png y target/lab08-irregular-small.png.

```powershell
.\mvnw.cmd compile exec:java '-Dexec.mainClass=gt.edu.uvg.sim.labs.Lab08Zona1Network' '-Dexec.args=--output output/labs/08-zona1-new-run'
.\.venv\Scripts\python.exe python/visualize_network.py --lab 8
```

Cada corrida Java requiere una carpeta de salida nueva; no sobrescribe resultados
previos. Para ver otra corrida, usar --output-dir con su carpeta.

## Calibracion asimetrica y argumentos tolerantes (configuracion vigente)

Java acepta --output y ruta como dos argumentos, o como un solo argumento
"--output ruta". Se divide solo en el primer separador para conservar espacios
en nombres de carpeta; tambien se retiran comillas exteriores simples o dobles.
Opciones desconocidas y rutas vacias producen un error claro. No se sobrescriben
corridas anteriores. Validacion: Maven test-compile y 10 casos ejecutados con
Lab08ArgumentsCheck, incluidos espacios, comillas y argumentos invalidos.

Todas las lineas y superficies viales se dibujan en negro #000000, alpha=1,
zorder=2; grosor principal 5+2*carriles puntos (5 para enlaces sin lane_width).
Agente, luces, hitos y controles mantienen sus colores.

map_to_web_mercator usa ahora scale_x y scale_y independientes: extension
Mercator destino dividida por extension local en cada eje. El minimo XY local
coincide con (-90.518,14.634) y el maximo con (-90.506,14.646). Se consideran
todos los nodos; los offsets de carriles/aceras pueden sobrepasar esos limites.
El ancla y la escala uniforme de versiones anteriores ya no gobiernan el dibujo,
incluso para XML v2. La fisica conserva sus coordenadas y distancias originales.
Esta deformacion encuadra el bounding box exactamente, pero cambia proporciones
y angulos y no garantiza coincidencia con cada calle real. Sustituye las reglas
de escala uniforme documentadas en las secciones historicas anteriores.

Validacion Python: compilacion y 10 pruebas de proyeccion, limites, estilos,
fallback, hover y controles. No se necesita regenerar XML por este cambio visual.
