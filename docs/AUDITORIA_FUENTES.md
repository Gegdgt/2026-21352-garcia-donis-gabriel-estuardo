# Auditoría de fuentes y criterio de distribución

Fecha de inspección: 20 de noviembre de 2026. El proyecto de desarrollo se inspeccionó en solo lectura. Esta auditoría describe la selección; los inventarios de extracción registran los archivos efectivamente copiados y excluidos. No acredita la reproducción de ninguna corrida.

## Cómo se determinó la selección

Se revisaron el `pom.xml`, el inventario de instalación original, los puntos de entrada de Python/PowerShell, los contratos de escenarios y las dependencias de pruebas. Dos inventarios del propio proyecto explican por qué algunos archivos aparentemente históricos son necesarios:

- `scripts/installation/simz1-required-files.json` identifica archivos para preparar el escenario, ejecutar una prueba de diez agentes, producir métricas y servir WebGL. Se conserva como documento original, sin alterar su lista.
- `python/simz1_workflow_state.py`, función `fingerprint_files()`, vincula la validación a fuentes Java, pruebas Java, módulos Python/JavaScript/HTML, scripts, entradas del escenario y fixtures. Recortar estos archivos alteraría la identidad de validación.
- `python/simz1_history_fixtures.py` enumera 63 archivos históricos de regresión y verifica su procedencia. Su función `materialize()` traslada rutas de la configuración a un directorio temporal; el manifiesto histórico permanece intacto y marcado como fallido. Esos subconjuntos **no son corridas aceptadas**.

La unidad de selección es el archivo con una función identificada, no una copia indiscriminada del árbol de desarrollo. Las familias indicadas a continuación se retienen por dependencias de compilación, ejecución o validación; se descartan cachés y productos generados dentro de ellas.

## Inventario funcional

Las rutas de esta tabla son relativas a la raíz Maven entregada, `src/`.

| Necesidad | Fuentes o recursos identificados | Criterio |
| --- | --- | --- |
| Compilar Java/MATSim | `pom.xml`, `mvnw`, `mvnw.cmd`, `.mvn/wrapper/`, `src/main/java/`, `src/main/resources/simz1/` | Java 17, MATSim 15.0; conservar paquetes y recursos. El JAR pequeño del wrapper es una herramienta de arranque existente, no un resultado de compilación. |
| Preparar la red OSM | `python/prepare_simz1.py`, `python/filter_zona1_osm.py`, módulos de carriles, parámetros viales y señales; `scenarios/zona1/map.osm`, `osm-source.json` | Conservar el extracto original y su procedencia. La red y los carriles existentes son entradas legítimas. |
| Preparar agentes | `prepare_simz1_agents.py`, `generate_demand_z1.py`, `generate_montecarlo_z1.py`, `simz1_agent_*`, `simz1_population.py`, `simz1_temporal.py` | Mantener los módulos auxiliares importados y las políticas de composición y tiempo. |
| Vehículos y perfiles | `DrivingProfiles.java`, `RoadVehicleProfiles.java`, `scenarios/zona1/agent-types-*.json`, `vehicle-types.xml` | Parámetros del modelo; no modificarlos para conseguir una aprobación. |
| Transmetro y TuBus | `python/simz1_transit_*`, `simz1_weekday_transit.py`, clases Java de tránsito; `scenarios/zona1/transit/weekday-v2/` y `transit/review-2026-10-22/` | Los catálogos de revisión son una dependencia activa, no residuos prescindibles. Mantener servicios, flotas, rutas y procedencia. |
| Camiones | `python/simz1_freight.py`, `prepare_simz1_freight_routes.py`, clases Java de carga; JSON de `scenarios/zona1/freight/` | Conservar variantes versionadas, incluida compact-v3, porque forman parte del fingerprint. |
| Ejecutar el simulador | `python/ejecutar_simz1.py`, `simz1_run.py`, `simz1_run_directory.py`, `scripts/run_simz1_with_analysis.ps1`, `simz1_workflow.ps1`, Java `SimZ1` | Distribuir lanzadores sin ejecutarlos durante la preparación de la entrega. |
| Diagnósticos y pruebas | `src/test/java/`, `python/test_*.py`, pruebas JS/CJS, `tests/`, `python/fixtures/`, `check_simz1_*.ps1`, `scripts/validation/`, `pytest-simz1.ini` | Conservar fixtures explícitas, incluso un `.log` histórico pequeño. La selección de pruebas ejecutadas debe constar aparte. |
| Gráficas y tablas | `procesar_eventos_z1.py`, `generar_graficas_z1.py`, `simz1_analysis.py`, módulos de estadísticas y reporte, `scripts/generate_thesis_graphs_v2.ps1` | Distribuir los generadores; excluir las gráficas y tablas históricas de resultados. |
| Preparar replay | `python/simz1_*replay*`, `simz1_sqlite_*`, módulos de recuperación; `scripts/replay/` | El código no equivale a distribuir sus eventos, SQLite ni cachés. |
| Levantar el visualizador | `python/serve_simz1_continuous.py`, `serve_simz1_replay.py`, `visualizador_z1*.html`, JS y lanzadores | Mantener HTML/JS como recursos estáticos ejecutables. Las bibliotecas externas del visor se documentan en la guía. |
| Consultar/seleccionar vehículos | `simz1_vehicle_picking.js`, `simz1_continuous_hud.js`, módulos de selección, SQLite y trayectorias | La selección requiere un replay preparado y datos de la corrida elegida. |

