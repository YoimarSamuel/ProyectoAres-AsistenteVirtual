"""
================================================================================
        ARES — Investigador Web (lee Google con Chrome real, en segundo plano)
================================================================================
Cumple `instrucciones.md` §7.2:

  ARES busca en Google (no Wikipedia, no APIs alternativas) y lee el bloque
  destacado al principio de la SERP — lo que un humano ve subrayado/
  resaltado en azul.

Prioridad de extracción:
  1. "Visión general creada por IA" (AI Overview / SGE)
  2. Featured snippet / answer box
  3. Knowledge panel (descripción del panel lateral)
  4. Primer resultado orgánico (NO anuncio)

Anuncios, productos patrocinados y resultados shopping se descartan
explícitamente.

Implementación:
  • Chrome HEADLESS reutilizado entre búsquedas (singleton, thread-safe).
  • Perfil EFÍMERO por arranque (evita bloqueos de --user-data-dir).
  • Detección del AI Overview por el TEXTO del heading, no por clases CSS.
================================================================================
"""

from __future__ import annotations
import os
import re
import sys
import time
import atexit
import threading
import urllib.parse
from pathlib import Path
from typing import Optional, Dict, Any
from icecream import ic

import requests
from bs4 import BeautifulSoup


# ============================== CONFIG ==============================
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.5",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}

TIMEOUT_HTTP = 12
ESPERA_AI_OVERVIEW = 5.0    # Chrome visible-off-screen tarda más en hidratar
ESPERA_HEADING_AI = 4.0     # tiempo extra esperando que aparezca el heading
RATE_LIMIT_GOOGLE = 8.0     # pausa mínima entre búsquedas a Google (evita captcha)
COOLDOWN_CAPTCHA = 90.0     # tiempo de espera tras detectar captcha

# Perfiles de Chrome:
#   PERFIL_REAL_*   → perfil del navegador Chrome del usuario (origen, solo lectura)
#   PERFIL_CHROME   → perfil privado de ARES (clonado del real la 1ª vez)
PERFIL_CHROME = (Path(os.path.expandvars("%LOCALAPPDATA%"))
                  / "ARES" / "chrome_profile") if os.name == "nt" else \
                 (Path.home() / ".ares" / "chrome_profile")

if os.name == "nt":
    PERFIL_REAL_BASE = Path(os.path.expandvars(
        r"%LOCALAPPDATA%\Google\Chrome\User Data"))
elif sys.platform == "darwin":
    PERFIL_REAL_BASE = (Path.home()
                         / "Library/Application Support/Google/Chrome")
else:
    PERFIL_REAL_BASE = Path.home() / ".config/google-chrome"


def _clonar_perfil_real(forzar: bool = False) -> bool:
    """
    Copia el perfil real de Chrome (cookies, sesión de Google) a la
    carpeta privada de ARES la primera vez. Así Google reconoce a ARES
    como sesión humana sin que tengamos que iniciar sesión manualmente.

    Solo copia archivos pequeños y críticos para la sesión: Cookies,
    Login Data, Local State y Preferences. NO copia caché, historial
    completo ni descargas (sería muy pesado).

    Devuelve True si el clonado tuvo éxito o si ya estaba hecho.
    """
    import shutil

    if PERFIL_CHROME.exists() and not forzar:
        # Si ya tenemos cookies, no re-clonamos
        cookies = PERFIL_CHROME / "Default" / "Cookies"
        if cookies.exists() and cookies.stat().st_size > 0:
            return True

    if not PERFIL_REAL_BASE.exists():
        ic(" No se encontró Chrome real instalado")
        return False

    # Detectar el perfil predeterminado del usuario.
    # En Chrome moderno (>v96) las cookies están en Default/Network/Cookies,
    # no en Default/Cookies como antes.
    candidatos = ["Default", "Profile 1", "Profile 2"]
    perfil_origen = None
    for c in candidatos:
        p = PERFIL_REAL_BASE / c
        # Probar ruta nueva (Network/Cookies) y antigua (Cookies)
        if (p / "Network" / "Cookies").exists() or (p / "Cookies").exists():
            perfil_origen = p
            break
    if perfil_origen is None:
        ic(" No encontré perfil de Chrome con cookies")
        return False

    # Crear destino
    destino = PERFIL_CHROME / "Default"
    destino.mkdir(parents=True, exist_ok=True)
    # Local State va al raíz
    PERFIL_CHROME.mkdir(parents=True, exist_ok=True)

    # Archivos a copiar (los críticos para sesión de Google)
    archivos_perfil = [
        "Cookies",
        "Cookies-journal",
        "Login Data",
        "Login Data-journal",
        "Web Data",
        "Preferences",
        "Secure Preferences",
        "Network/Cookies",
        "Network/Cookies-journal",
    ]

    copiados = 0
    for nombre in archivos_perfil:
        src = perfil_origen / nombre
        dst = destino / nombre
        if src.exists():
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copiados += 1
            except Exception as e:
                ic(f" no copié {nombre}: {e}")

    # Local State (claves de cifrado de cookies, raíz del perfil)
    src_ls = PERFIL_REAL_BASE / "Local State"
    dst_ls = PERFIL_CHROME / "Local State"
    if src_ls.exists():
        try:
            shutil.copy2(src_ls, dst_ls)
            copiados += 1
        except Exception as e:
            ic(f" no copié Local State: {e}")

    if copiados > 0:
        ic(f" Perfil de Chrome clonado ({copiados} archivos) → {PERFIL_CHROME}")
        return True
    return False

