# Integración opcional de Context7 para Codex

Remote Dev puede configurar el servicio Codex incluido para utilizar Context7 como servicio MCP alojado y opcional de documentación.

Context7 está operado por **Upstash** y es externo a Remote Dev y OpenAI. Remote Dev no incluye, redistribuye, instala ni persiste el CLI, paquete npm o runtime de servidor MCP de Context7 para esta integración. Se utiliza el cliente MCP HTTP nativo de Codex contra el endpoint alojado revisado:

```text
https://mcp.context7.com/mcp
```

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

Para automatización no interactiva revisada, las acciones aceptan `--yes`. `install` y `repair` permiten además `--anonymous` o `--api-key-stdin`; el uso de stdin requiere `--yes` para que la entrada de la clave no pueda confundirse con la confirmación interactiva.

`update` **no** descarga ningún runtime de Context7: vuelve a validar y aplicar el contrato MCP alojado actualmente revisado.

## Configuración de Codex gestionada

Remote Dev solo es propietario de un bloque marcado de forma explícita dentro de `CODEX_HOME/config.toml`, que ya es persistente:

```toml
# BEGIN REMOTE DEV MANAGED CONTEXT7
[mcp_servers.context7]
url = "https://mcp.context7.com/mcp"
bearer_token_env_var = "CONTEXT7_API_KEY"
enabled = true
required = false
# END REMOTE DEV MANAGED CONTEXT7
```

Todo lo que quede fuera de esos marcadores se conserva. Antes de escribir, el gestor analiza el TOML existente y se niega a sobrescribir un `mcp_servers.context7` previo que no sea propiedad de Remote Dev. Si faltan marcadores, están duplicados o son ambiguos, también falla de forma segura en lugar de adivinar qué contenido puede modificar.

Cuando cambia el bloque gestionado, la configuración completa anterior se guarda de forma privada en:

```text
$CODEX_HOME/config.toml.remote-dev-context7.bak
```

El reemplazo utiliza un archivo temporal en el mismo directorio y un renombrado atómico. La configuración y la copia se restringen al usuario del servicio Codex.

## Tratamiento de la API key

Context7 puede configurarse sin API key, sujeto a los límites del servicio para acceso anónimo. Si se proporciona una clave, Remote Dev solo la guarda dentro del estado persistente privado de Codex:

```text
$CODEX_HOME/.remote-dev-context7/api-key
```

El directorio utiliza modo `0700` y la clave `0600`. Se rechazan enlaces simbólicos, archivos no regulares, propietarios incorrectos o permisos demasiado amplios.

La clave **no** se escribe en TOML, argumentos, diagnósticos, estado del menú, issues/PR ni logs normales. Justo antes de iniciar Codex con una integración Context7 gestionada por Remote Dev, `run-codex` valida la ruta privada y exporta `CONTEXT7_API_KEY` únicamente al entorno del proceso Codex. Si la integración gestionada es anónima, se elimina cualquier valor heredado accidental con ese nombre. Cuando Context7 no está gestionado por Remote Dev, el wrapper no modifica el entorno ni la configuración que pueda mantener el usuario por su cuenta.

## Disponibilidad y comportamiento de red

La entrada MCP gestionada fija:

```toml
required = false
```

por lo que Context7 no es una dependencia obligatoria para arrancar Codex. Una caída de Context7 puede dejar sus herramientas de documentación sin servicio, pero no debe convertir el contenedor Remote Dev en no saludable.

Los límites de red dependen de la acción:

- arranque del contenedor sin Context7 gestionado: ninguna petición de instalación/configuración a Context7;
- `remote-dev-context7 status`: sin red hacia Context7;
- `install`, `repair`, `update`, `remove`: solo configuración/estado; no descargan paquetes Context7;
- `test`: comprobación explícita de la configuración con el Codex incluido y de `https://mcp.context7.com/ping`;
- una sesión normal de Codex después de habilitar Context7: Codex puede contactar el MCP alojado durante la inicialización y el uso normal de sus herramientas.

La build de imagen crea además una configuración temporal anónima y obliga al binario exacto de Codex incluido a aceptarla mediante `codex mcp list`. Así no se depende de `codex mcp add --url` como primitiva de escritura de confianza.

## Privacidad, términos y licencias de documentación

Habilitar Context7 introduce un límite de servicio externo. Según la documentación oficial de Context7/Upstash revisada para el issue #94:

- el prompt original, código y conversación permanecen con el asistente de IA, mientras el cliente MCP formula consultas de búsqueda de documentación para Context7;
- esas consultas generadas por MCP pueden procesarse para recuperación/reranking y almacenarse de forma anónima para evaluar la calidad de recuperación;
- Context7 documenta una retención de 30 días para logs de API;
- no se deben enviar datos sensibles, sanitarios, de pago u otros datos regulados mediante el servicio;
- la respuesta de Context7 puede ser incompleta o incorrecta y debe verificarse antes de utilizarla en producción;
- la documentación original devuelta por Context7 conserva sus propios derechos de autor y licencias.

El uso del servicio alojado queda sujeto al **Context7 Addendum**, los **Upstash Terms of Service** y la **Upstash Privacy Policy** vigentes. Remote Dev no está afiliado ni respaldado por Upstash, Context7 u OpenAI.

La revisión legal/de privacidad de este diseño MCP alojado y acotado está registrada en el tracker permanente #53. Será necesaria una nueva revisión si Remote Dev empieza a redistribuir código/paquetes de Context7, cambia el transporte/autenticación o amplía materialmente los datos enviados al servicio.

## Eliminación y recuperación

`remote-dev-context7 remove` elimina únicamente el bloque marcado como propiedad de Remote Dev y el archivo de API key propiedad de Remote Dev. No borra otros servidores MCP, `AGENTS.md`, instrucciones de Codex, skills, sesiones, autenticación ni una configuración Context7 no gestionada.

Si los marcadores de propiedad son ambiguos, la eliminación se detiene. Revisa la configuración y, si corresponde, restaura la copia privada antes de volver a intentarlo.

Eliminar Context7 no afecta al Codex CLI inmutable incluido ni al runtime opcional separado que gestiona `remote-dev-codex-runtime`.
