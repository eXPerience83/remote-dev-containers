# Admisión de Antigravity en tiempo de ejecución

## Estado y alcance

Antigravity CLI es un producto opcional de Google. Remote Dev no incluye, copia ni redistribuye su instalador ni su ejecutable. La instalación y la actualización son acciones expresas del usuario dentro del servicio aislado de Antigravity.

El servicio debe ejecutarse con `REMOTE_DEV_ROLE=antigravity` y la activación expresa `REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY=1`. El rol Antigravity permanece no disponible mientras esa puerta experimental esté desactivada. La integración continúa siendo deliberadamente experimental conforme a la decisión actual de política del proveedor registrada en #53/#96: Remote Dev actúa como launcher/wrapper no afiliado del CLI oficial `agy`, no como cliente alternativo de Antigravity ni como relay de OAuth hacia otro agente.

Este documento define el modelo de disponibilidad e integridad implementado en el issue #96 y la automatización consultiva de revisión implementada en el issue #83. La sincronización general del estado de la documentación continúa en el issue #92.

## Modelo de disponibilidad

Una versión compatible de Antigravity puede instalarse o actualizarse desde el endpoint oficial fijo de Google sin esperar a una imagen nueva de Remote Dev. La evidencia incluida en la imagen describe la versión exacta que Remote Dev ya ha revisado; no es una lista de versiones permitidas y la ausencia de una versión no equivale a revocarla.

El arranque normal del contenedor, las comprobaciones de estado, la verificación completa y el inicio del agente nunca contactan con el instalador ni actualizan el ejecutable. Los comandos informativos `status` y `status --menu` validan la estructura del ejecutable/manifiesto y el estado de revisión sin calcular el hash del ejecutable completo ni ejecutar código del proveedor. Justo antes de una sesión real, Remote Dev realiza una única verificación SHA-256 completa del ejecutable canónico contra su manifiesto privado. `remote-dev-antigravity verify` realiza expresamente la misma comprobación completa sin red y Ejecutar diagnósticos la invoca antes de mostrar el estado ligero. `AGY_CLI_DISABLE_AUTO_UPDATE=true` continúa siendo obligatorio durante las sesiones normales.

## Instalación y actualización expresas

El gestor:

1. muestra el aviso de términos, privacidad y no afiliación de Google;
2. descarga únicamente desde `https://antigravity.google/cli/install.sh` mediante HTTPS, ignora la configuración ambiental de curl y rechaza redirecciones fuera del origen de Google revisado;
3. limita el tamaño del instalador y del payload y guarda los bytes de red en staging privado, sin canalizarlos directamente a una shell;
4. valida archivo regular, sintaxis Bash y el contrato obligatorio `--dir <path>`;
5. ejecuta el instalador con entorno vacío, HOME aislado, destino controlado, límites de tiempo/salida y autoactualización desactivada;
6. cuando el contenedor de producción se ejecuta como root, baja al usuario sin privilegios `nobody` para ejecutar el instalador y validar el candidato;
7. valida tipo de archivo, propietario, formato ELF Linux AMD64, tamaño, versión semántica, ayuda acotada y estabilidad del ejecutable durante la comprobación;
8. crea un manifiesto privado `0600` con origen, URL fija/final, hash y tamaño del instalador, hash y tamaño del binario, versión y fecha;
9. publica ejecutable y manifiesto solo tras superar todos los controles y restaura la pareja anterior si la actualización falla o se interrumpe.

Un cambio incompatible del contrato del proveedor se rechaza. El gestor no rebaja automáticamente las validaciones para recuperar disponibilidad.

## Estados del runtime

El menú y los diagnósticos muestran únicamente información acotada y no secreta. El estado del menú es informativo; antes de ejecutar sigue siendo obligatoria una verificación completa correcta:

- **Oficial y revisada**: el manifiesto privado estructuralmente válido coincide con la evidencia de inspección incluida por Remote Dev. La integridad completa del ejecutable se comprueba antes del inicio y mediante la verificación expresa/los diagnósticos.
- **Origen oficial; revisión de Remote Dev pendiente**: el manifiesto privado estructuralmente válido registra un payload admitido mediante el flujo expreso desde el origen oficial, pero el instalador/payload exacto aún no aparece en la evidencia de la imagen. Solo puede ejecutarse si supera la verificación completa obligatoria previa al inicio.
- **Dañada o modificada localmente**: falta el ejecutable o el manifiesto, es un enlace simbólico, tiene permisos inválidos, está mal formado o no coincide su identidad. El inicio se bloquea hasta realizar una actualización expresa.

«Origen oficial; revisión pendiente» describe la ruta controlada de descarga y la integridad local respecto al manifiesto. No significa firma criptográfica de Google, certificación de Remote Dev, inclusión en el SBOM de la imagen ni cobertura por Apache-2.0.

## Sustitución y rollback de la imagen

Una versión instalada e íntegra sigue funcionando cuando una imagen de Remote Dev más nueva o anterior contiene otra evidencia de revisión. El cambio de imagen solo puede cambiar el estado mostrado; no invalida ni sustituye el ejecutable persistente.

Una actualización expresa correcta sustituye el ejecutable persistente. Un fallo de descarga, contrato, validación o publicación conserva utilizables el ejecutable y el manifiesto anteriores. El mismo comando de actualización expresa repara el estado parcial cuando falta el ejecutable o el manifiesto; la instalación inicial se niega a sobrescribir silenciosamente esos restos dañados.

## Límite de confianza

El manifiesto privado detecta modificaciones independientes del ejecutable o del propio manifiesto y corrupción accidental. No protege frente a un atacante o proceso que ya controle el usuario del servicio Antigravity o el root del contenedor y pueda sustituir coherentemente ambos archivos. Esta limitación coincide con el modelo de confianza monousuario y de contenedor exterior del proyecto.