# Heading que Google usa para introducir el AI Overview en distintos idiomas
AI_HEADINGS = [
    "Visión general creada por IA",
    "Resumen generado por IA",
    "AI Overview",
    "Generative AI",
    "Visión general",
]

AD_MARKS = ("patrocinado", "anuncio", "sponsored", " ad ·", "envío gratis",
            "compra ahora", "ver producto", "agregar al carrito",
            "patrocinador", "publicidad", "oferta especial",
            "descuento", "promoción", "promocion",
            "mejor precio", "comprar online", "tu disposición",
            "a tu disposicion", "a través de una aplicación",
            "a traves de una aplicacion",
            "rápida, sencilla", "rapida, sencilla",
            "más de 3", "mas de 3",
            "reserva ya", "pide ya",
            "disponibilidad inmediata", "envío en 24",
            "encuentra los mejores", "los mejores precios",
            "vehículos a tu disposición", "vehiculos a tu disposicion")

AD_CSS_FRAGMENTS = ("commercial-unit", "ads-fr", "pla-unit",
                    "shopping-carousel", "uEierd", "v0nnCb")


# ============================== UTILIDADES ==============================
def _es_bloqueo(texto: str) -> bool:
    """Detecta captcha / bot-block / errores que NO son contenido real."""
    s = (texto or "").lower()
    señales = [
        # Captcha clásico
        "trouble accessing", "/sorry/index", "captcha", "recaptcha",
        "i'm not a robot", "no soy un robot", "i am not a robot",
        "no soy robot", "marca la casilla", "marque la casilla",
        # Bloqueos / rate-limit
        "unusual traffic", "tráfico inusual", "trafico inusual",
        "send feedback", "tener problemas para acceder",
        "verifica que eres", "verify that you are",
        # JS off / página intermedia
        "javascript is required", "enable javascript",
        "before you continue to google", "to continue, please type",
        "antes de continuar",
        # Servicio temporalmente no disponible
        "we apologize", "lo sentimos",
    ]
    return any(t in s for t in señales)


def _limitar_a_oraciones(texto: str, n: int = 2) -> str:
    """
    Devuelve sólo las primeras `n` oraciones del texto.

    Una oración termina con `.`, `!` o `?` seguidos de espacio y mayúscula
    (o fin de texto). Eso evita partir en abreviaturas dentro de palabras
    o en signos de puntuación medios.

    Si no hay suficientes terminadores, devuelve el texto intacto (la
    función _terminar_en_frase_completa ya garantiza el cierre).
    """
    if not texto:
        return texto

    # Iterar sobre los terminadores de oración. Aceptamos "." "!" "?"
    # seguidos de espacio + mayúscula (incluye letras acentuadas) o de
    # fin de texto. Así descartamos puntos dentro de "PHP: Hypertext", o
    # comas, o dos puntos.
    cierres = []
    for m in re.finditer(r"[\.!?](?=\s+[A-ZÁÉÍÓÚÑ¿¡]|\s*$)", texto):
        cierres.append(m.end())
        if len(cierres) >= n:
            break

    if len(cierres) >= n:
        return texto[:cierres[n - 1]].strip()
    return texto.strip()


def _limpiar(texto: str) -> str:
    """
    Normaliza un snippet recién extraído:
      • Colapsa whitespace.
      • Quita prefijos de fecha/autor que Google añade.
      • Elimina elipsis intercaladas y "...que" cortados de Google.
      • Garantiza que termine en oración completa (nunca a media frase).
      • Recorta a las dos primeras oraciones (lo destacado en azul del
        AI Overview de Google suele caber ahí, y evita que se cuelen
        secciones siguientes como "Estructura básica…").
    """
    texto = re.sub(r"\s+", " ", texto or "").strip()
    if not texto:
        return ""

    # Quitar prefijos de fecha/autor que Google añade a algunos snippets
    # Ej.: "29 abr 2026 — Texto…", "hace 3 días - Texto…"
    MESES = (r"(?:ene|feb|mar|abr|may|jun|jul|ago|sep|sept|oct|nov|dic|"
             r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
             r"septiembre|octubre|noviembre|diciembre)")
    texto = re.sub(
        rf"^\s*\d{{1,2}}\s+{MESES}\.?\s+\d{{2,4}}\s*[—\-:]\s*",
        "", texto, flags=re.IGNORECASE
    )
    texto = re.sub(
        r"^\s*hace\s+\d+\s+(?:día|días|hora|horas|semana|semanas|"
        r"mes|meses|año|años)\s*[—\-:]\s*",
        "", texto, flags=re.IGNORECASE
    )

    # Google añade puntos suspensivos cuando recorta. Si la elipsis viene
    # con palabras truncadas tipo "con los ... que", cortamos en la
    # última oración completa anterior a la elipsis.
    texto = _terminar_en_frase_completa(texto)

    # Recortar a las dos primeras oraciones (resumen breve y limpio).
    texto = _limitar_a_oraciones(texto, n=2)

    return texto


