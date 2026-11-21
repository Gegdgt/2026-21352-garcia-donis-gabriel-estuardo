# Composición vehicular — 30 de octubre de 2026

## Contrato vigente de las corridas nuevas

Los lanzadores `run_simz1_with_analysis.ps1` y `simz1_workflow.ps1` utilizan
`scenarios/zona1/agent-types-nonpublic-v1.json` y el servicio de carga
`scenarios/zona1/freight/weekday-v2/service-composition-v2.json`.
La versión de rutas de carga cambia a `weekday-v2`; se mantienen la cantidad
derivada de N, el reparto de carros/motos y los 269 buses.

**N = carros + motos + transporte pesado. Los buses NO están incluidos en N.**
El rango predeterminado masivo es **180000..220000**. Es una sola selección
reproducible dentro del rango, no un barrido de todos los tamaños. Cada vehículo
no público tiene un viaje/expedición en esta configuración diaria.

Los pesos propuestos de carro:moto:pesado son 40:50:2.5. Se normalizan sobre 92.5:

| Familia | Fracción exacta de N | Porcentaje objetivo |
| --- | --- | --- |
| Carros | 16/37 | 43.243243… % |
| Motos | 20/37 | 54.054054… % |
| Pesados | 1/37 | 2.702702… % |
| Transporte público | Fuera de N | Flota y programación independientes |

No son porcentajes medidos ni una calibración de Zona 1. El rango y los pesos
son supuestos solicitados para experimentar. Un total de vehículos generados
no es ocupación simultánea, ni demuestra que todos esos viajes llegaron.

La flota pública nueva es **176 Transmetro + 93 TuBus = 269 vehículos únicos**,
independiente de N, incluso con N=0. Es un supuesto solicitado para el escenario,
no un aforo, asignación oficial ni evidencia empírica de unidades en el sector.
La selección predeterminada y explícita de los lanzadores es
`scenarios/zona1/transit/weekday-v2/service-fleet-176-93-v1.json`.
`service.json` conserva exactamente el servicio histórico 80/40; puede elegirse
con `-TransitService` o `--transit-service` para reproducibilidad.

El reparto por línea también es sintético: mayores restos dentro de cada sistema,
partiendo de las cuotas históricas, con desempate por `service_id` ascendente.
Para TuBus, el último asiento empatado corresponde a 105 antes que R5.

| Sistema | Línea | Histórica | Nueva |
| --- | --- | ---: | ---: |
| Transmetro | L1 | 8 | 18 |
| Transmetro | L2 | 5 | 11 |
| Transmetro | L6 | 12 | 26 |
| Transmetro | L7 | 12 | 26 |
| Transmetro | L12 | 20 | 44 |
| Transmetro | L13 | 10 | 22 |
| Transmetro | L18 | 13 | 29 |
| **Transmetro total** | | **80** | **176** |
| TuBus | 104 | 12 | 28 |
| TuBus | 105 | 8 | 19 |
| TuBus | 802 | 12 | 28 |
| TuBus | R5 | 8 | 18 |
| **TuBus total** | | **40** | **93** |

Se reutiliza el generador existente con las mismas rutas, paradas, horarios,
dwell, retornos, tiempos exteriores y modelos rígidos de 13.5/12 m; no cambian
PCU ni física. Se recalculan los turnos para las nuevas cantidades, reutilizando
cada ID sin solaparlo ni duplicarlo para cumplir un horario. Los retrasos y
cierres siguen vigentes: 269 configurados no son 269 simultáneos ni servicio 24 h.

La aceptación lee la política guardada y verificada de ESA corrida, contrasta
cuotas, XML, roster e IDs con eventos de despacho y entrada al tráfico. Nunca
usa el servicio predeterminado actual para reinterpretar una corrida histórica.
Si un resumen histórico no guardó IDs observados, se leen sus eventos con huella.

### Redondeo y perfiles

Se reserva primero la cuota de carga frente a particulares (1:36), después se
reparten los particulares entre carros y motos (4:5), y finalmente los perfiles.
Cada nivel usa mayores restos y un desempate canónico. La suma entera es exacta;
por tamaños pequeños puede haber categorías sin representación.

Dentro de carros se conserva Normal:Liebre:Tortuga = 4:1:1. Dentro de motos se
conserva Lenta:Normal:Rápida = 1:2:1. No se cambian velocidades, dimensiones,
PCU, aceleraciones ni el comportamiento de esos perfiles.

| N | Carros | Motos | Pesados | Buses adicionales |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 0 | 0 | 0 | 269 |
| 1000 | 432 | 541 | 27 | 269 |
| 50000 | 21622 | 27027 | 1351 | 269 |
| 180000 | 77838 | 97297 | 4865 | 269 |
| 200000 | 86487 | 108108 | 5405 | 269 |
| 220000 | 95135 | 118919 | 5946 | 269 |

