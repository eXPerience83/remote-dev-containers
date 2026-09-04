# Canales de publicación de imágenes

Versión inglesa: [`releases.md`](releases.md)

Remote Dev utiliza un único paquete runtime canónico:

```text
ghcr.io/experience83/remote-dev
```

El orden permanente de madurez es:

```text
dev -> edge -> stable = latest
```

Estos conceptos permanecen separados de la identidad legible del build y de la procedencia inmutable. Remote Dev **todavía no ha publicado una versión estable**; los despliegues públicos integrados actuales utilizan `edge`/`edge-amd64`.

## Capas de identidad

De la identidad más fuerte para reproducir a la etiqueta más orientada a personas:

1. **Digest OCI** — `@sha256:<digest>` identifica exactamente el objeto inmutable del registro y es la referencia más fuerte para rollback/reproducción.
2. **Revisión completa del código fuente** — el SHA completo del commit Git identifica el árbol de código. Las revisiones publicadas de `main` también reciben tags `sha-<full-sha>`.
3. **Identidad de build/release** — edge usa `edge-YYYY.MM.DD-<7-char-sha>`; stable usa `vMAJOR.MINOR.PATCH` exacto; los candidatos de PR publicados explícitamente conservan una identidad específica del candidato.
4. **Canal** — `dev`, `edge` o `stable` es el puntero mutable de madurez. `latest` es únicamente un alias de `stable`.

La fecha de una identidad edge corresponde a la fecha UTC de publicación. Nunca se trata como evidencia más fuerte que el SHA completo o el digest OCI.

Los diagnósticos muestran por separado identidad de build y canal, por ejemplo:

```text
Image version: edge-2026.09.04-22a3bda
Channel: edge
Source revision: 22a3bda...<SHA completo>
```

## Contrato canónico de tags

| Tag/referencia | Fuente | Movimiento | Uso previsto |
| --- | --- | --- | --- |
| `dev` / `dev-amd64` | Un HEAD de PR revisado y autorizado explícitamente por el propietario | Mutable solo tras superar el gate de publicación de candidato | Pruebas TrueNAS/desarrollo antes del merge |
| `edge` / `edge-amd64` | `main` integrado | Mutable después de una publicación edge correcta | Despliegue experimental normal |
| `stable` / `stable-amd64` | Última release SemVer estable explícita | Mutable solo al publicar una estable posterior | Despliegue estable cuando exista |
| `latest` | Exactamente el mismo digest que `stable` | Se mueve solo con `stable` | Alias convencional de estable |
| `vMAJOR.MINOR.PATCH` | Tag exacto de release estable | Direccionado por versión | Release estable con nombre |
| `candidate-pr-<PR>-<short-sha>` | Un candidato de PR publicado explícitamente | Específico del candidato | Revisión/auditoría |
| `sha-<full-sha>` | Una revisión publicada de `main` | Direccionado por fuente | Auditoría de una revisión integrada |
| `@sha256:<digest>` | Manifest OCI exacto | Inmutable | Validación/reproducción/rollback exactos |

`latest` es siempre un alias de `stable`; nunca debe apuntar a `dev` ni a `edge`.

Mientras no exista publicación runtime multi-arquitectura, los tags genéricos de canal y sus variantes `*-amd64` resuelven al build AMD64. Se mantienen recomendados `dev-amd64`, `edge-amd64` y el futuro `stable-amd64` para que una ampliación de arquitecturas sea explícita.

## Dev — candidato revisado antes del merge

Un push normal de PR o una ejecución de CI no puede mover `dev`.

La ruta soportada de publicación de candidato requiere un comando del propietario en un PR abierto contra `main`:

```text
/publish-candidate <full-40-character-head-sha>
```

El workflow verifica que el SHA siga siendo el HEAD exacto del PR y pertenezca a este repositorio, construye y hace smoke-test de esa fuente exacta, realiza comprobaciones independientes de identidad del artefacto y el gate de vulnerabilidades, y únicamente entonces promociona el digest verificado a:

```text
ghcr.io/experience83/remote-dev:dev
ghcr.io/experience83/remote-dev:dev-amd64
```

