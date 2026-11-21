# SimZ1: envolvente visual y evidencia de colas

Cambio limitado al renderizador continuo y sus pruebas. No modifica datos, eventos,
planes, velocidades, carriles nativos, semáforos, capacidades ni exports. La geometría
local es aproximada, no cartografía GIS verificada. Los cambios que ya existían en
el árbol de trabajo se conservaron.

## Diagnóstico confirmado por lectura del código anterior

`frame()` agrupaba por enlace/carril, ordenaba primero por fracción de avance y
comparaba cada carrocería únicamente con `leaderBody` del mismo grupo. Esto dejaba
sin comprobar otros carriles, otros enlaces y vehículos no consecutivos en un giro.
La prioridad de la fracción podía intercambiar identidades durante la formación.
Al salir un predecesor, la cola se compactaba aunque el siguiente vehículo siguiera
en una fase detenida. El buscador de separación en curvas solo exploraba un pitch.

Se confirmaron `omit()`, `body_overlap`, `storage_exceeded`, `boundary_transition`,
`geometry_or_lane_unavailable`, `body_unrepresentable`, y la capa `queue-overflow`
con `getText:d=>'! '+d.count`. `motion_unavailable` se producía en los controles
antes de llamar al renderizador de colas. También existía
`body_geometry_unavailable` para anchura incompatible con la franja disponible.
Los valores predeterminados eran 4.5 × 1.8 m y gap de 2 m.

No se ejecutaron fixtures, pruebas ni la corrida para esta entrega. Las causas
anteriores son verificaciones estáticas; las siguientes son expectativas de
regresión, no resultados de una ejecución ni IDs de la corrida real.
Se comprobó la sintaxis con `node --check` y el formato del diff con
`git diff --check`, sin ejecutar el código de los fixtures ni sus assertions.

## Fixtures reproducibles

`python/test_simz1_queue_safety.cjs --evidence` imprime JSON con instante, identidad,
enlace, carril, posiciones iniciales y finales, orientación, dimensiones, omisión,
pares en conflicto y limitaciones. Coordenadas de esta tabla en metros locales;
el JSON utiliza las coordenadas del visor. Todos los cuerpos son de 4.5 × 1.8 m.

| Fixture / IDs | Instante | Situación y expectativa |
|---|---:|---|
| `same_lane_2`, `q0`, `q1` | 50 s | Ambos parten del extremo x=150, carril 0; centros estimados x=145.5 y 139, gap 2 m. |
| `same_lane_5`, `same_lane_10`, `q0`…`q9` | 50 s | Pitch 6.5 m, orden por entrada, sin descartar identidades para aprobar separación. |
| `adjacent_bodies`, `adj-a`, `adj-b` | 50 s | Ejes a y b separados 1.5 m, cuerpos inicialmente solapados; retraso por la misma geometría: x=95.5 y 89. |
| `adjacent_lane_envelopes`, `left`, `right` | 50 s | Carriles 0 y 1 a 3 m; margen configurable de 0.7 m por lado provoca conflicto de envolventes, no aumento de carrocerías. |
| `stop_line_perpendicular`, `west`, `south` | 50 s | Colas perpendiculares en nodo j; carrocerías antes de la franja transversal y del margen de parada. |
| `possible_event_incompatibility`, `cross-a`, `cross-b` | 50 s | Dos movimientos sin WAIT en el mismo nodo. Se conservan visibles y se registra conflicto sin declarar una incompatibilidad física demostrada. |
| `former_bang_1`, `short0`, `short1` | 50 s | Enlace de 12 m: centro 7.5 para short0; slot 1 m no admite cuerpo completo. short1 sigue identificado como `storage_exceeded`. |
| `former_bang_3`, `short0`…`short3` | 50 s | Mismo enlace; tres omisiones geométricas explícitas, sin `! 3` en el mapa. |
| `supported_short_link_spillback`, `spill0`…`spill4` | 50 s | Enlace r de 2 m con predecesor up observado y compatible. Centros -0.25, -6.75, -13.25, -19.75, -26.25 relativos al inicio de r. |
| `link_boundary`, `transition` | 10 s | Salida de up y entrada de r contiguas; cuerpo visible, identidad y pose compartidas. |
| `unknown_and_forced`, `missing`, `forced` | 50 s | Geometría ausente y plan `unavailable`; no se fabrican ubicaciones. |

