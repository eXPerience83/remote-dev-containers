# TrueNAS SCALE: instalación, persistencia y actualización

> **Pruebas beta previas a v0.1.1:** el código fuente `0.1.1-beta.1` no es un tag publicado. Fija por digest la imagen `edge-amd64` tras confirmar CI/publicación, conserva el digest anterior para rollback y sigue el [checklist de aceptación beta](releases.es.md) antes de plantear una estable.

Esta guía describe el canal **edge experimental**; todavía no existe una release estable. La única definición de despliegue es [compose/truenas.yml](../compose/truenas.yml). Para pruebas más completas, consulta el [runbook TrueNAS](truenas-antigravity-validation.md) y el [contrato ACL](truenas-acl-contract.es.md).

## 1. Dataset inicial y seguridad

**Instalación nueva:** crea en la interfaz TrueNAS un dataset raíz, por ejemplo **Pool1/remote-dev**, montado en **/mnt/Pool1/remote-dev**, con preset **Generic / POSIX ACL**. Solo la raíz necesita ser un dataset ZFS. Los directorios hijos de trabajo y estado serán carpetas normales que crea el inicializador; no tienen por qué aparecer en la lista de datasets. Los datasets hijos creados deliberadamente por el administrador también están permitidos y no se modifican.

**Instalación existente:** conserva el dataset y todos sus datos. Guarda el YAML actual sin contraseñas ni secretos y el digest inmutable de la imagen anterior antes de actualizar. Si usas el preset Apps/NFSv4, no apliques cambios recursivos de ACL, permisos o propietario: revisa la [auditoría y guía de migración](truenas-acl-contract.es.md). Un preflight de rutas correcto no demuestra que las ACL NFSv4 heredadas sean privadas.

Los endpoints Codex/Antigravity protegen su acceso mediante WEB_PASSWORD en el YAML; no existe un árbol de ficheros de contraseña. El launcher sigue sin contraseña en la LAN privada.

## 2. Obtener scripts de la revisión exacta de la imagen

Ejecuta el siguiente bloque en el **shell Bash del host TrueNAS**, no dentro de un agente. Fija la imagen seleccionada por digest aunque tengas un checkout coincidente. Para instalaciones sin checkout descarga también el YAML Compose de esa revisión, no solo los scripts.

~~~bash
set -euo pipefail
IMAGE=ghcr.io/experience83/remote-dev:edge-amd64
ROOT=/mnt/Pool1/remote-dev

sudo docker pull "$IMAGE"
IMAGE_REPO=ghcr.io/experience83/remote-dev
PINNED_IMAGE=""
while IFS= read -r repo_digest; do
  case "$repo_digest" in
    "$IMAGE_REPO"@sha256:*) PINNED_IMAGE="$repo_digest"; break ;;
  esac
done < <(sudo docker image inspect "$IMAGE" \
  --format '{{range .RepoDigests}}{{println .}}{{end}}')
[[ "$PINNED_IMAGE" =~ ^ghcr\.io/experience83/remote-dev@sha256:[0-9a-f]{64}$ ]] || {
  echo 'Falta el digest del registro: no despliegues una etiqueta mutable' >&2
  exit 1
}
REV="$(sudo docker image inspect "$PINNED_IMAGE" \
  --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')"
[[ "$REV" =~ ^[0-9a-f]{40}$ ]] || { echo 'Revisión de origen inválida' >&2; exit 1; }

SETUP="$(mktemp -d /tmp/remote-dev-setup.XXXXXXXX)"
mkdir -p "$SETUP/scripts/lib" "$SETUP/compose"
for path in \
  scripts/init-data-layout.py \
  scripts/preflight-data-layout.py \
  scripts/truenas-acl-audit.py \
  scripts/lib/data_layout.py \
  compose/truenas.yml; do
  curl -fsSL --retry 2 \
    "https://raw.githubusercontent.com/eXPerience83/remote-dev-containers/$REV/$path" \
    -o "$SETUP/$path"
done
echo "Revisión de origen: $REV"
echo "Imagen inmutable: $PINNED_IMAGE"
echo "Ficheros de la misma revisión: $SETUP"
~~~

