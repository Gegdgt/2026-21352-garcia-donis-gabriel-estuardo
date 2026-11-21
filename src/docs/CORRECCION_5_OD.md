# Corrección 5 / 5B — demanda particular `balanced-gateway-v1`

Implementación preparada para pruebas manuales. **No ejecutada ni habilitada con
insumos reales**: falta un perímetro GeoJSON verificado y su catálogo de accesos.
No se generaron poblaciones, ni se preparó una corrida de 110000, ni se modificaron
lanzadores. No hay porcentajes OD observados ni una mezcla por defecto.

## Cierre estático 5B — 2026-11-01

Se conservaron los doce archivos de la fase anterior. En 5B se corrigieron solo
`python/simz1_balanced_od_audit.py`, `python/simz1_population.py`,
`python/simz1_run.py`, `python/test_simz1_balanced_gateway_od.py` y los dos documentos
`CORRECCION_5_OD.md` / `CONTINUAR_CORRECCION_5.md`. El generador y su selección CLI
se revisaron sin reescribirlos. La plantilla JSON sigue inhabilitada.

Inconsistencias demostrables corregidas:

- La auditoría OD contaba el `entered link` inicial opcional como otro tramo.
  Ahora conserva una sola incorporación y exige el `left link` correspondiente
  para los movimientos siguientes. Se mantiene la validación física existente.
- La ruta XML debía pertenecer también al vehículo de esa persona. Se comprueban
  `type=links`, `vehicleRefId` y la coincidencia persona/vehículo en eventos.
- La verificación de población devolvía el alcance histórico `observed_z1_only`.
  Ahora devuelve el alcance de anclas declaradas y validación por viaje del modo
  nuevo, manteniendo el resultado histórico para `network`/`gateway-od`.
- El manifiesto comparaba solo familias y clases del reporte. Ahora reconstruye
  desde los planes las clases, gateways, concentración de orígenes, top 20 y horas;
  recalcula la carga aceptada de incorporación y comprueba el reporte de
  particulares, incluso si alguien actualizara el hash de un reporte incorrecto.
- Faltaba un cierre explícito de evidencia OD. Ahora un archivo truncado no llega
  a `finish()`; reservas sin liberar, transiciones cortadas y salida nativa sin
  llegada impiden su aceptación. Una limpieza nativa al final puede dejar viajes
  incompletos: estos conservan `completed=0`, sin fabricar llegada ni despeje.
- Los resultados OD incluyen `run_id` y el artefacto/hash del XML de eventos
  consumido. El validador del modo nuevo requiere salida nativa natural con código
  0 y estado running/completed; una cuota preparada o un estado failed no basta.

El registro previo clasificaba como espera a toda persona sin incorporación.
Se corrigió esa inferencia: `never_observed` significa sin salida observada,
`waiting_to_incorporate` exige `departure` sin entrada efectiva, y
`never_incorporated` cuenta todas las personas sin entrada efectiva. La expectativa
de la prueba inicial cambió de una espera inferida a cero esperas observadas y un
vehículo nunca observado; no se cambió una cuota ni se ocultó un fallo.

