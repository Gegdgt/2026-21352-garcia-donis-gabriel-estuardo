# SimZ1: diseño de incidentes sintéticos y detección de oportunidades

Prompt 7, 22/10/2026. Alcance: diseño, auditoría y prototipo puro de referencia.
**No hay integración activa con MATSim, bloqueos de carril ni cambios de física.**
`AGENTS.md` se leyó; `git status --short` estaba limpio al comenzar. No se
ejecutaron simulaciones, servidores, navegadores ni regeneraciones masivas.

## Tres conceptos que no se intercambian

| Concepto | Evidencia exigida | Qué permite afirmar esta revisión |
|---|---|---|
| Conflicto vial potencial | Dos demandas nativas identificadas, rutas/carriles conocidos y par de movimientos con conflicto positivo verificado en la misma cota | Existe exposición a un cruce o incorporación; el control puede haberla resuelto correctamente |
| Colisión detectada | Contacto y cronología física entre cuerpos con posiciones y dinámica suficientes | **No observable con QSim de colas y los eventos actuales**; no hay detector de contacto implementado |
| Accidente estocástico sintético | Oportunidad elegible, sorteo reproducible y política de exclusión explícita | Anotación hipotética del modelo, no accidente observado ni estadística local calibrada |

Las dimensiones configuradas, las entradas/salidas de enlaces y un mismo segundo
de simulación no demuestran que dos carrocerías ocuparan simultáneamente el
cruce. WebGL, sus interpolaciones, rectángulos orientados, hitboxes, PCU y
solapamientos no son entradas de este detector. TTC, severidad, distracción,
uso de celular e impacto permanecen no observados.

La [auditoría nativa](SIMZ1_INCIDENT_NATIVE_AUDIT.md) detalla fuentes, líneas,
eventos y limitaciones. `PriorityMovements.conflicts()` incluye pares ambiguos:
no se reutiliza ese booleano como certificación positiva. Su tabla
`verified-node-table` certifica **no conflictos**, no puntos de accidente.

## Lo que existe y lo que se entrega

Ya existe `StochasticCrashEvent`, un generador exógeno por enlace ocupado, con
otra probabilidad/semilla y cambios de capacidad/velocidad. No identifica una
pareja ni detecta contacto. `RunZona1Simulation` lo instala cuando está
configurado; `SimZ1.main` actual no lo instala. El histórico de 227187 personas
usó la primera entrada y conserva un incidente genérico en
`osm_1313303878_6_backward`, 1500–4076 s. Su icono en el punto medio del enlace
no es evidencia de impacto. **Ese modelo, sus eventos y el histórico no cambian.**

Se añaden:

- [`simz1_incident_design.py`](../python/simz1_incident_design.py): validador,
  detección de encuentros en fixtures, deduplicación, sorteos y registro sin
  efectos físicos. Solo acepta `scope=fixture_only`; rechaza entrada de producción.
- [`test_simz1_incident_design.py`](../python/test_simz1_incident_design.py):
  pruebas pequeñas puras. No reutiliza `StochasticCrashCheck`, que ejecuta QSim.
- [`fixture.json`](../scenarios/zona1/versions/incident-design-2026-10-22/fixture.json):
  red, participantes y recibos **inventados exclusivamente para pruebas**,
  identificados como fixtures; no son datos de Zona 1 ni una flota real.
- [`network-candidates.json`](../scenarios/zona1/versions/incident-design-2026-10-22/network-candidates.json):
  auditoría de candidatos reales, todos pendientes y deshabilitados.

El prototipo no se importa desde generadores, servidor, replay, validadores de
corridas ni Java. El observador nativo de parejas y el catálogo real revisado
siguen **por implementar**. No se reconstruyen parejas desconocidas a partir
de `simz1NativeDecision`, de un WAIT agregado ni del SQLite histórico.

## Elegibilidad positiva y límites de red

Un futuro catálogo debe fijar hashes de red efectiva, carriles, restricciones,
OSM y VehicleTypes, más su propia versión/hash. Cada movimiento identifica
nodo, enlace entrante/saliente, carril entrante/receptor, cota, modos permitidos
y evidencia de giro permitido. Una oportunidad exige:

1. Dos vehículos reales diferentes, tipo y dimensiones configuradas con
   procedencia, viaje/visita identificados y siguiente enlace conocido.
