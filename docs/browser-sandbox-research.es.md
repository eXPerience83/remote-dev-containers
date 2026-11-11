# Investigación y requisitos de seguridad: navegador MCP compartido

Estado: diseño y pruebas preparatorias para el PR #313; NO es una autorización de despliegue. Referencia: issue #179, que conserva el objetivo diferente de Playwright por proyecto con versiones de framework/navegador emparejadas.

## Decisión de distribución e integración

1. La imagen inmutable incluye un Chromium Headless Shell emparejado con la versión bloqueada de Playwright MCP, las bibliotecas Linux requeridas y un ejecutable de arranque común. No hay descargas al iniciar una sesión ni puertos de escucha: comunicación local por stdio.
2. El proveedor Codex incluido en la imagen puede declarar el servidor en el TOML privado de Codex. AGY NO se redistribuye: lo instala el operador mediante el gestor propietario existente desde Google; el lanzador de AGY puede preparar su archivo privado de MCP. Claude Code no se instala en este PR.
3. Los volúmenes privados del NAS se montan después de construir la imagen. La reconciliación conservadora antes de una sesión real es la manera apropiada de dar configuración de serie sin sobrescribir servidores personales, incluidos los deshabilitados. Los comandos pasivos no deben escribir estado.
4. El servidor MCP es gratuito y local (licencia Apache-2.0); no equivale al MCP remoto Context7 ni sustituye a los paquetes/lockfiles Playwright de cada repositorio. Documentar el tamaño adicional de la imagen y los avisos de todas las bibliotecas del navegador redistribuidas.

## Modelo de amenaza y límites

Se busca contener el proceso que renderiza páginas de terceros y el servidor MCP que lo controla, reduciendo el impacto de contenido web malicioso o vulnerabilidades de Chromium/Playwright. NO se pretende aislar a Codex/AGY del propio repositorio: esos agentes pueden ejecutar herramientas y poseen permisos más amplios por diseño. Las opciones de Playwright que restringen orígenes y acceso a archivos son defensas preventivas, no fronteras de seguridad. Desactivar WebMCP evita que páginas visitadas registren herramientas experimentales innecesarias; esto tampoco constituye un sandbox.

## Diseño de lanzador incorporado al PR (pendiente de aceptación real)

