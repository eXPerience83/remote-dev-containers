# Remote Dev Containers — inicio v0.1

Entorno comunitario de agentes de programación accesible desde navegador para Docker, NAS y homelab.

> [!WARNING]
> **Desarrollo activo / experimental.** Todavía no existe una release estable. Las imágenes públicas `edge` son builds de desarrollo integrados y aún pueden cambiar antes de la primera release estable. No expongas ningún puerto web de Remote Dev directamente a Internet. Este proyecto no está afiliado ni respaldado por OpenAI, Google o Anthropic.

## Objetivo

Mantener herramientas de desarrollo, repositorios y agentes de programación en un host Docker remoto para que el ordenador personal solo necesite navegador.

## Implementación actual

El stack actual utiliza una única imagen canónica de Remote Dev para servicios aislados de rol fijo:

```text
Stack Remote Dev
├── launcher      7680 — solo navegación
├── codex         7681 — terminal autenticado de forma independiente
└── antigravity   7682 — terminal opcional/experimental autenticado de forma independiente
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
- un único contrato runtime de autenticación web basado en `WEB_PASSWORD`, con valores independientes por endpoint protegido;
- selección de proyecto debajo de cada `/workspace` privado para arrancar el agente en un proyecto concreto y no tratar `/workspace` como repositorio implícito;
- semántica de releases `dev -> edge -> stable = latest`, manteniendo la identidad fechada de edge separada del canal y de la procedencia inmutable.

## Instalar en TrueNAS SCALE

Utiliza [`compose/truenas.yml`](compose/truenas.yml) como **YAML canónico de Custom App para TrueNAS**. No mantengas una copia independiente del stack en el README.

Los detalles de la UI de TrueNAS pueden cambiar entre versiones. La referencia upstream actual es la [documentación de Custom Apps de TrueNAS](https://www.truenas.com/docs/scale/apps/installcustomappscreens/).

### 1. Crea explícitamente el dataset raíz

Crea un único dataset raíz administrado por el operador, por ejemplo:

```text
Pool1/remote-dev
```

que normalmente aparecerá en el host como:

```text
/mnt/Pool1/remote-dev
```

Para el modelo de seguridad Host Path de referencia de Remote Dev, crea/usa esta raíz como **Generic/POSIX**. La validación real en TrueNAS mostró que la herencia NFSv4 del preset Apps puede dejar acceso efectivo adicional en el host aunque una salida simple de permisos parezca `0700`. Consulta [`docs/truenas-acl-contract.es.md`](docs/truenas-acl-contract.es.md) antes de reutilizar un árbol existente con preset Apps/NFSv4.

Normalmente solo la raíz necesita ser un dataset ZFS. Los descendientes `workspaces/` y `state/` pueden ser directorios normales. Los datasets hijos deliberados siguen siendo válidos si el administrador quiere un límite separado para snapshots, cuotas o replicación.

La raíz debe existir previamente. `scripts/init-data-layout.py` se niega expresamente a crear implícitamente una raíz, padre o dataset ZFS inexistentes. No crees symlinks en ningún componente de las rutas persistentes requeridas.

### 2. Usa bootstrap, preflight y audit ACL de la misma revisión

La imagen seleccionada, `compose/truenas.yml` y los helpers del host deben corresponder a la misma revisión del repositorio. No combines una imagen fijada a una revisión con scripts copiados después desde una rama móvil como `main`.

Para el YAML de referencia, que declara Codex y Antigravity opcional/experimental, ejecuta tras crear el dataset raíz:

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

El inicializador crea únicamente los descendientes canónicos que falten, aplica modos iniciales solo a las rutas que crea y es idempotente. No borra, migra, renombra ni hace `chmod/chown` recursivo del contenido existente de proyectos/estado. Las rutas requeridas preexistentes, incluidos datasets hijos creados deliberadamente, se preservan.

El preflight valida el mismo contrato canónico de rutas. El audit ACL es de solo lectura y comprueba la política Generic/POSIX de estado privado de referencia. Las contraseñas web pertenecen a la configuración del despliegue y cada endpoint las valida al arrancar; ninguno de estos helpers crea ni requiere un árbol `secrets/` para contraseñas web.

Si mantienes intencionadamente un YAML local solo con Codex y sin Antigravity, omite `--include-antigravity` de forma coherente. No lo omitas si despliegas el YAML de referencia sin cambios porque sus bind sources de Antigravity también deben existir previamente.

Para validación exacta de candidato/digest y evidencia de migración, consulta el [runbook de validación TrueNAS](docs/truenas-antigravity-validation.md) y el [contrato ACL de TrueNAS](docs/truenas-acl-contract.es.md).

### 3. Revisa los valores del YAML específicos del host

Antes de guardar la Custom App, revisa como mínimo:

- cada IP bind de ejemplo y sustitúyela por la IP LAN o Tailscale/malla privada del host TrueNAS;
- cada bind source `/mnt/Pool1/remote-dev` si tu pool/ruta es distinto;
- `WEB_PASSWORD` de Codex y el `WEB_PASSWORD` independiente de Antigravity si mantienes ese servicio;
- zona horaria, identidad Git y modo de aprobación de Codex cuando corresponda;
- `REMOTE_DEV_PROJECT`: deja el valor literal vacío para el modo normal de menú o fija un proyecto validado si quieres modo directo.

Un administrador de TrueNAS con privilegios suficientes puede inspeccionar la configuración guardada de la App/contenedor. Ese administrador está dentro del límite de confianza de Remote Dev; sanea capturas y exportaciones de YAML antes de compartirlas.

La serialización de Custom Apps de TrueNAS puede reescribir formato, descartar comentarios y no conservar exactamente la interpolación Compose como lo haría el fichero fuente. Por tanto, la guía operativa depende de los valores guardados/renderizados reales, no de que comentarios o expresiones `${...}` sobrevivan a un ciclo de edición en la UI. Verifica la referencia/canal efectivo de la imagen después de guardar.

Cuando la App esté en ejecución, abre:

```text
http://<IP-LAN-o-malla-privada-de-TrueNAS>:7680
```

El puerto `7680` es el launcher. Codex se autentica de forma independiente en `7681`; Antigravity utiliza su propia autenticación independiente en `7682`. No expongas ninguno de estos puertos directamente a Internet.

Continúa con la [guía práctica de uso](docs/user-guide.es.md) para proyectos, sesiones/Resume, controles tmux/navegador, persistencia y herramientas propias del proyecto.

## Roles y puntos de entrada

Los puntos de entrada canónicos incluyen:

- `start-remote-dev-web`;
- `remote-dev-launcher`;
- `remote-dev-menu`;
- `remote-dev-doctor`;
- `remote-dev-healthcheck`.

`start-codex-web`, `codex-menu` y `codex-doctor` siguen como wrappers de compatibilidad que seleccionan Codex y llaman al runtime canónico.

Los roles implementados son:

```dotenv
REMOTE_DEV_ROLE=launcher
# o: codex
# o: antigravity
# o: shell
```

`claude` sigue reservado y sin implementar.

Los servicios de agente aceptan `REMOTE_DEV_START_MODE=menu|agent|shell`; el launcher acepta solo `menu`. Los roles/modos desconocidos se rechazan en vez de evaluarse como fragmentos shell editables.

## Workspaces por proyecto

`/workspace` es la **raíz privada que agrupa proyectos** del rol de agente actual. Las sesiones normales se ejecutan desde un hijo directo validado, por ejemplo `/workspace/pollenlevels`; `/workspace` no se trata como repositorio implícito.

El menú **Projects...** puede seleccionar, crear o eliminar —con confirmación exacta del nombre— directorios de proyecto hijos directos validados. La detección es deliberadamente no recursiva. Se rechazan symlinks, traversal y selectores absolutos arbitrarios.

Para modo agente directo, fija un proyecto cuando exista más de uno:

```dotenv
REMOTE_DEV_PROJECT=pollenlevels
```

Sin selector explícito, el modo agente directo resuelve automáticamente exactamente un proyecto válido y falla de forma clara en los demás casos.

Seleccionar proyecto elige directorio de trabajo; **no** crea aislamiento de sistema de archivos frente a proyectos hermanos ya montados dentro del mismo contenedor de rol. Codex y Antigravity reciben montajes de workspace escribibles separados, por lo que el mismo repositorio lógico debería utilizar clones/worktrees separados por rol en lugar de un único checkout escribible concurrentemente.

## Launcher y autenticación web

El launcher solo navega. No actúa como proxy de ttyd, no gestiona contenedores y no recibe estado de agentes. Comprueba same-origin cuando existe cabecera `Origin` y aplica una Content Security Policy restrictiva.

Cada endpoint de agente protegido utiliza un único `WEB_PASSWORD` basado en configuración. El Compose genérico mapea el `WEB_PASSWORD` externo de Codex y un `ANTIGRAVITY_WEB_PASSWORD` distinto a sus servicios respectivos. Las credenciales no se incluyen en enlaces, no pasan por el launcher y no se copian entre roles.

`WEB_PASSWORD_FILE`, `/run/secrets/web_password`, los secrets Compose de contraseña web y el antiguo árbol persistente de ficheros de contraseña están retirados.

La autenticación Basic opcional del launcher sigue disponible para despliegues avanzados del Compose genérico mediante `compose/launcher-auth.yml`. Usa un `LAUNCHER_PASSWORD` distinto mapeado al propio `WEB_PASSWORD` del launcher y no añade bind mounts ni secrets persistentes.

## Modos de aprobación de Codex

Los modos soportados por el launcher de comandos del proyecto son:

```dotenv
REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous
# o: guarded
```

- `autonomous` se traduce a `--ask-for-approval never`.
- `guarded` marca como no confiable solo el proyecto activo durante ese lanzamiento, de modo que Codex pide aprobación salvo que una regla explícita de exec-policy permita el comando.

Start y Resume pasan el proyecto seleccionado como directorio de trabajo de Codex. El menú puede conservar el modo del despliegue o elegir un override autonomous/guarded solo para el siguiente lanzamiento; esa elección puntual no reescribe la configuración permanente.

Comandos equivalentes:

```bash
run-codex --cd /workspace/pollenlevels --approval-mode autonomous
run-codex --cd /workspace/pollenlevels --approval-mode guarded resume
run-codex --print-policy
```

El comando upstream `/permissions` cambia el perfil de permisos del proceso Codex activo; no sustituye el resolver de despliegue/siguiente lanzamiento de Remote Dev.

## Actualizaciones explícitas del runtime de Codex

El `/usr/local/bin/codex` probado con la imagen permanece inmutable. Desde el menú o `remote-dev-codex-runtime`, un administrador puede instalar/actualizar/eliminar explícitamente un runtime oficial compatible más nuevo.

Un runtime admitido más nuevo puede aparecer como **official source; Remote Dev review pending**: ha superado la admisión acotada de origen/integridad/paquete/compatibilidad, pero esa release upstream exacta aún no tiene la evidencia de revisión/despliegue de la imagen. El estado opcional dañado o modificado localmente se rechaza y un runtime opcional igual o más antiguo nunca oculta el CLI incluido.

El runtime opcional vive en el montaje privado de Codex `state/codex/runtime`, separado de `CODEX_HOME`, y nunca sustituye el fallback incluido. Consulta [`docs/codex-runtime-updates.es.md`](docs/codex-runtime-updates.es.md).

## Antigravity — opcional y experimental

Antigravity está implementado, no reservado, pero continúa deliberadamente **experimental**.

Su Start/Resume por proyecto, continuidad útil de conversación, instalación/actualización explícitas, rollback de imagen, persistencia y validación amplia de ciclo de vida/aislamiento en TrueNAS están completados. El modelo endurecido de admisión #96 y la reconciliación humana #53 de términos/política actuales también están completados.

La interpretación de soporte aceptada por Remote Dev es estrecha:

- utilizar el CLI/runtime oficial de Google `agy` obtenido por la ruta oficial revisada;
- mantener instalación/actualización explícitas e iniciadas por el usuario;
- mantener desactivada la actualización automática del proveedor en sesiones soportadas;
- no redistribuir bytes propietarios del instalador/CLI de Google dentro de la imagen o el repositorio;
- no implementar un cliente alternativo del servicio Antigravity;
- no reutilizar/exportar OAuth de Google/Antigravity para Codex, Claude Code, OpenCode, OpenClaw u otro servicio de terceros;
- mantener credenciales/estado privados por rol y las salvaguardas de admisión/integridad;
- conservar el texto de no afiliación y de términos/privacidad del proveedor;
- no describir la evidencia de revisión de Remote Dev como firma, certificación o respaldo de Google.

El proyecto registra esto como interpretación humana de riesgo/soporte, no como aprobación legal del proveedor.

La automatización programada #83 ya está publicada. Su descubrimiento diario valida/descarga bytes acotados de instalador/manifest/archive como **datos**, calcula los hashes de instalador y payload `agy` y no ejecuta código del proveedor. Si cambia el par, solo se propone metadata. La inspección ejecutable requiere el workflow explícito de revisión confiable, que resuelve y verifica el par pendiente exacto antes de ejecutar.

Consulta [`docs/antigravity-runtime-admission.es.md`](docs/antigravity-runtime-admission.es.md) y [`third_party/optional-agents.md`](third_party/optional-agents.md).

## Context7 para Codex

El MCP hospedado de Context7 y el onboarding opcional por código de dispositivo están publicados para Codex.

Remote Dev no conserva un runtime/paquete Context7 en la imagen. El login explícito por dispositivo puede descargar/ejecutar el CLI transitorio `ctx7` revisado dentro de estado aislado desechable, adoptar únicamente la API key resultante validada dentro de la configuración privada gestionada de Codex y limpiar después el paquete/login/cache transitorios del proveedor.

Context7 es un servicio externo operado por Upstash. Consulta [`docs/context7-codex.es.md`](docs/context7-codex.es.md) y [`docs/context7-codex.md`](docs/context7-codex.md) para los límites de privacidad, términos, flujo de datos y credenciales.

## Aislamiento en TrueNAS

La imagen predeterminada no instala Bubblewrap del sistema. Los lanzamientos soportados de Codex desactivan explícitamente el sandbox interno no soportado; el contenedor Docker exterior y sus montajes estrechos son el límite de aislamiento soportado.

El modo autonomous puede actuar sobre todo lo montado dentro del servicio Codex sin confirmaciones. Guarded añade fricción de confirmación pero no es un sandbox de sistema de archivos.

Los contenedores de producción launcher, Codex y Antigravity usan root filesystem de solo lectura, `no-new-privileges`, `cap_drop: [ALL]`, sin grupos suplementarios, montajes privados por rol y límites acotados de PID/tmpfs/shm. El launcher se ejecuta como UID/GID `65532` sin capacidades restauradas. Los agentes restauran únicamente el mínimo exacto revisado necesario para propiedad/endurecimiento de estado privado y trabajo acotado de admisión sin privilegios.

No añadas modo privilegiado, `SYS_ADMIN`, perfiles unconfined, host networking/PID ni socket Docker/Podman para forzar un sandbox interno.

Consulta [`docs/security.md`](docs/security.md) para el modelo exacto de capacidades/tmpfs/montajes.

## Layout canónico de datos persistentes

El Compose genérico utiliza una única raíz administrativa:

```dotenv
REMOTE_DEV_DATA_ROOT=../data
```

La parte de Codex es:

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

Antigravity utiliza hijos privados correspondientes y disjuntos. La raíz padre de datos, `/root`, `/home`, `/mnt`, la raíz del host y los sockets del motor de contenedores nunca se montan de forma global.

Las contraseñas web son configuración del despliegue, no forman parte de `REMOTE_DEV_DATA_ROOT`.

`scripts/lib/data_layout.py` es el contrato canónico de rutas del host consumido por inicializador y preflight. No existe migración/copia/borrado automático de estado experimental. Utiliza el procedimiento de migración documentado para cualquier contrato que cambie en disco.

## Licencias y software opcional de proveedores

El código del proyecto Remote Dev usa Apache-2.0. El software upstream incluido conserva sus propias licencias/notices.

Inspecciona inventario/notices con:

```bash
remote-dev-notices
remote-dev-notices --list
remote-dev-notices --check
```

Google Antigravity, Claude Code y otros productos propietarios no quedan cubiertos por la licencia Apache-2.0 del repositorio. La integración actual de Antigravity descarga su runtime únicamente después de una acción explícita del usuario mediante la ruta de proveedor revisada y no redistribuye esos bytes. Las futuras integraciones propietarias opcionales deben seguir la misma política de fuente explícita, términos/privacidad, aislamiento de credenciales y no afiliación de [`third_party/optional-agents.md`](third_party/optional-agents.md).

## Build local

```bash
cp .env.example .env
chmod 600 .env
mkdir -p \
  data/workspaces/codex/example-project \
  data/state/codex/{agent,gh,git,ssh}
