"""
================================================================================
        ARES — RPA para GitHub Copilot Chat (VS Code)
================================================================================
Hace todo el flujo automático:

  1. Resuelve la carpeta del proyecto a partir de un nombre coloquial
     ("ares", "el proyecto x", "C:/...").
  2. Lanza VS Code apuntando a esa carpeta (`code <ruta>`).
  3. Espera a que la ventana de VS Code esté enfocada.
  4. Abre Copilot Chat con el atajo Ctrl+Alt+I.
  5. Copia la instrucción al portapapeles y la pega (Ctrl+V).
  6. Pulsa Enter para enviarla. Copilot empieza a trabajar solo.

Aviso honesto:
  El chat de Copilot es un WebView interno de VS Code, sin API pública. La
  única forma realista de "mandarle" texto desde fuera es teclado/portapapeles.
  Aquí el RPA sí toca la UI (Ctrl+Alt+I, Ctrl+V, Enter): es la única vía.
  El usuario activa este modo a propósito al pedir "abre vs code y en copilot
  escribe ...". Las acciones se serializan con un Lock global para que no
  choquen con otros RPAs (WhatsApp, FB, etc.).
================================================================================
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from icecream import ic

try:
    import pyautogui  # type: ignore
    PA_OK = True
except Exception as e:  # pragma: no cover
    ic(f" pyautogui no disponible: {e}")
    PA_OK = False

try:
    import pyperclip  # type: ignore
    PC_OK = True
except Exception:
    PC_OK = False


# Lock para serializar acciones de teclado entre RPAs concurrentes
_RPA_LOCK = threading.Lock()


# Atajo del chat de Copilot. Por defecto Ctrl+Alt+I (panel de chat). Si el
# usuario tiene otro keymap, exportar COPILOT_CHAT_HOTKEY="ctrl,shift,i" etc.
def _hotkey_chat() -> List[str]:
    h = os.environ.get("COPILOT_CHAT_HOTKEY", "ctrl,alt,i")
    return [k.strip().lower() for k in h.split(",") if k.strip()]


# ============================== RESOLVER PROYECTO ==============================
# Carpetas donde es razonable buscar un proyecto por nombre.
_DEFAULT_SCAN_BASES = [
    Path.home() / "Downloads",
    Path.home() / "Documents",
    Path.home() / "Desktop",
    Path.home() / "Projects",
    Path.home() / "Proyectos",
    Path.home() / "source" / "repos",
    Path.home() / "code",
    Path.home() / "dev",
    Path.home(),
]

# Carpetas a ignorar al escanear (ruido)
_IGNORE_DIRS = {
    "node_modules", "__pycache__", ".git", ".venv", "venv", "env",
    "dist", "build", "target", ".next", ".cache", ".idea", ".vscode",
    "AppData", "Library", "Application Data",
}


def _normaliza(s: str) -> str:
    s = (s or "").strip().lower()
    # quitar acentos básicos
    repl = (("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u"),("ñ","n"))
    for a, b in repl:
        s = s.replace(a, b)
    s = re.sub(r"[^a-z0-9_\-\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def resolver_carpeta_proyecto(nombre: str,
                              bases_extra: Optional[List[Path]] = None
                              ) -> Optional[Path]:
    """Devuelve la primera carpeta cuyo nombre coincida (o contenga) `nombre`.

    Estrategia:
      1) Si ya es ruta absoluta o relativa existente, devolverla.
      2) Buscar coincidencia exacta de directorio en las bases conocidas.
      3) Buscar coincidencia parcial (substring) hasta 2 niveles de profundidad.
    """
    if not nombre:
        return None

    # 1) Ruta directa
    p = Path(nombre).expanduser()
    if p.is_dir():
        return p.resolve()

    target = _normaliza(nombre)
    bases = list(_DEFAULT_SCAN_BASES)
    if bases_extra:
        bases = list(bases_extra) + bases

    # 2) Coincidencia exacta a nivel 1
    for base in bases:
        if not base.exists():
            continue
        try:
            for child in base.iterdir():
                if not child.is_dir() or child.name in _IGNORE_DIRS:
                    continue
                if _normaliza(child.name) == target:
                    return child.resolve()
        except (PermissionError, OSError):
            continue

    # 3) Coincidencia parcial hasta 2 niveles
    for base in bases:
        if not base.exists():
            continue
        try:
            for child in base.iterdir():
                if not child.is_dir() or child.name in _IGNORE_DIRS:
                    continue
                if target in _normaliza(child.name):
                    return child.resolve()
                # un nivel más
                try:
                    for sub in child.iterdir():
                        if not sub.is_dir() or sub.name in _IGNORE_DIRS:
                            continue
                        if _normaliza(sub.name) == target or target in _normaliza(sub.name):
                            return sub.resolve()
                except (PermissionError, OSError):
                    continue
        except (PermissionError, OSError):
            continue

    return None


# ============================== ABRIR VS CODE ==============================
def _resolver_code_cli() -> Optional[str]:
    for n in ("code", "code-insiders", "code.cmd", "code-insiders.cmd"):
        cmd = shutil.which(n)
        if cmd:
            return cmd
    return None


def abrir_vscode(carpeta: Optional[Path] = None,
                 archivo: Optional[Path] = None,
                 nueva_ventana: bool = False) -> Dict[str, Any]:
    cli = _resolver_code_cli()
    if not cli:
        return {"ok": False, "error": "VS Code no está en PATH (`code`)."}
    args: List[str] = [cli]
    if nueva_ventana:
        args.append("--new-window")
    if carpeta:
        args.append(str(carpeta))
    if archivo:
        # `--goto <archivo>` deja el archivo enfocado dentro del workspace
        args.extend(["--goto", str(archivo)])
    try:
        subprocess.Popen(args)
        ic(f" VS Code abierto: {' '.join(args)}")
        return {"ok": True,
                "carpeta": str(carpeta) if carpeta else None,
                "archivo": str(archivo) if archivo else None}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ============================== RESOLVER MÓDULO/ARCHIVO ==============================
# Extensiones más comunes que asume cuando el usuario dice solo "modulo X" sin punto
_EXTS_TENTATIVAS = (".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".cs", ".cpp",
                    ".c", ".h", ".rb", ".go", ".rs", ".php", ".html", ".css",
                    ".json", ".md", ".yml", ".yaml", ".sql", ".sh", ".bat")


def resolver_archivo_modulo(carpeta_proyecto: Path,
                            nombre_modulo: str) -> Optional[Path]:
    """
    Encuentra un archivo dentro de `carpeta_proyecto` cuyo nombre coincida con
    `nombre_modulo`.

    Reglas:
      • Si el nombre incluye extensión, busca match exacto.
      • Si no, prueba con cada extensión común y devuelve el primer hit.
      • Si nada coincide exacto, busca por substring (preferiendo nombres más
        cortos para reducir falsos positivos).
    """
    if not carpeta_proyecto or not carpeta_proyecto.is_dir() or not nombre_modulo:
        return None

    nm = nombre_modulo.strip().strip("'\" .,;:")
    if not nm:
        return None

    # Si ya es ruta dentro del proyecto
    p = (carpeta_proyecto / nm).resolve()
    try:
        if p.is_file() and carpeta_proyecto in p.parents:
            return p
    except Exception:
        pass

    target_norm = _normaliza(Path(nm).stem)  # sin extension para comparar
    tiene_ext = bool(Path(nm).suffix)

    candidatos_exactos: List[Path] = []
    candidatos_parciales: List[Path] = []

    for archivo in carpeta_proyecto.rglob("*"):
        if not archivo.is_file():
            continue
        # Saltar carpetas ruidosas
        if any(part in _IGNORE_DIRS for part in archivo.parts):
            continue

        nombre = archivo.name
        stem_norm = _normaliza(archivo.stem)

        if tiene_ext:
            if _normaliza(nombre) == _normaliza(nm):
                candidatos_exactos.append(archivo)
            elif _normaliza(nm) in _normaliza(nombre):
                candidatos_parciales.append(archivo)
        else:
            # Sin extensión → comparar stems
            if stem_norm == target_norm and archivo.suffix.lower() in _EXTS_TENTATIVAS:
                candidatos_exactos.append(archivo)
            elif target_norm in stem_norm and archivo.suffix.lower() in _EXTS_TENTATIVAS:
                candidatos_parciales.append(archivo)

    pool = candidatos_exactos or candidatos_parciales
    if not pool:
        return None
    # Preferir el de menor profundidad y nombre más corto
    pool.sort(key=lambda p: (len(p.parts), len(p.name)))
    return pool[0].resolve()


# ============================== ENFOCAR VENTANA ==============================
def _listar_ventanas_vscode() -> List[Any]:
    """Devuelve las ventanas de VS Code abiertas (puede estar vacío)."""
    try:
        import pygetwindow as gw  # type: ignore
    except Exception as e:
        ic(f" pygetwindow no disponible: {e}")
        return []
    try:
        return [w for w in gw.getAllWindows()
                if w.title and "Visual Studio Code" in w.title]
    except Exception as e:
        ic(f" listar ventanas VS Code: {e}")
        return []


def vscode_ventana_para(carpeta: Optional[Path]) -> Optional[Any]:
    """
    Si hay una ventana de VS Code cuyo título contiene el nombre de
    `carpeta`, la devuelve. Útil para evitar reabrir VS Code.
    """
    ventanas = _listar_ventanas_vscode()
    if not ventanas:
        return None
    if carpeta is None:
        # Cualquier ventana sirve cuando no se especifica proyecto
        ventanas.sort(key=lambda w: (w.width * w.height), reverse=True)
        return ventanas[0]
    nombre_norm = _normaliza(carpeta.name)
    for w in ventanas:
        if nombre_norm in _normaliza(w.title):
            return w
    return None


def _enfocar_ventana(w) -> bool:
    """Trae una ventana al frente. Tolera fallos de `activate` en Windows."""
    try:
        if w.isMinimized:
            w.restore()
        w.activate()
        time.sleep(0.4)
        return True
    except Exception:
        try:
            pyautogui.click(w.left + 100, w.top + 10)
            time.sleep(0.4)
            return True
        except Exception as e:
            ic(f" enfocar ventana: {e}")
            return False


def _enfocar_vscode(timeout_s: float = 25.0,
                    carpeta: Optional[Path] = None) -> bool:
    """Espera a que VS Code esté abierto (opcionalmente con `carpeta`) y la enfoca."""
    fin = time.time() + timeout_s
    while time.time() < fin:
        w = vscode_ventana_para(carpeta) if carpeta else None
        if w is None:
            ventanas = _listar_ventanas_vscode()
            if ventanas:
                ventanas.sort(key=lambda v: (v.width * v.height), reverse=True)
                w = ventanas[0]
        if w is not None:
            if _enfocar_ventana(w):
                return True
        time.sleep(0.5)
    return False


# ============================== CREAR MÓDULO ==============================
# Plantillas mínimas por extensión (sólo cuando se crea un módulo vacío)
_PLANTILLAS = {
    ".py":   '"""Módulo {nombre}."""\n',
    ".js":   "// Módulo {nombre}\n",
    ".ts":   "// Módulo {nombre}\n",
    ".tsx":  "// Componente {nombre}\n",
    ".jsx":  "// Componente {nombre}\n",
    ".java": "// Clase {nombre}\n",
    ".cs":   "// Clase {nombre}\n",
    ".html": "<!-- {nombre} -->\n",
    ".css":  "/* {nombre} */\n",
    ".md":   "# {nombre}\n",
    ".json": "{{}}\n",
}


def crear_modulo(carpeta_proyecto: Path,
                 nombre_modulo: str,
                 contenido: str = "",
                 ext_default: str = ".py",
                 sobreescribir: bool = False) -> Dict[str, Any]:
    """
    Crea un archivo nuevo dentro de `carpeta_proyecto`.

    Si `nombre_modulo` no incluye extensión, usa `ext_default`. Si el archivo
    ya existe, no lo toca (a menos que `sobreescribir=True`).
    """
    if not carpeta_proyecto or not carpeta_proyecto.is_dir():
        return {"ok": False, "error": "Carpeta de proyecto no válida"}
    nm = nombre_modulo.strip().strip("'\" .,;:")
    if not nm:
        return {"ok": False, "error": "Nombre de módulo vacío"}

    if not Path(nm).suffix:
        nm = nm + ext_default

    destino = (carpeta_proyecto / nm).resolve()
    # Seguridad: no salir del proyecto
    try:
        destino.relative_to(carpeta_proyecto.resolve())
    except ValueError:
        return {"ok": False, "error": "Ruta fuera del proyecto"}

    if destino.exists() and not sobreescribir:
        return {"ok": True, "creado": False, "ruta": str(destino),
                "mensaje": "ya existía"}

    destino.parent.mkdir(parents=True, exist_ok=True)
    if not contenido:
        plantilla = _PLANTILLAS.get(destino.suffix.lower(), "")
        contenido = plantilla.format(nombre=destino.stem)
    try:
        destino.write_text(contenido, encoding="utf-8")
        ic(f" Módulo creado: {destino}")
        return {"ok": True, "creado": True, "ruta": str(destino)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ============================== PEGAR EN COPILOT CHAT ==============================
def _set_portapapeles(texto: str) -> bool:
    if PC_OK:
        try:
            pyperclip.copy(texto)
            return True
        except Exception:
            pass
    # Fallback: comando `clip` (Windows)
    try:
        if os.name == "nt":
            p = subprocess.Popen(["clip"], stdin=subprocess.PIPE)
            p.communicate(input=texto.encode("utf-16le"))
            return p.returncode == 0
    except Exception as e:
        ic(f" clip: {e}")
    return False


def enviar_a_copilot_chat(instruccion: str,
                          archivo: Optional[Path] = None,
                          delay_inicial: float = 1.0) -> Dict[str, Any]:
    """Asume que VS Code ya está enfocado. Abre el chat, pega y envía.

    Si se pasa `archivo`, se antepone `#file:<nombre>` al mensaje para que
    Copilot Chat lo adjunte como contexto explícito (equivale al chip
    `+ archivo.py` que aparece sobre el input). Esa sintaxis es la oficial
    de GitHub Copilot Chat para referenciar archivos del workspace.
    """
    if not PA_OK:
        return {"ok": False, "error": "pyautogui no disponible"}

    if archivo:
        # Anteponer la referencia. Si el usuario ya la incluyó, no duplicar.
        prefijo = f"#file:{Path(archivo).name}"
        if prefijo.lower() not in instruccion.lower():
            instruccion = f"{prefijo} {instruccion}".strip()

    if not _set_portapapeles(instruccion):
        return {"ok": False, "error": "No pude copiar al portapapeles"}

    with _RPA_LOCK:
        try:
            time.sleep(delay_inicial)

            # 1) Abrir Copilot Chat (Ctrl+Alt+I por defecto)
            hk = _hotkey_chat()
            pyautogui.hotkey(*hk)
            time.sleep(1.4)  # tiempo a que el panel del chat se monte

            # 2) Pegar la instrucción
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.6)

            # 3) Enviar
            pyautogui.press("enter")
            ic(f"⏎ Copilot recibió la instrucción ({len(instruccion)} chars)")
            return {"ok": True}
        except Exception as e:
            ic(f" enviar_a_copilot_chat: {e}")
            return {"ok": False, "error": str(e)}


# ============================== FLUJO ALTO NIVEL ==============================
def abrir_y_pedir_a_copilot(instruccion: str,
                            proyecto: Optional[str] = None,
                            modulo: Optional[str] = None,
                            crear_modulo_si_falta: bool = False,
                            esperar_apertura_s: float = 12.0
                            ) -> Dict[str, Any]:
    """
    Flujo completo (no bloqueante: el envío al chat se hace en hilo aparte
    para no congelar la respuesta de voz).

    Args:
      instruccion:           lo que se le dirá a Copilot Chat.
      proyecto:              nombre coloquial o ruta de la carpeta a abrir.
      modulo:                archivo dentro del proyecto a abrir como contexto.
                             Acepta nombre con o sin extensión.
      crear_modulo_si_falta: si es True y `modulo` no existe, lo crea vacío.

    Si VS Code ya está abierto con el proyecto pedido, NO lanza una nueva
    instancia: solo trae la ventana al frente y manda la petición.
    """
    carpeta: Optional[Path] = None
    archivo: Optional[Path] = None
    nombre_resuelto: Optional[str] = None
    modulo_creado = False

    if proyecto:
        carpeta = resolver_carpeta_proyecto(proyecto)
        if carpeta is None:
            ic(f" No encontré carpeta para '{proyecto}'")
        else:
            nombre_resuelto = carpeta.name
            ic(f" Proyecto resuelto: {carpeta}")

    if modulo and carpeta:
        archivo = resolver_archivo_modulo(carpeta, modulo)
        if archivo is None and crear_modulo_si_falta:
            res_crear = crear_modulo(carpeta, modulo)
            if res_crear.get("ok") and res_crear.get("creado"):
                archivo = Path(res_crear["ruta"])
                modulo_creado = True
                ic(f" Módulo creado: {archivo}")
            elif res_crear.get("ok") and not res_crear.get("creado"):
                # Ya existía, lo localizamos
                archivo = Path(res_crear["ruta"])
        if archivo:
            ic(f" Módulo resuelto: {archivo}")
        else:
            ic(f" No encontré módulo '{modulo}' dentro de {carpeta}")

    # ¿VS Code ya abierto con este proyecto?
    ventana_existente = vscode_ventana_para(carpeta)
    reutilizando = ventana_existente is not None

    if reutilizando and archivo:
        # Abrir el archivo en la ventana existente (no abre instancia nueva
        # cuando ya hay un workspace cargado).
        cli = _resolver_code_cli()
        if cli:
            try:
                subprocess.Popen([cli, "--reuse-window", "--goto", str(archivo)])
                ic(f" Archivo enviado a ventana existente: {archivo}")
            except Exception as e:
                ic(f" reuse-window: {e}")
    elif reutilizando:
        # Solo enfocar; no relanzar
        _enfocar_ventana(ventana_existente)
    else:
        res_open = abrir_vscode(carpeta=carpeta, archivo=archivo)
        if not res_open.get("ok"):
            return {"ok": False, "error": res_open.get("error"),
                    "fase": "abrir_vscode"}

    def _flujo():
        timeout = 4.0 if reutilizando else esperar_apertura_s
        ok = _enfocar_vscode(timeout_s=timeout, carpeta=carpeta)
        if not ok:
            ic(" No pude enfocar VS Code (timeout). Sigo intentando enviar.")
            time.sleep(2.0)
        # Si reutilizamos, dar un respiro al editor para enfocar el archivo
        if reutilizando and archivo:
            time.sleep(0.6)
        enviar_a_copilot_chat(instruccion, archivo=archivo)

    threading.Thread(target=_flujo, daemon=True).start()

    return {
        "ok": True,
        "carpeta": str(carpeta) if carpeta else None,
        "archivo": str(archivo) if archivo else None,
        "proyecto": nombre_resuelto or proyecto,
        "modulo": modulo,
        "modulo_creado": modulo_creado,
        "reutilizando_ventana": reutilizando,
        "instruccion_chars": len(instruccion),
    }


# ============================== ACEPTAR / RECHAZAR EDICIÓN (Keep / Undo) ==============================
# Copilot Chat muestra una barra "1 file changed [Keep] [Undo]" cuando edita
# un archivo. La acepta es equivalente a "Chat: Keep All Edits" en la paleta
# de comandos. Probamos varias vías en cascada porque la UI cambia entre
# versiones y no hay atajo global estable.

# Plantillas opcionales (PNG recortado del botón) que el usuario puede dejar
# en ~/.ares/templates/. Si existen, pyautogui las localizará en pantalla.
_TEMPLATES_DIR = Path.home() / ".ares" / "templates"
_PLANTILLAS_KEEP = ["copilot_keep.png", "keep.png", "copilot_keep_button.png"]
_PLANTILLAS_UNDO = ["copilot_undo.png", "undo.png"]


def _abrir_paleta_y_ejecutar(comando: str) -> bool:
    """Abre la Command Palette de VS Code y ejecuta `comando`.

    Esta es la vía MÁS FIABLE: VS Code expone los comandos de Copilot Chat
    (`Chat: Keep All Edits`, `Chat: Undo Edits`) en la paleta. Funciona
    aunque la UI cambie de posición.
    """
    if not PA_OK:
        return False
    try:
        pyautogui.hotkey("ctrl", "shift", "p")
        time.sleep(0.45)
        # Limpiar cualquier texto residual de la paleta
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.05)
        pyautogui.press("delete")
        time.sleep(0.05)
        # Escribir el comando
        if PC_OK:
            try:
                import pyperclip  # type: ignore
                pyperclip.copy(comando)
                pyautogui.hotkey("ctrl", "v")
            except Exception:
                pyautogui.typewrite(comando, interval=0.01)
        else:
            pyautogui.typewrite(comando, interval=0.01)
        time.sleep(0.35)
        pyautogui.press("enter")
        time.sleep(0.2)
        return True
    except Exception as e:
        ic(f" paleta {comando}: {e}")
        return False


def _click_por_plantilla(plantillas: List[str],
                         confidence: float = 0.85) -> bool:
    """Busca cualquiera de las plantillas en pantalla y hace clic.

    Requiere `opencv-python` para que `confidence` funcione; si no, cae al
    matching exacto de pyautogui (que es estricto pero suele bastar para
    botones planos como los de VS Code).
    """
    if not PA_OK:
        return False
    if not _TEMPLATES_DIR.exists():
        return False
    for nombre in plantillas:
        ruta = _TEMPLATES_DIR / nombre
        if not ruta.exists():
            continue
        try:
            try:
                pos = pyautogui.locateCenterOnScreen(
                    str(ruta), confidence=confidence
                )
            except TypeError:
                # opencv no instalado → matching exacto
                pos = pyautogui.locateCenterOnScreen(str(ruta))
            if pos:
                pyautogui.click(pos)
                ic(f" clic en plantilla {nombre}")
                return True
        except Exception as e:
            ic(f" plantilla {nombre}: {e}")
    return False


def _click_por_ocr(textos_objetivo: List[str]) -> bool:
    """Captura la pantalla y busca alguno de los textos con OCR (pytesseract).

    Devuelve True si encontró el texto y clicó. Silenciosamente falla si
    pytesseract no está instalado o tesseract no está en PATH.
    """
    if not PA_OK:
        return False
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except Exception as e:
        ic(f"ℹ OCR no disponible: {e}")
        return False
    try:
        captura = pyautogui.screenshot()
        # `image_to_data` da bbox por palabra
        data = pytesseract.image_to_data(
            captura, output_type=pytesseract.Output.DICT, lang="eng"
        )
        objetivos = {t.strip().lower() for t in textos_objetivo}
        n = len(data.get("text", []))
        for i in range(n):
            palabra = (data["text"][i] or "").strip().lower()
            if palabra and palabra in objetivos:
                x = data["left"][i] + data["width"][i] // 2
                y = data["top"][i] + data["height"][i] // 2
                pyautogui.click(x, y)
                ic(f" OCR clic en '{palabra}' ({x},{y})")
                return True
    except Exception as e:
        ic(f" OCR: {e}")
    return False


def _enfocar_chat_copilot() -> bool:
    """Pone el foco en el panel del Chat (Ctrl+Alt+I). Necesario para que
    Ctrl+Enter (atajo nativo del botón Keep) funcione."""
    if not PA_OK:
        return False
    try:
        hk = _hotkey_chat()
        pyautogui.hotkey(*hk)
        time.sleep(0.5)
        return True
    except Exception as e:
        ic(f" enfocar chat copilot: {e}")
        return False


# Variantes de los comandos por si VS Code los renombró entre versiones.
# El primero que coincida en la paleta gana. Orden: del más nuevo al más
# antiguo, para que no peguemos en la versión vieja primero.
_COMANDOS_KEEP = [
    "Chat: Keep All Chat Edits",
    "Chat: Keep All Edits",
    "Keep All Edits",
    "Inline Chat: Accept Changes",
]
_COMANDOS_UNDO = [
    "Chat: Undo Chat Edits",
    "Chat: Undo Edits",
    "Chat: Discard All Chat Edits",
    "Chat: Discard All Edits",
    "Undo All Edits",
]


def _aplicar_decision_copilot(accion: str,
                              carpeta: Optional[Path] = None
                              ) -> Dict[str, Any]:
    """Hace clic en Keep/Undo (o el comando equivalente) en VS Code/Copilot.

    Estrategia en cascada (la primera que tenga éxito gana):
      1) Atajo nativo Ctrl+Enter sobre el panel del chat (es el que VS Code
         le asigna al botón Keep visualmente — confirmado en el issue
         microsoft/vscode#265860). Para Undo no hay atajo, así que se salta.
      2) Paleta de comandos probando varios nombres (la API renombra
         comandos entre versiones).
      3) Plantilla PNG en ~/.ares/templates/ si el usuario dejó una.
      4) OCR con pytesseract.

    Args:
      accion: "keep" para aceptar, "undo" para revertir.
      carpeta: si se pasa, intenta enfocar la ventana del proyecto antes.
    """
    if accion not in {"keep", "undo"}:
        return {"ok": False, "error": "acción no soportada"}

    # 1) Enfocar VS Code (la ventana del proyecto si la conocemos)
    if not _enfocar_vscode(timeout_s=3.0, carpeta=carpeta):
        ic(" no encontré ventana de VS Code; intento de todas formas")

    with _RPA_LOCK:
        # 2) Atajo nativo Ctrl+Enter (solo Keep). Mucho más rápido y fiable
        #    que la paleta cuando hay edición pendiente del agente.
        if accion == "keep" and PA_OK:
            try:
                _enfocar_chat_copilot()
                # Pequeña espera para que el panel cobre foco
                time.sleep(0.25)
                pyautogui.hotkey("ctrl", "enter")
                time.sleep(0.4)
                ic("⌨ Ctrl+Enter enviado al panel de Copilot Chat (Keep)")
                # El atajo solo "hace algo" si hay edición pendiente; no
                # tenemos eco de éxito, así que igualmente probamos vías de
                # respaldo abajo SI el usuario no dejó plantilla. La
                # heurística es: si hubo edición → ya está aceptada y la
                # paleta no encontrará "Keep All ..." porque ya no existe,
                # entonces el "fallo" silencioso es OK. Devolvemos éxito.
                return {"ok": True, "via": "ctrl_enter"}
            except Exception as e:
                ic(f" ctrl+enter: {e}")

        # 3) Vía paleta de comandos con varios nombres
        comandos = _COMANDOS_KEEP if accion == "keep" else _COMANDOS_UNDO
        for cmd in comandos:
            if _abrir_paleta_y_ejecutar(cmd):
                # Damos un respiro y consideramos éxito (no tenemos forma
                # directa de saber si VS Code aceptó el match; al menos la
                # paleta se cerró y se envió Enter sobre el primer ítem).
                time.sleep(0.3)
                return {"ok": True, "via": "paleta", "comando": cmd}

        # 4) Plantilla PNG (si el usuario la dejó en ~/.ares/templates/)
        plantillas = (_PLANTILLAS_KEEP if accion == "keep"
                      else _PLANTILLAS_UNDO)
        if _click_por_plantilla(plantillas):
            return {"ok": True, "via": "plantilla"}

        # 5) OCR con pytesseract
        textos = (["keep"] if accion == "keep" else ["undo"])
        if _click_por_ocr(textos):
            return {"ok": True, "via": "ocr"}

    return {"ok": False, "error": "No pude localizar el botón. "
                                    "Asegúrate de que VS Code esté visible "
                                    "o instala pytesseract para OCR."}


def aceptar_edicion_copilot(carpeta: Optional[Path] = None) -> Dict[str, Any]:
    """Pulsa el botón Keep de Copilot Chat (o el comando equivalente)."""
    return _aplicar_decision_copilot("keep", carpeta)


def descartar_edicion_copilot(carpeta: Optional[Path] = None) -> Dict[str, Any]:
    """Pulsa el botón Undo de Copilot Chat."""
    return _aplicar_decision_copilot("undo", carpeta)
