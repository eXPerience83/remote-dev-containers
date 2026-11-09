# Investigación y requisitos de seguridad: navegador MCP compartido

Estado: diseño y pruebas preparatorias para el PR #313; NO es una autorización de despliegue. Referencia: issue #179, que conserva el objetivo diferente de Playwright por proyecto con versiones de framework/navegador emparejadas.

## Decisión de distribución e integración

1. La imagen inmutable incluye un Chromium Headless Shell emparejado con la versión bloqueada de Playwright MCP, las bibliotecas Linux requeridas y un ejecutable de arranque común. No hay descargas al iniciar una sesión ni puertos de escucha: comunicación local por stdio.
2. El proveedor Codex incluido en la imagen puede declarar el servidor en el TOML privado de Codex. AGY NO se redistribuye: lo instala el operador mediante el gestor propietario existente desde Google; el lanzador de AGY puede preparar su archivo privado de MCP. Claude Code no se instala en este PR.
3. Los volúmenes privados del NAS se montan después de construir la imagen. La reconciliación conservadora antes de una sesión real es la manera apropiada de dar configuración de serie sin sobrescribir servidores personales, incluidos los deshabilitados. Los comandos pasivos no deben escribir estado.
4. El servidor MCP es gratuito y local (licencia Apache-2.0); no equivale al MCP remoto Context7 ni sustituye a los paquetes/lockfiles Playwright de cada repositorio. Documentar el tamaño adicional de la imagen y los avisos de todas las bibliotecas del navegador redistribuidas.

## Modelo de amenaza y límites

Se busca contener el proceso que renderiza páginas de terceros y el servidor MCP que lo controla, reduciendo el impacto de contenido web malicioso o vulnerabilidades de Chromium/Playwright. NO se pretende aislar a Codex/AGY del propio repositorio: esos agentes pueden ejecutar herramientas y poseen permisos más amplios por diseño. Las opciones de Playwright que restringen orígenes y acceso a archivos son defensas preventivas, no fronteras de seguridad. Desactivar WebMCP evita que páginas visitadas registren herramientas experimentales innecesarias; esto tampoco constituye un sandbox.

## Diseño propuesto del lanzador (no implementado)

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