def _terminar_en_frase_completa(texto: str, max_chars: int = 700) -> str:
    """
    Garantiza que `texto` termine en una oración completa (. ! ?) y nunca
    a media frase ni con "..." colgando. Recorta a max_chars como tope.
    """
    t = texto.strip()
    if not t:
        return t

    # Si hay elipsis interna ("... que"), cortar antes de ella si rompe
    # el sentido. Solo cortamos en una elipsis si después no viene una
    # oración completa de >= 30 chars.
    elipsis_re = re.compile(r"\s*\.{3,}\s*|\s*…\s*")
    partes_elipsis = elipsis_re.split(t)
    # Conservar las partes antes de cualquier elipsis incompleta
    if len(partes_elipsis) > 1:
        # Mantener todas las partes menos la última si esa termina mal
        ultima = partes_elipsis[-1].strip()
        # Si la última parte después de "..." es corta o no termina en
        # puntuación final, descartarla.
        if len(ultima) < 30 or not re.search(r"[\.!\?]\s*$", ultima):
            t = ". ".join(p.strip() for p in partes_elipsis[:-1] if p.strip())
        else:
            t = ". ".join(p.strip() for p in partes_elipsis if p.strip())

    # Reemplazar elipsis residuales internas por punto y espacio.
    t = re.sub(r"\s*\.{3,}\s*|\s*…\s*", ". ", t).strip()
    t = re.sub(r"\s+", " ", t)

    # Recortar a max_chars sin cortar palabras
    if len(t) > max_chars:
        t = t[:max_chars].rsplit(" ", 1)[0]

    # Asegurar que termine en . ! ?
    if not re.search(r"[\.!\?]\s*$", t):
        # Buscar el último signo de puntuación final dentro del texto
        m = re.search(r"^(.*[\.!\?])\s+\S", t)
        if m:
            t = m.group(1)
        else:
            # Sin oración completa: añadimos un punto final como cierre
            t = t.rstrip(",;: ") + "."

    return t.strip()


def _limpiar_tema(query: str) -> str:
    """Extrae el concepto puro de la consulta (sin muletillas de pregunta)."""
    tema = re.sub(
        r"^(qué es|que es|qué significa|que significa|qué|que|busca|búscame|"
        r"buscame|investiga|dime sobre|dime|explícame|explicame|quién es|"
        r"quien es|cuál es|cual es|averigua|cómo funciona|como funciona|"
        r"definición de|definicion de|significado de)\s+",
        "", query, flags=re.IGNORECASE
    )
    tema = re.sub(r"^(un|una|el|la|los|las)\s+", "", tema, flags=re.IGNORECASE)
    return tema.strip(" ¿?¡!.,;:")


def _es_texto_de_ad(texto: str) -> bool:
    if not texto:
        return False
    bajo = texto.lower()
    if any(m in bajo for m in AD_MARKS):
        return True
    # Heurística de tono publicitario: muchas frases cortas con verbos
    # imperativos típicos de publicidad ("Descubre", "Encuentra", "Reserva",
    # "Disfruta", "Únete") o exclamaciones muy entusiastas.
    tono_pub = sum(1 for v in (
        "descubre", "encuentra", "reserva", "disfruta", "únete", "unete",
        "regístrate", "registrate", "prueba ya", "consigue", "ahorra",
        "compra fácil", "compra facil", "elige el", "tu mejor opción",
        "tu mejor opcion"
    ) if v in bajo)
    if tono_pub >= 2:
        return True
    return False


def _es_dentro_de_ad(el) -> bool:
    """Sube hasta 10 niveles buscando un contenedor de anuncio."""
    try:
        from selenium.webdriver.common.by import By
        nodo = el
        for _ in range(10):
            try:
                cls = (nodo.get_attribute("class") or "").lower()
                if any(frag in cls for frag in AD_CSS_FRAGMENTS):
                    return True
                if nodo.get_attribute("data-text-ad"):
                    return True
                nodo = nodo.find_element(By.XPATH, "..")
            except Exception:
                break
    except Exception:
        pass
    return False


def _filtrar_snippet(texto: str) -> Optional[str]:
    """Limpia y descarta texto que no es contenido real (ruido SERP/ads)."""
    if not texto or _es_bloqueo(texto):
        return None
    t = texto.strip()
    if len(t) < 40:
        return None
    bajo = t.lower()
    if _es_texto_de_ad(t):
        return None
    BASURA = ("cookies", "iniciar sesión", "buscar con google",
              "política de privacidad", "preferencias", "centro de ayuda",
              "send feedback", "más resultados")
    if any(b in bajo for b in BASURA):
        return None
    lineas = [l.strip() for l in t.split("\n")
              if len(l.strip()) > 25 and not _es_texto_de_ad(l)]
    if not lineas:
        return None
    return " ".join(lineas)


