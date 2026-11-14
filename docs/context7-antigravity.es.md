# Context7 alojado para Antigravity CLI

> **Estado verificado (14-11-2026):** PR #324 **fusionado** como `258d79a` y distribuido en el canal experimental `edge`. Las **llamadas reales a Context7 de ambos agentes ya han pasado** en TrueNAS Edge y AGY ha completado el **login OAuth nativo**. Quedan pendientes la persistencia de tokens tras recreación, el rollback y #53; todavía no está incluido en una estable posterior. No confundir herramientas operativas con aceptación de persistencia. Consulta [la guía de aceptación v0.3.0](v0.3.0-acceptance.es.md).

Esta integración **instala o reinstala únicamente el registro MCP**, no descarga un servidor Context7 en la imagen. Antigravity usa `~/.gemini/config/mcp_config.json`, con la propiedad `mcpServers.context7.serverUrl` para el transporte HTTP.

Codex y Antigravity tienen estados separados. Codex conserva su API key privada. **No copiamos esa clave a `mcp_config.json` ni suponemos que Antigravity sustituya variables de entorno en cabeceras HTTP.** El gestor Remote Dev crea inicialmente una entrada de modo remoto anónimo; sin cambiar el JSON, **AGY puede iniciar OAuth nativo desde `/mcp → context7 → Authenticate`**. Las capturas de TrueNAS acreditan que ese login funciona, pero no la persistencia de sus tokens al recrear el contenedor:

```json
{"mcpServers":{"context7":{"serverUrl":"https://mcp.context7.com/mcp"}}}
```

**Aviso de privacidad:** Context7 es un servicio externo operado por Upstash. Las búsquedas de documentación y los identificadores de bibliotecas generados por el agente se envían a ese proveedor. Trata las consultas MCP como datos compartidos con un tercero; no envíes secretos, información confidencial de proyectos ni datos personales regulados.

Desde el menú de Antigravity, entra en **7) Context7 MCP integration...** para consultar estado, previsualizar, reinstalar y probar. También puedes usar:

```sh
remote-dev-context7-antigravity status --menu
remote-dev-context7-antigravity plan
remote-dev-context7-antigravity reinstall --yes
remote-dev-context7-antigravity test --yes
```

`status` y `plan` son pasivos y no hacen peticiones de red. `reinstall` requiere confirmación, utiliza el mismo bloqueo de directorio que Playwright, conserva el significado de las demás entradas MCP y hace una copia privada del JSON original antes de sustituirlo atómicamente. Puede normalizar el formato JSON, pero conserva todos los valores ajenos a Context7.

**Si Context7 contiene credenciales propias o cualquier opción adicional** (`headers`, OAuth, token, `env`, `timeoutSeconds`, `disabled`, `disabledTools`, filtros o argumentos), la entrada se considera personalizada y no se reinstala, aunque el endpoint sea antiguo. Se preserva sin cambios y exige revisión manual; no se eliminan restricciones de herramientas ni credenciales. Tampoco se modifican los MCP específicos del proyecto (`.agents/mcp_config.json`).

La prueba real con `agy /mcp` y `resolve-library-id` + `query-docs` para `/psf/requests` **ha pasado en TrueNAS Edge (14-11-2026)**. El login OAuth de AGY también informó `Authentication successful!`, pero los tokens deben verificarse en el almacenamiento privado tras reinicio/recreación antes de dar la autenticación por persistente. La documentación del proveedor indica `~/.gemini/antigravity/mcp_oauth_tokens.json`, que no figura entre los mounts actuales. Tras reinstalar, verifica el funcionamiento desde Antigravity CLI con `/mcp` y una consulta de documentación pública. `test --yes` solo comprueba la configuración local y el endpoint `/ping`: no demuestra por sí mismo que el agente pueda usar las herramientas.

Referencias oficiales:
- https://antigravity.google/docs/mcp
- https://context7.com/docs/resources/all-clients
- https://context7.com/docs/resources/troubleshooting
