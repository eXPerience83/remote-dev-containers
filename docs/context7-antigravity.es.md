# Context7 alojado para Antigravity CLI

> **Estado verificado (14-11-2026):** PR #324 **fusionado** como `258d79a` y distribuido en el canal experimental `edge`. Las **llamadas reales a Context7 de ambos agentes ya han pasado** en TrueNAS Edge y AGY ha completado el **login OAuth nativo**. Quedan pendientes la persistencia de tokens tras recreación, el rollback y #53; todavía no está incluido en una estable posterior. No confundir herramientas operativas con aceptación de persistencia. Las pruebas y verificaciones pendientes de TrueNAS están registradas en el [issue #95](https://github.com/eXPerience83/remote-dev-containers/issues/95); las guías bilingües de aceptación v0.3.0 se proponen por separado en el [PR #345](https://github.com/eXPerience83/remote-dev-containers/pull/345) y todavía no están en `main`.

Esta integración **instala o reinstala únicamente el registro MCP**, no descarga un servidor Context7 en la imagen. Antigravity usa `~/.gemini/config/mcp_config.json`, con la propiedad `mcpServers.context7.serverUrl` para el transporte HTTP.

Codex y Antigravity tienen estados separados. Codex conserva su API key privada. **No copiamos esa clave a `mcp_config.json` ni suponemos que Antigravity sustituya variables de entorno en cabeceras HTTP.** El gestor Remote Dev crea inicialmente una entrada de modo remoto anónimo; sin cambiar el JSON, **AGY puede iniciar OAuth nativo desde `/mcp → context7 → Authenticate`**. Las capturas de TrueNAS acreditan que ese login funciona, pero no la persistencia de sus tokens al recrear el contenedor:

```json
{"mcpServers":{"context7":{"serverUrl":"https://mcp.context7.com/mcp"}}}
```

**Aviso de privacidad:** Context7 es un servicio externo operado por Upstash. Las búsquedas de documentación y los identificadores de bibliotecas generados por el agente se envían a ese proveedor. Trata las consultas MCP como datos compartidos con un tercero; no envíes secretos, información confidencial de proyectos ni datos personales regulados.

Desde **7) MCP integrations... → 1) Context7...** puedes consultar las operaciones simplificadas. También están disponibles las órdenes:

```sh
remote-dev-context7-antigravity menu-state
remote-dev-context7-antigravity status --menu
remote-dev-context7-antigravity plan
remote-dev-context7-antigravity reinstall --yes
remote-dev-context7-antigravity remove --yes
remote-dev-context7-antigravity test --yes
```

`status` y `plan` son pasivos y no hacen peticiones de red. `reinstall` requiere confirmación, utiliza el mismo bloqueo de directorio que Playwright, conserva el significado de las demás entradas MCP y hace una copia privada del JSON original antes de sustituirlo atómicamente. Puede normalizar el formato JSON, pero conserva todos los valores ajenos a Context7.

**Si Context7 contiene credenciales propias o cualquier opción adicional** (`headers`, OAuth, token, `env`, `timeoutSeconds`, `disabled`, `disabledTools`, filtros o argumentos), la entrada se considera personalizada y no se reinstala, aunque el endpoint sea antiguo. Se preserva sin cambios y exige revisión manual; no se eliminan restricciones de herramientas ni credenciales. Tampoco se modifican los MCP específicos del proyecto (`.agents/mcp_config.json`).

La prueba real con `agy /mcp` y `resolve-library-id` + `query-docs` para `/psf/requests` **ha pasado en TrueNAS Edge (14-11-2026)**. El login OAuth de AGY también informó `Authentication successful!`, y una verificación posterior de metadatos (sin leer tokens) localizó el archivo en **`/root/.gemini/antigravity-cli/mcp_oauth_tokens.json`**: propietario `root:root`, permisos `0600`, directorio `0700` en montaje ZFS. El Compose actual ya monta **`/mnt/Pool1/remote-dev/state/antigravity/vendor` → `/root/.gemini/antigravity-cli`**, de modo que **no requiere un nuevo mount**. La ruta `~/.gemini/antigravity/mcp_oauth_tokens.json` publicada en documentación externa no existe en este runtime. **Persistencia tras recreación todavía no verificada**. Tras reinstalar, verifica el funcionamiento desde Antigravity CLI con `/mcp` y una consulta de documentación pública. `test --yes` solo comprueba la configuración local y el endpoint `/ping`: no demuestra por sí mismo que el agente pueda usar las herramientas.

## Menú compartido de Context7 (#347)

El submenú de ambos agentes utiliza **1 Estado/diagnóstico**, **2 Probar conexión**, **3 Gestionar autenticación**, **4 Instalar/reparar**, **5 Eliminar registro** y **0 Volver**. El menú principal conserva el acceso en el número 7, ahora bajo *MCP integrations*.

- **Estado** y **plan** son pasivos, no usan la red ni modifican el JSON. No se examina el archivo OAuth; la presencia del registro `serverUrl` **no implica modo anónimo ni OAuth autenticado**. La salida indica que Antigravity gestiona la autenticación y remite a `/mcp`.
- **Prueba**: comprueba HTTP `/ping` y el contrato local, no el inicio de sesión ni el éxito de herramientas MCP.
- **Autenticación**: inicia el CLI de Antigravity, entra en `/mcp → context7 → Authenticate` y confirma `[Authed]` desde el propio agente. Comprueba con una consulta real. Remote Dev no copia la API key de Codex ni lee tokens.
- **Instalar/reparar**: si falta el registro, permite instalarlo. Si hay un endpoint simple desactualizado, previsualiza el cambio y permite reinstalación selectiva. Una entrada sana **no solicita REINSTALL ni modifica archivos**. Si el JSON es inválido o hay personalizaciones, se bloquea.
- **Eliminar**: elimina solo el registro global Context7 gestionado y guarda una copia privada. No elimina otros MCP, ni cierra la sesión OAuth, ni revoca el permiso en el proveedor. Esas operaciones de cuenta son independientes.

CLI: `menu-state` devuelve solo `absent`, `healthy`, `repairable` o `blocked`; `remove --yes` elimina el registro de propiedad comprobada. Se mantienen `status`, `plan`, `reinstall` y `test` con los alias existentes. No se modifican proyectos, backups, sesiones ni los archivos OAuth del proveedor.

Referencias oficiales:
- https://antigravity.google/docs/mcp
- https://context7.com/docs/resources/all-clients
- https://context7.com/docs/resources/troubleshooting
