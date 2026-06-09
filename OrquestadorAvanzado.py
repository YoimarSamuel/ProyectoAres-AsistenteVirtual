"""
================================================================================
        ARES v2.0 — Orquestador Avanzado (RPA + Web Apps + Files)
================================================================================
Capacidades adicionales sobre OrquestadarSistema.py:
  - YouTube: abrir y reproducir
  - WhatsApp Web: enviar mensaje a contacto
  - Facebook: abrir mensajería y enviar texto
  - File ops: abrir / editar / eliminar archivos
  - Browser: abrir URL arbitraria
================================================================================
"""

from __future__ import annotations
import os
import time
import shutil
import urllib.parse
import webbrowser
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional
from icecream import ic

try:
    import pyautogui
    PA_OK = True
except Exception:
    PA_OK = False

pyautogui_pause = 0.4


# ============================== WEB APPS ==============================
def abrir_url(url: str) -> Dict[str, Any]:
    try:
        webbrowser.open(url, new=2)
        ic(f" URL abierta: {url}")
        return {"ok": True, "url": url}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def reproducir_youtube(consulta: str) -> Dict[str, Any]:
    """Busca la canción en YouTube y abre el primer video (auto-reproduce)."""
    q = urllib.parse.quote_plus(consulta)
    search_url = f"https://www.youtube.com/results?search_query={q}"

    video_id = _primer_video_id(consulta)
    if video_id:
        url = f"https://www.youtube.com/watch?v={video_id}"
        abrir_url(url)
        ic(f" YouTube reproduciendo: {consulta} ({video_id})")
        return {"ok": True, "tipo": "youtube", "consulta": consulta,
                "url": url, "video_id": video_id}

    # Fallback: si no se pudo extraer el ID (red bloqueada, layout cambió...)
    abrir_url(search_url)
    ic(f" YouTube fallback (búsqueda): {consulta}")
    return {"ok": True, "tipo": "youtube_search", "consulta": consulta,
            "url": search_url}


def _primer_video_id(consulta: str) -> Optional[str]:
    """Extrae el primer videoId del HTML de resultados de YouTube."""
    try:
        import re
        import requests
        r = requests.get(
            f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(consulta)}",
            headers={
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/124.0 Safari/537.36"),
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.5"
            },
            timeout=10
        )
        if r.status_code != 200:
            return None
        # YouTube embute videoId varias veces; el primero suele ser el top result
        m = re.search(r'"videoId":"([0-9A-Za-z_-]{11})"', r.text)
        return m.group(1) if m else None
    except Exception as e:
        ic(f" YouTube videoId error: {e}")
        return None


def enviar_whatsapp(numero: str, mensaje: str,
                     enviar_auto: bool = True) -> Dict[str, Any]:
    """
    Abre WhatsApp Web con mensaje pre-cargado y lo ENVÍA automáticamente.
    Estrategia:
      1. Abre web.whatsapp.com/send?phone=...&text=... (URL oficial).
      2. Espera a que cargue el DOM (varios reintentos progresivos).
      3. Envía ENTER vía pyautogui sobre la ventana enfocada del navegador.

    `numero` debe incluir prefijo internacional sin espacios.
    Si enviar_auto=False, el mensaje queda en el cuadro y el usuario
    pulsa Enter manualmente.
    """
    numero = "".join(c for c in numero if c.isdigit())
    msg = urllib.parse.quote(mensaje)
    url = f"https://web.whatsapp.com/send?phone={numero}&text={msg}"
    abrir_url(url)
    ic(f" WhatsApp → +{numero} : {mensaje[:60]}")

    if enviar_auto and PA_OK:
        # Reintentos progresivos: cubre desde cargas rápidas (5s)
        # hasta sesiones lentas (hasta 25s).
        _enviar_enter_reintentos([5, 10, 18, 25])

    return {"ok": True, "tipo": "whatsapp", "numero": numero,
            "url": url, "mensaje": mensaje}


def _enviar_enter_reintentos(segundos_lista):
    """Lanza un hilo que pulsa ENTER a varios tiempos para enviar el mensaje
    una vez WhatsApp Web haya cargado. Solo se necesita que UNO funcione."""
    import threading

    def _t():
        for s in sorted(segundos_lista):
            time.sleep(s if s == segundos_lista[0] else
                       s - segundos_lista[segundos_lista.index(s) - 1])
            try:
                if PA_OK:
                    pyautogui.press("enter")
                    ic(f"⏎ ENTER auto-enviado a los {s}s")
            except Exception as e:
                ic(f" no pude enviar ENTER ({s}s): {e}")

    threading.Thread(target=_t, daemon=True).start()


