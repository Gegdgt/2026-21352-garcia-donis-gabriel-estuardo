# Laboratorio 05: escenario Zona 1

El generador usa 10 avenidas (2–11) y 14 calles (2–15): 140 cruces,
9 × 13 intervalos de manzanas, 256 tramos de vía. Cuatro tramos con quiebres
de 4 m agregan 8 nodos geométricos: **148 nodos y 264 enlaces dirigidos**.
Los nodos `B_A…_C…` son los 44 cruces limítrofes; `G_` identifica cruces
interiores y `S_` puntos geométricos sin nuevas opciones de giro.

## Alcance geográfico

Es una **aproximación métrica del escenario solicitado**, no una extracción
catastral/OSM ni una red vial real exacta. Las tablas de distancias (112–132 m
entre ejes), los desfases y los quiebres son parámetros de diseño sin medición
GIS. El recinto local mide 1084 × 1638 m, con X hacia el este e Y hacia el norte;
no se asigna un EPSG a estas coordenadas locales.

Se identifican cruces del entorno del Palacio/Plaza entre avenidas 6–8 y calles
6–8, y la aproximación occidental al Hospital entre avenidas 2–3 y calles 9–12.
Estas etiquetas no representan accesos hospitalarios ni controles semafóricos.
La ubicación del Palacio en 6ª calle y 6ª avenida está documentada por
[CulturaGuate](https://culturaguate.gob.gt/palacio-nacional-de-la-cultura/).
La malla completa prescrita no reproduce vacíos de plazas, edificios ni
restricciones peatonales reales. Para una versión exacta se requieren geometrías
GIS y restricciones de acceso/giro verificadas, que pueden contradecir esa malla.

## Circulación y demanda

- Avenidas pares: norte → sur; impares: sur → norte.
- Calles pares: este → oeste; impares: oeste → este.
- Todos los enlaces: un carril, modo `car`, sin contravías ni redondel.
- Locales: 35 km/h y 800 veh/h. Avenidas 6/7 y calles 9/12: 50 km/h y 1500 veh/h.
- Un carril compartido permite todas las salidas compatibles con los sentidos.
  No se agregan carriles dedicados ni restricciones de giro no especificadas.
  La continuidad y los giros izquierdos/derechos existen distribuidos por la red;
  una intersección unidireccional no permite ambos giros desde cada aproximación.
- Los quiebres están en A2 entre C10–11, C6 entre A6–7, C8 entre A7–8 y
  C12 entre A2–3. Son polilíneas continuas sobre la misma vía, sin atajos
  diagonales a través de manzanas ni conexiones fuera del perímetro.
- 700 agentes, semilla 42, con 15–16 orígenes y destinos por cruce limítrofe.
  Salen entre 08:00 y 08:09:59 y conservan la actividad `parking` de 3 s.
  Los OD usan una permutación reproducible; no son una matriz OD observada.
- La validación Java exige conectividad fuerte sin eliminar componentes.

## Ejecución desde `matsim-guatemala`

Requiere el JDK 25 configurado por el proyecto y dependencias Maven disponibles.

```powershell
.\mvnw.cmd compile exec:java "-Dexec.mainClass=gt.edu.uvg.sim.labs.Lab05MiniCityNetwork" "-Dexec.args=--iter 1"
.\.venv\Scripts\python.exe -m unittest discover -s python -p test_zona1_network.py -v
.\.venv\Scripts\python.exe python/visualize_network.py --lab 5 --mode microscopic --check
.\.venv\Scripts\python.exe python/visualize_network.py --lab 5 --mode microscopic
```

Salida predeterminada: `output/labs/05-zona1`, priorizada por el visualizador.
MATSim exporta `output_network.xml.gz`, `output_plans.xml.gz`,
`output_lanes.xml.gz`, `output_events.xml.gz` y `output_config.xml`, además de
los resultados por iteración. `--mode microscopic` pertenece al visualizador
Python; Java siempre genera enlaces de un carril. `--iter 0` conserva la
semántica anterior: ejecuta la iteración inicial, igual que `--iter 1`.

No se borran resultados previos: para otra ejecución usa `--output` con una
carpeta nueva, `--output-dir` en Python y `ZONA1_OUTPUT` para las pruebas XML.
La reproducción predeterminada `balanced` reparte rutas visuales sintéticas;
`--routing observed` reproduce los recorridos exportados por MATSim.