| Apartado | Estado de entrega | Evidencia disponible |
|---|---|---|
| A. Generador, CLI, planes y manifiesto | IMPLEMENTADO, PENDIENTE DE PRUEBA | Revisión de ramas y prueba XML/manifiesto pequeña escrita |
| B. Composición y separación de servicios | IMPLEMENTADO, PENDIENTE DE PRUEBA | `split()`, conteos de los dos N y fixture 44+55+1; fuentes protegidas intactas |
| C. Horarios, semilla y reintentos | IMPLEMENTADO, PENDIENTE DE PRUEBA | Horario fuera del bucle OD; prueba que fuerza reintentos sin cambiar clase/tipo/hora |
| D. Cadena de gateways y despeje | IMPLEMENTADO, PENDIENTE DE PRUEBA | Clasificación geométrica, ruta completa y prueba con límite inferior nativo |
| E. Auditorías, reporte y resultados | IMPLEMENTADO, PENDIENTE DE PRUEBA | Comprobación desde planes, cierre de eventos y guardia de estado nativo |
| F. Restricciones por particular | IMPLEMENTADO, PENDIENTE DE PRUEBA | Sin whitelist global; validadores separados de carga/PT preservados |
| G. Política de orígenes | IMPLEMENTADO, PENDIENTE DE PRUEBA | Longitud útil × carriles, sitios revisados y conector de paso en fixture |
| Perímetro y accesos reales | BLOQUEADO POR INSUMO EXTERNO | No apareció un GeoJSON verificado; catálogo de ejemplo no aprobado |
| Continuación exterior, conectividad y capacidad reales | BLOQUEADO POR INSUMO EXTERNO | No se pueden acreditar sin perímetro/catálogo; no se presume que existan o falten |
| Lectores visuales del contrato histórico | PENDIENTE DE IMPLEMENTACIÓN | Fuera de generación/auditoría solicitadas en 5B; continúan rechazando el contrato nuevo |

No queda identificado otro pendiente de implementación dentro del alcance de
5B. Esta afirmación no sustituye las pruebas: no hay PASS registrado ni validación
QSim/GIS de la variante real. Su habilitación continúa bloqueada.

## Archivos y responsabilidades

| Archivo Python | Cambio |
|---|---|
| `generate_montecarlo_z1.py` | Integra la nueva opción en el generador existente, conserva cuotas/horarios, escribe rutas privadas y auditorías; una iteración y semilla 20261023. |
| `simz1_balanced_od.py` (nuevo) | Contrato de perímetro/accesos, rutas dirigidas sobre el grafo existente, incorporación, capacidad programada e informe previsto. |
| `simz1_balanced_od_audit.py` (nuevo) | Verificación del manifiesto, fuentes, rutas particulares y evidencia nativa de salida. |
| `simz1_od_policy.py` | Porcentajes decimales exactos de las cuatro clases; reutiliza reparto entero y presupuestos existentes. |
| `simz1_gateway_od.py` | Expone longitud física al cargar enlaces; conserva el contrato histórico de representantes interiores. |
| `simz1_agent_demand.py` | Comprueba que la hora conservada coincide exactamente con el muestreo del catálogo por persona. |
| `simz1_population.py` | Comprueba la ruta XML privada contra su evidencia OD. |
| `simz1_run.py` | Aceptación del contrato nuevo por viaje y auditoría adicional en el mismo recorrido de eventos. |
| `test_simz1_balanced_gateway_od.py` (nuevo) | Pruebas pequeñas sin MATSim ni población masiva. |

Se reutilizan sin editar `simz1_agent_types.py`, `simz1_demand_composition.py`,
`simz1_freight.py`, `simz1_freight_gateways.py` y `simz1_temporal.py`.
Los contratos de fuente, catálogo, restricciones OSM y manifiesto siguen activos.
Documentación adicional: este archivo, `simz1-balanced-gateway-access.example.json`
y `CONTINUAR_CORRECCION_5.md`.

## Selección explícita

La API sigue siendo `generate_montecarlo_z1.generar(...)`. Las opciones nuevas son:

```text
--od-mode balanced-gateway-v1
--origin-policy lane-length-access-v1
--destination-policy lane-length-destinations-v1
--agent-catalog scenarios/zona1/agent-types-balanced-v1.json
--seed 20261023
--matsim-seed 20261023
--use-lanes
--whole-vehicle-reservation
--storage-policy strict-receiver-v1
--qsim-threads 1
--zone-boundary <perimetro-verificado.geojson>
--od-access-catalog <catalogo-accesos-verificado.json>
--od-osm scenarios/zona1/map.osm
--od-mix <JSON de cuatro porcentajes que sumen exactamente 100>
```

