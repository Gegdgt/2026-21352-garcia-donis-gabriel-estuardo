# Medición del render continuo de SimZ1

Estado: instrumentado, sin benchmarks ni navegador ejecutados por el agente.
No hay resultados de FPS o de mejora de latencia todavía. La copia anterior a
estos cambios está en `runtime/simz1-render-baseline-20261018`; incluye los arreglos
de carga temporal de la tarea anterior. No se copian ni regeneran corridas.

## Revisión de contratos (2026-10-19)

El fallo `13 !== 12` comprobaba la cadencia, no el número de agentes: tras
`play()` y un RAF sin avance, un RAF a 10 ms debe avanzar el reloj sin dibujar
otra vez a 30 Hz. `play()` dibujaba pero reiniciaba `lastDrawTimestamp` a
`-Infinity`; solamente RAF registraba los dibujos. Ahora todo dibujo completado
registra su instante, incluidos play, seek y cámara. El reloj y Motion_Plan siguen
evaluándose a tiempo absoluto; los controles conservan su dibujo inmediato.

El fallo `false !== true` tenía un fixture geométrico incorrecto. Dos rectángulos
de 4,5 × 1,8 m orientados a 45°, separados verticalmente 3 m, tienen separación
transversal `3 / sqrt(2) = 2,121 m`: sus cuerpos no se intersectan. El SAT previo
a la optimización también devuelve false. Se conserva un caso positivo a 2 m,
el negativo a 3 m y un caso a 2,7 m donde se intersectan las envolventes de
seguridad, pero no los cuerpos. No se ensancharon vehículos ni se relajó SAT.

La regresión de cruce de ventana a 120x ahora presenta el instante 28081 mediante
pausa inmediata antes de comprobar la posición exacta 11. Su RAF llega solo
8,33 ms después de play; exigir allí otro dibujo contradiría el límite de 60 Hz.
Las regresiones de cadencia comprueban por separado reloj a 1x/120x, ausencia de
dibujo prematuro tras play/seek y equivalencia entre RAF y seek al mismo instante.

Validación realizada únicamente con fixtures en memoria:

- Pasan `test_simz1_render_performance.cjs`, `test_simz1_queue_safety.cjs`,
  `test_simz1_continuous_replay.cjs`, `test_simz1_window_loading.cjs`,
  `test_simz1_rigid_vehicles.cjs`, `test_simz1_visual_queues.cjs`,
  `test_simz1_visual_lanes.cjs`, `test_simz1_map_labels.cjs`,
  `test_simz1_spatial_view.cjs`, `test_simz1_continuous_bootstrap.cjs` y
  `test_simz1_parallel_geometry.cjs`. Ejecutar con `node python/<archivo>`.
- El SAT escalar coincide con la formulación anterior en 2000 pares de cuerpos
  y sus envolventes. Evaluaciones con caché y en frío coinciden en marcadores
  completos y diagnósticos, incluidos FIFO e identidad; se comprueban activos
  contra los intervalos fuente, su salida exacta a 115 y la inmutabilidad de
  timestamps, Motion_Plan y demás campos fuente.
- La copia `runtime/simz1-render-baseline-20261018` coincide en los 12 fixtures de
  evidencia de `test_simz1_queue_safety.cjs --evidence` (seleccionable con
  `SIMZ1_QUEUE_SOURCE`). Con `SIMZ1_RENDER_SOURCE_DIR` se compararon los marcadores
  completos, diagnósticos y conteos de ambas versiones: 30 vehículos, modos
  `dense` y `turn`, tiempos 0, 19.99, 20, 30, 37.49, 37.51, 60, 114.999, 115, 30;
  las 20 instantáneas coinciden. Son comprobaciones de corrección, no benchmarks.
