# SimZ1: intercambio XML Python / MATSim 15.0 (Tarea 1)

Corrección limitada a la serialización de rutas explícitas de población. La lista
textual de `<route type="links">` ahora incluye inicio y destino, igual que el
escritor nativo. No se modificó código Java de producción.

## Causa y evidencia nativa

`PopulationReaderMatsimV6` llama a `NetworkRoute.setRouteDescription()`. En MATSim
15.0, `LinkNetworkRouteImpl` toma del texto el primer y último enlace y reemplaza
los atributos de extremos. Por tanto, escribir solo intermedios cambia la ruta
cargada aunque los atributos originales parezcan correctos.

La prueba inicial, anterior a la reparación de los escritores, terminó con
código **0**: `RouteXmlTests.test_01_historical_native_reproduction`. Artefactos:
`runtime/route-xml-yxnfnemc/`. Solo se extrajo `z1_97936`; se leyó el archivo
original por bloques para verificar su hash, sin cargar las 180000 personas.

- Fuente: `scenarios/zona1/montecarlo/run-bg180-dd9e2a9d64fc4764835fed6602faf191/plans.xml`.
- Run: `simz1-8545ef106cbe43ce8fabb81bf0bc0a41`.
- SHA256 de `plans.xml`, verificado contra el manifiesto: `809d3c6713914258d7fce378d937e0d0e31bd894e23a5bdaaf0ca15bb57ea5ec`.
- SHA256 del fragmento literal: `594cb88e1e2e36c0526292aae68af32d517e6998e25ba499b1a66b20cf7c8f98`.
- SHA256 de la fixture envuelta como población: `5663bfd65cc19fc346dbd69fd85368e939609d343eb6956ad697a44f2923caa2`.

| Lectura nativa de z1_97936 | Enlaces | Inicio | Destino |
| --- | ---: | --- | --- |
| XML histórico | 73 | `osm_762765906_2_forward` | `osm_1305763184_1_forward` |
| XML con texto completo | 75 | `osm_762765906_1_forward` | `osm_1305763184_1_backward` |

La segunda fila coincide enlace por enlace con `route_link_ids`. Se mantienen
las actividades, coordenadas, atributos de persona, `vehicleRefId=z1_97936` y
salida `0.7991602372870776`. La fixture corregida cambia únicamente el texto de
la ruta; no reemplaza el XML histórico.

El comprobador Java usa `PopulationReader`, inspecciona `NetworkRoute`, escribe
con `PopulationWriter` y vuelve a leer con `PopulationReader`. El proceso exige
JDK17 y registra el JAR real de MATSim 15.0. No construye rutas Java manualmente
ni llama a `Controller`, QSim o `SimZ1Freight.notifyBeforeMobsim()`.

Para la ida/vuelta, exclusivamente en el comprobador, el escritor nativo usa
`Time.TIMEFORMAT_HHMMSSDOTSS` para conservar las fracciones de segundo; su formato
predeterminado `HH:mm:ss` las trunca. No se cambia la configuración de producción.

## Archivos y métodos

| Archivo | Cambio |
| --- | --- |
| `python/generate_montecarlo_z1.py` | `gateway_people().people()`: escribe todos los `route_link_ids`. |
| `python/simz1_freight.py` | `attach()`: texto completo. `verified_contract()`: coteja ruta, actividades, vehículo y salida con el registro; también para servicios sin `service_version`. |
| `python/simz1_route_xml.py` | Nuevo `validate_link_route()`: exige texto completo y coincidencia con atributos, actividades, secuencia esperada e identidad. |
| `python/simz1_population.py` | `_verify_population()`: aplica ese contrato después de validar los metadatos OD. |
| `python/simz1_balanced_od_audit.py` | `validate_manifest()`: mismo contrato; `implementation_signature()` incorpora el módulo nuevo. |
| `python/test_simz1_balanced_gateway_od.py` | Expectativa de texto completo y mutaciones de atributos rechazadas por población y auditor de manifiesto. |
| `python/test_simz1_sequence_contract.py` | Valida la secuencia textual completa sin agregar extremos otra vez. |
| `python/test_simz1_freight_through_integration.py` | Compara el texto completo con el registro de carga. |
| `python/test_simz1_route_xml.py` | Regresión focal Python → lector Java y pruebas de integración/fingerprint. |
| `src/test/java/gt/edu/uvg/sim/zona1/PopulationRouteXmlCheck.java` | `main()`, `read()` y `snapshot()`: comprobación nativa, limitada a fixtures pequeñas. |
| `scripts/simz1_workflow.ps1` | Validate ejecuta la regresión tras preparar el classpath y antes de escribir aprobaciones; cualquier fallo detiene el flujo. |

