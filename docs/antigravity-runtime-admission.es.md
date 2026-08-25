# Admisión de Antigravity en tiempo de ejecución

## Estado y alcance

Antigravity CLI es un producto opcional de Google. Remote Dev no incluye, copia ni redistribuye su instalador ni su ejecutable. La instalación y la actualización son acciones expresas del usuario dentro del servicio aislado de Antigravity.

El servicio debe ejecutarse con `REMOTE_DEV_ROLE=antigravity` y la activación expresa `REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY=1`. El rol Antigravity permanece no disponible mientras esa puerta experimental esté desactivada. Activarla no convierte Antigravity en un componente estable ni plenamente soportado de Remote Dev; la integración actual en edge continúa siendo experimental hasta completar las validaciones reales documentadas.

Este documento define el modelo de disponibilidad e integridad implementado en el issue #96. La detección programada y la renovación de evidencias siguen separadas en el issue #83. La sincronización general del estado de la documentación continúa en el issue #92.

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

## Automatización de la revisión

El issue #83 podrá detectar cambios del instalador o paquete y abrir una única PR de revisión humana con metadatos normalizados y evidencia renovada. Esa automatización no debe aprobar, fusionar, publicar ni revocar automáticamente ninguna versión. La disponibilidad se rige por el contrato de instalación expresa y compatible descrito aquí.
