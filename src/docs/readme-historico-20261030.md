# Archivo del README operativo anterior

Conservado el 30 de octubre de 2026 antes de reorganizar la portada.
Este registro contiene referencias y comandos históricos; la entrada vigente
es el [README principal](../README.md). Los enlaces relativos se ajustaron
a esta ubicación sin cambiar el contenido técnico.

<!-- SHA-256 del README original: cb72a4689435f5077fbed2ba68527995289a1e7c8a98f37c6a231df0ce04c38d -->

---

# SimZ1 — Simulación de tráfico de la Zona 1 de Guatemala

## Composición vigente para corridas nuevas — 2026-10-29

Los lanzadores usan ahora **N no público = carros + motos + pesados**, con rango
masivo predeterminado **180000–220000**. Pesos normalizados: carros **16/37**,
motos **20/37**, pesados **1/37**. El transporte público mantiene su flota fija
**176 Transmetro + 93 TuBus = 269**, adicional a N, mediante
`transit/weekday-v2/service-fleet-176-93-v1.json`. El histórico `service.json`
conserva 80/40. No añadir `-FreightVehicles 12`.
N=1000 produce 432 carros, 541 motos, 27 camiones y 269 buses: **1269 vehículos**.
El HUD conserva **973 particulares** y **269 públicos**, con 27 de carga en el
desglose técnico. Los bloques antiguos que esperan 120/1120 deben actualizarse
para corridas nuevas; las cifras de corridas históricas no se reinterpretan.

El catálogo nuevo es `agent-types-nonpublic-v1.json`; los catálogos anteriores
conservan su significado histórico. N=0 deja únicamente el servicio público.
Consulta [contrato, límites y comandos manuales](simz1-composicion-vehicular.md) antes de usar los
comandos históricos de esta página: aquellos que indican N privado/carga
adicional no describen el nuevo predeterminado. Ajuste de escenario sintético,
no calibración empírica. Esta entrega no ejecutó pruebas ni simulaciones.

---

La [verificación de ocupación de octubre de 2026](simz1-verification-20261027.md)
registra las correcciones nativas y visuales, las pruebas y los resultados de V7/V8.
V8 completó y validó **100/100 viajes privados y 12/12 viajes de carga**; su
análisis y entregables están generados. Pasan 50 suites JavaScript y la auditoría
de 100 fotogramas en Chrome: cuatro familias visibles y cero contactos entre
los cuerpos reconstruidos. La cobertura excluye poses sin movimiento inferible;
algunas ventanas tardan minutos en cargar. El registro enlazado contiene evidencia
y comandos para el visor, la masiva y las gráficas.
Las siguientes pruebas de desarrollo usarán **100 privados**, con las flotas pública
y pesada adicionales. La aceptación visual final se registra por separado de la
integridad y del porcentaje de viajes completados.

Proyecto de tesis de Ingeniería en Ciencias de la Computación, Universidad del Valle de Guatemala. **SimZ1** combina una red vial importada de OpenStreetMap, demanda sintética reproducible y MATSim 15.0 con un visualizador WebGL continuo. La jornada de estudio dura 24 horas; el escenario temporal nuevo añade calentamiento y observación posterior en la misma ejecución. Su objetivo es estudiar la circulación, los tiempos de viaje, la congestión y las diferencias entre perfiles, **sin presentar la demanda sintética como aforos municipales medidos**.

## 1. Explicación resumida del proyecto

Cada corrida conserva sus semillas, un `run_id`, una configuración, un manifiesto de integridad y, si finaliza correctamente, los eventos nativos de MATSim. Los análisis históricos agrupan por **hora de salida simulada**; la política temporal nueva atribuye la cohorte principal a su **salida planificada dentro de la jornada**, aunque la salida efectiva o llegada ocurra después. Las duraciones corresponden únicamente a **viajes que llegaron**. Abandonos y viajes censurados se contabilizan aparte; no equivalen a viajes de duración cero.

