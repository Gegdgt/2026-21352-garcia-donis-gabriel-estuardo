# Informe de rendimiento del motor de trafico

Fecha: 22 de septiembre de 2026. Escenario: Lab07 calibrado, 72 000 agentes/dia,
limite de 1500 visibles, paso fisico de 0.5 s, rutas `observed` y paradas
sinteticas habilitadas. Archivos: `output/labs/07-calibrated-zona1`.

## Conclusiones verificadas

**No se puede certificar fluidez a 30 FPS ni ausencia de bloqueo.** Las consultas
por carril y la preparacion de demanda mejoraron, y las pruebas de sincronizacion
de la interfaz pasan. Sin embargo, la corrida microscopica completa de 24 horas
queda bloqueada y el redibujado completo de Matplotlib no alcanza 30 FPS en las
mediciones realizadas. La estabilidad anterior de MATSim/QSim no demuestra la
estabilidad de este motor visual, que tiene reglas de seguimiento y admision distintas.

## Entorno y metodologia

- Windows 10.0.26200, Python 3.10.11, procesador Intel64 Family 6 Model 191
  Stepping 2; 24 procesadores logicos visibles.
- Tiempo transcurrido: `time.perf_counter`; CPU del proceso: `time.process_time`.
  CPU/tiempo transcurrido mide equivalentes de un procesador logico, no porcentaje
  del equipo completo. No se midieron potencia ni utilizacion GPU.
- RSS y pico RSS: `GetProcessMemoryInfo` de Windows, en MiB. Los picos RSS son
  acumulativos durante la vida del proceso; el segundo caso no reinicia ese pico.
- Memoria incremental Python: `tracemalloc`, con las rutas compartidas ya creadas.
  No equivale a RSS. Los tiempos de construccion incluyen la sobrecarga de tracing.
- Comparacion antes/despues mediante las dos implementaciones de consulta y la
  reconstruccion explicita del antiguo constructor anticipado. No se afirma una
  mejora global de toda la simulacion: no hay dos corridas completas cronometradas
  del mismo escenario con ambos motores.
- Las pruebas se ejecutaron en el equipo compartido; algunas coincidieron con la
  corrida larga/regresiones. No es un ensayo en hardware aislado. Las cifras de
  CPU y las distribuciones complementan los tiempos de pared.
- Instrumentacion reproducible: [benchmark_traffic.py](../../python/benchmark_traffic.py).

## Comparacion de las optimizaciones

### Consultas de espacio y rebase

Fixture: 1500 vehiculos separados 12 m, distribuidos en enlaces con las longitudes
y carriles de la red Lab07. 50 barridos completos por alternativa. El caso indexado
incluye construir el indice en cada barrido. Las decisiones coinciden exactamente.

| Implementacion | Media por barrido | P95 | CPU, 50 barridos |
|---|---:|---:|---:|
| Busqueda lineal anterior | 17.419 ms | 21.790 ms | 0.813 s |
| Indice ordenado actual | 7.956 ms | 9.393 ms | 0.391 s |

Resultado: **2.19 veces mas rapido; 54.3% menos tiempo de consulta** en este fixture.
No son tiempos de un cuadro completo de fisica. Los cambios se evaluan una vez
por segundo simulado y las reservas actualizan el indice secuencialmente.
Una prueba adicional verifica equivalencia despues de mover vehiculos entre carriles.

En una prueba limite de un enlace de 6000 m y cuatro carriles, 1500 vehiculos,
12 barridos: 393.864 ms lineal frente a 10.440 ms indexado. Ese resultado NO es
representativo de las manzanas cortas de Zona 1 y no se usa como mejora global.

Evidencia: performance-neighbors.json (`target/performance-neighbors.json`, evidencia local excluida de Git) y
performance-probes.json (`target/performance-probes.json`, evidencia local excluida de Git).

### Demanda pendiente y carga diferida

Fixture: 72 000 rutas con 20 operaciones cada una y tres cohortes; 216 000
salidas pendientes. El caso anterior crea todos los vehiculos y copia todas las
operaciones. El actual conserva referencias a rutas y crea estado al salir.

| Construccion | Tiempo con tracing | CPU | Pico incremental Python |
|---|---:|---:|---:|
| Anticipada anterior | 81.090 s | 76.578 s | 1195.985 MiB |
| Diferida actual | 1.183 s | 1.141 s | 35.737 MiB |

La memoria incremental baja **97.0%**. El cociente temporal bajo tracing es 68.5;
no debe interpretarse como aceleracion del motor completo ni como tiempo sin
instrumentacion. RSS al terminar cada constructor: 4035.063 y 643.379 MiB;
incluye rutas base, runtime y tracing. El pico RSS acumulado de ambos es 4045.609 MiB.

