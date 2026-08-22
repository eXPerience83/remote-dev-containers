# Actualizaciones del runtime de Codex

Remote Dev siempre incluye una versión inmutable de Codex CLI probada con la imagen. Además, un administrador puede instalar de forma explícita un runtime oficial de Codex más reciente sin reconstruir ni sustituir la imagen del contenedor.

Este mecanismo sigue deliberadamente el modelo de admisión de runtime de Antigravity, con una diferencia importante: OpenAI publica actualmente el CLI/paquete de Codex bajo sus propios términos de licencia Apache-2.0 de upstream y proporciona archivos de paquete completos. Esos términos y avisos de upstream siguen aplicándose al paquete de Codex descargado; la licencia del proyecto Remote Dev no se extiende a componentes de terceros. Por eso Remote Dev descarga el paquete oficial exacto de Codex en lugar de ejecutar el instalador mutable de upstream.

Estos estados de confianza describen el paquete de runtime de Codex de upstream, no la estabilidad de Remote Dev. La imagen pública `edge` de Remote Dev sigue siendo experimental y no es una release estable de Remote Dev; consulta [los canales de release y criterios de promoción](releases.md).

## Estados de confianza

El menú, `remote-dev-version` y `remote-dev-doctor` distinguen estos estados:

- **Incluido en la imagen** — la versión de Codex integrada en la imagen de Remote Dev. Es el fallback probado con esa imagen.
- **Fuente oficial; revisión de Remote Dev pendiente** — se ha descargado explícitamente un paquete estable más nuevo desde la release oficial de OpenAI en GitHub, se han verificado el SHA-256 publicado en los metadatos de la release y la identidad del paquete, y han pasado las pruebas de compatibilidad acotadas. Remote Dev todavía no ha revisado ni probado en uso real esa release exacta como parte de una build de imagen.
- **Dañado o modificado localmente** — el runtime opcional persistente ya no coincide con su manifiesto privado o incumple la identidad esperada de archivos/directorios. Remote Dev lo rechaza y usa el fallback incluido en la imagen.
- **Se prefiere el incluido** — el runtime opcional es igual o más antiguo que la versión de Codex que ahora incluye la imagen. Gana automáticamente la copia equivalente o más nueva ya probada con la imagen.

“Revisión pendiente” **no** significa que la descarga se acepte sin comprobaciones de integridad. Antes de publicarla se verifican origen, tag estable, arquitectura, digest de la release, estructura del paquete, identidad de archivos y pruebas de compatibilidad. Lo pendiente es la revisión y la validación real de Remote Dev para esa release concreta de Codex.

## Red sólo mediante acción explícita

El arranque normal, `status`, `resolve`, `verify`, el lanzamiento de Codex, reanudar sesiones, health checks y diagnósticos no contactan con el endpoint de actualizaciones.

Sólo hay acceso a red después de una acción explícita de instalación/actualización:

```bash
remote-dev-codex-runtime install
remote-dev-codex-runtime update
```

`install` y `update` utilizan la misma ruta de admisión acotada: comprueban la última release oficial estable exacta y sólo publican un runtime opcional cuando es más nuevo que el fallback inmutable incluido y que cualquier runtime opcional ya activo. Ambos comandos interactivos piden confirmación **antes** de contactar con la release oficial. `--yes` queda disponible para un administrador que ya está realizando de forma explícita una operación de ciclo de vida no interactiva:

```bash
remote-dev-codex-runtime install --yes
remote-dev-codex-runtime update --yes
```

El menú ofrece las acciones explícitas de actualización y eliminación. No hay actualizador en segundo plano ni sustituciones silenciosas del runtime.

## Límite del paquete oficial

El gestor reconoce el paquete Linux musl oficial correspondiente a la arquitectura de la máquina:

```text
codex-package-x86_64-unknown-linux-musl.tar.gz
codex-package-aarch64-unknown-linux-musl.tar.gz
```

