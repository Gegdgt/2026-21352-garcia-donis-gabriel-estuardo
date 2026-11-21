# Cierre de accesos y preparación manual 180K — 2026-11-01

**BLOQUEADO. No se ejecutaron preflight masivo, Validate, Run1000 ni MATSim.**

Este cierre continúa `CIERRE_180K_OSM.md`. El catálogo tiene revisión trazable de
elegibilidad del modelo; no certifica permisos de propiedad, aforos ni la ejecución.
`review.verified=true` acredita esa revisión local, mientras `status=BLOCKED`
conserva explícitamente las restricciones globales pendientes.

## Resultado final

- Perímetro OSM 9283360 v34 conservado, SHA256
  `441e7ca4fefff91d7b475d26f12a600415c67b862c5bb2195cd13f486b015688`.
- **10 entradas y 12 salidas** con cadenas existentes, giros de carril comprobados,
  continuidad exterior, almacenamiento y pares OD utilizables. Cada cruce dirigido
  aparece una sola vez. De las 57 alternativas originales se rechazaron 35.
- **22 orígenes interiores** de los 62 candidatos: un origen por componente
  conectado de pasillos/accesos de servicio. Se descartaron 36 alternativas del
  mismo componente y 4 candidatos sin egreso dirigido a la calle.
- Los 4 sin egreso son `osm_1196283990_1_forward`, `osm_1196283990_1_backward`,
  `osm_1196283991_2_forward` y `osm_1196283991_2_backward`.
- Hay 115 pares EE utilizables según el grafo estático y 5 pares inadmisibles
  por conectividad/condiciones del OD. Las 10 entradas admiten EE y EI, y los
  22 orígenes interiores admiten IE y II, para carro de 4.5 m y moto de 2.1 m.
  Esto no levanta el bloqueo OSM global ni acredita asignación completa a 180K.
- 22 alternativas de gateway se excluyeron por clasificación ambigua/sobre el
  límite en el contrato geométrico efectivo, aunque el inventario métrico anterior
  las marcara como candidatas. Las coordenadas, intervalos e IDs exactos quedan en
  `access-review.json`. No se desplazaron nodos ni se inventaron cruces.

Las fuentes originales permanecen intactas. La copia aislada es
`scenarios/zona1/od/balanced-gateway-v1/access-review-v2/`. Allí sólo se retiraron
22 referencias `toLink` de 9 asignaciones de carril, correspondientes a las diez
prohibiciones simples. No se cambiaron longitudes, capacidades, número de
carriles, señales, prioridades, FIFO ni reservas. La red vial local continúa
siendo geometría aproximada OSM, no un levantamiento GIS certificado.

## Contrato corregido

`BalancedGatewayModel._gateways()` ya no llama a `_incorporation()` para las
fronteras. Las entradas usan `entry_capacity_pcu_h`; las salidas usan
`exit_capacity_pcu_h`. `activity_allowed` e `incorporation_capacity_pcu_h` son
`null` en ambas fronteras por **no aplicables**, no por verificación pendiente.
Los orígenes interiores sí requieren elegibilidad sintética explícita y un
presupuesto `incorporation_capacity_pcu_h`.

`useful_length_m` es la longitud de la primera cola nativa disponible, no todo el
enlace ni la suma de una cadena. Se exige cuerpo completo más 0.10 m. Los pasajes
cortos permanecen transitables; no se convierten por ello en orígenes.

Cada presupuesto se deriva del mínimo entre las capacidades existentes de los
enlaces de la cadena y la suma de capacidades de los carriles terminales que
admiten cada movimiento. Los orígenes interiores tienen una cadena de egreso
comprobada. Éstos son **techos nominales de PCU/h para cohortes programadas**,
no mediciones de incorporación ni garantías de descarga efectiva. La admisión
física de QSim se conserva. No se atribuye disponibilidad observada de plazas,
propiedad, anchura o aforo; esas condiciones se declaran como supuestos sintéticos.

