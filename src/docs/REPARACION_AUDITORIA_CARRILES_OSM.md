# Reparación acotada de la auditoría de carriles OSM

Fecha: 2026-11-01.

La auditoría estructural de `access-review-v2/config-simz1.xml` pasa con las
restricciones comprobadas. Esto no aprueba una simulación ni la preparación
balanceada completa: una prueba pequeña encontró después una guarda independiente
de extremos de actividad que sigue rechazando los derivados del transporte.

## Cambios

- `audit_configuration(..., osm_path=...)` deriva las exclusiones de pares del
  contrato existente, la identidad de las relaciones OSM y el mapeo dirigido.
  Exige las demás salidas car en cada terminal. No deriva legalidad de `lanes.xml`
  ni acepta subconjuntos arbitrarios.
- Conserva los hashes del contrato y sus fuentes. Para descontar pares exige
  el OSM fijado; verifica la procedencia de todos los enlaces car. La selección
  de contexto distingue la revisión del escenario histórico aunque compartan
  bytes de red y mapa.
- `17478998` conserva su secuencia y autómata: ambos pares componentes siguen
  siendo necesarios como movimientos legales fuera de esa procedencia.
  `17884471` mantiene el tratamiento exacto y la advertencia
  `MALFORMED_SOURCE_NO_EXECUTABLE_MANEUVER`.
- Las cinco llamadas de preparación, ejecución y validación de exportaciones
  reciben el contexto OSM. La preparación copia y comprueba esa evidencia, la
  registra como artefacto y conserva las auditorías fuente/derivada. La ejecución
  comprueba el artefacto mediante `checked_path`.
- Los derivados bus-only de `attach_transit` no conceden acceso car. La guarda
  de relaciones no representadas usa los extremos del grafo car, conservando la
  identidad exacta y la ausencia de sus miembros. Esto evita que el nodo exclusivo
  de bus de `20224473` se confunda con un movimiento car.
- Las exportaciones admiten `origid` serializado como atributo XML o atributo
  MATSim. Rechazan valores contradictorios. Se comparan firmas semánticas de red,
  carriles, señales y procedencia; no se exige igualdad de bytes entre XML
  legítimamente serializados. Los hashes de artefactos se mantienen.
- Ambos preflights llaman al mismo auditor antes de construir/recorrer la demanda.
- Los lanzadores PowerShell guardan stdout/stderr fuera de la carpeta de corrida,
  verifican la existencia del manifiesto y preservan el código original cuando
  el hijo falla antes de producirlo. No fabrican manifiestos ni `run_id`.

## Comprobaciones realizadas

Se utilizó `.venv/Scripts/python.exe -m unittest` con selección explícita.
El Python global carecía de `pytest` y `pyproj`; no se instalaron paquetes.

| Grupo | Resultado |
| --- | --- |
| `test_simz1_lane_validation`, `test_simz1_osm_turn_audit`, `test_simz1_balanced_launch`, `test_simz1_experiment_repair` | 42 pruebas pasan |
| `test_simz1_lane_osm_policy` | 9 pruebas pasan: 8 en conjunto y la novena focalizada |
| `test_simz1_child_failure` | 6 pruebas pasan con PowerShell real y hijos pequeños de prueba |
| `test_simz1_rescue_contracts` | 17 pruebas pasan |
| `test_simz1_run.RunContractTests`: `test_loaded_lanes_and_events_must_belong_to_the_selected_network`, `test_modified_or_mixed_artifacts_rejected` | 2 pruebas pasan; ejecución del hijo sustituida por `fake_matsim`, con 2 personas por fixture |
| `SequenceRegressionTests`: pruebas 01, 08 y 09 | 3 pruebas pasan; secuencias/modos, identidad exacta y mutaciones de hashes; sin prueba Java |
| `test_simz1_lane_policy_integration` | 7 casos comprobados: 1 balanceado con rechazo esperado posterior y 6 casos de preparación pequeña, ejecución detenida antes del hijo, serialización, artefactos y paridad de preflight |