- La exploración adicional detectó dos fallos preexistentes fuera de estos
  cambios: `test_simz1_vehicle_picking.cjs:32` (desempate entre dos registros del
  mismo vehículo) y `test_simz1_continuous_hud.cjs:106` (el fixture presupone que
  una sola microtarea basta para entrar a `response.json()` desde otro contexto
  VM). Sus fuentes y pruebas coinciden con HEAD. No se declara toda la suite verde.

No se ejecutaron MATSim, simulaciones, servidores, navegadores ni benchmarks;
no se regeneraron SQLite, bloques HTML o Motion_Plan.

## Observación real: 229629 agentes a 120x

Datos aportados por el usuario: `lastLoadMs=10753`, `activeIndex=229`, una ventana
de aproximadamente 111 MiB retenida, presupuesto de 128 MiB y una solicitud
pendiente. Es una observación real aislada, sin comparación antes/después.

`lastLoadMs` mide la última carga **completada**, desde el inicio de la solicitud
hasta terminar validación y preparación; incluye reintentos/esperas y excluye
activación y primer render. No identifica por sí solo la ventana 229 ni el tiempo
que lleva la solicitud pendiente. El índice 229 no es un conteo de vehículos.
Debemos guardar población total, agentes activos, vehículos únicos activos,
visibles y omitidos por motivo como magnitudes separadas.

Los 111 MiB contabilizan JSON UTF-8 decodificado: no son bytes transferidos
comprimidos ni heap real. Quedan unos 17 MiB en ese presupuesto; otra ventana de
111 MiB necesitaría unos 222 MiB en total. Sin embargo, el cargador actual adapta
`cacheByteBudget` hasta `cacheHardBytes`: una sola ventana y otra pendiente pueden
ser un estado normal de precarga. Hay que obtener el límite duro, tamaños del
sucesor y motivos de descarte antes de atribuirlo a expulsiones por memoria.

Si `window_seconds=120`, a 120x se consume una ventana por segundo de pared.
Una carga de 10,753 s excede ese intervalo; sería insuficiente como latencia
repetida de la ruta crítica con una sola ventana de adelanto. Una muestra no
establece throughput sostenido ni permite atribuir el retraso a render, servidor
o red. Aumentar caché no demostraría que la producción de ventanas puede seguir
el ritmo. Hay que medir varias ventanas, en frío/caliente y a 1x/120x.

| Tramo | Obtener de la instrumentación existente | Datos que faltan para aislarlo |
| --- | --- | --- |
| Identidad y espera | `run_id`, iteración, hash del manifest, `loadSamples.index`, `pendingIndices`, reintentos 503, `transitions.waitMs` | Correlación por solicitud/intento y versión del visor; instante de demanda, inicio/fin de cada intento, espera de retry, fase y edad de cada pendiente; conservar también abortos y errores. |
| Servidor | `Server-Timing`, `/api/metrics`: hit/miss/coalesced, `wait_or_build_ms`, `cached_build_profile` (build/gzip), `write_ms`; payload: `timings_seconds`, `query_counters` | Separar cola/coalescencia de trabajo propio, SQLite, descompresión zlib, ensamblaje/serialización, gzip; correlacionar con cada intento. En un hit el perfil de construcción pertenece a la creación original del caché. |
| Transporte | `headersMs`, `bodyReadAndBrowserDecompressMs`; Resource Timing/CDP: requestStart, responseStart/End, encoded/decodedBodySize, transferSize y Content-Encoding | TTFB por intento y transferencia del cuerpo, throughput comprimido, demora del event loop y descompresión del navegador. `headersMs` incluye retries; TTFB no es exclusivamente servidor. La lectura del cuerpo mezcla transferencia, descompresión y scheduling. |
| Preparación | `decodeMs`, `parseMs`, `validateMs`, `prepareMs/preparePhases`, `mode`, `dispatchMs`, `preparationRoundTripMs`, `spatialValidationMs`, `runtimePreparationMs` | Despacho/arranque del Worker, clonación y entrega de resultados, esperas del hilo principal y CPU efectiva de las fases cooperativas. El residual del round trip menos cómputo Worker mezcla varias de estas causas. |
| Activación y render | `activationSamples`, `activationToFrameMs`, `renderMs`, `stages`, SAT/candidatos/poses, actualizaciones de capas, `deckSubmitMs`, `lastDeckDrawCpuMs`, brechas RAF | Latencia hasta presentación real, FPS presentado, frames perdidos, tareas largas, GC, heap pico (también Workers) y GPU. El primer frame instrumentado y los callbacks de Deck miden CPU, no presentación ni ejecución GPU. |
| Precarga/caché | `cacheBaseBytes`, `cacheByteBudget`, `cacheHardBytes`, `knownWindowBytes`, `prefetchBlocked`, hits/misses, evictions y budgetAborts | Línea temporal por índice: solicitado, listo, demandado, activado, expulsado; margen de precarga frente a demanda y bytes/segmentos/contexto de cada ventana. |

