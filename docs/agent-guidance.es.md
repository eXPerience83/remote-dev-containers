# Guía global para agentes

Remote Dev separa cuatro responsabilidades:

| Capa | Responsabilidad |
|---|---|
| Entorno Remote Dev | Defaults y restricciones mecánicas: herramientas de imagen en PATH, estado privado por rol, `$TMPDIR` ejecutable heredado, caches específicas, raíz de solo lectura y `/tmp` endurecido. |
| Guía global Remote Dev para agentes | Recordatorios breves entre proyectos mediante las instrucciones globales nativas de cada proveedor. |
| Instrucciones del repositorio/directorio | Comandos, versiones, entornos y restricciones más específicos; las convenciones legítimas del proyecto pueden concretar la guía global. |
| MCP/plugins | Capacidades y servicios externos, no política de entorno. |

La guía no es un motor de políticas ni una frontera de seguridad. El hardening del contenedor es independiente de la obediencia del modelo. No selecciona/detecta proyectos, activa `.venv`, carga `.env`, instala dependencias ni cambia PATH. Consulta el [contrato de herramientas](tool-matrix.md#project-toolchain-resolution).

## Fuente y ciclo de vida

La única regla redactada es [`config/agent-rules/development-environment.md`](../config/agent-rules/development-environment.md), instalada con propietario root y modo `0444` en `/usr/share/remote-dev/agent-rules/development-environment.md`. El helper inmutable `/usr/local/bin/remote-dev-agent-guidance` deriva ambas representaciones sin red:

```text
remote-dev-agent-guidance reconcile codex
remote-dev-agent-guidance reconcile antigravity
remote-dev-agent-guidance status codex
remote-dev-agent-guidance status antigravity
```

El helper está limitado al rol correspondiente del contenedor. Los wrappers existentes `run-codex` / `run-antigravity` reconcilian antes de una sesión real nueva/reanudada, después de validar runtime/proyecto y antes de ejecutar el proveedor. Startup, Login shell, navegación, Doctor, ayuda/versión y consulta de política no reconcilian. Las invocaciones directas del CLI vendor omiten estos wrappers gestionados.

Eliminar un bloque/archivo propio restaura el default en la siguiente sesión gestionada; no hay una opción separada para desactivarlo. Una actualización de imagen refresca la representación nativa en la siguiente sesión. Las instrucciones del usuario/proyecto pueden concretar la guía.

## Codex

El adaptador sigue la resolución global de Codex `rust-v0.160.0`: `$CODEX_HOME/AGENTS.override.md`, luego `$CODEX_HOME/AGENTS.md`, primer contenido no vacío tras recortar whitespace Unicode nativo. Las instrucciones globales preceden a las del repositorio/directorio. Consulta la [documentación oficial de AGENTS](https://learn.chatgpt.com/docs/agent-configuration/agents-md) y la [implementación fijada de resolución](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/codex-home/src/instructions/mod.rs).

Remote Dev posee solo este segmento acotado, inicialmente antepuesto al contenido global del usuario:

```text
<!-- BEGIN REMOTE DEV MANAGED DEVELOPMENT ENVIRONMENT -->
...regla canónica...
<!-- END REMOTE DEV MANAGED DEVELOPMENT ENVIRONMENT -->
```

La actividad del override se determina **después de retirar lógicamente un bloque propio válido**. Las instrucciones reales ajenas mantienen activo el override. Un override de solo whitespace sin bloque queda intacto. Si solo quedan nuestro bloque y whitespace del usuario, el adaptador retira únicamente ese bloque, conserva los bytes restantes y gestiona `AGENTS.md`. Sin archivo global activo crea/gestiona `AGENTS.md`; nunca activa un override vacío. Un override real añadido posteriormente pasa a ser el destino sin limpiar el archivo base inactivo.

Fuera del segmento se conservan los bytes del usuario, incluidos comentarios, saltos de línea y whitespace. Los segmentos válidos se actualizan idempotentemente; markers duplicados, parciales o malformados son conflictos. UTF-8 inválido, exceso de tamaño, symlinks, archivos especiales, ownership/modos inseguros o estado ambiguo se preservan con aviso. Codex omite un override que sea directorio y continúa ante errores recuperables de lectura: si ese fallback es inequívoco, Remote Dev puede gestionar el default seguro, pero sigue indicando `unsafe`. Symlinks legibles y entradas con codificación/tamaño incompatibles no se clasifican como inactivas. No se modifica ningún AGENTS de repositorio.

## Antigravity

La regla dedicada es `/root/.gemini/config/rules/remote-dev-development-environment.md`, dentro del mount privado existente `state/antigravity/config`. Comienza con:

```yaml
---
trigger: always_on
description: "Remote Dev development environment guidance"
---
```

El cuerpo es el mismo texto canónico entre los mismos markers de ownership. El archivo completo pertenece a Remote Dev solo cuando frontmatter exacto y un bloque completo acotado demuestran ownership; contenido adicional/desconocido es conflicto. Las colisiones ajenas en la ruta exacta nunca se sobrescriben, renombran ni eliminan. `GEMINI.md`, `AGENTS.md`, `settings.json`, otras reglas y archivos de proyecto permanecen intactos.

El adaptador depende del [contrato nativo de reglas modulares](https://www.antigravity.google/docs/rules/), no de una versión literal de Antigravity. No añade descargas ni ejecución de candidatos vendor. No introduce mounts, estado mutable de guía compartido, persistencia amplia HOME/XDG ni acceso del launcher.

## Diagnósticos y fallos

Status y Doctor solo leen el estado del rol correspondiente y nunca imprimen instrucciones/configuración privadas. Estados: `current`, `missing`, `stale`, `unowned-conflict`, `unsafe`, `unsupported`. Missing/stale se reconcilia en la siguiente sesión gestionada. Los conflictos/estado inseguro producen avisos y un código de diagnóstico degradado; nunca bloquean al proveedor únicamente porque no se pudo instalar la guía. Inspecciona ese estado manualmente; Remote Dev no repara objetos ajenos/inseguros.

El helper usa lecturas UTF-8 acotadas, validación de archivos regulares/ancestros sin symlinks, ownership esperado/permisos seguros, markers exactos, temporales privados en el directorio, revalidación de identidad del destino, reemplazo atómico y fsync. El estado nuevo usa archivos `0600` y directorios `0700`; conserva los modos seguros existentes. Estas comprobaciones no aíslan la guía de un proceso que ya controla el usuario del servicio/root del contenedor.

## Aceptación conductual suplementaria

CI prueba determinísticamente los adaptadores y el ciclo de vida sin red, con estado sintético y sin llamadas al modelo ni cuentas vendor. En un candidato exacto puede probarse opcionalmente ambos proveedores gestionados usando un runtime Antigravity ya instalado/admitido:

1. Un proyecto Python sintético tiene pytest solo en su `.venv`: observar uso explícito del entorno del proyecto.
2. Solicitar un entorno Python ejecutable ad-hoc: observar uso del `$TMPDIR` heredado.
3. Solicitar validación de contenedores sin Docker/backend: observar una explicación de capacidad ausente en vez de instalaciones globales o debilitamiento del aislamiento.

Registra revisión/digest del candidato, identidad del runtime admitido y observaciones sin contenido privado de prompts/credenciales. Estas observaciones dependientes del modelo complementan los tests deterministas y no condicionan CI. Un futuro adaptador debe revalidar su composición nativa, preservar contenido del usuario y reutilizar este texto canónico en su estado privado; aquí no se implementa ningún proveedor adicional.