Otros assertions cubren separación durante un giro rígido, espera hasta 3500 s,
salida de un predecesor sin salto de un seguidor detenido, orden contrario al avance,
seek inverso, margen configurable, carril único recuperable y rechazo de continuidad
con huecos temporales o con otra vía. El harness de controles prueba reproducción
1x/120x, ventanas, intervalos desconocidos y selección independiente de la envolvente.

Para comparar con una copia que se haya conservado del renderizador anterior,
establecer `SIMZ1_QUEUE_SOURCE` a ese archivo. Las regresiones exigen, entre otros,
diagnósticos globales, orden FIFO, reserva después de salir el predecesor y continuidad
respaldada en el enlace corto, que el código anterior no implementaba. No utilizar
`git show HEAD` como sustituto del estado inicial: había cambios locales previos.

## Reglas de colocación

- Carrocería de referencia: 4.5 × 1.8 m. No son dimensiones medidas por vehículo.
- Envolvente orientada: longitud de carrocería + `gap_m` (2 m por defecto) y anchura
  de carrocería + 2 × `lateral_clearance_m` (0.1 m por lado). SAT comprueba los cuatro
  ejes de ambos rectángulos; un índice espacial de celdas de 16 m reduce candidatos.
  Se comparan enlaces y carriles diferentes con niveles compatibles.
- El gap admite 0…10 m, y el margen lateral 0…1 m. Se configuran con
  `simz1Continuous.setSafetyEnvelope({gap_m:2,lateral_clearance_m:0.1})`.
  No se cambian el ancho de la calle ni los radios de selección (8/18 px).
- FIFO por entrada observada al carril, o entrada al enlace cuando no hay una
  observación única. Empates usan identidad estable y quedan marcados como orden
  estimado. La fracción de avance no cambia el orden.
- La posición de espera se reserva en `hold_start`, incluyendo predecesores de
  contexto cuyos intervalos coincidían entonces. Búsqueda aguas arriba sobre la
  misma geometría, pasos máximos de 0.25 m y refinamiento a menos de 1 mm durante
  formación. Las reservas detenidas conservan un margen conservador de hasta 0.25 m.
- La línea de parada usa la franja transversal existente y un margen de 2 m.
  Un enlace corto puede reducir este último, conservando el cuerpo antes del cruce.
- Extensión aguas arriba: solo un enlace anterior observado, contiguo, conectado,
  de la misma vía y subdivisión geométrica unívoca, mismo carril y nivel. En varias
  pistas se exigen ambos carriles nativos. Se rechazan cruces intermedios, carriles
  terminales recortados, saltos de tiempo, giros y pertenencia ambigua. El ID del
  enlace nativo no se cambia; `display_link` identifica el soporte visual.

## Tratamiento de las omisiones y límites

| Motivo anterior | Tratamiento |
|---|---|
| `body_overlap` | Se detecta globalmente y se busca separación sustentada. Una coincidencia con un coche ya dibujado no basta para ocultarlo. Si una cola no cabe, se informa `storage_exceeded` con evidencia del conflicto; movimientos libres incompatibles permanecen visibles y diagnosticados. |
| `storage_exceeded` | Se conserva si no cabe el cuerpo o la envolvente en la extensión verificable. No se modifica capacidad QSim ni se usa otra calle. |
| `boundary_transition` | Se mantiene la pose rígida de la conexión observada y sus extremos exactos. Una colocación que carezca de soporte sigue siendo explícita. |
| `geometry_or_lane_unavailable` | Se recupera el eje de un carril si trayectoria y geometría coinciden. Una pista ambigua en varias pistas no se inventa. |
| `body_unrepresentable` | Se normaliza la fracción respaldada y se recupera el centro desde el carril cuando es posible. Sin orientación/geometría suficiente sigue omitido. |
| `motion_unavailable` | Se conserva el motivo del plan. No se anula `distance_exceeds_speed_cap` ni se convierten movimientos forzados en trayectorias físicamente válidas. |

