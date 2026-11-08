# OpenAI Docs MCP para Codex

El MCP oficial de documentación OpenAI se habilita por defecto únicamente cuando el estado privado de Codex está vacío en el primer arranque. Las instalaciones existentes conservan todos sus archivos; Context7 sigue siendo opcional. No se añaden parámetros ni montajes.

La inicialización local ocurre antes de ejecutar Codex, con el intérprete administrativo de la imagen. Una transacción privada `.remote-dev-initial-config-v1/` registra la decisión: su ausencia con un directorio vacío inicia la provisión; una transacción pendiente puede recuperarse; `done` impide volver a instalar después de eliminar o deshabilitar el servidor. Configuración publicada atómicamente sin reemplazar destinos, archivos 0600, bloqueo entre inicializadores. No edites el mismo estado mientras arranca. Si aparece otro estado antes de completar, se preserva y se omite la provisión. Errores de permisos o estado inseguro generan una advertencia, no una dependencia de salud.

La provisión no usa red. Codex puede conectarse al MCP para inicializar y descubrir herramientas al abrir una sesión, incluso antes de consultar documentación. `required=false`, inicio de 10 s y herramientas de 60 s acotan esperas; un fallo del MCP no debe impedir las sesiones normales. Las instrucciones globales añaden solo a Codex una guía selectiva; Antigravity conserva la guía común.

El servidor público remoto de OpenAI es de solo lectura, no necesita claves y no ejecuta la API en nombre del usuario. El proveedor recibe las conexiones y los argumentos de consultas; no envíes secretos, código privado o conversaciones completas. Esquemas y resultados pueden consumir contexto/tokens. No hay garantías adicionales sobre retención ni métricas privadas. La configuración persiste en el montaje privado CODEX_HOME; verificar el montaje no sustituye probar una recreación real en TrueNAS.

```bash
# Inspect configuration (not a connectivity test)
codex mcp get openaiDeveloperDocs
# Inventory; may perform authentication discovery
codex mcp list
# Add manually only if absent (existing installations)
codex mcp add openaiDeveloperDocs --url https://developers.openai.com/mcp
# Explicit removal
codex mcp remove openaiDeveloperDocs
```

En la sesión, usa `/mcp` y solicita una búsqueda y lectura documentales para comprobar funcionamiento real. Para deshabilitar sin eliminar, establece `enabled = false` en `[mcp_servers.openaiDeveloperDocs]`. No borres el marcador para reparar: inspecciona primero `codex mcp get` y añade manualmente solo si falta; conserva entradas personalizadas o deshabilitadas. Reinicia la sesión para comprobar cambios.

Sources: [Docs MCP](https://developers.openai.com/learn/docs-mcp), [Codex MCP configuration](https://developers.openai.com/codex/mcp/).
