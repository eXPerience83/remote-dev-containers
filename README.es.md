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

## Prueba pública de la imagen edge

La imagen `edge` es una compilación experimental publicada automáticamente después de fusionar en `main` cambios relevantes para la imagen o el runtime. Puede descargarse sin credenciales:

```bash
docker pull ghcr.io/experience83/codex-remote-dev:edge-amd64
```

Para Docker Compose o TrueNAS:

```dotenv
CODEX_IMAGE=ghcr.io/experience83/codex-remote-dev:edge-amd64
```

Para identificar la compilación correspondiente a un commit concreto, utiliza la etiqueta `sha-...` mostrada en GHCR:

```text
ghcr.io/experience83/codex-remote-dev:sha-<commit-completo>
```

Las etiquetas de GHCR son mutables. Para una reproducción o rollback inmutable, registra el digest publicado y fija la imagen así:

```text
ghcr.io/experience83/codex-remote-dev@sha256:<digest>
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

Consulta `README.md`, `PROJECT_STATUS.md`, `CHANGELOG.md` y `docs/roadmap.md` para el estado y el orden de trabajo completos.
