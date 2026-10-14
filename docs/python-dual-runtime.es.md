# Contrato de Python 3.14 / 3.15 en paralelo

Estado: **candidato en PR #273; no está fusionado ni desplegado**. Issue responsable: [#270](https://github.com/eXPerience83/remote-dev-containers/issues/270). La ampliación de herramientas universales sigue separada en [#121 PR2](https://github.com/eXPerience83/remote-dev-containers/issues/121); el problema anterior de actualizaciones de Python #257 se corrigió en PR #271. Este documento describe el comportamiento candidato y los requisitos de aceptación, no que TrueNAS ya lo esté ejecutando.

## Versiones y selección

- `PYTHON_VERSION=3.14.8` sigue siendo el Python predeterminado de `python`/`python3` fuera de proyectos con otra selección, y el intérprete administrativo inmutable. Se mantiene dentro de la rama 3.14.x revisada.
- `PYTHON_315_VERSION=3.15.0` se distribuye en paralelo y solo se selecciona expresamente desde un proyecto compatible. Sus parches se actualizan dentro de 3.15.x. Nunca se migra silenciosamente a otra rama menor.
- El `mise.toml` del sistema declara `python = ["3.14.8", "3.15.0"]` en ese orden. Prevalece el `mise.toml` del repositorio; la configuración ejecutable exige confianza explícita mediante `mise trust`. Una versión no instalada falla sin descarga automática ni sustitución por la otra rama.
- No se introducen parámetros de arranque adicionales, activación automática de venv, descargas pasivas, modificaciones de `/opt/remote-dev/mise`, estado compartido entre agentes, socket Docker ni cambios en el root de solo lectura o el `noexec` de `/tmp`.

Para un proyecto revisado y compatible con Python 3.15:

```toml
[tools]
python = "3.15.0"
```

Tras aprobar expresamente la configuración del proyecto si requiere confianza, comprueba `python --version`, `python3 --version` y `mise which python`. Para crear un entorno virtual aislado con el intérprete **ya instalado** que selecciona el proyecto:

```bash
UV_PYTHON_DOWNLOADS=never uv venv --offline --python "$(mise which python)" .venv
.venv/bin/python -c 'import sys; print(sys.version)'
```

`uv venv` no activa el entorno ni instala dependencias en el Python de la imagen. Las dependencias reales se gestionan según el lock y las normas de cada repositorio.

## Procedencia y mantenimiento

- Ambos intérpretes proceden de entradas `core:python` de `mise.lock` revisadas, con URL, SHA-256 y procedencia exactas para `linux-x64` y `linux-arm64`.
- Una Action temporal de **solo lectura** regeneró el lock con el binario `mise` verificado por hash. El resultado coincidió **byte a byte** con el lock del PR; la Action temporal se eliminó. El procedimiento reproducible permanente es `scripts/regenerate-mise-lock.sh`.
- La licencia de Python 3.15 y sus metadatos legales completos están separados en `third_party/components/python-315/` y `third_party/components/python-build-standalone-315/`; se conserva por separado la evidencia de 3.14. Ambas pasan por las verificaciones de inventario y avisos.
- `.github/workflows/check-upstream.yml` busca y comprueba los parches de 3.14 y 3.15 independientemente mediante la política fail-closed de #257; un artefacto que todavía no esté publicado no debe actualizar silenciosamente esa rama ni impedir otras actualizaciones seguras.

## Pruebas de regresión y aceptación

La Action `Build AMD64` ejecuta `scripts/build-local.sh` y estos controles:

| Contrato | Prueba |
| --- | --- |
| Ambos Python exactos y 3.14 predeterminado | `scripts/smoke-test.sh` |
| Selección 3.14/3.15 por proyecto en **Codex y Antigravity** | `scripts/test-mise-project-resolution.sh` |
| Dos venv `uv` sin red: versión exacta, paquetes aislados y Python global intacto | `scripts/test-mise-project-resolution.sh` (añadida a este PR; exige CI verde del último commit) |
| Versión ausente, proyecto no confiable, sin instalación/fallback y almacén inmutable | `scripts/test-mise-project-resolution.sh` |
| Separación de estados y montajes, credenciales, launcher y rootfs | `scripts/test-cross-service-isolation.sh` |
| Lock: arquitecturas, backend, artefactos, procedencia y regeneración segura | `scripts/test-validate-mise-lock.py` y `scripts/test-regenerate-mise-lock.sh` |
| Retrasos de propagación y errores inesperados | `scripts/test_preflight_python_upstream.py` |
| Licencias y vulnerabilidades | `scripts/validate-third-party-inventory.sh`, `remote-dev-notices --check`, SBOM SPDX, Trivy y bloqueo de críticos corregibles |

CI demuestra ejecución AMD64 y metadatos de lock completos para AMD64/ARM64; **no** implica soporte de ejecución ARM64 (issue #112) ni sesiones reales autenticadas con los agentes. Antes de implantarlo sigue siendo necesaria la validación manual de TrueNAS: interfaz de ambos agentes, historial, selección de intérpretes y seguridad de contenedores.

## Tamaño y decisión de publicación

Añadir el segundo intérprete tiene coste. Con los mismos pins de componentes, el build verde de `main` `b42f9c2` ([38548947867](https://github.com/eXPerience83/remote-dev-containers/actions/runs/38548947867)) ocupa **1.547.987.128 bytes** sin comprimir. El candidato `bba44c0` ([38633948930](https://github.com/eXPerience83/remote-dev-containers/actions/runs/38633948930)) ocupa **1.655.339.677 bytes**. Incremento: **107.352.549 bytes / 102.38 MiB**. La imagen base aumenta 107.351.674 bytes. Supera el umbral **blando** de revisión de 50 MiB de #121: disponer siempre del segundo Python es una decisión explícita de funcionalidad frente a tamaño. No afirmamos conocer el incremento exacto de descarga comprimida.

## Pendiente antes de aceptar

- CI verde del último commit con el nuevo test de venv, revisión de CodeRabbit y resolución de sus observaciones.
- Coordinar [PR #272](https://github.com/eXPerience83/remote-dev-containers/pull/272), relativo a actualizaciones upstream, y repetir la CI tras cualquier fusión/rebase. No sobrescribir pins desde PR no relacionado.
- Revisar expresamente la excepción de +102.38 MiB, registrar las evidencias en #270/PR #273 y fusionar manualmente solo si todos los controles del commit final pasan.
- Mantener PR2 del #121 (Ruff, pytest, pre-commit, yq, shfmt y actionlint) y PR3 (demanda real de herramientas) como cambios independientes.
