# Navegacion temporal del replay existente

El servidor abre el SQLite publicado en modo `ro&immutable=1`. Abrir o navegar
el visor no ejecuta MATSim, no regenera exportaciones y no cambia la aceptacion.
El lanzador sigue siendo `scripts/replay/start_replay.py`, con `--run-dir`,
`--iteration`, `--replay-dir` y un puerto libre explicitos. Un proceso que ya
estaba iniciado conserva su codigo: usar un puerto nuevo para probar cambios.

## Espera, prioridad y cancelacion

- Se mantienen como maximo dos consultas distintas. Las peticiones del mismo
  indice y la misma identidad comparten el calculo y la respuesta comprimida;
  como maximo ocho seguidores esperan al propietario de cada consulta.
- `priority=demand` es el valor predeterminado compatible con los clientes
  anteriores. El lector SQLite usa dos procesos con caches acotadas; la precarga
  puede ocuparlos mientras no haya una demanda pendiente. El lector legado
  conserva una plaza para navegar. Una demanda sin plaza interrumpe cooperativamente
  una precarga, cuya respuesta 503 permite reintentar si todavia interesa.
- La cancelacion de `fetch` se comprueba tambien en el servidor. Cuando todos
  los clientes de una consulta se desconectan, sus bucles Python y su lector
  SQLite abandonan el trabajo. Un seguidor todavia conectado conserva el
  calculo compartido. Nunca se publica una ventana parcial cancelada.
- No hay un plazo maximo impuesto al calculo de una peticion conectada.
  Un 503 con `retryable: true` mantiene la hora solicitada y se reintenta
  respetando `Retry-After`, con espera creciente hasta diez segundos entre
  intentos (o el minimo mayor indicado por el servidor). No se agota una cuota
  fija de reintentos. Las consultas SQL fallidas devuelven 500 y su causa;
  `retryable: false`, errores de integridad y perdida de conexion ofrecen
  reintento manual sin sustituir el ultimo fotograma validado.
- El cliente conserva como maximo tres ventanas y dos peticiones de ventanas.
  No inicia la precarga hasta activar la ventana solicitada. Descarta respuestas
  obsoletas y valida corrida, iteracion, manifiesto, version de fuente, intervalo,
  longitud y, cuando Web Crypto esta disponible, SHA-256 de los bytes JSON.

## Diagnostico e integridad

`/api/metrics` conserva su identidad y contadores anteriores. `queries` agrega
`active_work`, `recent_work`, cancelaciones y fallos. Cada trabajo muestra fase,
tiempo transcurrido, checkpoints y edad del ultimo avance observado. Los
contadores de contexto de colas describen trabajo realizado, no un porcentaje
de progreso ni vehiculos unicos. La espera lenta con checkpoints crecientes es
distinta de un error SQL. No modificar limites de colas nativas para acelerar
esta reconstruccion.

La cache comprimida sigue limitada a 64 MiB y ocho entradas. Los snapshots de
colas conservan filas escalares y reutilizan registros nativos validados, sin
duplicar todo el arbol JSON para cada instante de espera. Las exclusiones de
dominio y de registros ya visitados se aplican antes de repetir la comprobacion
geometrica. Los mismos presupuestos logicos se cobran tambien en los aciertos
de cache; una respuesta incompleta sigue rechazandose.

Tras medir el conjunto de registros reutilizados, la cache de registros tiene
un limite de 64 MiB/16384 entradas y la de consultas compactas de 8 MiB/4096
entradas. Se publican en `read_caches`, junto con las otras caches. Estas medidas
contabilizan datos retenidos; no equivalen al uso total de RAM del proceso ni
eliminan el coste de una ventana completa. No se muestrean los datos.

Regresiones focalizadas: `test_simz1_replay_navigation_server.py`,
`test_simz1_temporal_navigation.cjs`, `test_simz1_continuous_replay.py` y
`test_simz1_continuous_replay.cjs`. Los errores, la concurrencia y los saltos
prolongados usan fixtures sinteticos. Los archivos historicos no se reparan ni
se reescriben para superar estas pruebas.

## Estado comprobado el 30 de octubre de 2026

**La recuperacion HTTP esta corregida; la fluidez sostenida a 120x sigue pendiente.**
No confundir tiempos HTTP con tiempo de preparacion o renderizado del navegador.
Computer Use rechazo Microsoft Edge; las comprobaciones siguientes son HTTP y
JavaScript real con WebGL simulado, no una comprobacion visual del navegador.

Corrida conservada: `run-1000-cursor-8ca9bc21577d423195c00c31e94ebfb0`,
`run_id=simz1-4626ba5ae24c452dbcb7a8c24ebd3aa2`, iteracion 0, 1269 vehiculos
configurados (973 particulares, 269 publicos y 27 camiones).