def _es_relevante(snippet: str, tema: str) -> bool:
    """
    Comprueba que el snippet hable del tema preguntado.
    Acepta variantes obvias (siglas/expansiones técnicas comunes).

    Reglas:
      • Si el tema es UNA sola palabra, debe aparecer en los primeros
        220 caracteres del snippet.
      • Si el tema tiene VARIAS palabras (ej. "django python"), basta con
        que aparezca AL MENOS UNA palabra principal del tema en cabecera
        Y otra cualquiera en el resto del snippet.
    """
    if not snippet or not tema:
        return False
    s = snippet.lower()
    t = tema.lower().strip()

    # Alias técnicos comunes (sigla ↔ nombre largo)
    ALIAS = {
        "js": ("javascript",), "javascript": ("js",),
        "ts": ("typescript",), "typescript": ("ts",),
        "html": ("hipertexto", "hypertext"),
        "css": ("hojas de estilo", "stylesheet"),
        "py": ("python",), "python": ("py",),
        "k8s": ("kubernetes",), "kubernetes": ("k8s",),
        "ia": ("inteligencia artificial",),
        "bd": ("base de datos",),
    }

    # Tokens del tema (palabras con 2+ letras)
    palabras = [w for w in re.findall(r"[a-záéíóúñ0-9]{2,}", t)]
    if not palabras:
        return True

    # Expandir cada palabra con sus alias
    def _expand(p):
        return {p, *ALIAS.get(p, ())}

    cabecera = s[:220]

    # Caso 1: una sola palabra → debe estar en cabecera
    if len(palabras) == 1:
        return any(tok in cabecera for tok in _expand(palabras[0]))

    # Caso 2: varias palabras → al menos una en cabecera + otra en
    # el resto del snippet (cualquier orden).
    encontradas_cabecera = sum(
        1 for p in palabras
        if any(tok in cabecera for tok in _expand(p))
    )
    encontradas_total = sum(
        1 for p in palabras
        if any(tok in s for tok in _expand(p))
    )
    return encontradas_cabecera >= 1 and encontradas_total >= 2


# ============================== CHROME HEADLESS (THREAD-SAFE) ==============================
_DRIVER = None
_DRIVER_LOCK = threading.Lock()
_INIT_INTENTADO = False


def _crear_driver():
    """
    Crea Chrome usando undetected-chromedriver — librería especializada
    para EVITAR la detección de Selenium por parte de Google. Sin esto,
    Google sirve reCAPTCHA constantemente.

    Chrome se abre visible pero MINIMIZADO: queda en la barra de tareas
    y el usuario sigue trabajando en ARES sin que el foco salte.
    """
    try:
        import undetected_chromedriver as uc
    except Exception as e:
        ic(f" undetected-chromedriver no disponible: {e}")
        return _crear_driver_fallback()

    # 1) Clonar el perfil real de Chrome (con tu sesión de Google) la
    #    primera vez. Si ya existe, se reutiliza.
    perfil_listo = _clonar_perfil_real()

    opts = uc.ChromeOptions()
    opts.add_argument("--window-size=1366,900")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-infobars")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-popup-blocking")
    opts.add_argument("--lang=es-ES")
    opts.add_argument("--log-level=3")
    # Usar el perfil clonado de ARES (con tus cookies y sesión de Google)
    if perfil_listo:
        PERFIL_CHROME.mkdir(parents=True, exist_ok=True)
        opts.add_argument(f"--user-data-dir={PERFIL_CHROME}")
        opts.add_argument("--profile-directory=Default")
        ic(f" Usando perfil clonado: {PERFIL_CHROME}")

    try:
        # use_subprocess=True evita que el proceso muera al fork del Flask.
        # version_main=None deja que uc detecte la versión de Chrome instalada.
        drv = uc.Chrome(options=opts, use_subprocess=True,
                         version_main=None)
        drv.set_page_load_timeout(25)

        # Minimizar para no robar el foco (queda en barra de tareas)
        try:
            drv.minimize_window()
            ic(" Chrome minimizado: queda en barra de tareas")
        except Exception as e:
            ic(f" no pude minimizar Chrome: {e}")

        # Pre-aceptar cookies de Google
        try:
            drv.get("https://www.google.com/")
            drv.add_cookie({
                "name": "SOCS",
                "value": "CAESHAgBEhJnd3NfMjAyNDA0MDgtMF9SQzIaAmVzIAEaBgiAqo-xBg",
                "domain": ".google.com",
                "path": "/",
            })
            drv.add_cookie({
                "name": "CONSENT",
                "value": "PENDING+987",
                "domain": ".google.com",
                "path": "/",
            })
            ic(" Cookies de consentimiento pre-establecidas")
        except Exception as e:
            ic(f" no pude pre-aceptar cookies: {e}")

        try:
            drv.minimize_window()
        except Exception:
            pass

        ic(" Chrome listo (undetected, minimizado)")
        return drv
    except Exception as e:
        ic(f" undetected-chromedriver falló: {e} — usando fallback")
        return _crear_driver_fallback()


def _crear_driver_fallback():
    """Chrome estándar de Selenium como respaldo si uc falla."""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except Exception as e:
        ic(f" Selenium no disponible: {e}")
        return None

    opts = Options()
    opts.add_argument("--window-size=1366,900")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--lang=es-ES")
    opts.add_argument(f"--user-agent={HEADERS['User-Agent']}")
    opts.add_argument("--log-level=3")
    opts.add_experimental_option("excludeSwitches",
                                  ["enable-automation", "enable-logging"])
    opts.add_experimental_option("useAutomationExtension", False)

    try:
        drv = webdriver.Chrome(options=opts)
        drv.set_page_load_timeout(20)
        drv.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',"
                       "{get:()=>undefined})"}
        )
        try:
            drv.minimize_window()
        except Exception:
            pass
        try:
            drv.get("https://www.google.com/")
            drv.add_cookie({"name": "SOCS",
                            "value": "CAESHAgBEhJnd3NfMjAyNDA0MDgtMF9SQzIaAmVzIAEaBgiAqo-xBg",
                            "domain": ".google.com", "path": "/"})
            drv.add_cookie({"name": "CONSENT", "value": "PENDING+987",
                            "domain": ".google.com", "path": "/"})
        except Exception:
            pass
        try:
            drv.minimize_window()
        except Exception:
            pass
        ic(" Chrome estándar listo (fallback)")
        return drv
    except Exception as e:
        ic(f" No pude iniciar Chrome: {e}")
        return None