No es un comando de ejecución. Los dos archivos verificados todavía no existen.
Faltar cualquiera produce un error antes de crear la carpeta o preparar servicios.
La plantilla de documentación tiene `verified: false` y no habilita el modo.

Para una preparación futura sin MATSim, después de resolver los insumos, se usa
este mismo generador con `--config <configuración fuente>`, `--run-dir <carpeta
nueva>`, una cantidad explícita, las opciones anteriores y los servicios
preservados. Se omite `--run-matsim`. `generar()` escribe planes/vehículos,
comprueba referencias, tipos, cuotas, horarios, capacidad y manifiesto antes de
publicar el estado `prepared`; no atribuye entrada ni llegada observada.
No se deja aquí un lanzador de 110000 ni una orden de generación masiva.

La comprobación de una preparación existente tampoco necesita MATSim: la API
`simz1_balanced_od_audit.validate_manifest(directorio, manifiesto_json)` es de
lectura, valida hashes/modelo/planes/reporte y devuelve modelo y registros privados.
No inicia procesos ni cambia `prepared` a `completed`. Las pruebas pequeñas del
comando al final ejercitan ese recorrido con archivos temporales sintéticos.

La configuración efectiva exige carriles, `strict-receiver-v1`, reserva de
carrocería completa, un hilo, FIFO, `removeStuckVehicles=false` y routing entre
enlaces. Se conservan semáforos y prioridades de la fuente. En la copia nueva,
el generador fija primera/última iteración en 0; no cambia el XML fuente.
`--run-matsim` se rechaza para esta variante en esta fase.

Debe mantenerse el servicio existente:
`freight/weekday-compact-v3/service-composition-v3.json` y
`transit/weekday-v2/service-fleet-176-93-v1.json`, con sus fechas y aceptación de
supuestos ya exigidas por las interfaces actuales. El generador no cambia sus
rutas, ventanas, frecuencias, vehículos ni calendarios. Tampoco activa un servicio
distinto automáticamente. La política temporal continua de varios días sigue
rechazada: no es compatible con el calendario actual de carga de un solo día.

El modo `network` continúa disponible con sus opciones anteriores. No se
reinterpreta `gateway-od`: sus antiguos representantes interiores siguen siendo
representantes, no salidas exteriores. Los lectores de visualización históricos
que únicamente aceptan ese contrato antiguo no quedan habilitados para el nuevo
contrato en esta fase; los reportes nuevos y la aceptación nativa usan el contrato
por viaje descrito aquí. No se relajan sus validaciones para forzar compatibilidad.

## Composición y clases

| N no público | Carros | Motos | Camiones | Particulares con OD | Buses adicionales |
|---:|---:|---:|---:|---:|---:|
| 110000 | 48400 | 60500 | 1100 | 108900 | 269 |
| 220000 | 96800 | 121000 | 2200 | 217800 | 269 |

`split()` reserva primero la cuota de carga incluida en N; solo la cuota privada
entra a `gateway_people()` y `typed_people()`. Después se adjunta la carga por la
interfaz existente. Los buses conservan 176 Transmetro y 93 TuBus, fuera de N.
El perfil pesado del catálogo privado no se utiliza para generar camiones:
estos siguen tomando 8 m × 2.3 m de `weekday-compact-v3`.

| Clase | Origen | Destino |
|---|---|---|
| `EXTERNAL_EXTERNAL_THROUGH` | Ancla exterior de entrada revisada | Ancla exterior de salida distinta; ruta con tramo interior |
| `EXTERNAL_INTERNAL` | Ancla exterior de entrada revisada | Enlace interior conectado con parada físicamente admisible |
| `INTERNAL_EXTERNAL` | Incorporación interior revisada | Ancla exterior de salida revisada |
| `INTERNAL_INTERNAL` | Incorporación interior revisada | Otro enlace interior conectado con parada admisible |