`IncorporationBudget.accept()` distingue la frontera del origen interior. El
presupuesto de salida se aplica a la hora de salida programada del viaje, porque
la hora real de cruce exterior sólo existe después de simular. `GatewayBudget`
comparte el presupuesto de todos los enlaces de las cadenas coincidentes, sin
sumar capacidades por alternativas. Se conserva la lectura de catálogos históricos
con su campo antiguo. `load_model()` ahora rechaza también los giros OSM pendientes
antes de entregar un modelo capaz de generar rutas particulares.

## Restricciones OSM

Las relaciones 6008781, 6016436, 17146405, 17146406, 17373677, 17475192,
17502672, 17947071, 20224530 y 20224531 quedan excluidas por los carriles de
la copia aislada. Los miembros, movimientos, carriles terminales y hashes antes
y después están en `osm-turn-resolution.json`.

**17478998: BLOQUEADA.** Prohíbe la secuencia
`osm_1273145789_0_forward → osm_1270930401_0_forward → osm_1273145790_0_forward`.
El enlace vía también recibe tráfico de `osm_734011349_14_forward`.
Eliminar simplemente el segundo movimiento prohibiría otra procedencia no
prohibida por esa relación. Los carriles estáticos no distinguen ese historial.
No se aplanó la restricción ni se alteró Java. La alternativa de salida que
contiene la secuencia fue rechazada, pero el validador global permanece cerrado
porque la red todavía admite la secuencia.

**17884471: BLOQUEADA.** La relación local v2 contiene únicamente
`to=34993910`, `restriction=no_straight_on`; faltan `from` y `via`. Su enlace real
`osm_34993910_0_forward` existe y lo utilizan los tramos de Transmetro L12 y L13.
No es una relación demostrablemente no aplicable. La evidencia disponible no
permite identificar el giro ni los carriles que habría que restringir.

Las cuatro rutas de carga conservadas no usan ninguno de los diez movimientos
retirados ni la secuencia vía-way. Sus geometrías, horarios y dimensiones son
idénticos; la copia de su bundle sólo cambia `lanes_sha256`, y la copia de su
servicio sólo ajusta la ruta relativa a `map.osm`. Los 24 tramos de buses tampoco
usan los movimientos retirados; L12/L13 mantienen la dependencia no resuelta
indicada arriba. El transporte público original no se editó.

## Demanda y presupuesto horario

Se conservan N=180000: 79200 carros, 99000 motos, 1800 camiones compactos y
269 buses adicionales; particulares=178200; seed=20261023, iteración=0.
Las cuotas exactas son EE=89100, EI=35640, IE=35640, II=17820.

| Recurso | Suma de techos nominales PCU/h | Expectativa privada en hora pico |
|---|---:|---:|
| Entradas | 24000 | 6821.71875 |
| Salidas por cohorte de partida | 40000 | 6821.71875 |
| Orígenes interiores | 44000 | 2923.59375 |

La expectativa deriva sólo de los pesos horarios existentes (suma 96; pico 9/96
a las 07:00 y 17:00) y 103950 PCU particulares diarios. No es el histograma
realizado con la semilla. Las sumas tampoco eliminan cuellos compartidos, carga,
buses ni concentración por gateway. **La viabilidad exacta de 180K no está
demostrada**: la programación completa por gateway/hora sigue sin ejecutarse,
por instrucción del usuario y por los dos bloqueos previos. No se publica PASS,
no se modifica N, no se reprograma y no se descartan vehículos.

`gateway-hour-budgets.csv` contiene los límites de cada recurso para las 24 horas.
Las solicitudes programadas, sobrecargas realizadas y concentración de salidas
están explícitamente sin calcular (`NOT_SCHEDULED_OSM_BLOCKED`), nunca como cero.

## Verificación y estado de aceptación

Se aprobaron **27 pruebas focalizadas distintas**: 12 nuevas en
`test_simz1_access_final.py`; 13 pruebas existentes de geometría/contrato/hash
en `GatewayContractTests` y `PerimeterInputTests`; 2 de argumentos/parseo de
PowerShell. Las pruebas nuevas comprueban las 22 retiradas exactas, conservación
de toda la física XML, presupuesto separado de salida, duplicados, límites de
cola, recursos compartidos, servicio de carga intacto, paso de la configuración
aislada por los wrappers y rechazo de las dos restricciones pendientes.
No se repitieron las Correcciones 1–5 completas. `git diff --check` pasó.