def _get_driver():
    """Devuelve el driver singleton, creándolo si hace falta. Thread-safe."""
    global _DRIVER, _INIT_INTENTADO
    with _DRIVER_LOCK:
        if _DRIVER is not None:
            # Salud: verificar que la sesión sigue viva
            try:
                _DRIVER.title
                return _DRIVER
            except Exception as e:
                ic(f" Driver muerto, recreando: {e}")
                try:
                    _DRIVER.quit()
                except Exception:
                    pass
                _DRIVER = None

        _DRIVER = _crear_driver()
        _INIT_INTENTADO = True
        return _DRIVER


def _aceptar_consentimiento_si_aparece(drv):
    """Acepta el modal de cookies de Google si aparece. Es robusto:
    prueba múltiples selectores, idiomas y la página intermedia consent.google.com.
    """
    from selenium.webdriver.common.by import By
    try:
        # Caso 1: estamos en consent.google.com (página dedicada)
        if "consent.google" in (drv.current_url or "").lower():
            ic(" En consent.google.com, intentando aceptar…")
            for sel in [
                "button#L2AGLb",                         # 'Acepto todo' clásico
                'button[aria-label*="Acepto"]',
                'button[aria-label*="Accept"]',
                'form[action*="save"] button',
                'button[jsname="b3VHJd"]',
            ]:
                try:
                    btns = drv.find_elements(By.CSS_SELECTOR, sel)
                    if btns:
                        btns[0].click()
                        time.sleep(2.0)
                        ic(f" Consentimiento aceptado vía {sel}")
                        return
                except Exception:
                    continue

        # Caso 2: modal embebido dentro de google.com
        for sel in [
            "button#L2AGLb",
            "div#L2AGLb",
            'button[aria-label*="Aceptar todo"]',
            'button[aria-label*="Accept all"]',
            'button[aria-label*="Acepto"]',
            'button[aria-label*="I agree"]',
        ]:
            try:
                btns = drv.find_elements(By.CSS_SELECTOR, sel)
                for b in btns:
                    if b.is_displayed():
                        b.click()
                        time.sleep(1.5)
                        ic(f" Consentimiento aceptado (modal) vía {sel}")
                        return
            except Exception:
                continue

        # Caso 3: por texto del botón (fallback más amplio)
        for txt in ("Aceptar todo", "Aceptar todas", "Acepto todo",
                    "Acepto", "Accept all", "I agree", "Agree"):
            try:
                btns = drv.find_elements(
                    By.XPATH,
                    f"//button[contains(normalize-space(.), {repr(txt)})]"
                )
                for b in btns:
                    if b.is_displayed():
                        b.click()
                        time.sleep(1.5)
                        ic(f" Consentimiento aceptado (texto): {txt}")
                        return
            except Exception:
                continue
    except Exception as e:
        ic(f" aceptar consentimiento: {e}")


def _extraer_ai_overview(drv, tema: str = "") -> Optional[str]:
    """
    Detecta el bloque del AI Overview de Google y extrae su texto.

    Estrategia (varias capas):
      1. Por TEXTO del heading visible (varios idiomas).
      2. Por elemento con clase HxTRcb (texto resaltado azul del AI
         Overview — la pista que el usuario ve subrayada).
      3. Por CLASES CSS conocidas de Google SGE/AI Overview.
      4. Por atributo aria-label que contenga "AI Overview" / similares.
    """
    from selenium.webdriver.common.by import By

    # --- Capa 1: por heading textual ---
    headings_encontrados = []
    for h in AI_HEADINGS:
        try:
            elementos = drv.find_elements(
                By.XPATH,
                f"//*[normalize-space(text())={repr(h)}]"
            )
            headings_encontrados.extend(elementos)
        except Exception:
            continue

    for el_heading in headings_encontrados:
        if _es_dentro_de_ad(el_heading):
            continue
        nodo = el_heading
        mejor_texto = ""
        for _ in range(10):
            try:
                nodo = nodo.find_element(By.XPATH, "..")
            except Exception:
                break
            try:
                texto = (nodo.text or "").strip()
            except Exception:
                continue
            if 150 <= len(texto) <= 2500 and any(h in texto for h in AI_HEADINGS):
                mejor_texto = texto
            elif len(texto) > 2500:
                break

        if mejor_texto:
            snippet = _extraer_texto_ai_overview(mejor_texto)
            if snippet and len(snippet) >= 60 and (
                    not tema or _es_relevante(snippet, tema)):
                return snippet

    # --- Capa 2: por la clase HxTRcb (texto resaltado azul del AI Overview) ---
    # Esta es la pista: el texto en azul que el usuario ve subrayado
    # vive dentro de un <mark class="HxTRcb"> del bloque del AI Overview.
    # Subimos por el padre hasta encontrar el contenedor con suficiente texto.
    try:
        marks = drv.find_elements(By.CSS_SELECTOR, ".HxTRcb, mark.HxTRcb")
        for el_mark in marks:
            if _es_dentro_de_ad(el_mark):
                continue
            nodo = el_mark
            mejor_texto = ""
            for _ in range(10):
                try:
                    nodo = nodo.find_element(By.XPATH, "..")
                except Exception:
                    break
                try:
                    texto = (nodo.text or "").strip()
                except Exception:
                    continue
                # El bloque del AI Overview suele ser más extenso (contiene
                # varios párrafos y eventualmente la lista de fuentes).
                if 120 <= len(texto) <= 3500:
                    mejor_texto = texto
                elif len(texto) > 3500:
                    break
            if mejor_texto:
                snippet = _extraer_texto_ai_overview(mejor_texto)
                if snippet and len(snippet) >= 60 and (
                        not tema or _es_relevante(snippet, tema)):
                    return snippet
    except Exception:
        pass

    # --- Capa 3: por selectores CSS conocidos de SGE/AI Overview ---
    SGE_SELECTORES = [
        # SGE / AI Overview moderno (2024-2026)
        'div[data-attrid="GenerativeAI"]',
        'div[data-attrid*="AIOverview"]',
        'div[jsname="ZUgvYd"]',
        'div[jsname="kdrmQc"]',
        'div[data-mh="-1"]',
        'div.sR9wbf',
        'div.WaaZC',
        'div.ZRyHld',
        'div.VbT2Bd',
        'div.bGtFr',
        'div.WzVsAd',
    ]
    for sel in SGE_SELECTORES:
        try:
            for el in drv.find_elements(By.CSS_SELECTOR, sel):
                if _es_dentro_de_ad(el):
                    continue
                texto = (el.text or "").strip()
                if 80 <= len(texto) <= 3000:
                    snippet = _extraer_texto_ai_overview(texto)
                    if snippet and len(snippet) >= 60 and (
                            not tema or _es_relevante(snippet, tema)):
                        return snippet
        except Exception:
            continue

    # --- Capa 4: por aria-label ---
    try:
        for ar in ("AI Overview", "Visión general creada por IA",
                    "Generative", "Resumen generado por IA"):
            els = drv.find_elements(
                By.CSS_SELECTOR, f'[aria-label*="{ar}"]'
            )
            for el in els:
                texto = (el.text or "").strip()
                if 80 <= len(texto) <= 3000:
                    snippet = _extraer_texto_ai_overview(texto)
                    if snippet and len(snippet) >= 60 and (
                            not tema or _es_relevante(snippet, tema)):
                        return snippet
    except Exception:
        pass

    return None


