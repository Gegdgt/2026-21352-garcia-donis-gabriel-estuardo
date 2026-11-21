# Corrección 5B — estado de entrega (2026-11-01)

Trabajo exclusivo de demanda particular. No ejecutar Python, Java, Maven,
MATSim, pruebas, generaciones ni subagentes; el usuario ejecutará manualmente.
No tocar Java de Correcciones 1–4, lanzadores, red, servicios ni históricos.

Implementado y revisado textualmente; pendiente de pruebas manuales:
- `python/simz1_balanced_od.py`: contrato balanced-gateway-v1, procedencia y
  hashes obligatorios, accesos exteriores existentes con cruce real y observación
  interior, orígenes revisados ponderados por longitud útil y carriles, rutas
  dirigidas, presupuesto de incorporación y reporte de demanda prevista.
- `python/simz1_balanced_od_audit.py`: firma de fuentes, aceptación de manifiesto
  y rutas particulares, comprobación de llegada exterior con evidencia nativa.
- Integración en generate_montecarlo_z1.py, simz1_agent_demand.py,
  simz1_gateway_od.py, simz1_od_policy.py, simz1_population.py y simz1_run.py.
- La nueva variante no instala zona1SpatialRouting global. El modo network
  conserva sus ramas. Camiones y buses continúan por sus integraciones existentes.
- La mezcla OD exige cuatro porcentajes explícitos que sumen exactamente 100.
  No hay mezcla empírica ni perímetro ficticio por defecto.

Trabajo concluido en esta fase:
- Pruebas pequeñas en `python/test_simz1_balanced_gateway_od.py`: cuotas grandes
  calculadas aritméticamente; generación de hasta 99 particulares; sin ejecutar.
- Contrato y comando PowerShell: `docs/CORRECCION_5_OD.md`.
- Plantilla inhabilitada: `docs/simz1-balanced-gateway-access.example.json`.
- Revisado el diff; `git diff --check` sin errores de whitespace. Comparados los
  171 hashes protegidos registrados antes de esta fase: ningún cambio. Las
  modificaciones Java ya presentes en git pertenecen a Correcciones 1–4.
- Horarios por persona idénticos al catálogo balanceado; mezcla decimal exacta
  con hash, reporte previsto, fallo de capacidad sin reprogramación ni manifiesto
  preparado, y aceptación de llegada exterior mediante evidencia nativa.

Pendientes para retomar: recibir resultados manuales de las pruebas nuevas y
resolver únicamente los fallos demostrados. No reiniciar el diagnóstico histórico
ni repetir las once regresiones Java aprobadas. No preparar Corrida 6.

Insumos reales pendientes: GeoJSON RFC7946 verificado/versionado y catálogo
de cruces, anclas exteriores, puntos interiores de incorporación y capacidades
documentadas, vinculados por SHA256 a red/carriles/OSM/perímetro. No se encontró
un perímetro verificado. La existencia de continuación exterior utilizable no
se puede certificar hasta disponer del perímetro; es una limitación distinta.

No se ejecutaron pruebas ni código Python. No avanzar a Corrección 6.

## Cierre 5B sobre los mismos archivos

Se releyeron documentos, diff e interfaces existentes. No se reinició el
generador. Se modificaron únicamente:
- `python/simz1_balanced_od_audit.py`: compara el reporte y uso de acceso contra
  planes; exige identidad persona/vehículo, salida programada observada y pareja
  LinkLeave/LinkEnter; admite el LinkEnter inicial opcional sin duplicar tramo;
  finaliza evidencia sin convertir viajes incompletos en llegadas.
- `python/simz1_population.py`: exige type/vehicleRefId en la ruta particular y
  devuelve el alcance correcto de anclas declaradas.
- `python/simz1_run.py`: conecta finish/source run_id/hash de eventos al resultado,
  registra comprobaciones OD y rechaza aceptación nativa de prepared/failed o
  proceso sin salida natural 0. Conserva todas las auditorías físicas anteriores.
- `python/test_simz1_balanced_gateway_od.py`: ahora 34 pruebas, sin ejecutar;
  agrega reintentos controlados, XML/manifiesto de 99 particulares, reporte
  alterado con hash actualizado, vehículo incorrecto, eventos iniciales,
  archivo truncado, cierre incompleto, llegada interior y estado failed.
- Este documento y `docs/CORRECCION_5_OD.md`: contratos, estados y un único bloque
  PowerShell manual con unittest -f, excepción inmediata y PASS/FAIL según salida.

La fixture 99 sigue representando N=100: 44 carros, 55 motos, 1 camión reservado.
La fixture del manifiesto usa la identidad separada de carga, no simula un servicio
de camiones o buses ni los declara aprobados. Los casos 110000/220000 calculan
solo cuotas, no construyen esas poblaciones. Un vehículo sin eventos se reporta
como nunca observado, no como espera comprobada de incorporación.

Estados:
- A–G de generación, composición, tiempos, cadenas, auditorías, restricciones y
  orígenes: IMPLEMENTADO, PENDIENTE DE PRUEBA.
- Perímetro/catálogo y acreditación de continuaciones/conectividad/capacidad
  reales: BLOQUEADO POR INSUMO EXTERNO. No apareció un GeoJSON verificado.
- Lectores visuales del contrato histórico: PENDIENTE DE IMPLEMENTACIÓN, fuera
  del alcance de generación/auditoría de 5B; no habilitados ni validados por omisión.

Siguiente acción autorizada: el usuario ejecuta únicamente el bloque de pruebas
del documento principal y comparte resultados. No ejecutar procesos desde el
agente. Si hay fallo, corregir su causa sin cambiar resultados para ocultarlo.
No preparar corridas reales hasta tener insumos revisados y nueva autorización.
