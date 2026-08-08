# Remote Dev Containers — inicio v0.1

Entorno comunitario de agentes de programación accesible desde navegador para Docker, NAS y homelab.

> [!WARNING]
> **Desarrollo activo / experimental.** Todavía no existe una versión estable. Las imágenes públicas `edge` pueden cambiar o romperse sin previo aviso y aún no han completado toda la validación de TrueNAS, seguridad y persistencia. No expongas ninguno de los dos puertos web directamente a Internet. Este proyecto no está afiliado ni respaldado por OpenAI, Google o Anthropic.

## Objetivo

Mantener las herramientas, los repositorios y los agentes de programación en un Docker remoto para que el ordenador personal solo necesite navegador.

## Implementación actual

El stack edge actual utiliza una única imagen de Remote Dev para dos servicios:

```text
Stack Remote Dev
├── launcher  → puerto principal 7680
└── codex     → terminal autenticado 7681
```

- El launcher es la entrada normal desde el navegador y no requiere contraseña por defecto.
- Codex se ejecuta en su propio contenedor con montajes privados y separados por rol.
- Docker reutiliza la misma imagen y sus mismas capas para ambos servicios.
- El terminal Codex conserva su propia autenticación independiente.
- La imagen incluye Ubuntu 26.04 LTS, Codex CLI fijado y verificado, más una ruta explícita y opcional para instalar un runtime oficial más nuevo manteniendo el Codex incluido como fallback, además de GitHub CLI, Python 3.14, Node 24, uv, mise, ttyd y tmux.
- La persistencia utiliza un único contrato canónico y neutral.
- AMD64 continúa siendo la arquitectura inicial.

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
# o: shell
```

`antigravity` y `claude` siguen reservados y fallan de forma clara. Nunca provocan una descarga implícita.

El launcher solo admite el modo `menu`. Los servicios de agente mantienen `REMOTE_DEV_START_MODE=menu|agent|shell` y la compatibilidad existente con `START_MODE=menu|codex|shell`.

### Funcionamiento del launcher

La página del launcher no requiere autenticación por defecto porque es navegación sin estado: no contiene credenciales, no actúa como proxy y no monta datos privados de los agentes. Mantiene la comprobación de origen cuando el navegador envía la cabecera `Origin` y aplica una política CSP restrictiva.

Al pulsar **Open Codex**, el navegador navega al endpoint ttyd de Codex. El launcher no transporta el tráfico HTTP/WebSocket del terminal, no recibe el socket Docker y no monta el workspace, el estado de Codex, GitHub, Git, SSH, el runtime opcional de Codex ni la contraseña del terminal.

El terminal Codex se autentica de manera independiente mediante su propia fuente de contraseña. La contraseña nunca se incluye en el enlace, no se transmite mediante el launcher y no se comparte entre los servicios.

La autenticación Basic del launcher sigue siendo opcional para despliegues avanzados del Compose genérico mediante el override separado y respaldado por secreto `compose/launcher-auth.yml`. El ejemplo doméstico normal de TrueNAS no requiere una segunda contraseña, secreto, mount ni dataset del launcher.

Las rutas configuradas se limitan a caracteres seguros de ruta URL antes de introducirse en la página. Antigravity/Claude y un proxy de origen único siguen fuera de la implementación actual.

### Modos de aprobación de Codex

```dotenv
REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous
# o: guarded
```

- `autonomous` es el valor predeterminado y se traduce a `--ask-for-approval never`.
- `guarded` se traduce a `--ask-for-approval untrusted`.

El menú separa **Start Codex** y **Resume a Codex session** y añade **Approval mode for next launch**. Ese selector permite conservar el modo configurado o elegir autonomous/guarded únicamente para el siguiente inicio o reanudación. La selección puntual se consume al arrancar Codex y después el menú vuelve automáticamente al valor del despliegue. Nunca reescribe la configuración permanente.

La interfaz equivalente es:

```bash
run-codex --approval-mode autonomous
run-codex --approval-mode guarded resume
run-codex --print-policy
```

Los valores desconocidos y los flags directos de sandbox/aprobación se rechazan antes de iniciar Codex.

La interfaz de Codex también ofrece `/permissions`. Ese comando modifica el perfil de permisos activo dentro del proceso Codex en ejecución; no cambia `REMOTE_DEV_CODEX_APPROVAL_MODE` ni sustituye el resolver validado autonomous/guarded de Remote Dev. Utiliza el menú o la variable del despliegue para el comportamiento soportado y persistente entre nuevos procesos.

### Actualizaciones explícitas del runtime de Codex

El `/usr/local/bin/codex` probado con la imagen permanece inmutable. Desde el menú de Codex o mediante `remote-dev-codex-runtime update`, un administrador puede instalar explícitamente un paquete compatible más nuevo desde la release oficial de Codex de OpenAI. La acción de actualización pide confirmación antes de la primera petición de red del actualizador.

Un paquete más nuevo admitido aparece como **fuente oficial; revisión de Remote Dev pendiente**. Eso significa que han pasado las comprobaciones de origen, digest de release, identidad del paquete y compatibilidad acotada, mientras que Remote Dev todavía no ha revisado ni probado en despliegue real esa release exacta como parte de una build de imagen. El estado opcional dañado o modificado localmente se rechaza, y un runtime igual o más antiguo nunca sustituye al Codex incluido.

El paquete opcional se guarda fuera de `CODEX_HOME` en un montaje exclusivo de estado de runtime de Codex, separando credenciales/configuración/sesiones e impidiendo que la ruta de autoactualización standalone de upstream pueda saltarse el gestor explícito del proyecto. Consulta `docs/codex-runtime-updates.es.md` para los estados de confianza, comprobaciones del paquete, fallback y eliminación.

## Aislamiento en TrueNAS

El launcher y Codex son contenedores separados. El launcher base solo recibe su configuración de navegación; no recibe secretos ni montajes de Codex. El override opcional de autenticación del launcher añade únicamente su propio secreto de contraseña en modo solo lectura.

La imagen no instala Bubblewrap del sistema. El lanzador de comandos de Codex desactiva expresamente el sandbox interno no compatible mediante `--sandbox danger-full-access`. El límite de seguridad soportado sigue siendo el contenedor exterior de Codex y sus montajes mínimos.

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
├── state/
│   └── codex/
│       ├── agent/
│       ├── runtime/
│       ├── gh/
│       ├── git/
│       └── ssh/
└── secrets/
    └── codex/
        └── web_password.txt
```