No se introdujo compatibilidad que adivine el formato histórico. Los auditores
rechazan texto vacío, intermedios solamente y extremos contradictorios en las
nuevas entradas. No deduplican enlaces. Las validaciones existentes de continuidad,
giros, secuencias OSM y cadenas gateway siguen usando la misma secuencia completa.

## Cobertura y reproducción

Desde la raíz del repositorio, con el classpath local existente:

```powershell
.venv\Scripts\python.exe -B python\test_simz1_route_xml.py
```

El comando compila únicamente el comprobador en un nuevo directorio
`runtime/route-xml-*`, conserva logs/comandos/códigos Java y no modifica recibos.
Usa `C:\Program Files\Java\jdk-17` (alternativa: variable `SIMZ1_JDK17`) y
`target/simz1-runtime-classpath.txt`; verifica `matsim.version=15.0` en `pom.xml`.

Incluye rutas de uno, dos y tres enlaces; un circuito y una repetición legítima;
contradicciones rechazadas; 99 particulares de las cuatro clases; una muestra
de cada una de las cuatro rutas compactas de carga; cuatro particulares en modo
`network`; la prohibición 17478998; identidad, horarios y cuotas. N=180000 se
verifica solo por aritmética: 79200 carros, 99000 motos, 1800 camiones. La muestra
de servicios conserva los 269 buses adicionales.

Los casos sintéticos de texto vacío con extremos iguales y distintos prueban que
MATSim conserva esos atributos, a diferencia del texto no vacío truncado. Así se
cubre la semántica corta relevante a las cuatro descripciones históricas vacías;
no se atribuye a ellas el desplazamiento de z1_97936 ni se extraen otras personas
históricas a fixtures. El generador privado sigue exigiendo OD distintos, aunque
el formato XML pueda representar una ruta de un enlace.

El fingerprint actual ya recorre `python/*.py`, `src/test/java/*.java` y los
scripts. La prueba nueva verifica, en un árbol temporal, que modificar el lector
compartido, la regresión Python o el comprobador Java cambia ese fingerprint.
No se alteraron hashes históricos para acomodar la corrección.

## Ejecuciones y códigos reales

Ejecuciones finales del 2026-11-01: **74 pruebas, cero fallos, cero omisiones**.
Logs en `runtime/route-xml-t0db1zp5/`; fixtures y snapshots nativos finales en
`runtime/route-xml-keq3_9er/`, con `provenance.json` y un archivo
`*.command.json` por compilación/lectura, que registra el comando y su código.

| Prueba | Cantidad | Código | Log |
| --- | ---: | ---: | --- |
| `test_simz1_route_xml.py` | 8 | 0 | `native-complete-tests.log` |
| `test_simz1_balanced_gateway_od.py` completo | 34 | 0 | `balanced-final-tests.log` |
| `SequenceRegressionTests` completo | 16 | 0 | `sequence-tests.log` |
| `FreightTests`, `GeneratedThroughFreightTests` y conservación del servicio | 13 | 0 | `freight-tests.log` |
| Población: ciclo dirigido pequeño, repetibilidad N=1/10/100 e identidad corrupta | 3 | 0 | `population-tests.log` |
| Parser de PowerShell y `git diff --check` | — | 0 | Salida de herramientas de la tarea |

Los 16 casos de secuencias incluyen la compilación JDK17 y ejecución de
`Restriction17478998Probe`, `RouteSafetyCheck`, `FastestTimeRoutingCheck` y
`GatewayRouteSafetyCheck`, todos sin simulación. Se redirigió `RESULTS` a
`runtime/route-xml-t0db1zp5/sequence-regression` para conservar la evidencia previa.
La prueba de flota con 5405 expediciones de la suite de carga no se ejecutó;
solo se seleccionaron sus casos pequeños pertinentes.

Los intentos iniciales del comprobador devolvieron **1** durante su construcción:
uso de `hashlib.file_digest` no disponible en Python 3.10, comparación de la
representación de objeto `PersonVehicles`, orden de personas al escribir,
expectativa del mensaje de secuencia e integración movida tras preparar el
classpath. Se corrigió el arnés y se repitió la suite completa; el último
resultado es el de la tabla. Estos intentos no produjeron aprobaciones.

## Límite de la evidencia

Esto verifica **lectura y escritura nativas**, no ejecución de una simulación.
No se ejecutaron Validate completo, Run1000, DryRun masivo, Controller/QSim ni
generación/corrida 180K. No se comprobó todavía la incorporación física de
z1_97936, la evolución del cursor durante QSim o la finalización de viajes.
`plannedPath()`, cursor, enlace actual, actividad inicial y reconstrucción Java
de carga permanecen intactos. No se investigó el colapso histórico ni se inició
la limpieza de carga de la Tarea 2.