Las cuatro claves son obligatorias, incluso si alguna tiene porcentaje cero.
La suma se verifica exactamente mediante aritmética decimal/racional, sin
normalizar una suma incorrecta. Los conteos enteros usan el reparto existente
por restos mayores; el informe distingue porcentaje configurado del realizado
tras redondeo. Se guardan decimales como cadenas para que el hash no dependa de
reconstruir porcentajes multiplicando números binarios por 100.

Las fixtures usan 25/25/25/25 **solo como hipótesis de prueba**. No es un valor
predeterminado ni un aforo de Zona 1. La hipótesis seleccionada conserva versión,
porcentajes exactos y SHA256 canónico en cada manifiesto futuro.

## Perímetro y contrato de accesos

No se encontró un GeoJSON verificado/versionado del perímetro. Los archivos de
`corridor-boundary` encontrados son fixtures de carrocería/corredor, no cartografía
administrativa. El bounding box OSM no sustituye el perímetro.

Insumos pendientes:

1. GeoJSON RFC7946 de un Polygon válido (puede tener huecos), con procedencia,
   versión, revisor y fecha de revisión. La red actual usa EPSG:32615.
2. Catálogo `simz1-verified-private-access-v1` vinculado por SHA256 a los bytes
   exactos de GeoJSON, OSM, red y carriles. Se comprueba contra la red y sus giros.
3. Entradas y salidas revisadas, con cadenas dirigidas de enlaces existentes.
4. Sitios interiores de incorporación revisados, longitud útil, permiso de
   actividad y capacidad de incorporación documentada en PCU/h.
5. Mezcla OD explícita y versionada como hipótesis experimental.

| Situación | Distinción y comportamiento |
|---|---|
| Perímetro ausente/no verificado | Falta `--zone-boundary` o procedencia/hash válido de `perimeter`; rechazo, sin bbox de respaldo. |
| Catálogo no verificado | Falta `--od-access-catalog` o su `review.verified` no es true; la plantilla no es utilizable. |
| Enlaces exteriores ausentes | Una geometría aprobada podría revelar que no existe ancla/cadena exterior; se rechaza ese gateway sin crear enlaces. Actualmente no está determinado. |
| Conectividad insuficiente | Los enlaces pueden existir y aun así no ofrecer un camino dirigido con giros/carriles válidos; se rechaza el par/clase. |
| Capacidad insuficiente | El camino existe, pero su presupuesto de incorporación/cohorte no admite la demanda; se conserva hora, clase y N y no se publica preparación exitosa. |

Cada catálogo tiene `review`, `perimeter`, `network_sha256`, `lanes_sha256`,
`osm_sha256`, `entry_gateways`, `exit_gateways`, `internal_origins`.
Cada bloque de revisión exige `verified: true`, `version`, `source`, `reviewed_by`
y `reviewed_at` no vacíos. La procedencia debe proceder de una revisión real:
una bandera o un hash no demuestran por sí solos exactitud cartográfica.

Cada gateway requiere:

| Campo | Significado |
|---|---|
| `id` | Identidad revisada del acceso/salida; entrada y salida de paso deben ser distintas. |
| `link_ids` | Cadena ordenada, conectada y compatible con movimientos de carril. |
| `crossing_link` | Enlace que realmente cruza la geometría, en el sentido declarado. |
| `observation_link` | Enlace completamente interior; no se acredita como salida real. |
| `anchor_link` | Enlace existente completamente exterior, conectado a la cadena. |
| `review` | Procedencia de la revisión del gateway. |
| `activity_allowed` | Debe ser true para utilizar el ancla como actividad. |
| `useful_length_m` | Espacio útil revisado, positivo y no mayor que la longitud física. |
| `incorporation_capacity_pcu_h` | Límite documentado, positivo y no mayor que la capacidad nativa. En salida limita cohortes programadas. |
| `capacity_basis` | Explicación de cómo se obtuvo ese límite; no se infiere de la demanda solicitada. |

