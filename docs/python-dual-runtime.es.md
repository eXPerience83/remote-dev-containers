# Contrato de Python 3.14 / 3.15 en paralelo

Estado: **PR #273 fusionada en main y distribuida en edge**. Issue [#270](https://github.com/eXPerience83/remote-dev-containers/issues/270), cerrado tras la aceptación de su excepción de tamaño y la CI. La ampliación universal [PR2 #281](https://github.com/eXPerience83/remote-dev-containers/pull/281) también está integrada y publicada como edge desde el 18/10/2026, pero su aceptación operativa en TrueNAS sigue pendiente. El incidente de actualizaciones #257 se corrigió en PR #271. Esta guía describe el contrato implementado; no confunde CI con sesiones reales de agentes.

## Versiones y selección

Los parches exactos siguientes corresponden a la PR #294 revisada (28/10/2026). Para revisiones posteriores, las fuentes autorizadas son `versions.env`, `mise.toml` y `mise.lock`; los ejemplos pueden quedar desactualizados después de futuras PR de mantenimiento.

- `PYTHON_VERSION=3.14.10` sigue siendo el Python predeterminado de `python`/`python3` fuera de proyectos con otra selección, y el intérprete administrativo inmutable. Se mantiene dentro de la rama 3.14.x revisada.
- `PYTHON_315_VERSION=3.15.2` se distribuye en paralelo y solo se selecciona expresamente desde un proyecto compatible. Sus parches se actualizan dentro de 3.15.x. Nunca se migra silenciosamente a otra rama menor.
- El `mise.toml` del sistema declara `python = ["3.14.10", "3.15.2"]` en ese orden. Prevalece el `mise.toml` del repositorio; la configuración ejecutable exige confianza explícita mediante `mise trust`. Una versión no instalada falla sin descarga automática ni sustitución por la otra rama.
- No se introducen parámetros de arranque adicionales, activación automática de venv, descargas pasivas, modificaciones de `/opt/remote-dev/mise`, estado compartido entre agentes, socket Docker ni cambios en el root de solo lectura o el `noexec` de `/tmp`.

Para un proyecto revisado y compatible con Python 3.15:

```toml
[tools]
python = "3.15.2"
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

## Recuperación del actualizador de octubre de 2026 (PR #291–#294)

La [PR #294](https://github.com/eXPerience83/remote-dev-containers/pull/294) actualizó los pines revisados de `main` a Python 3.14.10 y 3.15.2 sin cambiar el contrato: 3.14 es predeterminado y 3.15 solo se selecciona explícitamente por proyecto. Las correcciones [#291](https://github.com/eXPerience83/remote-dev-containers/pull/291), [#292](https://github.com/eXPerience83/remote-dev-containers/pull/292) y [#293](https://github.com/eXPerience83/remote-dev-containers/pull/293) resolvieron tres obstáculos distintos de la propuesta automática:

- Antes de regenerar el lock completo, se instala el **Python 3.14 exacto** mediante un lock de arranque validado y un entorno mise aislado. Los grafos nativos de uv se resuelven con ese intérprete disponible, sin depender del estado heredado ni permitir descargas implícitas de Python.
- Si la release GitHub de `ruff`, `pytest` o `pre-commit` tiene alguna distribución PyPI no retirada con menos de 24 horas, se **aplaza únicamente esa herramienta**, respetando el filtro habitual de mise/uv. Las demás actualizaciones continúan. No existe un bypass automático para hotfixes urgentes.
- La prueba de los dos Python usa los pines reales del fichero que valida, incluso después de actualizarlo. Los avisos legales de las ruedas Python se regeneran **antes** de las comprobaciones estrictas de versiones e integridad.

Consulta [automatización de dependencias](dependency-automation.md) y [mantenimiento de locks](runtime-locks.md). La CI prueba AMD64 y los metadatos de lock AMD64/ARM64, no soporte runtime ARM64 ni aceptación práctica en TrueNAS.

## Pruebas de regresión y aceptación

La Action `Build AMD64` ejecuta `scripts/build-local.sh` y estos controles:

| Contrato | Prueba |
| --- | --- |
| Ambos Python exactos y 3.14 predeterminado | `scripts/smoke-test.sh` |
| Selección 3.14/3.15 por proyecto en **Codex y Antigravity** | `scripts/test-mise-project-resolution.sh` |
| Dos venv `uv` sin red: versión exacta, paquetes aislados y Python global intacto | `scripts/test-mise-project-resolution.sh` (integrada; CI de la PR superada) |
| Versión ausente, proyecto no confiable, sin instalación/fallback y almacén inmutable | `scripts/test-mise-project-resolution.sh` |
| Separación de estados y montajes, credenciales, launcher y rootfs | `scripts/test-cross-service-isolation.sh` |
| Lock: arquitecturas, backend, artefactos, procedencia y regeneración segura | `scripts/test-validate-mise-lock.py` y `scripts/test-regenerate-mise-lock.sh` |
| Retrasos de propagación y errores inesperados | `scripts/test_preflight_python_upstream.py` |
| Licencias y vulnerabilidades | `scripts/validate-third-party-inventory.sh`, `remote-dev-notices --check`, SBOM SPDX, Trivy y bloqueo de críticos corregibles |

CI demuestra ejecución AMD64 y metadatos de lock completos para AMD64/ARM64; **no** implica soporte de ejecución ARM64 (issue #112) ni sesiones reales autenticadas con los agentes. La aceptación operativa de cada nueva imagen sigue requiriendo comprobar en TrueNAS las interfaces de los agentes, sus historiales, la selección de intérprete y los límites del contenedor; la integración PR2 se valida por separado en #121.

## Tamaño y decisión de publicación

Añadir el segundo intérprete tiene coste. Con los mismos pins de componentes, el build verde de `main` `b42f9c2` ([38548947867](https://github.com/eXPerience83/remote-dev-containers/actions/runs/38548947867)) ocupa **1.547.987.128 bytes** sin comprimir. El candidato `bba44c0` ([38633948930](https://github.com/eXPerience83/remote-dev-containers/actions/runs/38633948930)) ocupa **1.655.339.677 bytes**. Incremento: **107.352.549 bytes / 102.38 MiB**. La imagen base aumenta 107.351.674 bytes. Supera el umbral **blando** de revisión de 50 MiB de #121: disponer siempre del segundo Python es una decisión explícita de funcionalidad frente a tamaño. No afirmamos conocer el incremento exacto de descarga comprimida.

## Decisiones y seguimiento

- PR #273 está fusionada, con CI de su revisión final validada y excepción de **+102,38 MiB** sin comprimir aceptada explícitamente por el propietario el 17/10/2026. No se interpreta como incremento de descarga comprimida.
- PR2 #281, con las seis herramientas universales, se fusionó y publicó en edge el 18/10/2026. La aceptación de esa imagen en el TrueNAS real sigue pendiente en [#121](https://github.com/eXPerience83/remote-dev-containers/issues/121).
- El estudio PR3 y los toolchains bajo demanda de #180 siguen siendo trabajo independiente. No introducir parámetros de arranque ni instalaciones pasivas para suplirlos.
