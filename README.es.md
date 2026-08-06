# Remote Dev Containers — inicio v0.1

Entorno comunitario de agentes de programación accesible desde navegador para Docker, NAS y homelab.

> [!WARNING]
> **Desarrollo activo / experimental.** Todavía no existe una versión estable. Las imágenes públicas `edge` pueden cambiar o romperse sin previo aviso. No expongas directamente a Internet el launcher ni los terminales de los agentes. Este proyecto no está afiliado ni respaldado por OpenAI, Google o Anthropic.

## Objetivo

Mantener herramientas, repositorios y agentes de programación en un Docker remoto para que el ordenador personal solo necesite navegador.

## Stack actual

Una sola imagen de Remote Dev se reutiliza en tres servicios aislados:

```text
App / stack Compose de Remote Dev
├── launcher       → navegación, normalmente puerto 7680
├── codex          → terminal autenticado, normalmente puerto 7681
└── antigravity    → terminal experimental autenticado, normalmente puerto 7682
```

- El launcher solo navega y no recibe workspaces, OAuth, credenciales de GitHub, claves SSH ni el socket Docker.
- Codex y Antigravity se ejecutan en contenedores distintos con workspaces, GitHub CLI, Git, SSH, tmux y credenciales de agente separados.
- Todos los servicios reutilizan la misma referencia/digest de imagen.
- Codex se incluye en la imagen desde una release oficial fijada de OpenAI.
- Antigravity no se redistribuye. El servicio contiene únicamente wrappers de Remote Dev y evidencia de revisión basada en metadatos.
- La imagen compartida incluye Ubuntu 26.04 LTS, GitHub CLI, Git/Git LFS, OpenSSH, Python 3.14, Node 24, npm, uv, mise, ttyd y tmux.
- AMD64 es la arquitectura validada actualmente para Antigravity.

## Roles y puntos de entrada

Los comandos canónicos son:

- `start-remote-dev-web`;
- `remote-dev-launcher`;
- `remote-dev-menu`;
- `remote-dev-doctor`;
- `remote-dev-healthcheck`.

Roles implementados:

```dotenv
REMOTE_DEV_ROLE=launcher
# o: codex
# o: antigravity
# o: shell
```

`start-codex-web`, `codex-menu` y `codex-doctor` siguen siendo wrappers de compatibilidad. Los roles y modos desconocidos fallan sin evaluar fragmentos de shell editables.

## Launcher y autenticación

El launcher es navegación sin estado. En localhost/LAN/Tailscale de confianza puede funcionar sin Basic Auth, manteniendo comprobación de origen, CSP restrictiva, validación de rutas y restricciones de métodos.

Los terminales Codex y Antigravity se autentican de forma independiente y con contraseñas distintas. El launcher no actúa como proxy de ttyd y nunca incluye ni reenvía contraseñas.

El Compose genérico conserva un override opcional de autenticación del launcher respaldado por archivo; no sustituye la contraseña de ningún terminal.

## Codex

Codex sigue siendo el agente integrado de referencia y la copia garantizada incluida en la imagen. El menú permite:

- iniciar Codex;
- reanudar una sesión;
- elegir autonomous o guarded para un único inicio;
- login mediante device code;
- login de GitHub CLI;
- diagnósticos y shell.

Configuración del despliegue:

```dotenv
REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous
# o: guarded
```

- `autonomous` equivale a `--ask-for-approval never`.
- `guarded` equivale a `--ask-for-approval untrusted`.

El límite real de aislamiento es el contenedor exterior. Las confirmaciones no son un sandbox.

Codex se actualiza actualmente al actualizar la imagen. Una implementación futura y separada permitirá una actualización explícita desde una fuente oficial de OpenAI, conservando siempre el ejecutable incluido como fallback. Consulta `docs/agent-update-model.es.md`.

## Antigravity

Antigravity es una integración opcional **experimental**. El instalador de Google y el ejecutable `agy` nunca se guardan en el repositorio ni se incluyen en la imagen/SBOM pública.

El menú de Antigravity ofrece:

1. Iniciar Antigravity.
2. Reanudar mediante el selector completo `/resume`.
3. Instalar Antigravity desde Google.
4. Actualizar Antigravity desde Google.
5. Restaurar la versión local anterior.
6. Login de GitHub CLI, diagnósticos y shell.

### Instalación y actualización

La operación siempre es explícita. El gestor canónico:

- descarga solo desde `https://antigravity.google/cli/install.sh`;
- exige HTTPS y rechaza una URL final fuera del origen HTTPS oficial y fijo de Google;
- guarda la respuesta en un archivo privado y limitado, sin hacer `curl | sh`;
- valida sintaxis y el contrato vivo `--dir <path>` en un HOME sin credenciales;
- instala en una zona privada de preparación de Antigravity;
- comprueba que el candidato sea un ELF Linux AMD64 limitado y que `--version`/`--help` funcionen;
- guarda fuente, versión, tamaño y SHA-256 en un manifiesto local privado;
- publica únicamente tras superar todas las comprobaciones;
- mantiene la instalación activa si una actualización falla;
- conserva una versión local validada para rollback.

El arranque normal no descarga ni actualiza nada. Cada lanzamiento verifica el ejecutable frente a su manifiesto y establece:

```text
AGY_CLI_DISABLE_AUTO_UPDATE=true
```

### La revisión no bloquea la disponibilidad

