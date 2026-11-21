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

Estos conceptos permanecen separados de la identidad legible del build y de la procedencia inmutable. La primera estable `v0.2.0` se publicó el 5/11/2026. El código `0.2.1` preparado **no** publica por sí mismo otra imagen: hasta que termine satisfactoriamente su workflow de tag, `stable` y `latest` seguirán apuntando al último digest estable publicado. Utiliza `edge`/`edge-amd64` solo para pruebas experimentales.

La versión local de código de este corte de mantenimiento es `0.2.1`. El número de código no acredita la publicación: edge conserva su identidad fechada y solo el workflow del tag estable `v0.2.1`, tras terminar correctamente, puede mover `stable` y `latest`. Los pines, los locks y el changelog pertenecen a sus procesos de revisión; las actualizaciones rutinarias no crean una nueva release estable automáticamente.

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

**Identidad del candidato estable:** Edge y stable pueden compartir el
SHA de código revisado, pero no necesariamente el digest OCI: el tag estable
reconstruye la imagen con metadatos de canal y versión propios. Antes de mover
los tags SemVer, `stable`, `stable-amd64` y `latest`, el publicador resuelve
los manifiestos AMD64 exactos de base y runtime, comprueba sus etiquetas y
avisos, y ejecuta las pruebas de arranque, aislamiento y autenticación
sobre el **manifiesto runtime**. Los dos informes SPDX y los dos Trivy se
generan a partir de sus respectivos manifiestos AMD64. Ambos SPDX incluyen
la identidad suplementaria del ZIP, binario y licencia Chromium obtenida de
la imagen; esto **no equivale a un análisis de CVE de Chromium**. Después
se aplica el veto a vulnerabilidades críticas corregibles. Los cuatro tags deben resolver al
**digest del índice OCI estable validado**, que debe contener el mismo
manifiesto AMD64 runtime probado y escaneado. El digest del índice no es
el del manifiesto hijo, ni debe coincidir con el de Edge.
La aceptación previa de Edge no acredita un despliegue estable en TrueNAS.

**Guarda de tags y antirretroceso:** Antes de modificar ningún tag, el
publicador comprueba los dos tags SemVer y todos los alias estables de base y
runtime. No sobrescribe una versión ya publicada con otro índice OCI ni
permite que un tag antiguo haga retroceder `stable/latest`. Una segunda
ejecución con digests y alias idénticos es de **solo lectura**; si reconstruye
digests distintos, la rechaza aunque comparta SHA de código. Conserva el
registro `stable-promotion-preflight.json` y los metadatos de promoción.

**Límite de publicación parcial:** GHCR no permite una publicación atómica
entre los dos repositorios. Un workflow rojo puede haber cambiado cualquier
subconjunto de los seis tags; **no garantiza que `stable/latest` permanezcan intactos**.

**Reconciliación exclusivamente por el operador (sin reintentos automáticos):**

1. Detener todos los publicadores, incluidas las reejecuciones históricas y
   otros escritores del registro. Conservar el journal de preflight, los
   digests de los **índices OCI** candidatos y aceptados previamente (si
   existen), y los logs del fallo. Leer y registrar los **seis tags**:
   `remote-dev-base:vX.Y.Z`, `remote-dev-base:stable-amd64`,
   `remote-dev:vX.Y.Z`, `remote-dev:stable`,
   `remote-dev:stable-amd64` y `remote-dev:latest`.
   Distinguir explícitamente los tags **ausentes antes** del intento.
2. Identificar qué escrituras llegaron a completarse. Si existía una release
   estable anterior, restaurar los alias afectados solo tras aprobación, con
   los **índices inmutables anteriores registrados**, no con tags mutables,
   reconstrucciones ni digests supuestos. Conciliar también **ambos tags de
   versión**: si solo se creó `remote-dev-base:vX.Y.Z`, restaurar
   `stable-amd64` no basta, porque la guarda bloqueará un reintento mientras
   quede el tag de versión sin pareja. Como alternativa, una decisión humana
   explícita puede autorizar completar la release con los **índices candidatos
   exactos que ya pasaron smoke y escaneos**, nunca con otro build.
3. Si era la **primera publicación estable**, puede que no exista ningún
   índice anterior. El estado de reversión es la **ausencia** de los tags
   nuevos, no un digest inventado. Localizar los alias creados y sus versiones
   GHCR. Borrar requiere autorización expresa y comprobar el alcance:
   la operación oficial **Delete package version** puede borrar *todos los
   tags asociados al mismo digest*, no solo uno. Si no se puede eliminar un
   tag individual sin afectar a otros válidos, detenerse y documentar el
   estado parcial/bloqueado; **no borrar versiones compartidas**.
4. Tras cualquier reconciliación autorizada, releer **los seis tags**,
   incluidos los que deberían estar ausentes, y verificar los requisitos
   de consistencia de la guarda para ambos tags SemVer y todos los alias.
   Solo después decidir un nuevo intento. Nunca relanzar a ciegas un
   publicador histórico.

Consultar la [documentación oficial de borrado/restauración de versiones](https://docs.github.com/en/packages/learn-github-packages/deleting-and-restoring-a-package).
El proyecto no dispone de rollback automático de GHCR.

**Requisito administrativo:** Verificar explícitamente las reglas GitHub
para crear, modificar y borrar tags `v*`, así como quién puede reejecutar
publicadores de tags históricos. La guarda nueva no protege retroactivamente
los workflows guardados en tags antiguos. Sin verificar estas protecciones,
la release sigue en **NO GO** incluso con CI verde.

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