2. Dos movimientos de accesos distintos en un lugar revisado. Para incorporación:
   mismo carril receptor demostrado. Para cruce: geometría de movimientos con
   intersección positiva y misma cota revisada; cercanía o ambigüedad no bastan.
3. Evidencia de ambos participantes capturada por el propietario del nodo, sin
   leer concurrentemente cabeceras de colas receptoras ajenas.
4. En esta política inicial, una admisión confirmada y otra demanda en WAIT por
   conflicto de movimiento, prioridad o señal. Es **exposición gestionada**, no
   prueba de que ambos cruzaron ni de que alguien violó la señal.
5. Paso completo, orden temporal válido y artefactos coincidentes. No sirven
   `turn_go` sin inserción, solo almacenamiento insuficiente, dos WAIT sin
   movimiento, dos admisiones incompatibles o recorridos desconocidos.

Dos admisiones incompatibles requieren auditoría de transiciones, no una etiqueta
de accidente que disimule el defecto. FORCE/ABORT de la transición candidata se
rechazan; FORCE tiene su registro separado. No se excluye para siempre un
vehículo por un FORCE anterior en otro recorrido. Evidencias contradictorias
del mismo encuentro e instante invalidan la pareja de visitas completa antes
del sorteo; repetir el WAIT después no borra la contradicción. Un FORCE de esa
pareja de visitas también la excluye. Una visita nueva se evalúa por separado.

El prototipo verifica cruce estricto de segmentos de la red del fixture o
igualdad del carril receptor. Esa comprobación no certifica barrido de
carrocerías ni sustituye la futura revisión de geometría real. Tags de nivel
ausentes en OSM permanecen desconocidos. No se conectan niveles, extremos de
extracto ni vías privadas para producir oportunidades.

| Candidato aportado | Evidencia local | Estado |
|---|---|---|
| 6.ª Avenida / 21 Calle | Complejo de nodos `11583002439`, `631824824`, `410442286`, `748556818`, `3933136479`; no un único punto | Pendiente: cinco restricciones OSM locales sin resolver y geometría/cotas por revisar |
| 6.ª Avenida / 24 Calle | Nodo `479440975`, al sur del límite del extracto; un entrante y un saliente modelados | Contexto incompleto, no habilitado como cruce conflictivo |
| 11 Avenida / Calle Martí | Calle Martí no figura por nombre de vía en el extracto inspeccionado | Pendiente de fuente/contexto ampliado; no se asigna coordenada ni ID de cruce |

Las relaciones locales pendientes son `6008781`, `6016436`, `17373677`,
`17947071` y `20224531`; la auditoría encuentra 15 destinos terminales todavía
permitidos por carriles. No se aplica la propuesta de restricciones ni se
modifica ninguna red en este prompt. **Oportunidades reales habilitadas: cero.**

## Una evaluación por encuentro, no por frame o segundo

La unidad de exposición es el encuentro de una pareja de visitas en un lugar
canónico. Identidad v1: hash de modelo, `place_id` y las dos tuplas completas
`(vehicle_id, trip_id, visit_index)`, ordenadas. Movimientos, carriles, causa y
recibos quedan asociados a cada participante; nunca se ordenan IDs y movimientos
por separado. `visit_index` es una ocurrencia nativa estable por vehículo/viaje,
no un contador global dependiente de hilos.

Un reintento de WAIT, cambio de carril/ruta durante esa visita, pareja invertida,
otra zona del mismo lugar, frame, seek o consulta no vuelve a sortear el encuentro.
Una visita nueva permite otro encuentro. Se conserva la primera observación
elegible cronológica. Los duplicados incrementan un contador, no la exposición.

El catálogo debe agrupar carriles y movimientos de un mismo lugar físico con
un `place_id` revisado: usar IDs arbitrarios diferentes permitiría duplicados.
El registro de encuentros vistos se conserva durante toda la iteración. No se
borra al vencer una anotación activa. La integración futura necesita un ledger
persistente o retención por episodios cerrados si su volumen exige limitar RAM.

## Probabilidad, semilla y frecuencia