Estados posibles:

- `oficial, revisado`: coincide con la última evidencia incluida en el repositorio;
- `oficial, revisión pendiente`: instalado expresamente desde el endpoint fijo de Google y sin cambios locales, pero distinto de la revisión incluida en la imagen;
- `oficial, revisión no disponible`: integridad local válida pero la evidencia de la imagen no puede leerse;
- dañado/modificado localmente: ejecutable o manifiesto no coinciden y el arranque queda bloqueado.

Un cambio ordinario de versión o hash de Google no obliga a publicar otra imagen Docker antes de instalar/actualizar. Solo hará falta una imagen nueva cuando cambie el contrato del proveedor de forma incompatible con los validadores actuales.

Consulta:

- `docs/agent-update-model.es.md`;
- `third_party/optional-agents.md`;
- `third_party/antigravity-cli-inspection.md`.

## Aislamiento en TrueNAS

El límite soportado es cada contenedor exterior con montajes mínimos. No añadas modo privilegiado, `SYS_ADMIN`, perfiles sin restricciones, montajes amplios de home/root ni el socket Docker.

No ejecutes Codex y Antigravity simultáneamente contra el mismo checkout escribible. La topología suministrada utiliza workspaces separados.

## Estructura persistente

El Compose genérico utiliza:

```dotenv
REMOTE_DEV_DATA_ROOT=../data
```

Estructura completa:

```text
REMOTE_DEV_DATA_ROOT/
├── workspaces/
│   ├── codex/
│   └── antigravity/
├── state/
│   ├── codex/
│   │   ├── agent/
│   │   ├── gh/
│   │   ├── git/
│   │   └── ssh/
│   └── antigravity/
│       ├── bin/
│       ├── runtime/
│       ├── vendor/
│       ├── gh/
│       ├── git/
│       └── ssh/
└── secrets/
    ├── codex/web_password.txt
    └── antigravity/web_password.txt
```

En TrueNAS doméstico las contraseñas pueden permanecer en el YAML privado mediante `WEB_PASSWORD`; los despliegues genéricos/endurecidos pueden usar secretos en archivo. Nunca publiques valores reales.

Ejecuta el preflight antes del despliegue. Rechaza rutas ausentes, malformadas o con symlinks y contraseñas con permisos inseguros. Los bind mounts usan sintaxis larga con `create_host_path: false` como defensa adicional.

## Licencias y avisos

El código propio de Remote Dev usa Apache-2.0. Las herramientas incluidas mantienen sus licencias originales:

```bash
remote-dev-notices
remote-dev-notices --list
remote-dev-notices --check
```

Antigravity, Claude Code y otros productos del proveedor no están cubiertos por la licencia del proyecto. Antigravity se obtiene directamente de Google únicamente tras consentimiento explícito. Remote Dev no afirma derechos de redistribución ni afiliación.

## Compilación local

```bash
cp .env.example .env
mkdir -p \
  data/workspaces/{codex,antigravity} \
  data/state/codex/{agent,gh,git,ssh} \
  data/state/antigravity/{bin,runtime,vendor,gh,git,ssh} \
  data/secrets/{codex,antigravity}
printf '%s\n' 'contraseña-de-codex' > data/secrets/codex/web_password.txt
printf '%s\n' 'contraseña-distinta-de-antigravity' > data/secrets/antigravity/web_password.txt
chmod 600 data/secrets/*/web_password.txt
make preflight
./scripts/build-local.sh
```

Activa el perfil/configuración opcional de Antigravity indicado por el archivo de despliegue y utiliza la misma variable `REMOTE_DEV_IMAGE` para todos los servicios.

## Imagen edge pública

```bash
docker pull ghcr.io/experience83/remote-dev:edge-amd64
```

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:edge-amd64
```

Para reproducir o hacer rollback:

```text
ghcr.io/experience83/remote-dev:sha-<commit-completo>
ghcr.io/experience83/remote-dev@sha256:<digest>
```

Los menús y diagnósticos muestran la identidad embebida de la imagen. `edge` sigue siendo mutable y experimental.

## Advertencias

- No expongas los puertos 7680, 7681 o 7682 directamente a Internet.
- Limita el launcher a localhost, LAN o Tailscale salvo que exista un proxy revisado por separado.
- La autenticación de los terminales de agente es obligatoria.
- Quien tenga acceso al terminal puede leer los repositorios y credenciales montados en ese servicio.
- No compartas OAuth, tokens, GitHub o SSH entre agentes.
- No montes el socket Docker ni uses modo privilegiado.
- La actualización automática de Antigravity permanece desactivada; usa la acción explícita.
- `revisión pendiente` significa que el payload todavía no ha completado la revisión humana de Remote Dev.
- `edge` puede sustituirse sin previo aviso.

## Desarrollo y documentación

El desarrollo se realiza mediante pull requests enfocadas. Lee `AGENTS.md` y `CONTRIBUTING.md` antes de cambiar el runtime o su seguridad.

Documentos principales:

- `README.md`;
- `AGENTS.md`;
- `CHANGELOG.md`;
- `docs/agent-update-model.es.md`;
- `docs/architecture.md`;
- `docs/security.md`;
- `docs/tool-matrix.md`;
- `docs/truenas-antigravity-validation.md`;
- `third_party/optional-agents.md`;
- `third_party/antigravity-cli-inspection.md`.