- **Proceso separado sin privilegios:** arrancar MCP/Chromium con un UID/GID dedicado sin acceso a /root ni /workspace. El proceso supervisor crea recursos mínimos con los permisos apropiados antes de cambiar UID, elimina grupos suplementarios y comprueba que los descendientes carecen de capacidades Linux efectivas. La configuración privada de los agentes y sus procesos no deben ejecutarse bajo ese UID. Verificar la política DAC, seccomp y NoNewPrivs del contenedor real; no añadir SYS_ADMIN, privileged, socket Docker ni abrir puertos.
- **Entorno explícito:** usar execve con un conjunto permitido de variables de sistema; no heredar tokens, claves, cabeceras, variables de provider, LD_*, NODE_OPTIONS, configuración de GitHub ni proxy autenticado. Establecer HOME y TMPDIR separados, más XDG_CACHE_HOME, XDG_CONFIG_HOME, XDG_DATA_HOME y XDG_RUNTIME_DIR cuando corresponda; todas dentro de un directorio efímero privado. Nunca imprimir el entorno ni los secretos en las pruebas.
- **Descriptor de archivos:** cerrar todos los FD no imprescindibles antes de aplicar Landlock/arrancar Node; preservar exclusivamente el transporte stdio MCP legítimo y un stderr controlado. Landlock NO revoca descriptores abiertos antes de la política. Verificar también /proc/<pid>/fd, /proc/<pid>/environ, /proc/self/fd, cwd, symlinks y socket UNIX.
- **Temporales privados:** el TMPDIR normal de Remote Dev apunta a /workspace/.remote-dev-tmp/tmp y no sirve si se bloquea /workspace. Proponer un directorio aleatorio 0700 en /run, verificado writable en los Compose de cada rol, con propietario del UID del navegador. La ejecución de binarios permanece en rutas inmutables (/opt, /usr); el /run noexec de AGY no debe impedir arrancar. Sin perfiles/cookies persistentes de serie. Limpiar temporales y procesos descendientes ante cierre, error, señal y cancelación; un simple exec sin supervisor no permite asegurar toda la limpieza.
- **Landlock:** política explícita de rutas y derechos que incluya solo ejecutables/bibliotecas/configuración inmutable, dispositivos mínimos y directorio efímero; permitir /proc únicamente en la medida indispensable. Aplicar restricciones al MCP ANTES de exec para herencia por todos sus hijos. Comprobar ABI y syscalls reales; fallar de forma visible, sin retroceso silencioso a ejecución sin Landlock. Revisar ABI v7 observado por AGY en TrueNAS, qué derechos soporta y los errores en rootfs read-only.
- **Red (riesgo conocido asumido para el alcance actual):** el navegador debe poder visitar servicios internos de la LAN, además de Internet. No se implementará una denegación global de localhost/LAN ni se exigirá rediseñar Compose o las redes de TrueNAS para aprobar este PR. Landlock controla algunas operaciones TCP por puerto, pero no discrimina la IP de destino; las listas de orígenes de Playwright no constituyen una frontera de seguridad. Se documenta explícitamente que el navegador y los agentes pueden alcanzar endpoints administrativos si son accesibles desde la red del contenedor. Esto no les concede automáticamente autorización administrativa, pero unas credenciales presentes o vulnerabilidades en esos endpoints aumentarían el impacto. No prometer aislamiento de red ni protección completa del plano de administración del NAS.
- **MCP y salida:** mantener stdio sin puertos nuevos, configuración de navegador aislado y WebMCP desactivado. No almacenar trazas, cookies, cabeceras ni capturas fuera del perfil efímero por defecto; las capturas devueltas por herramientas MCP pueden ser visibles para el agente, como es habitual.

## Matriz de aceptación obligatoria antes de fusionar

| Área | Prueba y criterio |
| --- | --- |
| Instalación | AMD64 y ARM64 (si se ofrece), Chromium y librerías incluidos; sin descargas al entrar |
| Configuración | Nueva y existente para Codex/AGY; no pisar MCP ajenos ni playwright del usuario; funcionamiento tras instalar AGY por separado |
| Iniciación MCP | Protocolo stdio: inicializar, listar herramientas, navegar por página de fixture local y cerrar; mismo resultado desde ambos agentes |
| Navegación | HTTP/HTTPS local, DOM/JS, consola, captura, peticiones/respuestas y WebSocket en fixtures sin credenciales |
| Privilegios | UID diferente a agentes, capacidades efectivas vacías y NoNewPrivs; fallar si no se pueden aplicar |
| Sistema de archivos | Denegar lectura/escritura de workspace y estados de agente, rutas alternativas, symlinks, proc y FD preabiertos |
| Entorno | Secretos sintéticos en entorno padre ausentes en MCP/Chromium; no registrar valores |
| Temporales | TMPDIR privado fuera del workspace, usable con read-only/noexec, cero cookies o perfiles residuales |
| Red | Verificar acceso a un servicio interno sintético (HTTP/WebSocket) y a HTTPS de prueba; documentar claramente que localhost/LAN no están bloqueados y no se garantiza separación de la administración TrueNAS |
| Ciclo de vida | Cerrar MCP, matar/recolectar árbol, retirar perfil en éxito, error, SIGTERM y cancelación; sin procesos huérfanos |
| Conservación | Sin cambios en seguridad del Compose existente salvo aceptación expresa, y gates de CI, notices, SBOM y Trivy verdes |

Las pruebas locales de CI deben ser sintéticas, sin sesiones autenticadas de terceros; la aceptación en TrueNAS ha de repetir las restricciones reales del despliegue. No presentar como probado algo que no se haya ejecutado.

## Resultados de investigación registrados