El servicio Codex monta exclusivamente esos directorios hijo. `state/codex/runtime` contiene únicamente el paquete opcional de Codex gestionado por Remote Dev y su manifiesto privado de integridad; `state/codex/agent` sigue siendo `CODEX_HOME` para credenciales, configuración y sesiones. El launcher base no tiene montajes. Nunca se montan de forma completa la raíz administrativa, `/root`, `/home`, `/mnt`, la raíz del host ni sockets del motor de contenedores.

Antes de desplegar, ejecuta el preflight del host. Verifica todos los directorios necesarios, rechaza enlaces simbólicos y comprueba que la contraseña sea un archivo normal, no vacío y con permisos restrictivos. Los bind mounts también solicitan `create_host_path: false` como defensa adicional, pero el proyecto no presupone que todas las versiones de Compose respeten esa opción.

No existe migración automática ni alias para la estructura experimental anterior. El estado experimental debe moverse o recrearse manualmente. El uso opcional de SMB/ACL queda aplazado al issue #71 y nunca debe exponer `state` ni `secrets`.

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
mkdir -p \
  data/workspaces/codex \
  data/state/codex/{agent,runtime,gh,git,ssh} \
  data/secrets/codex
printf '%s\n' 'contraseña-de-codex' > data/secrets/codex/web_password.txt
chmod 600 data/secrets/codex/web_password.txt
make preflight
./scripts/build-local.sh
```

Para una raíz personalizada, ejecuta `make preflight DATA_ROOT=/ruta/absoluta/del/host` antes de desplegar.

Define `REMOTE_DEV_IMAGE=remote-dev:local` y el modo de aprobación deseado, y ejecuta:

```bash
docker compose -f compose/docker-compose.yml up -d
```

1. Abre el launcher en el puerto publicado `7680`.
2. Pulsa Codex.
3. Autentícate en el terminal del puerto `7681` con `WEB_USERNAME` —por defecto `codex`— y la contraseña de `web_password.txt`.
4. Desde el menú inicia o reanuda con el modo configurado, selecciona autonomous o guarded para el próximo inicio, actualiza o elimina explícitamente el runtime oficial opcional de Codex manteniendo el fallback incluido, inicia sesión en Codex y GitHub y ejecuta diagnósticos.

Para proteger también el launcher en un despliegue avanzado del Compose genérico, crea un archivo de contraseña distinto y añade el override revisado:

```bash
mkdir -p secrets
printf '%s\n' 'contraseña-distinta-del-launcher' > secrets/launcher_password.txt
chmod 600 secrets/launcher_password.txt
docker compose \
  -f compose/docker-compose.yml \
  -f compose/launcher-auth.yml \
  up -d
```

El override monta el valor como secreto Compose en `/run/secrets/launcher_password`; no incluye la contraseña en el entorno renderizado y no sustituye ni reutiliza la contraseña del terminal Codex.

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

- No expongas los puertos 7680 o 7681 directamente a Internet.
- El launcher sin contraseña solo debe publicarse en localhost, LAN o Tailscale.
- Codex sigue autenticado de forma independiente.
- El launcher no reenvía ni incluye en la URL la contraseña de Codex.
- El launcher no es un proxy y no convierte el terminal en una aplicación del mismo origen.
- No montes workspaces, credenciales de agente ni estado de runtime opcional en el launcher.
- No montes el socket Docker ni uses modo privilegiado.
- En modo autónomo, Codex puede actuar sin confirmaciones sobre todo lo montado en su servicio.
- Las confirmaciones del modo protegido no son un sandbox.
- Un runtime opcional de Codex marcado como revisión pendiente ha superado admisión de procedencia, integridad y compatibilidad, pero esa release exacta todavía no ha completado la revisión y validación real de Remote Dev.
- `edge` sigue siendo experimental.

## Desarrollo y revisiones

El desarrollo se realiza mediante pull requests. CodeRabbit revisa Dockerfiles, Bash, el launcher Python, GitHub Actions, Compose y cambios sensibles de seguridad. CI y las pruebas manuales siguen siendo obligatorios.

Consulta `AGENTS.md`, `README.md`, `PROJECT_STATUS.md`, `CHANGELOG.md`, `docs/architecture.md`, `docs/security.md`, `docs/codex-runtime-updates.es.md` y `docs/roadmap.md` para el estado y los siguientes pasos.