sudo install -d -o root -g root -m 0700 data/state/codex/runtime
# Edita .env y configura un WEB_PASSWORD no vacío y específico de Codex.
make preflight
./scripts/build-local.sh
```

Configura `REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous` o `guarded`, usa `REMOTE_DEV_IMAGE=remote-dev:local` y arranca:

```bash
docker compose -f compose/docker-compose.yml up -d
```

Abre el puerto `7680`, selecciona Codex y autentícate en su endpoint separado `7681`.

Para proteger también el launcher, configura credenciales distintas y añade el override revisado:

```dotenv
LAUNCHER_USERNAME=remote-dev
LAUNCHER_PASSWORD=replace-with-a-distinct-launcher-password
```

```bash
docker compose \
  -f compose/docker-compose.yml \
  -f compose/launcher-auth.yml \
  up -d
```

Para habilitar el perfil genérico de Antigravity, configura un `ANTIGRAVITY_WEB_PASSWORD` distinto y sigue las instrucciones experimentales de Antigravity. Nunca reutilices silenciosamente la contraseña de Codex entre endpoints.

## Pruebas públicas con edge

El canal AMD64 público integrado es:

```bash
docker pull ghcr.io/experience83/remote-dev:edge-amd64
```

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:edge-amd64
```

Los tags GHCR son mutables. Para reproducción/rollback exactos, registra el digest publicado y utiliza:

