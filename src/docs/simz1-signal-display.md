# Semáforos legibles en SimZ1 continuo

Revisión del 2026-10-22. Solo presentación del visor continuo. No cambia grupos,
programación, offsets temporales, prioridades, carriles nativos ni física MATSim.
No se regeneran corridas, SQLite, eventos, planes, HTML históricos ni manifiestos.

## Causa y cambio

`SimZ1SignalGeometry.layers()` agregaba `signal-state-labels`, una `TextLayer`
con `getSize`, `sizeMinPixels` y `sizeMaxPixels` fijos en 11. `stateProps()` usaba
`label()` para devolver R/A/V, R+A, OFF o ?. Simultáneamente, el cuerpo tenía
`sizeScale: 1` y una cabeza de 0.65 × 1.3 m, con luces de radio 0.12 m.
**No existía un umbral de zoom que sustituyera la malla:** la anotación conservaba
su tamaño mientras la malla proyectada desaparecía al alejarse.

Se elimina esa capa y sus accesores textuales. Ahora se usan tres capas WebGL
constantes: cuerpo/poste, postes sin dirección verificable y luces. Las mallas
se comparten mediante instancing. Los estados actualizan únicamente el color.

La cabeza tiene únicamente tres luces circulares frontales. Se retiraron la
caja horizontal superior y sus tres luces `top_repeater`, que producían una
segunda cabeza con silueta en L. El cuerpo contiene solo poste y cabeza vertical;
la capa de luces contiene tres instancias por señal. La capa de iconos histórica
se sustituye al cargar el visor, sin superponerla a las mallas.

Es un símbolo visual, no un modelo de un poste levantado en campo. No gira hacia
la cámara: cara frontal opuesta a la tangente terminal del enlace entrante y eje
vertical +Z. En una vista exactamente cenital se ve el borde superior de la
cabeza; las luces frontales siguen en su plano vertical y no se duplican arriba.
La eliminación del repetidor no filtra señales nativas ni fusiona otros accesos.

Se proyectan puntos de soporte del cuerpo y se ajusta **un escalar uniforme**
por instancia, incluyendo las traslaciones de las luces. Posición de apoyo y
rotación geográfica permanecen constantes. La envolvente en pantalla se limita
a 18–22 píxeles desde lejos y 24–34 píxeles en detalle. Se consideran posición,
perspectiva, inclinación, rotación y tamaño del viewport. El cálculo se reutiliza
mientras no cambie la cámara; no se ejecuta por cada tick del replay.

