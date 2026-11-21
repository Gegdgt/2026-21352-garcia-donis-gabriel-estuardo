# Verificación de la entrega SimZ1

Fecha: **20 de noviembre de 2026**, Guatemala. La copia de entrega está preparada en el fork local, rama `main`. No se hizo commit, push ni Pull Request.

La compilación limpia Java pasó, la demanda de diez agentes quedó preparada y se verificaron componentes Python/JavaScript. **Una prueba Python conserva una discrepancia preexistente de horario; no se presenta toda la batería como aprobada. No se ejecutó MATSim/QSim.**

## Resultados comprobados

| Comprobación | Resultado y evidencia |
| --- | --- |
| Copia e integridad | 937 archivos del origen, 131.191.301 bytes. SHA-256 de cada copia igual a la selección revisada. [Inventario](extraccion/inventario_incluidos.csv). |
| Repetición del extractor | Segunda aplicación: 937 idénticos, cero archivos de origen recopiados, cero bloqueos. [Resumen](extraccion/resumen.json). |
| Dependencias de fuentes | Todas las entradas de `simz1-required-files.json` y las 787 dependencias del fingerprint están presentes. |
| Fingerprint del proyecto | Igual en origen y copia: `12933cdfb843293e5ba7dcf9bc4cf30a3a8dd92e5aeb08d7d388c6138331d20a`. [Evidencia](verificacion/fingerprint_y_demanda.json). No se sustituyeron recibos históricos. |
| Compilación limpia | **BUILD SUCCESS**, JDK 17.0.12, Maven 3.9.6, 59 fuentes de producción y 112 de pruebas; objetivo Java 17. [Log](verificacion/compilacion_java_limpia.txt). |
| Bytecode y classpath | 430 clases examinadas, versión mayor 61, dependencias MATSim 15/Guice/Guava comprobadas. [Resultado](verificacion/bytecode_java.txt). |
| Instalador original | `check_simz1_install.py --tests`: **0 comprobaciones pendientes**. XML maestros, referencias relativas, OSM y wrapper verificados. [Log](verificacion/instalacion.txt). |
| Python | **46 aprobadas / 1 fallida**, 47 pruebas focales. 11 módulos principales y 11 dependencias importados; 54 módulos internos cargados desde la copia, ninguno desde las fuentes originales. [Detalle](RESULTADO_PRUEBAS.md). |
| Dependencias Python | `pip check`: código 0 en el entorno disponible. Versiones en el [resultado de pruebas](RESULTADO_PRUEBAS.md). |
| JavaScript | 3 suites aprobadas: dimensiones, ficha y selección geométrica de vehículos. [Log](verificacion/pruebas_javascript.txt). |
| Prueba funcional de preparación | Generador original, semilla 20261120: 10 personas y 10 viajes en XML, estado `prepared`, sin transporte público adicional ni ejecución QSim. [Resultado](verificacion/fingerprint_y_demanda.json). |
| OSM y demanda mínimos | Transformación de OSM mínimo y generación reproducible de un agente aprobadas. No se regeneraron 1K, 10K o 55K. |
| Secretos y tamaños | Ningún patrón de credencial ni nombre sensible detectado entre los archivos admitidos. Ningún archivo original seleccionado supera 25 MiB; máximo 7.841.289 bytes. Es una comprobación estática, no una garantía universal de ausencia de secretos. |
| Git y bytes al publicar | Atributos específicos conservan CRLF/LF originales; fixtures y evidencias seleccionadas quedan incorporables. [Comprobación de portabilidad](verificacion/git_portabilidad.json). |
| Enlaces del README | Se comprueban los destinos locales. Los tres archivos manuales todavía ausentes se identifican como pendientes, junto con las diez capturas. [Resultado](verificacion/revision_paquete.json). |

La demanda de prueba está en una carpeta local ignorada bajo `src/runtime/entrega-demanda-10-…`; su identidad consta en la evidencia. No se incorpora como resultado aceptado ni como replay. Puede generarse otra demanda siguiendo el README.

## Fallo que se conserva

`test_prepare_simz1.SimZ1Tests.test_cycle2_config` espera `07:59:00`, pero el escenario vigente utiliza `00:00:00`. La prueba también espera un fin a las 15:00 frente a las 24:00 del XML. La comparación SHA-256 confirma que tanto el test como la configuración son idénticos a los del origen. No se cambió ninguno para obtener un aprobado. El [informe de pruebas](RESULTADO_PRUEBAS.md) contiene aserción, hashes y cobertura.

Esta discrepancia deberá resolverse en el mantenimiento del proyecto definiendo a qué escenario pertenece la expectativa histórica. No bloqueó la compilación, la preparación OSM mínima ni la generación de demanda pequeña.

