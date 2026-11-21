# SimZ1: tiempos por perfil y hora de salida

El entregable principal de `python/generar_graficas_z1.py` se publica en
`analysis/it.N/graficas_perfiles/`. Usa `simz1_trip_table.py` para validar o
reutilizar `trips.csv.gz`, `procesar_eventos_z1.py` para leer las identidades
registradas en los planes y `simz1_trip_distributions.py` para las estadísticas.
`simz1_profile_plots.py` dibuja los resúmenes; no vuelve a leer los eventos.

## Reproducción en PowerShell

Desde la raíz del repositorio, con el entorno existente `.venv`:

```powershell
$run = '.\scenarios\zona1\montecarlo\run-manual-seven-b20ba6c09e7d422d826847ffe5155e52'
$analysis = '.\runtime\simz1-tesis-perfiles-revision2\analysis'
& .\.venv\Scripts\python.exe .\python\generar_graficas_z1.py `
    --run-dir $run --iteration 0 --profiles-only --analysis-dir $analysis
```

Sustituir `$run` y la iteración para analizar otra corrida **ya validada**. El
ejemplo usa una corrida pequeña existente de siete personas, con seis perfiles;
no constituye evidencia de una jornada masiva. Omitir `--run-dir` selecciona
`latest-successful`, con la comprobación de identidad y hashes existente. No se
ejecuta MATSim. La opción `--analysis-dir` mantiene intacta la corrida fuente y
escribe `it.N/` debajo de esa raíz; no admite seguimiento entre iteraciones,
historial de aprendizaje ni el gráfico horario anterior porque esos productos
utilizan rutas de la corrida fuente.

Sin `--analysis-dir`, la ubicación es `<run>/analysis/it.N/`. `--profiles-only`
produce el entregable completo de seis figuras, incluido su histograma, y evita
la generación adicional de productos anteriores. `--mode` conserva su alcance
sobre esos productos anteriores; el entregable principal siempre considera los
modos observados de cada perfil, identificados en sus metadatos y CSV. No fuerza
un modo `car` para las motocicletas.

Las imágenes existentes se conservan. Si `graficas_perfiles` ya contiene
archivos, se rechaza la escritura antes de exportar; utilizar otra raíz de
análisis para una revisión. Un CSV canónico válido se reutiliza sin recalcular
eventos ni modificar su archivo original. Un derivado con procedencia o
integridad incorrecta se reconstruye desde su fuente validada.

## Métrica e interpretación

- Unidad de observación: una salida aceptada `PersonDepartureEvent`, identificada
  por `(run_id, iteration, person_id, trip_index)`. Es una etapa departure-arrival,
  no un segmento de enlace ni un itinerario multimodal puerta a puerta.
- Duración completada: `(PersonArrivalEvent.time - PersonDepartureEvent.time)/60`,
  en minutos simulados, incluyendo espera antes de entrar al tráfico.
- Cohortes: hora absoluta de **salida**, `[h*3600, (h+1)*3600)`, para las 24 horas
  00..23. Una salida a las 23:59 con llegada después de medianoche permanece en
  la hora 23. Las salidas a partir de 86400 segundos se cuentan aparte, sin
  aplicar módulo 24.
- Las medias de familia, perfil global y distribución usan cada viaje completo
  con peso uno. No se promedian las medias horarias ni las de subtipos. Los
  percentiles exactos usan interpolación lineal sobre duraciones individuales.
- `n_excluded = n_aborted + n_censored`, dentro del mismo grupo y ventana de
  salida. Las tasas tienen como denominador `n_total` del grupo. Otros tipos,
  identidades no resueltas y salidas fuera de la jornada se contabilizan aparte.
- Aborto previo al horizonte y censura al final de observación siguen las reglas
  de `TripAudit`. Sin llegada válida no se inventan duración ni llegada cero.
- Una media, mediana o percentil sin datos es `null` en JSON y `sin datos` en CSV.
  Los PNG usan SD (sin observaciones) y SC (hay salidas, sin completos). Un conteo
  observado cero es distinto de una duración cero. Los conteos del CSV conservan
  cero para permitir reconciliación, junto con `sample_status`.
- `--min-sample 30` marca por defecto los grupos con 1..29 viajes completos.
  Es una advertencia descriptiva del tamaño de muestra; no certifica suficiencia
  estadística ni significancia. Las medias describen únicamente viajes que
  llegaron; deben interpretarse junto con sus tasas de aborto y censura.

## Identidades y población

`person_id`, `vehicle_id`, `vehicle_ids`, `trip_index`, `profile` y `mode` se
conservan en el CSV canónico. Los resúmenes usan `profile` como tipo efectivo,
`family` como familia y `modes` como lista de modos MATSim realmente observados.
`vehicle_id` es el primer vehículo observado y no se presupone igual a la persona.

| Tipo registrado | Etiqueta del entregable | Familia |
| --- | --- | --- |
| Normal | Carro (Normal) | Carro |
| Tortuga | Carro Tortuga (Tortuga) | Carro |
| Liebre | Carro liebre (Liebre) | Carro |
| Motociclista | Moto | Moto |
| MotocicletaLenta | Moto tortuga | Moto |
| MotocicletaRapida | Moto Liebre | Moto |

La identidad procede de planes verificados de la iteración, o del snapshot de
entrada de esa corrida cuando la iteración solo dispone de tabla compacta.
Se contrastan `effectiveVehicleType`, `simz1AgentType`, `simz1VehicleFamily`,
`simz1AgentSchema` y `drivingProfile`. El mapeo histórico acepta explícitamente
Normal/Tortuga/Liebre como carros. La velocidad, el nombre de la persona y el modo
MATSim no son pruebas de que sea una motocicleta. Las seis posiciones siempre
están presentes; un perfil sin respaldo/observaciones queda sin datos.

Transporte pesado, pasajeros e identidades ajenas a los seis perfiles tienen
resúmenes propios. La flota fija y sus conductores internos nunca incrementan la
población Monte Carlo. El compacto nativo puede excluir a esos conductores; su
contabilidad se toma del informe de transporte público ya auditado en el
manifiesto y se conserva en `resumen_perfiles.json/provenance`. Ausencia de esa
observación se registra como desconocida, no como cero ni como viaje de carro.

## Archivos

En `graficas_perfiles/`:

- `carros_por_hora.png`, `motos_por_hora.png`: barras agrupadas y N por perfil/hora.
- `comparacion_familias_por_hora.png`: medias de Carro y Moto desde viajes individuales.
- `comparacion_global_perfiles.png`: seis medias y N completos/excluidos.
- `completitud_por_hora.png`: conteos y tasas por hora/perfil, en tres paneles.
- `duration_distribution.png`: histograma real, mediana, P95 y distribución acumulada,
  separado de las barras; unidades en minutos simulados.
- `estadisticas_por_perfil_hora.csv`: 144 filas (seis perfiles por 24 horas).
- `estadisticas_por_familia_hora.csv`: 48 filas (dos familias por 24 horas).
- `estadisticas_globales.csv`: seis perfiles y dos familias; son vistas distintas,
  por lo que sus conteos no se suman entre sí.
- `categorias_separadas.csv`, `categorias_separadas_por_hora.csv`: tipos fuera de la
  comparación principal, sin mezclarlos con carros/motos.
- `resumen_perfiles.json`: identidad de corrida/iteración, fuentes, filtros,
  definiciones, percentiles, cuentas de exclusión y todos los resúmenes.

Los CSV incluyen media, mediana, P95, completos, excluidos, abortados, censurados,
tasas, modos observados y estado de muestra. Los PNG contienen identidad,
definición de métrica y filtros en título o metadatos. Los gráficos anteriores
conservan sus rutas, unidades y estadísticas originales.

## Rendimiento y pruebas

La agregación principal recorre el CSV.gz en streaming; retiene vectores numéricos
compactos para percentiles exactos y un índice de identidad por persona. No crea
un DataFrame de viajes ni consulta Motion_Plan. Produce seis imágenes para toda
la selección, independientemente del número de personas.

```powershell
$env:PYTHONPATH = '.\python'
& .\.venv\Scripts\python.exe -m unittest `
    test_simz1_profile_statistics test_simz1_profile_identity_cache `
    test_simz1_trip_table test_procesar_eventos_z1 test_generar_graficas_z1 -v
```

Las fixtures cubren seis perfiles ×24 horas, cruces de hora/medianoche, ausencia
de perfil o llegada, aborto/censura, varios viajes de una persona, vehículos con
ID diferente, modos distintos, esperas anteriores a la entrada al tráfico,
ponderación desigual, percentiles, identidades efectivas, integridad de caché,
PNG/CSV/JSON y preservación del origen con análisis externo. Las pruebas usan
temporales y simuladores mockeados; no lanzan simulaciones reales. La prueba de
evidencia cruzada Java se omite si su fixture previa no existe.