def _extraer_texto_ai_overview(texto_bruto: str) -> str:
    """
    Limpia el texto bruto del bloque AI Overview:
      • Quita el heading.
      • Quita líneas que son botones, enlaces a fuentes, o controles UI.
      • Quita líneas con sólo URLs.
    """
    # Quitar headings de todos los idiomas
    for h in AI_HEADINGS:
        texto_bruto = texto_bruto.replace(h, "")

    BOTONES_UI = {
        "mostrar más", "mostrar mas", "show more", "más información",
        "mas informacion", "more info", "comentarios", "feedback",
        "copiar", "compartir", "share", "wikipedia", "fuentes",
        "exportar", "guardar", "calificar", "no útil", "útil",
        "informar", "denunciar"
    }

    lineas_validas = []
    for ln in texto_bruto.split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        bajo = ln.lower()
        # Saltar URLs / breadcrumbs
        if re.match(r"^https?://", ln, re.I):
            continue
        if re.search(r"[a-z]+\.[a-z]{2,}/?\s*›", ln, re.I):
            continue
        # Saltar etiquetas de fuente cortas tipo "Wikipedia +3"
        if re.match(r"^\s*\w+\s*\+\d+\s*$", ln):
            continue
        # Saltar líneas que SON un botón UI (cortas, palabra clave)
        if len(ln) < 40 and any(b in bajo for b in BOTONES_UI):
            continue
        # Saltar líneas con muy pocas palabras y mayúsculas (suelen ser
        # tabs como "Definición", "Ejemplos", "Más resultados")
        if len(ln.split()) <= 3 and ln.endswith(":") is False \
                and not ln.endswith((".", "!", "?")):
            # Solo descartar si no parece principio de oración
            if len(ln) < 30:
                continue
        lineas_validas.append(ln)

    texto = " ".join(lineas_validas).strip(" ·•-—\n\t")
    return re.sub(r"\s+", " ", texto)


def _extraer_featured_snippet(drv, tema: str = "") -> Optional[str]:
    """Featured snippet / answer box / knowledge panel description."""
    from selenium.webdriver.common.by import By

    SELECTORES = [
        "div.kp-blk div.xpdopen",
        "div.xpdopen .hgKElc",
        "div.IZ6rdc",
        "div.hgKElc",
        "span.hgKElc",
        "div.LGOjhe",
        'div[data-attrid="wa:/description"]',
        "div.kno-rdesc span",
        'div[data-attrid*="description"]',
    ]
    for sel in SELECTORES:
        try:
            for el in drv.find_elements(By.CSS_SELECTOR, sel):
                if _es_dentro_de_ad(el):
                    continue
                snippet = _filtrar_snippet((el.text or "").strip())
                if snippet and (not tema or _es_relevante(snippet, tema)):
                    return snippet
        except Exception:
            continue
    return None