Exportar conjuntamente `getState()`, `getPerformance()` y `getRenderPerformance()`
con trazas del servidor y navegador en una medición futura autorizada. Los
buffers guardan solo 32 cargas/activaciones y 600 frames; capturarlos durante el
intervalo para no perder el bloqueo inicial. Comparar mediana/p95/máximo y tiempo
total detenido, con idéntica corrida, cámara, tiempos nativos y población.

No sumar métricas anidadas: `preparationRoundTripMs` contiene despacho y trabajo
de preparación; los perfiles SQL/zlib se solapan con fases de construcción;
`markerMs`/`queueMs` ya están incluidos en render. `write_ms` tampoco equivale a
transferencia recibida. Esta separación es necesaria antes de proponer otra
optimización. El rendimiento sigue pendiente de benchmarks reales comparables.

## Qué se compara

La ruta actual sigue evaluando Motion_Plan a tiempo absoluto, mantiene SAT entre
cuerpos orientados y conserva todos los diagnósticos. La geometría, el árbol de
intervalos activos y las capas estáticas ya se reutilizaban. Los cambios reducen:

- Trigonometría y arrays temporales de SAT; la búsqueda espacial usa AABB de la
  envolvente orientada y un conjunto de candidatos reutilizable.
- Reconstrucción de anclas de espera: se conserva una sola caché, invalidada por
  contexto, configuración, pertenencia/entrada de carril, plan, geometría o
  vecinos distintos. No depende del orden de reproducción ni del FPS.
- Consultas repetidas de geometría compatible, almacenamiento y dimensiones.
- Creación de marcadores detenidos y actualizaciones de su capa GPU si todos sus
  objetos permanecen iguales. No se comparan sólo los IDs para saltarse movimiento.
- Materialización de evidencia detallada: todas las colisiones se comprueban y
  cuentan en cada frame; los objetos de diagnóstico se expanden al consultar la API.
- Búsquedas de señales entre eventos y trabajo de etiquetas con cámara invariable.

El reloj avanza en cada requestAnimationFrame. El dibujo se limita a un máximo
configurable de 60 Hz por defecto, sin promesa de conseguirlos; evalúa la posición
continua al tiempo actual, sin integrar posiciones por pasos. Pausa, seek, cámara
y controles pueden solicitar dibujo inmediato. No se acumula una cola de dibujos.
Persisten cálculos síncronos, especialmente en la primera colocación y en grupos
de muchos cuerpos coincidentes: la evidencia de todos sus pares puede ser
cuadrática. Los controles no tienen una garantía de latencia hasta medir esto.

