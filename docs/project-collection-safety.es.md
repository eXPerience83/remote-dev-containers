# Seguridad y recuperación de la colección de proyectos

Este documento define la frontera de proyectos con fallo cerrado que pertenece a [#213](https://github.com/eXPerience83/remote-dev-containers/issues/213).

## La invariante

Para cada rol de agente, `/workspace` es una **raíz que agrupa proyectos**, nunca un repositorio de proyecto implícito. Las acciones gestionadas Start/Resume/Continue trabajan desde exactamente un hijo directo validado:

```text
/workspace/                 raíz de colección — no debe ser un repositorio Git
├── project-a/              posible proyecto seleccionado
├── project-b/              proyecto hermano
└── .remote-dev-tmp/        scratch de desarrollo de Remote Dev, no es un proyecto
```

Un proyecto puede ser un worktree Git normal, un worktree Git enlazado cuyo `.git` sea un gitfile, o un directorio vacío/sin Git. Si Git reconoce un repositorio para el proyecto seleccionado, la raíz efectiva de su worktree debe ser exactamente `/workspace/<proyecto-seleccionado>`.

La colección no puede contener una entrada `.git` de ningún tipo ni ser un repositorio Git bare. Remote Dev no intenta decidir si unos metadatos Git en la raíz de la colección son intencionados, antiguos o accidentales: las acciones gestionadas sobre proyectos se bloquean de forma segura.

Doctor también audita la estructura del primer nivel de la colección. Las entradas esperadas son directorios de proyecto válidos y, opcionalmente, el directorio gestionado `.remote-dev-tmp`. Otros archivos, enlaces simbólicos, directorios ocultos o entradas especiales se notifican para inspección manual; Doctor nunca los borra ni los modifica.

## Descubrimiento de ancestros Git

Los lanzamientos gestionados de proyectos con Codex y con Antigravity experimental establecen:

```text
GIT_CEILING_DIRECTORIES=/workspace
```

usando la ruta de colección validada. Así se evita que un proyecto vacío como `/workspace/new-project` herede silenciosamente un repositorio Git situado por encima de `/workspace`.

Remote Dev también rechaza asignaciones heredadas de `GIT_DIR`, `GIT_WORK_TREE`, `GIT_COMMON_DIR` y `GIT_OBJECT_DIRECTORY` en lanzamientos gestionados del agente, incluso cuando la variable está presente con valor vacío, porque esas variables pueden redirigir o alterar Git fuera del contrato del proyecto seleccionado.

En Codex no basta con establecer la variable en el proceso padre: Codex puede aplicar su propia política de entorno de shell antes de ejecutar comandos alcanzables por el modelo. Por eso, la comprobación previa al lanzamiento lee la configuración **efectiva** de Codex mediante el app-server del runtime bundled/opcional y falla de forma cerrada si la política no conserva el valor gestionado de `GIT_CEILING_DIRECTORIES`. La comprobación es de solo lectura y no sustituye otras restricciones de entorno configuradas por el usuario.

## Qué ocurre cuando la colección queda bloqueada

Si `/workspace` contiene `.git`, se reconoce como repositorio Git bare o falla de otro modo la comprobación de seguridad de la colección:

- Codex Start y Resume se bloquean antes de invocar Codex;
- Antigravity experimental Start y Continue se bloquean antes de invocar el CLI del proveedor;
- se bloquean la detección, Select, Create y Delete de proyectos;
- se descarta una selección anterior del menú en lugar de reutilizar estado obsoleto;
- **Run diagnostics** sigue disponible;
- **Open a login shell** sigue disponible para inspección/limpieza manual;
- Remote Dev no borra `.git`, no ejecuta `git reset`, no ejecuta `git clean`, no mueve proyectos ni reescribe metadatos del repositorio automáticamente.

Doctor muestra la colección como `CRITICAL`/`BLOCKED` sin imprimir remotos, contenido del repositorio, credenciales u otros datos privados.

## Limpieza manual

Remote Dev no automatiza deliberadamente la limpieza. Para una contaminación conocida y desechable/experimental, como el incidente confirmado de Antigravity, el operador puede eliminar manualmente la entrada exacta `/workspace/.git` después de comprobar que se trata de los metadatos no deseados de la raíz de colección. Como parte de esa limpieza no debe borrarse ninguna otra entrada de la colección.

Si los datos importan, inspecciónalos o crea una snapshot antes de una reparación destructiva. Nunca empieces con `git clean -fd`, `git reset --hard`, checkout forzado o una limpieza Git similar desde la raíz de la colección: si `/workspace` se ha convertido accidentalmente en la raíz del repositorio, Git puede interpretar los directorios de proyectos hermanos como contenido no rastreado y borrarlos.

Tras la limpieza manual, ejecuta Doctor de nuevo. La colección debe indicar que su raíz Git está limpia; las entradas inesperadas del primer nivel también deben inspeccionarse hasta que la estructura contenga únicamente directorios de proyecto válidos y el `.remote-dev-tmp` opcional.

## Recuperación cuando desaparece el directorio actual

Un agente puede renombrar o borrar el directorio del proyecto desde el que fue lanzado. Por eso el hardening posterior a la sesión recupera primero un directorio conocido y seguro mediante builtins del shell y después invoca los helpers externos de credenciales/estado. Se conserva el código de salida original del agente salvo que falle la propia recuperación del cwd seguro o el hardening obligatorio.

Así se evita que un cwd eliminado convierta el camino de limpieza en un segundo fallo de `getcwd`.

## Comportamiento específico de cada agente

La frontera de colección/Git es un contrato del runtime de Remote Dev compartido por Codex y Antigravity experimental. No introduce un nuevo sandbox anidado ni afirma aislamiento de filesystem frente a proyectos hermanos que sigan montados en el mismo contenedor de rol.

Esta diferencia es operativa, no teórica: una vez lanzado un agente autónomo dentro del proyecto validado, todavía puede ejecutar `cd ..` o acceder a cualquier otra ruta que los permisos ordinarios del filesystem del contenedor hagan visible y escribible, incluida la raíz de la colección o los proyectos hermanos. `GIT_CEILING_DIRECTORIES` limita únicamente el descubrimiento de ancestros de Git; no es un mecanismo de control de acceso al filesystem. Confinar las escrituras al proyecto seleccionado es un problema de hardening independiente y queda explícitamente fuera del alcance de #213/#214.

Codex conserva el modelo de contenedor exterior establecido por #36/#42 y su política autonomous/guarded actual. Antigravity conserva su comportamiento experimental de lanzamiento del proveedor; #213 no fuerza ni configura un sandbox del proveedor. Las futuras integraciones de agentes deberían reutilizar los helpers comunes de colección/proyecto en vez de reimplementar por separado la lógica de frontera Git.

## Expectativas de validación

La suite de regresión del repositorio cubre como mínimo:

- colección limpia + hijo vacío;
- repositorio cuya raíz es exactamente un hijo;
- worktree enlazado cuya raíz es exactamente un hijo;
- un repositorio Git ancestro por encima de la colección que no se hereda;
- `.git` en la raíz de la colección como directorio, gitfile, enlace simbólico/entrada especial, entrada malformada y repositorio bare;
- metadatos Git inválidos en el proyecto seleccionado;
- el mecanismo real de borrado de hermanos con `git clean -fd` desde la raíz, únicamente en una fixture de control desechable;
- canarios de proyectos hermanos que permanecen intactos cuando el preflight gestionado bloquea;
- recuperación de cwd eliminado antes del hardening posterior a la sesión;
- política efectiva del entorno de shell de Codex conservando el ceiling;
- Antigravity usando la misma entrada común a la colección y el mismo Git ceiling antes del lanzamiento del proveedor;
- Doctor notificando entradas inesperadas en la raíz de colección sin modificarlas.

La evidencia final en TrueNAS debe usar proyectos A/B y canarios desechables. No reproduzcas nunca el caso destructivo de control contra datos de proyectos reales del usuario.
