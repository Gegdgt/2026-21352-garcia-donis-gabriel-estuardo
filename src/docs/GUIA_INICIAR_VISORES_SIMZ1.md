# Cómo iniciar los dos visores finales de SimZ1

Esta guía abre los resultados que ya existen. No ejecuta MATSim/QSim, no repite corridas y no reconstruye el replay ni SQLite. Los servidores se mantienen activos aunque cierre PowerShell, VS Code o el navegador. Al apagar o reiniciar Windows, debe iniciarlos de nuevo.

## 1. Abrir PowerShell

Abra el menú **Inicio**, escriba **PowerShell** y abra **Windows PowerShell**. No necesita elegir «Ejecutar como administrador».

Copie un comando completo, péguelo en PowerShell y presione **Enter**. Espere el resultado antes de ejecutar el siguiente.

## 2. Un solo comando después de reiniciar Windows

Este comando funciona desde cualquier carpeta de PowerShell. Inicia ambos visores y abre sus páginas en Microsoft Edge cuando los servicios ya responden y su identidad fue comprobada:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala\scripts\start_simz1_viewers.ps1' -Both -Open
```

`-ExecutionPolicy Bypass` se aplica solamente a este proceso de PowerShell; no cambia la configuración permanente de Windows. Puede repetir el comando: reutiliza los servidores compatibles que ya estén activos.

No basta con abrir una URL mediante `Start-Process`: ese comando abre el navegador, pero no inicia los servidores. Use el lanzador anterior después de cada reinicio.

## 3. Entrar a la carpeta del proyecto

Para usar los comandos cortos del resto de esta guía, ejecute primero:

```powershell
Set-Location -LiteralPath 'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala'
```

Los comandos cortos siguientes suponen que sigue en esa carpeta.

## 4. Iniciar ambos visores

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_simz1_viewers.ps1 -Both -Open
```

Si desea encenderlos sin abrir el navegador, omita `-Open`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_simz1_viewers.ps1 -Both
```

El lanzador comprueba los archivos y las identidades, inicia las fuentes necesarias antes de las interfaces finales y espera su disponibilidad con un tiempo límite. Si algo falla, muestra un error; no debe interpretarse una URL impresa en un documento anterior como prueba de que un servidor sigue encendido.

El primer arranque, especialmente después de reiniciar Windows, puede tardar varios minutos mientras lee y comprueba los resultados existentes. En esta recuperación, el arranque frío de Run1000 tardó aproximadamente **5 minutos y 41 segundos**, incluida la preparación de la caché de lectura del visor. El límite predeterminado es **600 segundos por verificación o servicio**, no una espera fija: continúa en cuanto la comprobación termina. Esa lectura no ejecuta una simulación ni reconstruye el replay o SQLite.

Si vence el límite mientras un servicio se está preparando, el lector registrado puede seguir trabajando. Consulte sus logs y repita el mismo comando de inicio: el lanzador reconoce ese proceso y espera su disponibilidad sin crear otra copia. Un límite agotado durante la verificación previa se informa por separado y no inicia servicios nuevos.

## 5. Abrir solamente Run1000

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_simz1_viewers.ps1 -Run1000 -Open
```

Página final: <http://127.0.0.1:8804/index.html>.

Run1000 necesita dos servicios: la fuente de datos en **8799** y la interfaz final en **8804**. El lanzador se encarga de ambos.

## 6. Abrir solamente Run10K

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_simz1_viewers.ps1 -Run10K -Open
```

Página final: <http://127.0.0.1:8803/index.html>.

Run10K necesita su fuente de datos en **8801** y la interfaz final en **8803**. El puerto 8803 sigue dependiendo de 8801; el lanzador respeta ese orden. No necesita iniciar 8800 ni 8802.

## 7. Comprobar cuáles están encendidos

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_simz1_viewers.ps1 -Check
```

`-Check` consulta el estado sin iniciar, detener ni modificar servidores. Comprueba los puertos y sus respuestas HTTP; una identidad incompatible se informa como problema. Un servidor apagado después de reiniciar Windows es normal: use `-Both -Open` para encenderlos.

