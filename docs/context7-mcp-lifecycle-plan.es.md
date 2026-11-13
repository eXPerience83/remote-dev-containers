# Context7 — plan de diagnóstico y reinstalación por agente

**Estado:** EN DESARROLLO, PR #324 en borrador; no autoriza ninguna publicación.
**Fecha:** 13-11-2026. **Seguimiento:** issue #95 y revisión de terceros #53.
**Decisión:** [D016](decisions.md#d016--context7-is-a-role-local-hosted-mcp-registration-with-explicit-reinstall).
**Matriz completa y criterios técnicos:** [plan en inglés](context7-mcp-lifecycle-plan.md).

## Objetivo aprobado

La **imagen nueva** debe diagnosticar Context7 en Codex y en Antigravity y ofrecer **reinstalar únicamente su registro MCP** cuando esté ausente o dañado. No se trata de descargar/reinstalar un servidor Context7: es un servicio remoto alojado. Tampoco se pretende arreglar a mano una variante concreta del archivo que ya existe en TrueNAS.

| Aspecto | Codex | Antigravity |
|---|---|---|
| Archivo | \`CODEX_HOME/config.toml\` privado | \`/root/.gemini/config/mcp_config.json\` privado |
| Registro | TOML con URL, cabeceras y banderas de Context7 | JSON \`mcpServers.context7.serverUrl\` |
| Clave | Conservar la clave privada de Codex | Sin compartir claves: modo anónimo inicial |
| Diagnóstico | Menú, \`status --menu\`, \`plan\`, Doctor | Menú, \`status --menu\`, \`plan\`, Doctor |
| Reinstalación | \`remote-dev-context7 reinstall --yes\` | \`remote-dev-context7-antigravity reinstall --yes\` |
| Validación real | Herramienta Context7 desde Codex | \`agy /mcp\` y consulta real |

Reglas innegociables: diagnóstico **sin escrituras ni red**; acción explícita con aviso; proteger clave y otros MCP (Playwright y Developer Docs); copias de seguridad antes de escribir; bloqueo compartido con el configurador de Playwright; rechazo de casos ambiguos; sin instalar nada al arrancar; sin tocar credenciales de un agente desde el otro.

La reinstalación **sí restablece las personalizaciones de la propia entrada Context7** cuando el usuario lo confirma. Nunca debe borrar personalizaciones de otros MCP ni secretos de una entrada Context7 con autenticación propia de Antigravity. Los MCP definidos a nivel de proyecto y plugins pertenecen al usuario y necesitan diagnóstico separado.

## Hitos

1. **Implementación y pruebas offline:** adaptar TOML/JSON; menús; copias/rollback; errores de sintaxis, marcadores y entradas duplicadas; pruebas de propiedades y concurrencia.
2. **Revisión:** último SHA con CI íntegramente verde, CodeRabbit o auditoría manual documentada si hay limitación por cuota, y revisión específica de Context7-Antigravity bajo #53.
3. **Candidata aislada:** publicar \`candidate-pr-324-<sha>\` y canal \`dev\` únicamente tras validación. No confundir la candidata antigua anterior al rediseño con la nueva.
4. **Aceptación en TrueNAS:** probar en Codex y Antigravity reales, verificar Context7, el resto de los MCP, las claves separadas, idempotencia y rollback.
5. **Cierre:** solo tras GO funcional y seguridad, fusionar, publicar Edge con su propio CI y actualizar TrueNAS con autorización. Nunca modificar \`stable/latest\` por este PR.

**Pendiente:** verificaciones de configuración a nivel de proyecto en Antigravity, aceptación con agentes reales y revisión del contrato legal/privacidad específica. El CI verde no reemplaza estas pruebas.

No fusionar PR #324 ni considerar aprobado el desarrollo mientras queden puertas abiertas en la [matriz principal](context7-mcp-lifecycle-plan.md).
