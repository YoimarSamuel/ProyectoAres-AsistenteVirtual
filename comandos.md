#  Comandos de ARES

Lista completa de cosas que le puedes decir a ARES (por voz o por texto). Las palabras clave están detectadas en `Ares.py` (diccionario `INTENCIONES`) y resueltas por los módulos correspondientes.

> **Tip:** ARES no necesita una sintaxis exacta. Mientras tu frase contenga alguna de las palabras clave de cada bloque, la intención se detecta. Puedes anteponer `oye`, `ares` o `por favor` sin problema.

---

##  Investigar / aprender (web + memoria global)

Primero busca en la base de conocimiento global; si no lo sabe, va a la web, lo evalúa con la mente crítica y te ofrece guardarlo.

- `busca <tema>`
- `investiga <tema>`
- `averigua <tema>`
- `qué es <tema>` / `quién es <tema>`
- `dime sobre <tema>`
- `explícame <tema>` / `explicame <tema>`
- `qué significa <tema>`

**Confirmación tras una búsqueda:** ARES responde con el resultado y pregunta `¿Lo guardo?`. Responde con:
- Sí: `sí`, `claro`, `dale`, `ok`, `vale`, `hazlo`, `adelante`, `obvio`, `sip`
- No: `no`, `nop`, `negativo`, `déjalo`, `olvídalo`, `mejor no`

---

##  Personalización / onboarding

Inicia un cuestionario para que ARES te conozca (nombre, tono preferido, ciudad, ocupación, hobbies, gustos, alergias).

- `aprende sobre mí`
- `configúrame` / `personalízate`
- `quiero contarte sobre mí`
- `conóceme`
- `preséntate conmigo`

Durante el onboarding puedes **cancelar** diciendo `no`, `cancela` o `cancelar`.

**Tonos válidos** (cuando lo pregunte): `tranquilo`, `balanceado`, `analítico`, `directo`.

---

##  Datos personales

Solo accede a tu base de datos privada (cifrada).

- `quién soy`
- `cómo me llamo`
- `qué sabes de mí`
- `mis datos`
- `mi historial`

---

##  Saludo y charla casual

**Saludo:**
- `hola`, `buenas`, `buenos días`, `buenas tardes`, `buenas noches`

**Charla:**
- `cómo estás`, `qué tal`, `qué cuentas`, `qué haces`
- `gracias`, `muchas gracias`, `te quiero`
- `perdón`, `lo siento`
- `adiós`, `chao`, `chau`, `bye`, `nos vemos`, `hasta luego`
- `jaja`, `jeje`, `ok`, `vale`

---

##  Hora y fecha

- `qué hora es` / `dime la hora`
- `qué día es hoy` / `qué fecha es`
- `fecha de hoy`

---

##  Clima

- `clima` / `temperatura`
- `qué tiempo hace`
- `está lloviendo`
- `hace frío` / `hace calor`
- `pronóstico`
- `clima en <ciudad>` / `tiempo de <ciudad>`

---

##  Matemáticas

Resuelve operaciones en local (módulo `Matematicas.py`).

- `calcula <expresión>` / `calcúlame <expresión>`
- `cuánto es <expresión>` / `cuánto da <expresión>`
- `resuelve <expresión>`
- `el resultado de <expresión>`
- `raíz cuadrada de <n>`
- `factorial de <n>`
- `logaritmo de <n>`
- `<n> elevado a <m>` / `<n> al cuadrado` / `<n> al cubo`
- `<n> por ciento de <m>`

---

##  Abrir aplicaciones

ARES busca en PATH, en el menú inicio de Windows y, como último recurso, delega al shell.

- `abre <app>` / `ejecuta <app>` / `lanza <app>` / `inicia <app>` / `corre <app>`

**Atajos reconocidos:**
- `abre terminal` / `abre cmd` / `abre powershell`
- `abre vscode` / `abre vs code` / `abre código`
- `abre navegador` / `abre chrome` / `abre browser` (abre Google)

Cualquier nombre de app instalada (Spotify, Discord, Notepad, Explorador, etc.) funciona si está en el menú inicio.

---

##  Abrir un proyecto en un editor