Puede limitar la consulta:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_simz1_viewers.ps1 -Run1000 -Check
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_simz1_viewers.ps1 -Run10K -Check
```

Si necesita conservar el código de salida en PowerShell, guárdelo inmediatamente después del comando:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_simz1_viewers.ps1 -Check
$viewerExit = $LASTEXITCODE
"Código de salida: $viewerExit"
```

El código `0` indica que las comprobaciones solicitadas fueron satisfactorias. Ante otro código, lea el mensaje antes de continuar.

## 8. Abrir las páginas en Edge

La opción `-Open` ya abre las páginas correctas después de comprobarlas. Si los servidores están disponibles y solo cerró las pestañas, puede usar:

```powershell
Start-Process -FilePath 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe' -ArgumentList 'http://127.0.0.1:8804/index.html','http://127.0.0.1:8803/index.html'
```

También puede pegar las URLs directamente en la barra de direcciones de Edge. Use **8804 para Run1000** y **8803 para Run10K**; los puertos fuente no son las interfaces finales aprobadas.

Para ver tráfico, seleccione una hora como **11:05:25**. El contador **Dibujados** está junto al reloj. Los controles conservan reproducción, pausa, velocidades **1x/120x**, barra temporal, filtros, selección por ID y ocultar/mostrar barra. Transmetro es verde y TuBus azul.

Run1000 conserva el alcance de su adaptador previo de buses; Run10K conserva la representación de todas las familias. Los símbolos son reconstrucciones aproximadas respaldadas por eventos; la geometría local no es cartografía GIS verificada.

## 9. Si aparece ERR_CONNECTION_REFUSED

1. Abra PowerShell y entre a la carpeta con el comando de la sección 3.
2. Ejecute `-Check` como se indica en la sección 7.
3. Ejecute el comando `-Both -Open` de la sección 4.
4. Espere a que el lanzador confirme disponibilidad. Si informa un error, lea el mensaje y los logs de la sección 11.
5. Si ya confirmó disponibilidad, recargue la pestaña de Edge.

`ERR_CONNECTION_REFUSED` indica que no se pudo establecer la conexión con ese puerto. Abrir otra vez la URL no enciende el servidor. Una fuente apagada también impide que la interfaz final entregue los datos; el lanzador comprueba ambas partes.

No ejecute Run, Validate, DryRun ni preparadores de replay para resolver este problema. No necesita repetir la simulación.

## 10. Si un puerto está ocupado

El lanzador reutiliza un servidor compatible. Si detecta otro proceso o una identidad distinta, se detiene con un error y no mata ese proceso.

Primero ejecute `-Check`. Para consultar qué PID escucha en los puertos relevantes:

```powershell
Get-NetTCPConnection -ErrorAction Stop | Where-Object { $_.LocalPort -in 8799,8800,8801,8802,8803,8804 -and $_.RemotePort -eq 0 } | Select-Object LocalAddress,LocalPort,OwningProcess
```

No use `Stop-Process -Name python`, `taskkill /IM python.exe` ni comandos para detener todos los procesos de un nombre. Un puerto ocupado no autoriza detener un proceso desconocido ni cambiar el firewall. Conserve el mensaje de conflicto y los logs para identificarlo.

La consulta anterior incluye sockets reservados o en escucha. En este equipo, filtrar exclusivamente por `-State Listen` ha omitido sockets reales; el lanzador contrasta propietario, puerto y respuesta HTTP.

Si el conflicto corresponde a servidores que este mismo lanzador registró y puede comprobar, ciérrelos mediante `-Stop` como se explica abajo y vuelva a iniciar. Si no puede comprobar su propiedad, el cierre se rechaza: no fuerce la terminación con un PID antiguo.

## 11. Consultar los logs

Los registros están en:

