# Canales de publicación de imágenes

Versión inglesa: [`releases.md`](releases.md)

Remote Dev utiliza un único paquete runtime canónico:

```text
ghcr.io/experience83/remote-dev
```

Los canales de publicación visibles para el usuario quedan definidos permanentemente, de menor a mayor madurez, como:

```text
dev  ->  edge  ->  stable = latest
```

Son canales deliberadamente distintos. `dev` puede contener código de un pull request todavía no fusionado, `edge` contiene únicamente código integrado en `main`, y `stable`/`latest` contienen únicamente una release estable con versión semántica exacta.

## Capas de identidad

Remote Dev mantiene separados el nivel de madurez, la identidad legible de una build y la procedencia inmutable:

1. **Digest de imagen** — `@sha256:<digest>` es la identidad OCI exacta e inmutable y la referencia más fuerte para reproducción y rollback.
2. **Revisión de origen** — el SHA Git completo identifica el árbol de código; las revisiones publicadas de `main` conservan además la etiqueta de registro `sha-<full-sha>`.
3. **Identidad de build/release** — una publicación edge usa `edge-YYYY.MM.DD-<7-char-sha>`; una release estable usa SemVer exacto `vMAJOR.MINOR.PATCH`; un candidato de PR revisado conserva la identidad embebida `candidate-pr-<PR>` y su etiqueta específica de auditoría.
4. **Canal** — `dev`, `edge` o `stable` es el puntero mutable de madurez del despliegue. `latest` es únicamente un alias de `stable`.

La fecha de una identidad edge corresponde a la fecha UTC de publicación/build. Se combina deliberadamente con el prefijo del SHA para que dos publicaciones edge válidas del mismo día sigan siendo distinguibles. La fecha nunca se considera una evidencia más fuerte que la revisión completa de origen o el digest de imagen.

Las imágenes embeben el canal independientemente de la versión legible. Por ello `remote-dev-version` no necesita deducir si una imagen es local, dev, edge o stable a partir de una etiqueta mutable ni del texto de versión.

## Contrato canónico de etiquetas

| Etiqueta | Origen | Cuándo se mueve | Uso previsto |
| --- | --- | --- | --- |
| `dev` / `dev-amd64` | Candidato de PR revisado y autorizado explícitamente por el propietario | Mutable, solo después de que `/publish-candidate <full-head-sha>` supere todos los gates | Pruebas activas de desarrollo/TrueNAS antes del merge |
| `edge` / `edge-amd64` | `main` actual | Mutable tras una publicación edge correcta | Despliegue experimental integrado normal |
| `stable` / `stable-amd64` | Última release estable `vMAJOR.MINOR.PATCH` | Mutable solo al publicar una nueva estable | Despliegue estable |
| `latest` | Mismo digest que `stable` | Se mueve únicamente junto con `stable` | Alias convencional de la última release estable |
| `vMAJOR.MINOR.PATCH` | Tag exacto de una release estable | Asociado a esa versión | Release estable nombrada y reproducible |
| `candidate-pr-<PR>-<short-sha>` | Un candidato de PR publicado explícitamente | Específico de ese candidato | Auditoría/diagnóstico, no canal de despliegue |
| `sha-<full-sha>` | Una revisión publicada de `main` | Asociado a esa revisión | Auditoría/localización por revisión de código |
| `@sha256:<digest>` | Manifiesto exacto del registro | Referencia inmutable | Validación exacta, reproducción y rollback |

`latest` es siempre un alias de `stable`. Nunca debe apuntar a `edge` ni a `dev`.

Mientras Remote Dev no publique un runtime multi-arquitectura soportado, las etiquetas genéricas y sus variantes `*-amd64` resuelven al mismo digest AMD64. En la plataforma soportada actualmente se recomiendan `dev-amd64`, `edge-amd64` y `stable-amd64`, para que una futura transición multi-arquitectura sea explícita y no cambie silenciosamente la arquitectura de un despliegue existente.

## Dev

