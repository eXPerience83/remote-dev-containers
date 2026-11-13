# Context7 alojado para Antigravity CLI

Esta integración **instala o reinstala únicamente el registro MCP**, no descarga un servidor Context7 en la imagen. Antigravity usa `~/.gemini/config/mcp_config.json`, con la propiedad `mcpServers.context7.serverUrl` para el transporte HTTP.

Codex y Antigravity tienen estados separados. Codex conserva su API key privada. **No copiamos esa clave a `mcp_config.json` ni suponemos que Antigravity sustituya variables de entorno en cabeceras HTTP.** Por ahora la integración Antigravity se registra en modo remoto anónimo, con los límites de uso correspondientes:

```json
{"mcpServers":{"context7":{"serverUrl":"https://mcp.context7.com/mcp"}}}
```

Desde el menú de Antigravity, entra en **7) Context7 MCP integration...** para consultar estado, previsualizar, reinstalar y probar. También puedes usar:

```sh
remote-dev-context7-antigravity status --menu
remote-dev-context7-antigravity plan
remote-dev-context7-antigravity reinstall --yes
remote-dev-context7-antigravity test --yes
```

`status` y `plan` son pasivos y no hacen peticiones de red. `reinstall` requiere confirmación, utiliza el mismo bloqueo de directorio que Playwright, conserva el significado de las demás entradas MCP y hace una copia privada del JSON original antes de sustituirlo atómicamente. Puede normalizar el formato JSON, pero conserva todos los valores ajenos a Context7.

**Si la entrada Context7 contiene autenticación personalizada** (`headers`, OAuth, token, comando, argumentos o `env`), la reinstalación se bloquea para proteger las credenciales. No toca configuraciones MCP específicas del proyecto (`.agents/mcp_config.json`).

Tras reinstalar, verifica el funcionamiento desde Antigravity CLI con `/mcp` y una consulta de documentación pública. `test --yes` solo comprueba la configuración local y el endpoint `/ping`: no demuestra por sí mismo que el agente pueda usar las herramientas.

Referencias oficiales:
- https://antigravity.google/docs/mcp
- https://context7.com/docs/resources/all-clients
- https://context7.com/docs/resources/troubleshooting