- `runtime\viewers\logs\`: salida normal (`*.stdout.log`) y errores (`*.stderr.log`) de cada arranque.
- `runtime\viewers\services\`: registros de identidad de los servicios, con PID, creación del proceso, comando y rutas de logs.

Mostrar los archivos de log más recientes:

```powershell
Get-ChildItem -LiteralPath .\runtime\viewers\logs -File | Sort-Object LastWriteTime -Descending | Select-Object -First 12 Name,LastWriteTime,Length
```

Leer las últimas 60 líneas del log de errores más reciente:

```powershell
$viewerLog = Get-ChildItem -LiteralPath .\runtime\viewers\logs -Filter '*.stderr.log' -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($viewerLog) { Get-Content -LiteralPath $viewerLog.FullName -Tail 60 }
```

Seguir ese archivo en tiempo real:

```powershell
if ($viewerLog) { Get-Content -LiteralPath $viewerLog.FullName -Tail 20 -Wait }
```

Presione **Ctrl+C** para salir de esa lectura; esto no detiene el visor.

Consultar los cuatro registros exactos para localizar los logs de cada servicio:

```powershell
Get-Content -Encoding UTF8 -LiteralPath .\runtime\viewers\services\run1000-backend.json
Get-Content -Encoding UTF8 -LiteralPath .\runtime\viewers\services\run1000-presentation.json
Get-Content -Encoding UTF8 -LiteralPath .\runtime\viewers\services\run10k-backend.json
Get-Content -Encoding UTF8 -LiteralPath .\runtime\viewers\services\run10k-presentation.json
```

Un registro describe un arranque; por sí solo no prueba que ese PID siga siendo el mismo proceso. Use `-Check` para comprobar el estado actual. El archivo `stderr` también puede contener solicitudes HTTP normales; su existencia no significa que haya ocurrido una excepción.

## 12. Cerrar solamente los servidores de los visores

Cerrar Edge o PowerShell deja los servidores activos. Para cerrarlos expresamente, use el mismo lanzador:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_simz1_viewers.ps1 -Both -Stop
```

Cerrar solo Run1000 y su fuente:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_simz1_viewers.ps1 -Run1000 -Stop
```

Cerrar solo Run10K y su fuente:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_simz1_viewers.ps1 -Run10K -Stop
```

El cierre verifica los procesos registrados antes de detenerlos y cierra primero la interfaz y después su fuente. No usa nombres globales de procesos, no detiene MATSim ni toca procesos desconocidos. Si un registro no corresponde al proceso actual, rechaza la operación.

Si un arranque anterior agotó su tiempo y luego terminó de cargar, repita primero el comando de inicio para reconocer y registrar la instancia disponible; después use `-Stop`. No borre el registro ni fuerce la terminación de un PID antiguo. El cierre no necesita que los replays vuelvan a pasar una verificación completa.

Para volver a abrirlos, repita `-Both -Open`. Después de reiniciar Windows, use el comando único de la sección 2. No hay una tarea de inicio automático ni hace falta mantener Codex abierto.

## Identidades que conserva el lanzador

| Visor | Puerto final | Puerto fuente | LaunchId | RunId | Iteración |
|---|---:|---:|---|---|---:|
| Run1000 | 8804 | 8799 | `a32f15487b1a49ac910ba799175658ca` | `simz1-9d15f07ccc134aa69c60fdcbc887ea3f` | 0 |
| Run10K | 8803 | 8801 | `e496c091b9ef46ee9ca381576135e299` | `simz1-cdffd75c4bdb47a7bfb507efe2c8c4e9` | 0 |

SHA256 del manifiesto Run1000: `3399203616a3884cb17e360d46160cbd43bc006f44eb146e0d08aba1b249a427`.

SHA256 del manifiesto Run10K: `8d51af2202ceb29ec32aa782f18fa05440436c1fb6a879beeb8f11a086e3213f`.

El arranque de solo lectura comprueba la identidad de los resultados y el contrato del replay. Los lanzadores históricos y sus guardas de huella global permanecen intactos. No se editan manifiestos, recibos ni eventos para aprobar un arranque.

## Evidencia de esta recuperación

