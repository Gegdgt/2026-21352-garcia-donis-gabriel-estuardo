# Guía de ejecución de la copia de entrega

Esta guía corresponde al proyecto Maven situado en `src/` del repositorio UVG. Los comandos se revisaron contra los argumentos y contratos del código original. La preparación de la entrega no autoriza ejecutar MATSim/QSim: los pasos que lo ejecutan quedan señalados para uso posterior. La compilación y las pruebas de componentes no reproducen las corridas 1K, 10K ni 55K.

## Directorio de trabajo y entorno

Abra PowerShell en la raíz del repositorio descargado y entre una sola vez al proyecto:

```powershell
Set-Location .\src
```

Todos los comandos siguientes se ejecutan desde esa carpeta. El segundo `src/`, dentro del proyecto Maven, contiene `main/java`, `main/resources` y `test/java`; no debe aplanarse.

Instale un **JDK 17 completo** —con `java` y `javac`— y **Python 3.10 o superior**. Al instalar Python, habilite su acceso desde la terminal. Defina `JAVA_HOME` con la carpeta real de su JDK, no con su subcarpeta `bin`. Este ejemplo solicita la ruta de la instalación y la aplica únicamente a la terminal actual:

Los instaladores se encuentran en [Eclipse Temurin, versión 17](https://adoptium.net/temurin/releases/?version=17) y [Python para Windows](https://www.python.org/downloads/windows/). Elija el paquete JDK de Java y la arquitectura de su equipo. La ejecución comprobada utilizó Python 3.10.11; el requisito `3.10+` procede del proyecto, no de una prueba de todas las versiones posteriores.

```powershell
$env:JAVA_HOME = Read-Host 'Ruta de la carpeta del JDK 17 instalado'
if (-not (Test-Path -LiteralPath (Join-Path $env:JAVA_HOME 'bin\javac.exe'))) {
    throw 'La carpeta indicada no contiene un JDK completo.'
}
$env:Path = (Join-Path $env:JAVA_HOME 'bin') + ';' + $env:Path
java -version
javac -version
python --version
```

Aunque el verificador de instalación acepta Java >=17, la versión de referencia para ejecutar MATSim 15 es Java 17. No basta con tener un JRE. El bytecode de la aplicación está fijado a Java 17 en `pom.xml`.

```powershell
python -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno Python.' }
& .\.venv\Scripts\python.exe -m pip install -r requirements-test.txt
if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias.' }
& .\.venv\Scripts\python.exe -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Hay dependencias Python incompatibles.' }
```

No se requiere activar el entorno: los comandos invocan su ejecutable explícitamente. Los lanzadores PowerShell del proyecto esperan `.venv\Scripts\python.exe` dentro de este proyecto. El entorno virtual de la máquina del autor no forma parte de la entrega.

Dependencias declaradas en [requirements.txt](../src/requirements.txt): pandas >=2.0, numpy >=1.24, matplotlib >=3.7, PyYAML >=6, contextily >=1.6 y <2, pyproj >=3.6 y <4, openpyxl >=3.1 y <4, seaborn >=0.13 y <0.14, pydeck >=0.9.3 y <0.10, Pillow >=10. [requirements-test.txt](../src/requirements-test.txt) añade pytest >=7. SQLite se usa mediante `sqlite3`, incluido en Python. Los rangos originales se conservan; no constituyen un archivo de versiones congeladas.

Para las pruebas JavaScript se necesita Node.js >=22. El visor requiere un navegador con WebGL y acceso al CDN utilizado por el cliente. Node no es necesario para servir el visor con Python. Instale Node si desea ejecutar la batería JavaScript y compruebe `node --version`.

## Compilación y verificación sin simulación

```powershell
& .\mvnw.cmd --batch-mode --no-transfer-progress -DskipTests test-compile
if ($LASTEXITCODE -ne 0) { throw 'Compilacion incompleta; revisar la salida de Maven.' }
& .\mvnw.cmd --batch-mode --no-transfer-progress dependency:build-classpath `
    '-Dmdep.outputFile=target/simz1-runtime-classpath.txt' '-Dmdep.includeScope=test'
if ($LASTEXITCODE -ne 0) { throw 'No se pudo resolver el classpath.' }
& .\.venv\Scripts\python.exe -B .\python\simz1_runtime_check.py `
    --classpath-file .\target\simz1-runtime-classpath.txt
if ($LASTEXITCODE -ne 0) { throw 'Bytecode o dependencias incompatibles.' }
& .\.venv\Scripts\python.exe -B .\python\check_simz1_install.py --tests
if ($LASTEXITCODE -ne 0) { throw 'Hay requisitos de instalacion pendientes.' }
```

El wrapper declara Maven 3.9.6 y Maven Wrapper 3.2.0. La primera ejecución puede descargar el wrapper, Maven y dependencias desde Maven Central y el repositorio MATSim. Se necesita acceso a esos servidores o una caché completa. `test-compile` compila las clases de pruebas; no acredita que se hayan ejecutado. El verificador de bytecode tampoco lanza QSim.

No use `simz1_workflow.ps1 -Action Validate` como sustituto de una comprobación sin simulación: su batería integrada contiene componentes nativos y pruebas más amplias. La opción `-RunSmoke` de `prepare_simz1_runtime.ps1` ejecuta explícitamente una fixture QSim. Ninguno de esos flujos se necesita para comprobar solamente la instalación y compilación de esta entrega.

## Entradas y preparación de la red OSM

La entrega conserva el extracto `scenarios/zona1/map.osm` y su registro `osm-source.json`, con atribución a OpenStreetMap contributors y licencia ODbL. El registro no contiene fecha ni URL de descarga original. Su ejemplo de API devolvería datos actuales, no el mismo extracto histórico. No sustituya el OSM para reproducir un experimento existente.

Los archivos `network.xml`, `lanes.xml`, `facilities.xml`, `vehicle-types.xml`, `signalSystems.xml`, `signalGroups.xml`, `signalControl.xml` y `config-simz1.xml` son entradas legítimas. Se conservan porque el funcionamiento depende de ellas, aunque algunas fueron derivadas por herramientas del proyecto.

Para inspeccionar la conversión del OSM en una **carpeta nueva**, sin cambiar los insumos maestros:

```powershell
$redNueva = Join-Path (Get-Location).Path ('runtime\red-osm-' + [guid]::NewGuid().ToString('N'))
& .\.venv\Scripts\python.exe -B .\python\prepare_simz1.py `
    --input .\scenarios\zona1\map.osm --output-dir $redNueva
if ($LASTEXITCODE -ne 0) { throw 'Fallo la preparacion OSM; conservar el diagnostico.' }
Get-Content -LiteralPath (Join-Path $redNueva 'processing-report.json')
```

Este importador crea una red base y declara sus supuestos. No reconstruye por sí solo todas las revisiones de accesos, carriles, señales y servicios del experimento final. Por ejemplo, informa restricciones de giro que no impone el grafo básico. No reemplace los insumos revisados ni sus hashes con esta salida. Para el ejemplo pequeño siguiente se usa el escenario maestro entregado.

## Demanda pequeña sin MATSim

El ejemplo usa un catálogo de carros y motos ya existente, una semilla explícita y diez personas. Es una prueba de preparación; no equivale a la composición 44/55/1 y a la flota pública de los experimentos finales. El catálogo `agent-types-car-moto-v1.json` declara carga con peso cero y servicio público separado; no se cambia para aprobar una prueba.

```powershell
$demanda = Join-Path (Get-Location).Path ('runtime\entrega-demanda-10-' + [guid]::NewGuid().ToString('N'))
& .\.venv\Scripts\python.exe -B .\python\generate_montecarlo_z1.py `
    --config .\scenarios\zona1\config-simz1.xml --run-dir $demanda `
    --agents 10 --seed 20261120 --matsim-seed 20261120 `
    --corridor-policy redistribute --origin-policy uniform-nodes-v1 `
    --agent-catalog .\scenarios\zona1\agent-types-car-moto-v1.json
if ($LASTEXITCODE -ne 0) { throw 'Fallo la preparacion; no continuar a MATSim.' }
Get-Content -LiteralPath (Join-Path $demanda 'run-manifest.json')
```

Sin `--run-matsim`, este comando únicamente prepara entradas y registra la procedencia. La salida debe identificar diez personas y estado `prepared`. No se debe interpretar `prepared` como una corrida completada. Se utiliza un UUID porque los generadores rechazan un destino existente, incluso vacío.

`prepare_simz1_agents.py` es otra utilidad: produce una asignación de tipos, sin rutas OD ni vehículos instanciados. Su manifiesto señala `runnable: false`; esa asignación no sustituye a los planes del comando anterior.

## Simulación pequeña: ejecución futura, no realizada al preparar la entrega

El siguiente comando **sí ejecuta MATSim/QSim**. Se incluye para quien descargue el código y decida hacer una corrida nueva después de instalar y revisar el entorno. No debe ejecutarse como parte de una revisión limitada a lectura, compilación o preparación de la entrega.

```powershell
$corrida = Join-Path (Get-Location).Path ('runtime\entrega-simulacion-10-' + [guid]::NewGuid().ToString('N'))
& .\.venv\Scripts\python.exe -B .\python\ejecutar_simz1.py `
    --config .\scenarios\zona1\config-simz1.xml --run-dir $corrida `
    --agents 10 --seed 20261120 --matsim-seed 20261120 --iterations 1 `
    --corridor-policy redistribute --origin-policy uniform-nodes-v1 `
    --agent-catalog .\scenarios\zona1\agent-types-car-moto-v1.json
if ($LASTEXITCODE -ne 0) { throw 'Revisar manifiesto y log; conservar la corrida.' }
```

El lanzador genera otra demanda aislada y aplica `--iterations 1` a su copia de configuración. No reutiliza ni sobrescribe `$demanda`. El XML maestro contiene 50 iteraciones; no se recomienda ejecutarlo directamente con `exec:java`. El lanzador utiliza `gt.edu.uvg.sim.zona1.RunZona1Simulation`, invoca una JVM separada y comprueba el resultado nativo.

El código calcula un heap de 12 GiB cuando detecta al menos 16 GiB de RAM física y de 8 GiB en otro caso. Aunque la población sea pequeña, considere este requisito del lanzador y el espacio para salidas. No se alteran esos valores en la copia para conseguir una ejecución aprobada.

## Revisar resultados y generar gráficas

Estos pasos necesitan la carpeta de una corrida nueva ya ejecutada, o un paquete externo íntegro. `$corrida` debe apuntar a esa carpeta concreta. No se debe omitir `--run-dir` ni depender de `latest-successful` para identificar resultados de entrega.

```powershell
$estado = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $corrida 'run-manifest.json') | ConvertFrom-Json
$estado | Select-Object run_id,status,phase,iterations,validation
Get-Content -LiteralPath (Join-Path $corrida 'matsim-run.log') -Tail 40
if ($estado.status -ne 'completed' -or $estado.validation.status -ne 'valid') {
    throw 'No hay una corrida nativa completed/valid; conservar evidencia y diagnosticar.'
}
& .\.venv\Scripts\python.exe -B .\python\procesar_eventos_z1.py --run-dir $corrida --iteration 0
if ($LASTEXITCODE -ne 0) { throw 'No se pudo procesar la iteracion solicitada.' }
& .\.venv\Scripts\python.exe -B .\python\generar_graficas_z1.py `
    --run-dir $corrida --iteration 0 --profiles-only
if ($LASTEXITCODE -ne 0) { throw 'Fallo el analisis; no repetir QSim por este error.' }
```

