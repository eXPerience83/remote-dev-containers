# Remote Dev Containers — inicio v0.1

Entorno comunitario de agentes de programación accesible desde navegador para Docker, NAS y homelab.

> [!WARNING]
> **Desarrollo activo / experimental.** Todavía no existe una versión estable. Las imágenes públicas `edge` pueden cambiar o romperse sin previo aviso. No expongas ninguno de los dos puertos web directamente a Internet. Este proyecto no está afiliado ni respaldado por OpenAI, Google o Anthropic.

## Objetivo

Mantener las herramientas, los repositorios y los agentes de programación en un Docker remoto para que el ordenador personal solo necesite navegador.

## Implementación actual

El stack edge actual utiliza Codex como implementación de referencia:

```text
Stack Remote Dev
├── launcher  → puerto principal 7680
└── codex     → terminal autenticado 7681
```

- una imagen de Remote Dev reutilizada por ambos servicios;
- launcher sin estado y sin contraseña por defecto en redes privadas de confianza;
- terminal Codex aislado y autenticado de forma independiente;
- Ubuntu 26.04 LTS;
- Git, Git LFS, OpenSSH y GitHub CLI;
- Python 3.14, Node 24, npm 12, uv y mise;
- terminal web ttyd y sesiones persistentes mediante tmux;
- rutas persistentes canónicas y separadas por rol;
- AMD64 primero.

Los roles implementados son:

```dotenv
REMOTE_DEV_ROLE=launcher
# o: codex
# o: shell
```

`antigravity` y `claude` siguen reservados y no disponibles. Nunca provocan una descarga implícita.

## Launcher y autenticación

El launcher solo sirve para navegar. No actúa como proxy, no utiliza el socket Docker y no recibe workspaces, credenciales ni estado de los agentes. Al seleccionar Codex, el navegador abre su endpoint autenticado independiente.

La autenticación Basic del launcher es opcional para despliegues avanzados del Compose genérico mediante `compose/launcher-auth.yml`. El ejemplo normal de TrueNAS/LAN deja el launcher sin contraseña y exige autenticación únicamente en el terminal Codex.

## Modos de aprobación de Codex

```dotenv
REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous
# o: guarded
```

- `autonomous` se traduce a `--ask-for-approval never`;
- `guarded` se traduce a `--ask-for-approval untrusted`.

El menú ofrece inicio, reanudación y un selector para el siguiente lanzamiento. Un cambio puntual se consume al arrancar Codex y después vuelve al valor del despliegue.

Las confirmaciones no son un sandbox. El límite de aislamiento soportado es el contenedor exterior de Codex y sus montajes estrechos. En el perfil validado de TrueNAS, el launcher propio del proyecto fija el sandbox interno no compatible a `danger-full-access`.

## Estructura persistente canónica

El Compose genérico utiliza una única raíz administrativa:

```dotenv
REMOTE_DEV_DATA_ROOT=../data
```

Las rutas se resuelven respecto a `compose/docker-compose.yml`. La estructura canónica es:

```text
REMOTE_DEV_DATA_ROOT/
├── workspaces/
│   └── codex/
├── state/
│   └── codex/
│       ├── agent/
│       ├── gh/
│       ├── git/
│       └── ssh/
└── secrets/
    └── codex/
        └── web_password.txt
```

El servicio Codex monta exclusivamente esos directorios hijo. El launcher no tiene montajes. Nunca se montan de forma completa la raíz administrativa, `/root`, `/home`, `/mnt`, la raíz del host ni sockets del motor de contenedores.

Todos los bind mounts utilizan `create_host_path: false`. Debes crear deliberadamente todos los directorios necesarios antes de iniciar el stack; una ruta incorrecta falla en lugar de generar silenciosamente una carpeta nueva.

No existe migración automática ni alias para la estructura experimental anterior. El estado experimental debe moverse o recrearse manualmente. El uso opcional de SMB/ACL queda aplazado al issue #71 y nunca debe exponer `state` ni `secrets`.

## Licencias y software opcional

El código propio de Remote Dev utiliza Apache-2.0. Los componentes incluidos conservan sus licencias y avisos originales. Puedes inspeccionarlos con:

```bash
remote-dev-notices
remote-dev-notices --list
remote-dev-notices --check
```

Antigravity, Claude Code y productos similares no quedan cubiertos por Apache-2.0 y la imagen actual no los descarga ni redistribuye. Cualquier integración futura deberá utilizar una instalación explícita desde una fuente oficial después de la revisión legal y técnica específica.

## Compilación local

```bash
cp .env.example .env
mkdir -p \
  data/workspaces/codex \
  data/state/codex/{agent,gh,git,ssh} \
  data/secrets/codex
printf '%s\n' 'contraseña-de-codex' > data/secrets/codex/web_password.txt
chmod 600 data/secrets/codex/web_password.txt
./scripts/build-local.sh
```

Define `REMOTE_DEV_IMAGE=remote-dev:local` en `.env` y ejecuta:

```bash
docker compose -f compose/docker-compose.yml up -d
```

Abre el puerto `7680`, selecciona Codex y autentícate en el puerto `7681`.

Para proteger también el launcher en un despliegue genérico avanzado:

```bash
mkdir -p secrets
printf '%s\n' 'contraseña-distinta-del-launcher' > secrets/launcher_password.txt
chmod 600 secrets/launcher_password.txt
docker compose \
  -f compose/docker-compose.yml \
  -f compose/launcher-auth.yml \
  up -d
```

La contraseña del launcher debe seguir separada de las contraseñas de los agentes.

## Prueba pública de edge

```bash
docker pull ghcr.io/experience83/remote-dev:edge-amd64
```

Define:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:edge-amd64
```

El paquete `codex-remote-dev` y la variable `CODEX_IMAGE` siguen como aliases del nombre de imagen durante `v0.1.x`; no conservan la estructura de datos retirada.

Para reproducción inmutable, registra el digest publicado y utiliza:

```text
ghcr.io/experience83/remote-dev@sha256:<digest>
```

## Advertencias importantes

- No publiques los puertos 7680 o 7681 directamente en Internet.
- Publica el launcher sin contraseña solo en localhost, LAN de confianza o Tailscale/WireGuard.
- Mantén el terminal Codex autenticado de forma independiente.
- No montes el socket Docker ni uses modo privilegiado.
- No montes estado o credenciales de agentes en el launcher.
- El modo autónomo puede modificar sin confirmación todo lo montado en Codex.
- `edge` sigue siendo experimental.

Consulta `AGENTS.md`, `PROJECT_STATUS.md`, `CHANGELOG.md`, `docs/architecture.md`, `docs/security.md`, `docs/releases.md` y `docs/roadmap.md` para los detalles de implementación y publicación.
