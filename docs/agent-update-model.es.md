# Instalación y actualización de agentes sin depender de la imagen

## Decisión

Remote Dev separa tres aspectos que no deben confundirse:

1. **Distribución de la imagen:** código inmutable del proyecto, herramientas compartidas y una copia de Codex incluida como respaldo.
2. **Instalación explícita del proveedor:** descarga solicitada por el usuario de software que Remote Dev no puede redistribuir.
3. **Evidencia de revisión humana:** metadatos y pruebas de compatibilidad mantenidos mediante pull request.

No debe ser necesario publicar una imagen Docker nueva para cada versión ordinaria de un agente. Solo será necesaria cuando tengan que cambiar el código, la compatibilidad o la política de seguridad de Remote Dev.

## Antigravity

Antigravity solo se descarga después de que el usuario elija instalarlo o actualizarlo. El gestor usa el endpoint HTTPS oficial y fijo de Google, valida la respuesta y el contrato del instalador, instala en una zona privada de preparación, comprueba el ejecutable Linux AMD64 resultante y guarda un manifiesto local de integridad antes de publicarlo de forma atómica.

El arranque normal no descarga nada. Comprueba el ejecutable instalado frente a su manifiesto local y establece `AGY_CLI_DISABLE_AUTO_UPDATE=true`.

El informe incluido en el repositorio identifica el último payload revisado. Una versión más nueva instalada desde la fuente oficial aparece como `oficial, revisión pendiente`; puede utilizarse mientras supere sus comprobaciones locales de integridad. Una copia dañada o modificada queda bloqueada.

Se conserva un ejecutable y un manifiesto anteriores para una restauración explícita. Una actualización fallida no sustituye la instalación activa.

## Codex

Codex continúa incluido en todas las imágenes de Remote Dev como copia de respaldo conocida. La implementación actual sigue utilizando ese ejecutable incluido.

La futura actualización explícita de Codex será independiente de la de Antigravity. Tendrá que obtener un artefacto oficial de OpenAI, verificarlo, almacenarlo fuera de las rutas inmutables de la imagen y volver automáticamente a la copia incluida cuando la instalación opcional falte o no sea válida.

## Automatización de la revisión

El issue #83 controla la detección programada y la revisión humana de cambios de Antigravity. La automatización debe:

- detectar cambios en el endpoint fijo del instalador;
- conservar y subir únicamente metadatos;
- abrir o actualizar una única pull request de revisión;
- ejecutar la inspección dedicada, las regresiones del runtime, la compilación y smoke AMD64, SBOM, Trivy y el control de vulnerabilidades críticas;
- no fusionar ni aprobar evidencia automáticamente;
- no deshabilitar una instalación intacta únicamente porque su revisión esté pendiente.

La evidencia de revisión aumenta la confianza y detecta cambios de contrato. No autoriza a redistribuir el producto ni actúa como bloqueo ordinario de disponibilidad.

## Límite de compatibilidad

Una imagen antigua puede seguir necesitando una actualización si el proveedor cambia la URL, el origen, los argumentos, el formato del paquete, la arquitectura, el comportamiento del ejecutable u otro contrato que exceda los validadores limitados del gestor. El diseño evita que cada cambio normal de versión o hash obligue a publicar una imagen; no promete compatibilidad segura con cualquier cambio futuro del proveedor.