La publicación de imágenes y la CI de Remote Dev siguen siendo **AMD64-first**. Reconocer el formato de paquete AArch64 es una capacidad de mapeo de upstream en el gestor de runtime y la lógica de build; todavía no constituye un target ARM64 soportado/publicado por Remote Dev. La validación completa de build, seguridad, ciclo de vida y hardware real ARM64 se sigue en [#112](https://github.com/eXPerience83/remote-dev-containers/issues/112).

Se utiliza el paquete completo de upstream porque Codex resuelve sus binarios auxiliares y recursos respecto a la raíz de ese paquete. La estructura esperada incluye:

```text
bin/codex
bin/codex-code-mode-host
codex-path/rg
codex-resources/bwrap
codex-package.json
```

Se permiten otros archivos normales dentro de los directorios canónicos del paquete oficial, pero se rechazan rutas absolutas, traversal, enlaces, dispositivos, FIFOs, rutas superiores inesperadas y tamaños o cantidades de miembros excesivos.

El paquete se mantiene fuera del `CODEX_HOME` real. Es intencionado: `CODEX_HOME=/root/.codex` sigue siendo exclusivamente el límite de credenciales, configuración y sesiones del usuario, mientras que el runtime opcional vive en:

```text
/root/.local/share/remote-dev/codex-runtime
```

Esa ruta sólo se monta en el servicio de Codex. El launcher y el servicio Antigravity no la reciben.

Mantener el paquete fuera de `CODEX_HOME/packages/standalone/releases` también evita que Codex clasifique la copia gestionada por Remote Dev como su propia instalación standalone y pueda saltarse este gestor explícito mediante la ruta de autoactualización de upstream.

## Comprobaciones de admisión

Antes de activar un runtime opcional, Remote Dev:

1. obtiene los metadatos de release del repositorio oficial y fijo de Codex de OpenAI en GitHub;
2. exige un tag de release estable exacto;
3. selecciona sólo el paquete correspondiente al límite de arquitectura soportado actual;
4. verifica durante la descarga el tamaño y el SHA-256 publicado en los metadatos de la release de GitHub;
5. extrae con reglas acotadas y rechaza enlaces, archivos especiales y path traversal;
6. verifica los metadatos canónicos del paquete de Codex y los ejecutables obligatorios;
7. ejecuta los bytes nuevos del proveedor con un `HOME`/`CODEX_HOME` sintético sin credenciales, fuera del workspace del usuario y, cuando el proceso principal es root, con un UID/GID fijo sin privilegios;
8. limita el tiempo y la salida capturada de las pruebas del candidato;
9. comprueba `codex --version`, las opciones de launcher necesarias y el contrato `codex-code-mode-host --listen ws://127.0.0.1:0` + `/readyz`;
10. calcula la huella de cada archivo publicado y la guarda en un manifiesto privado restrictivo;
11. cambia el puntero activo de forma atómica sólo después de superar todas las comprobaciones;
12. inicializa un stamp privado de verificación sólo después de comprobar que la generación final publicada sigue correspondiendo al paquete que superó la verificación completa.

El staging ejecutable de admisión usa la raíz transitoria fija
`/run/remote-dev-codex-update`, nunca `/tmp` ni un `TMPDIR` controlado por quien
invoca el gestor. La raíz de staging y el directorio de cada operación,
propiedad del gestor, usan modo `0711`. Los directorios extraídos y ejecutables
del paquete, propiedad de root, se
normalizan a `0755` independientemente del umask del proceso, mientras que los
archivos no ejecutables usan `0644`. Antes de descargar el paquete, el gestor
también ejecuta una prueba acotada y sin privilegios dentro de la raíz de
staging. El `HOME` y directorio de trabajo sintéticos usan modo `0700` y
pertenecen a UID/GID `65534`. Así se conserva intacto el montaje
intencionadamente no ejecutable de `/tmp` sin hacer atravesables el runtime
persistente ni las credenciales, y cada operación elimina su árbol de staging
tras éxito, error, timeout o una señal de terminación capturable.

Las mutaciones se serializan con un lock privado. El hash del paquete se calcula sin mantener ese lock de mutación; sólo lo mantienen las secciones cortas de publicación y de nueva comprobación del stamp. Una admisión fallida o interrumpida deja intacto el runtime activo anterior. Los directorios de staging `.candidate-*` abandonados por una publicación anterior interrumpida se recuperan en un intento posterior, mientras que un marcador advisory por candidato evita eliminar una publicación que sigue activa. El lanzamiento normal no mantiene el lock de mutación.

## Detección rápida de cambios y verificación completa

La publicación y el verificador completo explícito comprueban el SHA-256 de cada archivo del paquete contra el manifiesto privado. Después de una verificación completa satisfactoria, el gestor escribe atómicamente `verification-stamp.json` fuera de la release activa. El stamp acotado y versionado liga el nombre de la release actual, la versión y el target del runtime con el SHA-256 del pequeño manifiesto privado y con una fingerprint canónica de metadatos Linux para el puntero, la release, el manifiesto, los directorios del paquete y sus objetos. La fingerprint registra tipo de objeto, dispositivo, inode, número de enlaces, tamaño, propietario, grupo, modo, mtime y ctime con precisión de nanosegundos.

`resolve`, `status` y `status --menu` vuelven a validar siempre las reglas estructurales y de permisos existentes, hashean el manifiesto pequeño y comparan la fingerprint actual de metadatos con ese stamp de confianza. Cuando coinciden, no se lee ni se hashea ningún archivo del paquete. Un stamp ausente, malformado, truncado, symlink, inseguro, incompatible o distinto nunca otorga confianza: el gestor ejecuta inmediatamente la verificación SHA-256 completa del paquete antes de permitir el runtime opcional. Una comprobación completa satisfactoria refresca el stamp de forma atómica. No hay TTL; la invalidación depende únicamente de cambios observados.

Usa el siguiente comando offline para forzar la verificación completa aunque exista un stamp válido:

```bash
remote-dev-codex-runtime verify
```

`remote-dev-doctor`, y por tanto la acción **Run diagnostics** del menú, ejecuta `verify` antes de mostrar el estado normal del runtime. La corrupción o la incapacidad de mantener el stamp de verificación hace fallar los diagnósticos. Si `resolve` acaba de completar una comprobación completa satisfactoria pero no puede persistir el stamp opcional, puede usar esos bytes verificados para esa invocación y emite una advertencia; la siguiente invocación los verificará por completo otra vez.

Esta optimización no amplía la frontera de confianza. La detección por metadatos cubre cambios locales ordinarios, sustituciones y corrupción que alteren la identidad registrada. No protege frente a un proceso con la autoridad del propietario del runtime o root del contenedor que pueda alterar coherentemente el runtime y el estado de verificación, frente a root que sustituya el propio gestor/launcher, frente al administrador del host o ZFS, ni frente a un kernel o almacenamiento comprometido. Por tanto, no se garantiza detectar antes de cada lanzamiento una corrupción física que conserve todos los metadatos registrados; los errores de lectura, los mecanismos de integridad de ZFS y `verify`/diagnostics explícitos siguen siendo las rutas de comprobación completa. La ventana TOCTOU final entre el gestor y `exec` no cambia y se sigue por separado en [#114](https://github.com/eXPerience83/remote-dev-containers/issues/114).

## Lanzamiento y fallback

Todos los caminos soportados para iniciar o reanudar Codex siguen pasando por `run-codex`. Primero se valida la política de aprobaciones/sandbox propiedad del proyecto y después se pide al gestor local de runtime el ejecutable activo.

Se selecciona un runtime opcional válido sólo cuando es más nuevo. Si falla el resolver, el estado está dañado, el ejecutable seleccionado no está disponible o la release opcional no es más nueva que la incluida, `run-codex` selecciona `/usr/local/bin/codex`.

El contrato de aislamiento existente no cambia: Remote Dev sigue pasando `--sandbox danger-full-access` porque el contenedor exterior es el límite de aislamiento soportado. El paquete opcional completo contiene el recurso Bubblewrap de upstream, pero Remote Dev no instala un comando `bwrap` de sistema ni habilita el sandbox anidado.

## Estado y eliminación

```bash
remote-dev-codex-runtime status
remote-dev-codex-runtime status --menu
remote-dev-codex-runtime resolve
remote-dev-codex-runtime verify
remote-dev-codex-runtime remove
remote-dev-codex-runtime remove --yes
```

`resolve` está pensado para el launcher del proyecto e imprime la ruta del ejecutable seleccionado. Realiza comprobaciones offline estructurales y de detección de cambios, escalando a la verificación SHA-256 completa cuando el stamp de confianza no está disponible o es distinto.

`remove` elimina únicamente el estado del runtime opcional gestionado por Remote Dev y vuelve inmediatamente al fallback inmutable incluido. Nunca modifica `/usr/local/bin/codex` ni `/root/.codex`. La eliminación interactiva pide confirmación; `--yes` es la forma explícita no interactiva.

## Layout persistente del host

El árbol canónico de datos del host añade un directorio exclusivo de Codex:

```text
state/codex/runtime/
```

En el ejemplo genérico debe crearse junto con el resto de directorios de estado de Codex antes de ejecutar el preflight. En el ejemplo de TrueNAS la ruta canónica es:

```text
/mnt/Pool1/remote-dev/state/codex/runtime
```

El preflight del host rechaza symlinks en esta ruta. Al arrancar el contenedor sólo se acepta el target canónico del runtime de Codex y se rechazan componentes de ruta que sean symlinks o no sean directorios antes de aplicar el endurecimiento recursivo de permisos privados.
