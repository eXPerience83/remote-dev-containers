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

La promoción mutable de `dev` queda serializada para que dos publicaciones de candidatos no compitan entre sí. El digest inmutable sigue siendo la evidencia autoritativa de una validación concreta en TrueNAS.

Para un TrueNAS utilizado principalmente para validar trabajo antes de fusionarlo, puede dejarse configurado una sola vez:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:dev-amd64
```

Después de publicar explícitamente un candidato, basta con recrear/actualizar el stack de la forma habitual. No es necesario editar el YAML para cada candidato. No uses `dev` donde no sea aceptable ejecutar código todavía no fusionado.

## Edge

`edge` es el canal público experimental integrado de la rama `main` actual.

El workflow **Publish edge AMD64** se ejecuta automáticamente después de que cambios relevantes de imagen, runtime o versiones entren en `main`. También puede lanzarse manualmente desde `main`. Cada ejecución compila y escanea un único digest final de Remote Dev y promociona únicamente ese digest exacto a:

```text
ghcr.io/experience83/remote-dev:edge
ghcr.io/experience83/remote-dev:edge-amd64
ghcr.io/experience83/remote-dev:sha-<sha-completo-de-main>
```

El workflow rechaza publicar `edge` desde cualquier rama distinta de `main`.

El Compose genérico y el de TrueNAS siguen usando por defecto:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:edge-amd64
```

Ese sigue siendo el canal recomendado para despliegues experimentales normales que deban recibir cambios ya integrados sin consumir candidatos de PR sin fusionar.

El stack utiliza la misma referencia de imagen para los roles habilitados. El launcher continúa siendo solo navegación y no recibe workspaces, estado ni credenciales de agentes; Codex y los agentes opcionales conservan sus montajes privados y sus límites de autenticación por rol.

Las imágenes públicas del registro pueden descargarse sin autenticación. Las etiquetas de contenedor son mutables en GHCR, por lo que debe registrarse y utilizarse el digest `sha256:...` cuando se necesite reproducción exacta.

Las releases estables de dependencias upstream se comprueban diariamente. El actualizador sigue las releases finales de Codex, GitHub CLI, ttyd, mise y uv, además del mantenimiento de las líneas seleccionadas de Python 3.14, Node 24 LTS y npm 12. Ubuntu LTS sigue gestionándose mediante Renovate.

La imagen por defecto no instala Bubblewrap del sistema. En el perfil soportado de TrueNAS, el lanzador de Codex fija `--sandbox danger-full-access`; el límite de seguridad es el contenedor exterior de Codex y sus montajes acotados. Los modos autonomous y guarded no cambian ese límite.

> [!WARNING]
> Que `edge` sea público no lo convierte en estable ni listo para producción. Puede haber cambios incompatibles y los endpoints web de Remote Dev no deben exponerse directamente a Internet.

## Stable y latest

La publicación estable se activa únicamente con un tag semántico exacto:

```text
vMAJOR.MINOR.PATCH
```

El commit etiquetado debe pertenecer al historial de `main`. El workflow estable rechaza expresamente pre-releases.

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

No dependas exclusivamente de etiquetas mutables. Registra el digest probado, la revisión de origen y, cuando corresponda, la etiqueta del candidato o de la versión.

Configura:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev@sha256:<digest>
```

y recrea todos los servicios del stack. Los despliegues `v0.1.x` existentes pueden continuar utilizando el alias de variable `CODEX_IMAGE` cuando `REMOTE_DEV_IMAGE` no esté definido, pero su valor debe apuntar al paquete canónico `ghcr.io/experience83/remote-dev`.

La estructura canónica de datos es independiente de la etiqueta de imagen. Un rollback no debe ampliar montajes ni copiar estado automáticamente. Conserva un backup o snapshot antes de mover manualmente datos experimentales a nuevas rutas.
