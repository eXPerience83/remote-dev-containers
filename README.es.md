# Remote Dev Containers — inicio v0.1

Entorno comunitario de agentes de programación accesible desde navegador para Docker, NAS y homelab.

> [!WARNING]
> **Desarrollo activo / experimental.** Todavía no existe una versión estable. Las imágenes públicas `edge` pueden cambiar o romperse sin previo aviso y aún no han completado toda la validación de TrueNAS, seguridad y persistencia. No expongas ningún puerto web directamente a Internet. Este proyecto no está afiliado ni respaldado por OpenAI, Google o Anthropic.

## Objetivo

Mantener las herramientas, los repositorios y los agentes de programación en un Docker remoto para que el ordenador personal solo necesite navegador.

## Implementación actual

El stack edge actual mantiene Codex como implementación de referencia y permite Antigravity únicamente como rol experimental habilitado de forma explícita:

```text
Stack Remote Dev
├── launcher      → puerto principal 7680
├── codex         → terminal autenticado 7681
└── antigravity   → terminal autenticado experimental opcional 7682
```

- El launcher es la entrada normal desde el navegador y no requiere contraseña por defecto.
- Codex se ejecuta en su propio contenedor con montajes privados y separados por rol.
- Antigravity puede ejecutarse en un contenedor opcional separado, con workspace/estado privados y un runtime del proveedor instalado solo mediante una acción explícita.
- Docker reutiliza la misma imagen y sus mismas capas para todos los servicios habilitados.
- Cada terminal de agente conserva su propia autenticación independiente.
- La imagen incluye Ubuntu 26.04 LTS, Codex CLI fijado y verificado, más una ruta explícita y opcional para instalar un runtime oficial más nuevo manteniendo el Codex incluido como fallback, además de GitHub CLI, Python 3.14, Node 24, uv, mise, ttyd y tmux.
- La persistencia utiliza un único contrato canónico y neutral.
- Los agentes seleccionan un proyecto concreto por debajo de su `/workspace` privado en lugar de arrancar en la raíz que agrupa los proyectos.
- AMD64 continúa siendo la arquitectura inicial.

## Instalar en TrueNAS SCALE

Utiliza [`compose/truenas.yml`](compose/truenas.yml) como **YAML canónico de Custom App para TrueNAS**. No mantengas una copia independiente del stack dentro del README.

La documentación actual de TrueNAS expone la instalación mediante Compose YAML desde **Apps → Discover Apps → ⋮ → Install via YAML**. Pon un nombre a la Custom App, pega el contenido de `compose/truenas.yml` en **Custom Config**, revisa los valores específicos del host indicados abajo y guarda la app solo después de que el preflight del layout del host sea correcto.

### 1. Crea únicamente el dataset raíz en TrueNAS

Crea un dataset administrado por el usuario, por ejemplo:

```text
Pool1/remote-dev
```

que normalmente aparecerá en el host como:

```text
/mnt/Pool1/remote-dev
```

La raíz debe existir antes de ejecutar el bootstrap de Remote Dev. `scripts/init-data-layout.py` se niega expresamente a crear implícitamente esa raíz, un padre inexistente o un dataset ZFS.

Las rutas necesarias por debajo de esa raíz pueden ser **directorios normales** o **datasets hijos** creados deliberadamente. La instalación sencilla recomendada utiliza un único dataset ZFS (`Pool1/remote-dev`) y deja que el bootstrap cree como directorios normales los descendientes de `workspaces/` y `state/`. Si un administrador crea alguno de esos descendientes como dataset hijo para disponer de un límite específico de snapshots, cuotas o replicación, Remote Dev acepta la ruta existente y no la sustituye, no cambia sus permisos y no modifica su contenido existente.

No crees symlinks en ningún componente de las rutas persistentes requeridas.

### 2. Usa bootstrap y preflight de la misma revisión de código fuente

La imagen seleccionada, `compose/truenas.yml`, `scripts/init-data-layout.py`, `scripts/preflight-data-layout.py` y `scripts/lib/data_layout.py` deben corresponder a la misma revisión del repositorio. No combines una imagen fijada a una revisión con scripts descargados después desde una rama móvil como `main`.