## Clasificación y decisiones

| Clase | Decisión de distribución |
| --- | --- |
| Código fuente imprescindible | Conservar Java, Python, HTML, JS/CJS y scripts que integran los flujos, sus importaciones y el fingerprint. Las fuentes de laboratorios también forman parte del árbol compilado y de la huella original; no incluyen sus resultados. |
| Configuraciones necesarias | Conservar Maven, requisitos Python, configuración de pruebas, XML/JSON/CSV/OSM del nivel base de Zona 1, variantes OD, políticas temporales, flotas, carga y experimentos. |
| Recursos estáticos necesarios | Conservar HTML/JS, OSM, GeoJSON, redes, carriles, señales, catálogos y recursos JSON de Java. |
| Scripts auxiliares útiles | Conservar instalación, revisión, posproceso, replay y mantenimiento cuando son dependencia de inventarios o fingerprint. La inclusión de utilidades de mantenimiento no autoriza ejecutarlas. |
| Tests | Conservar fuentes y fixtures; no copiar resultados de ejecuciones de pruebas, cachés ni compilados. |
| Documentación técnica pertinente | Guía técnica original, composición vehicular, carga, ocupación, replay, señales, contratos C529/OD y documentación de validación. Las bitácoras conservadas se interpretan como historia, no como evidencia de ejecución de esta entrega. |
| Artefactos generados excluidos | `.git` original, entornos, `target`, `build`, cachés, resultados `montecarlo/run-*`, runtime histórico, auditorías generadas, `audit-24h*`, tablas/gráficas/replays históricos, respaldos y temporales. |
| Archivos grandes | Se excluyen bases SQLite, eventos y resultados voluminosos. No hay candidatos funcionales de más de 10 MiB en las familias revisadas, salvo inventarios de mantenimiento generados que no son necesarios. |
| Potencialmente sensibles | No incorporar `.env`, credenciales, claves ni tokens; revisar también texto de candidatos, no solo nombres/extensiones. Las rutas privadas históricas se documentan y no se sustituyen en manifiestos protegidos. |

## Excepciones justificadas a la exclusión de productos históricos

- Los 63 archivos de `tests/fixtures/simz1-history-v1/` ocupan aproximadamente 68.76 MiB en conjunto. Ninguno supera 10 MiB. Son evidencia mínima de regresión declarada por el propio código y contienen procedencia verificable; no se eliminan por llamarse `historical-manifest.json`, `matsim-run.log`, `historical.xml` o por incluir redes.
- `scenarios/zona1/od/balanced-gateway-v1/access-review-v2/` es una variante activa. Sus configuraciones L18, OSM, red, carriles, señales, rutas de carga y evidencia OSM forman parte del contrato físico. Sus hashes y recibos no se corrigen ni reescriben en esta entrega.
- `scenarios/zona1/transit/review-2026-10-22/` contiene datos que importan directamente `simz1_transit_fleet.py` y `simz1_transit_catalog.py`.
- `plans.xml`, `population-smoke.xml` y los reportes pequeños del nivel base se conservan como entradas/procedencia y dependencias de inventario o fingerprint; no son eventos masivos.
- `docs/maintenance/simz1-test-contracts.csv` describe alcance y efectos de las pruebas. En cambio, `docs/maintenance/simz1-inventory-20261016.csv` (33,347,772 bytes) es un inventario generado prescindible.

