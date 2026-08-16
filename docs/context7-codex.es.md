# Integración opcional de Context7 para Codex

Remote Dev puede configurar el servicio Codex incluido para utilizar Context7 como servicio MCP alojado y opcional de documentación.

> **Estado de publicación:** esta integración se introduce mediante la ruta experimental actual `dev -> edge` de Remote Dev que sigue #31. Los candidatos revisados antes del merge pueden publicarse en `dev`; `edge` contiene únicamente cambios integrados en `main`. No forma parte de ninguna versión estable publicada anteriormente; no debe anunciarse como disponible en estable hasta que una versión estable que incluya este cambio complete sus gates de publicación.

Context7 está operado por **Upstash** y es externo a Remote Dev y OpenAI. Remote Dev no incluye ni conserva de forma persistente un CLI, paquete npm o runtime de servidor MCP de Context7. La integración normal utiliza el cliente MCP mediante Streamable HTTP nativo de Codex contra el endpoint alojado revisado:

```text
https://mcp.context7.com/mcp
```

Cuando el usuario elige expresamente el inicio de sesión mediante código de dispositivo, Remote Dev descarga y ejecuta de forma transitoria una versión publicada y fijada del CLI `ctx7` exclusivamente para esa operación de autenticación. El paquete, su caché de npm y el estado temporal de inicio de sesión de Context7 se eliminan inmediatamente después; no forman parte de la imagen ni del estado persistente de Codex.

## Ciclo de vida explícito

Construir o arrancar Remote Dev no configura ni contacta Context7. Utiliza **Context7 integration...** en el menú de Codex o el comando propio del proyecto:

```bash
remote-dev-context7 status
remote-dev-context7 install
remote-dev-context7 repair
remote-dev-context7 test
remote-dev-context7 update
remote-dev-context7 remove
```

`status` es pasivo y no realiza ninguna petición de red a Context7. `install`, `repair`, `update` y `remove` pueden modificar archivos persistentes privados de Codex y por eso exigen confirmación explícita. `test` también exige confirmación porque realiza una comprobación real contra el endpoint `/ping` documentado por Context7.

Un `install` o `repair` interactivo sin opciones pregunta ahora cómo debe gestionarse la autenticación:

1. **Iniciar sesión en Context7 con un código de dispositivo (recomendado)** — ejecuta el flujo oficial transitorio y aislado descrito más abajo.
2. **Introducir una API key existente de Context7** — conserva el flujo manual actual con entrada enmascarada.
3. **Conservar la API key actual** — o seguir en modo anónimo si no existe ninguna clave gestionada.
4. **Usar acceso anónimo** — elimina únicamente el archivo de API key gestionado por Remote Dev.

Para automatización no interactiva revisada, el contrato existente no cambia: las acciones aceptan `--yes` y `install`/`repair` permiten `--anonymous` o `--api-key-stdin`; el uso de stdin requiere `--yes` para que la entrada de la clave no pueda confundirse con una confirmación interactiva.

`update` **no** actualiza el servicio Context7 alojado ni descarga un runtime de Context7. Vuelve a validar y aplicar el contrato MCP alojado incluido en la imagen Remote Dev actual. Si Context7 cambia en el futuro su endpoint o su contrato de autenticación, Remote Dev deberá incorporar y revisar primero ese nuevo contrato; después, `update` sobre esa imagen más nueva podrá volver a aplicarlo.

## Alta mediante código de dispositivo

La ruta recomendada reutiliza deliberadamente la implementación publicada de Context7 para el inicio de sesión por dispositivo en lugar de duplicar su protocolo OAuth dentro de Remote Dev.

Remote Dev invoca la versión exacta revisada del paquete `ctx7` con:

```text
ctx7 login --no-browser
```

El CLI oficial muestra un código de un solo uso y una URL de verificación que pueden aprobarse desde cualquier navegador. Durante esta única operación explícita Remote Dev:

