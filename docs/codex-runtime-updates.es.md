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

El arranque normal, `status`, `resolve`, el lanzamiento de Codex, reanudar sesiones, health checks y diagnósticos no contactan con el endpoint de actualizaciones.

Sólo hay acceso a red después de una acción explícita de actualización:

```bash
remote-dev-codex-runtime update
```

El comando interactivo pide confirmación **antes** de contactar con la release oficial. `--yes` queda disponible para un administrador que ya está realizando de forma explícita una actualización no interactiva:

```bash
remote-dev-codex-runtime update --yes
```

El menú ofrece esa misma acción explícita. No hay actualizador en segundo plano ni sustituciones silenciosas del runtime.

## Límite del paquete oficial

El actualizador acepta únicamente la última release estable exacta `rust-vX.Y.Z` y únicamente el paquete Linux musl correspondiente a la arquitectura actual:

```text
codex-package-x86_64-unknown-linux-musl.tar.gz
codex-package-aarch64-unknown-linux-musl.tar.gz
```

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
3. selecciona sólo el paquete correspondiente a la arquitectura soportada actual;
4. verifica durante la descarga el tamaño y el SHA-256 publicado en los metadatos de la release de GitHub;
5. extrae con reglas acotadas y rechaza enlaces, archivos especiales y path traversal;
6. verifica los metadatos canónicos del paquete de Codex y los ejecutables obligatorios;
7. ejecuta los bytes nuevos del proveedor con un `HOME`/`CODEX_HOME` sintético sin credenciales, fuera del workspace del usuario y, cuando el proceso principal es root, con un UID/GID fijo sin privilegios;
8. limita el tiempo y la salida capturada de las pruebas del candidato;
9. comprueba `codex --version`, las opciones de launcher necesarias y el contrato `codex-code-mode-host --listen ws://127.0.0.1:0` + `/readyz`;
10. calcula la huella de cada archivo publicado y la guarda en un manifiesto privado restrictivo;
11. cambia el puntero activo de forma atómica sólo después de superar todas las comprobaciones.

Las mutaciones se serializan con un lock privado. Una admisión fallida o interrumpida deja intacto el runtime activo anterior. El lanzamiento normal no necesita ese lock: verifica el conjunto de archivos ya publicado y puede volver inmediatamente al Codex incluido en la imagen.

## Lanzamiento y fallback

Todos los caminos soportados para iniciar o reanudar Codex siguen pasando por `run-codex`. Primero se valida la política de aprobaciones/sandbox propiedad del proyecto y después se pide al gestor local de runtime el ejecutable activo.

Se selecciona un runtime opcional válido sólo cuando es más nuevo. Si falla el resolver, el estado está dañado, el ejecutable seleccionado no está disponible o la release opcional no es más nueva que la incluida, `run-codex` selecciona `/usr/local/bin/codex`.

El contrato de aislamiento existente no cambia: Remote Dev sigue pasando `--sandbox danger-full-access` porque el contenedor exterior es el límite de aislamiento soportado. El paquete opcional completo contiene el recurso Bubblewrap de upstream, pero Remote Dev no instala un comando `bwrap` de sistema ni habilita el sandbox anidado.

## Estado y eliminación

```bash
remote-dev-codex-runtime status
remote-dev-codex-runtime status --menu
remote-dev-codex-runtime resolve
remote-dev-codex-runtime remove
```

`resolve` está pensado para el launcher del proyecto e imprime la ruta del ejecutable seleccionado. Sólo realiza comprobaciones locales de integridad.

`remove` elimina únicamente el estado del runtime opcional gestionado por Remote Dev y vuelve inmediatamente al fallback inmutable incluido. Nunca modifica `/usr/local/bin/codex` ni `/root/.codex`.

## Layout persistente del host

El árbol canónico de datos del host añade un directorio exclusivo de Codex:

```text
state/codex/runtime/
```

En el ejemplo genérico debe crearse junto con el resto de directorios de estado de Codex antes de ejecutar el preflight. En el ejemplo de TrueNAS la ruta canónica es:

```text
/mnt/Pool1/remote-dev/state/codex/runtime
```

El preflight del host rechaza symlinks en esta ruta. Al arrancar el contenedor se endurecen los permisos del árbol de runtime montado antes de utilizarlo.