El resultado principal queda en `analysis/it.0/`: tabla `trips.csv.gz`, procedencia, manifiesto de análisis y `graficas_perfiles/`. El lanzador ya intenta el análisis al terminar; repetir el comando permite reutilizar productos compatibles o recuperar únicamente esta fase. No se corrige manualmente un manifiesto para habilitarla.

Con diez personas, el umbral predeterminado de 30 observaciones marca muestras insuficientes. No debe bajarse para presentar significancia. Distinga llegadas, viajes incompletos y censura: las medias de quienes llegaron no describen necesariamente toda la población.

## Preparar y abrir el replay

Conserve `$corrida` e iteración explícitos. La preparación siguiente procesa eventos existentes y puede crear una base SQLite; no vuelve a ejecutar MATSim.

```powershell
& .\.venv\Scripts\python.exe -B .\scripts\replay\prepare_replay.py `
    --run-dir $corrida --iteration 0 --sqlite-budget-gib 8 --scratch-budget-gib 4
if ($LASTEXITCODE -ne 0) { throw 'Replay incompleto; conservar SQLite y diagnostico.' }
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\replay\start_replay.ps1 `
    -RunDir $corrida -Iteration 0 -Port 8792
if ($LASTEXITCODE -ne 0) { throw 'No se pudo abrir el replay solicitado.' }
```

