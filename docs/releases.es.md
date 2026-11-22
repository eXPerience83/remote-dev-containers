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

Estos conceptos permanecen separados de la identidad legible del build y de la procedencia inmutable. La primera estable `v0.2.0` se publicó el 5/11/2026. El código `0.2.1` preparado **no** publica por sí mismo otra imagen: hasta que el publicador por tag empiece a modificar alias, `stable` y `latest` deberían conservar el último digest estable; un fallo durante la promoción todavía puede dejar una actualización parcial del registro. Utiliza `edge`/`edge-amd64` solo para pruebas experimentales.

La versión local de código de este corte de mantenimiento es `0.2.1`. El número de código no acredita la publicación: edge conserva su identidad fechada y solo una publicación autorizada por el tag estable `v0.2.1` debería avanzar `stable` y `latest`; un job fallido también podría haber escrito algunos tags, por lo que deben releerse los seis alias antes de aceptar o revertir. Los pines, los locks y el changelog pertenecen a sus procesos de revisión; las actualizaciones rutinarias no crean una nueva release estable automáticamente.

## Capas de identidad

De la identidad más fuerte para reproducir a la etiqueta más orientada a personas:

1. **Digest OCI** — `@sha256:<digest>` identifica exactamente el objeto inmutable del registro y es la referencia más fuerte para rollback/reproducción.
2. **Revisión completa del código fuente** — el SHA completo del commit Git identifica el árbol de código. Las revisiones publicadas de `main` también reciben tags `sha-<full-sha>`.
3. **Identidad de build/release** — edge usa `edge-YYYY.MM.DD-<7-char-sha>`; stable usa `vMAJOR.MINOR.PATCH` exacto; los candidatos de PR publicados explícitamente conservan una identidad específica del candidato.
4. **Canal** — `dev`, `edge` o `stable` es el puntero mutable de madurez. `latest` es siempre un alias de `stable`.

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

Todos los roles habilitados del stack utilizan la misma referencia de imagen prevista. El launcher sigue siendo navegación sin contraseña; el estado mutable de runtime de Codex/Antigravity continúa siendo privado por rol y no se considera parte implícita del digest de la imagen edge.

## Procedencia automatizada del changelog

`CHANGELOG.md` es un changelog de releases estables, no una sección de primer nivel por cada build de CI. `## [Unreleased]` acumula cambios revisados hasta preparar una release SemVer estable.

Dos propietarios de automatización acotados pueden modificar subsecciones machine-owned dentro de `Unreleased`:

### Actualizaciones upstream agrupadas

`.github/workflows/check-upstream.yml` es propietario de pines de runtime/herramientas agrupados como Codex CLI, GitHub CLI, ttyd, mise, uv, las seis CLI de validación PR2 y las líneas seleccionadas de Python/Node/npm.

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

## Beta aceptada → primera estable v0.2.0

**Alcance previsto de v0.2.0:** núcleo AMD64 validado para un solo usuario en red privada, con Codex integrado y estado persistente. Será la primera imagen del canal estable dentro de 0.x, sin prometer compatibilidad de API propia de 1.0. Antigravity continúa siendo opcional y experimental, y la versión 0.2.0 no implica exposición pública a Internet, aislamiento multiusuario, ejecución ARM64 ni retirada automática de alias compatibles.

La fase histórica `0.2.0-beta.1` fue una aceptación local, no una prerelease SemVer de GitHub ni una etiqueta beta de GHCR. Las pruebas reales de TrueNAS sobre herramientas, roles y persistencia quedaron registradas en #121, ya cerrado. El corte de código `0.2.0` no mueve por sí solo los canales; el publicador solo admite tags estables exactos `vMAJOR.MINOR.PATCH` en un commit revisado de main y exige construcción, análisis de seguridad y verificación de digest independientes.

