# Navegador común para todos los agentes

Remote Dev incluye Playwright MCP con versión fijada y Chromium headless shell
en la imagen base. No necesita Snap, socket de Docker, nuevos puertos,
credenciales durante la compilación ni descargas al arrancar.

Al iniciar una sesión real, Remote Dev **añade únicamente si falta** el
servidor MCP `playwright` a la configuración privada:

- Codex: `/root/.codex/config.toml` (`[mcp_servers.playwright]`).
- Antigravity CLI: `/root/.gemini/config/mcp_config.json`
  (`mcpServers.playwright`).
- Claude Code, si lo instalamos en el futuro, podrá reutilizar el mismo
  comando: `claude mcp add --scope user playwright -- /usr/local/bin/remote-dev-playwright-mcp`.
  **Este cambio no instala ni configura Claude.**

Si ya existe una definición `playwright` del usuario, se respeta incluso si
está deshabilitada. Las demás opciones permanecen; no se sobrescriben archivos
privados inválidos o inseguros. Los agentes no comparten configuraciones.
Los comandos pasivos como `--help` no alteran estos archivos.

El MCP se inicia bajo demanda mediante **stdio**, con perfil aislado, y termina al cerrar la sesión del agente. No se abre ningún puerto. Se puede comprobar
la herramienta común con `playwright --version`.

## Seguridad

Los agentes mantienen su modelo de permisos dentro del contenedor, pero el
lanzador del MCP inicia Node y Chromium con UID/GID `61123`, sin privilegios
ni grupos complementarios, tras limpiar entorno y FDs y aplicar Landlock al
proceso y descendientes. Un supervisor y un guardián separados eliminan el
perfil efímero de `/run` al terminar. No se necesita instalar nada al iniciar.

Chromium sigue con `chromiumSandbox: false`: **no es un sandbox de Chromium
adicional**. Landlock ABI 7 tampoco media todos los sockets UNIX; un socket
accesible para ese UID sigue siendo un riesgo residual. Se mantiene Internet
y acceso a la LAN por decisión del operador, sin aislamiento de red.

El nuevo lanzador **requiere aceptación real en Codex y AGY bajo el Compose
correspondiente** antes de fusionar; las pruebas sintéticas en CI no prueban
solas el aislamiento completo.

Los binarios viven en `/opt/remote-dev/playwright-browsers`, no se instalan
en `/tmp` ni en el arranque. La compilación AMD64 y las pruebas reales deben
pasar antes de fusionar.

## Validación

1. Ejecutar `python scripts/test-browser-config.py`.
2. Compilar la imagen y verificar que Chromium se instala sin Snap.
3. Abrir sesiones de Codex y AGY y comprobar que su MCP navega por una página
   local de prueba sin descargar nada.
4. Confirmar que se conservan los MCP personales, credenciales y configuraciones
   existentes, y que no hay nuevos puertos abiertos.
