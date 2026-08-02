# Remote Dev Containers — inicio v0.1

Entorno comunitario de Codex CLI accesible desde navegador para Docker, NAS y homelab.

> [!WARNING]
> **Desarrollo activo / experimental.** Todavía no existe una versión estable. Las imágenes públicas `edge` pueden cambiar o romperse sin previo aviso y aún no han completado toda la validación de TrueNAS, seguridad y persistencia. No expongas ninguno de los dos puertos web directamente a Internet. Este proyecto no está afiliado ni respaldado por OpenAI.

## Objetivo

Mantener Codex, las herramientas y los repositorios en un Docker remoto para que el ordenador personal solo necesite navegador.

## Implementación actual

El stack edge actual utiliza una única imagen de Remote Dev para dos servicios:

```text
Stack Remote Dev
├── launcher  → puerto principal 7680
└── codex     → terminal autenticado 7681
```

- El launcher es la entrada normal desde el navegador y no requiere contraseña por defecto.
- Codex sigue ejecutándose en su propio contenedor con sus montajes privados actuales.
- Docker reutiliza la misma imagen y sus mismas capas para ambos servicios.
- El terminal Codex conserva su propia autenticación independiente.
- La imagen incluye Ubuntu 26.04 LTS, Codex CLI fijado y verificado, GitHub CLI, Python 3.14, Node 24, uv, mise, ttyd y tmux.
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

Al pulsar **Open Codex**, el navegador navega al endpoint ttyd de Codex. El launcher no transporta el tráfico HTTP/WebSocket del terminal, no recibe el socket Docker y no monta el workspace, el estado de Codex, GitHub, Git, SSH ni la contraseña del terminal.

El terminal Codex se autentica de manera independiente mediante su propio secreto. La contraseña nunca se incluye en el enlace, no se transmite mediante el launcher y no se comparte entre los servicios.

La autenticación Basic del launcher sigue siendo opcional en el Compose genérico mediante `LAUNCHER_PASSWORD` y `LAUNCHER_ALLOW_INSECURE_WEB=0`. No es necesaria para el ejemplo doméstico de TrueNAS en una LAN o a través de Tailscale.

Las rutas configuradas se limitan a caracteres seguros de ruta URL antes de introducirse en la página. Esta fase todavía no cambia las rutas persistentes actuales, no migra `CODEX_DATA_ROOT`, no añade Antigravity/Claude y no incorpora un proxy de origen único.

### Modos de aprobación de Codex

```dotenv
REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous
# o: guarded
```

- `autonomous` es el valor predeterminado y se traduce a `--ask-for-approval never`.
- `guarded` se traduce a `--ask-for-approval untrusted`.

El menú inicia o reanuda Codex con el modo configurado y permite escoger otro modo para una sola ejecución:

```bash
run-codex --approval-mode autonomous
run-codex --approval-mode guarded resume
run-codex --print-policy
```

Los valores desconocidos y los flags directos de sandbox/aprobación se rechazan antes de iniciar Codex.

## Aislamiento en TrueNAS

El launcher y Codex son contenedores separados. El launcher solo recibe su configuración de navegación; no recibe secretos ni montajes de Codex. Codex conserva sus montajes privados actuales y su secreto para el terminal.

La imagen no instala Bubblewrap del sistema. El lanzador de comandos de Codex desactiva expresamente el sandbox interno no compatible mediante `--sandbox danger-full-access`. El límite de seguridad soportado sigue siendo el contenedor exterior de Codex y sus montajes mínimos.

No añadas modo privilegiado, `SYS_ADMIN`, perfiles sin restricciones, el socket Docker ni montajes amplios para intentar habilitar un sandbox anidado.

## Licencias y software opcional

El código propio de Remote Dev utiliza Apache-2.0. Ubuntu, Codex CLI, GitHub CLI, ttyd, mise, Python, Node.js, npm, uv y sus dependencias conservan sus licencias y avisos originales.

```bash
remote-dev-notices
remote-dev-notices --list
remote-dev-notices --check
```

Antigravity, Claude Code y productos similares no quedan cubiertos por la licencia Apache-2.0 del repositorio. La imagen actual no los descarga ni redistribuye.

## Uso local

```bash
cp .env.example .env
mkdir -p secrets data/{workspace,codex,gh,git,ssh}
printf '%s\n' 'contraseña-de-codex' > secrets/web_password.txt
chmod 600 secrets/web_password.txt
./scripts/build-local.sh
```

Define `REMOTE_DEV_IMAGE=remote-dev:local` y ejecuta:

```bash
docker compose -f compose/docker-compose.yml up -d
```

1. Abre el launcher en el puerto publicado `7680`.
2. Pulsa Codex.
3. Autentícate en el terminal del puerto `7681` con `WEB_USERNAME` —por defecto `codex`— y la contraseña de `web_password.txt`.
4. Desde el menú realiza el login de Codex/GitHub, inicia o reanuda sesiones y ejecuta diagnósticos.

## Prueba pública de la imagen edge

```bash
docker pull ghcr.io/experience83/remote-dev:edge-amd64
```

Para Docker Compose o TrueNAS:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:edge-amd64
REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous
```

Los despliegues `v0.1.x` pueden conservar `CODEX_IMAGE` y `ghcr.io/experience83/codex-remote-dev`. Los nombres de compatibilidad no se eliminarán antes de `v0.2.0`.

Para fijar un commit o digest:

```text
ghcr.io/experience83/remote-dev:sha-<commit-completo>
ghcr.io/experience83/remote-dev@sha256:<digest>
```

## Advertencias importantes

- No expongas los puertos 7680 o 7681 directamente a Internet.
- El launcher sin contraseña solo debe publicarse en localhost, LAN o Tailscale.
- Codex sigue autenticado de forma independiente.
- El launcher no monta, reenvía ni incluye en la URL la contraseña de Codex.
- El launcher no es un proxy y no convierte el terminal en una aplicación del mismo origen.
- No montes workspaces ni credenciales de agente en el launcher.
- No montes el socket Docker ni uses modo privilegiado.
- En modo autónomo, Codex puede actuar sin confirmaciones sobre todo lo montado en su servicio.
- Las confirmaciones del modo protegido no son un sandbox.
- `edge` sigue siendo experimental.

## Desarrollo y revisiones

El desarrollo se realiza mediante pull requests. CodeRabbit revisa Dockerfiles, Bash, el launcher Python, GitHub Actions, Compose y cambios sensibles de seguridad. CI y las pruebas manuales siguen siendo obligatorios.

Consulta `AGENTS.md`, `README.md`, `PROJECT_STATUS.md`, `CHANGELOG.md`, `docs/architecture.md`, `docs/security.md` y `docs/roadmap.md` para el estado y los siguientes pasos.