| Parámetro | Política inicial |
|---|---|
| `enabled` | `false` por defecto; sin observador, lectura de catálogo ni consumo de RNG |
| `probability_per_opportunity` | `0.00001`, sintética y configurable en `[0,1]`; valores altos sirven para fixtures, no constituyen calibración |
| `incident_seed` | Entero explícito independiente de 64 bits; obligatorio cuando se habilita; se serializa como cadena decimal en manifiesto |
| `daily_cap` | 5 por defecto, configurable de 0 a 5; **sin cuota mínima** |
| `active_duration_us` | 900 s por defecto, configurable; solo vigencia de exclusión de anotaciones, no duración física ni bloqueo |
| Día simulado | `floor(time_us / 86400000000)`; no reloj de pared ni zona horaria |

Por encuentro único se calcula SHA-256 de JSON canónico UTF-8:
`[model,"incident-draw",seedDecimal,replicationKey,iteration,registryHash,opportunityKey]`.
Se toman los primeros 64 bits sin signo, big-endian. Éxito si
`bits < floor(p * 2^64)`. El umbral se calcula decimal; `p=0` y `p=1` son exactos.
No se usa `MatsimRandom`, `Random`, `hash()` de Python ni un contador compartido.
El manifiesto conserva algoritmo, semilla, versión, probabilidad y hashes.

Vector de portabilidad incluido en las pruebas: semilla `0`, réplica
`golden-fixture`, iteración `3`, hash de catálogo de 64 letras `a` y oportunidad
de 64 letras `b` producen `draw_hex=e709e337c6ead59f`. La implementación Java
futura deberá reproducir los bytes JSON y este vector antes de integrarse.

`replication_key` identifica entradas/experimento estable, no UUID aleatorio de
corrida. La iteración cambia el dominio del sorteo. IDs de incidente son estables
para iguales entradas, semilla e iteración; el almacenamiento los particiona
también por `run_id` sin incluir ese UUID en el draw. Otra semilla cambia los
sorteos, pero no garantiza accidentes distintos cuando p es tan baja que ambos
resultados son cero. Cambiar número de hilos conserva draws **si las observaciones
nativas coinciden**; no promete que MATSim produzca trayectorias iguales con
configuraciones de concurrencia diferentes.

Se sortea una sola vez incluso si luego se suprime por cupo o anotación activa.
No hay repetición al vencer el cooldown. Las exclusiones impiden coexistencia
de anotaciones en el mismo lugar o sobre cualquiera de sus vehículos. Los
intervalos son `[inicio,fin)`; expiran antes de evaluar otro encuentro en el
mismo instante, y la exclusión de vehículos/lugares continúa al cruzar medianoche.
El cupo diario se reinicia; la vigencia activa no.

Se registran oportunidades únicas, duplicados, rechazadas y motivos, trials,
éxitos antes de exclusiones, supresiones activas, supresiones por cupo, incidentes
por día y tasa resultante. Antes de exclusiones, `E[éxitos]=N*p`: 10000 oportunidades
dan 0,1; 100000 dan 1; 500000 dan 5. Esto **no garantiza** ese número de incidentes.
Cupo y exclusiones reducen el resultado e introducen preferencia cronológica;
su conteo no debe ocultarse para aparentar una calibración. No se fuerza 2–5
accidentes, ni un porcentaje fijo de motos.
`incidents_by_day` es un mapa disperso: un día cubierto sin entrada significa
cero, y debe incluirse en el denominador de frecuencia. El horizonte se registra;
un fixture parcial de una hora no representa un día completo de tráfico.

## Contrato propuesto de observación, evento y manifiesto

El fixture ejecutable especifica los tipos exactos usados por el prototipo.
Los nombres con sufijo `Design` son exclusivos de pruebas y no se envían al
parser legado `zona1IncidentStart/Recovered` ni al icono `crash` del mapa.

