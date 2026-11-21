# C529-B â€” Contrato privado OD en el routing nativo

El candidato de `z1_60650:trip:0001` instalado a 720 s conservaba el destino,
pero omitÃ­a `osm_1196283991_0_backward`, el comienzo obligatorio de su cadena
de salida. La validaciÃ³n anterior de Java aceptaba sus 76 enlaces: comprobaba
red, secuencias OSM, prefijo, destino y carril, sin recibir el contrato OD.
`SimZ1TurnRouter` buscaba hasta el destino sin estado de gateway; el binding
de `ExperiencedTimeRouting` tenÃ­a la misma omisiÃ³n. El auditor Python rechazaba
correctamente la ruta con `Private route skipped part of its verified exit chain`.
La llegada histÃ³rica de 1111 s sigue sin acreditar cumplimiento OD.

La regresiÃ³n reutiliza `monitor_first_rejection.json`, el plan de
`early_case_plans.json`, `rerouting_decisions_summary.json`, `code_excerpts.txt`,
`code_sources.json` y la secciÃ³n 5 de `DIAGNOSTICO_C529.md`. Reconstruye las cuatro
fuentes anteriores desde el commit `91d3ffce66bee80da3f0450e9d98a5a0316b3ec7`
y exige sus hashes de C529 antes de compilarlas, sin reset del repositorio.
El escenario de prueba carga Ãºnicamente red y carriles efectivos del histÃ³rico;
no carga su poblaciÃ³n en MATSim ni ejecuta una simulaciÃ³n.

La prueba anterior confirma que la validaciÃ³n nativa admite el candidato exacto.
TambiÃ©n hace que el router real produzca esos mismos 76 enlaces con costes
focales que favorecen sus movimientos. Esos costes son una fixture sintÃ©tica:
no reconstruyen la serie de tiempos experimentados de 720 s. El candidato
comparado, el Ã­ndice 2, el enlace actual y el carril sÃ­ provienen literalmente
del evento registrado.

Con la reparaciÃ³n, ese candidato se rechaza antes de instalarlo. Con los mismos
costes focales, la bÃºsqueda produce una alternativa de 78 enlaces, conserva el
prefijo realmente recorrido y termina en:

```
osm_1196283991_0_backward
â†’ osm_60237264_2_forward
â†’ osm_60237264_3_forward
```

La alternativa pasa la validaciÃ³n Java y el mÃ©todo original del auditor Python.
Esto acredita compatibilidad de ruta, no circulaciÃ³n ni llegada observada.

El contexto llega al router de esta forma:

1. `SimZ1TripOd` lee el `run-manifest.json` asociado al contexto del config.
   Para `balanced-gateway-v1` comprueba el catÃ¡logo fijado, sus cadenas, las
   identidades de red/carriles efectivos y la versiÃ³n de secuencias OSM.
   Usa los enlaces permitidos y las cadenas ya verificadas del manifiesto.
   Recupera el dominio interior quitando Ãºnicamente las porciones exteriores
   y los cruces clasificados por esas cadenas. La prueba compara ese conjunto
   completo con `model.interior` del modelo geomÃ©trico Python original.
2. La pierna aporta `simz1TripId`; `simz1Trips` verifica persona, ordinal y
   extremos; `simz1SpatialOD[simz1TripId]` aporta clase, gateways y observaciones.
   La ausencia o contradicciÃ³n de un contrato requerido causa rechazo explÃ­cito.
3. MATSim 15 `PlanRouter` pasa a `RoutingRequest` los atributos de la actividad
   de origen. `bindPlans()` copia allÃ­ el ID existente una vez, en memoria,
   antes del routing. Las copias nativas de planes lo heredan. `forRequest()`
   contrasta la actividad real y su pierna, o un ID explÃ­cito de solicitud,
   con los metadatos del viaje. No elige por extremos iguales ni por horario.
   La pierna devuelta conserva el ID y el `PlanRouter` conserva el vehÃ­culo.
4. El reruteo por congestiÃ³n usa la pierna actual y el prefijo nativo completo
   hasta el Ã­ndice de ocurrencia actual. `candidate()` construye y valida una
   propuesta sin modificar ruta, cursor ni reservas. La instalaciÃ³n conserva
   despuÃ©s el guard existente `SimZ1CorridorOccupancy.replacementIssue()`.

La bÃºsqueda usa un Ãºnico estado compuesto: progreso OSM existente, historial
de vÃ­as OSM ya usado y progreso OD. Este Ãºltimo conserva la entrada pendiente,
el prefijo de cadena de salida, los cruces efectuados y la visita al interior.
Antes del cruce de salida se puede revisitar su observaciÃ³n; despuÃ©s del cruce,
la cola completa de la cadena es obligatoria. No se enrutan tramos independientes
ni se reinicia el autÃ³mata en sus uniones. Los enlaces repetidos se procesan
secuencialmente usando el Ã­ndice nativo. Los Ãºnicos `indexOf()` nuevos consultan
cadenas de catÃ¡logo cuya unicidad se verifica, nunca el recorrido del agente.

