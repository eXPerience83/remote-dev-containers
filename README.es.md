# Remote Dev Containers — inicio v0.1.1-dev

Entorno comunitario de agentes de programación accesible desde navegador para Docker, NAS y homelab.

> [!WARNING]
> **Desarrollo activo / experimental.** Todavía no existe una release estable. Las imágenes públicas `edge` son builds integrados de desarrollo y aún pueden cambiar antes de la primera release estable. No expongas ningún puerto web de Remote Dev directamente a Internet. Este proyecto no está afiliado ni respaldado por OpenAI, Google o Anthropic.

## Objetivo

Mantener herramientas de desarrollo, repositorios y agentes de programación en un host Docker remoto para que el ordenador personal solo necesite navegador.

## Implementación actual

```text
Stack Remote Dev
├── launcher      7680 — navegación sin contraseña
├── codex         7681 — terminal autenticado
└── antigravity   7682 — terminal opcional/experimental autenticado
```

Bases actuales:

- una referencia de imagen `ghcr.io/experience83/remote-dev` reutilizada por launcher, Codex y los servicios Antigravity habilitados;
- un launcher sin estado y solo de navegación, sin workspace, estado, contraseña de agente ni socket Docker/Podman;
- un servicio Codex de referencia aislado con montajes privados por rol;
- un servicio Antigravity opcional aislado con estado privado y runtime del proveedor instalado únicamente mediante acción explícita del usuario;
- Ubuntu 26.04 LTS, AMD64 primero;
- Codex CLI desde un artefacto oficial fijado, más una ruta opcional explícita de runtime oficial conservando el CLI incluido como fallback;
- GitHub CLI, Python 3.14, Node 24, npm, uv, mise, ttyd y tmux;
- un único contrato canónico y neutral de persistencia;
- un único contrato runtime de autenticación web basado en `WEB_PASSWORD` para los endpoints de agente protegidos, con entradas separadas para Codex/Antigravity; actualmente los valores pueden reutilizarse entre agentes;
- selección de proyecto debajo de cada `/workspace` privado;
- semántica de releases `dev -> edge -> stable = latest`, manteniendo la identidad fechada de edge separada del canal y de la procedencia inmutable.

## Instalar en TrueNAS SCALE

Utiliza [`compose/truenas.yml`](compose/truenas.yml) como **YAML canónico de Custom App para TrueNAS**. No mantengas una copia independiente del stack en el README.

