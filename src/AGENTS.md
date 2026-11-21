Base cartografica del proyecto
Por instruccion del usuario, Lab08 y los laboratorios posteriores deben construir
su mapa mediante Zona1BaseNetwork.build(network). No reintroducir una cuadricula
regular alternativa ni copiar el generador en cada laboratorio. Preservar limites
A2..12/C4..18, cortes, pasajes peatonales y atributos de prioridad.
Por instruccion posterior del usuario, no exportar hitos visualArea/visualPoi.
Los laboratorios anteriores mantienen sus escenarios historicos propios.
La geometria local es aproximada; no describirla como cartografia GIS verificada.

SimZ1 es un escenario independiente solicitado posteriormente: importa
scenarios/zona1/map.osm con python/prepare_simz1.py y se ejecuta mediante
gt.edu.uvg.sim.zona1.SimZ1. No debe sustituirse por el generador sintetico
Zona1BaseNetwork ni modificar los laboratorios anteriores al regenerarlo.
Alcance y autorizaciones
Estas son reglas estables; el estado de cada corrida pertenece al documento de
avance. La tarea vigente determina las operaciones autorizadas. Continuar las
fases ya autorizadas sin pedir confirmación repetida, pero no interpretar una
actualización documental como permiso para ejecutar o detener simulaciones.
Utilizar subagentes para este proyecto, coordinados por el agente principal.
Asignar un unico responsable de escritura por archivo; preservar cambios ajenos
y no duplicar compilaciones ni lecturas pesadas. Integrar y revisar antes de
congelar la revision; Validate y DryRun son secuenciales, sin cambios concurrentes.
La bateria experimental vigente se rige por la politica versionada
src/main/resources/simz1/day-observation-v1.json y su especificacion de experimento.
Las masivas futuras las inicia manualmente el usuario desde PowerShell externa;
Codex no ejecuta Run masivo ni lo encadena a Validate/DryRun. El horizonte futuro
es 24 h; la politica anterior de 30 h y sus resultados permanecen historicos.
No resucitar corridas interrumpidas ni reinterpretarlas como dias completos.
La limpieza de corridas historicas solo procede con autorizacion expresa vigente,
inventario validado y fixtures verificadas; no afecta fuentes ni laboratorios.
Recuperar el estado antes de continuar SimZ1
Revisar git status --short, el diff pertinente y los archivos nuevos. Leer el
encabezado activo de docs/SIMZ1_180000_AVANCE.md y las evidencias que identifica;
consultar secciones históricas solo cuando sean relevantes.

Contrastar con runtime/launches/<LaunchId>/state.json, el run-manifest.json
de la corrida explícita, logs y procesos reales. No interpretar un cierre histórico
como estado vigente ni sustituir una corrida por la carpeta más reciente o
latest-successful. Una discrepancia se documenta; no se alteran evidencias
para hacerlas coincidir. El MD no sustituye validadores ni eventos nativos.
Preservar el trabajo y limitar los cambios
Conservar cambios previos y archivos no rastreados. No hacer reset, clean,
checkout destructivo, commit, push ni borrados históricos sin autorización.
Corregir el mecanismo demostrado con cambios acotados en Python o Java y pruebas;
no prohibir genéricamente editar Java ni reescribir el motor.

No modificar silenciosamente N, composición, semilla, OD, horarios, horizonte,
rutas fijas, flotas, cuerpos, capacidades, geometría o señales para conseguir PASS.
Los parámetros proceden de la tarea y configuración versionada; no duplicarlos
como constantes permanentes en AGENTS.md. Conservar las variantes autorizadas;
cualquier variante nueva requiere alcance explícito, originales preservados,
procedencia y distinción entre supuestos sintéticos y observaciones.
Invariantes físicos y evidencia
Preservar FIFO por carril, separación de 0.10 m, recepción nativa, reservas de
carrocería, prioridades, señales, paradas, despeje corporal y restricciones OSM.
El reruteo conserva identidad OD, prefijo por ocurrencia, cursor y reservas
compatibles. Consultar admisión no equivale a confirmar movimiento.

No forzar cruces, adelantar cuerpos, fabricar llegadas, liberar reservas por
timeout ni retirar vehículos atascados para aprobar. Una espera larga no prueba
un error: distinguir congestión física y defectos mediante evidencia. IDs de
carril distintos no prueban independencia; coordenadas de enlace y corredor
requieren identificar su referencia. Datos ausentes no son ceros ni permisos.

Corregir un auditor solo ante un error demostrado de interpretación, con pruebas
positivas y negativas; no debilitarlo para aceptar una violación real. Mantener
requireApproved() y los criterios de aceptación vigentes.
Diagnóstico, pruebas y flujo de ejecución
Reutilizar informes y extractos antes de releer eventos. Procesar archivos grandes
incrementalmente, con cobertura explícita; no cargar XML completo en RAM ni repetir
escaneos sin necesidad. Distinguir hechos, reconstrucciones, hipótesis y fixtures.
Reproducir antes del parche y comprobar después el caso y sus controles negativos;
usar componentes nativos cuando el problema afecte movimiento o admisión.

