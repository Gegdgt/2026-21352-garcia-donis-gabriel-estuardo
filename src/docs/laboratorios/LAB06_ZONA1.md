# Laboratorio 6: Zona 1, ciclo diario

Clase: `gt.edu.uvg.sim.labs.Lab06Zona1Network`. Conserva Lab05.
El modelo implementa el mapeo verbal con coordenadas locales aproximadas, sin
precision GIS ni certificacion de sentidos reales.

## Topologia y puntos de interes

- Avenidas 2-11 y calles 2-15, incluida toda la calle 2. X este, Y norte, metros.
- Avenidas pares hacia el sur, impares hacia el norte. Calles pares al oeste,
  impares al este. Un carril por enlace, sin contravias.
- Calle 7 interrumpida entre avenidas 5 y 9; continuidad 2-5 y 9-11.
- Palacio: A6-8/C5-6 (amarillo). Plaza/Catedral: A6-8/C6-8 (verde).
  A7 no atraviesa C5-C8 y se elimina el cruce interior A7/C7. C6 es borde
  compartido. Los rectangulos solicitados prevalecen sobre la referencia verbal
  a A7 como costado: A7 queda dentro de esos rectangulos.
- C13 cortada entre A7-A8 y C14 entre A8-A9, con aproximaciones terminales de
  45 m. Los nodos ciegos D_ son vehiculares pero no son destinos de paso ni
  puntos intermedios del reparto visual. El router evita los cierres al planificar;
  no simula descubrirlos y retroceder contra via.
- Quiebres de 6 m mediante polilineas en el oeste/sur, dentro de la calle 15.
  No se incluyen Fegua/21 calle ni bulevares externos.
- Parque Colon: poligono verde de referencia al este de A11, fuera de la red.
  Hospital San Juan de Dios y Catedral: marcadores estaticos esquematicos.
- `visualArea.*` y `visualPoi.*` exportan vertices/tipo/etiqueta en network.xml.
  Nodos/enlaces cercanos tienen `greenArea`, `institutionalArea`, `hospitalZone`.
  Los terminales exportan `deadEnd` y `routingEligible=false`.

## Demanda y velocidades

Locales: 30 km/h, 600 veh/h. Colectores A6/A7/C9/C12: 45 km/h, 1200 veh/h.
Zona hospitalaria A2-3/C9-11: 25 km/h, 400 veh/h, con prioridad sobre colectores.
12 000 viajes por defecto (`--agents N`), OD limitrofes y horarios reproducibles
(semillas 42 y 20260922). Cada OD se comprueba antes de enrutar. Se conservan
home-parking (3 s)-work y los carriles MATSim. Diez iteraciones por defecto (0-9).

| Horas | Peso relativo por hora |
|---|---:|
| 00-04 | 0.04 |
| 04-04:30 | 0.4 |
| 04:30-08:30 | 3.2 |
| 08:30-09:30 | 1.0 |
| 09:30-15 | 0.65 |
| 15-16 | 1.2 |
| 16-20 | 3.4 |
| 20-21 | 0.9 |
| 21-22 / 22-23 / 23-24 | 0.4 / 0.2 / 0.08 |

Se normalizan pesos por duracion y se muestrean horarios con total fijo.
Son supuestos de escenario, NO aforos medidos de EMETRA. Durante picos se
concentra el 40% de entradas en C9/A2 por la manana y el 55% en A11/C12 por la
tarde para saturar accesos. Estas participaciones OD tampoco son observadas.
Las colas y colores resultan de capacidad, seguimiento y espacio receptor;
pueden persistir tras los picos. Una via local libre a 30 km/h permanece naranja;
el celeste corresponde a velocidades superiores en colectores.

`nightFreeSpeed=75 km/h` es una hipotesis visual en colectores entre 00-04,
con transicion gradual hasta 04:30, ajustada por perfil de conductor. No es
limite legal ni velocidad observada; no altera hospitales ni freespeed de QSim.
`--no-aggressive-profiles` desactiva este exceso de velocidad sintetico.

## Reloj: 24 horas en 12 minutos

`--lab 6 --mode microscopic` activa `--day`: escala fija 120x, una hora en 30 s.
La cinematica integra a 0.5 s; el refresco apunta a 30 FPS. Se prepara una cache
antes de arrancar `perf_counter`: esa preparacion NO cuenta en los 12 minutos.
Si la GUI no alcanza a dibujar, omite cuadros sin ralentizar el reloj; la ultima
actualizacion puede retrasarse un refresco del sistema grafico.

La cabecera, mapa, leyenda y hover usan ejes separados. La interpolacion opera
solo dentro del mismo enlace/carril y conserva distancias durante transiciones.
El reloj no depende del numero de cuadros ni aumenta el paso fisico.
`--no-day` vuelve al modo anterior. `--mode replay` conserva los tiempos XML.
El ciclo diario conserva rutas y primeras entradas XML, pero recalcula tiempos
de movimiento: sus colas no son una reproduccion exacta de QSim.