El recibo de Validate conserva `integrated_validate_pass` para la huella
`a9b9206b703abb8bde1f74541d8f277ccb741323707d7f8110235663fca59a01`.
Después de estos cambios el gate existente detecta otra revisión. Es un bloqueo
adicional del lanzador; no se alteró el recibo, no se transfirió su aprobación
y no se ejecutó Validate. La comparación exacta final queda en
`final-validation-binding.json`.

## Comandos manuales

La ruta real contiene **`.UVG`**. Estos comandos están preparados, pero **hoy el
preflight debe rechazar** las condiciones pendientes. `-Run` sólo corresponde
después de un preflight aprobado y del gate de revisión vigente; no hay bypass.
El wrapper 180K selecciona explícitamente la copia `access-review-v2` y su
servicio de carga con hash actualizado.

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -DryRun -FirstScaleTrial -JavaHome 'C:\Program Files\Java\jdk-17'
if ($LASTEXITCODE -ne 0) { throw "Preflight bloqueado: $LASTEXITCODE" }
```

Una única ejecución manual, iteración 0:

```powershell
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -Run -FirstScaleTrial -JavaHome 'C:\Program Files\Java\jdk-17'
if ($LASTEXITCODE -eq 3) { Write-Warning 'MATSim completed/valid; screening requiere revision. Conservar resultados.' }
elseif ($LASTEXITCODE -ne 0) { throw "Lanzamiento detenido: $LASTEXITCODE" }
```

Monitoreo de **05:00–09:00 de tiempo simulado**, en otra terminal. Seleccionar el
LaunchId exacto de la corrida real, no el del DryRun. Ctrl+C detiene sólo al lector:

```powershell
& .\scripts\watch_simz1_110k.ps1 -List
$launchId = Read-Host 'LaunchId exacto de la corrida 180K'
$state = Get-Content -LiteralPath ".\runtime\launches\$launchId\state.json" -Raw | ConvertFrom-Json
$runDir = $state.run_directory
& .\.venv\Scripts\python.exe -u -B .\python\simz1_balanced_launch_report.py --run-dir $runDir --watch --interval 15 |
    ForEach-Object {
        $progress = $_ | ConvertFrom-Json
        if ($null -eq $progress.observed -or
            ($progress.observed.simulated_seconds -ge 18000 -and $progress.observed.simulated_seconds -le 32400) -or
            $progress.status -in @('failed','interrupted','completed')) { $_ }
    }
