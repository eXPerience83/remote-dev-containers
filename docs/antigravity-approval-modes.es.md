# Modos de aprobación de Antigravity

## Alcance

Remote Dev expone para Antigravity la misma elección de alto nivel que para Codex:

```text
autonomous | guarded
```

Esto cambia únicamente el comportamiento de confirmación dentro de la autoridad que ya tiene el contenedor del rol Antigravity. **No** crea un sandbox de sistema de archivos, no amplía mounts/capabilities y no habilita el sandbox de terminal del proveedor.

La frontera de aislamiento soportada sigue siendo el contenedor exterior endurecido más la frontera del proyecto/Git seleccionado.

## Valor predeterminado y configuración de despliegue

El valor predeterminado es `autonomous`, igual que en la UX de Remote Dev para Codex.

```dotenv
REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE=autonomous
# o: guarded
```

El orden de resolución es:

1. `--approval-mode autonomous|guarded` para un solo lanzamiento;
2. `REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE`;
3. valor interno predeterminado `autonomous`.

`run-antigravity --print-policy` informa del modo resuelto y de un estado sanitizado de compatibilidad con guarded sin ejecutar el CLI del proveedor, contactar con la red ni realizar la verificación completa de integridad del runtime.

## Autonomous

En un lanzamiento gestionado autónomo, Remote Dev añade el bypass de aprobación por lanzamiento validado con Antigravity CLI 1.1.28:

```text
--dangerously-skip-permissions
```

La validación real en TrueNAS de #159 demostró que elimina las paradas normales por aprobación de herramientas y revisión de artefactos durante ese lanzamiento, funciona igual en Start y `--continue` y no deja estado de autonomía persistente al salir. Un lanzamiento posterior sin el bypass vuelve al comportamiento normal de permisos del proveedor.

El wrapper es propietario de este argumento. Pasar `--dangerously-skip-permissions` directamente a través de `run-antigravity` se rechaza para impedir que un llamador contradiga silenciosamente el resolver de Remote Dev.

Remote Dev no habilita además `--sandbox`, no persiste sus propios valores de aprobación y no reescribe `settings.json`.

Las reglas finas de permisos del proveedor siguen siendo propiedad del usuario. En el comportamiento validado de 1.1.28, una regla explícita `permissions.deny` siguió bloqueando el comando correspondiente incluso durante un lanzamiento autonomous.

## Guarded

Guarded significa que Remote Dev **no** añade el bypass global de aprobación. La configuración propia de permisos y revisión de Antigravity continúa activa.

El fichero persistente relevante del CLI es:

```text
~/.gemini/antigravity-cli/settings.json
```

Antes de un lanzamiento real en guarded, Remote Dev lee ese fichero de forma offline y comprueba únicamente el pequeño conjunto de valores de nivel superior que pueden eliminar el comportamiento protegido esperado:

- `toolPermission` puede estar ausente/predeterminado, ser `request-review` o el más restrictivo `strict`;
- `artifactReviewPolicy` puede estar ausente/predeterminado o ser `asks-for-review`;
- `agentMode` puede estar ausente/predeterminado, ser `default` o `plan`.

`strict` es compatible y se conserva: es más restrictivo que `request-review` y pide aprobación para todas las herramientas que no sean de lectura.

Estados globalmente permisivos conocidos como `toolPermission=always-proceed`, `toolPermission=proceed-in-sandbox`, `artifactReviewPolicy=agent-decides`, `artifactReviewPolicy=always-proceed` o `agentMode=accept-edits` son incompatibles con la promesa guarded gestionada y bloquean el lanzamiento en lugar de ignorarse silenciosamente.

Los valores desconocidos o malformados en esos campos revisados también bloquean porque Remote Dev no puede garantizar su significado.

### Reglas finas avanzadas

`permissions.allow`, `permissions.ask` y `permissions.deny` siguen siendo completamente gestionadas por el usuario. Su presencia **no** se considera un conflicto con guarded y Remote Dev no inspecciona ni reescribe su contenido.

Esto permite que un usuario avanzado autorice expresamente operaciones concretas y mantenga confirmación para el resto. Guarded significa que el motor de permisos del proveedor está activo y que Remote Dev no lo ha deshabilitado globalmente; no significa que Remote Dev elimine las excepciones que haya configurado el usuario.

Es el mismo principio que en el modo guarded de Codex, donde una regla explícita del usuario también puede evitar prompts concretos.

## Diagnóstico

`remote-dev-doctor` sigue siendo de sólo lectura. En el rol Antigravity muestra el modo efectivo de Remote Dev y un estado sanitizado de compatibilidad con guarded.

El helper offline específico es:

```bash
remote-dev-antigravity-policy status
```

Lee únicamente el `settings.json` canónico del CLI de Antigravity e informa de los valores de nivel superior revisados y de si existen reglas finas. No muestra datos OAuth/sesión, contenido de proyectos ni el contenido de `permissions.allow/ask/deny`.

Un resultado correcto se parece a:

```text
Antigravity guarded compatibility: OK (...)
Antigravity guarded policy source: settings.json (read-only)
Antigravity fine-grained permissions: user-managed and preserved
```

Un estado relevante incompatible, malformado, inseguro o desconocido se muestra como `BLOCKED`. Remote Dev no repara ni reescribe el fichero automáticamente ni desde Doctor.

Para cambiar esa política se utilizan las interfaces propias de Antigravity `/settings` o `/permissions`, o se edita deliberadamente el fichero del proveedor.

## Comportamiento del menú

El menú de Antigravity muestra el modo de aprobación de Remote Dev configurado/efectivo y ofrece:

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
- `docs/security.md`.