Los scripts **y la plantilla Compose original** se descargan por HTTPS del commit inmutable obtenido de la imagen **fijada por digest**. Mantén abierta la misma sesión Bash (`SETUP`, `REV` y `PINNED_IMAGE`) e inspecciona los scripts antes de ejecutarlos como administrador.

## 3. Crear directamente los directorios persistentes

Comprueba que ROOT **existe y coincide con el dataset correcto**. El inicializador no crea la raíz ni ningún dataset ZFS; rechaza symlinks y componentes no directorio, es idempotente y no borra, migra o cambia recursivamente contenido o permisos existentes.

Para el YAML de referencia (Codex y Antigravity opcional):

~~~bash
sudo python3 -B "$SETUP/scripts/init-data-layout.py" --root "$ROOT" --include-antigravity
sudo python3 -B "$SETUP/scripts/preflight-data-layout.py" --root "$ROOT" --include-antigravity
sudo python3 -B "$SETUP/scripts/truenas-acl-audit.py" --root "$ROOT" --include-antigravity
~~~

Si estás dentro de un checkout exactamente coincidente, los comandos equivalentes son:

~~~bash
sudo python3 -B scripts/init-data-layout.py --root /mnt/Pool1/remote-dev --include-antigravity
sudo python3 -B scripts/preflight-data-layout.py --root /mnt/Pool1/remote-dev --include-antigravity
sudo python3 -B scripts/truenas-acl-audit.py --root /mnt/Pool1/remote-dev --include-antigravity
~~~

Quita **--include-antigravity** solamente si eliminaste de verdad ese servicio y sus bind mounts del YAML. El archivo [scripts/lib/data_layout.py](../scripts/lib/data_layout.py) define el conjunto canónico de rutas:

~~~text
/mnt/Pool1/remote-dev/
  workspaces/codex/
  workspaces/antigravity/
  state/codex/{agent,runtime,mise,gh,git,ssh}/
  state/antigravity/{bin,runtime,vendor,config,mise,gh,git,ssh}/
~~~

Los nuevos workspaces se crean con modo 0755 y las hojas privadas de estado con modo 0700; los padres estructurales reciben 0755. **Las rutas preexistentes no se reescriben** (incluidos datasets hijos). No realices chmod/chown recursivo ni montes la raíz entera en un agente. Preflight valida rutas y la auditoría ACL es de solo lectura. Ninguno de estos comandos crea contraseñas o credenciales.

## 4. Configura el YAML y despliega

Usa **`$SETUP/compose/truenas.yml`**, descargado del mismo `REV` que la imagen y los scripts. Genera una copia distinta fijada por digest, sin modificar la plantilla original:

~~~bash
SOURCE_COMPOSE="$SETUP/compose/truenas.yml"
PINNED_COMPOSE="$SETUP/truenas-pinned.yml"
[[ -f "$SOURCE_COMPOSE" ]] || { echo 'Falta el YAML Compose de origen' >&2; exit 1; }
[[ "$(head -n 1 "$SOURCE_COMPOSE")" == 'x-remote-dev-image: &remote-dev-image '* ]] || {
  echo 'Ancla de imagen Compose inesperada; inspecciona la plantilla' >&2
  exit 1
}
{
  printf 'x-remote-dev-image: &remote-dev-image %s\n' "$PINNED_IMAGE"
  tail -n +2 "$SOURCE_COMPOSE"
} > "$PINNED_COMPOSE"
echo "Edita y pega este YAML fijado para Custom App: $PINNED_COMPOSE"
~~~

Utiliza **`PINNED_COMPOSE`** en el editor Custom App, no la plantilla con el tag mutable. El bloque sustituye el **ancla compartida** `x-remote-dev-image` para que launcher, Codex y Antigravity opcional usen la misma referencia inmutable `ghcr.io/experience83/remote-dev@sha256:…`. Antes de guardar:

- Cambia la IP bind de ejemplo 192.168.1.10 a tu IP LAN/Tailscale.
- Cambia cada bind source /mnt/Pool1/remote-dev si tu dataset está en otra ruta.
- Configura WEB_PASSWORD para Codex y Antigravity habilitado (valor no vacío, una línea). Pueden coincidir bajo el contrato actual.
- Verifica que todos los servicios habilitados usan **el mismo ancla de imagen fijada por digest**; comprueba el YAML guardado porque TrueNAS puede reescribir interpolaciones y comentarios.
- Conserva raíz de solo lectura, montajes/capacidades estrechos y puertos 7680/7681/7682 solo en red privada. No añadas el socket Docker.