Son **86 casos focalizados comprobados**. En la integración, la primera pasada
confirmó el rechazo balanceado y la paridad, pero el harness chocó con
`unittest.TestCase.run` al usar ese nombre para una ruta. Se corrigió el nombre;
los 6 casos restantes/paridad se ejecutaron de nuevo y pasaron en 47.953 s.
Se conserva el log de ese intento; no se interpreta como suite completa aprobada.

La preparación positiva usa N=6, modo `network`, el escenario revisado y el
servicio existente con 269 buses. Comprueba el manifiesto real `prepared/pending`,
los artefactos OSM, las dos auditorías, la entrada a `ejecutar()` sin iniciar un
hijo y las firmas de XML.gz de prueba. Esa modalidad no sustituye ni aprueba el
experimento balanceado. La prueba balanceada usa `generar()` completo hasta la
guarda independiente y comprueba 99 viajes particulares, las cuatro clases OD,
rutas y horarios, además del pesado y la flota fija.

La paridad negativa usa los mismos XML efectivos en preparación pequeña y ambos
preflights. Los iteradores de demanda están reemplazados por sentinelas que
fallarían si llegaran a ejecutarse. No se muestrearon las 180000 solicitudes.

La auditoría de lectura completa cuenta **6,183 enlaces**, **6,148 asignaciones**
y **7,468 colas terminales**. Acepta las **10 restricciones de pares**, que
justifican **22 referencias retiradas en 21 terminales de 9 enlaces**. La prueba
compara todas las propiedades de carriles originales/revisados y confirma que
solo difieren esas salidas. El escenario histórico también pasa su auditoría.

Las mutaciones negativas rechazan el giro prohibido reintroducido, salidas legales
eliminadas, referencias desconectadas, ciclos, capacidad, longitud, carriles
representados y procedencia alterados. Un mapa parcial que copia una relación
exacta tampoco autoriza una exclusión. Los códigos de hijo 37, 38 y 47 se
conservan; una causa seguida de 80 líneas sigue presente en el log completo.

Auditoría JSON de lectura:
`runtime/lane-policy-repair/access-review-v2-audit.json`.

## Bloqueo independiente conservado

La prueba de `generar()` balanceado con N=100 (99 particulares y 1 pesado), con
la flota fija de 269 buses, supera las dos auditorías de carriles. Después,
`check_effective_network()` rechaza:

```text
Native activity endpoint changed; access review must target effective lanes: osm_734011350_35_forward
```

El primer enlace rechazado puede variar por el orden de recorrido. La evidencia
de la última prueba registra `osm_384762167_1_forward`: extremo fuente
10.488502634659277 m y efectivo 50.44251317329641 m; longitud del enlace
52.44251317329641 m conservada. En el ejemplo anterior,
`osm_734011350_35_forward`, cambia de 10.103875966964836 m a
48.51937983482419 m. Se encontraron **46 extremos diferentes**.

El servicio existente aplica `service_original_endpoint_before_conflict_v1` y
ajusta la separación entre cola receptora y terminal. Es un cambio físico real
de los carriles derivados, no ruido numérico ni formato XML.

La prueba no produce manifiesto preparado balanceado ni inicia simulación.
No se cambió esa guarda, la revisión de accesos, los extremos físicos, el servicio
ni recibos para aprobarla. Este rechazo debe resolverse con evidencia de accesos
sobre los carriles efectivos antes de pretender aprobar la preparación balanceada.

Evidencia con valores, propiedades, ajustes y hashes:
`runtime/lane-policy-repair/integration-evidence.json`.
Log de los 6 casos finales:
`runtime/lane-policy-repair/integration-runtime-tests.log`.
Intento anterior conservado:
`runtime/lane-policy-repair/integration-tests.log`.

No se ejecutaron Validate integrado, DryRun masivo, Run1000, Maven, Java/MATSim ni
población masiva. No se modificaron visor, geometría fuente, capacidades,
dimensiones, horarios, composición, FIFO, Java de movimiento ni recibos de
aprobación. Las exportaciones usadas por las pruebas son XML construidos en
directorios temporales, no resultados de MATSim.