Detecta la carpeta del proyecto por nombre coloquial (busca en `~/Downloads`, `~/Documents`, `~/Desktop`, `~/Projects`, `~/Proyectos`, `~/source/repos`, `~/code`, `~/dev`) y la abre en el editor elegido. Por defecto: VS Code.

- `abre el proyecto <nombre>`
- `abre el proyecto <nombre> en vs code`
- `abre el proyecto <nombre> en cursor`
- `abre el proyecto <nombre> en windsurf`
- `abre el proyecto <nombre> en sublime`
- `abre la carpeta del proyecto <nombre>`
- `abre el repositorio <nombre>` / `abre el repo <nombre>`
- `abre el directorio <nombre>` / `abre el workspace <nombre>`
- `abre el proyecto <nombre> en una nueva ventana`
- `abre el proyecto C:\dev\foo` (acepta también rutas absolutas)

> Tras abrirlo, ARES recuerda ese proyecto como activo, así puedes seguir con `con copilot escribe …` sin volver a nombrarlo.

---

##  Editor de archivos (sin pyautogui, vía CLI)

Editores soportados: `visual` / `vscode` / `vs code` / `code`, `cursor`, `windsurf`, `sublime`, `notepad++`, `notepad`.

**Crear archivo:**
- `crea archivo <nombre>` / `crea un archivo <nombre>` / `nuevo archivo <nombre>`
- `crea archivo <nombre> con <contenido>`
- `crea archivo <nombre> con: <contenido>`
- `crea archivo <nombre> que contenga <contenido>`

**Crear y abrir en un editor:**
- `abre visual y crea un archivo saludo.py con print("Hola mundo")`
- `abre vscode y crea archivo notas.txt`

**Escribir/agregar a un archivo:**
- `escribe <contenido> en el archivo <nombre>`
- `escribe <contenido> en archivo <nombre>`
- `agrega <contenido> al archivo <nombre>`
- `añade <contenido> al archivo <nombre>`
- `inserta <contenido> en <nombre>`

**Solo abrir editor:**
- `abre visual` / `abre cursor` / `abre windsurf` / `abre sublime` / `abre notepad`
- `abre <editor> en <ruta>` (p. ej. `abre cursor en C:\proyectos\miapp`)

**Borrador rápido:**
- `abre visual y escribe <contenido>` (genera un `borrador_<HHMMSS>.py`)

> Si no especificas ruta absoluta, ARES guarda los archivos en `~/ARES_workspace`.

---

##  Delegar a IAs de desarrollo

Inyecta una instrucción en el chat de la IA elegida. Para Copilot / VS Code, el flujo es completamente automatizado: abre el proyecto, abre Copilot Chat, pega la petición y la envía.

**IAs soportadas:** `copilot`, `kiro`, `claude code` / `claude-code`, `cursor`, `windsurf`, `antigravity`, `vscode` / `visual`.

**Activadores:**
- `dile a <ia> que <instrucción>`
- `pídele a <ia> que <instrucción>`
- `<ia> escribe <instrucción>`
- `escribe en el chat de <ia>: <instrucción>`
- `con copilot escribe <instrucción>`
- `abre el chat de <ia> y escribe <instrucción>`
- `manda al chat: <instrucción>`

**Crear módulo nuevo (ruta Copilot):**
- `crea un nuevo módulo llamado <Nombre.py>`
- `crea un módulo llamado <Nombre> en el proyecto <Proyecto>`
- `crea un nuevo archivo en el proyecto <Proyecto>`
- `que crees un nuevo módulo llamado <Nombre>`

**Apuntar a un proyecto / módulo concreto:**
- `abre vs code en el proyecto Ares y en copilot escribe <instrucción>`
- `en el módulo ejemplo.py con copilot escribe <instrucción>`
- `abre el proyecto (nombre del proyecto - carpeta) en vs code`

> Para Cursor / Windsurf, ARES deja la petición en `~/ARES_workspace/_peticion_<ia>.md` y la copia al portapapeles. Solo abre el chat (`Ctrl+Alt+I` para Copilot) y pega con `Ctrl+V`.

---

##  Aceptar / rechazar cambios de Copilot (Keep / Undo)

Cuando Copilot Chat termina una edición aparece la barra `1 file changed [Keep] [Undo]`. ARES la pulsa por ti.

