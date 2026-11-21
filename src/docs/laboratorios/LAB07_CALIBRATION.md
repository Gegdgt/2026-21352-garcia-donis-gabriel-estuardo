# Lab07: ajuste temporal y espacial

Este es un escenario parametrizado con las ventanas solicitadas, no una
calibracion empirica milimetrica. No se dispone de aforos OD, fases semaforicas
ni tiempos de viaje observados de Zona 1 para estimar o validar los coeficientes.
Las paginas oficiales consultadas de [EMETRA](https://www.muniguate.com/emetra/)
y [Movilidad Urbana](https://www.muniguate.com/direccion-de-movilidad-urbana/)
no aportaron una serie temporal que valide estos horarios exactos.
La [direccion oficial del Congreso](https://www.congreso.gob.gt/contactanos)
es 9 Avenida 9-44, Zona 1; su entorno se aproxima en la malla local.

## Demanda

Se conservan 72 000 personas, semilla reproducible y OD perifericos alcanzables.
Los pesos son intensidades relativas por hora: probabilidad de cada intervalo
proporcional a su duracion multiplicada por su peso, normalizada sobre 24 h.

| Intervalo | Peso horario |
|---|---:|
| 00:00-04:00 | 0.04 |
| 04:00-04:30 | 0.40 |
| 04:30-05:00 | 1.60 |
| 05:00-05:30 | 2.50 |
| 05:30-08:45 | 3.20 |
| 08:45-09:30 | 1.00 |
| 09:30-12:00 | 0.65 |
| 12:00-14:00 | 1.25 |
| 14:00-15:00 | 0.65 |
| 15:00-16:30 | 1.20 |
| 16:30-20:30 | 3.40 |
| 20:30-21:00 | 0.90 |
| 21:00-22:00 | 0.40 |
| 22:00-23:00 | 0.20 |
| 23:00-24:00 | 0.08 |

Los extremos son intervalos [inicio, fin). La concentracion adicional de origen
del 5% matutino y 8% vespertino usa las ventanas 04:30-08:45 y 16:30-20:30.
Una meseta de salidas no garantiza una meseta exacta de congestion: esta depende
de las rutas, capacidades y colas. `--demand archivo.csv` permite sustituir los
pesos por datos medidos (`start_hour,end_hour,weight`, cobertura continua 0-24).

## Friccion espacial y enrutamiento

| Entorno aproximado | Factor velocidad | Factor capacidad |
|---|---:|---:|
| Congreso: A8-A9, C9-C10 | 0.70 | 0.90 |
| Plaza/Catedral: A6-A8, C5-C8 | 0.75 | 0.90 |
| Tramos restantes de A4 y A7 | 0.90 | 0.95 |
| Salidas al borde oeste/sur | 0.90 | 0.95 |

Se aplica la primera categoria coincidente, sin multiplicar penalizaciones
superpuestas. Las coordenadas corresponden al identificador de cada tramo.
La capacidad nominal por carril y el ancho se conservan como referencia; la
capacidad efectiva se reduce. No se agregan enlaces externos al recorte.
Las salidas son proxies hacia la red exterior, no conexiones verificadas al
Anillo Periferico. El Centro Historico ya esta representado dentro de la malla.

MATSim enruta inicialmente con el tiempo libre efectivo `longitud/velocidad` y
recalcula rutas con los tiempos experimentados en cada iteracion. QSim tambien
usa la capacidad efectiva: los retrasos y filas dependen de la carga real.
Python lee esos mismos valores; su ruteo opcional `balanced` incluye la friccion
una sola vez. `effectiveDelaySeconds` es informativo, no otra espera acumulada.
No se simulan ciclos semaforicos explicitos. La friccion se mantiene todo el dia;
el factor nocturno se aplica sobre la velocidad efectiva en el motor visual.

XML conserva `hotspot`, `nominalFreeSpeed`, `nominalCapacity`,
`frictionSpeedFactor`, `frictionCapacityFactor`, `effectiveDelaySeconds` y la
curva completa. Los carriles y la topologia dirigida permanecen conectados.

## Ejecucion y comprobaciones

```powershell
.\mvnw.cmd compile exec:java "-Dexec.mainClass=gt.edu.uvg.sim.labs.Lab07MultiLaneZona1" "-Dexec.args=--iter 10 --output output/labs/07-calibrated-zona1"
.\.venv\Scripts\python.exe python/visualize_network.py --lab 7 --output-dir output/labs/07-calibrated-zona1 --mode microscopic
$env:LAB07_OUTPUT = 'output/labs/07-calibrated-zona1'
.\.venv\Scripts\python.exe -m unittest discover -s python -p 'test_lab07*.py' -v
```

La carpeta nueva preserva la corrida anterior. La prueba comprueba distribucion
muestreada, costes/capacidades, carriles, conectividad y llegadas finales.
Estabilidad de MATSim y ausencia de bloqueo en el motor visual son verificaciones
distintas: los resultados MATSim no prueban que el ciclo Python se vacie.

## Resultado de la corrida de validacion

La corrida `07-calibrated-zona1` completo las iteraciones 0-9 con BUILD SUCCESS.
En cada iteracion: 144 000 etapas salieron y llegaron (dos por persona), cero
abortos y cero etapas pendientes al cierre de QSim. Los 72 000 agentes llegaron
a la actividad final en la exportacion final y sus rutas son conectadas.
Pasaron las tres pruebas del perfil (incluida la distribucion muestreada de
salidas), las dos de exportacion y las 30 pruebas del motor de trafico.
Esto verifica estabilidad computacional; no demuestra ajuste estadistico a PMT
ni continuidad de varios dias del motor visual bajo esta nueva carga.
