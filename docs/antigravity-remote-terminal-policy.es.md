# Antigravity CLI oficial en un terminal remoto privado — evidencias y decisión

**Revisado:** 14-11-2026 · **Código estudiado:** [main `7598562309b93cc67a8dbcd86db062207c195e91`](https://github.com/eXPerience83/remote-dev-containers/tree/7598562309b93cc67a8dbcd86db062207c195e91) · **Decisión del responsable:** conservar Antigravity opcional/experimental, registrada en [#53](https://github.com/eXPerience83/remote-dev-containers/issues/53). Es una **interpretación del proyecto**, no una autorización formal de Google ni un dictamen jurídico.

[English version](antigravity-remote-terminal-policy.md)

## Decisión y alcance

Se mantiene **el CLI oficial interactivo `agy`**, instalado a petición del usuario en el servicio aislado de Antigravity y utilizado mediante un terminal remoto privado. Sin redistribución, sin cliente alternativo del servicio y sin utilizar una cuenta de Antigravity para alimentar a Codex, Claude, OpenClaw u otro agente. Continúan vigentes la activación experimental, la separación de credenciales y los controles de integridad.

Esta decisión **no** avala crear un proxy de modelos, reenviar automáticamente prompts mediante `agy -p` desde otros agentes, rotar cuentas personales ni ofrecer acceso público/multiusuario.

## Evidencias oficiales y límites

| Fuente | Qué acredita | Qué NO acredita |
| --- | --- | --- |
| [Términos adicionales de Antigravity, §6](https://antigravity.google/terms) | Restringen el acceso al servicio mediante herramientas de terceros (ejemplo: OpenClaw + OAuth Antigravity) y contemplan suspensión de cuenta. | **No se limitan a prohibir redistribución.** No clasifican específicamente un emulador de terminal que muestra el CLI oficial. |
| [FAQ oficial](https://antigravity.google/docs/faq) | No soporta envolver `agy` como motor de aplicaciones/agentes externos con cuentas de consumo; distingue los scripts/CI directos `agy -p`. | No concede una excepción general a cualquier lanzador con menús. |
| [Configuración del CLI](https://antigravity.google/docs/settings?tab=cli) | Documenta explícitamente terminales SSH, `tmux` y `screen` para la interfaz interactiva. | No certifica por nombre nuestro frontend `ttyd`. |
| [Autenticación del CLI](https://antigravity.google/docs/install) | Admite flujos de autenticación al ejecutar el CLI en una máquina remota. | No autoriza reutilizar OAuth por otros clientes. |
| [Foro Google, 12–13 nov. 2026](https://discuss.ai.google.dev/t/tos-violation-appeal-request/199917) | Un usuario describe `agy` **interactivo, dentro de Docker y por SSH**, y una respuesta indica expresamente que ese modo está soportado. | El usuario recibió un bloqueo ToS; el foro no demuestra que se levantara ni constituye una modificación del contrato. |
| [Foro Google, PackStart, 28 oct. 2026](https://discuss.ai.google.dev/t/request-for-approval-free-desktop-app-that-brings-non-technical-users-to-gemini-with-their-own-google-plan/196378) | Se rechazó una aplicación de **otro asistente de IA** que utilizaba `agy` como motor, aunque empleaba el binario oficial sin extraer tokens. | Es una arquitectura distinta de teclear directamente en la TUI del proveedor. |

La diferencia es **el papel de la aplicación externa**, no si se emplea Docker o un navegador. Aun así, la amplitud del §6 deja un **riesgo contractual residual**, incluida la posibilidad de suspensión o cancelación de cuentas **Antigravity y/o Gemini CLI** según el [apartado 6](https://antigravity.google/terms) si Google considera prohibido el uso; no es correcto garantizar cumplimiento absoluto ni ausencia de suspensiones automáticas.

## Arquitectura real (auditoría estática)

```text
Navegador del usuario
   ↕ teclado / pantalla / tamaño / portapapeles
ttyd (WebSocket de terminal)
   ↕ pseudoterminal local
tmux
   ↕ entrada y salida de la sesión
agy oficial (interfaz interactiva)
   ↕ protocolo de servicio gestionado por Google
Antigravity / Google
```

`ttyd` no consume una API de modelos de Google; transporta **la entrada y salida del terminal**. **Las protecciones del terminal web son configurables**: `ALLOW_INSECURE_WEB=1` permite arrancar sin `WEB_PASSWORD` y `WEB_CHECK_ORIGIN=0` desactiva la comprobación de origen. Si falta alguna de esas protecciones, el acceso requiere controles independientes adecuados (por ejemplo, red privada protegida y pasarela autenticada); no debe afirmarse que el endpoint siempre aplica ambas. No es un visor completamente pasivo: recibe teclas, controla tamaño y muestra lo que produce `agy`, por lo que el endpoint local técnicamente puede ver los contenidos del terminal. **Solo `agy` gestiona la conexión a los servicios del proveedor.** Esta conclusión procede del código, no de una captura de paquetes de TrueNAS.

### Fuentes verificadas del repositorio (SHA fijo)

1. [`start-remote-dev-web.sh`](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/scripts/start-remote-dev-web.sh#L82-L127): inicia `ttyd --writable` con protección de acceso y comprobación de origen **según configuración**, y ejecuta `attach-remote-dev-tmux`, no con una URL de modelos Google.
2. [`attach-remote-dev-tmux.sh`](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/scripts/attach-remote-dev-tmux.sh#L24-L92): crea o adjunta una sesión `tmux` que contiene el menú o el agente.
3. [`remote-dev-menu.sh`](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/scripts/remote-dev-menu.sh#L973-L1024): selección de proyecto, instalación/actualización explícita, inicio/reanudación y ajustes **locales** del proceso.
4. [`run-antigravity.sh`: verificación del binario](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/scripts/run-antigravity.sh#L185-L205) y [ejecución de la TUI](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/scripts/run-antigravity.sh#L418-L463): verifica el binario y lo ejecuta como **TUI oficial** con entrada estándar interactiva; no usa a `agy` como backend de Codex.
5. [`installer.sh`](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/scripts/lib/antigravity-runtime/installer.sh#L1-L106) y [`commands.sh`](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/scripts/lib/antigravity-runtime/commands.sh#L15-L105): el usuario solicita la instalación; **el gestor Remote Dev sí descarga, valida y ejecuta el instalador oficial en nombre del usuario**. No es únicamente un enlace; el binario propietario queda fuera de las imágenes publicadas.
6. [`compose/truenas.yml`](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/compose/truenas.yml#L162-L239): volúmenes privados del rol Antigravity para ejecutable, estado y credenciales.
7. [`remote-dev-antigravity-oauth.py`: lectura del panel](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/scripts/remote-dev-antigravity-oauth.py#L95-L131), [observación](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/scripts/remote-dev-antigravity-oauth.py#L283-L299) y [visualización del popup](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/scripts/remote-dev-antigravity-oauth.py#L196-L216): observa temporalmente una **URL de autorización emitida por `agy`** en la pantalla y la muestra al usuario. No intercambia códigos por tokens ni copia credenciales a otro agente; sí hay un tratamiento local y limitado de esa URL.
8. [`remote-dev-antigravity-picker.py`](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/scripts/remote-dev-antigravity-picker.py#L27-L85): envía `/resume` a la interfaz oficial; no formula tareas para otro modelo.
9. [Frontend OSC 52](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/web/ttyd-osc52/README.md): mejora local de portapapeles, sin telemetría ni proxy del servicio.

## Futuro sustituto de ttyd

Los issues [#97](https://github.com/eXPerience83/remote-dev-containers/issues/97) y [#174](https://github.com/eXPerience83/remote-dev-containers/issues/174) deben conservar la distinción: **terminal WebSocket/PTY con E/S y reconexión**, nunca cliente alternativo de modelos, proxy de OAuth, motor de prompts para Codex ni telemetría externa. Cambiar el emulador de terminal sin alterar esa frontera **no equivale** a cambiar el cliente de Antigravity.

## Resolución del responsable — 14-11-2026

**Mantener Antigravity** como herramienta opcional, experimental y de uso manual del titular de la cuenta en un terminal privado. La decisión considera los términos generales, la FAQ, la documentación de SSH/`tmux`, la respuesta específica sobre Docker/SSH, el ejemplo contrario de PackStart y la auditoría del código.

- No redistribuir `agy` ni su instalador, conservar instalación explícita desde Google, seguridad/integridad, separación de estado y no afiliación (#96/#153).
- No convertir la cuenta de consumo en proveedor de IA para Codex u otros agentes y no crear proxies ni reutilizar OAuth.
- No desactivar la integración, forzar reinicios de sesión, sustituirla por Claude ni cambiar el modo de autenticación por esta decisión documental.
- Mantener el reconocimiento del **riesgo residual** de clasificación del frontend/lanzador y de posibles bloqueos de cuenta. No afirmar aprobación contractual de Google.
- Continuar la revisión periódica en [#53](https://github.com/eXPerience83/remote-dev-containers/issues/53), que **permanece abierto**. Los bloqueos independientes [#95](https://github.com/eXPerience83/remote-dev-containers/issues/95) (persistencia tras recreación) y [#320](https://github.com/eXPerience83/remote-dev-containers/issues/320) (seguridad Chromium) siguen pendientes. Este análisis no aprueba por sí solo `stable v0.3.0`.
- El campo `third_party/inventory.json.reviewed_on` registra revisión humana de los **componentes redistribuidos en imágenes** y no se modifica solo por esta decisión sobre uso del proveedor opcional.

**Posible consulta futura a Google:** preguntar específicamente si mostrar la interfaz interactiva oficial de `agy`, instalado por el usuario, mediante un terminal privado `ttyd/tmux` con menú de inicio/reanudación y enlace OAuth local, se equipara al SSH soportado. No presentar como obtenida una autorización que no existe.