## Herramientas y límites de la validación

La caché Maven disponible se copió a `.entrega-work/m2/`, excluida de Git. Se utilizó la distribución Maven 3.9.6 ya instalada, con Java 17, sin descargar ni modificar dependencias en el origen. Desde `src/`, el comando de validación fue equivalente a:

```powershell
# $maven y $cache apuntaron a herramientas/caches locales identificadas en los logs.
& $maven --batch-mode --no-transfer-progress --offline "-Dmaven.repo.local=$cache" `
    -DskipTests clean test-compile dependency:build-classpath `
    '-Dmdep.outputFile=target/simz1-runtime-classpath.txt' '-Dmdep.includeScope=test'
```

Para un clon nuevo, los comandos con `mvnw.cmd` del README resuelven las mismas versiones. El JAR del wrapper y su SHA-256 se comprobaron; no se ensayó su descarga desde Internet.

El primer intento bajo el entorno restringido falló con `AccessDeniedException` al cerrar un JAR de la caché, sin errores de código identificados. La ejecución fuera de esa restricción pasó; se completó después una compilación limpia de ambas colecciones. Se conservaron los logs [inicial](verificacion/compilacion_java.txt), [diagnóstico](verificacion/compilacion_java_diagnostico.txt) y [final limpio](verificacion/compilacion_java_limpia.txt).

Las pruebas Python utilizaron el intérprete 3.10.11 de la `.venv` original como herramienta externa de lectura, con `-B`; las fuentes importadas, temporales y cachés de prueba pertenecieron exclusivamente a la entrega. La `.venv` no se copió. **No se efectuó una instalación limpia desde Internet**; el destinatario debe instalar `requirements-test.txt` como explica la guía. El Python global de esta computadora carece de varias dependencias y no sustituye ese entorno.

Se compilaron las pruebas Java, pero no se ejecutaron. No se usaron `Validate`, `DryRun`, descubrimiento global de pytest, generadores masivos ni pruebas que lanzan QSim. No se abrió un replay real en WebGL, no se generaron gráficas de una corrida nueva y no se certificó el rendimiento de los replays históricos. Sus datos están excluidos.

## Preservación del origen

La inspección inicial enumeró **250.472 archivos**, con **140.597.655.969 bytes**. Las 559 rutas largas que Windows rechazó inicialmente se recuperaron mediante rutas extendidas; el inventario inicial quedó sin errores de metadatos. Se excluyeron 249.535 archivos del paquete de fuentes. El [CSV comprimido](inventario_excluidos_completo.csv.gz) enumera cada archivo excluido; el extractor recurrente agrupa los subárboles de productos para evitar recorrer repetidamente cientos de miles de archivos.

La comparación posterior de tamaño y mtime detectó actividad concurrente en **45 entradas de `.git/` del origen y cuatro registros de servicios bajo `runtime/viewers/services/`**. No se modificaron esas rutas mediante los comandos de preparación. El Git original pasó de tener cambios previos a mostrar un commit posterior; no se revirtió ni incorporó esa actividad en la entrega. No se afirma que todo el directorio original permaneciera estático durante la sesión.

Las **937 fuentes seleccionadas mantienen sus hashes**, el fingerprint sigue idéntico y no se observaron cambios de tamaño/mtime en corridas, eventos, replays ni resultados bajo `scenarios/`. La comparación de 250.472 rutas iniciales está en [preservacion_origen.json](verificacion/preservacion_origen.json); las 25 rutas que ya no se encontraron pertenecen exclusivamente a metadatos Git. No se rehashearon las bases y eventos multi-GB.

## Diferencias de empaquetado

No hubo adaptaciones del motor, la física, configuraciones, políticas, manifiestos ni recibos. La estructura completa del proyecto Maven se anida en `src/`; ejecutar desde allí conserva sus rutas relativas.

Se añadieron dos archivos de empaquetado, recreados por el extractor:

- `src/scenarios/.gitattributes`: `** -text`, para que las reglas originales más cercanas no conviertan bytes CRLF al crear un commit. La raíz también protege el resto de `src/`.
- `src/scenarios/.gitignore`: excepciones para los logs compactos de evidencia OSM seleccionados. La regla original `*.log` los ocultaría; no son corridas masivas ni logs nuevos de ejecución.

Los archivos originales `.gitattributes` y `.gitignore` también se conservaron íntegros. Las demás adiciones son documentación y herramientas de la entrega. Las presentaciones finales específicas de Run1K/Run10K, sus adaptadores y datos bajo runtime no se distribuyen; el visor genérico y su API de selección sí se incluyen. La guía identifica los recursos externos requeridos sin afirmar su disponibilidad pública.