```

Gráficas oficiales de esa misma corrida **completed/valid**, sin repetir MATSim:

```powershell
$manifest = Get-Content -LiteralPath (Join-Path $runDir 'run-manifest.json') -Raw | ConvertFrom-Json
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_with_analysis.ps1 -AnalysisOnly -RunDir $runDir -ExpectedRunId $manifest.run_id
```

## Evidencias entregadas

Carpeta: `scenarios/zona1/od/balanced-gateway-v1/`.

- `access.json`: catálogo actual, con evidencia, presupuestos y estado global.
- `source/access-candidates-v1.json`: catálogo anterior preservado íntegramente.
- `access-review.json`: una decisión por cada uno de los 57 gateways candidatos
  y 62 orígenes, continuación exterior, clasificación, conectividad, pares EE y
  comprobación estática de rutas de servicios.
- `access-decisions.csv`: lista exacta de aprobados/rechazados con razones.
- `osm-turn-resolution.json`: resolución individual de las 12 relaciones,
  incluyendo los IDs reales de carriles; fuentes históricas intactas.
- `gateway-hour-budgets.csv`: 24 horas de presupuestos por recurso; sin cargas
  programadas inventadas.
- `final-validation-binding.json`: recibo anterior y huella actual, lectura sin Validate.
- `final-access-hashes.json`: SHA256 completos de archivos creados/modificados
  en este cierre y de las fuentes preservadas. No incluye su propio hash.

Las listas detalladas siguientes son generadas desde el catálogo y su auditoría.

## Entradas aprobadas

| Gateway físico | Ancla | Longitud útil m | Presupuesto PCU/h |
|---|---|---:|---:|
| `entry-osm_30288333_3_forward` | `osm_381667651_0_forward` | 15.367432 | 2000 |
| `entry-osm_363667895_6_forward` | `osm_762765906_1_forward` | 95.787748 | 2000 |
| `entry-osm_400043601_9_forward` | `osm_400043601_5_forward` | 4.917382 | 4000 |
| `entry-osm_405188986_0_forward` | `osm_381667651_3_forward` | 13.704515 | 2000 |
| `entry-osm_406843605_2_forward` | `osm_406843605_1_forward` | 30.963613 | 2000 |
| `entry-osm_406872394_3_backward` | `osm_406872394_4_backward` | 5.926452 | 2000 |
| `entry-osm_511820719_13_forward` | `osm_511820719_6_forward` | 18.303750 | 4000 |
| `entry-osm_65754263_0_forward` | `osm_44486997_0_backward` | 12.788039 | 2000 |
| `entry-osm_917940877_0_forward` | `osm_260936848_14_forward` | 7.878168 | 2000 |
| `entry-osm_930035054_6_forward` | `osm_381667651_19_forward` | 13.007673 | 2000 |

## Salidas aprobadas

| Gateway físico | Ancla | Longitud útil m | Presupuesto PCU/h |
|---|---|---:|---:|
| `exit-osm_1051440046_6_forward` | `osm_1051440046_7_forward` | 35.834240 | 2000 |
| `exit-osm_1270930401_0_forward` | `osm_260940553_0_forward` | 10.552617 | 2000 |
| `exit-osm_30263020_51_forward` | `osm_381667651_19_forward` | 13.007673 | 2000 |
| `exit-osm_30289506_12_forward` | `osm_30289506_13_forward` | 21.001835 | 4000 |
| `exit-osm_400843677_5_forward` | `osm_400843677_6_forward` | 15.949543 | 6000 |
| `exit-osm_405188986_0_backward` | `osm_381667651_4_forward` | 19.078167 | 2000 |
| `exit-osm_406872394_3_forward` | `osm_406872394_4_forward` | 5.926452 | 2000 |
| `exit-osm_420120096_33_forward` | `osm_381667651_15_forward` | 15.187282 | 6000 |
| `exit-osm_58673255_6_forward` | `osm_58673255_12_forward` | 6.963549 | 4000 |
| `exit-osm_58692312_4_forward` | `osm_381667651_21_forward` | 66.324785 | 4000 |
| `exit-osm_60237264_2_forward` | `osm_60237264_3_forward` | 13.436847 | 2000 |
| `exit-osm_762765906_0_forward` | `osm_762765906_1_forward` | 95.787748 | 4000 |

## Gateways rechazados (alternativas exactas)

| Rol | Cruce | Ancla rechazada | Motivo |
|---|---|---|---|
| entry | `osm_292876837_2_forward` | `osm_292876837_1_forward` | Cadena local sin par OD conectado |
| entry | `osm_292876837_2_forward` | `osm_45494968_0_forward` | Alternativa del cruce sin par OD conectado |
| entry | `osm_30279782_2_forward` | `osm_30279782_1_forward` | Límite ambiguo/sin clasificación efectiva; intervalos exactos en JSON |
| entry | `osm_30288333_3_forward` | `osm_30288333_1_forward` | Alternativa duplicada; ancla elegida: osm_381667651_0_forward |
| entry | `osm_363667895_6_forward` | `osm_363667895_5_forward` | Alternativa duplicada; ancla elegida: osm_762765906_1_forward |
| entry | `osm_381097595_5_forward` | `osm_381097595_4_forward` | Límite ambiguo/sin clasificación efectiva; intervalos exactos en JSON |
| entry | `osm_405188986_0_forward` | `osm_1274240312_0_forward` | Alternativa duplicada; ancla elegida: osm_381667651_3_forward |
| entry | `osm_406843605_2_forward` | `osm_381667651_16_forward` | Alternativa duplicada; ancla elegida: osm_406843605_1_forward |
| entry | `osm_59566215_6_forward` | `osm_59566215_4_forward` | Límite ambiguo/sin clasificación efectiva; intervalos exactos en JSON |
| entry | `osm_65777805_7_forward` | `osm_65777805_5_forward` | Límite ambiguo/sin clasificación efectiva; intervalos exactos en JSON |
| entry | `osm_65786237_0_forward` | `osm_65792798_1_forward` | Límite ambiguo/sin clasificación efectiva; intervalos exactos en JSON |
| entry | `osm_65786237_0_forward` | `osm_699533700_5_forward` | Límite ambiguo/sin clasificación efectiva; intervalos exactos en JSON |
| entry | `osm_65786237_0_forward` | `osm_699533700_6_backward` | Límite ambiguo/sin clasificación efectiva; intervalos exactos en JSON |
| entry | `osm_699533700_4_backward` | `osm_30279775_3_forward` | Límite ambiguo/sin clasificación efectiva; intervalos exactos en JSON |
| entry | `osm_699533700_4_backward` | `osm_699533700_5_backward` | Límite ambiguo/sin clasificación efectiva; intervalos exactos en JSON |
| entry | `osm_917940877_0_forward` | `osm_1273145790_1_forward` | Alternativa duplicada; ancla elegida: osm_260936848_14_forward |
| entry | `osm_930035054_6_forward` | `osm_930035054_4_forward` | Alternativa duplicada; ancla elegida: osm_381667651_19_forward |
| exit | `osm_1270930401_0_forward` | `osm_1273145790_0_forward` | Secuencia prohibida por 17478998 |
| exit | `osm_1275050774_0_forward` | `osm_1243273719_0_forward` | Límite ambiguo/sin clasificación efectiva; intervalos exactos en JSON |
| exit | `osm_1275050774_0_forward` | `osm_45494968_0_forward` | Límite ambiguo/sin clasificación efectiva; intervalos exactos en JSON |
| exit | `osm_30263020_51_forward` | `osm_30263020_52_forward` | Alternativa duplicada; ancla elegida: osm_381667651_19_forward |
| exit | `osm_30279769_73_forward` | `osm_30279769_75_forward` | Límite ambiguo/sin clasificación efectiva; intervalos exactos en JSON |
| exit | `osm_359045350_9_forward` | `osm_359045350_10_forward` | Límite ambiguo/sin clasificación efectiva; intervalos exactos en JSON |
| exit | `osm_381158277_4_forward` | `osm_381158277_5_forward` | Límite ambiguo/sin clasificación efectiva; intervalos exactos en JSON |
| exit | `osm_382465689_1_forward` | `osm_382465689_5_forward` | Cadena local sin par OD conectado |
| exit | `osm_382465690_6_forward` | `osm_382465690_8_forward` | Límite ambiguo/sin clasificación efectiva; intervalos exactos en JSON |
| exit | `osm_405188986_0_backward` | `osm_1274240312_0_backward` | Alternativa duplicada; ancla elegida: osm_381667651_4_forward |
| exit | `osm_58692312_4_forward` | `osm_58692312_5_forward` | Alternativa duplicada; ancla elegida: osm_381667651_21_forward |
| exit | `osm_58692343_53_forward` | `osm_58692343_54_forward` | Límite ambiguo/sin clasificación efectiva; intervalos exactos en JSON |
| exit | `osm_699533700_4_forward` | `osm_30279775_3_backward` | Límite ambiguo/sin clasificación efectiva; intervalos exactos en JSON |
| exit | `osm_699533700_4_forward` | `osm_699533700_5_forward` | Límite ambiguo/sin clasificación efectiva; intervalos exactos en JSON |
| exit | `osm_699533700_8_backward` | `osm_699533700_7_backward` | Límite ambiguo/sin clasificación efectiva; intervalos exactos en JSON |
| exit | `osm_734011348_14_forward` | `osm_44486997_1_backward` | Límite ambiguo/sin clasificación efectiva; intervalos exactos en JSON |
| exit | `osm_734011348_14_forward` | `osm_44487200_0_forward` | Límite ambiguo/sin clasificación efectiva; intervalos exactos en JSON |
| exit | `osm_734011348_14_forward` | `osm_734011348_16_forward` | Límite ambiguo/sin clasificación efectiva; intervalos exactos en JSON |

## Orígenes interiores aprobados

Los otros 40 quedan identificados individualmente en `access-decisions.csv`.

| Enlace | Longitud útil m | Presupuesto PCU/h |
|---|---:|---:|
| `osm_1095527693_1_backward` | 11.139094 | 2000 |
| `osm_1095527695_0_backward` | 7.515500 | 2000 |
| `osm_1095551808_2_backward` | 7.040739 | 2000 |
| `osm_1095551811_2_backward` | 6.724268 | 2000 |
| `osm_1095760001_3_backward` | 6.844594 | 2000 |
| `osm_1095760094_0_backward` | 7.482713 | 2000 |
| `osm_1095760124_0_backward` | 12.019105 | 2000 |
| `osm_1107835856_7_forward` | 5.278879 | 2000 |
| `osm_1159529860_0_backward` | 5.260211 | 2000 |
| `osm_1174627092_0_backward` | 4.840580 | 2000 |
| `osm_1196002697_9_backward` | 6.581527 | 2000 |
| `osm_1197017583_1_forward` | 5.651273 | 2000 |
| `osm_1214455884_0_backward` | 7.685819 | 2000 |
| `osm_1218656796_0_forward` | 7.211070 | 2000 |
| `osm_1272882110_0_forward` | 8.388995 | 2000 |
| `osm_1274275468_9_backward` | 6.034808 | 2000 |
| `osm_1392432467_0_backward` | 7.892914 | 2000 |
| `osm_1392432602_0_backward` | 5.932415 | 2000 |
| `osm_390176418_0_forward` | 10.890790 | 2000 |
| `osm_406701907_9_backward` | 8.317607 | 2000 |
| `osm_488464043_0_backward` | 7.665619 | 2000 |
| `osm_989735832_1_forward` | 10.396150 | 2000 |

## Resolución individual de las doce relaciones

Todos los carriles terminales exactos se conservan en `osm-turn-resolution.json`.

| Relación | Restricción | Movimiento/secuencia | Estado |
|---|---|---|---|
| 6008781 | no_left_turn | `osm_1308544716_0_forward → osm_400252217_0_forward` | RESOLVED_IN_ISOLATED_COPY |
| 6016436 | no_left_turn | `osm_400252217_0_forward → osm_400843678_0_forward` | RESOLVED_IN_ISOLATED_COPY |
| 17146405 | no_left_turn | `osm_403151302_0_forward → osm_559513165_0_forward` | RESOLVED_IN_ISOLATED_COPY |
| 17146406 | no_left_turn | `osm_403151302_0_forward → osm_64387808_0_forward` | RESOLVED_IN_ISOLATED_COPY |
| 17373677 | no_right_turn | `osm_1274975828_1_forward → osm_1265232222_0_forward` | RESOLVED_IN_ISOLATED_COPY |
| 17475192 | no_left_turn | `osm_1272828335_0_forward → osm_1272828334_0_forward` | RESOLVED_IN_ISOLATED_COPY |
| 17478998 | no_u_turn | `osm_1273145789_0_forward → osm_1270930401_0_forward → osm_1273145790_0_forward` | BLOCKED |
| 17502672 | no_left_turn | `osm_60237269_2_forward → osm_1274975830_0_forward` | RESOLVED_IN_ISOLATED_COPY |
| 17884471 | no_straight_on | `from/via ausentes; to=osm_34993910_0_forward` | BLOCKED |
| 17947071 | no_right_turn | `osm_1274975827_3_forward → osm_559513163_0_forward` | RESOLVED_IN_ISOLATED_COPY |
| 20224530 | no_right_turn | `osm_258164128_5_forward → osm_1479114530_0_forward` | RESOLVED_IN_ISOLATED_COPY |
| 20224531 | no_left_turn | `osm_39931882_2_forward → osm_1265264312_0_forward` | RESOLVED_IN_ISOLATED_COPY |
