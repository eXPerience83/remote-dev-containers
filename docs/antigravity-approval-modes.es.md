# Modos de aprobación de Antigravity

## Alcance

Remote Dev expone una única abstracción de modo de aprobación para Antigravity:

```text
autonomous | guarded
```

Esto cambia únicamente el comportamiento de confirmación de Antigravity dentro de la autoridad que ya tiene el contenedor del rol Antigravity. **No** crea un sandbox de sistema de archivos, no amplía mounts/capabilities y no habilita el sandbox de terminal del proveedor.

La frontera de aislamiento soportada sigue siendo el contenedor exterior endurecido más la frontera del proyecto/Git seleccionado.

## Valor predeterminado y configuración de despliegue

El valor predeterminado es `autonomous`, igual que en la UX de Remote Dev para Codex.

Compose genérico puede configurarlo con:

```dotenv
REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE=autonomous
# o: guarded
```

El YAML de referencia para TrueNAS también deja el rol Antigravity en `autonomous` de forma predeterminada.

El orden de resolución del modo es:

1. `--approval-mode autonomous|guarded` para un solo lanzamiento;
2. `REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE`;
3. valor interno predeterminado `autonomous`.

`run-antigravity --print-policy` informa del modo resuelto y de su origen sin ejecutar el CLI del proveedor ni realizar la verificación completa de integridad del runtime.

## Autonomous

En un lanzamiento gestionado autónomo, Remote Dev añade el override por lanzamiento validado con Antigravity CLI 1.1.28:

```text
--dangerously-skip-permissions
```

La validación real en TrueNAS de #159 demostró que elimina las paradas normales por aprobación de herramientas y revisión de artefactos durante ese lanzamiento, funciona igual en Start y `--continue` y no deja estado de autonomía persistente al salir. Un lanzamiento posterior en guarded vuelve a pedir permisos.

El wrapper es propietario de este argumento. Pasar `--dangerously-skip-permissions` directamente a través de `run-antigravity` se rechaza para impedir que el llamador contradiga el resolver de modo de Remote Dev.

Remote Dev no fuerza además `--mode=accept-edits`, `--mode=plan`, `--sandbox`, `toolPermission`, `artifactReviewPolicy` ni `agentMode`.

Las reglas finas de permisos del proveedor siguen siendo propiedad del usuario. En el comportamiento validado de 1.1.28, una regla explícita `permissions.deny` siguió bloqueando el comando correspondiente incluso en autonomous.

## Guarded

El modo guarded omite el argumento de bypass y utiliza el comportamiento normal de solicitud/revisión del proveedor.

Remote Dev no reescribe silenciosamente los ajustes de Antigravity por el mero hecho de elegir guarded. Antes de un lanzamiento real en guarded realiza una comprobación offline y acotada únicamente de los ajustes de aprobación de nivel superior necesarios para poder garantizar ese comportamiento.

Son compatibles con guarded los valores predeterminados/ausentes del proveedor y los valores documentados de solicitud/revisión. Los valores persistentes conocidos que fuerzan autonomía o son incompatibles bloquean el lanzamiento gestionado en guarded en lugar de ignorarse silenciosamente.

`permissions.allow`, `permissions.ask` y `permissions.deny` siguen siendo propiedad del usuario y esta comprobación no los reescribe.

## Diagnóstico

`remote-dev-doctor` sigue siendo de sólo lectura. En el rol Antigravity muestra el modo efectivo de aprobación de Remote Dev y un estado sanitizado de compatibilidad con guarded.

El helper offline específico es:

```bash
remote-dev-antigravity-policy status
```

Sólo lee la ruta canónica privada de ajustes de Antigravity y no muestra datos OAuth/sesión, contenido de proyectos ni el contenido de las reglas finas de permisos.

Un resultado correcto se parece a:

```text
Antigravity guarded compatibility: OK (...)
```

Un valor persistente conocido que entra en conflicto se muestra como `CONFLICT`. Un JSON malformado, un estado inseguro o una semántica relevante desconocida se muestra como `BLOCKED`; Remote Dev no intenta adivinar ni repararlo automáticamente.

## Reparación explícita de guarded

Un conflicto conocido y reparable puede restablecerse explícitamente con:

```bash
remote-dev-antigravity-policy repair-guarded --yes
```

Esta operación nunca se ejecuta automáticamente desde Start, Continue, status ni Doctor.

La reparación es deliberadamente estrecha:

- sólo acepta el `settings.json` canónico, regular, privado y propiedad de root;
- rechaza symlinks, permisos inseguros, JSON malformado y semánticas de aprobación desconocidas;
- elimina únicamente los overrides de nivel superior `toolPermission` / `artifactReviewPolicy` que estén en conflicto y hayan sido revisados;
- conserva los ajustes no relacionados/desconocidos y el objeto completo `permissions`;
- escribe de forma atómica en el mismo directorio privado con modo `0600`.

Eliminar esos overrides conflictivos devuelve esas opciones a los valores predeterminados del proveedor en vez de convertir a Remote Dev en propietario permanente del fichero de ajustes de Antigravity.

## Comportamiento del menú

El menú de Antigravity muestra la política de aprobación configurada/efectiva y ofrece:

```text
Approval mode for next launch...
```

La selección para un solo lanzamiento se consume en la siguiente acción Start o Continue y después vuelve al modo configurado en el despliegue, igual que el contrato del menú de Codex.

Start y Continue usan el mismo resolver; `Continue latest Antigravity conversation` sigue utilizando la ruta `--continue` soportada por el proveedor.

## Diferencia respecto al sandbox

El modo de aprobación y el sandbox de terminal del proveedor son controles independientes.

El baseline endurecido probado en TrueNAS no puede utilizar el sandbox de terminal anidado de Antigravity sin debilitar el perfil soportado del contenedor exterior. #215 documenta ese resultado. Por eso #159 no añade `--sandbox`, no persiste bypass del sandbox y no relaja el contenedor para hacerlo funcionar.

Consulta también:

- `docs/antigravity-sandbox-baseline.es.md`;
- `docs/antigravity-runtime-admission.es.md`;
- `docs/security.es.md`.
