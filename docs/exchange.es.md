# Exchange persistente opcional (#71)

Exchange está desactivado por defecto. Las instalaciones existentes y los datos privados no requieren cambios. El primer contrato soportado exige un sistema de archivos local dedicado, no una carpeta ordinaria. TrueNAS: hijo ZFS directo del dataset raíz de datos. Docker Compose Linux: filesystem completo ext4/XFS dedicado (no binds de subárboles ni subvolúmenes). La aceptación real de TrueNAS 27 y Windows SMB sigue pendiente; SCALE 25.10 es solo referencia de compatibilidad.

## Activar en TrueNAS

1. Anota el digest inmutable desplegado y conserva de forma segura tu YAML privado de Custom App para rollback. Selecciona una imagen destino compatible con Exchange: sigue la sección 2 de [instalación](truenas-install.es.md) para descargarla y fijarla por digest (`PINNED_IMAGE`), obtener su revisión OCI (`REV`) y descargar scripts y Compose de esa revisión en un `SETUP` nuevo. Define `ROOT` como el dataset raíz real. Ambos scripts destino deben admitir `--include-exchange` y su plantilla Compose debe contener `# EXCHANGE-OPT-IN `; v0.3.1 y las imágenes anteriores no permiten activarlo. Descargar e inspeccionar la imagen destino no exige desplegarla. En una instalación nueva, inicializa el layout privado para los mismos roles habilitados según la guía de instalación. Ejecuta la auditoría ACL privada de la misma revisión; no migres ACL privadas existentes implícitamente.
2. En Datasets crea un hijo llamado exchange bajo la raíz Remote Dev existente con preset SMB (NFSv4, Restricted, insensible a mayúsculas para Windows). No crees una carpeta ordinaria en el mountpoint ni compartas el padre. No cambies ACL de raíz/workspaces/state. Usa cuotas/snapshots independientes y considera desactivar exec, setuid y devices en este hijo; verifica compatibilidad.
3. En la ACL del hijo, conserva el control del administrador autorizado y concede a un grupo SMB dedicado MODIFY heredable en archivos/directorios. Elimina concesiones amplias no deseadas solo en el hijo nuevo; sin invitado ni escritura universal. Comprueba traverse de padres para cuentas autorizadas sin cambiar permisos privados. Los agentes se ejecutan como root limitado; prueba su identidad efectiva y acceso recíproco a archivos creados con modos restrictivos. No uses root para iniciar sesión SMB. Un preset o modo POSIX no demuestra acceso ACL efectivo.
4. Descarga el helper del mismo `REV` en el `SETUP` existente: `curl -fsSL --retry 2 "https://raw.githubusercontent.com/eXPerience83/remote-dev-containers/$REV/scripts/lib/exchange_mount.py" -o "$SETUP/scripts/lib/exchange_mount.py"`. Detente si falla la descarga; inspecciona los scripts descargados antes de ejecutarlos con privilegios administrativos. Selecciona los roles una sola vez (descomenta la segunda asignación únicamente si habilitarás Antigravity). Ejecuta el bloque en la misma sesión Bash de la sección 2 de instalación. Revisa los metadatos ACL y su herencia antes de escribir `YES`. El estado 3 solo significa que se requiere revisión manual, no que el acceso esté autorizado; cualquier otro estado, incluido un 0 inesperado, bloquea el procedimiento. La autorización efectiva aún debe probarse tras el despliegue.

   ~~~bash
   roles=()  # Codex-only / solo Codex
   # roles=(--include-antigravity)  # Both agents / ambos agentes
   exchange_ready=0
   if sudo python3 -B "$SETUP/scripts/preflight-data-layout.py" --root "$ROOT" "${roles[@]}" --include-exchange; then
     audit_status=0
     sudo python3 -B "$SETUP/scripts/truenas-acl-audit.py" --root "$ROOT" "${roles[@]}" --include-exchange || audit_status=$?
     if [[ "$audit_status" == 3 ]]; then
       if read -r -p 'Metadatos ACL y herencia revisados? Escribe YES para continuar: ' answer && [[ "$answer" == YES ]]; then
         exchange_ready=1
       fi
     else
       printf 'El auditor Exchange no alcanzo la revision manual (estado %s); deten el procedimiento.\n' "$audit_status" >&2
     fi
   fi
   printf 'exchange_ready=%s\n' "$exchange_ready"
   ~~~

