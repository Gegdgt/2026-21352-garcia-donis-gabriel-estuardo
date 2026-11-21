# Resultado de pruebas focales de la entrega

Fecha: **20 de noviembre de 2026**, Guatemala.

Se ejecutaron **47 pruebas Python: 46 aprobadas, 1 fallida, 0 errores y 0 omitidas**. Las **3 suites JavaScript aprobaron**. La prueba fallida revela una expectativa histórica que no coincide con la configuración actual del origen; ambos archivos se conservaron sin cambios. Este resultado no se presenta como una aprobación de toda la batería.

## Entorno y procedencia

Las pruebas se ejecutaron sobre el código de `src/` de esta entrega. Se utilizó el intérprete Python 3.10.11 del entorno virtual de desarrollo existente como herramienta externa de solo lectura, con `-B` y `PYTHONDONTWRITEBYTECODE=1`. No se copió ese entorno ni se realizó una instalación limpia de dependencias como parte de estas pruebas.

`PYTHONPATH` apuntó exclusivamente a `src/python/`. Se comprobaron **54 módulos del proyecto cargados desde la copia** y **ninguno desde la carpeta Python del origen**. `TEMP`, `TMP` y `MPLCONFIGDIR` apuntaron a subcarpetas de `src/runtime/validacion-entrega/`, por lo que los temporales y la caché de fuentes de Matplotlib permanecieron dentro de la entrega.

Se importaron correctamente los 11 módulos principales seleccionados: `prepare_simz1`, `generate_demand_z1`, `generate_montecarlo_z1`, `ejecutar_simz1`, `simz1_weekday_transit`, `simz1_analysis`, `generar_graficas_z1`, `serve_simz1_continuous`, `simz1_continuous_replay`, `simz1_paged_replay` y `simz1_motion`. Importar un módulo no ejecuta su simulación ni acredita por sí solo su flujo completo.

Las dependencias declaradas también se importaron correctamente: pandas 2.3.3, NumPy 2.2.6, Matplotlib 3.10.9, PyYAML 6.0.3, contextily 1.7.1, pyproj 3.7.1, openpyxl 3.1.5, seaborn 0.13.2, pydeck 0.9.3, Pillow 12.3.0 y pytest 9.1.1. `python -B -m pip check` sobre ese entorno terminó con código **0** y `No broken requirements found.`

## Pruebas Python

| Módulo | Aprobadas | Fallidas | Cobertura |
| --- | ---: | ---: | --- |
| `test_simz1_agent_types` | 11 | 0 | Catálogo, distribución y restricciones de perfiles. |
| `test_simz1_event_validation` | 8 | 0 | Continuidad de eventos y métricas de auditoría. |
| `test_simz1_agent_metadata` | 5 | 0 | Identidad y características de vehículos. |
| `test_simz1_selection_metadata` | 12 | 0 | Identidad, llegada y censura de viajes seleccionados. |
| `test_simz1_daily_window` | 4 | 0 | Ventanas del replay, SQLite en memoria y respuestas HTTP simuladas sin socket. |
| `test_prepare_simz1` | 3 | 1 | OSM mínimo, proyección, red y configuración. |
| `test_generate_demand_z1` | 3 | 0 | Generación reproducible de un agente y rechazos de entradas inválidas. |

El conjunto tardó aproximadamente **3,3 segundos**, sin contar importaciones y comprobación del entorno. Se usó `unittest` sobre esta lista explícita; no se ejecutó el descubrimiento global ni el archivo completo `pytest-simz1.ini`.

### Fallo conservado y documentado

`test_prepare_simz1.SimZ1Tests.test_cycle2_config`, línea 76 de `src/python/test_prepare_simz1.py`, espera `qsim.startTime = 07:59:00`. `src/scenarios/zona1/config-simz1.xml` contiene `00:00:00`. La aserción emitió:

```text
AssertionError: '00:00:00' != '07:59:00'
```

El mismo test también codifica un fin a las `15:00:00`, mientras que la configuración actual termina a las `24:00:00`; la ejecución se detuvo en la primera aserción. Esta discrepancia existe en el proyecto original: los SHA-256 de la prueba y de la configuración coinciden byte por byte entre origen y copia.

| Archivo | SHA-256 idéntico en origen y entrega |
| --- | --- |
| `python/test_prepare_simz1.py` | `b8d91c354c626427a7eb724fd9a654790fdebdab208b8e8da2da079599cafefb` |
| `scenarios/zona1/config-simz1.xml` | `33e5a3b7ee2c7b31dce3d04d527f686b36d9de6d50734dd107fe410686ffa640` |

No se cambió la configuración, la prueba ni ninguna evidencia para obtener un resultado aprobado. La corrección futura debe decidir qué escenario pretende comprobar ese test, manteniendo la política de observación vigente.

La transformación OSM mínima y la generación de exactamente **un agente** sí aprobaron. El caso que pasa `count=10000` comprueba un rechazo antes de escribir; no generó 10.000 agentes ni una corrida 10K.

## Pruebas JavaScript

Node.js **22.12.0**, ejecutado desde `src/`:

| Comando | Código |
| --- | ---: |
| `node python/test_simz1_vehicle_dimensions.cjs` | 0 |
| `node python/test_simz1_vehicle_card.cjs` | 0 |
| `node python/test_simz1_vehicle_picking_dimensions.cjs` | 0 |

Se comprobaron dimensiones y su procedencia, campos de la ficha, identidad durante la selección, selección geométrica, hover, fijación y navegación temporal mediante fixtures en memoria. No se abrió un navegador ni se utilizó GPU; estos resultados no acreditan una revisión visual ni el rendimiento de un replay real.

## Evidencia y límites

- [Salida completa de Python](verificacion/pruebas_python.txt).
- [Salida completa de JavaScript](verificacion/pruebas_javascript.txt).
- [Resultado estructurado, rutas de módulos y comparación SHA-256](verificacion/resultado_pruebas.json).
- [Plan y comandos reproducibles](PLAN_VALIDACION.md).

No se ejecutó Java, MATSim ni QSim durante estas pruebas. No se regeneraron 1K, 10K o 55K, no se modificaron configuraciones y no se reescribieron evidencias del origen. La compilación Java y otras comprobaciones de la entrega se informan por separado. Estos resultados no sustituyen una validación integrada, una instalación limpia, una simulación nueva ni la reproducción de corridas aceptadas.