Los detalles de la UI de TrueNAS pueden cambiar entre versiones. La referencia upstream actual es la [documentación de Custom Apps de TrueNAS](https://www.truenas.com/docs/scale/apps/installcustomappscreens/).

### 1. Crea explícitamente el dataset raíz

Crea un único dataset raíz administrado por el operador, por ejemplo:

```text
Pool1/remote-dev
```

normalmente visible en el host como:

```text
/mnt/Pool1/remote-dev
```

Para el modelo Host Path de referencia de Remote Dev, crea/usa esta raíz como **Generic/POSIX**. La validación real en TrueNAS mostró que la herencia NFSv4 del preset Apps puede dejar acceso efectivo adicional en el host aunque una salida simple de permisos parezca `0700`. Consulta [`docs/truenas-acl-contract.es.md`](docs/truenas-acl-contract.es.md) antes de reutilizar un árbol existente con preset Apps/NFSv4.

Normalmente solo la raíz necesita ser un dataset ZFS. Los descendientes `workspaces/` y `state/` pueden ser directorios normales. Los datasets hijos deliberados siguen siendo válidos si el administrador quiere un límite separado para snapshots, cuotas o replicación.

La raíz debe existir previamente. `scripts/init-data-layout.py` se niega a crear implícitamente una raíz, padre o dataset ZFS inexistentes. No crees symlinks en la ruta persistente requerida.

### 2. Usa bootstrap, preflight y audit ACL de la misma revisión

La imagen seleccionada, `compose/truenas.yml` y los helpers del host deben corresponder a la misma revisión del repositorio.

Para el YAML de referencia, que declara Codex y Antigravity opcional/experimental:

```bash
sudo python3 scripts/init-data-layout.py \
  --root /mnt/Pool1/remote-dev \
  --include-antigravity

sudo python3 scripts/preflight-data-layout.py \
  --root /mnt/Pool1/remote-dev \
  --include-antigravity

sudo python3 scripts/truenas-acl-audit.py \
  --root /mnt/Pool1/remote-dev \
  --include-antigravity
```

El inicializador crea únicamente los descendientes canónicos que falten y es idempotente. No borra, migra, renombra ni reescribe de forma recursiva contenido existente de proyectos/estado. El preflight valida el mismo contrato de rutas y el audit ACL es de solo lectura.

Las contraseñas web pertenecen a la configuración del despliegue y las validan los endpoints de agente al arrancar. El antiguo diseño de autenticación web mediante ficheros/árbol de secrets está retirado y no forma parte de bootstrap/preflight.

Si mantienes intencionadamente un YAML local solo con Codex, omite `--include-antigravity` de forma coherente. Para validación exacta consulta el [runbook TrueNAS](docs/truenas-antigravity-validation.md) y el [contrato ACL](docs/truenas-acl-contract.es.md).

### 3. Revisa valores específicos del host

Antes de guardar la Custom App, revisa como mínimo:

- cada IP bind de ejemplo y sustitúyela por la IP LAN/Tailscale/malla privada del host;
- cada bind source `/mnt/Pool1/remote-dev` si tu pool/ruta es distinto;
- los valores `WEB_PASSWORD` configurados para Codex y Antigravity opcional; son entradas separadas, pero actualmente pueden contener el mismo valor;
- zona horaria, identidad Git y modo de aprobación de Codex;
- `REMOTE_DEV_PROJECT`: vacío para menú normal o un proyecto validado para modo directo.

Remote Dev exige actualmente únicamente un valor no vacío de una sola línea para un endpoint de agente protegido. No impone longitud mínima, composición ni unicidad entre agentes; esas reglas quedan deliberadamente aplazadas a una futura decisión sobre acceso/autenticación web.

Un administrador privilegiado de TrueNAS puede inspeccionar la configuración guardada y está dentro del límite de confianza. Sanea capturas/exportaciones antes de compartirlas.

La serialización de Custom Apps puede reescribir formato, descartar comentarios y no conservar exactamente la interpolación Compose. Verifica la referencia/canal efectivo de imagen después de guardar.

Cuando la App esté en ejecución, abre:

```text
http://<IP-LAN-o-malla-privada-de-TrueNAS>:7680
```

El puerto `7680` es el launcher y permanece deliberadamente sin contraseña en el modelo privado actual. Codex se autentica en `7681`; Antigravity lo hace en su endpoint `7682`. Que sean endpoints/configuraciones de agente separadas no obliga a usar contraseñas distintas. No expongas estos puertos directamente a Internet.

Continúa con la [guía práctica](docs/user-guide.es.md).

## Roles y puntos de entrada

Los puntos de entrada canónicos incluyen `start-remote-dev-web`, `remote-dev-launcher`, `remote-dev-menu`, `remote-dev-doctor` y `remote-dev-healthcheck`. Los comandos específicos de Codex continúan como wrappers de compatibilidad.

```dotenv
REMOTE_DEV_ROLE=launcher
# o: codex
# o: antigravity
# o: shell
```

`claude` sigue reservado y sin implementar.

Los servicios de agente aceptan `REMOTE_DEV_START_MODE=menu|agent|shell`; el launcher solo acepta `menu`.

## Workspaces por proyecto

`/workspace` es la **raíz privada que agrupa proyectos** de un rol. Las sesiones normales se ejecutan desde un hijo directo validado, por ejemplo `/workspace/pollenlevels`.

El menú **Projects...** puede seleccionar, crear o eliminar —con confirmación exacta— hijos directos validados. Se rechazan symlinks, traversal y selectores absolutos arbitrarios.

```dotenv
REMOTE_DEV_PROJECT=pollenlevels
```

Seleccionar proyecto elige directorio de trabajo; **no** crea aislamiento de sistema de archivos frente a proyectos hermanos ya montados en el mismo contenedor. Codex y Antigravity tienen workspaces escribibles separados; usa clones/worktrees separados entre roles.

## Launcher y autenticación web

El launcher es una interfaz pequeña y solo de navegación. No actúa como proxy ttyd, no gestiona contenedores y no recibe estado ni credenciales de agentes.

**El launcher soportado actualmente no requiere contraseña.** Debe vincularse solo a localhost, una LAN de confianza o una malla privada como Tailscale. Todavía no es la puerta de entrada de autenticación segura central del stack.

Codex y Antigravity habilitado son los endpoints protegidos. Cada uno utiliza un `WEB_PASSWORD` basado en configuración. Compose mantiene entradas separadas para esos servicios de agente para que puedan cambiarse de forma independiente. Remote Dev permite actualmente reutilizar el mismo valor entre ellos y no aplica reglas de longitud mínima o composición.

El mecanismo antiguo de contraseña web basada en fichero está retirado. Una futura entrada única segura, gateway central, identidad/passkeys/MFA o un diseño en el que el launcher se convierta en el límite de autenticación confiable pertenece al trabajo futuro de #181.

Existe `compose/launcher-auth.yml` como override avanzado y no predeterminado, pero no forma parte del flujo normal actual ni es necesario para usar Remote Dev.

## Modos de aprobación de Codex

```dotenv
REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous
# o: guarded
```

- `autonomous` se traduce a `--ask-for-approval never`.
- `guarded` marca como no confiable solo el proyecto activo durante ese lanzamiento.

Start/Resume usan el proyecto seleccionado como directorio de trabajo. Un override puntual no reescribe la configuración permanente.

## Actualizaciones explícitas de Codex

El `/usr/local/bin/codex` probado con la imagen permanece inmutable. `remote-dev-codex-runtime` puede instalar/actualizar/eliminar explícitamente un runtime oficial compatible más nuevo manteniendo el CLI incluido como fallback.

Un runtime más nuevo puede aparecer como **official source; Remote Dev review pending**. El estado opcional permanece dentro de persistencia privada de Codex. Consulta [`docs/codex-runtime-updates.es.md`](docs/codex-runtime-updates.es.md).

## Antigravity — opcional y experimental

Antigravity está implementado, no reservado, pero sigue deliberadamente **experimental**.

Start/Resume por proyecto, continuidad útil de conversación, instalación/actualización explícitas, rollback de imagen, persistencia y validación amplia de ciclo de vida/aislamiento en TrueNAS están completados. También lo están el modelo de admisión #96 y la reconciliación humana #53 de términos/política.

La interpretación de soporte es estrecha:

- usar el CLI/runtime oficial `agy` de Google por la ruta oficial revisada;
- mantener instalación/actualización explícitas e iniciadas por el usuario;
- mantener desactivada la actualización automática del proveedor;
- no redistribuir bytes propietarios del instalador/CLI;
- no implementar un cliente alternativo del servicio Antigravity;
- no reutilizar/exportar OAuth de Google/Antigravity para otro agente/servicio;
- mantener estado/credenciales privados y salvaguardas de admisión/integridad;
- conservar no afiliación y términos/privacidad;
- no describir la evidencia de Remote Dev como firma, certificación o respaldo de Google.

Es una interpretación humana de riesgo/soporte, no aprobación legal del proveedor.

La automatización #83 ya está enviada. El descubrimiento programado valida bytes acotados del proveedor como **datos** y no ejecuta código del proveedor. Los cambios se representan como metadata y la inspección ejecutable requiere el workflow explícito de revisión confiable.

Consulta [`docs/antigravity-runtime-admission.es.md`](docs/antigravity-runtime-admission.es.md) y [`third_party/optional-agents.md`](third_party/optional-agents.md).

## Context7 para Codex

El MCP hospedado de Context7 y el onboarding opcional por código de dispositivo están enviados para Codex. Remote Dev no conserva el paquete runtime de Context7 en la imagen; el login explícito utiliza tooling transitorio revisado y lo limpia después.

Context7 es un servicio externo operado por Upstash. Consulta [`docs/context7-codex.es.md`](docs/context7-codex.es.md).

## Aislamiento en TrueNAS

La imagen predeterminada no instala Bubblewrap del sistema. Los lanzamientos soportados de Codex desactivan explícitamente el sandbox interno no soportado; el contenedor Docker exterior y sus montajes estrechos son el límite soportado.

Los contenedores de producción usan root filesystem de solo lectura, `no-new-privileges`, `cap_drop: [ALL]`, montajes privados y límites acotados. El launcher se ejecuta como UID/GID `65532` sin capacidades restauradas.

No añadas modo privilegiado, `SYS_ADMIN`, namespaces host ni socket Docker/Podman para forzar un sandbox interno. Consulta [`docs/security.md`](docs/security.md).

## Layout persistente

```dotenv
REMOTE_DEV_DATA_ROOT=../data
```

```text
REMOTE_DEV_DATA_ROOT/
├── workspaces/
│   └── codex/
│       └── <project>/
└── state/
    └── codex/
        ├── agent/
        ├── runtime/
        ├── gh/
        ├── git/
        └── ssh/
```

Antigravity utiliza hijos privados disjuntos. Las contraseñas web son configuración del despliegue, no ficheros persistentes.

## Licencias

El código del proyecto usa Apache-2.0. El software upstream incluido conserva sus licencias/notices.

```bash
remote-dev-notices
remote-dev-notices --list
remote-dev-notices --check
```

Google Antigravity, Claude Code y otros productos propietarios no quedan cubiertos por Apache-2.0 del repositorio. Los bytes runtime de Antigravity se obtienen solo tras acción explícita del usuario desde la fuente revisada y no se redistribuyen.

## Build local

```bash
cp .env.example .env
chmod 600 .env
mkdir -p \
  data/workspaces/codex/example-project \
  data/state/codex/{agent,gh,git,ssh}
sudo install -d -o root -g root -m 0700 data/state/codex/runtime
# Configura un WEB_PASSWORD no vacío para Codex.
make preflight
./scripts/build-local.sh
```

La versión base de desarrollo local es `0.1.1-dev`; las publicaciones edge usan su identidad fechada `edge-YYYY.MM.DD-<short-sha>` en lugar de ese valor local predeterminado.

## Pruebas públicas con edge

```bash
docker pull ghcr.io/experience83/remote-dev:edge-amd64
```

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:edge-amd64
```

Para reproducción/rollback exactos usa el digest publicado:

```text
ghcr.io/experience83/remote-dev@sha256:<digest>
```

Una identidad edge normal separa build y canal:

```text
Image version: edge-YYYY.MM.DD-<7-char-sha>
Channel: edge
Source revision: <full-commit-sha>
Codex CLI: codex-cli <bundled-version>
```

`latest` **no** es edge. El contrato permanente es `dev -> edge -> stable = latest`; `stable`/`latest` solo se mueven tras una publicación SemVer estable explícita.

Consulta [`docs/releases.es.md`](docs/releases.es.md).

## Advertencias importantes

- No publiques 7680, 7681 ni 7682 directamente a Internet.
- Vincula el launcher sin contraseña solo a localhost, LAN de confianza o malla privada.
- Codex y Antigravity habilitado requieren contraseñas configuradas no vacías de una sola línea salvo que se aplique explícitamente un override inseguro revisado; el producto actual no exige contraseñas largas ni mutuamente distintas.
- El launcher todavía no es el gateway de autenticación segura; ese diseño futuro pertenece a #181.
- No montes estado de agentes ni socket del motor de contenedores en el launcher.
- Seleccionar proyecto no aísla hermanos ya montados bajo el mismo `/workspace`.
- No compartas un checkout escribible entre agentes por defecto.
- El root del agente está limitado por el contenedor exterior y sus montajes.
- Los administradores TrueNAS/Docker están dentro del límite de confianza.
- Antigravity continúa experimental aunque sus gates técnicos estén implementados.
- `edge` sigue siendo experimental; todavía no existe release estable.

## Documentación

- [`PROJECT_STATUS.md`](PROJECT_STATUS.md)
- [`docs/architecture.md`](docs/architecture.md)
- [`docs/security.md`](docs/security.md)
- [`docs/tool-matrix.md`](docs/tool-matrix.md)
- [`docs/decisions.md`](docs/decisions.md)
- [`docs/releases.md`](docs/releases.md) / [`docs/releases.es.md`](docs/releases.es.md)
- [`docs/user-guide.md`](docs/user-guide.md) / [`docs/user-guide.es.md`](docs/user-guide.es.md)
- [`docs/codex-runtime-updates.es.md`](docs/codex-runtime-updates.es.md)
- [`docs/context7-codex.es.md`](docs/context7-codex.es.md)
- [`docs/antigravity-runtime-admission.es.md`](docs/antigravity-runtime-admission.es.md)
- [`docs/truenas-acl-contract.es.md`](docs/truenas-acl-contract.es.md)
- [`docs/dependency-automation.md`](docs/dependency-automation.md)
- [`docs/roadmap.md`](docs/roadmap.md)
