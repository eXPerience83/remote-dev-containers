# Remote Dev Containers — inicio v0.1

Entorno comunitario de Codex CLI accesible desde navegador para Docker, NAS y homelab.

> [!WARNING]
> **Desarrollo activo / experimental.** Todavía no existe una versión estable. Las imágenes públicas `edge` pueden cambiar o romperse sin previo aviso y aún no han completado toda la validación de TrueNAS, seguridad y persistencia. No expongas el terminal web directamente a Internet. Este proyecto no está afiliado ni respaldado por OpenAI.

## Objetivo

Mantener Codex, las herramientas y los repositorios en un Docker remoto para que el ordenador personal solo necesite navegador.

## Decisiones principales

- Base compartida ligera sobre Ubuntu 26.04 LTS.
- Ejecución como root.
- Codex CLI desde una release oficial fijada y verificada.
- GitHub CLI incluido desde el principio.
- Python 3.14, Node 24, uv y mise.
- ttyd como terminal web y tmux para reconectar sesiones.
- Volúmenes separados para workspace, Codex, GitHub, Git y SSH.
- AMD64 como única arquitectura inicial.

### Puntos de entrada neutrales por rol

La migración hacia la arquitectura de stack único utiliza una única implementación canónica:

- `start-remote-dev-web`;
- `remote-dev-menu`;
- `remote-dev-doctor`.

`start-codex-web`, `codex-menu` y `codex-doctor` continúan como wrappers de compatibilidad que seleccionan el rol Codex y llaman a los comandos canónicos.

El selector de rol implementado es:

```dotenv
REMOTE_DEV_ROLE=codex
# o: shell
```

`launcher`, `antigravity` y `claude` son nombres reservados y fallan de forma clara porque todavía no están implementados. Nunca provocan una descarga implícita.

El selector neutral de arranque directo acepta `menu`, `agent` o `shell`:

```dotenv
REMOTE_DEV_START_MODE=menu
```

La configuración existente `START_MODE=menu|codex|shell` sigue siendo compatible; el valor antiguo `codex` se traduce a `agent`. Cuando se define `REMOTE_DEV_START_MODE`, tiene prioridad. Los roles y modos desconocidos se rechazan sin evaluar fragmentos de shell.

Esta fase todavía no incorpora la URL del launcher, múltiples servicios, nuevos montajes ni migración de datos.

### Modos de aprobación de Codex

Codex siempre se inicia mediante el lanzador controlado por el proyecto, con el sandbox interno no compatible desactivado expresamente. El despliegue puede seleccionar uno de estos dos modos validados:

```dotenv
REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous
# o: guarded
```

- `autonomous` es el valor predeterminado y se traduce a `--ask-for-approval never`.
- `guarded` se traduce a `--ask-for-approval untrusted`.

El menú inicia o reanuda Codex con el modo configurado y permite escoger otro modo para una sola ejecución sin reescribir la configuración permanente. La interfaz equivalente es:

```bash
run-codex --approval-mode autonomous
run-codex --approval-mode guarded resume
run-codex --print-policy
```

La selección de una ejecución tiene prioridad sobre el valor del despliegue solo para ese proceso. Los valores desconocidos y los intentos de introducir flags directos de sandbox o aprobación se rechazan antes de iniciar Codex. Los argumentos situados después de `--` se conservan literalmente.

## Aislamiento en TrueNAS

La imagen predeterminada no instala el paquete Bubblewrap del sistema. El lanzador soportado desactiva explícitamente el sandbox interno no compatible de Codex mediante `--sandbox danger-full-access`. El modo autónomo utiliza `--ask-for-approval never`; el modo protegido utiliza `--ask-for-approval untrusted`. Todos los arranques y reanudaciones soportados pasan por el mismo resolver.

En este contexto, `danger-full-access` solo describe el sandbox interno de Codex: no concede privilegios Docker ni acceso adicional al host. El límite de seguridad soportado es el contenedor exterior y sus montajes mínimos. Las aprobaciones no son un sandbox ni ocultan a Codex los archivos y credenciales ya montados en el servicio.

