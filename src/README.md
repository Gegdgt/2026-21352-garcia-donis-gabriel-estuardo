# SimZ1 🚦

**Simulación basada en agentes del tráfico urbano mediante un entorno tipo sandbox para análisis y evaluación de estrategias de movilidad en un sector de la Zona 1 de la Ciudad de Guatemala**

![Java 17](https://img.shields.io/badge/Java-17-orange)
![MATSim 15.0](https://img.shields.io/badge/MATSim-15.0-blue)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB)

## Descripción

SimZ1 es un entorno de experimentación para estudiar el tráfico urbano de un sector de la Zona 1 de Guatemala.
Combina simulación basada en agentes con MATSim, una red de OpenStreetMap y un visualizador WebGL.
Permite explorar escenarios de movilidad y analizar tiempos de viaje, congestión y diferencias entre perfiles de conducción.

La demanda es sintética: los resultados describen experimentos de simulación, no aforos municipales ni una calibración empírica del tráfico real.

## Características principales

- **Red vial basada en OpenStreetMap:** enlaces, carriles, señales y atributos de prioridad.
- **Diversidad de vehículos:** carros, motocicletas, transporte de carga y servicio público Transmetro/TuBus.
- **Escenarios configurables:** demanda, horarios, rutas y reglas de circulación para comparar experimentos.
- **Ejecuciones reproducibles:** semillas, identificadores de corrida y manifiestos para conservar la procedencia de los resultados.
- **Análisis y entregables:** métricas de viajes y completitud, tablas CSV/JSON y gráficas PNG.
- **Visualización WebGL:** navegación temporal del replay, selección de vehículos y consulta de sus recorridos.

## Requisitos

- Windows y PowerShell.
- JDK 17; el proyecto incluye Maven Wrapper para compilar y resolver las dependencias de MATSim.
- Python 3.10 o superior y un entorno `.venv` con las dependencias de [requirements.txt](requirements.txt).
- Node.js 22 o superior para las pruebas JavaScript incluidas en `Validate`.
- Un navegador compatible con WebGL y acceso a Internet para cargar las bibliotecas del visor.

Consulta las [notas de instalación y dependencias](docs/README.md#regeneracion) para preparar el entorno.

<a id="inicio"></a>
## Inicio rápido

Ejecuta los siguientes pasos desde la raíz del repositorio, en orden, y continúa solo si el anterior termina correctamente.

### 1. Validar el entorno y compilar

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\simz1_workflow.ps1 -Action Validate
```

### 2. Ejecutar la prueba de 1000 vehículos

`Run1000` crea una corrida nueva de 1000 vehículos no públicos —carros, motos y carga— con transporte público adicional. El ejemplo fija la semilla y la fecha de servicio para permitir su reproducción.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\simz1_workflow.ps1 `
    -Action Run1000 -Seed 20261023 -ServiceDate 2026-10-23 `
    -AcceptTransitRouteAssumptions
```

La opción `-AcceptTransitRouteAssumptions` reconoce los [supuestos documentados del servicio público](docs/README.md#flota-publica-entre-semana-v2).

### 3. Abrir el visualizador

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\simz1_workflow.ps1 -Action View
```

`View` abre el replay de la prueba de 1000 registrada. Los resultados, las gráficas y las tablas se guardan dentro de la carpeta de corrida que imprime el lanzador.

### 4. Corrida masiva de 180.000 a 220.000 vehículos

Después de aceptar la prueba de 1000, este bloque sortea una cantidad de **180.000 a 220.000 vehículos no públicos**, añade los **269 buses** y ejecuta **10 iteraciones (0–9)** en una carpeta nueva. La semilla del sorteo queda registrada en los resultados. Ejecútalo desde la raíz del repositorio cuando no haya otra simulación en marcha.

Si la corrida y sus controles terminan correctamente, abre la carpeta de gráficas y el visualizador de la **iteración 9**. El umbral de 150 GiB libres es una comprobación preventiva, no una garantía de espacio suficiente para toda la ejecución.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    & .\.venv\Scripts\python.exe -B .\python\simz1_workflow_state.py require-trial
    if ($LASTEXITCODE -ne 0) { throw 'Se requiere una prueba de 1000 aceptada para esta revisión.' }

    $name = 'run-massive-10it-' + [guid]::NewGuid().ToString('N')
    $run = Join-Path (Get-Location).Path "scenarios\zona1\montecarlo\$name"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_simz1_with_analysis.ps1 `
        -MinAgents 180000 -MaxAgents 220000 -Iterations 10 -MinFreeGiB 150 `
        -ServiceDate 2026-10-23 -AcceptTransitRouteAssumptions -NewRunDir $run
    if ($LASTEXITCODE -ne 0) { throw "Revisar los resultados conservados en $run antes de continuar." }

    Invoke-Item -LiteralPath (Join-Path $run "entregables\$name-it.9\graficas")
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $listener.Start()
    $port = $listener.LocalEndpoint.Port
    $listener.Stop()
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\simz1_workflow.ps1 `
        -Action View -RunDir $run -Iteration 9 -Port $port `
        -SQLiteBudgetGiB 64 -ScratchBudgetGiB 32
    if ($LASTEXITCODE -ne 0) { throw "Revisar la preparación del visor de $run; conservar la simulación." }
}
```

## Estructura del código

```text
matsim-guatemala/
├─ AGENTS.md                       Convenciones de trabajo del proyecto
├─ pom.xml                         Dependencias MATSim 15.0 y compilación Java 17
├─ src/main/java/                  Escenarios Java e integración con MATSim
├─ scenarios/zona1/                OSM, red, carriles, señales y configuración
│  └─ montecarlo/run-*/            Resultados independientes de cada corrida
├─ python/
│  ├─ ejecutar_simz1.py            Generación, ejecución y validación de MATSim
│  ├─ procesar_eventos_z1.py       Procesamiento de eventos
│  ├─ generar_graficas_z1.py       Gráficas y comparaciones estadísticas
│  ├─ simz1_analysis.py            Publicación del análisis
│  ├─ simz1_weekday_transit.py     Flota pública y horarios de servicio
│  ├─ simz1_congestion_audit.py    Diagnóstico sobre eventos existentes
│  ├─ simz1_result_quality.py      Evaluación de completitud y anomalías
│  └─ serve_simz1_continuous.py    Servidor del replay WebGL
├─ scripts/
│  ├─ simz1_workflow.ps1           Flujo de validación, ejecución y visualización
│  ├─ prepare_simz1_runtime.ps1    Compilación y comprobación del arranque
│  ├─ run_simz1_with_analysis.ps1  Ejecución, análisis y empaquetado
│  └─ replay/start_replay.ps1      Apertura de un replay existente
└─ docs/README.md                  Guía técnica, contratos y limitaciones
```

## Documentación Técnica

Los detalles microscópicos del modelo, las correcciones de errores, las validaciones de corridas anteriores y los comandos de recuperación se encuentran en [`docs/`](docs/README.md).

| Documento | Contenido |
| --- | --- |
| [Guía técnica](docs/README.md) | Arquitectura, configuración, análisis, validación y recuperación de resultados. |
| [Composición vehicular](docs/simz1-composicion-vehicular.md) | Definición de la demanda, perfiles y relación entre vehículos privados, carga y flota pública. |
| [Transporte de carga](docs/simz1-freight.md) | Rutas, horarios y contratos del servicio pesado. |
| [Ocupación y separación](docs/simz1-occupancy.md) | Reglas del modelo, reconstrucción visual y límites de interpretación. |
| [Navegación del replay](docs/simz1-replay-navigation.md) | Carga temporal, rendimiento, comprobaciones y limitaciones vigentes del visor. |
| [Registro de verificaciones](docs/simz1-verification-20261027.md) | Pruebas, evidencias y alcance de las validaciones documentadas. |
| [Archivo del README anterior](docs/readme-historico-20261030.md) | Bitácora y referencias históricas conservadas fuera de la portada. |

## Créditos

**Gabriel García** · Carnet **21352**

**Universidad del Valle de Guatemala (UVG)**
