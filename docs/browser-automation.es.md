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

Si ya existe una definición `playwright` personalizada o deshabilitada,
se respeta. Solo se actualiza automáticamente una entrada de Codex que coincida
exactamente con el formato generado por una versión anterior de Remote Dev,
para añadir `REMOTE_DEV_ROLE=codex`. Las demás opciones permanecen; no se
sobrescriben archivos privados inválidos o inseguros ni se genera TOML no válido.
Los agentes no comparten configuraciones.
Los comandos pasivos como `--help` no alteran estos archivos.

La imagen no incluye FFmpeg: no se ofrece grabación de vídeo de sesión, pero sí navegación, JavaScript y capturas. El MCP se inicia bajo demanda mediante **stdio**, con perfil aislado, y termina al cerrar la sesión del agente. No se abre ningún puerto. Se puede comprobar
la herramienta común con `playwright --version`.

## Seguridad

Los agentes mantienen su modelo de permisos dentro del contenedor, pero el
lanzador del MCP inicia Node y Chromium con UID/GID `61123`, sin privilegios
ni grupos complementarios, tras limpiar entorno y FDs y aplicar Landlock al
proceso y descendientes. Un supervisor y un guardián de limpieza separados eliminan el
perfil efímero de `/run` al terminar. El guardián es un proceso mínimo de
confianza distinto del UID del navegador: conserva los permisos de limpieza
ya permitidos por el contenedor, no hereda secretos y se marca no depurable
para que Chromium no pueda detenerlo por compartir UID.
Además es el **padre y subreaper** de Node: puede recoger Chromium incluso cuando
Playwright crea grupos de procesos independientes y el supervisor recibe SIGKILL.
El propio supervisor también se marca subreaper y recoge los descendientes si
muere el guardián. Como límite conocido, un SIGKILL durante el brevísimo tramo
entre crear el scratch y arrancar el guardián puede dejar un directorio
huérfano en /run, sin procesos Chromium iniciados. No se necesita instalar nada al iniciar.

El lanzador exige **Landlock ABI 5 o superior** y no inicia Node ni Chromium
si falta. Ante ese fallo, stderr comunica únicamente el tipo de excepción
(`IsolationError`; en algunos hosts sin soporte puede ser `OSError`),
sin imprimir credenciales ni variables privadas.

Chromium sigue con `chromiumSandbox: false`: **no es un sandbox de Chromium
adicional**. Landlock ABI 7 tampoco media todos los sockets UNIX; un socket
accesible para ese UID sigue siendo un riesgo residual. Se mantiene Internet
y acceso a la LAN por decisión del operador, sin aislamiento de red.

**Estado verificado (14-11-2026):** Playwright MCP está **integrado en `main` y Edge experimental**, pero **no en la última estable publicada v0.2.0**. No está aceptado para navegación general: la revisión exacta de Chromium `158.0.8127.18` sigue sin parche acreditado para **CVE-2026-125350** (#320), una vulnerabilidad explotada. **Evita sitios externos/no confiables**; limita cualquier prueba a páginas locales controladas hasta resolver #320. Consulta [aceptación v0.3.0](v0.3.0-acceptance.es.md). Las pruebas de CI incluyen construcción AMD64,
navegación HTTP/JavaScript/WebSocket, capturas, comprobaciones negativas
de Landlock y limpieza de procesos. La aceptación con AGY real en TrueNAS
sigue sin verificarse; los tests opcionales de integración no la sustituyen.

Los binarios viven en `/opt/remote-dev/playwright-browsers` y no se instalan
en `/tmp` ni se descargan al arrancar.

## Validación

1. Ejecutar `python scripts/test-browser-config.py`.
2. Compilar la imagen y verificar que Chromium se instala sin Snap.
3. Abrir sesiones de Codex y AGY y comprobar que su MCP navega por una página
   local de prueba sin descargar nada.
4. Confirmar que se conservan los MCP personales, credenciales y configuraciones
   existentes, y que no hay nuevos puertos abiertos.
