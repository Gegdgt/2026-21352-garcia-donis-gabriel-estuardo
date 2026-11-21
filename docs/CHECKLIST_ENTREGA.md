# Checklist de entrega UVG 2026

## Preparación realizada

- [x] Fork local correcto: `Gegdgt/2026-21352-garcia-donis-gabriel-estuardo`, rama `main`.
- [x] `src/` conserva Maven, Java, Python, scripts, entradas, recursos y pruebas.
- [x] README en español con comandos reales y límites de reproducción.
- [x] `.gitignore`, preservación de bytes y carpetas manuales preparadas.
- [x] Extractor con vista previa, SHA-256, protección del origen y repetición sin duplicar.
- [x] Inventarios incluidos/excluidos y dependencias documentadas.
- [x] Compilación limpia Java 17 y verificación de bytecode aprobadas.
- [x] Demanda de diez agentes preparada sin ejecutar MATSim/QSim.
- [x] Pruebas focales documentadas: 46 Python aprobadas, una discrepancia histórica conservada; tres suites JavaScript aprobadas.
- [x] Sin commit, push ni Pull Request de la entrega.

## Únicos materiales que agrega el autor

- [ ] **A. Capturas:** copiar al menos diez capturas reales a [capturas/](../capturas/).
- [ ] **B. Video:** copiar el demostrativo a [demo/demo.mp4](../demo/demo.mp4).
- [ ] **C. Tesis:** copiar la versión definitiva a [docs/informe_final.pdf](informe_final.pdf).
- [ ] **D. Consentimiento:** copiar el documento firmado a [docs/consentimiento_firmado.pdf](consentimiento_firmado.pdf).

Los `.gitkeep` de capturas y demo pueden permanecer; no interfieren con los materiales. Al añadirlos, actualizar sus estados en la tabla del README. No se necesitan capturas inventadas ni archivos de muestra.

## Revisión antes de publicar

Leer el [resultado de verificación](VERIFICACION.md), en particular la prueba histórica fallida y la ausencia de replays aceptados. Comprobar que las capturas y el video corresponden al software real, abrir ambos PDF y revisar los tamaños de los materiales que se incorporan. Los medios todavía ausentes no pudieron revisarse.

Desde la raíz UVG:

```powershell
git remote -v
git branch --show-current
git status --short
git diff -- README.md
Import-Csv .\docs\extraccion\inventario_incluidos.csv | Measure-Object
Get-Content .\docs\VERIFICACION.md
Get-ChildItem .\capturas -File
Get-Item .\demo\demo.mp4, .\docs\informe_final.pdf, .\docs\consentimiento_firmado.pdf
```

La extracción no es necesaria para publicar esta copia. Si se desea contrastar nuevamente con el origen todavía disponible, ejecutar únicamente la vista previa:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\preparar_entrega_simz1.ps1
```

## Commit y push, solamente cuando el autor los autorice

**Estos comandos se dejan preparados; no fueron ejecutados.** Revisar el contenido staged antes de confirmar. No se usa `--force` ni se crea otro repositorio.

```powershell
git add -- README.md .gitignore .gitattributes preparar_entrega_simz1.ps1 capturas demo docs src
git diff --cached --stat
git diff --cached --check
git status --short

# Despues de revisar y autorizar el commit:
git commit -m 'Preparar entrega UVG 2026 de SimZ1'

# Despues de autorizar la publicacion en el fork personal:
git push origin main
```

El remoto de destino debe seguir siendo `https://github.com/Gegdgt/2026-21352-garcia-donis-gabriel-estuardo`. Un eventual Pull Request hacia GraduacionesUVG requiere una instrucción posterior; no forma parte de esta preparación.
