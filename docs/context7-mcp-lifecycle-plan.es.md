# Context7 — plan de diagnóstico y reinstalación por agente

**Estado verificado (14-11-2026):** PR #324 **integrado** en `main` y distribuido en Edge; la **aceptación funcional real** de Context7 en Codex y Antigravity y la revisión específica de terceros (#53) siguen pendientes. Este documento conserva hitos históricos y no autoriza `stable/latest`. Guía de pruebas: [v0.3.0](v0.3.0-acceptance.es.md).
**Fecha:** 13-11-2026. **Seguimiento:** issue #95 y revisión de terceros #53.
**Decisión:** [D016](decisions.md#d016--context7-is-a-role-local-hosted-mcp-registration-with-explicit-reinstall).
**Matriz completa y criterios técnicos:** [plan en inglés](context7-mcp-lifecycle-plan.md).

## Objetivo aprobado

La **imagen nueva** debe diagnosticar Context7 en Codex y en Antigravity y ofrecer **reinstalar únicamente su registro MCP** cuando esté ausente o dañado. No se trata de descargar/reinstalar un servidor Context7: es un servicio remoto alojado. Tampoco se pretende arreglar a mano una variante concreta del archivo que ya existe en TrueNAS.

| Aspecto | Codex | Antigravity |
|---|---|---|
| Archivo | `CODEX_HOME/config.toml` privado | `/root/.gemini/config/mcp_config.json` privado |
| Registro | TOML con URL, cabeceras y banderas de Context7 | JSON `mcpServers.context7.serverUrl` |
| Clave | Conservar la clave privada de Codex | Sin compartir claves: modo anónimo inicial |
| Diagnóstico | Menú, `status --menu`, `plan`, Doctor | Menú, `status --menu`, `plan`, Doctor |
| Reinstalación | `remote-dev-context7 reinstall --yes` | `remote-dev-context7-antigravity reinstall --yes` |
| Validación real | Herramienta Context7 desde Codex | `agy /mcp` y consulta real |

Reglas innegociables: diagnóstico **sin escrituras ni red**; acción explícita con aviso; proteger clave y otros MCP (Playwright y Developer Docs); copias de seguridad antes de escribir; bloqueo compartido con el configurador de Playwright; rechazo de casos ambiguos; sin instalar nada al arrancar; sin tocar credenciales de un agente desde el otro.

**Codex** puede restablecer las opciones de su propia entrada Context7 después de una confirmación expresa, solo si puede aislarla sin alterar otros MCP. **Antigravity no sigue esa política**: cualquier opción Context7 adicional, con o sin autenticación (por ejemplo `timeoutSeconds`, `disabled` o `disabledTools`), se considera configuración del usuario; la reinstalación se bloquea y requiere revisión manual. Nunca se borran las credenciales ni las opciones de otros MCP. Los MCP de proyecto y plugins necesitan diagnóstico separado.

## Hitos

1. **Implementación y pruebas offline:** adaptar TOML/JSON; menús; copias/rollback; errores de sintaxis, marcadores y entradas duplicadas; pruebas de propiedades y concurrencia.
2. **Revisión:** último SHA con CI íntegramente verde, CodeRabbit o auditoría manual documentada si hay limitación por cuota, y revisión específica de Context7-Antigravity bajo #53.
3. **Integrar en `main`:** con CI verde y observaciones relevantes de CodeRabbit corregidas, fusionar el PR #324 cuando el propietario lo autorice; no publicar una candidata `dev`.
4. **PR de actualizaciones:** después de integrar #324, rebasar o regenerar el PR de actualizaciones; validar y fusionar por separado.
5. **Edge y aceptación en TrueNAS:** publicar Edge desde el `main` integrado mediante sus controles propios; después actualizar voluntariamente y probar Context7 con Codex y Antigravity, el resto de MCP, claves separadas, idempotencia y rollback. Los fallos funcionales abrirán correcciones; esta aprobación no supone aceptar los resultados antes de probarlos. No modificar `stable/latest` con este PR.

**Pendiente:** verificaciones de configuración a nivel de proyecto en Antigravity, aceptación con agentes reales y revisión del contrato legal/privacidad específica. El CI verde no reemplaza estas pruebas.

PR #324 ya está fusionado; **no cerrar #95 ni declarar la integración aceptada en producción** mientras queden pendientes las pruebas reales y las decisiones humanas de la [matriz principal](context7-mcp-lifecycle-plan.md).