Las esperas externas ya estaban agrupadas por posicion/carril de entrada. Cuando
una entrada esta bloqueada, no se repite la comprobacion para todos los que esperan
en ella. El indice de admision mantiene el orden de llegada entre accesos y conserva
la demanda pendiente. La carga diferida no implica memoria constante: las rutas
base y los vehiculos que ya salieron pero aun esperan siguen ocupando memoria.

## Validacion completa de 24 horas

La ejecucion previa con el indice por carril y carga diferida completo todos los
**172 801 cuadros**, de 0 a 86 400 s inclusive. Validaba separacion longitudinal,
valores finitos, velocidades y telemetria en cada cuadro.

| Resultado | Valor |
|---|---:|
| Pico de vehiculos visibles | 1500 |
| Cambios de carril | 7840 |
| Agentes completados | 7922 / 72000 |
| Agentes pendientes a medianoche, dentro y fuera de red | 64078 |
| Vehiculos visibles detenidos al cierre | 1500 |
| Velocidad maxima observada | 89.76 km/h |

Desde las 08:00 hasta medianoche, las muestras reportadas estan detenidas y la
velocidad media es cero. **La prueba de descarga falla.** No se borraron vehiculos
ni se reinicio el motor para ocultar las colas. El log antiguo decia "Verificacion
OK" porque comprobaba invariantes de los cuadros, no finalizacion de viajes.
`visualize_network.py --check` ahora distingue expresamente ambas comprobaciones.

Evidencia: lab07-optimized-day.log (`target/lab07-optimized-day.log`, evidencia local excluida de Git). Ese proceso
no estaba instrumentado para CPU/RAM/tiempos; no se inventan esas cifras.

### Cruce real de medianoche y continuacion hasta 36 horas

La segunda ejecucion instrumentada proceso dos cohortes en el mismo motor hasta
la hora 36 (259 201 cuadros inclusive). El ultimo registro es de las 20:44 del
22 de septiembre. Al retomar el trabajo el proceso ya no estaba activo; no hay
registro de finalizacion ni excepcion que permita atribuir la interrupcion.
**El objetivo adicional de 48 horas no se completo.** La validacion solicitada
de 24 horas y el cruce al segundo dia si se ejecutaron.

| Instante simulado | Visibles | En movimiento | Completados acumulados | Vehiculos del segundo dia visibles |
|---|---:|---:|---:|---:|
| 23:59:59 | 1500 | 0 | 7922 | 0 |
| 23:59:59.5 | 1500 | 0 | 7922 | 0 |
| Dia 2, 00:00:00 | 1500 | 0 | 7922 | 0 |
| Dia 2, 00:00:00.5 | 1500 | 0 | 7922 | 0 |
| Dia 2, 00:00:01 | 1500 | 0 | 7922 | 0 |
| Dia 2, 12:00:00 | 1500 | 0 | 7922 | Sin admisiones adicionales |

Los cinco cuadros alrededor de medianoche conservan exactamente IDs y posiciones:
no hay limpieza o reinicio de agentes. Sin embargo, conservarlos detenidos no
equivale a continuidad de flujo. No hubo nuevas finalizaciones entre las horas
8 y 36; las muestras horarias tienen cero vehiculos en movimiento. Esto demuestra
un bloqueo prolongado observado, no una prueba matematica de inmovilidad eterna:
el detector conservador no certifico este escenario (`gridlock_time = null`).
La descarga y el ingreso fluido del nuevo dia **fallan**.

Preparacion de XML/rutas: 48.129 s. Tiempo de simulacion hasta 36 horas:
8433.531 s (140.56 minutos reales). RSS cargada: 746.309 MiB; RSS a la hora 36:
623.625 MiB; pico observado: 941.535 MiB, incluida la escritura del checkpoint.
Estos valores corresponden al proceso largo. No se obtuvo su CPU acumulada final
ni su distribucion completa de tiempos por cuadro porque no termino el benchmark.
Evidencia: performance-full.json (`target/performance-full.json`, evidencia local excluida de Git) y
performance-full.log (`target/performance-full.log`, evidencia local excluida de Git), conservados como resultados parciales.

### CPU y coste fisico del estado real con 1500 vehiculos