Las cuatro clases usan sus propias cadenas: una clase interior no recibe cadenas
inexistentes. El dominio privado no cambia el grafo global de carros, buses o
camiones. Se conserva el servicio explÃ­cito `SimZ1Freight.applies`, la identidad
de transporte pÃºblico existente y la compatibilidad histÃ³rica sin contrato
privado o con `synthetic_gateway_od`. Un viaje con el esquema privado nuevo no
puede usar esa compatibilidad para omitir un artefacto requerido.

| Archivo Java | Cambio |
| --- | --- |
| `SimZ1TripOd.java` (nuevo) | Carga de artefactos, vinculaciÃ³n por viaje y estado OD inmutable por consulta. |
| `SimZ1RouteSafety.java` | Sobrecarga de `validateReplacement` con contrato del viaje. Los controles fÃ­sicos existentes permanecen. |
| `SimZ1TurnRouter.java` | BÃºsqueda con estado OD y OSM continuo; rechaza omitir un contexto requerido. |
| `CongestionAwareRerouting.java` | PreparaciÃ³n pura `candidate()` utilizada por `attempt()`; motivo real de rechazo antes de la instalaciÃ³n. |
| `ExperiencedTimeRouting.java` | Contexto del viaje en el binding car utilizado por ReRoute estÃ¡ndar. |

Las pruebas nuevas son `SimZ1OdHistoricalBeforeCheck`, `SimZ1OdContractCheck` y
`SimZ1OdReservationsCheck`, coordinadas por `python/test_simz1_native_od.py`.
La salida reproducible final estÃ¡ en
[`runtime/c529-b-jerirbwr`](../runtime/c529-b-jerirbwr/), con comandos y cÃ³digos
en [`focused-results.json`](../runtime/c529-b-jerirbwr/focused-results.json),
rutas en `java-cases.json`, comparaciÃ³n en `python-parity.json` e integraciÃ³n en
`integration.json`. Son resultados de fixtures de routing, no de una corrida.

Cobertura focal:

- Candidato histÃ³rico rechazado y alternativa compatible encontrada.
- Entrada pendiente/completa, antes/dentro de salida, observaciÃ³n de salida
  repetida y segunda ocurrencia de un enlace interior.
- Igual destino con cadena equivocada, salto de entrada y salida del dominio.
- Contrato ausente, gateway inconsistente, ordinal incorrecto y dimensiones
  mal tipadas; ausencia de alternativa conserva el destino y el estado nativo.
- Cuatro clases OD; ReRoute estÃ¡ndar real sobre planes no seleccionados y
  distintos viajes con los mismos extremos; conservaciÃ³n de ID de vehÃ­culo.
- Secuencia 17478998 en la uniÃ³n con una cadena obligatoria: una llegada legal
  puede continuar y el prefijo prohibido no se reinicia para hacerla pasar.
- Preparaciones repetidas con `BasicPlanAgentImpl` y cursor nativo controlado.
- Diez propuestas aceptadas y diez rechazadas sobre un ledger ocupado: snapshot
  idÃ©ntico de reservas, locks, ordinales y eventos, ademÃ¡s de ruta/cursor intactos.
- Paridad Java/Python sobre 26 rutas, sin reemplazar mÃ©todos del auditor.
- Regresiones existentes: `RouteSafetyCheck`, `FastestTimeRoutingCheck`,
  `GatewayRouteSafetyCheck`, `Restriction17478998Probe`,
  `SimZ1OpposedReturnRerouteCheck`, `SimZ1ReturnSignalRerouteCheck` y el
  componente `rerouting()` de `SimZ1TransitDiagnosticsCheck` (sin exportar trazas
  de llegada). Tambi?n se comprueba el permiso nativo de un bus registrado fuera
  del dominio privado.

`scripts/simz1_workflow.ps1` invoca la prueba focal antes de escribir una aprobaciÃ³n.
El fingerprint existente incluye automÃ¡ticamente las fuentes Java, las pruebas
y el runner Python nuevos; se comprueba mediante mutaciones en un Ã¡rbol sintÃ©tico.
`python/test_simz1_sequence_contract.py` incorpora la nueva clase en su compilaciÃ³n
focal. Sus cuatro exclusiones previas de routing Java se sustituyen por hashes
exactos de versiones revisadas, incluyendo los cambios autorizados de Correction 7
y C529-B. No se eliminan protecciones, no se altera el baseline histÃ³rico y no
se actualizan recibos. Se comprueban 112 fuentes protegidas y las siete pruebas
de mutaciÃ³n de expectativas. Los tres hashes de Java de C529-A permanecen iguales.

Desde la raÃ­z, con las evidencias histÃ³ricas existentes y JDK17:

```powershell
.\.venv\Scripts\python.exe -B .\python\test_simz1_native_od.py
```

La compilaciÃ³n y todos los procesos de la ejecuciÃ³n final terminan con cÃ³digo 0.
No se ejecutaron Controller, QSim.run, Validate completo, DryRun ni otra corrida.
No hay certificados de llegada ni manifiestos completed/valid nuevos. No se
comprobaron rendimiento, congestiÃ³n, progresiÃ³n de colas o resultados OD a escala
180000. La corrida histÃ³rica no queda aprobada. C529-A, el auditor Python,
histÃ³ricos y recibos se conservan; no se avanza a otra tarea.