- ejecuta el CLI transitorio desde un directorio privado bajo `/run`, no desde el proyecto real ni desde `CODEX_HOME`;
- cuando el servicio se ejecuta como root, baja el paquete de proveedor transitorio a la identidad fija sin privilegios `nobody` con `no-new-privs`;
- utiliza HOME, configuración/estado/caché XDG y caché de npm nuevos y desechables;
- desactiva los scripts de ciclo de vida de npm y la telemetría del CLI de Context7 para esa invocación transitoria;
- ignora la configuración npm de usuario/global y fija como origen el registro npm público;
- no entrega al proceso transitorio credenciales de Codex, GitHub, OpenAI ni la API key Context7 existente;
- valida que la credencial privada resultante tenga el formato esperado de API key bearer de larga duración `ctx7sk-...`;
- transfiere esa clave al gestor existente de Remote Dev únicamente por stdin del proceso hijo;
- elimina por completo el directorio transitorio de CLI/login/caché tanto si termina correctamente como si se cancela o falla.

Remote Dev **no** ejecuta `ctx7 setup`. Ese comando de upstream puede escribir configuración MCP del agente, reglas y skills; Remote Dev mantiene esas mutaciones dentro de su gestor propio ya revisado. Por ello el CLI del proveedor nunca recibe el `CODEX_HOME` real ni modifica `config.toml`, `AGENTS.md` o las skills de Codex durante el alta por dispositivo.

Antes de descargar el paquete transitorio, Remote Dev valida el límite de propiedad de la configuración existente mediante la ruta normal y segura de `repair`. Una API key gestionada que ya funciona no se sustituye hasta que el nuevo inicio de sesión haya terminado correctamente y se haya validado el formato local de la credencial. Un inicio de sesión fallido, denegado, caducado o cancelado conserva la clave anterior.

## Configuración de Codex gestionada

Remote Dev solo es propietario de un bloque marcado de forma explícita dentro de `CODEX_HOME/config.toml`, que ya es persistente:

```toml
# BEGIN REMOTE DEV MANAGED CONTEXT7
[mcp_servers.context7]
url = "https://mcp.context7.com/mcp"
env_http_headers = { "CONTEXT7_API_KEY" = "CONTEXT7_API_KEY" }
enabled = true
required = false
# END REMOTE DEV MANAGED CONTEXT7
```

La documentación actual de Context7 para el cliente Codex exige una cabecera HTTP llamada `CONTEXT7_API_KEY` para la autenticación mediante API key. La opción `env_http_headers` de Codex relaciona esa cabecera con el nombre de una variable de entorno, de forma que el valor secreto queda fuera del TOML y Codex envía la cabecera que espera el MCP alojado.

Todo lo que quede fuera de esos marcadores se conserva. Antes de escribir, el gestor analiza el TOML existente y se niega a sobrescribir un `mcp_servers.context7` previo que no sea propiedad de Remote Dev. Si faltan marcadores, están duplicados o son ambiguos, también falla de forma segura en lugar de adivinar qué contenido puede modificar.

Cuando cambia el bloque gestionado, la configuración completa anterior se guarda de forma privada en:

```text
$CODEX_HOME/config.toml.remote-dev-context7.bak
```

El reemplazo utiliza un archivo temporal en el mismo directorio y un renombrado atómico. La configuración y la copia se restringen al usuario del servicio Codex.

## Tratamiento de la API key

Context7 puede configurarse sin API key, sujeto a los límites del servicio para acceso anónimo. Tanto si se introduce manualmente como si se adopta mediante el inicio de sesión por dispositivo, una clave gestionada solo se guarda dentro del estado persistente privado de Codex:

```text
$CODEX_HOME/.remote-dev-context7/api-key
```

El directorio utiliza modo `0700` y la clave `0600`. Se rechazan enlaces simbólicos, archivos no regulares, propietarios incorrectos o permisos demasiado amplios.

La clave **no** se escribe en TOML, argumentos, diagnósticos, estado del menú, issues/PR ni logs normales. Justo antes de iniciar Codex con una integración Context7 gestionada por Remote Dev, `run-codex` valida la ruta privada y exporta `CONTEXT7_API_KEY` únicamente al entorno del proceso Codex. Codex resuelve después esa variable mediante `env_http_headers` y envía su valor en la cabecera HTTP `CONTEXT7_API_KEY`. Si la integración gestionada es anónima, se elimina cualquier valor heredado accidental con ese nombre. Cuando Context7 no está gestionado por Remote Dev, el wrapper no modifica el entorno ni la configuración que pueda mantener el usuario por su cuenta.

El inicio de sesión por dispositivo crea una API key en la cuenta de Context7. `remote-dev-context7 remove` elimina la copia local gestionada por Remote Dev, pero **no** afirma revocar esa clave en la cuenta. Si hace falta, hay que rotarla o revocarla desde los controles de cuenta/dashboard de Context7.