`dev` es el canal mutable para pruebas antes del merge. Es intencionadamente más volátil que `edge` y puede contener código que todavía no ha entrado en `main`.

Un push normal a un PR o su CI no puede mover `dev`. La única ruta soportada es un comentario del propietario en un PR abierto que apunte a `main`:

```text
/publish-candidate <sha-completo-de-40-caracteres-del-head>
```

El workflow de candidatos verifica que el SHA indicado siga siendo exactamente el HEAD del PR y que la rama pertenezca a este repositorio. Después compila y ejecuta smoke tests sobre ese HEAD exacto sin permisos de escritura en paquetes, exporta las imágenes, vuelve a cargar y valida de forma independiente el artefacto, comprueba la identidad embebida, aplica el gate de vulnerabilidades críticas corregibles y solo entonces permite publicar al job con acceso al registro.

Una publicación correcta conserva la etiqueta específica del candidato y promociona el mismo digest verificado a:

```text
ghcr.io/experience83/remote-dev:dev
ghcr.io/experience83/remote-dev:dev-amd64
```

La versión embebida del candidato continúa siendo `candidate-pr-<PR>` y el canal embebido es `dev`; la revisión completa de origen permanece separada. La etiqueta específica del candidato en el registro ya incluye el SHA corto, por lo que no hace falta añadir una etiqueta dev basada en fecha.

La promoción mutable de `dev` queda serializada para que dos publicaciones de candidatos no compitan entre sí. El digest inmutable sigue siendo la evidencia autoritativa de una validación concreta en TrueNAS.

Para un TrueNAS utilizado principalmente para validar trabajo antes de fusionarlo, puede dejarse configurado una sola vez:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:dev-amd64
```

Después de publicar explícitamente un candidato, basta con recrear/actualizar el stack de la forma habitual. No es necesario editar el YAML para cada candidato. No uses `dev` donde no sea aceptable ejecutar código todavía no fusionado.

## Edge

`edge` es el canal público experimental integrado de la rama `main` actual.

El workflow **Publish edge AMD64** se ejecuta automáticamente después de que cambios relevantes de imagen, runtime o versiones entren en `main`. También puede lanzarse manualmente desde `main`. Cada ejecución deriva una identidad legible a partir de la fecha UTC de publicación y de la revisión exacta de origen:

```text
edge-YYYY.MM.DD-<7-char-sha>
```

Por ejemplo, una publicación del 27 de agosto de 2026 desde una revisión que empiece por `d6cf2a3` queda embebida como:

```text
edge-2026.08.27-d6cf2a3
```

El workflow continúa compilando y escaneando un único digest final de Remote Dev y promociona únicamente ese digest exacto a:

```text
ghcr.io/experience83/remote-dev:edge
ghcr.io/experience83/remote-dev:edge-amd64
ghcr.io/experience83/remote-dev:sha-<sha-completo-de-main>
```

La identidad fechada se embebe en la metadata OCI/runtime; no es un tag Git SemVer ni se publica como sustituto de los contratos más fuertes `sha-<full-sha>` o digest. El workflow rechaza publicar `edge` desde cualquier rama distinta de `main`.

El Compose genérico y el de TrueNAS siguen usando por defecto:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:edge-amd64
```

Ese sigue siendo el canal recomendado para despliegues experimentales normales que deban recibir cambios ya integrados sin consumir candidatos de PR sin fusionar.

Un informe normal de identidad de una imagen edge comienza así:

```text
Image version: edge-2026.08.27-d6cf2a3
Channel: edge
Source revision: d6cf2a3...<SHA completo>
Codex CLI: codex-cli <versión-incluida>
```

El stack utiliza la misma referencia de imagen para los roles habilitados. El launcher continúa siendo solo navegación y no recibe workspaces, estado ni credenciales de agentes; Codex y los agentes opcionales conservan sus montajes privados y sus límites de autenticación por rol.