| Producto futuro | Campos obligatorios y significado |
|---|---|
| Observación nativa de pareja | `schema`, tiempo simulado en microsegundos enteros, paso/cierre, origen `node_owned_paired_snapshot`, nodo/zona, hashes; dos participantes con vehículo, viaje, visita, tipo/familia, enlace/carril, movimiento, entrada a cola, decisión/motivo, recibo de admisión cuando corresponda y referencia de evidencia |
| Dimensiones por participante | `length_m`, `width_m`, `nature=configured`, fuente y SHA de VehicleTypes; no dimensiones del renderer ni inferidas de PCU |
| Persona | `person_id` nullable si no consta; nunca inventar conductor/pasajero para completar identidad |
| Incidente sintético | ID estable, oportunidad, tiempo/día, nodo/zona/lugar, ambos participantes con sus enlaces/carriles, riesgo, causa modelada, referencias/hashes, semilla, probabilidad, draw, clasificación sintética, contacto no observado y `physics_effect=none` |
| Vigencia | Fin programado de anotación; estado `expired` o `censored` al horizonte. No se afirma recuperación física ni se emite anticipadamente un evento futuro |
| Manifiesto | Modelo/versión, habilitación solicitada **e instalación efectiva**, semilla independiente/origen, algoritmo, p, cupo, vigencia, horizonte, iteración/replicación, artefactos y hash del ledger/reporte |

La causa inicial es `synthetic_residual_risk_at_verified_conflict`. El riesgo es
`crossing_demand` o `merge_demand`. No atribuye celular, exceso de velocidad,
infracción de rojo/alto o culpabilidad a un vehículo que no registró esa conducta.
Simular esas causas requeriría después un modelo de comportamiento explícito;
no se modifica la aceptación de giros para producirlas ahora.

Bus y moto requieren su `VehicleType` y dimensiones configuradas; si falta
evidencia, la oportunidad se rechaza. No se usa el respaldo de carro de WebGL.
Tampoco se convierte un pasajero de transporte público en bus. Las dimensiones
se conservan como contexto, sin usarlas para declarar un contacto que QSim no
observa. Un bus real de 4,5 m configurado por error necesita preflight de catálogo;
no se corrige silenciosamente con una medida supuesta.

## Integración futura Java/Python y cuatro hilos

**Ninguna de estas conexiones se instala en este prompt.**

| Punto | Cambio propuesto después de revisar este diseño |
|---|---|
| Nueva configuración `simz1SyntheticIncidents` | Default apagado; parámetros tipados, semilla independiente; rechazo de catálogo no revisado o hashes distintos |
| `SimZ1.loadConfiguration/main` | Cargar esa configuración y registrar observador solo al habilitarlo. Verificar instalación efectiva; el antiguo `incidentsEnabled` no certifica este módulo |
| `Zona1QNodeImpl` | Copiar IDs/visita/movimiento y contexto ya calculado, desde el actor propietario, en decisiones y tras inserción confirmada; preservar ambos participantes del conflicto. No llamar otra vez a `chooseNextLinkId`, cambiar orden de colas ni consumir RNG nativo |
| `Zona1NativeDiagnostics` / `UnsignalizedPriority` | Referencias nativas de evidencia y ocurrencia universal de visita; la visita local de prioridad actual no cubre todos los nodos |
| Nuevo colector después del paso | Cerrar todos los productores; ordenar `(tiempo,nodo,opportunity_id)`; deduplicar, sortear, aplicar exclusión/cupo y emitir ledger separado |
| `prepare_simz1.py` / `simz1_config_validation.py` | Preflight futuro de catálogo, rutas, restricciones, modos, dimensiones y conflictos positivos. No activar por nombre de calle ni por cuota de siniestros |
| `simz1_run.create_manifest/validate_outputs` | Fijar bloque nuevo de manifiesto y comparar config solicitada/efectiva, identidad, hashes, cronología, unicidad, máximo diario y métricas por tipo/lugar |
| Exportación Python futura | Producto separado de incidentes sintéticos, decisiones FORCE y perturbaciones legadas. Ningún cambio en eventos históricos o trayectoria física |

MATSim asigna cada nodo y sus salidas al mismo runner, y usa una barrera entre
fases de nodos y enlaces. El observador debe recibir copias inmutables, no
referencias `QVehicle`/colas vivas. El estado local de captura pertenece al
nodo; los mapas de exclusión y cupo se actualizan solo en el colector serial
después del cierre global. No hay locks globales en la decisión de admisión,
reservas físicas, lecturas de receptores ajenos ni RNG compartido.