El presupuesto indicado es un límite, no una reserva de espacio ni una garantía de capacidad para corridas grandes. El preparador comprueba el espacio disponible y la identidad de los artefactos. El lanzador del visor abre el navegador una vez comprobado el servidor HTTP. Si el puerto está ocupado, elija otro libre. Mantenga la terminal abierta y use Ctrl+C para cerrar su servidor. No abra el HTML con `file://`: las consultas del replay requieren el servidor local.

En el visor:

1. Confirme la corrida e iteración mostradas antes de interpretar el mapa.
2. Use pausa, velocidad, navegación temporal y filtros de carros, motos, carga o buses. El campo de ruta filtra el ID exacto de una ruta de bus o carga.
3. Haga clic sobre un vehículo para consultar agente, vehículo, perfil, viaje, origen y destino, tiempos y enlaces disponibles. El recorrido completo se solicita al servidor.
4. La ruta recorrida aparece en celeste oscuro y su continuación registrada en celeste claro. Esta continuación pertenece al replay; no es una predicción.
5. Haga clic en el fondo o cierre la tarjeta para limpiar la selección. Una llegada ausente o una posición desconocida se conserva como tal.

El movimiento visual incluye interpolación entre eventos; no es una medición continua de velocidad o posición nativa. El funcionamiento WebGL real debe comprobarse en el navegador del destinatario. No se publican capturas de pruebas no realizadas.