# Compatibilidad hacia atrás
def threading_send_enter_after(segundos: float):
    _enviar_enter_reintentos([segundos])


def abrir_facebook_mensaje(destinatario: str = "",
                            mensaje: str = "") -> Dict[str, Any]:
    """
    Abre Facebook Messenger Web. Si se da destinatario, navega a su chat.
    El mensaje se inyecta vía portapapeles + paste (más fiable que typewrite
    para acentos/emojis).
    """
    if destinatario:
        url = f"https://www.facebook.com/messages/t/{urllib.parse.quote(destinatario)}"
    else:
        url = "https://www.facebook.com/messages/"
    abrir_url(url)
    ic(f" FB Messenger → {destinatario or '(inbox)'}")

    if mensaje and PA_OK:
        import threading
        def _t():
            time.sleep(8)  # esperar carga
            try:
                # Pegar via portapapeles (más fiable que typewrite con tildes)
                _set_clipboard(mensaje)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.4)
                pyautogui.press("enter")
                ic(" Mensaje FB pegado y enviado")
            except Exception as e:
                ic(f" FB send error: {e}")
        threading.Thread(target=_t, daemon=True).start()

    return {"ok": True, "tipo": "facebook", "destinatario": destinatario,
            "url": url}


def _set_clipboard(text: str) -> None:
    """Copia texto al portapapeles de Windows sin dependencias extra."""
    try:
        import subprocess
        p = subprocess.Popen(["clip"], stdin=subprocess.PIPE,
                             shell=True, close_fds=True)
        p.communicate(input=text.encode("utf-16le"))
    except Exception as e:
        ic(f" clipboard fail: {e}")


# ============================== FILE OPS ==============================
def abrir_archivo(ruta: str) -> Dict[str, Any]:
    p = Path(ruta).expanduser()
    if not p.exists():
        return {"ok": False, "error": f"No existe: {ruta}"}
    try:
        os.startfile(str(p))  # Windows
        ic(f" Archivo abierto: {p}")
        return {"ok": True, "ruta": str(p)}
    except AttributeError:
        # Fallback no-Windows
        subprocess.Popen(["xdg-open", str(p)])
        return {"ok": True, "ruta": str(p)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def editar_archivo(ruta: str, contenido: str,
                    modo: str = "sobrescribir") -> Dict[str, Any]:
    """
    modo: 'sobrescribir' | 'agregar' | 'reemplazar:<texto>'
    """
    p = Path(ruta).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)

    try:
        if modo == "agregar":
            with p.open("a", encoding="utf-8") as f:
                f.write(contenido)
        elif modo.startswith("reemplazar:"):
            target = modo.split(":", 1)[1]
            actual = p.read_text(encoding="utf-8") if p.exists() else ""
            nuevo  = actual.replace(target, contenido)
            p.write_text(nuevo, encoding="utf-8")
        else:
            p.write_text(contenido, encoding="utf-8")
        ic(f" Archivo editado ({modo}): {p}")
        return {"ok": True, "ruta": str(p), "modo": modo}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def eliminar_archivo(ruta: str, force: bool = False) -> Dict[str, Any]:
    """Elimina archivo o carpeta. Operación destructiva."""
    p = Path(ruta).expanduser()
    if not p.exists():
        return {"ok": False, "error": f"No existe: {ruta}"}

    try:
        if p.is_dir():
            if not force:
                return {"ok": False,
                        "error": "Es directorio; pasa force=True para borrar recursivo."}
            shutil.rmtree(p)
        else:
            p.unlink()
        ic(f"  Eliminado: {p}")
        return {"ok": True, "ruta": str(p)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def listar_directorio(ruta: str = ".") -> Dict[str, Any]:
    p = Path(ruta).expanduser()
    if not p.exists():
        return {"ok": False, "error": f"No existe: {ruta}"}
    items = []
    for child in p.iterdir():
        items.append({
            "nombre": child.name,
            "tipo":   "dir" if child.is_dir() else "file",
            "tamaño": child.stat().st_size if child.is_file() else 0
        })
    return {"ok": True, "ruta": str(p), "items": items}