Se conserva además el tag específico de auditoría del candidato. La promoción mutable de `dev` está serializada para impedir carreras entre dos candidatos.

Para pruebas temporales de candidato en TrueNAS:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:dev-amd64
```

Tras fusionar el cambio revisado, vuelve a `edge-amd64` salvo que quieras mantener intencionadamente un digest exacto.

## Edge — main integrado

`edge` es el canal público experimental integrado de `main`.

El workflow **Publish edge AMD64** se ejecuta después de que cambios relevantes de imagen/runtime/versiones entren en `main` y también puede iniciarse explícitamente desde un `main` confiable. Rechaza fuentes de ramas distintas de `main`.

Una publicación edge correcta embebe:

```text
edge-YYYY.MM.DD-<7-char-sha>
Channel: edge
```

y promociona el digest exacto ya escaneado a:

```text
ghcr.io/experience83/remote-dev:edge
ghcr.io/experience83/remote-dev:edge-amd64
ghcr.io/experience83/remote-dev:sha-<full-main-sha>
```

La cadena con fecha es una identidad embebida del build, no un tag SemVer ni un sustituto del SHA completo o del digest.

El selector de despliegue normal actual es:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:edge-amd64
```

Todos los roles habilitados del stack utilizan la misma referencia de imagen prevista. El launcher sigue siendo solo navegación; el estado mutable de runtime de Codex/Antigravity continúa siendo privado por rol y no se considera parte implícita del digest de la imagen edge.

## Procedencia automatizada del changelog

`CHANGELOG.md` es un changelog de releases estables, no una sección de primer nivel por cada build de CI. `## [Unreleased]` acumula cambios revisados hasta preparar una release SemVer estable.

Dos propietarios de automatización acotados pueden modificar subsecciones machine-owned dentro de `Unreleased`:

### Actualizaciones upstream agrupadas

`.github/workflows/check-upstream.yml` es propietario de pines de runtime/herramientas agrupados como Codex CLI, GitHub CLI, ttyd, mise, uv y las líneas seleccionadas de Python/Node/npm.

Cuando cambian realmente versiones de componentes, el mismo PR de revisión actualiza el área acotada `### Automated upstream refreshes` utilizando los valores antiguos/nuevos del repositorio. El ruido exclusivo de checksums no inventa una falsa actualización de aplicación. Repetir la ejecución contra la misma base es determinista y la automatización nunca hace auto-merge.

### Actualizaciones de imagen de Renovate

Renovate tiene un límite de propiedad separado.

- Los cambios de tag/digest de Ubuntu LTS alteran materialmente la imagen runtime producida y por tanto actualizan el área acotada `### Renovate image refreshes`.
- El ancla oculta de estado Ubuntu debe coincidir con la versión/digest comprometidos en `versions.env` e `images/base/Dockerfile`.
- El reemplazo de Renovate deriva la identidad visible anterior -> nueva a partir del tag Ubuntu y digest inmutable actuales/propuestos, y avanza el ancla en el mismo PR agrupado `Ubuntu LTS base`.
- Recrear el mismo PR de Renovate desde la misma base reproduce la misma salida; una actualización Ubuntu posterior ya fusionada añade un nuevo delta machine-owned sin sobrescribir entradas previas ni texto humano.
- Los cambios exclusivos de SHA de GitHub Actions y el frontend fijado del Dockerfile siguen siendo mantenimiento de CI/build y **no** se presentan como actualizaciones de aplicaciones incluidas en runtime.
- Renovate continúa con `automerge: false`.

El validador del repositorio obliga offline ambos límites de automatización. El texto humano del changelog fuera de sus marcadores explícitos no es objetivo de automatización.

## Stable y latest

La publicación estable solo se activa mediante un tag SemVer exacto sin prerelease:

```text
vMAJOR.MINOR.PATCH
```

El commit etiquetado debe pertenecer a `main` y superar los gates de publicación estable. Las imágenes estables embeben la identidad SemVer y un canal `stable` separado.

Después de construir y escanear correctamente el candidato estable exacto, el mismo digest se promociona a:

```text
ghcr.io/experience83/remote-dev:vMAJOR.MINOR.PATCH
ghcr.io/experience83/remote-dev:stable
ghcr.io/experience83/remote-dev:stable-amd64
ghcr.io/experience83/remote-dev:latest
```

Por tanto, `latest` es únicamente el alias convencional del digest estable más reciente. Publicar `dev` o `edge` nunca lo mueve.

Cuando existan releases estables, el selector AMD64 normal será:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:stable-amd64
```

## Elección de canal por el operador

Usa un canal de madurez en la configuración normal y cámbialo solo de forma intencionada:

```dotenv
# Candidato revisado todavía no fusionado
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:dev-amd64

# Build experimental integrado actual
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:edge-amd64

# Estable, cuando exista una release estable
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:stable-amd64
```

Para validación exacta o rollback, fija el digest inmutable:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev@sha256:<digest>
```

No dependas de un tag mutable ni de la fecha legible de edge cuando importe la reproducción exacta.

## Checklist de release estable

Antes de crear la primera o cualquier release estable posterior, verifica sobre una única revisión/digest exactos de `main` que:

1. La validación del repositorio y toda la suite AMD64 de build/smoke pasan.
2. Las imágenes base y Remote Dev final superan el gate de vulnerabilidades de publicación; un `CRITICAL` corregible bloquea la promoción.
3. Notices y generación de SBOM pasan y los informes retenidos corresponden a la imagen que se promociona.
4. Existe la raíz TrueNAS prevista creada por el administrador y bootstrap/preflight de la misma revisión pasan.
5. El layout Host Path de referencia TrueNAS cumple el contrato Generic/POSIX de estado privado o existe una decisión equivalente explícitamente documentada; ejecuta el audit ACL del host cuando corresponda.
6. Launcher y agentes habilitados utilizan la referencia/digest común previsto manteniendo montajes escribibles/privados disjuntos.
7. El launcher conserva origen/CSP/navegación correctos y no recibe estado/contraseña de agentes ni socket del motor de contenedores.
8. Los endpoints Codex y Antigravity habilitado se autentican de forma independiente con `WEB_PASSWORD` de configuración; el launcher no recibe ninguna contraseña de agente.
9. Workspace/proyectos, estado del agente, GitHub/Git/SSH y estado runtime que deba persistir sobreviven stop/start y recreación.
10. Login de dispositivo Codex, Resume de sesiones y las rutas soportadas autonomous/guarded funcionan en el despliegue objetivo.
11. Si Antigravity forma parte del soporte anunciado, su ruta explícita de runtime del proveedor, estado actual de admisión/integridad y restricciones experimentales siguen siendo válidos; #53 no tiene un bloqueo out-of-cycle pendiente para esa afirmación exacta.
12. Las integraciones externas opcionales incluidas en el soporte anunciado mantienen sus límites documentados de privacidad/credenciales.
13. `CHANGELOG.md` tiene una sección estable fechada derivada del contenido revisado de `Unreleased`.
14. La evidencia del repositorio/release no contiene credenciales, rutas de infraestructura privada ni datos sensibles de cuenta/sesión.
15. #31 no contiene ningún issue pendiente que contradiga la afirmación estable que realmente se va a realizar.

El trabajo opcional/futuro #181/#170/#124/#95/#159/#71/#112/#121/#148/#151 no se convierte automáticamente en bloqueo estable salvo que #31 o su issue correspondiente identifique una dependencia concreta para la release.

## Rollback

Registra el digest OCI probado y el SHA completo antes de cambiar de canal de madurez o desplegar una imagen nueva.

Para volver a una imagen anterior sin alterar la semántica del layout persistente:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev@sha256:<known-good-digest>
```

Después recrea todos los servicios del stack con esa referencia exacta.

El rollback no debe ampliar montajes ni copiar/migrar estado silenciosamente. Si una release nueva cambia un contrato en disco, sigue el procedimiento de migración/rollback expresamente documentado para ese contrato en vez de asumir que una imagen anterior puede reinterpretar de forma segura los datos persistentes más nuevos.