- La prueba previa de SOL en TrueNAS reportó Chromium/Playwright funcional con sandbox interno deshabilitado, librerías suministradas y Landlock. AGY reportó Landlock ABI v7 y cuatro riesgos: entorno heredado, FDs, TMPDIR dentro del workspace y acceso de red LAN/loopback.
- En un entorno local distinto de TrueNAS, una sonda de landlock_create_ruleset devolvió ENOSYS. No se puede considerar una validación funcional; probablemente existe bloqueo del sistema anfitrión o del entorno contenedor. Dejar la verificación a los agentes con acceso real.
- Codex usa ~/.codex/config.toml, tabla mcp_servers; AGY usa ~/.gemini/config/mcp_config.json, mapa mcpServers, comando local stdio y timeoutSeconds. Confirmado con documentación de proveedor.
- La imagen actual del PR supera compilación AMD64 y smoke de Chromium, **no** prueba aún MCP real con agentes ni la protección de procesos. Mantener draft/no fusionar.

## Referencias

- Playwright MCP v0.0.84: https://github.com/microsoft/playwright-mcp/blob/v0.0.84/README.md
- Playwright browser versions: https://playwright.dev/docs/browsers
- Antigravity CLI MCP: https://antigravity.google/docs/mcp?tab=cli
- Linux Landlock: https://docs.kernel.org/userspace-api/landlock.html
- PR de trabajo: https://github.com/eXPerience83/remote-dev-containers/pull/313

## Decisión de alcance: riesgo de red conocido

El operador considera el acceso a la red local parte del riesgo aceptable de este entorno de desarrollo. Es un **requisito funcional** poder probar proyectos y servicios internos desde Codex y AGY, tanto con el navegador como con herramientas CLI. No se añade una confirmación molesta en cada navegación ni se bloquea toda la LAN.

Esta aceptación **no significa** que una IA pueda administrar TrueNAS sin credenciales o permisos. Las restricciones actuales del contenedor (sin socket Docker, sin SYS_ADMIN/NET_ADMIN, raíz de solo lectura, montajes estrechos) reducen el control directo del host, pero un servicio administrativo accesible por red sigue siendo una superficie de ataque, especialmente si hubiera credenciales expuestas, una sesión autorizada o vulnerabilidades. Mantener autenticación y permisos mínimos en TrueNAS; no proporcionar tokens administrativos al agente; no almacenar cookies de su panel en el navegador del MCP. Un posible bloqueo de endpoints administrativos puede evaluarse como endurecimiento futuro separado, fuera de los requisitos de aceptación de este PR.

**Lo que sigue siendo bloqueante antes de activar por defecto:** que el proceso navegador/MCP no herede tokens del agente, no pueda leer su estado privado mediante rutas o descriptores heredados, tenga temporales correctos fuera de /workspace, aplique la separación de privilegios/Landlock verificable y cierre correctamente los procesos. La funcionalidad de navegar por LAN debe preservarse en esas pruebas.

## Implementación del supervisor, revisión y límites

El PR incluye el prototipo independiente `scripts/remote-dev-browser-sandbox.py`, ejecutado por `remote-dev-playwright-mcp` con el Python inmutable de la imagen. Cambia a UID/GID `61123`, elimina grupos y capacidades efectivas, aplica Landlock antes de ejecutar Node, crea HOME/TMPDIR/XDG aislados en `/run`, no hereda secretos ni FDs adicionales y crea un guardián independiente para limpiar grupo de procesos y estado si el cliente termina bruscamente. Requiere Landlock ABI >=5 y falla cerrado si falta. **No se ha recuperado el `launcher.py` original de Codex**, que está en `/workspace/testing/pr313-security-evidence/` de otra sesión; esta implementación debe validarse por separado con su matriz y con AGY real.

Las pruebas de CI incluyen una prueba de protocolo stdio HTTP/JS/WebSocket con permisos TrueNAS-like y `/run noexec`, más comprobaciones del contrato de entorno, rutas, FDs y guardián. La ejecución de CI no sustituye la aceptación operativa real. La prueba de Codex aportada anteriormente demuestra viabilidad de un prototipo, no la corrección automática de este nuevo código. **Riesgo residual:** Landlock ABI 7 no puede denegar de forma general sockets de dominio UNIX accesibles por DAC; `0777` puede seguir siendo alcanzable. No se ha añadido una prohibición de LAN por decisión expresa del operador.

