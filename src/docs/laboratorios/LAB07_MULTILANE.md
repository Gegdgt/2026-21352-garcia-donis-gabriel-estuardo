# Laboratorio 7: Zona 1 multicarril

Clase `gt.edu.uvg.sim.labs.Lab07MultiLaneZona1`, independiente de Lab05/06.
Conserva la malla A2-A11/C2-C15, sentidos alternados, cierres del Palacio/Plaza,
callejones y puntos de interes del Lab06. La geometria y las secciones son
parametros del escenario solicitado, NO cartografia ni anchos reales verificados.

## Secciones

| Via | Carriles | Capacidad total veh/h | Velocidad nominal |
|---|---:|---:|---:|
| A6 | 4 | 3200 | 45 km/h |
| A7, A9, C12 | 3 | 2400 | 45 km/h |
| Otras avenidas | 2 | 1200 | 30 km/h |
| Calles pares restantes | 2 | 1200 | 30 km/h |
| Calles impares | 1 | 600 | 30 km/h |
| Aproximaciones hospitalarias | Conservan su numero de carriles | 400 por carril | 25 km/h |
| Callejones terminales | 1 | 600 | 30 km/h |

Ancho nominal 3.2 m/carril. `roadWidth`, `laneWidth`, `laneChanging` y
`extremeNight` se exportan en XML. Los carriles MATSim representan el numero
fisico y permiten las salidas compatibles con los sentidos; no se inventan
restricciones exclusivas de giro. QSim mantiene sus velocidades nominales.

## Rebase y colas

El motor visual decide cambios a carriles adyacentes con una ganancia minima de
1.5 m/s. Requiere separacion frontal y posterior, incluyendo reaccion y distancia
de frenado relativa. Las decisiones se reservan secuencialmente contra la
ocupacion actualizada: dos agentes no pueden ocupar el mismo hueco.

Las decisiones se evaluan una vez por segundo. Hay 5 s de espera entre cambios;
no se cambia durante una parada, en los primeros
12 m ni en los ultimos 20 m del enlace. Se conserva el carril al pasar a otro
tramo y se ajusta al reducirse la seccion; si el receptor esta ocupado se espera.
Los vehiculos que entran desde fuera eligen entre los carriles con espacio.
La capacidad total se reparte por carril y las colas se propagan aguas arriba.

El modelo usa cambios discretos de carril, no una integracion de trayectoria
lateral ni un modelo de colisiones en la superficie completa de intersecciones.
Las comprobaciones de seguridad son longitudinales y de aceptacion de huecos;
no es una calibracion MOBIL ni una validacion de seguridad vial real.

La visualizacion centra los marcadores dentro del ancho fisico y dibuja bordes
y separadores. El diametro visual corresponde a 2 m y se adapta al zoom, para
que un marcador no cubra varios carriles al mostrar el mapa completo.
La cache conserva los cambios de carril al buscar o retroceder.
El hover, deslizador, botones y dias periodicos continuos del Lab06 siguen activos.

## Demanda y madrugada

72 000 viajes programados por dia, con el perfil horario estocastico del Lab06.
Este total NO equivale a vehiculos simultaneos. El motor limita la admision a
1500 activos; los restantes esperan fuera del mapa sin eliminarse. `--check`
informa el pico realmente alcanzado y el numero de cambios de carril.
La admision agrupa las esperas por posicion y carril de entrada: un acceso lleno
se comprueba una vez por paso, conservando el orden de llegada entre accesos.
El objetivo de ocupacion pico es 1000-1500; la madrugada mantiene demanda baja.

Por defecto el ciclo diario usa rutas `observed`, calculadas por MATSim con la
resistencia vial exportada. `--routing balanced` sigue disponible como experimento
con puntos intermedios, pero en el escenario previo produjo bloqueo circular:
66 668 agentes pendientes a medianoche. No se recomienda para este perfil.
Los tiempos del modelo visual no sustituyen los de MATSim.
Para poblaciones superiores a 10 000 viajes, los costes de reparto se actualizan
por lotes de 4096 trayectos y se reutilizan arboles de rutas; la conectividad y
los OD se conservan. Esto evita recalcular Dijkstra completo para cada agente.

De 00:00 a 04:00 cada perfil usa un factor reproducible de 1.5-2.0 sobre la
velocidad nominal, con transicion hasta 04:30. En los ejes de 45 km/h supone
67.5-90 km/h deseados. Se suprimen las paradas sinteticas nocturnas, pero no las
actividades explicitas ni el frenado por vehiculos. Las colas de horas pico
reducen velocidades fisicamente; no se fuerzan colores segun la hora.
`--no-aggressive-profiles` desactiva los factores extremos. Son hipotesis de
simulacion, no limites legales ni velocidades medidas en el centro historico.

## Ejecutar desde matsim-guatemala

```powershell
.\mvnw.cmd compile exec:java "-Dexec.mainClass=gt.edu.uvg.sim.labs.Lab07MultiLaneZona1" "-Dexec.args=--iter 10"
.\.venv\Scripts\python.exe python/visualize_network.py --lab 7 --mode microscopic
.\.venv\Scripts\python.exe python/visualize_network.py --lab 7 --mode microscopic --check
.\.venv\Scripts\python.exe -m unittest discover -s python -p 'test_*lane*.py' -v
.\.venv\Scripts\python.exe -m unittest discover -s python -p test_lab07_network.py -v
```

Salida `output/labs/07-multilane-zona1`, XML de red, carriles, planes, eventos,
configuracion y CSV de demanda. Se preservan resultados existentes: usa `--output`
con otra carpeta y `--output-dir` en Python para nuevas ejecuciones. Java acepta
`--agents N` y `--demand perfil.csv`; el perfil y las rutas modifican la ocupacion.
La preparacion del ciclo continuo simula varias cohortes en el mismo motor y
requiere que la red se vacie en un punto de enlace periodico; no elimina colas
persistentes para simular un reinicio.
La preparacion inicial es costosa con 72 000 viajes y ocurre antes de arrancar
el reloj: los 12 minutos corresponden a la reproduccion del dia ya preparado.
