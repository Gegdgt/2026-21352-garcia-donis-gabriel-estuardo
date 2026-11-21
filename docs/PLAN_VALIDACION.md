# Alcance de la validación de la entrega

Inspección realizada el 20 de noviembre de 2026. Este documento describe la selección de comprobaciones y las herramientas encontradas. Los resultados ejecutados se registran por separado en el informe de verificación de la entrega.

La preparación no autoriza ejecutar MATSim/QSim, siquiera con pocos agentes. Tampoco autoriza regenerar las corridas 1K, 10K o 55K, modificar sus entradas ni cambiar contratos, recibos o hashes para conseguir una aprobación.

## Herramientas encontradas

| Herramienta | Resultado de inspección |
| --- | --- |
| JDK 17 | `C:\Program Files\Java\jdk-17`; `java` y `javac` reportan 17.0.12. |
| Java del PATH | JDK 25; debe seleccionarse explícitamente JDK 17 al compilar. |
| Maven | Wrapper incluido: Maven 3.9.6, wrapper 3.2.0. Su JAR y archivo de propiedades existen. |
| Caché Maven | Existen la distribución 3.9.6 y el JAR MATSim 15.0; esto no demuestra por sí solo que estén todas las dependencias transitivas. |
| Python | Python 3.10.11. |
| Node.js | 22.12.0. |

El Python global tiene pandas, NumPy, Matplotlib y Pillow, pero faltan PyYAML, contextily, pyproj, openpyxl, seaborn y pytest. Su pydeck 0.9.1 no satisface el mínimo declarado de 0.9.3. Debe prepararse un entorno propio de la copia con los archivos originales `requirements.txt` y `requirements-test.txt`.

La consulta de metadatos del entorno del desarrollo, realizada con `-B`, encontró todas las dependencias declaradas: pandas 2.3.3, NumPy 2.2.6, Matplotlib 3.10.9, PyYAML 6.0.3, contextily 1.7.1, pyproj 3.7.1, openpyxl 3.1.5, seaborn 0.13.2, pydeck 0.9.3, Pillow 12.3.0 y pytest 9.1.1. El entorno virtual no forma parte de la entrega. Estas versiones observadas no reemplazan ni modifican los requisitos originales.

## Compilación sin ejecución

Desde `src/`, con `JAVA_HOME` apuntando al JDK 17 instalado:

```powershell
& .\mvnw.cmd --batch-mode --no-transfer-progress '-DskipTests' test-compile
if ($LASTEXITCODE -ne 0) { throw 'Falló la compilación.' }
```

`test-compile` compila fuentes principales y fuentes de pruebas; no ejecuta las comprobaciones Java ni QSim. No usar `exec:java`, `exec:exec`, `Run`, `Run1000` ni `prepare_simz1_runtime.ps1` para esta validación limitada. Este último script ejecuta una batería de comprobaciones Java después de compilar y no equivale a una mera comprobación de compilación.

## Pruebas pequeñas revisadas

Los siguientes módulos existentes se inspeccionaron para excluir lanzamientos de simulación y dependencia de corridas históricas. Desde `src/` y una vez instalado el entorno:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$validationRoot = Join-Path (Get-Location).Path 'runtime\validacion-entrega'
New-Item -ItemType Directory -Force -Path (Join-Path $validationRoot 'tmp'), (Join-Path $validationRoot 'matplotlib') | Out-Null
$env:TEMP = Join-Path $validationRoot 'tmp'
$env:TMP = $env:TEMP
$env:MPLCONFIGDIR = Join-Path $validationRoot 'matplotlib'
Push-Location .\python
try {
    & ..\.venv\Scripts\python.exe -B -m unittest `
        test_simz1_agent_types `
        test_simz1_event_validation `
        test_simz1_agent_metadata `
        test_simz1_selection_metadata `
        test_simz1_daily_window
    if ($LASTEXITCODE -ne 0) { throw 'Falló el conjunto unitario.' }
} finally { Pop-Location }
```

Cubren catálogos de perfiles, auditoría de eventos sintéticos, metadatos de vehículos, identidad durante la selección y límites temporales del replay. Usan registros pequeños en memoria o archivos temporales; la prueba del replay usa SQLite `:memory:`. No son resultados experimentales de Zona 1.

La entrada OSM y la demanda mínima pueden comprobarse con `test_prepare_simz1` y `test_generate_demand_z1`. El primero transforma una fixture OSM pequeña en un directorio temporal y comprueba la red entregada. El segundo genera exactamente un agente en archivos temporales y verifica su repetibilidad. Su argumento inválido `count=10000` debe ser rechazado antes de escribir: no genera la corrida 10K.

Para cubrir la consulta de vehículos y el visor, desde `src/`:

```powershell
& node .\python\test_simz1_vehicle_dimensions.cjs
if ($LASTEXITCODE -ne 0) { throw 'Fallaron las dimensiones.' }
& node .\python\test_simz1_vehicle_card.cjs
if ($LASTEXITCODE -ne 0) { throw 'Falló la ficha del vehículo.' }
& node .\python\test_simz1_vehicle_picking_dimensions.cjs
if ($LASTEXITCODE -ne 0) { throw 'Falló la selección geométrica.' }
```

Estas pruebas usan módulos JavaScript y un entorno DOM simulado. No abren un navegador, no usan GPU, no miden FPS y no prueban visualmente un replay real. La carpeta de trabajo debe ser `src/`: el entorno de pruebas lee `python/visualizador_z1_continuous.html` y otros recursos por rutas relativas.

No ejecutar por defecto el descubrimiento completo de pruebas ni `python -m pytest -c pytest-simz1.ini`: el conjunto completo contiene fixtures de 1.000 y 10.000 personas. Otros tests fuera de ese conjunto ejecutan Java y requieren revisión adicional antes de usarlos bajo las restricciones de esta preparación.

## Rutas y dependencias históricas

- Los módulos principales calculan la raíz usando `Path(__file__).resolve().parents[1]`. Conservar íntegros `src/python/`, `src/scenarios/` y `src/src/` mantiene esa relación.
- Algunos lanzadores experimentales tienen un valor predeterminado Windows para `JavaHome`; en otra instalación debe proporcionarse `-JavaHome` explícitamente. No es una dependencia del nombre de usuario.
- Pruebas Java especializadas como `test_simz1_active_retention.py`, `test_simz1_l18_coordination.py`, `test_simz1_native_od.py` y `test_simz1_sequence_contract.py` usan una instalación concreta de JDK 17. No están incluidas en la validación pequeña propuesta.
- `python/fixtures/simz1-visibility-history.json` contiene rutas absolutas del desarrollo como procedencia de evidencia histórica. Deben documentarse como referencias históricas; no convertirlas en una promesa de que esos eventos o bases SQLite se distribuyen.
- `python/test_simz1_analysis.py` contiene una ruta del desarrollo como dato de prueba. No confundirla con la configuración de ejecución nueva.
- Las utilidades de inspección visual pueden buscar Chrome o Edge en rutas habituales de Windows; algunas admiten `SIMZ1_BROWSER`. Las utilidades de colección histórica para tesis no son el flujo de inicio de esta entrega.

## Interpretación de resultados

La integridad SHA-256 comprueba fidelidad de la copia; la compilación verifica compatibilidad del código con las dependencias disponibles; las pruebas unitarias verifican contratos concretos. Ninguna de ellas acredita reproducción de 1K, 10K o 55K, calibración empírica, aceptación de una corrida nueva ni apertura del visor con datos históricos ausentes.