Recuperación terminada el **9 de noviembre de 2026, Guatemala**. Ambos visores quedan activos. Los PIDs de esta tabla corresponden al cierre de la prueba; cambiarán después de otro arranque. Use `-Check` para consultar los actuales.

| Servicio | Puerto | PID final | Logs de esta sesión |
|---|---:|---:|---|
| Fuente Run1000 | 8799 | 52388 | [stdout](../runtime/viewers/logs/run1000-backend-20261109T183002776Z-6087773d.stdout.log) · [stderr](../runtime/viewers/logs/run1000-backend-20261109T183002776Z-6087773d.stderr.log) |
| Run1000 final | 8804 | 19948 | [stdout](../runtime/viewers/logs/run1000-presentation-20261109T183233930Z-245bb3c3.stdout.log) · [stderr](../runtime/viewers/logs/run1000-presentation-20261109T183233930Z-245bb3c3.stderr.log) |
| Fuente Run10K | 8801 | 228 | [stdout](../runtime/viewers/logs/run10k-backend-20261109T183237672Z-9992d3e1.stdout.log) · [stderr](../runtime/viewers/logs/run10k-backend-20261109T183237672Z-9992d3e1.stderr.log) |
| Run10K final | 8803 | 24684 | [stdout](../runtime/viewers/logs/run10k-presentation-20261109T183559420Z-c4864dda.stdout.log) · [stderr](../runtime/viewers/logs/run10k-presentation-20261109T183559420Z-c4864dda.stderr.log) |

Se comprobaron HTTP, RunId, LaunchId, iteración 0, los SHA256 de ambos manifiestos y el HTML exacto de las interfaces aprobadas. La prueba completa en **Chrome real, WebGL2/ANGLE Intel UHD D3D11** pasó **113/113 comprobaciones**, y la apertura posterior al reinicio de servidores pasó **45/45**, sin excepciones JavaScript. Los mapas y vehículos son visibles; a las 11:05:25 se dibujan 97 en Run1000 y 218 en Run10K. Pasaron reproducción 1x/120x, contador, selección Transmetro/TuBus y carro/motocicleta Run10K, filtros y ocultar/restaurar barra. Se conservaron los colores y la interfaz limpia.

Se cerró y reabrió Chrome conservando los cuatro servidores. También se ejecutó `-Both -Stop`, se comprobó que solo cerró los visores y sus lectores, y se iniciaron nuevamente con `-Both`. Los comandos conjuntos, individuales y `-Check` fueron comprobados; repetirlos no cambió los PIDs. La consola auxiliar de captura se cerró y los servidores continuaron respondiendo. Windows no se reinició durante estas pruebas.

La apertura de una ventana visible de Edge desde el agente fue rechazada por la revisión automática (`blocked by policy`), y el acceso interactivo al navegador estaba indisponible. Por eso **no se afirma haber probado aquí la apertura visible de `-Open`**: las pruebas gráficas se hicieron en Chrome real sin ventana, con capturas inspeccionadas. `-Open` está preparado para abrir Edge desde su PowerShell, después de comprobar los servicios.

La causa inmediata de `ERR_CONNECTION_REFUSED` era la ausencia de los procesos de los visores. Los últimos logs históricos terminaban en HTTP 200 y no demostraban por qué finalizaron. Además, los lanzadores antiguos exigían una huella global histórica diferente de la actual; el nuevo contrato de publicación de solo lectura comprueba los resultados existentes y deja intactas esas guardas. No se repitió ninguna simulación, Validate o DryRun, ni se reconstruyeron SQLite o replay. Los 751 archivos nativos/replay conservaron tamaño y fecha de modificación; los manifiestos mantuvieron sus hashes exactos.

Evidencia detallada: [estado final y procesos](../runtime/diagnostics/viewers-startup-20261109/final-status.json), [113 pruebas gráficas](../runtime/diagnostics/viewers-startup-20261109/browser/verification-1/browser-results.json) y [45 pruebas tras reinicio](../runtime/diagnostics/viewers-startup-20261109/browser/after-restart/browser-results.json).