1. Congela el `main` de prueba después de integrar los PR previstos **actualizados/rebasados a su base y verificados con CI en su SHA exacto**, siguiendo `AGENTS.md`. No confundas verde de CI en una rama antigua con la validación de la combinación.
2. Exige Build AMD64 y Publish edge AMD64 correctos **en la misma revisión**; registra el SHA completo, el digest OCI exacto publicado de `ghcr.io/experience83/remote-dev`, la identidad `edge-YYYY.MM.DD-<sha>` y los informes de notices, SBOM y Trivy de ese candidato. El tag mutable `edge` por sí solo no identifica la beta probada.
3. Guarda digest anterior y configuración del Custom App antes de cambiar nada. En TrueNAS despliega los tres roles habilitados con **el mismo** `REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev@sha256:<digest>`, sin recrear datasets, cambiar ACL, ampliar capacidades ni usar montajes generales.
4. Ejecuta las pruebas herméticas de las seis CLI con `scripts/test-validation-tools.sh` de la misma revisión, sin red ni capacidades DAC; exige `remote-dev-base-verify`, notices, 53 comandos, Python 3.14 por defecto y 3.15 opcional con resolución de proyecto correcta. No declares aprobado un paso que requiera `CAP_DAC_READ_SEARCH`.
5. Comprueba autenticación web, navegación del launcher, aislamiento de roles, Codex Start/Resume, Antigravity experimental si está habilitado, persistencia y conversaciones reales tras stop/start/recreación; nunca publiques tokens ni nombres de sesiones.
6. Documenta los resultados verificables en #121 y actualiza #31, distinguiendo pendientes reales de mejoras futuras. Corrige cualquier regresión mediante PR nuevo, actualizado a `main` y con CI propio; repite la aceptación de la nueva revisión/digest.
7. **Corte estable:** una vez aceptadas las pruebas funcionales reales de TrueNAS y revisados los demás controles, fija `BASE_VERSION` y ambos Dockerfile en `0.2.0` mediante una PR revisada (fusionada en #307), prepara el changelog fechado, exige CI del SHA exacto y fusiona en main. Solo entonces crea el tag `v0.2.0` sobre ese commit; el publicador rechaza cualquier tag distinto de `v${BASE_VERSION}` según el `versions.env` de la revisión, y el workflow estable construirá y analizará su candidato y promocionará el mismo digest verificado a `v0.2.0`, `stable`, `stable-amd64` y `latest`.

## Stable y latest

La publicación estable exige un tag exacto `vMAJOR.MINOR.PATCH` que coincida
con `versions.env` en el historial de `main`. Edge y Stable pueden compartir
un SHA de código, pero construyen candidatos distintos con su versión y canal.

El publicador verifica la identidad y los avisos de los dos manifiestos AMD64.
El arranque, la autenticación y el aislamiento se prueban sobre el manifiesto
Runtime. Ambos manifiestos tienen informes SPDX y Trivy. Los registros del ZIP,
binario y licencia de Chromium acreditan procedencia. Trivy no analiza el
Chromium de ese ZIP. Los dos SPDX finales pasan `pyspdxtools` con las ruedas
fijadas en `scripts/spdx-validator-requirements.lock.txt`. La instalación usa
`pip --require-hashes` y solo ruedas. Si cambia la ABI del runner, revisar y
validar los nuevos hashes antes de publicar. Las vulnerabilidades CRITICAL
corregibles bloquean la promoción.

Cada alias debe resolver al **índice OCI** validado de su repositorio, que
contiene el manifiesto AMD64 probado:

| Repositorio | Alias |
| --- | --- |
| `ghcr.io/experience83/remote-dev-base` | `vMAJOR.MINOR.PATCH`, `stable-amd64` |
| `ghcr.io/experience83/remote-dev` | `vMAJOR.MINOR.PATCH`, `stable`, `stable-amd64`, `latest` |

Usar `ghcr.io/experience83/remote-dev:stable-amd64` como selector estable AMD64.

Antes de escribir, la guarda lee los seis alias, impide sobrescribir tags de
versión o retroceder y solo permite una reejecución de lectura si coinciden
exactamente ambos índices candidatos y todos los alias. La promoción en GHCR
no es atómica. Un fallo puede dejar actualizado un subconjunto de los seis.

### Reconciliar una promoción parcial

1. Detener todos los escritores del registro y las reejecuciones históricas.
   Conservar los logs, `stable-promotion-preflight.json`, los metadatos de
   promoción y los digests de los índices candidatos y aceptados. Inventariar
   los seis alias de la tabla, con digest o ausencia anterior y actual.
2. Identificar las escrituras completadas. Si existía una release anterior,
   el operador puede restaurar sus alias con los índices previos registrados.
   Conciliar también ambos tags de versión. Si se publicó Base y falló Runtime,
   restaurar únicamente `stable-amd64` de Base deja un tag de versión huérfano
   y bloquea el reintento. Para autorizar la finalización se deben usar los
   índices exactos del candidato revisado y escaneado.
3. En la primera publicación, los alias antes ausentes carecen de digest
   previo. Recuperar la ausencia exige autorización del operador y verificar
   cada tag y dependencia afectados. Borrar una versión GHCR puede eliminar
   todos los alias ligados al digest. Si no hay retirada segura, documentar
   el bloqueo y conservar la versión compartida.
4. Tras la reconciliación autorizada, releer los seis alias, incluidas las
   ausencias esperadas. Verificar las condiciones de la guarda antes de
   decidir otro intento.

Consultar la [guía de borrado y restauración de versiones de GitHub](https://docs.github.com/en/packages/learn-github-packages/deleting-and-restoring-a-package).
Antes de publicar, verificar la protección de creación, modificación y
borrado de tags `v*` y el control de reejecuciones históricas.
Los workflows de tags anteriores a la guarda carecen de ese control.

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

Antes de crear el primer tag Git de versión estable (o uno posterior), verifica sobre una revisión exacta de `main` ya revisada y el digest Edge aceptado que:

1. La validación del repositorio y toda la suite AMD64 de build/smoke pasan.
2. Existe la raíz TrueNAS prevista creada por el administrador y bootstrap/preflight de la misma revisión pasan.
3. El layout Host Path de referencia TrueNAS cumple el contrato Generic/POSIX de estado privado o existe una decisión equivalente explícitamente documentada; ejecuta el audit ACL del host cuando corresponda.
4. Launcher y agentes habilitados utilizan la referencia/digest común previsto manteniendo montajes escribibles/privados disjuntos.
5. Se verifica origen/CSP/navegación del launcher sin contraseña; no recibe estado/contraseña de agentes ni socket del motor de contenedores y está vinculado únicamente a la red privada/de confianza prevista. Una futura entrada segura central no forma parte de la afirmación estable actual salvo que #181 cambie explícitamente ese límite antes.
6. Los endpoints Codex y Antigravity habilitado se autentican mediante sus entradas de configuración separadas; el soporte actual no exige que esos valores de contraseña sean distintos ni que cumplan una longitud mínima/composición impuesta por el proyecto.
7. Workspace/proyectos, estado del agente, GitHub/Git/SSH y estado runtime que deba persistir sobreviven stop/start y recreación.
8. Login de dispositivo Codex, Resume de sesiones y las rutas soportadas autonomous/guarded funcionan en el despliegue objetivo.
9. Si Antigravity forma parte del soporte anunciado, su ruta explícita de runtime del proveedor, estado actual de admisión/integridad y restricciones experimentales siguen siendo válidos; #53 no tiene un bloqueo out-of-cycle pendiente para esa afirmación exacta.
10. Las integraciones externas opcionales incluidas en el soporte anunciado mantienen sus límites documentados de privacidad/credenciales.
11. `CHANGELOG.md` tiene una sección estable fechada derivada del contenido revisado de `Unreleased`.
12. La evidencia del repositorio/release no contiene credenciales, rutas de infraestructura privada ni datos sensibles de cuenta/sesión.
13. #31 no contiene ningún issue pendiente que contradiga la afirmación estable que realmente se va a realizar.

**Después de crear el tag Git revisado: controles del candidato stable, promoción y aceptación posterior** (en ese orden):

1. Construir los candidatos independientes de base y runtime stable; vincular los digests del índice OCI y los manifiestos AMD64 exactos al SHA, versión y canal del código etiquetado; ejecutar smoke de arranque, autenticación y aislamiento sobre ese candidato.
2. Validar avisos y ambos SPDX, incluida la evidencia suplementaria del paquete/archivos Chromium, y los dos informes Trivy vinculados al candidato con cobertura de paquetes Ubuntu y lenguajes. Rechazar hallazgos `CRITICAL` corregibles.
3. Ejecutar la guarda de inmutabilidad de tags SemVer y avance monótono de stable; después, promocionar y releer todos los alias de base/runtime. Comprobar que el índice OCI promocionado contiene el manifiesto AMD64 exacto ya probado. Las escrituras registrales no son atómicas: un job fallido puede haber movido algunos alias y exigir reconciliación humana por digest inmutable.
4. Comprobar la imagen estable resultante en TrueNAS conforme a la aceptación del operador antes de dar la release por completada.

El trabajo opcional/futuro #181/#170/#124/#95/#159/#71/#112/#121/#148/#151 no se convierte automáticamente en bloqueo estable salvo que #31 o su issue correspondiente identifique una dependencia concreta para la release.

## Rollback

Registra el digest OCI probado y el SHA completo antes de cambiar de canal de madurez o desplegar una imagen nueva.

Para volver a una imagen anterior sin alterar la semántica del layout persistente:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev@sha256:<known-good-digest>
```

Después recrea todos los servicios del stack con esa referencia exacta.

El rollback no debe ampliar montajes ni copiar/migrar estado silenciosamente. Si una release nueva cambia un contrato en disco, sigue el procedimiento de migración/rollback expresamente documentado para ese contrato en vez de asumir que una imagen anterior puede reinterpretar de forma segura los datos persistentes más nuevos.