Un solapamiento de dibujos no demuestra por sí solo una incompatibilidad física
MATSim: sus eventos no son mediciones continuas de carrocerías. Los conflictos no
resueltos se clasifican como geometría insuficiente o posible incompatibilidad,
con `physical_incompatibility_confirmed:false` y los intervalos implicados.

Límites explícitos: una espera que comenzó antes de la ventana cargada puede carecer
de predecesores ya salidos (`hold_roster_may_precede_loaded_window`). No se garantiza
la misma reserva entre ventanas si ese historial falta. Tampoco se fabrica el
recorrido subpaso entre la cola espaciada y un nuevo enlace: se conserva
`queue_exit_has_no_substep_trajectory`. Pueden persistir discontinuidades en esas
salidas y conflictos de movimientos simultáneos sin evidencia suficiente para
recolocarlos. Las comprobaciones geométricas por instante no prueban una trayectoria
física continua entre dos eventos o entre frames saltados a 120x.

Los `! N` se quitaron porque su diagnóstico se trasladó al apartado técnico,
con consulta por `vehicle_id` y API. No significa que sus causas hayan desaparecido.

## Inspección

```javascript
simz1Continuous.getVisualDiagnostics();
simz1Continuous.diagnoseVehicle('vehicle_id');
simz1Continuous.traceVehicle('vehicle_id', [119.9, 120, 120.1]);
```

La consulta evalúa la cohorte completa, no un vehículo aislado. Incluye activos,
visibles, omitidos, motivos, en cola, conflictos corregidos/no resueltos, posiciones
insuficientes y contexto incompleto. Las consultas temporales son de solo lectura.
Fuera de la ventana disponible devuelven `window_not_loaded`; hacer seek, esperar
la carga y consultar de nuevo. Los huecos de eventos permanecen `unknown_interval`.

## Comandos PowerShell (no ejecutados)

Desde la raíz del proyecto:

```powershell
$simz1Checks = @(
  'test_simz1_queue_safety.cjs',
  'test_simz1_visual_queues.cjs',
  'test_simz1_rigid_vehicles.cjs',
  'test_simz1_visual_lanes.cjs',
  'test_simz1_parallel_geometry.cjs',
  'test_simz1_vehicle_picking.cjs',
  'test_simz1_continuous_replay.cjs',
  'test_simz1_continuous_bootstrap.cjs',
  'test_visualizador_z1_controls.cjs',
  'test_visualizador_z1_paged.cjs'
)
foreach ($simz1Check in $simz1Checks) {
  & node (Join-Path '.\python' $simz1Check)
  if ($LASTEXITCODE -ne 0) { throw "Falló $simz1Check" }
}
& node .\python\test_simz1_queue_safety.cjs --evidence
```

Para reiniciar, detener con Ctrl+C el servidor anterior en su consola y ejecutar
el servidor existente contra el export de 229629 agentes. No reprocesa los 96
bloques ni SQLite y no abre navegador:

```powershell
& .\.venv\Scripts\python.exe -B .\python\serve_simz1_continuous.py --directory .\scenarios\zona1\montecarlo\run-night-20261017-012651-6a8d9ac3\webgl-continuo --port 8793
```

Dirección: `http://localhost:8793/index.html`. Recargar sin caché para recibir el
JavaScript actual. Esta entrega no inició servidores ni navegadores, no ejecutó
MATSim ni pruebas, no regeneró archivos científicos y no hizo commit ni push.