## Transporte público, camiones y experimentos finales

Las configuraciones conservadas separan demanda privada, camiones y flotas Transmetro/TuBus. Las familias de entradas relevantes son `scenarios/zona1/agent-types-*.json`, `transit/weekday-v2/`, `freight/`, `od/balanced-gateway-v1/` y `experiments/`, junto con las políticas Java de `src/main/resources/simz1/` dentro del proyecto Maven.

`simz1_weekday_transit.py` valida fecha laboral, rutas, paradas, flota y supuestos; `simz1_freight.py` valida servicio y rutas de carga. Las revisiones v1, v2, v3 y v8 no son intercambiables. La variante final depende de configuración L18, catálogos, perímetro, mezcla OD, bundle de rutas y políticas concretos. Se mantienen sus contratos.

El comando antiguo `simz1_workflow.ps1 -Action Run1000` sin especificación ya no corresponde al código actual: exige `ExperimentSpec` versionada de 24 horas. Los experimentos usan validaciones integradas, huellas de fuentes, recibos y aprobación de ensayo. La copia no incorpora ni fabrica recibos de aprobación de la máquina del autor. Estos experimentos no son un requisito para la prueba pequeña y no se regeneraron al preparar la entrega.

## Resultados históricos externos y diferencias de distribución

El código fuente permite preparar ejecuciones nuevas. No incluye automáticamente eventos masivos, bases SQLite de varios GiB, corridas bajo `montecarlo/run-*`, salidas de `output/`, replays ni estados históricos de `runtime/`. Por tanto, **un clon de esta entrega no permite abrir Run10K ni reproducir sus gráficas sin sus datos originales**.

`scripts/start_simz1_viewers.ps1` y `python/simz1_viewers_readonly.py` pertenecen a las presentaciones finales concretas de Run1000/Run10K. Exigen fuentes, adaptadores de interfaz y recibos bajo `runtime/diagnostics/`, además de las bases y corridas originales. La interfaz final depurada de esas presentaciones no es la misma distribución que el visor genérico documentado arriba. Su ausencia no se resuelve cambiando los hashes de aprobación. Asimismo, `scripts/generate_thesis_graphs_v2.ps1` y `python/simz1_thesis_collection_v2.py` dependen de esas corridas concretas; para una corrida nueva se debe usar `generar_graficas_z1.py`.

Para revisar una corrida aceptada existente se necesita un paquete externo íntegro, autorizado para distribución, con:

- `run-manifest.json` original y los artefactos de entrada y salida referenciados por él, con sus hashes originales.
- Eventos y planes nativos de la iteración requerida, configuración efectiva, red, carriles, señales y servicios utilizados.
- Para reabrir un replay ya publicado: `continuous-manifest.json`, su fuente SQLite completa y el manifiesto de esa fuente, más los demás archivos que sus contratos referencien.
- Identidad exacta de corrida, iteración y versión de posprocesamiento. Las rutas absolutas históricas se deben inspeccionar; no se deben editar recibos o hashes para fingir una instalación portable.

No se ha establecido un enlace público de descarga para ese paquete. Como alternativa reproducible disponible, se entregan insumos y generadores para crear una corrida nueva según los pasos anteriores. Una corrida nueva no reemplaza ni demuestra igualdad con resultados aceptados históricos.

Algunas fixtures de regresión conservan rutas originales como evidencia. `python/simz1_history_fixtures.py` verifica su procedencia y materializa copias temporales con rutas de configuración reubicadas. No se deben editar los manifiestos históricos de esas fixtures: son subconjuntos de prueba, no corridas aceptadas. Las rutas del código operativo principal se calculan desde la ubicación de sus archivos; trabajar desde la carpeta Maven `src/` mantiene esa relación.

La documentación técnica original conserva historia de desarrollo y puede mencionar carpetas excluidas. No se debe usar una referencia histórica ausente como instrucción de instalación. Esta guía describe los puntos de entrada de la distribución; los inventarios y el informe de verificación de la entrega precisan qué se incluyó y qué se comprobó realmente.