En modo autónomo, Codex puede leer, modificar o eliminar cualquier elemento montado en su servicio y utilizar las credenciales disponibles sin pedir confirmación. No obtiene acceso adicional al concedido por los montajes, la red y las credenciales existentes. El modo protegido añade confirmaciones, pero no aislamiento del sistema de archivos.

No debilites el host ni el contenedor con modo privilegiado, `SYS_ADMIN`, perfiles de seguridad sin restricciones o el socket de Docker para intentar iniciar un sandbox anidado. Monta únicamente las rutas que necesite el servicio.

## Licencias y software opcional de proveedores

El código propio de Remote Dev utiliza Apache-2.0. Ubuntu, Codex CLI, GitHub CLI, ttyd, mise, Python, Node.js, npm, uv y sus dependencias conservan sus respectivas licencias y avisos originales. La imagen mantiene los archivos de copyright de los paquetes y copia las licencias incluidas en los artefactos exactos instalados.

Consulta el inventario revisado en `third_party/README.md` o, desde una imagen construida:

```bash
remote-dev-notices
remote-dev-notices --list
remote-dev-notices --check
```

Antigravity, Claude Code y productos similares no quedan cubiertos por la licencia Apache-2.0 de este repositorio. La imagen actual no los descarga ni redistribuye. Cualquier instalador opcional futuro deberá ser iniciado expresamente por el usuario, descargar desde el proveedor y respetar la política de términos, privacidad, aislamiento de credenciales y no afiliación de `third_party/optional-agents.md`.

## Prueba pública de la imagen edge

La imagen `edge` es una compilación experimental publicada automáticamente después de fusionar en `main` cambios relevantes para la imagen o el runtime. Puede descargarse sin credenciales:

```bash
docker pull ghcr.io/experience83/remote-dev:edge-amd64
```

Para Docker Compose o TrueNAS:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:edge-amd64
REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous
```

Los despliegues existentes de la serie `v0.1.x` pueden conservar `CODEX_IMAGE` y `ghcr.io/experience83/codex-remote-dev`. `REMOTE_DEV_IMAGE` tiene prioridad cuando ambas variables están definidas, y los dos paquetes apuntan al mismo digest promocionado en edge y stable. Los nombres de compatibilidad no se eliminarán antes de `v0.2.0`.

Utiliza `guarded` en lugar de `autonomous` cuando quieras confirmaciones de comandos. El cambio se aplica a las sesiones nuevas; no altera un proceso Codex que ya está ejecutándose.

Para identificar la compilación correspondiente a un commit concreto, utiliza la etiqueta `sha-...` mostrada en GHCR:

```text
ghcr.io/experience83/remote-dev:sha-<commit-completo>
```

Las etiquetas de GHCR son mutables. Para una reproducción o rollback inmutable, registra el digest publicado y fija la imagen así:

```text
ghcr.io/experience83/remote-dev@sha256:<digest>
```

El menú web muestra el canal de imagen embebido, la revisión de origen embebida en forma abreviada y la versión instalada de Codex CLI detectada en tiempo de ejecución. Para consultar los metadatos completos de la imagen junto con la versión de Codex CLI en ejecución desde los diagnósticos o desde un shell:

```bash
remote-dev-version
```

Salida esperada para `edge`:

```text
Image version: edge
Source revision: <commit-completo>
Codex CLI: codex-cli <versión>
```

## Desarrollo y revisiones

El desarrollo se realiza mediante pull requests. CodeRabbit se configura en `.coderabbit.yaml` para revisar Dockerfiles, scripts Bash, GitHub Actions, archivos Compose y cambios sensibles de seguridad. Durante esta fase sus comentarios son orientativos: CI y las pruebas manuales siguen siendo obligatorios.

Consulta `AGENTS.md`, `README.md`, `PROJECT_STATUS.md`, `CHANGELOG.md`, `third_party/README.md`, `third_party/optional-agents.md` y `docs/roadmap.md` para el estado, los límites y el orden de trabajo completos.