La distribución exacta aparece en `inputs/demand-composition.json` y en
`run-manifest.json -> demand_composition`. Los campos históricos
`planned_persons` y `road_demand_persons` siguen contando únicamente conductores
particulares; no se renombran ni se les suman conductores de buses. Se añaden
`non_public_vehicles_configured`, `private_vehicles_configured` y
`all_vehicles_configured`. Por ejemplo, N=200000 significa 194595 particulares,
5405 pesados y 269 buses. El HUD conserva su contador de **particulares**, con
la carga en la información técnica: no confundir ese contador con el nuevo N.
Para N=1000: HUD **973 particulares / 269 públicos**, carga **27** en el
desglose técnico y total configurado **1269**. Los bloques antiguos que esperan
120 buses o 1120 vehículos totales deben actualizarse al usar el servicio nuevo.

El análisis conserva los denominadores privados y añade
`composicion_demanda.csv` y `composicion_demanda.json` al paquete de `docs`.
Son cantidades configuradas, no resultados de viaje. Se conservan las métricas
existentes y los datos nativos; esta intervención no incorpora gráficas nuevas
de flujo/colas ni una nueva comparación estadística entre todos los servicios.

## Transporte pesado

La carga sigue usando su generador dedicado. Sus cuatro rutas representan
transporte de paso por corredores principales: accesos distintos del perímetro,
sin entregas, estacionamientos ni destinos internos. `weekday-v2` conserva los
tramos aptos de las cuatro rutas históricas y reemplaza recorridos inadecuados,
respetando la conectividad dirigida y los giros de carril. La cuota se calcula
desde N; no hace falta indicar una cifra externa de 12.
**No uses `-FreightVehicles 12` con el catálogo nuevo**; una cifra que contradiga
la cuota es rechazada. Para N=0 no se generan camiones.

El servicio conserva `stratified-feasible-windows-v1`: cuotas equilibradas por
ruta y salidas estratificadas en las ventanas permitidas, con duración mínima
de ruta y el margen configurado. Así no acumula miles de salidas añadiendo 120 s
indefinidamente hasta rebasar los horarios. Se mantienen los cuerpos, PCU y
ventanas. La programación recorta las salidas para que, en flujo
libre y con el margen existente, terminen antes del horizonte diario de 86400 s.
**No garantiza que salgan a tiempo con congestión**: las auditorías nativas
siguen detectando infracciones, abortos y viajes pendientes.

El servicio nuevo declara `service_version=weekday-v2` y
`route_policy=principal-through-v2`. Conserva `schema_version=simz1-freight-weekday-v1`
para la compatibilidad del actor nativo. Los servicios y rutas de `weekday-v1`
permanecen disponibles para reproducibilidad; la corrida fallida se interpreta
con sus insumos guardados. La selección de corredores no acredita capacidad
masiva ni corrige por sí sola los bloqueos artificiales diagnosticados.

También se reconoce exclusivamente la conversión LF/CRLF del archivo fuente de
red: el ZIP contiene la red LF y el bundle de carga referencia su versión CRLF.
Las dos huellas corresponden a los mismos bytes salvo saltos de línea. No se
modifican mapas, geometría ni hashes de los archivos originales de cada corrida;
los cambios de contenido siguen rechazándose.

## Compatibilidad y límites

Los catálogos y servicios anteriores no se sobrescriben. El contrato nuevo se
activa con el catálogo `agent-types-nonpublic-v1.json`, predeterminado en los
lanzadores actualizados. Para reproducir la composición del 29 de octubre con
las rutas anteriores, seleccionar explícitamente
`freight/weekday-v1/service-composition-v1.json`. Para reproducir expresamente
la modalidad anterior de particulares y carga fija,
indica el catálogo `agent-types-car-moto-v1.json`, el servicio de carga
`freight/weekday-v1/service.json`, el servicio público histórico
`transit/weekday-v2/service.json` y las cantidades de aquella modalidad.

Esta composición usa el calendario diario que ya soporta la carga. La política
continua multidía sigue siendo incompatible con ese servicio; no se omite una
`-TemporalPolicy` explícita ni se desactiva carga para ocultarlo. No se ha
implementado un calendario de carga multidía en esta intervención.

N=0 está contemplado en generación, flota pública, conteos y screening privado.
Las métricas sin observaciones permanecen `null`/sin datos. Su screening privado
se identifica como `not_applicable_no_private_demand`, no como 100 % completado.
La comprobación nativa de los buses permanece independiente.

La aceptación `Run1000` reconoce 1000 vehículos **no públicos** con el catálogo
nuevo (973 particulares + 27 pesados), manteniendo las verificaciones reales de
flota y calidad. Una aprobación anterior no acredita este código. Los controles
no se saltan y ningún estado de ejecución se ha editado durante esta entrega.