## Disponibilidad y comportamiento de red

La entrada MCP gestionada fija:

```toml
required = false
```

por lo que Context7 no es una dependencia obligatoria para arrancar Codex. Una caída de Context7 puede dejar sus herramientas de documentación sin servicio, pero no debe convertir el contenedor Remote Dev en no saludable.

Los límites de red dependen de la acción:

- arranque del contenedor sin Context7 gestionado: ninguna petición de instalación/configuración a Context7;
- `remote-dev-context7 status`: sin red hacia Context7;
- `install` o `repair` con API key manual/modo anónimo: solo configuración y estado locales;
- inicio por código de dispositivo elegido desde `install`/`repair`: descarga explícita por npm del paquete transitorio `ctx7` fijado más autorización de dispositivo de Context7, seguida de limpieza local completa;
- `update` y `remove`: solo configuración/estado locales;
- `test`: comprobación explícita de la configuración con el Codex incluido y de `https://mcp.context7.com/ping`;
- una sesión normal de Codex después de habilitar Context7: Codex puede contactar el MCP alojado durante la inicialización y el uso normal de sus herramientas.

La build de imagen crea además una configuración temporal anónima y exige que el binario exacto de Codex incluido analice y describa ese único servidor mediante la ruta exclusivamente local `codex mcp get context7 --json`. Así se evita tanto el descubrimiento de autenticación MCP con capacidad de red como depender de `codex mcp add --url` como primitiva de escritura de confianza.

## Privacidad, términos y licencias de documentación

Habilitar Context7 introduce un límite de servicio externo. Según la documentación oficial de Context7/Upstash revisada para el issue #94:

- Remote Dev no envía intencionadamente a Context7 el prompt original completo, archivos de código ni la conversación; Codex formula peticiones MCP de documentación y el texto de consulta que envía debe considerarse igualmente dato comunicado a un servicio externo;
- una petición MCP mediante Streamable HTTP puede incluir la consulta de documentación y los identificadores de librería, además de metadatos HTTP/MCP normales generados por el cliente Codex configurado, como identidad/versión del cliente y cabeceras de protocolo/transporte; en modo autenticado se envía además la cabecera `CONTEXT7_API_KEY`;
- esas consultas generadas por MCP pueden procesarse para recuperación/reranking y almacenarse de forma anónima para evaluar la calidad de recuperación;
- Context7 documenta una retención de 30 días para logs de API;
- no se deben enviar datos sensibles, sanitarios, de pago u otros datos regulados mediante el servicio;
- la respuesta de Context7 puede ser incompleta o incorrecta y debe verificarse antes de utilizarla en producción;
- la documentación original devuelta por Context7 conserva sus propios derechos de autor y licencias.

El uso del servicio alojado y del flujo de inicio por dispositivo queda sujeto al **Context7 Addendum**, los **Upstash Terms of Service** y la **Upstash Privacy Policy** vigentes. Remote Dev no está afiliado ni respaldado por Upstash, Context7 u OpenAI.

La revisión legal/de privacidad del diseño MCP alojado original está registrada en el tracker permanente #53. La nueva ruta de CLI transitorio/autenticación por dispositivo introducida por #123 exige una nueva revisión extraordinaria en #53 antes del merge, porque añade una descarga de paquete de proveedor y un flujo de creación de credencial en la cuenta, aunque ningún paquete Context7 quede retenido en la imagen o en el estado persistente.

## Eliminación y recuperación

Como no se conserva ningún runtime/paquete local de Context7, `remote-dev-context7 remove` sigue siendo el equivalente a desinstalar esta integración. Elimina únicamente el bloque marcado como propiedad de Remote Dev y el archivo de API key propiedad de Remote Dev. No borra otros servidores MCP, `AGENTS.md`, instrucciones de Codex, skills, sesiones, autenticación ni una configuración Context7 no gestionada.

Si los marcadores de propiedad son ambiguos, la eliminación se detiene. Revisa la configuración y, si corresponde, restaura la copia privada antes de volver a intentarlo.

Eliminar Context7 no afecta al Codex CLI inmutable incluido ni al runtime opcional separado que gestiona `remote-dev-codex-runtime`. Las API keys creadas en la cuenta mediante el flujo de dispositivo deben rotarse o revocarse desde Context7 cuando se desee.