Las imágenes públicas del registro pueden descargarse sin autenticación. Las etiquetas de contenedor son mutables en GHCR, por lo que debe registrarse y utilizarse el digest `sha256:...` cuando se necesite reproducción exacta.

Las releases estables de dependencias upstream se comprueban diariamente. El actualizador agrupado sigue las releases finales de Codex, GitHub CLI, ttyd, mise y uv, además del mantenimiento de las líneas seleccionadas de Python 3.14, Node 24 LTS y npm 12. Ubuntu LTS sigue gestionándose por separado mediante Renovate.

### Procedencia automática en el changelog

Cuando el actualizador agrupado cambia una o más versiones de componentes seguidos, el mismo PR de revisión actualiza también la sección propiedad de la automatización `### Automated upstream refreshes` bajo `## [Unreleased]` en `CHANGELOG.md`.

La entrada se obtiene de los valores reales de `versions.env` antes y después de ejecutar el actualizador. Solo enumera versiones que hayan cambiado, por ejemplo:

```text
- 2026-08-27 — Codex CLI 0.149.1 → 0.150.1; GitHub CLI 2.96.0 → 2.98.0; uv 0.12.0 → 0.12.6.
```

Un cambio únicamente de checksum no inventa una falsa actualización de versión visible para el usuario. El updater solo controla la sección marcada explícitamente del changelog, falla de forma cerrada si el marcador/sección esperado está mal formado, conserva el contenido escrito manualmente fuera de ese límite y trata una entrada idéntica repetida de forma idempotente. La rama de automatización se reconstruye desde el `main` actual, por lo que una ejecución programada posterior regenera la procedencia respecto a la base vigente en vez de acumular historial obsoleto de la rama.

Esta primera implementación cubre únicamente `.github/workflows/check-upstream.yml`. Renovate tiene un límite de responsabilidad independiente: las actualizaciones de Ubuntu/imagen base pueden afectar al runtime, mientras que cambios de SHA inmutable de GitHub Actions pueden afectar solo a CI. El seguimiento #189 es responsable de la procedencia específica de Renovate para evitar presentar esas clases silenciosa o incorrectamente como actualizaciones del updater agrupado.

La imagen por defecto no instala Bubblewrap del sistema. En el perfil soportado de TrueNAS, el lanzador de Codex fija `--sandbox danger-full-access`; el límite de seguridad es el contenedor exterior de Codex y sus montajes acotados. Los modos autonomous y guarded no cambian ese límite.

> [!WARNING]
> Que `edge` sea público no lo convierte en estable ni listo para producción. Puede haber cambios incompatibles y los endpoints web de Remote Dev no deben exponerse directamente a Internet.

## Stable y latest

La publicación estable se activa únicamente con un tag semántico exacto:

```text
vMAJOR.MINOR.PATCH
```

El commit etiquetado debe pertenecer al historial de `main`. El workflow estable rechaza expresamente pre-releases. Las imágenes estables embeben la versión semántica como versión de imagen y `stable` como canal separado; las identidades de calendario de edge nunca sustituyen SemVer estable.

Después de compilar y escanear correctamente el candidato estable exacto, el mismo digest se promociona a:

```text
ghcr.io/experience83/remote-dev:vMAJOR.MINOR.PATCH
ghcr.io/experience83/remote-dev:stable
ghcr.io/experience83/remote-dev:stable-amd64
ghcr.io/experience83/remote-dev:latest
```

`stable` es el canal semántico de despliegue. `latest` existe únicamente como alias convencional del mismo digest estable. Publicar `dev` o `edge` nunca debe mover `latest`.

Cuando existan releases estables, el despliegue AMD64 recomendado será:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:stable-amd64
```

Los workflows de edge y estable publican candidatos por digest, escanean esos digests exactos y solo después promocionan las etiquetas públicas. Una vulnerabilidad `CRITICAL` con corrección conocida bloquea la promoción; las críticas sin corrección conocida permanecen visibles en los informes conservados.

`CHANGELOG.md` continúa siendo un changelog de releases estables, no un log de builds de CI. `## [Unreleased]` acumula cambios revisados, incluida la procedencia de refreshes upstream automáticos. Al preparar una release estable `vMAJOR.MINOR.PATCH`, ese contenido se mueve a una sección estable con fecha y `Unreleased` se reinicia. Las fechas de publicaciones edge no crean secciones top-level del changelog.