`getRenderPerformance()` separa etiquetas, incidentes, señales, consulta de activos,
Motion_Plan/marcadores, colas, diagnósticos, selección, capas, envío a Deck y DOM.
Las colas incluyen entradas, colisiones originales, anclas, colocación, diagnóstico,
llamadas SAT, candidatos, solicitudes de pose y reutilizaciones. Sus 600 muestras
son una ventana reciente; no un historial ilimitado. `deckSubmitMs` y
`lastDeckDrawCpuMs` son CPU, **no tiempo de ejecución GPU**. Los contadores de
marcadores cubren sólo esas asignaciones; no sustituyen el perfil de memoria.

## PowerShell: regresiones y comparación CPU

Desde la raíz del repositorio, con Node 22 o posterior:

```powershell
node .\python\test_simz1_render_performance.cjs
node .\python\test_simz1_queue_safety.cjs
node .\python\test_simz1_rigid_vehicles.cjs
node .\python\test_simz1_continuous_replay.cjs
node .\python\test_simz1_map_labels.cjs
node --expose-gc .\scripts\validation\benchmark_simz1_render.cjs --source .\runtime\simz1-render-baseline-20261018 --frames 30 --output .\runtime\render-before.json
node --expose-gc .\scripts\validation\benchmark_simz1_render.cjs --source .\python --frames 30 --output .\runtime\render-after.json
node .\scripts\validation\compare_simz1_render.cjs .\runtime\render-before.json .\runtime\render-after.json
```

Los fixtures tienen 100, 1000 y 3000 vehículos; tres carriles por enlace, colas
densas, movimiento, giros y rojo prolongado. Incluyen reproducción muestreada a 1x,
pausa, fotogramas idénticos, cámara, seek frío/caliente y cambios de señal. Usan JS real y Deck/DOM
simulados; no abren navegador, servidor, SQLite ni archivos de una corrida.
El perfil de asignaciones V8 incluye objetos recogidos; es una estimación por
muestreo. Heap delta es memoria neta, no bytes asignados. Se registra GC, p50/p95,
máximo y capacidad CPU (`1000 / media_ms`); ese último valor **no es FPS presentado**.
El comparador rechaza cambios en IDs, posiciones, orientación y conteos.
Repita ambos comandos al menos tres veces, alternando el orden, sin otras tareas
pesadas. No compare una corrida con profiler con otra sin profiler.

## PowerShell: servidor anterior y actual sobre la misma exportación

Detenga el servidor existente con Ctrl+C. Para la versión anterior al cambio de
render, en una terminal desde la raíz:

```powershell
$replay = (Resolve-Path '.\scenarios\zona1\montecarlo\run-night-20261017-012651-6a8d9ac3\webgl-continuo').Path
$env:PYTHONPATH = (Resolve-Path '.\python').Path
& .\.venv\Scripts\python.exe -B .\runtime\simz1-render-baseline-20261018\serve_simz1_continuous.py --directory $replay --port 8793
```

Para la versión actual, Ctrl+C en esa terminal y:

```powershell
& .\.venv\Scripts\python.exe -B .\python\serve_simz1_continuous.py --directory $replay --port 8793
```

Estos comandos sirven el código actual/guardado y leen la misma exportación; no
ejecutan MATSim ni reconstruyen bloques, SQLite o Motion_Plan.

## Chrome/Edge DevTools: corrida de 229629, render a 1x