## Prueba negativa de seguridad en contenedor

La prueba `browser-sandbox-runtime-probe.py` ejecuta **Node real con la misma transición de UID y Landlock** utilizada por Playwright MCP. Comprueba `EACCES/EPERM` al enumerar `/workspace`, `/root` y `/tmp`, acceso positivo a `/etc/passwd` y al directorio privado de `/run`, entorno saneado con secretos sintéticos, FD 99 deliberadamente heredable pero cerrado, UID/GID 61123, capacidades vacías y `NoNewPrivs=1`. Se ejecuta en el smoke normal y bajo restricciones similares a AGY (`/run noexec`). No se conecta a servicios administrativos ni maneja credenciales reales.

El guardián de limpieza **no comparte UID con Chromium**: se ejecuta como un pequeño proceso de confianza root con `NoNewPrivs`, entorno saneado, sin puertos ni secretos heredados y `PR_SET_DUMPABLE=0`; retiene los permisos que ya necesita el supervisor para terminar el árbol y limpiar directorios de cualquier propietario. Así evitamos que un Chromium comprometido pueda matar o depurar al guardián mediante identidad compartida. No aumenta los permisos de Compose. Este proceso privilegiado debe revisarse como código de confianza y sigue sujeto a las limitaciones generales de los agentes root.

## Guardian subreaper y cierre de grupos detached

La fuente de Playwright indica que el navegador se lanza con `detached: true` en plataformas no Windows, lo que crea **otro grupo de procesos**. Por eso no basta con `killpg(pid_node)` tras SIGKILL del supervisor. El guardián de confianza ahora es **padre directo de Node** y solicita `PR_SET_CHILD_SUBREAPER`: tras la salida de Node, los Chromium huérfanos (incluso con `setsid()`) se le reparentan. Recorre los hijos adoptados de `/proc/self/task/<pid>/children`, termina sus grupos y recolecta los procesos hasta que no queden hijos; entonces elimina el perfil efímero.

Este cambio no añade `SYS_ADMIN`, contenedores privilegiados ni acceso al socket Docker. En sistemas sin `/proc/.../children` o sin soporte `PR_SET_CHILD_SUBREAPER`, el guardián **no debe iniciar Node**. El test de ciclo de vida provoca `SIGKILL` del supervisor con Chromium ya abierto y verifica que desaparecen tanto el perfil como los procesos. No sustituye la aceptación con AGY propietario real en TrueNAS.

Referencia upstream: https://github.com/microsoft/playwright/blob/main/packages/utils/processLauncher.ts.

## Fijación de dependencias npm

El proyecto registra el grafo de producción en `config/playwright-package.json` y `config/playwright-package-lock.json`. El lockfile fue generado por un trabajo aislado de GitHub Actions con `@playwright/mcp@0.0.84` y sus tres entradas de paquetes (`@playwright/mcp`, `playwright`, `playwright-core`). Las integridades SHA-512 de Playwright y Playwright Core se cotejaron con el `package-lock.json` oficial de la etiqueta `microsoft/playwright-mcp@v0.0.84`. La compilación usa `npm ci --ignore-scripts --omit=dev`; `validate-playwright-lock.py` bloquea cambios de versión, integridad, origen del tarball o grafo no revisados.

**Límite pendiente:** el archivo ZIP de Chromium descargado por `playwright install --only-shell` no se verifica todavía contra un SHA-256 independiente, específico por arquitectura, conservado en el repositorio. El navegador no se descarga al iniciar el agente, pero el hecho de fijar su revisión de Playwright no supone por sí solo garantizar el contenido criptográfico del ZIP descargado durante la construcción. Se debe completar la comprobación del artefacto para cerrar esa observación de CodeRabbit.