Las matrices usan las unidades de
[SimpleMeshLayer 9.1.14](https://github.com/visgl/deck.gl/blob/v9.1.14/modules/mesh-layers/src/simple-mesh-layer/simple-mesh-layer-vertex.glsl.ts)
y la proyección de
[WebMercatorViewport](https://deck.gl/docs/api-reference/core/web-mercator-viewport).
La escala visual no se escribe en datos de simulación.

## Anclas y agrupación

El exportador histórico colocaba las señales 18 m atrás y 8 m a la derecha
usando la recta entre extremos del enlace. Ese desplazamiento no era evidencia
de la posición real de un poste y podía salir de un enlace corto o curvo.

El ancla de presentación se deriva ahora del **mismo enlace controlado** y del
borde derecho de los carriles que dibuja `SimZ1VisualLanes`: 0.5 m de separación
visual y retroceso de hasta 3 m, limitado al 35 % del último segmento no
degenerado. Respeta las separaciones de sentidos opuestos y la altitud guardada.
`position` original queda intacta; `Signal_Geometry.anchor` contiene el apoyo
visual y `placement` documenta procedencia, desplazamiento y medidas asumidas.
Sin evidencia suficiente se conserva un poste sin rumbo y un diagnóstico.
El filtrado del dominio usa el ancla corregida.

Desde lejos se elige una señal real por `to_node`, priorizando el acceso con
más carriles registrados y usando IDs como desempate estable. Su color es
**el estado de ese acceso**, no una fase agregada de la intersección. El tooltip
enumera los estados de sus miembros. Se muestran todos los accesos al alcanzar
zoom 16.6 y se vuelve al resumen por debajo de 16.2; al iniciar, corte en 16.4.
Nunca se fusionan nodos distintos por cercanía en pantalla. La rotación no cambia
la señal representativa. Solo se descartan instancias fuera del viewport ampliado.

Inspección local, exclusivamente de metadatos y red efectiva verificada:

- Fuente: `runtime/simz1-227187-direct/webgl-continuo`, `sqlite-direct-v1`.
- Corrida: `simz1-0dd152dabbc24d1d84d9b738c449cc35`, iteración 0, 227187 personas.
- 312 señales, 312 enlaces controlados y 163 nodos semaforizados.
- 312 anclas visuales corregidas, ninguna señal sin dirección verificable.
- Desplazamiento respecto del icono histórico: 15.13–18.08 m; mediana 16.36 m.
- Ningún nuevo apoyo quedó antes o después del segmento terminal controlado.

La geometría y los márgenes de presentación son aproximados; no constituyen
cartografía GIS ni posiciones de postes verificadas en campo.

## Pruebas

Ejecutadas sin navegador, servidor ni MATSim:

```powershell
node .\python\test_simz1_signal_geometry.cjs
node .\python\test_simz1_continuous_bootstrap.cjs
node .\python\test_simz1_transit_stops.cjs
& .\.venv\Scripts\python.exe -B .\python\test_simz1_client_identity.py
git diff --check
```

Pasan: zoom 12/14/16/17/19/22; pitch 0/30/45/60/80; bearing 0/37/90/180/270;
proyección con perspectiva, diferentes posiciones y resize; límites comprobados
también sobre los vértices transformados de las mallas; accesos opuestos,
curvos y cortos; altitud y anclas originales; colores RED/YELLOW/GREEN/REDYELLOW,
OFF/UNKNOWN; eliminación de letras; agrupación e histéresis; estados de miembros
con fases distintas; exactamente una cabeza y tres discos circulares frontales
por señal; accesos opuestos en un mismo nodo preservados; ausencia del repetidor
en vértices, matrices y capas; 800 señales en 200 nodos y tres capas compartidas; ausencia
de reconstrucción con cámara quieta; carga inicial antes de que Deck esté listo,
pausa, seek inverso, cambio de ventana al mismo instante y diagnóstico completo.

Las suites generales siguientes fallan también al cargar los controles de HEAD
anteriores a este cambio, sin reemplazar archivos del árbol de trabajo:

| Suite | Fallo preexistente reproducido |
| --- | --- |
| `test_simz1_continuous_replay.cjs` | `future route stops at day closure`, 0 frente a 1 |
| `test_visualizador_z1_controls.cjs` | `window is not defined` en el contexto de prueba |
| `test_simz1_render_performance.cjs` | `stationary rows do not invalidate GPU attributes` |

**Pendiente:** aspecto real en WebGL, oclusiones con tráfico, FPS y memoria GPU.
Las pruebas numéricas no se presentan como capturas ni como mediciones GPU.

Revisión manual preparada para después del reinicio: centrar una intersección
con sentidos opuestos; revisar zoom lejano, medio y máximo, con pitch 0 y 45/60,
girando 0/90/180/270. Verificar cuerpo y círculos legibles, apoyo en el borde del
acceso, poste vertical, rumbo constante, colores nativos, ausencia de letras y
carriles legibles al máximo. Al alejarse debe quedar un acceso representativo
por nodo; al acercarse deben reaparecer todos. Repetir en un acceso corto/curvo.

En DevTools, este bloque consulta el estado actual sin alterar datos:

```javascript
const api = window.simz1Continuous;
const signals = api.getSignalDiagnostics();
if (signals.version !== 'simz1-single-head-signals-v3' ||
    signals.run_id !== 'simz1-0dd152dabbc24d1d84d9b738c449cc35') {
  throw new Error('Verificar corrida y recargar el cliente actual');
}
console.table(signals.rendered.map(({signal_id, Link_ID, scale, extent}) =>
  ({signal_id, Link_ID, scale, pixels: extent})));
console.table(signals.states);
console.log(signals.clusters, signals.issues);
console.log(api.getRenderPerformance().features.work);
```

Para recorrer las cámaras exactas, usar manualmente
`api.deck.props.onViewStateChange({viewState: {...api.getState().camera.viewState,
zoom: 17, pitch: 45, bearing: 90}})` cambiando los tres valores de la matriz.
Registrar `signalViewCpuMs`, `signalViewUpdates`, tamaño de las tres capas y
FPS/GPU mediante DevTools, tanto en pausa como reproduciendo 1x/120x. La pausa
sin cambios de cámara no debe aumentar `view_builds` en los diagnósticos.

## Reiniciar el mismo replay

Detener manualmente el servidor anterior con Ctrl+C en su consola y ejecutar
desde la raíz del repositorio:

```powershell
& .\.venv\Scripts\python.exe -B .\python\serve_simz1_continuous.py --directory .\runtime\simz1-227187-direct\webgl-continuo --port 8793
```

Después recargar la pestaña. El servidor ensambla las fuentes actuales al arrancar;
no hace falta regenerar HTML, SQLite ni datos. Este comando **no fue ejecutado**
durante la revisión. Tampoco se abrieron navegadores ni se hicieron commits/push.
