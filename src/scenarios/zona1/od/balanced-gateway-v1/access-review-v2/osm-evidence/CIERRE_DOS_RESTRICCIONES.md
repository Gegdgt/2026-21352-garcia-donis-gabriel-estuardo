# Revisión focalizada de 17478998 y 17884471 — 2026-11-01

Estado: **BLOQUEADO**. No se modifica el motor Java ni los insumos efectivos.
Esta revisión complementa, sin sobrescribir, `../../osm-turn-resolution.json`.
Los resultados de diagnóstico no son una aprobación de generación/reruteo.

## 17478998 v1: incompatibilidad exacta

La fuente completa coincide con la relación local: `from=1273145789`,
`via=1270930401` (way), `to=1273145790`, `restriction=no_u_turn`.
No contiene `except`, restricciones por modo ni condiciones temporales.
Prohíbe A→V→B, donde A=`osm_1273145789_0_forward`,
V=`osm_1270930401_0_forward`, B=`osm_1273145790_0_forward`.
C=`osm_734011349_14_forward` también llega a V; C→V→B no es prohibida
por esta relación. A→V→`osm_260940553_0_forward` tampoco lo es.

Los dos carriles terminales de V admiten B y `osm_260940553_0_forward`.
Ambas procedencias pueden usar esos carriles. Quitar V→B elimina también
C→V→B; quitar A→V elimina la otra salida legal. Ninguna retirada de pares
es equivalente a la prohibición de tres enlaces. No se retira ninguno.

Puntos exactos del código actual:

- `SimZ1RouteSafety.successors` y `allowedTurnInfos()` guardan pares.
  `validateNetwork()` conserva solamente el enlace inmediatamente anterior;
  `validateReplacement()` delega a ese comprobador después del empalme.
- `SimZ1TurnRouter.State(Id<Link> id, boolean initial)` fusiona las llegadas
  a V desde A y C. `path()` no recibe el prefijo recorrido.
- `CongestionAwareRerouting.attempt()` llama a `router.path(position.link(), …)`
  sin transmitir la procedencia, y luego empalma con `splice(old,index,suffix)`.
- `ExperiencedTimeRouting.configure()` instala `allowedTurnInfos()` como
  `NetworkTurnInfoBuilderI`: el enrutamiento primario/ReRoute tampoco tiene
  estado de secuencia.
- `BalancedGatewayModel._tree()` indexa distancias por enlace;
  `validate_route()` solo comprueba pares. El cargador de producción sí bloquea
  previamente ambas relaciones mediante `validate_osm_turns()`.

### Cambio mínimo necesario, documentado antes de cualquier cambio físico

1. Un contrato de secuencias OSM con huellas, compartido por Python y Java,
   que preserve los miembros ordenados, modos y excepciones.
2. Validar rutas completas contra ese contrato, incluyendo el límite entre
   prefijo recorrido y sufijo nuevo, usando el índice de ocurrencia real.
3. Buscar rutas en estados `(enlace, progreso de secuencia)` tanto en generación
   inicial como en el reruteador. Pasar a `path()` el estado derivado del prefijo.
   Un rechazo posterior del único camino más barato no basta para conservar
   alternativas legales.
4. Sustituir/ampliar la integración primaria de pares de `ExperiencedTimeRouting`
   para que ReRoute utilice la misma política; comprobar también rutas fijas.
   La expansión necesaria sería del grafo de búsqueda, nunca duplicación de
   enlaces/carriles físicos, capacidad o reservas.
5. Probar el rechazo de A→V→B, conservación de C→V→B y A→V→otra salida,
   generación, reruteo desde V, rutas repetidas, buses y carga.

Esto requiere cambiar el enrutamiento Java que el usuario pidió conservar.
No existe una opción de los XML actuales que haga este trabajo. No se modifica
Java, no se elimina el bloqueo y no se presenta un filtro de `access.json` como
solución. El probe Java de seis enlaces ejecuta únicamente funciones de búsqueda
y validación compiladas desde el código actual; no inicia Controller ni QSim.

## 17884471 v2: dato fuente malformado confirmado

La respuesta `/full` y el historial oficial coinciden exactamente con la copia:
v2, changeset **178612606**, timestamp **2026-02-16T06:36:31Z**, único miembro
`to=34993910`, tags `restriction=no_straight_on`, `type=restriction`.
La pérdida de `from` y `via` no fue causada por el extracto.

La v1 contenía `from=381158225`, `via=node 333864721`, `to=34993910`.
El historial del way 381158225 confirma su eliminación (v11, `visible=false`)
en el mismo changeset y timestamp de la v2. No aparece en la red/OSM local.
Restaurar v1 exigiría recuperar o sustituir un way eliminado y extrapolar qué
movimiento actual corresponde. Esa evidencia no existe; no se restaura v1.

Tratamiento preparado: clasificar exclusivamente ese contenido y versión como
`MALFORMED_SOURCE_NO_EXECUTABLE_MANEUVER`, con advertencia verificable, sin
inventar un giro, prohibir el destino ni conceder permisos generales. La
clasificación comprueba identidad completa, historial y SHA256 de las cuatro
respuestas fuente. Cambiar ID, versión, miembros, tags o evidencia invalida
este tratamiento; no se aplica a otras relaciones.