En entrada, la cadena es exterior → cruce → observación interior; en salida,
observación interior → cruce → exterior. Puede haber varios enlaces del mismo
lado, sin reentradas. Se reutiliza el límite existente de 250 m para anclas
exteriores. El grafo interior y su conectividad proceden de `GatewayModel`.
Los giros de las cadenas también se comprueban contra carriles y restricciones OSM.

**La continuación exterior es un pendiente diferente del GeoJSON.** Sin el
perímetro no se puede certificar qué enlaces existentes son exteriores. Una vez
recibido, si no hay una cadena exterior existente que permita el despeje, las
clases afectadas se rechazan. No se extiende la red ni se convierte un observador
interior en una llegada exterior. El alcance temporal sigue limitado al interior
y anclas expresamente modeladas; no hay tiempo puerta a puerta.

Cada origen interior usa `link_id` y los cinco campos de incorporación/revisión
anteriores. Un enlace de observación de gateway no puede hacerse pasar por origen
interior anónimo. Los conectores no son sitios de incorporación implícitos.

## Orígenes, horarios y capacidad

`lane-length-access-v1` pondera los orígenes elegibles por longitud útil × carriles.
Exige acceso permitido, sentido, conectividad al destino y espacio nativo para
carrocería + 0.10 m. La longitud de la primera cola nativa se calcula desde las
definiciones de carriles; no se sustituye por la longitud total cuando hay división.
No existe un corte general de 10 m: la fixture admite un origen revisado de 6 m
y conserva un conector de 2 m en las rutas, sin originar vehículos en él.

Los destinos interiores conservan ponderación por metros-carril entre candidatos
conectados con espacio geométrico para una parada. Las salidas además requieren
despeje completo del perímetro antes de su posible terminación nativa.
La distancia del cruce se lleva a la geometría métrica antes de compararla con
las longitudes nativas. Ninguna de estas comprobaciones aumenta almacenamiento.

El tipo, la identidad y la salida de cada particular usan las mismas funciones
de asignación y `sample_departures()` del catálogo balanceado. Las clases OD no
reponderan las horas. La comprobación se repite al escribir tipos y al aceptar
el manifiesto. Una incompatibilidad de capacidad no cambia N, hora ni clase.

Los presupuestos incluyen incorporación revisada y enlaces compartidos de cruce.
Se limita el muestreo a 1024 pares por persona; agotar esos intentos rechaza la
preparación. El error distingue un muestreo agotado de una prueba matemática de
saturación global. Si ya había una carpeta nueva, queda
`inputs/od-preflight-failure.json` con hora, persona, clase, carga aceptada y
rechazos; no se publica un manifiesto preparado. Las cuotas de salida por hora
son de la cohorte de partida, ya que la hora de llegada aún es desconocida.
Estos presupuestos privados no predicen colas compartidas con buses/carga.

## Separación de servicios y auditorías

La nueva variante no escribe `zona1SpatialRouting.allowedLinks`; rechaza una
configuración fuente que ya tenga esa whitelist global. Sus rutas iniciales se
escriben explícitamente y la aceptación se hace por viaje privado. Camiones y
buses mantienen sus validadores y rutas. Un reruteo interior puede aceptarse;
cruzar por otro gateway o saltarse la cadena elegida invalida la auditoría.
Esto es selección y validación; no se ha cambiado el router nativo ni se ha
forzado movimiento. No promete evitar toda congestión ni aumentar llegadas.

La auditoría nueva se ejecutará junto a las auditorías físicas existentes, en
el mismo recorrido de eventos. Una salida exterior requiere `vehicle leaves
traffic` en el destino y límite inferior nativo de avance suficiente para que
carrocería + 0.10 m hayan cruzado. La llegada requiere también `arrival` coherente.
Un `entered link` o el fin del reloj no constituyen una llegada.

Artefactos preparados para futuras generaciones autorizadas:

