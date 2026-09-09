# Baseline del sandbox de terminal de Antigravity

Esta página registra la posición soportada de Remote Dev respecto al sandbox de terminal del proveedor de Antigravity en el despliegue endurecido actual de TrueNAS/Docker.

## Frontera soportada

Remote Dev **no** fuerza ni gestiona el sandbox de terminal del proveedor de Antigravity en la ruta soportada de TrueNAS. La frontera soportada de aislamiento del servicio es el contenedor exterior endurecido del rol Antigravity junto con la frontera de proyecto/Git seleccionada.

Esto es independiente de la política de aprobaciones de Antigravity. Los avisos de aprobación y el funcionamiento autónomo controlan si Antigravity pregunta antes de usar herramientas; no son un sandbox de sistema de archivos ni de kernel. El issue #159 es el propietario del comportamiento de aprobaciones/autonomía.

## Evidencia en TrueNAS — 2026-09-09

Se realizó una prueba controlada y desechable con Antigravity CLI **1.1.27** dentro del servicio Antigravity endurecido existente. La prueba **no** cambió Compose, capabilities, seccomp, sysctls, mounts ni ajustes persistentes de permisos.

El contenedor exterior mostró:

```text
NoNewPrivs: 1
Seccomp: 2
Seccomp_filters: 2
```

El kernel exponía los user namespaces como habilitados:

```text
kernel.unprivileged_userns_clone = 1
user.max_user_namespaces = 62105
```

pero una prueba efectiva desde dentro del contenedor falló:

```text
unshare -Ur true
unshare: unshare failed: Operation not permitted
```

Antigravity 1.1.27 expone `--sandbox` como opción de sandbox de terminal limitada al lanzamiento. El lanzamiento desechable exacto fue:

```text
REMOTE_DEV_PROJECT=agy-sandbox-test run-antigravity --sandbox
```

La interfaz de Antigravity arrancó correctamente. Sin embargo, en la primera invocación de una herramienta de terminal, Antigravity solicitó un **sandbox bypass** explícito y advirtió de que el comando se ejecutaría fuera del sandbox con acceso completo a red y disco. Se rechazó el bypass.

Una petición posterior para ejecutar únicamente `pwd` dentro del sandbox falló con:

```text
Encountered error in tool execution: fork/exec /root/.local/bin/agy: operation not permitted
```

No se persistió ningún permiso de bypass y el proyecto Git desechable se eliminó después de la prueba.

## Decisión

Para el baseline soportado actual de TrueNAS/Docker:

- los lanzamientos normales de Remote Dev no añaden `--sandbox`;
- Remote Dev no exige ni gestiona `enableTerminalSandbox`;
- el modo autónomo de aprobaciones no debe depender de `proceed-in-sandbox` ni de sandbox bypass;
- Remote Dev no añadirá `privileged`, `SYS_ADMIN`, perfiles unconfined, namespaces del host ni debilitamientos similares únicamente para hacer funcionar el sandbox anidado del proveedor;
- el contenedor exterior endurecido del rol sigue siendo la frontera soportada de aislamiento del servicio;
- la frontera de proyecto/Git completada en #213 sigue siendo una frontera independiente de seguridad de proyectos dentro del mismo rol y no es aislamiento del sistema de archivos entre proyectos hermanos.

Esta evidencia es específica de versión: establece el resultado para Antigravity CLI 1.1.27 bajo el despliegue endurecido probado. No afirma que todas las versiones futuras del proveedor o cualquier otro perfil de contenedor se comporten igual.

## Reconsideración futura

El sandbox anidado de Antigravity no forma parte del roadmap/baseline actual. Cualquier reconsideración futura debe ser una decisión de seguridad específica que vuelva a probar la versión exacta admitida del proveedor en TrueNAS con el mismo perfil de endurecimiento exterior y demuestre que no requiere debilitar esa frontera.

Véase también:

- `docs/security.md`
- `docs/architecture.md`
- issue #215 — propiedad/reconciliación de la documentación
- issue #159 — modo autónomo/aprobaciones de Antigravity
- issue #213 / PR #214 — frontera Git de la colección de proyectos
- issue #36 — decisión de Codex sin Bubblewrap