QSim permite drenaje hasta las 30:00 para viajes que cruzan medianoche. La vista
interactiva repite jornadas sin cortar los viajes pendientes a medianoche.
El comando `--check` sigue validando una ventana de 24 horas e informa pendientes.
`output_demand.csv` registra viajes programados cada media hora; no son conteos
vehiculares observados en enlaces. El perfil y las participaciones se exportan
como atributos de la red.

## Fuentes y calibracion externa

- [Publinews, 12/01/2026, declaraciones de EMETRA/PMT](https://www.publinews.gt/noticias/2026/01/12/cambiara-la-hora-pico-en-la-ciudad-de-guatemala-esto-dice-la-pmt/):
  informa picos 05:30-08:45 y 16:30-20:30, sin aforos horarios de esta red.
  Los intervalos implementados 04:30-08:30 y 16-20 corresponden a la solicitud;
  no son una transcripcion de esos datos. No se encontro una serie de aforos
  que permita presentar los pesos como mediciones reales de Zona 1.
- [Municipalidad: Biblioteca Cristobal Colon](https://www.muniguate.com/blog/2020/03/05/conoce-la-biblioteca-publica-municipal-cristobal-colon-zona-1/):
  ubica el parque junto a 8a calle entre 11 y 12 avenida. Se representa fuera
  del limite A11 sin ampliar la red vial.

Para incorporar aforos: `--demand archivo.csv`, cabecera
`start_hour,end_hour,weight`, intervalos contiguos que cubran [0,24], pesos finitos
no negativos. El peso es intensidad relativa por hora: divide los conteos de
cada intervalo por su duracion. `--agents` fija el total diario. La ruta del
archivo se registra en `demandSource` para trazabilidad.

## Ejecucion desde matsim-guatemala

```powershell
.\mvnw.cmd compile exec:java "-Dexec.mainClass=gt.edu.uvg.sim.labs.Lab06Zona1Network" "-Dexec.args=--iter 10"
.\.venv\Scripts\python.exe python/visualize_network.py --lab 6 --mode microscopic
.\.venv\Scripts\python.exe python/visualize_network.py --lab 6 --mode microscopic --check
.\.venv\Scripts\python.exe -m unittest discover -s python -p 'test_*.py' -v
```

Salida: `output/labs/06-zona1`, con red, planes, carriles, configuracion, demanda
y eventos finales y por iteracion. No sobrescribe resultados: usa `--output`
con una carpeta nueva y `--output-dir` en Python (`LAB06_OUTPUT` en pruebas).
El reparto `balanced` crea rutas visuales sinteticas; por defecto el ciclo diario
usa los recorridos exportados (`observed`) para mantener la distribucion OD.

## Barra multimedia y dias continuos

En Lab06 microscopico (`--day`, predeterminado), el deslizador inferior cubre
00:00:00-23:59:59 del dia actualmente mostrado. Cambia inmediatamente mapa,
reloj y telemetria, incluso en pausa. No cambia el dia seleccionado.

Botones: `-2.0x`, `-1.5x`, `0.0x Pausa`, `+1.0x`, `+1.5x`, `+2.0x`.
Estos multiplicadores se aplican a la base de 120 segundos simulados por segundo
real: +2.0x tarda 6 minutos por dia y -1.5x retrocede a 180 segundos simulados
por segundo real. Cambiar velocidad no cambia la posicion temporal. La reversa
cruza medianoches hacia dias anteriores y se limita al inicio del Dia 1.
Los valores del hover son los del instante consultado; retroceder no produce
velocidades fisicas negativas ni reintegra ecuaciones hacia atras.

La preparacion ejecuta cohortes consecutivas en el mismo motor: vehiculos nuevos
y viajes del dia anterior comparten capacidad y espacio receptor. Los perfiles,
carriles y paradas de cada viaje se repiten de forma determinista. Se busca un
instante sin vehiculos ni cola de entrada despues del calentamiento, dejando
expirar tambien los intervalos de capacidad. Se verifica de nuevo un dia despues
y se guarda el ciclo entre esos dos instantes, que NO tienen que ser medianoche.

La cache permite consultar cualquier instante hacia adelante o atras con memoria
acotada, incluso miles de dias despues. Los IDs `D<dia de salida>:<agente>`
permanecen estables mientras un viaje atraviesa medianoche. Un ID D0 al comienzo
del Dia 1 corresponde a un viaje iniciado en la jornada de calentamiento previa.
La demanda diaria se repite: no se generan dias estadisticamente independientes.
Si el escenario nunca libera la red o no cierra el ciclo, la preparacion falla
explicitamente; no elimina vehiculos para fingir continuidad.

El coste de preparar varias jornadas se paga antes de activar la reproduccion.
Los controles tienen filas propias, separadas del mapa, leyenda y panel hover.
El modo `--no-day` y la reproduccion XML de los demas laboratorios conservan su
comportamiento previo.

Pruebas especificas:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s python -p test_playback_controls.py -v
```