- `inputs/balanced-od-audit.json`: N, familias, buses adicionales, clases/cantidades,
  porcentajes configurados y realizados, entradas/salidas por gateway, histograma
  de longitud de orígenes, top 20 con categoría, salidas privadas por hora y
  desglose horario de carga/expediciones públicas, rechazos, integridad y límites.
- `montecarlo-report.json` y `run-manifest.json`: conservan los contratos anteriores
  y añaden `balanced_od`, `spatial_demand`, hipótesis y artefactos con hash.
- `inputs/od-implementation.json`: huellas de los módulos que determinan este
  comportamiento; se exige coincidencia para aceptar una ejecución posterior.
- `private_od_events` en los resultados de aceptación: programados, incorporados,
  completados, pendientes de incorporación, circulando, no llegados, abortados y
  pruebas nativas de despeje. Antes de QSim los valores observados son null.

El resultado distingue además salidas programadas/observadas, transiciones de
enlace, llegadas interiores, llegadas exteriores verificadas, nunca observados y
nunca incorporados. `evidence_status=not_finalized` no acredita cierre; el cierre
de un archivo válido no significa que todos sus viajes hayan llegado. La cadena
previa de validación completa de XML, hashes, iteraciones, colisiones, reservas,
servicios y estado del proceso sigue siendo obligatoria.

## Pruebas manuales

El archivo contiene 34 pruebas de cuotas grandes mediante aritmética, clases,
porcentajes exactos, direccionalidad, conectividad, geometría, hashes, ausencia de
insumos, acceso inválido, parada insuficiente, orígenes, capacidad, semilla,
horarios, XML, duplicados, auditoría nativa y separación de servicios. Incluye la
compatibilidad de las opciones `network` y conserva sus ramas existentes.
Las fixtures de generación usan 99 particulares como máximo. Los grandes N no
crean XML ni listas de vehículos. No son pruebas de integración QSim ni de sus
correcciones previas, y no sustituyen una revisión GIS.

Ejecutar **solo las pruebas nuevas** en PowerShell:

```powershell
$odPreviousErrorAction = $ErrorActionPreference
$ErrorActionPreference = 'Stop'
$odLocationPushed = $false
try {
    Push-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala\python'
    $odLocationPushed = $true
    if (-not (Test-Path -LiteralPath '..\.venv\Scripts\python.exe')) {
        throw 'No se encontró el Python del entorno .venv del proyecto.'
    }
    & '..\.venv\Scripts\python.exe' -B -m unittest -v -f test_simz1_balanced_gateway_od
    if ($LASTEXITCODE -ne 0) { throw "unittest terminó con código $LASTEXITCODE" }
    Write-Host 'PASS: pruebas de Corrección 5/5B.' -ForegroundColor Green
} catch {
    Write-Host ('FAIL: ' + $_.Exception.Message) -ForegroundColor Red
    throw
} finally {
    if ($odLocationPushed) { Pop-Location }
    $ErrorActionPreference = $odPreviousErrorAction
}
```

`-f` detiene unittest en el primer error/fallo. PASS se imprime únicamente si el
proceso real devuelve código 0; FAIL detiene el bloque con una excepción. Este
comando no descubre otros archivos de prueba ni ejecuta las regresiones Java.

No se ejecutó este comando. Se realizó revisión textual y `git diff --check`,
sin intérprete Python, compilación ni simulación. La comparación SHA256 con el
registro previo confirmó **171 archivos protegidos sin cambios**: implementaciones
y regresiones Java previas, lanzadores e insumos de red/carriles/catálogos/servicios.
Las Correcciones 1–4 se conservaron. No se repitieron sus once verificaciones.
No se escribió en los resultados históricos ni se amplió capacidad física.

En esta fase no interviene MATSim: ninguna fixture puede obtener PASS mediante
su ampliación automática de almacenamiento. Tampoco se afirma un PASS de estas
pruebas hasta que el usuario las ejecute. La habilitación real y cualquier corrida
posterior quedan pendientes de los insumos y de los resultados manuales.
