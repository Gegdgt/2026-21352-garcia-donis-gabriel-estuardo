# Transporte pesado de paso en SimZ1

Los lanzadores usan ahora
`scenarios/zona1/freight/weekday-v2/service-composition-v2.json`. Sus camiones
`FreightTruck` representan **transporte de paso**: entrada por el perímetro,
recorrido por corredores principales y salida por otro acceso, sin entregas,
estacionamientos ni destinos internos. La cantidad se deriva de N mediante el
catálogo `agent-types-nonpublic-v1.json`; no es una flota adicional fija de 12.
Véase [composición vehicular](simz1-composicion-vehicular.md) para el reparto.

Los conductores se serializan junto a los planes y se identifican por
`simz1FreightService`. `planned_persons`, `planned_trips`, los seis perfiles y
el CSV compacto conservan su denominador de carros y motos. Los 269 buses
mantienen su servicio independiente. Este cambio de rutas no modifica esos
vehículos ni el reparto de N.

`weekday-v1/routes.json`, `weekday-v1/service.json` y
`weekday-v1/service-composition-v1.json` se conservan para reproducir las
corridas históricas. La versión nueva declara `service_version=weekday-v2`
y `route_policy=principal-through-v2`; mantiene el esquema
`simz1-freight-weekday-v1` compatible con el actor nativo. Los manifiestos y
las copias de insumos de cada corrida determinan qué versión se audita. Las
huellas de aceptación incluyen ambas carpetas versionadas; una aceptación
anterior no acredita las rutas nuevas.

## Supuestos y alcance

- PBV estrictamente superior a 3.5 toneladas. El valor configurado es 12 t,
  PCU 3.5, máximo 40 km/h y cuerpo físico/visual 12 × 2.5 m: supuestos editables,
  sin calibración empírica. El mismo cuerpo de 12 × 2.5 m se comparte entre
  la ocupación nativa y el replay. Los pesados se dibujan morados.
- Una expedición por vehículo/día. La cuota de carga es 1/37 de N, con el
  redondeo definido en el contrato de composición: N=1000 produce 27 camiones.
  `-FreightVehicles` no puede contradecir esa cuota. El servicio histórico
  `weekday-v1/service.json` conserva su modalidad de flota fija. Ninguna de
  estas cantidades constituye un aforo.
- Salidas en la jornada civil de lunes a viernes, 00:00–24:00. Permitido
  `[00:00,05:00)`, `[09:00,16:00)`, `[21:00,05:00 del día siguiente)`.
  `weekday_overnight_until_05_v2` permite residencia hasta 104400 s; no agrega
  salidas al día siguiente. El horizonte de la simulación no se amplía por esta
  regla y toda expedición debe terminar para validar. Los snapshots anteriores
  conservan su recorte a 86400 s como `legacy_horizon_clip_v1`. Son las reglas
  solicitadas para el escenario, no una certificación legal. Fechas de fin de
  semana se rechazan.
- `stratified-feasible-windows-v1` reparte cuotas equilibradas entre rutas y
  estratifica sus salidas en las ventanas viables usando el tiempo de flujo
  libre de cada ruta. Se conservan el margen planificado de 1800 s y el recorte
  al horizonte diario de 86400 s. La modalidad histórica de flota fija conserva las salidas
  base 01:00, 09:30 y 21:30 y la separación de 120 s. Una programación que no
  cabe en sus franjas falla en preflight; no se recorta la cantidad de camiones.
- Cuatro corredores sintéticos cuyos enlaces de entrada y salida cruzan el
  rectángulo `<bounds>` de `map.osm`, obtenidos de la red importada y sus giros
  de carril. Ese perímetro de extracción no es un límite administrativo GIS
  verificado ni una autorización municipal de carga. La versión histórica v1
  conserva sus accesos en el 10% exterior del componente vial principal.
  Las rutas de `weekday-v1` ya eran de tránsito de paso. La versión nueva
  conserva los tramos aptos y sustituye recorridos inadecuados; el criterio es
  usar vías principales con accesos distintos, conectividad dirigida y giros
  de carril permitidos, con preferencia por extremos opuestos cuando sea viable.
  La única excepción es un enlace residencial terminal de 186.132 m en 5a
  Calle, necesario para conservar la salida occidental por Avenida Elena.
  El [mapa lógico y la tabla de rutas](simz1-freight-through-v2.md) detallan
  enlaces, accesos, distancias, tiempos libres y límites de la validación.
  Los planes representan entrada, recorrido y salida; no dibujan ni calculan
  los viajes fuera del dominio. No se modifica la red ni los laboratorios.
- `routes.json` contiene enlaces concretos y las huellas de red, carriles, OSM
  y rutas históricas. Para
  regenerar deliberadamente los corredores al cambiar esa red:
  `.\.venv\Scripts\python.exe -B python/prepare_simz1_freight_routes.py`.