La respuesta 503 original era saturacion transitoria, no un error de SQLite.
Los calculos de las ventanas 161 y 162 progresaban, pero tardaban 325,641 y
349,094 segundos. La reconstruccion repetida de los contextos de cola dominaba
el coste. Las consultas abandonadas retenian plazas; el cliente agotaba siete
reintentos cortos y transformaba esa espera en un fallo permanente.

Ademas de las caches compactas, el servidor conserva respuestas completas y
comprimidas bajo `runtime/replay-cache/`. La clave incluye corrida, iteracion,
manifiesto, fuente y version del lector. Comprueba longitud y SHA-256 tanto del
gzip como del JSON al reutilizarlo. La publicacion es atomica y el presupuesto
es 2 GiB por identidad y 8 GiB globales, sin borrar caches anteriores. Agotar el
presupuesto impide guardar nuevas entradas, pero no trunca las respuestas.
No se modifica SQLite ni se crea ningun indice dentro de la fuente historica.

Se prepararon y comprobaron las 720 ventanas contra las filas escalares completas
de SQLite, con su orden e identidad. En 15 ventanas distintas se compararon ademas
todos los objetos de segmento con una consulta independiente de los payloads
nativos. Las ventanas 161 y 162 conservaron sus hashes semanticos anteriores.
Los hashes completos de SQLite, manifiesto de corrida, manifiesto de replay y
configuracion permanecieron iguales. El trial de la nueva simulacion del usuario
queda fuera de esta comparacion: su flujo normal puede actualizarlo.

La reapertura en un servidor nuevo reutilizo siete ventanas dificiles desde disco,
sin crear procesos lectores ni consultas SQLite. URL comprobada en esta sesion:
`http://127.0.0.1:64095/` (puerto no permanente).

| Ventana | HTTP completo con cache persistente | Segmentos |
| --- | ---: | ---: |
| 161 | 0,219 s | 1118 |
| 162 | 0,219 s | 1126 |
| 187 | 0,297 s | 1433 |
| 188 | 0,328 s | 1446 |
| 189 | 0,297 s | 1522 |
| 190 | 0,328 s | 1619 |
| 191 | 0,281 s | 1373 |

Pasaron 138 pruebas en nueve suites Python y siete suites Node, mas las pruebas
de procesos lectores y cache persistente. Se ejecutaron tambien las dos
regresiones de memoria con el constructor actual de `EncodedPayload` (SHA-256
obligatorio); la copia historica sin ese argumento conserva su error de contrato
en la evidencia, no se cuenta como aprobada.

El ensayo de 60,20 segundos con workers y precarga avanzo 5979,92 segundos
simulados: **no sostuvo los 120x solicitados**. El perfil posterior localizo
aproximadamente 100 ms por fotograma en la reconstruccion visual de colas, sobre
todo la preparacion de entradas y anclas. No hay un porcentaje de carga inventado
ni se han ocultado estas pausas. La masiva iniciada por el usuario esta usando la
revision validada; las fuentes compartidas quedan sin nuevas ediciones durante
esa ejecucion. La siguiente correccion requiere optimizar esa preparacion visual,
con equivalencia de posiciones y regresiones de colas, y repetir el ensayo sostenido.
Estos resultados no acreditan rendimiento de un replay de 180000 a 220000 agentes.

Evidencia: `runtime/diagnostics/temporal-navigation-20261030-8d76/`:

- `cached-tests/tests.json`: comandos y codigos de las suites.
- `cache-preparation-stream.json`: las 720 ventanas verificadas.
- `cached-verification/`: comparacion independiente de segmentos y hashes nativos.
- `reopened-verification.json`: identidad, tiempos y ausencia de lectores activos.
- `cached-play-prefilled.json` y `cached-play-profile.json`: pausas y perfil pendiente.

Para reabrir este mismo replay en otro puerto libre, sin simular ni regenerarlo:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
    $selection = Get-Content -Raw -LiteralPath '.\runtime\diagnostics\temporal-navigation-20261030-8d76\reopened-viewer-selection.json' | ConvertFrom-Json
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $listener.Start()
    $port = $listener.LocalEndpoint.Port
    $listener.Stop()
    & .\.venv\Scripts\python.exe -u -B .\scripts\replay\start_replay.py `
        --run-dir $selection.run_directory --replay-dir $selection.replay_directory `
        --iteration 0 --port $port
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo abrir el replay; conservar sus datos.' }
}
```

La masiva iniciada por el usuario usa
`runtime/workflow/run-massive-10it-with-viewer-20261030.ps1`. Su seleccion es
`massive-10it-bf195d4718a3477a9b12572b379fc65b-selection.json`: 204848 no publicos
mas 269 buses, diez iteraciones 0..9. La prueba previa de 1000 termino aceptada;
la masiva estaba ejecutando la iteracion 0 al registrar este estado. No se declara
terminada. Su script abre graficas y visor de la iteracion 9 solo despues del
cierre y las validaciones correspondientes; no ejecutar una segunda copia ahora.
