# Visualización del tráfico

Desde `matsim-guatemala`, con las dependencias del entorno virtual:

```powershell
.\.venv\Scripts\python.exe python/visualize_network.py --lab 5 --mode microscopic
```

`microscopic` es el modo predeterminado. Usa perfiles reproducibles mediante
SHA-256 del ID, velocidades derivadas de `freespeed`, carriles de `permlanes`,
aceleración de 2 m/s², frenado cómodo de 3 m/s² y separación longitudinal
mínima de 8 m. La capacidad XML se interpreta como vehículos/hora; limita
las salidas del enlace, mientras su longitud limita el espacio para la cola.
Un enlace receptor ocupado retiene vehículos en el anterior. No se permiten
cambios de carril durante un tramo. El límite de seguridad tiene prioridad
sobre el frenado cómodo cuando ambos son incompatibles. El controlador reactivo
usa la diferencia de velocidad con el precedente y el error de distancia
respecto a `8 m + 1,2 s × velocidad`. Así busca igualar su velocidad y recuperar
el intervalo de seguimiento, en lugar de mantener siempre la velocidad libre.
Se mantienen el límite de desplazamiento y la reserva de espacio al entrar
en otro enlace. Es una aproximación longitudinal, no un IDM calibrado.

El reloj avanza en pasos de 0,2 s. Los perfiles lento, estándar y rápido usan
respectivamente 70 %, 88 % y 100 % de la velocidad libre. No se imponen
60 km/h a una calle cuyo límite es menor. El perfil determina la velocidad
deseada, pero el color se calcula nuevamente en cada cuadro con `Sample.speed`:

| Velocidad instantánea | Color |
| --- | --- |
| 0 km/h, incluido parking | Blanco `#FFFFFF` |
| Mayor que 0 y hasta 30 km/h | Naranja `#FF6600` |
| Mayor que 30 y hasta 60 km/h | Celeste `#00BFFF` |
| Mayor que 60 y hasta 100 km/h | Morado `#8A2BE2` |
| Mayor que 100 y menor que 150 km/h | Rojo `#FF0000` |
| 150 km/h o más | Alterna rojo y amarillo `#FFFF00` por cuadro |

Los rangos también cubren velocidades fraccionarias (por ejemplo, 0,5 o
30,5 km/h). Se considera cero una tolerancia numérica de 0,000001 m/s.
No hay una excepción amarilla para parking: su velocidad cero produce blanco.
El parpadeo depende del índice del cuadro, no de la hora del sistema: se
repite de forma determinista y se detiene al bajar de 150 km/h.

La selección de perfiles asigna una probabilidad del 4 % a un factor agresivo
de 1,65 y del 1 % a un factor excepcional de 2,15, exclusivamente en enlaces
de bypass (ambos nodos `B_` y `freespeed >= 20 m/s`). Son probabilidades de
asignación, no cuotas garantizadas de vehículos que alcancen esas velocidades.
El tráfico y las distancias de frenado siguen limitando el avance; nunca se
fuerza el rojo si el agente realmente circula despacio. En las demás calles
se conservan los factores normales de 0,70/0,88/1,00. Estas infracciones son
**sintéticas** y se desactivan con `--no-aggressive-profiles`.

Al continuar por enlaces conectados se conserva la velocidad, con anticipación
al límite de la vía siguiente. Los giros mayores de 60 grados reducen la
velocidad objetivo a un máximo de 8,33 m/s multiplicado por el perfil. Las
actividades, colas y tiempos de liberación XML siguen exigiendo frenado; un
nodo geométrico de una vía libre ya no obliga a frenar hasta cero. El recorte
del último paso de distancia de un enlace tampoco reduce artificialmente
la velocidad que se transmite al siguiente.

La reproducción predeterminada es 10×: un paso de 0,2 s solicita un cuadro
cada 20 ms. `--playback-speed 1` solicita tiempo real y `--playback-speed 20`
duplica la velocidad visual predeterminada, sin cambiar velocidades físicas
ni colores. La cadencia efectiva depende del equipo. Una sola colección de
puntos actualiza todos los vehículos para reducir el coste del renderizado.
Cabecera, mapa y leyenda ocupan tres ejes separados: los textos no se dibujan
encima de los enlaces. La leyenda incluye los nuevos umbrales y el parpadeo.

## Inspector interactivo de agentes

Pasa el cursor sobre un vehículo para ver su ID y telemetría en el panel
derecho, separado del mapa. La selección usa un radio de 10 píxeles de
pantalla; funciona independientemente de la escala del mapa y del zoom.
Los datos se actualizan con cada cuadro, incluso sin mover el cursor. Si el
agente se aleja del cursor, sale del mapa o se retira el cursor, el panel vuelve
a «Seleccione un agente con el cursor...». No es una selección permanente.

- **Tiempo transcurrido:** segundos desde la primera aparición del agente en
  esta reproducción; en modo microscópico empieza al ser admitido en la red.
- **Velocidad actual:** velocidad del cuadro, en km/h, usada también para el
  color. Cuando el espacio disponible impide avanzar, se informa cero en el
  mismo cuadro; no se reutiliza la velocidad libre o de transición del motor.