- El servicio tiene una expedición por unidad y un día civil. La
  política temporal de múltiples días/contextos requiere un calendario de
  carga adicional; se rechaza explícitamente con carga activa. Para conservar
  ese flujo anterior, usar `-NoFreightTransport`.

## Integridad operativa

La ruta se fija antes de cada QSim y la carga no participa en el reruteo dentro
del viaje. Comparte calles, carriles, semáforos, prioridades y colas reales con
los demás vehículos. La auditoría nativa registra las infracciones horarias
y rechaza la aprobación final; no constituye una barrera física que retire
camiones al cerrar una ventana. La validación posterior exige que
**todo el intervalo entre salida y llegada,
incluidas las colas** quepa en una sola franja permitida. También comprueba
el orden completo de enlaces. No elimina vehículos del replay para aparentar
cumplimiento. Una congestión que impide cumplir horarios o terminar todas las
expediciones deja la corrida inválida, con los archivos y el error conservados.
El margen de despacho no garantiza capacidad suficiente para una corrida masiva.
Cambiar rutas tampoco demuestra que se hayan resuelto los bloqueos de reservas,
señales o prioridades diagnosticados en la corrida fallida del 30 de octubre.

`run-manifest.json` distingue `freight_transport.vehicles_configured`,
`departures_scheduled` y, por iteración, `freight_transport_events` con vehículos,
salidas, llegadas, IDs y duraciones observados. Se validan las huellas de
servicio/rutas/roster, atributos de personas y tipos/vehículos efectivos.
La versión v2 verifica además el grafo de carriles desde su entrada, los
sentidos y restricciones OSM y los accesos al perímetro. Se valida tanto la
red base como la red efectiva derivada al incorporar buses, antes de agregar
los camiones. Cada corrida conserva `map.osm` y `route-validation.json` junto
al servicio, las rutas y el roster.
Los manifiestos antiguos sin carga conservan su interpretación.

El análisis incluye los contadores de carga en su procedencia; las medias de
carros/motos mantienen su denominador. El paquete copia servicio, rutas y roster
a `entregables/<nombre-corrida>/docs/freight-*.json` en la prueba de una iteración,
además del manifiesto de corrida.
`freight_service.json` incluye cada expedición observada y su duración, además
de la media global del servicio; no mezcla esa media con los perfiles privados.
El replay reconstruye la carga desde los eventos nativos. El HUD publica
configurados/observados/salidas y el detalle contextual muestra el tipo y las
dimensiones físicas y visuales por separado.

## Prueba reproducible

En PowerShell, desde la raíz del repositorio:

```powershell
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/run_simz1_with_analysis.ps1 `
  -MinAgents 1000 -MaxAgents 1000 -Seed 20261026 -Iterations 1 `
  -ServiceDate '2026-10-23' -AcceptTransitRouteAssumptions `
  -NewRunDir 'scenarios\zona1\montecarlo\run-freight-demo'
.\.venv\Scripts\python.exe -B scripts/replay/prepare_replay.py `
  --run-dir scenarios/zona1/montecarlo/run-freight-demo --iteration 0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/simz1_workflow.ps1 `
  -Action View -RunDir scenarios/zona1/montecarlo/run-freight-demo -Port 8794
```

El directorio debe ser nuevo. Para desactivar carga explícitamente:
`-NoFreightTransport`. Para escoger otro servicio/fecha: `-FreightService` y
`-FreightServiceDate`. Las mismas opciones pasan por `simz1_workflow.ps1`.
La CLI Python permite seleccionar explícitamente la versión con
`--freight-service scenarios/zona1/freight/weekday-v2/service-composition-v2.json`
y `--freight-service-date 2026-10-23`; desactivar con `--no-freight-transport`.
Para reproducir una modalidad histórica, seleccionar su servicio y catálogo
compatibles de forma explícita. Las opciones incompatibles se rechazan.

Antes de relanzar una corrida masiva con la garantia fisica solicitada, resolver
la ocupacion multienlace descrita en [simz1-occupancy.md](simz1-occupancy.md).
La evidencia actual no cumple ese criterio global. Despues: ejecutar
`simz1_workflow.ps1 -Action Validate`, luego
`-Action Run1000 -AcceptTransitRouteAssumptions`, revisar el cumplimiento de
carga y los diagnósticos de capacidad, y finalmente `-Action RunMassive` con
los mismos parámetros de servicio. La corrida pequeña acredita integración,
no estabilidad ni calibración a 150000–250000 privados.

Prueba histórica con el servicio de aquella fecha:
[evidencia 20261026](simz1-verification-20261026.json). No acredita las rutas de
`weekday-v2`.
