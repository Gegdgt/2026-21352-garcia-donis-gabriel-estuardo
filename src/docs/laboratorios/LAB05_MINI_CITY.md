# Laboratorio 5: Mini-ciudad

Clase: `gt.edu.uvg.sim.labs.Lab05MiniCityNetwork` (MATSim 15, Java 25).

## Geometria y circulacion

- 10 x 10 manzanas: cruces desde 0 hasta 10, separados 1000 m. X crece al este,
  Y al norte. Filas pares al este, impares al oeste; columnas pares al norte,
  impares al sur. Locales: 8.33 m/s, 600 veh/h, un carril.
- El cruce (5000, 5000) se sustituye por ocho nodos de rotonda a 250 m del centro.
  Anillo horario, 5.56 m/s, 600 veh/h. Cuatro accesos cardinales y cuatro diagonales
  conectan con la reticula; las diagonales tienen entradas occidentales y salidas
  orientales, a 13.89 m/s y 1000 veh/h.
- Bypass exterior horario con 40 nodos `B_...`, margen de 500 m y esquinas
  compartidas. Velocidad 22.22 m/s, capacidad 2400 veh/h, dos carriles. Rampas
  de entrada y salida separadas, sin enlaces opuestos sobre el mismo segmento.
- Alas escalonadas dentro de X=0..3 km, Y=2..4 km y su reflejo exacto respecto
  de X=5 km. Los desvios con segmentos diagonales permanecen dentro de manzanas
  individuales y conectan en sus esquinas; no crean cruces geometricos ambiguos.
- Total: 186 nodos y 376 enlaces. La validacion previa exige conectividad fuerte
  en ambos sentidos del grafo. No usa NetworkCleaner para ocultar nodos aislados.

## Poblacion y ejecucion

400 agentes por defecto; `--agents` acepta 250..500. Semilla 42. Todos los hogares
y trabajos se asignan a enlaces del bypass, con salidas entre 07:00 y 07:30.
Cada plan contiene `home -> car -> parking -> car -> work`; parking se distribuye
en calles interiores para inducir viajes por la ciudad y dura 3.0 segundos.
Diez iteraciones por defecto (0..9); ventana QSim de 24 horas para completar viajes.

```powershell
.\mvnw.cmd compile exec:java '-Dexec.mainClass=gt.edu.uvg.sim.labs.Lab05MiniCityNetwork' '-Dexec.args=--agents 500 --iter 10 --output output/labs/05-mini-city-recreated'
.\.venv\Scripts\python.exe -m unittest discover -s python -p test_lab05_network.py -v
.\.venv\Scripts\python.exe python/visualize_network.py --lab 5 --output-dir output/labs/05-mini-city-recreated --mode microscopic
```

La salida predeterminada sin `--output` es `output/labs/05-mini-city`. MATSim
rechaza un directorio existente para preservar resultados; use un nombre nuevo
al repetir una corrida. `LAB05_OUTPUT` permite seleccionar otra salida para las
pruebas; estas verifican diez iteraciones. El visualizador puede seleccionar una
red antigua del Lab05 por prioridad de carpetas: use `--output-dir` explicitamente.

## Validacion realizada

22 de septiembre de 2026: compilacion y ejecucion de 500 agentes, diez iteraciones,
en `output/labs/05-mini-city-recreated`. Se exportaron `output_network.xml.gz`,
planes, configuracion y eventos. Las tres pruebas de integracion pasaron:

- Coordenadas, paridad, velocidades y sentido horario de la rotonda.
- Conectividad fuerte, ausencia de enlaces inversos/duplicados y simetria lateral.
- En cada una de las diez iteraciones: los 500 agentes llegan a `work`, cero
  eventos `stuckAndAbort`, y las 500 actividades parking duran exactamente 3.0 s
  entre sus eventos de inicio y fin.

Parking en QSim es una actividad fuera del flujo de circulacion: su duracion no
significa que bloquee fisicamente un carril. Las colas de QSim dependen de capacidad
y almacenamiento; el bloqueo espacial del motor microscopico Python requiere su
propia validacion. Los resultados anteriores verifican este escenario MATSim y
esta demanda, no garantizan ausencia de bloqueos con cualquier carga o motor.