```text
ghcr.io/experience83/remote-dev@sha256:<digest>
```

Las revisiones publicadas de `main` también reciben:

```text
ghcr.io/experience83/remote-dev:sha-<full-commit-sha>
```

Una identidad runtime edge normal separa ahora identidad del build y canal de madurez:

```text
Image version: edge-YYYY.MM.DD-<7-char-sha>
Channel: edge
Source revision: <full-commit-sha>
Codex CLI: codex-cli <bundled-version>
```

`latest` **no** es edge. El contrato permanente es `dev -> edge -> stable = latest`; `stable`/`latest` solo se mueven tras una publicación SemVer estable explícita.

Consulta [`docs/releases.es.md`](docs/releases.es.md) para publicación de candidatos, procedencia de changelog del updater/Renovate, criterios de promoción y rollback.

## Advertencias importantes

- No publiques los puertos 7680, 7681 ni 7682 directamente en Internet.
- Vincula el launcher sin contraseña únicamente a localhost, una LAN de confianza o una malla privada como Tailscale.
- Los terminales Codex y Antigravity siguen autenticándose de forma independiente con contraseñas configuradas distintas.
- El launcher nunca embebe ni reenvía una contraseña de agente y no convierte los terminales de agentes en una aplicación same-origin.
- No montes estado de agentes ni runtime opcional dentro del launcher.
- Seleccionar proyecto cambia el directorio de trabajo; no aísla proyectos hermanos ya montados en el mismo `/workspace`.
- No compartas por defecto un único checkout escribible entre servicios de agente; usa clones/worktrees separados.
- No montes socket Docker/Podman ni uses modo privilegiado.
- El root del agente está limitado por el contenedor exterior de rol y sus montajes; cualquiera con acceso al terminal puede utilizar las credenciales visibles para ese servicio.
- Los administradores TrueNAS/Docker pueden inspeccionar la configuración del despliegue y están dentro del límite de confianza del host.
- `auth.json`, tokens GitHub, claves Context7 y claves SSH son secretos.
- Los agentes opcionales propietarios no están incluidos ni cubiertos por la licencia Apache-2.0 del proyecto.
- Antigravity continúa experimental aunque sus gates técnicos de lifecycle/admisión estén implementados.
- `edge` sigue siendo experimental y puede moverse después de cambios integrados; todavía no existe release estable.