Se restauro el checkpoint propio de las 08:00 y se midieron 600 pasos consecutivos,
de 08:00:00.5 a 08:05:00, con 1500 agentes activos. No es un fixture sintetico ni
una nueva corrida completa. El estado esta congestionado y detenido; no representa
el coste de 1500 vehiculos moviendose libremente. La regresion de restauracion
compara cada cuadro con una ejecucion ininterrumpida en un escenario pequeno.

| Medida | Resultado |
|---|---:|
| Paso fisico medio / mediana | 30.467 / 27.134 ms |
| P95 / maximo | 48.972 / 316.962 ms |
| Tiempo de pared / CPU del tramo | 18.282 / 17.031 s |
| CPU equivalente a un procesador logico | 93.16% |
| RSS final / pico RSS del proceso de restauracion | 1181.086 / 1208.469 MiB |
| Viajes completados al inicio y al final | 7922 / 7922 |

El RSS de esta prueba incluye la deserializacion y estructuras del checkpoint;
no debe confundirse con el RSS del proceso largo. Los tiempos excluyen renderizado.
Con dt=0.5 s, reproducir fisica en vivo a 120x exigiria 240 pasos/s, unos 4.17 ms
por paso. Esta medicion no satisface ese presupuesto. La reproduccion desde una
cache tiene un coste distinto y requiere prepararla primero.
Evidencia: performance-checkpoint.json (`target/performance-checkpoint.json`, evidencia local excluida de Git).

## Interfaz con 1500 agentes

Se utiliza la red del escenario exportada y un fixture determinista de 1500 marcadores;
las posiciones/velocidades del fixture NO son trayectorias fisicas. Se ejecutan
30 saltos (00:00, 18:00, 05:00, 23:59:59, 00:00:01 y 12:00 repetidos), eventos
de raton de hover y pulsaciones sobre los seis botones de reproduccion.

Se comprueba en cada salto:

- Hora del reloj igual a la del panel de telemetria.
- Coordenadas del scatter iguales a `position(link, distance, lane)`.
- Color igual al intervalo de velocidad actual.
- Velocidad actual/promedio del hover iguales a las del agente seleccionado.
- Pausa sin avance; tasas negativas retroceden; tasas positivas avanzan conforme
  a la base de 120 segundos simulados por segundo real.

No hubo excepciones ni fallos de estas aserciones. Se probaron Agg y TkAgg nativo
con ventana oculta y procesamiento de eventos. TkAgg requirio acceso a la
instalacion local de Tcl fuera del sandbox; la segunda ejecucion completo la prueba.
No se midieron refresco del monitor ni latencia percibida por una persona.
La integracion de estos controles con una cache real del Lab07 que descargue sus
colas sigue sin validarse: el escenario masivo no alcanza ese estado. Las pruebas
de interfaz verifican sincronizacion y excepciones, no resuelven ese bloqueo.

| Medicion | Agg | TkAgg oculto |
|---|---:|---:|
| Actualizacion de agentes, media (40 cuadros) | 11.005 ms | 20.215 ms |
| Dibujado de canvas, media (40 cuadros) | 127.562 ms | 274.010 ms |
| Cuadro total medio | 138.567 ms | 294.225 ms |
| Cuadro total P95 | 306.509 ms | 382.715 ms |
| FPS de redibujado completo medido | 7.22 | 3.40 |
| Busqueda temporal + hover + redibujados, media | 516.281 ms | 575.451 ms |
| CPU de las 30 interacciones y botones | 15.156 s | 16.125 s |
| RSS en esa fase | 82.410 MiB | 101.594 MiB |

Las interacciones incluyen mas de un redibujado por los callbacks; no son un FPS
de animacion. El presupuesto para 30 FPS es 33.3 ms/cuadro: no se cumple con el
redibujado completo. El reloj puede saltar cuadros para mantener 120x, pero eso no
equivale a fluidez. Estas medidas no incluyen construir la cache de varios dias.

Evidencia: performance-gui.json (`target/performance-gui.json`, evidencia local excluida de Git),
performance-gui-tk.json (`target/performance-gui-tk.json`, evidencia local excluida de Git) y
captura de esfuerzo (`target/lab07-stress-gui.png`, evidencia local excluida de Git).

## Regresiones y limites