## Elección del canal en el despliegue

Utiliza un único canal en la configuración y cámbialo solo cuando quieras cambiar conscientemente el nivel de madurez:

```dotenv
# Revisión activa / pruebas antes del merge
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:dev-amd64

# Despliegue experimental normal (valor por defecto del repositorio)
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:edge-amd64

# Despliegue estable, cuando existan releases estables
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:stable-amd64
```

Para una validación concreta o un rollback exacto, sustituye temporalmente el canal por el digest inmutable:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev@sha256:<digest>
```

## Checklist de promoción estable

Antes de crear un tag de versión estable:

1. La build AMD64, los smoke tests del runtime y el gate de vulnerabilidades críticas corregibles pasan sobre `main`.
2. Las etiquetas runtime de `remote-dev` que se van a promocionar resuelven al `REMOTE_DEV_DIGEST` probado y la metadata de `remote-dev-base` coincide por separado con `BASE_DIGEST`.
3. El stack se ha desplegado en TrueNAS usando un digest publicado exacto.
4. Docker confirma que launcher y los servicios de agente habilitados utilizan el digest común previsto.
5. El portal de TrueNAS abre el launcher en el puerto 7680.
6. El launcher abre en el endpoint privado de confianza y mantiene el comportamiento de origin/CSP.
7. Seleccionar Codex navega al endpoint autenticado independiente sin exponer credenciales.
8. El launcher base no tiene montajes de agentes ni socket Docker/Podman; la autenticación opcional del launcher usa su propia contraseña de configuración y no añade mounts bind ni persistentes.
9. Ningún servicio utiliza host networking, modo privilegiado ni capacidades añadidas fuera del contrato revisado.
10. La raíz administrativa de datos prevista ya existe; el inicializador canónico y el preflight de la misma revisión que la imagen/YAML seleccionados pasan antes del despliegue, una segunda ejecución del inicializador es idempotente y no se genera ninguna raíz ni ruta `secrets/` inesperada para contraseñas web.
11. Workspace, estado de agente, GitHub CLI, configuración Git y SSH persisten tras stop/start y recreación según lo documentado.
12. El login por device code de Codex persiste tras recreación.
13. Se han verificado login, clone, push y creación de PR con GitHub CLI.
14. Se han probado los modos autonomous y guarded de Codex en el host TrueNAS objetivo.
15. Las credenciales web de Codex se configuran por configuración y se validan contra el endpoint de Codex bajo #69; cuando Antigravity esté habilitado, sus credenciales web se configuran de forma independiente y se validan contra su propio endpoint.
16. El changelog contiene una sección de release fechada.
17. Las licencias y avisos de terceros están completos.
18. El repositorio no contiene credenciales, rutas personales ni detalles de infraestructura privada.

El hardening entre servicios y la validación de agentes opcionales continúan siendo gates separados antes de considerar completa la arquitectura.

## Rollback

No dependas exclusivamente de etiquetas mutables ni de la fecha legible de edge. Registra el digest probado, la revisión completa de origen y, cuando corresponda, la etiqueta del candidato o de la versión estable.

Configura:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev@sha256:<digest>
```

y recrea todos los servicios del stack. Los despliegues `v0.1.x` existentes pueden continuar utilizando el alias de variable `CODEX_IMAGE` cuando `REMOTE_DEV_IMAGE` no esté definido, pero su valor debe apuntar al paquete canónico `ghcr.io/experience83/remote-dev`.

La estructura canónica de datos es independiente de la etiqueta de imagen. Un rollback no debe ampliar montajes ni copiar estado automáticamente. Conserva un backup o snapshot antes de mover manualmente datos experimentales a nuevas rutas.