1. Abra manualmente `http://localhost:8793/index.html`. Use igual navegador,
   tamaño de viewport, zoom y dispositivo en ambas versiones. Abra DevTools (F12).
   En **Performance**, seleccione CPU sin throttling y la casilla **Memory**.
   La pista Main muestra trabajo JS y GC; Frames muestra frames tardíos. Guarde
   el trace completo, además de los promedios. Véanse las referencias oficiales de
   [Chrome](https://developer.chrome.com/docs/devtools/performance/reference/) y
   [Edge](https://learn.microsoft.com/en-us/microsoft-edge/devtools/performance/reference).
2. En Console, prepare un intervalo interior a la ventana para aislar render:

   ```javascript
   simz1Continuous.pause();
   simz1Continuous.setSpeed(1);
   simz1Continuous.seek(28051); // 07:47:31
   simz1Continuous.deck.props.onViewStateChange({viewState:{
     ...simz1Continuous.getState().camera.viewState,
     longitude:-90.513,latitude:14.636,zoom:17,pitch:45,bearing:0
   }});
   await new Promise((resolve,reject)=>{
     const deadline=performance.now()+120000;
     const poll=setInterval(()=>{
       const s=simz1Continuous.getState();
       if(s.error || performance.now()>deadline){clearInterval(poll);reject(Error(s.error || 'Carga pendiente'));}
       else if(!s.buffering && s.cache.pendingRequests===0){clearInterval(poll);resolve();}
     },100);
   });
   console.log(simz1Continuous.getState()); // comprobar identidad y conteos reales
   simz1Continuous.resetRenderMetrics?.();
   ```

3. Inicie grabación en Performance. Abra el cajón Console (Esc) y ejecute:

   ```javascript
   simz1Continuous.play();
   setTimeout(()=>simz1Continuous.pause(),15000);
   ```

   Al quedar pausado, detenga la grabación y guárdela como `render-before` o
   `render-after`. Esta prueba termina cerca de 07:47:46; no debe cruzar ventana.
   Un temporizador tardío también es evidencia de bloqueo, no motivo para borrar
   el tramo lento. En **Bottom-up**, compare `renderFrame`, `markerAt`,
   `motionAt`, `frame` de colas, `overlap`/`bodiesOverlap`, `pose`, `vehicleBody`,
   `AttributeManager` y teselación/actualización de PathLayer. Use **Self time** y
   **Total time**; no atribuya todo `setProps` al GPU.
4. Exporte las métricas técnicas desde Console (no al HUD):

   ```javascript
   copy(JSON.stringify({state:simz1Continuous.getState(),
     performance:simz1Continuous.getPerformance(),
     render:simz1Continuous.getRenderPerformance?.() ?? null},null,2));
   ```

   Pegue en un JSON distinto para cada versión. Compare p95 de los mismos tiempos
   y conteos. No evalúe `getVisualDiagnostics()` repetidamente durante el perfil:
   expandir todos los pares es trabajo de inspección adicional.
5. Para FPS efectivo/GPU, Ctrl+Shift+P → **Show Rendering** → **Frame rendering
   stats**. Repita el intervalo con el panel Performance detenido. Anote FPS,
   frames perdidos y memoria GPU; mantenga la misma cámara y no interprete el FPS
   CPU del fixture como dibujo real. La disponibilidad de pistas GPU depende del
   navegador/controlador; conserve esa limitación en el informe.
   [Procedimiento de Edge](https://learn.microsoft.com/microsoft-edge/devtools/performance/).
6. En otra pasada: Ctrl+Shift+P → **Show Memory** → **Allocation sampling** →
   Start, reproduzca el mismo intervalo, pause y Stop. Compare funciones y bytes
   muestreados. Para ver GC use Memory en Performance; las caídas del heap no son
   por sí solas una reducción de asignaciones.
   [Chrome Memory](https://developer.chrome.com/docs/devtools/memory),
   [Edge Allocation sampling](https://learn.microsoft.com/en-ca/microsoft-edge/devtools/rendering-tools/js-runtime).
7. Repita 10 segundos en pausa; rote y haga zoom, luego seek a 28061 y atrás a
   28051. Compruebe etiquetas, semáforos, picking y estabilidad de colas. Repita
   después 07:47:31 → 07:48:25 a 1x, sin esperar la precarga antes de Play, para
   comprobar integración con carga. Reporte por separado buffering y render.

No hay criterio de aceptación basado únicamente en FPS: identidades, conteos,
separación, orientación, tiempos y limitaciones de movimiento deben conservarse.
Una cola fría excesivamente costosa o un trace con tareas largas sigue siendo
un caso abierto; no se declara fluidez universal sin esa medición.