El primer callback no cierra un paso: se exige watermark de todos los workers.
Una llegada tardía a un paso finalizado debe marcar fallo de integridad, sin
insertarla retroactivamente. El prototipo procesa un lote finito completo y
exige `complete_until_us == end_us`; no implementa ingestión concurrente en vivo.
Cada llamada representa una réplica completa: no conserva cupos, encuentros ni
vigencias entre llamadas. No se deben concatenar resultados de lotes parciales
como si fueran una sola réplica; la futura versión en vivo necesitará estado y
checkpoint de esos registros, además del watermark. El rechazo de contradicciones
examina el lote completo. Una versión en vivo deberá impedir evidencia tardía
contradictoria tras su barrera y declarar fallo de integridad si ocurre.
Permutar cuatro lotes de entrada prueba determinismo de reducción, no carreras
de JVM. Antes de integración real faltan pruebas de barrera/entrega Java.

Apagado, el prototipo devuelve cero y ni consume el iterable de observaciones.
Como no se conecta con MATSim, no altera resultados normales. La futura
implementación deberá comprobar además equivalencia off/off de eventos y
resultados con las mismas entradas, sin instalar listeners ni tocar la semilla
nativa. No se afirma haber ejecutado esa corrida.

## Cifras aportadas: contexto, no calibración

Consulta web del 22/10/2026. No se encontró una serie oficial reciente con
denominador territorial/temporal que confirme **2–5 accidentes diarios en
Zona 1**, la concentración diaria en los tres cruces o las proporciones
causales locales. Se conservan como hipótesis aportadas, pendientes de fuente.

La comunicación oficial de [AGN del 19/01/2026](https://agn.gt/motocicletas-estuvieron-involucradas-en-el-50-de-accidentes-en-el-2025/)
informa, citando DT-PNC/ONSET, 6925 motocicletas entre 13834 vehículos involucrados
**en el país durante 2025**. Ese aproximadamente 50 % no es una probabilidad por
moto ni una proporción demostrada para Zona 1. Requiere exposición por tipo y
datos locales antes de calibrar multiplicadores.

Hay un [reporte periodístico del 16/07/2025](https://www.prensalibre.com/guatemala/sucesos/tres-cierres-viales-complican-la-movilidad-en-zona-1-de-la-capital-tras-accidente-mortal-en-el-amate-breaking/)
sobre un hecho en 6.ª/21 con información de Bomberos/PMT. Un caso localizado no
establece una frecuencia diaria ni certifica todos los movimientos del complejo.
La consulta directa al sitio de DT-PNC devolvió HTTP 403; no se presenta como
base de datos local consultada. No se extrapolan cifras nacionales/hospitalarias
a estos enlaces.

## Pruebas pequeñas y comandos

Desde la raíz, sin iniciar MATSim:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s python -p test_simz1_incident_design.py -v
.\.venv\Scripts\python.exe -B python/simz1_incident_design.py --fixture scenarios/zona1/versions/incident-design-2026-10-22/fixture.json
```

El segundo comando solo imprime el informe del fixture. Opcionalmente
`--output-new ruta-nueva.json` crea un archivo y rechaza sobrescritura. No se
proporciona un comando de corrida MATSim porque la integración está pendiente.

Cobertura: semillas, Bernoulli acotado, off sin consumo, clones/inversión/WAIT,
visitas nuevas, cuatro órdenes de productores, cupo, exclusión por vehículo y
lugar, medianoche, fin exacto de vigencia, censura, cronología, señales/receptores,
FORCE separado, contradicciones, evidencia visual prohibida, rutas/dimensiones
desconocidas, bus/moto sin respaldo de carro, geometría/cota y hashes inválidos.
La prueba con p alto verifica algoritmos; no estima frecuencia real de accidentes.

**Resultado ejecutado: 30 pruebas aprobadas.** La reducción conserva el mismo
ledger bajo las 24 permutaciones de cuatro productores simulados; no se ejecutan
threads QSim. El fixture de referencia tiene tres encuentros elegibles, tres
sorteos y **cero incidentes** con p=0,00001. Su
[`fixture-result.json`](../scenarios/zona1/versions/incident-design-2026-10-22/fixture-result.json)
registra la semilla, cada draw, el umbral y los contadores. No se aplica una cuota
para convertir ese cero en dos o cinco. Las pruebas p=1 verifican techo diario,
deduplicación, exclusión y contrato de los incidentes generados.

Los resultados ejecutados y hashes se guardan en
[`validation.json`](../scenarios/zona1/versions/incident-design-2026-10-22/validation.json).
El paso posterior es revisar el contrato y completar catálogo/observador nativos;
los bloqueos de carril quedan fuera de este diseño de detección.