La ejecucion final completa paso **55 pruebas en 151.711 s**, incluidas las
regresiones de motor, restauracion de checkpoint, controles, interfaz densa y
exportaciones MATSim disponibles. Evidencia:
performance-final-regression.log (`target/performance-final-regression.log`, evidencia local excluida de Git).
La ejecucion previa de 47 pruebas queda en
performance-regression.log (`target/performance-regression.log`, evidencia local excluida de Git).
Matplotlib emitio una advertencia por una animacion de prueba eliminada sin
renderizar; unittest termino con `OK`, sin fallos ni errores de prueba.
Se corrigio la restauracion de checkpoints: la variable usada al restaurar
atributos sobrescribia la funcion local de ordenacion de vehiculos y causaba un
TypeError al reanudar. La regresion compara cuadros, finalizaciones y cambios de
carril entre ejecucion continua y restaurada.
Las pruebas pequenas del ciclo periodico y de cruce de medianoche pasan; eso no
certifica que las colas del Lab07 masivo se vacien.

Se agrego una prueba integrada de cache de 1500 agentes, interpolacion, saltos
abruptos y hover. Comprueba el ID mas cercano al pixel del evento, las coordenadas
interpoladas y los colores/velocidades en ambos sentidos temporales. Usa un fixture
periodico corto, no sustituye los resultados de descarga del escenario completo.

### Deteccion conservadora de bloqueo permanente

Se agrego un certificado suficiente de estado absorbente para el modelo actual,
con rutas, capacidades y parametros viales constantes durante la ejecucion:
admision al limite, velocidades cero, liberaciones/cooldowns vencidos, todos los
avances bloqueados por otros vehiculos y ningun cambio de carril posible incluso
con el mayor objetivo de velocidad del dia. Incluye las salidas de parking cuyo
destino sigue ocupado. No afirma detectar todos los bloqueos posibles.

En ese estado se conservan posiciones, IDs y demanda; se generan muestras
inmutables bajo demanda que actualizan el tiempo transcurrido y la velocidad media.
No se soluciona la congestion ni se finge movimiento. La equivalencia con el
calculo sin atajo se comprobo cuadro a cuadro, incluidas las salidas de parking.
La cache periodica rechaza ese estado explicitamente y `--check` falla si lo
detecta; ya no se confunde con una validacion exitosa de descarga.

Prueba de 1500 vehiculos bloqueados en un anillo de tres carriles, 241 cuadros:

| Coste | Recalculo | Estado certificado |
|---|---:|---:|
| Produccion de cuadro, media | 15.308 ms | 0.722 ms |
| Materializacion de las 1500 muestras, media | 0.127 ms | 13.153 ms |
| CPU total | 3.547 s | 3.219 s |

Si el consumidor lee todas las muestras en cada paso, el coste no desaparece:
se desplaza a la materializacion. La ventaja principal es omitir trabajo cuando
el consumidor salta cuadros, y diagnosticar el ciclo imposible. No se usa esa
reduccion como FPS de vehiculos en movimiento.
Evidencia: performance-steady.json (`target/performance-steady.json`, evidencia local excluida de Git).

El siguiente trabajo necesario es diagnosticar y corregir la dependencia circular
de carriles receptores/rutas bajo saturacion, y volver a validar la descarga sin
eliminar agentes ni teletransportarlos. Para renderizado, las mediciones justifican
evaluar agrupacion de geometria estatica y blitting, con pruebas de resize y hover.
No se atribuye el bloqueo a falta de CPU: un motor mas rapido puede calcular el
mismo estado bloqueado mas rapidamente.

## Reproduccion

Desde `matsim-guatemala`, con los XML ya generados:

```powershell
.\.venv\Scripts\python.exe python/benchmark_traffic.py neighbors --result target/performance-neighbors.json
.\.venv\Scripts\python.exe python/benchmark_traffic.py probes --result target/performance-probes.json
.\.venv\Scripts\python.exe python/benchmark_traffic.py steady --result target/performance-steady.json
.\.venv\Scripts\python.exe python/benchmark_traffic.py gui --result target/performance-gui.json
.\.venv\Scripts\python.exe python/benchmark_traffic.py gui --backend TkAgg --result target/performance-gui-tk.json
.\.venv\Scripts\python.exe -u python/benchmark_traffic.py full --result target/performance-full.json
.\.venv\Scripts\python.exe python/benchmark_traffic.py checkpoint --resume target/performance-full.checkpoint.pkl --result target/performance-checkpoint.json
.\.venv\Scripts\python.exe -m unittest discover -s python -p 'test_*.py' -v
```

El modo `full` procesa dos cohortes en un motor unico, 48 horas y dt=0.5 s,
registra estadisticas por hora y muestra estados a ambos lados de medianoche.
Sus comprobaciones geometricas son horarias; la corrida previa de 24 horas
realizo las comprobaciones geometricas en todos los cuadros.
El modo `checkpoint` solo admite archivos pickle propios y confiables; mide un
tramo separado y nunca lo presenta como tiempo acumulado de la corrida completa.