La simulación utiliza colas QSim, no detección física continua de contactos. En el visor, los cuerpos y sus separaciones son reconstrucciones visuales. La política `strict-receiver-v1`, los cambios de carril, las cuatro clases OD, flota pública y los incidentes requieren comprobar su **configuración efectiva** antes de atribuirlos a una corrida. El módulo de **bloqueo nativo por carril debido a accidentes no está habilitado** en este código; los fixtures no equivalen a accidentes físicos simulados. Consulta [la documentación y matriz de validación](README.md#integracion-prompts-1-8).

## 2. Estructura del proyecto

```text
matsim-guatemala/
├─ AGENTS.md                       Contrato de trabajo del proyecto
├─ pom.xml                         MATSim 15.0 / bytecode Java 17
├─ scenarios/zona1/               OSM, red, carriles, señales y configuración
│  └─ montecarlo/run-*/            Resultados independientes de cada corrida (no en Git)
├─ python/
│  ├─ ejecutar_simz1.py            Generación, ejecución y validación de MATSim
│  ├─ procesar_eventos_z1.py       Procesamiento de eventos
│  ├─ generar_graficas_z1.py       Gráficas y comparaciones estadísticas
│  ├─ simz1_analysis.py            Publicación atómica del análisis
│  ├─ simz1_weekday_transit.py     Flota fija, horarios y entradas/salidas del dominio
│  ├─ simz1_congestion_audit.py    Diagnóstico de eventos sin repetir MATSim
│  ├─ simz1_result_quality.py      Finalización y anomalías, aparte de integridad
│  └─ serve_simz1_continuous.py    Servidor de replay continuo WebGL
├─ scripts/
│  ├─ simz1_workflow.ps1          Validar → limpiar → 1000 → masiva → WebGL
│  ├─ prepare_simz1_runtime.ps1   Compilar bytecode 17 y probar arranque
│  ├─ run_simz1_with_analysis.ps1  Corrida + gráficas, solo análisis o solo empaquetado
│  └─ replay/start_replay.ps1      Apertura del replay existente
└─ docs/README.md                  Guía técnica, contratos y limitaciones
```

## 3. Comandos de ejecución y resultados esperados

**Requisitos:** Windows + PowerShell, JDK 17 o superior (puedes conservar JDK 25), bytecode 17, Maven Wrapper y entorno `.venv` con las dependencias de `requirements.txt`. Ejecútalos desde la raíz:

```powershell
Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
.\.venv\Scripts\python.exe --version
java -version
```

### Jornada continua entre semana (2026-10-25)

La política optativa [weekday-continuous-v1.json](../scenarios/zona1/temporal/weekday-continuous-v1.json)
es la fuente única de horarios para generador, preflight, manifiesto y análisis.
Produce una **versión y carpeta nuevas**; no cambia eventos, planes, manifiestos,
SQLite ni entregables de la masiva histórica. Esta intervención no borra corridas.
Sin `-TemporalPolicy` se conserva el comportamiento temporal legado.

El ejemplo estudia el **miércoles 2026-10-28, America/Guatemala (UTC−06:00)**.
QSim utiliza segundos absolutos desde el martes a las 18:00 locales:

| Fase | Segundos técnicos | Hora civil local | Nuevas salidas particulares planificadas |
| --- | --- | --- | --- |
| Calentamiento | `[0,21600)` | Martes 18:00–miércoles 00:00 | Contexto previo |
| Jornada de estudio | `[21600,108000)` | Miércoles 00:00–jueves 00:00 | Cohorte principal, exactamente N |
| Observación con demanda posterior | `[108000,129600)` | Jueves 00:00–06:00 | Contexto del día siguiente |
| Drenaje final | `[129600,136800]` | Jueves 06:00–08:00 | Ninguna; continúan viajes e inserciones pendientes |

Son **6 h + 24 h + 6 h + 2 h**, configurables. No se reinicia la red al comenzar
la jornada ni al cruzar medianoche, y no se concatenan iteraciones como días.
El estado inicial procede de planes auxiliares simulados en el calentamiento.
La duración elegida no garantiza equilibrio ni ausencia de censura.

La intensidad sintética tiene nodos cada 15 minutos e interpolación lineal
continua, también entre 23:59 y 00:00. Usa un mínimo relativo de **0,12**, una
componente diurna de **0,6** y dos aumentos de **1,8**, con ascenso y descenso
graduales alrededor de **05:30–08:45** y **16:30–20:30**. Se muestrea la densidad
dentro de cada intervalo mediante su integral, sin acumular salidas en el minuto
00. Estos pesos son supuestos ajustables, no porcentajes oficiales ni una curva
de congestión impuesta. Los seis perfiles mantienen sus proporciones; por defecto
comparten esta curva. La semilla temporal independiente permite cambiar horarios
sin volver a sortear N, perfiles u orígenes/destinos de la cohorte principal.

Para **N=1000**, la asignación comprobada es **1000 principales + 320 de contexto
previo + 76 de contexto posterior = 1396 personas particulares en el XML**.
Los **120 buses configurados (80 Transmetro y 40 TuBus)** y sus conductores internos
siguen separados. Los buses obedecen calendarios de servicio de cada fecha, con
IDs de expedición distintos y la misma flota física; no se mantienen activos toda
la madrugada para rellenar la gráfica. Los manifiestos y el HUD distinguen N,
contexto y flota. Una prueba funcional de 1000 no valida la capacidad para 183154.

**Resultado nativo de la prueba nueva:** `simz1-ca9b7469f9bb480fb8764daf6a582455`,
iteración **0**, en `run-weekday-continuous-1000-20261028-95e674aa5f20`. Llegaron
los **1000 principales y los 396 auxiliares**, sin censura particular. El viaje
`ctx_pre_00311`, **21219..21625 s**, atraviesa físicamente el inicio de la jornada.
Al comenzar el drenaje había **48 vehículos activos**; antes de la limpieza final,
**0**. El máximo de las fotografías de progreso fue **65 activos**, no 65 vehículos
únicos ni un máximo continuo exacto.

De **8565 expediciones públicas programadas**, **7168 iniciaron y llegaron**;
las **1397 restantes tienen cancelación explícita**: **1324** por cierre civil
del servicio y **73** por corte de nuevas salidas del experimento. La disponibilidad
real del mismo bus propagó atrasos: mediana **2606,5 s**, percentil 95 **11785 s**.
El horario sintético requiere calibración; `screening_pass` corresponde al criterio
del proyecto para los particulares y **no acredita puntualidad ni cumplimiento
del calendario público**. La comprobación posterior de SQLite, API y navegador
confirmó la misma identidad, iteración y población; no se acreditó solo por el
arranque del servidor.

La primera apertura detectó otro error de presentación: el desglose por sistema
sumaba la misma flota por cada fecha y mostraba **240 Transmetro + 120 TuBus**.
El HUD corregido cuenta los IDs físicos distintos y deriva **80 + 40**, conserva
`declared_fleet_by_system` para auditar el dato original y no modifica el manifiesto
publicado, los eventos ni SQLite. El visor verificado está en
**http://127.0.0.1:8799/index.html**, servido por **python.exe, PID 19452**,
inicio **2026-10-25T23:09:26.9507910Z**. Ese PID identifica esta comprobación,
no un proceso que deba detenerse en futuras sesiones.

También se corrigió la omisión de **siete buses en paradas interiores**: sus
segmentos inmóviles `[P,P]` eran válidos, pero el renderizador los descartaba.
La regresión con datos reales recupera **56 de 56 posiciones representables**
a 48000 s (**07:20 locales**), usando posición, carril y parada nativos verificados;
el encuadre contiene **53 centros y deja 3 fuera de cámara**. Persisten **tres
cuerpos que exceden su enlace y tres solapamientos visuales**, reportados sin
atribuirlos a choques físicos. El último tramo de `ctx_pre_00311` tiene una
interpolación incompatible entre 21624 y 21625 s: se representa la entrada nativa
exacta a **21624 s**, con velocidad desconocida; a **21624,5 s** no se reconstruye
una posición interior sin evidencia. No se modifica la fuente publicada.

El barrido posterior corrigió otras tres omisiones de posiciones válidas: una
espera particular y dos tramos de bus desde una parada. Se conserva el centro
de la fuente y se declara la posición lateral desconocida, sin inventar carriles
ni colas. En **12 instantes comprobados**, los activos nativos, la API y los
marcadores representables coinciden, incluidos **57 a 90000 s** y **48 a 129600 s**.
Esto no elimina las incompatibilidades de cuerpos/solapamientos ni convierte las
interpolaciones entre eventos en posiciones medidas.

El navegador real confirmó esos conteos en mañana, tarde y comienzo del drenaje:
**56/56, 57/57 y 48/48** entre fuente y representables. En cámara quedaron
**53, 54 y 44 centros**, respectivamente. Reprodujo a 1x el cruce **21599→21602 s**
con el mismo vehículo, permitió pausa y seek, mostró la posición exacta a 21624 s
y se detuvo a **136800 s** con «fin de observación», sin reiniciar el día. La API
y el DOM muestran **N=1000, contexto=396 y flota=120 (80+40)**. El HTML recibido
coincide con el código final y usa `no-store`; las evidencias están en
`runtime/maintenance/temporal-weekday-20261025/`.
También se comprobaron reproducción **120x**, pausa, retroceso de **60 s** y
el recorrido del bus **TuBus 802_004**, conservando la tarjeta de seis campos.
`browser-final-8799-public-route.png` registra el estado final. La reapertura
PowerShell con `-NoBrowser` salió **0** y reutilizó fuente y servidor sin extraer
eventos ni repetir MATSim (`final-8799-reuse.log`).

La comparación de conservación de la referencia aprobó **539 archivos**, con
**487 hashes pequeños** revisados y sin cambios. Los nativos grandes conservaron
tamaño, fecha, identidad de archivo y manifiestos de integridad, sin releerlos
completamente. Esta intervención no eliminó corridas.

La validación consolidada terminó con **271 pruebas Python en 25 suites,
22 suites Node (incluidas 16 de renderizado), 4 comprobaciones nativas y
5 micropruebas QSim aprobadas**. Son verificaciones de contratos y de esta prueba
funcional; no certifican circulación masiva ni calibración del calendario público.

Validación de política y sensibilidad de sus integrales, sin generar población
ni ejecutar MATSim; este contrato de CLI está comprobado:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
    & .\.venv\Scripts\python.exe -B .\python\simz1_temporal.py `
        --policy .\scenarios\zona1\temporal\weekday-continuous-v1.json `
        --temporal-seed 20261028 --agents 1000 `
        --agent-catalog .\scenarios\zona1\agent-types-car-moto-v1.json `
        --sensitivity-hours 3,6,12 --output .\runtime\temporal-policy-validation.json
    if ($LASTEXITCODE -ne 0) { throw 'Politica temporal invalida; no ejecutar MATSim.' }
}
```

El preflight del lanzador se comprobó con `-TemporalPolicy`, `-TemporalSeed`,
`-ServiceDate 2026-10-28`, N fijo e `-Iterations 1`. `-DryRun` valida y muestra
el comando, **no ejecuta la prueba**:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
    $run = '.\scenarios\zona1\montecarlo\run-weekday-preflight-' + [guid]::NewGuid().ToString('N')
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_with_analysis.ps1 `
        -MinAgents 1000 -MaxAgents 1000 -Seed 20261023 -Iterations 1 `
        -TemporalPolicy .\scenarios\zona1\temporal\weekday-continuous-v1.json `
        -TemporalSeed 20261028 -ServiceDate 2026-10-28 `
        -TransitService .\scenarios\zona1\transit\weekday-v2\service.json `
        -AcceptTransitRouteAssumptions -StoragePolicy strict-receiver-v1 `
        -MinFreeGiB 10 -NewRunDir $run -DryRun
    if ($LASTEXITCODE -ne 0) { throw 'Preflight fallido; no se inicia la corrida.' }
}
```