Un administrador puede leer el YAML, incluidos secretos configurados. Sanea capturas/exportaciones.

## 5. Aceptación de PR2 después de actualizar

Cuando la App use el nuevo edge sin haber borrado estado:

~~~bash
set -euo pipefail
CHECK_ANTIGRAVITY=0  # Pon 1 si el servicio opcional está desplegado
containers=(codex-remote-dev)
if [[ "$CHECK_ANTIGRAVITY" == "1" ]]; then
  containers+=(antigravity-remote-dev)
fi
for container in "${containers[@]}"; do
  sudo docker exec "$container" remote-dev-version --check
  sudo docker exec "$container" remote-dev-base-verify
  [[ "$(sudo docker exec "$container" stat -c '%u:%g %a' /usr/share/doc/remote-dev)" == '0:0 755' ]] || {
    echo "ERROR: $container has an unsafe or unreadable notice directory" >&2
    exit 1
  }
  sudo docker exec "$container" remote-dev-notices --check
  sudo docker exec "$container" /bin/bash -c \
    'set -euo pipefail; cd / && for tool in ruff pytest pre-commit yq shfmt actionlint; do "$tool" --version; done'
done
~~~

En la imagen posterior a #285, el directorio de avisos debe ser `root:root 0755` y `remote-dev-notices --check` debe pasar **sin añadir `DAC_READ_SEARCH`, `DAC_OVERRIDE` ni otras capacidades**. Si falla, revisa el digest de imagen desplegado; no relajes `cap_drop: [ALL]` ni cambies ACL del host para ocultar el defecto.

El bloque comprueba **solo Codex** por defecto. Pon `CHECK_ANTIGRAVITY=1` **cuando Antigravity esté habilitado**, para no omitir silenciosamente sus comprobaciones. Base Verify comprueba **53 comandos** desde un CWD neutral; el bucle demuestra que las seis CLI nuevas resuelven directamente. CI ya probó operaciones reales de las seis bajo ambos roles, pero no sustituye sesiones autenticadas.

Abre el launcher en **http://IP-PRIVADA-TRUENAS:7680**, accede a Codex y Antigravity habilitado y **comprueba que las conversaciones anteriores se pueden retomar**. Para una imagen construida desde la [revisión exacta de la PR #294](https://github.com/eXPerience83/remote-dev-containers/commit/03e7c650828f47482e12b568f4a6127e658ed1d6), las versiones revisadas son Python **3.14.10** por defecto y **3.15.2** seleccionable por proyecto. Una revisión posterior puede fijar otros parches: contrasta el SHA de origen exacto de la imagen con su `versions.env`, sin suponer que el tag mutable `edge` ya se ha actualizado. Comprueba que Python 3.14 sigue siendo predeterminado y que 3.15 solo se selecciona por un proyecto compatible sin cambiar los proyectos reales para probar. Revisa Doctor, montajes privados y aislamiento sin copiar secretos a los informes.

Registra SHA, digest, resultados y errores saneados en [#121](https://github.com/eXPerience83/remote-dev-containers/issues/121). No cierres la aceptación de PR2 antes de estas pruebas reales.

## 6. Actualización, rollback y limpieza

Para actualizar, anota el digest anterior, comprueba los workflows edge verdes, haz pull del nuevo edge, registra su **RepoDigest** y `REV`, descarga su YAML de Compose correspondiente, vuelve a generar la copia fijada por digest como en la sección 4 y recrea los contenedores conservando sus bind mounts y ajustes específicos del host. Verifica después el SHA/digest efectivo y las sesiones. Para revertir, restaura el digest anterior **sin borrar los datos persistentes**; revertir datos requiere otro plan.

Puedes borrar solo la carpeta temporal SETUP cuando ya no necesites los scripts. Nunca borres ROOT ni credenciales para reinstalar. El tag edge es mutable; **latest** está reservado para stable y no debe usarse aquí.
