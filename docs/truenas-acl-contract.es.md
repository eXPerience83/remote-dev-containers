# Contrato ACL de TrueNAS y migración segura

Remote Dev guarda los workspaces y el estado/credenciales de los agentes bajo una única raíz Host Path creada por el administrador. En TrueNAS, los bits de modo POSIX por sí solos no describen todo el acceso efectivo cuando el dataset usa ACL NFSv4.

Este documento define el contrato de ACL de host soportado por el issue #186 y la migración conservadora validada sobre un TrueNAS 26 real con datos persistentes.

## Contrato de referencia para instalaciones nuevas

Crea el dataset raíz de Remote Dev con el preset **Generic** de TrueNAS.

Esta es una excepción deliberada de Remote Dev frente a la recomendación general de TrueNAS de usar el preset **Apps** para datos de aplicaciones. Remote Dev almacena credenciales de agentes y estado privado de runtime en el mismo árbol Host Path, y la validación real de #186 demostró que la herencia NFSv4 del preset Apps puede dejar acceso efectivo a principales adicionales del host aunque `ls -l` muestre `0700`. Por tanto, elegir Generic/POSIX forma parte del contrato de seguridad del estado privado de Remote Dev; no significa que el preset Apps sea incorrecto de forma general para aplicaciones de TrueNAS.

La raíz de referencia es:

```text
Pool1/remote-dev
/mnt/Pool1/remote-dev
```

En el host TrueNAS 26 validado, el dataset de referencia informa estas propiedades ZFS:

```text
acltype=posix
aclmode=discard
```

La documentación de TrueNAS describe el modo ACL del preset Generic como no aplicable en la UI porque Generic usa ACL POSIX; aun así, el audit del host registra la propiedad ZFS `aclmode` real y trata `discard` como el valor de referencia validado para Remote Dev.

El layout canónico de Remote Dev sigue usando directorios normales debajo de esa raíz, salvo que el administrador cree deliberadamente algún descendiente requerido como child dataset para snapshots, cuotas o replicación.

Los padres estructurales y workspaces usan sus modos iniciales documentados `0755`. Cada hoja canónica de estado privado pertenece a root (UID `0`), usa `0700` y, en el layout TrueNAS de referencia, su ACL efectiva debe ser una **ACL POSIX1E trivial** que contenga únicamente:

- propietario/root: `rwx`;
- grupo: sin acceso;
- otros: sin acceso;
- sin entradas de usuario/grupo nominales, máscara, default o heredadas.

La lista autoritativa de hojas privadas no se duplica aquí: procede de `scripts/lib/data_layout.py` y la comparten bootstrap, preflight y el audit de ACL.

## Por qué el preset Apps no es equivalente

Los datasets **Apps** de TrueNAS usan ACL NFSv4 con `aclmode=passthrough`. La validación en sistema real mostró que seguían existiendo ACE heredadas efectivas en las hojas privadas de Remote Dev aunque `ls -l` mostrase `0700`.

Por tanto, `0700` puede ser correcto como representación del modo POSIX y, aun así, otras identidades del host pueden conservar acceso efectivo mediante ACE NFSv4. TrueNAS 26 documenta una entrada adicional `MODIFY` para el grupo Apps (GID 568), y las ACL heredadas también pueden incluir principales built-in de administradores/usuarios o de servicios de directorio según el padre y el sistema. Los principales exactos observados en un host son evidencia, no una lista universal de permitidos o bloqueados.

Por eso Remote Dev **no** recomienda el preset Apps para su raíz Host Path simplemente por ejecutarse como una App.

## Diagnóstico ACL en el host

Ejecuta el audit desde la shell de TrueNAS usando el script de la **misma revisión fuente** que la imagen y las herramientas de layout desplegadas:

```bash
sudo python3 scripts/truenas-acl-audit.py \
  --root /mnt/Pool1/remote-dev \
  --include-antigravity
```

El audit es de solo lectura. Comprueba:

- que la raíz configurada sea exactamente el mountpoint de un dataset ZFS;
- `acltype` y `aclmode` de la raíz;
- propiedad root (UID `0`) de cada hoja privada canónica;
- modo `0700` en las hojas privadas canónicas;
- tipo `POSIX1E` devuelto por `filesystem.getacl`;
- `trivial=true`;
- únicamente entradas owner/group/other con los permisos efectivos esperados.

Una instalación de referencia correcta termina con:

```text
Remote Dev TrueNAS ACL audit: OK (Generic/POSIX private-state contract)
```

NFSv4, un propietario privado distinto de root, ACL POSIX no triviales, entradas nominales/default o modos más amplios generan warnings y un código de salida distinto de cero. La herramienta nunca modifica propietario, permisos ni ACL.

### Qué puede y qué no puede ver `Run diagnostics`

`remote-dev-doctor` se ejecuta **dentro** del contenedor aislado del agente. Ahora comprueba el modo POSIX de cada bind mount privado y avisa si un estado privado montado es más permisivo que `0700`.

No pretende determinar el tipo de ACL del dataset TrueNAS ni el ownership autoritativo del host. No damos al contenedor acceso a middleware/API de TrueNAS, a la raíz del host ni al socket del motor de contenedores solo para inspeccionar política ACL. Una ACE NFSv4 heredada del host puede requerir por tanto el audit del host aunque el contenedor vea `0700`.

La separación preserva el modelo de aislamiento:

- diagnostics del contenedor: regresiones de modo en los paths montados;
- audit en TrueNAS: comprobación autoritativa de ZFS, ownership y ACL efectiva.

## Instalaciones NFSv4 existentes

No conviertas en sitio una raíz poblada y no ejecutes `chmod`, `chown` o reescritura ACL recursivos como migración implícita. Ni bootstrap ni el arranque de contenedores deben realizar silenciosamente una migración de ACL/ownership del dataset. Bootstrap conserva los paths existentes que pertenecen al operador; el hardening de permisos del estado privado que ya pertenece al runtime sigue siendo un contrato de ejecución separado y no debe confundirse con una migración de ACL del host.

El modelo validado es **copia lateral + cutover verificado + rollback conservado**.

### 1. Parar Remote Dev e inventariar el origen

Para la copia/cutover final, detén la Custom App de TrueNAS. Haz inventario de tipos de objeto inesperados y hardlinks. Un árbol Remote Dev normal ya detenido debería contener directorios, archivos normales y symlinks. Si aparecen device nodes, FIFOs o sockets, revísalos antes de continuar.

### 2. Crear protección de rollback

Crea un snapshot del dataset original mediante WebUI/API soportada de TrueNAS y conserva además el dataset original intacto durante la migración.

### 3. Crear un dataset Generic nuevo

Crea un dataset hermano temporal, por ejemplo:

```text
Pool1/remote-dev-posix-migrate
```

Usa **Dataset Preset = Generic** y confirma que está vacío, con `acltype=posix` y `aclmode=discard`.

### 4. Copiar sin arrastrar las ACL NFSv4

La copia validada usó el modo archive de rsync sin flags de copia de ACL/xattr:

```bash
sudo rsync -a --numeric-ids --info=progress2,stats2 \
  /mnt/Pool1/remote-dev/ \
  /mnt/Pool1/remote-dev-posix-migrate/
```

No añadas `-A` ni `-X` al procedimiento validado: el objetivo es conservar contenido, symlinks, IDs de propietario/grupo, modos y timestamps sin trasplantar el antiguo modelo de ACL/metadatos de seguridad. El dataset validado no dependía de atributos extendidos arbitrarios. Si un despliegue depende deliberadamente de xattrs de proyectos o aplicaciones, detente y diseña un plan específico de conservación/verificación en lugar de añadir `-X` de forma global. Si el inventario previo encuentra archivos con hardlinks, revisa ese caso y añade `-H` deliberadamente; el dataset real usado para validar el procedimiento no tenía hardlinks.

Verifica el contenido de archivos antes de cambiar los modos de los directorios canónicos:

```bash
sudo rsync -a --numeric-ids --checksum --dry-run --itemize-changes \
  /mnt/Pool1/remote-dev/ \
  /mnt/Pool1/remote-dev-posix-migrate/
```

Sin salida significa que rsync no detecta diferencias de archivos/contenido bajo esas mismas semánticas de copia; no afirma que se hayan comparado las ACL/xattrs omitidas.

### 5. Normalizar solo los directorios canónicos

Aplica los modos documentados `0755`/`0700` únicamente a los directorios canónicos definidos por `scripts/lib/data_layout.py`. Nunca hagas un chmod recursivo sobre repositorios, entornos virtuales, cachés o contenido de proyectos del usuario.

Después ejecuta bootstrap, preflight y el audit ACL de la misma revisión contra la raíz temporal. Bootstrap debe indicar `no changes required`, preflight debe devolver `OK` y el audit debe terminar con el resultado Generic/POSIX correcto.

La migración real validada ya tenía las hojas privadas propiedad de root, por lo que no necesitó reescribir ownership. Si el audit detecta una hoja privada cuyo propietario no sea UID 0, detente y revisa ese path antes del cutover. No introduzcas un `chown` recursivo como remedio automático.

### 6. Confirmar que ningún proceso usa los datasets

Con la App todavía parada, consulta procesos y attachments de TrueNAS tanto para el origen como para el destino. No renombres mientras alguno esté en uso.

### 7. Hacer el cutover mediante rename reversible

El middleware de TrueNAS 26 probado exige `force=true` para renombrar datasets porque ese endpoint, de forma deliberada, no realiza comprobaciones de seguridad por sí mismo. Úsalo solo después de las comprobaciones explícitas de procesos/attachments anteriores.

Renombra primero el dataset antiguo a un nombre de backup y después el POSIX verificado al nombre canónico. Por ejemplo:

```text
Pool1/remote-dev                -> Pool1/remote-dev-nfsv4-backup
Pool1/remote-dev-posix-migrate  -> Pool1/remote-dev
```

Después del rename, vuelve a comprobar que `Pool1/remote-dev` es `posix/discard`, ejecuta preflight y audit ACL sobre `/mnt/Pool1/remote-dev` y solo entonces arranca la App.

### 8. Validar persistencia real tras el arranque

Confirma que cargan launcher y cada agente habilitado, que siguen presentes los proyectos y sesiones/conversaciones anteriores y que los bind mounts de los contenedores siguen usando `/mnt/Pool1/remote-dev/...`.

Ejecuta diagnostics dentro de los contenedores y repite el audit ACL en el host tras el arranque. Las escrituras de los procesos sobre el dataset nuevo no deben ensanchar ni volver no trivial la ACL del estado privado.

### 9. Mantener rollback hasta probar uso normal

No borres inmediatamente el dataset NFSv4 antiguo. Déjalo offline como origen de rollback hasta que la revisión exacta desplegada haya superado el audit ACL del host, diagnostics de los contenedores, comprobaciones de restart/recreation, reanudación de sesiones/conversaciones y al menos un ciclo normal de trabajo del operador sin necesitar rollback. La retención es una decisión del operador, no un temporizador automático.

Si hay que volver atrás, para Remote Dev antes de invertir los nombres de los datasets. No mezcles sin revisión las escrituras nuevas del lado POSIX de vuelta al backup NFSv4: eso es una reconciliación de datos independiente.

Cuando se completen esos gates, el dataset NFSv4 antiguo puede eliminarse deliberadamente mediante herramientas soportadas de TrueNAS. Decide por separado si conservar un snapshot u otra copia verificada según la política normal de backups del operador; este proyecto nunca borra automáticamente los datos de rollback.

## No objetivos deliberados

- Sin migración ACL automática desde bootstrap o arranque del contenedor.
- Sin normalización recursiva de permisos u ownership dentro de proyectos.
- Sin afirmar que la inspección de modo dentro del contenedor prueba la privacidad NFSv4 del host.
- Sin compartir `state` por SMB.
- El diseño de SMB/ACL para workspaces sigue separado en #71.