## Desarrollo y revisiones

El desarrollo se realiza mediante pull requests. CodeRabbit está configurado para áreas sensibles del repositorio, pero la revisión automatizada es consultiva; CI del repositorio, gates exactos de workflows y la validación humana/real requerida siguen siendo autoritativos.

Lee `AGENTS.md` y `CONTRIBUTING.md` antes de proponer cambios.

## Documentación

- [`PROJECT_STATUS.md`](PROJECT_STATUS.md)
- [`docs/architecture.md`](docs/architecture.md)
- [`docs/security.md`](docs/security.md)
- [`docs/tool-matrix.md`](docs/tool-matrix.md)
- [`docs/decisions.md`](docs/decisions.md)
- [`docs/releases.md`](docs/releases.md) / [`docs/releases.es.md`](docs/releases.es.md)
- [`docs/user-guide.md`](docs/user-guide.md) / [`docs/user-guide.es.md`](docs/user-guide.es.md)
- [`docs/codex-runtime-updates.md`](docs/codex-runtime-updates.md) / [`docs/codex-runtime-updates.es.md`](docs/codex-runtime-updates.es.md)
- [`docs/context7-codex.md`](docs/context7-codex.md) / [`docs/context7-codex.es.md`](docs/context7-codex.es.md)
- [`docs/antigravity-runtime-admission.md`](docs/antigravity-runtime-admission.md) / [`docs/antigravity-runtime-admission.es.md`](docs/antigravity-runtime-admission.es.md)
- [`docs/truenas-acl-contract.md`](docs/truenas-acl-contract.md) / [`docs/truenas-acl-contract.es.md`](docs/truenas-acl-contract.es.md)
- [`docs/dependency-automation.md`](docs/dependency-automation.md)
- [`docs/roadmap.md`](docs/roadmap.md)
- [`third_party/README.md`](third_party/README.md)
- [`third_party/optional-agents.md`](third_party/optional-agents.md)
- `CHANGELOG.md`, `SECURITY.md`, `CONTRIBUTING.md`, `AGENTS.md`

## Referencias upstream

- OpenAI Codex: https://github.com/openai/codex
- Documentación de Codex: https://developers.openai.com/codex/cli
- GitHub CLI: https://github.com/cli/cli
- ttyd: https://github.com/tsl0922/ttyd
- mise: https://github.com/jdx/mise