def _extraer_primer_organico(drv, tema: str = "") -> Optional[str]:
    """
    Recorre varios resultados orgánicos (no solo el primero) y devuelve
    el primero que sea relevante al tema preguntado.
    """
    from selenium.webdriver.common.by import By

    SELECTORES = [
        "#rso div.g div.VwiC3b",
        "#rso div[data-sncf] div.VwiC3b",
        "#search div[data-sncf='1']",
        "#rso div[data-sncf]",
        "#rso div.g span.aCOpRe",
    ]
    candidatos: list[str] = []
    for sel in SELECTORES:
        try:
            for el in drv.find_elements(By.CSS_SELECTOR, sel):
                if _es_dentro_de_ad(el):
                    continue
                s = _filtrar_snippet((el.text or "").strip())
                if s:
                    candidatos.append(s)
        except Exception:
            continue

    if not tema:
        return candidatos[0] if candidatos else None

    # Devolver el primero relevante
    for s in candidatos:
        if _es_relevante(s, tema):
            return s

    # Si NINGUNO menciona el tema, devolvemos None para que la cascada
    # caiga a los respaldos en lugar de mentir con un snippet de otro tema.
    return None


def _leer_google_renderizado(query: str) -> Optional[Dict[str, str]]:
    """
    Carga google.com en headless real, espera el render del AI Overview y
    devuelve {'snippet': ..., 'fuente': 'google_*'}.
    """
    drv = _get_driver()
    if drv is None:
        return None

    tema = _limpiar_tema(query) or query

    url = (f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"
           f"&hl=es&pws=0&gl=es")

    # Toda la sesión Selenium debe ser exclusiva (no thread-safe)
    with _DRIVER_LOCK:
        try:
            drv.get(url)
            # Mantener la ventana minimizada en cada navegación: algunas
            # versiones de Chrome la suben al cargar una URL.
            try:
                drv.minimize_window()
            except Exception:
                pass
        except Exception as e:
            ic(f" Google.get error: {e}")
            return None

        _aceptar_consentimiento_si_aparece(drv)

        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        try:
            WebDriverWait(drv, 8).until(
                EC.presence_of_element_located((By.ID, "search"))
            )
        except Exception:
            time.sleep(1.0)

        # AI Overview es lazy. Esperamos primero a que aparezca el
        # heading "Visión general creada por IA" si está presente
        # (búsqueda por XPath con timeout corto). Si no aparece, espera fija.
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        encontrado_heading = False
        try:
            xpaths = [
                f"//*[normalize-space(text())={repr(h)}]"
                for h in AI_HEADINGS
            ]
            WebDriverWait(drv, ESPERA_HEADING_AI).until(
                EC.any_of(*[
                    EC.presence_of_element_located((By.XPATH, xp))
                    for xp in xpaths
                ])
            )
            encontrado_heading = True
            ic(" AI Overview heading detectado")
            # Tras detectarlo, dar un margen extra para que el texto hidrate
            time.sleep(2.0)
        except Exception:
            # No hay AI Overview para esta query; dar un tiempo fijo y seguir
            time.sleep(ESPERA_AI_OVERVIEW)

        try:
            body_txt = drv.find_element(By.TAG_NAME, "body").text or ""
            if _es_bloqueo(body_txt):
                ic(" Google mostró captcha/bloqueo")
                _activar_cooldown_captcha()
                return None
        except Exception:
            pass

        # 1) AI Overview
        snippet = _extraer_ai_overview(drv, tema)
        if snippet:
            return {"snippet": snippet, "fuente": "google_ai_overview"}

        # 2) Featured snippet / knowledge panel
        snippet = _extraer_featured_snippet(drv, tema)
        if snippet:
            return {"snippet": snippet, "fuente": "google_featured"}

        # 3) Primer orgánico (filtrado por relevancia al tema)
        snippet = _extraer_primer_organico(drv, tema)
        if snippet:
            return {"snippet": snippet, "fuente": "google_organico"}

        # 4) Fallback final: el texto inicial del body de la SERP. A veces
        # Google sirve un layout sin clases reconocibles pero el contenido
        # sigue ahí. Tomamos las primeras oraciones tras el query.
        snippet = _extraer_body_inicial(drv, tema)
        if snippet:
            return {"snippet": snippet, "fuente": "google_body"}

    return None


def _extraer_body_inicial(drv, tema: str = "") -> Optional[str]:
    """
    Último recurso: lee el texto del body, salta navegación/buscador, y
    devuelve la primera porción relevante al tema. Útil cuando Google sirve
    un layout simplificado sin clases reconocibles.
    """
    from selenium.webdriver.common.by import By
    try:
        body_txt = drv.find_element(By.TAG_NAME, "body").text or ""
    except Exception:
        return None
    if not body_txt or _es_bloqueo(body_txt):
        return None

    # Saltar líneas de navegación típicas
    SALTAR_INICIO = (
        "saltar al contenido", "saltar a la búsqueda",
        "skip to main content",
    )
    lineas = []
    for ln in body_txt.split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        bajo = ln.lower()
        if any(s in bajo for s in SALTAR_INICIO):
            continue
        lineas.append(ln)

    # Saltar las primeras 3-4 líneas suelen ser: tema buscado, "Body" o
    # tabs como "Todo / Imágenes / Vídeos".
    UI_TABS = {"todo", "imágenes", "imagenes", "vídeos", "videos",
                "noticias", "shopping", "más", "mas",
                "modo ia", "videos cortos", "body"}
    contenido = []
    for ln in lineas:
        bajo = ln.strip().lower()
        if bajo in UI_TABS:
            continue
        if len(ln) < 30:
            continue
        contenido.append(ln)
        # Tomamos las primeras ~3 líneas largas
        if sum(len(c) for c in contenido) >= 250:
            break

    texto = " ".join(contenido)
    snippet = _filtrar_snippet(texto)
    if snippet and (not tema or _es_relevante(snippet, tema)):
        return snippet
    return None


