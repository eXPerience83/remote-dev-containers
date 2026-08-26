# Guía de uso de Remote Dev

Esta guía cubre el uso diario normal **después de instalar Remote Dev**. Para la entrada de instalación en TrueNAS SCALE, empieza por el [README en español](../README.es.md#instalar-en-truenas-scale).

Remote Dev sigue siendo experimental. Codex es el agente de referencia. Antigravity continúa como rol experimental habilitado de forma explícita y su validación real de proyectos/sesiones en TrueNAS se sigue por separado en [#131](https://github.com/eXPerience83/remote-dev-containers/issues/131).

## 1. Modelo mental

Cada servicio de agente tiene su árbol de workspace privado:

```text
Servicio de rol Remote Dev
/workspace/                    <- raíz que agrupa proyectos
├── pollenlevels/              <- un proyecto / ruta exacta
├── remote-dev-containers/     <- otro proyecto / ruta exacta
└── feature-worktree/          <- ruta distinta aunque sea el mismo repo Git
```

`/workspace` es la **raíz que agrupa proyectos**, no el directorio de trabajo normal del repositorio. Antes de iniciar o reanudar un agente, Remote Dev selecciona un hijo directo validado, por ejemplo `/workspace/pollenlevels`.

Seleccionar un proyecto cambia el directorio de trabajo predeterminado del agente; **no** crea aislamiento de sistema de archivos entre proyectos hermanos. Todo el montaje `/workspace` privado del rol sigue disponible para los procesos de ese contenedor. Codex y Antigravity usan árboles de workspace y estado privados distintos, así que no debes asumir que un proyecto visible en un rol existe también en el otro.

La autenticación, configuración y el historial de sesiones del agente viven en el estado persistente privado del rol, no dentro del checkout del proyecto. Por eso borrar o renombrar un proyecto no elimina automáticamente el historial de sesiones del agente.

## 2. Seleccionar, crear o borrar un proyecto

El flujo normal de Codex es:

1. Abre el launcher de Remote Dev y después el terminal de Codex.
2. Entra en **Projects...** desde el menú de Codex.
3. Selecciona un proyecto existente o crea uno nuevo.
4. Tras seleccionar o crear correctamente el proyecto, Remote Dev vuelve al menú de Codex; comprueba la línea `Project:`.
5. Elige **Start Codex** o **Resume a Codex session (current project)**.

Antigravity usa el mismo contrato de navegación de **Projects...**: tras una acción Select/Create correcta, Remote Dev vuelve al menú de Antigravity con ese proyecto activo para que puedas elegir **Start Antigravity** o **Continue latest Antigravity conversation (current project)**.

Las acciones Select/Create canceladas, inválidas o fallidas permanecen en **Projects...** para que puedas reintentarlas o usar Back de forma explícita. Delete también permanece en **Projects...** después de la operación para que puedas revisar o seguir gestionando los proyectos restantes.

La detección de proyectos es deliberadamente no recursiva:

- cero proyectos válidos: Start/Resume queda bloqueado hasta que exista uno;
- exactamente un proyecto válido: se selecciona automáticamente;
- varios proyectos válidos: debes elegir uno explícitamente;
- la selección activa pertenece solo a la vida del menú/tmux actual y no se guarda en un nuevo archivo de estado global.

**Create project** crea un único hijo directo vacío de `/workspace`. No ejecuta `git init`, no clona un repositorio y no contacta con servicios remotos.

**Delete project** es destructivo. Remote Dev muestra la ruta y exige escribir el nombre exacto del proyecto antes de borrar recursivamente ese directorio. Haz commit, push o copia de seguridad de lo que debas conservar. Borrar un proyecto no elimina la autenticación de Codex ni el historial de sesiones guardado en `CODEX_HOME`.

Los nombres se limitan a 1–128 caracteres ASCII: letras/dígitos más `.`, `_` y `-`, empezando por una letra o un dígito. Se rechazan traversal, barras, nombres con punto inicial y entradas de proyecto que sean symlinks.

## 3. Sesiones de Codex y Resume

El comportamiento siguiente se validó en TrueNAS real con Codex `0.147.0`. El selector Resume es **UI nativa de Codex**, por lo que runtimes opcionales más nuevos pueden cambiar etiquetas o teclas. Si la TUI difiere, su pie de pantalla es la fuente inmediata de verdad.

Remote Dev lanza **Resume a Codex session (current project)** con el proyecto seleccionado como directorio de trabajo explícito de Codex. En el selector probado:

- `[Cwd]` es el filtro normal y muestra sesiones cuyo cwd guardado coincide exactamente con la ruta del proyecto seleccionado;
- se conservan y pueden aparecer juntas varias sesiones con contenido real del mismo proyecto exacto;
- cambiar de proyecto en Remote Dev cambia el conjunto normal de `[Cwd]` sin borrar historial;
- una sesión recién abierta puede no tener una vista previa útil hasta contener un mensaje de usuario significativo;
- `All` elimina deliberadamente el filtro de cwd y puede mostrar sesiones creadas desde otras rutas;
- seleccionar con `All` un hilo histórico no mueve su historial al directorio del proyecto; Remote Dev sigue iniciando el proceso reanudado de Codex con el proyecto actualmente seleccionado como directorio de trabajo;
- las rutas exactas importan: dos clones o worktrees del mismo repositorio Git son ámbitos `[Cwd]` normales distintos;
- renombrar o borrar un proyecto puede dejar sesiones históricas asociadas a la ruta antigua, normalmente visibles mediante `All` y no mediante el nuevo `[Cwd]`.

Ejemplo:

```text
/workspace/pollenlevels
/workspace/remote-dev-containers
```

Si está seleccionado `pollenlevels`, `[Cwd]` muestra normalmente solo sesiones cuyo cwd guardado sea `/workspace/pollenlevels`. Cambia el proyecto de Remote Dev a `remote-dev-containers` y `[Cwd]` pasa a mostrar las sesiones de esa ruta exacta. `All` puede mostrar ambos conjuntos.

### Controles del selector Resume

Controles nativos probados en Codex `0.147.0`:

| Tecla | Comportamiento probado |
| --- | --- |
| `Tab` | Mueve el foco entre controles de la barra, como filtro/orden. |
| Izquierda / Derecha | Cambia la opción enfocada, incluido `Cwd` / `All`. |
| Arriba / Abajo | Recorre las sesiones. |
| `Enter` | Reanuda la sesión seleccionada. |
| `Esc` | Sale del selector/inicia una sesión nueva según la pantalla nativa. |
| `Ctrl+C` | Cierra el selector. |

Son controles de Codex upstream, no un protocolo de teclado propio de Remote Dev.

## 4. El terminal web, tmux y el agente son capas distintas

```text
navegador / ttyd  ->  tmux  ->  TUI de Codex o shell
```

Una desconexión del navegador no significa necesariamente que la sesión de desarrollo haya terminado. Remote Dev usa tmux para que, al volver al mismo endpoint del rol, sea posible adjuntarse a la sesión de menú/tmux que siga viva.

Dentro del menú de Remote Dev:

- al salir de Codex, el control vuelve al menú cuando termina la acción interactiva;
- **Open a login shell** abre una shell general y no un lanzamiento del agente;
- **Exit this tmux session** termina esa sesión tmux, en lugar de limitarse a cerrar la pestaña del navegador.

La selección del proyecto es estado del proceso menú/tmux. Una desconexión/reconexión normal del navegador al mismo tmux vivo puede conservarla. Una recreación completa del contenedor/tmux puede iniciar un proceso de menú nuevo y, por tanto, exigir seleccionar el proyecto otra vez; eso no implica que se hayan perdido los directorios de proyecto ni el historial del agente.

### Soluciones provisionales actuales para portapapeles y móvil

El cliente de terminal propio previsto en #90/#91 todavía no ha llegado. Hasta entonces se aplica el comportamiento provisional recogido en [#87](https://github.com/eXPerience83/remote-dev-containers/issues/87):

- `Ctrl+V` puede ser consumido por la TUI activa; `Ctrl+Shift+V` funcionó para pegar en el entorno de escritorio probado;
- con el manejo de ratón de tmux/TUI, mantén `Shift` al arrastrar para hacer selección normal de texto del navegador/xterm en el camino de escritorio probado;
- el atajo final de copia depende hoy de navegador/SO/distribución de teclado; Firefox puede reservar `Ctrl+Shift+C` para las herramientas de desarrollo;
- una prueba con distribución española copió mediante `Ctrl+AltGr+C`, pero es solo una observación, **no** el contrato de atajo de Remote Dev;
- en Android puede hacer falta temporalmente un teclado que exponga teclas de terminal como `Esc` y `Ctrl`.

No desactives globalmente el ratón de tmux ni añadas puentes gráficos/portapapeles del host dentro del contenedor como solución.

## 5. Verificar instrucciones del proyecto (`AGENTS.md`)

Remote Dev no interpreta ni gestiona el `AGENTS.md` del repositorio. Inicia Codex dentro del proyecto seleccionado para que Codex realice su detección upstream normal de instrucciones.

En Codex `0.147.0` probado, la comprobación más útil es la pantalla nativa `/status`:

1. Selecciona el proyecto de Remote Dev previsto.
2. Inicia Codex.
3. Ejecuta `/status`.
4. Comprueba `Directory: /workspace/<proyecto>`.
5. Comprueba la entrada `Agents.md:` esperada, por ejemplo `Agents.md: AGENTS.md` para un archivo en la raíz.

No copies el contenido privado de `AGENTS.md` a diagnósticos solo para demostrar que cargó. Las filas de directorio y fuentes de instrucciones de `/status` son mejor evidencia que preguntar al modelo cómo recibió las instrucciones.

## 6. Herramientas y entornos propios del proyecto

Remote Dev proporciona el sustrato general de desarrollo: por ejemplo Python, Node.js, `uv`, `mise`, Git y GitHub CLI. Intencionadamente **no** instala globalmente todos los linters, runners de tests o paquetes específicos de cada repositorio.

El proyecto es dueño de su lock de dependencias y de su entorno. Un `.venv` de Python creado debajo de `/workspace/<proyecto>` vive en ese workspace persistente. Que `.venv` esté ignorado por Git depende del propio repositorio y debe definirlo ese proyecto.

`uv sync` realiza por defecto una sincronización exacta. Si un repositorio separa herramientas en grupos de dependencias, sincronizar solo un grupo puede eliminar paquetes que pertenezcan únicamente a otro grupo. Es comportamiento normal del entorno del proyecto, no una señal de que Remote Dev haya perdido paquetes al recrear el contenedor.

Un ejemplo real validado es `pollenlevels`, donde Ruff está fijado únicamente en el grupo `lint` y el proyecto usa `default-groups = []`. La secuencia definida por ese repositorio es:

```bash
uv lock --check
uv sync --locked --only-group lint
uv run --locked --no-sync ruff check .
uv run --locked --no-sync ruff format --check .
```

`--no-sync` impide deliberadamente reparar/instalar dependencias que falten. Si una tarea prohíbe explícitamente instalaciones o red, el agente debe informar de que falta la herramienta del proyecto en lugar de ejecutar `uv sync` silenciosamente.

Sigue siempre el `AGENTS.md`, lockfile y comandos CI del repositorio seleccionado; no copies el ejemplo de `pollenlevels` sin comprobar el proyecto actual.

## 7. Qué persiste

Remote Dev separa el estado persistente por función:

- los directorios de proyecto persisten mediante el bind mount privado de workspace del rol;
- la autenticación, configuración e historial de sesiones de Codex persisten en el mount privado de estado de agente de Codex;
- GitHub CLI, Git y SSH tienen mounts persistentes privados separados por rol;
- un runtime opcional admitido de Codex tiene su propio estado de runtime privado de Codex;
- los archivos temporales normales y las cachés de uv/npm/pip persisten bajo el árbol privado del rol `/workspace/.remote-dev-tmp`;
- la selección activa de proyecto es únicamente estado del proceso menú/tmux actual.

El sistema de archivos raíz del contenedor es de solo lectura. `/tmp` y `/run` siguen siendo tmpfs privados y acotados; `/tmp` también usa `noexec`. Las sesiones normales de Codex y Antigravity fijan `TMPDIR`, `TMP`, `TEMP` y las variables de caché de uv/npm/pip en hijos fijos de `/workspace/.remote-dev-tmp`, de modo que las cargas de desarrollo potencialmente grandes usan el workspace privado respaldado por disco. Este directorio oculto no es un proyecto y es scratch no confiable, nunca staging confiable de actualización, admisión, publicación o credenciales. Para limpiarlo, detén el servicio del rol, borra `.remote-dev-tmp` de su workspace en el host y reinicia; el arranque recrea de forma segura los directorios fijos. No guardes credenciales, configuración ni trabajo de proyecto en el scratch ni en los tmpfs transitorios.

Recrear el contenedor con los mismos mounts revisados debería conservar los directorios de proyecto y el estado del agente aunque arranque un proceso nuevo. Si se borra un proyecto, el historial de Codex puede seguir conteniendo sesiones de la ruta antigua porque ese historial no estaba almacenado en el checkout eliminado.

## 8. Antigravity: límite documental actual

Antigravity continúa siendo experimental. El comportamiento común que es seguro documentar con la implementación actual de Remote Dev es el contrato de selección del sistema de archivos junto con los puntos de entrada de conversación documentados por el proveedor:

- el rol Antigravity tiene su propio `/workspace` y estado privados;
- selecciona un proyecto concreto de Remote Dev antes de Start/Continue;
- Remote Dev inicia todas las acciones de Antigravity desde el cwd del proyecto seleccionado;
- **Start Antigravity** abre la TUI normal; usa `/resume` dentro de ella para explorar/reanudar conversaciones anteriores mediante el selector nativo de Google;
- **Continue latest Antigravity conversation** pasa el flag `--continue` soportado por el proveedor y pide a Antigravity cargar la conversación más reciente asociada a ese workspace;
- Remote Dev no expone una acción separada para explorar conversaciones ni interpreta el almacenamiento/caché de Antigravity para construir un selector alternativo;
- las rutas de reanudación del menú ya no dependen del texto renderizado del prompt para decidir cuándo inyectar `/resume`, porque la apariencia de la TUI del proveedor puede cambiar de forma independiente al contrato CLI.

Google documenta que `--continue` puede caer en una sesión nueva cuando la caché del workspace no contiene una conversación previa válida. El selector `/resume` dentro de la TUI sigue siendo la vía correcta cuando necesitas elegir entre varias conversaciones o conversaciones anteriores.

**No** extrapoles a Antigravity el filtrado de sesiones, visibilidad de previews, reasociación hilo/ruta ni semántica de persistencia de Codex. La validación real de proyectos/sesiones en TrueNAS sigue en [#131](https://github.com/eXPerience83/remote-dev-containers/issues/131), dentro del ciclo experimental más amplio de #29/#106.

## 9. Resolución rápida de problemas

### `No sessions yet` después de cambiar de proyecto

Comprueba el filtro del selector de Codex. `[Cwd]` está acotado a la ruta exacta; el proyecto seleccionado puede no tener sesiones aunque otro proyecto sí.

### Una sesión aparece en `All` pero no en `[Cwd]`

Su cwd guardado no coincide con la ruta exacta del proyecto actual. Es normal para otros proyectos, worktrees, rutas renombradas y directorios históricos.

### Dos clones del mismo repositorio muestran sesiones distintas

El filtro normal probado de Codex usa el cwd exacto, no la identidad del remoto Git. Clones/worktrees con rutas distintas son ámbitos `[Cwd]` distintos.

### El proyecto se renombró o se borró

El checkout del proyecto y el historial de sesiones de Codex son estados separados. El historial de la ruta antigua puede seguir visible mediante `All`; crea/selecciona el proyecto actual correcto en lugar de asumir que el historial se movió.

### Una shell se abre en `/workspace`

Es lo esperado para el modo shell general. Start/Resume del agente selecciona un `/workspace/<proyecto>` concreto; la shell es intencionadamente una shell de operador en la raíz que agrupa proyectos.

### Se desconectó el navegador

Vuelve a entrar al mismo endpoint del rol antes de asumir que tmux terminó. Cerrar una pestaña/perder red es distinto de usar **Exit this tmux session** o recrear el contenedor/proceso tmux.

### Copiar/pegar o las teclas de Android resultan incómodas

Usa la guía provisional anterior y [#87](https://github.com/eXPerience83/remote-dev-containers/issues/87). #90 y #91 son los issues de la futura experiencia soportada de teclas móviles y copia de selección.

## Documentación relacionada

- [README en español](../README.es.md) — instalación, resumen de arquitectura y advertencias.
- [Actualizaciones del runtime de Codex](codex-runtime-updates.es.md) — admisión y fallback del runtime oficial opcional.
- [Context7 para Codex](context7-codex.es.md) — integración MCP alojada opcional.
- [Seguridad](security.md) — límite de aislamiento soportado en el contenedor exterior.
- [Canales de release](releases.es.md) — `dev`, `edge`, `stable` y rollback.
- [Matriz de herramientas](tool-matrix.md) — herramientas incluidas en la imagen frente a tooling que pertenece al proyecto.
