# Exchange persistente opcional (#71)

Exchange está desactivado por defecto. Las instalaciones existentes y los datos privados no requieren cambios. El primer contrato soportado exige un sistema de archivos local dedicado, no una carpeta ordinaria. TrueNAS: hijo ZFS directo del dataset raíz de datos. Docker Compose Linux: filesystem completo ext4/XFS/Btrfs dedicado (no binds de subárboles ni subvolúmenes). La aceptación real de TrueNAS 27 y Windows SMB sigue pendiente; SCALE 25.10 es solo referencia de compatibilidad.

## Activar en TrueNAS

1. Anota el digest inmutable desplegado y conserva de forma segura tu YAML privado de Custom App. Ejecuta la auditoría ACL privada de la misma revisión; no migres ACL privadas existentes implícitamente.
2. En Datasets crea un hijo llamado exchange bajo la raíz Remote Dev existente con preset SMB (NFSv4, Restricted, insensible a mayúsculas para Windows). No crees una carpeta ordinaria en el mountpoint ni compartas el padre. No cambies ACL de raíz/workspaces/state. Usa cuotas/snapshots independientes y considera desactivar exec, setuid y devices en este hijo; verifica compatibilidad.
3. En la ACL del hijo, conserva el control del administrador autorizado y concede a un grupo SMB dedicado MODIFY heredable en archivos/directorios. Elimina concesiones amplias no deseadas solo en el hijo nuevo; sin invitado ni escritura universal. Comprueba traverse de padres para cuentas autorizadas sin cambiar permisos privados. Los agentes se ejecutan como root limitado; prueba su identidad efectiva y acceso recíproco a archivos creados con modos restrictivos. No uses root para iniciar sesión SMB. Un preset o modo POSIX no demuestra acceso ACL efectivo.
4. Usa los scripts de la revisión exacta de la imagen, según [instalación](truenas-install.es.md). Ejecuta el preflight existente con --include-exchange. Copia el valor REMOTE_DEV_EXCHANGE_FS informado en la entrada opcional de entorno YAML de cada agente habilitado. El audit opcional devuelve deliberadamente 2 con revisión manual requerida aun cuando montaje/tipo sean correctos; revisa metadatos ACL y prueba autorización por separado.

~~~bash
sudo python3 -B "$SETUP/scripts/preflight-data-layout.py" --root "$ROOT" --include-antigravity --include-exchange
sudo python3 -B "$SETUP/scripts/truenas-acl-audit.py" --root "$ROOT" --include-antigravity --include-exchange
~~~

5. En el YAML existente, elimina el marcador literal "# EXCHANGE-OPT-IN " de la entrada de entorno y las siete líneas de bind de cada agente habilitado. Sustituye identidad de ejemplo por la informada y la ruta de ejemplo por el hijo exchange de tu raíz. Nada en launcher. Guarda/recrea. Doctor debe mostrar Exchange: ENABLED. Inspecciona source/destino real del bind, no solo YAML. Conserva los bloques opcionales en tus notas de despliegue privadas: TrueNAS puede descartar comentarios al guardar.
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
