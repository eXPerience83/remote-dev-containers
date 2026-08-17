# Integración opcional de Context7 para Codex

Remote Dev puede configurar el servicio Codex incluido para utilizar Context7 como servicio MCP alojado y opcional de documentación.

> **Estado de publicación:** esta integración se introduce mediante la ruta experimental actual `dev -> edge` de Remote Dev que sigue #31. Los candidatos revisados antes del merge pueden publicarse en `dev`; `edge` contiene únicamente cambios integrados en `main`. No debe anunciarse disponibilidad estable hasta que una versión estable que incluya este cambio complete sus gates de publicación.

Context7 está operado por **Upstash** y es externo a Remote Dev y OpenAI. La integración normal utiliza el cliente MCP Streamable HTTP nativo de Codex contra:

```text
https://mcp.context7.com/mcp
```

Remote Dev **no** incluye ni conserva de forma persistente el CLI de Context7 ni un runtime de servidor MCP. El inicio mediante código de dispositivo descarga de forma transitoria una versión oficial y exacta del paquete npm `ctx7`, la ejecuta solo para la autenticación y después elimina paquete, caché npm y estado temporal del proveedor. Solo persiste la API key que se adopta en el estado privado de Context7 ya existente en Remote Dev.

## Ciclo de vida explícito

Utiliza **Context7 integration...** en el menú de Codex o:

```bash
remote-dev-context7 status
remote-dev-context7 install
remote-dev-context7 repair
remote-dev-context7 test
remote-dev-context7 update
remote-dev-context7 remove
```

`status` es pasivo. `install`, `repair`, `update` y `remove` pueden modificar estado persistente privado de Codex y exigen confirmación explícita. `test` también pide confirmación porque realiza una comprobación real contra el endpoint `/ping` documentado por Context7.

Un `install` o `repair` interactivo pregunta cómo gestionar la autenticación:

1. **Iniciar sesión en Context7 con un código de dispositivo (recomendado)**.
2. **Introducir una API key existente de Context7** mediante la ruta manual enmascarada.
3. **Conservar la API key gestionada actual**, o seguir anónimo si no existe.
4. **Usar acceso anónimo**, eliminando solo la API key gestionada por Remote Dev.
5. **Cancelar**.

El contrato no interactivo existente sigue disponible con `--yes`, `--anonymous` y `--api-key-stdin`. La automatización del device login puede elegir además `--cli-channel reviewed` o `--cli-channel latest`; el menú interactivo utiliza `auto`.

`remote-dev-context7 update` vuelve a validar/aplicar la configuración MCP alojada que incluye la imagen. Es independiente de la versión transitoria de `ctx7`, que solo se utiliza para la autenticación por dispositivo.

## CLI de Context7 revisado y última versión oficial

Remote Dev mantiene en su código una versión exacta **revisada** de `ctx7`. La automatización de upstream del repositorio se encarga de proponer versiones revisadas más nuevas; nunca debe cambiar estable de forma silenciosa.

En un device login interactivo, Remote Dev resuelve primero el `latest` actual desde el registro npm público fijado. Antes de ejecutar código del proveedor valida identidad del paquete, versión semántica estable exacta, contrato de licencia MIT revisado y metadatos de integridad de npm.

- Si `latest` coincide con la versión revisada por Remote Dev, se utiliza esa versión exacta.
- Si npm tiene una versión más nueva, Remote Dev muestra ambas y permite elegir:
  - la versión revisada (recomendada); o
  - la última versión oficial exacta, marcada como **`official source; Remote Dev review pending`**.
- Una versión nueva **no se bloquea solo por no haber sido revisada todavía**. Debe superar igualmente los gates de origen/metadatos/integridad y los de credencial/limpieza posteriores al login.
- Primero se resuelve `latest` y después se ejecuta `ctx7@X.Y.Z`; Remote Dev nunca pide a npm que ejecute directamente el selector mutable `ctx7@latest`.
- Un origen, identidad, formato de versión, licencia, integridad o modelo de credenciales incompatible falla de forma segura.

Es el mismo principio de runtimes opcionales que usamos con Codex y Antigravity: la evidencia de revisión describe versiones conocidas, no es una allowlist de disponibilidad.

## Alta mediante código de dispositivo

Remote Dev invoca únicamente:

```text
ctx7 login --no-browser
```

No ejecuta `ctx7 setup`, porque ese comando puede modificar configuración MCP del agente, reglas y skills fuera del modelo de propiedad ya revisado por Remote Dev.

Durante el device login, Remote Dev:

- crea un árbol privado nuevo `/run/remote-dev-context7-login-*`;
- utiliza HOME, configuración/estado/caché/runtime XDG, temporales, caché npm y configuraciones npm user/global nuevas;
- fija el registro npm público y desactiva scripts de ciclo de vida, audit/fund/update noise y telemetría de Context7;
- pasa explícitamente la versión de Node fijada por la imagen al shim npm/mise incluido, con resolución mise offline;
- no entrega credenciales existentes de Codex, OpenAI, GitHub o Context7 ni usa el `CODEX_HOME` real o el proyecto como HOME/config/cwd del proveedor;
- cuando el servicio corre como root, ejecuta npm/Context7 como UID/GID 65534, sin grupos suplementarios y con `no-new-privs`;
- crea el proceso del proveedor en su propio grupo y con `umask 077`;
- entrega `/dev/null` como stdin al CLI del proveedor. Remote Dev conserva el teclado y muestra **`type q and press Enter`** como método soportado de cancelación mientras espera la autorización del navegador. `Ctrl+C` queda solo como fallback porque no dependemos de cómo ttyd/tmux propaguen esa señal;
- termina y recoge todo el grupo de procesos al cancelar o agotar tiempo, con TERM/KILL acotados;
- valida cada componente de la ruta de credenciales sin seguir symlinks, con propietario/permisos privados y tamaño limitado;
- acepta únicamente la API key bearer de larga duración `ctx7sk-...` que usa el flujo revisado; se rechaza estado con refresh/expiry;
- elimina todo el árbol transitorio de CLI/login/caché antes de pasar la clave resultante por stdin al gestor existente.