**No está activado como excepción del preflight.** La función de producción
no dispone de un contrato de calidad de datos; sigue rechazando la relación.
El tratamiento queda preparado en `remaining-osm-review.json`, sin borrar ni
reclasificar el objeto original en `map.osm`. Su integración debe conservar la
advertencia y verificar las huellas antes de exceptuar exclusivamente v2.
Las restricciones completas conservan todos sus criterios de rechazo.

## Preservación y aceptación

`preserved-input-hashes.json` fija los insumos antes de esta revisión: copia
aislada, Java, fuentes históricas, perímetro, gateways, mezcla, horarios, carga,
transporte público y recibo Validate. Las diez correcciones de carril siguen
intactas. No se cambian longitudes, capacidades, carriles, semáforos, prioridades,
FIFO, reservas, separación de 0.10 m, semilla 20261023 ni composición.

Las rutas L12/L13 mantienen `osm_34993910_0_forward`; no se editan para pasar
una prueba. La verificación de rutas es estática, sin simular ni certificar
capacidad. La asignación efectiva de los 178200 particulares por gateway/hora
sigue sin calcular. No se suman techos nominales para declarar viabilidad.

La huella se compara solo en lectura. No se fabrica ni actualiza un recibo.
Los archivos de evidencia dentro de `od/` no forman parte del fingerprint actual
de `simz1_workflow_state.py`; no cambian insumos operativos en esta revisión.
La huella anterior ya era obsoleta. La evidencia nueva no renueva autorización.

## Resultado de las pruebas focalizadas

`test_remaining_osm.py`: **15 diagnósticos aprobados**, 0 fallos, 0 errores,
0 omitidos; 28.066 s. Resultado operativo: **BLOQUEADO**, conservado explícitamente
en `remaining-osm-review.json` y al final del log. No hay PASS de restricciones.

- Se reproduce el error exacto de producción para las dos relaciones antes
  de que `load_model()` entregue un generador de demanda.
- La prueba Java compila desde las fuentes actuales `SimZ1RouteSafety`,
  `SimZ1TurnRouter` y `DrivingProfiles` en un directorio temporal. El fixture
  de seis enlaces reproduce la fusión de procedencias: genera A→V→B y
  `validateReplacement()` acepta el mismo patrón tras empalmar un sufijo.
  C→V→B sigue admitido. Es una prueba del algoritmo, no una corrida de QSim
  ni evidencia de un vehículo efectivamente reruteado en el escenario real.
- Los **115 pares OD seleccionados** conservan rutas estáticas sin la secuencia;
  la búsqueda interior no incluye B. Esta selección de accesos no demuestra
  la imposición global de la relación y no levanta el guard de producción.
- **4 rutas de carga y 24 tramos de buses** conservan conectividad y no usan
  la secuencia prohibida. Las conexiones de buses incluyen las extensiones
  bus-only ya documentadas en su bundle, con la regla de preparación existente.
  L12/L13 conservan el destino de 17884471. No se inventa acceso nuevo.
- Se conservan las **10 restricciones corregidas y 22 retiradas**; una
  restricción válida distinta sin corregir (6008781) sigue siendo rechazada.
- La clasificación de calidad rechaza otros IDs, versiones, changesets,
  visibilidad, tags o miembros añadidos. Se comprueban las huellas de las
  fuentes descargadas y de **115 archivos preservados**, incluido el recibo.

El primer intento de prueba se conserva en `attempt-1-*`: tenía dos supuestos
incorrectos del fixture (extensiones de buses y dominio interior), y Java no
pudo acceder a dependencias bajo el sandbox. Se corrigieron exclusivamente las
pruebas y se repitieron con acceso de lectura a los JAR locales. No se cambió
ningún criterio de producción para obtener el resultado final.

Huella aprobada: `a9b9206b703abb8bde1f74541d8f277ccb741323707d7f8110235663fca59a01`.
Huella actual: `0e90642a28041355f9af92645987f7ad4345c004b8eaec43b193f7076ee8707c`.
Recibo intacto SHA256: `cec20a291daa3dcac86149c8fe75cfde91795d421a307098c6563a48babfd349`.

## Comandos manuales preparados (no ejecutados)

Desde `C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala`:

```powershell
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_simz1_110k_balanced_gateway.ps1 -Action Validate -JavaHome 'C:\Program Files\Java\jdk-17'
if ($LASTEXITCODE -ne 0) { throw "Validate fallo: $LASTEXITCODE" }
```

Solo después de cerrar la incompatibilidad y renovar Validate:

```powershell
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_180k_balanced_gateway.ps1 -DryRun -FirstScaleTrial -JavaHome 'C:\Program Files\Java\jdk-17'
if ($LASTEXITCODE -ne 0) { throw "Preflight bloqueado: $LASTEXITCODE" }
```

El DryRun actual debe seguir rechazando ambas relaciones. No se ejecutaron
Validate, DryRun, Run1000, preflight completo, generación masiva ni MATSim.