El instalador descargado continúa siendo código del proveedor. Ejecutarlo con un usuario sin privilegios, un entorno vacío y un staging privado reduce su exposición a credenciales montadas, pero no lo convierte en un programa sandboxeado ni auditado de forma independiente.

## Automatización programada de la revisión

`.github/workflows/check-upstream.yml` ejecuta la revisión compartida de upstream **cada día a las 05:17 UTC** y también permite ejecución manual. El descubrimiento de Antigravity se realiza en un job separado `antigravity-detect` con `contents: read`, sin credenciales persistidas por checkout y sin capacidad de escritura en el repositorio.

Ese job descarga bytes acotados del instalador desde la URL canónica exacta `https://antigravity.google/cli/install.sh`, JSON acotado desde el endpoint fijo revisado del manifest Linux AMD64 y el archivo del payload acotado al que apunta ese manifest. Cada URL inicial, destino de redirección y URL final se comprueba contra una política HTTPS estrecha antes de permitir la petición; además se desactivan los proxies ambientales. El manifest debe conservar exactamente el esquema revisado `version`/`url`/`sha512` y la URL del archivo debe permanecer dentro de la ruta revisada de Google Storage.

Todos esos bytes del proveedor se tratan estrictamente como **datos**. El instalador se comprueba por hash y solo se inspeccionan los marcadores estáticos del contrato revisado; no se ejecuta. El SHA-512 del archivo se valida contra el manifest y después se lee en streaming el único miembro regular `antigravity` del tar para calcular el SHA-256 de `agy`. El archivo no se extrae y ni `install.sh` ni `agy` se ejecutan durante el descubrimiento programado. Enlaces, dispositivos, archivos regulares inesperados, manifests mal formados, redirecciones inseguras y excesos de tamaño provocan fallo cerrado.

Los artefactos subidos contienen únicamente esquemas de metadatos normalizados y fijos para la detección del instalador y el descubrimiento estático del payload: URL de origen/final, tamaños/content types acotados, hashes, identidad del instalador revisado, versión del manifest/integridad del archivo y ruta/tamaño/SHA-256 del payload descubierto. No se conservan contenido crudo del instalador/manifest/archive, stdout/stderr, datos OAuth/de cuenta ni binarios propietarios. Los metadatos se validan contra esquema antes de subirlos y vuelven a validarse al entrar en el job separado con permisos de escritura que mantiene la PR.

El escritor integra el estado de Antigravity en la misma rama/PR `automation/update-upstreams` que utiliza el actualizador agrupado. Una reejecución programada parte de `main` actual y solo puede conservar evidencia de descubrimiento o revisión completa que siga correspondiendo a la pareja instalador/payload detectada y preserve los campos de política legal/runtime propiedad de la revisión humana. El descubrimiento estático reciente sustituye propuestas de candidato/revisión completa obsoletas. La ruta del candidato se añade al índice antes de decidir «no hay cambios», de modo que un archivo nuevo todavía untracked no puede perderse. La automatización nunca hace auto-merge.

## Una única admisión expresa para ejecutar

El descubrimiento programado puede identificar un instalador cambiado y/o un `agy` cambiado sin ejecutar ninguno. El código del proveedor solo puede ejecutarse mediante una ejecución manual de `.github/workflows/review-antigravity-candidate.yml` desde `main`, después de que un mantenedor revise la PR de automatización e introduzca **los dos** SHA-256 exactos en minúsculas: el hash del instalador descubierto estáticamente y el hash de `agy` descubierto estáticamente.

El job de ejecución, sin credenciales y de solo lectura, descarga primero el instalador mediante la misma política estricta de URL/redirecciones/proxies desactivados y lo rechaza salvo que su SHA-256 coincida exactamente con el hash autorizado. Solo después de superar ese prefetch se entrega el archivo local ya verificado al inspector acotado. El inspector vuelve a verificar el hash del instalador, ejecuta el instalador admitido dentro de un HOME temporal aislado, verifica que el `agy` resultante coincide exactamente con el SHA-256 del payload autorizado **antes de invocarlo** y solo entonces ejecuta `agy --version`/`--help` de forma acotada junto con los controles de compatibilidad existentes.

El job que ejecuta bytes del proveedor tiene únicamente `contents: read`; no puede escribir en repositorio, issues ni pull requests. Solo sube metadatos normalizados validados contra esquema. Un job escritor separado descarga esos metadatos, vuelve a validarlos, confirma que los hashes suministrados coinciden con el candidato estático pendiente y solo entonces propone la evidencia revisada actualizada en la rama de automatización. Los bytes del instalador, archives, bytes de `agy` y stdout/stderr crudos del proveedor nunca se suben como artefactos de revisión ni se incluyen en commits.

Una inspección completa correcta actualiza `third_party/antigravity-cli-inspection.json`, el bloque actual generado de `third_party/antigravity-cli-inspection.md`, elimina el candidato estático ya sustituido y reinicia `third_party/antigravity-cli-detection.json` con la identidad del instalador recién revisado. Antes de fusionar sigue siendo necesaria la revisión humana de compatibilidad y del límite vigente de términos/privacidad de Google.

## La automatización de revisión no es la admisión del runtime

La detección programada, una PR pendiente, una inspección fallida o la ausencia de una versión en la evidencia incluida nunca revocan un runtime local íntegro y ya admitido. La disponibilidad continúa gobernada por el contrato de instalación expresa, manifiesto privado e integridad de #153 descrito arriba. Una versión/hash concretamente insegura exigiría una decisión expresa de revocación del proyecto; no se deduce simplemente del estado «revisión pendiente».