Si trabajas desde un checkout del repositorio, usa la misma revisión que contiene la imagen y ejecuta los scripts desde ese checkout. Para una validación exacta de candidato/digest, el [runbook de validación de TrueNAS](docs/truenas-antigravity-validation.md) explica cómo leer la revisión embebida en la imagen y obtener los archivos del host correspondientes.

Para el YAML de referencia, que declara Codex y Antigravity experimental, ejecuta desde la shell de TrueNAS después de crear el dataset raíz:

```bash
sudo python3 scripts/init-data-layout.py \
  --root /mnt/Pool1/remote-dev \
  --include-antigravity

python3 scripts/preflight-data-layout.py \
  --root /mnt/Pool1/remote-dev \
  --include-antigravity
```

El bootstrap crea únicamente los descendientes canónicos que falten y aplica modos iniciales solo a las rutas que él mismo crea. Es idempotente y no borra, migra, renombra, ni hace `chmod/chown` recursivo, ni reescribe el contenido existente de proyectos o estado. Volver a ejecutarlo es seguro y, cuando el layout ya está completo, debe indicar que no hacen falta cambios.

Después, el preflight valida el mismo contrato canónico y rechaza rutas ausentes, objetos que no sean directorios y symlinks antes del despliegue. Las contraseñas del navegador pertenecen a la configuración del despliegue y cada endpoint las valida al arrancar; bootstrap y preflight **no crean ni requieren un árbol `secrets/` para contraseñas web**.

Si mantienes intencionadamente un YAML local solo con Codex y sin el servicio Antigravity, omite `--include-antigravity` en ambos comandos. No omitas el flag si vas a desplegar sin cambios el YAML de referencia, porque sus bind sources de Antigravity también deben existir previamente.

### 3. Revisa los valores del YAML específicos del host

Antes de guardar la Custom App, revisa como mínimo:

- todas las IP de ejemplo `192.168.1.10` y sustitúyelas por la IP LAN o Tailscale del host TrueNAS;
- todas las fuentes bind `/mnt/Pool1/remote-dev` y cámbialas si tu pool/dataset utiliza otra ruta;
- `WEB_PASSWORD` de Codex y el `WEB_PASSWORD` independiente de Antigravity si mantienes el terminal experimental de Antigravity declarado en el YAML de referencia;
- zona horaria, identidad Git y modo de aprobación de Codex si los valores predeterminados no son adecuados;
- `REMOTE_DEV_PROJECT`: deja el valor literal del YAML vacío para el modo normal de menú. Para un proyecto fijo en modo directo, edita ese campo del YAML de TrueNAS. Un `REMOTE_DEV_PROJECT` ambiental de `.env` **no** sustituye este campo literal de `compose/truenas.yml`.

Un administrador de TrueNAS con privilegios suficientes puede inspeccionar la configuración guardada de la App o del contenedor. Ese administrador está dentro del límite de confianza de Remote Dev; por tanto, las capturas y exportaciones de YAML deben sanearse antes de compartirlas.

Cuando TrueNAS muestre la Custom App en ejecución, abre:

```text
http://<IP-LAN-o-Tailscale-de-TrueNAS>:7680
```

El puerto `7680` es el launcher. Codex continúa autenticándose de forma independiente en `7681`; el terminal experimental de Antigravity tiene su propia autenticación en `7682`. No expongas ninguno de estos puertos directamente a Internet.

Después de instalar, continúa con la [guía práctica de uso](docs/user-guide.es.md) para proyectos, sesiones/Resume de Codex, controles de tmux/navegador, `AGENTS.md`, persistencia y herramientas propias del proyecto.