**Aceptar (Keep):**
- `dale siguiente`
- `siguiente`
- `dale al keep` / `dale keep`
- `presiona keep` / `click en keep` / `clickea keep`
- `acepta los cambios` / `acepta el cambio`
- `aprueba los cambios`
- `mantén los cambios`
- `guarda los cambios de copilot`

**Rechazar (Undo):**
- `dale al undo` / `presiona undo`
- `rechaza los cambios` / `rechaza el cambio`
- `descarta los cambios`
- `deshaz los cambios`

**Cómo lo hace, en orden:**
1. **Paleta de comandos:** ejecuta `Chat: Keep All Edits` o `Chat: Undo Edits`.
2. **Plantilla PNG:** si dejaste una captura del botón en `~/.ares/templates/copilot_keep.png` (o `copilot_undo.png`), la localiza con `pyautogui` y hace clic.
3. **OCR:** si tienes `pytesseract` + `tesseract` instalado, busca la palabra "Keep"/"Undo" en pantalla y clica.

> Si la paleta no encuentra el comando en tu versión de VS Code, ARES intenta automáticamente con plantilla y OCR. Lo más fiable es dejar la captura del botón en `~/.ares/templates/`.

---

##  WhatsApp

**Enviar mensaje:**
- `manda whatsapp a <nombre> diciendo <mensaje>`
- `envía whatsapp a <nombre> que <mensaje>`
- `mensaje a <nombre>: <mensaje>`
- `mándale a <nombre> que <mensaje>`
- `manda whatsapp a +573001234567 diciendo <mensaje>`

**Guardar contacto:**
- `guarda el contacto <nombre> +573001234567`
- `guarda el contacto whatsapp <nombre> <número>`

**Reenviar último mensaje:**
- `envía el mensaje` / `envíalo` / `mándalo` / `reenvíalo`

---

##  Facebook / Messenger

- `abre facebook` / `abre messenger`
- `manda mensaje a facebook a <persona> diciendo <mensaje>`
- `mensaje a <persona> en messenger: <mensaje>`

---

##  YouTube / música

- `pon <canción>` / `reproduce <canción>`
- `pon la canción <nombre>`
- `pon música de <artista>`
- `youtube <búsqueda>`

---

##  Archivos del sistema

- `abre archivo <ruta>` / `abre el archivo <ruta>`
- `elimina <ruta>` / `borra <ruta>`
- `edita <ruta>`

---

##  Control / detener

Detiene la voz (TTS) y cancela seguimientos pendientes.

- `detente`
- `para`
- `calla` / `cállate`
- `silencio`

---

##  Seguimientos conversacionales

ARES recuerda contexto entre turnos:

- Si te ofreció buscar algo (`¿Lo busco?`) y dices **sí** → lo busca.
- Si encontró algo y pregunta `¿Lo guardo?`:
  - **sí** → guarda principal + fragmentos atómicos en memoria global.
  - **no** → lo descarta.
- Durante el onboarding, cualquier respuesta se interpreta como contestación a la pregunta actual. Di `cancela` o `no` para abortar.
- En WhatsApp, ARES recuerda el último envío para `envíalo` / `reenvíalo`.
- En Copilot, ARES recuerda el último proyecto abierto. Puedes decir `ahora con copilot escribe <…>` sin volver a nombrar el proyecto.

---

##  Tonos de respuesta

Configurables vía onboarding (`personalízate`) o en el perfil. Afectan la longitud y el estilo de las respuestas:

| Tono | Estilo |
|---|---|
| `tranquilo` | Voz pausada, cercana, frases cortas |
| `balanceado` | Directo y profesional, máx. 2 frases (default) |
| `analítico` | Precisión técnica, datos y razonamiento breve |
| `directo` | Una sola frase, sin adornos |

---

## ℹ Notas finales

- Todas las interacciones se guardan cifradas en tu base privada.
- ARES **no depende de ningún LLM externo** para entender intenciones (PLN puro en `PLNOptimizado.py`).
- La mente crítica (`MenteCritica.py`) filtra resultados antes de proponer guardarlos.
- Si una intención no se detecta, ARES busca en la memoria global con el tema normalizado y, si no lo sabe, te ofrece investigarlo.
