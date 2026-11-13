# Context7 alojado para Antigravity CLI

> **Estado de publicación:** Integración experimental desarrollada en el PR #324 (borrador). Aún no está fusionada ni incluida en las imágenes publicadas `edge`, `stable` o `latest`. Los comandos requieren una futura imagen revisada que contenga estos cambios.

Esta integración **instala o reinstala únicamente el registro MCP**, no descarga un servidor Context7 en la imagen. Antigravity usa `~/.gemini/config/mcp_config.json`, con la propiedad `mcpServers.context7.serverUrl` para el transporte HTTP.

Codex y Antigravity tienen estados separados. Codex conserva su API key privada. **No copiamos esa clave a `mcp_config.json` ni suponemos que Antigravity sustituya variables de entorno en cabeceras HTTP.** Por ahora la integración Antigravity se registra en modo remoto anónimo, con los límites de uso correspondientes:

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

Tras reinstalar, verifica el funcionamiento desde Antigravity CLI con `/mcp` y una consulta de documentación pública. `test --yes` solo comprueba la configuración local y el endpoint `/ping`: no demuestra por sí mismo que el agente pueda usar las herramientas.

Referencias oficiales:
- https://antigravity.google/docs/mcp
- https://context7.com/docs/resources/all-clients
- https://context7.com/docs/resources/troubleshooting