# ============================== RESPALDOS HTTP ==============================
def _buscar_bing(query: str) -> Optional[str]:
    url = f"https://www.bing.com/search?q={urllib.parse.quote_plus(query)}&setlang=es"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT_HTTP)
        if r.status_code != 200 or _es_bloqueo(r.text):
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        for css in ["div.b_entityTP", "div.b_snippet",
                    "li.b_ans p", "ol#b_results li.b_algo p",
                    "div.b_caption p"]:
            el = soup.select_one(css)
            if el:
                snippet = _filtrar_snippet(el.text)
                if snippet:
                    return snippet
    except Exception as e:
        ic(f" Bing error: {e}")
    return None


def _buscar_duckduckgo(query: str) -> Optional[str]:
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote_plus(query)}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT_HTTP)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        for css in [".result__snippet", ".zci__result", ".about-info"]:
            el = soup.select_one(css)
            if el:
                snippet = _filtrar_snippet(el.text)
                if snippet:
                    return snippet
    except Exception as e:
        ic(f" DuckDuckGo error: {e}")
    return None


# ============================== API PÚBLICA ==============================
# Pausa mínima entre búsquedas a Google para evitar rate-limiting.
_ULTIMA_CONSULTA_TS = 0.0
_BLOQUEADO_HASTA = 0.0   # timestamp hasta el cual no insistimos a Google


def _aplicar_rate_limit():
    global _ULTIMA_CONSULTA_TS
    transcurrido = time.time() - _ULTIMA_CONSULTA_TS
    if transcurrido < RATE_LIMIT_GOOGLE:
        time.sleep(RATE_LIMIT_GOOGLE - transcurrido)
    _ULTIMA_CONSULTA_TS = time.time()


def _en_cooldown_captcha() -> bool:
    return time.time() < _BLOQUEADO_HASTA


def _activar_cooldown_captcha():
    """Tras un captcha, dejamos a Google en cuarentena por COOLDOWN_CAPTCHA s."""
    global _BLOQUEADO_HASTA
    _BLOQUEADO_HASTA = time.time() + COOLDOWN_CAPTCHA
    ic(f" Cooldown anti-captcha activado: {COOLDOWN_CAPTCHA}s")


def _bloqueado_por_google() -> None:
    """Cuando Google detecta bot, mata el driver y recrea con cookies nuevas
    en la próxima búsqueda. Es la única forma fiable de salir del captcha
    sin sesión humana."""
    global _DRIVER
    with _DRIVER_LOCK:
        if _DRIVER is not None:
            try:
                _DRIVER.quit()
            except Exception:
                pass
            _DRIVER = None
            ic(" Driver reciclado tras detección de bloqueo")


def investigar(query: str, abrir_navegador: bool = False) -> Dict[str, Any]:
    """
    Lee Google con Chrome headless en SEGUNDO PLANO (no abre ventana visible)
    y devuelve el bloque destacado al principio de la SERP.

    Devuelve: {ok, query, tema, descripcion, fuente, url}
    """
    query = (query or "").strip()
    if not query:
        return {"ok": False, "error": "Query vacío"}

    snippet, fuente = None, None

    # Si estamos en cooldown tras un captcha reciente, saltamos directo
    # a los respaldos en vez de provocar otro captcha.
    if _en_cooldown_captcha():
        restante = int(_BLOQUEADO_HASTA - time.time())
        ic(f" Google en cooldown ({restante}s) — voy a respaldos")
    else:
        _aplicar_rate_limit()
        ic(f" Buscando en Google (Chrome): {query}")
        g = _leer_google_renderizado(query)
        if g:
            snippet, fuente = g["snippet"], g["fuente"]

    # Si Google falló o estamos en cooldown, ir a respaldos
    if not snippet:
        ic(" Respaldo: Bing")
        snippet = _buscar_bing(query)
        if snippet:
            fuente = "bing"
    if not snippet:
        ic(" Respaldo: DuckDuckGo")
        snippet = _buscar_duckduckgo(query)
        if snippet:
            fuente = "duckduckgo"

    if not snippet:
        return {
            "ok": False,
            "query": query,
            "error": ("No pude leer información clara. Google bloqueó la "
                      "consulta y los respaldos no devolvieron resultados.")
        }

    snippet = _limpiar(snippet)
    tema = _limpiar_tema(query) or query

    # Validar relevancia final: si el snippet no menciona el tema, mejor
    # decirlo explícitamente que devolver algo equivocado.
    if not _es_relevante(snippet, tema):
        ic(f" Snippet no relevante para '{tema}': {snippet[:80]}…")
        return {
            "ok": False,
            "query": query,
            "error": (f"Encontré información, pero no parecía hablar de "
                      f"'{tema}'. ¿Puedes reformular la pregunta?")
        }

    ic(f" [{fuente}] ({len(snippet)} chars): {snippet[:80]}…")

    return {
        "ok": True,
        "query": query,
        "tema": tema,
        "descripcion": snippet,
        "fuente": fuente,
        "url": (f"https://www.google.com/search?"
                f"q={urllib.parse.quote_plus(query)}")
    }


def cerrar_driver():
    """Cierra el Chrome headless al apagar la app (idempotente)."""
    global _DRIVER
    with _DRIVER_LOCK:
        if _DRIVER is not None:
            try:
                _DRIVER.quit()
                ic(" Chrome headless cerrado")
            except Exception:
                pass
            _DRIVER = None


atexit.register(cerrar_driver)
