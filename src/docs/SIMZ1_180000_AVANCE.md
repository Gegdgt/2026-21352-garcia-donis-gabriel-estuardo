<!-- SIMZ1_VIEWERS_RELAUNCH_ACTIVE_START -->
# Estado activo: ambos visores levantados nuevamente

2026-11-10, Guatemala. **Arranque solicitado terminado.** La comprobación inicial encontró los cuatro servicios apagados y sus puertos libres (`-Check`, exit 2). Se ejecutó el lanzador existente con `-Both`, exit 0; comprobación posterior exit 0. Sin cambios al código, interfaz ni contrato `simz1-viewers-readonly-v1`.

Run1000: LaunchId `a32f15487b1a49ac910ba799175658ca`, RunId `simz1-9d15f07ccc134aa69c60fdcbc887ea3f`, iteración 0; fuente **8799 / PID 18168**, visor **8804 / PID 7744**. Run10K: LaunchId `e496c091b9ef46ee9ca381576135e299`, RunId `simz1-cdffd75c4bdb47a7bfb507efe2c8c4e9`, iteración 0; fuente **8801 / PID 56732**, visor **8803 / PID 51172**. Manifiestos e identidades comprobados mediante el contrato existente; se conserva la discrepancia histórica del estado de lanzamiento Run10K y su cierre recuperado.

**Evidencia actual:** [procesos, identidades y rutas de logs](../runtime/diagnostics/viewers-relaunch-20261110/services.json), [comprobación posterior](../runtime/diagnostics/viewers-relaunch-20261110/check.log). Chrome 157 real headless, WebGL2 Intel UHD/ANGLE D3D11: **45/45 PASS, exit 0**, mapas, vehículos, Dibujados 97/218, cero excepciones JS y los cuatro PIDs conservados después de cerrar/reabrir el navegador. [Resultados](../runtime/diagnostics/viewers-relaunch-20261110/browser/browser-results.json), [inspección de capturas](../runtime/diagnostics/viewers-relaunch-20261110/browser/visual-inspection.json). No se abrió una ventana visible del navegador durante esta comprobación.

**Siguiente acción:** abrir [Run1000](http://127.0.0.1:8804/index.html) y [Run10K](http://127.0.0.1:8803/index.html). Ambos servidores quedan activos después de terminar el lanzador. Se conserva la [guía de PowerShell](GUIA_INICIAR_VISORES_SIMZ1.md). No MATSim/QSim, Validate, DryRun ni reconstrucción de SQLite/replay; no se alteraron resultados, eventos, manifiestos o recibos. Los PIDs del cierre anterior quedan como históricos.

Seguimiento de solo lectura:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala\scripts\start_simz1_viewers.ps1' -Check
```
<!-- SIMZ1_VIEWERS_RELAUNCH_ACTIVE_END -->

<!-- SIMZ1_VIEWERS_STARTUP_HISTORICAL_START -->
# Histórico: recuperación de visores finales y lanzador independiente de PowerShell

2026-11-09, Guatemala. **Fase cerrada: ambos visores finales activos, reinicio y navegador comprobados.** Se conserva Run1000 LaunchId `a32f15487b1a49ac910ba799175658ca`, RunId `simz1-9d15f07ccc134aa69c60fdcbc887ea3f`, iteración 0, interfaz final 8804 y fuente 8799; Run10K LaunchId `e496c091b9ef46ee9ca381576135e299`, RunId `simz1-cdffd75c4bdb47a7bfb507efe2c8c4e9`, iteración 0, interfaz final 8803 y fuente 8801. No se necesitan 8800 ni 8802. [Estado final y procesos](../runtime/diagnostics/viewers-startup-20261109/final-status.json).

**Causa y contrato.** No había procesos de los visores al recuperar el estado. Las URLs abren el navegador pero no crean servidores; los últimos logs históricos terminan en HTTP 200 sin demostrar por qué finalizaron sus procesos. Los lanzadores históricos también exigen una huella global anterior. Se conserva esa guarda intacta y se añade el contrato explícito `simz1-viewers-readonly-v1`: identidad y SHA exacto de manifiestos, recibo recuperado Run10K, fuente SQLite inmutable y contrato nativo, configuración/replay e interfaz aprobados, evidencia preparada y dependencias del lector. No se afirma que la revisión actual sea la productora. El `state.json` histórico de Run10K sigue `running`; su cierre recuperado y manifiesto `completed/valid` se contrastan sin editar ninguno.

**Entrega.** [Lanzador único](../scripts/start_simz1_viewers.ps1), [guía de PowerShell](GUIA_INICIAR_VISORES_SIMZ1.md), [lector de solo lectura](../python/simz1_viewers_readonly.py). `-Both`, `-Run1000`, `-Run10K`, `-Check`, `-Open` y cierre acotado `-Stop`. Registros de PID/creación/padre/comando/propietario/logs en `runtime/viewers/services/`; stdout y stderr en `runtime/viewers/logs/`. Comprobación TCP por endpoint y propietario más HTTP/identidad/hash: en esta sesión Windows devolvió estados TCP inconsistentes para sockets reales y el filtro `-State Listen` resultó insuficiente. El arranque usa exclusividad de puerto y mutex; `-Check` no escribe ni reserva sockets.

**Pruebas ya terminadas.** Contrato 12/12 PASS; conflicto real en 8804 rechazado antes de iniciar servicios; reutilización conjunta e individual con los mismos PIDs; `-Check` sin cambios de registros; identidad ajena HTTP 400 en las cuatro APIs. Chrome real con WebGL2/ANGLE Intel UHD D3D11: **113/113 PASS**, cero excepciones JS, mapa, 97/218 dibujados a 11:05:25, 1x/120x, selección Transmetro/TuBus y carro/moto Run10K, filtros y barra. Cerrar y reabrir Chrome conservó los cuatro procesos y mapas. [Evidencia de navegador](../runtime/diagnostics/viewers-startup-20261109/browser/verification-1/browser-results.json). Se comprobó además `-Both -Stop`, exit 0, retirando solo los cuatro servidores y sus lectores propios, sin modificar el conjunto de procesos Java. [Log de cierre](../runtime/diagnostics/viewers-startup-20261109/stop-verified.log).

**Reinicio final terminado.** Run1000: fuente **8799 / PID 52388**, final **8804 / PID 19948**. Run10K: fuente **8801 / PID 228**, final **8803 / PID 24684**. Se comprobaron PID, creación, padre, ejecutable, comando y propietario; los registros incluyen el directorio de trabajo usado al iniciar. Reutilización final `-Both` exit 0, sin nuevos servidores; la consola auxiliar de captura también se cerró sin cambiar los PIDs. Chrome volvió a abrirse y cerrarse dos veces después del reinicio: **45/45 PASS**, mapas, WebGL2, 97/218 dibujados y cero excepciones JS. [QA después del reinicio](../runtime/diagnostics/viewers-startup-20261109/browser/after-restart/browser-results.json), [inspección de capturas](../runtime/diagnostics/viewers-startup-20261109/browser/after-restart/visual-inspection.json). Ambos servicios finales quedan activos. El arranque frío previo tomó 340.74 s para Run1000 y 245.10 s para Run10K, principalmente en la validación espacial original. El límite final es 600 s por servicio, con error explícito y conservación del proceso propio si vence. Se conservan el primer timeout de 300 s y la fixture de conflicto corregida. La apertura visible de Edge por shell fue rechazada por revisión automática (`blocked by policy`); Computer Use y el host de navegador no están disponibles. La verificación gráfica se completó en Chrome real headless, con capturas inspeccionadas. No se reinició Windows durante la prueba.

**Preservación.** Los 751 archivos nativos/replay conservan tamaño y mtime frente al inventario previo; no se ha repetido el hash multi-GB. Los manifiestos coinciden con los SHA pedidos y los HTML finales siguen `98995ffa27a1ef1210577e3bd69e76f276efcde89a67840a04f15a0ebde88bc1` (Run1000) y `917f3831020822b17f6e2db292f8244fc6782c89a48cbd963186cde06977ab1a` (Run10K). No MATSim/QSim, Run, Validate, DryRun, reconstrucción de SQLite/replay ni cambios de física, demanda, eventos, recibos o manifiestos. Los nuevos Python/PowerShell afectan la huella del siguiente experimento; sus guardas originales siguen vigentes.

**Siguiente acción:** abrir [Run1000](http://127.0.0.1:8804/index.html) y [Run10K](http://127.0.0.1:8803/index.html). Tras reiniciar Windows, ejecutar desde PowerShell el comando único de la guía con `-Both -Open`; no hace falta Codex ni VS Code. La revisión de supervisión es `simz1-viewers-readonly-v1`; huella global final observada `12933cdfb843293e5ba7dcf9bc4cf30a3a8dd92e5aeb08d7d388c6138331d20a`, distinta de la productora y sin actualizar recibos.

Seguimiento de solo lectura fuera del editor:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala\scripts\start_simz1_viewers.ps1' -Check
```
<!-- SIMZ1_VIEWERS_STARTUP_HISTORICAL_END -->

<!-- SIMZ1_RUN1000_CLEANUP_V1_HISTORICAL_START -->
# Histórico: Run1000 y Run10K con la misma interfaz limpia, servidores y datos independientes

2026-11-09, Guatemala. **Fase cerrada: replicación puntual de la limpieza aprobada**, sin rediseño ni nueva reconstrucción. [Run1000 limpio 8804](http://127.0.0.1:8804/index.html), fuente propia 8799; [Run10K limpio 8803](http://127.0.0.1:8803/index.html), fuente propia 8801, **referencia conservada intacta**. Run1000 original 8799 y los históricos restantes permanecen intactos. [Entrega y comandos](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/cleanup-run1000-20261109/README.md), [capturas comparativas](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/cleanup-run1000-20261109/browser/comparacion.html), [QA](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/cleanup-run1000-20261109/browser/qa-summary.json).

**Cambio mínimo.** Copia aislada de `cleanup.js`, `clean_viewer.py` y `start.ps1` aprobados, adaptando identidad, puerto y etiqueta de la casilla de aproximados para igualdad visual. No se modificaron archivos Run10K ni los compartidos de `visual/`. Run1000 retira los mismos bloques técnicos, Ayuda, totales inferiores y combobox duplicado; conserva hora, Dibujados, velocidad, todos los controles, filtros, colores y leyendas. Misma tarjeta flotante de 280 px, cierre sin perder selección/resaltado y ausencia de espacio residual. Los datos técnicos permanecen internos; el adaptador Run1000 conserva su alcance previo de buses, sin nueva reconstrucción privada.

**Verificación real: 258/258 PASS, exit 0**, Chrome/WebGL a 1920×1080 y 1366×768, sin excepciones JS. Textos, rectángulos y estilos de controles idénticos, con cámara/zoom/hora/filtros comparables; barras de 153.375/181.672 px y tarjetas seleccionadas de 280×135.984 px en ambos. Selección clic/ID, resaltado siguiendo al vehículo, tarjeta cerrable/reabrible, 1x/120x, pausa, saltos, filtros y ocultar/mostrar comprobados. Run1000 conserva conteos 07:00 **91**, 09:00 **94**, 11:05:25 **97**, 12:00 **97**, 17:00 **97**, 20:00 **80**. Tres fronteras: **3/3 precargadas** antes/después, tasa efectiva 119.54→119.80x y activaciones finales 0.6/0.5/0.8 ms, sin cambiar loader/caché. Se conserva un ensayo inicial cuya aserción comparaba tiempo interno entre frames; fue corregida para reloj visible/frame y repetida antes de publicar con control negativo, 8/8 PASS. No se alteró el motor.

**Identidades e integridad.** Run1000 LaunchId `a32f15487b1a49ac910ba799175658ca`, RunId `simz1-9d15f07ccc134aa69c60fdcbc887ea3f`, iteración 0. Run10K conserva las identidades documentadas en el cierre anterior. Revisión del parche 15/15 e integridad 27/27 PASS: metadatos de 751 nativos/replay y 159 protegidos intactos, 46 hashes clave y 19 fuentes de presentación intactos. [Cierre independiente](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/cleanup-run1000-20261109/integrity-after.json). Run10K HTML sigue `917f3831020822b17f6e2db292f8244fc6782c89a48cbd963186cde06977ab1a`; Run1000 limpio `98995ffa27a1ef1210577e3bd69e76f276efcde89a67840a04f15a0ebde88bc1`. Solo se reemplazó el proceso propio 8804 previa comprobación de PID/creación/padre/comando, nueva cadena `54812→59328`; originales y Run10K sin intervención.

No MATSim/QSim, Run, DryRun, Validate, reconstrucción SQLite/replay ni modificación de resultados, eventos, manifiestos, recibos o huellas productoras. El único archivo preexistente editado es este encabezado; el historial se conserva. **Siguiente acción:** abrir ambos visores; fuentes 8799/8801 deben seguir activas. Lanzadores vigentes: `cleanup-run1000-20261109/start.ps1` y `cleanup-20261109/start.ps1`, ambos reutilizados con exit 0, sin iniciar replays.

```powershell
Start-Process 'http://127.0.0.1:8804/index.html' # Run1000 limpio
Start-Process 'http://127.0.0.1:8803/index.html' # Run10K limpio
```

Seguimiento de solo lectura: `Invoke-RestMethod 'http://127.0.0.1:8804/api/presentation-build'`.
<!-- SIMZ1_RUN1000_CLEANUP_V1_HISTORICAL_END -->

<!-- SIMZ1_RUN10K_CLEANUP_V1_HISTORICAL_START -->
# Histórico: Run10K 8803 con interfaz limpia; reproducción y datos preservados

2026-11-09, Guatemala. **Fase cerrada: limpieza visual puntual**, sin nueva homologación ni reconstrucción. [Run10K limpio en 8803](http://127.0.0.1:8803/index.html), misma fuente reparada 8801. Run1000 8799 y su presentación adicional 8804 permanecen byte a byte intactos, al igual que 8801 y 8802. [Entrega y comandos](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/cleanup-20261109/README.md), [captura limpia](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/cleanup-20261109/browser/after/after-1920-overview.png), [antes/después](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/cleanup-20261109/browser/comparacion.html).

**Cambio autorizado.** Se retiraron del DOM visible dimensiones, lista de tipos, diagnóstico de aproximados/activos/omitidos, Ayuda, totales inferiores y selector de velocidad duplicado. Se conserva el contador **Dibujados junto al reloj**, botones 1x/120x, controles, filtros y leyendas de colores. La ficha pasa a tarjeta flotante de 280×136 px con ID, tipo/perfil y velocidad/tiempo de viaje cuando existen; cerrarla mantiene selección y resaltado. Los registros internos, dimensiones, métricas y procedencia permanecen íntegros. El mapa comienza inmediatamente después de los controles/leyenda, sin franja residual.

**Alcance mínimo y aislado.** Solo se añade `cleanup-20261109/cleanup.js`, aplicado mediante `clean_viewer.py` y su `start.ps1`, reutilizando la verificación y el servidor originales. Todos los archivos compartidos de `visual/` siguen idénticos; no se tocaron loader, caché, precarga, adaptadores, tamaños, colores, señales, selección temporal ni API. El HTML solo difiere por este parche y su metadato. Revisión `run10k-visual-cleanup-v1`, SHA256 `917f3831020822b17f6e2db292f8244fc6782c89a48cbd963186cde06977ab1a`. Se preservan RunId Run10K `simz1-cdffd75c4bdb47a7bfb507efe2c8c4e9`, LaunchId `e496c091b9ef46ee9ca381576135e299`, iteración 0, y la identidad Run1000 documentada abajo.

**Pruebas reales.** Chrome/WebGL 1920×1080 y 1366×768: antes **13/13**, después **171/171 PASS**, exit 0 y sin excepciones JS; 18 capturas. Se comprobaron clic/ID, resaltado siguiendo al vehículo, cierre/reapertura de tarjeta, 1x/120x, pausa/continuación, saltos ±1 h, filtros, barra oculta/restaurada y contador superior. Tres cruces con filtro de buses: **3/3 ventanas listas**, activación 1.5/1.4/0.6 ms, tasa efectiva 118.81x; mismos límites de precarga y memoria, sin nuevo ajuste de rendimiento. Conteos 07:00 **212**, 09:00 **255**, 11:05:25 **218**, 12:00 **212**, 17:00 **218**, 20:00 **220**, omitidos 0. [QA y mediciones](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/cleanup-20261109/browser/qa-summary.json). Las 175 pruebas y evidencias históricas se conservan; no se afirma repetir expectativas visuales de paneles retirados expresamente.

**Integridad y procesos.** Revisión 12/12 e integridad 24/24 PASS. Metadatos de 751 nativos/replay y 159 protegidos contrastados con el SHA completo previo; 46 manifiestos/fuentes clave rehasheados sin cambios. [Cierre](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/cleanup-20261109/integrity-after.json). Solo se reemplazó la fachada propia 8803 tras comprobar PID/creación/padre/comando; nueva cadena `55324→59852`, procesos originales y Run1000 intactos. No MATSim/QSim, Run, DryRun, Validate, reconstrucción SQLite/replay ni escritura de resultados/manifiestos/recibos. El historial y todos los archivos previos se conservan.

**Siguiente acción:** abrir 8803; su fuente 8801 debe seguir activa. El lanzador vigente de la interfaz limpia está en `cleanup-20261109/start.ps1`; el lanzador anterior conserva la revisión histórica. Ambos lanzadores, limpio Run10K y original Run1000, se reutilizaron con exit 0. Seguimiento de solo lectura: `Invoke-RestMethod 'http://127.0.0.1:8803/api/presentation-build'`.

```powershell
Start-Process 'http://127.0.0.1:8803/index.html'
```
<!-- SIMZ1_RUN10K_CLEANUP_V1_HISTORICAL_END -->

<!-- SIMZ1_THESIS_VIEWERS_V2_HISTORICAL_START -->
# Histórico: visores completos 8803/8804 y reproducción anticipada para tesis, con datos intactos

2026-11-09 00:20, Guatemala. **Fase: presentación, optimización de lectura/preparación y regresión.** Run10K completo en [8803](http://127.0.0.1:8803/index.html), fuente propia 8801; presentación adicional Run1000 autorizada expresamente en [8804](http://127.0.0.1:8804/index.html), fuente propia 8799. Instancias, identidades, datos y relojes independientes. **8799, 8800, 8801 y 8802 permanecen intactos.** No se ejecutaron MATSim/QSim, Run, Validate integrado, DryRun ni reconstrucción SQLite/replay. [Entrega](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/README.md), [estado final](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/final-status.json), [capturas](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/qa/comparacion.html), [contrato visual](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/visual/CONTRATO_TESIS_V2.md).

**Identidades conservadas, iteración 0.** Run1000 LaunchId `a32f15487b1a49ac910ba799175658ca`, RunId `simz1-9d15f07ccc134aa69c60fdcbc887ea3f`; Run10K LaunchId `e496c091b9ef46ee9ca381576135e299`, RunId `simz1-cdffd75c4bdb47a7bfb507efe2c8c4e9`. Nativas `completed/valid`, `screening_pass`. Permanece la discrepancia histórica del gateway Run10K `running/simulation_and_analysis` frente al cierre recuperado; no se alteraron recibos. Huella productora intacta `1db657d6f60b487c96d2180798e3d4beba8ed58be693de8617f22c5257bbdc17`.

**Causa de las pausas demostrada.** El backend de un lector servía configuración de una sucesora/dos ventanas/una petición total, y los controles impedían precargar pausado. La siguiente ventana podía estar solicitada pero no preparada al llegar a la frontera: a 120x solo hay un segundo real por ventana. 8802 además pedía datos sin compresión y omitía los encabezados de longitud/hash/tiempos originales; numerosos `setTimeout(0)` añadían espera durante preparación. Se midieron backend, HTTP, lectura/descompresión, parse, validaciones, Worker, espacio, preparación, aproximación y Deck; no se atribuyó el problema exclusivamente a SQLite. [Diagnóstico y datos](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/performance/README.md).

**Corrección aislada.** Tres sucesoras y cuatro ventanas retenidas, precarga útil durante pausa, una petición de red de ventanas y hasta dos fases solapadas de descarga/preparación. Presupuesto original conservado: 128 MiB base / 512 MiB máximo de JSON. `scheduler.yield()` mantiene los mismos registros, validaciones y cancelaciones evitando el mínimo de temporización del fallback. Proxy gzip en bloques de 64 KiB, sin nuevo lector SQLite ni caché duplicada, con SHA/longitud, `Server-Timing`, errores y `Retry-After` originales. Se conservaron validadores, adaptadores VIS-01/VIS-02, intervalos, rutas, censura, anclajes y último frame válido. No se fabricó movimiento ni avance de reloj durante buffering.

**Medición final antes/después, Chrome/WebGL real.** Comparación controlada con backend calentado: 21 fronteras, listas **1/21→21/21**, tardías **20→0**, espera **p50 498.7→0.6 ms**, **p95 811.9→0.9 ms**. Casos solicitados de cuatro minutos a 120x: tasa efectiva final **119.06–119.64x**, sin presentarla como 120x exactos. Recorrido ampliado 07:58–08:10: **70.43→119.64x**, seis fronteras listas. Heap máximo muestreado 614.3→672.7 MiB; caché JSON 74.4→137.3 MiB, bajo el techo vigente. Selección durante reproducción en la revisión final: bus **118.44x**, carro **119.27x**, cuatro fronteras listas; pausa y saltos ±1 h comprobados. [Informe](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/performance/report.json), [79 respuestas y fases](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/performance/windows.csv), [interacciones](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/performance/interactions.json). Una espera intermedia de 296.2 ms se conserva; no se promete ausencia de buffering en las 720 ventanas, caché fría u otros equipos.

**Interfaz completa.** Hora válida, Dibujados y velocidad; todos los controles de reproducción, 12 h, −60 s, ±1 h, familia/ruta/sistema, aproximados, ID, barra 0–24 h y ocultar/mostrar; leyendas visibles. Panel inferior independiente: Run1000 **990 particulares / 269 buses físicos / 10 camiones**; Run10K **9900 / 269 / 100**. Son totales configurados del día, no activos ni 13261 expediciones. Ficha con identidad, perfil, ruta/expedición, enlace/corredor, hora, estimación/procedencia de velocidad, dimensiones y limitaciones. Un hallazgo visual corrigió la ficha larga que tapaba el panel inferior: ahora respeta el área del mapa, deja separación de 8 px y usa scroll, también al ocultar/restaurar la barra. Solo se reiniciaron las fachadas propias tras comprobar PID/creación/padre/comando; originales preservados.

**Dimensiones y colores.** Catálogos congelados efectivos de ambas corridas: moto 2.1×0.8 m, carro 4.5×1.8, camión **8×2.3**, TuBus 12×2.5, Transmetro 13.5×2.5. Servicio `weekday-compact-v3` documenta el cambio histórico 12→8 m; no se usó un tipo declarado sin unidades como sustituto. [Fuentes/hashes y 15 comprobaciones](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/dimensions/README.md). Símbolos proporcionales con escala gráfica común 0.5 y mínimo cenital 2 px por metro nominal usando Deck/WebMercator 512; no son cuerpos físicos a escala. Privados/camiones usan el evaluador existente solo con plan válido o procedencia suficiente; gris desconocido nunca se convierte en cero. Transmetro verde/TuBus azul representan sistema. Las dimensiones, extremos, velocidades físicas o separaciones no se certifican por estos símbolos; geometría local aproximada, no GIS verificada.

**Regresiones.** 175 heredadas repetidas PASS; 647 controles integrales Chrome en 1920×1080 y 1366×768 PASS; después del ajuste final de ficha, **237 controles focales PASS**, cero excepciones JS. HTTP503 controlado: último reloj/frame válido conservado, objetivo pendiente separado, reintento tras 2006 ms respetando `Retry-After: 2`, recuperación correcta. Se preservaron intentos QA anteriores: la comparación de cámara se acotó a sus parámetros geográficos porque la altura del viewport debe cambiar al ocultar la barra; se añadió control negativo de zoom. [Resumen QA](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/qa/qa-summary.json), [647](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/qa/final-verified/browser-results.json), [237 finales](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/qa/post-layout-verified/browser-results.json). Además: pipeline 35, 17 escenarios loader y política parcial, estilo 29, integración UI 6, proyección WebGL 3, layout 9 y proxy HTTP 12, todos PASS0. Adaptadores y funciones nativas protegidas conservados.

**Conteos Run10K sin divergencias, en ambas resoluciones.** 07:00 **212**, 09:00 **255**, 11:05:25 **218**, 12:00 **212**, 17:00 **218**, 20:00 **220**: activos=elegibles=dibujados, omitidos 0, IDs y expediciones únicos. El adaptador original Run1000 sigue representando su propio alcance de buses; no se inventó reconstrucción privada para igualar cantidades entre corridas.

**Integridad y revisión.** 751/751 archivos nativos/replay (10,441,106,231 bytes) y 159/159 protegidos, SHA256 completo antes/después intacto; ajuste posterior exclusivamente de layout contrastado aparte sin repetir el escaneo grande. SQLite Run1000 `08656d7ec2c2c4f71519b084801c380bc75445a8d6ca45c6625695f3b0e470ee`; Run10K `ec6cbb69b17280debbb311ccbd6c4fd1536ead8fc6cda20d262ba7ef1df00790`. [Integridad](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/integrity/after.json), [revisión independiente](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/integrity/independent-code-review-final.json). Versión visual `simz1-thesis-viewer-v2`, separada de la productora: HTML final Run10K `8c71c1157128960632469012ec094552e2231569bc300f81e419abd8ad439837`; Run1000 `036f620bfba0234949388488be8b0822f365098f04351787285a7b450e270819`. No se modificaron fuentes productivas ni se excluyeron dependencias del fingerprint.

**Procesos y cierre final.** [Verificación final del layout](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/integrity/layout-closure.json) PASS0; [procesos con creación/padre/comando](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/integrity/viewer-processes-layout-final.json): originales 8799 `43188→23892`, 8801 `53956→53340`, 8802 `5380→31736`; fachadas finales 8803 `54412→58652` y 8804 `58860→55652`. Sin JVM SimZ1 observada. Reutilización de ambos lanzadores nuevos exit 0, sin iniciar replays. Las [175 regresiones se repitieron sobre el HTML final](../runtime/diagnostics/run10k-v8-thesis-viewer-20261108/browser/regression-post-layout/browser-results.json), PASS0; los hashes completos anteriores permanecen como evidencia y los metadatos/manifiestos/fuentes protegidas volvieron a comprobarse tras el cambio exclusivamente visual.

**Siguiente acción:** abrir las dos presentaciones y seleccionar hora; la pausa permite preparar sucesoras antes de 120x. Las fuentes 8801/8799 deben permanecer activas. Sus lanzadores históricos conservan las guardas de huella global previas; esta revisión no las elude, ni autoriza otra corrida. Los comandos de arranque/reutilización y seguimiento están en la entrega.

```powershell
Start-Process 'http://127.0.0.1:8803/index.html?run_id=simz1-cdffd75c4bdb47a7bfb507efe2c8c4e9&iteration=0'
Start-Process 'http://127.0.0.1:8804/index.html?run_id=simz1-9d15f07ccc134aa69c60fdcbc887ea3f&iteration=0'
```

Seguimiento de solo lectura fuera del editor:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8803/api/presentation-build' | ConvertTo-Json -Depth 5
Invoke-RestMethod 'http://127.0.0.1:8803/api/presentation-metrics' | ConvertTo-Json -Depth 6
Get-Content -Encoding UTF8 .\runtime\diagnostics\run10k-v8-thesis-viewer-20261108\final-status.json
```

Los archivos previos no rastreados y todos los cierres anteriores se conservan. Único archivo preexistente editado en esta tarea: este encabezado. Nuevos archivos operativos, pruebas, mediciones y capturas están en la carpeta aislada `runtime/diagnostics/run10k-v8-thesis-viewer-20261108/`.
<!-- SIMZ1_THESIS_VIEWERS_V2_HISTORICAL_END -->

<!-- SIMZ1_VISUAL_PARITY_V1_HISTORICAL_START -->
# Histórico: Run10K homologado visualmente con Run1000; reconstrucción y resultados preservados

2026-11-08 22:40, Guatemala. **Fase cerrada: presentación y regresión, sin simulación ni reconstrucción de replay.** Run1000 de referencia sigue en [8799](http://127.0.0.1:8799/index.html). La revisión Run10K está en [8802](http://127.0.0.1:8802/index.html), aislada y con su API propia Run10K 8801 como fuente; el visor reparado **8801 permanece íntegro**, al igual que 8800. No hay dependencia Run10K→Run1000. [Entrega, diferencias antes/después y comandos](../runtime/diagnostics/simz1-visual-parity-20261108/README.md), [contrato visual exacto](../runtime/diagnostics/simz1-visual-parity-20261108/visual/CONTRATO_VISUAL_V1.md), [capturas lado a lado](../runtime/diagnostics/simz1-visual-parity-20261108/browser/comparacion.html), [estado final](../runtime/diagnostics/simz1-visual-parity-20261108/final-status.json).

**Identidades.** Run1000 LaunchId `a32f15487b1a49ac910ba799175658ca`, RunId `simz1-9d15f07ccc134aa69c60fdcbc887ea3f`; Run10K LaunchId `e496c091b9ef46ee9ca381576135e299`, RunId `simz1-cdffd75c4bdb47a7bfb507efe2c8c4e9`; iteración 0. Nativas `completed/valid`, `screening_pass`, sin cambios. Se conserva la discrepancia histórica del gateway Run10K `running/simulation_and_analysis` y su cierre recuperado; no se editaron recibos. Huella productora intacta `1db657d6f60b487c96d2180798e3d4beba8ed58be693de8617f22c5257bbdc17`.

**Causa y cambio acotado.** Comparación del HTML realmente servido: barra Run10K 1050 px frente a 720 px; símbolos con mínimo 3.5 px/extremos redondos frente a mínimo 0/extremos rectos; buses 2.8×1.6 frente a cuadrados compactos 1.4×1.4 m. Se homologaron únicamente presentación, leyendas y huella gráfica de selección. El adaptador `vehicle_approximation.js`, VIS-01/VIS-02, loader, API, reconstrucción temporal, censura, rutas y posiciones permanecen idénticos. Revisión `simz1-run1000-visual-v1`, HTML SHA256 `b55d39328825010db0d85428bf9e458ee6f52ccdf1dc184dd78ec731156ada80`, separado de la huella experimental. [Auditoría previa](../runtime/diagnostics/simz1-visual-parity-20261108/audit/served-before.json), [revisión independiente de 19 controles](../runtime/diagnostics/simz1-visual-parity-20261108/integrity/independent-code-review-final.json).

**Semántica visual.** Barra principal con CSS y rectángulos idénticos; Run10K conserva conteos y Ayuda en un panel sobre el mapa. Buses mantienen colores de sistema y el cuadrado aproximado aceptado; dimensiones nominales Transmetro/TuBus distintas en la ficha. Privados usan dimensiones del catálogo existente y gris de velocidad desconocida; camión usa violeta de referencia. Tortuga/normal/liebre conservan sus etiquetas, sin inferir velocidad del perfil. La referencia no representa privados aproximados en las ventanas comparadas: su extensión de catálogo se prueba por código/accesores, no por capturas ficticias. Los símbolos no certifican posiciones corporales, separación ni velocidad física; geometría local aproximada, no GIS verificada.

**Regresión y Chrome real.** 175/175 comprobaciones heredadas PASS, nombres/orden y evidencias anteriores conservados; 86/86 nuevas comprobaciones de presentación/interacción PASS; 20/20 smoke posterior al reinicio de la fachada PASS, códigos 0. WebGL2/ANGLE Intel UHD D3D11, sin excepciones JS ni pérdida de contexto. Pausa, 1x/120x, slider, filtros, ID/ruta, entrada/salida, L12/TuBus, carro/moto/camión y respuestas obsoletas verificados. Conteos Run10K nativos=elegibles=dibujados: 07:00 **212**, 09:00 **255**, 11:05:25 **218**, 12:00 **212**, 17:00 **218**, 20:00 **220**; omitidos 0 en todos. IDs físicos y expediciones únicos en los seis horarios. [QA](../runtime/diagnostics/simz1-visual-parity-20261108/browser/qa-summary.json), [175 nuevas](../runtime/diagnostics/simz1-visual-parity-20261108/browser/regression-final/browser-results.json), [unicidad](../runtime/diagnostics/simz1-visual-parity-20261108/browser/uniqueness-six-times.json). Cuatro pares de capturas a 1440×960, cámara/zoom/filtros iguales; selecciones a zoom 20 inspeccionadas. No se exige igual cantidad de vehículos entre corridas.

**Pruebas adicionales.** Adaptador 121 y VIS-01/VIS-02 44 controles PASS; loader y política parcial PASS; presentación 42 controles con negativos de alteración/ausencia PASS; API real 8, identidad negativa 10 y proxy 9 fixtures PASS. Se corrigió durante la revisión un encabezado `Retry-After` que el proxy debía conservar; HTML idéntico después y smoke posterior PASS. No se ejecutaron Validate, DryRun, Run, MATSim/QSim, compilación Java ni preparación SQLite/replay. [Regresiones](../runtime/diagnostics/simz1-visual-parity-20261108/tests/results.json).

**Integridad y procesos.** 751/751 archivos nativos/replay de ambas corridas, 10,441,106,231 bytes, SHA256 completo incremental antes/después sin cambios; 96 artefactos protegidos y las seis fuentes originales 8801 intactos. SQLite Run1000 `08656d7ec2c2c4f71519b084801c380bc75445a8d6ca45c6625695f3b0e470ee`; Run10K `ec6cbb69b17280debbb311ccbd6c4fd1536ead8fc6cda20d262ba7ef1df00790`. Manifiestos y ambos replays conservan sus hashes. [Integridad](../runtime/diagnostics/simz1-visual-parity-20261108/integrity/after.json). Procesos comprobados por PID/creación/padre/comando: originales 8799 `43188→23892`, 8801 `53956→53340`; fachada final 8802 `5380→31736`; sin JVM SimZ1 observada. Se reinició solo la fachada propia, con [evidencia](../runtime/diagnostics/simz1-visual-parity-20261108/visual/restart-receipt.json); su reutilización posterior dio exit 0. [Procesos finales](../runtime/diagnostics/simz1-visual-parity-20261108/integrity/processes-after.json).

**Siguiente acción:** abrir los dos visores existentes por separado y consultar las capturas/contrato. La fachada 8802 requiere su fuente 8801 activa. Los lanzadores históricos rechazarían la huella global actual por los cambios previos de tesis; no se eludió esa guarda ni se modificaron recibos. [Diagnóstico de huella](../runtime/diagnostics/simz1-visual-parity-20261108/integrity/current-source-fingerprint.json). Si se cierran esos servidores, resolver la transición de fuentes mediante su flujo original antes de arrancarlos; esta entrega no autoriza otra simulación.

```powershell
Start-Process 'http://127.0.0.1:8799/index.html'
Start-Process 'http://127.0.0.1:8802/index.html'
```

Seguimiento de solo lectura fuera del editor:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8802/api/presentation-build' | ConvertTo-Json -Depth 6
Get-Content -Encoding UTF8 .\runtime\diagnostics\simz1-visual-parity-20261108\final-status.json
```

Se preservan todos los cambios previos y archivos no rastreados. Único archivo preexistente editado en esta tarea: este encabezado; el resto está en la carpeta aislada de entrega. La colección de tesis y todos los cierres anteriores se conservan abajo como históricos.
<!-- SIMZ1_VISUAL_PARITY_V1_HISTORICAL_END -->

<!-- THESIS_V2_COLLECTION_HISTORICAL_START -->
# Histórico: colecci?n de tesis v2 1K/10K completa y verificada

2026-11-08 22:01, Guatemala. **82 figuras de las dos corridas solicitadas: 60 nuevas y 22 antecedentes de Run1000 conservados; 18 copias seleccionadas para tesis.** 33 figuras en Run1000, 26 en Run10K, 12 comparativas y 11 mapas. Cada figura final tiene PNG de 300 dpi, SVG y CSV/JSON; **400 artefactos verificados** incluyendo selecci?n, con 52 fuentes comprobadas por SHA. [?ndice y cobertura de objetivos](../graficas_tesis_v2/INDICE_GENERAL.md), [manifest](../graficas_tesis_v2/manifest.json), [verificaci?n](../graficas_tesis_v2/verification.json), [selecci?n](../graficas_tesis_v2/figuras-seleccionadas-tesis/README.md). Los 20 PNG anal?ticos nativos se inventar?an aparte; no se cuentan como figuras nuevas. Las carpetas hist?ricas de tesis quedan intactas y excluidas del cat?logo final.

**Identidades preservadas, iteraci?n 0, horizonte 0?86400 s.** Run1000: LaunchId `a32f15487b1a49ac910ba799175658ca`, RunId `simz1-9d15f07ccc134aa69c60fdcbc887ea3f`; Run10K: LaunchId `e496c091b9ef46ee9ca381576135e299`, RunId `simz1-cdffd75c4bdb47a7bfb507efe2c8c4e9`. Ambas nativas `completed/valid`, `screening_pass`; Run10K mantiene su [recuperaci?n 57c61494b1804a3cbaff53f7afdf797a](../runtime/recoveries/57c61494b1804a3cbaff53f7afdf797a/recovery-receipt.json), y el gateway original sigue hist?ricamente `running/simulation_and_analysis`. No se alteraron recibos para aparentar concordancia ni se promovi? otra escala.

**Fase y alcance.** Se cerr? exclusivamente posprocesamiento y documentaci?n: no MATSim/QSim, Run, Validate, DryRun, compilaci?n Java ni preparaci?n nueva del replay. Auditor?a, mapas, comparativas y figuras por corrida tuvieron responsables separados; integraci?n y entrada ?nica secuenciales. Red realmente simulada: 4257 nodos, 6240 enlaces, 163 sistemas semaf?ricos/312 accesos controlados. `map.osm` ra?z est? ausente; existe el de `scenarios/zona1`, contrastado con snapshot nativo. Geometr?a local aproximada, no GIS verificada. Se conservan Java, pol?ticas, flotas, OD, rutas, semillas, se?ales y fuentes nativas.

**Causa de la ampliaci?n.** Faltaban una colecci?n Run10K equivalente, flujo/acumulaci?n espacial y A?B medido. Se reutilizaron CSV/JSON publicados y se cre? una vez por corrida un agregado aislado del SQLite existente, usando el constructor nativo de asociaci?n sin modificarlo (807095 y 1374858 segmentos). No se reley? XML de eventos. La cach? y sus CSV verifican procedencia y reutilizaci?n sin otro escaneo. Integrales asociadas = nativas: 6003954 y 14339608 s-veh; picos globales 126 y 310 veh?culos. Asociaci?n es proxy de acumulaci?n por enlace, no posici?n corporal ni cola de intersecci?n.

**Frontera temporal comprobada.** En Run10K, 1252416 transiciones nativas incluidas al corte menos 14 exactamente a 86400 =1252402 LinkEnter representados en [0,86400). Esos 14 tienen receptor en el censo, pero no intervalo replay posterior de duraci?n positiva; por eso hay 88 asociados frente a 102 activos exactamente al corte. No se inventaron intervalos ni se confundieron esos datos con p?rdida de cobertura integral. [Evidencia por ID y fuentes](../graficas_tesis_v2/datos-espaciales/cut-boundary-review.json).

**Resultados e interpretaci?n.** N es no p?blico: 1000/10000; permanecen 269 buses f?sicos y 13261 expediciones programadas. Privados completos 988/9700, censurados 2/200; camiones completos 10/100; buses completos 9952/9610, no iniciados 3309/3651. Tiempos de completos incluyen incorporaci?n: carros media 8.605?40.999 min; en 10K se descompone en 26.588 min esperando entrada y 14.411 min entrada?llegada para la misma cohorte completa. Las medias no sustituyen mediana/colas de distribuci?n. A?B: cuatro pares comunes observados, n1K/n10K=36/273,32/356,26/231,26/290, selecci?n exploratoria posterior y censura declarada aparte. No acredita efecto causal independiente de sem?foros, composici?n o condiciones externas, ni calibraci?n. La comparaci?n estricta por bytes permanece rechazada; se documenta igualdad sem?ntica de red y horarios y diferencias de metadatos/hashes.

**Verificaci?n y revisi?n.** 17 regresiones existentes de asociaci?n, 4 pruebas del extractor, 6 de m?tricas por corrida, 10 comparativas, 2 de mapas y 5 de integraci?n/lock/scope: 44 pruebas PASS0. El primer cat?logo de integraci?n recogi? derivados hist?ricos presentes en la ra?z; se acot? por carpetas e identidades expl?citas y se a?adieron negativos de identidad y exclusi?n hist?rica antes de la entrega final. No se borraron esos hist?ricos. Entrada ?nica final completa exit0, cach? reutilizada, todas las fases y c?digos en [logs](../graficas_tesis_v2/logs/). [Revisi?n visual](../graficas_tesis_v2/logs/visual-review.json): 18 seleccionadas en 3 l?minas y originales representativos de mapas/comparativas; no se proclama inspecci?n individual nueva de cada figura no seleccionada.

**Integridad y revisi?n de posproceso.** 751/751 archivos de las dos carpetas nativas mantienen tama?o/mtime; 694 peque?os tambi?n SHA256. Los manifiestos, tablas consumidas e identidades del replay se verifican adicionalmente; el chequeo final no rehace el SHA de eventos/SQLite multi-GB. [Procesos antes](../graficas_tesis_v2/logs/processes-before.json), [despu?s](../graficas_tesis_v2/logs/processes-after.json): sin JVM de simulaci?n observada; IDE y servidores existentes preservados. Versi?n de colecci?n `simz1-thesis-collection-v2.2`; revisi?n agregada de scripts `0cb4c5330b0049877a4726119520ef205be3553fab32d1d34401d6517f45775a` en manifest, separada de la huella experimental productora. Scripts nuevos Python/PowerShell pueden afectar la huella del pr?ximo lanzamiento: se mantiene el control existente, sin excluir dependencias ni actualizar recibos.

**Siguiente acci?n:** consultar el ?ndice y la selecci?n para redactar resultados. Regeneraci?n exclusiva de figuras desde PowerShell externa:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
.\scripts\generate_thesis_graphs_v2.ps1
```

Seguimiento de solo lectura:

```powershell
Get-Content -Encoding UTF8 .\graficas_tesis_v2\logs\collection-progress.json
Get-Content -Encoding UTF8 .\graficas_tesis_v2\verification.json
```

`-VerifyOnly` comprueba entrega; `-ForceFigures` fuerza n?cleo Run10K y complementos conservando antecedentes 1K. No autoriza ni requiere otra simulaci?n. El estado anterior del visor se conserva abajo como hist?rico.
<!-- THESIS_V2_COLLECTION_HISTORICAL_END -->

<!-- RUN10K_V8_VISUAL_REPAIR_HISTORICAL_START -->
# Hist?rico: visor Run10K v8 corregido en 8801; vehículos representados y Chrome/WebGL verificado

2026-11-08, Guatemala, cierre visual 21:08. **Entrega visual verificada con 175 comprobaciones PASS0 en Chrome real headless, WebGL2/ANGLE Intel UHD Graphics D3D11, y 17 capturas.** No se repitió MATSim/QSim, Run, DryRun, Validate ni la preparación completa del replay. LaunchId `e496c091b9ef46ee9ca381576135e299`, RunId `simz1-cdffd75c4bdb47a7bfb507efe2c8c4e9`, iteración `0`; carpeta `scenarios/zona1/montecarlo/run-bg10-e496c091b9ef46ee9ca381576135e299`. Estado nativo preservado `completed/valid`, `screening_pass`. [Estado final de esta reparación](../runtime/diagnostics/run10k-v8-visual-repair-20261108/final-status.json).

**Causa demostrada de Dibujados 0.** La ventana API 332, 11:04–11:06 (39840–39960 s), contiene 2615 segmentos; a las 11:05:25 hay 218 intervalos activos únicos. `partial-native-v1` publica `queue_context.availability=not_reconstructed`; `pending_queue_context()` marca las semillas `reconstruction_pending` y el renderizador estricto omite todos sus cuerpos. El visor oficial 8800 no incorporaba el adaptador aislado VIS-01/VIS-02 de Run1000. Chrome reprodujo cero en los seis horarios, con capa `trips` visible, reloj/frame concordantes, sin excepciones JS y sin pérdida de contexto WebGL. No era falta de tráfico, filtro activo, escala de coordenadas ni corrupción demostrada del SQLite. [API original](../runtime/diagnostics/run10k-v8-visual-repair-20261108/api/window-332-summary.json), [baseline Chrome](../runtime/diagnostics/run10k-v8-visual-repair-20261108/browser-baseline/browser-results.json), [captura original 11:05:25](../runtime/diagnostics/run10k-v8-visual-repair-20261108/browser-baseline/hour-39925.png).

**Corrección aislada.** Se reutilizó VIS-01/VIS-02 y se añadió el adaptador de presencia de todas las familias, alimentado exclusivamente por intervalos y segmentos de esta Run10K. El roster de 19610 viajes se deriva de los metadatos SQLite existentes; los censos CSV oficiales permiten un contraste independiente. No se copiaron vehículos ni bases de Run1000. Cada símbolo exige ID físico, viaje, intervalo nativo inclusivo/exclusivo, enlace y referencia temporal válidos. Las cotas nativas conservan su referencia de corredor y procedencia lateral; los símbolos no certifican cuerpos, velocidades, distancias, colisiones ni separaciones. No continúan después de la salida del tráfico ni duplican un bus entre expediciones. La omisión permanece cuando no hay soporte suficiente. Las pruebas negativas cubren esas condiciones.

Los colores y formas compactas distinguen carros/motos normales, liebres y tortugas, camiones, Transmetro y TuBus. Su ancho mínimo en pantalla mejora legibilidad sin cambiar la posición ni dimensiones nominales. Selección muestra ID, ruta y explicación de aproximación. Se conserva barra temporal, reproducción, velocidades 1x/120x y filtros. Un `replaceChildren()` heredado desconectaba los contadores y Ayuda en la interfaz simplificada: ambos vuelven a estar visibles, con diagnósticos detallados dentro de Ayuda. Los marcadores de estaciones/paradas nunca integran el contador de vehículos.

**Conciliación final sin filtros; unidades: vehículos físicos simultáneamente activos.** En cada fila, activos nativos = intervalos válidos = elegibles por enlace/tiempo = símbolos aproximados = enviados a la capa `trips`, con igualdad de todos los IDs y claves de viaje. Cuerpos físicos estrictamente representables: **0 en los seis horarios**; esa reconstrucción sigue pendiente. Las omisiones por falta de enlace, reconstrucción sin sustituto o filtros son **0** en estas seis vistas. El total diario de 269 buses físicos no se confunde con expediciones ni activos simultáneos.

| Hora | Carros | Motos | Camiones | Transmetro | TuBus | Nativos = elegibles = aproximados = dibujados | Omitidos | Personas privadas esperando entrada | Expediciones bus esperando entrada |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 11:05:25 | 58 | 65 | 1 | 78 | 16 | 218 | 0 | 183 | 8 |
| 07:00 | 50 | 69 | 0 | 69 | 24 | 212 | 0 | 0 | 7 |
| 09:00 | 70 | 86 | 0 | 73 | 26 | 255 | 0 | 240 | 8 |
| 12:00 | 58 | 60 | 1 | 76 | 17 | 212 | 0 | 193 | 6 |
| 17:00 | 55 | 66 | 0 | 75 | 22 | 218 | 0 | 278 | 2 |
| 20:00 | 67 | 77 | 0 | 76 | 0 | 220 | 0 | 481 | 1 |

Las expediciones activas de bus y sus IDs físicos activos coinciden: 94, 93, 99, 93, 97 y 76, respectivamente. A las 20:00, TuBus=0 procede del censo nativo. Esperar incorporación no crea un símbolo circulante. [Conteos nativos por familia/ID](../runtime/diagnostics/run10k-v8-visual-repair-20261108/native/native-counts.json), [conciliación SQLite→JS→Deck](../runtime/diagnostics/run10k-v8-visual-repair-20261108/counts-reconciliation.json).

**Verificación real.** [Chrome final PASS175](../runtime/diagnostics/run10k-v8-visual-repair-20261108/browser-final/browser-results.json): seis horarios, diez muestras de familias/perfiles, L12, TuBus y camión, selección con ruta completa, picking WebGL real, clic sobre `freight_000046`, veinte controles antes/después de entrada/salida, filtros de tipo/ruta, reproducción a 1x/120x cruzando ventanas y tres seeks consecutivos con respuestas obsoletas descartadas. A 11:05:25→11:05:26 cambian 37 símbolos conforme a su soporte temporal; no son posiciones continuas medidas. Reloj, consulta y frame permanecen concordantes; cero excepciones JS y contexto WebGL conservado. El 403 de favicon corresponde a la allowlist estática y las solicitudes abortadas corresponden a seeks sustituidos. Las regresiones existentes del loader cubren además respuestas fuera de orden, 503, cancelación, reloj congelado durante carga y cache acotada.

[Captura 11:05:25 con 218 símbolos](../runtime/diagnostics/run10k-v8-visual-repair-20261108/browser-final/hour-39925.png), [07:00](../runtime/diagnostics/run10k-v8-visual-repair-20261108/browser-final/hour-25200.png), [09:00](../runtime/diagnostics/run10k-v8-visual-repair-20261108/browser-final/hour-32400.png), [12:00](../runtime/diagnostics/run10k-v8-visual-repair-20261108/browser-final/hour-43200.png), [17:00](../runtime/diagnostics/run10k-v8-visual-repair-20261108/browser-final/hour-61200.png), [20:00](../runtime/diagnostics/run10k-v8-visual-repair-20261108/browser-final/hour-72000.png), [L12 seleccionado](../runtime/diagnostics/run10k-v8-visual-repair-20261108/browser-final/selected-transmetro_L12.png), [camión seleccionado](../runtime/diagnostics/run10k-v8-visual-repair-20261108/browser-final/selected-truck.png). Inspeccionadas visualmente la vista final, L12 y camión; se conservaron las demás capturas. El canal interactivo Computer Use estaba indisponible; estas pruebas se realizaron mediante el arnés Chrome existente, sin DOM simulado. Dibujados cuenta instancias enviadas a Deck, incluidas fuera de cámara; no garantiza un píxel distinguible por vehículo si se superponen. La geometría local sigue siendo aproximada, no cartografía GIS verificada.

**Archivos y pruebas.** Instancia [visual/](../runtime/diagnostics/run10k-v8-visual-repair-20261108/visual/): `vehicle_approximation.js` nuevo; `bus_approximation.js` reutilizado sin cambios; adaptaciones aisladas de `visualizador_z1_controls.js`, `visualizador_z1_continuous.html`, `serve_bus_viewer.py` y `start.ps1`. Ningún archivo productivo de `python/` fue modificado por esta reparación. 121 comprobaciones del adaptador, 44 VIS-01/VIS-02, 7 pruebas de identidad y 7 de conciliación nativa, todas PASS0; regresiones loader/partial PASS0. [Revisión independiente de 18 controles y hashes](../runtime/diagnostics/run10k-v8-visual-repair-20261108/integrity/independent-code-review-final.json). Primera batería real PASS139 preservada; justificó la corrección DOM/legibilidad y contadores de filtro antes de la batería final. No se relajó ningún auditor físico.

**Integridad PASS0.** [Comprobación SHA incremental final](../runtime/diagnostics/run10k-v8-visual-repair-20261108/integrity/after.json): 89/89 artefactos nativos sin cambios; SQLite de 4229419008 bytes conserva SHA256 `ec6cbb69b17280debbb311ccbd6c4fd1536ead8fc6cda20d262ba7ef1df00790`. Manifiesto nativo `8d51af2202ceb29ec32aa782f18fa05440436c1fb6a879beeb8f11a086e3213f`, recibo de recuperación `57c61494b1804a3cbaff53f7afdf797a` y huella productora `1db657d6f60b487c96d2180798e3d4beba8ed58be693de8617f22c5257bbdc17` intactos. Las 772 dependencias mantienen la huella revisada de recuperación `38d811815cd80f2f2268ab5263c030ead8ebec5b6b5404471d604e9ce12a98bd`, separada de la productora. La revisión visual es `bccaa1b726dc36f57e18d5fca2529f64066095537579a827e92870eab9424a3a`, también separada. El gateway original sigue históricamente `running/simulation_and_analysis`; no se editó para ocultar su discrepancia con el cierre recuperado.

**Servidor definitivo 8801.** El inventario de sockets de 8800 devolvía propiedad no concluyente; se conservaron 8800 y 8799. Se reinició exclusivamente la cadena propia de prueba 8801, comprobando PID/creación/padre/comando antes de cada terminación. [Antes del reinicio](../runtime/diagnostics/run10k-v8-visual-repair-20261108/restart-before.json), [motivo y cierre propio](../runtime/diagnostics/run10k-v8-visual-repair-20261108/restart-receipt.json), [procesos finales](../runtime/diagnostics/run10k-v8-visual-repair-20261108/processes-final.json). Un lector, prioridad baja y SQLite de solo lectura; reutilización del lanzador PASS0, rechazo HTTP400 de identidad ajena/horizonte incorrecto. Ninguna JVM SimZ1 observada.

[Abrir visor Run10K corregido](http://127.0.0.1:8801/index.html?run_id=simz1-cdffd75c4bdb47a7bfb507efe2c8c4e9&iteration=0&run_manifest_sha256=8d51af2202ceb29ec32aa782f18fa05440436c1fb6a879beeb8f11a086e3213f&source_version=c67ad110071192ffa42a2a0c143070d85c717fdba365833eb2b3984a4148dc06&visual_policy=partial-native-v1). Apertura/reutilización desde PowerShell externa:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\runtime\diagnostics\run10k-v8-visual-repair-20261108\visual\start.ps1 -Open
$viewerExit = $LASTEXITCODE
if ($viewerExit -ne 0) { throw "Visor rechazado: $viewerExit. Revisar logs; no repetir QSim ni el replay." }
```

Seguimiento de solo lectura:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8801/api/visual-build' | ConvertTo-Json -Depth 5
Get-Content -Encoding UTF8 .\runtime\diagnostics\run10k-v8-visual-repair-20261108\final-status.json
Get-Content -Encoding UTF8 .\runtime\diagnostics\run10k-v8-visual-repair-20261108\visual\server-20261108-210348.log -Tail 10
```

**Siguiente acción:** abrir 8801 y navegar al instante deseado. Entrega visual aproximada verificada; no se autoriza otra simulación, escala ni modificación física. La aceptación nativa no equivale a calibración ni a reconstrucción corporal continua.
<!-- RUN10K_V8_VISUAL_REPAIR_HISTORICAL_END -->

<!-- RUN10K_V8_RECOVERY_HISTORICAL_START -->
# Histórico: Run10K v8 recuperada completed/valid; screening_pass; replay publicado y HTTP verificado

2026-11-08, Guatemala. **Recuperación nativa y posprocesamiento terminados con código 0, sin volver a ejecutar MATSim/QSim.** LaunchId `e496c091b9ef46ee9ca381576135e299`, RunId `simz1-cdffd75c4bdb47a7bfb507efe2c8c4e9`, iteración `0`, carpeta `scenarios/zona1/montecarlo/run-bg10-e496c091b9ef46ee9ca381576135e299`. Experimento `final-20261108-transit-service-24h-v8.json`, horizonte completo 0–86400 s, política `native_diagnostic_v1`. Validación nativa publicada a las **19:29:34 Guatemala** y cierre recuperado a las **19:30:07**. [Recibo oficial nuevo](../runtime/recoveries/57c61494b1804a3cbaff53f7afdf797a/recovery-receipt.json), RecoveryId `57c61494b1804a3cbaff53f7afdf797a`; `closure_recovered`, `completed/valid`, `screening_pass`, exit 0. No se publicó aceptación para otra carga ni se cambió el trial Run1000.

**Interrupción y procedimiento.** El original ya registraba `returncode=0/natural_exit`, `running/validating`, validación `pending`, último paso nativo 86400 s y cierre de iteración/Maven. El log ubica la interrupción dentro de `validate_outputs`; no identifica su línea interna exacta. La recuperación explícita añadió una entrada al flujo existente para este estado huérfano, comprobó identidad/huella/salida natural ya persistida y ausencia concluyente de escritores, y reutilizó **íntegramente `simz1_run.validate_outputs()` sin modificar sus criterios**. El manifiesto solo se publicó tras el éxito de todos sus auditores y las comprobaciones de integridad.

**Historia preservada.** El gateway original mantiene `running/simulation_and_analysis` y su `finished_utc` histórico incongruente: no se editó para aparentar cierre. El nuevo recibo acredita la recuperación. [Request/state/manifiesto originales](../runtime/recoveries/57c61494b1804a3cbaff53f7afdf797a/), [manifiesto pendiente preservado](../scenarios/zona1/montecarlo/run-bg10-e496c091b9ef46ee9ca381576135e299/validation-history/orphan-pending-741aaa0cf991dc3b.json), [inventario SHA256 de 89 entradas/salidas/log nativos](../scenarios/zona1/montecarlo/run-bg10-e496c091b9ef46ee9ca381576135e299/validation-history/orphan-inventory-741aaa0cf991dc3b.json). Se comprobaron antes/después de la validación y al terminar el posproceso; sin cambios nativos. Eventos de iteración/final idénticos: SHA256 `5f95a96fd5b0269333c9aaffed28d4831e4995669601ff9f3a0b7c1823ffee7b`, 1011707998 bytes por copia. Manifiesto validado SHA256 `8d51af2202ceb29ec32aa782f18fa05440436c1fb6a879beeb8f11a086e3213f`.

**Censo nativo conciliado:**

| Familia | Programados | Salidas/inicios | Incorporaciones | Llegadas completas | Censurados al corte |
|---|---:|---:|---:|---:|---:|
| Carros | 4400 | 4400 | 4360 | 4313 | 87 |
| Motos | 5500 | 5500 | 5442 | 5387 | 113 |
| Camiones | 100 | 100 | 100 | 100 | 0 |
| Buses: expediciones de 269 vehículos físicos | 13261 | 9610 | 9610 | 9610 | 0 iniciadas |

Privados: 9900 salidas, 9802 incorporaciones, 9700 llegadas y **200 censurados: 98 esperando incorporación y 102 activos al corte**. Los abortos administrativos emparejados del horizonte no son abortos previos: 0 antes del corte, 200 pares terminales. Clasificación de los 102 activos: 88 incorporaciones recientes con solicitud antigua y 14 recientes al horizonte; no se reinterpretan como viajes completados. Buses: **3651 expediciones programadas no iniciadas**, separadas de las 9610 completas y de la flota física; el contador nativo independiente boundary_cancelled_duty_after_closing también registra 3651, sin inferir una hora de cancelación de la hora programada. Camiones: 100/100 completos nominales bajo `freight-entry-and-completion-close-plus3600-v2`, sin infracción de ventanas. [Resumen de resultados y auditorías](../runtime/diagnostics/run10k-v8-recovery-20261108/results-summary.json).

**Auditorías originales:** 1252416 transiciones físicas, 0 inválidas; 0 movimientos forzados y 0 retiros por almacenamiento; prioridades `validated`, 0 cruces forzados; FIFO en 32289 intervalos de parada bloqueante, 0 salidas ilegales de seguidores; reservas `verified_native_aggregate_ledger`, separación contractual 0.10 m, 0 violaciones y 0 reservas/bloqueos restantes. Se aprobaron integridad XML/GZIP/SHA, población, configuración efectiva, semáforos, OD/OSM, carrocerías, reservas, contrato de rutas/paradas y carga v2 mediante el validador completo. El mecanismo nativo de última parada se preservó; estos informes no contienen un cotejo individual de cada última parada programada contra su salida antes de cada llegada. El registro acredita reservas longitudinales modeladas, **no posiciones continuas medidas ni calibración empírica**; `physical_stability.proven=false` se conserva. WAIT cuenta intentos, no segundos ni vehículos únicos. Geometría aproximada, no GIS verificada.

**Posprocesamiento:** `-AnalysisOnly` (perfiles, censo balanced, empaquetado y screening) exit 0; informe operativo exit 0; cierre compartido y recibo exit 0. Umbral original 0.90 y seis perfiles intactos. El screening privado usa 9700/9900 = 97.98%; la completitud agregada de expediciones programadas es otra métrica: 19410/23261 = 83.44%, incluyendo las 3651 expediciones de buses no iniciadas. [Log de análisis/paquete/screening](../runtime/recoveries/57c61494b1804a3cbaff53f7afdf797a/analysis-package-screening.log), [log operativo](../runtime/recoveries/57c61494b1804a3cbaff53f7afdf797a/operations-0.log). [Reportes](../scenarios/zona1/montecarlo/run-bg10-e496c091b9ef46ee9ca381576135e299/analysis/), [paquete de entrega](../scenarios/zona1/montecarlo/run-bg10-e496c091b9ef46ee9ca381576135e299/entregables/run-bg10-e496c091b9ef46ee9ca381576135e299/): **10 PNG en analysis** (7 incluidos en el paquete oficial y 3 operativos en analysis/prompt13/it.0) comprobados por SHA, decodificación y dimensiones; completitud y cronología operativa inspeccionadas visualmente sin recortes. Las gráficas reutilizan datos compactos/censos e informes, sin nueva lectura XML para generarlas.

**Revisión del recuperador:** 61 pruebas focales PASS0, incluidos controles negativos de salida/procesos/identidad/corrupción/sustitución/procedencia y cierre `review_required` sin promoción. [Pruebas](../runtime/diagnostics/run10k-v8-recovery-20261108/tests-revision2.log), [revisión de código](../runtime/diagnostics/run10k-v8-recovery-20261108/review-revision2.json), [parche acotado](../runtime/diagnostics/run10k-v8-recovery-20261108/recovery-only-revision2.patch). Cinco archivos: dos módulos de recuperación, dos pruebas y wrapper. Se preservaron los cambios previos del usuario. No hubo compilación Java, QSim, Validate integrado, DryRun, nuevas poblaciones, ni cambios de escenario/demanda/semilla/OD/horarios/criterios.

**Procedencia:** 772 dependencias completas antes/después. Huella productora congelada `1db657d6f60b487c96d2180798e3d4beba8ed58be693de8617f22c5257bbdc17`; revisión de recuperación `38d811815cd80f2f2268ab5263c030ead8ebec5b6b5404471d604e9ce12a98bd`, separada de la experimental. [Transición revisada real](../runtime/diagnostics/run10k-v8-recovery-20261108/reviewed-transition-revision2.json); ninguna dependencia excluida ni recibo histórico modificado. La nueva huella no autoriza otra simulación ni acredita capacidad de otra escala.

**Tentativa previa conservada:** RecoveryId `85aff183108b4931affe20808d82fe22`, exit 1 antes del validador original/lectura de eventos. Una comprobación adicional nueva exigía igualdad de bytes entre planes de iteración y finales. [Fuente MATSim 15](../runtime/diagnostics/run10k-v8-recovery-20261108/plan-serialization-source-evidence.json) demuestra que se guardan antes de QSim y después de scoring, respectivamente. La [comparación XML de las 10000 personas](../runtime/diagnostics/run10k-v8-recovery-20261108/plan-structural-comparison.json) encontró únicamente score añadido y 100 distancias de carga recalculadas. Se corrigió solo esa guarda con pruebas positivas/negativas: identidad/estructura privada de iteración mediante `population`; carga final por el validador original. No se modificaron los planes. La segunda tentativa tiene causa, directorio y recibo propios.

**Visor disponible:** [abrir Run10K en el puerto 8800](http://127.0.0.1:8800/index.html?run_id=simz1-cdffd75c4bdb47a7bfb507efe2c8c4e9&iteration=0&run_manifest_sha256=8d51af2202ceb29ec32aa782f18fa05440436c1fb6a879beeb8f11a086e3213f&source_version=c67ad110071192ffa42a2a0c143070d85c717fdba365833eb2b3984a4148dc06&visual_policy=partial-native-v1). Una única preparación oficial mediante `scripts/replay/prepare_replay.py`, it.0, terminó con **exit 0**: 1374858 tramos, 19610 viajes registrados (incluidos incompletos), SQLite de 4229419008 bytes y 720 ventanas de 120 s para 0–86400 s. Presupuestos originales SQLite 8 GiB/scratch 4 GiB y prioridad BelowNormal. Se verificaron quick_check, referencias, índice temporal, SHA e identidad; no se ejecutó QSim. [Log](../runtime/diagnostics/run10k-v8-recovery-20261108/replay-prepare.log), [exit](../runtime/diagnostics/run10k-v8-recovery-20261108/replay-prepare.exit.txt).

El lanzador oficial validó el contrato nativo `balanced-gateway-v1` y publicó la política visual `partial-native-v1`, sin sustituir resultados por históricos. [Verificación HTTP](../runtime/diagnostics/run10k-v8-recovery-20261108/viewer-verification.json): **exit 0**, HUD/identidad/huella/horizonte correctos; ventanas 00:00–00:02, 12:00–12:02 y 23:58–24:00 con hashes comprobados; consultas de otra identidad y fuera del horizonte rechazadas con HTTP 400. HTML disponible HTTP 200. Estas pruebas acreditan la navegación de datos mediante API, **no una inspección visual ni interacción WebGL**: el host de navegador y el canal nativo de Computer Use no estuvieron disponibles. La política parcial conserva sus límites; no acredita pose corporal continua completa.

Manifiesto visual SHA256 `64981bf83b7c88daa7f7dab837b4de03c4441522add30bbc43051054b5863386`; fuente SQLite SHA256 `ec6cbb69b17280debbb311ccbd6c4fd1536ead8fc6cda20d262ba7ef1df00790`. La versión/identidad del posproceso quedan separadas de la huella experimental. Servidor listo a las 20:02:28 Guatemala; inicialización espacial 117.50 s. [Registro oficial del visor](../runtime/replay/launch-8d9b89bd463347fba9e37334c5d88e42.jsonl), [procesos con fechas/padres/comandos](../runtime/diagnostics/run10k-v8-recovery-20261108/processes-after.json): cadena del visor 52620 → 35760 → 34220, sin JVM SimZ1 observada. Los visores históricos siguen intactos.

**Cierre:** [integridad de fuentes, recibos y texto histórico](../runtime/diagnostics/run10k-v8-recovery-20261108/closure-integrity.json), [estado final y evidencia](../runtime/diagnostics/run10k-v8-recovery-20261108/final-status.json). Sin bloqueo de recuperación nativa, análisis o publicación HTTP. Quedan declaradas la inspección UI no realizada y la cobertura poshoc limitada de última parada; no se relanza QSim para cubrirlas.

Comando exacto para abrir esta Run10K desde PowerShell externa; reutiliza el servidor compatible si sigue activo:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$run10k = '.\scenarios\zona1\montecarlo\run-bg10-e496c091b9ef46ee9ca381576135e299'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\replay\start_replay.ps1 -RunDir $run10k -Iteration 0 -ReplayDir "$run10k\webgl-continuo-it.0" -VisualPolicy partial-native-v1 -Port 8800
$viewerExit = $LASTEXITCODE
if ($viewerExit -ne 0) { throw "Visor rechazado: $viewerExit. Revisar logs; no repetir la simulación." }
```

Seguimiento de solo lectura:

```powershell
Get-Content -Encoding UTF8 .\runtime\diagnostics\run10k-v8-recovery-20261108\final-status.json
Get-Content -LiteralPath .\runtime\diagnostics\run10k-v8-recovery-20261108\viewer.stdout.log -Tail 10
```
<!-- RUN10K_V8_RECOVERY_HISTORICAL_END -->

<!-- RUN1000_V8_DELIVERY_HISTORICAL_START -->
# Histórico: Run1000 v8 aceptada — 22 gráficas y visor 8799 entregados

2026-11-08, Guatemala. **Entrega terminada; Run1000 v8 conserva su aceptación para la siguiente carga, sin calibración.** LaunchId `a32f15487b1a49ac910ba799175658ca`, RunId `simz1-9d15f07ccc134aa69c60fdcbc887ea3f`, iteración `0`, carpeta `scenarios/zona1/montecarlo/run-bg1-a32f15487b1a49ac910ba799175658ca`. [Estado del lanzamiento](../runtime/launches/a32f15487b1a49ac910ba799175658ca/state.json): `completed/PASSED`, exit 0, nativo `completed/valid`, `screening_pass`, cierre 13:33 Guatemala. Aceptación `accepted_for_next_load_test_not_calibrated`. El encabezado anterior describía la preparación y queda histórico; no se modificaron sus evidencias. [Cierre de esta entrega](../runtime/diagnostics/run1000-v8-delivery-20261108/final-status.json).

**Censo verificado:** privados 988/990 completos y 2 censurados recientes al horizonte; camiones 10/10; 269 buses físicos; 13 261 expediciones programadas, 9952 iniciadas y completadas, 3309 no iniciadas; 0 movimientos forzados. Las 3309 cancelaciones al cierre son además un contador nativo agregado, separado de la clasificación de expediciones no iniciadas. No se comparan las ofertas v7/v8 como equivalentes.

**Integridad final PASS0, 15:10:36 Guatemala:** huella `1db657d6f60b487c96d2180798e3d4beba8ed58be693de8617f22c5257bbdc17`, 772 dependencias y 53 archivos controlados de manifiestos, recibos e insumos sin diferencias. Manifiesto SHA256 `3399203616a3884cb17e360d46160cbd43bc006f44eb146e0d08aba1b249a427`. Experimento `final-20261108-transit-service-24h-v8.json`. [Antes](../runtime/diagnostics/run1000-v8-delivery-20261108/integrity-before.json), [después](../runtime/diagnostics/run1000-v8-delivery-20261108/integrity-after.json). Este documento y los derivados aislados están fuera de la huella existente; no se excluyó ninguna dependencia. No se modificaron Java, física, OD, rutas, horarios, carga, señales, especificación, recibos ni resultados históricos. No se ejecutaron Run1000, Run10K, Run55K, Validate o DryRun.

**Gráficas:** [Índice de las 22 figuras](../graficas_tesis_v2/run1000-v8-a32f15487b1a49ac910ba799175658ca/INDICE.md), 15 del generador integrado y 7 suplementos con el mismo Publisher; 22 PNG de 300 dpi, 22 SVG, 22 CSV y 22 JSON. Demanda por hora/familia/perfil, solicitudes/incorporaciones/llegadas, activos/pendientes, completitud/censura, duración/percentiles, transiciones, cuatro OD, camiones con sus ventanas y buses por línea/hora. Se conservan 10 PNG analíticos originales. [88 archivos verificados por hash e identidad](../graficas_tesis_v2/run1000-v8-a32f15487b1a49ac910ba799175658ca/artifact-verification.json), 17 fuentes intactas y ocho figuras representativas inspeccionadas visualmente. Versión `simz1-graficas-tesis-v2.1`, separada de la revisión experimental. Suplemento y verificación exit 0; el generador publicó `generated`, pero no quedó capturado su código original al ejecutarse desacoplado: se declara en [delivery.json](../graficas_tesis_v2/run1000-v8-a32f15487b1a49ac910ba799175658ca/delivery.json). No se releyó XML para estas figuras.

**Replay:** faltaba para esta corrida; se preparó una sola vez mediante `scripts/replay/prepare_replay.py`, a prioridad BelowNormal. Iteración completa 0–86 400 s, 807 095 segmentos, 10 952 viajes registrados y SQLite de 2 459 852 800 bytes. Publicación y procedencia oficiales verificadas; `resolve_selection` posterior exit 0 y guardas nativas/SQLite/espaciales del servidor conservadas. El observador desacoplado no recuperó el código original de preparación ni del constructor del dataset; se conservan null y no se proclama PASS0 de esos procesos. No se repitió la preparación para obtener un código. [Log oficial](../runtime/diagnostics/run1000-v8-delivery-20261108/visual/replay-prepare.log), [cierre visual con esta limitación](../runtime/diagnostics/run1000-v8-delivery-20261108/visual/final-status.json).

**Visor v8:** <http://127.0.0.1:8799/index.html>. Instancia independiente, vinculada al LaunchId/RunId/it.0/manifiesto/huella indicados y al contrato `balanced-gateway-v1`, con política visual `partial-native-v1`. El puerto 8798 sigue siendo v7; el arranque nuevo lo rechaza con exit 1 esperado y sin intervenirlo. [start.ps1](../runtime/diagnostics/run1000-v8-delivery-20261108/visual/start.ps1) verifica identidad, huella actual y puerto; la [reapertura](../runtime/diagnostics/run1000-v8-delivery-20261108/visual/launcher-reuse-test.json) dio exit 0 y cero procesos nuevos. Primera inicialización espacial: 109.74 s; la apertura posterior reutiliza el servidor compatible. [README del visor](../runtime/diagnostics/run1000-v8-delivery-20261108/visual/README.md). Huella del paquete visual aislado: `55e638bbe26b9a9d049f8922b7f698e4ed1c222752ce79fb37c62720db264bf3`.

El dataset propio v8 concilia las 9952 expediciones y los 269 buses con el censo oficial, leyendo 739 119 segmentos de buses por Índice SQLite, sin otro escaneo XML. Archivo comprimido de 7 572 352 bytes; un lector, caché HTTP de 16 MiB y prioridad BelowNormal. La caché no es el límite total de RAM. [Dataset/procedencia](../runtime/diagnostics/run1000-v8-delivery-20261108/visual/data/native-baseline.json). El [snapshot final de procesos](../runtime/diagnostics/run1000-v8-delivery-20261108/processes-after.json) documenta la cadena del visor 43188 → 23892, sus fechas, padres y comandos; no encontró JVM SimZ1 ni el lanzador original. Los visores históricos permanecieron intactos.

**Pruebas:** 44 controles JS de VIS-01/VIS-02, 4 de identidad y 5 del dataset con negativos, todos exit 0. [Chrome/WebGL definitivo](../runtime/diagnostics/run1000-v8-delivery-20261108/browser/verification-final/browser-results.json): **102 comprobaciones, exit 0**, WebGL2 real ANGLE/Intel UHD/Direct3D11, contexto conservado, cero excepciones JS y cero solicitudes fallidas de datos; solo favicon 403 ajeno al mapa. [Seis comprobaciones focales](../runtime/diagnostics/run1000-v8-delivery-20261108/browser/focus-final/browser-results.json), exit 0. Se verificaron intervalos nativos de entrada/salida, unicidad, cambios de enlace/posición aproximada, recorridos cargados de Transmetro L12 (77 enlaces) y TuBus 104 (54), clic real en TuBus, filtros exactos, barra temporal, pausa, reproducción y velocidades 1x/120x. La barra principal conserva únicamente esos controles y la hora.

| Hora simulada | Activos nativos | Símbolos aproximados | Transmetro / TuBus | Omitidos |
|---|---:|---:|---:|---:|
| 05:00 | 28 | 28 | 28 / 0 | 0 |
| 07:00 | 91 | 91 | 70 / 21 | 0 |
| 09:00 | 94 | 94 | 74 / 20 | 0 |
| 12:00 | 97 | 97 | 76 / 21 | 0 |
| 17:00 | 97 | 97 | 78 / 19 | 0 |
| 20:00 | 80 | 80 | 80 / 0 | 0 |

También se comprobaron 00:00 y 23:59:59 sin buses activos. Son fotografías temporales, no vehículos únicos acumulados. En estas muestras no hay cuerpos con pose completa certificada. Inspección visual realizada sobre [Transmetro](../runtime/diagnostics/run1000-v8-delivery-20261108/browser/verification-final/transmetro-selected.png), [TuBus](../runtime/diagnostics/run1000-v8-delivery-20261108/browser/verification-final/tubus-selected.png), vista general y el caso focal a zoom 20. El primer script heredado cambiaba directamente la cámara de Deck y omitía el callback que reescala semáforos: creó una malla gris sobredimensionada solo en esa prueba. Se corrigió únicamente el script QA y se repitió el mismo caso; [captura corregida](../runtime/diagnostics/run1000-v8-delivery-20261108/browser/focus-final/transmetro-25600-zoom20.png). Los intentos previos se conservan; el pase vigente es `verification-final`/`focus-final`. No hubo parche productivo, de señales o de geometría por este hallazgo.

**Límites:** símbolos compactos de presencia, sustentados por eventos y cotas nativas, sin afirmar pose corporal completa, velocidad instantánea, separación, colisiones o exclusividad Transmetro. VIS-01 conserva cotas frontales sin interpolación inventada; VIS-02 conserva referencia y procedencia lateral. La reconstrucción exacta de carrocerías sigue pendiente. La geometría es aproximada, no cartografía GIS verificada. Las duraciones excluyen dos censuras; las series horarias no se presentan como datos de 15 minutos. WAIT cuenta intentos. Flujo por secciones y ocupación por intersecciones siguen sin fuente publicada adecuada; A–B es exploratorio. La aceptación técnica no constituye calibración ni acredita la siguiente escala.

Para levantar o abrir de nuevo **solo el visor v8** desde PowerShell externa:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\runtime\diagnostics\run1000-v8-delivery-20261108\visual\start.ps1 -Open
$viewerExit = $LASTEXITCODE
if ($viewerExit -ne 0) { throw "Visor v8 rechazado: $viewerExit. Revisar los logs; no relanzar la simulación." }
```

Empieza en 00:00; seleccionar 09:00 permite ver ambos sistemas activos. Seguimiento de solo lectura, fuera del editor:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8799/api/visual-build' | ConvertTo-Json -Depth 5
Get-Content -Encoding UTF8 .\runtime\diagnostics\run1000-v8-delivery-20261108\final-status.json
```

**Siguiente acción:** utilizar las gráficas y el visor entregados. La siguiente escala queda bajo control manual del usuario y los controles originales del lanzador. Esta entrega no cambia la aceptación, no ejecuta fases experimentales ni exige repetir QSim/Validate/DryRun por cambios visuales o documentales aislados.
<!-- RUN1000_V8_DELIVERY_HISTORICAL_END -->

<!-- SIMZ1_V8_PREPARATION_HISTORICAL_START -->
# Histórico: v8 preparada; Validate PASS0 y DryRun1000 elegible antes del Run manual

2026-11-08, Guatemala. **Preparación terminada: Validate PASS0 a las13:32 y DryRun1000 PASS0 a las13:37.** El usuario sustituyó la decisión anterior de conservar Run10K v7 por la preparación urgente de v8. Solo se preparan Run1000, Run10K y Run55K condicional; ninguna corrida de escala se inició desde Codex. La revisión conserva los insumos, resultados y recibos históricos; el recibo activo Validate fue actualizado exclusivamente por el validador oficial, con su copia v7 preservada. [Cierre verificable](../runtime/diagnostics/v8-preparation-20261108/final-status.json).

**Run10K v7 interrumpida, incompleta.** LaunchId `501433d0ad044670ab530ed037ec5f19`, RunId `simz1-96e7200e77bd411fbcdbcc57ba7d2688`. Tras la interrupción manual quedaron JVM PID1288 y cmd PID1884. Con autorización posterior expresa se verificaron PID, creación, padre y comando y se cerraron únicamente esos dos procesos. Toda la cadena registrada quedó ausente y la guarda de escritores SimZ1 vacía antes de integrar. Los JSON históricos aún declaran `running`; esa discrepancia se conserva, no acredita jornada completa ni aceptación. [Identidades y motivo](../runtime/diagnostics/v8-preparation-20261108/interruption-authorized.json), [comprobación del cierre](../runtime/diagnostics/v8-preparation-20261108/processes-after-interruption.json), [último prefijo de log](../runtime/diagnostics/v8-preparation-20261108/run10k-tail-at-interruption.log).

**Cambio defendible.** Variante `final-20261108-transit-service-24h-v8.json`: L12 conserva 44 buses, rutas y dwell25s; recuperación terminal180→400s en ambos extremos. Intervalo nominal20.088957→30.088957s, oferta179.202929→119.645223/h por sentido. Expediciones programadas totales15336→13261 (−2075 exclusivamente L12;6224→4149). Los269 IDs, demanda privada, composición, semilla, OD, carga v2 y horizonte24h se preservan. Son supuestos de oferta sintética, no caudal medido ni garantía de completar toda la programación. [Comparación](../runtime/diagnostics/v8-preparation-20261108/timetable/comparison.json).

**CFG-01 permanece pendiente.** Plaza Municipal conserva tres carriles mixtos, capacidad6000veh/h, cola original compartida y parada bloqueante25s. Los insumos no acreditan continuidad lateral exclusiva y el motor no restringe modos por slot; separar IDs no aporta independencia física. Se excluye la exclusividad especulativa. No hay parche Java, nuevos conectores, cuarta vía ni aumento de capacidad. [Revisión física](../runtime/diagnostics/v8-preparation-20261108/physical/PHYSICAL.md).

**Revisión congelada:** `1db657d6f60b487c96d2180798e3d4beba8ed58be693de8617f22c5257bbdc17`,772 dependencias;28 archivos históricos comparados sin cambios al cierre, y recibos de ensayo v7 intactos. Pruebas focales v8:22 PASS0; fixtures de huella:7 PASS0; contratos origen, carga, preparación y DryRun:53 pruebas PASS0. **Validate integrado PASS0**, JDK17, `balanced-launch-42134f4f469a4a489d3686059b2b0c1a`; huella inicial/final coincidente. Incluyó C529-A/B/C/D, OD/OSM, L18, recepción, FIFO, reservas, llegada corporal, última parada, carga v2 y pruebas v8. Solo componentes y QSim focales; ninguna corrida de escala. [Estado Validate](../runtime/validation/balanced-launch-42134f4f469a4a489d3686059b2b0c1a/state.json), [inventario congelado](../runtime/diagnostics/v8-preparation-20261108/frozen-sources.json), [log focal](../runtime/diagnostics/v8-preparation-20261108/focal-v8.log), [recibo Validate v7 archivado](../runtime/diagnostics/v8-preparation-20261108/before/runtime/workflow/validated-balanced-gateway-v1.json).

**DryRun1000 v8:** LaunchId **`dfe75a0af38946e3a42d37f24dac51ac`**, `dry_run_pass/completed/PASSED`, exit0, `run_launch_eligible=true`, `prior_trial_status=not_applicable_this_is_trial`. La comprobación oficial `require-experiment-dry-run` devolvió0 con la misma selección y huella. El request y comando hijo fijan `service-fleet-176-93-v8.json`; la procedencia y SHA del servicio también se guardan en request.json. No se creó directorio de simulación, población privada, QSim ni replay; RunId nativo sigue null. [Estado DryRun](../runtime/launches/dfe75a0af38946e3a42d37f24dac51ac/state.json), [request](../runtime/launches/dfe75a0af38946e3a42d37f24dac51ac/request.json), [comprobación de identidad](../runtime/diagnostics/v8-preparation-20261108/dryrun-identity.log).

| Frente | Resultado final | Evidencia |
|---|---|---|
| Agente1, visor | VIS-01/VIS-02 corregidos;44 controles JS y79 Chrome/WebGL PASS0;5 capturas. Reloj, reproducción, velocidad, barra, cinco tipos y clic; API diagnóstica conservada. | [Entrega visual](../runtime/diagnostics/v8-preparation-20261108/visual/README.md) |
| Agente2, Plaza | Exclusividad rechazada por falta de soporte; configuración mixta preservada.11 checks estáticos y2 del auditor PASS0;6 pruebas físicas integradas PASS0. | [Revisión física](../runtime/diagnostics/v8-preparation-20261108/physical/PHYSICAL.md) |
| Agente3, horarios | Recuperación L12 terminal400s,269 buses,13261 expediciones nominales;9 pruebas de servicio/negativos PASS0. | [Informe y supuestos](../runtime/diagnostics/v8-preparation-20261108/timetable/REPORT.md) |
| Agente4 y coordinación, regresiones/recursos | Revisión independiente de matriz y guardas; coordinación integró16 archivos, ejecutó82 pruebas focales Python, Validate y DryRun PASS0. | [Cierre integrado](../runtime/diagnostics/v8-preparation-20261108/final-status.json) |

**VIS-01/VIS-02 y límites.** El símbolo de L12_039 sigue la cota mínima nativa del frente:92.28006287m a15:02:03 y105.88006287m a15:02:09, conservando referencia de corredor y `positions_observed=false`. No se interpola movimiento inventado. Se conserva fuente, índice y offset lateral; el fallback sin evidencia no se etiqueta como carril certificado. Un símbolo compacto evita dibujar un rectángulo13.5m con anclaje corporal desconocido en un enlace4.2m; las dimensiones nominales siguen disponibles. Reconstrucción corporal continua exacta y exclusividad Transmetro permanecen pendientes. La geometría es aproximada, no cartografía GIS verificada. L12_011, TuBus, clic, entradas/salidas, seis horarios y reproducción también se comprobaron con WebGL2/Intel D3D11, sin pérdida de contexto. Intentos previos fallidos por guarda de lector, espera inicial y aserción del reloj se conservaron; el pase vigente es `browser-delivery`.

**Archivos.** [Inventario exacto de16 archivos de código/configuración](../runtime/diagnostics/v8-preparation-20261108/integration-files.json): cinco Python de contrato/generación/auditoría/recuperación, cuatro pruebas, cuatro scripts de gateway/validación/seguimiento, la especificación v8 y dos JSON de servicio/rutas. Además, este encabezado y cinco archivos productivos del visor aislado, con sus pruebas/evidencias. No cambió Java, `network.xml`, `lanes.xml`, señales ni el replay nativo. Huella visual separada: `9598b57edbf20398152dce4bb4b5c9e3beea63c3a2f73ee7ab2e12d09539b2c1`.

| Cobertura integrada | Pruebas incluidas |
|---|---|
| Carriles/rutas/parada | `test_simz1_v8_physical`, `SimZ1TransitAccessCheck`, `RouteSafetyCheck`, `SimZ1BlockingStopCheck` |
| FIFO/recepción/cuerpos/reservas | `SimZ1ParallelOriginalFifoCheck`, `SimZ1IndependentLaneDischargeCheck`, `SimZ1TenthStreetReceptionCheck`, `SimZ1DownstreamStorageCheck`, `SimZ1VehicleReservationCheck`, `SimZ1CorridorOccupancyCheck` |
| Señales/prioridades/pasajes/L18 | `SimZ1PriorityReceiverCheck`, `SimZ1SignalCycleRouteCheck`, `test_simz1_temporal_passage`, `test_simz1_l18_coordination` |
| C529-A/B/C/D y OD/OSM | `test_simz1_passage_cycle`, `test_simz1_native_od`, `test_simz1_active_retention`, `test_simz1_retention_phases`, `test_simz1_balanced_gateway_od`, `test_simz1_sequence_contract` |
| Llegada corporal/último stop/flota | `SimZ1ArrivalClearanceCheck`, `SimZ1DischargeArrivalCheck`, `SimZ1DayTransitCheck`, `test_simz1_transit_service_v8`, `test_simz1_weekday_transit` |
| Carga v2/identidad/recibos | `SimZ1FreightOriginAdmissionCheck`, `SimZ1FreightAdmissionQSimCheck`, `test_simz1_freight_admission`, `test_simz1_v8_experiment`, `test_simz1_freight_version`, contratos de preparación y DryRun |

**Recursos y anexo metodológico.** Comprobación previa `planning_budget_pass`: RAM instalada32GiB, heap QSim12GiB; el plan admite paginación. La reserva de crecimiento automático fue13GiB antes de Validate y11GiB en DryRun, según memoria disponible en cada instante; no son picos medidos ni ajustes del sistema. DryRun observó127.27GiB libres y exigió100GiB; el lanzador mantiene el máximo entre100GiB, lo solicitado y su presupuesto calculado. El estudio restringe la escala por disponibilidad de cómputo, almacenamiento y tiempo; no extrapola costes lineales ni acredita escalabilidad110K/180K–220K. La aceptación técnica verifica contratos modelados y no constituye calibración empírica. Se conservan mutex y exclusividad; al cierre no quedan escritores SimZ1. [Memoria previa](../runtime/diagnostics/v8-preparation-20261108/memory-before.json), [log DryRun con presupuesto vigente](../runtime/diagnostics/v8-preparation-20261108/dryrun1000.log), [procesos finales](../runtime/diagnostics/v8-preparation-20261108/processes-final.json).

**Siguiente acción: Run1000 manual**, desde PowerShell externa, sin repetir Validate ni DryRun si fuentes e insumos siguen iguales. El lanzador mantiene sus comprobaciones normales y creará otro LaunchId para la ejecución real:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 `
  -Run `
  -ExperimentSpec .\scenarios\zona1\experiments\final-20261108-transit-service-24h-v8.json `
  -ExperimentScenario run1000 `
  -DryRunLaunchId dfe75a0af38946e3a42d37f24dac51ac `
  -PostprocessingPolicy native_diagnostic_v1 `
  -JavaHome 'C:\Program Files\Java\jdk-17' `
  -MinFreeGiB 100
$runExit = $LASTEXITCODE
if ($runExit -ne 0) { throw "Run1000 terminó con código $runExit; revisar su evidencia antes de continuar." }
```

**Secuencia posterior, sin ejecución automática.** Tras Run1000 `completed/valid`, aceptación oficial compatible y revisión de sus resultados: crear DryRun nuevo con selector `run10000`, comprobar elegibilidad y usar su propio LaunchId en un Run10K manual. Solo tras revisar esa Run10K y el tiempo/recursos disponibles, considerar selector `run55000` con otro DryRun y Run manual. El gateway exige Run1000 compatible para escalar; **no exige automáticamente una Run10K previa a55K**: ese requisito es parte del procedimiento autorizado del usuario. No hay selectores110K/180K–220K en v8 ni `FirstScaleTrial` habilitado.

Preparación manual futura de Run10K, únicamente tras aceptar Run1000:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 `
  -DryRun -ExperimentSpec .\scenarios\zona1\experiments\final-20261108-transit-service-24h-v8.json `
  -ExperimentScenario run10000 -PostprocessingPolicy native_diagnostic_v1 `
  -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$prepareExit = $LASTEXITCODE
if ($prepareExit -ne 0) { throw "DryRun10K rechazado: $prepareExit" }
```

Para55K, el mismo comando de preparación usa `-ExperimentScenario run55000` solamente tras la revisión indicada. El Run posterior conserva el selector y usa `-Run -DryRunLaunchId <ID nuevo aprobado>`, sin reutilizar el DryRun1000.

**Visor corregido:** <http://127.0.0.1:8798/index.html>. Muestra exclusivamente Run1000 v7 `simz1-b6a0e4e466d044adb337599f0a993c80`, it.0; no simula resultados futuros v8. [Capturas15:02:03](../runtime/diagnostics/v8-preparation-20261108/visual/browser-delivery/ptbus_transmetro_L12_039-54123.png), [15:02:09](../runtime/diagnostics/v8-preparation-20261108/visual/browser-delivery/ptbus_transmetro_L12_039-54129.png), [15:02:19](../runtime/diagnostics/v8-preparation-20261108/visual/browser-delivery/ptbus_transmetro_L12_039-54139.png), [L12_011](../runtime/diagnostics/v8-preparation-20261108/visual/browser-delivery/ptbus_transmetro_L12_011-73758.png), [TuBus](../runtime/diagnostics/v8-preparation-20261108/visual/browser-delivery/tubus-selected.png).

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\runtime\diagnostics\v8-preparation-20261108\visual\start.ps1
$viewerExit = $LASTEXITCODE
if ($viewerExit -ne 0) { throw "Visor no disponible: $viewerExit" }
```

Seguimiento de solo lectura fuera del editor, utilizable ahora:

```powershell
Get-Content -LiteralPath .\runtime\launches\dfe75a0af38946e3a42d37f24dac51ac\state.json
Invoke-RestMethod 'http://127.0.0.1:8798/api/visual-build' | ConvertTo-Json -Depth 4
```

Para una ejecución real posterior usar `scripts/watch_simz1_110k.ps1 -LaunchId <LaunchId real mostrado por Run> -Watch -Iteration 0`; el ID de DryRun identifica preparación, no QSim.
<!-- SIMZ1_V8_PREPARATION_HISTORICAL_END -->

<!-- RUN1000_V7_BUS_INVESTIGATION_HISTORICAL_START -->
# Histórico: investigación de buses terminada; decisión anterior de conservar Run10K

2026-11-08, Guatemala. **Diagnóstico entregado, sin implementación. Decisión provisional: CONSERVAR COMO REFERENCIA**, dejando finalizar Run10K bajo control exclusivo del usuario. No se ha demostrado un defecto funcional que justifique detenerla. [Informe técnico A–H](../runtime/diagnostics/run1000-v7-bus-investigation-20261108/DIAGNOSTICO.md), [JSON integrado](../runtime/diagnostics/run1000-v7-bus-investigation-20261108/diagnostico.json), [cronologías](../runtime/diagnostics/run1000-v7-bus-investigation-20261108/chronology.md), [carriles y física](../runtime/diagnostics/run1000-v7-bus-investigation-20261108/lanes-physics.md), [causa visual](../runtime/diagnostics/run1000-v7-bus-investigation-20261108/visual-findings.md).

**Identidad examinada.** Run1000 `simz1-b6a0e4e466d044adb337599f0a993c80`, LaunchId `fff83bc5136f46aba5bcb92adca15fa4`, it.0, permanece `completed/valid`, gateway `completed/PASSED`, exit 0. Huella registrada **`a1630747dd8a511268a40c8824b84f3afb8f699a33f0025396f7a5bfb934d6e5`**; esta investigación no la recalcula ni modifica. Las evidencias y el cierre de la reparación visual anterior se conservan debajo como históricos.

**Hallazgos demostrados.** Se reconstruyeron ocho expediciones de siete buses. L12_039 d0032 tiene un aumento de cota corporal nativa a las **15:02:09**, mientras el plan del visor produce una posición fija entre las capturas 15:02:03/10. L12_011 d0050 cambia de carril nativo a **20:29:18**. Los cuerpos aproximados y sus offsets no certifican invasión física de carriles. Plaza Municipal está configurada `bus,car`, con tres carriles representados y parada bloqueante compartida de 25 s; no hay exclusividad lateral Transmetro allí. Hay acumulación nativa y esperas receptoras finitas, no solo dibujo. El roster L12 ofrece nominalmente 179.20 expediciones/h por sentido frente al techo serial ideal de 144 servicios/h; es una limitación de diseño, no caudal medido ni defecto probado del motor.

El censo oficial completo conserva **9954 expediciones iniciadas/completadas, 5382 no iniciadas, cero solapamientos del mismo bus y máximo viaje real de 1880 s**. Ninguna expedición iniciada contiene una hora continua de inmovilidad. La muestra tiene progreso dentro de enlaces; el máximo exacto de inmovilidad corporal sigue indeterminado porque las cotas no son coordenadas continuas observadas. Las demoras horarias de varias horas corresponden al arrastre de servicios, no a la inmovilidad de esa expedición. No se propone retirar buses ni liberar reservas por timeout.

**Run10K recuperada por identidad explícita.** DryRun `1ae11b2d89ef4aceba4efbafd8b43e68` → LaunchId real **`501433d0ad044670ab530ed037ec5f19`**, RunId **`simz1-96e7200e77bd411fbcdbcc57ba7d2688`**, it.0. A las **12:26:35 Guatemala**: gateway/manifiesto `running`, validación `pending`, último paso **40980 s = 11:23 simuladas**; último intervalo de 60 s con **1175 transiciones y 18 llegadas**, 113 buses activos y 3907 inicios públicos acumulados, cero movimientos forzados/retiros en ese intervalo. Se contrastó JVM PID1288, creación `17:46:50.973Z`, padre35220 y comando Java17 con la cadena del lanzador PID31396 y su carpeta real. [Snapshot y procesos](../runtime/diagnostics/run1000-v7-bus-investigation-20261108/run10k-observation-final.json), [tail persistente](../runtime/diagnostics/run1000-v7-bus-investigation-20261108/run10k-log-tail-final.txt). Es una observación fechada, no aceptación del cierre futuro.

**Alcance y comprobaciones.** Cero QSim, compilaciones, Validate, DryRun o nuevas pruebas de simulación; no hay nuevos códigos PASS de esas fases. Se revisaron informes existentes y consultas SQLite indexadas en solo lectura; cero XML de eventos leído y cero eventos masivos Run10K leído. No se alteraron visor, fuentes protegidas, configuración, recibos ni procesos. Once fuentes pequeñas coinciden con la revisión aceptada. Las comprobaciones de JSON/CSV, enlaces del informe, continuidad de fuentes e histórico documental se registran en [integridad del diagnóstico](../runtime/diagnostics/run1000-v7-bus-investigation-20261108/integrity-final.json); no sustituyen el fingerprint ni validadores oficiales. La geometría sigue siendo aproximada, no GIS verificada.

Seguimiento de solo lectura desde PowerShell externa, sin eventos ni relanzamientos:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_simz1_110k.ps1 -LaunchId 501433d0ad044670ab530ed037ec5f19 -Watch -Iteration 0
$watchExit = $LASTEXITCODE
if ($watchExit -ne 0) { throw "Observación rechazada: $watchExit. Revisar evidencia sin relanzar." }
```

**Siguiente acción:** revisión del informe por el usuario para decidir si autoriza una corrección visual aislada o una variante de carril/servicio. No iniciar implementación, detener Run10K, repetir pruebas ni encadenar validaciones por este cierre. Después de su cierre natural, evaluar la misma Run10K con el posproceso existente y conservar sus limitaciones de configuración. El encabezado anterior y todo el histórico permanecen preservados.
<!-- RUN1000_V7_BUS_INVESTIGATION_HISTORICAL_END -->

<!-- RUN1000_V7_BUS_VISUAL_HISTORICAL_START -->
# Histórico: Run1000 v7 aceptada; buses recuperados en visor aislado

2026-11-08, Guatemala. **Reparación visual terminada, con Chrome y WebGL real verificados.** Run1000 `simz1-b6a0e4e466d044adb337599f0a993c80`, LaunchId `fff83bc5136f46aba5bcb92adca15fa4`, it.0, carpeta `scenarios/zona1/montecarlo/run-bg1-fff83bc5136f46aba5bcb92adca15fa4`. El cierre real es `completed/valid`, gateway `completed/PASSED`, exit 0, `screening_pass`; el recibo existente acepta el ensayo para la siguiente carga, sin calibración. El encabezado anterior estaba atrasado: su Run1000 pendiente queda como **histórico**, sin cambiar ninguna evidencia para hacerlo coincidir.

**Alcance y concurrencia.** El usuario informó una Run10K externa durante esta reparación. No se inició, detuvo ni modificó Run10K, su carpeta o configuración. No se ejecutaron Java, compilación, QSim, Validate, DryRun ni corridas de ninguna escala. Todo el código visual nuevo está fuera del inventario protegido, en [directorio aislado](../runtime/diagnostics/run1000-v7-bus-visual-20261108/). Las 766 dependencias originales conservan la huella **`a1630747dd8a511268a40c8824b84f3afb8f699a33f0025396f7a5bfb934d6e5`**; manifiesto, recibos Validate/DryRun/trial y replay originales se conservan. [Integridad antes](../runtime/diagnostics/run1000-v7-bus-visual-20261108/integrity_before.json), [comprobación final](../runtime/diagnostics/run1000-v7-bus-visual-20261108/integrity-after.json), [cierre y procesos](../runtime/diagnostics/run1000-v7-bus-visual-20261108/final-status.json).

**Causa demostrada.** `partial-native-v1` marca cuerpos con reconstrucción pendiente; la propagación conservadora del frontend y `visualQueueRenderer.frame` los omiten. No existe un filtro erróneo por los prefijos `ptbus_transmetro_*`/`ptbus_tubus_*`, ni ausencia de transporte nativo. A las 09:00 hay 108 buses activos: el modo estricto reproduce **0 marcadores y 108 omitidos por posición estricta no disponible**; al activar aproximación aparecen 108. No se cambió globalmente `partial-native-v1` ni se convirtió un anclaje aproximado en certificación física.

**Implementación.** [Servidor aislado](../runtime/diagnostics/run1000-v7-bus-visual-20261108/serve_bus_viewer.py), [copia de controles](../runtime/diagnostics/run1000-v7-bus-visual-20261108/visualizador_z1_controls.js), [adaptador aproximado](../runtime/diagnostics/run1000-v7-bus-visual-20261108/bus_approximation.js). Se reutilizan el backend, validación de identidad/contrato, geometría dirigida, catálogo corporal, selección y rutas existentes. El overlay se aplica después del renderer estricto y solo a buses dentro de sus intervalos nativos `[entrada al tráfico, salida del tráfico)`. Prefiere una posición disponible del replay; de faltar, usa el último enlace observado y su anclaje representativo. Actualiza con cambios de enlace/parada, permite saltos y nunca prolonga servicio por falta de interpolación. La identidad es el bus físico y la expedición vigente: no se duplica al reutilizar el vehículo.

La casilla **Mostrar buses aproximados** está habilitada inicialmente. Verde identifica Transmetro y azul TuBus, conservando sus dimensiones, ID, ruta/sentido; estos colores no indican velocidad. Hay contadores separados de activos nativos, dibujados verificados, aproximados y activos sin enlace, además de omisiones/filtros. Se conservan pausa, reproducción, tiempo, velocidades 1x/120x y búsqueda/selección por ID. Tarjeta y tooltip indican aproximación y no atribuyen velocidad instantánea. Los anclajes no acreditan separación, colisiones ni cumplimiento físico; los auditores no se modificaron. La geometría sigue siendo aproximada, no cartografía GIS verificada.

**Datos reutilizados y límites de recursos.** [Dataset y procedencia](../runtime/diagnostics/run1000-v7-bus-visual-20261108/data/native-baseline.json): 9,954 expediciones observadas, 269 buses físicos, máximo 126 activos, cero movimientos forzados según el cierre nativo. Se excluyen 5,382 expediciones programadas que nunca entraron al tráfico. Una lectura indexada de 738,934 segmentos de buses del SQLite existente terminó en 67.75 s antes de la nueva restricción de concurrencia; no se leyó XML ni se reconstruyó el replay. Se conciliaron las 9,954 expediciones con `bus-expeditions.csv`. Después solo hubo lecturas ligeras y ventanas solicitadas. El servidor usa un único lector, prioridad BelowNormal, caché HTTP de 16 MiB y dataset comprimido de 7.63 MB; esos límites de caché no son un límite total de RAM. Solo escucha loopback. Se comprobaron los servidores existentes: pertenecían a otras corridas; no se intervinieron. Los reinicios de desarrollo afectaron exclusivamente nuestros procesos identificados, registrados en el directorio aislado.

**Comprobación con datos reales, sin filtros:**

| Hora simulada | Activos nativos | Marcadores verificados | Marcadores aproximados | Sin enlace / omitidos |
|---|---:|---:|---:|---:|
| 05:00 | 30 | 0 | 30 | 0 / 0 |
| 07:00 | 97 | 0 | 97 | 0 / 0 |
| 09:00 | 108 | 0 | 108 | 0 / 0 |
| 12:00 | 99 | 0 | 99 | 0 / 0 |
| 17:00 | 113 | 0 | 113 | 0 / 0 |
| 20:00 | 84 | 0 | 84 | 0 / 0 |

Pruebas PASS0: cinco pruebas de datos con controles negativos; 39 aserciones del adaptador y 16 del estado UI; [65 comprobaciones en Chrome/WebGL](../runtime/diagnostics/run1000-v7-bus-visual-20261108/browser-1/browser-results.json) y [27 comprobaciones finales focales](../runtime/diagnostics/run1000-v7-bus-visual-20261108/browser-final/browser-results.json). Estas últimas verifican los ajustes posteriores de tarjeta, halo/filtros y leyendas, con recorridos completos cargados. Se probaron entradas/salidas y expedición siguiente de Transmetro L12_001 y TuBus R5_001, cambios de enlace, unicidad, sistemas/rutas, pausa y reproducción, y ausencia de buses antes/después del servicio. No hay excepciones JavaScript. El primer recorrido TuBus recibió un 503 reintentable con el lector único; las selecciones finales completaron con HTTP 200. El 403 de favicon es ajeno al mapa.

**Inspección visual realizada:** WebGL2 real, ANGLE/Intel UHD Direct3D11, sin pérdida de contexto; no son solo pruebas HTTP/DOM. Se inspeccionaron las capturas de ambos sistemas con selección y rutas: [Transmetro](../runtime/diagnostics/run1000-v7-bus-visual-20261108/browser-final/transmetro-selected.png), [TuBus](../runtime/diagnostics/run1000-v7-bus-visual-20261108/browser-final/tubus-selected.png). Las seis capturas horarias están en `browser-1/`. No hay certificación física nueva por estas pruebas visuales.

La prueba de reapertura detectó que el inventario de sockets de Windows podía omitir el listener o reportar PID 0, por lo que abrió una instancia aislada redundante. Se cerró exclusivamente esa instancia tras comprobar PID, padre, creación y comando; no se tocó Run10K ni los visores ajenos. Se corrigió `start.ps1` para consultar primero la identidad HTTP y comprobar el puerto exclusivo; el servidor nuevo desactiva `SO_REUSEADDR` antes de inicializar el replay. La [prueba final de reutilización](../runtime/diagnostics/run1000-v7-bus-visual-20261108/launcher-reuse-test.json) terminó con 0 y **cero procesos nuevos**; queda un único servidor de esta reparación con un lector de baja prioridad.

**Visor reparado:** <http://127.0.0.1:8796/index.html>. El servidor está ligado exclusivamente al RunId/it.0/manifiesto indicados. La apertura conserva el reloj inicial 00:00; para ver transporte activo inmediatamente, seleccionar 09:00. El control aproximado ya está habilitado.

Desde PowerShell externa, este comando reutiliza un servidor compatible o levanta únicamente el visor, sin preparación ni simulación:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\runtime\diagnostics\run1000-v7-bus-visual-20261108\start.ps1
$viewerExit = $LASTEXITCODE
if ($viewerExit -ne 0) { throw "Visor no disponible: código $viewerExit. Consultar su log." }
```

Seguimiento de solo lectura, independiente del editor:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8796/api/visual-build' | ConvertTo-Json -Depth 4
Get-Content -Encoding UTF8 .\runtime\diagnostics\run1000-v7-bus-visual-20261108\final-status.json
```

**Siguiente acción:** utilizar este visor para inspección aproximada de Run1000. La Run10K externa permanece bajo control del usuario; este cierre no cambia su estado, no autoriza otra escala y no exige repetir ninguna validación por el cambio visual/documental aislado.
<!-- RUN1000_V7_BUS_VISUAL_HISTORICAL_END -->

<!-- RUN10K_V7_PREPARATION_HISTORICAL_START -->
# Histórico: preparación v7 validada y DryRun1000 aprobado antes del ensayo manual

2026-11-08, Guatemala. **Validate y DryRun1000 v7 aprobados con código 0.** La siguiente acción es Run1000 manual y su aceptación oficial; después corresponde DryRun10K v7. No se ejecutó desde Codex ninguna corrida de escala. Run55K queda sujeta a evaluación de Run10K y autorización posterior; no hay secuencia automática. [Cierre verificable de esta preparación](../runtime/diagnostics/run10k-v7-preparation-20261108/final-status.json).

La recuperación confirmó la huella reportada `1923f029075540fbbd36d9191f1452f261f2e35620f967fe6dbe81d19ccefc1d` y sus 766 dependencias sin diferencias. La única modificación posterior amplía `SimZ1FreightOriginAdmissionCheck.java`: 50 casos nativos PASS0, con seguidores carro/moto/bus/camión retenidos por cabeza vencida aun con hueco libre, controles positivos independientes, FIFO/reservas/flujo conservados y una única denegación. Nueva huella congelada: **`a1630747dd8a511268a40c8824b84f3afb8f699a33f0025396f7a5bfb934d6e5`**. No se cambió producción ni insumos. Siete pruebas de versión de carga y nueve negativos de mutación/ausencia aprobaron.

**Validate oficial PASS0**, JDK17 y `.venv`, cerrado a las 08:25 Guatemala (14:25 UTC) en [balanced-launch-25edacad3d1b465fa47458b4dce4e124](../runtime/validation/balanced-launch-25edacad3d1b465fa47458b4dce4e124/state.json). El [recibo activo](../runtime/workflow/validated-balanced-gateway-v1.json) acredita la huella congelada; la copia anterior se preservó en las evidencias de esta fase. Incluye las regresiones C529-A/B/C/D, OD/OSM, temporales/L18, llegada corporal, última parada de buses, carga v2 y los 50 casos FIFO. Son componentes y QSim focales; no certifican una jornada v7 de escala ni una nueva aceptación Run1000.

El ensayo anterior `simz1-502eeee04ee64def8cbc7a07d84bca1a`, de v6/huella `cd80724f…`, sigue sin acreditar esta revisión. Tras Validate, `require-trial` oficial terminó con 1: `Private OD implementation changed since preparation; source fingerprints differ` ([log](../runtime/diagnostics/run10k-v7-preparation-20261108/prior-trial-after-validate.log)). El mensaje corresponde al contrato de fuentes de aquella preparación; no se modificó OD en esta tarea ni se rebajó el control. Se preparó únicamente DryRun1000 v7; DryRun10K queda pendiente de una nueva aceptación real. El gateway permite preparar un DryRun no elegible sin trial, pero esta tarea exige esperar y se respeta esa condición.

**DryRun1000 PASS0**, cerrado a las 08:28 Guatemala (14:28 UTC). LaunchId **`a8e8ab4a7c4e49b0b2e7a9cf0927d426`**, `status=dry_run_pass`, `run_launch_eligible=true`, `prior_trial_status=not_applicable_this_is_trial`, `run_id=null`; [estado](../runtime/launches/a8e8ab4a7c4e49b0b2e7a9cf0927d426/state.json), [identidad de preparación](../runtime/launches/a8e8ab4a7c4e49b0b2e7a9cf0927d426/preparation-identity.json), [log persistente](../runtime/diagnostics/run10k-v7-preparation-20261108/dryrun1000-console.log). Huella idéntica a Validate. No se creó carpeta de simulación, población privada, QSim ni replay. Es aprobación de preparación, no aceptación de una Run1000 real.

El plan confirma `simz1Admission.originPolicy=physical-gap-origin-v1`, reserva corporal y `removeStuckVehicles=false`; la etiqueta separada `OriginPolicy=lane-length-access-v1` es la política de selección de orígenes OD, no la de admisión física. Se mantienen 100 GiB mínimos de disco (141.10 GiB disponibles en ese preflight); las guardas originales de recursos no se modificaron y se repetirán normalmente al lanzar. El presupuesto de memoria es una comprobación de planificación, no una medición de escalabilidad.

| Paso | Estado al cierre |
|---|---|
| Identidad v7, selector Run10K y revisión FIFO | Verificados; 50 casos nativos aprobados y controles positivos/negativos preservados. |
| Validate integrado | PASS0, revisión `a1630747…34d6e5`. |
| DryRun1000 v7 | PASS0 y elegible; LaunchId explícito anterior. |
| Run1000 real y aceptación oficial | Pendientes de inicio manual del usuario. No hay nuevo RunId ni recibo de ensayo. |
| DryRun10K | No ejecutado; bloqueado hasta ensayo v7 compatible aceptado. |
| Run10K real | No ejecutada; manual después de DryRun10K elegible. |
| Run55K v7 | No ejecutada ni programada; requiere evaluar Run10K y autorización posterior. |

No se ejecutó Run110K, no se eliminaron resultados ni se editaron recibos históricos. El recibo activo de Validate fue publicado por el flujo oficial y su versión anterior quedó copiada antes de ejecutarlo. Los cambios documentales no pertenecen al inventario actual de la huella; no se modificó ese inventario ni se excluyeron dependencias.

[Recuperación](../runtime/diagnostics/run10k-v7-preparation-20261108/recovery.json), [revisión congelada](../runtime/diagnostics/run10k-v7-preparation-20261108/source-frozen.json), [FIFO nativo](../runtime/diagnostics/run10k-v7-preparation-20261108/fifo-native.json). La corrida histórica `8280dc44854048ffbeb6fae8c21ee7ca` permanece failed/invalid. En la recuperación no había escritores vivos de esa corrida ni otras corridas de escala; Validate ejecutó después sus componentes focales. Los procesos del visor/IDE no se intervinieron.

**Identidad prevista.** [Experimento v7](../scenarios/zona1/experiments/final-20261108-freight-entry-24h-v7.json), [carga v2](../src/main/resources/simz1/freight-entry-completion-v2.json), `physical-gap-origin-v1`, `native_diagnostic_v1`, semilla `20261023`, servicio `2026-10-23`, iteración 0. Demanda `[0,86400)`; `native_qsim_end_seconds` configurado `86399`; cierre observado y censo previo a limpieza con cobertura `86400`, incluyendo los eventos físicos de frontera en T. El selector `run10000` validado declara **4400 carros + 5500 motos + 100 camiones = 10000 no públicos, más 269 buses**; los buses configurados no son el número de expediciones. `run1000` conserva 440/550/10 más 269 buses. La geometría local sigue siendo aproximada, no cartografía GIS verificada.

**Riesgo FIFO demostrado y alcance.** La cabeza diurna vencida impide el avance de la lista compartida de origen, incluso a un camión con su propia ventana nocturna válida. No se rehabilita al abrir otra ventana. Se probó admisión nativa puntual en geometría sintética, no una jornada urbana continua. La limpieza sigue cubierta por la microQSim específica; no se simuló limpieza artificial en la nueva fixture. El contrato v2 prescribe conservar la cabeza hasta censo/limpieza normal, por lo que el bloqueo observado respeta el contrato y supone un riesgo de descarga para Run10K. No se elimina ni se salta la cabeza.

`simz1FreightAdmissionRejected` identifica vehículo, origen, ventana asignada, límite inclusivo y razón `assigned_entry_deadline_expired`; se emite una vez por razón al consultar la cabeza. Los seguidores retenidos no necesariamente generan un rechazo propio. La guarda precede a ocupación, por lo que ausencia de WAIT no demuestra ausencia de espera. El CSV nativo conserva `admission_status=authorization_expired_not_admitted`, `admission_rejection_time/reason` y el límite; el censo distingue `waiting_for_incorporation`/`incorporation_wait`, antigüedad de solicitud y `traffic_entry` ausente. No convertir abortos de limpieza en abortos previos al corte.

Los límites de entrada son 21600 y 61200 inclusivos para las ventanas de madrugada y diurna. La ventana nocturna conserva el límite 108000, fuera de esta jornada de 86400. El mismo límite rige la finalización; entrar justo en el límite no garantiza poder completar con despeje corporal. `fixed-day-24h-v1` admite ciertos `pending_not_evaluable` censurados como integridad técnica válida y no siempre los convierte en `review_required`: un PASS no acredita 100/100 camiones completos ni resuelve el efecto FIFO.

**Criterios de evaluación de Run10K antes de decidir Run55K.** Son comprobaciones de los contratos vigentes y revisión explícita de descarga; no se cambian umbrales ni se publica una autorización automática.

| Evidencia | Revisión exigida |
|---|---|
| Identidad y cierre | LaunchId/RunId exactos, v7, huella congelada, composición, semilla, it.0 y políticas. Separar `completed/valid` nativo, salida del gateway y screening. Código 3 conserva resultados y requiere revisión. |
| Jornada y conservación | Censo nativo `verified_precleanup_census` con cobertura 86400; conciliar programados, salidas, entradas, llegadas, circulación, espera de incorporación y pendientes antes de limpieza. Ausencias no equivalen a cero. |
| Screening oficial | Finalización privada programada y de etapas seleccionadas al menos 0.90; seis perfiles presentes; sin pendientes privados en tráfico por más de 3600 s al corte, salida sin llegada ni terminales inconciliables. Espera de incorporación no es tiempo circulando. |
| Carga | Cero incorporaciones posteriores al límite asignado; entradas/salidas/llegadas/despeje conciliados; nominales, toleradas, excesos y pendientes por ventana/ruta/origen. Revisar por separado todos los vencidos y `not_evaluable`, aun con screening aprobado. |
| FIFO | Contar cabezas vencidas, orígenes, seguidores afectados por familia y antigüedad/intervalo con cobertura explícita. Distinguir rechazo horario de falta de hueco; reconstrucciones de eventos no son snapshots nativos. Un bloqueo material sin resolver impide concluir que procede Run55K. |
| Física y OD | Auditores vigentes aprobados para OD/OSM, FIFO por carril, reserva corporal completa, 0.10 m, recepción, señales/prioridades/paradas y despeje; cero movimientos forzados o retiros por atasco. |
| Buses | 269 configurados separados de vehículos distintos observados y expediciones. Última parada, llegada/despeje, pendientes al corte y abortos previos. |
| Distribución temporal | Series horarias por familia, perfil, OD/acceso: solicitudes, departures, incorporaciones, llegadas y pendientes. Intervalos separados de acumulados; WAIT cuenta intentos. |

Reutilizar primero `analysis/it.0/balanced-launch/report.json`, `hours-00-24.csv`, `day-lifecycle.csv`, `nonpublic-lifecycle.csv`, `bus-expeditions.csv`, `freight-completion.csv`, el CSV nativo de carga y `analysis/it.0/graficas_perfiles/calidad_resultados.json`. Ampliar lectura incremental de eventos sólo si falta evidencia concreta. No repetir QSim por fallos de análisis. Bajo `native_diagnostic_v1`, visor y aceptación visual permanecen manuales y separados; no se ha realizado prueba visual de una Run10K v7 inexistente. La aceptación técnica no es calibración empírica.

**Acciones manuales posteriores, separadas.** No ejecutar el bloque de DryRun10K antes de obtener una nueva Run1000 v7 aceptada. Su código 0 por sí solo no basta: el estado debe declarar `dry_run_pass`, `run_launch_eligible=true` y `prior_trial_status=accepted_same_base_and_revision`. El lanzador real vuelve a verificar estos requisitos. Nunca usar el LaunchId de una corrida real como si fuera un DryRun.

Primera acción pendiente: Run1000 real, desde PowerShell externa. Este comando inicia sólo ese ensayo y su análisis/aceptación oficiales; no encadena otra escala:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -Run -ExperimentSpec .\scenarios\zona1\experiments\final-20261108-freight-entry-24h-v7.json -ExperimentScenario run1000 -DryRunLaunchId a8e8ab4a7c4e49b0b2e7a9cf0927d426 -PostprocessingPolicy native_diagnostic_v1 -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$run1000Exit = $LASTEXITCODE
if ($run1000Exit -ne 0) { throw "Run1000 terminó con código $run1000Exit. Revisar evidencia; no avanzar." }
```

Comprobar oficialmente la aceptación Run1000 después de terminar esa corrida (el gateway publica el recibo; no editarlo ni invocar una aceptación manual):

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& .\.venv\Scripts\python.exe -B .\python\simz1_workflow_state.py require-trial --state .\runtime\workflow\trial-balanced-gateway-v1.json --experiment-spec .\scenarios\zona1\experiments\final-20261108-freight-entry-24h-v7.json --experiment-scenario run10000 --od-mode balanced-gateway-v1 --zone-boundary .\scenarios\zona1\od\balanced-gateway-v1\perimeter.geojson --od-access-catalog .\scenarios\zona1\od\balanced-gateway-v1\access.json --od-mix-file .\scenarios\zona1\od\balanced-gateway-v1\mix.json
$trialExit = $LASTEXITCODE
if ($trialExit -ne 0) { throw "Aceptación incompatible o ausente: código $trialExit. No avanzar." }
```

Preparar DryRun10K únicamente tras esa aceptación:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -DryRun -ExperimentSpec .\scenarios\zona1\experiments\final-20261108-freight-entry-24h-v7.json -ExperimentScenario run10000 -PostprocessingPolicy native_diagnostic_v1 -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$dryRun10kExit = $LASTEXITCODE
if ($dryRun10kExit -ne 0) { throw "DryRun10K rechazado: código $dryRun10kExit. No avanzar." }
```

Run10K real manual, sólo con el nuevo DryRun10K elegible; este bloque no se ejecutó desde Codex:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$run10kDryRunId = Read-Host 'LaunchId exacto del nuevo DryRun10K v7 aprobado y elegible'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -Run -ExperimentSpec .\scenarios\zona1\experiments\final-20261108-freight-entry-24h-v7.json -ExperimentScenario run10000 -DryRunLaunchId $run10kDryRunId -PostprocessingPolicy native_diagnostic_v1 -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$run10kExit = $LASTEXITCODE
if ($run10kExit -ne 0) { throw "Run10K terminó con código $run10kExit. Revisar evidencia; no iniciar Run55K." }
```

**Observación fuera del editor.** Seleccionar el LaunchId real explícito, no el DryRun ni la carpeta más reciente. Listado:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_simz1_110k.ps1 -List
$listExit = $LASTEXITCODE
if ($listExit -ne 0) { throw "Listado rechazado: código $listExit" }
```

Estado ligero, RunId y reloj nativo publicado:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$observedLaunchId = Read-Host 'LaunchId exacto de la corrida real'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_simz1_110k.ps1 -LaunchId $observedLaunchId -Watch -Iteration 0
$watchExit = $LASTEXITCODE
if ($watchExit -ne 0) { throw "Observación terminada con código $watchExit" }
```

Incorporaciones y llegadas, después de existir el manifiesto; utilizar una sola consola lectora por corrida/iteración:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$observedLaunchId = Read-Host 'LaunchId exacto de la corrida real con manifiesto disponible'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_simz1_110k.ps1 -LaunchId $observedLaunchId -Events -Iteration 0
$eventsExit = $LASTEXITCODE
if ($eventsExit -ne 0) { throw "Lector terminado con código $eventsExit" }
```

`-Watch` consulta estados/procesos cada 10 s sin leer XML. `-Events` usa lectura incremental y memoria acotada desde el inicio del archivo, con exclusividad por corrida/iteración; reiniciarlo repite la lectura. No modifica QSim ni publica aceptación. Separar `process_observation.last_completed_step.seconds` de `auditor_coverage_seconds` y `reader_lag_sim_seconds`; `observed.cumulative.entries/arrivals` son eventos acumulados (buses por expedición), mientras `incorporated_unique` cuenta vehículos distintos. `waiting_to_incorporate` describe solicitudes no públicas sin incorporación; no es ocupación vial. `SIMZ1_PROGRESS.arrivals` es del intervalo, no acumulado. El lector provisional no certifica OD/despeje y no expone directamente las denegaciones horarias: consultar después eventos/auditor de carga. `-Reports` genera/verifica derivados y se reserva para cierre `completed/valid`; no es una lectura pura ni hace falta repetirlo si ya existen productos válidos.

No se proporciona ni programa una orden Run55K: primero se evaluará la Run10K identificada y el usuario decidirá su autorización.

<!-- RUN10K_V7_PREPARATION_HISTORICAL_END -->

<!-- RUN55K_FREIGHT_REPAIR_HISTORICAL_START -->
# Histórico: Run55K fallida diagnosticada; corrección de incorporación verificada focalmente

2026-11-08, Guatemala. **Run55K permanece `failed/invalid`, exit 1.** La causa está reproducida y corregida; las pruebas focales y estáticas aprobaron. No se ejecutaron Run1000, Run10K, Run55K, Run110K, Validate integrado ni DryRun. Sólo se ejecutaron componentes y QSim pequeños de prueba. [Cierre y evidencias verificables](../runtime/diagnostics/run55k-freight-failure-20261108/final-status.json).

**Identidad preservada.** LaunchId `8280dc44854048ffbeb6fae8c21ee7ca`, RunId `simz1-7c17e81800f04c8ab41412299800d94f`, it.0, carpeta `scenarios/zona1/montecarlo/run-bg55-8280dc44854048ffbeb6fae8c21ee7ca`. Huella de origen `cd80724f3534cb4b2eb13567ef4e29430e97fc5a0f6bccc2b483f221d0ef51fb`. Los procesos de ese lanzamiento ya no estaban activos; se contrastaron PID, creación, padre y comandos, sin detener simulaciones ni procesos ajenos. Coinciden los inventarios de sus 250 archivos y los 19 hashes comprobados de manifiesto, estado, orquestación y recibos. La evidencia histórica no se modificó.

**1. Causa comprobada.** La salida programada era legal. `QueueWithBuffer.isAcceptingFromWait()` comprobaba flujo y hueco físico, pero omitía la autorización horaria. `QLinkLanesImpl.moveWaitToRoad()` podía comprometer la reserva, extraer la cabeza FIFO y emitir la incorporación después del cierre. `SimZ1Freight.handleEvent()` la rechazaba posteriormente en la línea 278 de la revisión congelada. La espera no es por sí sola el defecto; el defecto es admitir después de vencer la autorización. El rechazo del auditor era correcto para el contrato de origen, no un error de interpretación ni un duplicado demostrado.

**2. Horarios de `freight_000392`.** Roster y plan coinciden; ruta `west-north-elena`, 45 enlaces, origen `osm_406654687_4_forward`. [Metadatos y plan](../runtime/diagnostics/run55k-freight-failure-20261108/case-metadata.json), [seis eventos conservados](../runtime/diagnostics/run55k-freight-failure-20261108/events-target.xmlfrag).

| Hecho o límite | Segundos | Hora simulada |
|---|---:|---|
| Ventana nominal asignada, cierre exclusivo | [32400, 57600) | 09:00–16:00 |
| Salida programada | 50620.17320287385 | 14:03:40.173 |
| `departure` observado, discretización válida | 50621 | 14:03:41 |
| Primer WAIT corporal observado | 56783 | 15:46:23 |
| última incorporación entera permitida por v1 | 57599 | 15:59:59 |
| Finalización tolerada y nueva incorporación v2, inclusivas | 61200 | 17:00:00 |
| Reserva ENTER y progreso nativo observados | 86309 | 23:58:29 |

La espera entre departure y reserva fue **35,688 s (9:54:48)**. La reserva ocurrió **25,109 s después del nuevo límite**. No existe un `VehicleEntersTraffic` serializado del camión: su instante se reconstruye mediante ENTER/progreso a 86309, el orden del productor y la excepción específica; no se fabricó el evento ausente.

La reconstrucción de solicitudes pendientes sitúa 51 delante del camión al salir (posición 52); al WAIT aparece primero entre 15 pendientes. El rechazo nativo dice `origin_no_compatible_accessible_gap`: falta de hueco compatible/accesible para 8 m + 0.10 m. No demuestra agotamiento de todos los metros del corredor. Al ENTER hay 40 solicitudes sin incorporación serializada, incluida la del camión porque falta ese evento. Estos conteos son reconstrucciones de eventos, no snapshots de la cola nativa. Un WAIT no mide segundos ni prueba la causa de cada paso intermedio; no se atribuye una cadena completa de bloqueos aguas abajo sin evidencia. [Reconstrucción y límites](../runtime/diagnostics/run55k-freight-failure-20261108/events-queue-analysis.json).

**3–4. Corrección y contrato.** El contrato histórico `freight-close-plus3600-v1` conserva entrada nominal y tolerancia sólo de finalización. Tras aclararlo, el usuario autorizó expresamente incorporar hasta cierre +3600, manteniendo el mismo límite de finalización. Se creó [v2 de carga](../src/main/resources/simz1/freight-entry-completion-v2.json) y [experimento v7](../scenarios/zona1/experiments/final-20261108-freight-entry-24h-v7.json), derivados de v6; los originales permanecen intactos. No se cambia `physical-gap-origin-v1`, mapa, OSM, OD, horarios, composición, flotas ni jornada de 24 h. La autorización se calcula desde la ventana asignada original; no se reasigna a la ventana nocturna.

La guarda está ahora en `QueueWithBuffer.java:323/333`, antes de flujo, reserva y extracción; consulta `SimZ1Freight.java:102`. `SimZ1FreightCompletion.java:26` y el evaluador Python distinguen v1/v2. Un camión vencido permanece en la cabeza FIFO, sin reserva ni entrada, y emite una denegación explícita. Se conserva la limpieza normal, `requireApproved()`, los rechazos tardíos/duplicados, las pruebas corporales y el screening de finalización fuera de plazo. El generador, manifiesto, selección, trial y monitor verifican la nueva identidad; no hay aceptación retroactiva.

Revisión corregida: **`1923f029075540fbbd36d9191f1452f261f2e35620f967fe6dbe81d19ccefc1d`**, 766 dependencias, ninguna excluida o eliminada. Se revisaron las dos expectativas protegidas modificadas y sus controles negativos; no se editaron recibos. [Revisión de fuentes](../runtime/diagnostics/run55k-freight-failure-20261108/source-review.json).

**5. Pruebas.** Compilación aislada JDK17 y `.venv`. Antes del parche: auditor PASS0; admisión nativa FAIL1, 12 fallos de 20 casos. Después: 42 casos nativos PASS0, incluidos nominal, tolerancia, frontera inclusiva, exceso, cuatro horas después, espera vencida, FIFO y `freight_000392` reconstruido. Pasaron 200 pruebas Python en 15 suites, nueve controles de mutación/ausencia, auditor y cierre Java, 34 componentes y diez comprobaciones extendidas con C529-A/B/C/D, paridad OD de 26 rutas, temporales, rojo y L18. Se conservan los mutantes y validadores de la batería oficial para el próximo Validate.

Dos microQSim v2, de dos actores cada uno, verificaron entrada real a 59390 y llegada corporal a 59407; el negativo negó a 61201, sin entrada/reserva/llegada, conservando el aborto normal de limpieza a 61220 y la excepción esperada `FREIGHT_NOT_APPROVED`. El PASS del test no aprueba esa expedición incompleta. Las capacidades reducidas son exclusivas de esas fixtures sintéticas. También aprobaron QSim de seis y diez actores: cuatro OD, carga, última parada de bus, despeje y censo diario, con 142 negativos sobre copias. [MicroQSim v2](../runtime/diagnostics/run55k-freight-failure-20261108/qsim-admission-v2-attempt1/result.json), [pruebas Python](../runtime/diagnostics/run55k-freight-failure-20261108/static-regression-summary.json), [caso nativo](../runtime/diagnostics/run55k-freight-failure-20261108/corrected-realcase-native.json).

Se conserva un fallo de invocación de `SimZ1OdContractCheck` sin su directorio obligatorio; corregida la invocación con las fixtures originales, pasó con 0. Un descubrimiento unittest vacío no se cuenta como cobertura. La sintaxis PowerShell/Python y `git diff --check` aprobaron.

**6. Recuperación.** Los **4,254,132,060 bytes** originales tienen GZIP válido (CRC/ISIZE) y XML bien formado: **136,205,063 eventos**, último `simz1OccupancyProgress` del camión a **86309**. SHA256 `b63c78d87be6255996dada19c72ddccaec9bbfcd5cef0a5b305af825d87f4f8d`. Se procesaron secuencialmente 70,546,038,076 bytes descomprimidos, con memoria acotada. Dos intentos iniciales de optimización del lector están preservados; la pasada completa final terminó con 0. No quedan lectores activos. [Integridad](../runtime/diagnostics/run55k-freight-failure-20261108/events-integrity.json), [recuperación](../runtime/diagnostics/run55k-freight-failure-20261108/events-recovery.json).

**7–8. Uso y siguiente acción.** Se recuperan hechos y diagnósticos exploratorios, no una jornada científica aceptada: faltan el evento que falló, el cierre/censo completo y las auditorías de una ejecución válida. Los extractos generales tienen límite de 128 MiB cada uno; los seis eventos del camión y el seguimiento de pendientes cubren todo el archivo. No se generaron gráficas oficiales ni se certificó el visor. **Para obtener una Run55K oficial completa hará falta una corrida nueva**, con controles aplicables; el log no es un checkpoint.

Antes de cualquier escala quedan Validate integrado de esta revisión, DryRun exacto de v7 y el ensayo aceptado de la misma base que exija el lanzador, seguidos de decisión/autorización manual. Los recibos anteriores no aprueban esta huella. Una cabeza vencida retiene a sus seguidores hasta el corte por FIFO; la descarga y factibilidad a escala siguen sin acreditarse. La microQSim v2 cubrió un intervalo focal; el censo diario probado conserva carga v1: falta aceptación de jornada completa v7. No se debe repetir Run55K ni lanzar Run10K automáticamente.

Seguimiento de sólo lectura desde la raíz:

```powershell
Get-Content -Encoding UTF8 runtime/diagnostics/run55k-freight-failure-20261108/final-status.json
```
<!-- RUN55K_FREIGHT_REPAIR_HISTORICAL_END -->

<!-- RUN55K_PHASE10B_HISTORICAL_START -->
# Histórico: Fase 10B — secuencia nocturna autorizada con guardas

2026-11-07, Guatemala. El usuario autorizó **una Run1000 v6 real y, sólo tras su aceptación oficial y un nuevo DryRun55K elegible, una Run55K real**. Run10K, Run110K y 180K–220K no están autorizadas. Las fases 8 y 9 permanecen cerradas; no se repitieron ni se convirtió el NO-GO de Run110K en GO.

**Revisión congelada:** `cd80724f3534cb4b2eb13567ef4e29430e97fc5a0f6bccc2b483f221d0ef51fb`, 761 dependencias idénticas. Validate oficial `balanced-launch-fa78d9f2dcb8463dab7fb4479ee4d617`, PASS0 con JDK17, reutilizado tras comprobación canónica. Recibo `runtime/workflow/validated-balanced-gateway-v1.json`, SHA256 `113b427297d225c07c436547e110f7dbdff0e70176472daa9423050bf8445d2f`. No se modificaron producción, demanda, OD, señales, capacidades, rutas, política física ni screening. [Recuperación](../runtime/diagnostics/phase10b-run55k-nocturna-20261107/recovery.json).

El [orquestador independiente](../runtime/diagnostics/phase10b-run55k-nocturna-20261107/orchestrator.ps1) ejecuta **DryRun1000 → Run1000 con análisis/aceptación oficial → nuevo DryRun55K → Run55K**. Sólo usa el gateway vigente, `final-20261106-origin-gap-24h-v6.json`, selectores `run1000`/`run55000`, `physical-gap-origin-v1`, `native_diagnostic_v1`, JDK17 y mínimo 100 GiB. Conserva 440/550/10 y 24,200/30,250/550 no públicos respectivamente, más 269 buses, semilla 20261023, servicio 2026-10-23, it.0, observación de 86,400 s y último paso nativo 86,399.

Cada etapa debe terminar con código 0 e identidad exacta. Código 3 (`review_required`), cualquier fallo o cambio de huella detiene toda la secuencia. El gateway publica el trial por su procedimiento normal; el orquestador exige que el recibo identifique **el Run1000 recién terminado**, con la misma huella y base v6, y ejecuta `require-trial` oficial. Cada Run requiere su propio DryRun elegible; el DryRun bloqueado `e25a61d65d044e4cbd3c1eb53610586f` no se reutiliza. No hay `FirstScaleTrial`, aceptación manual, reintentos automáticos ni escalas adicionales. Una claim permanente creada de manera exclusiva impide ejecutar dos veces esta operación; los mutex y guardas del gateway siguen vigentes.

La sintaxis y el modo de comprobación previa aprobaron con código 0: ocho controles negativos y un caso positivo en memoria; cero QSim y cero recibos publicados en esas comprobaciones. La revisión independiente del script no encontró bloqueos. Una prueba inocua terminó fuera de la sesión de herramientas con padre `WmiPrvSE.exe`, verificando el mecanismo de creación independiente de Windows. El equipo estaba conectado a corriente, sin suspensión/hibernación automática en AC; no se cambió permanentemente ninguna configuración. [Preparación y pruebas](../runtime/diagnostics/phase10b-run55k-nocturna-20261107/prelaunch-status.json).

**La entrega efectiva a Windows se acredita exclusivamente en [handoff.json](../runtime/diagnostics/phase10b-run55k-nocturna-20261107/handoff.json).** Este encabezado registra la preparación; no acredita que Run1000 haya aprobado ni que Run55K haya comenzado. El proceso independiente escribe [operation-state.json](../runtime/diagnostics/phase10b-run55k-nocturna-20261107/operation-state.json), `orchestration.log`, logs completos por etapa y código final. Allí se publican los LaunchId auténticos cuando el gateway los emite. `RUN55K_PENDING_TRIAL` significa que 55K aún depende del ensayo; no es `RUN55K_LAUNCHED`.

Codex realizará una única comprobación de identidad y entrega del proceso y finalizará, sin observar ninguna simulación, abrir visor, leer eventos ni dejar subagentes o monitores. Los controles, análisis y aceptación oficiales posteriores pertenecen al proceso de Windows; no se programa una continuación de Codex. Las evidencias históricas y los servidores existentes se preservan.

Desde la raíz del proyecto, comandos manuales de sólo lectura para el usuario (no ejecutados por Codex):

```powershell
$ops = '.\runtime\diagnostics\phase10b-run55k-nocturna-20261107'
& "$ops\observe.ps1"
& "$ops\observe.ps1" -Watch
# Alternativa puntual al monitor, sin -Events:
& "$ops\observe.ps1" -Evidence
```

`observe.ps1` obtiene exclusivamente el LaunchId real de la etapa Run55K, verifica identidad v6/N/huella/preparación y llama a `scripts/watch_simz1_110k.ps1 -LaunchId <real> -Iteration 0` con la opción elegida. Si aún no existe Run55K, informa el estado pendiente o detenido y no sustituye su ID por el del DryRun.
<!-- RUN55K_PHASE10B_HISTORICAL_END -->

<!-- RUN55K_PHASE10_HISTORICAL_START -->
# Histórico: Fase 10 — RUN55K_BLOCKED_REQUIRED_TRIAL

2026-11-07, Guatemala. **Run55K no se lanzó.** Las fases 8 y 9 estaban realmente cerradas. Se reutilizó legítimamente Validate oficial PASS0 y se ejecutó exactamente un DryRun de 55K. Terminó `dry_run_pass/PASSED`, código 0, pero **`run_launch_eligible=false`**, con `existing_trial_rejected; required_before_Run`. El contrato exige Run1000 aceptado con la misma revisión y base física v6; esta fase no autoriza ese Run1000. [Cierre de Fase 10](../runtime/diagnostics/phase10-run55k-nocturna-20261107/final-status.json).

La huella canónica completa sigue siendo **`cd80724f3534cb4b2eb13567ef4e29430e97fc5a0f6bccc2b483f221d0ef51fb`**, con 761 dependencias idénticas. Validate reutilizado: `balanced-launch-fa78d9f2dcb8463dab7fb4479ee4d617`, JDK17, código 0; recibo `runtime/workflow/validated-balanced-gateway-v1.json`, SHA256 `113b427297d225c07c436547e110f7dbdff0e70176472daa9423050bf8445d2f`. No se repitió la batería ni se modificaron fuentes, políticas o recibos. [Recuperación e inventario](../runtime/diagnostics/phase10-run55k-nocturna-20261107/recovery.json).

**DryRunLaunchId: `e25a61d65d044e4cbd3c1eb53610586f`.** Es preparación, no LaunchId de una corrida real. Se utilizó `final-20261106-origin-gap-24h-v6.json` / `run55000`, con 24,200 carros, 30,250 motos, 550 camiones y 269 buses físicos adicionales; it.0, semilla 20261023, servicio 2026-10-23, observación de 86,400 s y último paso nativo 86,399. Política de posprocesamiento exacta: `native_diagnostic_v1`. La especificación, solicitud, plan de configuración y recibo de preparación coinciden en `physical-gap-origin-v1` (M1/M2/M5), receptor estricto, reserva corporal completa y un hilo QSim. No existe configuración ejecutándose ni manifiesto de Run nuevo. [Estado oficial](../runtime/launches/e25a61d65d044e4cbd3c1eb53610586f/state.json), [identidad y configuración comprobadas](../runtime/launches/e25a61d65d044e4cbd3c1eb53610586f/preparation-identity.json), [log completo](../runtime/diagnostics/phase10-run55k-nocturna-20261107/dryrun.log).

**Guarda que impide Run55K.** El trial conservado pertenece a `simz1-61974d8bfa6a4e5cb34739d9d76c0e3c`, huella histórica `d9c47644bb8d3afa18f383aab1c9d0407fd18228361e06629527d38f8e31a96d` y base anterior. El rechazo oficial dice `Private OD implementation changed since preparation; source fingerprints differ`. `require-trial` exige también la misma base versionada; `FirstScaleTrial` está prohibido para v6. No se modificó ni se volvió a publicar la aceptación antigua. [Rechazo conservado](../runtime/launches/e25a61d65d044e4cbd3c1eb53610586f/04b-same-scenario.log). El runbook conserva comandos históricos v3/`quarter`; no se utilizaron para esta preparación v6. El NO-GO de Fase 9 para la última Run110K se mantiene y no sustituye esta guarda específica.

Java 17.0.12 y el presupuesto de memoria aprobaron. El DryRun observó 146.45 GiB libres y conservó el mínimo de 100 GiB, retención y auditorías. Windows estaba conectado a corriente, con suspensión e hibernación automáticas en AC a 0 (desactivadas); no se cambió energía, pagefile ni servicios. Eso no garantiza supervivencia ante desconexión, cierre de tapa, reinicio o apagado. Los procesos previos del visor y del IDE no se intervinieron.

**No hay PID independiente, LaunchId real ni Run ID nuevos.** No se creó lanzador nocturno, no se entregó una corrida a Windows, no se inició QSim, no se dejó monitor ni subagente trabajando y no se leyeron eventos históricos. La única ejecución de preparación terminó naturalmente. Una autorización posterior para Run1000 v6 y su aceptación real es requisito previo a un nuevo DryRun55K elegible; no se ejecuta nada automáticamente. Por instrucción vigente, la familia futura de 180K–220K queda cancelada; sus evidencias y especificaciones históricas se preservan.

Consulta puntual del bloqueo, sin monitor ni eventos:

```powershell
Get-Content -Encoding UTF8 -LiteralPath '.\runtime\diagnostics\phase10-run55k-nocturna-20261107\final-status.json' -Raw
```

No existe un LaunchId real con el cual construir `-Watch`; no debe sustituirse por el DryRunLaunchId.
<!-- RUN55K_PHASE10_HISTORICAL_END -->

<!-- RUN110K_DECISION_PHASE9_HISTORICAL_START -->
# Histórico: Fase 9 — NO-GO para la última Run110K

2026-11-07, Guatemala. **NO-GO: todavía no hay evidencia suficiente para recomendar la última Run110K.** La incorporación focal y Validate aprobaron, pero faltan Run1000, Run10K y Run55K compatibles con la variante v6, la demostración de descarga y recursos a escala y la inspección visual WebGL. Este dictamen no declara físicamente imposible completar 110K; declara que su factibilidad aún no está justificada. [Decisión formal, doce criterios y diez entregables](../runtime/diagnostics/run110k-go-no-go-phase9-20261107/decision.json).

La revisión real sigue siendo **`cd80724f3534cb4b2eb13567ef4e29430e97fc5a0f6bccc2b483f221d0ef51fb`**, con sus 761 dependencias idénticas a Fase 8. Validate oficial conserva `completed/PASSED`, código 0, JDK17, cierre `2026-11-07T06:51:33Z`, evidencia `balanced-launch-fa78d9f2dcb8463dab7fb4479ee4d617`. No se repitió Validate: esta fase sólo revisó evidencias y metadatos y calculó presupuestos de lectura. Run110K histórica sigue siendo `simz1-d42056291fa2422699a8b6613f795eeb`, LaunchId `748fa7117cdb485ba566a60f289b2994`, iteración 0, `completed/valid`, screening `review_required` y salida del lanzador 3. No se modificaron su manifiesto, eventos ni estado. [Recuperación y huellas](../runtime/diagnostics/run110k-go-no-go-phase9-20261107/recovery.json).

**1. Diagnóstico definitivo de incorporación, dentro de la evidencia disponible.** Los 108,900 privados solicitaron salida dentro del siguiente segundo de su hora original. Solicitar no es incorporarse: `PersonDepartureEvent` y `VehicleEntersTrafficEvent` tienen funciones distintas. La hora del primer intento de cada seguidor no queda acreditada por su solicitud; una cola sin evaluación individual no equivale a rechazos individuales comprobados.

| Familia | Programados | Solicitaron | Incorporados | Llegados | Activos al corte | Pendientes de incorporación |
|---|---:|---:|---:|---:|---:|---:|
| Carros | 48,400 | 48,400 | 8,164 | 5,432 | 2,732 | 40,236 |
| Motos | 60,500 | 60,500 | 10,428 | 6,918 | 3,510 | 50,072 |
| Camiones | 1,100 | 1,100 | 613 | 368 | 245 | 487 |

Los 32 orígenes privados tenían reservas en sus 41 slots modelados, con 46 propietarios. La política histórica exigía slot vacío para esta incorporación al buffer; así podía retener las cabezas de las colas que acumulaban 90,308 privados pendientes. No implica que se evaluaran 90,308 cuerpos ni que cada rechazo histórico fuese indebido. Los 269 buses físicos y sus 15,336 expediciones se contabilizan aparte; 13,343 expediciones no solicitaron salida y no representan otros tantos buses.

En 12 Avenida (`osm_762765906_1_forward`), los dos cuerpos retenidos conservaban unos 2.2 m de huella por slot. El origen está a 29.455442 m del corredor, pero el ancla nativa de actividad está a 125.243190 m. La cota trasera de los propietarios deja 117.015094 m delante de esa ancla. La fixture demuestra que cabe longitudinalmente una incorporación bajo la variante, manteniendo el punto nativo; la regla histórica sigue rechazándola porque el slot no está vacío. Es una **variante de escenario B**, no la demostración de un `if` históricamente mal evaluado. Faltan los permisos simultáneos de cada intento histórico para juzgarlos todos. [Conciliación, tiempos y límites](../runtime/diagnostics/run110k-go-no-go-phase9-20261107/demand-review.json).

**2. Matriz de los catorce mecanismos.** La [matriz completa](../runtime/diagnostics/run110k-implementation-phase8-20261106/decision-matrix-final.json) conserva problema, evidencia, archivos/métodos, reglas, CPU/memoria, riesgo, prueba mínima, antes, después y decisión. La selección vigente es:

| Mecanismo | Aplicabilidad y decisión | Riesgo que limita su uso |
|---|---|---|
| 1. Hueco físico | Implementado en el paquete explícito M1/M2/M5. | Confundir metros agregados con intervalo accesible. |
| 2. Carril de origen | Implementado con conectividad y almacenamiento comunes comprobados. | Declarar independencia sólo por IDs. |
| 3. Solicitudes separadas | Reutilizar espera nativa y agregados; no duplicar colas. | Contar pendientes como cuerpos o darles calle infinita. |
| 4. Equidad por carril | Investigar antes de cambiar el arbitraje. | Adelantar una cabeza bajo el contrato FIFO compartido. |
| 5. Reserva atómica | Integrada con M1/M2, un hilo QSim y compromiso síncrono. | Reservas dobles, ofertas obsoletas y mutación parcial. |
| 6. Caudal por origen | Conservar créditos y débito nativos. | Sobreadmisión PCU o demora artificial de solicitudes. |
| 7. Capacidad aguas abajo | Conservar recepción, pasajes y reservas actuales. | Convertir una consulta favorable en permiso completo. |
| 8. Reintentos por cambios | Investigar si el coste justifica optimizarlos. | Perder un cambio habilitante y crear inanición. |
| 9. Fuentes exteriores | Alternativa de escenario no instalada. | Cambiar frontera, OD o significado de la cola. |
| 10. Anclas y distribución | Auditadas; conservar cuotas y fuentes actuales. | Redistribuir carga para mejorar el indicador sin fundamento físico. |
| 11. Ciclos sin descarga | Reutilizar diagnóstico y completar evidencia simultánea. | Llamar deadlock a cualquier ciclo o liberar por timeout. |
| 12. Reruteo seguro | Conservar algoritmo; extender protección del ancla comprometida. | Cambiar prefijo/cursor/OD o atravesar una reserva. |
| 13. Protección de circulación | Diferida como alternativa separada. | Retener flujo legítimo o alterar capacidad/señales sin prueba. |
| 14. Observabilidad | Reutilizar registros acotados y capas agregadas implementadas. | Confundir ausencia de evaluación con rechazo o fabricar precisión. |

**3. Correcciones efectivamente realizadas.** Fase 9 no cambia producción. Las mejoras anteriores y su acreditación son:

| Archivos y métodos | Cambio efectivo | Evidencia |
|---|---|---|
| `SimZ1CorridorOccupancy.originOffer()`, `activityFromWait()`, `originSlots` | Oferta pura al ancla real; cuerpo, 0.10 m, ruta, conectividad y propietarios; compromiso sin doble reserva; ancla conservada para reruteo. | Diez casos integrados y siete grupos PolicyCheck. |
| `QueueWithBuffer.isAcceptingFromWait()` | Llama al compromiso nuevo después del gate de flujo; conserva débito nativo y FIFO. | Deuda PCU, espera compartida, consulta obsoleta y reserva ajena. |
| `SimZ1AdmissionConfigGroup.validateOriginPolicy()` y `SimZ1Configuration` | Variante opt-in; receptor estricto, reserva completa, queue/FIFO y un hilo; legado predeterminado y fallbacks conservados. | Positivos y configuraciones negativas nativas. |
| `simz1_scale_contract.py`, generación/configuración/lanzador y `simz1_workflow_state.inspect()` | Política v6 vinculada a configuración, huella y ensayo. Se corrigió el despacho v6 que perdía la identidad del trial. | Reproducción previa: tres fallos; después: 18 pruebas de política y 29 de trial aprobadas. |
| `simz1_aggregate_replay.populate()/build()`, `AggregateReplay`, `SimZ1AggregateView`, `/api/aggregate` | Solicitudes por origen y asociación nativa por enlace; ninguna carrocería agregada ficticia. | Conciliaciones de Fase 6, HTTP/DOM y regresiones conservadas. |

El [inventario exacto de archivos y hashes](../runtime/diagnostics/run110k-implementation-phase8-20261106/change-review.json), el [diff exclusivo de Fase 8](../runtime/diagnostics/run110k-implementation-phase8-20261106/phase8-only.patch) y la [revisión del defecto cerrado](../runtime/diagnostics/run110k-implementation-phase8-20261106/final-contract-review.json) permiten separar implementación, variante y reparación. No quedan fallos reproducibles abiertos en ese alcance probado; las causas D aguas abajo siguen siendo desconocidas.

**4. Comparación física antes/después.** Las ocho pruebas y doce trazas del legado integrado coinciden con el productor anterior. En condiciones nativas sembradas equivalentes, el focal pasa de **0 a 2 incorporaciones**, conservando la tercera solicitud en espera; el caso con un slot autorizado libre pasa de **0 a 1**. Se mantienen los negativos de solapamiento, cuerpo anterior, ruta/carril prohibido, reserva, pasaje y flujo. Los QSim pequeños de seis y diez actores completan sus propios recorridos y controles. **Ninguna llegada histórica se atribuye a esta implementación**, y estas entradas focales no prueban recuperación de la red. [Comparación y alcance nativos](../runtime/diagnostics/run110k-implementation-phase8-20261106/native-execution-review.json).

**5. Factibilidad de la demanda 110K.** Se revisaron 32 accesos privados, cuatro de carga y 23 de servicios de bus. Las [series por acceso, hora y capacidad](../runtime/diagnostics/run110k-capacity-phase5-20261106/access-capacity-demand-hourly.csv), [capacidades corporales y PCU](../runtime/diagnostics/run110k-capacity-phase5-20261106/access-capacity-table.json) y [cohortes horarias](../runtime/diagnostics/run110k-capacity-phase5-20261106/cohort-departure-hour.csv) permanecen preservadas. Estos seis accesos concentran 61,948 privados pendientes:

| Acceso privado | Programados | Incorporados | Pendientes | Hora pico | Demanda pico PCU/h | Flujo nominal original PCU/h |
|---|---:|---:|---:|---:|---:|---:|
| 12 Avenida, `osm_762765906_1_forward` | 34,585 | 1,566 | 33,019 | 07 | 1,927.75 | 4,000 |
| Avenida Elena, `osm_381667651_0_forward` | 8,315 | 803 | 7,512 | 07 | 477.75 | 6,000 |
| Avenida Elena, `osm_381667651_3_forward` | 7,368 | 1,048 | 6,320 | 07 | 438.00 | 6,000 |
| 10a Avenida, `osm_511820719_6_forward` | 6,638 | 1,107 | 5,531 | 07 | 380.25 | 4,000 |
| Avenida Elena, `osm_381667651_19_forward` | 7,040 | 1,877 | 5,163 | 17 | 388.00 | 6,000 |
| 15 Calle, `osm_406843605_1_forward` | 5,717 | 1,314 | 4,403 | 17 | 323.75 | 2,000 |

Ninguna hora-origen privada supera el nominal modelado; eso no mide el caudal efectivo del receptor. En 12 Avenida, el presupuesto del programador es 2,000 PCU/h, el almacenamiento de la original es 25.5434 PCU y el almacenamiento declarado de la original receptora inmediata es 1.2115 PCU. Este último dato **no es espacio libre observado**. La recepción disponible, sus créditos y el servicio efectivo permanecen desconocidos para esos cortes. Desde las 11:00 hasta el cierre hay horas completas con pendientes y cero entradas en ese origen. Los pesos longitud útil × carriles y las diez anclas exteriores/22 interiores no constituyen demanda empírica calibrada ni justifican por sí solos concentrar 34,585 salidas en una única cola modelada.

Se conserva la meta de **98,010 llegadas sobre 108,900 privados programados**. La historia registró 12,350; faltaron 85,660 para ese screening. Una cota optimista prueba que al menos 40 salidas de las 23 h no tenían tiempo material suficiente; siguen en el denominador. Esa cota no descarta el 90 %, pero tampoco acredita a los 108,860 restantes. No se cambian horarios ni cuotas. [Revisión de factibilidad y supuestos](../runtime/diagnostics/run110k-go-no-go-phase9-20261107/demand-review.json).

**6. Diagnóstico aguas abajo.** No está demostrada la recuperación de 12 Avenida, 22 Calle, 12 Avenida A, 20 Calle, 11 Avenida ni Avenida Bolívar. En 129 cabezas nocturnas seleccionadas hay 35 restricciones C locales y 94 causas D. No se reprodujo un defecto A pendiente en esa cobertura. Cero SCC en ocho subgrafos parciales no prueba ausencia de ciclos en el grafo global, que está incompleto.

| Ventana histórica | LinkEnter nativos, todas las familias | Llegadas nativas, todas las familias | Alcance |
|---|---:|---:|---|
| 06:30–08:00 | 224,792 | 2,611 | Contador alineado `(inicio, fin]`; sin descarga exacta por calle. |
| 08:00–09:00 | 212,682 | 2,528 | Recuperación agregada; mismo límite de intervalos. |
| 09:15–11:00 | 60,689 | 1,044 | Deterioro sostenido; mismo límite de intervalos. |
| 20:02–21:02 | 0 | 0 | Ventana exacta verificada con extractos; 6,655 activos persistentes. |
| 21:02–24:00 | 182 | 0 | Sólo 25 camiones nuevos, principalmente 14 Calle/13 Avenida; no recuperación de la cohorte anterior. |

12 Avenida conserva una negativa corporal cuya recepción de pasaje completa no está acreditada. En 22 Calle se comprobó un rojo y un dueño real aún sin despeje; eso no demuestra un lock huérfano. En 12 Avenida A los metros libres agregados no prueban un hueco accesible. En 20 Calle existen rojos legítimos locales y rechazos de almacenamiento todavía indeterminados. En 11 Avenida hay déficits corporales necesarios y una dependencia de predecesor comprobada; otras aristas siguen siendo candidatas. En Avenida Bolívar faltan estados conjuntos de pasajes y reservas. Para imputar un rechazo indebido se requieren **cola, receptor, señal, prioridad, cuerpo, pasaje y reservas del mismo intento**. No se liberó nada por tiempo. [Seis corredores, cinco ventanas y dependencias verificadas/candidatas](../runtime/diagnostics/run110k-go-no-go-phase9-20261107/downstream-review.json).

**7. Visor y cobertura real.** Se conservan el HUD de camiones **1,100/613/368/245/487/732**, `partial-native-v1`, `Dibujados`, identidades y reintentos. Las capas muestran pendientes agregados y vehículos asociados a un enlace por evidencia nativa; asociación no significa posición exacta ni hueco disponible. Se reutilizan las conciliaciones de Fase 6:

| Hora | Run110K activos/asociados a enlace | Run1000 histórico activos/asociados |
|---|---:|---:|
| 00:04 | 52/52 | 0/0 |
| 06:30 | 1,194/1,194 | 122/122 |
| 08:30 | 4,400/4,400 | 106/106 |
| 09:15 | 4,955/4,955 | 124/124 |
| 10:30 | 5,662/5,662 | 107/107 |
| 20:05 | 6,655/6,655 | 93/93 |
| 23:00 | 6,680/6,680 | 2/2 |

La cobertura individual histórica sigue siendo prácticamente nula en gran parte del día; los agregados no la convierten en posiciones. HTTP/DOM y conteos aprobaron, pero **WebGL no está inspeccionado**. Se conserva el [procedimiento manual con identidades, horas, filtros, pausa, selección y recuperación](../runtime/diagnostics/run110k-viewer-phase6-20261106/manual-visual-check.json). En esta revisión respondieron las conexiones TCP de 8792–8795; ello no sustituye HTTP ni inspección de píxeles. No se reiniciaron servidores; 8793 conserva su build anterior. [Revisión de cobertura](../runtime/diagnostics/run110k-go-no-go-phase9-20261107/readiness-review.json).

**8. Pruebas y recursos.** Se reutiliza el Validate aprobado y sus regresiones Java/Python/JavaScript, C529-A/B/C/D, OD/OSM, L18, FIFO, prioridades, recepción, paradas, carga, llegada corporal y recibos. Los tres mutantes peligrosos de C529-D dieron 1 como rechazo esperado; las suites dieron 0. Los 142 negativos diarios son mutaciones de copias, no simulaciones adicionales. Los fallos de fixtures y el despacho v6 corregido conservan sus logs. [Códigos y cobertura oficial](../runtime/diagnostics/run110k-implementation-phase8-20261106/validate-coverage-final.json).

El benchmark focal midió 31.25 ms de CPU del hilo por 10,000 intentos bloqueados y 1,472 bytes asignados por intento para la variante; el pico observado del proceso fue 489,455,616 bytes, incluyendo JVM y fixture. La cuantización y orden de medición impiden afirmar una aceleración precisa o extrapolar a 110K. La planificación de recursos de esta fase dio **código 0**, heap QSim 12 GiB, Maven 2 GiB, reserva nativa 2 GiB y posible paginación con 9 GiB de crecimiento de pagefile previsto por la política existente. A `07:02 UTC`, había **146.72 GiB libres**, frente al mínimo conservado de **100 GiB**. Se mantienen dos copias de eventos y dos de planes; la referencia histórica de eventos es una estimación, no un máximo futuro. No se cambió ninguna opción del sistema. **Presupuesto admisible no equivale a rendimiento demostrado.** [Recursos y límites reproducibles](../runtime/diagnostics/run110k-go-no-go-phase9-20261107/resources-review.json).

**9. Plan de ensayos.** El [inventario de 75 lanzamientos](../runtime/diagnostics/run110k-go-no-go-phase9-20261107/launch-metadata-inventory.json) no encontró experimentos v6 ni lanzamientos con la huella actual. El recibo de trial existente pertenece a la huella histórica `d9c47644…`; no se reutiliza. Está preparada la especificación v6 para **Run1000 → Run10K → Run55K → posible Run110K**, siempre con un nuevo DryRun de la escala exacta, revisión de su identidad y ejecución manual posterior por el usuario desde PowerShell externa. Primero debe aprobar el Run1000 de la nueva base. La revisión entre escalas compara los 16 criterios de Fase 8 y puede detener el avance si mejora la incorporación pero empeora la descarga, servicios o seguridad. [Comandos existentes y condiciones de cada etapa](../runtime/diagnostics/run110k-implementation-phase8-20261106/scale-strategy-final.json). Esta fase no concede autorización de lanzamiento ni crea un recibo.

**10. Decisión final y riesgo residual.** El límite actual procede de **factibilidad dinámica no acreditada**, representación/configuración de fuentes aún no justificada a escala y causas aguas abajo indeterminadas. No se atribuye a una insuficiencia estática PCU/h demostrada ni a un defecto reproducible que se esté ocultando. El estado de los doce criterios es:

| Criterio | Resultado para recomendar la última Run110K |
|---|---|
| 1. Incorporación segura | Aprobada en fixtures nativas; alcance focal. |
| 2. Negativos físicos | Conservados y aprobados en la batería revisada. |
| 3. Defectos reproducibles pendientes | Ninguno abierto en el alcance probado; no garantiza ausencia universal. |
| 4. Demanda por acceso | Auditada; factibilidad dinámica y justificación de fuentes pendientes. |
| 5. Dependencias aguas abajo | Analizadas; persisten causas D y grafo incompleto. |
| 6. Huella y Validate | Vigentes y aprobados. |
| 7. Ensayo pequeño con nueva física | QSim de 6/10 actores aprobados; Run1000 v6 de aceptación pendiente. |
| 8. Run10K y Run55K | No ejecutados ni examinados para v6. |
| 9. Recursos | Planificación pasa; rendimiento y volumen a escala no acreditados. |
| 10. Visor | Conteos y agregados verificados; WebGL pendiente. |
| 11. Errores y llegadas | Auditorías/negativos aprobados y fallos visibles; sin garantía general fuera de cobertura. |
| 12. Screening | 90 % y población programada conservados; `review_required` no promovido. |

**NO-GO se mantiene hasta reunir y revisar esas evidencias.** Un 55K satisfactorio no garantiza 110K: pueden aparecer spillback y ciclos nuevos cerca de saturación, cambia la interacción con la flota pública fija, se amplifican las esperas y queda menos tiempo antes del corte. El crecimiento de eventos, memoria y posproceso tampoco es necesariamente lineal. No hay liberaciones por timeout, restricciones retiradas, capacidades ficticias, cambios silenciosos de OD/demanda ni umbrales reducidos que sustituyan estas pruebas.

Esta fase no ejecutó QSim, corridas completas, DryRun ni Validate; no leyó el XML de 121 millones de eventos ni censos/poblaciones masivos, no modificó fuentes y no borró evidencia. Reutilizó informes reducidos, metadatos explícitos y comprobaciones de recursos de sólo lectura. [Cierre e integridad](../runtime/diagnostics/run110k-go-no-go-phase9-20261107/final-status.json). Seguimiento de sólo lectura: `Get-Content -Encoding UTF8 runtime/diagnostics/run110k-go-no-go-phase9-20261107/decision.json`.
<!-- RUN110K_DECISION_PHASE9_HISTORICAL_END -->

<!-- RUN110K_IMPLEMENTATION_PHASE8_HISTORICAL_START -->
# Histórico: Fase 8 — variante de incorporación integrada y validada

2026-11-07, Guatemala. **La variante explícita `physical-gap-origin-v1` está implementada y Validate oficial terminó `completed/PASSED`, código 0, con JDK17 y `.venv`.** Combina M1/M2/M5: hueco corporal verificable, selección del slot permitido y reserva síncrona antes de extraer la cabeza de espera nativa. La política predeterminada sigue siendo `empty-slot-origin-v1`. **No se ejecutó Run1000, Run10K, Run55K, Run110K ni DryRun.** Se ejecutaron únicamente componentes y QSim pequeños de validación. [Cierre verificable](../runtime/diagnostics/run110k-implementation-phase8-20261106/final-status.json).

**Revisión e identidad.** La huella inicial comprobada fue `ee2f343feeed9c307a5d1b82e80359be55fe3737cbcb0d0ee5be8ba5c8d130eb` (757 dependencias). La revisión final es **`cd80724f3534cb4b2eb13567ef4e29430e97fc5a0f6bccc2b483f221d0ef51fb`**, con 761 dependencias, incluidas la política, el experimento v6 y las pruebas nuevas. Run110K histórica conserva Run ID `simz1-d42056291fa2422699a8b6613f795eeb`, LaunchId `748fa7117cdb485ba566a60f289b2994`, iteración 0, `completed/valid` y screening `review_required`. Su manifiesto y estado no se modificaron. Los insumos físicos anteriores, cuotas OD, semilla, horarios, flotas y horizonte permanecen intactos. [Recuperación y respaldos](../runtime/diagnostics/run110k-implementation-phase8-20261106/recovery.json), [fuentes congeladas](../runtime/diagnostics/run110k-implementation-phase8-20261106/frozen-source.json), [cambios de esta fase](../runtime/diagnostics/run110k-implementation-phase8-20261106/phase8-only.patch).

**Selección mínima y clasificación.** La incorporación en un slot ocupado es una **variante de escenario B** frente a la regla histórica de slot vacío; no se presenta esa regla histórica como un defecto A demostrado. M1/M2/M5 forman una sola operación, y su mejora focal no se suma tres veces. Se reutilizan las colas, créditos de flujo, recepción, pasajes, reruteo y observabilidad existentes. Las nuevas colas con arbitraje, reintentos por cambios de estado, fuentes exteriores y protección adicional contra gridlock quedan como alternativas o investigación, con sus requisitos pendientes. [Matriz de 14 mecanismos y diez campos por mecanismo](../runtime/diagnostics/run110k-implementation-phase8-20261106/decision-matrix-final.json).

| Reproducción controlada | Productor previo y legado integrado | Variante integrada |
|---|---:|---:|
| 12 Avenida, dos propietarios aguas abajo y tres solicitudes | 0 incorporaciones | 2 incorporaciones; la tercera espera para evitar solapamiento |
| Un slot compatible bloqueado y otro realmente accesible | 0 incorporaciones | 1 incorporación por el slot accesible |
| Cuerpos de 2.1, 4.5, 8 y 13.5 m, ensayos separados | 0 incorporaciones nuevas por ensayo | 1 por ensayo, conservando 0.10 m de separación |

Estos resultados proceden de estados nativos controlados, no de posiciones históricas reconstruidas ni de una nueva medición de circulación masiva. El ancla del buffer se mantiene en **125.243190 m del corredor**; el inicio del enlace está en 29.455442 m. Se comprueba cuerpo completo, alcance de la ruta, posición de los propietarios anteriores, conectividad original-terminal en todo el prefijo pertinente y reservas. No se desplaza el ancla para hacer caber el vehículo. El límite lateral utiliza el ancho nominal del modelo, sin atribuir precisión GIS. El nuevo ancla comprometida también limita un reruteo posterior.

**Integración y límites físicos.** La oferta es de sólo lectura y no concede flujo, prioridad, verde ni movimiento. El compromiso conserva el débito nativo único, la cabeza FIFO compartida y las reservas. La variante exige receptor estricto, reserva corporal, dinámica queue/FIFO y un hilo QSim. Los buses de servicio, actividades terminales, orígenes cortos, pasajes y topologías no representadas completamente conservan el camino legado. La recepción upstream y la entrada al buffer de actividad tienen contabilidad nativa distinta: no se sustituyen por una suma de metros libres ni por un permiso futuro del receptor. Se mantienen el despeje real, rojos, prioridades, paradas y prohibición de retirar atascados. [Revisión nativa y controles](../runtime/diagnostics/run110k-implementation-phase8-20261106/native-execution-review.json), [contrato versionado](../src/main/resources/simz1/origin-admission-v1.json).

**Pruebas y Validate.** Los ocho casos y las doce trazas del comportamiento legado coinciden con la reproducción anterior al parche. La variante pasó diez casos focales, siete grupos adicionales de controles y QSim de seis y diez actores con OD, carga, bus, última parada, censo y despeje. Los 142 negativos diarios son mutaciones de copias del resultado, no 142 QSim. Pasaron las cinco suites JavaScript focales del visor, nueve negativas de fuentes protegidas, las suites Python afectadas y la batería oficial completa: C529-A/B/C/D, FIFO, descarga independiente, StopAndYield, paradas, llegada corporal, OD/OSM, L18, pasajes, servicios, integridad y recibos. Los mutantes peligrosos de C529-D fueron rechazados como se exige. [Ejecuciones focales](../runtime/diagnostics/run110k-implementation-phase8-20261106/focal-regressions.json), [cobertura integrada](../runtime/diagnostics/run110k-implementation-phase8-20261106/validate-coverage-final.json).

Validate se ejecutó mediante `scripts/check_simz1_110k_balanced_gateway.ps1 -Action Validate -JavaHome 'C:/Program Files/Java/jdk-17'`. El segundo intento terminó a `2026-11-07T06:51:33Z` y publicó normalmente el recibo nuevo para la huella final. Los recibos de trial permanecieron intactos; el Run1000 histórico no aprueba la nueva base. [Estado oficial](../runtime/validation/balanced-launch-fa78d9f2dcb8463dab7fb4479ee4d617/state.json), [log persistente](../runtime/diagnostics/run110k-implementation-phase8-20261106/validate-attempt2.log), [resultado y recibo](../runtime/diagnostics/run110k-implementation-phase8-20261106/validation-result.json).

**Fallos conservados y corregidos.** La revisión independiente encontró un defecto A nuevo en la integración: `inspect()` omitía el despacho v6 y perdería la identidad del ensayo. El primer Validate se interrumpió de forma controlada antes de corregirlo; terminó con código 1, sin aprobación, y su fixture hija terminó normalmente. La reproducción añadió tres pruebas y produjo los fallos esperados antes del cambio. Después aprobaron las 18 pruebas del contrato y las 29 del ensayo. Se conservan además el fallo inicial de una fixture que intentaba sembrar un carril nativo desconectado, la entrada de carriles ausente en una fixture Python y una invocación del runner con dos flags excluyentes. Se corrigieron sus causas, manteniendo los controles. Una actualización externa de clases en `target` motivó compilación focal aislada con JDK17; no se detuvo el IDE. [Defecto y cierre revisado](../runtime/diagnostics/run110k-implementation-phase8-20261106/final-contract-review.json), [interrupción documentada](../runtime/diagnostics/run110k-implementation-phase8-20261106/validate-attempt1-interruption.json), [procedencia de clases](../runtime/diagnostics/run110k-implementation-phase8-20261106/external-target-update.json).

**Coste y observabilidad.** En el benchmark de una cabeza bloqueada, cada ventana de 10,000 intentos conservó movimientos y eventos con el recolector activado o desactivado; no emitió nuevos eventos redundantes durante la ventana estable. La primera ejecución midió 31.25 ms de CPU del hilo por ventana y 1,472 bytes asignados por intento para la variante. La cuantización, calentamiento y orden de medición impiden afirmar una aceleración precisa. El pico observado del proceso de componentes fue aproximadamente 489 MB, incluyendo JVM, carga de red y pruebas. Asignación acumulada, heap y memoria residente se informan separadamente. No se extrapolan estos valores a 110,000 vehículos ni se añadieron snapshots masivos. [Mediciones, unidades y límites](../runtime/diagnostics/run110k-implementation-phase8-20261106/cost-observability-final.json).

**Preservación del visor.** Los 28 archivos respaldados del visor, HUD y pruebas relacionadas conservan sus bytes. Continúan las conciliaciones de camiones, `partial-native-v1`, `Dibujados`, las identidades del replay y las capas agregadas de Fase 6. No se añadieron avisos públicos de L12. Los procesos de 8792–8795 y el Java del IDE conservaron identidad; 8793 mantiene su build anterior. La inspección WebGL pendiente de Fase 6 sigue declarada, con su [procedimiento manual reproducible](../runtime/diagnostics/run110k-viewer-phase6-20261106/manual-visual-check.json). [Integridad final](../runtime/diagnostics/run110k-implementation-phase8-20261106/integrity-after.json).

**Etapa G preparada, sin ejecuciones.** El [experimento v6](../scenarios/zona1/experiments/final-20261106-origin-gap-24h-v6.json) define `run1000`, `run10000`, `run55000` y `run110000`, con la misma política y base física, una iteración y 24 h. La escala final mantiene 48,400 carros, 60,500 motos, 1,100 camiones y 269 buses físicos adicionales. Cada etapa requiere su DryRun nuevo, identidad exacta y Run manual posterior desde PowerShell externa. Se conserva el screening privado del 90 % sobre 108,900 programados para Run110K; las cohortes tardías son un informe adicional. La revisión entre 10K, 55K y 110K es una decisión manual, no un gate automático inventado. [Comandos, recursos, secuencia y 16 criterios de evaluación](../runtime/diagnostics/run110k-implementation-phase8-20261106/scale-strategy-final.json).

Esta validación no demuestra capacidad dinámica para 110,000, recuperación de todos los corredores ni completitud futura. La mejora de incorporación deberá compararse con descarga, congestión, servicios, errores físicos, cobertura y recursos en los ensayos autorizados. Seguimiento de sólo lectura: `Get-Content runtime/diagnostics/run110k-implementation-phase8-20261106/validate-attempt2.log -Tail 20`.
<!-- RUN110K_IMPLEMENTATION_PHASE8_HISTORICAL_END -->

<!-- RUN110K_PHYSICAL_PHASE7_HISTORICAL_START -->
# Histórico: Fase 7 — regresiones físicas e integridad verificadas

2026-11-06, Guatemala. **Validate integrado y las seis comprobaciones nativas complementarias aprobaron con código 0.** Se revisaron las reglas físicas solicitadas, conservando sus controles positivos y negativos. Esta fase no modifica código productivo, pruebas, expectativas de hashes ni parámetros físicos; añade evidencia y actualiza este encabezado. Se ejecutaron componentes nativos y QSim pequeños de las fixtures existentes. **No se ejecutó Run110K, un nuevo Run1000 ni DryRun.** [Cierre verificable](../runtime/diagnostics/run110k-physical-phase7-20261106/final-status.json).

**Revisión e identidad.** La huella inicial y final es **`ee2f343feeed9c307a5d1b82e80359be55fe3737cbcb0d0ee5be8ba5c8d130eb`**; las 757 dependencias conservan individualmente su SHA256. Run110K histórica sigue siendo `simz1-d42056291fa2422699a8b6613f795eeb`, LaunchId `748fa7117cdb485ba566a60f289b2994`, iteración 0, `completed/valid`, screening `review_required`; manifiesto y estado del lanzamiento permanecen idénticos. Se mantienen 48,400 carros, 60,500 motos, 1,100 camiones, 269 buses físicos adicionales, cuatro categorías OD, semilla, horarios y horizonte de 24 h. [Recuperación](../runtime/diagnostics/run110k-physical-phase7-20261106/recovery.json), [comparación de integridad y procesos](../runtime/diagnostics/run110k-physical-phase7-20261106/integrity-after.json).

**Ejecución integrada.** Se utilizó JDK 17 y `.venv`, mediante `scripts/check_simz1_110k_balanced_gateway.ps1 -Action Validate -JavaHome 'C:/Program Files/Java/jdk-17'`. La validación terminó `completed/PASSED`, código 0; el lanzador publicó normalmente el recibo `integrated_validate_pass` para esta huella, a `2026-11-07T05:32:03Z`. Los recibos anteriores se conservaron como respaldo; los recibos de trial no cambiaron ni se promovió Run1000. [Estado del validador](../runtime/validation/balanced-launch-112b9321e45a4348a802ab13eaab2bd3/state.json), [log persistente](../runtime/diagnostics/run110k-physical-phase7-20261106/validate-attempt1.log).

| Regla conservada | Cobertura ejecutada y revisada |
|---|---|
| FIFO por carril y cola original compartida | `ParallelOriginalFifo`, `IndependentLaneDischarge`, `SimZ1LaneHeadArbitrationCheck`, colas de origen y descarga interna. |
| Independencia física de carriles | Controles de slot reservado, original compartida, barrera de parada y descarga independiente; IDs distintos no bastan. |
| Reserva corporal completa y separación de 0.10 m | Ledger mixto, `PhysicalGap`, pasajes, cuerpos de carro/moto/camión/bus y rechazos de solapamiento. |
| Posición y despeje | `ArrivalClearance`, `CrossingClearance`, `OrdinaryReceiptClearance`, `DownstreamRelease`; progreso modelado separado de posición observada. |
| Capacidad de flujo y almacenamiento | Crédito/deuda nativos, receptor ocupado, descarga de originales/terminales y negativa de incorporación sin flujo. |
| Semáforos, rojos y despeje | `SignalGreenWindow`, C529-C/D, L18, pasajes temporales y rojo después de liberar la reserva. |
| Prioridades y StopAndYield | Contratos de prioridad, arbitraje, recepción y nodo nativo con STOP todavía pendiente. |
| Restricciones OSM | C529-B, secuencias OSM y controles de restricciones y procedencia. |
| Rutas dirigidas, giros y secuencias | Seguridad de rutas, cursores por ocurrencia, prefijo preservado e instalación de rutas temporales. |
| Paradas bloqueantes | `BlockingStopCheck` completo y tres variantes de incidente; barrera de 25 s, paso independiente legítimo y FIFO retenido. |
| Última parada y llegada corporal | `DischargeArrival`, `ArrivalClearance`, `DayTransitBoundary`; una llegada exige el evento y despeje adecuados. |
| Carga y ventanas | Suites de servicio, versiones, rutas, accesos exteriores, señales y cierre; censura separada de llegada. |
| Cuatro categorías OD | EE/EI/IE/II en generación, auditoría y fixtures nativas de descarga para carros y motos. |
| Identidades | Planes, tipos, familias, vehículos físicos/expediciones, eventos y censos; negativos de cambios de destino e identidad. |
| Duración y límite de jornada | Día de 86,400 s, salida tardía, cierre y dos iteraciones pequeñas para detectar fugas de estado. |
| Auditorías físicas | Ocupación, cola, reservas, prioridades, eventos y reportes; evidencia ausente o mutada se rechaza. |
| Huellas y recibos | Nueve pruebas focales previas y contrato integrado de secuencias/fuentes; mutación, ausencia y recibos incompatibles rechazados. |

**C529 y servicios.** Los cuatro wrappers C529-A/B/C/D aprobaron sus reproducciones y regresiones. En C529-D los mutantes `red-clears`, `red-credited` y `reservation-bypassed` terminaron con 1, como rechazo exigido por la prueba; el wrapper terminó con 0. L18 conserva sus negativos de receptor lleno, conflicto de conector y rojo; sus escenarios históricos y la variante local no se confunden con una autorización nueva de movimiento. Pasajes temporales, rutas serializadas y paridad de todos los servicios fijos aprobaron. [Inventario nativo y límites](../runtime/diagnostics/run110k-physical-phase7-20261106/native-coverage-review.json), [cobertura OD, jornada y servicios](../runtime/diagnostics/run110k-physical-phase7-20261106/od-services-coverage-review.json).

**Complementos sobre clases actuales, sin overlays.** Tras Validate se ejecutaron secuencialmente `BlockingStopCheck incident-blocking`, `incident-nonblocking`, `incident-free-bus`, `SimZ1OriginAdmissionFixture`, `SimZ1OriginMechanismsCheck baseline` y `SimZ1DownstreamReleaseCheck`; los seis dieron 0. Las dos fixtures de origen tienen ocho casos cada una y reproducen la regla productora actual. El caso de 12 Avenida conserva su ancla de buffer de 125.243190 m y el bloqueo del origen con reservas aguas abajo; el PASS acredita esa reproducción, no la instalación de una solución. M1/M2/M5 sigue siendo la variante evaluada en fases anteriores, sin activar. La diferencia entre recepción upstream y entrada de actividad al buffer continúa documentada como requisito pendiente de integración.

La fixture de descarga ejecutó dos casos de hasta dos actores, con once intentos: rojo, STOP pendiente, deuda de flujo, cuerpo todavía sin despejar, propietario real del pasaje, vencimiento temporal insuficiente para liberar y recuperación tras progreso nativo. Una consulta favorable no se convierte en cruce si falta otro permiso. Se comparó estado antes/después de consultas sin mutación. [Comandos, tiempos y códigos](../runtime/diagnostics/run110k-physical-phase7-20261106/supplemental-executions.json), [origen](../runtime/diagnostics/run110k-physical-phase7-20261106/origin-admission.json), [baseline de mecanismos](../runtime/diagnostics/run110k-physical-phase7-20261106/origin-mechanisms-baseline.json), [descarga y reservas](../runtime/diagnostics/run110k-physical-phase7-20261106/downstream-release.json).

**Alcance y límites.** No se retiró ni debilitó ninguna prueba. Las 142 negativas del censo diario son mutaciones de copias del resultado de una fixture, no 142 simulaciones físicas. Las fixtures históricas de carga de 30 h conservan su alcance histórico; la política futura sigue en 24 h. Un snapshot antiguo de reruteo no incluye `passageRequests`, por lo que su PASS no demuestra igualdad de todo el estado interno; los controles nuevos de consultas aportan cobertura complementaria. Los tests agregados del visor de Fase 6 se reutilizan con exactamente la misma huella. [Revisión de fuentes protegidas y reutilización](../runtime/diagnostics/run110k-physical-phase7-20261106/integrity-coverage-review.json).

No se demostró un defecto nuevo que justificara una reparación física en esta fase. Este PASS no acredita capacidad dinámica para 110,000, cumplimiento del 90 %, ausencia de bloqueos en toda la red ni corrección de cada rechazo histórico con datos incompletos. Permanece pendiente la inspección WebGL descrita en Fase 6. Los servidores 8792–8795 y el Java del IDE conservaron PID, creación, padre y comando; 8793 mantiene su build anterior. No quedan procesos Java de estas pruebas. El comprobador auxiliar de cierre corrigió su propia ordenación manual de hashes para usar la función canónica, sin alterar fuentes ni recibos; [intento conservado](../runtime/diagnostics/run110k-physical-phase7-20261106/integrity-check-attempt1.json).

**Siguiente acción.** Resolver los requisitos de integración de la variante física y completar la inspección visual pendiente antes de preparar un lanzamiento nuevo. Cualquier cambio posterior de fuentes invalida esta revisión y exige las comprobaciones correspondientes; DryRun y Run no se encadenaron. Seguimiento de solo lectura desde PowerShell externa: `Get-Content runtime/diagnostics/run110k-physical-phase7-20261106/validate-attempt1.log -Tail 20`.
<!-- RUN110K_PHYSICAL_PHASE7_HISTORICAL_END -->

<!-- RUN110K_VIEWER_PHASE6_HISTORICAL_START -->
# Histórico: Fase 6 — solicitudes pendientes y asociaciones nativas por enlace

2026-11-06, Guatemala. **Las dos capas agregadas están implementadas y conciliadas con Run110K y Run1000. La inspección visual WebGL queda pendiente por indisponibilidad del navegador.** Los pendientes son solicitudes fuera de la red; los trazos de asociación muestran conteos sobre enlaces, sin fabricar posiciones, carrocerías ni espacio disponible. No se ejecutó Run110K, QSim, Validate ni DryRun. Esta entrega no modifica la física ni acredita que la carga futura pueda completarse. [Cierre y verificaciones](../runtime/diagnostics/run110k-viewer-phase6-20261106/final-status.json).

**Identidades y revisión.** Run110K conserva `simz1-d42056291fa2422699a8b6613f795eeb`, LaunchId `748fa7117cdb485ba566a60f289b2994`, iteración 0, `completed/valid` y screening `review_required`. El control Run1000 es la corrida explícita `simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af`, LaunchId `9d73afe94f0b438d934e6c7870a24b82`, iteración 0, `completed/valid` y screening aprobado; no se sustituye por otra carpeta ni por latest-successful. La huella inicial verificada fue `96333b64f44bf5bdcee5d563ee054f931c42604e6c3e01d6f6c22045cdae3aed` (752 dependencias). La revisión final es **`ee2f343feeed9c307a5d1b82e80359be55fe3737cbcb0d0ee5be8ba5c8d130eb`**, con 757 dependencias, incluidas las nuevas fuentes y pruebas. Build del cliente servido: **`59ee0608837cf98cf557d6097937d0bbb39b277ef6e99db407a899e919b28b45`**. No se actualizaron recibos de aprobación. [Recuperación](../runtime/diagnostics/run110k-viewer-phase6-20261106/recovery.json), [fuentes congeladas](../runtime/diagnostics/run110k-viewer-phase6-20261106/frozen-source.json).

**Instancias nuevas.** [Abrir Run110K en 8794](http://127.0.0.1:8794/index.html?run_id=simz1-d42056291fa2422699a8b6613f795eeb&iteration=0&run_manifest_sha256=07a6fb1349533ce4d6cd8198e5e05c195f3c09d1f97b9aec191bb89ac7fad89a&source_version=4266373e0812451c6580c9f01f9e12713355767b585603645fcb3a984fa425ea&visual_policy=partial-native-v1) · [Abrir Run1000 en 8795](http://127.0.0.1:8795/index.html?run_id=simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af&iteration=0&run_manifest_sha256=750e8c363f8fa8fa2114cc62af39e8194c9be7a935016b0bdda22a7538e31596&source_version=70e464d009b85480aef9483507852e9c42edc4785dbbfa0c371b2abbffad7e0c&visual_policy=partial-native-v1). Ambas usan `partial-native-v1` y datos históricos inmutables. El servidor **8793 sigue activo con su build anterior**, comprobado por hash HTTP; no representa esta revisión. Las copias pequeñas y los índices nuevos están en `runtime/diagnostics/run110k-viewer-phase6-20261106/instances/`; no se reescribieron los exports originales. [Identidad HTTP y consultas](../runtime/diagnostics/run110k-viewer-phase6-20261106/http-verification.json), [procesos comprobados](../runtime/diagnostics/run110k-viewer-phase6-20261106/processes-after.json).

**Solicitudes por origen.** La selección ofrece nombre/enlace, programados del día y hasta el instante, solicitudes, incorporaciones, pendientes, llegadas, activos de la cohorte, retiros observados, familia, solicitud pendiente más antigua, última incorporación, cobertura y cola acumulada por hora. Los activos de una cohorte pueden estar en otros enlaces. Se verifican los **32 orígenes privados**, además de 4 de carga y 23 de servicios de bus. Las 15,336 expediciones se distinguen de los 269 buses físicos. El caso de 12 Avenida conserva al corte 34,585 programados, 1,566 entradas, 33,019 pendientes y última entrada a 37,222 s. No se transforman solicitudes pendientes en vehículos estacionados.

**Asociación por enlace.** El índice usa límites nativos conservados en SQLite, incluidos intervalos sin cuerpo representable, y el censo nativo auditado. Se separan stock, entradas/salidas de pertenencia al tráfico y eventos `LinkEnter/LinkLeave`; la censura no se convierte en salida. La capa muestra familias, última entrada/salida observada, último cambio de asociación, tiempo desde ese cambio, cobertura y residual sin enlace. El color y grosor representan cantidad asociada. El indicador de persistencia exige al menos un asociado y 300 s sin cambio de asociación del enlace: es una señal descriptiva, **no prueba inmovilidad corporal, congestión física ni deadlock**. No se reconstruyen carriles o reservas faltantes.

| Hora | Run110K activos nativos | Asociados a enlace | Sin enlace acreditado | Run1000 activos/asociados |
|---|---:|---:|---:|---:|
| 00:04 | 52 | 52 | 0 | 0 |
| 06:30 | 1,194 | 1,194 | 0 | 122 |
| 08:30 | 4,400 | 4,400 | 0 | 106 |
| 09:15 | 4,955 | 4,955 | 0 | 124 |
| 10:30 | 5,662 | 5,662 | 0 | 107 |
| 20:05 | 6,655 | 6,655 | 0 | 93 |
| 23:00 | 6,680 | 6,680 | 0 | 2 |

También se verificó 24:00: 6,680 activos/asociados en Run110K y 2 en Run1000. Al corte de Run110K concilian **1,083,213 LinkEnter y 1,083,213 LinkLeave** con el extracto histórico. Las entradas/salidas de pertenencia son 1,104,346 y 1,097,666; su diferencia es 6,680. Tener enlace acreditado no aumenta la cobertura de posición corporal. [Conciliación de censos, familias, flujos y accesos](../runtime/diagnostics/run110k-viewer-phase6-20261106/backend-assessment.json).

**Navegación y preservación.** En pausa se consulta el segundo seleccionado; en reproducción los objetivos son por minuto simulado. Una petición en vuelo puede terminar y mostrar su `as_of`; después se consulta el último objetivo pendiente. Así la velocidad 120x no cancela indefinidamente respuestas más lentas. Pausa, retroceso y cambio explícito de hora invalidan datos incompatibles. Los filtros por familia usan los mismos datos; un filtro de ruta sin desglose agregado oculta esas capas y lo declara, manteniendo el filtro original de cuerpos. Se conserva recuperación explícita de errores, sin avisos duplicados. La caché del cliente mantiene cuatro respuestas y el servidor conserva su presupuesto compartido de 64 MiB y dos consultas.

El HUD servido en 8794 es idéntico al de 8793: **camiones 1,100 configurados, 613 incorporados, 368 llegados, 245 activos, 487 pendientes y 732 censurados**. Se conservan `Dibujados`, los reintentos anteriores y la ausencia de avisos públicos históricos L12. Siete componentes de cuerpo/HUD mantienen exactamente sus hashes iniciales; las capas nuevas crean **cero marcadores vehiculares**. Las mediciones corporales históricas se conservan como evidencia previa, sin presentarlas como una nueva inspección visual. [HUD verificado](../runtime/diagnostics/run110k-viewer-phase6-20261106/hud-verification.json), [preservación corporal](../runtime/diagnostics/run110k-viewer-phase6-20261106/body-evidence-preservation.json).

**Pruebas y coste.** Pasaron 63 pruebas de regresión Python, incluidas tres de transporte agregado, y 17 pruebas del backend nuevo; diez suites JavaScript existentes y la suite agregada. Incluyen mutación/ausencia, identidad/política, censura, límites horarios, flujos de duración cero, paradas, expediciones solapadas y respuestas lentas. Pasaron además 16 consultas HTTP reales, 12 rechazos HTTP deliberados y **14 contratos reales en DOM/capas simuladas** con selección y filtros. Esto no equivale a WebGL. [Prueba real de la interfaz](../runtime/diagnostics/run110k-viewer-phase6-20261106/ui-real-contract.json), [revisión independiente](../runtime/diagnostics/run110k-viewer-phase6-20261106/review-implementation.json).

La preparación incremental tardó 179.079 s para Run110K y 103.936 s para Run1000; índices de 585,756,672 y 368,492,544 bytes. Cada preparación exitosa recorrió una vez el censo comprimido y el SQLite correspondiente, sin releer eventos XML. El benchmark final de consultas, incluida serialización, midió 0.473–1.013 s y pico de proceso 70.41 MB en Run110K; 0.082–0.202 s y 42.98 MB en Run1000. La caché del sistema operativo no se vació; estos costes no son sobrecarga de QSim. El arranque de los visores ejecutó sus validaciones espaciales habituales, por separado del benchmark agregado. [Coste Run110K](../runtime/diagnostics/run110k-viewer-phase6-20261106/backend-run110k-final-benchmark.json), [coste Run1000](../runtime/diagnostics/run110k-viewer-phase6-20261106/backend-run1000-final-benchmark.json).

**Observación futura.** Queda una propuesta versionada, no instalada, para contadores incrementales y puntos de control coherentes, con posiciones ausentes explícitas. Los límites corporales modelados no pasan a llamarse posiciones observadas. El presupuesto condicionado de 1.14–2.54 GB raw no incluye todos los índices/metadatos/asociaciones variables; CPU y RAM nativas aún requieren medición comparativa. Se descartan snapshots de todos los actores cada segundo. No se añadieron eventos Java ni datos nuevos atribuidos a la corrida histórica. [Contrato propuesto](../runtime/diagnostics/run110k-viewer-phase6-20261106/future-observation-contract-v1.json), [supuestos, costes y condiciones de adopción](../runtime/diagnostics/run110k-viewer-phase6-20261106/observation-cost-review.json).

**Siguiente acción.** Abrir las URLs exactas nuevas y completar la inspección manual WebGL en ambos tamaños de pantalla y los siete horarios. Dos consultas de Computer Use devolvieron `native pipe unavailable (os error 2)` y `browser access host unavailable`; no hubo acceso a píxeles WebGL. [Bloqueo registrado](../runtime/diagnostics/run110k-viewer-phase6-20261106/browser-verification.json), [procedimiento reproducible y conteos esperados](../runtime/diagnostics/run110k-viewer-phase6-20261106/manual-visual-check.json). Seguimiento de solo lectura desde PowerShell externa: `Get-Content runtime/diagnostics/run110k-viewer-phase6-20261106/server-8794.log -Tail 20`; ver errores en `server-8794.err.log`. Antes de cualquier lanzamiento futuro deben satisfacerse de nuevo Validate/DryRun y las guardas vigentes de la revisión; esta entrega no autoriza Run110K.
<!-- RUN110K_VIEWER_PHASE6_HISTORICAL_END -->

<!-- RUN110K_CAPACITY_PHASE5_HISTORICAL_START -->
# Histórico: Fase 5 — auditoría de capacidad, demanda y tiempo disponible

2026-11-06, Guatemala. **La carga de 110,000 no públicos se conserva, pero su sostenibilidad dinámica no está acreditada.** Ninguna hora de demanda programada por origen supera su tasa nominal original en la comparación realizada. Eso no evita la espera corporal y aguas abajo observada: completaron 12,350 de 108,900 privados, **11.34068 %**, frente al screening original del **90 % = 98,010 llegadas**. Faltaron 85,660 llegadas para ese umbral. La cota temporal acredita **al menos 40 privados sin tiempo material** antes del cierre; no excluye ninguno del denominador ni explica por sí sola los 90,308 pendientes de incorporación.

Se mantienen 48,400 carros, 60,500 motos, 1,100 camiones, 269 buses físicos adicionales, 24 h, iteración 0 única, composición OD, horarios y semillas de demanda/MATSim **20261023**. Identidad histórica: Run ID `simz1-d42056291fa2422699a8b6613f795eeb`, LaunchId `748fa7117cdb485ba566a60f289b2994`, nativo `completed/valid`, screening `review_required`. Estado del lanzador, manifiesto, logs y procesos fueron contrastados. La huella inicial y final es **`96333b64f44bf5bdcee5d563ee054f931c42604e6c3e01d6f6c22045cdae3aed`**, con sus 752 dependencias conservadas. Esta fase añade diagnóstico y documentación; no cambia código productivo, parámetros, horarios ni recibos. **No ejecuta Run110K, QSim, Validate ni DryRun.** [Recuperación](../runtime/diagnostics/run110k-capacity-phase5-20261106/recovery.json), [cierre verificado](../runtime/diagnostics/run110k-capacity-phase5-20261106/final-status.json).

**Contabilidad y unidades.** La demanda PCU siguiente es la suma programada del día, no PCU simultáneamente almacenadas ni capacidad de descarga.

| Familia / unidad | Programados | PCU programadas | Solicitudes nativas | Entradas al tráfico | Completados | Activos al corte | Esperando incorporación | Sin solicitud |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Carros | 48,400 | 48,400 | 48,400 | 8,164 | 5,432 | 2,732 | 40,236 | 0 |
| Motocicletas | 60,500 | 15,125 | 60,500 | 10,428 | 6,918 | 3,510 | 50,072 | 0 |
| Camiones | 1,100 | 3,850 | 1,100 | 613 | 368 | 245 | 487 | 0 |
| Expediciones de bus, flota de 269 cuerpos reutilizados | 15,336 | 44,857.5 | 1,993 | 1,928 | 1,735 | 193 | 65 | 13,343 |

PCU/cuerpo efectivos: carro 1 PCU y 4.5 m; moto 0.25 y 2.1 m; camión **3.5 y 8 m**; Transmetro 3 y 13.5 m; TuBus 2.5 y 12 m. Se conserva separación corporal de 0.10 m, ancho y velocidad por perfil. El camión histórico no se sustituye por las dimensiones del catálogo general. Las 15,336 expediciones no son 15,336 buses físicos nuevos; sus solicitudes y entradas son episodios de servicio. Las 13,343 expediciones sin solicitud observada permanecen separadas de las 65 que solicitaron y esperan incorporación. [Conciliación y procedencia](../runtime/diagnostics/run110k-capacity-phase5-20261106/demand-summary.json).

Las **108,900 solicitudes privadas** ocurren entre 0.000001629 y 0.9999985 s después de su horario: dentro del siguiente segundo nativo. Las diferencias de unos pocos vehículos entre columnas horarias de programación y solicitud se explican por esa discretización. `PersonDeparture` no se cuenta como entrada; no se encontró un retraso privado de horas antes de solicitar. El problema observado se concentra en espera de incorporación y permanencia posterior en la red.

**Auditoría por acceso.** Se identificaron **59 enlaces de origen distintos: 32 privados, 4 de carga y 23 de servicios de bus**. Sus rutas pueden compartir almacenamiento y descarga aguas abajo. La entrega incluye los diez puntos solicitados:

| Punto | Resultado y ubicación |
|---|---|
| 1. Vehículos programados/h | Por enlace, familia y hora; buses expresados como expediciones. |
| 2. Demanda PCU/h | Conversión por tipo efectivo, antes de agregar familias que comparten origen. |
| 3. Solicitudes | Conteo por hora real de `PersonDeparture`; ausencia no se rellena con la programación. |
| 4. Incorporaciones | Conteo y PCU por hora de `VehicleEntersTraffic`; llegada de la cohorte de origen aparte. |
| 5. Flujo | Tasas original/terminales y límite nominal de etapas en serie; crédito/deuda nativos preservados. |
| 6. Almacenamiento corporal | Dominio, slots, metros por slot, huella, ancla real y reservas históricas disponibles. PCU de cada partición separadas. |
| 7. Receptor | Enlaces/colas permitidos por terminal, flujo y almacenamiento declarados, dominio corporal compartido o distinto. Disponibilidad y permiso del intento desconocidos quedan `null`. |
| 8. Cola acumulada | Solicitudes acumuladas menos entradas, en vehículos/episodios y PCU; solicitudes externas no son cuerpos dentro de la calle. |
| 9. Bloqueos | Primer backlog observado, inicio del backlog final sin vaciar, última entrada y horas sin entradas con pendientes. Un backlog o una hora sin entradas no demuestra la causa de un rechazo ni cuándo se evaluó un seguidor. |
| 10. Regulación/fuentes | Recomendación por origen y familia, con requisitos pendientes y sin política nueva instalada. |

[Tabla integrada de 2,184 filas acceso/familia/hora](../runtime/diagnostics/run110k-capacity-phase5-20261106/access-capacity-demand-hourly.csv), [detalle de capacidad y receptores de los 59 accesos](../runtime/diagnostics/run110k-capacity-phase5-20261106/access-capacity-table.json), [tabla compacta de capacidad](../runtime/diagnostics/run110k-capacity-phase5-20261106/access-capacity-table.csv), [resumen y comparación por acceso](../runtime/diagnostics/run110k-capacity-phase5-20261106/capacity-demand-integrated.json). Las capacidades repetidas en filas de distintas familias son **compartidas y no se suman**.

El índice reproduce 6,240 enlaces y 13,708 colas: 6,148 asignaciones explícitas y 92 enlaces con fallback nativo de una cola. Se verificaron periodo de capacidad 3,600 s, paso 1 s, factores de flujo/almacenamiento 1, FIFO/queue y acumulación lenta. El almacenamiento PCU usa el máximo de geometría, mínimo de buffer y mínimo de viaje libre del productor. El almacenamiento de `vehQueue`, el buffer, el ledger corporal y un hueco accesible son restricciones distintas. `isAcceptingFromWait` usa flujo/ledger; no equivale al gate de almacenamiento PCU de `isAcceptingFromUpstream`. Este último comprueba ocupación anterior a añadir el cuerpo y puede sobrepasar discretamente el umbral con el último vehículo. La tasa de tokens tampoco es un techo exacto por intervalo: un vehículo completo puede dejar deuda de crédito. [Métodos, fórmulas, controles y límites](../runtime/diagnostics/run110k-capacity-phase5-20261106/capacity-assessment.json).

**Comparación estática.** En privados, 28 presupuestos de programación igualan el flujo nominal original; cuatro son menores: tres fuentes de Avenida Elena usan 2,000 frente a 6,000 PCU/h, y el focal de 12 Avenida usa 2,000 frente a 4,000. Ninguna de las 768 combinaciones origen/hora privadas supera su presupuesto programador. Tampoco se supera la tasa nominal original en las 96 combinaciones de carga ni en las 552 de expediciones de bus. La mayor razón demanda programada/tasa nominal por grupo es 0.4819375, 0.018375 y 0.9, respectivamente. Son comparaciones del flujo que **se programa en cada origen**: no incluyen como demanda de origen todo el tránsito que cruza después ese enlace y no certifican capacidad efectiva de la red compartida.

**12 Avenida, `osm_762765906_1_forward`.** Tiene 34,585 privados programados, 1,566 entradas y 33,019 pendientes al cierre, equivalentes a 19,333 PCU pendientes. Su pico programado es **1,927.75 PCU/h a las 07:00–08:00** (3,277 vehículos); a las 17:00–18:00 programa 3,353 vehículos y 1,922.75 PCU. No registra entradas desde la hora 11; la última fue a 37,222 s (10:20:22). Primer backlog observado: 16 s; backlog final sin vaciar desde 29 s. Estos instantes describen la cola, no prueban un rechazo físico desde ese momento.

El flujo original nominal es 4,000 PCU/h y las dos terminales tienen 2,000 cada una, en serie con la original. No se suman a 8,000. La original declara 25.543399 PCU de almacenamiento y cada terminal 13.333333; el receptor inmediato `_2_forward.original` declara 1.211516 PCU y comparte el dominio corporal. La disponibilidad del receptor en el intento concreto no se conoce. El ledger tiene 244.458284 m por cada uno de dos slots; la incorporación real al buffer original ocurre a **125.243190 m del corredor**, no a su offset de enlace de 29.455442 m. Dos reservas de moto de 2.2 m siguen ocupando ambos slots. Esa geometría no es un permiso de inserción ni acredita descarga. En los 32 orígenes privados hay 41 slots con 46 propietarios al corte. La revisión de representación sigue siendo la variante M1/M2/M5 de Fase 3, separada del diagnóstico de circulación.

**Cohortes y tiempo hasta el cierre.** El estado al corte es excluyente: completado, esperando incorporación, activo sin llegada o sin solicitud. La insuficiencia temporal es una bandera adicional que puede coexistir con esos estados. Cada cohorte mantiene su horario original y sus tiempos de solicitud, espera y viaje; los censurados aportan duración observada hasta el corte, no una duración final inventada. [96 cohortes familia/hora y tiempos](../runtime/diagnostics/run110k-capacity-phase5-20261106/cohort-departure-hour.csv), [las mismas cohortes expresadas por tiempo disponible](../runtime/diagnostics/run110k-capacity-phase5-20261106/cohort-time-available.csv).

| Salida programada privada | Tiempo disponible al cierre | Programados | Completados | Esperando incorporación | Activos sin llegada | Sin tiempo material acreditado |
|---|---|---:|---:|---:|---:|---:|
| 00:00–01:00 | 23–24 h | 1,178 | 1,178 | 0 | 0 | 0 |
| 01:00–02:00 | 22–23 h | 833 | 833 | 0 | 0 | 0 |
| 02:00–03:00 | 21–22 h | 569 | 569 | 0 | 0 | 0 |
| 03:00–04:00 | 20–21 h | 557 | 557 | 0 | 0 | 0 |
| 04:00–05:00 | 19–20 h | 862 | 812 | 0 | 50 | 0 |
| 05:00–06:00 | 18–19 h | 2,243 | 1,595 | 347 | 301 | 0 |
| 06:00–07:00 | 17–18 h | 6,846 | 3,941 | 2,317 | 588 | 0 |
| 07:00–08:00 | 16–17 h | 10,362 | 2,185 | 5,519 | 2,658 | 0 |
| 08:00–09:00 | 15–16 h | 8,987 | 474 | 7,301 | 1,212 | 0 |
| 09:00–10:00 | 14–15 h | 5,694 | 84 | 5,138 | 472 | 0 |
| 10:00–11:00 | 13–14 h | 4,535 | 20 | 4,229 | 286 | 0 |
| 11:00–12:00 | 12–13 h | 5,680 | 22 | 5,479 | 179 | 0 |
| 12:00–13:00 | 11–12 h | 6,817 | 16 | 6,724 | 77 | 0 |
| 13:00–14:00 | 10–11 h | 5,504 | 18 | 5,421 | 65 | 0 |
| 14:00–15:00 | 9–10 h | 4,521 | 9 | 4,458 | 54 | 0 |
| 15:00–16:00 | 8–9 h | 4,571 | 9 | 4,501 | 61 | 0 |
| 16:00–17:00 | 7–8 h | 6,709 | 10 | 6,614 | 85 | 0 |
| 17:00–18:00 | 6–7 h | 10,382 | 18 | 10,246 | 118 | 0 |
| 18:00–19:00 | 5–6 h | 9,078 | 0 | 9,042 | 36 | 0 |
| 19:00–20:00 | 4–5 h | 4,437 | 0 | 4,437 | 0 | 0 |
| 20:00–21:00 | 3–4 h | 3,421 | 0 | 3,421 | 0 | 0 |
| 21:00–22:00 | 2–3 h | 2,279 | 0 | 2,279 | 0 | 0 |
| 22:00–23:00 | 1–2 h | 1,703 | 0 | 1,703 | 0 | 0 |
| 23:00–24:00 | 0–1 h | 1,132 | 0 | 1,132 | 0 | 40 |

Las salidas usan [inicio, fin); el tiempo disponible correspondiente usa (límite inferior, límite superior]. El corte nativo admite llegada a 86,400 s antes de la limpieza. Las horas de esta tabla son **cohortes de programación**, no horas de llegada o de movimiento. Cero insuficientes acreditados significa que esta cota no los descarta, no que puedan completar todos.

![Diagnóstico de cohortes privadas al corte](../runtime/diagnostics/run110k-capacity-phase5-20261106/cohort-departure-hour.png)

**Cota de tiempo material.** Para privados se calcula el camino más corto en un supergrafo dirigido permisivo de la red nativa, con máxima velocidad del tipo, tiempos redondeados hacia abajo por partición de cola y coste cero para origen/destino. Se relajan giros, modos, carriles, señales, prioridad, cuerpos y esperas únicamente en el cálculo de la cota; no se habilitan esos movimientos. Así se permite incluso una alternativa más rápida que la ruta inicial y se conserva validez frente al reruteo. Para servicios de carga/bus se usan sus rutas fijas congeladas, omitiendo paradas y disponibilidad del bus anterior. Ausencia de topología o de datos produciría indeterminado, no cero. Los recorridos completados se comprobaron contra la cota sin contradicciones.

La desigualdad estricta `salida_programada + cota_optimista > 86400` acredita **21 carros y 19 motos**, programados entre 86,160.5808 y 86,397.5489 s, con cotas de 9–390 s. Los 40 están esperando incorporación. [Identidades y desigualdades verificables](../runtime/diagnostics/run110k-capacity-phase5-20261106/cohort-material-time-insufficient.csv). La cota es deliberadamente débil: prueba **al menos 40**, no el número exacto de viajes inevitablemente censurados. Los otros 108,860 privados no quedan declarados factibles. Como 40 es menor que el margen de 10,890 no completados que admite el 90 %, esta prueba temporal no refuta por sí sola ese objetivo; tampoco lo acredita.

**Factibilidad y decisión.** Generar los 110,000 vehículos y cumplir presupuestos estáticos de los orígenes no demuestra que puedan circular ni llegar en el horizonte. Completar todos al corte tampoco es exigible con estas salidas tardías. La corrida observada incumple ampliamente el 90 % privado y mantiene 90,308 privados esperando más 6,242 activos. La Fase 4 acreditó ausencia de transiciones de la cohorte nocturna retenida y restricciones locales, conservando causas D donde faltaban permisos conjuntos. El tiempo en red o el exceso sobre una cota optimista no se etiqueta automáticamente como retraso causado exclusivamente por congestión: también intervienen señales, prioridad, paradas y representación. Los informes separan esas duraciones; no atribuyen causas individuales ausentes.

No se justifica un regulador adicional **solo** por exceso de PCU programadas en el origen, porque ese exceso no aparece. Tampoco se justifica subir tasas o capacidades. Para los privados corresponde evaluar la representación de admisión y la descarga conjunta con los controles ya propuestos. Para carga y buses se conservan sus fuentes/servicios y se requiere evidencia de recepción y de ejecución antes de regularlos; la ausencia de solicitud de un servicio no se imputa como rechazo de admisión. Si se estudia dosificación, debe ser una variante explícita basada en descarga local demostrada, sin retrasar la solicitud programada, cambiar OD o trasladar entradas arbitrariamente. **La factibilidad dinámica de mantener la carga y alcanzar el 90 % sigue sin demostrarse.** [Revisión independiente de contratos, capacidad y cotas](../runtime/diagnostics/run110k-capacity-phase5-20261106/feasibility-review.json), [revisión de la integración](../runtime/diagnostics/run110k-capacity-phase5-20261106/integration-independent-review.json).

**Verificación y coste.** Pasaron los controles de capacidad, seis pruebas focales del auditor de cohortes, conciliaciones por familia y 768 celdas origen/hora del informe privado previo, integración y revisión independiente. Se conservaron dos detenciones defensivas del índice de capacidad: enlaces sin laneDefinitions resueltos con el fallback nativo comprobado y metadatos de corredor ausentes distinguidos del ledger nativo. No fueron defectos físicos ni se alteraron insumos para aprobar. La lectura principal de demanda fue una pasada incremental por censo privado, auditor de carga y expediciones de buses: 5.845 s de pared, sin medir CPU/pico de memoria. Capacidad registra pared y CPU en sus JSON, con pico de memoria no medido; no es un benchmark online. No se releyó el XML de eventos ni se ejecutó una simulación. La figura diagnóstica fue inspeccionada visualmente; no reemplaza gráficas oficiales ni hubo nueva prueba del visor. HUD y limitaciones visuales aceptadas se conservan.

Siguiente acción: cerrar la observación simultánea de las causas D y evaluar la variante mínima de incorporación junto con descarga aguas abajo mediante pruebas acotadas. La auditoría no autoriza Run110K ni modifica el screening. Seguimiento de solo lectura desde la raíz:

```powershell
Get-Content runtime/diagnostics/run110k-capacity-phase5-20261106/final-status.json -Raw -Encoding UTF8
```

<!-- RUN110K_CAPACITY_PHASE5_HISTORICAL_END -->

<!-- RUN110K_DOWNSTREAM_PHASE4_HISTORICAL_START -->
# Histórico: Fase 4 — congestión aguas abajo y controles de liberación

2026-11-06, Guatemala. **Investigación completada dentro de la cobertura histórica disponible: no se reprodujo un defecto nuevo A del productor.** Hay restricciones locales C comprobadas y causas conjuntas D todavía indeterminadas. No se demuestra un ciclo físico irreversible ni una nueva configuración defectuosa B. Esto no certifica que toda la congestión sea correcta: faltan estados simultáneos de cola, receptor, señal, prioridad, cuerpo, pasaje y reservas en los intentos históricos decisivos. La variante de incorporación propuesta en Fase 3 continúa separada de este diagnóstico.

Identidad conservada: Run ID `simz1-d42056291fa2422699a8b6613f795eeb`, LaunchId `748fa7117cdb485ba566a60f289b2994`, iteración 0, horizonte 86,400 s, nativo `completed/valid`, screening `review_required`. Se contrastaron estado del lanzador, manifiesto, logs y procesos. **No se ejecutaron Run110K, otro QSim, Validate ni DryRun en esta fase.** Solo se ejecutaron componentes Java pequeños contra el productor original, sin el overlay de admisión V2.

La huella real inicial fue `c1c99b3d5ba93ce35c53936d9064db1e6f3fcb5c9b0cc7083dd4a33cb1557045`. La huella final es **`96333b64f44bf5bdcee5d563ee054f931c42604e6c3e01d6f6c22045cdae3aed`**: se conservan las 751 dependencias iniciales y se añade únicamente la fixture `SimZ1DownstreamReleaseCheck.java`, incluida normalmente en el fingerprint. No se modificaron fuentes productivas, insumos físicos ni recibos. [Recuperación](../runtime/diagnostics/run110k-downstream-phase4-20261106/recovery.json), [verificación final](../runtime/diagnostics/run110k-downstream-phase4-20261106/final-status.json).

**Evolución y descarga.** Se reutilizó el escaneo histórico completo de 121,569,942 eventos; esta fase no volvió a leer el XML. Se procesaron los 1,441 registros del contador nativo hasta 86,400 s, el censo privado incremental y ocho snapshots seleccionados. `progress-complete.jsonl` termina en 76,980 s y no se utilizó como cobertura completa del día.

| Ventana solicitada | LinkEnter, todas las familias | Llegadas, todas las familias | Privados incorporados / llegados | Activos privados al final de ventana |
|---|---:|---:|---:|---:|
| 06:30–08:00 | 224,792 (*) | 2,611 (*) | 5,301 / 2,198 | 4,174 |
| 08:00–09:00 | 212,682 (*) | 2,528 (*) | 2,785 / 2,319 | 4,640 |
| 09:15–11:00 | 60,689 (*) | 1,044 (*) | 1,737 / 966 | 5,546 |
| 20:02–21:02 | 0 | 0 | 0 / 0 | 6,242 |
| 21:02–24:00 | 182 | 0 | 0 / 0 | 6,242 |

(*) Los contadores globales matutinos cubren **(inicio, fin]**; no se renombran como [inicio, fin), porque faltan los eventos de los instantes fronterizos. El censo privado sí usa **[inicio, fin)** y la última ventana incluye el corte nativo de 86,400 s antes de la limpieza. Las dos ventanas nocturnas globales están conciliadas con esos límites exactos. LinkEnter cuenta transiciones entre enlaces, no despejes completos del corredor. No hay conteo completo de descarga por calle para las tres ventanas matutinas: los campos faltantes permanecen nulos. [Auditoría temporal y límites](../runtime/diagnostics/run110k-downstream-phase4-20261106/temporal-assessment.json), [30 combinaciones calle/ventana](../runtime/diagnostics/run110k-downstream-phase4-20261106/corridor-window-evidence.csv).

Al normalizar las distintas duraciones, las tres ventanas matutinas registran 41.628, 59.078 y 9.633 LinkEnter/s. Entre 08:00 y 09:00 se recupera esa tasa, pero siguen acumulándose privados; no equivale a vaciar la red. Entre 09:15 y 11:00 cae la circulación. Los WAIT alineados respectivos son 1,991,378; 2,111,059; 4,061,788; 2,808,000 y 8,406,596: **intentos**, no segundos ni vehículos distintos.

La conciliación al cierre es **2,732 carros + 3,510 motos = 6,242 privados activos**; más 245 camiones y 193 episodios de bus activos = 6,680. La flota física de 269 buses y sus 15,336 expediciones siguen siendo magnitudes separadas. El HUD de camiones conserva 1,100 configurados, 613 incorporados, 368 llegados, 245 activos, 487 pendientes y 732 censurados.

**La circulación residual nocturna no es recuperación de la cohorte retenida.** Los 6,655 episodios activos a las 20:05 conservan su último evento LinkEnter hasta el cierre. La última transición previa al intervalo sin movimientos fue a 72,061 s; la primera posterior, a 75,735 s. Los 182 LinkEnter tardíos pertenecen a 25 camiones nuevos, incorporados desde 75,731 s. Bajo el contrato nativo de ruta fija, sus prefijos conciliados contienen **175 LinkEnter en 14 Calle y 7 en 13 Avenida**; ninguno corresponde a las seis calles focales. Se verificaron los hashes del roster y rutas congelados contra el manifiesto, identidades, auditoría técnica válida, ocurrencia única del extremo y conectividad; nueve pares de transiciones retenidos corroboran parte del prefijo. No se inventaron tiempos intermedios ni recorridos posteriores al extremo observado.

Ese prefijo contiene **70 cambios de dominio de corredor**, no 70 liberaciones corporales. Para las seis calles focales se acreditan cero LinkEnter, cero cruces de salida de dominio en la secuencia de enlaces y cero llegadas en 21:02–24:00 mediante esta reconstrucción restringida. No se infiere ausencia de progreso corporal dentro del enlace o de cambios de locks. [Reconstrucción](../runtime/diagnostics/run110k-downstream-phase4-20261106/corridor-freight-prefix-assessment.json), [seis calles](../runtime/diagnostics/run110k-downstream-phase4-20261106/corridor-night-focus-reconstruction.csv), [revisión independiente](../runtime/diagnostics/run110k-downstream-phase4-20261106/temporal-independent-review.json). El extracto `night-movements` cubre solo 72,000–72,300 y 75,660–75,900 s; por sí solo no cubre toda la noche.

**Corredores y clasificación causal.** Los activos de la tabla se atribuyen a cada calle por su último enlace nativo en el censo al cierre; no se cuentan a partir de las reservas corporales ni de la calle de origen. Por ejemplo, los 350 activos de la cohorte de origen focal de 12 Avenida no equivalen a los 187 atribuidos por último enlace a toda esa vía.

| Calle | Privados localizados al cierre | Hallazgo comprobado y límite |
|---|---:|---|
| 12 Avenida | 187 | `z1_03084` y `z1_36824` permanecen en `osm_762765906_2_forward`, con último LinkEnter a 37,215/37,235 s y frente nativo/modelado 244.458284 m en los cortes tardíos. No los limita un líder de su propio slot; faltan partición exacta del receptor y permisos conjuntos del pasaje: **D**. |
| 22 Calle | 161 | A 28,799 s, `z1_59680` tiene rojo: **C local**. El pasaje pertenece a `z1_44606`, adquirido a 28,794 s; no se demuestra lock huérfano. Se respeta el ordinal: el progreso posterior al WAIT solo es una cota retrospectiva, no estado previo. La falta de descarga prolongada conserva **D**. |
| 12 Avenida A | 45 | `z1_71937` espera hacia `_64401505_2`; quedan 2.606213 m agregados frente a su huella de 2.2 m. `z1_48622` espera hacia 20 Calle con 14.386290 m agregados. Ninguna suma prueba hueco accesible ni permisos: **D**, sin alegar déficit métrico inexistente. |
| 20 Calle | 45 | `z1_17647` está en rojo en los intentos muestreados: **C local**. `z1_94711` tiene recepción nativa favorable y restricción corporal no completamente reconstruida; `z1_52030` espera hacia 11 Avenida: **D** para esas causas conjuntas. |
| 11 Avenida | 124 | Hay déficits de almacenamiento en receptores distintos acreditados como **C local**. `z1_57179` comparte dominio entre subdivisiones: no se le suma otra huella. Su frente modelado 35.404313 m está limitado por el predecesor `z1_58636`, frente nativo 60.141439 m; la causa precisa de recepción/partición sigue **D**. |
| Avenida Bolívar | 216 | L12_039/041 esperan hacia `osm_64387808_0_forward` con recepción nativa favorable pero reserva corporal no aprobada; L12_040/043/001 encuentran conector ocupado. Sin todos los permisos y propietarios simultáneos: **D**. El bus requiere pasaje completo donde el carro puede almacenarse; eso no demuestra un fallo de implementación. |

Los IDs abreviados de la tabla conservan sus enlaces completos, ordinales, medidas y siete condiciones disponibles/ausentes en los [21 casos de evidencia](../runtime/diagnostics/run110k-downstream-phase4-20261106/dependencies-fixture-cases.json) y [hallazgos](../runtime/diagnostics/run110k-downstream-phase4-20261106/dependencies-findings.json). Los buses se examinan únicamente como tráfico y propietarios de reservas; no se reabre la reconstrucción de los tres casos visuales L12 aceptados.

**Dependencias y liberación.** Se amplió la cadena candidata de 12 Avenida A a 20 cabezas, a través de 20 Calle, 11 Avenida, 16 Calle y conexiones posteriores hasta 8a Avenida. Encontrar una cabeza en el receptor no prueba que sea el propietario que necesariamente bloquea al anterior; esas flechas se mantienen como candidatas. Las relaciones corporales por ordinal, como `z1_57179` detrás de `z1_58636`, sí tienen evidencia propia. Un rojo no crea por sí mismo una dependencia de recepción.

| Corte del snapshot | Cabezas con decisión vigente revisadas | C local | D | SCC candidatas |
|---|---:|---:|---:|---:|
| 06:30 (reloj 23,399 s) | 32 | 14 | 18 | 0 |
| 08:00 (28,799 s) | 156 | 50 | 106 | 0 |
| 09:00 (32,399 s) | 146 | 69 | 77 | 0 |
| 09:15 (33,299 s) | 128 | 37 | 91 | 0 |
| 11:00 (39,599 s) | 128 | 50 | 78 | 0 |
| 20:02 (72,119 s) | 129 | 35 | 94 | 0 |
| 21:02 (75,719 s) | 129 | 35 | 94 | 0 |
| Corte nativo 86,400 s | 129 | 35 | 94 | 0 |

Estos son subconjuntos seleccionados, no un censo de toda la red ni personas sumables entre cortes. Las mismas 129 cabezas nocturnas conservan evento de enlace, ordinal, slot y frentes en los tres cortes. **Cero SCC en este grafo parcial no descarta un ciclo global**, ni demuestra descarga posible o irreversibilidad. Los snapshots contienen prefijos ordenados de eventos, no toda la cola/vehQueue/buffer y el estado conjunto de prioridad del mismo intento. La coincidencia de segundo no elimina ese límite. Rojo repetido en cortes periódicos tampoco prueba rojo permanente. [Resumen de dependencias y cobertura](../runtime/diagnostics/run110k-downstream-phase4-20261106/dependencies-state-summary.json).

No cambiar de enlace tampoco prueba inmovilidad corporal del modelo: `z1_48622` aumenta su cota de frente de 74.2062 a 83.4062 m entre los cortes de 09:15 y 11:00 sin nuevo LinkEnter. Las motos focales registran recomputaciones `leader_release` a 64,670 y 64,365 s, pero ya tenían frente 244.458284 m a 39,599 s: esas recomputaciones no demuestran un avance adicional. Son cotas modeladas, no posiciones observadas. Algunos casos matutinos vuelven a moverse —por ejemplo L12_010 a 24,934 s y L12_007/013 a 35,906/35,854 s—, control histórico contra declarar irreversible cualquier espera. Las etiquetas antiguas `A_local` se traducen aquí a **C**, y `C_indeterminate` a **D**; no se cuentan como defectos A.

**Pruebas nativas del productor original.** La nueva [fixture Java](../src/test/java/org/matsim/core/mobsim/qsim/qnetsimengine/SimZ1DownstreamReleaseCheck.java) pasa dos casos sintéticos de dos actores como máximo, 11 intentos nodales y cinco cruces efectivos. Compilación JDK17 y ejecución final: códigos 0/0. No pretende reproducir los estados históricos que faltan ni el scheduler global de QSim.

- Una salida nativa del líder actualiza el frente permitido del seguidor y conserva su reserva/ordinal. El seguidor espera mientras tiene deuda PCU; después de procesar su recuperación nativa, está realmente ofrecido en buffer. Rojo y STOP impiden movimiento. Con verde, STOP cumplido y receptor factible, el cuerpo anterior todavía puede rechazar el cruce mediante `admission_conflict_executed`; el progreso nativo del líder permite avanzar después.
- Un pasaje conserva propietario y locks aunque haya vencido su tiempo mínimo si falta despeje corporal. El avance nativo libera una sola vez; el rojo sigue bloqueando al competidor después de liberar y el verde permite el cruce. No se llama a liberación por timeout ni se inyectan posiciones para aprobar.
- Las 11 consultas físicas envueltas por los snapshots se verifican sin mutación mediante comparación profunda de ledger, locks, temporizadores, colas, PCU, crédito, reloj, cursores, eventos y movimientos. La consulta preparatoria anterior al intento de 213 s no tiene una guarda individual; no se afirma pureza universal de cada llamada. Un permiso de consulta no se presenta como movimiento ejecutado.
- Se ejecutaron separadamente contra el baseline original `SimZ1InternalSplitBackpressureCheck` y `SimZ1BlockingStopCheck incident-blocking`, ambos código 0: terminal/receptor lleno conserva al original hasta descarga nativa real; dwell bloqueante 15–40 s retiene el intento a 16 s y conserva reservas/FIFO. La parada de bus es distinta del STOP de prioridad de la fixture nueva.

Los cuatro primeros intentos de la fixture se conservan con fuentes/logs: expectativa STOP incompatible con el rol de avenida del helper; oferta aún ausente por deuda de flujo; atribución incorrecta al receptor; y ejecución forense sin relajar aserciones. El cuarto mostró recepción factible y rechazo por cuerpo del cruce, lo que fundamentó la corrección de expectativa del quinto. **Fueron problemas de preparación/atribución de la prueba, no defectos A del productor.** El helper ya construía nodos strict; solo se alineó su módulo diagnóstico antes de los actores. [Resultado final](../runtime/diagnostics/run110k-downstream-phase4-20261106/native-release-check-attempt5.json), [revisión del código y límites](../runtime/diagnostics/run110k-downstream-phase4-20261106/native-code-review.json), [revisión independiente](../runtime/diagnostics/run110k-downstream-phase4-20261106/native-independent-review.json).

Se preservan las regresiones previas de C529-A/B/C/D, OD/OSM, pasajes, L18, llegada corporal y última parada; no se repite la batería completa ante una adición de prueba sin cambios productivos. El tiempo de pared de los diagnósticos no se declara CPU ni pico de memoria; no se midió impacto online ni mejora de caudal. No se cambió el visor ni se realizó una nueva prueba de navegador. Los servidores existentes y el Java del IDE se conservaron.

**Siguiente acción técnica:** obtener una observación acotada y simultánea de los siete permisos en las cabezas D prioritarias —partición receptora de las motos focales, entrada de 12 Avenida A y recepción compartida de 11 Avenida/Bolívar—, con identidad/ordinal y condición de liberación. Ese registro permitiría una reproducción histórica equivalente antes de un parche. No hay base en esta fase para liberar por antigüedad, forzar cruces, activar `removeStuckVehicles`, aumentar capacidades ni prometer que más incorporaciones resolverán la descarga. Cualquier revisión de política que funcione según el modelo actual seguirá siendo una variante explícita de escenario.

Seguimiento de solo lectura desde PowerShell en la raíz del proyecto:

```powershell
Get-Content runtime/diagnostics/run110k-downstream-phase4-20261106/final-status.json -Raw -Encoding UTF8
```

<!-- RUN110K_DOWNSTREAM_PHASE4_HISTORICAL_END -->

<!-- RUN110K_ADMISSION_PHASE3_HISTORICAL_START -->
# Histórico: Fase 3 — matriz de decisión y solución mínima propuesta

2026-11-06, Guatemala. **Se propone una única variante versionada de admisión, compuesta por M1/M2/M5, y observación mínima M14.** Las colas, créditos PCU, recepción y reruteo existentes se reutilizan. Esta fase compara y decide prioridades; no integra código físico ni ejecuta simulaciones. «Implementar» en la matriz es una recomendación condicionada para la siguiente fase, no una función ya instalada ni una aprobación de Run.

**Precisión de clasificación respecto de las fases anteriores:** el productor aplica correctamente su regla de slot vacío. La reproducción demuestra que esa regla conservadora rechaza una inserción que cumple los controles corporales del caso focal; no demuestra un `if` mal evaluado. Por instrucción de esta fase, M1/M2/M5 se clasifica como **variante explícita del modelo/política de incorporación**, no como reparación de un error de ejecución demostrado. La limitación de representación sigue acreditada. La variante conservaría OD, identidades, horarios, ancla, cuerpos, capacidades, geometría, señales y reservas; su procedencia y comparación con el original deben quedar versionadas. El fallo de API de V1 en C529-B sí fue un defecto de integración reproducido y corregido en el overlay V2. Se conservan los informes anteriores como historia, con esta precisión vigente.

Identidad contrastada: Run ID `simz1-d42056291fa2422699a8b6613f795eeb`, LaunchId `748fa7117cdb485ba566a60f289b2994`, iteración 0, 86,400 s, nativo `completed/valid`, screening `review_required`. La huella verificada es **`c1c99b3d5ba93ce35c53936d9064db1e6f3fcb5c9b0cc7083dd4a33cb1557045`**. La comparación reutiliza las evidencias y ejecuciones de Fase 1/2 ligadas a sus hashes; no convierte sus resultados focales en rendimiento esperado de Run110K. [Recuperación Fase 3](../runtime/diagnostics/run110k-admission-phase3-20261106/recovery.json), [matriz completa de diez campos](../runtime/diagnostics/run110k-admission-phase3-20261106/decision-matrix.json).

La matriz se divide en cuatro tablas enlazadas por ID para que los diez campos sean legibles. **N** = evidencia nativa controlada ya ejecutada; **H** = reconstrucción histórica con cobertura declarada; **S** = prototipo sintético; **pendiente** = no ejecutado. Un «después» S/H no es un resultado de una política física nueva en producción. Los riesgos son cualitativos, no probabilidades medidas.

**Problema, evidencia y decisión.**

| ID | Problema que pretende resolver | Evidencia de Run110K | Decisión y alcance |
|---|---|---|---|
| M1 | Rechazo aunque exista un intervalo corporal accesible en el ancla. | 32 orígenes, 41 slots ocupados, 46 propietarios; en 12 Avenida las dos motos están aguas abajo del ancla 125.243190 m. | **Implementar**, dentro de una sola variante M1/M2/M5, tras cerrar geometrías no cubiertas. |
| M2 | No utilizar otro slot permitido y realmente accesible. | Hay dos slots focales; los IDs de carril por sí solos no prueban independencia. | **Implementar** la selección dentro de la misma variante; no crear carriles ni reasignar reservas. |
| M3 | Confundir solicitudes pendientes con cuerpos circulantes. | 90,308 privados sin incorporación; Departure y TrafficEntry son distintos. La waitingList ya los separa. | **Descartar** una segunda cola; conservar la existente y ampliar observación mediante M14. |
| M4 | Bloqueo de cabeza entre fuentes que podrían ser independientes. | Fixture reproduce cabeza bloqueada y seguidor no examinado; la independencia física de nuevas fuentes no está demostrada. | **Investigar**; dividir fuentes sería una nueva política. Mantener FIFO global vigente mientras tanto. |
| M5 | Doble reserva, oferta obsoleta o incorporación parcial. | La admisión actual ya reserva antes de poll/TrafficEntry; no hay prueba histórica de doble incorporación. El riesgo aparece al ampliar M1/M2. | **Implementar** como parte inseparable de esa variante, preservando el compromiso serial y la API original. |
| M6 | Exceder flujo permitido o confundir solicitudes con entradas. | Hay espera de origen, pero el cortocircuito de flujo no siempre emite WAIT corporal. No se demostró un crédito PCU incorrecto. | **Descartar** un regulador adicional arbitrario; conservar crédito, deuda y débito nativos. |
| M7 | Admitir sin recepción pertinente o exigir demasiado aguas abajo. | Al corte aparecen restricciones de almacenamiento/pasaje; no equivalen a ruta completa bloqueada ni a permisos futuros. | **Descartar** un veto de ruta vacía o de recepción upstream para toda actividad; conservar controles nativos por etapa. |
| M8 | Recalcular consultas sin cambios relevantes. | Predominan WAIT nodales; los WAIT de origen ya se deduplican por causa. Ningún contador mide CPU por sí solo. | **Investigar** equivalencia y perfil de coste antes de omitir intentos. |
| M9 | Evaluar una fuente exterior explícita si la representación del origen actual no basta. | El focal ya es un ancla exterior; moverlo a `_0` daría 257.767089 m exteriores frente al máximo contractual de 250 m. | **Mantener como alternativa** de escenario; no es una corrección equivalente ni necesaria para el caso focal. |
| M10 | Concentración de demanda en una sola fuente; no está demostrado que represente demasiados ingresos físicos reales. | Las 34,585 elecciones coinciden exactamente con pesos y semilla: 24,714 EE + 9,871 EI. | **Mantener como alternativa** una política de fuentes con procedencia física; descartar redistribución arbitraria para mejorar resultados. |
| M11 | Distinguir ciclos de dependencia, falta de descarga y espera recuperable. | 6,680 activos; 789 WAIT vigentes; estados nativos incompletos. Cero SCC en los grafos cubiertos no descarta gridlock global. | **Investigar** captura simultánea faltante; reutilizar el diagnóstico offline, sin añadir todavía un controlador de ciclos. |
| M12 | Obtener una salida mediante una ruta alternativa legítima. | 1,571 contextos conciliados; 1,051 instalaciones históricas y 40 alternativas no instaladas por rechazo de almacenamiento. | **Mantener como alternativa** el reruteo protegido existente; no duplicarlo ni forzar las rutas rechazadas. |
| M13 | Evitar que nueva admisión agrave un bloqueo recuperable. | Falta descarga observable completa por ventana/corredor; cero descarga por sí solo no prueba irreversibilidad. | **Investigar** una nueva política preventiva con parámetros explícitos; no dosificar arbitrariamente. |
| M14 | Saber cuándo se evaluó una cabeza y por qué esperó. | Faltan primeros intentos individuales; seguidores no evaluados no son rechazos. WAIT no cuenta vehículos ni segundos. | **Implementar** observación mínima acotada, sin conceder movimiento, con medición de coste e identidad nativa. |

Naturaleza por ID: **M1/M2/M5**, una variante de admisión (compatibilidad de slots y compromiso serial ya existen); **M3/M6/M7/M12**, conductas nativas correctas en lo revisado; **M4/M9/M10/M13**, políticas alternativas de escenario, sin defecto físico demostrado; **M8**, optimización de una reevaluación actualmente correcta, pendiente de equivalencia; **M11/M14**, lagunas de observabilidad, sin nuevo defecto de movimiento acreditado. No se atribuye a ninguna ausencia de datos el significado de permiso o de fallo físico.

**Archivos, métodos, invariantes y riesgo.** Los enlaces de archivo siguientes identifican los puntos principales; la matriz JSON conserva ubicaciones y referencias adicionales por mecanismo. Q = [QueueWithBuffer.java](../src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/QueueWithBuffer.java); L = [QLinkLanesImpl.java](../src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/QLinkLanesImpl.java); O = [SimZ1CorridorOccupancy.java](../src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/SimZ1CorridorOccupancy.java); R = [CongestionAwareRerouting.java](../src/main/java/gt/edu/uvg/sim/zona1/CongestionAwareRerouting.java); D = [SimZ1Diagnostics.java](../src/main/java/gt/edu/uvg/sim/zona1/SimZ1Diagnostics.java); B = [simz1_balanced_od.py](../python/simz1_balanced_od.py). Los métodos `candidate*` solo están en el [overlay V2](../runtime/diagnostics/run110k-admission-phase2-20261106/candidate-v2/manifest.json). Ninguno de estos archivos productivos se modifica en Fase 3.

| ID | Archivos y métodos afectados si se adopta | Reglas físicas/contables que conservar | Riesgo de bloqueo nuevo |
|---|---|---|---|
| M1 | O: `choose`, `activity`, `freeFront`, `routeReach`; overlay `candidateOriginOffer`. | Cuerpo entero, 0.10 m, ancla y dirección, soporte de ruta por ocurrencia/setback; no insertar por delante de propietarios. | Alto al generalizar fuera del foco: ancla o cola mal representada. No confundir holgura métrica con acceso. |
| M2 | O: `compatibleSlots`, oferta del overlay; L: `moveWaitToRoad` como consumidor, sin cambiar FIFO. | Tipos, giros/OSM, dominio compartido, locks, reserva de slot estable. | Alto si se declara independencia por ID, se mueve lateralmente una reserva o se omite un bloqueo compartido. |
| M3 | L: `getWaitingList`/`moveWaitToRoad`; prototipo `Request` y `OriginObservation`. | Identidad, OD, ruta, horario/solicitud original; pendiente no ocupa espacio vial. | Una segunda cola puede duplicar IDs, divergir del censo o conceder espacio ficticio. |
| M4 | L: arbitraje previo a `isAcceptingFromWait`; prototipo `IndependentArbitration.choose/commit`. | FIFO por fuente físicamente acreditada; ofertas fallidas no retiran cabeza; equidad solo con oportunidad legal. | Alto: adelantamiento indebido, recursos compartidos o inanición al repartir créditos. |
| M5 | Q: `isAcceptingFromWait`; O: `activity`, `enter`, overlay `candidateActivityFromWait`. | Consulta pura no es permiso; recomprobar antes de reservar; sin eventos ni reservas parciales; escritor serial. | Alto si se reutiliza una oferta, cambia el contrato API o se conserva estado de pasaje obsoleto. |
| M6 | Q: `hasFlowCapacityLeft`, `updateFastFlowAccumulation`, `updateSlowFlowAccumulation`, `addToBuffer`, `addFromWait`. | Presupuesto/deuda/débito PCU nativos; no reescribir hora de solicitud. | Un segundo limitador puede retener una entrada legal, duplicar débito o alterar el reparto. |
| M7 | O: `receiverFeasibility`, pasajes/locks; Q: recepción y buffer; nodo nativo y `StopAndYield`. | Recepción inmediata, señal, prioridad, paradas y despeje en su etapa; vehQueue y buffer no son lo mismo. | Alto si se exige ruta vacía, se confunde consulta con autorización o se omite recepción posterior de un pasaje. |
| M8 | Q: actualización de flujo; O: progreso/liberación; eventos de señal/parada/ruta; prototipo `may_skip_shadow`. | Mismos movimientos, tiempos y orden; dato desconocido fuerza reevaluación; no caducar reservas. | Alto: perder una transición verde, crédito, fin de parada, progreso o cambio de cabeza produce bloqueo artificial. |
| M9 | B y contratos de acceso; importador de red y fuente explícita solo en variante nueva. | Frontera/OD, topología, cola exterior declarada y entrada solo con recepción nativa. | Alto: fuente sin recepción, conector sin capacidad o cambio encubierto de frontera. |
| M10 | B: `origins`, `sample`, `IncorporationBudget.accept`; `simz1_od_policy.allocate` y catálogo/política versionada. | Cuotas, semilla/procedencia, OD, puntos reales, capacidades y restricciones; conservar variante original. | Redistribuir puede trasladar el cuello de botella, concentrar más tráfico o crear accesos inexistentes. |
| M11 | D y decisiones/reservas nativas; diagnóstico `circulation-audit.py`, `scc`. | Un mismo estado simultáneo, propietarios y liberación corporal; ciclo candidato no es deadlock. | Instrumentación mal situada puede bloquear escritores; un controlador basado en falsos ciclos puede retener o liberar indebidamente. |
| M12 | R: `evaluate` y ruta candidata/instalación; O y contrato OD/OSM por ocurrencia. | Identidad, destino, prefijo, cursor, clase, permisos y reservas; candidato ≠ factible ≠ instalado. | Reruteos inválidos u oscilantes pueden romper reservas o mover la congestión; una ruta rechazada no es una salida legal. |
| M13 | Q/O en un posible gate nuevo; observador `circulation-policy-evaluate.py`. | Solicitud puntual, capacidades/señales intactas, no vaciar por timeout; cobertura explícita de descarga. | Alto: un umbral arbitrario o una medición atrasada puede impedir la recuperación que busca proteger. |
| M14 | L/Q para cabeza/flujo; D/censo de ciclo de vida; `OriginObservation.attempt/entered/moved/route`. | Entrada solo por evento nativo; no evaluado ≠ rechazado; unidades, identidad y corte temporal. | Bajo en física si es de solo lectura; riesgo operativo de exceso de logs/memoria o de observación que cambie el estado. |

**Prueba nativa mínima y comparación antes/después.** Las ejecuciones citadas se realizaron en Fase 1/2; Fase 3 no las repite. «Sin cambio productivo» es un resultado explícito, no un PASS implícito de la propuesta.

| ID | Prueba nativa mínima y estado | Antes | Después disponible |
|---|---|---|---|
| M1 | **N existente:** ancla focal con dos propietarios aguas abajo; negativos cuerpo solapado/aguas arriba/flujo. **Pendiente:** ancla frente a `routeReach`/setback y salidas interiores. | Paquete original: 0 entradas, 3 solicitudes pendientes. | Paquete V2: 2 entradas en slots distintos, 1 pendiente. No atribuir esta ganancia por separado a M1, M2 y M5. |
| M2 | **N existente:** slot bloqueado y otro compatible accesible; negativos giro/modo/ancho/reserva compartida. | El origen conserva la política conservadora y la cabeza global. | V2 selecciona el slot accesible; conserva FIFO y no reasigna reservas. Es control del paquete, no ablación independiente. |
| M3 | **N existente:** esperar sin reserva, entrada única al aprobar; Departure separado de TrafficEntry. | waitingList ya independiente de cuerpos. | Sin cambio productivo. **S:** contrato de solicitud conserva metadatos y consulta censo/cabeza autoritativos. |
| M4 | **Pendiente nativa:** dos fuentes realmente independientes y una fuente compartida, cabeza bloqueada, elegibilidad cambiante y servicio repetido. | **N:** una cabeza rechazada impide examinar al seguidor. | **S:** round-robin conserva FIFO de fuentes certificadas; no demuestra que dividir el origen nativo sea correcto. |
| M5 | **N existente:** oferta repetida sin mutación; alterar slot/ruta/ancho entre consulta y compromiso; doble reserva y pasaje adquirido; compatibilidad C529-B. | `activity` reserva serialmente; V1 rompió llamadores métricos. | V2 deja API original intacta y pasa los controles; no acredita atomicidad multihilo general. |
| M6 | **N existente:** crédito agotado y posterior recuperación, deuda/FIFO de slots y ausencia de entrada/reserva al rechazar. | Gate y débito nativos ya operativos. | Idénticos bajo V2; no se midió ni promete aumento de caudal por un regulador nuevo. |
| M7 | **N existente:** receptor lleno/libre, rojo/verde, pasaje/stop y despeje; buffer libre con vehQueue llena. | Guardia correcta según etapa; recepción upstream y actividad al buffer difieren. | V2 conserva las guardas; permite holgura corporal focal sin exigir ruta vacía. Sin efecto aislado de M7 medido. |
| M8 | **Pendiente nativa:** trazas diferenciales idénticas incluyendo rojo→verde, créditos, dwell, reservas, progreso, ruta y cabeza. | Reevaluación nativa normal; no hay perfil comparativo de CPU. | **S:** vector completo/plazo obliga a reevaluar cuando corresponde; ningún intento nativo omitido. |
| M9 | **Pendiente nativa en variante:** conector exterior limitado, receptor libre/lleno, cruces de frontera y conciliación OD. | Origen actual intacto. | **H:** mover a `_0` incumple el máximo exterior vigente; no se construyó ni ejecutó esa variante. |
| M10 | **H existente:** replay de 108,900 selecciones por identidad y negativos semilla/pesos/consumo RNG. **Pendiente nativa para variante:** fuentes reales con igual contrato OD y límites de capacidad. | 34,585 focales por pesos originales. | Se reproducen exactamente; cero cambios de distribución, planes o rutas. |
| M11 | **Pendiente nativa:** ciclo cerrado y controles con escape, fase verde, despeje y dato ausente, todos en el mismo estado. | Esperas prolongadas no prueban ciclo irreversible. | **H/S:** diagnóstico parcial y controles SCC; cero ciclos en la cobertura disponible, sin conclusión global. |
| M12 | **N existente:** C529-A/B/C/D, rutas temporales, repetición de enlace/ocurrencia, OD/OSM y reservas; receptor favorable/desfavorable. | Reruteo protegido ya instalado; rechaza candidatos físicamente inviables. | Sin ruta nueva generada/instalada. Las 40 no instaladas revisadas siguen siendo rechazos, no alternativas habilitadas. |
| M13 | **Pendiente nativa:** atasco con escape y sin escape; observador encendido/apagado con movimientos idénticos. Una dosificación declararía sus demoras deliberadas, mantendría solicitud original y probaría reanudación y ausencia de inanición artificial. | Sin nuevo limitador preventivo ni umbral calibrado. | **S:** 12 controles de observación; sin permiso físico, dosificación ni mejora de descarga demostrada. |
| M14 | **N parcial:** trazas de fixture y atribución de flujo/cabeza. **Pendiente integración:** eventos/tiempos idénticos con observador encendido/apagado y primer intento persistido por ID. | Faltan primeros intentos históricos; no son recuperables por inferencia. | **S:** observador acotado y 11 controles compartidos M3/M4/M8/M14; sin hooks productivos ni medición de overhead nativo. |

**Coste CPU/memoria.** No se asignan números de CPU ni RAM nativa sin medición. Las descripciones de crecimiento son inspección de código/diseño, no benchmarks. Conservar una guarda existente significa que no se propone un coste nuevo, no que su coste total sea cero.

| ID | CPU / trabajo adicional previsto | Memoria adicional prevista | Medición disponible y límite |
|---|---|---|---|
| M1 | Consultar ruta, ancla y reservas de los slots por cabeza candidata. | Temporales de consulta; reutiliza ledger, sin nueva cola. | CPU/pico nativos y diferencia baseline/V2 no medidos. Coste inseparable del paquete sin benchmark específico. |
| M2 | Examinar slots compatibles y acceso corporal; aumenta con candidatos y propietarios. | Lista/conjunto de slots y ruta temporales; no nuevos cuerpos ni carriles. | Sin coste nativo separado de M1/M5. |
| M3 | Reutilizar waitingList no añade arbitraje; validar metadatos añade comparaciones. | No duplicar censo/rutas. Persistir primeros intentos puede añadir campos por ID al censo existente. | El prototipo no mide memoria de un censo nativo completo. |
| M4 | Revisar cabezas elegibles por ronda; validar certificados de recursos compartidos. | Estado por fuente y certificados; riesgo de duplicar rutas si se diseña mal. | Solo controles sintéticos, sin CPU/RAM nativas ni ahorro demostrado. |
| M5 | Recomprobar oferta y registrar reserva dentro del flujo serial. | Oferta efímera y estructuras de reserva ya existentes. | No asumir que consulta+compromiso es gratis; sin benchmark nativo ni desglose por mecanismo. |
| M6 | Se conserva actualización/débito de crédito por consulta; un segundo regulador añade decisiones. | Crédito/deuda existentes; no se propone estado adicional. | No hay medición nueva; no se asigna coste cero al motor. |
| M7 | Se conservan comprobaciones locales/pasajes; recorrer toda la ruta sería trabajo y bloqueo adicionales. | Locks/reservas existentes; no se propone otro ledger. | Sin perfil nativo por guarda. La capacidad libre es una magnitud física, no una medición de RAM. |
| M8 | Comparar revisiones/plazo más gestionar invalidaciones; beneficio neto depende del perfil real. | Revisiones/suscripciones por dependencia y cabeza; necesita límite y limpieza. | Ahorro CPU no medido. WAIT cuenta intentos; 45,548,492 WAIT nodales no son segundos de CPU. |
| M9 | QLinks/colas/recepción adicionales y cruces de frontera del conector. | Depende del número de fuentes, cola exterior y política de capacidad declarada. | Ninguna variante ejecutada; coste no medido ni parametrizado todavía. |
| M10 | Preparación de candidatos/pesos y selección por demanda; depende de la política nueva. | Catálogo y pools de fuentes; no deben duplicarse cuerpos para repartir demanda. | Replay histórico mide explicación de selección, no CPU/memoria de una red redistribuida. |
| M11 | Construcción del grafo; recorrido SCC lineal en vértices+aristas, más ordenaciones deterministas y obtención de dependencias fiables. | Grafo/estados y evidencia; puede crecer con candidatos de propietario. | 1.139337 s de **pared** del diagnóstico conjunto M11/M12, sin CPU/pico RAM ni coste online medidos. |
| M12 | Evaluación de rutas y contratos existente; crece con búsqueda, alternativas y prefijo. | Ruta/caché/contexto existentes; conservar límites del rerouter. | Hay instrumentación `cpuNanos`/`wallNanos` en el productor, sin agregado comparable reutilizado aquí. No inferir coste del rerouter del diagnóstico offline. |
| M13 | Medir ventanas y dependencias; el coste de un gate real depende de su diseño y frecuencia. | Contadores por ventana/corredor y, si se usa, grafo simultáneo. | Doce pruebas sintéticas, sin benchmark CPU/RAM de política nativa. |
| M14 | Actualización acotada por evento/cambio, con consulta autoritativa de identidad; evitar log por intento. | Última cabeza/motivo por origen y hasta 1,440 buckets por origen; persistencia individual en censo aparte. | **0.515262 s de pared**, **4,481 bytes pico Python trazado**, 110,000 intentos de **una cabeza**. No mide CPU, RSS total, 110,000 vehículos ni hooks Java. |

**Combinación mínima y condiciones de integración.** M1/M2/M5 deben mantenerse juntos: una admisión con hueco real necesita slot permitido y compromiso coherente. El **0 → 2** de tres solicitudes es evidencia del paquete; no hubo ablaciones que permitan sumar tres ganancias. M14 aporta únicamente trazabilidad de solicitudes/cabeza/flujo/cuerpo/entrada; no introduce un control de tráfico nuevo. M3/M6/M7/M12 se conservan y sus duplicados no se implementan. M4/M8/M11/M13 requieren evidencia adicional; M9/M10 permanecen variantes alternativas y no se mezclan con la comparación focal.

Antes de integrar la variante física: conservar la reproducción original y sus negativos equivalentes; probar **ancla ≤ alcance de ruta por ocurrencia/setback**, salidas interiores y geometrías fuera del foco; mantener los caminos originales de tránsito, terminales, orígenes cortos y pasajes hasta demostrar su cobertura. Comparar estados/eventos además de entradas; proteger flujo, prioridad/señal, última parada y despeje. Medir CPU por hilo, tiempo de pared y memoria/asignaciones de baseline y variante con igual trabajo y calentamiento, reportando también intentos/entradas; no comparar solo la duración total de dos ejecuciones que procesan distinta cantidad de tráfico. Medir M14 activado/desactivado con equivalencia de movimiento. Solo después corresponderían regresiones afectadas → Validate vigente → DryRun del experimento, secuenciales, con revisión congelada. **No hay Run110K autorizada ni ejecutada en esta fase.**

La evidencia reutilizada incluye 8 casos baseline, 10 V2, 19 suites y dos QSim pequeños ya aprobados en Fase 2; no se repitieron ni se renuevan recibos. Se preservan HUD, cifras de camiones y limitaciones visuales aceptadas; no se implementa visualización complementaria ni se realiza prueba de navegador. La verificación documental comprueba diez campos por cada uno de los 14 mecanismos, referencias existentes, hashes y conservación del historial. [Estado final Fase 3](../runtime/diagnostics/run110k-admission-phase3-20261106/final-status.json).

Seguimiento de solo lectura desde PowerShell externa:

```powershell
Get-Content -LiteralPath '.\runtime\diagnostics\run110k-admission-phase3-20261106\final-status.json' -Encoding UTF8
Get-Content -LiteralPath '.\runtime\diagnostics\run110k-admission-phase3-20261106\decision-matrix.json' -Encoding UTF8
```

<!-- RUN110K_ADMISSION_PHASE3_HISTORICAL_END -->

<!-- RUN110K_ADMISSION_PHASE2_HISTORICAL_START -->
# Histórico: Fase 2 evaluada; candidato nativo de incorporación probado y todavía aislado

2026-11-06, cierre posterior a las fixtures de las 21:04 Guatemala. **Los 14 mecanismos se evaluaron; la combinación priorizada es hueco corporal verificable + selección de slot compatible + compromiso de reserva (M1/M2/M5), usando flujo y recepción nativos.** No se modificó Java productivo ni se habilitaron políticas nuevas. Se ejecutaron componentes nativos y dos QSim pequeños de prueba, **ninguna Run110K ni otra masiva, Validate o DryRun**. La evaluación no acredita recuperación de la red completa.

Corrida histórica explícita: Run ID `simz1-d42056291fa2422699a8b6613f795eeb`, LaunchId `748fa7117cdb485ba566a60f289b2994`, iteración 0, horizonte 86,400 s, `completed/valid`, screening `review_required`. Manifiesto y estado del lanzamiento conservan sus hashes originales. La Fase 1 y sus conciliaciones quedan debajo como historia; las solicitudes, incorporaciones, llegadas y censuras siguen siendo estados distintos.

**Resultado focal:** con las dos motos ya reservadas aguas abajo en 12 Avenida, el productor incorpora **0 de 3 solicitudes**. El candidato V2 incorpora **2 en slots diferentes** y mantiene la tercera esperando porque su cuerpo solaparía el ancla ocupada. No cambia el frente de inserción: **125.243190 m del corredor**, en el buffer nativo, ni la separación de 0.10 m. La distancia al final del slot por sí sola no concede admisión. Se prueban además reserva aguas arriba, cuerpo completo, ancho nominal, dirección, giro, ruta, flujo agotado, locks de pasaje, mutación de estado y FIFO. [Comparación baseline](../runtime/diagnostics/run110k-admission-phase2-20261106/candidate-v2/native-baseline.json), [candidato](../runtime/diagnostics/run110k-admission-phase2-20261106/candidate-v2/native-candidate.json), [evaluación final V2](../runtime/diagnostics/run110k-admission-phase2-20261106/candidate-v2/assessment.json).

**Revisión efectiva y preservación.** La huella inicial verificada era `5b9db3d2325b5ff5d5c27fc90bf29e82f14c1349fa2b45d741633973e972d6ac`. La final es **`c1c99b3d5ba93ce35c53936d9064db1e6f3fcb5c9b0cc7083dd4a33cb1557045`**. Las **750 dependencias iniciales permanecen idénticas**; se añadió solamente [SimZ1OriginMechanismsCheck.java](../src/test/java/org/matsim/core/mobsim/qsim/qnetsimengine/SimZ1OriginMechanismsCheck.java) a la huella existente, SHA `58fcde7b28115507072e7c2cf65035ce996f9826a18c517023a8a22b86f37376`. No se excluyeron dependencias ni se editaron recibos. [Recuperación](../runtime/diagnostics/run110k-admission-phase2-20261106/recovery.json), [preservación comprobada](../runtime/diagnostics/run110k-admission-phase2-20261106/preservation-verification.json).

V2 se genera mediante un overlay reproducible bajo `runtime/diagnostics/run110k-admission-phase2-20261106/candidate-v2/` y solo se carga antes de las clases baseline en las JVM de fixtures. Sus hashes son distintos de la huella del workspace: ledger `5db5f32634c0a8e07a622f7cbb75dab79d01d8f45bc6bd62e8b9459299a461c9`; `QueueWithBuffer` `cdb19cbf04ecbedeb4afd69f5077495c635c900bb0c1ef47a2401bdb7b619e93`. Se reutilizó el build aislado de Fase 1 después de verificar que sus fuentes productoras no cambiaron. [Manifiesto de overlay y procedencia](../runtime/diagnostics/run110k-admission-phase2-20261106/candidate-v2/manifest.json).

**Decisión por mecanismo.** La matriz distingue pruebas nativas, reconstrucción histórica y diseños sintéticos; no atribuye a todos el mismo grado de validación. [Matriz completa con evidencia y límites](../runtime/diagnostics/run110k-admission-phase2-20261106/mechanisms-matrix.json).

| Mecanismo | Resultado de evaluación y decisión |
|---|---|
| **1. Hueco físico** | Demostrado en V2 para el buffer ordinario: cuerpo completo en el ancla, separación, acceso y reservas anteriores. Rechaza insertar delante de un propietario o solaparlo. Candidato para integrar; no permiso para toda geometría. |
| **2. Carril seguro** | V2 examina slots de la ruta y el dominio corporal. Un slot bloqueado no impide otro realmente accesible; no reasigna reservas ni infiere independencia de IDs. Complementa M1. |
| **3. Cola separada** | `waitingList` ya separa solicitudes y cuerpos. Duplicarla es redundante. Prototipo de metadatos y observación conserva ID, tiempos, familia, perfil, OD, ruta, orden y candidatos; no concede almacenamiento vial. |
| **4. Equidad por carril** | Round-robin sintético conserva FIFO por fuente y rechaza certificados de recursos compartidos u ofertas obsoletas. Solo tiene sentido con fuentes físicamente independientes demostradas. No se activó bypass de la cabeza global actual. |
| **5. Reserva atómica** | V2 separa oferta pura y recomprobación/compromiso síncrono dentro del escritor serial nativo. Mantiene flujo previo y poll/evento/inserción posteriores. No concede permisos reutilizables ni acredita una transacción multihilo general. |
| **6. Caudal** | Reutilizar créditos y débito PCU existentes. Flujo agotado no produce reserva/entrada. Añadir un cupo arbitrario sería redundante y podría retrasar admisiones legítimas. Solicitud, incorporación y descarga tienen tasas diferentes. |
| **7. Aguas abajo** | Se conservan recepción, reservas y locks; las señales/prioridad se revalidan al cruzar. Exigir toda la ruta vacía contradice la inserción segura detrás de tráfico. Buffer de actividad y almacenamiento viajero tienen contratos distintos. |
| **8. Reintentos** | Diseño shadow con dependencias completas y plazo temporal; estado desconocido obliga a reevaluar. Reserva sola es insuficiente. No se omitió ningún intento nativo; falta equivalencia de trazas y tiempos para habilitar optimización. |
| **9. Fuente exterior** | Alternativa que cambia contrato, innecesaria para el defecto focal ya reproducido. Mover el origen a `_0` altera OD y excede la cadena exterior permitida. Requiere variante explícita, frontera y capacidad declaradas. |
| **10. Anclas/pesos** | 34,585 elecciones reproducidas exactamente. La concentración procede del peso longitud útil × carriles; no de un error de semilla. No hay evidencia para distribuir vehículos entre nuevos ingresos físicos arbitrarios. |
| **11. Dependencias/SCC** | Grafo diagnóstico creado sobre un mismo prefijo de cierre, separando aristas sustentadas/candidatas. No aparecen SCC cíclicas en la parte cubierta; el estado incompleto impide concluir ausencia global de gridlock. |
| **12. Reruteo** | Conservar mecanismo protegido y sus rechazos. Las 40 alternativas no instaladas revisadas fueron rechazadas por almacenamiento nativo; no son permisos actuales. C529 y controles OD/OSM/ocurrencia permanecen. |
| **13. Protección de circulación** | Doce controles sintéticos distinguen hueco, flujo y descarga con cobertura temporal explícita. No se inventó umbral de dosificación. Una política preventiva necesita estado simultáneo, parámetros y pruebas propios. |
| **14. Observabilidad** | Prototipo acotado y trazas de fixture probados. No evaluado ≠ rechazado, intento de cabeza ≠ consulta corporal, entrada ≠ solicitud. Falta conectar hooks/censo nativos y medir su coste real. |

M1/M2/M5 forman una admisión conjunta; M6/M7 aportan controles ya existentes. M3 se conserva y M14 permite explicarla. M4 requiere una política de fuentes independiente demostrada: saltar libremente la cabeza actual contradice FIFO. M8 es una optimización posterior, no una reparación de espacio. M9/M10 no son cambios equivalentes del mecanismo de inserción. M11/M12/M13 investigan descarga; ni un ciclo candidato, ni una espera larga, ni una ruta alternativa histórica autorizan movimiento o liberación.

**Contrato del candidato y defecto encontrado al probarlo.** V1 pasó la comparación focal, pero falló `C529-B-reservations` al cambiar el contrato de `activity()` para llamadores métricos cuyo driver no ofrece `getMode()`; **C529-A sí había pasado**. Se detuvo esa secuencia y se conservaron el fallo y sus logs. V2 mantiene `activity()` original y añade `candidateOriginOffer`/`candidateActivityFromWait`, llamado únicamente desde `QueueWithBuffer.isAcceptingFromWait`. Tránsito, terminales, tramos cortos y pasajes especiales mantienen el camino original. Los cálculos/débitos de flujo, cola de espera, emisión de TrafficEntry y `addFromWait` no cambian. La oferta no concede flujo ni derecho de paso. [Fallo V1 preservado](../runtime/diagnostics/run110k-admission-phase2-20261106/native-regressions.json), [revisión independiente V2](../runtime/diagnostics/run110k-admission-phase2-20261106/circulation-mechanism-review.json).

El control de almacenamiento distingue una cola viajera nativa llena y un buffer de actividad libre: ambos baseline y V2 admiten al buffer bajo el contrato nativo. `usedStorageCapacity` contabiliza `vehQueue`, no ese buffer. No se añadió un veto genérico que exija recepción upstream para toda actividad, ni se aumentó capacidad. El exceso discreto de PCU de la cola sintética pertenece a la semántica nativa conservada. Este límite queda para la revisión de integración; no es una aprobación global de almacenamiento. El ancho de slot empleado es **nominal del modelo**, no una medición GIS. Las pruebas de longitudes 2.1/4.5/8/13.5 m usan drivers sintéticos; no afirman que todas las ramas de servicio de buses reciban la nueva admisión.

**Concentración de fuentes reproducida por identidad.** Se repitió únicamente la selección RNG de los 108,900 privados, sin regenerar demanda, rutas ni horarios. Los 34,585 de 12 Avenida son **24,714 EE + 9,871 EI**. Su peso es `(195.7877478595 − 100) × 2 = 191.575495719` frente a **421.812889659** de las diez anclas exteriores: probabilidad **0.454171743955**, aplicada a 76,230 viajes con origen exterior. Los 22 orígenes internos suman peso 166.794670602. Los pools elegibles de cada clase OD/cuerpo estaban completos y hubo cero rechazos de presupuesto; por eso este cociente describe esta corrida. Los controles negativos de semilla, pesos uniformes y consumo RNG incorrecto difieren en 88,261 / 76,548 / 88,237 IDs. Nueve controles PASS. Las 32 cadenas fuente respetan dirección, carriles y secuencia OSM en la revisión. Llevar 12 Avenida a `_0` produciría una cadena exterior de **257.767089 m**, superior a los 250 m del contrato vigente. Estos pesos son sintéticos; no equivalen a conteos de acceso calibrados. [Auditoría de fuentes](../runtime/diagnostics/run110k-admission-phase2-20261106/sources-assessment.json), [pesos](../runtime/diagnostics/run110k-admission-phase2-20261106/sources-weights.csv).

**Circulación y alternativas: cobertura comprobada.** Se reutilizó el snapshot de 4.6 MB, sin escanear el XML histórico de eventos. El prefijo termina en el evento 121,297,540 a 86,400 s: contiene 6,680 actores/reservas y 789 decisiones WAIT vigentes en el enlace al corte. Se obtuvieron 6,004 dependencias corporales sustentadas y 10,148 aristas candidatas hacia propietarios de receptores; cero SCC cíclicas en ambos grafos cubiertos. No es un snapshot atómico de colas: faltan 5,891 últimas decisiones, partición `vehQueue`/buffer y identidades de recurso/propietario para 34 cabezas con motivos de recepción de pasaje/conector y para seis cruces ejecutados; no se afirman 34 locks adquiridos y el snapshot registra cero pasajes activos. No prueba ausencia de bloqueo circular en toda la red. Ocho controles diagnósticos PASS. [Resumen y cobertura](../runtime/diagnostics/run110k-admission-phase2-20261106/circulation-summary.json), [dependencias](../runtime/diagnostics/run110k-admission-phase2-20261106/circulation-dependencies.json).

De 6,242 privados activos, 1,571 contextos concilian ruta, OD y cursor por ocurrencia; 3,806 carecen de evidencia de ruta y 865 tienen prefijo posterior truncado. En los contextos conciliados aparecen 1,091 alternativas distintas registradas: **1,051 instalaciones históricas**, ya incorporadas al estado, y **40 no instaladas**, todas rechazadas por `active_candidate_receiver_native_storage`. No se generó ni instaló una alternativa nueva ni se acreditó una alternativa actualmente factible. [Contextos de reruteo](../runtime/diagnostics/run110k-admission-phase2-20261106/circulation-reroute-contexts.json). La política de protección de circulación solo observa ventanas cubiertas; cero descarga no implica deadlock y ausencia de datos no implica cero. [Doce controles sintéticos](../runtime/diagnostics/run110k-admission-phase2-20261106/circulation-policy-evaluation.json).

**Solicitudes, equidad, reintento y observación.** Once controles del prototipo Python PASS. La observación exige callbacks autoritativos de identidad/cabeza, conserva estado inmutable de solicitud y cuenta cambios sin guardar cada intento. El benchmark de **110,000 intentos repetidos de una sola cabeza** tardó **0.515262 s**, con **4,481 bytes** de pico Python trazado, un cambio de motivo y cero registros crudos retenidos. No son 110,000 vehículos ni una medición del coste en QSim. `current_nonempty_since` describe el segmento no vacío según orden de llamadas; para la primera cola persistente histórica hacen falta lotes temporales finalizados y el corte final. Las tasas completas de solicitudes/descarga y la persistencia individual de primeros intentos siguen pendientes de integración con el censo; la cuenta de incorporaciones por minuto sí está en el prototipo. [Resultados y límites](../runtime/diagnostics/run110k-admission-phase2-20261106/requests-evaluation.json), [revisión independiente](../runtime/diagnostics/run110k-admission-phase2-20261106/requests-independent-review.json).

El reintento shadow considera revisiones conocidas de reserva, receptor, flujo, señal, elegibilidad, parada bloqueante, ruta, cabeza, prioridad y progreso nativo, junto con el siguiente vencimiento temporal. No cambia la ejecución del motor. Los numerosos WAIT de decisiones nodales y los WAIT deduplicados del ledger de origen son flujos distintos; no se promete eliminar los eventos históricos mediante una caché de origen. El arbitraje sintético solo acota la espera entre oportunidades de servicio de cabezas continuamente elegibles; no garantiza servicio ante imposibilidad física.

**Validación realizada con JDK17 y `.venv`, todas las ejecuciones finales con código 0:**

- Comparación de componentes: **8 casos baseline y 10 del candidato V2**, incluida la preservación de llamadores métricos, ofertas puras, mutaciones, ancho/ruta, doble reserva y pasajes adquiridos nativamente.
- **19 regresiones**: C529-B de reservas; carriles independientes; split interno; atribución; tránsito/pasajes; C529-A, B contrato, C, D fase/ciclo/instalación; rutas temporales OD/OSM, instalación y rojo; parada bloqueante y no bloqueante; despeje corporal y temporizadores. [Índice con clases, argumentos y logs](../runtime/diagnostics/run110k-admission-phase2-20261106/candidate-v2/native-regressions.json).
- **Dos QSim pequeños:** seis actores sintéticos (EE/EI/IE/II, carga y bus, horizonte controlado 800 s) con seis llegadas, rutas, última parada y reservas despejadas; **cero desajustes de almacenamiento nativo** bajo `--require-native-storage`. Un bus L18, horizonte controlado 3,600 s, completa su duty nativo, parada cercana y liberación corporal. [Log de seis actores](../runtime/diagnostics/run110k-admission-phase2-20261106/candidate-v2/six-actor-qsim.log), [log L18](../runtime/diagnostics/run110k-admission-phase2-20261106/candidate-v2/l18-one-bus-qsim.log). Las advertencias históricas de ampliación automática presentes en otros harness no son cambios del candidato; no se extrapola el control estricto de seis actores a toda fixture antigua.
- Diagnósticos/prototipos: nueve controles de fuentes, ocho de dependencias/contextos, doce de protección de circulación y once de solicitudes/equidad/reintento/observación. Son alcances distintos; no sustituyen una prueba de integración completa o escala.

No se ejecutaron Validate/DryRun: no hay un parche productivo integrado que esos pasos puedan aprobar. La huella del workspace y los dos hashes de overlay identifican la prueba; ningún recibo previo se renovó o modificó. [Estado final e inventario de evidencia](../runtime/diagnostics/run110k-admission-phase2-20261106/final-status.json).

**Visor y procesos preservados.** Los cambios anteriores de HUD y sus conciliaciones de carga permanecen idénticos; no se añadieron mensajes sobre los tres casos visuales aceptados. La visualización complementaria no se implementó en esta fase y no se repitió la prueba de navegador. Al cierre no hay proceso Java de SimZ1/fixtures activo; el Java del servidor de lenguaje del IDE es ajeno y no se intervino. Se conservaron los servidores 8792 (wrapper 48088, Python 7552), 8793 (wrapper 25456, Python 31560) y sus workers. PID, creación, padre y comando se registran como observación, no como permiso para intervenir. [Procesos iniciales](../runtime/diagnostics/run110k-admission-phase2-20261106/processes-before.json), [finales](../runtime/diagnostics/run110k-admission-phase2-20261106/processes-final.json).

**Siguiente acción:** revisar e integrar únicamente el candidato acotado M1/M2/M5 y la observabilidad necesaria, manteniendo sus fallbacks y los controles nativos. Una fase de integración deberá cerrar la cobertura de geometrías/servicios de origen y los hooks de observación, repetir controles afectados y pasar Validate vigente → DryRun del experimento secuencialmente con revisión congelada. No habilitar M4/M8 ni una nueva política M9/M10/M13 sin su evidencia específica. **Run110K sigue fuera de esta tarea; cualquier masiva futura la inicia manualmente el usuario.**

Seguimiento de solo lectura desde PowerShell externa:

```powershell
Get-Content -LiteralPath '.\runtime\diagnostics\run110k-admission-phase2-20261106\final-status.json' -Encoding UTF8
Get-Content -LiteralPath '.\runtime\diagnostics\run110k-admission-phase2-20261106\candidate-v2\native-regressions.json' -Encoding UTF8
Get-Content -LiteralPath '.\runtime\diagnostics\run110k-admission-phase2-20261106\candidate-v2\l18-one-bus-qsim.log' -Tail 5
```

<!-- RUN110K_ADMISSION_PHASE2_HISTORICAL_END -->

<!-- RUN110K_ADMISSION_PHASE1_HISTORICAL_START -->
# Histórico: Fase 1 terminada; bloqueo conservador de incorporación reproducido, mecanismos evaluados

2026-11-06 20:41 Guatemala. **Alcance confirmado por el usuario: completar Fase 1 y evaluar mecanismos; no implementar todavía la reparación productiva ni ejecutar Run110K.** Corrida histórica explícita: Run ID `simz1-d42056291fa2422699a8b6613f795eeb`, LaunchId `748fa7117cdb485ba566a60f289b2994`, iteración 0, horizonte 86,400 s. Conserva `completed/valid` y screening `review_required`. No se ejecutaron Controller/QSim, Run, Validate ni DryRun. La fixture usa métodos nativos de componentes, con estados controlados, sin reproducir toda la jornada.

**Hallazgo demostrado:** la incorporación actual exige vaciar un slot completo, aunque las reservas que contiene estén suficientemente aguas abajo del punto real de inserción. En 12 Avenida se reprodujo ese rechazo con `QLinkLanesImpl.moveWaitToRoad`, `QueueWithBuffer` y el ledger productor actuales. Las dos motos retenidas **no ocupan el intervalo corporal de inserción**. Esto demuestra una restricción excesiva de representación; no demuestra que todos los intentos históricos fueran admisibles ni resuelve la congestión aguas abajo.

Recuperación: `git status`, diff previo, encabezado vigente, manifiesto, estado del lanzamiento, final del log y procesos contrastados. La huella inicial sí era `e9eb663ddb9c55457bec9726a3b8774f50eceedfbba21987fd1ebde96d393628`. La huella final es **`5b9db3d2325b5ff5d5c27fc90bf29e82f14c1349fa2b45d741633973e972d6ac`**, por la nueva fixture incluida en el fingerprint existente. Java productivo, scripts, Python/JS del visor e insumos permanecen idénticos al inicio de esta tarea. Los cambios previos y la carpeta no rastreada de gráficas se conservan. [Recuperación e inventario](../runtime/diagnostics/run110k-admission-phase1-20261106/recovery.json), [estado y comprobaciones finales](../runtime/diagnostics/run110k-admission-phase1-20261106/final-status.json).

**Demanda conciliada por identidad.** Se comprobaron 108,900 IDs privados y 1,100 IDs de carga, únicos y disjuntos. Para los privados, `PersonDepartureEvent` ocurrió después del horario planificado con atraso entre 0.0000016 y 0.9999985 s: las solicitudes sí se hicieron a tiempo dentro del paso nativo. La carga conserva sus 1,100 solicitudes observadas, verificadas aquí como agregado, y sus 1,100 registros individuales de resultado.

| Familia | Programados / solicitudes | Incorporados | Llegados | Activos al corte | Sin incorporación | Censurados |
|---|---:|---:|---:|---:|---:|---:|
| Carros | 48,400 | 8,164 | 5,432 | 2,732 | 40,236 | 42,968 |
| Motos | 60,500 | 10,428 | 6,918 | 3,510 | 50,072 | 53,582 |
| Camiones | 1,100 | 613 | 368 | 245 | 487 | 732 |
| No públicos | 110,000 | 19,205 | 12,718 | 6,487 | 90,795 | 97,282 |

Los 90,308 pendientes del diagnóstico original son **privados**; con carga son 90,795 no públicos. Los 269 buses físicos y 15,336 expediciones siguen separados: 1,993 expediciones iniciadas, 1,928 incorporadas, 1,735 completadas, 193 activas, 65 esperando incorporación y 13,343 sin iniciar. No se suman expediciones a vehículos físicos.

Procedencia efectiva comprobada: configuración y manifiesto seleccionan `inputs/transit-weekday`. Para los 32 corredores se compararon 102 enlaces y 133 nodos; carriles, geometría, capacidades y atributos originales coinciden con la base. En 33 enlaces se añade el modo bus a car, diferencia conservada y compatible con esta comparación de cuerpos privados. Se verificaron seis hashes de entradas y el catálogo congelado contra el manifiesto. [Comparación semántica y diferencias de serialización documentadas](../runtime/diagnostics/run110k-admission-phase1-20261106/evidence-input-provenance.json).

La secuencia comprobada es horario → solicitud `PersonDeparture` → espera FIFO → intento como cabeza → consulta corporal cuando hay flujo → incorporación `VehicleEntersTraffic` → transiciones `LinkEnter` → llegada, o estado activo/pendiente censurado en el corte previo al cleanup. **El primer intento individual no está disponible en los extractos para los 108,900 privados.** No se sustituye por Departure ni por el primer WAIT de otro vehículo. El informe conserva totales y últimos movimientos nativos por familia, sin convertir actividad de reloj, WAIT o limpieza final en circulación. [Conciliación, cobertura y fuentes con hashes](../runtime/diagnostics/run110k-admission-phase1-20261106/evidence-reconciliation.json).

**Auditoría de los 32 orígenes.** Tienen **41 slots y 46 propietarios únicos**; los 41 slots están ocupados y conservan una cota de progreso en la referencia correcta de corredor. Se contrastó el extremo de cada cola original con `min(frente_modelado − longitud − 0.10)`, limitado por su capacidad. En los 32 orígenes aparece un intervalo longitudinal candidato para los cuerpos privados del catálogo congelado (2.1 y 4.5 m): longitud mínima de cola original 4.840580 m y separación mínima entre buffer y retaguardia protegida 8.262315 m. Esto no acredita compatibilidad de ruta/slot de la cabeza real, presupuesto PCU, recepción, señal, prioridad ni locks. No se infieren permisos de la suma de metros ni se proyectan los propietarios del cierre a horas anteriores. [41 filas por origen/slot](../runtime/diagnostics/run110k-admission-phase1-20261106/evidence-origin-slots.csv).

**Punto real de 12 Avenida.** Origen `osm_762765906_1_forward`, corredor `osm_762765906_0_forward`. Mantiene 34,585 viajes programados, 1,566 incorporados, 1,216 llegados, 350 activos y 33,019 pendientes; última incorporación 37,222 s = 10:20:22.

| Magnitud | Metros / referencia |
|---|---:|
| Inicio del enlace de origen | 29.455442 del corredor |
| Longitud del enlace | 195.787748 |
| Tramo terminal de carriles | últimos 100.000000 del enlace |
| Buffer de la cola original, punto de `addFromWait` | 95.787748 del enlace = **125.243190 del corredor** |
| Frente mínimo modelado de cada moto retenida | 244.458284 del corredor |
| Longitud de cada moto / separación | 2.100000 / 0.100000 |
| Retaguardia protegida: frente menos cuerpo y separación | **242.258284 del corredor** |
| Distancia desde el buffer hasta esa retaguardia | **117.015094** |

Los propietarios son `z1_03084`, slot 0, y `z1_36824`, slot 1, en los terminales de `osm_762765906_2_forward`. Una tercera moto con frente en 125.243190 ocupa el intervalo corporal [123.143190, 125.243190]; incluso añadiendo la separación por detrás permanece dentro del origen. Por tanto, **cabe detrás de las motos en la geometría longitudinal del modelo**. El valor 244.458284 de capacidad por slot, por sí solo, no habría demostrado esto. Las cotas del ledger declaran `positionsObserved=false`: no son posiciones GPS, cartografía GIS verificada ni autorización para dibujar cuerpos individuales. [Evidencia focal y procedencia](../runtime/diagnostics/run110k-admission-phase1-20261106/evidence-12avenida.json).

**Cadena productora reproducida.** `moveWaitToRoad` examina solo la cabeza global del origen y se detiene ante un rechazo. `isAcceptingFromWait` comprueba primero flujo nativo; si falta, puede no existir un intento corporal ni un evento WAIT. `choose()` exige slot vacío para una reserva nueva cuando el origen está en el interior del corredor; comprueba además rutas, slot, locks, capacidad y clearance. `activity()` añade otra exigencia de slot vacío, incluso desde offset cero. En el focal se alcanza primero el rechazo `receiver_storage_or_terminal_slot`, no necesariamente `activity_requires_empty_model_slot`.

Una aprobación de actividad reserva sincrónicamente antes de retirar la cabeza y emitir TrafficEntry; esto también protege buses que pasan directamente a su cola de parada. `addFromWait` inserta al buffer y conserva la reserva sin duplicar su huella. **`isAcceptingFromWait`/`activity` no son consultas puras reutilizables para explorar candidatos.** `receiverFeasibility` sí es una consulta, y la fixture comprueba que no altera reservas, dominios, pendientes, locks, temporizadores ni eventos. La recepción real, señales y prioridad se revalidan al cruzar; los conectores y pasajes requieren su recepción completa, permisos y despeje. Transferir dentro del corredor conserva slot/ordinal; liberar o llegar requiere el evento y despeje correspondientes, sin timeout ficticio. [Revisión del código con referencias](../runtime/diagnostics/run110k-admission-phase1-20261106/mechanism-review.json).

**Fixture Java y controles.** [SimZ1OriginAdmissionFixture.java](../src/test/java/org/matsim/core/mobsim/qsim/qnetsimengine/SimZ1OriginAdmissionFixture.java) carga red, carriles y señales congelados; solo crea las colas nativas focales. Sembrar propietarios en sus terminales es una fixture declarada, no la reproducción de sus trayectorias históricas. Ocho casos PASS, código **0**:

1. Dos propietarios aguas abajo: cuerpo cabe en el buffer, pero el código actual rechaza.
2. Offset cero: recepción ordinaria posible, actividad todavía exige slot vacío.
3. Slot compatible libre: incorporación real al buffer; reasignación del slot ya reservado rechazada.
4. Reserva aguas arriba y FIFO por carril: no se permite insertar por delante.
5. Cabeza global rechazada: no se examina ni incorpora al seguidor aunque este sea receivable por separado.
6. Flujo agotado: no se reserva ni fabrica un rechazo corporal tras el cortocircuito nativo.
7. Ambos puntos de buffer ocupados: tercer cuerpo solapado rechazado.
8. Recepción bloqueada y rojo rechazan; verde con recepción admite. La prioridad se comprueba por llamadas separadas a `StopAndYield.passageMayProceed`; no se presenta como arbitraje integrado de prioridad en ese cruce de control.

[Resultado final](../runtime/diagnostics/run110k-admission-phase1-20261106/native-fixture-final.json), [log final](../runtime/diagnostics/run110k-admission-phase1-20261106/native-fixture-final.log). JDK17, un build aislado y una recompilación de la fixture tras ampliar/revisar sus controles; se conserva la ejecución inicial de siete casos. Revisión independiente: reloj monotónico, snapshot profundo y alcance de prioridad corregidos antes de la ejecución final. SHA de la fixture revisada: `bab6b09a523943716fd2431028d73d4b3a98ad131c678664661ddcfc34359a3c`.

Cinco suites complementarias PASS, código **0**: `SimZ1IndependentLaneDischargeCheck`, `SimZ1InternalSplitBackpressureCheck`, `SimZ1AdmissionAttributionCheck`, `SimZ1TransitPassageNativeCheck` y `SimZ1TransitPassageReleaseCheck`. Cubren deuda de flujo/FIFO, contrapresión terminal, consultas cortocircuitadas, movimiento nativo, llegada de tránsito y liberación por despeje corporal. [Índice y logs](../runtime/diagnostics/run110k-admission-phase1-20261106/native-regressions.json). No equivalen a Validate ni a una prueba masiva; no se renovó la batería completa C529/OD/OSM/L18, que no sufrió cambios productivos. Antes de una reparación productiva deben conservarse esas regresiones, las de última parada y llegada corporal.

**Mecanismos evaluados para la siguiente fase; ninguno activado.**

| Mecanismo | Evaluación y condiciones |
|---|---|
| Intervalo corporal en el buffer real | Candidato principal: admitir detrás de reservas aguas abajo comprobando cuerpo completo, separación, ancla y orden. Requiere transacción coherente con `nativeEntry`/`progress`, elección de slot y ramas de tránsito. Un recién incorporado bloquea otra inserción en la misma ancla hasta despejarla. No consiste en eliminar ambos `if`. |
| Aprovechamiento de slots compatibles | Conservar y probar `moveIndependentOriginalSlot`, que ya existe. Seleccionar solo carriles compatibles y físicamente demostrados, mantener FIFO por slot, deuda nativa y reservas. Saltar libremente la cabeza de espera o reasignar lateralmente no está justificado. |
| Recorrido físico desde una entrada explícita | Alternativa con cambio de contrato: recorrer el origen en cola nativa, en vez de comenzar en su buffer. Cambia punto y tiempo de incorporación; necesita alcance de variante, eventos y servicios de origen explícitos. No se recomienda introducirlo silenciosamente como parche equivalente. |
| Observabilidad de solicitudes e intentos | Registrar primera consulta como cabeza, primer intento corporal, cambios de motivo e incorporación; conservar null para seguidores nunca examinados. Permite separar flujo, FIFO y cuerpo sin interpretar WAIT como segundos o vehículos. No aumenta por sí sola la circulación ni recupera tiempos históricos ausentes. |

La combinación a desarrollar primero es **intervalo anclado + slots compatibles/FIFO + observabilidad**, manteniendo la recepción, prioridad y señales existentes. La investigación de descarga aguas abajo debe partir de movimientos concretos que fallen sus controles, no atribuir toda la retención al origen. Los mecanismos propuestos todavía no tienen implementación ni medición de mejora a escala.

**Visor preservado.** Conserva los 1,100 camiones configurados, 613 incorporados, 368 llegados, 245 activos, 487 pendientes y 732 censurados, así como reintentos y rótulo Dibujados. No se reabrió la investigación ni se añadieron avisos de los tres casos visuales históricos aceptados. La capa complementaria de conteos nativos por enlace/corredor queda para su fase: debe mostrar tiempo/cobertura e identidad sin inventar posiciones. No se hizo una nueva prueba visual de navegador.

Procesos: se comprobaron PID, creación, padre y comando; no había Java SimZ1 activo. Se conservaron los servidores 8792 (wrapper 48088, Python 7552) y 8793 (wrapper 25456, Python 31560), junto a sus workers. No se iniciaron observadores, servidores ni lanzadores ni se terminaron procesos. Los PID son observaciones de esta entrega, no instrucciones para intervenir. [Procesos iniciales](../runtime/diagnostics/run110k-admission-phase1-20261106/processes-before.json), [procesos finales](../runtime/diagnostics/run110k-admission-phase1-20261106/processes-final.json).

**Siguiente acción:** implementar y probar los mecanismos priorizados en una fase posterior con alcance explícito. Tras cualquier cambio productivo: reproducción y controles negativos → regresiones afectadas → Validate vigente → DryRun del experimento, secuenciales y con fuentes congeladas. Run110K continúa prohibida en esta tarea; cualquier masiva futura la inicia manualmente el usuario. La nueva fixture cambia la huella: los recibos antiguos no autorizan esta revisión y no se editaron.

Seguimiento de solo lectura desde PowerShell externa:

```powershell
Get-Content -LiteralPath '.\runtime\diagnostics\run110k-admission-phase1-20261106\final-status.json' -Encoding UTF8
Get-Content -LiteralPath '.\runtime\diagnostics\run110k-admission-phase1-20261106\native-fixture-final.log' -Tail 10
Get-Content -LiteralPath '.\runtime\diagnostics\run110k-admission-phase1-20261106\native-regressions.json' -Encoding UTF8
```

<!-- RUN110K_ADMISSION_PHASE1_HISTORICAL_END -->

<!-- RUN110K_VIEWER_REPAIR_HISTORICAL_START -->
# Histórico: visor Run110K reparado y HTTP verificado; cobertura corporal insuficiente

2026-11-06 20:10 Guatemala. **Escalamiento suspendido; ninguna nueva simulación autorizada por esta reparación.** Corrida exacta: Run ID `simz1-d42056291fa2422699a8b6613f795eeb`, LaunchId `748fa7117cdb485ba566a60f289b2994`, iteración 0, `completed/valid`, screening `review_required`, política `partial-native-v1`. El estado del launcher y los manifiestos históricos se preservan. No se ejecutó QSim, Validate, DryRun ni otra corrida; tampoco se releyó el XML de 121 millones de eventos.

**Causa demostrada y corrección:** `/api/hud` respondió HTTP 200 con datos correctos, pero `SimZ1ContinuousHud.validate()` exigía `configured.vehicles_configured === observed.vehicles_observed`: `1100 !== 613`. La otra igualdad sí pasaba: 1,100 salidas programadas y 1,100 observadas. [Reproducción previa](../runtime/diagnostics/run110k-viewer-repair-20261106/hud-rejection-before.json), [comparación JS antes/después con Run110K, Run1000 y fixture](../runtime/diagnostics/run110k-viewer-repair-20261106/hud-real-js-checks.json).

`validateFreight()` en [simz1_continuous_hud.js](../python/simz1_continuous_hud.js) y `checked_freight_hud()`/`checked_hud()` en [simz1_continuous_replay.py](../python/simz1_continuous_replay.py) concilian el contrato fixed-day por subconjuntos, IDs únicos, tiempos y censo individual/agrupado. Se conservan las igualdades de servicio completo para contratos históricos. Identidad, iteración, hash de manifiesto y versión de fuente son obligatorios; se rechazan campos ausentes/corruptos, negativos, booleanos usados como números, duplicados y flotas ajenas. TrafficExit y Arrival siguen siendo eventos distintos: se admite salida anterior a llegada, pero no llegada anterior a salida. No se convierten censurados ni abortos administrativos en llegadas.

| Carga Run110K | Conteo nativo |
|---|---:|
| Camiones configurados / salidas programadas / salidas observadas | 1,100 / 1,100 / 1,100 |
| Incorporados | 613 |
| Llegados | 368 |
| Activos al corte | 245 |
| Esperando incorporación | 487 |
| Censurados | 732 |

Conciliación: `368 ≤ 613 ≤ 1100`; `613 = 368 + 245`; `1100 = 368 + 245 + 487`; `732 = 245 + 487`. Screening intacto. Run1000 histórico compatible: 10 configurados, 10 incorporados, 10 llegados; [verificación de metadatos real](../runtime/diagnostics/run110k-viewer-repair-20261106/hud-real-python-checks.json). Esta prueba de presentación no renueva su recibo experimental.

**Interfaz:** `renderRunHud()`, `loadRunHud()` y `renderFrame()` en [visualizador_z1_controls.js](../python/visualizador_z1_controls.js) separan los fallos de totales de la reproducción. Una única promesa comparte las peticiones simultáneas; no se muestran datos de una respuesta obsoleta. El mismo error antes se presentaba en el HUD y se propagaba al registro global, donde sobrevivía al reintento exitoso. Ahora tiene un indicador breve y un único detalle técnico en Ayuda, que se limpia al recuperar la carga; si falla el propio panel, queda un error explícito de presentación.

Se retiraron los textos, tooltips y la alerta amarilla sobre los tres casos históricos aceptados, sin borrar sus registros internos ni suprimir errores nuevos. La única explicación de cobertura, en Ayuda, es: «Vista parcial: algunos vehículos no tienen posición verificable y pueden no aparecer.» Los recuentos y motivos de omisión permanecen en el panel técnico.

**Cobertura visual real:** «Visibles» ahora se rotula **Dibujados**: marcadores con posición representable enviados al mapa tras filtros. Incluye marcadores fuera de cámara y no mide oclusión; no significa activos nativos. Los pictogramas de paradas son referencias estáticas, no buses en movimiento. A las **00:04:03** se reproduce la captura: **53 activos nativos, 1 representable, 52 pendientes**, cobertura 1.89%.

| Hora | Activos nativos | Representables | Omitidos | Reconstrucción pendiente en replay | Sin intervalo replay | Cobertura sobre activos |
|---|---:|---:|---:|---:|---:|---:|
| 00:04 | 52 | 1 | 51 | 51 | 0 | 1.92% |
| 06:30 | 1,194 | 0 | 1,194 | 1,194 | 0 | 0% |
| 07:00 | 2,012 | 0 | 2,012 | 1,948 | 64 | 0% |
| 08:30 | 4,400 | 0 | 4,400 | 3,817 | 583 | 0% |
| 09:15 | 4,955 | 0 | 4,955 | 2,683 | 2,272 | 0% |
| 09:45 | 5,073 | 0 | 5,073 | 1,618 | 3,455 | 0% |
| 10:30 | 5,662 | 0 | 5,662 | 962 | 4,700 | 0% |
| 11:00 | 5,861 | 0 | 5,861 | 878 | 4,983 | 0% |
| 20:05 | 6,655 | 0 | 6,655 | 780 | 5,875 | 0% |
| 23:00 | 6,680 | 0 | 6,680 | 789 | 5,891 | 0% |

Los activos se concilian por ID físico único, con entrada a tráfico `≤ t` y sin salida a tráfico `≤ t`, todas las familias; los pendientes de incorporación quedan fuera. Los representables son un subconjunto comprobado de esos mismos IDs, sin filtros de usuario. «Reconstrucción pendiente» es una supresión conservadora por falta de soporte corporal/cola o dependencia de un intervalo no reconstruido. «Sin intervalo replay» acredita ausencia de un segmento que cubra el instante; no acredita llegada ni ausencia de tráfico y no se le asigna una causa física universal. [CSV](../runtime/diagnostics/run110k-viewer-repair-20261106/coverage-summary.csv), [definiciones y evidencia por instante](../runtime/diagnostics/run110k-viewer-repair-20261106/coverage-summary.json), [conciliación PASS](../runtime/diagnostics/run110k-viewer-repair-20261106/coverage-review.json).

**La cobertura corporal es insuficiente para investigar un atasco.** La visualización adicional propuesta es una capa separada de conteos nativos por enlace/corredor y última transición observada, con hora y cobertura explícitas. No ubicaría cuerpos dentro del enlace ni inventaría colas, velocidades o separaciones. Esta tarea no implementó esa capa ni una reconstrucción causal nueva.

Verificación: **85 pruebas Python** (13 HUD y 72 replay/política parcial/lanzador/integración/navegación), **10 suites JS**, metadatos reales de ambas corridas y 11 evaluaciones del render, todas código **0**. Se cubren excesos de observados/llegadas, identidad/iteración/versiones ajenas, ausencias, corrupción, duplicados, separación TrafficExit/Arrival, ausencia de avisos históricos, recuperación del HUD sin duplicados y reproducción/pausa/selección/rutas. Los fallos previos se reprodujeron y preservaron como evidencia. [Python HUD](../runtime/diagnostics/run110k-viewer-repair-20261106/hud-python-tests.log), [Python regresiones](../runtime/diagnostics/run110k-viewer-repair-20261106/regressions-python.log), [JS regresiones](../runtime/diagnostics/run110k-viewer-repair-20261106/regressions-js.json), [UI](../runtime/diagnostics/run110k-viewer-repair-20261106/ui-replay-after.log).

La evaluación de frames ejecutó el código real con dobles DOM/Deck; **no hubo comprobación visual WebGL en navegador**, porque el host de acceso y el pipe nativo no estuvieron disponibles. [Bloqueo de acceso UI](../runtime/diagnostics/run110k-viewer-repair-20261106/ui-access-blocker.json). Se reutilizaron ocho ventanas y se consultaron sólo dos nuevas por HTTP, ambas 200. La conciliación leyó una vez el CSV derivado de 319,020,580 bytes, SHA verificado, 4.34 s; no eventos nativos. Se procesaron incrementalmente 2.06 GB de JSON derivados en 71.44 s. Durante la cobertura hubo cambios de presentación/HUD; los motores de movimiento, colas, geometría y loader conservaron sus hashes, y dos revisores comprobaron que el diff de controles no cambia el cálculo de frames.

Revisión coordinada: un escritor por archivo; revisión independiente de contrato HUD y de conciliación. Se preservaron los cambios documentales previos y `graficas_tesis_v2/run110k-dfbbe000305a413a92327419528bc9b2/`. Sin cambios Java, física, demanda, rutas, señales, reservas ni manifiestos; sin commits, push, limpieza o detención de servidores.

Huella nativa histórica `d9c47644bb8d3afa18f383aab1c9d0407fd18228361e06629527d38f8e31a96d`; **huella actual `e9eb663ddb9c55457bec9726a3b8774f50eceedfbba21987fd1ebde96d393628`**. Build de cliente separado `154306a1f2dc8890a61dfbeceddb32e9edfdf11c2b78184a61e38496c1808258`. [Inventario del posprocesador](../runtime/diagnostics/run110k-viewer-repair-20261106/postprocessor-build.json). **Antes de una futura corrida real deberán renovarse Validate y DryRun para la revisión vigente y aplicarse las guardas del ensayo correspondiente. No reutilizar los recibos anteriores ni editarlos para aprobar.**

Servidor nuevo **listo**, puerto 8793, wrapper PID 25456 y Python PID 31560, creados el 2026-11-06 a las 20:03:33 Guatemala; padre de Python 25456. Comando explícito `scripts/replay/start_replay.py --run-dir ...run-bg110-748fa7117cdb485ba566a60f289b2994 --iteration 0 --replay-dir .../webgl-continuo-it.0 --visual-policy partial-native-v1 --port 8793 --no-browser`. Se comprobó comando/fecha/parentesco e identidad HTTP. El inventario de sockets produjo también filas transitorias PID 0, conservadas como observación, sin usarlas para intervenir procesos. El servidor anterior 8792/PID7552 no se detuvo. [Procesos](../runtime/diagnostics/run110k-viewer-repair-20261106/processes-final.json), [sockets observados](../runtime/diagnostics/run110k-viewer-repair-20261106/listeners-final.json). La preparación espacial se revalidó por cambio de huella con el mecanismo existente: arranque 197.63 s; no eventos nativos ni bypass.

**HTTP final PASS, código 0:** configuración, HUD y HTML 200; 16 solicitudes negativas 400, incluidos identidad/iteración/hash/versión/política ausentes, duplicados y valores ajenos. El HUD sigue idéntico al JSON previo y el HTML es exactamente el ensamblado de las fuentes corregidas. [19 comprobaciones](../runtime/diagnostics/run110k-viewer-repair-20261106/http-checks.json). Una ventana pequeña (índice 2, 1,268 segmentos) se comprobó además en el servidor nuevo: 200, hash de transporte válido y campos de evidencia iguales. Se repitió su lectura desde caché para explicar la diferencia binaria: exclusivamente tiempos de consulta y contadores de caché/SQL, sin cambios de segmentos, posiciones ni estados. [Comparación final de ventana](../runtime/diagnostics/run110k-viewer-repair-20261106/http-window-final.json).

**Abrir la nueva URL y pulsar Ctrl+F5:** [Run110K corregido](http://127.0.0.1:8793/index.html?run_id=simz1-d42056291fa2422699a8b6613f795eeb&iteration=0&run_manifest_sha256=07a6fb1349533ce4d6cd8198e5e05c195f3c09d1f97b9aec191bb89ac7fad89a&source_version=4266373e0812451c6580c9f01f9e12713355767b585603645fcb3a984fa425ea&visual_policy=partial-native-v1). Comprobar Run ID/iteración, «Camiones: 1100» y rótulo «Dibujados»; en Ayuda aparecen los 613 incorporados, 368 llegadas, 245 activos y 487 esperando. La pestaña antigua en 8792 no es la URL de esta entrega. **Siguiente acción:** revisión del usuario en navegador; cualquier futura visualización adicional de atascos deberá mostrar conteos por enlace con cobertura explícita. No iniciar QSim para resolver presentación. [Estado final y evidencia](../runtime/diagnostics/run110k-viewer-repair-20261106/final-status.json).

Seguimiento de solo lectura desde PowerShell externa:

```powershell
Get-Content -LiteralPath '.\runtime\diagnostics\run110k-viewer-repair-20261106\viewer-server.log' -Tail 10 -Encoding UTF8
Get-Content -LiteralPath '.\runtime\diagnostics\run110k-viewer-repair-20261106\viewer-server-error.log' -Tail 10 -Encoding UTF8
Get-NetTCPConnection -State Listen -LocalPort 8793 -ErrorAction SilentlyContinue
```

<!-- RUN110K_VIEWER_REPAIR_HISTORICAL_END -->

<!-- RUN110K_ROOT_CAUSE_HISTORICAL_START -->
# Histórico: investigación de incorporación Run110K, anterior a la reparación del visor

2026-11-06 19:49 Guatemala. **No se autoriza ni recomienda iniciar otra escala mientras se investiga.** Esta instrucción sustituye las recomendaciones históricas de Run10K/55K. Run110K conserva `completed/valid`, screening `review_required`, LaunchId `748fa7117cdb485ba566a60f289b2994`, Run ID `simz1-d42056291fa2422699a8b6613f795eeb`, iteración 0 y horizonte 86400 s. No se ejecutó QSim, Run1000, Validate ni DryRun; no se modificó producción, escenarios ni resultados históricos.

**Hallazgo principal:** los 90,308 privados sin incorporación se concentran en 32 orígenes. Al corte nativo, los 32 conservan al menos una reserva en cada carril modelado: 46 propietarios distintos bastan para impedir nuevas inserciones con la regla actual de actividad, que exige un carril sin reservas. Esto explica una condición suficiente del bloqueo de incorporación **al cierre**, no la primera causa de cada cadena ni todos los rechazos anteriores. Muchos corredores tienen metros libres: «no hay carril vacío para insertar» y «almacenamiento completamente lleno» no son equivalentes.

El acceso de **12 Avenida** concentra 33,019 pendientes. Se acreditó una cadena adicional hacia 22 Calle, 12 Avenida A, 20 Calle y 11 Avenida; los tres focos L12 previos no explican por sí solos toda la red. No se demostró todavía un movimiento físicamente admisible impedido por error. Clasificación actual: **C local respecto de las restricciones comprobadas; diseño de incorporación B como cuestión a revisar; causa global indeterminada**. No hay parche productivo ni fixture de defecto justificados todavía.

Evidencias nuevas, separadas de `closure/`: [censo y alcance](../runtime/diagnostics/run110k-root-cause-20261106/admission-summary.json), [ranking completo](../runtime/diagnostics/run110k-root-cause-20261106/admission-access-ranking.csv), [reservas por origen](../runtime/diagnostics/run110k-root-cause-20261106/admission-dependencies-summary.json), [revisión de datos de ocho horas](../runtime/diagnostics/run110k-root-cause-20261106/viewer-times-data-review.json), [conciliación independiente PASS](../runtime/diagnostics/run110k-root-cause-20261106/review-checks.json). La narrativa vigente es este encabezado; no se creó otro documento de avance.

## 1. Qué le ocurre a un agente, desde su creación hasta el cierre

«Crear 110,000 agentes» no significa poner 110,000 vehículos simultáneamente en las calles. Primero se preparan los registros y planes: 108,900 conductores privados y 1,100 de carga. Se cargan en Java antes de la simulación. Al preparar QSim, MATSim crea los agentes de esos planes y sus vehículos; empiezan esperando el fin de su actividad inicial. Los 269 buses físicos pertenecen a otro servicio: atienden 15,336 expediciones programadas y no son otros 15,336 vehículos.

El generador reparte exactamente 48,400 carros y 60,500 motos privados. La familia se subdivide en normal, liebre y tortuga mediante cuotas y barajado reproducible. Cada privado recibe un viaje. Los cuatro OD se asignan por cuotas enteras y un barajado con semilla: II=10,890, IE=21,780, EI=21,780, EE=54,450. Son porcentajes sintéticos 10/20/20/50, no aforos de Guatemala.

La hora de salida se sortea una vez por persona usando semilla 20261023, ID y tipo. Los perfiles privados permiten el día 0..86400; las densidades horarias versionadas son `[1,0.7,0.5,0.5,0.8,2,6,9,8,5,4,5,6,5,4,4,6,9,8,4,3,2,1.5,1]`. El sorteo pondera duración del intervalo por densidad y elige un instante dentro de la hora. En esta variante se preserva ese resultado: la clase OD no cambia la hora y una saturación no la aplaza artificialmente. En los 108,900 registros, la salida nativa ocurre entre 0 y 1 segundo después del instante fraccionario planificado.

El origen se elige entre anclas exteriores revisadas o sitios internos explícitos, con peso `longitud útil × carriles`; el destino entre opciones conectadas, con peso `longitud × carriles`. Se comprueba que el cuerpo cabe en el punto correspondiente. La ruta es dirigida, respeta carriles y secuencias OSM; utiliza tiempo de recorrido libre como coste y la reparación temporal autorizada cuando un pasaje resulta imposible. El presupuesto PCU/h limita la carga **programada**, con hasta 1024 intentos de par OD manteniendo persona, clase y hora. Si no encuentra par, la preparación falla. No garantiza que la red descargue a esa tasa cuando ya hay colas. Run110K registra cero rechazos de pares por presupuesto en su auditoría de preparación.

Cuando llega la hora, QSim termina la actividad y emite `PersonDepartureEvent` **antes** de llamar al manejador de salida. Es «quiero salir»: el vehículo puede quedar en la lista de espera de su enlace. En `moveWaitToRoad`, solo se examina la cabeza de esa lista. Se requiere capacidad de flujo y aprobación corporal. Si falla, se deja en la lista y se termina ese intento; los seguidores no se examinan. Si pasa, se saca de la lista, se emite `VehicleEntersTrafficEvent` y se inserta en la cola nativa. Ese segundo evento acredita incorporación física al modelo. Se emite con posición relativa 1.0 para el enlace de origen: el punto de inserción y su interpretación como actividad/ancla forman parte del modelo, no una posición GPS observada.

Dentro de la red, el vehículo avanza por enlaces y carriles con FIFO, recepción, prioridades, señales, paradas y reservas. El reruteo privado puede cambiar el sufijo admisible, conservando identidad OD, prefijo por ocurrencia, cursor y reservas; no convierte una consulta favorable en un movimiento. Los servicios de buses/carga conservan sus contratos propios. Llegar exige alcanzar el destino nativo y satisfacer el despeje corporal; `QueueWithBuffer` comprueba `arrivalHeldByBody` antes de `letVehicleArrive`. La terminación de la etapa emite `PersonArrivalEvent` y libera la reserva correspondiente. Los abortos administrativos de las 24 h no son llegadas. Los pendientes permanecen censurados.

Fuentes verificadas: [generación OD](../python/generate_montecarlo_z1.py), funciones `gateway_population/people` alrededor de 357–490; [muestreo de horas](../python/simz1_agent_types.py), `sample_departures` 180–210; [asignación de clases](../python/simz1_od_policy.py), `allocate` 58–72; [selección/rutas/presupuesto](../python/simz1_balanced_od.py), 259–437; [carga Java](../src/main/java/gt/edu/uvg/sim/zona1/SimZ1.java), 64–95; [incorporación](../src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/QLinkLanesImpl.java), 433–460; [puerta de inserción y llegada](../src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/QueueWithBuffer.java), 292–327; [reservas](../src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/SimZ1CorridorOccupancy.java), 460–486 y 630–640. Se consultó el **sources.jar local de MATSim 15.0**, sin sustituirlo por otra versión: [creación de agentes](../runtime/diagnostics/run110k-root-cause-20261106/demand-agent-source.json) y [orden de Departure/Arrival](../runtime/diagnostics/run110k-root-cause-20261106/demand-native-lifecycle-source.json).

## 2. Conciliación de programación, solicitud, incorporación y llegada

| Familia | Programados y solicitaron salida | Incorporados | Llegaron | Incorporados sin llegada | Sin incorporación |
|---|---:|---:|---:|---:|---:|
| Carros | 48,400 | 8,164 | 5,432 | 2,732 | 40,236 |
| Motos | 60,500 | 10,428 | 6,918 | 3,510 | 50,072 |
| **Privados** | **108,900** | **18,592** | **12,350** | **6,242** | **90,308** |
| Carga, separada | 1,100 | 613 | 368 | 245 | 487 |

Privados: `108900 = 12350 + 6242 + 90308`; `18592 = 12350 + 6242`. No quedan privados sin una salida programada vencida ni sin `PersonDepartureEvent` al cierre. La completitud privada es 12,350/108,900 = 11.34%; la incorporación es 18,592/108,900 = 17.07%. No se usa Departure como sustituto de TrafficEntry.

Público: 15,336 expediciones programadas, 1,993 iniciadas, 1,928 incorporadas, 1,735 completadas, 193 activas, 65 esperando incorporación y 13,343 sin iniciar. Los 269 buses físicos se incorporaron alguna vez. Estos conteos conservan las unidades y el censo anterior al cleanup.

El [censo privado individual comprimido](../runtime/diagnostics/run110k-root-cause-20261106/admission-private-census.csv.gz) contiene 108,900 IDs únicos. Incluye familia, perfil, clase OD, origen, acceso, hora programada, solicitud observada, incorporación, llegada y espera medible. El [desglose conjunto](../runtime/diagnostics/run110k-root-cause-20261106/admission-full-breakdown.csv) cruza familia × perfil × OD × hora × origen; los [grupos marginales](../runtime/diagnostics/run110k-root-cause-20261106/admission-groups.csv) y [horas por acceso](../runtime/diagnostics/run110k-root-cause-20261106/admission-access-hourly.csv) permiten verificar las sumas sin releer eventos.

| Familia/perfil | Sin incorporación |
|---|---:|
| Carro normal | 26,841 |
| Carro liebre | 6,697 |
| Carro tortuga | 6,698 |
| Moto normal | 25,046 |
| Moto liebre | 12,500 |
| Moto tortuga | 12,526 |

## 3. Los 90,308 pendientes: accesos, tiempos y mecanismo

66,664 parten de las diez anclas exteriores y 23,644 de los 22 orígenes internos. No se debe llamar «espera antes de entrar a Zona 1» a los 23,644 internos: esperan incorporarse a tráfico en un origen que ya está dentro del área. La espera observada al cierre se calcula como `86400 − PersonDeparture`, y va de 2 a 66,697 s. Es edad de solicitud pendiente; no es tiempo de cabeza FIFO, duración de un motivo ni suma de WAIT.

**Primera solicitud versus primer intento:** se conoce el instante de solicitud de cada privado mediante Departure. Los extractos conservados no retienen la primera llamada a `isAcceptingFromWait` ni el motivo individual de todos los pendientes. Los snapshots anteriores seleccionaron actores activos/reservados, no la lista de espera completa. Además, la rama que falla por capacidad de flujo y los seguidores todavía no consultados no producen necesariamente un rechazo corporal individual. Por eso los campos `first_insertion_attempt` e `individual_rejection_reason` quedan vacíos con explicación explícita; no se rellenan con Departure ni con motivos de otros vehículos.

El siguiente ranking usa conteos reales. **Inicio cola persistente** significa el último paso de cero a un saldo positivo `Departure − TrafficEntry` que nunca vuelve a cero hasta el cierre, agrupando eventos del mismo segundo. No es el instante de un defecto. **Primera solicitud final pendiente** es el Departure más antiguo entre quienes nunca se incorporaron; **última incorporación** no significa última transición ni llegada.

| Origen / acceso | Tipo | Pendientes | Inicio cola persistente | Primera solicitud final pendiente | Última incorporación |
|---|---|---:|---|---|---|
| 12 Avenida: `osm_762765906_1_forward` | Exterior | 33,019 | 00:00:29 | 05:28:23 | 10:20:22 |
| Avenida Elena: `osm_381667651_0_forward` | Exterior | 7,512 | 06:00:34 | 06:40:30 | 09:13:02 |
| Avenida Elena: `osm_381667651_3_forward` | Exterior | 6,320 | 06:03:40 | 07:15:21 | 09:20:48 |
| 10a Avenida: `osm_511820719_6_forward` | Exterior | 5,531 | 06:00:15 | 07:23:04 | 09:33:34 |
| Avenida Elena: `osm_381667651_19_forward` | Exterior | 5,163 | 07:11:04 | 08:28:43 | 09:52:15 |
| 15 Calle: `osm_406843605_1_forward` | Exterior | 4,403 | 06:00:09 | 08:02:18 | 10:51:30 |
| Sin nombre en insumo: `osm_1095760124_0_backward` | Interno | 2,046 | 07:00:46 | 07:04:44 | 07:15:40 |
| Sin nombre en insumo: `osm_1095527693_1_backward` | Interno | 1,590 | 08:05:42 | 08:24:11 | 10:48:10 |
| Sin nombre en insumo: `osm_989735832_1_forward` | Interno | 1,540 | 07:51:40 | 08:20:08 | 11:11:20 |
| 24 Calle: `osm_400043601_5_forward` | Exterior | 1,453 | 07:44:04 | 07:44:04 | 07:43:09 |
| Sin nombre en insumo: `osm_1272882110_0_forward` | Interno | 1,379 | 07:18:10 | 07:34:31 | 08:48:50 |
| Sin nombre en insumo: `osm_390176418_0_forward` | Interno | 1,356 | 10:27:40 | 10:27:40 | 10:26:07 |
| Sin nombre en insumo: `osm_406701907_9_backward` | Interno | 1,269 | 07:25:28 | 08:06:41 | 11:10:00 |
| 1a Avenida: `osm_44486997_0_backward` | Exterior | 1,252 | 12:03:00 | 12:03:00 | 12:02:46 |
| 9a Calle: `osm_260936848_14_forward` | Exterior | 1,240 | 07:23:59 | 07:23:59 | 07:23:43 |
| Sin nombre en insumo: `osm_1392432467_0_backward` | Interno | 1,236 | 07:42:26 | 07:42:42 | 07:42:50 |
| Sin nombre en insumo: `osm_1095527695_0_backward` | Interno | 1,228 | 07:32:15 | 07:45:38 | 09:04:50 |
| Sin nombre en insumo: `osm_1218656796_0_forward` | Interno | 1,123 | 07:04:28 | 07:56:38 | 08:50:21 |
| Sin nombre en insumo: `osm_1274275468_9_backward` | Interno | 1,067 | 07:21:09 | 07:33:35 | 10:12:25 |
| Sin nombre en insumo: `osm_1095760094_0_backward` | Interno | 1,050 | 07:39:31 | 08:24:08 | 11:43:34 |
| Sin nombre en insumo: `osm_1095760001_3_backward` | Interno | 1,039 | 07:42:47 | 08:10:55 | 11:27:00 |
| Sin nombre en insumo: `osm_1392432602_0_backward` | Interno | 954 | 07:51:35 | 07:51:35 | 07:51:13 |
| Sin nombre en insumo: `osm_1095551808_2_backward` | Interno | 944 | 08:01:44 | 09:05:19 | 11:53:10 |
| Sin nombre en insumo: `osm_488464043_0_backward` | Interno | 942 | 10:47:02 | 10:47:02 | 10:44:37 |
| Sin nombre en insumo: `osm_1095551811_2_backward` | Interno | 924 | 09:28:06 | 09:32:27 | 11:45:41 |
| Sin nombre en insumo: `osm_1196002697_9_backward` | Interno | 854 | 07:02:23 | 09:23:21 | 10:13:31 |
| Sin nombre en insumo: `osm_1197017583_1_forward` | Interno | 816 | 08:02:34 | 08:34:07 | 10:33:02 |
| Sin nombre en insumo: `osm_1159529860_0_backward` | Interno | 786 | 07:45:50 | 08:09:55 | 11:06:35 |
| 23 Calle: `osm_406872394_4_backward` | Exterior | 771 | 08:21:45 | 08:30:20 | 08:32:46 |
| Sin nombre en insumo: `osm_1107835856_7_forward` | Interno | 634 | 10:55:34 | 10:55:34 | 10:55:16 |
| Sin nombre en insumo: `osm_1174627092_0_backward` | Interno | 619 | 10:31:21 | 10:31:21 | 10:29:27 |
| Sin nombre en insumo: `osm_1214455884_0_backward` | Interno | 248 | 18:15:13 | 18:15:13 | 18:14:56 |

Las seis primeras entradas concentran 61,948 pendientes. 12 Avenida recibió 34,585 viajes programados, incorporó 1,566, completó 1,216 y conserva 350 activos más 33,019 sin incorporación. Su saldo de espera ya no se vació desde 00:00:29: **había una limitación de incorporación anterior al deterioro de circulación de 06:30**. Esa cola aún descargaba durante horas; no se interpreta como inmovilidad desde medianoche. El más antiguo de sus pendientes finales solicitó salir a las 05:28:23, y la última incorporación fue 10:20:22.

La reconstrucción del corte contiene 46 propietarios distribuidos en los 32 dominios de origen, con todos sus slots ocupados. Para una actividad nueva, `choose()` prohíbe insertarse por delante de reservas previas cuando el origen está en una subdivisión interior del corredor; `activity()` exige también que el slot seleccionado esté vacío. Si el origen necesita atravesarse como conector de un pasaje, la ocupación de ese dominio tampoco permite eludir la restricción. Son condiciones del código productor, no permisos deducidos de metros nominales libres. En el corte constituyen una obstrucción suficiente para todas las listas pendientes; **no identifican qué rama exacta se ejecutó en cada intento**.

En 12 Avenida el origen está a 29.4554 m del comienzo del corredor `osm_762765906_0_forward`. El ledger ofrece 244.4583 m por slot y conserva dos motos de huella 2.2 m, una por slot. No está lleno por suma de longitudes: está cerrado a nuevas actividades por la regla de inserción y porque esas motos no pueden abandonar su corredor. Avenida Elena y los sitios internos presentan el mismo patrón de ausencia de slot vacío, con cantidades y cuerpos diferentes. [Propietarios, reservas y capacidades por origen](../runtime/diagnostics/run110k-root-cause-20261106/admission-dependencies-summary.json); [evolución en snapshots existentes](../runtime/diagnostics/run110k-root-cause-20261106/admission-origin-slot-history.json).

No se demostró que las rutas planificadas de los pendientes sean desconectadas, que falte un permiso estático ejecutable ni que su hora no haya llegado. Tampoco se demostró que todos los rechazos fueran por almacenamiento lleno: las reglas de inserción, la capacidad de flujo y la recepción aguas abajo son mecanismos distintos. Los presupuestos sintéticos PCU/h de preparación no modelan la necesidad de que se vacíe un slot completo y no garantizan esa capacidad efectiva de incorporación.

## 4. Los 6,242 incorporados sin llegada

Los 2,732 carros y 3,510 motos están identificados individualmente en [activos privados](../runtime/diagnostics/run110k-root-cause-20261106/admission-active-private.csv), con enlace/corredor final, reserva, slot, último LinkEnter, edad en tráfico y último motivo retenido. Se conciliaron ID, entrada y enlace final contra `state-day-cut.json.gz`; no se usaron los ceros posteriores a la limpieza.

Todos llevaban al menos 20,704 s en tráfico al cierre y al menos 20,701 s desde su último LinkEnter o entrada inicial: más de 5 h 45 min. Esto no excluye movimiento dentro del enlace. Entre los últimos motivos retenidos hay 423 `storage_wait`, 169 `receiver_storage_or_terminal_slot`, 56 `signal_red`, 18 `passage_receipt_storage_or_slot`, 1 `passage_connector_occupied` y 2 `admission_conflict_executed`. Para 5,573 actores no se conserva una decisión individual desde su último cambio de enlace: muchos son seguidores y ese vacío **no equivale a ausencia de congestión**. Los motivos tienen su timestamp, no se presentan como diagnósticos simultáneos de todos los actores. [Ranking de enlaces finales](../runtime/diagnostics/run110k-root-cause-20261106/admission-active-links.csv).

La prueba histórica de cohortes sigue siendo válida: los 6,655 episodios de todas las familias activos a las 20:05 siguen activos al DayCut sin otro LinkEnter. Los 25 nuevos camiones explican las 182 transiciones posteriores; ninguno llegó. Los 6,242 privados pertenecen a esa cohorte retenida. No hubo recuperación privada nocturna.

## 5. Los cuatro OD y la permanencia dentro de Zona 1

| OD privado | Comportamiento planificado | Programados | Incorporados | Llegadas | Sin incorporación | Activos |
|---|---|---:|---:|---:|---:|---:|
| INTERNAL_INTERNAL | Origen y destino internos; sin cruce exterior | 10,890 | 3,004 | 1,817 | 7,886 | 1,187 |
| EXTERNAL_INTERNAL | Ancla exterior → cruce de entrada → destino interno | 21,780 | 2,704 | 1,834 | 19,076 | 870 |
| INTERNAL_EXTERNAL | Origen interno → cruce de salida → ancla exterior | 21,780 | 6,022 | 3,717 | 15,758 | 2,305 |
| EXTERNAL_EXTERNAL_THROUGH | Entrada real → recorrido interno → salida distinta | 54,450 | 6,862 | 4,982 | 47,588 | 1,880 |

Se comprobaron los 108,900 metadatos publicados y 18,105 rutas distintas con la red, carriles, secuencias y perímetro congelados: cero errores de conectividad/secuencia comprobada o de orden de cruces. Las cadenas de los diez accesos y doce salidas distinguen ancla exterior, enlace que cruza el polígono y observación interior. `BalancedGatewayModel._gateways` rechaza anclas interiores, cadenas que entran/salen incorrectamente y anclas demasiado alejadas; las rutas EE deben atravesar interior y usar accesos distintos. Esta comprobación adicional es de **rutas planificadas**, no una nueva auditoría exhaustiva de cada sufijo realmente reruteado. La validación nativa histórica mantiene cero transiciones físicas inválidas y cero eventos de ruta actual inválida.

El perímetro es el archivo versionado con procedencia OSM `osm-9283360-v34`; su SHA y la red/carriles efectivos se verificaron por el contrato del visor. No se afirma cartografía GIS de campo verificada. El catálogo original conserva un texto histórico `BLOCKED` para restricciones que debían revisarse; no se borra. La revisión **efectiva** de esta corrida es `accepted_for_preparation`: 17478998 se aplica por contrato compartido de secuencias y 17884471 conserva `MALFORMED_SOURCE_NO_EXECUTABLE_MANEUVER`, sin inventar permiso irrestricto. Esa discrepancia documental no demuestra un rechazo dinámico de los 90,308.

**Departure→Arrival no mide permanencia dentro de Zona 1.** Incluye espera de incorporación y tramos de anclas exteriores. TrafficEntry→TrafficExit elimina la primera espera, pero conserva tramos exteriores. En un origen interno, el reloj de circulación dentro del área empieza con la incorporación; su espera anterior se informa aparte. En un origen exterior, TrafficEntry todavía no acredita haber cruzado el perímetro. El nombre `System_Entry` de metadatos del replay se refiere a entrada al tráfico del modelo, no necesariamente al polígono.

Indicador adicional propuesto, sin sustituir las métricas originales: **permanencia en tráfico dentro del perímetro por episodios observados**. Reconstruir la secuencia real de enlaces por ocurrencia. Mantener estado fuera/dentro/desconocido y contabilizar cada intervalo interior; ante varios cruces, sumar todos los intervalos interiores disjuntos, excluyendo las excursiones exteriores, no restar simplemente última salida menos primera entrada. Para II: incorporación interna hasta llegada interna, descontando cualquier salida observada. Para EI: entrada perimetral hasta llegada interna. Para IE: incorporación interna hasta salida perimetral. Para EE: cada entrada hasta su salida correspondiente. Guardar número y orden de cruces, regla de punto de referencia del vehículo y cobertura.

El cruce geométrico suele estar **dentro de un enlace**. Los eventos LinkEnter/LinkLeave no dan por sí solos el segundo exacto en que el cuerpo lo cruza. Deben producirse límites temporales `[entrada al enlace de cruce, salida del enlace de cruce]`, y una duración interior mínima/máxima coherente; el punto exacto queda no observado. Las cotas nativas del frente/cola pueden estrechar el intervalo cuando sean suficientes, sin convertirlas en trayectoria continua. Debe declararse si el indicador usa cruce del punto de referencia o despeje del cuerpo completo. Sin un cruce final o llegada acreditados, el episodio queda pendiente/censurado; no se cierra artificialmente a 86400 como viaje completado. Se puede informar permanencia observada hasta el corte como cota, con censura explícita. Nunca interpolar una posición para hacerla pasar por observación del perímetro.

## 6. Dónde se observa el deterioro y qué cadenas se pueden explicar

La cronología agregada reutilizada distingue descenso 06:30–08:00, recuperación parcial 08:00–09:00 y caída fuerte desde 09:15, persistente desde 09:45. Las esperas de incorporación pueden crecer durante una recuperación de transiciones: son series diferentes. Una tasa positiva de movimientos no significa que se vacíen los accesos.

Los focos anteriores conservan su evidencia, con **las letras de la clasificación nueva del usuario**. Los antiguos JSON denominaban `A_local` a un rechazo físicamente consistente y `B` a un defecto; esas etiquetas históricas no se reutilizan como si significaran lo mismo ahora.

| Foco | Hecho comprobado | Clasificación actual y límite |
|---|---|---|
| 21 Calle / L12_010, 06:29:59 | Receptor con cuatro slots: quedan 4.46/4.46/6.46/4.26 m frente a huella de bus 13.6 m; reservas anteriores a la decisión. El bus sí avanzó después; a 09:00 era otra expedición. | C local, rechazo explicado. No es prueba del inicio del bloqueo global. |
| 22 Calle / nodo 410441329, 07:59:59 | `z1_59680` encuentra reserva de `z1_44606` todavía sin despeje y rojo. Cumplir el tiempo mínimo no obliga a liberar el cuerpo. | C local. Se mantiene la cautela del orden de eventos del mismo segundo. |
| Avenida Bolívar / L12_039, desde 06:40:43 | Último LinkEnter 06:40:41. Su pasaje necesita recepción posterior; propietarios de conectores cambian entre mañana y 11 h y luego persisten. | C en los contextos con propietarios comprobados; primera causa y raíz aguas abajo indeterminadas. No proyectar propietarios de 11 h a 06:40. |
| 32 orígenes al corte | Todos los slots modelados contienen reservas; 46 propietarios impiden insertar los 90,308 pendientes según la regla actual. | C respecto del bloqueo bajo esa regla. B: revisar si la representación de inserción y sus presupuestos son adecuados; no hay defecto A demostrado. |
| 12 Avenida → 22 Calle → 12 Avenida A | Se identifican cabezas persistentes, receptores y acumulación posterior; detalle abajo. | Propagación observada. La primera causa aguas abajo sigue indeterminada; `passage_receipt_native_queue` no significa receptor inmediato lleno. |

Nueva cadena acotada, a partir de snapshots ya existentes, sin reextraer los contextos L12:

1. `z1_71937`, en `osm_64401505_1_forward` (12 Avenida A), conserva su primera espera por `receiver_storage_or_terminal_slot` desde t33673 = **09:21:13**, hacia `_2_forward`.
2. En `osm_42840290_0_forward` (22 Calle), las cabezas `z1_79297` y `z1_27221` conservan esperas hacia `osm_64401505_0_forward` desde **09:23:52 y 09:24:17**, después de su parada obligatoria. Los 17 propietarios del corredor receptor suman 54.2 m frente a 60.8903 m; esa suma sola no demuestra admisibilidad, pues importa el hueco de recepción corporal y la cola nativa.
3. En el cruce `osm_363667895_6_forward`, `z1_00268` y `z1_67492` esperan recepción en 22 Calle desde **09:38:25 y 09:38:50**. A 09:45/11 h/cierre, el corredor de 22 Calle conserva 39 propietarios, ocupaciones 58.6/58.4 m por slot frente a 61.8711 m. Las reservas y decisiones originales quedan en el extracto.
4. Las motos `z1_03084` y `z1_36824` entran al tráfico del ancla de 12 Avenida a **10:20:02 y 10:20:22** y su último LinkEnter ocurre a 10:20:15/10:20:35. Primero registran `storage_passage_lock`; desde **10:20:42** conservan el motivo corporal `passage_receipt_native_queue`, con recepción nativa inmediata favorable pero reserva del pasaje denegada. El pequeño conector `osm_1342389560_0_forward` está sin reservas al corte: no se lo declara lleno. La comprobación alcanza la recepción posterior.
5. Ambas motos permanecen en el corredor de origen y mantienen no vacíos sus dos slots. Esa retención impide que el ancla admita más solicitudes, aunque en el corredor queden metros libres. La cola pendiente de ese origen llega a 33,019.

Se siguió además una cadena potencial de diez saltos desde `z1_71937`: `_64401505_2` → 20 Calle → 11 Avenida → 16 Calle. Incluye rojos y estados de recepción; **no se convierte en prueba de ciclo cerrado**. Un dominio puede contener al propio solicitante; esa arista no demuestra dependencia circular. No se encontró un par de cabezas recíprocas con WAIT exactamente a 86400 en la comprobación acotada. Eso no descarta ciclos más largos ni ciclos de prioridad/pasajes. Faltan partición nativa vehQueue/buffer, compatibilidad completa por slot, estados de prioridad anticipada y oportunidad de verde/recepción simultánea para acreditar que existió descarga admisible. No se deduce defecto de un largo tiempo de espera.

[Cadena de 12 Avenida y fuentes temporales](../runtime/diagnostics/run110k-root-cause-20261106/causal-12avenida-existing-snapshots.json), [dependencias potenciales acotadas](../runtime/diagnostics/run110k-root-cause-20261106/causal-12avenida-downstream-candidates.json), [búsqueda de pares recíprocos](../runtime/diagnostics/run110k-root-cause-20261106/causal-reciprocal-head-candidates.json). Las primeras esperas conservadas son primeras **desde el último LinkEnter de ese actor**, no el primer rechazo de toda la calle. No se acredita que estos focos expliquen todos los corredores.

Entre 20:02 y 21:02 hay 60 minutos completos sin transiciones; la cohorte de 20:05 nunca volvió a cambiar de enlace. De 21:02 a 24:00 solo entran los 25 camiones nuevos ya comprobados. No hay llegadas desde 20:01:01 y la última transición global es a 22:11:55. Cero LinkEnter no excluye desplazamiento interno del enlace.

## 7. Visor parcial: identidad, ocho horas y límites

Se validaron la identidad explícita, la iteración 0, la huella de manifiesto, el contrato `balanced-gateway-v1` por el mecanismo existente, el horizonte 0..86400, `sample_rate=1` y la política `partial-native-v1`. El export contiene 19,474 vehículos físicos que alguna vez entraron: 18,592 privados + 613 camiones + 269 buses; eso no es el total programado. La política declara `body_position_available=false` para soporte pendiente y no reconstruye el grafo causal de los contextos. No se dibujaron posiciones nuevas ni se modificó el export.

El servidor previo desapareció durante la investigación; se comprobó que no quedaba listener ni proceso de ese lanzador antes de abrir uno nuevo de solo lectura. Se inició únicamente el servidor de replay existente, sin navegador automático ni QSim, con registro [viewer-server.log](../runtime/diagnostics/run110k-root-cause-20261106/viewer-server.log). [Comprobación de ocho respuestas HTTP](../runtime/diagnostics/run110k-root-cause-20261106/viewer-window-checks.json) PASS. En la comprobación final ya no se observó listener en 8792; se conserva el éxito de las consultas realizadas, sin afirmar que el servidor siga disponible. No se solicitó terminarlo y no se atribuye una causa a su desaparición. **Inspección visual/UI pendiente:** ambas vías de control fallaron por servicio nativo/browser host no disponible. La tabla siguiente es inspección de los datos que sirve el visor, no afirmación de haber visto el mapa o probado sus controles.

Cada fila usa el censo privado hasta el segundo indicado; las transiciones nativas son el intervalo previo `(t−60,t]` de todas las familias. Los intervalos representados corresponden a vehículos con un segmento que cubre ese instante; no garantizan pose corporal visible. Las calles son ejemplos de registros presentes y salidas de enlace en el minuto siguiente, no rankings exhaustivos de congestión real.

| Hora | Privados esperando | Privados activos | Activos todas las familias | Con intervalo representado | Transiciones minuto previo | Acumulaciones presentes / calles con descarga registrada después |
|---|---:|---:|---:|---:|---:|---|
| 06:30 | 2,414 | 1,073 | 1,194 | 1,194 | 3,810 | 6a Avenida/9a Calle/21 Calle; descargan 10a Avenida y 14 Calle |
| 07:00 | 3,872 | 1,866 | 2,012 | 1,948 | 2,786 | 4a Avenida/10a Avenida/9a Calle; descargan 8a y 2a Avenida; L12_039 sigue retenido |
| 08:30 | 14,278 | 4,227 | 4,400 | 3,817 | 5,054 | 9a Calle/14 Calle/4a Avenida; descargan 4a Avenida y 14 Calle durante la recuperación parcial |
| 09:15 | 17,821 | 4,776 | 4,955 | 2,683 | 2,127 | 14 Calle/6a Avenida/4a Avenida; aún descargan 14 Calle y 4a Avenida |
| 09:45 | 19,969 | 4,844 | 5,073 | 1,618 | 1,177 | 6a Avenida/19 Calle/21 Calle; descargas en 21 y 17 Calle; cadena 12 Avenida–22 Calle ya retenida |
| 10:30 | 22,812 | 5,375 | 5,662 | 962 | 359 | 9a Calle/10a Avenida; descargas residuales en 12 y 15 Calle; ancla de 12 Avenida ya cerrada |
| 11:00 | 24,877 | 5,546 | 5,861 | 878 | 72 | 9a Calle/10a Avenida; descargas residuales en 3a Calle y 13 Avenida; L12_039 persiste |
| 20:05 | 82,054 | 6,242 | 6,655 | 780 | 0 | Registros detenidos en 9a/12 Calle y 7a Avenida; ninguna descarga registrada; faltan miles de intervalos abiertos |

A las 20:05 hay 6,655 activos nativos y solo 780 vehículos con intervalo representado: no confundir el mapa escaso con una red vacía. Las 82,054 solicitudes privadas todavía sin incorporación a esa hora tampoco se ven automáticamente. El metadato global declara 5,891 intervalos abiertos sin representación al abortar, además de soporte corporal pendiente. Las curvas cinemáticas del export son interpolación visual, no aceleraciones/posiciones medidas; no se usaron para inferir una autorización física, un cruce exacto ni un tiempo interior. Los datos locales no muestran por sí solos vehículos aún fuera del tráfico, el orden completo de la lista de espera, capacidad nativa por buffer, propietarios causales de todas las retenciones ni alternativas de prioridad.

## 8. Decisión causal y propuesta mínima

**A — defecto de implementación demostrado:** ninguno todavía. La prueba necesaria es un movimiento admitido por todas las condiciones físicas y de prioridad que el productor impidió, o una liberación obligatoria omitida. No se preparó una fixture con estados inventados ni se aplicó un parche. `completed/valid` acredita integridad y propiedades auditadas, no vivacidad universal.

**B — diseño/configuración:** se demuestran supuestos con impacto: demanda exterior ponderada por metros útiles (34,585 solicitudes en un único acceso), presupuestos horarios que no predicen inserción y exigencia de vaciar un slot para nuevas actividades. Su adecuación empírica sigue sin acreditarse. La propuesta es una variante explícita de **representación de fuentes e inserción**, conservando N, IDs, composición, semilla, OD, horas, horizonte, cuerpos, flotas, señales, capacidades y reservas. Primero verificar el punto físico de inserción y si puede existir un hueco detrás del último cuerpo con FIFO/recepción íntegros; si la representación nativa no lo admite, revisar de forma documentada ancla y almacenamiento de fuente con evidencia, sin añadir espacio ficticio. No mover anclas ni repartir más accesos sin autorización de esa variante. Revisar el peso `metros útiles × carriles` contra aforos futuros, no reemplazarlo ahora por una distribución que produzca más llegadas. Una capacidad PCU nominal no basta para calibrar la capacidad de una fuente sometida a vaciado de slot.

**C — congestión consistente con el modelo:** los rechazos locales de espacio/cuerpo/rojo ya acreditados y la obstrucción de incorporación en los 32 orígenes al corte. **Indeterminado:** causa global inicial, necesidad de todos los rechazos intermedios y ciclos mayores. La coexistencia de C local y B por revisar es válida: ejecutar correctamente una regla no verifica que represente bien la calle real.

Siguiente paso mínimo de investigación: fixture nativa **exploratoria** del acceso de 12 Avenida y su recepción de pasaje, con el código productor, cuerpo/slots/cola y rutas documentados. Primero reproducir los rechazos conocidos y los controles admisibles independientes; solo si surge una contradicción pasa a fixture de defecto A. Debe retener negativos de rojo, seguidor FIFO, reserva ajena, recepción nativa ocupada y cola corporal sin despejar. La evidencia actual no permite presentar de antemano un «debe pasar» del estado histórico completo. Esta entrega deja la causa y la propuesta revisables; no modifica producción.

## 9. Qué permite el posproceso y qué necesita una nueva corrida

Sin QSim ya se resolvieron censo por origen, familia/perfil/OD/hora, separación solicitud/incorporación, edad observada de espera, identificación de 6,242 activos, reservas de origen, cadena nueva acotada y comprobación HTTP de ocho horas. Con los productos existentes se puede añadir la métrica perimetral **acotada**, la separación de espera/recorrido exterior/interior y mejorar rótulos del visor. La interfaz visual pendiente requiere acceso al navegador, no repetir la simulación.

No se propone otra lectura de los 121,569,942 eventos: no hace falta para estos hallazgos. Recuperar motivos de cabezas pendientes ausentes podría requerir leer los eventos de reservas originales, pero **no recuperaría intentos no emitidos ni negativas individuales de seguidores**. Cualquier lectura adicional debe especificar antes el campo/ID/intervalo, límite de cobertura, 4,328,390,890 bytes comprimidos / 82,325,724,655 descomprimidos del archivo completo y coste medido de lectura; no se autoriza una repetición ciega. Primero comprobar si el dato realmente fue emitido.

Cambiar el movimiento, el lugar/regla de incorporación o cualquier escenario físico exige una nueva corrida con revisión distinta y resultados nuevos. Medir con precisión un instante físico que nunca se observó exige instrumentación nativa explícita para una corrida futura; no puede crearse retrospectivamente con interpolación. El ensayo exploratorio no acredita una masiva ni reemplaza la aceptación.

## 10. Secuencia si se propone cambiar producción — no ejecutada

1. Congelar y revisar causa, evidencia y alcance. Reproducir con fixture nativa sobre el productor y controles negativos; presentar antes de aplicar un parche.
2. Si se demuestra A y se aprueba la corrección, cambio mínimo con la misma fixture pasando y los negativos todavía rechazados. Conservar C529-A/B/C/D, OD/OSM, pasajes temporales, L18, recepción/FIFO/reservas, llegada corporal y última parada de buses. Verificar fixtures dependientes de archivos nuevos y negativos de mutación/ausencia de hashes.
3. Revisión integrada, un solo escritor, JDK17 y `.venv`; ejecutar `check_simz1_110k_balanced_gateway.ps1 -Action Validate` cuando esa fase corresponda a la nueva tarea. Capturar inmediatamente `$LASTEXITCODE`; detener el flujo si no es 0. No actualizar recibos a mano.
4. Preparar **DryRun del ensayo pequeño explícito** con spec/scenario versionados, porque el lanzador lo exige antes de cualquier Run. El Run del ensayo necesita autorización nueva: la solicitud actual prohíbe Run1000/10K/55K/110K. Una fixture focal no es ese ensayo.
5. Tras el ensayo autorizado, auditar nativamente incorporación, OD/perímetro, flujo, cuerpos y censura. Solo después preparar DryRun del experimento futuro con la nueva huella. Validate y DryRun serán secuenciales, sin cambios concurrentes. No encadenar ningún Run masivo; lo inicia manualmente el usuario cuando corresponda.
6. Si se confirma B, preservar el escenario original y especificar una variante con parámetros/procedencia y objetivo de contraste antes de la misma secuencia. No tocar screening, demanda ni capacidades para conseguir PASS.

## Evidencia, pruebas y continuidad

La revisión aritmética PASS tiene once comprobaciones de conciliación/identidad; no es una fixture nativa. `admission_audit.py` leyó una vez el CSV publicado de 319,020,580 bytes, verificó su SHA contra el informe original y tardó 33.55 s. No releyó los planes de 693 MB ni el archivo nativo de eventos. Se redujeron snapshots ya preservados. El visor reutilizó SQLite y cache espacial verificadas; ocho ventanas de 120 s produjeron 1,969,800,374 bytes JSON en total y 131.75 s de consulta/lectura, conservadas comprimidas. Su reducción posterior leyó incrementalmente solo el prefijo `segments`, sin nueva consulta de eventos ni reconstrucción causal L12. Se informa este coste para no repetir esas lecturas.

La huella productora y actual comprobada por el mecanismo existente es `d9c47644bb8d3afa18f383aab1c9d0407fd18228361e06629527d38f8e31a96d`; manifiesto original SHA `07a6fb1349533ce4d6cd8198e5e05c195f3c09d1f97b9aec191bb89ac7fad89a`. Los scripts de diagnóstico quedan fuera de producción por su ubicación habitual en runtime y se versionan por SHA por separado; no se cambió el inventario del fingerprint. Se preservó la modificación documental previa y `graficas_tesis_v2/run110k-dfbbe000305a413a92327419528bc9b2/` no rastreado. Los subagentes iniciales fallaron por límite de uso antes de entregar trabajo; no se presenta una revisión humana o de subagente inexistente. No hay commit, push, limpieza histórica ni promoción de Run110K.

Estado y seguimiento de solo lectura, desde la raíz:

```powershell
Get-Content -LiteralPath '.\runtime\diagnostics\run110k-root-cause-20261106\investigation-status.json' -Raw -Encoding UTF8
Get-Content -LiteralPath '.\runtime\diagnostics\run110k-root-cause-20261106\admission-access-ranking.csv' -Encoding UTF8
Get-Content -LiteralPath '.\runtime\diagnostics\run110k-root-cause-20261106\viewer-server.log' -Tail 10 -Encoding UTF8
Get-Content -LiteralPath '.\runtime\launches\748fa7117cdb485ba566a60f289b2994\state.json' -Raw -Encoding UTF8
```

**Siguiente acción:** revisar la representación de incorporación y preparar el caso nativo focal acotado si se continúa esa fase; resolver acceso visual al visor. El escalamiento queda suspendido. La causa global no está cerrada y no hay autorización para otra corrida.
<!-- RUN110K_ROOT_CAUSE_HISTORICAL_END -->

---

<!-- RUN110K_CLOSURE_ACTIVE_START -->
# Histórico: cierre Run110K anterior a la investigación de incorporación (recomendaciones de escala suspendidas)

2026-11-06, cierre diagnóstico **17:33 Guatemala**. La QSim original terminó naturalmente. Identidad: LaunchId `748fa7117cdb485ba566a60f289b2994`, Run ID `simz1-d42056291fa2422699a8b6613f795eeb`, iteración 0, horizonte 86400 s. Fuentes de cierre: [estado del lanzador](../runtime/launches/748fa7117cdb485ba566a60f289b2994/state.json), [evidencia de cierre preservada](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/closure-evidence.json), [resultado final del diagnóstico](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/final-status.json). La QSim cerró el log a las 11:53:41 Guatemala; el lanzador terminó a las 15:47:26, después de auditorías y análisis. El proceso hijo del ejecutor terminó naturalmente con código 0; el lanzador devolvió 3 por screening **review_required**. No se promueve la corrida.

Procesos originales JVM23428/padre4000 y launcher2664 ausentes; el Java del IDE es ajeno. [Inventario observado](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/processes-observed.json). Manifiesto SHA `07a6fb1349533ce4d6cd8198e5e05c195f3c09d1f97b9aec191bb89ac7fad89a`, huella actual y productora `d9c47644bb8d3afa18f383aab1c9d0407fd18228361e06629527d38f8e31a96d` (comprobación de lectura exit0).

El censo previo a limpieza conserva **6680 activos**. No sustituirlo por los ceros de vehículos/reservas posteriores al cleanup. [Tabla reproducible](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/metrics_family.csv):

| Familia y unidad | Programados | Incorporados | Completados | Esperando incorporación | Activos al corte | Iniciados censurados | Sin iniciar |
|---|---:|---:|---:|---:|---:|---:|---:|
| Carros privados: vehículos/viajes únicos | 48400 | 8164 | 5432 | 40236 | 2732 | 42968 | 0 |
| Motos privadas: vehículos/viajes únicos | 60500 | 10428 | 6918 | 50072 | 3510 | 53582 | 0 |
| Carga: vehículos/viajes únicos | 1100 | 613 | 368 | 487 | 245 | 732 | 0 |
| Transporte público: expediciones | 15336 | 1928 | 1735 | 65 | 193 | 258 | 13343 |

Pendientes de completar: carros42968, motos53582, carga732 y expediciones públicas13601. En público,13601 =258 iniciadas censuradas +13343 sin iniciar; **no** se renombran13601 como censurados nativos. Las1993 expediciones iniciadas no equivalen a1928 incorporaciones. Los269 buses físicos se incorporaron y completaron alguna expedición durante el día;193 seguían en tráfico al corte. Los76 restantes no se declaran estacionados sin evidencia. No hay abortos anteriores al horizonte; los abortos administrativos finales no fabrican llegadas.

La auditoría conserva cero transiciones físicas inválidas, cero salidas ilegales de seguidores en4775 intervalos de parada bloqueante y cero violaciones del ledger corporal; cero movimientos forzados/remociones por atasco. Esto verifica las propiedades observadas, **no prueba que todas las denegaciones fueran necesarias**. Carga conserva **220 incumplimientos de ventanas de residencia**; integridad nativa válida no significa cumplimiento de horarios. `physical_stability.proven=false`, posiciones continuas/laterales no observadas y `empirical_calibration=false`; no trasladar este escenario sintético a la ciudad real como calibración.

El screening permanece `review_required`: completitud privada12350/108900 por debajo del objetivo declarado0.9,6242 privados activos con más de3600s en tráfico al corte y completitud global inferior al objetivo. Se conserva el umbral versionado; el objetivo de screening no es un criterio empírico o legal.

### Gráficas y cronología reutilizada

Todas las figuras son **diagnósticas**, incluyen Run ID/iteración0, fuentes, cobertura24h y `review_required`; PNG y SVG están en la misma carpeta. No son una entrega oficial aceptada. [Métricas/procedencia](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/metrics_summary.json), [revisión independiente PASS41 comprobaciones](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/metrics-independent-review.json).

| Contenido | PNG |
|---|---|
| Salidas programadas, incorporaciones y llegadas por familia/hora | [01](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/figures/01_salidas_incorporaciones_llegadas.png) |
| Transiciones entre enlaces por hora, todas las familias | [02](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/figures/02_transiciones_horarias.png) |
| Activos, espera de incorporación y solicitudes vencidas sin incorporación | [03](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/figures/03_activos_pendientes.png) |
| Completitud y censura por familia | [04](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/figures/04_completitud_censura.png) |
| Intentos WAIT por motivo | [05](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/figures/05_esperas_por_motivo.png) |
| Deterioro matinal y transiciones residuales nocturnas | [06](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/figures/06_deterioro_recuperacion.png) |
| Composición/completitud por clase OD privada | [07](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/figures/07_composicion_comportamiento_od.png) |
| Buses físicos y expediciones separados | [08](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/figures/08_buses_flota_expediciones.png) |
| Transiciones nativas exactas por familia/hora | [09](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/figures/09_transiciones_por_familia.png) |

Nueve PNG revisados visualmente y nueve SVG comprobados: [verificación final PASS](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/metrics_figure_verification.json). El suplemento nativo concilia422727 transiciones de carros,544078 de motos,37060 de camiones y79348 de buses:1083213 en total. [Suplemento y versiones de fuentes](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/metrics_native_summary.json). No se ejecutó ni se probó el visor HTTP/UI.

La caída empieza06:30–08:00, hay recuperación parcial08:00–09:00 y una nueva caída desde09:15, persistente desde09:45. Son intervalos descriptivos de la serie, no un umbral físico ni el instante de un defecto. Entre20:02 y21:02 hay60 minutos completos sin transiciones/llegadas. Después aparecen182 transiciones y ninguna llegada; última ventana positiva22:11–22:12, seguida de108 minutos completos sin transiciones hasta24h. Desde20:02 hasta24h hay238 minutos completos sin llegadas. [Series y cobertura](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/metrics_temporal_summary.json).

**Últimos eventos exactos de la única extracción nativa completa:**

| Familia | Última llegada nativa | Último `entered link` | Vehículo de la última transición |
|---|---|---|---|
| Carros | 64670 =17:57:50 | 65699 =18:14:59 | `z1_92699` |
| Motos | 64365 =17:52:45 | 65690 =18:14:50 | `z1_55419` |
| Carga | 16494 =04:34:54 | 79915 =22:11:55 | `freight_000999` |
| Buses | 72061 =20:01:01 | 72061 =20:01:01 | `ptbus_transmetro_L2_003` |

Última transición global: evento111526396/línea111526398, enlace `osm_64401484_4_forward`, t79915; última llegada: evento99779441/línea99779443, t72061. Quedan6485s sin transiciones y14339s sin llegadas hasta el corte86400. `last_physical_event` del CSV de ciclos de vida incluye salidas y eventos de carril/tráfico: **no** se utilizó como si fuera LinkEnter. [Eventos exactos y contadores por familia](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/events/event-summary.json).

**La reaparición nocturna no recuperó la cohorte retenida.** Comparación completa por vehículo, índice de su incorporación y último LinkEnter: los6655 episodios activos a20:05 siguen siendo exactamente los mismos en DayCut, sin otra transición, salida ni reincorporación. Los25 episodios nuevos son camiones; sus182 transiciones explican íntegramente la circulación posterior y el aumento6655→6680 activos. Ninguno llegó. Primer ingreso nuevo: `freight_000903`, t75731 =21:02:11 en `osm_64401484_2_forward`; primer cruce posterior al hueco: t75735 =21:02:15 a `osm_64401484_3_forward`, evento105259583. No se dedujo el resultado de una muestra de cuatro minutos: se contrastó toda la cohorte final y los contadores de eventos completos. [Prueba de cohortes PASS](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/focal-night-cohort-comparison.json). Cero LinkEnter no excluye desplazamientos dentro del enlace.

WAIT diario: almacenamiento/recepción38751364, señal5647306, cesión427563, parada obligatoria311212, congestión16425 y desconocido394622 **intentos**. No son segundos ni vehículos distintos; las categorías de IDs se solapan. La familia de almacenamiento incluye varios mecanismos, no demuestra que todos los receptores nativos estuvieran llenos. Gráficas de progreso agregan intervalos completos `(h,h+1]`; eventos de ciclo de vida usan `[h,h+1)`. No se prorratean intervalos ni se inventan tiempos de viaje para censurados.

`unknown` es la categoría nativa, no ausencia de motivo crudo: sus394622 intentos se concilian exactamente con `passage_connector_occupied`367706, `passage_connector_locked`245, `passage_node_locked`915, `passage_signal_not_green`24372 y `passage_signal_window_too_short`1384. Se preserva la clasificación original sin modificar el auditor.

La composición OD conserva las cuatro clases privadas del insumo. Los viajes con origen interno tienen completitudes observadas alrededor de16.5–17.1%, frente a8.3–9.3% con origen exterior; son diferencias descriptivas de esta realización, no causas identificadas. Carga y público permanecen como servicios separados. [Tabla OD](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/metrics_od.csv).

### Causa: congestión física acreditada en focos; clasificación global C — indeterminado

**No se demostró un movimiento admisible impedido incorrectamente ni se reprodujo un defecto.** Hay rechazos locales físicamente consistentes, pero no prueba suficiente de que todas las denegaciones fueran necesarias ni de la causa última del bloqueo global. `completed/valid` conserva su alcance de integridad y propiedades físicas auditadas; no se convierte en prueba de progreso garantizado. [Revisión causal y límites](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/cause-review.json), [revisión independiente de los primeros focos](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/cause-independent-review.json).

| Foco y estado | Evidencia temporalmente coherente | Clasificación y alcance |
|---|---|---|
| 21 Calle, `L12_010`, t23399 =06:29:59, receptor `osm_60237259_1_forward`/`_2_forward` | 35 reservas vivas anteriores al WAIT. Cuatro slots de capacidad efectiva38.2599274m; ocupaciones33.8/33.8/31.8/34.0m. Restan4.46/4.46/6.46/4.26m, todos menores que13.6m del bus. El enlace `_1` vacío no implica corredor vacío. | **A local**: rechazo de recepción justificado. La capacidad efectiva del ledger no es la longitud nominal46.8198846m. [Propietarios y cuentas](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/focal-L12-010-23400.json). |
| 22 Calle, nodo410441329, `z1_59680` esperando, propietario `z1_44606`, t28799 | Reserva344880 adquirida28794; estado28797: tiempo mínimo satisfecho, cuerpo sin despejar. El frente0m de28799 es posterior al WAIT dentro del mismo segundo: sólo se usa como cota retrospectiva explícita por monotonía, en la misma referencia del corredor receptor; no medición simultánea. Además el WAIT registra rojo. | **A local**: no hay obligación de liberar por tiempo mínimo. [Orden, referencias y prueba](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/focal-22calle-lock-28800.json). |
| Avenida Bolívar, `L12_039`, ruta `1521208741_3`→`64387808_0..3`→`60237257_0`, estados07/08/11/20:05 y cierre | Misma incorporación23972 =06:39:32; último LinkEnter24041 =06:40:41. En07/08 el conector tenía tres propietarios; en11h cambian a `z1_01965`, `z1_09656`, `z1_52134`, `z1_35594`, que siguen en20:05 y al cierre. Las reservas anteceden a las decisiones examinadas. El carro01965 espera un corredor con sólo3.44734/1.64734m disponibles frente a su huella4.6m. | **A local** para las dependencias comprobadas; **C** para su causa inicial y la raíz aguas abajo. La geometría de paso es una reconstrucción del modelo, no GIS verificado. [11h](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/focal-persistent-L12-039-39600.json), [comparación matinal](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/focal-persistent-L12-039-morning.json), [noche](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/focal-persistent-L12-039-night.json). |

Controles temporales: `L12_010` sí salió de la retención de06:30 y avanzó a24934; a09:00 aparece con otra incorporación, una expedición distinta. `L12_007/013` permanecieron retenidos durante horas pero avanzaron entre09:45 y10:00; `L12_011/026` también avanzaron después. El deterioro agregado no se interpreta como inmovilidad de todos desde06:30. En contraste,039 conserva el mismo episodio hasta86400; edad nativa de cabeza62358s, distinta del número de intentos y de la duración de cada motivo.

**Lo que impide una clasificación global A o B:** las trazas y extractos no reconstruyen exhaustivamente la partición nativa vehQueue/buffer ni todos los estados anticipados de prioridad; el primer rechazo corporal de039 en24043 no tiene un contexto inicial completo de propietarios. La extracción acotada no conserva por vehículo todos los PassageHold previos a una adquisición: su ausencia no significa cero. Un déficit de espacio de parada del enlace inmediato tampoco basta cuando puede existir un pasaje autorizado con recepción posterior. Por ello las pruebas A de capacidad se limitan a las ramas y receptores acreditados; no se usan estados de otro instante ni IDs de carril como prueba de independencia. Los frentes son límites modelados, no posiciones continuas observadas.

**B: defecto reproducido, ninguno.** No se preparó una fixture con estados inventados ni se aplicó un parche de producción. La evidencia actual no justifica cambiar QueueWithBuffer, demanda, rutas, geometría, señales, cuerpos, capacidades, recepción, prioridades ni reservas para mejorar el resultado.

Para039, el frente utilizable del conector `_3` es17.6099999m, mientras el paso del bus requiere18.3282926m (huella13.6m más margen de despeje4.7282926m). Por eso necesita atravesarlo hacia una recepción posterior: no basta comparar la longitud del bus con la longitud nominal del enlace. Es una reconstrucción con la fórmula nativa y la ruta fija preservada, declarada como tal en la evidencia.

Se reutilizaron productos existentes para [métricas y gráficas diagnósticas](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/metrics_summary.json). **Única lectura incremental de eventos cerrados terminada PASS/exit0:**121569942 eventos, t0..86400,4328390890 bytes comprimidos,82325724655 descomprimidos, XML cerrado, CRC/EOF correctos, cero retrocesos temporales y SHA `11e4ec21f72fac7bd8ce05222d619f446427aca5a5995288a777771be69b2bb1`, idéntico al manifiesto. Fuente explícita `output/ITERS/it.0/0.events.xml.gz`;**2593** contextos focales, estados acotados y ejemplos de reruteo preservados. [Cobertura](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/events/coverage.json), [conciliación con productos previos PASS](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/native-reconciliation.json), [log persistente](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/scan-closed.log). No se volvió a extraer el log textual ni se repitió la lectura de eventos. No se ejecutó QSim, Validate o DryRun ni se modificaron fuentes productivas. No hay un defecto demostrado ni un parche productivo propuesto.

Seguimiento de solo lectura desde la raíz:

```powershell
Get-Content -LiteralPath '.\runtime\diagnostics\run110k-circulation-20261106-748fa711\closure\final-status.json' -Raw -Encoding UTF8
Get-Content -LiteralPath '.\runtime\launches\748fa7117cdb485ba566a60f289b2994\state.json' -Raw -Encoding UTF8
```

Entrega comprobada: extracción, conciliaciones y posproceso diagnóstico exit0; revisiones independientes de métricas, pruebas locales y [cierre nativo/figuras](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/final-independent-review.json) PASS. El primer agregador de gráficas rechazó una convención de límite horario; se corrigió la interpretación del producto publicado y el segundo intento pasó. Se conservan ambos logs y las dos lecturas del CSV derivado; los retoques visuales usan caché. No hubo segunda lectura de eventos ni reextracción del log.

La huella se comprobó antes/después mediante el mecanismo existente y sigue siendo `d9c47644…a96d`; el manifiesto y el SHA nativo permanecen intactos. `git diff --check` PASS; único archivo rastreado modificado: este avance, preservando su contenido previo como histórico. [Inventario final de procesos](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/processes-final.json): procesos originales y lector ya ausentes; no se terminó ninguno. [final-status.json](../runtime/diagnostics/run110k-circulation-20261106-748fa711/closure/final-status.json) registra por separado los SHA de los seis scripts diagnósticos respecto de la huella productora nativa. No hubo compilación ni regresiones de producción porque no se cambió producción; las comprobaciones de datos no acreditan otra masiva. No hubo commit, push, reset, clean, borrado histórico, modificación de recibos ni promoción de Run110K.

### Próxima escala y alcance preservado

**Recomendación:10K manual primero;55K sólo después de revisar su cierre y circulación.** Los DryRun preparados `3c17e4f81421405a8d6c7fbb4a029c5e` (10K/v5/native_diagnostic_v1) y `d0d0694dc6534355aef253bcd6c5ce97` (55K/v3/automatic_replay_v1) comparten la base, semillas20261023, servicio2026-10-23, OD, señales, políticas físicas, composición44/55/1, horizonte24h e iteración0 de Run110K. Conservan269 buses fijos. La semilla común no garantiza poblaciones anidadas ni un umbral monotónico. Comparar tasas, acumulación, incorporación y deterioro por familia/OD, no sólo conteos absolutos. Si10K también pierde circulación gravemente, diagnosticar antes de55K. No ejecutar201381/220K para resolver esta incertidumbre.

Los recibos proceden del ensayo Run1000 aceptado de esta base; **Run110K no se convierte en ensayo aprobado**. El lanzador manual debe aplicar sus guardas ordinarias y verificar de nuevo identidad, huella, recursos y exclusividad. [Runbook existente](RUNBOOK_MANUAL_24H.md). Ninguna escala, QSim, Validate o DryRun se inició en este diagnóstico.

Si se demuestra un defecto en el futuro: fixture nativa que reproduzca la contradicción y controles negativos, propuesta revisable antes del cambio productivo; después regresiones afectadas (incluidas C529-A/B/C/D, OD/OSM, pasajes temporales, L18, llegada corporal, parada bloqueante y última parada de buses), Validate y DryRun secuenciales con huella nueva y ensayo Run1000 manual aplicable antes de las escalas. No reutilizar recibos de una revisión incompatible ni modificar esta Run110K histórica.

**Siguiente acción recomendada:** el usuario puede decidir el lanzamiento manual10K preparado, con sus guardas ordinarias, para comparar la aparición del deterioro. Este diagnóstico está cerrado;55K queda condicionado a revisar10K y ninguna escala se inicia automáticamente.
<!-- RUN110K_CLOSURE_ACTIVE_END -->

# Estado histórico: Run110K en ejecución; una hora registrada sin transiciones ni llegadas, causa pendiente

2026-11-06, corte de evidencia **09:38:25 Guatemala / 15:38:25 UTC**. Diagnóstico autorizado de solo lectura de la ejecución: no se detuvo ningún proceso, no se lanzó QSim ni se ejecutaron pruebas, Validate o DryRun; no se modificaron fuentes, insumos, scripts, manifiestos ni recibos. Se conservaron únicamente copias y extractos diagnósticos y se actualizó este encabezado. El cierre documental del 5 de noviembre que sigue debajo es histórico: precede al lanzamiento manual actual.

**Recomprobación de entrega09:46:58 Guatemala:** misma JVM, launcher y manifiesto **running/pending**, retorno nulo, último paso registrado77580=21:33:00. [Observación de entrega](../runtime/diagnostics/run110k-circulation-20261106-748fa711/delivery-observation.json); se conserva también la [observación anterior09:42](../runtime/diagnostics/run110k-circulation-20261106-748fa711/final-observation.json). No extiende la cobertura detallada de circulación más allá de76980. Integridad de copias, vínculos, intervalos y conciliación de categorías/reruteos PASS/exit0; revisión independiente de semántica y cronología matinal, y `git diff --check` PASS. [Controles de extracción](../runtime/diagnostics/run110k-circulation-20261106-748fa711/extraction-verification.json); no equivalen a aprobación de la corrida.

**Identidad contrastada:** LaunchId `748fa7117cdb485ba566a60f289b2994`, Run ID `simz1-d42056291fa2422699a8b6613f795eeb`, iteración 0, directorio `scenarios/zona1/montecarlo/run-bg110-748fa7117cdb485ba566a60f289b2994`. Selector `half`, N=110000 no públicos (108900 privados y1100 carga),269 buses adicionales, horizonte86400. Huella registrada `d9c47644bb8d3afa18f383aab1c9d0407fd18228361e06629527d38f8e31a96d`. El `state.json` y el manifiesto dicen **running**; validación **pending**, ninguna iteración completada y retorno nulo. La JVM nativa23428, padre4000, creación `2026-11-06T06:33:35.315Z`, usa JDK17/heap12G y coincide con `native-process.json`; se comprobó la cadena del launcher2664 por PID, padre, creación y comando. No se confunde con el Java del IDE.

**Hallazgo principal:** la primera ventana completa con cero `LinkEnterEvent`, cero `PersonArrivalEvent` y activos constantes es **(72120,72180] = (20:02:00,20:03:00]**. Le siguen59 ventanas iguales: **60 minutos completos hasta75720 =21:02:00**, con6655 activos y780 IDs distintos con WAIT en cada minuto. No hubo ninguna ventana de cero transiciones anterior, salvo el reporte inicial t=0. El segundo exacto del último evento y sus IDs no están en este log: ambas últimas observaciones positivas previas están en **(72060,72120] = (20:01:00,20:02:00]**, una llegada y una transición. No se asigna72120 como segundo exacto de esos eventos.

La ausencia global de transiciones **no continuó indefinidamente**: en **(75720,75780]** aparecen8 transiciones y los activos suben a6656. Hasta el corte76980 =21:23:00 se registran69 transiciones desde esa reaparición,8 activos netos adicionales y **ninguna llegada**. Última ventana observada con transiciones: **(76920,76980]**,6 transiciones; último reporte:6663 activos,783 IDs con WAIT, edad máxima de cabeza52938s. Son **81 minutos completos sin llegadas** desde72120. Esto no demuestra liberación de la cohorte retenida ni invalida la hora completa sin cruces entre enlaces.

### Evidencia y cobertura de esta observación

Directorio separado: [runtime/diagnostics/run110k-circulation-20261106-748fa711](../runtime/diagnostics/run110k-circulation-20261106-748fa711/). [Resumen verificable](../runtime/diagnostics/run110k-circulation-20261106-748fa711/summary.json), [serie por minuto](../runtime/diagnostics/run110k-circulation-20261106-748fa711/progress-60s.csv), [serie horaria](../runtime/diagnostics/run110k-circulation-20261106-748fa711/progress-hourly.csv), [primera ventana y contexto](../runtime/diagnostics/run110k-circulation-20261106-748fa711/first-zero-window-context.log), [procesos observados](../runtime/diagnostics/run110k-circulation-20261106-748fa711/processes-observed.json).

Se leyó una vez un prefijo acotado del **log de texto** `output/logfile.log` y después sólo su cola desde el offset conservado. Copias `logfile-prefix.log` y `logfile-tail-01.log`: bytes[0,11134712), líneas1..43850;1284 reportes t0..76980, una iteración, sin huecos entre muestras de60s. `coverage.json` conserva SHA del prefijo y `tail-01-coverage.json` sus límites. `progress-complete.jsonl` usa el parser existente `simz1_operational_report.progress_attributes`; la extracción inicial de1281 muestras se contrastó campo por campo contra ese parser, PASS/exit0. Son controles de extracción, **no auditoría nativa ni aceptación**. Las copias de identidad conservan procedencia y SHA en `identity-snapshot-provenance.json`. No se abrió el gzip activo de eventos, planes ni `signalEvents2Via.csv`; no se inició otro observador persistente.

### Deterioro matinal, circulación residual y ventana vacía

Los intervalos siguientes son abiertos al inicio y cerrados al final; las cantidades de llegadas/transiciones son del intervalo, activos al cierre y máxima edad observada en el minuto final. Las llegadas incluyen todos los modos registrados por `PersonArrivalEvent`; no son viajes privados aceptados.

| Intervalo simulado | Llegadas | Transiciones | Activos al cierre | Máxima edad de cabeza observada en el minuto final, s |
|---|---:|---:|---:|---:|
|05:00–06:00|1876|135367|432|726|
|06:00–07:00|2858|225765|2012|3037|
|07:00–08:00|1237|118175|4363|6637|
|08:00–09:00|2528|212682|4795|10237|
|09:00–10:00|1466|92698|5372|12772|
|10:00–11:00|206|15861|5861|15558|
|11:00–12:00|61|5778|6092|19158|
|12:00–13:00|56|3652|6186|22758|
|13:00–14:00|51|3133|6276|26358|
|14:00–15:00|49|2478|6347|29958|
|15:00–16:00|45|1896|6418|33558|
|16:00–17:00|47|1897|6503|37158|
|17:00–18:00|56|1963|6619|40758|
|18:00–19:00|36|439|6656|44358|
|19:00–20:00|36|325|6657|47958|
|20:00–21:00|2|7|6655|51558|
|21:00–21:23, parcial|0|69|6663|52938|

La pérdida es progresiva, no comienza con la ventana nocturna: hay deterioro en07:00–08:00, recuperación parcial08:00–09:00 y una caída marcada entre09:00 y11:00. La primera pareja consecutiva sin llegadas termina38940 y39000, **10:49 y10:50**, pero conserva171 y173 transiciones: todavía había circulación. El perfil de salidas generado tiene demanda durante las24h; salidas programadas no equivalen a incorporaciones efectivas. Esta evidencia no demuestra que N o el perfil sintético sean erróneos ni autoriza reducirlos.

**Detalle solicitado sobre el comienzo de la degradación:** [serie de15 minutos05:00–12:00](../runtime/diagnostics/run110k-circulation-20261106-748fa711/degradation-15m.csv), derivada del mismo snapshot, sin nueva lectura de eventos. Entre05:00 y06:30 crecen simultáneamente caudal y activos132→1194. El primer descenso sostenido entre cuartos aparece06:30–08:00: transiciones56011→50606→41931→34870→24221→17153, mientras activos1194→4363. **No es bloqueo global permanente:**08:00–09:00 recupera212682 transiciones y2528 llegadas;08:30–08:45 registra65565 transiciones, el mayor cuarto entre05:00 y11:00. Las retenciones largas coexisten con esa recuperación.

La última franja comparable al caudal alto matinal llega hasta **09:00–09:15:47870 transiciones,628 llegadas**, frente a65565/749 en08:30–08:45. Después09:15–09:30 cae a17333/267;09:30–09:45 conserva16553 transiciones y recupera444 llegadas, con activos5112→5073. Desde09:45 continúa un deterioro marcado:10942/127 en09:45–10:00,7840/91 en10:00–10:15 y1924/22 en10:45–11:00. «Circulación significativa» no tiene aquí un umbral físico ni de aceptación predefinido: estos intervalos identifican la última fase de caudal alto y la posterior circulación irregular, no el segundo exacto de un defecto. La tarde conserva flujo residual;21:02–21:23 sólo69 transiciones en21 minutos, **3.29/min**, sin llegadas.

En la primera ventana vacía t72180 se registran46800 intentos WAIT,780 vehículos distintos y edad máxima48138s; al final t75720 siguen46800 intentos y780 distintos, con edad máxima51678s. El máximo es una edad de cabeza observada, no duración demostrada de una razón ni de un mismo vehículo a través de todos los minutos.

| Categoría WAIT durante los60 minutos vacíos | Intentos por minuto, mínimo–máximo | IDs distintos por minuto | Intentos acumulados en la hora |
|---|---:|---:|---:|
|insufficient_storage|40983–41374|767|2469735|
|signal|4818–5196|162|301320|
|yield|248–261|7|15345|
|unknown|360|6|21600|

Total2808000 **intentos**, no segundos ni vehículos únicos. Los IDs de categorías se solapan: no sumar767+162+7+6. Tampoco restar780 de6655 para inferir vehículos circulando. `activeVehicles` es entradas menos salidas de tráfico, no movimiento;780 sólo cubre IDs que emitieron WAIT ese minuto. El log no acredita que los mismos780 hayan esperado en cada minuto. Cero `LinkEnter` no mide desplazamientos dentro del enlace.

Los contadores públicos permanecen en193 buses activos y1993 expediciones iniciadas acumuladas desde72120 hasta76980. Las incorporaciones netas posteriores a75720 son del componente no público; el log no permite atribuir las69 transiciones a IDs nuevos o antiguos. Tampoco permite restar expediciones de llegadas para obtener completados privados. No hubo abortos públicos registrados en este prefijo.

### Qué está acreditado y qué sigue indeterminado

Predominan rechazos nativos agrupados como **almacenamiento/recepción**, con señales, cesión/prioridad y una categoría desconocida. Esta agrupación incluye más de un mecanismo; no separa receptor nativo lleno, reserva corporal, pasaje bloqueado o propagación desde otro receptor. El log operativo no contiene IDs actuales de vehículos, enlaces, nodos ni propietarios de reservas. No existe un foco espacial actual demostrado con esta evidencia.

Durante la hora vacía hubo3543 cálculos de reruteo y **cero segmentos de instalación**; los callbacks terminaron `completed`. La última fase de instalación observada en el prefijo fue t65880=18:18, sin identificación de vehículo en el texto. Buscar alternativas y consumir CPU no implica instalar rutas ni circular. Los motivos de rechazo de candidatos requieren los eventos. `deadlockedThreads=0` sólo corresponde al detector de ciclos de hilos JVM: no descarta bloqueo físico de red. Los contadores del prefijo conservan cero movimientos forzados y cero remociones por atasco.

**Clasificación actual: ausencia sostenida de descarga y de transiciones acreditada; causa raíz indeterminada.** Es compatible con retención física y propagación de falta de recepción, pero aún no está demostrado un ciclo irreversible, defecto del motor, defecto de configuración o exceso de demanda como causa única. No se ha demostrado un defecto de QueueWithBuffer ni se propone deshacer su reparación de parada bloqueante.

**Tres situaciones que pueden coexistir por vehículo, componente y ventana:**

| Situación | Qué permite afirmar esta corrida | Qué falta para clasificar los retenidos |
|---|---|---|
|Demora con circulación|Hay transiciones durante el deterioro matinal, la tarde y después de21:02; cero llegadas por sí solo no es inmovilidad.|Identificar qué vehículos siguen cruzando o despejando, sin atribuir a los6655 las transiciones de otra cohorte.|
|Bloqueo físicamente consistente|Es una hipótesis compatible con la falta de recepción dominante, las edades largas y la acumulación de activos.|Acreditar simultáneamente cabezas FIFO, receptor y cuerpo completos, reservas/propietarios, señales, prioridad, ruta y dependencias que justifican cada espera. Los agregados no bastan.|
|Defecto de implementación|No está demostrado un movimiento físicamente autorizado que el código haya impedido.|Reproducción focal nativa del mismo estado y orden de decisión, con todas las condiciones de avance satisfechas, o liberación/actualización obligatoria omitida.|

Un rechazo local correcto puede propagarse desde otro receptor o desde un defecto aguas abajo; hace falta seguir la cadena. Un verde, ruta topológica válida o hueco PCU aislados no autorizan el movimiento: deben coincidir elegibilidad FIFO/tiempo/flujo, cursor y giro, permiso y despeje, recepción nativa, cuerpo completo con0.10m y reservas compatibles. No combinar mediciones de instantes distintos ni tratar una consulta como movimiento confirmado. En ausencia de esas condiciones observables se conserva **indeterminado**.

**Plausibilidad de congestión del modelo:** la configuración registrada usa factores de flujo/almacenamiento1.0, reservas de cuerpo completo, admisión `strict-receiver-v1`, señales, prioridades y `removeStuckVehicles=false`; superar stuckTime10s no obliga a forzar paso ni retirar cuerpos. El código nativo conserva expresamente esa posibilidad de gridlock (`Zona1QNodeImpl.java:557`). Es coherente que colas propagadas puedan bloquear componentes aun con JVM activa. Esto acredita la posibilidad del mecanismo, no que todas las reservas y decisiones de esta corrida sean correctas. [Contexto de configuración preservado](../runtime/diagnostics/run110k-circulation-20261106-748fa711/model-context.json).

La plausibilidad empírica queda separada: la demanda y composición son sintéticas, el perfil horario suma108900 salidas privadas programadas y los offsets semafóricos no son tiempos medidos de campo. Las validaciones declaran `physical_stability_proven=false` y `empirical_calibration=false`. No atribuir un eventual gridlock consistente a la ciudad real sin contrastar demanda, capacidades, geometría y controles con observaciones. Si el bloqueo se acredita físicamente válido, reportarlo como **congestión del modelo**, conservándolo; no «arreglarlo» mediante más capacidad, liberaciones por timeout, saltos FIFO o remociones. Si se acredita un defecto, exigir la reproducción nativa antes de modificar producción.

Comparación histórica, sin trasladar causalidad:

- **C529/N180K:** primer minuto completo vacío también termina72180; el movimiento residual de buses terminó cerca de72061. El foco temprano Elena/10a Calle y el veto de pasaje/prioridad pertenecen a aquella corrida. [Diagnóstico C529](../runtime/diagnostics/c529-a27d8bae5d/DIAGNOSTICO_C529.md).
- **5906/N180K:** última transición75597 y llegada75598;6311 activos y10803s posteriores sin ambas. Se reprodujo un defecto focal de factibilidad temporal entre señales, reparado después, sin demostrar que explicara toda la red. La reaparición actual de transiciones desde75780 distingue las cronologías. [Diagnóstico5906](../runtime/diagnostics/5906-h0kzpokz/DIAGNOSTICO_5906.md).
- **220K/9da9:** deterioro desde07:00 y ausencia de nuevas llegadas no públicas desde11:00, pero cuatro buses aún circulaban en58800–59159;6681 activos al corte incompleto. Tres focos reproducidos posteriormente fueron rechazos correctos de recepción/despeje. [Diagnóstico220K](../runtime/diagnostics/220k-closure-20261103-9da9ec50/DIAGNOSTICO.md), [reproducciones](../runtime/diagnostics/repair24h-20261103/REPARACION.md). No era prueba de inmovilidad total ni de la causa actual.

### Siguiente acción tras el cierre natural; sin otra QSim

Mientras continúe la ejecución, mantener fuentes e insumos congelados. Esta observación termina con QSim activa; no se declara completed/valid, no se publica aceptación ni se generan gráficas oficiales. Alcanzar86400 no acredita movilidad.

Después del cierre natural, comprobar la misma identidad, salida nativa, manifiesto, iteración0, integridad XML/gzip, auditorías OD/OSM/FIFO/cuerpos/señales/buses, llegadas y censura al corte. Reutilizar las auditorías y compactos del posproceso existente antes de otra lectura; mantener `review_required` y sus informes si corresponde. No repetir QSim por fallo de análisis o presentación.

Si faltan IDs y razones focales, realizar **una única extracción incremental de eventos cerrados**, coordinada con el lector existente: contadores por minuto durante toda la cobertura y retención acotada de últimos movimientos por vehículo, cabezas persistentes y dependencias de sus receptores/propietarios. Ventanas prioritarias de detalle:06:00–11:00 para el deterioro,72000–72300 para el último movimiento previo y75660–75900 para la reaparición. Expandir sólo la historia de las dependencias identificadas; mantener cobertura, límites y datos ausentes explícitos. No cargar XML completo ni duplicar escaneos masivos.

Eventos necesarios: LinkEnter/LinkLeave/PersonArrival y entradas/salidas de tráfico; `simz1NativeDecision` con razón, enlace/carril/siguiente receptor, señal, `rejectionStage`, `nativeReceiverAcceptedAtDecision` y observación de reserva; `simz1OccupancyReservation`, `Progress`, `Passage/PassageState/PassageHold`; reruteos candidatos, rechazados e instalados con OD, prefijo por ocurrencia y cursor. Separar consulta de admisión y movimiento confirmado. Reconstruir una dependencia física sólo con receptor y propietario identificados; los límites corporales modelados no son posiciones observadas.

**Corrección mínima propuesta: aún no hay un parche justificable.** Primero aislar un rechazo incorrecto reproducible. Si se acredita, preparar fixture con componentes nativos que falle antes del cambio y pase después, más controles de rojo, receptor ocupado, reserva válida y prioridad real. Elegir según mecanismo `SimZ1AdmissionAttributionCheck`, `SimZ1PriorityReceiverCheck`, pasajes/despeje o reruteo; conservar BlockingStopCheck, C529-A/B/C/D, OD/OSM, pasajes temporales, L18, llegada corporal y última parada de buses. No ajustar N, capacidades, semilla, rutas, señales o auditor para conseguir PASS; no aplicar nada a esta corrida histórica. Pruebas focales, Validate y DryRun sólo en la futura revisión autorizada y secuencial; Run masivo permanece manual.

Seguimiento puntual de solo lectura desde la raíz, sin `-Events` ni observador nuevo:

```powershell
Get-Content -LiteralPath '.\runtime\launches\748fa7117cdb485ba566a60f289b2994\state.json' -Raw -Encoding UTF8
Get-Content -LiteralPath '.\scenarios\zona1\montecarlo\run-bg110-748fa7117cdb485ba566a60f289b2994\output\logfile.log' -Tail 80 -Encoding UTF8 |
    Select-String 'SIMZ1_PROGRESS|SIMZ1_TRANSIT_COUNTERS|SIMZ1_WATCHDOG'
```

No hubo cambios productivos ni pruebas de movilidad en este diagnóstico. La extracción y conciliación de texto terminaron exit0; `git status --short` estaba limpio antes de esta actualización documental. Comprobar el impacto documental en la huella mediante el mecanismo existente antes del próximo lanzamiento, sin alterar exclusiones.

## Histórico: reparación validada, Run1000 recuperada y seis DryRuns elegibles; ejecución futura manual

2026-11-05 23:55 Guatemala. **Trabajo autorizado completado sin ninguna simulación completa.** Se ejecutaron fixtures pequeñas, pruebas Java/Python/PowerShell, Validate integrado, recuperación sin QSim y seis DryRuns oficiales secuenciales. La siguiente acción posible es el Run manual del escenario elegido desde PowerShell externa, usando exclusivamente su DryRunLaunchId de esta revisión. Run1000 ya está recuperada y no necesita repetirse. Comandos separados en [runbook vigente](RUNBOOK_MANUAL_24H.md); no hay Run automático encadenado.

Revisión congelada **`d9c47644bb8d3afa18f383aab1c9d0407fd18228361e06629527d38f8e31a96d`**,749 dependencias, incluidas las cinco fuentes nuevas. **Validate integrado PASS0**: `balanced-launch-890908db581e4f7290fe2f191495da63`,22:50 Guatemala del5noviembre. No se modificaron fuentes después. La huella se comprobó de nuevo al cerrar la documentación; estos dos MD no pertenecen al inventario existente, sin cambiar exclusiones. [Índice verificable de evidencias](../runtime/diagnostics/launcher-repair-20261105/final-status.json), [estado Validate](../runtime/validation/balanced-launch-890908db581e4f7290fe2f191495da63/state.json).

**Run1000 recuperada oficialmente**,23:10 Guatemala del5noviembre: LaunchId original `1ec248b580a24c5fa933c57d17fcc56b`, Run ID `simz1-61974d8bfa6a4e5cb34739d9d76c0e3c`, directorio `scenarios/zona1/montecarlo/run-bg1-1ec248b580a24c5fa933c57d17fcc56b`, it.0. Conserva completed/valid nativo,988 viajes privados completos y2 censurados al corte86400. El state original sigue postprocessing_failed/verify_result, exit1, child_exit0 y screening_pass. La recuperación `b5666e151a3f41f5bcc8176f6a90aa38` publicó un recibo nuevo y el trial oficial accepted_for_next_load_test_not_calibrated; el inspector y el cierre compartido aprobaron. No se editó el estado histórico, el manifiesto ni los eventos. La revisión productora nativa `eb4e66b366ec7815b8711c1cc360125d093a7a06c9a5b130f0d7e8e2128a5b11` sigue identificada por separado.

Causa demostrada y corregida: postflight exigía en output_config.xml los nombres Java-only writeEventsUntilIteration y writePlansUntilIteration, después del empaquetado. MATSim15 no los serializa como parámetros XML; sus defaults0/1 se comprobaron con la API real. La normalización compartida ahora se usa en preflight, entrada preparada antes de JVM, comparación efectiva antes de análisis y cierre/recuperación. La reproducción original y los controles negativos permanecen en `runtime/diagnostics/launcher-repair-20261105/config/`; no se agregaron parámetros ficticios ni se redujeron reservas.

| Escenario | N | Contrato | Validate | DryRun | LaunchId DryRun | run_launch_eligible | Observaciones |
|---|---:|---|---|---|---|---|---|
| Run1000 | 1000 | v3 / `run1000` | PASS0 | PASS0 | `de24f4cec7834d39b0cb370c7ec15ed3` | true | 440 carros / 550 motos / 10 camiones; +269 buses |
| Run10000 | 10000 | v5 / `run10000` | PASS0 | PASS0 | `3c17e4f81421405a8d6c7fbb4a029c5e` | true | 4400 carros / 5500 motos / 100 camiones; +269 buses |
| Run55000 | 55000 | v3 / `quarter` | PASS0 | PASS0 | `d0d0694dc6534355aef253bcd6c5ce97` | true | 24200 carros / 30250 motos / 550 camiones; +269 buses |
| Run110000 | 110000 | v3 / `half` | PASS0 | PASS0 | `77fb528d35fc4d9bbfdc61b407eb3659` | true | 48400 carros / 60500 motos / 1100 camiones; +269 buses |
| Masiva aleatoria | 201381 | v4 / `random-full-1` | PASS0 | PASS0 | `4bea6d88762f4823abaeb351c2fa1a60` | true | 88608 carros / 110759 motos / 2014 camiones; +269 buses |
| Max-test | 220000 | v3 / `max-test` | PASS0 | PASS0 | `eb0f06364c25416299cf33e6c1659c08` | true | 96800 carros / 121000 motos / 2200 camiones; +269 buses |

Todos los recibos tienen la misma huella que Validate, Java17, semilla20261023, servicio2026-10-23, una iteración0 y horizonte físico86400 (último paso QSim86399). La identidad de especificación/copias/reconstrucción y el gate oficial DryRun→Run aprobaron para los seis; cualquier cambio posterior de selección, revisión o política se rechaza. Ningún DryRun creó población privada, directorio de simulación, Run ID, QSim ni replay.

La selección histórica de189834 (`32fd3de8aa86485586f84c2e0f0348b7`, candidato `bac5f258d6d24935a24bdde0888a157a`) conserva su recibo SHA y su intención de sorteo. El contrato la rechaza con **Sources changed after the random selection**; además su inventario físico precede la corrección FIFO. No se reasignó a la huella nueva ni se consumió otra vez. El procedimiento oficial sorteó una sola vez el candidato nuevo `2c694e9df27d464d94d30b2aa8ffb5ad`: selección `a17518bffee840818110232374a05b17`, **N201381**. Su especificación inmutable es `runtime/experiment-selections/a17518bffee840818110232374a05b17/experiment.json`, SHA `27cd3f901a12e144769bf38efac744f344489a2b4627176b42e6cb1680b8e9e1`; no existe run-claim. Max-test220000 tiene DryRun independiente. Las fronteras180000/220000 también pasaron pruebas de contrato; eso no se presenta como otro DryRun de180000.

Eventos y planes: intervalos1/1, propiedades Java Until0/1, XML/gzip, ITERS conservado y dumps finales; se retienen eventos/planes it.0 más una copia final de cada tipo. Los seis planes normalizados son idénticos. Memoria planning_budget_pass (heap QSim12GiB) y disco PASS, piso100GiB en cada caso, unos169.8GiB libres al comprobar; el cálculo mayor, si lo hubiera, prevalece. Los presupuestos se conservan como estimaciones, no cotas garantizadas. Política automatic_replay_v1 para Run1000/quarter; native_diagnostic_v1 para Run10000/half/random-full-1/max-test, ligada a cada recibo.

Procesos contrastados por PID, padre, creación y comando al terminar: sin launcher, QSim ni recuperación activos; sólo permanece el servidor Java del IDE, ajeno a la tarea. [Instantánea de procesos](../runtime/diagnostics/launcher-repair-20261105/final-processes.json). QueueWithBuffer y BlockingStopCheck conservan sus SHA; la regresión nativa retiene z1_05698 durante la parada bloqueante de L12_006. Validate incluyó OD/OSM, C529-A/B/C/D, señales/prioridades, rojo/recepción ocupada, cuerpos/llegada/despeje, L18, camiones compact-v3, buses y última parada. Windows no permitió crear symlinks: test_reject_symlink quedó omitido; mutación/ausencia de fuentes protegidas sí pasaron.

DryRun no certifica descarga, congestión, recursos máximos ni aceptación futura de una jornada. La aceptación técnica de Run1000 no equivale a calibración. Replay actual preparado e identidad comprobada; no hubo navegación visual HTTP/UI y siguen pendientes las tres omisiones históricas L12. El primer log parcial de BlockingStopCheck se conserva como captura fallida de stderr/WARN; el log completo posterior acredita PASS0. No se hicieron commit, push, reset, clean ni borrados de corridas.

Seguimiento de solo lectura, desde la raíz: `Get-Content -LiteralPath '.\runtime\diagnostics\launcher-repair-20261105\final-status.json' -Raw -Encoding UTF8`. Para un Run futuro, usar su LaunchId real nuevo con `watch_simz1_110k.ps1`; el runbook incluye el comando. Los encabezados inferiores son históricos.

### Mecanismo y comprobaciones de esta reparación

**Recuperación oficial PASS0**,23:10 Guatemala: `runtime/recoveries/b5666e151a3f41f5bcc8176f6a90aa38/recovery-receipt.json`, creada por `recover_simz1_launch.ps1` para el LaunchId explícito anterior. El inspector, el informe operacional, el cierre compartido y el replay obligatorio automatic_replay_v1 aprobaron. `runtime/workflow/trial-balanced-gateway-v1.json` acredita ahora `simz1-61974d8bfa6a4e5cb34739d9d76c0e3c` / it.0 / N1000 bajo la huella actual; coincide byte a byte con `trial-acceptance.json` de la recuperación. El recibo previo se conserva como `prior-trial.json`. No se cambió el state histórico ni se repitió QSim. Manifiesto SHA `0dfd4e38937f5429ab01b5ea74f13e504bc86718d4199a1df37778cf26d34996` y eventos SHA `d02a3c62f650db69d083c5fc49a75ce8c9c3d0e9ed35cf7f5b4d7864044a6485` se verificaron intactos. Los dos censurados al corte86400 y los988 privados completados permanecen tal como se registraron.

El replay se preparó desde SQLite de2,461,728,768 bytes, con quick_check, referencias temporales, SHA secuencial e identidad de la iteración comprobados. No se inició servidor ni navegador, no se efectuó revisión visual y las tres omisiones históricas L12 siguen pendientes. El posprocesamiento tiene procedencia separada de la revisión nativa productora `eb4e66b3…`; no se atribuyen los eventos a la revisión del lanzador `d9c47644…`.

La llamada defectuosa era el bucle de retención de `run_massive_z1_pasante_10it.ps1`, que invocaba `Get-SimZ1MassiveXmlValue` sin default sobre output_config.xml. El helper nuevo `simz1_configuration_contract.py` normaliza únicamente defaults verificados contra la API MATSim15 real y contrasta plan, entrada y configuración publicada. No escribe los campos Java-only en XML. La configuración desconocida o incompatible se rechaza.

| Parámetro controler | XML base | Entrada Run1000 | Publicado MATSim | Interpretación real |
|---|---:|---:|---:|---|
| writeEventsInterval |10|1|1|XML opcional nativo, default50; preparación versionada exige1|
| writePlansInterval |10|1|1|XML opcional nativo, default50; preparación versionada exige1|
| writeEventsUntilIteration |ausente|ausente|ausente|Propiedad Java sin parámetro XML; default0|
| writePlansUntilIteration |ausente|ausente|ausente|Propiedad Java sin parámetro XML; default1|

El probe Java17 comprueba los defaults y que MATSim rechaza ambos nombres Until como parámetros XML; también verifica formato XML/gzip, conservación ITERS, dumps finales, writingOutputEvents y ausencia de prefijo runId. No se cambió `generate_montecarlo_z1.py`. La comprobación de la entrada ocurre antes de iniciar la JVM; la configuración publicada se compara después de la validación nativa y antes del análisis, fuera del manejador que clasifica fallos de movilidad.

| Fase legítima | Controles |
|---|---|
| Antes de QSim | Especificación/selector/N/composición/semilla/fecha/horizonte/iteraciones, insumos, Java17, huella Validate/trial, copia binaria/reconstrucción, pin DryRun→Run, procesos/mutex, retención normalizada, presupuesto RAM/disco y configuración preparada |
| Con archivos nativos | completed/valid, salida natural0, identidad/iteraciones, XML/gzip completo y hashes del inspector, OD/FIFO/cuerpos/señales/carga/buses, censo86400, configuración efectiva y archivos retenidos |
| Con análisis | Identidad de cada iteración, manifiesto/productos, salidas/incorporaciones/llegadas/censura y screening |
| Con paquete | Manifiesto, inventario y hashes del paquete mediante el mismo cierre usado por ejecución y recuperación |

La reserva conserva SQLite8GiB, scratch4GiB, replay2GiB, margen compartido de auxiliares/planes20GiB y crecimiento calculado del pagefile; se aplica el mayor entre100GiB, petición y estimación. Los16,200,887,988 bytes históricos por fichero de eventos son una referencia de planificación, no una cota de demanda futura. Se enumeran también los planes retenidos. No se redujeron guardas.

Pruebas focales:12 de configuración/API/retención/presupuesto,17 del ejecutor con proceso nativo sustituido,10 de cierre/recuperación,100 finales de contratos/identidad/escalas,11 de orquestación de paquete; todos PASS0, además de BlockingStopCheck nativo. Los grupos tienen cobertura compartida; no se suman como pruebas únicas. El ciclo nuevo usa dos personas y dos iteraciones sintéticas, validador nativo de salidas real, análisis/screening/paquete reales y la misma función de cierre; no asigna completed/valid para eludir el validador ni publica aceptación experimental. Logs y controles de mutación/ausencia están en `config/`, `recovery/` y `audit/` del diagnóstico.

Se detectó además que `validate_manifest_selection` fijaba0/1 aunque la especificación v3 incluye full-10. La reproducción previa falló en cuatro subcasos. Ahora exige el número autorizado por la selección y un prefijo entero, ordenado y sin duplicados de iteraciones completadas; v4/v5 siguen una iteración. No se ejecutó full-10. El gate DryRun es común a los selectores oficiales y exige huella, identidad, elegibilidad y política coincidentes; Run1000 conserva su condición de ensayo, sin requerirse a sí mismo como ensayo previo.

Archivos de código modificados, todos dentro de la huella:

- Nuevos: `python/simz1_configuration_contract.py`, `python/test_simz1_configuration_contract.py`, `python/simz1_launch_recovery.py`, `python/test_simz1_launch_recovery.py`, `scripts/recover_simz1_launch.ps1`.
- Integración y gates: `python/ejecutar_simz1.py`, `python/simz1_experiment_preflight.py`, `python/simz1_workflow_state.py`, `python/simz1_scale_contract.py`, `scripts/run_massive_z1_pasante_10it.ps1`, `scripts/check_simz1_110k_balanced_gateway.ps1`, `scripts/run_simz1_with_analysis.ps1`, `scripts/simz1_workflow.ps1`.
- Regresiones existentes ampliadas: `python/test_simz1_dryrun_identity.py`, `python/test_simz1_package_launcher.py`, `python/test_simz1_trial_experiment.py`.

Sólo se actualizan además este avance y `docs/RUNBOOK_MANUAL_24H.md`, fuera del inventario de la huella. No hay cambios Java, del generador de población, de auditores físicos, gráficos, visor, especificaciones, geometría ni servicios. No se hicieron commit, push, reset, clean ni limpieza de corridas.

## Histórico: consolidación anterior al cierre fallido de la Run1000 manual

# Estado histórico: principal consolidado; Validate y DryRun Run1000 aprobados, ejecución manual pendiente

2026-11-05 Guatemala. Integración selectiva terminada, sin corrida completa, commit ni push. Base principal `main`, HEAD `b10b4b750aa330e06fe7083cc022c9c25cfd5306`. Se preservó la huella focal inicial `70b6886b19cc0b39191f8ab8890fec3e9834fe36c9309865c93161a41bc6290a`. La revisión integrada tiene huella **`eb4e66b366ec7815b8711c1cc360125d093a7a06c9a5b130f0d7e8e2128a5b11`**,744 dependencias: las736 anteriores intactas y ocho archivos Python nuevos. **Validate integrado PASS0** con JDK17, `balanced-launch-3dd6fb0cf2884672b5a09f5713fe3940`, terminado21:02 Guatemala; **DryRun Run1000 PASS0**, LaunchId `2475376a4cfa4e369231b8165c95cad1`, terminado21:05. Ambos acreditan exactamente esa huella. [Cierre verificable](../runtime/diagnostics/consolidacion-20261105/final-status.json), [Validate](../runtime/validation/balanced-launch-3dd6fb0cf2884672b5a09f5713fe3940/state.json), [DryRun](../runtime/launches/2475376a4cfa4e369231b8165c95cad1/state.json).

DryRun confirmó `prior_trial_status=not_applicable_this_is_trial`, `run_launch_eligible=true`, identidad de preparación verificada y política `automatic_replay_v1`. Memoria `planning_budget_pass`;173.65GiB libres frente a100 exigidos. **No creó directorio de simulación, población, Run ID, QSim ni replay.** El LaunchId anterior es sólo preparación; la ejecución manual tendrá otro LaunchId real. No se registró trial nuevo ni se habilitó Run10K. El cierre documental no está en el inventario de la huella, comprobado antes/después; no se repite Validate por ese cambio.

## Consolidación y preservación

Integrados byte a byte `python/simz1_thesis.py`, `simz1_thesis_profiles.py`, `simz1_thesis_operations.py`, `simz1_thesis_spatial.py` y sus cuatro `test_simz1_thesis*.py`. Los helpers existentes no cambiaron. Revisión de 78 módulos transitivos sin dependencias operativas de las carpetas auxiliares. Generación individual con RunDir/it.0 explícitos; N procede del manifiesto y las comparativas requieren contratos compatibles.

Los tres archivos físicos/protegidos conservan los mismos SHA256 antes y después:

| Archivo | SHA256 antes = después |
|---|---|
| `src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/QueueWithBuffer.java` | `a1bbdb596b3b3ff5013094c6f75c7776a72d236d34cfe25085b714646f2929ef` |
| `src/test/java/org/matsim/core/mobsim/qsim/qnetsimengine/SimZ1BlockingStopCheck.java` | `df518d0efc4ee0a7da4b7dfceb1e08de4816476651f74db405622f5939268cfd` |
| `python/test_simz1_sequence_contract.py` | `250f3847eb3b75f77610557695820861fc2fd95c1827d3633d99f6bc6144ed30` |

El avance anterior completo se conserva debajo y en `main-before.zip`; se actualiza únicamente el encabezado y el runbook operativo. No se reemplazó Java, contratos, auditores ni lanzadores desde una copia antigua.

Respaldos locales fuera de GitHub: [runtime/archives/consolidacion-20261105](../runtime/archives/consolidacion-20261105/). Inventarios por archivo incluyen destinos, SHA256 y exclusiones justificadas de bytecode/builds; el junction `.venv` se identificó separadamente. Se verificó cada miembro comprimido y el SHA del ZIP, además de `git bundle verify`:

| Respaldo | Miembros verificados | SHA256 |
|---|---:|---|
| `graficas-tesis-v2.zip` | 774 | `4979d69a0009b96f6adeb56bf5d5ee487a8a3569d1d50648ff17a9770da7da92` |
| `repair-20261104.zip` | 4268 | `1b25f83ba0bc2006a8ed8a0abc0072483f10e17352ba45d9da357424a9c6f4b1` |
| `repair-20261104-history.bundle` | historia Git | `884c40ff6fc954374721405c41df84bc8f5921cc71d3ad1cae28e5c15cb9db6b` |

También se preservaron diffs binarios staged/unstaged, archivos nuevos/ignorados relevantes, metadatos administrativos del worktree y archivos iniciales del principal. El HEAD repair `4550fdc7cca46b2d4c3ea5fd0b0fff81ec6d98dd` es ancestro del principal, sin commits exclusivos. Sus 34 cambios locales: **21 ya integrados,12 reemplazados por versiones posteriores,1 runbook histórico exclusivo respaldado; cero inciertos**. Los 818 diagnósticos históricos únicos están dentro del ZIP con sus rutas originales y mapa por miembro. [Clasificación y evidencia](../runtime/diagnostics/consolidacion-20261105/repair-audit/INFORME.md).

Los inventarios originales son anteriores a la retirada. La nota de intención del junction `.venv` (`no linked contents ... removed`) quedó superada por el incidente descrito abajo; no se reescribió para ocultarlo. El resultado posterior está en `repair-20261104-removal.json` y `venv-recovery-result.json` del diagnóstico de consolidación.

Ambas rutas auxiliares exactas ya fueron retiradas. Gráficas era una carpeta ordinaria: `Remove-Item -LiteralPath <ruta exacta> -Recurse -Force`. Repair era un worktree con cambios íntegramente respaldados: `git worktree remove --force <ruta exacta>`. Antes de cada operación se verificaron ruta raíz sin reparse, procesos, clasificación, SHA del respaldo y todos los archivos originales frente al inventario. Git reconoce sólo el worktree principal. No se borraron ramas ni corridas.

**Incidente de retirada resuelto:** Git siguió el junction interno `.venv` del worktree y vació el entorno compartido del principal. El guard posterior detectó inmediatamente la ausencia de `Scripts/python.exe`; el wrapper terminó1 aunque Git ya había retirado el worktree. No se repitió la eliminación. Se reconstruyó `.venv` con Python3.10.11 y las48 dependencias fijadas del entorno de instalación previamente conservado en `runtime/install-python-16539c5af4d74ae58116566f8dba556c`; numpy2.2.6/matplotlib3.10.9/Pillow12.3.0 coinciden con los manifiestos anteriores. Instalación y `pip check` PASS0;71 pruebas gráficas repetidas PASS0 (13.584s). No se afirma identidad completa con el entorno perdido. Fuentes y datos nativos permanecen intactos. Evidencia de recuperación y comprobaciones en `runtime/diagnostics/consolidacion-20261105/venv-*`.

## Figuras, pruebas y siguiente fase

La publicación `graficas_tesis_v2/revision-03` conserva **22 figuras/92 archivos byte a byte**. [Traslado y hashes](../graficas_tesis_v2/traslado-20261105.json), [operación de los generadores](../graficas_tesis_v2/ENTREGA.md). `revision-04` es una publicación nueva desde el principal sobre los productos históricos permitidos por el lector:22 figuras/92 archivos, sin eventos ni replay. CSV/JSON y22 PNG coinciden con revision-03; PNG decodificados300dpi y cuatro muestras visuales legibles;22 SVG XML/identidades comprobados, sin render independiente en segundo motor.

Run1000 `simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af` mantiene revisión productora de eventos `290af1f6a3640fb2fe2d33520124f1d9810cb0b1ddc22de4dc2c83b609500ea1`; para `simz1-b53c842bb51f407ea894295d9605c5c3` no se encontró huella productora inequívoca y se registra null. Ambas conservan estado histórico completed/valid, identidades y hashes originales; la aceptación histórica no acredita la física nueva. La comparación entre ellas fue rechazada exit2 por contratos incompatibles. [Procedencia separada de eventos/generador/aceptación](../runtime/diagnostics/consolidacion-20261105/graphics/publication-provenance.json).

Focales previas:71 gráficas PASS0;89 contratos/huellas/compatibilidad PASS0; `SimZ1BlockingStopCheck` completo con JDK17 PASS0 desde el principal. Tras reconstruir `.venv` se repitieron las71 gráficas PASS0 por esa causa. Los logs y códigos están bajo [diagnóstico de consolidación](../runtime/diagnostics/consolidacion-20261105/). Validate integrado recompiló y ejecutó sus fixtures nativas sobre la revisión congelada, incluidas parada bloqueante, C529-A/B/C/D,OD/OSM,pasos temporales,L18,llegada corporal y última parada de buses, seguido secuencialmente por DryRun Run1000; nunca Run.

Preparación oficial: `final-20261104-24h-v3.json/run1000`,1000 no públicos+269 buses,it.0,24h,semilla20261023,servicio2026-10-23,balanced-gateway-v1,L18 revisada y compact-v3. No FirstScaleTrial, aceptación fabricada ni record-trial antiguo. El ensayo usa `automatic_replay_v1`; su Run será exclusivamente manual. [Comandos de preparación, ejecución manual, observación por LaunchId real futuro y aceptación](RUNBOOK_MANUAL_24H.md).

Se conserva Run10K `simz1-21da19695188490e8895ba54924f9ad0` **failed/validating**, LaunchId `7aa4ac6f93554deb9059e394304e162e` failed/verify_result, eventos y diagnóstico del defecto. No se promueven recibos previos de Run10K/110K/masiva. Las tres limitaciones L12 siguen pendientes: L12_029/d0024,L12_020/d0024,L12_015/d0040. No se investigaron ni reconstruyeron. Seguimiento de sólo lectura del cierre: `Get-Content -LiteralPath 'runtime/diagnostics/consolidacion-20261105/final-status.json' -Encoding UTF8`.

## Histórico: cierre focal de la parada bloqueante anterior a consolidación

# Estado histórico: parada bloqueante Run10K corregida y demostrada; corrida histórica inválida

2026-11-05 Guatemala. **Cierre de corrección focal, sin nueva Run10K, Run110K, masiva, Validate completo ni DryRun.** Tampoco se reconstruyeron los 328448 estados visuales L12. Run ID `simz1-21da19695188490e8895ba54924f9ad0`, LaunchId `7aa4ac6f93554deb9059e394304e162e`, carpeta `run-bg10-7aa4ac6f93554deb9059e394304e162e`: manifiesto **failed/validating**, validación invalid; lanzador **failed/verify_result**, exit1. MATSim llegó a 86400 y Maven salió 0; eso no aprobó sus eventos. La cadena de procesos original ya no estaba activa; no se detuvo ningún proceso ni se tocaron servidores del IDE. La entrega gráfica permanece aislada en la copia hermana.

**Causa demostrada: defecto físico del contrato de parada de la adaptación nativa, no falso positivo del auditor.** `QueueWithBuffer.independentTravellingHead` podía saltar un bus con parada bloqueante pendiente al seleccionar un vehículo de otro slot. El seguidor podía quedar en el buffer antes de que `moveQueueToBuffer/TransitQLink.handleTransitStop` comenzara la parada en ese mismo paso; `QLinkLanesImpl.moveBufferToNextLane/moveIndependentOriginalSlot` lo transfería al paso siguiente. Se corrigió también la selección equivalente tras una llegada retenida por cuerpo. La prueba nativa reproduce ese orden interno; los eventos históricos, por sí solos, no identifican la partición vehQueue/buffer ni posiciones continuas.

El parche añade 13 líneas a `QueueWithBuffer.java`: cada búsqueda conserva al bus como barrera FIFO para candidatos posteriores mientras su siguiente parada nativa sea bloqueante en el enlace actual. El propio bus sigue siendo seleccionable si es elegible. La barrera termina por el ciclo nativo de la parada, sin timeout, crédito, movimiento forzado ni estado paralelo. No se cambiaron `QLinkLanesImpl`, auditor Python, señales, prioridades, reservas, flotas, rutas, OD, capacidades, geometría ni `requireApproved()`.

## Incidente y evidencia histórica conservada

Una sola lectura incremental del prefijo original: **2,669,662 eventos** hasta el primero excluido a 23501 s; se conservaron 25,134 registros seleccionados de 22500..23500, máximo 50,000, con orden original incluso dentro de cada segundo. No se releyeron los eventos grandes ni se declaró verificado el sufijo. [Captura e identidad](../runtime/diagnostics/run10k-blocking-stop-20261105/capture/native-sample.json), [secuencia de 763 registros](../runtime/diagnostics/run10k-blocking-stop-20261105/incident-sequence.csv), [contexto y límites](../runtime/diagnostics/run10k-blocking-stop-20261105/audit-incident-context.json).

| Evento | Tiempo(s) | Secuencia original |
|---|---:|---:|
| Bus `ptbus_transmetro_L12_006` entra en `.original` | 23080 | 2462295 |
| Seguidor `z1_05698` entra en `.original` | 23142 | 2491917 |
| Bus llega a Plaza Municipal | 23148 | 2494777 |
| Seguidor sale de `.original` | 23149 | 2495254 |
| Reserva del seguidor se transfiere sin cambiar slot0 | 23149 | 2495255 |
| Seguidor entra en `.lane.0`, mismo enlace | 23149 | 2495266 |
| Segundo seguidor `z1_01073` sale de `.original` | 23152 | 2496654 |
| Bus termina la parada | 23173 | 2506393 |

Enlace `osm_1057486080_1_forward`, cola `osm_1057486080_1_forward.original`, parada `gis_station_41_L12_14106867_part1`: **isBlocking=true**, 25 s, bus 13.5 m, separación 0.10 m y política `scenario_blocking_native_queue_not_microscopic_lane`. La configuración efectiva carga `inputs/transit-weekday/lanes.xml`: original de 3 carriles representados y terminales 2 m; no el snapshot previo de 63.073 m. Bus en slot1; seguidores en slot0; `laneObserved=false` no prueba independencia física ni exime el bloqueo explícito de la cola. No hay señales configuradas en ese enlace o receptor. No hay autorización de nodo del seguidor a 23148..23150: fue un movimiento interno. No se registró salida de enlace del seguidor ni salida de cola del bus hasta 23500. Delante del bus se observaron en `.original` L12_042, z1_07221, L12_001, z1_06533 y z1_00546; detrás, los dos seguidores citados. Esto es membresía por eventos, no coordenadas. [Insumos efectivos y hashes](../runtime/diagnostics/run10k-blocking-stop-20261105/effective-inputs.json).

Auditor original sobre captura: dos infracciones, incluida la exacta del rechazo inicial; antes y después del parche Java mantiene **REJECTED**. [Auditoría inicial](../runtime/diagnostics/run10k-blocking-stop-20261105/audit-historical-capture.json), [auditoría posterior](../runtime/diagnostics/run10k-blocking-stop-20261105/audit-after-fix.json). No equivale a reauditoría del día completo ni modifica aceptación.

## Corrección focal y regresiones

JDK17 y `.venv`, un compilador/escritor por fase, mutex del proyecto. Prueba nueva en `SimZ1BlockingStopCheck`: componentes reales `QLinkLanesImpl`, `QueueWithBuffer`, `TransitQLink` y permanencia de producción 25 s; enlace/asignación afectados, bus 13.5 m, moto 2.1 m, receptor libre y sin señal roja. Conductor proxy sólo para entradas de ruta/parada, sin fabricar eventos históricos; el Controller existente conserva la prueba del ciclo real de agente, eventos y última parada. Las ramas receptoras auxiliares de la fixture son sintéticas y están identificadas como tales.

- Antes, producción intacta: [bloqueante FAIL1](../runtime/diagnostics/run10k-blocking-stop-20261105/before-blocking.log), `RUN10K_BLOCKING_STOP_BYPASS`, parada 15 s/salida 16 s; snapshot nativo incluye seguidor en buffer antes de atender parada. [No bloqueante PASS0](../runtime/diagnostics/run10k-blocking-stop-20261105/before-nonblocking.log).
- Después: [suite de parada PASS0](../runtime/diagnostics/run10k-blocking-stop-20261105/final-blocking.log): bloqueo 15..40 s, intento+1 retenido, circulación posterior, no bloqueante libre y bus elegible en otro slot sin restricción excesiva; caso Controller original también PASS0. Se conservó un intento fallido de preparación del control adicional por reserva de entrada legítima; se corrigió avanzando al predecesor con la cola nativa, sin inyectar espacio ni crédito.
- [36 programas Java PASS0](../runtime/diagnostics/run10k-blocking-stop-20261105/java-regression-results.json): FIFO paralelo/anillo/cabezas, cuerpos/0.10 m/reservas, despeje/llegadas, prioridades y señales, C529-A/B/C/D, OD/OSM, pasos temporales y negativo rojo. Incluye [L18, una expedición nativa acotada PASS0](../runtime/diagnostics/run10k-blocking-stop-20261105/SimZ1L18NativeTripCheck.log); no es reconstrucción visual L12 ni corrida de escala.
- Python: [19 casos de parada PASS0](../runtime/diagnostics/run10k-blocking-stop-20261105/python-blocking.log), [160 relacionados PASS0](../runtime/diagnostics/run10k-blocking-stop-20261105/python-related.log), [9 controles negativos de huellas/mutación/ausencia PASS0](../runtime/diagnostics/run10k-blocking-stop-20261105/protected-after-review.log); 112 fuentes protegidas comprobadas. Paridad nativa/Python OD/OSM registrada en [log](../runtime/diagnostics/run10k-blocking-stop-20261105/od-parity.log).

## Fuentes, preservación y siguientes aprobaciones

Huella final **`70b6886b19cc0b39191f8ab8890fec3e9834fe36c9309865c93161a41bc6290a`**, 736 dependencias; anterior `6982a11c6e6863c1a0674415facf0a3b5b832357389d764bd10e9c0291b19023`. Sólo tres dependencias cambiaron: `QueueWithBuffer.java`, `SimZ1BlockingStopCheck.java` y la expectativa revisada de `python/test_simz1_sequence_contract.py`; además este documento, excluido por el inventario existente. El guard detectó primero el cambio de Java y rechazó el hash anterior; se conservan hashes históricos, justificación y negativos, sin exclusiones nuevas. [Comparación de fuentes](../runtime/diagnostics/run10k-blocking-stop-20261105/source-final.json).

[Preservación PASS](../runtime/diagnostics/run10k-blocking-stop-20261105/preservation-final.json): 313 archivos de corrida/lanzamiento/recibos, 309 con SHA256 y 4 grandes por tamaño/mtime; sin archivos añadidos, borrados o alterados en esos árboles. Los eventos grandes no se rehashearon. Fuentes de las gráficas intactas; sin commit/push/reset/clean. Los builds focales quedaron bajo diagnóstico, sin sustituir la aceptación del flujo oficial.

**La Run10K histórica no puede revalidarse legítimamente con esta corrección física; hace falta QSim nuevo para obtener eventos corregidos.** Los gates existentes rechazan el Validate previo, la recuperación de este rechazo físico y el puente de posproceso del Run1000 anterior: [rechazos esperados](../runtime/diagnostics/run10k-blocking-stop-20261105/approval-gates.json). No se editaron recibos ni estados; tampoco se extendió compatibilidad para admitir cambios físicos.

Pendiente, fuera de esta tarea: congelar la revisión y renovar Validate integrado; DryRun y ensayo Run1000 de la misma revisión por el flujo oficial/manual, con aceptación real; luego nuevo DryRun de `final-20261105-run10k-24h-v5.json/run10000`, y Run10K manual en directorio nuevo, seguido de auditorías completas. Los DryRun10K/110K/189834/220K antiguos no aprueban estas fuentes. No usar `FirstScaleTrial`, recibos editados ni un Run1000 histórico para saltar el gate. Ningún Run queda iniciado o autorizado automáticamente por este cierre.

Seguimiento de sólo lectura fuera del editor: `Get-Content -LiteralPath 'runtime/diagnostics/run10k-blocking-stop-20261105/regression-progress.log' -Encoding UTF8 -Tail 12`. La prueba focal demuestra el mecanismo reparado; no acredita descarga de 10K ni calibración cartográfica. No hubo inspección visual del visor en esta tarea.

## Histórico: entrega gráfica anterior y estado de lanzamiento ya superado

# Estado histórico: gráficas de tesis entregadas en copia aislada; Run10K manual sigue en validación

2026-11-05 19:27 Guatemala. Tarea exclusivamente gráfica, sin QSim, replay L12, Validate, DryRun ni lanzamientos nuevos de Codex. Desarrollo y entrega fuera del repositorio: `C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala-graficas-tesis-v2`. [Entrega, inventario, límites y comandos](../../matsim-guatemala-graficas-tesis-v2/ENTREGA.md). Versión `simz1-graficas-tesis-v2.1`, publicación `graficas_tesis_v2/revision-03`: 15 figuras de Run1000 balanced `simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af` y 7 de la histórica `simz1-b53c842bb51f407ea894295d9605c5c3`, ambas it.0 completed/valid. Cada figura tiene PNG300dpi/SVG/CSV/JSON e índice. Originales y revisiones intermedias conservados. Sin capítulo de Resultados, Discusión ni Conclusiones.

El usuario ya inició LaunchId **`7aa4ac6f93554deb9059e394304e162e`**, Run ID **`simz1-21da19695188490e8895ba54924f9ad0`**, carpeta `run-bg10-7aa4ac6f93554deb9059e394304e162e`; el encabezado anterior quedó desactualizado. Lanzamiento `running / simulation_and_analysis`; manifiesto nativo `running / validating`, validación `pending`. Cadena 26992 → 30072 → 42924 → 8068 comprobada por PID, padre, creación y comando; no se intervino. El cierre del log de MATSim no acredita aceptación nativa ni fin del posproceso. Run10K queda fuera de las figuras entregadas. [Estado comprobado](../../matsim-guatemala-graficas-tesis-v2/evidence/launch-state-final.json), [procesos](../../matsim-guatemala-graficas-tesis-v2/evidence/processes-final.json).

Pruebas: 69 casos nuevos integrados PASS0; tras ajustes finales, 25 espaciales (incluyen dos nuevos) y 14 operativos PASS0. Regresiones existentes: 49 aprobadas inicialmente y tres focales recuperadas PASS0; una fixture nativa omitida porque su evidencia no existe, sin compilar para fabricarla. Dos errores iniciales provenían de insumos ausentes en la copia; el tercero de una importación bajo un mock, comprobado en proceso separado. [Logs y evidencias](../../matsim-guatemala-graficas-tesis-v2/ENTREGA.md). [Consistencia final de 22 figuras PASS](../../matsim-guatemala-graficas-tesis-v2/evidence/delivery-consistency-03.json): SHA256, CSV/JSON exactos, identidades, fuentes, unidades, denominadores, PNG300dpi y SVG.

Conservación SHA256 PASS: 736 fuentes protegidas, 32 recibos, 71 artefactos históricos. Huella preservada **`6982a11c6e6863c1a0674415facf0a3b5b832357389d764bd10e9c0291b19023`**; los ocho módulos/pruebas nuevos siguen exclusivamente en la copia hermana. Este cambio documental no pertenece a la lista protegida. [Conservación](../../matsim-guatemala-graficas-tesis-v2/evidence/preservation-final.json), [huella actual](../../matsim-guatemala-graficas-tesis-v2/evidence/fingerprint-final.txt). Simulador, demanda, rutas, señales, visor, manifiestos nativos, análisis canónicos y recibos intactos. Los eventos grandes no se releyeron; se reutilizaron referencias nativas y productos pequeños verificados.

Sin par A–B formal, se entregan fichas de candidatos sin ruta ni tiempo inventado. Flujo por sección y acumulación por intersección requieren tablas cuantificables; el generador admite paquetes con identidad, hash, cobertura y población explícitos. WAIT nunca se convierte en cola. Las dos Run1000 difieren en configuración, servicios y políticas: su comparación como escenarios equivalentes se rechazó. No hay barras ficticias de preparaciones futuras. CLI individual y comparativa admite cualquier N del manifiesto y selecciones de iteraciones realmente completadas.

Siguiente acción: revisar las figuras. Mantener la implementación aislada mientras haya escritores o se quieran conservar aprobaciones actuales. Integrar los nuevos Python cambia la huella y requiere revisión, pruebas focales, Validate y DryRun de la nueva revisión, secuenciales y sin editar recibos. Ningún Run queda autorizado por esta entrega. Seguimiento de sólo lectura: `Get-Content -LiteralPath 'runtime/launches/7aa4ac6f93554deb9059e394304e162e/state.json' -Encoding UTF8`.

## Histórico: preparación anterior al lanzamiento manual y a esta revisión de gráficas

# Estado histórico: Run10K, Run110K y candidato N=189834 listos para ejecución manual

2026-11-05 Guatemala, cierre de preparación. **Ninguna simulación completa nueva ejecutada por Codex.** No existe una Run10K nueva ni Run ID: `4fdb670675594543bbdd76a8eb68dbde` sigue siendo el intento fallido antes de MATSim y se conserva íntegro. Run1000 de referencia `simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af`, carpeta `run-bg1-9d73afe94f0b438d934e6c7870a24b82`, permanece nativamente completed/valid; no se repitió QSim.

Revisión final **`6982a11c6e6863c1a0674415facf0a3b5b832357389d764bd10e9c0291b19023`**, 736 dependencias. Validate05 Java17 **PASS0**, `balanced-launch-57d99330d7f24d208e4987401bce448b`; inspector/record-trial oficial05 **PASS0**. Todos los DryRun siguientes cerraron0, `run_launch_eligible=true`, `accepted_same_base_and_revision`, identidad de preparación v2 verified y gate posterior oficial aprobado. No crearon población, carpeta de simulación, manifiesto ni replay.

| Escenario | Estado | DryRun aprobado |
|---|---|---|
| V5/run10000, N10000 | READY_FOR_MANUAL_RUN | `b8178068f7044364b775449175409a6e` |
| V3/half, N110000 | READY_FOR_MANUAL_RUN | `6f693c82bf30455dab9cda467019d693` |
| V4/random-full-1, N189834 | READY_FOR_MANUAL_RUN | `892f0111a70d45de8c789aafd01d8a39` |
| Extremo oficial V3/max-test, N220000 | DryRun adicional aprobado; sin Run solicitado | `aede6a37e6a14c428c660eeda45d939e` |

Run10K conserva4400/5500/100; Run110K48400/60500/1100; candidato189834 conserva83527/104409/1898, según redondeo del contrato44/55/1. Cada uno añade176Transmetro+93TuBus. Una iteración0,24h, semilla20261023, servicio2026-10-23, balanced-gateway-v1, L18 revisada y compact-v3. Las126fuentes físicas comparadas siguen intactas; 373archivos nativos y41del intento fallido preservados. El extremo180000 se verificó sólo mediante contrato; no hay selector fijo oficial para su DryRun.

Sorteo real único: candidato `bac5f258d6d24935a24bdde0888a157a`, selección `32fd3de8aa86485586f84c2e0f0348b7`, especificación inmutable `runtime/experiment-selections/32fd3de8aa86485586f84c2e0f0348b7/experiment.json`. El Run manual debe usar ese archivo y el DryRun892f; no volver a sortear. Claim de Run ausente al cierre. Piso100GiB aprobado;178.79GiB disponibles al verificar,32GiB instalados,heap12GiB,SQLite8GiB,scratch4GiB; memoria planning_budget_pass con reserva de crecimiento automático del pagefile. No cambios al SO ni capacidad física demostrada por DryRun.

Causa original resuelta: reserializar la especificación cambió LF→CRLF y su `specification_sha256`; copia binaria exacta y reconstrucción estricta ahora compartidas por generador y DryRun. Se conservaron comparaciones y hashes. Focales99 contratos/gates (22Parte2 incluidas),38 replay/lanzador,43compatibilidad,7huellas y25fixtureJS PASS; Validate05 completo PASS. Validate04 fallido y recibos ec532/975c quedan históricos, sin reutilización. OSM `MALFORMED_SOURCE_NO_EXECUTABLE_MANEUVER` conserva su tratamiento.

Visor `partial-native-v1` implementado: mapa, rutas, itinerarios y navegación disponibles con datos acreditados; cuerpo sin soporte y sus dependientes se ocultan con posición no disponible. **Sin certificación visual completa**: `ptbus_transmetro_L12_029/d0024`, `ptbus_transmetro_L12_020/d0024`, `ptbus_transmetro_L12_015/d0040` siguen pendientes; pueden omitirse más cuerpos dependientes. Sin grafo global ni nuevos checkpoints L12. HTTP real sobre Run1000 de referencia y fixtures aprobaron seis horas05/07/12/17/20/23; no son resultados Run10K. Navegador no disponible, inspección visual real no realizada. No hay gráficas nuevas de Run10K porque todavía no existe esa corrida.

Entrega: [bloques A/B/C y comandos manuales PowerShell5.1](RUNBOOK_MANUAL_24H.md), [informe técnico con campos, pruebas y recibos](../runtime/diagnostics/run10k-manual-20261105/preparation-failure-4fdb/IDENTIDAD-TECNICA.md), [verificación final](../runtime/diagnostics/run10k-manual-20261105/preparation-failure-4fdb/delivery-verification-05.json), [procedimiento del visor de la futura Run10K](../runtime/diagnostics/run10k-manual-20261105/viewer/PROCEDIMIENTO.md). Siguiente acción exclusiva del usuario: iniciar manualmente una sola corrida con su DryRun exacto. No commit, push, reset, clean ni borrado histórico. Seguimiento de sólo lectura de la preparación10K: `Get-Content -LiteralPath 'runtime/launches/b8178068f7044364b775449175409a6e/state.json' -Encoding UTF8`; el Run futuro tendrá otro LaunchId real.

## Histórico: integración, congelación y validaciones de esta preparación

# Estado histórico: visor parcial comprobado; escalamiento congelado para Validate

Hito vigente 2026-11-05: Validate05 **PASS0** `balanced-launch-57d99330d7f24d208e4987401bce448b` (22:27:23Z), huella **`6982a11c6e6863c1a0674415facf0a3b5b832357389d764bd10e9c0291b19023`**. Inspector/record-trial05 oficial de Run1000 **PASS0** (22:29:42Z), sin repetir QSim. DryRun10K nuevo **PASS0** `b8178068f7044364b775449175409a6e`: `run_launch_eligible=true`, `accepted_same_base_and_revision`, prueba de preparación v2 verified con el SHA v5 original; gate posterior oficial también PASS0. Java17, piso100GiB,179.25GiB libres. Sin Run ID, carpeta de simulación ni población creada por ese DryRun.

Sorteo único real: candidato `bac5f258d6d24935a24bdde0888a157a`, selección `32fd3de8aa86485586f84c2e0f0348b7`, **N189834 = 83527 carros + 104409 motos + 1898 camiones**, más269 buses =190103 físicos. Recibo v2 inmutable; semilla de demanda20261023, una iteración24h. Especificación seleccionada `runtime/experiment-selections/32fd3de8aa86485586f84c2e0f0348b7/experiment.json`, sin claim de Run ni nuevo sorteo. En curso: DryRuns secuenciales v3/half110K, v4/random-full-1 y v3/max-test220K, todos con política explícita `native_diagnostic_v1`. No corrida real nueva. Las notas siguientes de freeze04/05 y Validate en curso son hitos históricos superados por este encabezado.

Actualización 2026-11-05 15:59 Guatemala: Validate04 `balanced-launch-3b4569d54ad64799adbaa33f63e7402f` terminó FAIL1 por una fixture JavaScript que extraía `prepareContinuousWindow` sin su nueva dependencia `preparePartialAvailability`. No se cambió producción: la fixture ahora carga el helper real y el modo predeterminado explícito. Sus 25 casos pasan y las 43 pruebas de compatibilidad vuelven a pasar. Nueva huella congelada **`6982a11c6e6863c1a0674415facf0a3b5b832357389d764bd10e9c0291b19023`**, 736 dependencias, 126 físicas intactas; reemplaza a 2561019… únicamente para la validación pendiente. Se reinicia Validate integrado; ninguna aprobación final ni sorteo real todavía. [Freeze05](../runtime/diagnostics/run10k-manual-20261105/preparation-failure-4fdb/source-freeze-05.json). Seguimiento vigente: `Get-Content -LiteralPath 'runtime/diagnostics/run10k-manual-20261105/preparation-failure-4fdb/validate-console-05.log' -Encoding UTF8 -Tail 12`.

2026-11-05 Guatemala. No existe una Run10K nueva: el único Run del selector sigue siendo `4fdb670675594543bbdd76a8eb68dbde`, fallido antes de MATSim, sin Run ID. Los DryRun `ec5321930d3c4afbbbb2e6ec3491b787` y `975c94c53b0a436aadc3d4e806936c2b` son históricos y no aprueban las fuentes actuales. No QSim activo ni nuevas simulaciones iniciadas.

Revisión congelada `2561019a803b0fe1f67e775086afb0f309deda313a25ea8b40230c9c81b4692f`, 736 dependencias. Identidad reparada mediante copia binaria exacta y comparación estricta compartida por generador/DryRun; adaptación explícita de cuotas de transporte v3. Selector `half` conserva 110000 no públicos: 48400/60500/1100 + 176/93 buses; v3 no se modifica. Candidatos v4 con intención exclusiva por UUID y recibo inmutable, sin sorteo real todavía. Política explícita `native_diagnostic_v1` ligada a request/state/recibo y gate; sin omitir aceptación física. 99 pruebas de contratos/identidad PASS, 38 backend/lanzador parcial PASS, 43 compatibilidad PASS. Revisión independiente de scripts sin bypass. Las 126 fuentes físicas comparadas siguen intactas.

Modo `partial-native-v1` integrado: omite cuerpos sin soporte certificado y vecinos dependientes, conserva mapa/rutas/itinerarios y controles; nunca declara certificación visual completa. Tres L12 históricos pendientes; puede haber más cuerpos omitidos por dependencia. HTTP acotado sobre Run1000 existente, sólo referencia del software: seis ventanas 05/07/12/17/20/23 y tres itinerarios PASS0, identidades alteradas rechazadas, servidor cerrado. Duración 129.25s, sin grafo causal/checkpoints globales; validación espacial nativa intacta. Navegador no disponible: inspección visual real no realizada. No hay resultados Run10K nuevos para gráficas o visor.

Siguiente: liberar mutex de edición por su flujo cooperativo; Validate integrado Java17, inspector/record-trial oficial de Run1000 existente, un sorteo nuevo autorizado y DryRuns secuenciales de v5/run10000, v3/half, v4/random-full-1 y v3/max-test. El extremo 180000 sólo se acredita por pruebas de contrato; 220000 dispone de selector oficial. No Run. Evidencias: [informe técnico](../runtime/diagnostics/run10k-manual-20261105/preparation-failure-4fdb/IDENTIDAD-TECNICA.md), [huella](../runtime/diagnostics/run10k-manual-20261105/preparation-failure-4fdb/source-freeze-04.json), [HTTP parcial](../runtime/diagnostics/run10k-manual-20261105/preparation-failure-4fdb/partial-http-smoke-result-04.json). Seguimiento de sólo lectura: `Get-Content -LiteralPath 'runtime/diagnostics/run10k-manual-20261105/preparation-failure-4fdb/validate-console-04.log' -Encoding UTF8 -Tail 12` cuando comience Validate.

## Histórico: integración secuencial del visor parcial

2026-11-05 Guatemala. Prioridad coordinada del usuario: cerrar identidad Run10K, habilitar visualizaci?n parcial segura, despu?s preparar escalamiento. No existe una nueva Run10K nativa: recuperaci?n de request y procesos s?lo identifica intento fallido `4fdb670675594543bbdd76a8eb68dbde`, DryRun hist?rico `ec5321930d3c4afbbbb2e6ec3491b787` y DryRun nuevo `975c94c53b0a436aadc3d4e806936c2b`; ninguno iniciado por Codex como Run. Run ID nuevo inexistente, sin resultados10K v?lidos para an?lisis o visor.

Hito de identidad cerrado sobre huella `1f60abbb17229986756ad2f4d5019498993ca5f5100dc3d1396ff60dd97d1b1d`: Validate `balanced-launch-3f172b34c97446e99c7b8242ebe4db86` PASS0; inspector/record-trial oficial de Run1000 PASS0; DryRun `975c94c53b0a436aadc3d4e806936c2b` PASS0, `run_launch_eligible=true`, misma base/revisi?n. La comparaci?n real de copia/reconstrucci?n se ejecut? y produjo `preparation-identity.json` verified. Java17,180.03GiB libres/100m?nimos, heap12GiB; ninguna poblaci?n ni carpeta de simulaci?n creada por DryRun. Fuentes posteriores del visor requerir?n nueva congelaci?n/Validate/recibos;975c es intermedio, no autorizaci?n de una revisi?n distinta.

Integraci?n protegida por mutex oficial y un escritor principal por turno, tras comprobar ausencia de QSim/otros escritores. Backend `partial-native-v1` integrado: no prepara ?ndice ni grafo causal, conserva integridad/identidad y devuelve soporte corporal pendiente. Pruebas peque?as backend/worker/cache pasan; regresi?n launcher23 PASS despu?s de conservar su llamada predeterminada. Frontend a?n aislado: revisi?n independiente exige ocultar tambi?n vecinos cuya pose dependa de un cuerpo no certificado. No se reconstruyen328448 estados, no nuevas generaciones/checkpoints L12, no se inventan coordenadas. Casos L12 hist?ricos aceptados como limitaci?n y **SIN CERTIFICAR**; auditor?as f?sicas permanecen.

Parte2 contin?a s?lo en staging separado, sin aplicar: v3half110K, pol?tica expl?cita de posproceso, candidatos aleatorios por UUID y gates asociados. Navegador/pipe nativo no disponibles en el entorno; inspecci?n visual real no realizada. Se har?n pruebas HTTP acotadas y se declarar? su alcance sin sustituir Run10K por Run1000.

Evidencias en [carpeta de reparaci?n](../runtime/diagnostics/run10k-manual-20261105/preparation-failure-4fdb/IDENTIDAD-TECNICA.md). Seguimiento de s?lo lectura del hito cerrado: `Get-Content -LiteralPath 'runtime/launches/975c94c53b0a436aadc3d4e806936c2b/state.json' -Encoding UTF8`. Siguiente: integrar/verificar visor parcial, cerrar sus procesos, aplicar Parte2 secuencialmente, congelar y validar revisi?n final; DryRuns manual-ready s?lo con recibos de esa revisi?n. No Run real.

## Hist?rico: alcance PARTE2 antes de coordinar prioridad Run10K/visor

# Estado activo: PARTE 2; no existe Run10K nueva, escalamiento en preparaci?n

2026-11-05 Guatemala. Cambio definitivo de alcance del usuario: preparar Run110K y una candidatura aleatoria180K?220K con DryRun y comandos manuales; ninguna corrida real nueva por Codex. Las tres limitaciones L12 se aceptan como reconstrucci?n incompleta: investigaci?n cerrada en esta fase, certificaci?n visual pendiente; se conservan auditor?as f?sicas nativas y correcciones probadas.

Recuperaci?n ligera de todos los request de selector run10000: s?lo DryRun hist?rico `ec5321930d3c4afbbbb2e6ec3491b787` e intento fallido `4fdb670675594543bbdd76a8eb68dbde`. No hay lanzamiento Run10K nuevo, Run ID, manifiesto ni log nativo. Procesos reales: s?lo pruebas del Validate autorizado y JDT7136, sin QSim de escenario. No hay resultados Run10K v?lidos para gr?ficas o visor.

Validate de reparaci?n `balanced-launch-3f172b34c97446e99c7b8242ebe4db86` sigue activo sobre huella congelada `1f60abbb17229986756ad2f4d5019498993ca5f5100dc3d1396ff60dd97d1b1d`; no se modifican sus fuentes. Cambios PARTE2 se preparan ?nicamente en runtime/diagnostics/run10k-manual-20261105/preparation-failure-4fdb/part2-staging. V3/half tiene N110000 y composici?n48400/60500/1100+269, sin necesidad de modificar la especificaci?n hist?rica. Se adapta expl?citamente el transporte de cuotas CLI; opci?n versionada de diagn?stico nativo ligada a request/DryRun/Run para v3half/max-test y v4. Candidato aleatorio nuevo s?lo despu?s de congelar y validar la revisi?n final; no se ha sorteado N real. Max-test220K dispone de selector oficial;180K se verifica por contrato.

Siguiente: dejar terminar Validate03, revalidar ausencia de corrida y exclusividad antes de integrar; focales, congelaci?n y Validate de la revisi?n final si hay cambios, inspector/record-trial oficial y DryRuns secuenciales10K/110K/v4/max-test. No se ejecutar? Run. Seguimiento de s?lo lectura: `Get-Content -LiteralPath 'runtime/diagnostics/run10k-manual-20261105/preparation-failure-4fdb/validate-console-03.log' -Encoding UTF8 -Tail 10`.

## Hist?rico: reparaci?n de identidad antes del cambio de alcance PARTE2

# Estado activo: identidad reparada; Validate nuevo en curso, sin Run

2026-11-05 Guatemala. Causa corroborada del intento manual `4fdb670675594543bbdd76a8eb68dbde`: copia de especificacion v5 reserializada de 1980 bytes LF a 2030 bytes CRLF; unico campo fatal `specification_sha256`, original `d5f2dc6ea1cbbb66b483c4ddece83c661afcd0302c573faf7e7bc13c59a7157e` frente a copia `fb08ee333c09b9fd44d6d581a53087063c8d10063b5ef25d9052168d705090d4`. Comparador estricto preservado. Copia binaria atomica y reconstruccion real compartidas por generacion y DryRun temporal; DryRun no crea poblacion ni manifiesto.

Fuentes congeladas `1f60abbb17229986756ad2f4d5019498993ca5f5100dc3d1396ff60dd97d1b1d`, 733 dependencias. Focales PASS0: 20 preparacion/contrato, 29 DryRun/v4, 43 compatibilidad, 7 fingerprint y 5 demanda. AST del generador identico salvo helper y llamada de copia; transicion exacta de firma versionada, sin cambios fisicos. Solo JDT7136 presente entre Java/Python al recuperar estado; ningun QSim/replay activo. Se inicia Validate oficial Java17, luego inspector/record-trial sobre la Run1000 existente y DryRun nuevo secuenciales. No Run1000 nueva ni Run10K por Codex; L12 permanece pendiente.

Evidencias: [informe de identidad](../runtime/diagnostics/run10k-manual-20261105/preparation-failure-4fdb/IDENTIDAD-TECNICA.md), [congelacion](../runtime/diagnostics/run10k-manual-20261105/preparation-failure-4fdb/source-freeze-03.json). El DryRun `ec5321930d3c4afbbbb2e6ec3491b787` es historico y no se reutiliza. Seguimiento de solo lectura: `Get-Content -LiteralPath 'runtime/diagnostics/run10k-manual-20261105/preparation-failure-4fdb/validate-console-03.log' -Encoding UTF8 -Tail 12`.

## Historico: reparacion inicial antes de completar DryRun

# Estado activo: Run10K manual falló en preparación; reparación de identidad en curso

2026-11-05 Guatemala. El lanzamiento manual `4fdb670675594543bbdd76a8eb68dbde` terminó código1 antes de publicar manifiesto: `run_id=null`, sin directorio output, log nativo ni QSim. Se conserva íntegra `run-bg10-4fdb670675594543bbdd76a8eb68dbde`. Causa comprobada: el generador reserializó la especificación v5 de1980 bytes con LF como2030 bytes con CRLF; mismo JSON pero distinto SHA. El auditor rechazó correctamente `Experiment selection identity differs`. No lo causó la advertencia OSM ni el error posterior al introducir `elseif` como orden separada en la consola.

Se corrige únicamente la copia de la especificación y su cobertura de pruebas. Los recibos bbcca/ec532 del hito anterior no acreditan una revisión corregida; no reintentar con ellos. No hay autorización para que Codex ejecute Run. La reparación L12 permanece detenida y los tres casos SIN CERTIFICAR. Evidencia de este fallo: [captura](../runtime/diagnostics/run10k-manual-20261105/preparation-failure-4fdb/failure-evidence.json). Seguimiento de solo lectura: `Get-Content -LiteralPath 'runtime/launches/4fdb670675594543bbdd76a8eb68dbde/state.json' -Encoding UTF8`.

## Histórico: entrega Run10K anterior al fallo de preparación

# Estado activo: reparación L12 detenida; Run10K lista para ejecución manual

2026-11-05 Guatemala. Cambio explícito de prioridad: se cierra la reparación costosa L12 y se prepara únicamente un diagnóstico Run10K manual. Quedan revocados los lanzamientos anteriores: Codex no ejecutó Run10K, Run1000 nueva ni masiva; tampoco preparación09 ni otra expansión global. Único Validate integrado PASS0: `balanced-launch-91a46198972d44e78a8483266b39c2f9`, Java17, revisión congelada `bbcca8d739a8dd0258aec12e4949deea5877b73d9ee043b5ca0680d031ff8a58`,731 dependencias. Inspector/record-trial oficial de la Run1000 histórica PASS0; no se repitió QSim. Único DryRun de run10000 PASS0: `ec5321930d3c4afbbbb2e6ec3491b787`, `run_launch_eligible=true`, `accepted_same_base_and_revision`, misma huella y contrato. No existe Run ID nuevo ni carpeta de simulación de ese DryRun.

Preparación08 terminada por solicitud del usuario a18:58:22Z, código1. Se revalidaron PID, creación con precisión nativa, padre, ejecutable y comando de17992→42232→39388. No existe canal cooperativo externo antes de HTTP: se terminó sólo el kernel Node39388; ambos Python y su supervisor cerraron por el flujo de error y limpieza. JDT7136 permanece. La primera guarda rechazó una fecha truncada a milisegundos y no detuvo nada; la segunda usó la identidad completa recién observada. Evidencia en [cierre dirigido](../runtime/diagnostics/run10k-manual-20261105/shutdown/result.json).

Se preservan intentos04–08, capturas, índices y biblioteca parcial sin aprobación. Último progreso08:18435 componentes/generación0; no convergencia ni publicación válida. Se conservan correcciones HOLD, anclas, clasificación, soporte indexado y evaluador por componentes con guardas originales. Las fixtures focales siguen siendo evidencia local; L12_029/d0024, L12_020/d0024 y L12_015/d0040 permanecen **SIN CERTIFICAR**. No se cambian eventos ni física. Run1000 histórica completed/valid preservada,373 archivos originales sin cambio de tamaño/mtime; no nueva lectura completa de eventos/SQLite en este cierre.

Preparación terminada: contrato sucesor v5 fijo `final-20261105-run10k-24h-v5.json/run10000`,10000 no públicos(4400 carros/5500 motos/100 camiones)+176 Transmetro+93 TuBus=10269 vehículos físicos, it.0,24h, semilla20261023 y servicio2026-10-23. OD privados9900:4950/1980/1980/990. Misma base física;126 fuentes comparadas intactas y reconstrucción exacta de huellas c13/290. V3 y v4 se conservan. Las24 pruebas nuevas aprobaron dentro de Validate; fuentes y guards sin rebajas. Aceptación nativa y replay manual posterior separados: `visual_acceptance=not_certified`.

DryRun comprobó180.88GiB libres frente a100 requeridos, memoria `planning_budget_pass`, heap12/SQLite8/scratch4. Sin limpieza ni ajustes OS. Monitor oficial de ese DryRun PASS0. Inventario final19:46:05Z: ningún escritor incompatible; sólo JDT7136 entre Java/Python antes del verificador final.373 archivos nativos originales y manifiesto de Run1000 intactos; aceptación998/1000 y estado histórico del lanzador conservados. No commit, push, reset ni clean.

Siguiente acción exclusiva del usuario: ejecutar manualmente el bloque Run10K del [runbook activo](RUNBOOK_MANUAL_24H.md), en PowerShell externa. Contiene comprobación de aprobación/DryRun, Run separado y observación por el LaunchId real que se creará entonces. [Informe y límites](../runtime/diagnostics/run10k-manual-20261105/RESULTADOS.md), [comprobación final](../runtime/diagnostics/run10k-manual-20261105/delivery-verification.json), [visor posterior](../runtime/diagnostics/run10k-manual-20261105/viewer/PROCEDIMIENTO.md). Cero simulaciones completas iniciadas en esta tarea. Seguimiento de solo lectura: `Get-Content -LiteralPath 'runtime/launches/ec5321930d3c4afbbbb2e6ec3491b787/state.json' -Encoding UTF8` consulta únicamente el DryRun finalizado.

## Histórico: preparación08 antes del cambio de prioridad

# Estado activo: HOLD corregido y probado; preparación08 en curso

2026-11-05 Guatemala. Revisión congelada `b760d0b488b6a7fc197ed38df93e392f14c67d2b262f974fc030344aa083b9ab`,727 dependencias; Validate integrado vigente todavía pendiente. Normal07 terminó naturalmente con código1, sin interrupción. Su paquete exacto fue reproducido antes de corregir `hold_time()`: un intervalo estacionario con salida de parada y ocupación nativa conserva HOLD también cuando termina en `vehicle leaves traffic`. Sólo cambia un candidato entre412 registros; no cambia física, datos ni kernel.

Reproducción después: productor real sobre el universo capturado,23 componentes, generación1 convergente, sin publicar biblioteca histórica. Se preservan412 registros y8 solicitudes; los6 estados ajenos son exactamente iguales y los2 reparados coinciden exactamente con la referencia acotada. Retirar la fase sigue siendo rechazado. Evidencia `runtime/diagnostics/l12-architecture-20261105/renderer/evaluation07/after-comparison.json`. Focales PASS0:71 soporte/contexto,18 pipeline,49 JavaScript,22 integración y42 compatibilidad. El primer wrapper de las22 pruebas falló por tratar stderr de unittest como error de PowerShell5.1; log conservado y ejecución corregida completa0 en `integration-storage-09-02.log`. Freeze `source-freeze-09.json`: reconstrucción exacta c13/290 y126 fuentes Java/escenario comparadas intactas. Estas pruebas no certifican todavía los3 L12 reales.

Tras esas comprobaciones se inició una única preparación08 a18:11:18Z, misma Run1000,it.0, presupuestos originales. PID17992→42232 verificados por creación/padre/comando; revalidar antes de intervenir. Recibo `runtime/replay/launch-99098dbfc5e54e1896e898ddeb39c052.jsonl`, sesión y comando propios en `replay-normal-08-command.json`. El grafo fallido07 permanece preservado, sin sello final ni autoridad para reanudarlo bajo fuentes distintas. No hay preparadores simultáneos ni QSim nuevo. Sin sorteo, trial nuevo, DryRun o masiva; las fases autorizadas seguirán sólo tras certificar los3 L12.

Seguimiento de sólo lectura: `Get-Content -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala\runtime\diagnostics\l12-architecture-20261105\replay-normal-08.log' -Encoding UTF8 -Tail 8`.

## Histórico: fallo natural07 y reparación focal

# Estado activo: fallo HOLD capturado; reparación focal en curso

2026-11-05 Guatemala. `replay-normal-07` terminó naturalmente con código1 a17:52:39Z; no fue interrumpido ni se inició otro preparador. Revisión del intento `b3149116b099790105387c7091624fbd6fa0927f9a5b3ed777a85161681fc0b0`. El cierre de componentes terminó (máximo20 registros por componente); último progreso de evaluación:168775 componentes/generación0,10536.65s. El kernel rechazó después un paquete con `Interpolacion HOLD sin fase corporal certificada`. No hay convergencia ni certificación de los tres L12.

Captura exacta preservada: `runtime/replay/queue-checkpoints/0e5bd4e6e8d94a0296491e5914d7e03e/rejected-g0-eb5ab9f96275b77f8dadb809.packet.json.gz`,191341 bytes,SHA `cb22b076bc6550b1c014c228eaa018e9f43d623d532270266fc0e5c1f9409b10`. Contiene412 registros/8 solicitudes y5544635 bytes expandidos. La reproducción con el kernel de producción intacto y heap192MiB devuelve el mismo rechazo; evidencia y copias previas en `runtime/diagnostics/l12-architecture-20261105/renderer/evaluation07/before.json`. Se investiga la diferencia de clasificación HOLD para un intervalo estacionario con ocupación nativa y final `vehicle leaves traffic`, sin relajar la guarda del renderer. Primero corrección demostrada y regresiones focales; ninguna preparación completa nueva antes de esas pruebas.

Procesos originales11540→37776→2916 ausentes tras la salida natural. A17:55:58Z los373 archivos nativos inventariados conservan tamaño/mtime; manifiesto SHA `750e8c363f8fa8fa2114cc62af39e8194c9be7a935016b0bdda22a7538e31596`,completed/valid, y LaunchId histórico failed/verify_result intactos. Evidencia `native-preservation-after-normal07.json`; no se releyeron eventos ni SQLite nativos. Sin sorteo, trial nuevo, DryRun, Run1000 nueva ni masiva. Las fases de lanzamiento siguen condicionadas a la certificación L12 y los gates oficiales.

Seguimiento de sólo lectura: `Get-Content -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala\runtime\diagnostics\l12-architecture-20261105\replay-normal-07.log' -Encoding UTF8 -Tail 4`.

## Histórico: preparación07 antes del rechazo capturado

# Estado activo: revisión congelada; reconstrucción L12 real07 en curso

Hito de continuación 2026-11-05 Guatemala: se mantiene el mismo intento `replay-normal-07`, sin interrupción ni otro preparador. El cierre de componentes terminó (más de321000 componentes; máximo20 registros por componente). La evaluación de generación0 alcanzó24836 componentes, todavía sin convergencia ni poses L12 certificadas. Máximos observados:512 registros/paquete,15 estados y9490283 bytes decodificados; no se elevaron guardas. Los helpers HTTP/renderer están preparados, aún sin ejecutar, en `runtime/diagnostics/l12-architecture-20261105/renderer/capture-readiness-normal07.json`. Un eventual paquete rechazado se reproducirá desde su captura exacta antes de considerar otra preparación. Tras certificar los tres casos siguen automáticamente Validate vigente, aceptación oficial de la Run1000 compatible, sorteo único, DryRun del mismo N y una sola masiva visible autorizada.

2026-11-05 Guatemala. Revisión congelada `b3149116b099790105387c7091624fbd6fa0927f9a5b3ed777a85161681fc0b0`,727 dependencias, todavía sin Validate integrado vigente. La guarda agregada cuenta índice, grafo, journals y temporales FILE propios, con comprobaciones antes/después de commits y durante SQL. Informa el máximo observado, sin afirmar una cuota estricta del sistema operativo. Presupuestos originales conservados.

Retención incremental probada: antes de calcular g se verifican los resultados y las restricciones de g−1; se conservan sus hashes/Merkle y mapas HMAC, se retiran únicamente los envoltorios ya consumidos y se archivan generaciones anteriores mediante sellos encadenados. La escritura usa páginas acotadas y cursor estable, sin VACUUM. Una cadena sintética del kernel real converge en generación4: todos los estados de las cinco pasadas coinciden exactamente con el control sin retención. Ocho corrupciones son rechazadas. El sellado público conserva una frontera Merkle privada entre commits; una sustitución con hashes públicos recalculados falla. No cambia física ni eventos.

Pruebas focales PASS0:38 soporte/guardas,45 grafo/confianza/scheduler/pipeline,22 integración/biblioteca y42 compatibilidad. Publicación real del kernel para258 estados/129 raíces, todas verificadas. Evidencias bajo `runtime/diagnostics/l12-architecture-20261105`: `resource-guard-probe/RESULTADOS.md`, `v4/RETENCION-Y-GUARDA.md`, `integration-storage-08.log`, `integration-revalidate-08.log`, `renderer/sealing-commit-repro-03/result.json` y `source-freeze-08.json`. La compatibilidad reconstruye exactamente c13/290 sin excluir dependencias de la huella normal. Estas fixtures no certifican todavía los tres L12 históricos.

Preparación normal07 iniciada 2026-11-05T14:21:34Z sobre la misma Run1000 `simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af`,it.0. Recibo `runtime/replay/launch-36fe3e6abe734d74b4c0b8d03650d246.jsonl`; procesos11540→37776 contrastados por creación/padre/comando, revalidar antes de intervenir. Comando y log `replay-normal-07-command.json`/`replay-normal-07.log` en la carpeta diagnóstica. Único preparador; fuentes/tests congelados. La preparación06 interrumpida permanece incompleta, con causa y grafo conservados.

Run1000 mantiene completed/valid; LaunchId histórico failed/verify_result conservado. A 14:05:09Z los373 archivos inventariados mantienen tamaño/mtime y el manifiesto conserva SHA `750e8c363f8fa8fa2114cc62af39e8194c9be7a935016b0bdda22a7538e31596`, sin releer eventos/SQLite completos. No hay sorteo real, trial nuevo, DryRun ni Run nuevos. No se abrió PowerShell de simulación. Siguiente acción: completar convergencia y verificar los tres casos reales por HTTP/renderer, incluidos vecinos no reconstruibles; después Validate y gates oficiales.

Seguimiento sólo lectura: `Get-Content -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala\runtime\diagnostics\l12-architecture-20261105\replay-normal-07.log' -Encoding UTF8 -Tail 12`.

## Histórico: reparación de almacenamiento anterior a la preparación07

# Estado activo: reparación de almacenamiento auxiliar; masiva pendiente

2026-11-05 Guatemala. La preparación06 del replay se cerró intencionalmente a 2026-11-05T13:50:24Z, código1, antes de publicar. Había evaluado20,741 componentes de generación0, sin otro rechazo de poses: máximo512 registros/paquete,15 estados,9,490,283 bytes expandidos y heap Node114,666,288 bytes observados. No equivale a convergencia ni acredita aún los tres L12. Grafo parcial conservado en `runtime/replay/queue-checkpoints/d918b99ff90d443ea5b38eac3f0383a0`; fuentes del intento `8e47dafe72e616143ce253707c7d32697cf9763cc915ee1d1bbc31e2a1d86c2a`.

Causa de esta intervención: una fixture SQLite pequeña demostró que `disk_guard()` aceptaba557,056 bytes de base más554,568 bytes de journal con presupuesto589,824 bytes. La guarda medía sólo la base. Es un defecto del almacenamiento auxiliar nuevo, no una violación observada en la corrida histórica. Evidencia `runtime/diagnostics/l12-architecture-20261105/resource-guard-probe/journal-before.json`. Se implementan controles del directorio propio y temporales antes/después del commit, más retención verificada de generaciones anteriores; no se elevan presupuestos ni se cambia física.

Interrupción dirigida sólo al evaluador Node28276, tras comprobar creación2026-11-05T13:15:21.063Z, padre4636 y comando completo. El preparador consumió el cierre y terminó1; Python4636/30108 y Node28276 ausentes en CIM posterior. Evidencia `replay-normal-06-interruption.json`, `replay-normal-06-result.json` y log bajo `runtime/diagnostics/l12-architecture-20261105`. El error final de pipe es consecuencia de esta interrupción explícita, no un nuevo defecto de geometría. No se detuvo ninguna simulación.

Run1000 preservada: `simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af`, it.0; manifiesto nativo completed/valid y LaunchId histórico failed/verify_result conservados. No hay selección real de N, trial nuevo, DryRun ni Run nuevos. El Validate anterior sobre88d permanece histórico y no acredita esta revisión. La autorización de una masiva sigue condicionada a todos los controles de la tarea.

Siguiente acción: probar las guardas y retención con equivalencia de varias generaciones y negativos, integrar/congelar y completar la reconstrucción real; después verificar poses/vecinos/itinerarios y renovar Validate/gates. Un escritor por archivo: arquitectura soporte/guardas, v4 grafo/confianza/retención, principal integración/documentación. Ningún lector histórico activo. Seguimiento sólo lectura: `Get-Content -LiteralPath 'runtime/diagnostics/l12-architecture-20261105/replay-normal-06-interruption.json' -Encoding UTF8`.

## Histórico: preparación06 anterior a la interrupción

# Estado activo: paquete real corregido y comparado; preparaci?n06 en curso

2026-11-05 Guatemala. Fuentes congeladas `8e47dafe72e616143ce253707c7d32697cf9763cc915ee1d1bbc31e2a1d86c2a`, 727 dependencias, sin Validate vigente todav?a. El fallo exacto de05 se reprodujo con sus320 registros y8 solicitudes: con certificado privado de paradas, el clasificador emit?a `shared_upstream_without_blocking_facility`, que el productor no admit?a para la exclusi?n estricta sin HOLD/ocupaci?n. Se a?adi? esa combinaci?n s?lo con certificado vigente y enlace fuera del conjunto completo de paradas bloqueantes; las dem?s guardas se conservan.

Gate local real: el paquete original sigue rechazado; el derivado por SupportIndex/QueueContext/CausalGraph conserva320 observaciones+Trips/carriles/fases/c?psulas/releases y elimina una solicitud de ancla mediante certificado, sin selecci?n especial por ID. Las siete restantes producen estados completos EXACTAMENTE iguales a la referencia, Node192MiB. Dos aristas entrantes BASE explican la solicitud; ninguna otra rama la introduce. Fixture expl?citamente diagn?stica, no publicaci?n/aceptaci?n nativa. Evidencia: `runtime/diagnostics/l12-architecture-20261105/evaluation-05/RESULTADOS.md`, `renderer/rejected-normal05-derived-comparison.json`, `renderer/rejected-normal05-provenance-binding.json` y `runtime/diagnostics/cap05-02/exclusion-certificate.json`.

Pruebas: before espec?fico1FAIL conservado; 68 Python de soporte/grafo/contexto y14 pipeline PASS0; integraci?n principal20PASS0, compatibilidad42PASS0. Fuente/compatibilidad en `source-freeze-07.json`. JS/CJS de producci?n no cambiaron en esta correcci?n. Comparador auxiliar tuvo OOM al formatear diferencias compactas/inline; se conserv? y se corrigi? s?lo el diagn?stico mediante hashes can?nicos por registro/estado, sin aumentar heap ni guardas. Preservaci?n nativa reciente373/373 tama?os/mtime iguales.

Preparaci?n normal06 iniciada 2026-11-05T13:10:27Z, misma Run1000 `simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af`, it.0. Recibo replay `runtime/replay/launch-705ecc5c4b624df08aaeb122f7793d20.jsonl`; procesos30108?4636 contrastados porcreaci?n/padre/comando, revalidar antes de intervenir. Comando e identidad en `runtime/diagnostics/l12-architecture-20261105/replay-normal-06-command.json`. Todos lectores/Node diagn?sticos cerrados, ?nico preparador nativo. No MATSim, sorteo, record-trial, DryRun ni Run nuevos. Las tres poses L12 a?n pendientes de aceptaci?n completa.

Siguiente acci?n: comprobar evaluaci?n/convergencia y los tres casos reales v?aHTTP/renderer antes de Validate y gates. Seguimiento de solo lectura: `Get-Content -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala\runtime\diagnostics\l12-architecture-20261105\replay-normal-06.log' -Encoding UTF8 -Tail 12`.

## Hist?rico: rechazo05 y preparaci?n previa conservados

# Estado activo: preparaci?n05 rechazada; reproducci?n desde paquete exacto

2026-11-05 06:56 Guatemala. La preparaci?n05 termin?1 en generaci?n0, tras64 componentes, con `Estado de soporte sin entrada representable`. Los componentes del grafo cerraron dentro de la guarda (m?ximo20 observado); la correcci?n focal de m?viles sin ancla no resolvi? todav?a el paquete real. No se public? biblioteca ni HTTP y no est?n certificados los tres L12. Fuentes del intento: `bad503def98743bdfade7ed041add15668ec1a415f8d631e3fee1bf85a67d1f1`, 727 dependencias, sin Validate vigente.

La captura autom?tica conserva el paquete EXACTO rechazado: `runtime/replay/queue-checkpoints/c739112bba37457b9b78916deac86bc9/rejected-g0-796846d83218da72664824e6.packet.json.gz`, 180715 bytes comprimidos, 4682318 bytes expandidos, ocho solicitudes. Incluye interpolate89706 y siete solicitudes adicionales; no atribuir todo el rechazo a un candidato sin reproducir el lote completo. Grafo y resultados parciales preservados, sin promover su confianza. Log/c?digo: `runtime/diagnostics/l12-architecture-20261105/replay-normal-05.log` y `replay-normal-05-result.json`.

Siguiente acci?n: reproducir la captura completa y probar por qu? la exclusi?n focal no se aplica en el productor real. Arquitectura es ?nico lector auxiliar; renderer usa la captura JSON; ninguna lectura nativa adicional autorizada por defecto para este diagn?stico. No reexpandir el grafo ni preparar otro intento antes de PASS del paquete exacto y controles negativos. Run1000 y sus eventos conservados; sin QSim, sorteo, record-trial, DryRun ni Run nuevos.

Seguimiento de solo lectura: `Get-Content -LiteralPath 'runtime/diagnostics/l12-architecture-20261105/replay-normal-05.log' -Encoding UTF8 -Tail 12`.

## Hist?rico: preparaci?n05 y correcci?n focal previa conservadas

# Estado activo: soporte m?vil corregido; preparaci?n real05 en curso

2026-11-05 Guatemala. Revisi?n congelada `bad503def98743bdfade7ed041add15668ec1a415f8d631e3fee1bf85a67d1f1`, 727 dependencias, sin Validate integrado vigente todav?a. La solicitud interpolate89706 del intento04 fue reproducida: m?vil sin HOLD y sin ocupaci?n representable que permanece visible activo, pero no restringe BASE/FINAL/FIFO. Se excluye s?lo de restricciones de ancla mediante prueba de fuente y raz?n exacta; su registro, cuerpo activo y vecinos geom?tricos permanecen. HOLD, ocupaci?n v?lida, ausencia gen?rica o evidencia incompleta conservan dependencias. Se agreg? captura acotada de futuros paquetes rechazados, sin reemplazar el error original ni publicar resultados parciales.

Pruebas: 68 Python de contexto/grafo/soporte; 43 puente/pipeline +una prueba nueva de captura; 25 JS causales; integraci?n principal20PASS0 y compatibilidad42PASS0. Reproducci?n activa y comparaci?n con seguidor en `runtime/diagnostics/l12-architecture-20261105/renderer/interpolate-inactive-01.json`; informe `scc-evaluation-04/RESULTADOS.md`, hashes en `source-freeze-06.json` y `v4/inactive-review.json`. La reconstrucci?n completa c13/290 sigue igual y las fuentes f?sicas no cambian. Ninguna prueba focal certifica todav?a las tres poses hist?ricas.

Preparaci?n normal05 iniciada 2026-11-05T12:37:04Z sobre la misma Run1000 `simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af`, it.0. Recibo replay `runtime/replay/launch-f9cf225649f94f8d80b1069e9aacc1e7.jsonl`; comando/identidad en `runtime/diagnostics/l12-architecture-20261105/replay-normal-05-command.json`. Procesos propios45664?40040 contrastados por creaci?n/padre/comando; revalidar antes de intervenir. Un lector preparador, sin lectores diagn?sticos concurrentes. No MATSim, sorteo real, record-trial, DryRun ni Run nuevos. El intento04 termin?1 y sus fuentes/resultado/grafo permanecen preservados.

Siguiente acci?n: verificar evaluaci?n/convergencia, preparar HTTP y comprobar los tres L12 reales antes de renovar Validate y gates oficiales. Seguimiento de solo lectura: `Get-Content -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala\runtime\diagnostics\l12-architecture-20261105\replay-normal-05.log' -Encoding UTF8 -Tail 12`.

## Hist?rico: rechazo de evaluaci?n04 conservado

# Estado activo: componentes L12 cierran; evaluaci?n de soporte rechazada

2026-11-05 06:20 Guatemala. Preparaci?n normal04 termin? c?digo1 durante evaluaci?n generaci?n0: `Estado de soporte sin entrada representable`. Antes cerr? los componentes sin exceder la guarda; ?ltimo progreso322304 componentes y m?ximo20 registros. Tras64 componentes evaluados: m?ximo424 registros/8 estados por paquete, heapJavaScript93081096B, RSS153550848B, solicitud expandida m?xima6038545B. No hay biblioteca publicada ni HTTP listo; estos hitos no certifican las tres poses L12.

Fuentes del intento `286fb2e49f44a3bd37765335b320bdb52cb00ef676a3f9dd4caecac3fb85737e`, 727 dependencias, todav?a sin Validate integrado vigente. Grafo cerrado `runtime/replay/queue-checkpoints/042b6c7a870446368c4a5c3c45e9fa39/library.sqlite`; ?ndice `runtime/replay/queue-support/7b3d43bbbe4a4f066ea58afdf15e90fc6abe2992cf0f63995c4c48d95a73e462.sqlite`. Log y c?digo en `runtime/diagnostics/l12-architecture-20261105/replay-normal-04.log` y `replay-normal-04-result.json`. Python43164 y Node30060 salieron naturalmente tras el rechazo; no MATSim ni masiva. Sin sorteo, aceptaci?n nueva ni DryRun.

Siguiente acci?n autorizada: recuperar exclusivamente el paquete y la solicitud que fallan desde el grafo cerrado, con lectura nativa indexada acotada si es necesaria, y distinguir una ausencia sem?ntica de soporte geom?trico incompleto. Un ?nico lector asignado a arquitectura; renderer revisa el c?lculo. No repetir expansi?n, ?ndice ni eventos para este diagn?stico. No convertir una entrada ausente de un paquete parcial en ausencia universal. Seguimiento: `Get-Content -LiteralPath 'runtime/diagnostics/l12-architecture-20261105/replay-normal-04.log' -Encoding UTF8 -Tail 12`.

## Hist?rico: preparaci?n04 y revisi?n anterior conservadas

# Estado activo: clasificador causal integrado; preparaci?n real 04 en curso

2026-11-05 Guatemala. Fuentes congeladas en `286fb2e49f44a3bd37765335b320bdb52cb00ef676a3f9dd4caecac3fb85737e`, 727 dependencias, todav?a sin Validate integrado para esta revisi?n. El renderer de producci?n clasifica grupo/orden/elegibilidad antes de construir el grafo, usando el evento nativo exacto en el HOLD; clasificaci?n y pose son contratos distintos. El grupo visual y orden se conservan separados del ordinal nativo. Casos ausentes, no elegibles o sin cobertura probada mantienen la alternativa conservadora. No se elevan guardas.

La partici?n auxiliar anterior se recuper? completa: 331220/331220 estados; ?nico SCC excesivo 131662, 577 registros. Su proyecci?n con el evento terminal52607/HOLD52611 conserva el FINAL real, elimina 73 relaciones no consumidas y reduce el m?ximo a tres registros. Los dem?s componentes tienen m?ximo253. No es todav?a certificaci?n de las tres poses. Se retir? expresamente la ausencia FINAL anterior, que utilizaba un extracto sin el evento de carril interno. Evidencia: `runtime/diagnostics/l12-architecture-20261105/scc-overflow-03/RESULTADOS.md`, `partition-verification.json` y `architecture-freeze-06.json`.

Pruebas: 88 focales de arquitectura y controles conservadores posteriores; 41 puente/pipeline; 41 kernel +23 causales JS y12 estados reales peque?os equivalentes; integraci?n principal20PASS0 y compatibilidad42PASS0. Revisiones independientes y hashes en `v4/classification-review.json`, `renderer/evidence-current.json` y `source-freeze-05.json`. La compatibilidad reconstruye c13/701 y nativa290 completas, con fuentes f?sicas conservadas; no publica ensayo ni copia recibos hist?ricos.

Preparaci?n normal04 iniciada 2026-11-05T11:58:42Z. Run1000 exclusiva `simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af`, it.0; recibo replay `runtime/replay/launch-960db0c327f14ff386e1bd6da17bc170.jsonl`. Comando e identidad en `runtime/diagnostics/l12-architecture-20261105/replay-normal-04-command.json`; procesos propios contrastados37980?43164 (revalidar antes de intervenir). Un preparador nativo, todos los lectores auxiliares anteriores cerrados. No hay QSim, sorteo, aceptaci?n nueva, DryRun ni Run. El intento03 termin? naturalmente1 y permanece ?ntegro; su helper cuadr?tico se detuvo con identificaci?n verificada, se conserv? y se complet? mediante cursor e ?ndices en una copia diagn?stica nueva.

Siguiente acci?n: terminar preparaci?n normal y verificar posiciones/continuidad/vecinos/reproducci?n de los tres L12 antes de Validate y gates oficiales. Seguimiento de solo lectura: `Get-Content -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala\runtime\diagnostics\l12-architecture-20261105\replay-normal-04.log' -Encoding UTF8 -Tail 12`.

## Hist?rico: rechazo03 y rectificaci?n de su evidencia

# Estado activo: preparaci?n L12 03 rechazada; nuevo componente en reparaci?n

2026-11-05 05:33 Guatemala. La preparaci?n normal 03 termin? c?digo 1 por `Reciprocal causal component exceeds original record guard`. ?ltimo progreso: 131584 componentes, m?ximo previo 227 registros; la expansi?n lleg? a 331008 estados registrados con 164 cargas nativas, 832459 bytes decodificados acumulados y 84 registros directos m?ximos. No se ampli? ninguna guarda. No hay biblioteca publicada, HTTP listo ni aceptaci?n de los tres L12. La correcci?n focal anterior sigue probada, pero no cierra el grafo completo.

Revisi?n congelada del intento: `33f98b3166abbb76835ab1101e15ff0558a2d967fe1fbeb2f91c74c41bd68f43`, 727 dependencias, sin Validate vigente. Grafo preservado `runtime/replay/queue-checkpoints/0662f0a55cdd4b9c81cff614dd6b1fa0/library.sqlite`; ?ndice verificado `runtime/replay/queue-support/a638595ca79c1097f046957ed4b90ddc6001d3e818335074065905e4593b30b5.sqlite`. Evidencias en `runtime/diagnostics/l12-architecture-20261105/replay-normal-03.log` y `replay-normal-03-result.json`. Preparador termin? naturalmente; no QSim iniciado. ?ltima preservaci?n: 373/373 archivos nativos mantienen tama?o y mtime, sin rehash completo de eventos.

Correcci?n de evidencia a las 05:37 Guatemala: el componente exacto es 131662, 746 estados/577 registros. El FINAL492090 conserva 134 relaciones porque el evento real a 52607 cambia a carril terminal antes del HOLD52611. El extracto focal anterior s?lo ten?a eventos al inicio/fin y omit?a esta transici?n. Por tanto su afirmaci?n de una ausencia FINAL no acredita el estado real; queda retirada, aunque las 19 ausencias FIFO dependen de otra condici?n. La guarda productiva s? consult? el HOLD exacto y rechaz? correctamente esa ausencia. Dos consultas indexadas, siete filas/985 bytes, conexi?n cerrada y SQLite intacto: `scc-overflow-03/hold-lane-native.json`. Se implementar? clasificaci?n efectiva de grupo/orden temporal del renderer para este tipo de caso, sin eliminar el FINAL v?lido ni inventar su ancla.

Siguiente acci?n autorizada: recuperar el componente exacto desde el grafo cerrado, distinguir relaciones conservadoras restantes de un componente rec?proco genuino e implementar una reconstrucci?n acotada fiel. Un ?nico lector auxiliar asignado al subagente de arquitectura; no otra lectura nativa para este diagn?stico. No hay sorteo, record-trial, DryRun ni Run nuevo. Seguimiento: `Get-Content -LiteralPath 'runtime/diagnostics/l12-architecture-20261105/replay-normal-03.log' -Encoding UTF8 -Tail 12`.

## Hist?rico: preparaci?n 03 antes de su rechazo

# Estado activo: arquitectura L12 corregida; preparaci?n real 03 en curso

2026-11-05 Guatemala. Se corrigieron dependencias conservadoras que no son consumidas por las fases BASE/FINAL del renderer y se a?adi? prueba privada de ausencia de ocupaci?n, vinculada a geometr?a, carril, horario nativo completo, SQLite e identidad. Una ausencia sigue sin ancla ni pose; nunca aprueba por s? misma el contexto. Fuentes congeladas en `33f98b3166abbb76835ab1101e15ff0558a2d967fe1fbeb2f91c74c41bd68f43`, 727 dependencias, todav?a sin Validate integrado para esta revisi?n. El PASS `88d42?` anterior permanece hist?rico.

El componente que fall? ten?a 1541 estados y 726 registros, no una carencia de memoria demostrada del renderer. Se acreditaron 20 fases sin ocupaci?n sobre seis observaciones nativas de dos veh?culos; el horario completo tiene 110 paradas, 62 bloqueantes en 56 enlaces, ninguna en los tres enlaces afectados. Las proyecciones diagn?sticas conservan componentes rec?procos de hasta tres registros. Esto no sustituye todav?a la prueba de las tres poses L12. Evidencias: `runtime/diagnostics/l12-architecture-20261105/scc-overflow/architecture-freeze-05.json`, `phase-absence-consumer-projection.json`, `renderer/six-absences-kernel-01.json` y `v4/facility-review.json`.

Pruebas de esta correcci?n: 84 Python de arquitectura; 45 Python de puente/pipeline/biblioteca; 33 kernel y 23 causales JavaScript; 12 estados reales peque?os equivalentes. Integraci?n principal: 43 pruebas aprobadas y un error auxiliar por nombre de m?dulo inexistente, conservado en `integration-final-04.log`; m?dulo correcto ejecutado aparte, 42 PASS0 en `integration-revalidate-04.log`. No se atribuye PASS al comando que termin? 1. La pol?tica de compatibilidad exacta reconstruye c13/701 y la revisi?n nativa 290, conserva las fuentes f?sicas; no publica aceptaci?n ni altera recibos.

La preparaci?n normal 03 usa la misma Run1000 `simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af`, it.0, manifiesto completed/valid y SHA `750e8c363f8fa8fa2114cc62af39e8194c9be7a935016b0bdda22a7538e31596`. Recibo de replay `runtime/replay/launch-81a31477208b46fa9ee9e3f47bd3a27e.jsonl`; comando y proceso en `runtime/diagnostics/l12-architecture-20261105/replay-normal-03-command.json`. No es LaunchId de simulaci?n. No hay sorteo real, inspector nuevo, record-trial, DryRun ni Run. No se ha iniciado MATSim. Guardas originales conservadas; un lector nativo del preparador, subagentes sin lectores.

Siguiente acci?n: comprobar preparaci?n normal, identidad y posiciones/vecinos/continuidad/reproducci?n de los tres casos, antes de renovar Validate y los gates de ejecuci?n. Seguimiento de solo lectura: `Get-Content -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala\runtime\diagnostics\l12-architecture-20261105\replay-normal-03.log' -Encoding UTF8 -Tail 12`.

## Hist?rico: Validate anterior y rechazo del componente conservados

# Estado activo: Validate PASS; componente L12 excede guarda y sigue en reparación

2026-11-05 04:19 Guatemala. Validate oficial Java17 terminó código 0, recibo `runtime/validation/balanced-launch-1e72e61099714dca83df8a12743eb5de`, para la revisión `88d42e6e81a7b4f3c44933cfea672696426496ef323a5c8e268078cda6e11bdb` (727 dependencias). La preparación real de los tres L12 terminó código 1: `Reciprocal causal component exceeds original record guard`. No se elevó el límite de 512 registros ni se publicó una biblioteca incompleta. Este PASS de Validate no acredita las posiciones L12 ni autoriza todavía la masiva.

El grafo externo cerró su expansión y alcanzó la fase de componentes recíprocos. Último progreso de expansión: 406016 estados; máximo directo observado 84 registros. Último progreso de componentes: 127488, máximo previo 336 registros; el componente siguiente que activó el rechazo requiere medición específica. Grafo preservado en `runtime/replay/queue-checkpoints/be03c44bfd264f86a5352e8ecf3139f3/library.sqlite`, con índice v2 cerrado conservado. No se confunde el volumen acumulado decodificado con memoria residente. Evidencias: `runtime/diagnostics/l12-architecture-20261105/replay-normal-02.log`, `replay-normal-02-result.json`, `validate-01.log` y `validate-01-result.json`.

Los procesos de ambas fases ya cerraron: se comprobó ausencia de los PID propios 35180/39544/41376/43400 después de obtener los códigos. No hay HTTP nuevo listo, inspector nuevo, `record-trial`, sorteo real, DryRun ni Run. La Run1000 original conserva su identidad y evidencia; no hubo cambio físico ni de eventos. Siguiente acción autorizada: diagnosticar el componente exacto usando el grafo/índice conservados e implementar su reconstrucción acotada con equivalencia y negativos; cualquier cambio posterior de fuentes requiere nueva congelación y validación antes del lanzamiento. No repetir el escaneo nativo para este diagnóstico.

Seguimiento de solo lectura: `Get-Content -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala\runtime\diagnostics\l12-architecture-20261105\replay-normal-02.log' -Encoding UTF8 -Tail 10`.

## Histórico: preparación y validación antes del rechazo real

# Validate y reconstrucción real L12 en curso; sin masiva

2026-11-05 Guatemala. Nueva tarea autorizada: reparar los tres contextos L12 sobre la Run1000 preservada, completar v4 y validar antes de iniciar una única masiva aleatoria en PowerShell externa visible. La autorización de Run está condicionada a todos los controles; todavía no se sorteó N, no existe LaunchId nuevo ni QSim iniciado. Una Run1000 nueva sólo se usará si el gate o un cambio físico lo exige.

Recuperación comprobada: HEAD `211d7f7ee1232670df29c194468c5e5397e4910f`, 709 dependencias iniciales, cambios locales v4 y documentos preservados. Run `simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af`, LaunchId histórico `9d73afe94f0b438d934e6c7870a24b82`, it.0: manifiesto `completed/valid`, SHA `750e8c363f8fa8fa2114cc62af39e8194c9be7a935016b0bdda22a7538e31596`; estado histórico `failed/verify_result` intacto. Inventario de 373 archivos nativos. Procesos comprobados por PID/creación/padre/comando: sin QSim ni replay activo; Java del IDE preservado. No se reutilizan recibos anteriores para la revisión nueva.

Principal: integración, compatibilidad exacta, documentación y fases secuenciales. Subagentes: índice causal L12 (único lector SQLite histórico), renderer/pruebas y contrato v4. Índice externo implementado: 808802 filas procesadas incrementalmente, sin modificar SQLite nativo. Los intentos 01–03 de consulta siguen incompletos y preservados. El grafo persistido posterior cierra 112433 estados y 1535518 relaciones en 63147 componentes; mantiene 16732 componentes cíclicos, máximo 13 observaciones distintas por componente. Es completitud de dependencias, todavía no certificación de las tres posiciones.

Reconstrucción implementada mediante fases base/final/FIFO, generaciones síncronas de liberación y cápsulas autenticadas. La integración conserva identidad, geometría, anclas y referencias de soporte; rechaza cápsulas alteradas incluso si se recalcula su hash. Los paquetes mantienen 512 registros y 64 MiB como guardas. La separación entre restricciones causales y observaciones geométricas conserva los 248 registros de una captura real cerrada, reduce las entradas evaluadas de 237 a 21 y reproduce exactamente sus 12 estados. El pipeline completo conserva equivalencia geométrica dentro de 1e-7 m (máxima diferencia 2.84e-14 m). Esos casos cerrados son controles, no sustituyen los tres intervalos pendientes.

Revisión independiente: una fixture sintética demostró que el radio espacial del enlace/corredor actual omitía un HOLD que restringía el cuerpo desplazado hacia un corredor anterior por `releaseSetback`. El productor cerraba/publicaba ese grafo pero su ancla difería 2 m del renderer completo; esa completitud semántica fue rechazada. Corregido mediante índice v2 de soporte observado contiguo para ambos cuerpos, incluidas extensiones nativas, y bins temporales con filtro exacto. Se conservan `v4/checkpoint-spatial-before.log` y `v4/spatial-release-review`; los nuevos positivos, exclusiones justificadas y negativos de alteración pasan. El índice 02 y grafo 07 son prototipos históricos, no acreditan la corrección actual.

Correcciones adicionales verificadas: el loader exige todas las cápsulas declaradas por un contexto convergente; recetas y liberaciones tienen autenticación privada durante la producción; el camino indexado pequeño conserva la liberación anterior para BASE/FINAL y la ancla BASE propia al interpolar. Se preservan sus fallos previos y controles negativos. La unión de componentes usa una cota de bytes comprobada y el puente comprueba de nuevo el tamaño exacto. Índice y grafo comparten 4 GiB auxiliares; no se duplicó ese presupuesto por archivo.

Congelación d2a83e7a99d7bb444d185f6ed8be9ce93ad757fea8c128ff6d376d019883e218 preservada en `source-freeze-02.json`, 727 dependencias, **sin Validate integrado**. Se revisó la política exacta de compatibilidad y reconstruyó c13/290; 236 fuentes e insumos físicos conservan SHA. Esa congelación queda pendiente de sustitución por la corrección posterior del vínculo entre raíz externa e interna de biblioteca; no acredita la fuente actual. Política anterior y congelación d5f690 intermedia preservadas. No se alteraron recibos nativos ni se publicó trial.

Preparación normal 01: inició 2026-11-05T09:26:20Z y produjo índice v2 completo de 427208704 bytes, conservado en `runtime/replay/queue-support/0e1751c95d548880d7c9837a2024a3005e0a71cdb4f1d8bf7952f5e0ba69ebc7.sqlite`. Se detuvo únicamente su Python 3796 tras comprobar PID/creación/padre/comando, antes de evaluar cápsulas, por una prueba que aceptaba mezclar la raíz externa de una respuesta con otra raíz interna. Loader corregido; positivo/negativo por `validateRecords` pasan. Interrupción diagnóstica, no QSim: `replay-normal-01-interruption.json`, salida nativa 4294967295, grafo incompleto preservado. Primera guarda de interrupción rechazó una comparación por enumeración de arrays PowerShell; no detuvo procesos hasta corregirla y verificar de nuevo las mismas identidades.

Revisión vigente congelada **`88d42e6e81a7b4f3c44933cfea672696426496ef323a5c8e268078cda6e11bdb`**, 727 dependencias (`source-freeze-03.json`). Se cerró el vínculo de raíz de biblioteca y se corrigió el coste SQL demostrado: materializar primero filtros temporales/orden conserva exactamente 64/64 consultas reales del índice auxiliar y reduce 5.722 s a 0.092 s en ese microperfil. No se extrapola ese factor a toda la preparación. Pruebas focales/controles preservados, incluida equivalencia de 96 combinaciones sintéticas. Última integración afectada: 49 Python PASS0; JS y comprobación mediante `validateRecords` PASS0. Ningún cambio físico.

Validate oficial Java17 activo desde 2026-11-05T09:52:25Z: `runtime/validation/balanced-launch-1e72e61099714dca83df8a12743eb5de`, log `validate-01.log`; únicamente sus fixtures nativas pequeñas autorizadas, sin ensayo de escala. Preparación normal de replay 02 desde 09:52:47Z, recibo `runtime/replay/launch-47d667cf2acf484e85a4addd64319abb.jsonl`, log `replay-normal-02.log`; verifica el índice cerrado y crea grafo nuevo, con la misma Run1000/it.0. Procesos iniciales 35180→39544 (Validate) y 41376→43400 (replay) comprobados en `processes-validation-and-replay.json`; volver a comprobar identidades antes de intervenir. Fuentes sin cambios mientras actúen estas fases; salidas separadas. DryRun será posterior y secuencial.

Todavía no hay HTTP listo ni convergencia/poses acreditadas de los tres buses. Los recibos de replay no son LaunchId de simulación. Los 373 archivos nativos conservan tamaño y mtime, sin altas/bajas; manifiesto SHA intacto (`native-preservation-midtask.json`). Navegador/uso nativo no disponibles por host/pipe ausentes; inspección visual de navegador no realizada (`browser-availability.json`).

V4: 62 pruebas focalizadas PASS0. Corregidos el segundo sorteo accidental y la validación de los campos de identidad de población que añade el generador. El índice rechaza alteración de contenido aunque se recalcule su recibo, y conexión SQLite ajena. Loader/renderer preservan fase certificada y no promueven una semilla incompleta por pertenecer a otro contexto. No hay cambios físicos ni aumento de guardas.

Evidencia bajo `runtime/diagnostics/l12-architecture-20261105`: recuperación en `source-before.json`, `prior-work.diff`, `git-status-before.txt` y `processes-before.json`; grafo en `attempt-07-dependencies`; evaluación en `graph-evaluate-11.log`; equivalencia en `renderer/constraint-roster-real-01.log` y `v4/closed-http-pipeline-03/geometric-comparison.json`; pruebas y hashes en `v4/final-owned-files-and-tests.json`. Siguiente hito: convergencia y verificación de los tres L12 reales, integración y congelación. Validate, inspector/record-trial, require-trial, sorteo único, DryRun y Run permanecen pendientes de sus precondiciones. No masiva ejecutada por esta tarea.

Seguimiento de solo lectura: `Get-Content -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala\runtime\diagnostics\l12-architecture-20261105\replay-normal-02.log' -Encoding UTF8 -Tail 12 -Wait`. Validate: mismo directorio, `validate-01.log`.

## Histórico: cierre previo preservado

# Estado activo: LANZAMIENTO BLOQUEADO — NO SE INICIÓ MATSim

2026-11-05 Guatemala. La solicitud vigente autorizó una sola masiva aleatoria en PowerShell visible **condicionada a certificar los tres casos L12**. Esa condición falló tras una investigación semántica nueva; se termina sin sorteo real, sin `record-trial`, sin Validate integrado nuevo, sin DryRun y sin Run. La autorización condicionada de esta tarea no constituye permiso permanente para otro lanzamiento.

Run1000 preservada: `simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af`, LaunchId histórico `9d73afe94f0b438d934e6c7870a24b82`, it.0. Manifiesto nativo `completed/valid`, SHA `750e8c363f8fa8fa2114cc62af39e8194c9be7a935016b0bdda22a7538e31596`; estado histórico del lanzador `failed/verify_result` conservado, sin reinterpretarlo. Comparación final: 373/373 archivos mantienen tamaño y mtime, sin altas/bajas. No se recalculó el SHA completo de eventos/SQLite ni se repitió QSim.

L12_029/d0024 [43113,43259], L12_020/d0024 [43071,43257] y L12_015/d0040 [61190,61266] siguen `complete=false`. La poda de movimiento foráneo y orden de HOLD llega a `row_limit` con las guardas originales. El control diagnóstico por IDs únicos también falla `decoded_byte_limit` antes del cierre y supera el presupuesto original de visitas; no es candidato productivo. No se cambió el visor ni se entregaron poses nuevas. Las seis fixtures JS respaldan predicados concretos, no certifican continuidad ni ausencia de solapes reales. [Informe L12](../runtime/diagnostics/l12-final-20261105/RESULTADOS.md), [revisión independiente](../runtime/diagnostics/l12-final-20261105/review/RESULTADOS.md).

Preparación conservada: política `scenarios/zona1/experiments/final-20261105-random-24h-v4.json`, selector `random-full-1`, entropía `secrets.token_hex(32)`, algoritmo `sha256-rejection-u256be-v1`, intervalo inclusivo 180000–220000, recibo separado, vínculo a DryRun explícito y consumo único por LaunchId. v3/full-1 permanece intacto. Se agregaron verificaciones en contrato, auditor, lanzador y monitor. **Preparación probada en fixtures, no validada para ejecución. No existe N elegido, semilla real ni recibo de selección de esta tarea.**

Revisión actual calculada **no validada**: `2c21b0e1944e3f2855dc6dc8ebbe8909a7cfe98606727123c3b82d8bcd636ca5`, 709 dependencias (8 fuentes cambiadas, 3 añadidas). Las 130 entradas originales de fuentes nativas/insumos/políticas seleccionadas para comparación conservan SHA; delta completo en [revisión de fuentes](../runtime/diagnostics/final-launch-20261105/source-review.json). No se actualizó la política de compatibilidad histórica ni se copiaron recibos: los PASS f4cf anteriores no acreditan esta revisión. Una futura continuación requiere revisar las transiciones exactas de contrato y posproceso antes de la compatibilidad oficial con Run1000.

Pruebas acotadas: 12 contrato aleatorio + 8 gate de DryRun/lanzador/auditor + 13 contrato histórico + 25 ensayo = 58 Python PASS, códigos 0. Cinco scripts PowerShell pasan análisis de sintaxis. Java17 y .venv comprobados; no se ejecutó la batería Java ni Validate integrado en esta tarea. [Preparación y logs](../runtime/diagnostics/random-final-20261105/contract-preparation.json), [tests de gate](../runtime/diagnostics/final-launch-20261105/random-launch-tests.log), [sintaxis](../runtime/diagnostics/final-launch-20261105/powershell-syntax.json).

Procesos finales comprobados por PID/creación/padre/comando: sólo JDT del IDE entre Java/Python, sin MATSim ni servidor replay activo; procesos ajenos preservados. No se abrió consola de simulación. [Inventario final](../runtime/diagnostics/final-launch-20261105/processes-final.json), [preservación nativa](../runtime/diagnostics/final-launch-20261105/native-preservation.json). Trial oficial ausente; cero masivas, cero iteraciones nuevas, cero procesos diagnósticos remanentes. Disco observado al recuperar: 196.55 GiB; esa observación no sustituye preflight.

Siguiente acción técnica: índice de soporte que evite consultas redundantes o checkpoints persistidos con contrato verificable, demostrados en los tres casos y vecinos reales dentro de todas las guardas. Sólo tras resolver L12: revisar/integrar compatibilidad, congelar fuentes, sorteo único, regresiones, Validate, inspector/record-trial, require-trial, DryRun y eventual Run autorizado. No repetir investigaciones FIFO/L12 históricas cerradas ni grandes escaneos.

Seguimiento de solo lectura fuera del IDE: `Get-Content -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala\runtime\diagnostics\l12-final-20261105\RESULTADOS.md' -Encoding UTF8`. No hay LaunchId nuevo que observar esta noche.

## Histórico: encabezado anterior conservado

# Estado activo: cierre comprobado; REQUIERE REVISIÓN

2026-11-04 Guatemala. La Run1000 `simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af`, LaunchId `9d73afe94f0b438d934e6c7870a24b82`, it.0, conserva completed/valid y screening_pass; revisión actual compatible. Siguen abiertas las tres omisiones de contexto L12 a12:00/17:00. No se acredita replay íntegro ni capacidad masiva; full-1 mantiene gatefalse/pending y trial ausente. No otra simulación completa; solo fixtures pequeñas QSim autorizadas de Validate.

Fuentes congeladas `f4cf50840216a1772b89f2a24536e5d5be7d9940c9e69660f6966066de2082df`,706 dependencias, reconstrucción exacta c13/290. Validate0 `balanced-launch-629dafda90554187b901fd483a98bba7`:633PythonPASS+1SKIP,Java17,13JS. DryRun run1000=0 `22069874cc144e5fbf2e101a0010a621`; full-1=0 `675dd849c6dc438683f639ed04c5581b`. Inspector oficialPASS0 sin publicartrial.373/373metadatos nativos preservados trasHTTP;166Java/70físicos/48refs/8baseSHA iguales; no rescaneo de eventos ni SQLite completo.

Correcciones verificadas: ancla FIFO visual07:00 elimina el solape L6_005/L1_015,56instantes/55pares con pose; caché espacial privada verificada reduce reinicio a13.42 s hastaHTTP, manteniendo primera apertura sin preparación115.24 s y primerworker10.08 s. FIFO conserva33198/33198; L126224=2381+3843 legítimas, cero duplicados/sin conciliar. Sin cambios físicos/horarios.

HTTP29respuestas finales,14ventanas/13expediciones/11buses, seis horas;26payloadscomunes idénticos semánticamente. JSidentidad/503/selección/anclas pasan. Los tres afectados conservan85registros observados y77ocurrencias programadas por expedición, pero posición desconocida en sus intervalos por contexto incompleto. Se preservan prototipos fallidos y primeros verificadores rechazados; ningún recorte silencioso. Navegador no disponible, no inspección visual real.

Servidor final propio puerto59203:28920→44120→38240/conhost40564, recibo `runtime/replay/launch-dace6d0b7c474176b7e2c62e594dea78.jsonl`; JDT11424 ajeno preservado. Inventario fechado en evidencia; no usar estos PID sin revalidar creación/padre/comando. Ningún escritor de simulación activo comprobado. Fuentes y procesos no se limpian globalmente.

Informe y límites: [RESULTADOS](../runtime/diagnostics/run1000-closure-20261104/RESULTADOS.md), [recibos actuales](../runtime/diagnostics/run1000-closure-20261104/resume/receipts-current.json), [runbook activo](RUNBOOK_MANUAL_24H.md). Siguiente acción técnica: demostrar un contrato incremental de dependencias/checkpoints visuales o una proyección semántica certificada para esos tres casos, conservando la misma Run1000. No repetir MATSim por el visor, no publicar trial ni iniciar full-1 por este cierre.

Seguimiento de solo lectura: `Get-Content -LiteralPath 'runtime/diagnostics/run1000-closure-20261104/RESULTADOS.md' -Encoding UTF8 -Tail 12`.

## Histórico: encabezado anterior conservado

# Estado activo: revisi?n congelada y Validate en curso

2026-11-04 Guatemala. Run1000 `simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af`, LaunchId `9d73afe94f0b438d934e6c7870a24b82`, it.0, conserva completed/valid y screening_pass. General **REQUIERE REVISI?N**: los tres cierres corporales L12 no se recuperaron; los prototipos acotados quedaron fuera de producci?n y preservados en evidencia. Se corrigi? el solape independiente07:00 y se implement? cach? espacial verificada para reinicios; benchmark HTTP actual pendiente.

Fuentes congeladas `f4cf50840216a1772b89f2a24536e5d5be7d9940c9e69660f6966066de2082df`,706 dependencias; prueba reconstruye c13/290. Validate integrado activo `balanced-launch-629dafda90554187b901fd483a98bba7`, Java17, ?nicamente peque?as fixtures QSim autorizadas. A?n no se atribuyen recibos1aa a esta revisi?n. Despu?s siguen ambos DryRun separados, inspector en solo lectura, reinicio del servidor propio y HTTP/JS real. No otra Run1000 completa, full-1 ni publicaci?ntrial.

FIFO33198/33198 y L126224=2381+3843 se conservan sin rescaneo. Integridad nueva373/373metadatos,166Java+70f?sicos+48refs+8baseSHA coinciden; eventos/SQLite grandes no rele?dos. Servidor1aa inventariado31984?41224?17256/conhost45208 en59203; JDT11424 ajeno preservado. No detener por nombre ni reutilizarlo para acreditar c?digo nuevo.

Evidencia vigente: [continuaci?n](../runtime/diagnostics/run1000-closure-20261104/resume/CONTINUACION.md), [freeze](../runtime/diagnostics/run1000-closure-20261104/resume/source-freeze-validated.json), [l?mite de recuperaci?n](../runtime/diagnostics/run1000-closure-20261104/resume/STREAMING-RESULTADOS.md). Logpersistente `runtime/diagnostics/run1000-closure-20261104/resume/validate-console.log`. Siguiente acci?n: comprobar c?digo final sin editar fuentes; no iniciar ni habilitar full-1 mientras las omisiones sigan abiertas.

## Hist?rico: estado previo a esta congelaci?n

# SimZ1: continuación activa del replay; fuentes nuevas en integración

Estado activo 2026-11-04 Guatemala. Se retoma la tarea tras el límite de uso, sin reiniciar investigaciones FIFO/L12 ni otra Run1000/full-1. Corrida exclusiva `simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af`, LaunchId `9d73afe94f0b438d934e6c7870a24b82`, it.0, `completed/valid` nativo y `screening_pass` del análisis. La aceptación general continúa **REQUIERE REVISIÓN**.

Base recuperada y archivada: huella `1aa22ec81f3255bc3670fac05d0909aef428bbafeedd7a1add55369dd3c32fe1`, 703 dependencias. Validate0 `balanced-launch-578c282b3003403292a66583319e40cc`; DryRun run1000=0 `31ecd8fd72584a2c84cca47aee7e6dbe`; DryRun full-1=0 `c6a3d459da154c36bae87fc63944214e`. 599 Python PASS+1 SKIP, Java17 y12 scriptsJS. Esos recibos pertenecen a la revisión anterior: no acreditan las ediciones nuevas en integración.

FIFO 33198/33198 y L12 6224=2381+3843 conciliadas se conservan, sin otro escaneo nativo. HTTP previo26/26,14 ventanas,10 expediciones/8 buses y JS completos0. Servidor reobservado31984→41224→17256, puerto59203, recibo `runtime/replay/launch-2ba2879b68504ebebdf105261392a15a.jsonl`; JDT11424 ajeno preservado, sin QSim de escenario activo. Verificar nuevamente identidades antes de intervenir.

Trabajo actual: contexto corporal paginado con codificación reversible y guardas, reparación de ancla histórica FIFO del solape completo07:00 y preparación espacial persistente validada. Ningún cambio de física o resultados. La primera regresión visual pasó con separación13.600488m, y el codecJS pasó controles positivos/negativos; falta integrar los tres cierres reales, congelar fuentes y renovar las comprobaciones. No publicar trial ni comandos de Run habilitados antes de la decisión oficial.

Continuación detallada: [CONTINUACION](../runtime/diagnostics/run1000-closure-20261104/resume/CONTINUACION.md). [Informe activo](../runtime/diagnostics/run1000-closure-20261104/RESULTADOS.md). Seguimiento de solo lectura: `Get-Content -LiteralPath 'runtime/diagnostics/run1000-closure-20261104/resume/CONTINUACION.md' -Encoding UTF8 -Tail 12`.

## Histórico: encabezado anterior a la continuación

# SimZ1: cierre de pendientes Run1000 en investigaci?n, sin QSim

Estado activo 2026-11-04 Guatemala. Tarea autorizada: investigar/corregir replay, cobertura FIFO y conciliaci?n L12 sobre la corrida existente; renovar Validate y ambos DryRun si cambia su huella, sin ejecutar Run1000 ni full-1. LaunchId `9d73afe94f0b438d934e6c7870a24b82`, run_id `simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af`, it.0, carpeta `scenarios/zona1/montecarlo/run-bg1-9d73afe94f0b438d934e6c7870a24b82`. Manifiesto completed/valid y LaunchId hist?rico failed conservados; no se reinterpreta el fallo original del posvalidador.

Recuperaci?n: HEAD `4550fdc7cca46b2d4c3ea5fd0b0fff81ec6d98dd`, huella inicial `c13e4f73ec792c64b3c899d769ff964e381b0d45dbe5cead4c770562e722309d`, 701 dependencias y 373 archivos de la corrida inventariados. Cambios locales anteriores preservados. Evidencia en `runtime/diagnostics/run1000-closure-20261104`; principal integra/docs/HTTP/JavaScript, subagentes replay/FIFO/L12 con archivos asignados. Una sola pasada nativa incremental compartida a cargo de FIFO; los dem?s reutilizan SQLite read-only y extractos.

Procesos contrastados por PID/creaci?n/padre/comando en processes-before.json: no QSim activo; JVM11424 es JDT y permanece. Servidor hist?rico replay puerto59203 (launcher25448/16208, worker41340) preservado; no se sustituye por otra corrida. Navegador automatizado sin host/pipe, inspecci?n visual no realizada. No se alteran fuentes f?sicas, insumos ni eventos. Aceptaci?n general contin?a REQUIERE REVISI?N mientras se contrasta la evidencia.

Siguiente acci?n: reproducir y probar correcciones acotadas, integrar revisi?n y congelar antes de Validate/DryRun secuenciales. Seguimiento de solo lectura: `Get-Content -LiteralPath 'runtime/diagnostics/run1000-closure-20261104/RESULTADOS.md' -Tail 30` cuando se publique el cierre. Ning?n lanzamiento Run autorizado ni programado.

## Hist?rico: cierre anterior conservado ?ntegro

# SimZ1: Run1000 completed/valid; aceptacion completa REQUIERE REVISION

Estado activo 2026-11-04 Guatemala. Una unica Run1000 v3 ejecutada: LaunchId `9d73afe94f0b438d934e6c7870a24b82`, run_id `simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af`, carpeta `scenarios/zona1/montecarlo/run-bg1-9d73afe94f0b438d934e6c7870a24b82`, iteracion 0, 1000 no publicos +269 buses, 24h. QSim termino naturalmente0; revalidacion nativa integral0 publico completed/valid. El fallo original del posvalidador y el estado failed original del LaunchId permanecen preservados. No se repitio QSim ni se ejecuto full-1.

Resultados: 439 carros +549 motos +10 camiones completados; 2 particulares recientes censurados al corte. Todos269 buses circularon: 9975 expediciones completadas y5361 canceladas explicitamente por cierre. 10973 llegadas y691533 transiciones conciliadas; ninguna violacion corporal ni intervencion forzada; ledger sin reservas/locks despues del cleanup. No se reprodujo bloqueo sostenido en Run1000. La causa global unica del atasco masivo anterior sigue sin demostrarse y esta prueba no acredita capacidad204186.

Se corrigieron lectores del paso00:00:01, recuperacion estricta de ese fallo y CSV heterogeneo de26columnas. Sin cambios Java/fisicos/entradas/eventos en esta fase. Huella nativa `290af1f6a3640fb2fe2d33520124f1d9810cb0b1ddc22de4dc2c83b609500ea1`; final de posprocesado `c13e4f73ec792c64b3c899d769ff964e381b0d45dbe5cead4c770562e722309d`. Los8insumos base y14fuentes del auditor completo permanecen iguales; diferencias revisadas, backups y pruebas negativas preservados.

Validate final JDK17 PASS0: `balanced-launch-af4ea62eb0eb45ee989b03b13cbf5695`, 576PythonPASS+1SKIP unicos, Java nativo/C529-A/B/C/D y12scriptsJS. DryRun run1000 PASS0 `8b0f532a326944e18940ffbb93fc6c52`; DryRun full-1 PASS0 `85b076c9e4d740c38c74a361d0c2ad28`, misma huella/contrato/base, sin QSim ni carpetas de simulacion. Full-1 mantiene la guarda de ensayo pendiente. Piso100GiB, heap12, SQLite8/scratch4/reserva2 sin rebajas; pagefile6GiB calculado en controles finales, sin ajustes OS.

AnalysisOnly02=0, screening_pass, paquete integro,13PNG (7 empaquetados). Replay preparado0 y check0; SQLite2.465.746.944B, ventana0..86400, identidad nativa/it0 comprobada. HTTP real:14ventanas y6expediciones; JSreal/503controlados/seleccion/cambioexpedicion/ausencias PASS0. Servidor propio y URL exacta en replay-server-ready.json y replay-url.txt; browser CUA no disponible, inspeccion visual pendiente.

REQUIERE REVISION: arranque frio del lector~103s;3omisiones reales por decoded_byte_limit64MiB (no se subio la guarda), posiciones no reconstruibles y solapes graficos pendientes. 7857 llegadas a paradas bloqueantes sin cola indexada limitan cobertura FIFO. L12 concentra3843 cancelaciones y falta atribuir sus demoras. Ninguno de estos limites se disfraza como colision nativa o como prueba de fallo global. No se publica aprobacion oficial de escalamiento; full-1 no esta autorizado.

Informe y matriz: [RESULTADOS](../runtime/diagnostics/run1000-acceptance-20261104-2c0e2340/RESULTADOS.md), con delivery-verification.json, fuentes, codigos y anexos. [Runbook](RUNBOOK_MANUAL_24H.md) permite reabrir los mismos resultados sin QSim. Seguimiento solo lectura: `Get-Content -LiteralPath 'runtime/diagnostics/run1000-acceptance-20261104-2c0e2340/replay-server.stderr.log' -Tail 15`. No lectores de eventos adicionales; sin commit/push/reset/clean/borrados. Servidor ajeno JDT preservado; procesos finales y alcance en processes-final.json.

## Historico: estado anterior, no instrucciones vigentes de lanzamiento

# SimZ1: Run1000 completed/valid; an?lisis recuperado, replay y validaci?n final en curso

Estado activo 2026-11-04 Guatemala. Run ID `simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af`, LaunchId `9d73afe94f0b438d934e6c7870a24b82`, carpeta `scenarios/zona1/montecarlo/run-bg1-9d73afe94f0b438d934e6c7870a24b82`. ?nica Run1000 v3 ejecutada:1000 no p?blicos+269 buses, it.0,24h. QSim termin? naturalmente0. La auditor?a integral real de los mismos resultados concluy?0 y public? completed/valid; el manifiesto fallido anterior y el estado original del lanzamiento quedan preservados. No se repiti? QSim.

Resultados conciliados:998/1000 no p?blicos completados (439carros,549motos,10camiones);2particulares recientes censurados al cierre.269buses circularon:9975expediciones completadas y5361cancelaciones nativas por cierre.10973llegadas,691533transiciones,0violaciones corporales,0reservas/locks tras cleanup,0forzados/remociones/deadlocks. No hubo bloqueo sostenido sin transiciones; esto no demuestra capacidad de full-1. L12 concentra3843cancelaciones; su atribuci?n de demoras y7857intervalos de parada no localizados requieren distinguir alcance de evidencia y cumplimiento de servicio.

Se repararon lectores del paso temporal MATSim y la exportaci?n CSV heterog?nea (cabecera fija de26columnas, sin perder OD/perfil). Pruebas antes/despu?s preservadas. Revalidaci?n0, AnalysisOnly02=0, reporte operacional0, gr?ficas adicionales0, screening_pass. Huella nativa290af1f6a3640fb2fe2d33520124f1d9810cb0b1ddc22de4dc2c83b609500ea1; posprocesador actualc13e4f73ec792c64b3c899d769ff964e381b0d45dbe5cead4c770562e722309d. Fuentes nativas/8insumos/archivos de resultados intactos; revisi?n separada de recuperaci?n.

Validate final JDK17 iniciado sobrec13 en `runtime/validation/balanced-launch-af4ea62eb0eb45ee989b03b13cbf5695`; pendiente al escribir este hito. Se ejecutar?n ambos DryRun secuencialmente sin Run. Replay en preparaci?n oficial con SQLite8/scratch4GiB, un lector incremental; sin JVM SimZ1 activa, JDT ajeno preservado. Browser CUA no disponible (native pipe/host); inspecci?n visual pendiente, HTTP/JS real despu?s del replay. No aprobar ensayo por suposici?n.

Evidencia en `runtime/diagnostics/run1000-acceptance-20261104-2c0e2340`, especialmente native-acceptance-review.*, native-official-report-comparison.*, repair/lifecycle-csv-*, analysis-recovery-02-result.json y postprocessor-source-freeze-v2.json. Seguimiento solo lectura: `Get-Content -LiteralPath 'runtime/diagnostics/run1000-acceptance-20261104-2c0e2340/validate-final-01.log' -Tail 15`. Full-1 no ejecutado ni autorizado; sin commit/push/borrados.

## Hist?rico: revalidaci?n nativa a?n pendiente al registrar el hito anterior

# SimZ1: Run1000 ejecutada; Validate y ambos DryRun PASS, auditoria nativa en curso

Estado activo 2026-11-04 Guatemala. Run ID `simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af`, LaunchId `9d73afe94f0b438d934e6c7870a24b82`, carpeta `scenarios/zona1/montecarlo/run-bg1-9d73afe94f0b438d934e6c7870a24b82`. Una unica Run1000 v3 fue ejecutada: 1000 no publicos +269 buses, it.0, dia24h. QSim termino naturalmente0 y paso86400. El fallo posterior del lector `00:00:01` sigue preservado en el manifiesto hasta que termine la revalidacion integral; el estado original del LaunchId fallido no se edita.

Reparacion comprobada: normalizacion de tiempo en auditor balanced y TemporalPassage; recuperacion existente ampliada al fallo exacto con pares de SHA revisados, backup obligatorio y auditoria completa. No cambios Java, fisicos, de demanda, horarios, entradas o eventos en esta subfase. Huella ejecutada `290af1f6a3640fb2fe2d33520124f1d9810cb0b1ddc22de4dc2c83b609500ea1`; posvalidador congelado `9de97c4406454bd91c02de0f770f3c22b06bd5f356edc041c52908fb1530aa10`. La reconstruccion en memoria de hashes anteriores reprodujo exactamente290; los8insumosbase son identicos. No se alteraron recibos para aprobar.

Validate integrado JDK17 PASS0 `balanced-launch-aec3b064f49a49e2907cdf6ef393452b`:574PythonPASS+1SKIPunicos; Java nativo y12scriptsJS/13invocacionesPASS. DryRun run1000 PASS0 `aa821c28eff44138a9ae2c938ccca966`; DryRun full-1 PASS0 `a001847bad9a4b09b808b24880313152`. Ambos huella9de97, mismo contrato/base, run_idnull y sin carpetas de simulacion ni QSim. full-1 permanece eligiblefalse y ensayo pendiente. Recursos originales100GiB/heap12/SQLite8/scratch4 conservados.

Auditoria real de los resultados existentes iniciada con `python/revalidar_simz1.py --run-dir <carpeta explicita> --apply`, unico lector incremental de eventos. La publicacion completed/valid depende de su PASS y de identidad/hashes intactos; todavia pendiente. Analisis, screening y replay pendientes. Seguimiento: `Get-Content -LiteralPath 'runtime/diagnostics/run1000-acceptance-20261104-2c0e2340/revalidation-01.log' -Tail 20`; codigo final en `revalidation-01-result.json` cuando exista.

Datos provisionales, no aceptacion:1440intervaloslog completos,10973llegadas,691533transiciones,0forzados/remociones/deadlocks. Censo gzip pequeno leido una vez y extraido:439carros+549motos+10camiones completados;2privados activos recientes(124s/40s). Buses9975expedicionescompletadas+5361sin iniciar, todos269conactividad. Roster+censo concilian los5361 como sufijos sin disponibilidad antes del cierre; falta confirmar los eventos explicitos de cancelacion en el auditor. No se modifica el horario para mejorar esos resultados.

Evidencias en `runtime/diagnostics/run1000-acceptance-20261104-2c0e2340`: `postvalidator-source-freeze.json`, `integrated-validation-review.*`, `dryrun-comparison.*`, `diagnostics-log-review.*`, `bus-census-provisional-findings.md`, backups, reproducciones antes/despues y logs. No se repitio Run1000 ni ejecuto full-1; sin commit/push/reset/clean/borrados. La inspeccion visual permanece pendiente; HTTP/JS real se ejecutara despues del replay valido.

## Historico: fallo del posvalidador y comienzo de reparacion
# SimZ1: Run1000 v3 ejecutada; recuperacion del validador en curso

Estado activo 2026-11-04 Guatemala. Unicamente Run1000 autorizada y ejecutada, LaunchId `9d73afe94f0b438d934e6c7870a24b82`, Run ID `simz1-90e8f9a5c3e54c5594a15c2a9b8bd1af`, carpeta `scenarios/zona1/montecarlo/run-bg1-9d73afe94f0b438d934e6c7870a24b82`. La JVM18568 cerro naturalmente con codigo0, iteracion0 y ultimo paso86400; Maven shutdown18:33:13 Guatemala. Su identidad completa esta preservada. No quedan JVM SimZ1; JDT11424 del editor permanece intacto.

El pipeline oficial termino codigo1: el auditor `simz1_balanced_od_audit.py` intento `float('00:00:01')`, formato efectivo de MATSim para el paso de1s. Manifiesto `failed/invalid`, fase validating, categoria output_validation_error, natural_exit0. El fallo original y archivos pequenos se preservan en `runtime/diagnostics/run1000-acceptance-20261104-2c0e2340/validation-failure-before`; el estado de lanzamiento fallido no se reescribe. Todavia NO es completed/valid ni esta aprobada.

Se corrigen exclusivamente lectores/recuperacion demostrados y se volveran a ejecutar regresiones, Validate y DryRun antes de revalidar integralmente los mismos resultados. Huella nativa ejecutada `290af1f6a3640fb2fe2d33520124f1d9810cb0b1ddc22de4dc2c83b609500ea1` se conserva; la revision de posvalidacion se registrara por separado. Ningun cambio de eventos, entradas, fisica o poblacion. No se repite QSim por este fallo; full-1 no autorizado. Analisis, screening y replay pendientes.

Seguimiento solo lectura: `Get-Content -LiteralPath 'runtime/diagnostics/run1000-acceptance-20261104-2c0e2340/launch-01.log' -Tail 20`. Evidencia de antes/despues del parser bajo la misma carpeta. El resumen horario se prepara desde el log sin abrir eventos, mientras un unico futuro validador conserva la propiedad de su lectura incremental.

## Historico: inicio del ensayo
# SimZ1: FASE 4 autorizada, Run1000 v3 en preparación

Estado activo 2026-11-04 Guatemala. El usuario autorizó explícitamente ejecutar Run1000 y sus validaciones, análisis, empaquetado y visor. Se inició únicamente el lanzador oficial para `final-20261104-24h-v3.json / run1000`, N1000 no públicos +269 buses, it.0, semilla20261023 y servicio2026-10-23. Nunca full-1. Máximo una repetición adicional solo ante defecto de simulación demostrado y tras las validaciones correspondientes; ningún posproceso fallido justifica repetir QSim.

LaunchId `9d73afe94f0b438d934e6c7870a24b82`, carpeta planificada `scenarios/zona1/montecarlo/run-bg1-9d73afe94f0b438d934e6c7870a24b82`. Al registrar este hito permanece en configuration_preflight: run_id aún null, sin manifiesto, no se afirma QSim iniciado. Comando y consola persistentes en `runtime/diagnostics/run1000-acceptance-20261104-2c0e2340/launch-01-command.json` y `launch-01.log`; identidad viva del lanzador y sus hijos bajo `runtime/launches/9d73afe94f0b438d934e6c7870a24b82`.

Precondiciones frescas PASS: huella `290af1f6a3640fb2fe2d33520124f1d9810cb0b1ddc22de4dc2c83b609500ea1`,32 archivos y8 insumos base coinciden con freeze; Validate0 y ambos DryRun0 de la entrega anterior concordantes. JVM nocturna ausente, manifiesto failed/invalid conservado; único Java ajeno JDT del IDE. Memoria planning_budget_pass y disco202.59GiB sobre piso100GiB, sin reducir guardas. Fuentes/insumos congelados; no compilar ni editar mientras actúe el escritor.

Principal único ejecutor y responsable de documentación. Subagentes revisan contrato, plan de auditoría nativa y visor sin escritores compartidos; durante la corrida no se agrega lector de eventos. La aceptación está pendiente de finalización nativa, integridad, llegadas/reservas, screening y replay real. No se presume capacidad masiva por el ensayo.

Seguimiento de solo lectura desde PowerShell externa: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_simz1_110k.ps1 -LaunchId 9d73afe94f0b438d934e6c7870a24b82 -Watch -Iteration 0` (sin `-Events`; capturar LASTEXITCODE al terminar). Cola persistente: `Get-Content -LiteralPath 'runtime/diagnostics/run1000-acceptance-20261104-2c0e2340/launch-01.log' -Tail 20`.

## Histórico: cierre de integración anterior al Run autorizado


# SimZ1: LISTO PARA RUN1000 v3; full-1 pendiente

Estado activo 2026-11-05T00:10:33.919530+00:00 (2026-11-04 Guatemala). Las correcciones están integradas y validadas en `C:/Users/gegdg/Documents/.UVG/Sim/matsim-guatemala`. Se integraron 32 archivos de producción/pruebas, con revisión de ambos árboles, copias previas y cero conflictos; se preservaron los cambios documentales anteriores. HEAD `4550fdc7cca46b2d4c3ea5fd0b0fff81ec6d98dd`, sin commit ni push. Huella de fuentes/configuración **`290af1f6a3640fb2fe2d33520124f1d9810cb0b1ddc22de4dc2c83b609500ea1`**.

La JVM nocturna fue detenida con autorización explícita, tras contrastar PID 40484, creación `2026-11-04T04:43:52.828Z`, padre, ejecutable y comando. Run ID `simz1-41a34efdd0ee440d8b9ca911cf414f09`, carpeta `run-massive-night-20261103-224052-0084d200`, LaunchId ausente. El ejecutor dejó `failed/invalid`, returncode 1, terminado `2026-11-04T23:18:58.661162+00:00`, sin iteraciones completadas. No se interpreta como día completo; returncode es del hijo observado por el ejecutor/Maven, no un código Windows nativo medido por separado. Se preservaron 27 entradas, 180 clases y gzip/log/manifiesto finales. No se releyó el gzip ni se reanudó QSim.

Diagnóstico ampliado: ciclo local de 62 actores, 85 al seguir alternativas, más 22 seguidores examinados para cerrar el almacenamiento del split (107 distintos). En el puente z1_23393 → z1_150867 se deducen 10 PCU viajeros frente a 9.786436 PCU de capacidad nativa; no se cuenta el buffer como cola viajera. Las condiciones proceden del prefijo hasta t52799 y de las entradas/código preservados, no de un snapshot atómico de heap. No se encontró un defecto nuevo de movimiento. La fixture nativa de split conserva rechazo con receptor lleno y permite avance real tras despeje, sin forzados. El ciclo es condicionado por las solicitudes/reservas observadas; no prueba atasco eterno ni causa única global. La otra cadena z1_129411 mantiene una limitación de ruta instalada.

Validate JDK17 **PASS0**, recibo `runtime/validation/balanced-launch-d40629c5651f47879a9fd2a5cf63822b`. Python: 548 identidades únicas PASS y 1 SKIP (symlinks no disponibles); Java nativo y 12 scripts JS/13 invocaciones PASS. DryRun run1000 **PASS0**, LaunchId `51866fe06196430984d0781896da1f5c`; DryRun full-1 **PASS0**, LaunchId `2c43ccf1add644f7a5318e0dfd870ad7`. Ambos conservan esta huella, base `472a4273d05353b1e8ca2fafda8a34a6eb32f1e5757e68b679ea7e888fa8c7f0`, spec v3 `e60478c6bc3a89e541de00e40487401d72a7bd2aee852cdc7df1084947306b38`, run_id null y carpeta de simulación ausente. Ningún DryRun ejecutó QSim. Recursos originales y presupuesto de replay sin rebajas.

Run1000: 1000 no públicos (440 carros, 550 motos, 10 camiones) +269 buses. full-1: 204186 (89842/112302/2042) +269 buses. Misma base L18, OD balanced, compact-v3, semilla20261023, servicio2026-10-23, it.0 y día24h. No existe aceptación nueva Run1000; el recibo legacy no sirve. full-1 tiene `run_launch_eligible=false`, `prior_trial_status=pending_not_approved`; este cierre NO autoriza la masiva y conserva la limitación causal global. Run1000 está lista como ensayo manual, no como garantía de descarga masiva.

No quedan escritores incompatibles al cierre; el JDT del IDE se conserva. No hubo Run1000/full-1 nuevos, commit, push, reset, clean, limpieza histórica ni alteraciones físicas para aprobar. Evidencia completa y copias en [completion/RESULTADOS.md](C:/Users/gegdg/Documents/.UVG/Sim/matsim-guatemala-repair-20261104/runtime/diagnostics/phases123-20261104/completion/RESULTADOS.md), más `native/COMPLETION-DIAGNOSTIC.md`, `integrated-validation-review.md`, `dryrun-comparison.md`, `source-freeze.json` y `delivery-verification.json`. Comandos exactos manuales y visor de la misma identidad en [RUNBOOK_MANUAL_24H.md](RUNBOOK_MANUAL_24H.md).

Seguimiento de solo lectura: `Get-Content -LiteralPath 'C:/Users/gegdg/Documents/.UVG/Sim/matsim-guatemala-repair-20261104/runtime/diagnostics/phases123-20261104/completion/dryrun-full-1-01.log' -Tail 20`. Siguiente acción: el usuario puede iniciar únicamente Run1000 v3 desde PowerShell externa; después revisar aceptación, resultados, llegadas/censura y visor. Una Run1000 aprobada no prueba capacidad204186.

## Histórico: integración antes de Validate y DryRun

# SimZ1: integración realizada; validación pendiente de congelación diagnóstica

Estado activo 2026-11-04 17:19 Guatemala: la interrupción fue autorizada explícitamente por el usuario y ejecutada únicamente sobre la JVM nativa identificada. Se verificaron de nuevo PID 40484, creación, padre, ejecutable y comando, junto con los seis procesos restantes de su árbol. La JVM y sus supervisores salieron; el ejecutor conservó `failed/invalid`, código 1, terminado `2026-11-04T23:18:58.661162+00:00`, sin iteraciones completadas. Run ID `simz1-41a34efdd0ee440d8b9ca911cf414f09`, carpeta `run-massive-night-20261103-224052-0084d200`, LaunchId ausente. No es un día completo ni una corrida aceptada. No se editaron sus resultados ni se reinició QSim.

Los 31 archivos de producción/pruebas del freeze fueron integrados desde el worktree al repositorio principal: 27 originales coincidentes con la línea base y cuatro nuevos sin colisión. Copias previas, hashes y transacción en `C:/Users/gegdg/Documents/.UVG/Sim/matsim-guatemala-repair-20261104/runtime/diagnostics/phases123-20261104/completion/original-before-integration` e `integration-transaction.json`. No se copiaron clases, target ni recibos del worktree. Huella principal verificada `87f4d77b884046b2aecc8b6f3c82f6162b7a09e34b8378797342dc7e22096906`; diff --check código 0. Las entradas originales de la corrida (27 archivos) conservan sus hashes.

El diagnóstico continúa en aislamiento, reutilizando extractos. Se identificó la terminal omitida del split interno tras z1_178169 y el recibo único tras z1_129411; aún no se afirma un defecto global ni reparación de descarga. Los nuevos campos diagnósticos no existen retroactivamente en los eventos de la JVM anterior. Validate y ambos DryRun están autorizados y se ejecutarán secuencialmente después del freeze de esta investigación y sus pruebas focales. No se ha iniciado Run1000 ni full-1. El único Java ajeno observado es el servidor JDT del IDE, preservado.

Evidencia de interrupción: `completion/interruption-20261104T231845383Z` bajo la carpeta de diagnóstico del worktree; contiene autorización, procesos y archivos antes/después. El estado `failed` proviene del ejecutor y se conserva. Siguiente acción: cerrar la extensión causal y sus controles, congelar fuentes, ejecutar Validate JDK17 y DryRun run1000/full-1 v3, sin encadenar Run. Seguimiento de solo lectura: `Get-Content -LiteralPath 'C:/Users/gegdg/Documents/.UVG/Sim/matsim-guatemala-repair-20261104/runtime/diagnostics/phases123-20261104/completion/integration-transaction.json'`.

## Histórico: entrega anterior mientras la JVM estaba activa

# SimZ1: fases 1–3 implementadas en aislamiento; BLOQUEADO para Run1000

Estado activo verificado 2026-11-04T20:46:38.507429+00:00 (2026-11-04 Guatemala). Corrida explícita `scenarios/zona1/montecarlo/run-massive-night-20261103-224052-0084d200`, run_id `simz1-41a34efdd0ee440d8b9ca911cf414f09`, it.0. JVM40484, creación nativa `2026-11-04T04:43:52.828Z`, padre38972; identidad completa nuevamente contrastada. Lanzador genérico, LaunchId ausente y sin state/request asociado. Última cola de log al cierre: t=55800, activos=20301, llegadas=0 y transiciones=3 en 60s. No se detuvo la corrida ni se inició Run1000/masiva. Fuentes/insumos/build originales intactos; solo estos dos documentos de continuidad cambian en el original.

Recomendación **DETENER**, sin ejecutar interrupción: contrato equivocado y descarga casi detenida. El prefijo provisional contiene182667816 eventos completos hasta t52799,10770 llegadas, última t40774;20175 vehículos activos y20175 reservas conciliadas.10430 llegadas no públicas se conciliaron con salida nativa/liberación corporal. Snapshot logt52980:203 intervalos de60s sin llegadas; en (51180,52980] hubo0 llegadas y182 transiciones. Gzip aún abierto, no día completo ni auditoría integral aprobada. Cadenas de12/58/58 dependencias terminan en observabilidad insuficiente: no se demostró causa global ni arreglo de descarga.

Implementado en `C:/Users/gegdg/Documents/.UVG/Sim/matsim-guatemala-repair-20261104`: atribución nativa/corporal de rechazo con reproducción Java antes/después sin cambiar movimientos; recovery503/Retry-After y protección de selección; itinerario verificado independiente de interpolación; contrato sucesorv3 con run1000 N1000 y full-1 N204186, misma base L18/balanced/carga v3/día24h; guardas de propietario, huella y aceptación de ensayo. Corregido bootstrap de fixtures para primer Validate sin recibo, conservando controles de aparición/mutación/ausencia. Cambios de hashes protegidos limitados a dos archivos Java revisados y probados. AGENTS.md y variantes históricas intactos.

Revisión base HEAD `4550fdc7cca46b2d4c3ea5fd0b0fff81ec6d98dd`; huella original `31177dd4e290bef407cf8f8512a615c55f0da22536246a308fb83212165ae056`. No se atribuye ese HEAD posterior al lanzamiento original. Huella preparada congelada **`87f4d77b884046b2aecc8b6f3c82f6162b7a09e34b8378797342dc7e22096906`**. Las180 clases previas al parche coinciden con el build de la corrida; las clases finales nuevas solo están en el worktree aislado. No se compilaron archivos usados por la JVM original.

Pruebas focales JDK17, Python y JavaScript con códigos y cobertura en [RESULTADOS](C:/Users/gegdg/Documents/.UVG/Sim/matsim-guatemala-repair-20261104/runtime/diagnostics/phases123-20261104/RESULTADOS.md) y `native/native-test-summary-final.json`. Validate integrado y DryRun run1000/full-1 **NO EJECUTADOS**, códigos y recibos null; no hay aprobación nueva. Siguiente acción: después del fin verificado del escritor (interrupción solo con autorización explícita nueva), ejecutar Validate y ambos DryRun secuencialmente en la revisión congelada, según [runbook](C:/Users/gegdg/Documents/.UVG/Sim/matsim-guatemala-repair-20261104/docs/RUNBOOK_MANUAL_24H.md). No usar comandos históricos ni FirstScaleTrial. Run1000 y masiva siguen manuales y fuera de esta tarea.

Evidencia persistente `C:/Users/gegdg/Documents/.UVG/Sim/matsim-guatemala-repair-20261104/runtime/diagnostics/phases123-20261104`: cobertura, preservación, procesos, diagnóstico causal, pruebas, source-freeze, fases pendientes y procedimiento de interrupción preparado. Seguimiento externo de solo lectura: `Get-Content -LiteralPath 'C:/Users/gegdg/Documents/.UVG/Sim/matsim-guatemala/scenarios/zona1/montecarlo/run-massive-night-20261103-224052-0084d200/matsim-run.log' -Tail 25`. No requiere releer XML ni crear un observador.

## Histórico anterior a esta recuperación; no representa el estado vigente

# SimZ1: limpieza historica auditada, eliminacion bloqueada

Estado activo 2026-11-03 20:44 Guatemala: AUDITORIA DE LIMPIEZA CERRADA; BORRADO NO EJECUTADO POR BLOQUEO AUTOMATICO. Autorizacion expresa del usuario para limpieza, sin simulaciones. Informe y rutas exactas: runtime/diagnostics/cleanup-20261103/INFORME.md e inventory-approved.json. Principal unico responsable de escritura/eliminacion; tres subagentes de revision de solo lectura. La revision automatica rechazo dos intentos (bloque combinado y luego cuatro rutas literales con guardas separadas) con "blocked by policy", sin mas razon. No se intento otra via. Eliminadas 0 corridas/0 carpetas, recuperados 0 bytes. Cuatro carpetas legacy output tecnicamente elegibles suman113137760 bytes y permanecen presentes; nueve carpetas principales protegidas, mas todas las evidencias runtime, fuentes y laboratorios. Libre medido al cierre 221.215 GiB.

Verificacion final: misma revision HEAD3fba93ec96a4d5b85a0354c32fa3b08bbd2fcd70 y huella31177dd4e290bef407cf8f8512a615c55f0da22536246a308fb83212165ae056; 713 hashes iniciales intactos,18123 archivos preservados sin cambio de tamano/mtime y62 fixtures de procedencia PASS. Catorce pruebas focales de huella/proteccion PASS0; primer import auxiliar fallido y corregido conservado. Guardia previa PASS0 con375 archivos abiertos exclusivamente sin conflicto, cuatro arboles intactos y33 copias pequenas verificadas. Fallo auxiliar UTF-16 corregido solo en el lector del informe, sin modificar mecanismo vigente. Recibos Validate e743041f5da04dfeb9eb87ba4bfcde50 y DryRun85efb216b386470580fe7873e1cbc344 conservados con misma huella; no se renovaron. Este encabezado es la unica actualizacion documental fuera del informe y conserva literalmente el texto anterior.

Sin MATSim/Maven/ejecutor/observador/replay activo identificado por PID/creacion/padre/comando; JVM11424 es Eclipse JDT y permanece. Historico9da9ec50b78b45fe86550f81a558fa06 / simz1-46d19e61442942a7bfbc86b1fdb8a5a1: running persistido, orphaned/incomplete observado; se conserva completa la corrida porque diagnosticos consumen log/planes/insumos y los extractos son selectivos. Se preservan seis preparaciones (una sin manifiesto), auditorias, C529-A/B/C/D, L18, cabeza before/after t102, PCU y discharge/coverage-followup. No se alteraron evidencias historicas ni se ejecuto QSim, Validate completo, DryRun, commit, push o reset.

Hallazgo de solo lectura: el Run1000 existente usa catalogo/OD balanceados pero NO propaga ExperimentSpec/Scenario ni activa fixed-day-24h-v1/endTime86399/censo; tampoco usa la variante L18 del experimento. No hay selector N1000 en la especificacion24h. El informe conserva el comando existente y las salidas de graficas/replay, sin presentarlo como ensayo compatible de24h. Siguiente accion: resolver el bloqueo de eliminacion por fuera de este intento, con guardas frescas, y tratar la alineacion de Run1000 en una tarea independiente antes de usarlo para el contrato24h. No hay lanzamiento programado. Seguimiento externo de solo lectura: `Get-Content -LiteralPath 'runtime/diagnostics/cleanup-20261103/deletion-result.json'`.

## Historico: cobertura complementaria previa a la auditoria de limpieza

# SimZ1: recuperacion de descarga y cadenas causales

Estado activo 2026-11-03 19:18 Guatemala: COBERTURA COMPLEMENTARIA DE FASES 2/3/4 CERRADA; VALIDATE Y DRYRUN PASS0. Matriz de requisito/evidencia/resultado/pendiente, contraste previo y cierre en runtime/diagnostics/discharge-20261103/coverage-followup/MATRIZ.md; verificacion final en delivery-verification.json del mismo directorio. Revision de trabajo HEAD3fba93ec96a4d5b85a0354c32fa3b08bbd2fcd70, huella nueva31177dd4e290bef407cf8f8512a615c55f0da22536246a308fb83212165ae056. La entrega anterior se conserva:947 archivos,848 hashes comprobados, grandes sin cambios de tamano/fecha; solo mtime del SHM auxiliar difiere con contenido identico, documentado sin restaurarlo. Sus recibos92c2 siguen historicos.

Brechas cerradas: C amplio una fixture nativa minima a cuatro carros/cuatro motos EE/EI/IE/II, carga y bus con llegada unica, despeje, liberacion y censo; B concilio before/after y agrego censos exactos a OrdinaryReceipt; A caracterizo hora/familia/OD/destino/receptor mediante indice existente y una pasada incremental de planes de entrada, sin releer eventos historicos originales. Un escritor por archivo; principal integro y ejecuto build/Validate/DryRun secuenciales. Solo cambiaron dos pruebas Java, su invocacion en simz1_workflow.ps1 y documentacion. Las dos correcciones de produccion anteriores permanecen; no aparecio otro defecto demostrado. Demanda, capacidades, senales, prioridades y visor sin cambios.

Hito 2026-11-03 18:19 Guatemala: build focal JDK17 PASS0, componente OrdinaryReceipt con cinco censos de tres actores y cuatro negativos PASS0, Controller day-cycle diez actores/ocho enlaces/t85300..86400 PASS0 con142 negativos de copias y ocho destinos OD rechazados. Modo anterior de seis actores intacto; nueve fixtures previas conciliadas sin repetir QSim. Revision congelada en coverage-followup/source-freeze.json. Los negativos fisicos previos se reutilizan y distinguen de las mutaciones de copias del verificador. Fase4: cohorte A2341/B752, union2785, solapamiento308;20 comprobaciones PASS y tres CSV horarios. Hechos, hipotesis y estados internos historicos ausentes separados en la matriz.

Hitos de aprobacion: Validate nuevo PASS, codigo0, a las19:00, runtime/validation/balanced-launch-e743041f5da04dfeb9eb87ba4bfcde50; cobertura C529-A/B/C/D, OD/OSM, temporal, L18, llegada corporal, censo y ultima parada revisada en coverage-followup/integrated-validation-review.md. DryRun max-test220000 x1 separado PASS, codigo0, LaunchId85efb216b386470580fe7873e1cbc344, final2026-11-03T19:18:28-06:00. Recibo normal, huella congelada y DryRun concordantes; estado dry_run_pass, run_id null, sin directorio de corrida ni QSim. Desconexiones del cliente no duplicaron lanzamientos. Ningun Run1000 ni masiva iniciada/programada.

Procesos finales contrastados por PID/creacion/padre/comando: sin MATSim/Maven/ejecutor activo; JVM11424 es Eclipse JDT y se conserva. Historico explicito9da9ec50b78b45fe86550f81a558fa06, run_id simz1-46d19e61442942a7bfbc86b1fdb8a5a1, it0: metadatos running preservados, observado orphaned/incomplete;432 archivos y18 hashes de metadatos sin cambios. No se reanuda ni se transforma su horizonte30h en dia24h.

Siguiente accion: ensayo masivo solo manual del usuario desde PowerShell externa, segun docs/RUNBOOK_MANUAL_24H.md y guardas normales. No quedan requisitos locales de esta cobertura que impidan ensayar. Descarga/capacidad global, distribucion de esperas, propagacion de bloqueos y costo real solo pueden medirse a escala; observaciones simultaneas necesarias documentadas sin bloquear indefinidamente por estados historicos ausentes. No hay nueva corrida aceptada para graficas/visor ni prueba visual. Seguimiento externo de solo lectura, desde la raiz: `Get-Content -LiteralPath 'runtime/diagnostics/discharge-20261103/coverage-followup/dryrun.log' -Tail 25`.

## Historico: entrega de reparacion y cadenas, anterior al complemento de cobertura

Reanudado por instruccion del usuario el 2026-11-03; cierre documental a partir de la recuperacion de 17:45 (Guatemala). La pausa queda historica. Git status/diff, huella, recibo y procesos contrastados: misma revision validada, sin MATSim/Maven/analisis activos ni masiva programada; servicio Java del editor intacto. Preservacion final: 432 archivos historicos sin cambios de tamano/fecha, 18 hashes de metadatos iguales y 65 bloques de diff previos conservados. Verificacion de entrega en runtime/diagnostics/discharge-20261103/delivery-verification.json; hashes documentales actualizados en changed-files.json. No se repitieron pruebas, Validate ni DryRun tras la pausa porque no cambiaron fuentes ni insumos. Revision documental independiente distingue los escenarios Controller de la matriz de componentes y limita el before a ausencia de llegada al corte 350, sin afirmar bloqueo permanente. El historico permanece orphaned/incomplete.

Estado activo 2026-11-03: REPARACION FOCAL COMPLETADA, VALIDATE Y DRYRUN PASS, SIN MASIVA. Dos defectos demostrados corregidos: cabeza viajera independiente oculta en la original y PCU omitido al reinsertar buses desde parada. Base recuperada HEAD 3fba93ec96a4d5b85a0354c32fa3b08bbd2fcd70; huella inicial 9b23dd448a864e853579b41512f249b29b158c6f4b75598949bd62b819bf5823. La revision nueva se aprobo por el mecanismo normal; recibo inicial conservado como evidencia. Tres subagentes A/B/C, unico escritor de QueueWithBuffer y compilaciones secuenciales por el principal. Sin commit ni cambios de demanda, semilla, OD, horarios, horizonte, capacidades, cuerpos, geometria o senales de produccion.

Procesos recuperados por PID/creacion/padre/comando: sin MATSim/Maven/ejecutor activo; JVM11424 es Eclipse JDT del editor. Ningun proceso ajeno detenido. Historico explicito LaunchId9da9ec50b78b45fe86550f81a558fa06, run_id simz1-46d19e61442942a7bfbc86b1fdb8a5a1, it0: metadatos running preservados, arbol ausente, orphaned/incomplete; no se reanuda ni se convierte a24h. Una unica extraccion incremental compartida amplia evidencia temporal; los offsets descomprimidos no son checkpoints.

Hito demostrado: Controller/QSim sintetico de5carros falla antes del parche (codigo1). Snapshot nativo t100: original buffer slot0, primer viajero slot0 y siguiente viajero slot1 listo; terminalslot1 vacio, credito0. La cabeza independiente pierde verde y no llega al corte350; control minimo4carros PASS0. QueueWithBuffer ahora selecciona esa cabeza independiente conservando FIFO por slot, reservas y acumulacion/cobro normal de flujo. Segundo defecto demostrado por fixture6actores (EE/EI/IE/II/carga/bus): seis llegadas y liberaciones ya correctas, pero21 muestras de PCU discrepantes por reinsercion de parada. Se restaura PCU al reinsertar; no se atribuye ese subconteo al atasco.

Evidencias persistentes: runtime/diagnostics/discharge-20261103/RESULTADOS.md, changed-files.json y chain-a/b/c.md. Snapshot before: runtime/original-travel-head-5912729438018808084/native-snapshot-t100.json. Compilaciones JDK17 antes/despues 0; positivo Controller y controles de mismo slot, original unico, deuda y minimo de actores PASS; carro independiente llega a 102 despues, frente a ninguna llegada antes del corte 350 en la base. Matriz de 12 variantes nativas con tres actores maximos PASS; 12 regresiones nativas afectadas PASS; seis llegadas OD/carga/bus y cero discrepancias PCU. Mutacion/ausencia/huella protegidas: 7 pruebas PASS y 112 archivos protegidos concordantes. Se preservan 432 archivos historicos por tamano/fecha y los hashes de metadatos.

Hito de congelacion: huella nueva 92c2b3244267f944adece1b7b6795c878b6863d91f128b115a4d5d226684e592. Validate integrado PASS, codigo 0, runtime/validation/balanced-launch-fafd8339e48243b0ac5e99da26afae54; recibo normal concordante y cobertura revisada en coverage-review.json. DryRun max-test 220000 x 1 PASS, codigo 0, LaunchId 035d011d16ee4022b84bf6c431f4844e, terminado 2026-11-03T15:57:24-06:00. Estado dry_run_pass, run_id null, carpeta planeada inexistente y ningun QSim ejecutado por DryRun; sin Run encadenado ni programado. Fuentes congeladas. Logs persistentes runtime/diagnostics/discharge-20261103/validate.log y dryrun.log; verificacion final en delivery-verification.json del mismo directorio.

Cadenas A/B cerradas al ultimo evento completo t=59159 mediante una unica lectura incremental de eventos (codigo 0, 85395435 eventos, SHA256 original identico). El prefijo sigue truncado. A: recepcion corporal y ventanas consumidas por otros accesos explican dependencias observadas; 6020 exige 14.329259 m, mejor cota disponible antes del intento 28773 <=14.243528 m. B: reserva de freight_000757 permanece sin consumo posterior en su slot hasta el fin del prefijo; z1_53393 retiene original mientras terminal 0 y ledger del receptor 3/4 quedan vacios. Su ruta pre-QSim concuerda con 66 entradas y no hay reruteo exitoso; falta particion atomica historica viaje/buffer para atribucion exacta del defecto local. No se modifican rechazos fisicos correctos ni se atribuye toda la red a la fixture. Siguiente accion: ensayo masivo solo manual del usuario desde PowerShell externa, segun docs/RUNBOOK_MANUAL_24H.md. Ninguna fixture ni preflight acredita descarga a 220K. No hay nueva corrida aceptada para graficas/visor; no se hizo prueba visual. Seguimiento de solo lectura: Get-Content runtime/diagnostics/discharge-20261103/dryrun.log -Tail 25.

## Historico anterior: entrega de reparacion de 24 h

# SimZ1: reparacion de ejecucion y observacion de 24 h

Estado activo 2026-11-03T11:49-06:00: LISTO PARA ENSAYO MANUAL, CON RIESGOS DE CIRCULACION IDENTIFICADOS. Validate normal y DryRun max-test 220000 x 1 PASS, codigos 0, secuenciales; ninguna masiva iniciada ni programada. La siguiente masiva sera manual del usuario. Evidencia: runtime/diagnostics/repair24h-20261103/REPARACION.md y delivery-verification.json. Subagentes coordinados con un escritor por archivo; fuentes congeladas y entregas revisadas.

Terminado: identidades atomicas/conciliacion (suite vigente 21 pruebas inertes); censo nativo antes de cleanup, clasificacion por viaje y politica versionada 24h; observabilidad/reruteo; informes/replay y docs/RUNBOOK_MANUAL_24H.md. QSim focal: un camion por caso y N=3/B=2, dos iteraciones, llegada real en T y pendientes, sin eventos fisicos posteriores. Los tres casos de circulacion reproducen rechazos correctos; no se acredito un defecto que autorice cambiar su rechazo.

Evidencia final: revision de trabajo HEAD 3fba93ec96a4d5b85a0354c32fa3b08bbd2fcd70, huella 9b23dd448a864e853579b41512f249b29b158c6f4b75598949bd62b819bf5823. Validate: runtime/validation/balanced-launch-e4ad30b044124e07992c3912424778dc/; DryRun LaunchId 3e2b36d357c8499d940e9868f4f16388, estado dry_run_pass, run_id null, sin directorio de corrida ni QSim. Dos Validate previos fallaron por preparacion de fixtures y quedaron conservados; se corrigieron y se renovo el recibo mediante Validate completo, sin exclusiones ni aprobaciones artificiales. Recursos frescos: 234.50 GiB libres, piso 100; presupuesto derivado full-10 227 GiB, sujeto a su propio DryRun futuro.

Pendiente: solo ensayo manual, acreditacion de descarga/costo a escala y cualquier investigacion global que requiera sus datos. Ninguna prueba focal ni DryRun acredita desempeno a 220K. Interpretacion historica final separada en historical-observed-final.json: orphaned/incomplete, salida y muerte desconocidas. historical-observed.json conserva una observacion anterior al arreglo que contaba al observador; no usarla como resultado final. Los 432 archivos historicos mantienen tamano/fecha y los metadatos sus hashes; gzip sin alterar ni releer completo. No hay nueva corrida para analizar; el runbook permite posprocesar/replay de la futura corrida sin repetir QSim.

Hallazgo temporal probado: MATSim 15 con onlyUseEndtime ejecuta endTime+un paso. La politica nueva declara fin fisico inclusivo T=86400 y parametro nativo endTime=86399 con paso 1. Se drenan eventos ya emitidos y se conserva el cleanup bruto, sin convertirlo en llegada. Preparaciones de 30h y sus recibos siguen historicos.

## Historico anterior: diagnostico de cierre

# SimZ1: diagnóstico del cierre sin registro de 220000 x 1

Estado activo 2026-11-03T09:25:15-06:00: diagnostico entregado; intento incompleto sin arbol de ejecucion observado. LaunchId 9da9ec50b78b45fe86550f81a558fa06; run_id simz1-46d19e61442942a7bfbc86b1fdb8a5a1; iteracion 0; carpeta explicita scenarios/zona1/montecarlo/run-bg220-9da9ec50b78b45fe86550f81a558fa06. Las comprobaciones CIM de 08:53:07 y 09:25:15 (Guatemala) no encuentran MATSim/Maven/ejecutor/observador; Java 3016 y 15908 son servicios del editor, identificados por creacion, padre y comando. Los metadatos originales siguen running y se preservaron: no prueban actividad ni se promovieron a completed/valid.

Informe y evidencia: [runtime/diagnostics/220k-closure-20261103-9da9ec50/DIAGNOSTICO.md](../runtime/diagnostics/220k-closure-20261103-9da9ec50/DIAGNOSTICO.md). Cierre del arbol: probable asociacion al desmontaje de la sesion propietaria registrado a las 02:36:52; mecanismo concreto, codigo de salida y hora exacta de muerte no determinados. No hay excepcion nativa, OOM o cierre normal demostrados. No se atribuye la congestion anterior a ese cierre.

Una pasada incremental verifico 85395435 eventos completos, ultimo a 59159 s (WAIT de z1_06812), seguido de otro evento cortado; gzip sin fin/CRC verificable y XML sin cierre. Ultimo SIMZ1_PROGRESS 59100; watchdog 59159; no garantizan todos los eventos del segundo final. La caida de descarga se observa desde la hora simulada 07; desde 11:00 solo hay llegadas de expediciones publicas en el prefijo. Siete cabezas documentan recepcion nativa/corporal, senales y despeje de cruce, sin demostrar una violacion global del motor. Las evaluaciones de reruteo 58980/59040/59100 consumieron 93.319/87.017/88.073 s, 282 calculos, cero rutas instaladas. El trabajo exacto del paso inconcluso 59160 no quedo registrado.

Revision preservada: huella leida de solo lectura 5ca33fffe7eb61035bf95d4d7ed8c2dbcad97fcf5c3927b390a2e68d884df092, igual a la congelada; 432 archivos originales sin cambios. Pruebas focales Python 8/8, prueba de filtro/pilas con clase de la corrida y JDK17, escaneo e indices y conciliacion: codigos 0; evidencia en el directorio diagnostico. Se reproducen running sin comprobacion de procesos, PID solo en memoria y omission de main/recorte de pilas. Sin cambios de produccion, Validate completo, DryRun, nueva masiva, subagentes ni visor. El cambio documental no integra la huella segun el mecanismo vigente; no se cambio el mecanismo ni los recibos.

Siguiente accion: detener el trabajo tras el diagnostico; una reparacion o ejecucion futura requiere su tarea correspondiente. No hay checkpoint compatible demostrado: el JSON live-checkpoint es observacional. No presentar un nuevo inicio como reanudacion. El horizonte original de esta corrida permanece 30 h; la revision futura de 24 h y clasificacion de pendientes no se aplico retroactivamente. El informe contiene el comando externo de seguimiento de solo lectura y las reparaciones minimas propuestas.

## Estado histórico anterior al diagnóstico de 2026-11-03

Lo que sigue conserva el estado observado durante la ejecucion y sus instrucciones historicas; no acredita una corrida actualmente activa ni autoriza otro lanzamiento.

Estado activo 2026-11-03T02:23:36.334503+00:00: QSim en curso, unica corrida 220000 x 1, LaunchId 9da9ec50b78b45fe86550f81a558fa06, run_id simz1-46d19e61442942a7bfbc86b1fdb8a5a1, iteracion 0. Paso nativo completo 36000.0 s; lector 23781.0 s. En ese prefijo de carga: nominales 639, tolerados 27, excesos 12, errores tecnicos/fisicos 0; pendientes/futuros no equivalen a completar. Snapshot provisional Run-220K-live-checkpoint.json. Validate normal y DryRun aprobaron (0), huella congelada 5ca33fffe7eb61035bf95d4d7ed8c2dbcad97fcf5c3927b390a2e68d884df092. Java QSim PID 9344 (padre 16476); observador PID 14560 (padre 23780); verificar identidades reales antes de intervenir. No hay cierre ni aceptacion final.

Limpieza finalizada con codigo 0: 33 corridas anteriores eliminadas segun runtime/closure-20261102/cleanup-inventory.json y cleanup-result.json. Archivos inventariados: 105.119976 GiB; espacio libre realmente recuperado: 101.532082 GiB; libre al cierre: 198.911644 GiB. Las ocho regresiones migradas pasaron con las rutas historicas inaccesibles. Fixtures exactas y procedencia: tests/fixtures/simz1-history-v1/provenance.json. No son corridas aceptadas. Se preservaron fuentes, dependencias, OSM, variante L18 y diagnostico compacto de segunda avenida. Compilacion JDK17 y SimZ1FreightCompletionCheck: 0 (logs compile.log y freight-completion-java.log en runtime/closure-20261102).

Politica versionada: src/main/resources/simz1/freight-completion-v1.json. Entrada nominal sin cambios; finalizacion hasta cierre original +3600 inclusive; demanda hasta 24:00 y observacion hasta 30:00. Los excesos quedan separados de integridad y completitud. Sorteo independiente registrado: N=204186, compartido full-1/full-10; especificacion scenarios/zona1/experiments/final-20261102-v1.json. Solo max-test=220000 x 1 se ejecutara tras focales, Validate normal y DryRun real. Huella congelada vigente: 5ca33fffe7eb61035bf95d4d7ed8c2dbcad97fcf5c3927b390a2e68d884df092; recibo normal integrated_validate_pass vigente, completado 2026-11-02T23:46:36.6800242Z; identidades en runtime/closure-20261102/Validate-final-identities.json.

El intento historico c1c0dda877de4cfbb504f5baf3f82de1 sigue interrumpido/failed/invalid, ultimo evento completo 22224 s. Los 13 retrasos de 13..920 s caben retrospectivamente en la nueva tolerancia, pero no acreditan integridad ni cierre de esa corrida. La conclusion antigua de no reintentar por puntualidad nominal queda historica por la nueva autorizacion, sin atribuir otro defecto de prioridad.

Pruebas focales recientes: politica/analisis/paquete 61 pruebas (0), seleccion/preparacion/replay Python 38 (0), contratos finales 26 (0), JS dominio balanceado y navegacion 24-30/filtros (0), controlador nativo 33 comprobaciones hasta 108000 (0), QSim pequeno llegada corporal a 86416 s (0). Logs persistentes: runtime/closure-20261102/. Dos invocaciones de pruebas tuvieron nombres de modulos inexistentes; corregidas, sin fallos de las pruebas reales. No se interpretan como validacion masiva.

Compactacion adicional 2026-11-02: siete extractos redundantes eliminados segun runtime/closure-20261102/diagnostic-cleanup.json; hashes y referencias historicas conservados. Recuperacion observada adicional 482353152 bytes, afectada por preparacion concurrente. Las referencias antiguas a esos JSONL/CSV son historicas; el archivo compacto esta en tests/fixtures/simz1-history-v1/second-avenue. No se altera la evidencia de interrupcion ni la falta de cierre.

Preparacion intermedia: prepare-final-2.log termino 1 al solicitar full-1 sin massive explicito; ninguna simulacion se inicio. Se corrigio solo la invocacion de preparacion temporal y se conservaron/reutilizaron las tres carpetas ya verificadas. Continuacion: prepare-final-3.log; nueva carpeta para full-1. Esto no modifica la huella congelada.

Correccion de fixture: routing_observation_summary.json y reroute_trigger_timeline.csv seguian intactos en runtime/diagnostics/c529-a27d8bae5d. Copias exactas agregadas a c529-evidence y a la huella obligatoria; procedencia/hashes en c529-fixture-completion.json. C529-C y C529-D pasan (0), con rechazos esperados de rojo/reserva y mutaciones; siete pruebas de dependencias obligatorias pasan (0). C/D no leen la poblacion masiva: preservan sus fragmentos y resumenes reales en lugar de exigir un archivo plans.xml desechable no utilizado. No se debilita ninguna asercion fisica.

Segundo rechazo conservado: test_simz1_compact_motion.py usaba salida sintetica 0/enlace l con un actor tomado del roster real. El nuevo control de replay lo rechazo correctamente. Se mantuvo la geometria de serializacion explicitamente sintetica, usando identidad/enlace/hora del roster y agregando negativos por enlace/hora alterados. Prueba corregida: 0 (remaining-test_simz1_compact_motion.py.log). Se ejecutan las suites restantes y consumidores de motion antes de repetir Validate; no se cambia el motor. full-1: simz1-ce76b0a02831420ea82774f955fe7b83, plans SHA256 ce32e5531c5c04ee94dce6ba630c70d010d815151e58eecb3d8166628d465300.

Focales posteriores: 35 suites restantes del flujo vigente pasaron (0), detalle remaining-focals.json; no escriben recibo Validate. Consumidores de motion: 54 pruebas, dos errores demostraron que latest-attempt invalidado no contiene folder. Se corrigio selection_warning/select_run para reconocer la invalidacion, mantener la comprobacion propia de una corrida explicita y rechazar seleccion implicita sin referencia valida. Los dos casos afectados y la politica/negativos del selector pasan: 15 pruebas, 0 (selector-cleanup-regressions.log). Las otras 52 pruebas de consumidores pasaron antes del parche. No se modificaron punteros para fabricar una aprobacion.

Preparacion final cerrada 2026-11-02T23:34:01.139398+00:00: codigo 0; identidades y configuraciones en runtime/closure-20261102/prepared-final.json. No se ejecuto QSim en ninguno de estos cinco escenarios.

Siguiente accion: seguir el unico lanzamiento Run 220K x 1 hasta su preparacion, QSim y cierre natural cuando sea tecnicamente seguro; luego auditorias/productos. DryRun e9ce9f276dce4455905912d94681efcb aprobo (0), finalizo 2026-11-02T23:54:31.7482401Z y no creo carpeta de corrida. Cuotas verificadas: 96800 carros, 121000 motos, 2200 camiones +269 buses; particulares OD 108900/43560/43560/21780. Evidencia compacta DryRun-220K-identities.json. Seguimiento vigente: Get-Content runtime/closure-20261102/Run-220K.log -Tail 40; Get-Content runtime/launches/9da9ec50b78b45fe86550f81a558fa06/state.json. No lanzar otro Run ni otro observador. Historial de preparacion: el preparador PID 14360 termino 1 y la continuacion termino 0; ambos cerrados. Evidencia actual del hijo preflight del Run: runtime/closure-20261102/run-preflight-processes.json (PID 32092, padre 14716, creado 2026-11-03T00:02:04.2122700Z). No es QSim y estos PID deben volver a comprobarse antes de intervenir.

Preparacion de servicios verificada (prepared-services-all.json, codigo 0): las cinco configuraciones conservan los mismos 269 buses y 15336 expediciones, ultima salida 78968.329973 s; mismo hash semantico de salidas nativas y mismo roster publico. Carga por ventanas originales: quarter 184/266/100; half 368/531/201; full-1 y full-10 680/988/374. Todas las salidas permanecen dentro del dia; observacion configurada 30:00, full-10 termina en iteracion 9. Full-10 termino la validacion independiente con codigo 0; prepare-final-3.log confirma las cinco preparaciones y la paridad exacta de poblacion inicial. SHA256 plans.xml del par: ce32e5531c5c04ee94dce6ba630c70d010d815151e58eecb3d8166628d465300.

Contrato preparado 220K verificado (Run-220K-prepared-contract.json, codigo 0): 217800 particulares +2200 camiones +269 buses =220269 vehiculos configurados. Camiones por ventanas originales 732/1065/403; ultima salida 84408.72031854258 s. Buses: 269 vehiculos, 15336 expediciones, ultima salida 78968.329973 s. Demanda 0-86400, seguimiento hasta 108000, QSim un hilo, iteracion 0. Comparaciones seleccionadas por misma ruta/ventana y salida mas cercana: freight_000191 (east-west-14calle, 4128.805722677247 s) y freight_000522 (north-south-2avenida, 11253.02184763711 s); primera expedicion de ptbus_transmetro_L18_001. No se suponen identidades/cohortes iguales a 180K.

Seguimiento externo de solo lectura del Run vigente:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
Get-Content -LiteralPath 'runtime/launches/9da9ec50b78b45fe86550f81a558fa06/state.json'
Get-Content -LiteralPath 'scenarios/zona1/montecarlo/run-bg220-9da9ec50b78b45fe86550f81a558fa06/matsim-run.log' -Tail 30
Get-Content -LiteralPath 'runtime/closure-20261102/observer-220K.log' -Tail 1
```

El estado del lanzador agrupa preparacion/ejecucion/analisis y puede mantener run_id nulo hasta recuperar el manifiesto final; la identidad nativa vigente procede del manifiesto explicito anterior. El reloj nativo y la cobertura del lector se informan por separado. No iniciar otro observador.

Comprobacion de lectura anticipada: output/output_config.xml no estaba publicado durante QSim (Run-220K-effective-config-exit.txt=1, FileNotFoundError); queda pendiente contrastarlo al cierre mediante el flujo normal. No es rechazo de la simulacion ni se afirma activacion efectiva solo por la configuracion solicitada. Seguimiento externo -Evidence comprobado con codigo 0 en watch-live-check.log; no crea otro lector de eventos.

Incidencia auxiliar: la serializacion PowerShell del checkpoint consumio mas de 1.7 GiB para un log pequeno; se detuvo solo su PID 352 tras verificar creacion/padre/comando (checkpoint-helper-abort.json). QSim 9344 y lector 14560 siguieron activos. Se sustituyo esta operacion puntual por lectura acotada de 64 KiB de cada log y JSON simple; no se modifico codigo/insumo congelado ni se repitio QSim.

Hito de primera incorporacion (provisional, first-window-incorporation-prefix.json): cobertura del lector 17368.0 s, antes del cierre 18000; 627 completados nominales +105 activos =732 camiones incorporados, cero esperando incorporacion y cero errores tecnicos observados en ese prefijo. Los otros 1468 camiones pertenecen a ventanas posteriores. Esto no acredita finalizacion de la primera cohorte, tolerancia, dia completo ni aceptacion.

Primer prefijo real con tolerancia (2026-11-03T01:32:53.572283+00:00, first-window-tolerance-prefix.json): lector hasta 18405.0 s; primera cohorte 732: 639 nominales, 5 finalizados tolerados, 88 activos, 0 esperando incorporacion. Incumplimientos nominales conservados: 53. Excesos observados 0 y errores tecnicos/fisicos 0 SOLO en ese prefijo; experimental_acceptance=not_evaluable. No es aceptacion del dia ni de pendientes. QSim continua naturalmente.

Corte posterior al limite de primera ventana (first-window-deadline-prefix.json): cobertura 21670.0 s >21600; 639 nominales, 27 completados tolerados, 66 activos y 0 esperando incorporacion de los 732 de esa cohorte. Incumplimientos nominales originales observados: 93. Los activos siguen pendientes, sin inventar llegada ni retraso exacto; no acreditan cumplimiento del plazo. Experimental_acceptance sigue not_evaluable; QSim continua hasta cierre natural, sin interrupcion por puntualidad. No es aceptacion de integridad/completitud del dia.

Primer exceso completado observado (first-completed-excess-prefix.json): cobertura 21773.0 s; 639 nominales, 27 tolerados, 1 exceso(s) y 65 activos. Criterio experimental not_satisfied; errores tecnicos/fisicos observados 0 en ese prefijo. Se conserva QSim en curso para obtener cierre y diagnostico completos; no se transforma el exceso en aborto ni se interrumpe por este criterio. La identidad individual y el retraso exacto se conciliaran con el informe final, sin releer ahora eventos desde cero.

## Inventario resumido de corridas eliminadas

Corresponde solo al inventario congelado anterior a los nuevos escenarios. Las rutas canonicas, identidad, estado original, archivos, referencias, hashes y comprobaciones estan en runtime/closure-20261102/cleanup-inventory.json; las eliminaciones reales en cleanup-result.json. Resumen compacto: cleanup-summary.json. Ninguna fila representa una aprobacion para la revision nueva.

| Carpeta original (bajo scenarios/zona1) | Run ID | Estado original | GiB de archivos |
|---|---|---|---:|
| `montecarlo/run-1000-018bbffc8c5f49969c01119d6bb24bbc` | `simz1-e4de57f7c8a54045989322ed08b45123` | completed | 0.951245 |
| `montecarlo/run-1000-0a79921b1a8b45e1be602c96943d3449` | `simz1-7f55ad89a4dd485e996a5be73bea3e0d` | completed | 0.975858 |
| `montecarlo/run-1000-1c6fe2100a674df2ba8dffc4236a51cc` | `simz1-586749ab25a44dfd8c128f844b1ff613` | completed | 1.008499 |
| `montecarlo/run-1000-2bdc98fe0c1c4d44ba1338fb99d20534` | `simz1-d36953269fa04e6889deaff0bd217c89` | completed | 0.975468 |
| `montecarlo/run-1000-2fab376b0cbd4300b351a8e4a787c797` | `simz1-0694115cad2646519c0b82d878f9008c` | completed | 0.997592 |
| `montecarlo/run-1000-3f6bd582df7c4216aceb91c6b5aab5d8` | `simz1-957ff4092d244f6c84c56dc61832b17f` | completed | 1.005753 |
| `montecarlo/run-1000-40520266c5ea433c8b393992cf318449` | `simz1-316c093db1aa4d46b8f45cef832a3c89` | completed | 0.970755 |
| `montecarlo/run-1000-6825a46c686d4bd78934a34a4c7d2f67` | `simz1-cab0be90a1024922a00e38e9b9495f4d` | completed | 0.975152 |
| `montecarlo/run-1000-6ec810490b5c4e99bcce29978eaf885d` | `simz1-498beb684775467484e2857f9c034d00` | completed | 1.003007 |
| `montecarlo/run-1000-7e54e662108d4755ae2a5bed66b86a5b` | `simz1-bb33233fe9784baca87901ca66118957` | failed | 0.982371 |
| `montecarlo/run-1000-846ca411871e4c119fe0b05eb274df99` | `simz1-859a21753c1e4acd882842820873874e` | completed | 0.967889 |
| `montecarlo/run-1000-9319f8e611bb47999606c07c50b51642` | `simz1-24cec71def5a49f1ae98e244ca2bf9d2` | completed | 0.993754 |
| `montecarlo/run-1000-996056c7f01a49feb2466f7739a87a4d` | `simz1-e07d40ff23f44e53bb8262c70523a571` | failed | 0.748955 |
| `montecarlo/run-1000-c6cb7df12b364f6db55f2673941a8863` | `simz1-be464535c6f7425d9463b9af236c119a` | completed | 0.957881 |
| `montecarlo/run-1000-cursor-8ca9bc21577d423195c00c31e94ebfb0` | `simz1-4626ba5ae24c452dbcb7a8c24ebd3aa2` | completed | 3.003022 |
| `montecarlo/run-1000-eb1dfb21a24c46c38529fb71309acf89` | `simz1-f27cf67a57994f658159ef2b714b18bd` | completed | 0.973592 |
| `montecarlo/run-1000-ebbb17ea0e104a79ad80392f39a07009` | `simz1-7837e141e66047d69e4f19b492cc4da8` | completed | 0.971135 |
| `montecarlo/run-acceptance-1000-d57966b4563746dbbd488e850a47c5f8` | `simz1-b91ac0ecf901486984b477dbf8e15e6f` | completed | 0.597901 |
| `montecarlo/run-bg180-15c925016bde4b23abe3828450f53479` | `simz1-0efa3979342b4cb59437c27b387e58f0` | failed | 2.239347 |
| `montecarlo/run-bg180-590679ae2497441c84440d14f9530e83` | `simz1-3ddfb6868aee4c2591f48c09134a7051` | failed | 4.994928 |
| `montecarlo/run-bg180-65e9b78c2f9d4f4ca32de63226ca7acc` | `simz1-33fe51e7b903411386174435a3ad3207` | failed | 1.888155 |
| `montecarlo/run-bg180-c1c0dda877de4cfbb504f5baf3f82de1` | `simz1-9d7db3ba801841f9b501209229f58bfc` | failed | 1.745439 |
| `montecarlo/run-bg180-c52934de7de1435ebc85867e0b728f50` | `simz1-309d75ccb2d947629807a89d2e826987` | failed | 5.059311 |
| `montecarlo/run-bg180-dd9e2a9d64fc4764835fed6602faf191` | `simz1-8545ef106cbe43ce8fabb81bf0bc0a41` | failed | 1.326147 |
| `montecarlo/run-massive-pasante-10it-7676312b3fb84f98b238205695b6c641` | `simz1-faa2e00cfb384b308cc5814294fa5a9a` | failed | 15.617101 |
| `montecarlo/run-massive-pasante-10it-f8a2d66ecbc042829025996976df77df` | `simz1-2cccccb7c2b943d2b729681de8526ecc` | failed | 15.994005 |
| `montecarlo/run-scale-10000-8b1bd078f9f945e48bd4497902f2fba1` | `simz1-61458c9a17ef40428f170ee2f35f6f40` | completed | 1.778033 |
| `montecarlo/run-scale-10000-b7a9748dde06410cb55c52824056d399` | `simz1-894df1976a04445ab3201a850f884c5b` | completed | 1.775636 |
| `montecarlo/run-scale-40000-7f18a07a9eaf440e87e0f8464199fb5e` | `simz1-b9ae94a34280465f96fc531855fc3f17` | failed | 5.072334 |
| `montecarlo/run-scale-40000-e1d9985a83e94a9eb7379910437d7f92` | `simz1-bde45e0458cd4397a1f335a68a4f6efd` | failed | 7.943411 |
| `montecarlo/run-scale-40000-fda4e6147cce4521b143dc29fe80d97f` | `simz1-5a1670658fb74d1192d2902c57e7a310` | failed | 3.210983 |
| `montecarlo/run-scale-balanced-10000-it0-88a4a4ae488c4fcea3b706cfd8693a8e` | `simz1-4e2d3f2c11ad4324a4c29cbde006db80` | completed | 1.702025 |
| `montecarlo/run-z1-1it-cc6bd5666aff46a49456ccd5161cfd85` | `simz1-50c3836960014a32aed7b28a9c946597` | failed | 15.713293 |

Las nuevas carpetas prepared-final-* y la futura prueba 220K quedan fuera de este inventario. Los selectores antiguos que apuntaban a carpetas eliminadas se invalidaron con copia exacta de su contenido en invalidated-selectors; no se sustituyeron por otra corrida aprobada.

Planificacion de disco (final-resource-planning.json), basada en la retencion efectiva del lanzador y el preflight real max-test: 220K x 1 requiere 100 GiB libres (referencia de eventos 46.103 GiB incluyendo copia final); full-10 requiere 273 GiB, retiene 0..9 y copia final (referencia 235.340 GiB). Con 194.201 GiB disponibles al DryRun, full-10 no cabe en la guarda. Sus comandos estan implementados, pero requieren liberar/proveer espacio antes de ejecutarlos. Son estimaciones de planificacion, no cotas medidas del volumen futuro. No se bajo MinFreeGiB.

## Comandos manuales de la bateria final (no ejecutados)

Estos cinco escenarios no se ejecutan en esta tarea. Cada bloque es independiente; primero DryRun y solo despues Run si DryRun devuelve 0. La especificacion ya contiene N=204186; ninguna fase vuelve a sortearlo. Las diez iteraciones son 0..9 del mismo escenario diario, no diez dias ni diez veces N vehiculos unicos. FirstScaleTrial registra explicitamente la ausencia de Run1000; no lo fabrica ni omite Validate.

| Escenario | Clave | N no publico | Carros | Motos | Camiones | Buses adicionales | Iteraciones |
|---|---|---:|---:|---:|---:|---:|---|
| Solo buses | buses | 0 | 0 | 0 | 0 | 269 | 0 |
| Media de 220K | half | 110000 | 48400 | 60500 | 1100 | 269 | 0 |
| Cuarto de 220K | quarter | 55000 | 24200 | 30250 | 550 | 269 | 0 |
| Completa sorteada | full-1 | 204186 | 89842 | 112302 | 2042 | 269 | 0 |
| Misma completa | full-10 | 204186 | 89842 | 112302 | 2042 | 269 | 0..9 |

Antes de una ejecucion manual futura, si cambio la huella, renovar Validate con el comando normal (no repetirlo si sigue vigente):

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_simz1_110k_balanced_gateway.ps1 -Action Validate -JavaHome 'C:\Program Files\Java\jdk-17'
$rc = $LASTEXITCODE
if ($rc -ne 0) { throw "Validate rechazo la revision: $rc" }
```

### Solo buses

DryRun:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -ExperimentSpec .\scenarios\zona1\experiments\final-20261102-v1.json -ExperimentScenario buses -DryRun -FirstScaleTrial -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$rc = $LASTEXITCODE
if ($rc -ne 0) { throw "DryRun rechazo el escenario: $rc; no ejecutar Run" }
```

Run:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -ExperimentSpec .\scenarios\zona1\experiments\final-20261102-v1.json -ExperimentScenario buses -Run -FirstScaleTrial -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$rc = $LASTEXITCODE
if ($rc -notin @(0,3)) { throw "Lanzamiento incompleto: $rc; revisar sus logs, sin reintento automatico" }
if ($rc -eq 3) { Write-Warning "completed/valid con screening review_required; no es aprobacion experimental plena" }
```

### Carga media

DryRun:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -ExperimentSpec .\scenarios\zona1\experiments\final-20261102-v1.json -ExperimentScenario half -DryRun -FirstScaleTrial -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$rc = $LASTEXITCODE
if ($rc -ne 0) { throw "DryRun rechazo el escenario: $rc; no ejecutar Run" }
```

Run:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -ExperimentSpec .\scenarios\zona1\experiments\final-20261102-v1.json -ExperimentScenario half -Run -FirstScaleTrial -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$rc = $LASTEXITCODE
if ($rc -notin @(0,3)) { throw "Lanzamiento incompleto: $rc; revisar sus logs, sin reintento automatico" }
if ($rc -eq 3) { Write-Warning "completed/valid con screening review_required; no es aprobacion experimental plena" }
```

### Cuarto de carga maxima

DryRun:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -ExperimentSpec .\scenarios\zona1\experiments\final-20261102-v1.json -ExperimentScenario quarter -DryRun -FirstScaleTrial -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$rc = $LASTEXITCODE
if ($rc -ne 0) { throw "DryRun rechazo el escenario: $rc; no ejecutar Run" }
```

Run:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -ExperimentSpec .\scenarios\zona1\experiments\final-20261102-v1.json -ExperimentScenario quarter -Run -FirstScaleTrial -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$rc = $LASTEXITCODE
if ($rc -notin @(0,3)) { throw "Lanzamiento incompleto: $rc; revisar sus logs, sin reintento automatico" }
if ($rc -eq 3) { Write-Warning "completed/valid con screening review_required; no es aprobacion experimental plena" }
```

### Carga completa sorteada, una iteracion

DryRun:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -ExperimentSpec .\scenarios\zona1\experiments\final-20261102-v1.json -ExperimentScenario full-1 -DryRun -FirstScaleTrial -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$rc = $LASTEXITCODE
if ($rc -ne 0) { throw "DryRun rechazo el escenario: $rc; no ejecutar Run" }
```

Run:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -ExperimentSpec .\scenarios\zona1\experiments\final-20261102-v1.json -ExperimentScenario full-1 -Run -FirstScaleTrial -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$rc = $LASTEXITCODE
if ($rc -notin @(0,3)) { throw "Lanzamiento incompleto: $rc; revisar sus logs, sin reintento automatico" }
if ($rc -eq 3) { Write-Warning "completed/valid con screening review_required; no es aprobacion experimental plena" }
```

### Misma carga completa, diez iteraciones

DryRun:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -ExperimentSpec .\scenarios\zona1\experiments\final-20261102-v1.json -ExperimentScenario full-10 -DryRun -FirstScaleTrial -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$rc = $LASTEXITCODE
if ($rc -ne 0) { throw "DryRun rechazo el escenario: $rc; no ejecutar Run" }
```

Run:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -ExperimentSpec .\scenarios\zona1\experiments\final-20261102-v1.json -ExperimentScenario full-10 -Run -FirstScaleTrial -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
$rc = $LASTEXITCODE
if ($rc -notin @(0,3)) { throw "Lanzamiento incompleto: $rc; revisar sus logs, sin reintento automatico" }
if ($rc -eq 3) { Write-Warning "completed/valid con screening review_required; no es aprobacion experimental plena" }
```

### Seguimiento, analisis y visor de una corrida explicita

Los lanzadores imprimen LAUNCH EVIDENCE y guardan request.json, state.json y logs. Use el LaunchId de la corrida que acaba de ejecutar; no seleccione latest ni una corrida historica como reemplazo. Este bloque de lectura sirve para cualquiera de los cinco escenarios:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$launchId = Read-Host 'LaunchId explicito de 32 caracteres'
if ($launchId -notmatch '^[a-f0-9]{32}$') { throw 'LaunchId invalido' }
$state = Get-Content -LiteralPath (Join-Path 'runtime/launches' ($launchId + '/state.json')) -Raw -Encoding UTF8 | ConvertFrom-Json
$runDir = $state.run_directory
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch_simz1_110k.ps1 -LaunchId $launchId -Evidence -Iteration 0
$rc = $LASTEXITCODE
if ($rc -ne 0) { throw "Seguimiento rechazo la identidad: $rc" }
if (Test-Path -LiteralPath (Join-Path $runDir 'matsim-run.log')) { Get-Content -LiteralPath (Join-Path $runDir 'matsim-run.log') -Tail 40 }
```

Para lectura continua liviana del reloj nativo, use Get-Content -LiteralPath (Join-Path $runDir matsim-run.log) -Tail 40 -Wait. Si se desea el auditor incremental, iniciar una sola instancia de watch_simz1_110k.ps1 -LaunchId $launchId -Watch -Iteration 0, con su salida redirigida a un log. En diez iteraciones seleccione 9 expresamente cuando corresponda; la cobertura del lector puede ir atras del reloj nativo. No iniciar observadores duplicados.

Analisis y paquete de todas las iteraciones nativas completadas, sin MATSim; exige completed/valid e identidad exacta:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$runDir = Read-Host 'Ruta absoluta de la corrida completed/valid'
$runId = Read-Host 'run_id exacto de su manifiesto'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_with_analysis.ps1 -AnalysisOnly -RunDir $runDir -ExpectedRunId $runId -MinFreeGiB 100
$rc = $LASTEXITCODE
if ($rc -notin @(0,3)) { throw "Analisis/paquete pendiente: $rc; conservar la corrida y reparar esta fase" }
if ($rc -eq 3) { Write-Warning "Productos conservados; screening review_required" }
```

Preparar o reabrir el visor de una iteracion exacta (0 o 9 en full-10). La preparacion reutiliza las fuentes derivadas compatibles y nunca inicia QSim:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
$runDir = Read-Host 'Ruta absoluta de la corrida completed/valid'
$iteration = [int](Read-Host 'Iteracion exacta existente: 0; o 9 para full-10')
if ($iteration -notin @(0,9)) { throw 'Seleccion de entrega: 0 o 9' }
& .\.venv\Scripts\python.exe -B .\scripts\replay\prepare_replay.py --run-dir $runDir --iteration $iteration --sqlite-budget-gib 8 --scratch-budget-gib 4
$rc = $LASTEXITCODE
if ($rc -ne 0) { throw "Preparacion del replay fallo: $rc; no repetir QSim" }
& .\.venv\Scripts\python.exe -B .\scripts\replay\start_replay.py --run-dir $runDir --iteration $iteration --check-only
$rc = $LASTEXITCODE
if ($rc -ne 0) { throw "Contrato/identidad de replay invalido: $rc" }
& .\.venv\Scripts\python.exe -B .\scripts\replay\start_replay.py --run-dir $runDir --iteration $iteration --port 8792
$rc = $LASTEXITCODE
if ($rc -ne 0) { throw "Servidor/visor no abierto: $rc; revisar identidad del proceso o puerto" }
```

El puerto ocupado por otro servidor no autoriza terminarlo. Cada replay conserva Run ID, iteracion, manifiesto nativo y version independiente del posprocesador. Los controles permiten pausa, deslizador, +/-1 h, tipos e ID exacto de ruta; los filtros son seleccion visual explicita y no reducen los totales nativos. No se afirma prueba de navegador hasta realizarla.

El presupuesto de disco conserva eventos/planes de todas las iteraciones solicitadas y la copia final nativa. Se escala la referencia de eventos por N y 30/24, con reservas de SQLite, scratch, paquete e incertidumbre; MinFreeGiB=100 sigue siendo solo un piso. La guarda puede rechazar full-10 con el disco actual. No reducirla para forzar inicio.

## Historial anterior, conservado sin reinterpretar resultados

# SimZ1: reparación temporal y entrega de 180000

Estado HISTORICO 2026-11-02T20:52Z: tercer intento INTERRUMPIDO / INCOMPLETO / NO ACEPTADO, codigo 1. Se corrigio y probo la postergacion artificial entre cabezas de carriles; Validate y DryRun aprobaron (0). La nueva masiva redujo las infracciones de la primera ventana de carga de 26 a 13, pero sigue incumpliendo la aceptacion. La cadena lateral restante examinada concuerda con recepcion, FIFO y prioridad vigentes; no se demostro otro defecto que justifique una cuarta masiva. No se modificaron prioridades para forzar aprobacion. Todos los procesos propios terminaron; el observador acabo con codigo 0 a 20:42:38Z. Cobertura real: ultimo evento completo 22224 s (06:10:24), sin cierre XML ni trailer gzip. Sin screening, graficas oficiales ni visor de una corrida aceptada. Espacio medido: 97.9175 GiB frente a 100 exigidos. Siguiente accion admisible: reproducir la cadena con el bytecode conservado y definir una nueva correccion demostrada o revisar explicitamente el alcance de equidad del modelo antes de otra masiva; tambien debe superarse la guarda de disco.

## Cierre de esta continuacion: tercer intento y limite restante

Identidad: LaunchId `c1c0dda877de4cfbb504f5baf3f82de1`, run_id `simz1-9d7db3ba801841f9b501209229f58bfc`, iteracion 0. Carpeta `scenarios/zona1/montecarlo/run-bg180-c1c0dda877de4cfbb504f5baf3f82de1`. Huella vigente, nuevamente comprobada con el comando normal (0): `bb6d1453a566405281d76968e9470615ff0e1d66e8bd50d598511a190bb26563`. La huella no cambio durante ni despues de QSim. Los 43 hashes de insumos coinciden con el segundo intento, incluida la poblacion; las diferencias de config son rutas absolutas de la nueva carpeta. Se conserva la variante sintetica L18 y todas las reparaciones anteriores.

| Fase ejecutada | Resultado real |
|---|---|
| Fixture de arbitraje con bytecode del intento 2 | Falla 1: cabeza nueva desplaza a la antigua |
| Misma fixture con reparacion | Pasa 0; recepcion, rojo, FIFO y despeje conservados |
| Regresiones focales y siete negativas de huellas | Todas 0 |
| Validate `balanced-launch-323e5a564e2f4dfc8860d87694049ee4` | 0, recibo normal vigente |
| DryRun FirstScaleTrial `147670920dc74fbab225ef1ecd942b0c` | 0, MinFreeGiB=100 y JDK17 |
| Run del intento 3 | Iniciado; interrumpido tras documentar 13 infracciones irrevocables; salida 1 |
| Fixture causal lateral con bytecode conservado del intento 3 | Compilacion 0, ejecucion 0; sin parche adicional |
| Conciliacion de eventos del prefijo | 0; coincide con observador, sin acreditar cierre nativo |
| Screening, graficas oficiales y visor | No ejecutados: no existe corrida nueva completed/valid |

Evidencias bajo `runtime/2avenida-20261102/`: `Validate-process.json`, `Validate.log`, `DryRun-process.json`, `DryRun.log`, `Run-process.json`, `Run.log`, `Run-3-native-interruption.json`, `Run-3-input-preservation.json`, `regressions.json`, `protected-hashes.log`. La JVM propia 36460 se detuvo a 20:14:08Z despues de verificar PID, fecha completa, padre y comando; Maven/lanzador cerraron con 1. No se tocaron servidores del IDE. No hay restauracion de checkpoint ni continuacion artificial del prefijo.

### Cadena causal restante comprobada

`freight_000426` cumple en el intento 3: incorporacion 11225, llegada 15148; permanencia en el enlace 43 de 12490 a 13041 = 551 s, frente a 6195 s en el intento 2. La duracion total cambia de 7601 a 3923 s; las demoras se redistribuyen en otros enlaces. No se atribuye toda la diferencia a un solo mecanismo. `freight_000155` llega a 4639 s con margen corporal +1.477839 m y liberacion. La primera expedicion L18 completa 87/87 enlaces, 18000 a 18642 s, parada proxima de 25 s y ocho adquisiciones/liberaciones. Esto no acredita el servicio completo.

Entre los 13 camiones aun tardios, `freight_000546` permanece en `osm_48273209_11_forward` de 16646 a 17506 s. Al alcanzar la cabeza solo espera 3 s: el resto incluye recorrido y FIFO. La cabeza anterior `z1_160867` requiere un receptor lateral ocupado por `z1_84173`. Ese dominio ofrece 9.196815378 m utiles; dos cuerpos de 4.5 m mas sus separaciones de 0.10 m requieren 9.2 m. Rechazar al segundo es coherente con la capacidad actual: no se redondeo ni aumento almacenamiento.

`z1_84173` ocupa la recepcion desde 12464 hasta 17494 s y necesita el pasaje `osm_1272882108_1_forward -> osm_48273209_13_forward -> osm_48273209_14_forward -> osm_30279769_42_forward`. Sus 123 cambios registrados a `passage_control_or_crossing_wait` coinciden todos con un cruce principal ejecutado en el mismo segundo o en el siguiente; durante la retencion se registran 169 cruces principales. Son muestras de cambios de motivo, no 123 segundos ni toda la historia microscopica. No se atribuyen retrospectivamente campos que el WAIT no emitio.

La fixture `side-priority-pinned-_ui2f7yk/` usa red, carriles, controles y bytecode de produccion preservados del intento 3. Con condiciones iniciales focales declaradas, reproduce `priority_yield_conflict` frente a `freight_000424`; este cruza nativamente a 12529 y libera a 12537. Sin mas flujo principal, el lateral adquiere a 12609, atraviesa y libera a 12619; no quedan locks. No es una restauracion completa del estado historico. La fixture tuvo ajustes de preparacion documentados en sus logs anteriores: recurso de contrato ausente en el classpath, carga inicial fuera del principio del dominio y colas vacias que no se estaban escalonando; se corrigio la fixture, no produccion. La ejecucion final fija el bytecode y registra SHA256 de sus clases.

El contrato actual de `StopAndYield` concede equidad de 30 s a cabezas reales en el nodo de prioridad. El lookahead de un vehiculo retenido antes de un pasaje conserva la prioridad de los movimientos principales ejecutables; no le concede esa equidad en un nodo futuro. Esto explica el veto focal observado sin demostrar una reserva obsoleta. Extender la equidad a solicitudes de pasajes retenidos aguas arriba exige definir y validar ese supuesto del modelo; no se aplico como si fuera un bug demostrado ni garantiza por si solo cumplir las 13 ventanas. La evidencia tampoco prueba que la red real sea intrinsecamente inviable ni reparte toda la demora de los 13 camiones. No hay fundamento para repetir esta misma revision ni para modificar horarios, rutas fijas, cuerpos, capacidades o prioridades silenciosamente.

Fuentes: `Run-3-546-link11-fifo.json`, `Run-3-side-receipt-ownership.json`, `Run-3-side-priority-historical-check.json`, `Run-3-retention-conclusion.json`, `side-priority-pinned-_ui2f7yk/execution.json` y `result.json`. Reproduccion real, desde la raiz, sin masiva:

```powershell
& .\.venv\Scripts\python.exe -B runtime/2avenida-20261102/run_side_priority_check.py
```

### Conciliacion del prefijo, no cierre del dia

Fuente: `output/ITERS/it.0/0.events.xml.gz` del intento 3, 455653636 bytes; SHA256 `b89b750442264f7127216e83391e49305ffc4bff72ff4c465e857557317b0c99`. Ultimo evento completo 22224 s, linea 14688236. Gzip truncado, XML sin cierre: no CRC/cierre completo ni aceptacion. Se seleccionaron en una sola lectura adicional los eventos de ciclo de vida que faltaban para conciliar por clase; se conservaron en `Run-3-lifecycle-events.jsonl` para evitar nuevos escaneos. El ultimo timestamp no garantiza que todos los eventos de ese tick esten presentes.

| No publicos, vehiculos distintos | Programados | Incorporados | Completados | Activos al corte | Esperando incorporacion | Salida futura | Abortos observados |
|---|---:|---:|---:|---:|---:|---:|---:|
| Carros | 79200 | 3861 | 3332 | 529 | 1499 | 73840 | 0 |
| Motos | 99000 | 4816 | 4117 | 699 | 1904 | 92280 | 0 |
| Camiones | 1800 | 600 | 600 | 0 | 0 | 1200 | 0 |
| Total | 180000 | 9277 | 8049 | 1228 | 3403 | 167320 | 0 |

Completados + activos + esperando + futuros = programados. No incorporados = esperando + futuros = 170723. Abortos **finales** desconocidos/null: no hubo cleanup. Carga primera ventana: 600 completados y 13 fuera de horario, todos `north-south-2avenida`; los 1200 futuros no son omitidos. Publicos separados: 269 configurados, 240 vehiculos distintos incorporados, 219 con alguna llegada; 586 expediciones incorporadas, 463 completadas y 123 activas, sobre 15336 expediciones programadas para el dia. No sumar expediciones como vehiculos.

Datos diagnosticos conciliados: `Run-3-prefix-reconciliation.json`, `Run-3-prefix-counts.csv`, `Run-3-prefix-vehicles.csv`, `Run-3-remaining-violations.csv`. Incluyen identidad, iteracion, unidades, denominadores/cobertura y estado. Los tiempos de viaje de completados no representan los activos ni futuros. No se generaron PNG oficiales ni replay/servidor; no hay URL o comando valido para reabrir un visor de esta entrega.

Comparacion: intento 2 y 3 tienen los mismos insumos y primera ventana de 600; pasan de 26 a 13 infracciones, sin nuevos infractores fuera del conjunto anterior. No se compara este prefijo de 6 h 10 min con el cierre de 24 h de 5906 como si fueran el mismo intervalo. La tabla historica de 5906 se conserva mas abajo; no se releyeron sus 112936012 eventos. No hay prueba de mejora global del dia ni calibracion.

Checkpoint: `runtime/2avenida-20261102/current-checkpoint.json`; registro de intentos y estado global en `runtime/temporal-repair/attempts.json` y `delivery-status.json`. Pendientes: resolver la aceptacion de la primera ventana dentro de un alcance justificable, superar nuevamente recursos si hay reparacion nueva, y completar el dia, auditorias, graficas y visor. No se deja trabajo propio en segundo plano.

## Hitos anteriores de esta continuacion (historicos)

## Retención de 2.ª avenida: continuación tras reinicio

Recuperación y preservación: `runtime/2avenida-20261102/initial-state.json`, `initial-status.txt`, `initial.diff` e `initial-processes.json`. No sobreviven JVM ni observadores propios de los intentos anteriores. El Java del IDE se conservó. Se detectó una actualización externa de AGENTS.md durante el trabajo; se leyó y preservó, sin modificarla. El seguimiento externo es:

```powershell
Get-Content -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala\runtime\2avenida-20261102\progress.jsonl' -Encoding UTF8 -Tail 10 -Wait
```

Evidencia focal: extracción acotada de 107105 eventos de nodos/corredores hasta 17510 s, desde 8538196 líneas; `node-extraction.json` y `node-receiver-events.jsonl`. No es una validación completa del XML. Se reutilizaron el resumen de los 600 camiones y los extractos originales; no se releyeron los eventos de 5906.

`freight_000426` permanece 11308–17503 s en el enlace 43, cola `lane.1`, cuerpo 8 m y huella 8.1 m. Su cabeza se registra desde 11313 s. Mientras espera hay 54 admisiones desde `lane.0`, incluyendo camiones posteriores del mismo servicio y cuerpo, antes de su admisión. Por ejemplo, `freight_000438` obtiene el receptor a 12652 s con cabeza desde 12646 s; inmediatamente después el camión focal recibe `receiver_native_storage`. Ambos tienen la misma continuación fija y pueden solicitar el receptor original desde sus colas permitidas. El bucle anterior vaciaba `lane.0` antes de probar `lane.1`, sin arbitrar la antigüedad entre cabezas que compiten por el mismo espacio. Se demuestra postergación artificial; no se supone independencia física de los giros.

Los 928 rechazos `modeled_body_clearance` tienen un propietario reconstruible como la última admisión del mismo movimiento serializado, con frente registrado todavía inferior al umbral de despeje. No se observaron rechazos después del despeje en ese conjunto. Ejemplo: `freight_000490`, ordinal 137148, entra al receptor a 14018 s, slot 0; su frente queda en 9.427876 m hasta que alcanza la terminal y progresa a 24.522332 m a 14819 s. El umbral para 8 m es 11.101253 m (margen de entrada 3.001253 + cuerpo 8 + separación 0.10), referido al corredor 44, offset de entrada cero. No se compara con los 35.324391 m del enlace origen. Esos rechazos son coherentes con el ledger; no justifican liberar por tiempo. La identidad del propietario se **infiere** de admisiones serializadas y progreso: el evento histórico WAIT no incluía propietario, `notBefore` ni `clearFront`. Evidencia: `first-body-blockers.json` y `body-clearance-reconstruction.json`.

Reparación mínima en `Zona1QNodeImpl.moveLink`: con reservas corporales y varios carriles, ofrecer primero la cabeza nativa más antigua; actualizar la comparación después de cada extracción; un rechazo solo excluye ese carril durante la visita. Se conserva el camino original de turno, prioridad, recepción, conflicto y movimiento. Sin excepciones para IDs, giros iguales, carriles supuestamente independientes, ni cambios de liberación, flujo, cuerpos o tiempos. C529-A/B/C/D, llegada corporal y L18 se conservan.

`SimZ1LaneHeadArbitrationCheck` ejecuta selección real del nodo con colas, admisión y ledger de producción. Falla con código 1 usando el bytecode **preservado del segundo intento** (`arbitration-before-pinned-run2.log`) y pasa con el parche (`arbitration-after-5.log`, código 0). La cabeza más nueva sigue bloqueada antes del despeje; avanzar solo el reloj no libera; después del progreso nativo se sustituye el propietario. Rojo, receptor lleno y 240 consultas repetidas conservan cabeza/ruta/reservas. Son condiciones de fixture, no reconstrucción íntegra del QSim histórico.

Regresiones aprobadas (código 0, `regressions.json`): arbitraje, descarga independiente, FIFO paralelo con Controller, llegada corporal con Controller, parada bloqueante, despeje de cruce OSM y recepción/prioridad. Las siete negativas de huellas pasan (`protected-hashes.log`). Se revisó el diff de 24 líneas del nodo y se actualizó únicamente su hash esperado, conservando el hash histórico y el previo. La prueba nueva se incorpora a `prepare_simz1_runtime.ps1`; la huella normal incluye fuentes y prueba.

Alcance sobre las 26 infracciones: todas pasaron por el enlace 43; permanencias entre 5 y 6195 s, suma 22204 vehículo·s, medida por entradas consecutivas, **no** por WAIT. `freight_000434` permanece 5974 s; otros acumulan demoras en enlaces distintos. La corrección explica el mecanismo y oportunidades perdidas del caso focal; no demuestra que las 26 infracciones desaparezcan ni autoriza atribuirle toda mejora. `violators-link43.json` conserva la tabla completa. La masiva siguiente será la comprobación del experimento completo, si pasan las guardas.

Validate usa el lanzador normal: `runtime/2avenida-20261102/Validate-process.json` y `Validate.log`. No se ha escrito recibo de aprobación manual. Espacio inicial 98.57 GiB frente a 100 requeridos: se evalúa compresión transparente y sin pérdida únicamente de archivos propios cerrados, con SHA256 antes/después; sin borrar históricos ni modificar el sistema. La guarda de DryRun decide con una medición nueva.

## Estado recuperado previo al parche (histórico)

Estado activo 2026-11-02: Validate y DryRun completos APROBADOS (ambos código 0) para la revisión 4fa3bd9369f98eb525397fb9984456af5e23a00180c989613c43186818d51204. Segundo Run 180000 INTERRUMPIDO / INCOMPLETO / NO ACEPTADO, código 1; run_id simz1-0efa3979342b4cb59437c27b387e58f0. Se demostraron 26 infracciones de ventana de carga en north-south-2avenida, que impiden requireApproved. La retención causal aún se está reproduciendo; no se presume un defecto de software ni un límite físico. L18 y freight_000155 sí pasaron sus comprobaciones focales en esta masiva. JVM 33840, Maven 27504 y lanzador 18064 ya terminaron; el observador de lectura histórico (18228/37468, sesión 98815) tampoco sobrevivió al reinicio de VS Code. Recuperación verificada 2026-11-02T18:26Z: no hay procesos propios activos; su código de salida final es desconocido. Huella actual comprobada: 4fa3bd93…1204. Espacio disponible: 98.57 GiB, inferior a los 100 GiB requeridos para otra masiva. Snapshot inicial y seguimiento: runtime/2avenida-20261102/. No hay masiva activa, corrida aceptada, gráficas oficiales ni visor.

## Continuación autorizada: coordinación local de L18 (2026-11-02)

Nueva instrucción del usuario: corregir traducciones demostrablemente erróneas o, si los tiempos son sintéticos, crear una variante local explícita y versionada. Se conserva íntegro el trabajo anterior; snapshot del diff y hashes en `runtime/l18-local-20261102/prior-work.diff` y `prior-work-hashes.json`. No subagentes.

Los enlaces del tramo coinciden con la relación OSM 6245758 guardada y el bundle de L18; sus carriles permiten ambos giros. Los dos nodos constan como traffic_signals en OSM. Los ciclos/fases/offsets proceden de TrafficLightsGenerator (orientación geométrica, ciclo 80, offsets cero), no de mediciones de campo. No hay prueba para eliminar un control ni cambiar el recorrido. La parada Plaza Barrios/Fegua está trasladada por la representación nativa existente al enlace anterior P; debe incluirse en la prueba de aceptación.

Base de esta continuación: `43f66b6` (la reparación temporal anterior ya está incorporada; diff inicial vacío). La búsqueda concluyó: 6400 asignaciones de offsets examinadas, 5360 factibles, 1852153 prefijos físicos, siete restricciones temporales locales y 100 testigos por cuerpo/velocidad/carril. La variante explícita `l18-local-synthetic-offsets-v1` conserva 579787032=0 y cambia únicamente 333531372 de 0 a 60 s. Ciclos de 80 s, grupos, duraciones, ámbar, seguridad, geometría, cuerpos, servicios y paradas se conservan. No es programación observada en campo. La ventana de avenida previamente compatible disminuye de 39 a 19 ticks; la de L18 aumenta de 0 a 18. Se preserva factibilidad, no capacidad ni calibración.

Originales sin modificar: config-simz1.xml y signalControl.xml del access-review-v2. Variantes y procedencia/hashes: config-l18-local-v1.xml, signalControl-l18-local-v1.xml y l18-local-v1.json, en ese mismo directorio versionado. Propuesta completa: `runtime/l18-local-20261102/proposal.json`. El lanzador de 180000 selecciona expresamente la variante; el generador la registra en el manifiesto y copia su política. Los tres archivos forman parte de la huella normal. La coordinación automática sigue en `none` para balanced (igual que 5906); no se aplicó la propuesta genérica de cuatro cambios adicionales guardada únicamente como consulta en existing-coordination-parity.json.

Suite focal aprobada, código 0: `runtime/l18-coordination-9si6sjp7/results.json`. Controller/QSim ejecutó una expedición ORIGINAL completa de L18 (87 enlaces, salida 18000 s, llegada 18553 s, bus ptbus_transmetro_L18_001 de 13.5 m). Parada cercana 18518–18543 s: dwell 25 s. Pasaje afectado adquirido a 18547 s y liberado por body_clearance a 18552 s, después del mínimo 18549.702799675553 s. Prueba aislada de una expedición, no aprobación de 180000 ni de todo el servicio. Todas las 24 rutas públicas y cuatro de carga son compatibles en Java y Python; también los 100 testigos locales. Negativas nativas de receptor lleno, tercero en el conector y rojo: cero movimientos, reservas/ordinales conservados, consulta pura sin mutaciones. La prueba inicial de receptor lleno confundía contadores WAIT con reservas: se corrigió la aserción, sin cambiar admisión (antes código 1, después 0).

Preparación real de 100 no públicos aprobada con serialización/auditoría: 99 particulares, un camión y 269 buses; directorio preparation-100 dentro de esa suite. No es Run1000 ni se ejecutó QSim para esa demanda. Los originales históricos no se regeneraron.

Defecto adicional reproducido: verify_population llamaba al contrato OD sin la velocidad serializada y exigía otra vez la ruta nominal imposible (código 1, temporal-population-before.log). Corregido para usar maximumVelocity del tipo del vehículo en el XML, sin aceptar datos físicos ausentes. Regresión real: `runtime/temporal-population-kn5wr7uo/result.json`, código 0; conserva OD/identidad y rechaza tanto la ruta nominal imposible como la ausencia de velocidad. No relee eventos históricos. Cambios en simz1_population.py y test_simz1_temporal_population.py, incluido en Validate.

Primer Validate de esta continuación: código 1, balanced-launch-5322051a420842f9a932cc503a8fedd1. Causa: una fixture de repositorio mínimo omitía los tres nuevos archivos obligatorios de la variante. Corregidas las fixtures compartidas, conservando todas las negativas de mutación/ausencia y sin excluir archivos de la huella. Pruebas focales de huella: código 0 (fingerprint-fixtures.log y route-fingerprint-fixed.log). Registro en runtime/temporal-repair/attempts.json.

Segundo Validate: código 1, balanced-launch-2700bad55cfa402ea6cbc51dabe5d9f6, por la misma omisión en otra fixture (failure_cleanup). Después se revisaron TODOS los llamadores de fingerprint, incluidos los omitidos por las reglas de búsqueda. Las 15 pruebas focales y las comprobaciones de integración A/B/C/D pasaron, código 0: runtime/l18-local-20261102/all-fingerprint-fixtures.log.

Tercer Validate aprobado, código 0: balanced-launch-17c78cce90964b008c72be541850d91b. Recibo NORMAL en runtime/workflow/validated-balanced-gateway-v1.json, huella `6330c2baa7f99c56242f3d71593826f8bf0fbeeda0838eb31ffc3b76a46dd02d`. Log runtime/l18-local-20261102/Validate-3.log y estado/command en Validate-3-process.json. C529-A/B/C/D, ambas suites temporales, lectura de rutas reparadas, servicios, auditorías físicas, OD/OSM y lanzador pasaron. Único skip observado: test_reject_symlink (Symlinks unavailable). No se eludió ese permiso.

DryRun 180000 FirstScaleTrial aprobado, código 0: LaunchId 0613e931045b471f99653afdac294304, estado dry_run_pass/PASSED, run_id=null (no generó carpeta/población/QSim). Log runtime/l18-local-20261102/DryRun-180000.log y estado/command en DryRun-process.json. JDK17 y MinFreeGiB=100; 103.17 GiB disponibles. Pasaron memoria/commit/pagefile, preflight efectivo, huella y runtime. Se conserva la evidencia nativa del lanzador en runtime/launches/0613e931045b471f99653afdac294304.

Primer Run 180000 INTERRUMPIDO / NO ACEPTADO con FirstScaleTrial: LaunchId 65e9b78c2f9d4f4ca32de63226ca7acc; run_id `simz1-33fe51e7b903411386174435a3ad3207`, iteración 0. Carpeta scenarios/zona1/montecarlo/run-bg180-65e9b78c2f9d4f4ca32de63226ca7acc. Configurados: 178200 particulares + 1800 camiones + 269 buses; 15336 expediciones públicas programadas (no vehículos nuevos). plans.xml tiene EXACTAMENTE el mismo hash que 5906; también se conservaron los hashes de tipos, red, carriles, rutas, horarios y flotas. Diferencias registradas en runtime/l18-local-20261102/input-preservation.json: control sintético local, auditorías/implementación y rutas de configuración. Sin resorteo ni cambios de salidas/OD/identidades.

Procesos de este intento terminados y comprobados: lanzador 27968 (sesión 44168), Maven 30168 y JVM nativa JDK17/12G 39792, creada 2026-11-02T14:27:12.087Z como hija de 30168. Interrupción dirigida únicamente a esa JVM, verificando PID/padre/fecha/jar, registrada en runtime/l18-local-20261102/native-interruption.json. El lanzador propagó código 1. Los Java del IDE no se tocaron. Log Run-180000.log y estado/command Run-process.json en ese directorio. El lector de eventos se cambió de intervalo 15 a 1 s, sin tocar la simulación, y terminó con código 1 al detectar el defecto; ambos logs se conservan (observer-process.json, observer-fast-process.json).

Causa demostrada de la interrupción: freight_000155 llegó a t=4641 con dos motos precedentes en el mismo espacio corporal. El frente inferior nativo fue 2192.7548711580453 m desde el origen de su ruta; cuerpo de 8 m y separación de 0.10 m dejaban -2.922160925756998 m de despeje del perímetro. QueueWithBuffer procesó la llegada sin esperar el progreso físico limitado por esos líderes. Evidencia focal: freight-000155-events.json (1302 eventos del camión, extracción detenida en su llegada) y freight-000155-failure.json, contrastados con roster y geometría de hashes verificados. No se debilitó el auditor. El estado normal del lanzador registra fallo de Maven por la interrupción; native-interruption.json conserva su causa operativa real. Eventos incompletos, sin aprobación del prefijo ni conteos finales.

Siguiente acción: reproducir el cierre prematuro con las colas nativas, corregirlo y renovar las validaciones afectadas antes de otro intento. Ninguna masiva activa. La revisión del intento interrumpido permanece identificada por la huella 6330c2ba… completa arriba. Comando ejecutado: `scripts/run_simz1_180k_balanced_gateway.ps1 -Run -FirstScaleTrial -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100`.

Reparación del cierre prematuro implementada: QueueWithBuffer exige que el frente inferior del ledger alcance el extremo nativo de su cola antes de registrar llegada y liberar el cuerpo. SimZ1CorridorOccupancy expone una consulta pura; no adelanta cuerpos ni cambia el auditor. La espera conserva FIFO por carril y permite descargar un carril físico independiente en la cola original compartida; deuda, presupuesto de flujo, dimensiones, separación y reservas conservados. Cadena real confirmada en freight-000155-leader-chain.json: z1_119104 → z1_77220 → freight_000155, dos huellas precedentes de 2.2 m.

Regresión Controller/QSim nueva SimZ1ArrivalClearanceCheck: antes código 1, llegada prematura a 36 s, frente 82.1 m frente a extremo 85 m (arrival-before-3.log). Después código 0: el camión espera hasta 103 s y 85 m; sin líderes termina a 26 s sin esperar un rojo que no cruza. En el caso paralelo, el vehículo independiente cruza a 94 s mientras el camión sigue esperando; las ocho llegadas son nativas. Consultas positivas/negativas repetidas 240 veces no alteran estado ni eventos. Evidencia final arrival-final.log y carpetas native-arrival-clearance allí identificadas. Las dos primeras preparaciones de fixture se conservaron: una rechazó una configuración de prueba fast-capacity incompatible con señales; otra no reproducía el problema porque actividades compartían un dominio que exige inserción en vacío. No se contaron como prueba del defecto.

Diff de producción revisado y únicamente dos expectativas de hashes protegidos actualizadas, conservando hashes históricos, revisiones previas y negativas de mutación. La prueba nativa está incorporada al Validate normal. Huella de la reparación de llegada: `a7b48eaa93f27d6dc963692510e6be210a7af3f888955d5877769c38d45c917c`. Validación completa pendiente de esta revisión; el recibo 6330c2ba… pertenece al intento anterior. Siguiente fase: Validate → DryRun nuevo con FirstScaleTrial y MinFreeGiB=100 → Run nuevo únicamente si ambos aprueban.

Validate posterior al primer parche de llegada: código 1, balanced-launch-d1bb27b0905d441fb7d38ddfe734ccdb (Validate-arrival.log). La regresión de parada real detectó que peek consultaba llegada antes de atender la última parada del TransitDriverAgent nativo. Corregido el orden: mientras exista una parada pendiente, se conserva su ciclo nativo antes de consultar llegada. Después, BlockingStop, ArrivalClearance, IndependentLaneDischarge y ParallelOriginalFifo pasaron con código 0 (arrival-transit-regressions.json/.log). Huella revisada vigente: `4fa3bd9369f98eb525397fb9984456af5e23a00180c989613c43186818d51204`; requiere Validate renovado. No se lanzó otra masiva.

Las cuatro rutas de carga tienen margen corporal positivo al alcanzar el extremo nativo real: 62.5823, 60.5816, 1.47784 y 23.0034 m respectivamente; cálculo con geometría fijada y declaraciones nativas de dominio, en freight-native-terminal-margins.json. Es una condición estática necesaria, no cuatro viajes completados.

Espacio: se comprimió por archivo NTFS únicamente plans.xml del intento interrumpido propio, cerrado y failed. Misma ruta, 1114715724 bytes lógicos y SHA256 25e6877109eb0d0e947d71152c0fa25ecd745fbbc7696c58055010ce306638cc antes/después; almacenamiento físico 417169408 bytes. Se recuperaron aproximadamente 0.65 GiB sin borrar archivos ni alterar su contenido; sin cambios de configuración del SO o guardas. Evidencia workspace-file-compression.json. El siguiente DryRun debe volver a acreditar 100 GiB libres reales.

Validate renovado APROBADO, código 0: balanced-launch-f8ffb0b15890433b9fd7e998312941f9; log Validate-arrival-2.log y registro Validate-arrival-2-process.json. El flujo normal produjo runtime/workflow/validated-balanced-gateway-v1.json con huella 4fa3bd93… y fecha 2026-11-02T16:24:41.3544036Z. Incluye las nuevas pruebas de llegada/paradas, C529-A/B/C/D, temporalidad, L18, servicios, auditorías y contratos. DryRun siguiente iniciado con FirstScaleTrial, JDK17 explícito y MinFreeGiB=100. No editar código/insumos entre esta revisión aprobada y el siguiente intento.

DryRun renovado APROBADO, código 0, Launch 3407cf3643964a5c8410b0c4d3b41583. Sin QSim ni carpeta de simulación. Memoria disponible 15126614016 bytes físicos / 13832482816 de commit; disco 100.80 GiB, mínimo 100. Evidencias memory.json, retention-and-space.json y state.json del Launch, DryRun-arrival.log/process.json. Segundo Run autorizado iniciado a continuación por el flujo normal, con las mismas opciones y una identidad nueva; motivo comprobado: defecto de llegada prematura más prueba positiva/negativas y Validate renovado. Se preserva el intento incompleto anterior.

Segundo lanzamiento: 15c925016bde4b23abe3828450f53479, carpeta scenarios/zona1/montecarlo/run-bg180-15c925016bde4b23abe3828450f53479. A las 10:53 locales continúa la preparación de entradas; aún no hay inicio nativo confirmado ni run_id publicado. Guardas reales repetidas: 15009447936 bytes físicos / 13759946752 de commit disponibles y 100.80 GiB libres. Procesos propios: lanzador 18064, hijo PowerShell 1068, generador Python 27836 (bootstrap 31040). Observador de solo lectura PID inicial 18228 / sesión 98815, esperando manifiesto/eventos; logs Run-2-live.jsonl y Run-2-live-errors.log. La sesión del lanzamiento es 41830. Siguiente acción: comprobar inicio nativo y registrar identidad/PID; luego reconciliar el camión 000155 con sus eventos nuevos y seguir las métricas de circulación. No repetir lanzamientos ni editar código/insumos durante este intento.

Inicio nativo CONFIRMADO: run_id simz1-0efa3979342b4cb59437c27b387e58f0, iteración 0. JVM propia PID 33840, padre Maven 27504, creada 2026-11-02T17:00:43.715Z, JDK17 -Xmx12G, jar maven-exec5988978251144032407.jar. Evidencia de árbol/argv: Run-2-descendants.json. Compilación aislada en build de esta carpeta; fuentes e insumos congelados. Manifiesto: 180000 no públicos (178200 particulares + 1800 carga), 269 buses y 15336 expediciones públicas. La población conserva SHA256 25e6877109eb0d0e947d71152c0fa25ecd745fbbc7696c58055010ce306638cc, cuotas OD y perfiles. Run-2-input-preservation.json confirma 43 insumos iguales al intento anterior; difieren config y demand_report (identidad/rutas de archivos de esta ejecución). A 4320 s había 186 activos, 19 llegadas y 1219 transiciones en el último intervalo de 60 s: observaciones provisionales, sin aceptación ni resultados finales. Ya son DOS intentos masivos efectivamente iniciados; el primero permanece incompleto/interrumpido.

Comprobación focal en el segundo intento, código 0: freight_000155 incorporado a 4091 s y llegado a 4649 s. El mismo NativeGatewayAudit, geometría guardada y cuerpo 8 m + 0.10 m verifican frente modelado 213.95657821352864 m y despeje posterior +1.477839074243093 m; EXIT observado y sin reserva activa restante del vehículo. Antes: llegada 4641 s y despeje -2.922160925756998 m. Evidencia reproducible de dominios/eventos/insumos fijados: Run-2-freight-000155.json; lectura acotada a 2614879 líneas, 4.718 s, detenida al EXIT. No es aceptación global ni reemplaza la auditoría física completa. Una primera consulta auxiliar falló por pasar una ruta relativa a checked_path; se corrigió a ruta absoluta, sin tocar simulación ni insumos. A 11880 s la corrida seguía con 201 activos, 15 llegadas y 992 transiciones en el último minuto simulado.

L18 también pasó en la masiva nueva: ptbus_transmetro_L18_001, primera expedición original desde 18000 s, llegada 18802 s, secuencia exacta 87/87 enlaces. Parada próxima gis_station_6 a 18734–18759 s (25 s). Pasaje afectado ACQUIRE 18796 / RELEASE 18801, reserva 194852; mínimo temporal 18798.702799675553 y frente corporal 20.067246512321518 >= despeje 15.101869033553186. Estado nativo acredita cuerpo 13.5 m, separación 0.10 m y suficiencia de recepción. Ocho ACQUIRE/ocho RELEASE, sin pasajes pendientes; EXIT de ocupación observado. Código 0 en extracción y conciliación; Run-2-L18-first-duty.json conserva eventos y hash del horario fijado. Lectura hasta el primer EXIT: 9642211 líneas, 14.563 s. Esto acredita esa expedición, no las 650 de L18 ni aceptación global. A 20880 s: 747 activos, 50 llegadas y 3353 transiciones en el último intervalo de 60 s.

Segunda causa observada: 26 de los 600 camiones de la ventana 00–05 llegaron después de las 05:00; todos north-south-2avenida. Fuente acotada a t=21000: Run-2-first-window-freight.json (código 0, 12667351 líneas, 76.062 s); Run-2-first-window-violations.json detalla identidades, salidas, incorporaciones y llegadas. Otros 1200 aún futuros en ese corte, no se declaran omitidos ni completados. El primer intento de extracción llegó al EOF parcial porque no había eventos de carga después del corte; se corrigió el corte usando el reloj de todos los eventos, sin modificar fuentes ni simulación. Los resúmenes históricos de 5906 ya tenían 27 infractores completados en esa misma ruta/ventana; no se atribuye causalmente la diferencia de uno a los parches.

Retención focal: freight_000426 incorporó a 11225 y llegó a 18826 s (7601 s). Pasó 11308–17503 (6195 s) en osm_65777805_43_forward, 35.32439090646351 m y dos carriles; cola lane.1, control UNSIGNALIZED/free, nodo 12095723576. Evidencia: Run-2-freight-link-residence.json y Run-2-freight-retention-events.json (dos vehículos, hasta t=20300, 33.375 s de lectura). Registros del vehículo: 5192 receiver_storage_or_terminal_slot, 70 receiver_native_storage y 928 admission_conflict_executed tras turn_go, en ese enlace. Son intentos/razones registrados, NO segundos ni prueba suficiente de la causa. El frente modelado alcanzó 37.79136682984813 m; hay que reconstruir receptor, reservas y selección de carril. No se cambian horarios/rutas/cuerpos para resolverlo.

Interrupción controlada 2026-11-02T17:54:43.6884815Z: únicamente JVM propia 33840, padre 27504 y jar maven-exec5988978251144032407.jar; identidad contrastada con CIM y fecha de creación. La primera orden se negó por diferencia de precisión microsegundos frente a la fecha JSON en milisegundos, sin detener ningún proceso; la segunda comprobó la precisión original y ejecutó Stop-Process. Evidencia Run-2-native-interruption.json. Flujo normal terminó con código 1, sin gráficas oficiales ni aprobación. Último progreso completo t=27600 (07:40): 4859 activos, 26 llegadas / 2107 transiciones en el último minuto; no es estado final ni cleanup. La carpeta, eventos parciales, entradas, build, manifiesto y logs se conservan. El próximo trabajo es reproducir la retención de 2.ª avenida y corregir solo un defecto demostrado; NO lanzar una tercera masiva con esta revisión. La sesión 41830 ya terminó. Observador aún leyendo este prefijo: sesión 98815, procesos 18228/37468. No se ha iniciado una prueba nativa nueva de esta retención.

Revisión anticipada de presentación (solo lectura): el visor todavía llama al contrato histórico gateway-od desde simz1_motion.load_selected y simz1_continuous_replay, mediante simz1_gateway_od.validated_spatial_demand. Se deberá integrar la validación equivalente balanced-gateway-v1 cuando exista corrida aceptada, conservando huella nativa y versión propia del posprocesador. El análisis existente ya genera perfiles/completitud; el informe balanced-launch produce minutos/horas sin PNG operativos. Reutilizar esos componentes para completar los productos pedidos, sin repetir QSim por presentación.

La sección histórica siguiente corresponde al cierre anterior. Estado de entrega en runtime/temporal-repair/delivery-status.json; original preservado como runtime/l18-local-20261102/delivery-status-before.json. Sin resultados/PNG/replay/URL nuevos todavía; no sustituir por los históricos.

Conciliación adicional de la prueba nativa: 87/87 enlaces originales en orden; ocho pasajes adquiridos y ocho liberados, cero ordinales de pasaje pendientes. Evidencia: runtime/l18-local-20261102/native-route-and-release-reconciliation.json y affected-native-passage.json. Esto acredita la fixture, no el desempeño de la masiva.

---

Estado final al 2026-11-02: reparación focal probada y Validate integrado aprobado (código 0). DryRun 180000 bloqueado (código 1) por incompatibilidad demostrada del servicio fijo L18. No se inició una masiva nueva. No quedan procesos propios activos.

## Identidad y preservación

Base inicial limpia: `c429f1dd433edd8fb7170bf6cb3b49c83e687a59`; status/diff iniciales vacíos. C529-A/B/C/D eran trabajo previo incorporado. Sin subagentes, reset, borrados históricos, push ni cambios del SO.

Huella actual: `3c1e4d0551943b83757908385d571ad880d02a4315d4d64f7290755406a6d91f`. El flujo normal incluye las fuentes/pruebas nuevas; no se excluyeron archivos para aprobar.

LaunchId del DryRun nuevo: `44cf20b256c64e08baeef450a857e960`. Estado `blocked / configuration_preflight`; run_id=null y ejecución nativa no iniciada. Evidencia: `runtime/launches/44cf20b256c64e08baeef450a857e960/state.json`. La carpeta prevista `scenarios/zona1/montecarlo/run-bg180-44cf20b256c64e08baeef450a857e960` NO existe. Iteración solicitada: 0. El estado original del lanzador conserva source_fingerprint=null porque se detuvo antes de esa fase; la huella indicada arriba se verificó independientemente contra el recibo normal de Validate. Referencia histórica NO aceptada:

- Launch: `590679ae2497441c84440d14f9530e83`.
- Run: `simz1-3ddfb6868aee4c2591f48c09134a7051`.
- Carpeta: `scenarios/zona1/montecarlo/run-bg180-590679ae2497441c84440d14f9530e83`.
- Huella: `08e2c4c77c9daa17faed8ac658be383589ebddf74fc428c2b2fab98c185ac3fa`.
- Estado: failed/invalid; FREIGHT_NOT_APPROVED, restricted=89, carga completada=600/1800, activos antes de cleanup=6311.

## Experimento conservado

180000 no públicos: 79200 carros, 99000 motocicletas, 1800 camiones de 8 × 2.3 m. Además 269 buses: 176 Transmetro y 93 TuBus. Particulares 178200; cuotas EE/EI/IE/II=89100/35640/35640/17820. balanced-gateway-v1/access-review-v2, semilla 20261023, fecha 2026-10-23, iteración 0, JDK17/.venv. Horarios, horizonte, señales, rutas fijas, dimensiones, separación 0.10 m, FIFO, geometría, capacidades y restricciones OSM conservados. Geometría aproximada, no cartografía GIS verificada.

## Cambios nuevos

- `Zona1SignalGreenWindow`: COMPATIBLE/IMPOSSIBLE/UNKNOWN, controladores distintos, ciclos, offsets y ámbar/despeje nativos. Período común exacto acotado a 100000 ticks; lo no soportado no prueba imposibilidad. Caché con fases efectivas y parámetros de consulta.
- `SimZ1PassageTiming` / `QueueWithBuffer`: comparten la fórmula nativa existente del presupuesto, sin contar otra vez el ámbar.
- `SimZ1CorridorOccupancy`: reutiliza dominios, routeReach, márgenes y carriles hasta una recepción donde cabe el cuerpo. Consulta sin crear reservas/eventos. Conserva admisión física y rechaza incompatibilidad permanente en el pasaje.
- `SimZ1RouteSafety` / `SimZ1TurnRouter`: búsqueda con estado OD, secuencia OSM y contexto físico simultáneos; sin eliminar globalmente un giro válido para otro cuerpo/aproximación.
- `CongestionAwareRerouting`: detección conectada a selección y al único camino de instalación, attempt(). Reparación de una ruta imposible con alternativa compatible aunque su costo nominal sea mayor; mejora estricta entre factibles. Cohorte, presupuesto, cooldown y acumulación C/D conservados.
- `simz1_temporal_passage.py`, generador y auditoría OD: paridad física/temporal, reparación del par ya seleccionado sin resorteo ni cambio de salida, registro de rutas/personas/motivos y cachés por configuración efectiva y parámetros físicos.
- `simz1_effective_access.py` y `simz1_freight.py`: auditoría de servicios fijos. `simz1_balanced_launch.py` aplica al XML derivado las mismas opciones que antes solo comprobaba en un diccionario.

Se conservaron señales, servicios, OSM e insumos históricos. Expectativas de huellas actualizadas de forma exacta y revisada, manteniendo el baseline y negativas. QueueWithBuffer sigue protegido; QLinkLanesImpl, idéntico al histórico, es el ejemplo sin cambios de la fixture de mutaciones.

## Pruebas observadas

| Verificación | Resultado / evidencia |
|---|---|
| Compilación JDK17 con mvnw.cmd -q -DskipTests test-compile | Código 0; runtime/temporal-compile.log |
| C529-A/B/C/D | Todos código 0; runtime/temporal-repair/regressions.json |
| Detección/búsqueda Java, ReRoute estándar y paridad Java/Python | Código 0; runtime/temporal-passage-r1l9ajap/focused-results.json |
| Selección real → búsqueda → attempt → instalación → movimiento nativo | Código 0; installation-result.json en esa carpeta |
| Rojo temporal sin mutación de ruta/cursor/reservas | Código 0; red-rejection.json en esa carpeta |
| Ciclos/offsets, ventana insuficiente, desconocido y caché al cambiar offset | Código 0 en la suite temporal |
| Reparación inicial Python con accesos efectivos reconstruidos/verificados | Código 0; runtime/temporal-repair/python-initial-result.json |
| Preflight balanceado 180000 | Rechazo de L18; NO aprobación |
| Preflight del experimento 180000, CLI real | Código 1 por L18; runtime/temporal-repair/experiment-preflight.json y .log |
| Preparación real pequeña 100 | Rechazada por L18; no demanda aceptada, Run1000 ni QSim |
| Controller/QSim sintético N=3/B=2 y regresiones nativas de reservas | Pasaron dentro de Validate; no certifican la masiva real |

La fixture integrada conserva cursor por ocurrencia (38→39), prefijo, destino, OD y secuencia 17478998. Costo viejo 8.367608 s frente a 245.094750 s de la alternativa compatible de 122 enlaces, encontrada por búsqueda. Movimiento nativo a osm_1056144032_0_forward, avance suficiente para 4.6 m, dominio anterior vacío y sin locks residuales. Acredita recepción corporal local, NO llegada de los 122 enlaces. La cohorte se demuestra en una fixture determinista de dos personas, no se atribuye al vehículo de la masiva histórica.

Python repara desde el origen original una ruta nominal de 45 enlaces IMPOSSIBLE a otra de 88 COMPATIBLE, con mismos extremos/OD/cuerpo, metadatos válidos y árbol nominal del sorteo intacto. Script reproducible: runtime/temporal-repair/check_python_initial.py. No se regeneró demanda ni ejecutó QSim.

## Bloqueo del escenario

transmetro_L18 / L18_6245758_part1, cuerpo 13.5 m, 29 vehículos y 650 expediciones programadas:

`osm_420120098_2_forward → osm_420138103_0_forward → osm_1056730555_0_forward`.

El receptor del bus es distinto del receptor particular. El conector ofrece aproximadamente 3.919593 m detenibles. Dos controles de ciclo 80 s, offsets cero y fases 49–78 / 0–47 carecen de permiso conjunto con la semántica nativa. Las otras 23 rutas públicas y las cuatro de carga de 8 m son temporalmente compatibles; no implica garantía de descarga dinámica.

Evidencia: runtime/temporal-passage-r1l9ajap/fixed-service-java.json, fixed-service-python.json y fixed-native/signal_fixture_cycle.csv. Fixture nativa con dominio receptor completo: 240 ticks, receptor disponible, cero movimientos, cero permisos simultáneos y motivo passage_incompatible_signal_phases. Prueba necesaria de paso sin dwell, no servicio completo.

Resolverlo exige revisar una ruta fija, sus señales o el contrato físico, que el alcance actual exige conservar. No se alteraron silenciosamente ni se gastó otra masiva con esa contradicción.

## Registro y fases

| Fase | Identidad / estado |
|---|---|
| Primer ensayo de preflight | runtime/temporal-passage-kyb1h69z: detectó XML con wholeVehicleReservation=false; corregido. Sin masiva. |
| Primer Validate | balanced-launch-2da2d188bd7e4f56a5e1de17e3374aee: código 1 por conteo duplicado de fixture de huellas; corregido sin exclusiones. Log runtime/temporal-repair/Validate-integrated.log. |
| Regresiones repetidas | C529-A/B/C/D y suite temporal: código 0; no recibos artificiales. |
| Segundo Validate | balanced-launch-3559b59f007b439d8669dca6c096e94b: código 0; recibo normal runtime/workflow/validated-balanced-gateway-v1.json. Log runtime/temporal-repair/Validate-integrated-2.log. |
| DryRun FirstScaleTrial | Launch 44cf20b256c64e08baeef450a857e960: código 1, BLOCKED/configuration_preflight por L18. Log runtime/temporal-repair/DryRun-180000.log. |
| Run 180000 | No ejecutado tras DryRun fallido; sin run_id ni carpeta de masiva nuevos. |
| Auditorías finales / screening | No ejecutados para masiva nueva; no completed/valid ni screening pass/review_required nuevo. |
| Gráficas / visor | No generados: no hay corrida nueva aceptada. Sin URL/PID de visor nuevo. |

La guarda real del DryRun pasó: 32 GiB instalados, 14156427264 bytes físicos y 13203992576 de commit disponibles, pagefile automático de 7 GiB, heap QSim 12 GiB y reserva prevista de crecimiento del pagefile de 4 GiB. Espacio: 103.65 GiB libres, 100 GiB exigidos, incluyendo presupuestos de eventos/análisis/replay. Evidencia memory.json y retention-and-space.json dentro de la carpeta del Launch. Esto es planificación, no pico observado ni garantía de escalabilidad. MinFreeGiB=100 conservado; sin cambios del SO.

Procesos propios pendientes: ninguno, comprobado tras finalizar el DryRun. Los dos procesos Java restantes pertenecen a los servidores del IDE y no se tocaron. No se ejecutó Run tras el rechazo ni se repetirá la misma revisión sin cambios. La continuación requiere resolver explícitamente la incompatibilidad del servicio fijo fuera del alcance actual. Comando focal reproducible: `& .\.venv\Scripts\python.exe -B python\test_simz1_temporal_passage.py --preflights`; actualmente prueba el rechazo, no habilita Run.

Comandos ejecutados, con JDK17 explícito y códigos propagados:

```powershell
& .\scripts\check_simz1_110k_balanced_gateway.ps1 -Action Validate -JavaHome 'C:\Program Files\Java\jdk-17'
& .\scripts\run_simz1_180k_balanced_gateway.ps1 -DryRun -FirstScaleTrial -JavaHome 'C:\Program Files\Java\jdk-17' -MinFreeGiB 100
```

Registro de fases e intentos: `runtime/temporal-repair/attempts.json`. Cero intentos masivos. No existe un comando válido para reabrir un visor de esta entrega: no se generó replay ni servidor de una corrida nueva aceptada.

## Comparación con 5906

No hay resultados observados de una masiva nueva. Sus campos programados/incorporados/completados/abortados/pendientes son null en runtime/temporal-repair/delivery-status.json; no equivalen a cero.

Referencia histórica failed/invalid, iteración 0, vehículos únicos no públicos:

| Grupo | Programados | Incorporados | Completados | Activos antes de cleanup | Pendientes antes de cleanup | Abortados finales |
|---|---:|---:|---:|---:|---:|---:|
| Carros | 79200 | 6217 | 3559 | 2658 | 72983 | 75641 |
| Motos | 99000 | 7798 | 4410 | 3388 | 91202 | 94590 |
| Camiones | 1800 | 662 | 600 | 62 | 1138 | 1200 |
| No públicos | 180000 | 14677 | 8569 | 6108 | 165323 | 171431 |

Antes de cleanup: completados + activos + pendientes = programados. Al cierre: completados + abortados = programados. No sumar abortados a activos/pendientes: corresponden a momentos distintos. Pendientes se calcula como programados menos incorporados en estos viajes únicos.

Fuentes: runtime/diagnostics/5906-h0kzpokz/comparison.json, freight_summary.json y resúmenes verificados. Solo se amplió la lectura al CSV 0.simz1-trips.csv.gz para confirmar abortos particulares: 178200 personas distintas, cero duplicados, 170231 censurados con aborto registrado. Evidencia: runtime/temporal-repair/historical-trip-reconciliation.json. No se releyeron los 112936012 eventos.

Públicos históricos separados: 269 configurados, 268 vehículos incorporados distintos, 194 con alguna llegada; 1291 expediciones incorporadas, 1088 llegadas y 203 activas antes de cleanup. No sumar expediciones como vehículos. No se atribuye mejora global a un parche sin una corrida nueva.

Datos: runtime/temporal-repair/historical-comparison.csv y delivery-status.json. Son referencia histórica/estado de reparación, NO resultados de una corrida nueva aceptada. Sin PNG, replay ni visor nuevos. Pendientes: aceptación de 180000, análisis, gráficas y comprobación del visor, sujetos a resolver el bloqueo y superar guardas.
