# Auditoría integral de interacción de menús (Codex / Antigravity / Shell)

Seguimiento: issue #357. Motivación: en TrueNAS Edge la **misma opción 2 Test de Context7** pide `y/N` en Codex y escribir `TEST` en Antigravity. Revisamos **todo el recorrido, confirmaciones, ejecución real y vuelta**, no solo los rótulos. Las pruebas de herramientas MCP reales se mantienen aparte en #355/#356 (borrador).

## Todas las ramas y confirmaciones

| Ruta / opción | Codex | Antigravity | Resultado / consentimiento |
| --- | --- | --- | --- |
| Principal → 1 Start | `run-codex` en proyecto validado | `run-antigravity` en proyecto del rol | Ejecución nativa, hardening y pausa; jamás invocar otro proveedor |
| Principal → 2 Resume/Continue | `codex resume` | `agy --continue` | Diferencia real del proveedor; mismo retorno |
| 3 Projects → 1 Select → selector | Proyectos del volumen privado Codex | Proyectos privados AGY | Selector muestra **0 Back**, acepta alias histórico N+1; éxito vuelve a principal |
| 3 → 2 Create | Nombre de proyecto y creación segura | Igual | Éxito selecciona y regresa; errores mantienen Projects |
| 3 → 3 Delete → selector | Validación y borrado con límites | Igual | Requiere **nombre exacto**; permanece en Projects tras borrar |
| 3 → 0 Back | No modifica estado | Igual | Alias 4 del menú Projects aceptado sin mostrar |
| 4 Approval → 1/2/3 | Configurado/autónomo/guarded | Mismos modos, implementación AGY propia | Solo próximo lanzamiento, sin escritura persistente |
| 4 → 4/5 Presets Guarded | No disponibles | Modifica `toolPermission` persistente | **Confirmación `y/N`**, cancelar no escribe; pausa y retorno |
| 4 → 0 Back | Sin modificar | Igual | Alias histórico de Codex 4 y AGY 6 |
| 5 Manage → 1 | Actualizar Codex oficial | Instalar AGY solo si ausente | Gestores oficiales, confirmación propia y controles de integridad |
| 5 → 2 | Eliminar actualización Codex / fallback | Actualizar AGY instalado o dañado | `y/N` de backend; estado desconocido bloquea |
| 5 → 3 | Login Codex por código | Información del login nativo AGY | Diferencia justificada; AGY no inicia sesión desde el menú |
| 5 → 0 Back | Sin cambios | Igual | Principal |
| 6 MCP → 1 Context7 | Gestor de Codex | Gestor de AGY | Opciones 1–5 y 0 compartidas; credenciales privadas de cada agente |
| Context7 → 1 Estado/diagnóstico | Status y plan offline | Igual | Sin red ni modificación; Enter para volver |
| Context7 → 2 Test | Configuración Codex y HTTP | Configuración AGY y HTTP | **Mismo `[y/N]`**, divulgación del servicio Upstash. Cancelar no llama al gestor; aceptar llama a `test --yes`, devuelve estado, endurece y pausa |
| Context7 → 3 Autenticación | API key privada, alta/dispositivo | Instrucciones `agy /mcp` OAuth | Por diseño, distintos; jamás copiar tokens entre roles |
| Context7 → 4 Install/repair | Alta con onboarding; reparación `reinstall --menu-safe` | Alta nativa; reparación `reinstall` | **El alta inicial pide el mismo y/N en ambos menús**; Codex abre después su asistente privado de autenticación y AGY delega en su gestor JSON. Los comandos directos conservan sus confirmaciones propias. El alta inicial desde el menú Antigravity exige además que Context7 **siga ausente dentro del bloqueo de escritura**; si otra sesión modifica su registro mientras aparece la confirmación, se bloquea el alta sin reemplazarlo silenciosamente. La **reparación** exige `REINSTALL` exacto en ambos menús, después `--yes`; estado bloqueado nunca escribe |
| Codex Context7 → 3/4 → asistente de autenticación | Login por dispositivo / clave existente / conservar clave / anónimo | AGY utiliza su `/mcp` nativo | El asistente Codex muestra **0 Cancel**, admite el 5 histórico sin efectos |
| Codex device login → selector de versión CLI | Versión revisada fijada / última oficial, pendiente de revisión | Sin equivalente propio en Remote Dev para AGY | Selector de versión muestra **0 Cancel**; el 3 histórico sigue cancelando sin adoptar credenciales |
| Context7 → 5 Remove | Quita registro y **clave local** | Quita registro, **no revoca OAuth** | Teclear **`REMOVE`** en ambos, después `--yes` |
| Context7 → 0 / MCP → 0 | Volver un nivel | Igual | Ninguna modificación |
| Principal → 7 GitHub CLI | Login web y configuración Git | Igual | Credenciales privadas por rol |
| Principal → 8 Diagnósticos | Doctor por proveedor | Igual | Diagnóstico sin confirmación, pausa al terminar |
| Principal → 9 Shell | `bash --login` | Igual | Vuelta endureciendo estado |
| Principal → 0 Exit | Cierra sesión tmux | Igual | No cierra cuentas ni elimina secretos |
| Rol de emergencia Shell → 1/2/3/0 | Shell / GitHub / Doctor / salir | Independiente | **0 Exit** visible; 4 histórico sigue aceptándose |

## Reglas de seguridad y regresión

- Mismo riesgo, misma interfaz: prueba de red `y/N`; reparar/eliminar Context7 `REINSTALL` / `REMOVE`; borrar un proyecto exige nombre exacto. Los logins específicos mantienen sus flujos nativos. Los comandos CLI invocados **fuera del menú conservan sus propias confirmaciones**.
- Cancelar, responder incorrectamente, agotar stdin o pulsar Back nunca debe ejecutar tests/instalaciones/borrados ni manipular credenciales. El menú solo envía `--yes` cuando ya obtuvo confirmación.
- Las etiquetas similares no implican mezclar comandos: cada rama ejecuta su gestor con el rol correcto; se preservan respaldos, permisos, límites del workspace y aislamiento OAuth/API key.
- Un `/ping` de Context7 **no demuestra** llamadas MCP reales; mejoras técnicas en #355/#356. Las pruebas del CI no consultan la red.
- Colección de proyectos bloqueada: **Select/Create/Delete se interceptan antes de entrar en sus flujos**; la biblioteca runtime mantiene su propia comprobación de límites. Los fixtures de ambos proveedores verifican que no se presentan selectores ni confirmaciones de borrado, ni se ejecutan agentes.
- Cobertura: contratos estructurales de **todos los menús** y fixtures reales de consentimiento/cancelación/acciones por rol, además de los tests existentes de operaciones y seguridad.

Este cambio no despliega TrueNAS, no actualiza `stable/latest` y no acredita autenticación real ni subsana el bloqueo de Chromium (#320).
