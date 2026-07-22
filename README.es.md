# Remote Dev Containers — inicio v0.1

Entorno comunitario de Codex CLI accesible desde navegador para Docker, NAS y homelab.

> Estado: diseño y starter de implementación. Todavía no es una imagen publicada ni auditada. No está afiliado ni respaldado por OpenAI.

## Objetivo

Mantener Codex, las herramientas y los repositorios en un Docker remoto para que el ordenador personal solo necesite navegador.

## Decisiones principales

- Base compartida ligera sobre Ubuntu 24.04.
- Ejecución como root.
- Codex CLI desde una release oficial fijada y verificada.
- GitHub CLI incluido desde el principio.
- Python 3.14, Node 24, uv y mise.
- ttyd como terminal web y tmux para reconectar sesiones.
- Volúmenes separados para workspace, Codex, GitHub, Git y SSH.
- AMD64 como única arquitectura estable inicial.

Consulta `docs/roadmap.md` para el orden de trabajo.