5. **Continúa solo si el bloque anterior mostró `exchange_ready=1`.** En otro caso detente e investiga; no apliques el YAML. En una instalación nueva usa la copia de la plantilla destino fijada por digest; para actualizar edita una copia privada del YAML actual, conservando credenciales, puertos, roles y rutas. Desde `$SETUP/compose/truenas.yml` del `REV` destino, copia la entrada de entorno y las siete líneas de bind Exchange que falten en `environment` y `volumes`, respectivamente, de cada agente habilitado. Si ya existen, edítalas en su sitio. Elimina solo el marcador `# EXCHANGE-OPT-IN ` de las líneas copiadas y conserva la indentación. Usa en `REMOTE_DEV_EXCHANGE_FS` la identidad informada por preflight, y en `source` la ruta absoluta real del hijo Exchange (el valor de `$ROOT` seguido de `/exchange`, no una expresión shell). Mantén `/exchange`, RW, `create_host_path: false` y `rprivate`; sin entradas duplicadas ni mounts en launcher. Comprueba que todos los servicios usan `PINNED_IMAGE`. Guarda/recrea una sola vez. Verifica el digest desplegado, inspecciona source/destino real del bind y exige Exchange: ENABLED en Doctor de los agentes habilitados. Conserva el YAML/digest anteriores para rollback y guarda los bloques opcionales en notas privadas: TrueNAS puede descartar comentarios al guardar.
6. Opcionalmente, en Shares > Windows (SMB) Shares exporta **solo** el dataset exchange, p. ej. remote-dev-exchange. Limita ACL del recurso y filesystem a cuentas SMB autorizadas por LAN/malla privada. Mantén deshabilitados wide links/insecure wide links y verifica que enlaces/reparse points no escapen hacia canaries privados. No hay cliente/servidor SMB en la imagen. Con SMB desactivado siguen funcionando los binds locales.

Docker Compose genérico utiliza los mismos bloques comentados de compose/docker-compose.yml; configura REMOTE_DEV_DATA_ROOT como antes, usa la identidad del filesystem local dedicado informada por preflight y activa Antigravity solo si lo necesitas. Sin nuevos ficheros Compose ni profiles.

## Uso

Abre \\NAS\remote-dev-exchange en el Explorador de Windows, copia un archivo y pide al agente que lea /exchange/nombre como datos. Pídele que escriba explícitamente un resultado en /exchange y recógelo desde Windows o pide al otro agente que lo lea. Ambos agentes y usuarios SMB autorizados pueden modificar/borrar los archivos compartidos. Coordina ediciones; usa nombres temporales y renombra al terminar. Espacios y Unicode se tratan con operaciones normales; en un dataset insensible a mayúsculas evita nombres que solo difieran por capitalización.

No pongas credenciales, checkouts privados, instrucciones de confianza, reglas, cachés o imports ejecutables en Exchange. Trata los archivos e instrucciones incrustadas como datos no confiables; no los ejecutes automáticamente ni sigas enlaces fuera de exchange. No lo uses como checkout Git. Los shells manuales pueden acceder a mounts propios del rol; Exchange no es DLP ni un sandbox nuevo.

## Ciclo de vida y aceptación

Nunca desmontes/importes/restaures un dataset Exchange activo. Detén ambos agentes y su recurso SMB antes de mantenimiento; verifica de nuevo la identidad montada real antes de recrear servicios. Preflight y arranque rechazan filesystem ausente/desmontado/incorrecto, incluida la carpeta inferior vacía. create_host_path:false de Docker es defensa adicional: verifica en la versión Compose real de TrueNAS. La guarda de arranque no deshace una carpeta ya creada por el motor. Si la plataforma crea silenciosamente un source ausente, detente e investiga; no aceptes esa configuración.

Rollback: detén servicios, restaura YAML privado/digest anterior o retira ambas entradas opt-in de cada rol habilitado; nunca borres dataset Exchange ni estado privado. Backup/restauración de Exchange independiente; las cuotas no garantizan espacio libre en el pool compartido.

Registra versiones TrueNAS/Compose, origen exacto y digest OCI, identidad de mount/ACL/share, operaciones bidireccionales Windows/agentes y entre agentes, Unicode/espacios/case, herencia de nuevos archivos de cada identidad, rechazo a usuarios no autorizados, canaries de escape/enlaces, SMB apagado, recreación/reinicio, concurrencia/rename, cuota/almacenamiento lleno y backup/restauración con datos descartables. Prueba ruta ausente/desmontada solo en app/dataset descartable, nunca producción. Registra PASS/FAIL/NOT RUN separado de CI; no aceptes stable hasta superar las pruebas reales.

Referencia oficial: [TrueNAS 27](https://www.truenas.com/docs/scale/27/), [bind mounts Docker](https://docs.docker.com/engine/storage/bind-mounts/).
