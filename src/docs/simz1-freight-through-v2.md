# Rutas de carga de paso: weekday-v2

La versión `scenarios/zona1/freight/weekday-v2/service-composition-v2.json`
representa una expedición de paso por camión: una actividad `freight_external`
de entrada, una pierna con ruta explícita y otra actividad `freight_external`
de salida. No incluye entregas, estacionamiento ni destinos internos.
Los cuatro IDs históricos se conservan; `reverse` identifica otro corredor
dirigido, no la inversión mecánica del mismo recorrido.

El perímetro utilizado es el rectángulo de extracción de `map.osm`:
longitud −90.522 a −90.505, latitud 14.625 a 14.646. Cada primer enlace cruza
desde fuera hacia dentro y cada último enlace cruza hacia fuera. Las partes
intermedias permanecen dentro. No es un límite administrativo ni cartografía
GIS verificada. Los enlaces completos conservan sus pequeños extremos fuera
del rectángulo; no se modifica ni se recorta la red OSM.

## Mapa lógico

| ID | Entrada → corredores → salida | Distancia | Tiempo libre |
|---|---|---:|---:|
| `west-east` | Oeste, 19 Calle → 3a Avenida → 9a Calle → 13 Avenida → 7a Calle, este | 3154.993 m | 318.064 s |
| `west-east-reverse` | Este, 15 Avenida → 8a Calle → 10a Avenida → 12 Calle → 7a Avenida → 6a Calle → Avenida Elena → 5a Calle, oeste | 3141.564 m | 298.206 s |
| `south-north` | Sur, 12 Avenida → 22 Calle → 13 Avenida → 20 Calle → 11 Avenida, norte | 2806.182 m | 280.050 s |
| `south-north-reverse` | Norte, 6a Avenida → 6a Calle → 4a Avenida → enlaces principales sin nombre → 21 Calle → 6a Avenida, sur | 2726.923 m | 248.084 s |

Los tiempos suman `longitud / min(freespeed, 40 km/h)` de todos los enlaces,
incluidos los accesos. Excluyen semáforos, prioridades, reservas y colas.
El corredor oeste–este aprovecha extremos al suroeste y noreste; en los otros
tres se priorizó conservar los tramos principales correctos. Todos conectan
lados opuestos. No se impusieron desvíos adicionales para forzar esquinas.

| ID | Enlace de entrada | Enlace de salida |
|---|---|---|
| `west-east` | `osm_381158292_0_forward` | `osm_1358273948_0_forward` |
| `west-east-reverse` | `osm_49009942_2_forward` | `osm_65792798_1_backward` |
| `south-north` | `osm_363667895_5_forward` | `osm_732305247_6_forward` |
| `south-north-reverse` | `osm_381097595_10_forward` | `osm_400843677_5_forward` |

El mapa y los CSV de revisión de esta modificación están en
`runtime/diagnostics/freight-through-20261030/`:
`mapa_logico_rutas_weekday_v2.png`, su SVG, `route_map_summary.csv`,
`route_map_segments.csv` y `route_overlap.csv`. `routes.json` conserva la
secuencia completa de enlaces, los accesos y las anclas históricas.

## Qué se conserva y qué cambia

| ID | Enlaces v1 → v2 | Enlaces principales v1 conservados | Cambio |
|---|---:|---:|---|
| `west-east` | 52 → 100 | 0 / 0 | Sustituye el recorrido íntegramente residencial por 5a Calle con corredores principales. |
| `west-east-reverse` | 85 → 127 | 66 / 66 | Sustituye el tramo residencial interior de 8a Calle/9a Avenida/6a Calle; conserva 8a Calle, 6a Calle y Avenida Elena principales. Ajusta ambos accesos al borde. |
| `south-north` | 71 → 78 | 68 / 68 | Sustituye tres enlaces residenciales de 12 Avenida A por 13 Avenida/20 Calle y prolonga los accesos por sus mismas avenidas. |
| `south-north-reverse` | 76 → 99 | 69 / 69 | Sustituye la aproximación residencial de 4a Avenida por 6a Avenida/6a Calle y prolonga entrada y salida al borde. |

Se conservan **203 de 203 enlaces principales históricos**, en su orden.
La clasificación vial guía la nueva política de paso: una calle residencial
no se declara legalmente prohibida solo por su clasificación.

