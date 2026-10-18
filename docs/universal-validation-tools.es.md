# Herramientas de validación local PR2 (#121)

El candidato añade exactamente seis comandos a PR1 (47 → 53): Ruff **0.17.1**, pytest **9.1.1**, pre-commit **4.7.0**, yq de Mike Farah **4.54.1**, shfmt **3.14.1** y actionlint **1.7.12**. Las versiones estables y sus artefactos oficiales se consultaron de nuevo el 18/10/2026. La aceptación sigue pendiente; no implica una versión estable ni soporte ARM64.

## Instalación y precedencia del proyecto

Las tres CLI Python usan identidades explícitas `pypi:` y `python = "3.14.8"` en mise. El formato 3 de `mise.lock` referencia por SHA-256 los grafos nativos uv de `.mise/locks`, con versiones transitivas exactas, marcadores y hashes de ruedas oficiales PyPI. La instalación congelada, sin compilar distribuciones fuente, crea entornos CLI separados e inmutables. No añade paquetes al site-packages de Python 3.14 ni 3.15. Estas CLI no proporcionan dependencias ni plugins del proyecto: para su validación final prevalece el entorno declarado, por ejemplo `.venv/bin/python -m pytest`. Una versión solicitada ausente debe fallar sin instalación automática ni fallback. No se activa `.venv` automáticamente.

Los comandos nativos conservan identidades cortas mise y los backends revisados `aqua:mikefarah/yq`, `aqua:mvdan/sh` y `aqua:rhysd/actionlint`. El lock generado registra cosign para yq y attestations GitHub para actionlint, verificadas al generarlo con `locked_verify_provenance=true`. shfmt tiene checksums oficiales, sin atribuirle procedencia criptográfica adicional. Se bloquean artefactos Linux AMD64 y ARM64. No se incorpora otra implementación de yq, pyflakes, shims Corepack ni herramientas adicionales.

Arranque, health checks y Doctor no instalan ni descargan herramientas. Base Verify usa `/`; Doctor consume el inventario común para roles de desarrollo y exime al launcher. Las reglas globales existentes informan a ambos agentes de disponibilidad y precedencia. Se conservan raíz de solo lectura, `/tmp noexec`, `$TMPDIR` ejecutable y privado y `PRE_COMMIT_HOME` separado por rol. Una ejecución explícita de pre-commit puede descargar hooks configurados por el proyecto; la prueba sin red usa únicamente un hook local `language: system`.

## Mantenimiento y licencias

`scripts/regenerate-mise-lock.sh` exige el mise fijado y uv exacto (`UV_BIN`), aísla estado y valida los grafos antes de publicar el lock. Conserva directorios anteriores para no romper el lock previo ante un fallo. Los grafos acompañan a ambos nombres del lock dentro de la imagen. El actualizador upstream mantiene las seis líneas estables, el resolver verificado, grafos, inventario y licencias mediante una PR revisada sin fusión automática.

`scripts/sync-python-cli-notices.py --write` descarga ruedas oficiales verificadas con los hashes comprometidos y conserva sus licencias/notices reales, incluidas las ruedas de semillas redistribuidas en virtualenv. La comprobación sin red vincula evidencia y artefactos. El inventario incluye conservadoramente todos los paquetes del grafo, incluido colorama condicional, sin afirmar que todos se instalen en Linux. Siguen siendo obligatorios SPDX, Trivy y el bloqueo de CRITICAL corregibles. La evidencia complementa las limitaciones de detección del escáner; la revisión humana #53 sigue pendiente.

## Validación y evidencias

`test-validation-tools.sh` prueba los seis comandos sin red en contenedores de solo lectura y sin capacidades, para fixtures Codex y Antigravity, desde CWD neutro y proyecto Python 3.15. Comprueba lint/formato Ruff, tests pytest reales y su intérprete aislado 3.14, hooks locales pre-commit, transformación yq, formato shfmt, workflows válidos/inválidos, site-packages globales limpios, venv explícito del proyecto y estabilidad del almacén inmutable. Las pruebas mise añaden ausencia de versión y ausencia de fallback para yq. Los fixtures prueban el entorno de procesos; no sustituyen tareas de modelos autenticados ni aceptación externa en TrueNAS.

La generación local con mise y uv fijados ha terminado para ambas arquitecturas. Pasan también las pruebas funcionales de los payloads en entornos uv privados y congelados; ambos Python globales permanecen limpios. La reproducción local con estado de instalación heredado devolvió `No lockfile URL found for python@3.14.8`; **la instalación bloqueada de Docker limpio y todas las pruebas de imagen/runtime pasaron después en CI para `6108761`**, incluidos ambos roles endurecidos y la selección de proyecto Python 3.15. El fixture local no demuestra un defecto de mise en una imagen limpia. No se desactivó ninguna garantía de bloqueo o aislamiento.

La sesión carece de Docker CLI/backend. La ejecución endurecida, tamaños exactos antes/después, SPDX y Trivy deben verificarse en GitHub CI; no se atribuyen resultados locales inexistentes. Sigue pendiente revisar el umbral orientativo de 50 MiB sin comprimir. No se modifica TrueNAS, no se publica una versión estable y no se fusiona esta PR.

Los bytes de licencias se agrupan por paquete en `NOTICES.txt` con nombres exactos de rueda/miembro, para facilitar la revisión sin excluir evidencia. La inspección standalone incluye los seis artefactos Aqua nuevos AMD64/ARM64 y conserva la evidencia previa.