El análisis conserva las gráficas de los tres perfiles de carro y los tres de
moto, y añade demanda/salida/inserción, activos/pendientes, llegadas/salidas y
completitud por cohorte. `active_end` es una fotografía; `active_mean` es el
promedio temporal del intervalo. Las medias de duración de dos o diez llegadas
vespertinas no acreditan tráfico fluido. CSV/JSON se publican en `docs/` y PNG
en `graficas/`, dentro del paquete de la corrida/iteración. El código **3** indica
`review_required` con resultados conservados, no una corrida aprobada.

La referencia masiva ya tenía demanda vespertina: sus problemas no se reducen a
la curva horaria. Se rastreó la fila omitida de la selección diaria hasta una
salida efectiva a **86400 s**, y se comprobó acumulación nativa muy superior a
los segmentos representados por el replay histórico. Esa fuente visual omite
tramos abiertos de colas; pocos marcadores no demuestran descongestión. La fuente
histórica permanece intacta, con aviso de fin de observación; las nuevas
exportaciones solo prolongan posiciones respaldadas por eventos nativos y
declaran geometría desconocida donde no se puede reconstruirla.
[Diagnóstico, contratos, evidencias y límites de la prueba](README.md#jornada-continua-20261025).

Los [comandos completos de análisis, apertura y escalado posterior](README.md#comandos-jornada-continua)
seleccionan la corrida explícitamente. La intermedia de 10000 y la masiva de 183154
están preparadas para **una iteración**, no se ejecutan automáticamente y no están
acreditadas por el preflight ni por la prueba funcional pequeña.

### Replay de la masiva existente, iteración 9 (2026-10-25)

La carpeta conservada es
`scenarios/zona1/montecarlo/run-massive-10it-e0ea36d7601a4548af18c252d4bf5e7e`,
con `run_id=simz1-eb9c02f113544d93a82c0954f38dd381` y diez iteraciones, **0..9**.
Su manifiesto contiene **183154 personas particulares**, separadas de los
**120 buses configurados: 80 Transmetro y 40 TuBus**. La calidad científica
permanece `review_required`; abrir el replay no cambia los resultados.
La fuente SQLite de la iteración 9 y su replay están publicados. La API de
`http://127.0.0.1:8793/index.html` confirmó esa identidad y población; el
proceso propietario registrado en la comprobación fue **PID 32400**. Ese PID
es evidencia de la sesión, no un identificador permanente para detener procesos.
La comprobación real del navegador cubrió cuatro ventanas con actividad,
reproducción, pausa, avance, retroceso y recorridos particulares y públicos,
con la tarjeta de seis campos. El bloque siguiente se ejecutó y reutilizó
el mismo servidor y fuente, sin nueva exportación (`reopen-tested.log`).

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
    $run = 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala\scenarios\zona1\montecarlo\run-massive-10it-e0ea36d7601a4548af18c252d4bf5e7e'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\simz1_workflow.ps1 `
        -Action View -RunDir $run -Iteration 9 -Port 8793
    if ($LASTEXITCODE -ne 0) { throw 'No se verifico el replay solicitado; conservar sus datos y revisar el mensaje.' }
}
```

`View` no ejecuta MATSim, no genera población ni análisis. Reutiliza la SQLite
declarada por el replay completo compatible; en esta masiva está en
`webgl-source-recovery-f9d0824baf294c4596fb61081d74ccb9`, dentro de la carpeta
protegida. Conserva el parcial original de `webgl-source` y no lo toma como
fuente publicada. Solo prepara derivados visuales faltantes de
la iteración solicitada. Si otro exportador sigue activo, se detiene sin iniciar
un segundo escritor. Durante esa preparación, **la URL antigua no acredita la
nueva corrida**. Antes de abrir, comprueba por HTTP identidad, iteración,
horizonte, población y huellas de fuente/replay. El cambio de un servidor SimZ1
anterior comprueba su PID actual, comando y hora de inicio; un servicio ajeno
no se cierra. [Evidencia y alcance](README.md#replay-masiva-20261025).

La limpieza selectiva terminó después de esas comprobaciones: eliminó **35
corridas anteriores y un derivado antiguo de runtime**, incluidos los resultados
de 100 personas, **31802740172 bytes lógicos (29,62 GiB)**. El aumento medido de
espacio libre fue **29,59 GiB**. La masiva, sus diez iteraciones y paquetes, la
fuente publicada y el parcial original permanecen íntegros. El inventario,
238 respaldos pequeños, exclusiones y verificación posterior están en
`runtime/maintenance/massive-replay-verification/`; el detalle está en
[la guía técnica](README.md#replay-masiva-20261025).

### Prueba de 100 particulares con transporte público (2026-10-24)

**Registro histórico.** Sus resultados y comandos documentan aquella prueba;
su carpeta fue eliminada en la limpieza selectiva y no es el replay que se debe
reabrir. Usa el [flujo de la masiva existente](#replay-de-la-masiva-existente-iteración-9-2026-10-25).

El bloqueo `transit_stop_position_unknown` confundía `useLanes=true` con carriles
explícitos en cada enlace. El replay ahora reconoce la cola única nativa de los
enlaces sin `lanesToLinkAssignment`, comprobando primero el XML efectivo y su
hash. Conserva la procedencia y rechaza los casos ambiguos.

Corrida: `scenarios/zona1/montecarlo/run-100-transit-stop-20261024-a7d9f2c6`,
`run_id=simz1-f9261a9936d64d1a86ee65d6e8075cf5`. Terminó `completed/valid`:
100 particulares (71 carros y 29 motos), 100 llegadas, sin abortos/censura;
120 buses adicionales (80 Transmetro + 40 TuBus), 5.779 expediciones completadas.
Las seis gráficas y sus tablas se publicaron en `entregables/<nombre-de-la-corrida>/`.
`screening_pass` acredita el criterio del proyecto, no calibración empírica.
Esta prueba de 100 **no autoriza la masiva ni sustituye el requisito de 1000**.

Para repetir con una carpeta nueva y fecha de servicio fija en viernes:

```powershell
Set-Location 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare_simz1_runtime.ps1 -RunSmoke
if ($LASTEXITCODE -ne 0) { throw 'Fallo compilacion/verificacion' }
$run = '.\scenarios\zona1\montecarlo\run-100-transit-stop-' + [guid]::NewGuid().ToString('N')
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_with_analysis.ps1 -MinAgents 100 -MaxAgents 100 -Seed 20261023 -Iterations 1 -ServiceDate 2026-10-23 -TransitService .\scenarios\zona1\transit\weekday-v2\service.json -AcceptTransitRouteAssumptions -NewRunDir $run
if ($LASTEXITCODE -ne 0) { throw "Revisar y conservar $run" }
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\simz1_workflow.ps1 -Action View -RunDir $run -Port 8793
```

El lanzador fija ambas semillas y horizonte de 24 horas. La reserva de cuerpos
por corredor usa un hilo QSim; `-LegacyPcuStorage -QSimThreads 4` conserva la
comparación con capacidad PCU histórica, sin atribuirle la nueva reserva física.
`View` exporta SQLite directo, prepara `webgl-continuo` y abre el servidor; no
genera 96 HTML. Antes de cambiar de corrida, identifica el dueño del puerto con
`Get-NetTCPConnection -LocalPort 8793 -State Listen`; no cierres procesos ajenos.
La apertura vigente es la de la masiva, iteración 9, indicada al inicio de este
documento; el antiguo comando de reapertura de 100 personas queda retirado.

[Diagnóstico, pruebas ejecutadas y evidencia](README.md#paradas-replay-20261024).

### Corrección de precisión en los turnos de buses

La generación usa microsegundos enteros para que las salidas, llegadas programadas
y transferencias conserven la misma precisión en el XML y el roster. El preflight
comprueba también el horario **serializado** con la tolerancia Java existente,
no solo hashes y cantidades. `serialized_timetable_pass` no certifica circulación
real. Si falló `ptbus_transmetro_L12_011` por `overlapping duty`, instala los archivos
corregidos y ejecuta de nuevo **Validate → Run1000**; no repitas `Clean`, no cambies
los tiempos mínimos ni edites el manifiesto de la corrida fallida.
[Diagnóstico y regresiones](README.md#precision-de-turnos-publicos-20261024).

### Recuperar una corrida que terminó pero falló leyendo eventos XML

Si Maven cerró con código 0 y la validación Python falló con
`TypeError: element indices must be integers` en `simz1_transit_events.py`, **no borres
ni vuelvas a simular esa corrida**. El lector corregido admite los elementos XML
reales y los diccionarios de las pruebas, conservando las verificaciones de buses.
`python/revalidar_simz1.py --run-dir <carpeta>` revisa en modo lectura; al añadir
`--apply` respalda el manifiesto y publica `completed/valid` únicamente si pasa el
validador completo. No reescribe eventos, horarios ni demanda; no cambia `latest-*`
ni autoriza por sí mismo el escalado. Después usa `-AnalysisOnly -RunDir <carpeta>`
y `-Action View -RunDir <carpeta>`.
[Comandos completos y alcance de las pruebas](README.md#revalidacion-xml-transporte-20261024).

### Prioridades de buses al revalidar resultados existentes

Si las pruebas XML pasan pero aparece `decision fuera de cruce elegible` para un
bus, revisa la evidencia de política, no cambies su ruta ni desactives la auditoría.
El emisor anterior registraba `simz1PriorityPolicy` solo para enlaces `car`, aunque
la lógica de cola también actuaba sobre enlaces `bus`. El emisor corregido usa
el mismo filtro para ambos y declara `policyCoverage=car-bus-v2`.

Para la corrida existente detenida originalmente por el TypeError XML,
`revalidar_simz1.py` permite reconstruir exclusivamente las políticas omitidas de
enlaces bus-only, a partir de la red/configuración verificadas de **esa corrida**.
Comprueba identidad de la flota, elegibilidad, señales, roles y tiempos; no modifica
eventos ni inventa cruces. El manifiesto distingue `native_policy_links` de
`reconstructed_bus_policy_links`. Una contradicción real sigue deteniendo el proceso.
No repitas MATSim ni borres la carpeta para hacer esta revalidación.
[Corrección, pruebas y comandos](README.md#prioridades-bus-only-20261024).

### Flujo recomendado tras la corrección del arranque

El `pom.xml` genera bytecode **Java 17 (major 61)** para MATSim 15 / Guice 5.1.
Se puede mantener el JDK 25 instalado. No usar compilaciones manuales `--release 25`
ni el antiguo parche con destino 21. `Validate` limpia únicamente clases regenerables,
compila los fuentes actuales, verifica las dependencias y ejecuta una prueba sintética
QSim de N=3 / B=2 (no una corrida de Zona 1). MATSim se lanza en otra JVM, no dentro
del cargador de clases de `exec:java`. Un fallo detiene el proceso; no imprime éxito.

Ejecuta cada comando por separado desde la raíz. No pegues `PS ...>` ni `>>`.

```powershell
# 1. Compilar, comprobar y ejecutar el caso sintético de arranque.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\simz1_workflow.ps1 -Action Validate

# 2. OPCIONAL Y DESTRUCTIVO: inventario y confirmación explícita de corridas antiguas.
# Cierra antes simulaciones, exportadores y servidores. No ejecutar mientras estén activos.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\simz1_workflow.ps1 -Action Clean

# 3. Prueba nueva: N=1000 (973 particulares + 27 camiones) + 269 buses; una iteración.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\simz1_workflow.ps1 -Action Run1000 -Seed 20261023 -ServiceDate 2026-10-23 -AcceptTransitRouteAssumptions

# 4. Preparar SQLite directo y abrir precisamente esa prueba, no una carpeta anterior.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\simz1_workflow.ps1 -Action View

# 5. Solo tras revisar la prueba; no se ejecuta automáticamente al terminar Run1000.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\simz1_workflow.ps1 -Action RunMassive -Seed 20261023 -ServiceDate 2026-10-23 -AcceptTransitRouteAssumptions
```

`Clean` elimina permanentemente solo carpetas `run-*` **listadas**, terminales y con
identidad comprobable bajo `montecarlo/`, `debug/` e `historical/`. Guarda sus
manifiestos, no los eventos. Omite resultados activos, archivos versionados, enlaces
simbólicos/reparse points, fuentes, bases con WAL y carpetas desconocidas. Conserva
`runtime/` y salidas externas: pueden seguir ocupando disco. Invalida los punteros
`latest-*` correspondientes. Se requiere escribir `BORRAR CORRIDAS SIMZ1`.

El plan v2 también exige el SHA256 del archivo revisado al aplicar, protege
obligatoriamente `run-massive-50it-ee85beafe608490b9c184b7b148b86e7` y las
dependencias de elementos conservados, e invalida `trial.json` y punteros de
replay afectados antes de borrar. El diario distingue eliminación parcial,
bytes lógicos y cambio observado de espacio libre. **Respaldar manifiestos no
recupera las simulaciones eliminadas.** Esta revisión solo prepara código y
regresiones; no se ha generado ni aplicado un plan. La comprobación manual de
espacio para 50 iteraciones está en el apartado técnico enlazado abajo: un umbral
de 30 GiB no constituye una estimación suficiente.

`RunMassive` exige una prueba de 1000 aceptada con la misma revisión. Además de la
calidad vial, verifica XML/roster contra el servicio guardado de esa corrida,
conductores y los IDs de todos sus buses con despacho y entrada nativa al tráfico,
tráfico público y ausencia de buses aún en red al corte. `review_required` conserva
archivos y bloquea el escalado; no prueba una excepción del motor ni calibración real.

Cada corrida imprime su **ruta exacta**. Para abrir la masiva, usa `-Action View -RunDir`
con esa ruta. Sin `-RunDir`, `View` abre solamente la prueba de 1000 registrada. La
exportación visual se hace al solicitar `View`, no genera cientos de páginas HTML.
Las gráficas PNG y sus CSV/JSON se publican durante la corrida, dentro de
`entregables/<nombre-de-corrida>/{docs,graficas}`. Los presupuestos de SQLite/temporales
son límites configurables y no garantías de espacio suficiente.

Para detalles técnicos y límites de verificación, consulta
[Arranque y reinicio controlado](README.md#arranque-y-reinicio-controlado).

### Uso directo del lanzador de análisis

**Revisar el comando sin ejecutar MATSim** (la ruta mostrada es solo un ejemplo; no crea la carpeta):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_with_analysis.ps1 `
    -MinAgents 150000 -MaxAgents 250000 -Seed 20261023 -MinFreeGiB 30 `
    -ServiceDate 2026-10-23 -AcceptTransitRouteAssumptions -DryRun
```

**Nuevo experimento Carro/Moto:** el lanzador pasa explícitamente
`agent-types-car-moto-v1.json`, `--origin-policy uniform-nodes-v1` y
`strict-receiver-v1`. Genera tres tipos de carro y tres de moto efectivos;
no solo etiquetas en el visor. Los orígenes se distribuyen entre nodos elegibles
para evitar que la regla histórica del 70 % se concentre en Avenida Elena.
Son supuestos sintéticos nuevos, no una calibración municipal. El catálogo
histórico y el generador sin opciones explícitas conservan su comportamiento.
El lanzador principal usa una **flota pública fija separada**: 176
Transmetro y 93 TuBus, también cuando N=0 o N=1000. Son cantidades y repartos
experimentales explícitos, no aforos ni unidades simultáneas dentro del mapa.
Se exige `-AcceptTransitRouteAssumptions`: reconoce los límites documentados
sobre trazados, tiempos exteriores y cuatro conflictos de sentido en las fuentes.
Sin ese consentimiento se detiene; **no continúa silenciosamente sin buses**.
`-NoPublicTransport` permite un control explícito sin flota pública. El transporte
pesado se agrega como servicio separado; `-NoFreightTransport` lo desactiva.
Los accidentes permanecen fuera de este experimento. Los comandos Python históricos
no activan por sí solos este contrato: usa el lanzador principal o pasa sus opciones
`--transit-service`, `--transit-service-date` y `--accept-transit-route-assumptions`.
La implementación nativa usa bytecode Java 17 y validación QSim local;
las comprobaciones de preparación no certifican circulación real.

**Primero validar la integración pública con N=1**, después de compilar Java.
Mantén los mismos parámetros del siguiente comando, usando `-MinAgents 1 -MaxAgents 1`.
Debes obtener N=1, B=269 y cero conductores públicos añadidos a N. La fecha
`2026-10-23` selecciona un viernes modelado; no se toma automáticamente el día del
reloj del equipo. No hay aún calendario de feriados. Verifica las entradas nativas,
paradas y retornos; **un contador B=269 no prueba que circularon 269 unidades**.

**Después una prueba pequeña de los seis perfiles**, sin sobrescribir corridas:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_with_analysis.ps1 `
    -MinAgents 120 -MaxAgents 120 -Seed 20261023 -Iterations 1 -MinFreeGiB 10 `
    -ServiceDate 2026-10-23 -AcceptTransitRouteAssumptions
if ($LASTEXITCODE -ne 0) { throw 'Revisar la corrida o su calidad; no escalar automaticamente.' }
```

Comprueba los conteos, llegadas y diagnóstico antes de repetir con
`-MinAgents 1000 -MaxAgents 1000`. Solo después usa la corrida masiva.

**Generar una nueva corrida de 150 000 a 250 000 personas y sus gráficas**, siempre en una carpeta nueva. Puede requerir bastante tiempo, memoria y disco. El script utiliza el modo OD `network` y `--no-incidents`, no afirma tener todas las funciones experimentales activadas:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_with_analysis.ps1 `
    -MinAgents 150000 -MaxAgents 250000 -Seed 20261023 -Iterations 1 -MinFreeGiB 30 `
    -ServiceDate 2026-10-23 -AcceptTransitRouteAssumptions
```

Se espera `MATSim completed/valid` **y**, por separado, `GRAFICAS GENERADAS`, `ENTREGABLE` y `screening_pass` con dos carpetas (`docs/` y `graficas/`). El lanzador genera automáticamente las gráficas después de validar MATSim; la segunda verificación reutiliza sus productos si coinciden los hashes. `BUILD SUCCESS` de Maven **no** equivale a una corrida validada. **No ejecutes análisis oficial cuando falte `output_events.xml.gz`**.

El control de calidad exige los seis perfiles cuando N >= 6 (no los exige con N=1) y, por defecto, al menos 90 % de
etapas completadas sin anomalías terminales pendientes. Este 90 % es un umbral
explícito de revisión del proyecto, **no una regla de validez universal ni
calibración**. `-MinCompletionRate` modifica solo la comprobación del lanzador;
`calidad_resultados.json` declara su umbral estándar de 0.90. Si requiere revisión,
el lanzador termina con error **después de conservar las gráficas y el paquete**;
no cambia la corrida de `completed/valid` a `failed`, ni inventa llegadas.
No reduzcas el umbral para ocultar un atasco.

**Reintentar solamente las gráficas de una corrida anterior ya validada**, sin repetir MATSim:

Ejemplo histórico de `run-mc-verified-d8fc4f9da2c348f09d5536d63e639b8e`,
eliminada en la limpieza selectiva; no forma parte de la reapertura actual. Los diez análisis
y entregables de la masiva están completos y no requieren este comando.

```powershell
$run = '.\scenarios\zona1\montecarlo\run-mc-verified-d8fc4f9da2c348f09d5536d63e639b8e'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_with_analysis.ps1 `
    -AnalysisOnly -RunDir $run
explorer.exe (Join-Path (Resolve-Path $run).Path ('entregables\' + (Split-Path $run -Leaf) + '\graficas'))
```

La estructura lista para compartir es `<corrida>/entregables/<nombre-de-corrida>/docs` (CSV/JSON) y `graficas` (PNG). Ese nombre sin sufijo identifica la iteración 0; las demás utilizan `<nombre-de-corrida>-it.N`. Cada manifiesto registra corrida, iteración y fuentes. Los artefactos canónicos permanecen en `analysis/it.N` y `output/`. Un paquete completo compatible se reutiliza tras verificar identidad, versión y hashes; una copia incompatible se prepara y verifica aparte antes de sustituirla con respaldo y recuperación.

**Recuperar solo el empaquetado de las diez iteraciones existentes**, sin generar
análisis, invocar MATSim ni reconstruir eventos/SQLite/Motion_Plan:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
    $run = 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala\scenarios\zona1\montecarlo\run-massive-10it-e0ea36d7601a4548af18c252d4bf5e7e'
    $runId = 'simz1-eb9c02f113544d93a82c0954f38dd381'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_with_analysis.ps1 `
        -PackageOnly -RunDir $run -ExpectedRunId $runId
    $code = $LASTEXITCODE
    if ($code -eq 3) { Write-Warning 'Paquetes completos; screening review_required. Revisar calidad sin repetir MATSim.' }
    elseif ($code -ne 0) { throw "Recuperacion incompleta (codigo $code); conservar paquetes, temporales y diagnostico." }
    else { Write-Host 'Paquetes completos; screening_pass.' }
}
```

Repetir el bloque comprueba la reutilización. `-PackageOnly` exige la carpeta
explícita y valida los análisis publicados; no busca `latest-successful`.
Sus códigos son **0** (paquetes completos y screening aprobado), **3** (paquetes
completos y screening requiere revisión) y **1** (fallo). Un análisis faltante o
incompatible requiere `-AnalysisOnly`; no se publica como completo. Los detalles
de bloqueo, respaldo y diagnóstico están en [entregables](README.md#entregables-separados-para-cada-corrida-csvjson-y-png).

Al actualizar el código analítico, el fingerprint puede cambiar: **no uses
`-AnalysisOnly` sobre un paquete histórico publicado para forzar su reemplazo**.
Para estudiar esa corrida conservándola, usa el diagnóstico separado siguiente:

El siguiente bloque conserva el ejemplo histórico de `run-mc-verified`; su
ruta fue eliminada y no es una selección vigente ni una instrucción para regenerar derivados.

```powershell
$run = '.\scenarios\zona1\montecarlo\run-mc-verified-d8fc4f9da2c348f09d5536d63e639b8e'
& .\.venv\Scripts\python.exe -B .\python\simz1_congestion_audit.py --run-dir $run --iteration 0 --events
if ($LASTEXITCODE -ne 0) { throw 'Diagnostico detenido; conservar datos originales.' }
```

Lee los eventos existentes en streaming y crea un JSON nuevo en
`analysis/it.0/diagnostico_trafico/`; no simula ni modifica eventos, CSV nativo,
red, manifiesto o estadísticas publicadas. La lectura de una corrida masiva puede
ser costosa. Distingue vehículos que abordaron pero no entraron a la red, etapas
sin llegada tras entrar, esperas del receptor y ciclos candidatos por hora.

Sustituye `$run` por **la carpeta que contiene `run-manifest.json`**. El análisis no acepta corridas con `status=failed`, aunque Maven haya indicado `BUILD SUCCESS`. Si únicamente falla el postproceso, el estado es `analysis_failed` y MATSim permanece validado; repite `-AnalysisOnly`. Si no aparecen eventos nativos, inspecciona el manifiesto y el `matsim-run.log` antes de programar otra corrida.

## 4. Cómo utilizar el sistema y qué significa cada elemento

**Abrir el visor WebGL de la masiva existente:** usa el
[bloque completo de apertura de iteración 9](#replay-de-la-masiva-existente-iteración-9-2026-10-25).
Ese flujo valida y reutiliza el replay publicado, sin repetir exportación,
MATSim, análisis ni empaquetado. Sustituye el antiguo ejemplo de preparación
manual de `run-mc-verified`, cuya ruta ya no es una selección operativa.

La URL es **http://127.0.0.1:8793/index.html**. El lanzador abre una URL con la
identidad solicitada y la comprueba por HTTP. `Ctrl+C` detiene únicamente un
servidor iniciado por esa consola; si se reutilizó otro, el lanzador lo informa.
Consulta [el contrato de fuente y reanudación](README.md#replay-masiva-20261025)
antes de intervenir un parcial; la ausencia de checkpoint no permite publicarlo
como completo ni sobrescribirlo.

La barra conserva **hora simulada**, **Visibles** y controles. La esquina inferior
derecha muestra solamente **Vehículos particulares: N · Transporte público: B**.
N usa la cohorte principal con política temporal, o los particulares configurados
en otro caso, únicamente con equivalencia persona/vehículo acreditada. B cuenta
IDs únicos de flota pública configurada; sin evidencia se muestra **—**, no cero.
Identidad, semillas, fechas, contexto, Transmetro/TuBus, carga, expediciones y
diagnósticos quedan en **Ayuda**. La tarjeta mantiene seis campos y presenta
**Vehículo &lt;identidad disponible&gt;**, sin cambiar IDs ni datos históricos.
El cambio y sus regresiones están preparados, sin ejecutar; el refresco del
cliente ligero está descrito en [Visor, API y SQLite](README.md#visor).
B no significa buses activos simultáneos. Los buses
aparecen solo durante intervalos nativos dentro de la red; las ausencias exteriores
están registradas, no son trayectorias invisibles inventadas. Las paradas respaldadas
son verdes (Transmetro) y azules (TuBus). La ruta 104 no incorpora paradas ficticias
cuando faltan sus ubicaciones. Consulta [flota entre semana](README.md#flota-publica-entre-semana-v2)
para reparto, horarios, hipótesis de acceso y comandos de prueba.
 `1x` y `120x` cambian la velocidad del reloj del replay, no la dinámica de MATSim ya ejecutada. Los vehículos usan colores de velocidad: **verde** mayor que 40 km/h, **amarillo** de 15 a 40 km/h, **rojo** menor que 15 km/h y **blanco** para 0 km/h según la leyenda del visor. La presencia de rojo/blanco no prueba por sí sola un accidente. Selecciona un vehículo con clic para ver su tarjeta (identidad, tipo, velocidad y tiempos simulados); la ruta seleccionada diferencia recorrido registrado de posición actual. Las etiquetas y hitboxes son visuales; no garantizan seguimiento físico microscópico ni eliminan un conflicto nativo.

Al comprobar una ejecución, verifica `run-manifest.json`: `completed/valid` exige cierre y salidas nativas verificadas. `failed/invalid` significa que esa corrida **no** debe utilizarse para estadísticas oficiales. `analysis_failed` significa que los gráficos no pudieron publicarse, sin invalidar por sí mismo un MATSim ya `completed/valid`.

## 5. Cómo entender las gráficas

Las figuras canónicas se guardan en `analysis/it.0/graficas_perfiles/` (o `it.N`). Las **copias organizadas** aparecen en `entregables/<nombre-de-corrida>/graficas/` (PNG) y `docs/` (CSV/JSON):

| Archivo | Interpretación |
|---|---|
| `carros_por_hora.png` | Duración media por **hora de salida**: Carro, Carro Tortuga y Carro liebre. |
| `motos_por_hora.png` | Comparación de Moto, Moto tortuga y Moto Liebre, **solo si existen en la corrida**. |
| `comparacion_familias_por_hora.png` | Comparación Carro/Moto, ponderada por la cantidad real de viajes completos. |
| `comparacion_global_perfiles.png` | Media diaria por perfil y tamaño de muestra. |
| `completitud_por_hora.png` | Completados, abortados y censurados por tipo/hora. |
| `duration_distribution.png` | Histograma de duración de viajes completados, separado de las medias. |
| `estadisticas_por_perfil_hora.csv` | Media, mediana, P95 y conteos por perfil/hora para análisis reproducible. |
| `calidad_resultados.json` | Finalización, perfiles ausentes y anomalías pendientes; no certifica realismo. |
| `resumen_perfiles.json` | `run_id`, iteración, definiciones, fuentes y estadísticas agregadas. |

**Eje X:** hora de salida (00–23). **Eje Y:** minutos simulados que tardaron los viajes *completados*. `SD` significa que ese perfil/hora no tiene datos y `SC` que no terminó ningún viaje; **no son cero minutos**. Un asterisco indica muestra pequeña según el mínimo configurado. Compara las medias **junto con la completitud**: un promedio menor podría deberse a que los viajes más lentos no llegaron. Las tres categorías de motos no deben aparecer artificialmente en corridas históricas que solo contienen carros. Las comparaciones de escenarios con y sin incidentes requieren políticas activadas, entradas equivalentes y fuentes verificadas.

Para el catálogo ejecutable, la reconciliación terminal y pruebas usa [la corrección Carro/Moto y censura](README.md#correccion-carro-moto-y-censura-20261023); para el resto del sistema, [la guía técnica completa](README.md).

Los CSV/JSON de flota y sus metadatos siguen separados de las medias de carros/motos.
Los horarios son ventanas de expedición, no promesas de llegada sin retrasos.

# Transporte pesado en SimZ1

El flujo `scripts/run_simz1_with_analysis.ps1` agrega un servicio de carga
independiente de `MinAgents`/`MaxAgents`, además de Transmetro/TuBus.
Configuración: `scenarios/zona1/freight/weekday-v1/service.json`;
cantidad: `-FreightVehicles`; desactivación: `-NoFreightTransport`.
Consulta [reglas, trazabilidad y comandos de prueba](simz1-freight.md).

El cierre de carga registra incumplimientos sin lanzar excepciones horarias en
el handler de eventos; rechaza la iteración después del cierre de QSim. Separa
espera de inserción, residencia en tráfico y resultado del viaje. Implementación
y regresiones preparadas, **sin ejecutar**; evidencia histórica y diagnóstico
manual pendiente en [Servicio de carga SimZ1](README.md#servicio-de-carga-simz1).

La [revision de ocupacion y separacion](simz1-occupancy.md) distingue
bloqueo nativo de paradas, espaciado geometrico y limites aun pendientes.
Una corrida `completed/valid` no certifica separacion microscopica global.
