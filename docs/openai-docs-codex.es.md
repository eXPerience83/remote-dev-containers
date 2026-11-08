# OpenAI Docs MCP para Codex

Estado: funcionalidad Unreleased de PR #312, aún no incluida en la imagen estable v0.2.0. Para probarla, verifica la revisión fuente con `remote-dev-version` y compárala con el SHA del candidato del PR que contiene este cambio; un contenedor antiguo no configura el MCP automáticamente aunque su estado esté vacío.

El MCP oficial de documentación OpenAI se habilita por defecto únicamente cuando el estado privado de Codex está vacío en el primer arranque. Las instalaciones existentes conservan todos sus archivos; Context7 sigue siendo opcional. No se añaden parámetros ni montajes.

La inicialización local ocurre antes de ejecutar Codex, con el intérprete administrativo de la imagen. Una transacción privada `.remote-dev-initial-config-v1/` registra la decisión: su ausencia con un directorio vacío inicia la provisión; una transacción pendiente puede recuperarse; `done` impide volver a instalar después de eliminar o deshabilitar el servidor. Configuración publicada atómicamente sin reemplazar destinos, archivos 0600, bloqueo entre inicializadores. No edites el mismo estado mientras arranca. Antes de la decisión inicial, cualquier estado existente omite la provisión. Una decisión de estado vacío se conserva durante la recuperación aunque Codex cree otros archivos; un config.toml concurrente siempre tiene prioridad. El bloqueo espera como máximo dos segundos antes de avisar y continuar. Los estados existentes registran la omisión en `.remote-dev-initial-config-skipped-v1/`. Errores de permisos o estado inseguro generan una advertencia, no una dependencia de salud.

La provisión no usa red. Codex puede conectarse al MCP para inicializar y descubrir herramientas al abrir una sesión, incluso antes de consultar documentación. `required=false`, inicio de 10 s y herramientas de 60 s acotan esperas; la disponibilidad de sesiones normales con el MCP inaccesible es un objetivo de diseño pendiente de aceptación sobre el candidato exacto; las pruebas registradas aún no demuestran sus tiempos ni comportamiento. Las instrucciones globales añaden solo a Codex una guía selectiva; Antigravity conserva la guía común.

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

Si `done` está malformado, detén el servicio antes de repararlo. Comprueba que la transacción es un directorio privado real, sin enlaces, y conserva config.toml y cualquier decisión de desactivación/eliminación. Retira solo el enlace de staging `.remote-dev-initial-config.toml` dentro de la transacción, si existe; no borres config.toml. Sustituye atómicamente solo `done`, mediante un temporal privado en ese directorio, por los bytes `done` seguidos de salto de línea, con modo 0600 y propietario correcto. Esto marca la inicialización como completada sin instalar ni reactivar el MCP. Si las rutas/propietarios no son seguros, requiere reparación manual por el administrador; no ejecutes la provisión sobre ese estado.