Los detalles de la UI de Custom App/YAML pueden cambiar entre versiones de TrueNAS; la referencia upstream actual es la [documentación de Custom Apps de TrueNAS](https://www.truenas.com/docs/scale/apps/installcustomappscreens/).

### Puntos de entrada y roles

La implementación canónica utiliza:

- `start-remote-dev-web`;
- `remote-dev-launcher`;
- `remote-dev-menu`;
- `remote-dev-doctor`;
- `remote-dev-healthcheck`.

`start-codex-web`, `codex-menu` y `codex-doctor` continúan como wrappers de compatibilidad.

Los roles implementados son:

```dotenv
REMOTE_DEV_ROLE=launcher
# o: codex
# o: antigravity
# o: shell
```

`antigravity` está implementado como **rol opcional experimental**. Su Start/Resume por proyecto, continuidad de conversación, actualización/rollback y validación amplia del ciclo de vida en TrueNAS están completados; el rol sigue siendo experimental mientras se reconcilian los gates restantes de autenticación web, política del proveedor y documentación. Su runtime del proveedor solo se instala mediante una acción explícita del usuario y el arranque normal nunca lo descarga implícitamente. `claude` sigue reservado y sin implementar.

El launcher solo admite el modo `menu`. Los servicios de agente mantienen `REMOTE_DEV_START_MODE=menu|agent|shell` y la compatibilidad existente con `START_MODE=menu|codex|shell`.

### Workspaces y proyectos

`/workspace` es la **raíz privada que agrupa proyectos** del servicio de agente actual. Las sesiones normales del agente se ejecutan desde un hijo directo validado, por ejemplo `/workspace/pollenlevels`; `/workspace` ya no se trata implícitamente como si fuera un repositorio.

El menú del agente ofrece **Projects...** con acciones para seleccionar, crear o eliminar directorios de proyecto. La detección es deliberadamente no recursiva. Si existe exactamente un proyecto válido se selecciona automáticamente; si hay varios, debes elegir uno antes de Start/Resume. La selección actual dura únicamente durante esa sesión de menú/tmux.

Crear un proyecto solo crea un directorio hijo vacío. No ejecuta `git init`, no clona repositorios y no contacta con servicios remotos. El borrado es destructivo y exige escribir el nombre exacto del proyecto antes de eliminar todo el directorio. Los nombres se limitan a un único componente conservador: letras/dígitos ASCII y `.`, `_` o `-`, empezando por una letra o un dígito. Se rechazan enlaces simbólicos y rutas con traversal.

Para `REMOTE_DEV_START_MODE=agent` directo, indica un nombre de proyecto validado cuando exista más de uno:

```dotenv
REMOTE_DEV_PROJECT=pollenlevels
```

Sin selector explícito, el modo directo resuelve automáticamente un único proyecto y falla de forma clara si no hay ninguno o hay varios, en vez de arrancar en `/workspace`. El modo shell general continúa abriéndose en la raíz que agrupa proyectos.

Seleccionar un proyecto fija el directorio de trabajo predeterminado del agente; **no** crea un límite de aislamiento del sistema de archivos. Todo el montaje `/workspace` privado de ese rol sigue disponible dentro del contenedor del agente, por lo que los procesos que se ejecuten allí pueden acceder también a proyectos hermanos. Si necesitas aislamiento entre esos proyectos, utiliza servicios de rol o montajes separados.

Cada servicio de agente conserva su propio montaje de workspace escribible. Que el gestor de proyectos sea común **no** significa compartir el mismo checkout entre Codex, Antigravity u otros roles futuros. Si el mismo repositorio lógico debe usarse desde varios agentes, utiliza clones/worktrees independientes; no montes por defecto un único checkout escribible en varios servicios.

### Funcionamiento del launcher

La página del launcher no requiere autenticación por defecto porque es navegación sin estado: no contiene credenciales, no actúa como proxy y no monta datos privados de los agentes. Mantiene la comprobación de origen cuando el navegador envía la cabecera `Origin` y aplica una política CSP restrictiva.

Al pulsar **Open Codex**, el navegador navega al endpoint ttyd de Codex. El launcher no transporta el tráfico HTTP/WebSocket del terminal, no recibe el socket Docker y no monta el workspace, el estado de Codex, GitHub, Git, SSH, el runtime opcional de Codex ni la contraseña del terminal. Cuando se habilita Antigravity experimental, su terminal continúa siendo un endpoint independiente con autenticación, workspace y estado propios.

El terminal Codex se autentica de manera independiente con `WEB_PASSWORD`. Antigravity recibe su propio valor independiente. Las contraseñas nunca se incluyen en los enlaces, no se transmiten mediante el launcher y no se comparten entre servicios.

La autenticación Basic del launcher sigue siendo opcional para despliegues avanzados del Compose genérico mediante `compose/launcher-auth.yml`. El override mapea `LAUNCHER_PASSWORD` al `WEB_PASSWORD` privado del proceso launcher sin montar ficheros ni secretos persistentes. El ejemplo doméstico normal de TrueNAS no requiere una segunda contraseña ni dataset del launcher.

Las rutas configuradas del launcher y de los agentes se limitan a caracteres seguros de ruta URL antes de introducirse en la página. Antigravity sigue siendo experimental; Claude y un proxy de origen único siguen fuera de la implementación actual.

### Modos de aprobación de Codex

```dotenv
REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous
# o: guarded
```

- `autonomous` es el valor predeterminado y se traduce a `--ask-for-approval never`.
- `guarded` marca como no confiable solo el proyecto activo durante ese lanzamiento. Codex pide aprobación para los comandos salvo que una regla explícita de exec-policy los permita; `on-request` en un proyecto confiable no es el modo guarded de Remote Dev.

El menú separa **Start Codex** y **Resume a Codex session**, añade **Projects...** y mantiene **Approval mode for next launch**. Start y Resume pasan a Codex el proyecto seleccionado como directorio de trabajo, de modo que Codex arranca en `/workspace/<proyecto>` y lo utiliza como directorio predeterminado para detectar el repositorio y localizar `AGENTS.md`. Esta selección del directorio de trabajo no restringe el acceso al sistema de archivos a ese hijo; los proyectos hermanos del mismo `/workspace` montado siguen siendo accesibles. El selector de aprobación permite conservar el modo configurado o elegir autonomous/guarded únicamente para el siguiente inicio o reanudación. La selección puntual se consume al arrancar Codex y después el menú vuelve automáticamente al valor del despliegue. Nunca reescribe la configuración permanente.

La interfaz equivalente es:

```bash
run-codex --cd /workspace/pollenlevels --approval-mode autonomous
run-codex --cd /workspace/pollenlevels --approval-mode guarded resume
run-codex --print-policy
```

Los valores desconocidos y los flags directos de sandbox/aprobación se rechazan antes de iniciar Codex.

La interfaz de Codex también ofrece `/permissions`. Ese comando modifica el perfil de permisos activo dentro del proceso Codex en ejecución; no cambia `REMOTE_DEV_CODEX_APPROVAL_MODE` ni sustituye el resolver validado autonomous/guarded de Remote Dev. Utiliza el menú o la variable del despliegue para el comportamiento soportado y persistente entre nuevos procesos.

### Actualizaciones explícitas del runtime de Codex

El `/usr/local/bin/codex` probado con la imagen permanece inmutable. Desde el menú de Codex o mediante `remote-dev-codex-runtime install` / `remote-dev-codex-runtime update`, un administrador puede instalar explícitamente un paquete compatible más nuevo desde la release oficial de Codex de OpenAI. Ambos comandos utilizan la misma ruta de admisión acotada y piden confirmación antes de la primera petición de red del actualizador. `--yes` es la forma explícita no interactiva para `install`, `update` y `remove`.

Un paquete más nuevo admitido aparece como **fuente oficial; revisión de Remote Dev pendiente**. Eso significa que han pasado las comprobaciones de origen, digest de release, identidad del paquete y compatibilidad acotada, mientras que Remote Dev todavía no ha revisado ni probado en despliegue real esa release exacta como parte de una build de imagen. El estado opcional dañado o modificado localmente se rechaza, y un runtime igual o más antiguo nunca sustituye al Codex incluido.

El paquete opcional se guarda fuera de `CODEX_HOME` en un montaje exclusivo de estado de runtime de Codex, separando credenciales/configuración/sesiones e impidiendo que la ruta de autoactualización standalone de upstream pueda saltarse el gestor explícito del proyecto. Consulta `docs/codex-runtime-updates.es.md` para los estados de confianza, comprobaciones del paquete, fallback y eliminación.

## Aislamiento en TrueNAS

El launcher y Codex son contenedores separados. El launcher base solo recibe su configuración de navegación; no recibe secretos ni montajes de Codex. El override opcional de autenticación del launcher no añade montajes bind, persistentes ni de estado de agentes; conserva únicamente los tmpfs privados `/tmp` y `/run` del perfil de hardening.

La imagen no instala Bubblewrap del sistema. El lanzador de comandos de Codex desactiva expresamente el sandbox interno no compatible mediante `--sandbox danger-full-access`. El límite de seguridad soportado sigue siendo el contenedor exterior de Codex y sus montajes mínimos.

Los contenedores de producción usan un sistema de archivos raíz de solo lectura, `no-new-privileges`, `cap_drop: [ALL]`, ningún grupo suplementario, mounts privados por rol y límites PID explícitos (`64` para el launcher y `1024` para cada agente). El launcher arranca directamente como UID/GID `65532` y no recupera ninguna capability. Los terminales de agente root reciben solo `CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `KILL`, `SETGID` y `SETUID`; estas capacidades mantienen la propiedad y el endurecimiento de los bind mounts privados y la ejecución acotada de candidatos como UID/GID `65534`, no acceso al host.

Cada rol tiene tmpfs transitorios y privados para `/tmp` y `/run`. `/tmp` sigue siendo un sistema de archivos acotado con `noexec,nosuid,nodev`; `/run` de Codex permite deliberadamente ejecución para el staging acotado de actualizaciones de Codex y del login de dispositivo de Context7. Las sesiones normales de Codex y Antigravity usan en su lugar el árbol oculto `/workspace/.remote-dev-tmp`, respaldado por el workspace, para los temporales genéricos y las cachés de uv, npm y pip. Este scratch de desarrollo no confiable persiste con el workspace privado de su rol, queda excluido de la detección de proyectos y puede borrarse con el servicio detenido para recrearlo de forma limpia. El launcher no lo recibe. Las contraseñas web se suministran mediante variables específicas de cada servicio; no forman parte del árbol persistente.

No añadas modo privilegiado, `SYS_ADMIN`, perfiles sin restricciones, el socket Docker ni montajes amplios para intentar habilitar un sandbox anidado.

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
│       └── <proyecto>/
└── state/
    └── codex/
        ├── agent/
        ├── runtime/
        ├── gh/
        ├── git/
        └── ssh/
```

El servicio Codex monta `workspaces/codex` en `/workspace`; el gestor de proyectos opera únicamente sobre hijos directos validados de ese montaje. `state/codex/runtime` contiene el estado completo del runtime opcional de Codex gestionado por Remote Dev, incluido el puntero activo `current`, los directorios de releases conservados, los archivos del paquete y manifiestos privados de integridad como `remote-dev-runtime.json`; `state/codex/agent` sigue siendo `CODEX_HOME` para credenciales, configuración y sesiones. El launcher no tiene montajes bind, persistentes ni de estado de agentes; conserva únicamente sus tmpfs privados `/tmp` y `/run`. Nunca se montan de forma completa la raíz administrativa, `/root`, `/home`, `/mnt`, la raíz del host ni sockets del motor de contenedores.

`scripts/lib/data_layout.py` contiene la lista canónica del host que comparten `scripts/init-data-layout.py` y `scripts/preflight-data-layout.py`. En TrueNAS, normalmente solo la raíz configurada necesita ser un dataset ZFS; los descendientes requeridos pueden seguir siendo directorios normales o pueden existir ya como datasets hijos creados deliberadamente por el administrador. El inicializador nunca crea la raíz, nunca sustituye los descendientes existentes y solo aplica modos iniciales a las rutas que él crea. El preflight valida las rutas resultantes independientemente de que una ruta existente esté respaldada por el dataset raíz o por un dataset hijo independiente.

`state/codex/runtime` es un límite de confianza propiedad de root: debe ser un directorio real `root:root` con modo `0700`. El gestor de runtime rechaza un propietario inesperado en lugar de admitir estado opcional del runtime desde una identidad arbitraria del host. Antes de desplegar, ejecuta el bootstrap del host seguido del preflight. Los bind mounts también solicitan `create_host_path: false` como defensa adicional, pero el proyecto no presupone que todas las versiones de Compose respeten esa opción.

No existe migración automática ni alias para la estructura experimental anterior. El estado experimental debe moverse o recrearse manualmente. Si una instalación anterior conservaba ficheros de contraseña web, configura y valida primero los nuevos `WEB_PASSWORD`, comprueba stop/start o recreación y conserva cualquier copia necesaria únicamente durante la ventana de rollback. Cuando la migración esté confirmada, elimina manualmente esos ficheros obsoletos; Remote Dev no los borra automáticamente. El uso opcional de SMB/ACL queda aplazado al issue #71 y nunca debe exponer `state`; si se implementa más adelante, debe trabajar con proyectos concretos seleccionados y no exponer por defecto toda la raíz que los agrupa.

## Licencias y software opcional

El código propio de Remote Dev utiliza Apache-2.0. Ubuntu, Codex CLI, GitHub CLI, ttyd, mise, Python, Node.js, npm, uv y sus dependencias conservan sus licencias y avisos originales.

```bash
remote-dev-notices
remote-dev-notices --list
remote-dev-notices --check
```

Antigravity, Claude Code y productos similares no quedan cubiertos por la licencia Apache-2.0 del repositorio. La imagen actual no los descarga ni redistribuye. Cualquier integración futura debe iniciarse expresamente, descargar desde la fuente oficial y superar su revisión legal y técnica específica.

## Uso local

```bash
cp .env.example .env
chmod 600 .env
mkdir -p \
  data/workspaces/codex/proyecto-ejemplo \
  data/state/codex/{agent,gh,git,ssh}
sudo install -d -o root -g root -m 0700 data/state/codex/runtime
make preflight
./scripts/build-local.sh
```

Edita `.env` y define como mínimo una contraseña fuerte para Codex:

```dotenv
WEB_PASSWORD=contraseña-distinta-de-codex
```

Si habilitas el perfil de Antigravity, utiliza un valor diferente:

```dotenv
ANTIGRAVITY_WEB_PASSWORD=contraseña-distinta-de-antigravity
```

Para corregir un directorio de runtime vacío existente con propietario incorrecto, ejecuta únicamente:

```bash
sudo chown root:root data/state/codex/runtime
sudo chmod 0700 data/state/codex/runtime
```

Para una raíz personalizada, define `REMOTE_DEV_DATA_ROOT=/ruta/absoluta/del/host` en `.env` y ejecuta `make preflight DATA_ROOT=/ruta/absoluta/del/host` antes de desplegar. También puedes dejar inicialmente vacía `data/workspaces/codex` y crear el primer proyecto desde **Projects...** después de arrancar el servicio.

Define `REMOTE_DEV_IMAGE=remote-dev:local` y el modo de aprobación deseado, y ejecuta:

```bash
docker compose -f compose/docker-compose.yml up -d
```

1. Abre el launcher en el puerto publicado `7680`.
2. Pulsa Codex.
3. Autentícate en el terminal del puerto `7681` con `WEB_USERNAME` —por defecto `codex`— y el `WEB_PASSWORD` definido en `.env`.
4. Desde **Projects...** selecciona o crea el proyecto con el que quieres trabajar; el borrado exige escribir su nombre exacto.
5. Inicia o reanuda Codex dentro de ese proyecto con el modo configurado, selecciona autonomous o guarded para el próximo inicio, actualiza o elimina explícitamente el runtime oficial opcional manteniendo el fallback incluido, inicia sesión en Codex/GitHub o ejecuta diagnósticos.

Para proteger también el launcher en un despliegue avanzado del Compose genérico, define una contraseña distinta en el mismo `.env` protegido y añade el override revisado:

```dotenv
LAUNCHER_USERNAME=remote-dev
LAUNCHER_PASSWORD=contraseña-distinta-del-launcher
```

```bash
docker compose \
  -f compose/docker-compose.yml \
  -f compose/launcher-auth.yml \
  up -d
```

El override mapea ese valor al `WEB_PASSWORD` del launcher; no crea ni monta un secreto persistente y no sustituye ni reutiliza la contraseña del terminal Codex.

## Prueba pública de la imagen edge

```bash
docker pull ghcr.io/experience83/remote-dev:edge-amd64
```

Para Docker Compose o TrueNAS:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:edge-amd64
REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous
```

El único package runtime publicado en GHCR es `ghcr.io/experience83/remote-dev`. La variable heredada `CODEX_IMAGE` continúa aceptándose durante `v0.1.x` como fallback de configuración, pero debe apuntar al package canónico `remote-dev`. El antiguo package remoto `ghcr.io/experience83/codex-remote-dev` está retirado y puede eliminarse de GHCR una vez fusionado este cambio.

Para fijar un commit o digest:

```text
ghcr.io/experience83/remote-dev:sha-<commit-completo>
ghcr.io/experience83/remote-dev@sha256:<digest>
```

El launcher y los diagnósticos muestran la identidad embebida de la imagen. Desde una shell de Codex también puedes ejecutar:

```bash
remote-dev-version
```

Cuando exista un runtime opcional, el comando también muestra su versión, estado de confianza y la fuente activa.

## Advertencias importantes

- No expongas los puertos 7680, 7681 o el 7682 opcional directamente a Internet.
- El launcher sin contraseña solo debe publicarse en localhost, LAN o Tailscale.
- Cada terminal de agente sigue autenticado de forma independiente.
- El launcher no reenvía ni incluye en la URL la contraseña de Codex.
- El launcher no es un proxy y no convierte el terminal en una aplicación del mismo origen.
- No montes workspaces, credenciales de agente ni estado de runtime opcional en el launcher.
- Seleccionar un proyecto cambia el directorio de trabajo del agente; no aísla ese proyecto de los directorios hermanos montados bajo el mismo `/workspace`.
- No compartas por defecto un mismo checkout escribible entre servicios de agente; utiliza clones/worktrees independientes.
- El borrado de proyectos elimina por completo `/workspace/<proyecto>` después de confirmar el nombre exacto; haz commit o copia de seguridad de lo que necesites conservar.
- No montes el socket Docker ni uses modo privilegiado.
- En modo autónomo, Codex puede actuar sin confirmaciones sobre todo lo montado en su servicio.
- Las confirmaciones del modo protegido no son un sandbox.
- Un runtime opcional de Codex marcado como revisión pendiente ha superado admisión de procedencia, integridad y compatibilidad, pero esa release exacta todavía no ha completado la revisión y validación real de Remote Dev.
- `edge` sigue siendo experimental.

## Desarrollo y revisiones

El desarrollo se realiza mediante pull requests. CodeRabbit revisa Dockerfiles, Bash, el launcher Python, GitHub Actions, Compose y cambios sensibles de seguridad. CI y las pruebas manuales siguen siendo obligatorios.

Consulta `AGENTS.md`, `README.md`, `PROJECT_STATUS.md`, `CHANGELOG.md`, `docs/architecture.md`, `docs/security.md`, `docs/codex-runtime-updates.es.md` y `docs/roadmap.md` para el estado y los siguientes pasos.

## Documentación

- `AGENTS.md`
- `CHANGELOG.md`
- `CONTRIBUTING.md`
- `SECURITY.md`
- `PROJECT_STATUS.md`
- `third_party/README.md`
- `third_party/optional-agents.md`
- `docs/architecture.md`
- `docs/tool-matrix.md`
- `docs/security.md`
- `docs/decisions.md`
- `docs/releases.md`
- `docs/releases.es.md`
- `docs/runtime-locks.md`
- `docs/user-guide.md`
- `docs/user-guide.es.md`
- `docs/codex-runtime-updates.md`
- `docs/codex-runtime-updates.es.md`
- `docs/context7-codex.md`
- `docs/context7-codex.es.md`
- `docs/roadmap.md`