**Alcance de verificación:** las pruebas focalizadas de rutas y versión se
ejecutan sin MATSim. El cambio de corredores no constituye una aceptación de
1000 ni una verificación de capacidad masiva. Los ejemplos siguientes son
comandos manuales y no forman parte de esa comprobación focalizada.

## Comandos manuales

Todos los siguientes comandos los ejecuta el usuario. No usan el limpiador.

### Ver el reparto de N sin simular

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
    & .\.venv\Scripts\python.exe -B .\python\simz1_demand_composition.py --agents 200000
    $rc = $LASTEXITCODE
    if ($rc -ne 0) { throw "No se pudo mostrar la composicion: $rc" }
}
```

### Regresiones focalizadas (sin ejecutar MATSim)

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
    $python = (Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe').Path
    $suites = @(
        'test_simz1_demand_composition.py',
        'test_simz1_public_fleet_version.py',
        'test_simz1_transit_accounting.py',
        'test_simz1_transit_events.py',
        'test_simz1_stop_proxy.py',
        'test_simz1_stop_queue_refinement.py',
        'test_simz1_road_profiles.py',
        'test_simz1_experiment_repair.py',
        'test_simz1_freight.py',
        'test_simz1_freight_routes_v2.py',
        'test_simz1_freight_version.py',
        'test_simz1_freight_midnight.py',
        'test_simz1_freight_closure.py',
        'test_simz1_weekday_transit.py',
        'test_simz1_runtime_restart.py'
    )
    foreach ($suite in $suites) {
        if (-not (Test-Path -LiteralPath (Join-Path 'python' $suite) -PathType Leaf)) {
            throw "Falta prueba: $suite"
        }
    }
    foreach ($suite in $suites) {
        & $python -B -m unittest discover -s python -p $suite -v
        $rc = $LASTEXITCODE
        if ($rc -ne 0) { throw "$suite fallo: $rc. No iniciar la masiva." }
    }
}
```

### Preparar runtime y aceptación nueva

Este es el flujo propio de simulación, no el antiguo bloque B del limpiador.
`Run1000` sí ejecuta una corrida técnica y genera sus resultados; ejecútalo tú
cuando corresponda. No reutilices una aceptación anterior después del cambio.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
    $env:JAVA_HOME = 'C:\Program Files\Java\jdk-17'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\simz1_workflow.ps1 -Action Validate
    $rc = $LASTEXITCODE
    if ($rc -ne 0) { throw "Validate fallo: $rc" }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\simz1_workflow.ps1 `
        -Action Run1000 -Seed 20261029 -ServiceDate '2026-10-23' -AcceptTransitRouteAssumptions
    $rc = $LASTEXITCODE
    if ($rc -ne 0) { throw "Run1000 requiere revision: $rc. Conservar los resultados." }
}
```

### Lanzar una corrida nueva de la cantidad elegida

Cambia únicamente `$minimum`, `$maximum` y `$iterations` antes de pegar el
bloque. Para cero: 0/0. Para intermedia: 50000/50000. Para alta: 180000/220000.
Empieza con una iteración exploratoria; aumentarla no demuestra convergencia.
El bloque comprueba el requisito de la prueba previa antes de alta demanda.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
    $env:JAVA_HOME = 'C:\Program Files\Java\jdk-17'
    $minimum = 180000
    $maximum = 220000
    $iterations = 1
    $seed = 20261029
    if ($maximum -ge 150000) {
        & .\.venv\Scripts\python.exe -B .\python\simz1_workflow_state.py require-trial
        $rc = $LASTEXITCODE
        if ($rc -ne 0) { throw 'Falta una aceptacion real vigente de 1000.' }
    }
    $name = 'run-composicion-' + [guid]::NewGuid().ToString('N')
    $run = Join-Path (Get-Location).Path ('scenarios\zona1\montecarlo\' + $name)
    Write-Host "CONSERVAR ESTA RUTA: $run"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass `
        -File .\scripts\run_simz1_with_analysis.ps1 `
        -MinAgents $minimum -MaxAgents $maximum -Iterations $iterations `
        -Seed $seed -ServiceDate '2026-10-23' -AcceptTransitRouteAssumptions `
        -QSimThreads 1 -ShortLinkSignalCoordination derive `
        -MinFreeGiB 30 -NewRunDir $run
    $rc = $LASTEXITCODE
    if ($rc -eq 3) {
        Write-Warning "Resultados conservados; screening requiere revision: $run"
    } elseif ($rc -ne 0) {
        throw "Fallo tecnico o de procesamiento: $rc. Revisar $run; no repetir MATSim si solo fallo analisis/empaquetado."
    } else {
        Write-Host "Flujo terminado: $run"
    }
}
```

La reserva de 30 GiB es solo un mínimo de arranque, no una certificación de
espacio para un tamaño o cantidad de iteraciones. Los comandos reales están
sujetos a las comprobaciones actuales del repositorio y no se han ejecutado aquí.