- **Velocidad promedio:** distancia acumulada sobre los enlaces dividida por
  tiempo transcurrido, convertida a km/h. Incluye las colas y el parking.
- **Velocidad mínima:** mínimo de las velocidades registradas desde la primera
  aparición, incluyendo cero durante arranque o detenciones. Por eso es normal
  que un agente microscópico conserve un mínimo de 0 km/h durante su recorrido.

Las métricas abarcan la secuencia de viajes y actividades de cada agente; no
se reinician al cambiar de enlace o al aparcar. Se reinician al repetir la
animación. En modo `replay` se calculan con las distancias e intervalos XML
interpolados. No son medidas GPS ni resultados adicionales de MATSim.

La telemetría y el color reciben el mismo `Sample`. El estado `queued` implica
velocidad cero (blanco); `following` identifica seguimiento lento hasta
30 km/h (naranja). Seguir a otro vehículo a velocidad alta con espacio suficiente
no se etiqueta como una cola detenida ni se recolorea artificialmente.

## Distribución de rutas

`--routing balanced` es el valor predeterminado en modo microscópico. El módulo
`traffic_routing.py` reconstruye recorridos sintéticos sobre los enlaces reales,
conservando los enlaces de origen/destino y las duraciones de las actividades.
Distribuye puntos intermedios entre grid, diagonales, rotonda y bypass; los
costos penalizan enlaces ya asignados y recorridos periféricos. Dijkstra respeta
la dirección de los enlaces y evita giros inmediatos de 180 grados. Si no
encuentra un desvío entre los candidatos, conserva el recorrido y lo informa.
Esto busca mayor cobertura, sin garantizar densidad idéntica en toda la ciudad.

Los nuevos recorridos y horarios llevan `source="synthetic-route"`. El resumen
de consola compara enlaces utilizados y kilómetros por zona antes/después.
Usa `--routing observed` para mantener la secuencia de enlaces registrada.
No se editan Java, la población ni los archivos de salida de MATSim.

## Eventos y actividades

Los pares `vehicle enters traffic`/`left link`, `entered link`/`left link` y
`entered link`/`vehicle leaves traffic` reconstruyen cada recorrido. Se
asocia el vehículo al conductor; los enlaces repetidos se emparejan por orden
de eventos. Los registros incompletos se omiten con una advertencia.

El parking XML conserva su duración `actend - actstart`: cuando es 3 s se
muestra blanco e inmóvil durante exactamente 15 pasos de 0,2 s. La posición
se infiere de la llegada al enlace, o de la coordenada de actividad si existe;
estos eventos no proporcionan una trayectoria GPS microscópica. En el modo
visual el vehículo conserva su posición efectiva al comenzar la actividad.

Para representar paradas internas, una parte de los perfiles añade actividades
**sintéticas**, de 3 s, al 55 % de algunos enlaces internos. Están identificadas
como `source="synthetic"` en los estados y el registro del motor. No modifican
el XML, la población ni los resultados de MATSim. Desactívalas con
`--no-synthetic-stops`.

## Reloj visual frente al reloj de MATSim

La dinámica añadida puede retrasar la entrada, salida y actividad respecto al
XML. Con `--routing observed`, los tiempos XML son cotas mínimas. Con rutas
balanceadas se conservan las horas iniciales de salida y se calculan tiempos
de viaje nuevos, ajustados después por la dinámica del tráfico. La demanda
espera fuera del mapa si no hay espacio seguro en su posición de aparición.
No es posible imponer simultáneamente tiempos XML exactos y bloqueos nuevos.

Para conservar los intervalos temporales originales:

```powershell
.\.venv\Scripts\python.exe python/visualize_network.py --lab 5 --mode replay
```

Ese modo interpola posiciones dentro del enlace y reproduce las actividades
observadas; utiliza rutas originales automáticamente, no añade paradas ni
perfiles agresivos y no promete separación física entre vehículos.
El modelo visual tampoco reproduce prioridades de cruce, conflictos entre
carriles que se intersectan ni dinámica física calibrada: la garantía de
separación es longitudinal por carril. El tamaño del marcador en pantalla no
es la longitud física del vehículo, por lo que puntos cercanos pueden tocarse
al alejar el zoom. Un bloqueo circular que no se resuelve se informa como error.

## Elegir y verificar resultados

El Lab 5 mantiene la preferencia existente por `05-mini-city-directed`.
Para elegir otra salida sin ambigüedad:

```powershell
.\.venv\Scripts\python.exe python/visualize_network.py --lab 5 --output-dir output/labs/05-mini-city --iter 10
.\.venv\Scripts\python.exe python/visualize_network.py --lab 5 --check
.\.venv\Scripts\python.exe -m unittest discover -s python -p test_microscopic_traffic.py -v
```

Sin `--iter` se carga `output_events.xml.gz`; con `--iter N` se exige el archivo
de esa iteración. `--check` recorre todos los cuadros sin ventana, comprueba
separación longitudinal, límites de velocidad y muestra el número de agentes
y actividades, la velocidad máxima y las muestras de cada color.
La animación genera cuadros progresivamente, sin guardar todas las posiciones
de toda la simulación en memoria.
