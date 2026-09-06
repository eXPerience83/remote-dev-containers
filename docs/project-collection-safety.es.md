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

## Descubrimiento de ancestros Git

Los lanzamientos gestionados de proyectos con Codex y con Antigravity experimental establecen:

```text
GIT_CEILING_DIRECTORIES=/workspace
```

usando la ruta de colección validada. Así se evita que un proyecto vacío como `/workspace/new-project` herede silenciosamente un repositorio Git situado por encima de `/workspace`.

Remote Dev también rechaza valores heredados de `GIT_DIR`, `GIT_WORK_TREE` y `GIT_COMMON_DIR` en lanzamientos gestionados del agente, porque esas variables pueden redirigir Git fuera del contrato del proyecto seleccionado.

En Codex no basta con establecer la variable en el proceso padre: Codex puede aplicar su propia política de entorno de shell antes de ejecutar comandos alcanzables por el modelo. Por eso, la comprobación previa al lanzamiento lee la configuración **efectiva** de Codex mediante el app-server del runtime bundled/opcional y falla de forma cerrada si la política no conserva el valor gestionado de `GIT_CEILING_DIRECTORIES`. La comprobación es de solo lectura y no sustituye otras restricciones de entorno configuradas por el usuario.

## Qué ocurre cuando la colección queda bloqueada

Si `/workspace` contiene `.git`, se reconoce como repositorio Git bare o falla de otro modo la comprobación de seguridad de la colección:

- Codex Start y Resume se bloquean antes de invocar Codex;
- Antigravity experimental Start y Continue se bloquean antes de invocar el CLI del proveedor;
- se bloquean la detección, Select, Create y Delete de proyectos;
- se descarta una selección anterior del menú en lugar de reutilizar estado obsoleto;
- **Run diagnostics** sigue disponible;
- **Open a login shell** sigue disponible para recuperación manual;
- Remote Dev no borra `.git`, no ejecuta `git reset`, no ejecuta `git clean`, no mueve proyectos ni reescribe metadatos del repositorio automáticamente.

Doctor muestra la colección como `CRITICAL`/`BLOCKED` sin imprimir remotos, contenido del repositorio, credenciales u otros datos privados.

## Procedimiento de recuperación

Trata un repositorio Git en la raíz de la colección como un incidente de seguridad de datos hasta entender su origen.

1. Detén el trabajo gestionado de agentes en el rol afectado. No inicies otra sesión de agente contra esa colección.
2. Conserva primero los datos actuales. En TrueNAS, crea una snapshot adecuada del dataset o una copia equivalente antes de realizar una reparación destructiva.
3. Usa **Run diagnostics** para confirmar que la frontera de la colección es lo que está bloqueando el lanzamiento.
4. Usa **Open a login shell** solo para inspeccionar. Determina si `/workspace/.git` es un directorio, gitfile, enlace simbólico/entrada especial, o si `/workspace` es un repositorio bare.
5. Identifica a qué proyecto pertenecen realmente esos metadatos Git, si pertenecen a alguno, antes de mover o borrar nada.
6. Repara manualmente la estructura para que `/workspace` solo agrupe proyectos y cada repositorio tenga como raíz su `/workspace/<proyecto>` correspondiente.
7. Ejecuta de nuevo diagnostics. Los lanzamientos gestionados deben seguir bloqueados hasta que pasen tanto la comprobación de colección como la del proyecto seleccionado.

No uses como primer paso de recuperación un `git clean -fd`, `git reset --hard`, checkout forzado o limpieza similar desde la raíz de la colección. Si `/workspace` se ha convertido accidentalmente en la raíz del repositorio, Git puede interpretar los directorios de proyectos hermanos como contenido no rastreado y borrarlos.

## Recuperación cuando desaparece el directorio actual

Un agente puede renombrar o borrar el directorio del proyecto desde el que fue lanzado. Por eso el hardening posterior a la sesión recupera primero un directorio conocido y seguro mediante builtins del shell y después invoca los helpers externos de credenciales/estado. Se conserva el código de salida original del agente salvo que falle la propia recuperación del cwd seguro o el hardening obligatorio.

Así se evita que un cwd eliminado convierta el camino de limpieza en un segundo fallo de `getcwd`.

## Confinamiento experimental de Antigravity

Antigravity sigue siendo experimental y no pasa a ser una integración soportada en TrueNAS solo porque supere las comprobaciones comunes de colección.

Para la ruta experimental gestionada, Remote Dev actualmente:

- fuerza el flag del proveedor `--sandbox` documentado para la sesión;
- rechaza intentos del llamador de desactivar/sustituir el sandbox o usar el flag peligroso que omite permisos;
- valida `~/.gemini/antigravity-cli/settings.json` en **solo lectura** y conservando sus bytes;
- exige que `allowNonWorkspaceAccess` esté desactivado;
- exige que `permissions.deny` contenga `unsandboxed(*)`;
- rechaza reglas persistentes `unsandboxed(...)` en allow;
- rechaza reglas allow `read_file(...)` / `write_file(...)` que escapen léxicamente del proyecto seleccionado o atraviesen un enlace simbólico existente desde el proyecto hacia una ruta exterior.

La documentación actual del CLI de Google indica que `--sandbox` fuerza el sandbox durante la sesión, que los montajes de sistema de archivos se derivan de los permisos `read_file`/`write_file` y que la precedencia de permisos es `Deny > Ask > Allow`. También documenta `unsandboxed(...)` como el recurso de escape del sandbox. Consulta la documentación upstream de [Sandbox](https://antigravity.google/docs/cli/sandbox/) y [Permissions](https://antigravity.google/docs/permissions/).

Esa semántica documentada es necesaria, pero no constituye por sí sola evidencia suficiente para este proyecto. El runtime exacto de Antigravity admitido todavía debe superar la matriz desechable de aceptación en TrueNAS de #213. Si el runtime exacto no puede demostrar confinamiento de proyectos hermanos y estado privado con la topología soportada del contenedor exterior, Antigravity gestionado seguirá bloqueado; la corrección común/Codex no espera a esa prueba.

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
- validación de settings persistentes de Antigravity manteniéndose de solo lectura.

La evidencia final en TrueNAS debe usar proyectos A/B y canarios desechables. No reproduzcas nunca el caso destructivo de control contra datos de proyectos reales del usuario.