La única excepción residencial es `osm_65792798_1_backward`, **186.132 m**
de 5a Calle al final de `west-east-reverse`. Conecta Avenida Elena con el
borde occidental y evita eliminar sus tramos principales correctos. Se
declara en `perimeter_connector_links`; el validador solo permite estos
conectores en extremos y limita su longitud total a 250 m. Esta ruta recorre
94.075% de su distancia por vías principales; las otras tres, 100%.

Los camiones se reparten con diferencia máxima de una unidad entre las
cuatro rutas. Para 5536 unidades corresponden 1384 por ruta. Solo dos rutas
comparten enlaces dirigidos: `west-east-reverse` y `south-north-reverse`,
15 enlaces de 6a Calle que suman 193.305 m (6.15% y 7.09% de sus recorridos).
Los otros cinco pares no comparten enlaces dirigidos. Cruces e interacciones
en nodos siguen existiendo; esta distribución no demuestra capacidad suficiente.

## Validación y reproducibilidad

`prepare_simz1_freight_routes.py` conserva las anclas principales de v1 y
busca puentes de distancia mínima sobre enlaces y giros aptos según los datos
disponibles. Los accesos elegidos son explícitos y deterministas. El generador
rechaza sobrescribir v1 o una versión existente con contenido diferente.
Las huellas de red, carriles, OSM y rutas históricas quedan en el bundle.

`simz1_freight_routes.py` comprueba conectividad dirigida, correspondencia
de segmentos con OSM, sentidos, accesos y restricciones dimensionales,
restricciones de giro relevantes y alcance de los destinos desde la raíz
del grafo de carriles. Rechaza ciclos de carriles, enlaces repetidos y giros
en U inmediatos. Una restricción relevante no interpretada exige revisión.
Las indicaciones OSM de giro por carril se comprueban al extremo dirigido de
la vía, no en cada subdivisión geométrica. La red nativa modela colas;
no demuestra la trayectoria lateral real de un camión.

`simz1_freight_signals.py` comprueba las fases y referencias de señales y la
existencia de ticks verdes para todos los carriles nativos alcanzables del
movimiento. La red base
incluye 16, 20, 20 y 3 movimientos controlados en las cuatro rutas,
respectivamente. Esta comprobación no garantiza una ventana conjunta para
todos los cruces de un paso compuesto.

`simz1_freight.py` verifica la procedencia de los insumos base y vuelve a
validar el grafo efectivo después de incorporar el servicio de buses. Cada
corrida v2 guarda OSM, reporte de validación, servicio, rutas y roster bajo
`inputs/freight-weekday/`, con huellas en el manifiesto. La identidad del
servicio es `weekday-v2`; el esquema del actor permanece
`simz1-freight-weekday-v1` para conservar compatibilidad nativa e histórica.

Se mantienen la fórmula de cantidad derivada de N, PBV 12 t, PCU 3.5,
cuerpo 12 × 2.5 m, máximo 40 km/h, las tres ventanas horarias, su política
de residencia y el margen de despacho de 1800 s. Los instantes estratificados
se recalculan con el tiempo libre de cada nueva ruta. No se cambia el catálogo
privado ni el servicio independiente de 269 buses.

Pruebas focalizadas, sin QSim:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s python -p test_simz1_freight_routes_v2.py -v
.\.venv\Scripts\python.exe -B -m unittest discover -s python -p test_simz1_freight_signals.py -v
.\.venv\Scripts\python.exe -B -m unittest discover -s python -p test_simz1_freight_through_integration.py -v
.\.venv\Scripts\python.exe -B -m unittest discover -s python -p test_simz1_freight_version.py -v
```

## Límites pendientes del diagnóstico de congestión

La geometría y anchura nominales, los tags OSM y los carriles permiten una
validación estática del escenario. Faltan mediciones de gálibo, radios y
barrido de un cuerpo de 12 m para certificar aptitud física de campo. Un
enlace menor de 12 m puede formar parte de un corredor continuo o un paso
compuesto; no se rechaza automáticamente por esa subdivisión.

Esta modificación no corrige las dos retenciones artificiales confirmadas
en el diagnóstico de la corrida masiva: el criterio de liberación inalcanzable
en el acceso de servicio de 8a Avenida/19 Calle y la reserva cuyo vencimiento
no se reevalúa sin nuevo progreso en el acceso de 24 Calle. Deben corregirse
y probarse por separado antes de atribuir el atasco a capacidad real. No se
ejecutó otra simulación ni se ha demostrado desalojo completo o mejora de
congestión con las rutas v2.