## Tamaños de referencia del origen

Estos números corresponden a la inspección de familias, excluyendo cachés; no sustituyen el total exacto del inventario de extracción.

| Familia | Archivos | Tamaño aproximado |
| --- | ---: | ---: |
| Java de producción | 59 | 0.74 MiB |
| Recursos JSON de Java | 6 | 0.04 MiB |
| Java de pruebas | 112 | 1.20 MiB |
| Python/HTML/JS/CJS en el nivel `python/` | 437 | 6.74 MiB |
| `python/fixtures/` | 23 | 2.15 MiB |
| Scripts | 45 | 0.52 MiB |
| Fixtures históricas explícitas | 63 | 68.76 MiB |

El OSM base mide 4,289,056 bytes, `network.xml` 7,826,179 bytes y `lanes.xml` 6,299,706 bytes. Sus tamaños permiten incluirlos como entradas. La base de datos completa de una corrida y los eventos masivos cumplen otra función y no son requisitos para compilar ni para una prueba pequeña.

## Procedencia y portabilidad

`scenarios/zona1/osm-source.json` registra atribución a colaboradores de OpenStreetMap y ODbL 1.0. También reconoce que la fecha y URL exactas de adquisición no están registradas. La consulta de API que aparece allí obtiene datos actuales y no reproduce exactamente el snapshot incluido.

`transit/review-2026-10-22/sources.json` registra CC-BY-4.0 y atribución a Municipalidad de Guatemala, DMU / DIGM para los conjuntos municipales indicados. Los metadatos del servicio de límite administrativo en `od/balanced-gateway-v1/source/item.json` registran acceso público, pero `licenseInfo` y `accessInformation` son nulos; no se les atribuye una licencia inexistente en los metadatos. Se conserva la procedencia original para revisión.

Las rutas históricas de desarrollo dentro de manifiestos y fixtures no se editan. El propio adaptador `simz1_history_fixtures.py` materializa las fixtures en una ubicación temporal cuando corresponde. Las instrucciones de entrega deben ejecutarse desde la raíz Maven `src/` y usar rutas relativas o parámetros explícitos. Los lanzadores de Run1K/Run10K/Run55K o de visores previamente aceptados pueden exigir carpetas y recibos externos: su presencia como código no hace disponibles esos resultados.

La preservación byte a byte también debe mantenerse después de un clon. Las reglas de atributos Git de la entrega deben evitar conversiones de finales de línea en archivos cuyo hash forma parte de los contratos, sin modificar los hashes esperados ni los manifiestos.

## Revisión de información sensible

Se inspeccionaron nombres y contenido textual de los candidatos de código, configuración y documentación para localizar archivos de entorno/credenciales/claves, encabezados de claves privadas, tokens reconocibles de GitHub/AWS, secretos literales y URLs con credenciales. No se detectaron credenciales con estos patrones. Dos coincidencias de URL en `scripts/start_simz1_viewers.ps1` fueron revisadas y corresponden a direcciones de localhost con interpolación de PowerShell, no a usuarios o contraseñas.

Este resultado describe el alcance del escaneo estático y no atribuye ausencia absoluta de secretos a los árboles generados excluidos. Los nombres de colaboradores y metadatos de cambios en el extracto OSM pertenecen a la procedencia pública del conjunto.

## Alcance de la comprobación

Esta auditoría no ejecutó Maven, QSim, simulaciones, preparación de demanda ni scripts de limpieza. No modificó el origen, las corridas, los recibos ni los manifiestos. Los resultados efectivos de compilación, pruebas pequeñas, integridad y enlaces corresponden al informe de verificación de la entrega.