Ejecutar las regresiones afectadas y conservar la cobertura de C529-A/B/C/D,
OD/OSM, pasajes temporales, L18, llegada corporal y última parada de buses.
Una prueba focal no acredita la masiva. Revisar las fixtures dependientes de
archivos nuevos antes de repetir Validate completo.

No excluir dependencias del fingerprint ni editar recibos para aprobar. Actualizar
expectativas de hashes protegidos únicamente tras revisar el cambio autorizado,
su justificación y las pruebas negativas de mutación/ausencia.

Flujo para una revisión nueva: pruebas focalizadas -> Validate vigente -> DryRun
del experimento -> Run autorizado -> auditorías -> gráficas -> visor. No repetir
fases válidas sin causa, salvo las comprobaciones normales del lanzador. Un cambio
solo documental no requiere MATSim; comprobar su impacto en la huella antes del
próximo lanzamiento, sin eludir el mecanismo existente.

Usar JDK17 y .venv; verificar los parámetros reales de los scripts. Capturar
$LASTEXITCODE inmediatamente en PowerShell y no pasar a la siguiente fase tras
un rechazo. -FirstScaleTrial requiere autorización y no sustituye Validate,
fingerprint, preflight ni auditorías; nunca fabricar una aprobación Run1000.
Procesos, recursos y recuperación
Mantener una sola masiva activa, mutex, exclusividad de escritores y guardas
originales de memoria/disco. No reducir el mínimo de espacio para forzar el inicio.
Antes de intervenir, verificar PID, fecha de creación, padre y comando; un PID
guardado puede estar obsoleto. No terminar procesos por nombre global ni tocar
servidores del IDE o procesos ajenos.

Un reinicio del editor no demuestra que la simulación terminó. Recuperar primero
el estado en solo lectura; no duplicar lanzamientos u observadores ni eliminar
locks sin acreditar su propiedad. Un log no es un checkpoint para reanudar QSim.
Congelar fuentes e insumos durante la corrida. No detenerla solo por lentitud o
atraso del lector. Una interrupción autorizada debe conservar evidencia, motivo,
identidad del proceso y estado incompleto. Cada reintento necesita una causa
documentada, directorio nuevo y controles aplicables, no una repetición ciega.
Resultados, gráficas y visor
Distinguir preparado, preflight aprobado, QSim iniciado y completed/valid.
El reloj o la CPU avanzando no prueban descarga; una llegada no acredita por sí
sola OD, ventana ni despeje. La aceptación técnica no equivale a calibración.
Separar reloj nativo y cobertura del auditor, intervalos y acumulados, vehículos
y expediciones, espera de incorporación y ocupación. WAIT cuenta intentos, no
segundos ni vehículos distintos; no mezclar abortos finales con estados previos.

No promover corridas fallidas/interrumpidas ni editar manualmente sus entradas,
eventos o aceptación. Gráficas oficiales: corrida aceptada, Run ID e iteración
explícitos. Diagnósticos provisionales: carpeta separada, estado real, fuentes y
cobertura. No sustituyen la entrega aceptada. Conservar informes cuando el estado
nativo sea válido pero el screening indique review_required.

No repetir QSim por fallos de análisis o presentación. Reutilizar el posproceso;
verificar que los archivos entregados existan. El visor debe validar el contrato
de la corrida, incluido balanced-gateway-v1 cuando corresponda, sin sustituir
resultados por históricos ni cambiar la identidad nativa. Registrar por separado
la versión del posprocesador; comprobar navegación temporal e identidad y declarar
cualquier prueba visual no realizada.
Continuidad y puntos de entrada
Actualizar el encabezado activo de docs/SIMZ1_180000_AVANCE.md por hitos:
fecha, fase, causa demostrada, revisión, LaunchId/run_id, procesos comprobados,
pruebas/códigos, evidencias y siguiente acción. Marcar lo anterior como histórico.
No guardar PID, hashes, bloqueos o éxitos pasajeros en AGENTS.md.

Informar por hallazgos, sin porcentajes inventados. Dejar logs persistentes y un
comando de seguimiento de solo lectura utilizable fuera del panel del editor.
No crear documentación paralela, herramientas o dependencias si el flujo existente
resuelve la tarea. Mantener este archivo estable y evitar duplicar el historial.

Puntos de entrada a inspeccionar según la tarea, no órdenes para ejecutarlos todos:
- scripts/check_simz1_110k_balanced_gateway.ps1: validación integrada.
- scripts/run_simz1_180k_balanced_gateway.ps1: DryRun y Run del experimento.
- scripts/watch_simz1_110k.ps1: seguimiento de lanzamientos.
- scripts/run_simz1_with_analysis.ps1: análisis y empaquetado.