La bajada a UID/GID 65534 **no es un sandbox de sistema de archivos**. Los archivos del contenedor Codex que sean legibles por ese UID/GID siguen siendo técnicamente legibles para el proceso transitorio. Utiliza la ruta manual de API key si no quieres ejecutar código transitorio de Context7 dentro del servicio Codex.

Antes de cualquier trabajo transitorio de npm/proveedor, Remote Dev ejecuta únicamente el preflight de solo lectura `status --menu` del gestor existente. Un login fallido, denegado, caducado o cancelado no muta el gestor, por lo que una API key gestionada que ya funcionaba permanece intacta.

## Configuración de Codex gestionada

Remote Dev solo es propietario de este bloque marcado de `CODEX_HOME/config.toml`:

```toml
# BEGIN REMOTE DEV MANAGED CONTEXT7
[mcp_servers.context7]
url = "https://mcp.context7.com/mcp"
env_http_headers = { "CONTEXT7_API_KEY" = "CONTEXT7_API_KEY" }
enabled = true
required = false
# END REMOTE DEV MANAGED CONTEXT7
```

Todo lo demás se conserva. Un `mcp_servers.context7` previo no gestionado, marcadores ambiguos o estado inseguro fallan de forma segura. Antes de sustituir un bloque gestionado, se guarda la configuración anterior completa y privada en:

```text
$CODEX_HOME/config.toml.remote-dev-context7.bak
```

## Tratamiento de la API key

Una clave gestionada, tanto manual como obtenida por device login, se almacena únicamente en:

```text
$CODEX_HOME/.remote-dev-context7/api-key
```

El directorio es `0700` y el archivo `0600`. Se rechazan symlinks, archivos no regulares, propietarios incorrectos o permisos excesivos.

La clave no se escribe en TOML, argumentos, diagnósticos, estado del menú ni logs normales. `run-codex` inyecta `CONTEXT7_API_KEY` únicamente al proceso hijo Codex cuando la integración gestionada está sana. El modo anónimo gestionado elimina del hijo un valor heredado accidental del mismo nombre. La configuración Context7 no gestionada se deja intacta.

El device login crea una API key en la cuenta de Context7. `remote-dev-context7 remove` elimina la copia local y el bloque gestionado, pero **no** revoca la clave en la cuenta.

## Disponibilidad y comportamiento de red

La entrada MCP utiliza `required = false`, por lo que una caída de Context7 no puede convertir el contenedor Remote Dev en no saludable.

Límites de red:

- arranque y `status`: sin petición de setup/descarga a Context7;
- `install`/`repair` manual o anónimo: solo estado local;
- device login: consulta explícita de metadatos del npm público y descarga del paquete exacto, seguida de autorización por dispositivo en Context7;
- `update`/`remove`: solo estado local;
- `test`: comprobación explícita de configuración + `https://mcp.context7.com/ping`;
- sesión Codex con Context7 habilitado: Codex puede contactar el MCP alojado para inicialización y herramientas.

## Privacidad, términos y evidencia

Context7 es un servicio externo. Las consultas de documentación generadas por MCP deben considerarse datos comunicados a Context7/Upstash; no envíes datos sensibles, sanitarios, de pago u otros regulados mediante esta integración. La salida de Context7 puede ser incompleta o incorrecta y la documentación subyacente conserva sus propias licencias.

El flujo oficial de dispositivo envía el hostname del contenedor de forma best-effort con la autorización para que la página del navegador identifique el dispositivo. Tras aprobarlo, el CLI usa la nueva clave para `whoami` y puede mostrar identidad/teamspace localmente. Remote Dev no persiste esa salida.

**Nunca incluyas códigos de dispositivo, URLs únicas de autorización, API keys, identificadores de cuenta, emails ni nombres de teamspace en evidencia de issues/PR.**

El uso del servicio/flujo de dispositivo sigue sujeto al Context7 Addendum, Upstash Terms of Service y Upstash Privacy Policy vigentes. El registro legal/de privacidad permanente está en #53. La revisión del 17/08/2026 acepta `ctx7@0.5.8` como versión revisada para login y registra el modelo explícito revisada-vs-última-oficial. Un cambio material de origen, licencia, autenticación/ciclo de credenciales, estado retenido, divulgación o acceso a filesystem/credenciales sigue exigiendo revisión en #53.

## Eliminación y recuperación

Como no se conserva ningún CLI/runtime de Context7, `remote-dev-context7 remove` es el equivalente local a desinstalarlo. Solo elimina configuración/clave de Context7 propiedad de Remote Dev y no toca otros servidores MCP, sesiones, proyectos, skills ni configuración no gestionada.

Eliminar Context7 no afecta al Codex CLI inmutable incluido ni al runtime opcional de Codex gestionado por `remote-dev-codex-runtime`.
