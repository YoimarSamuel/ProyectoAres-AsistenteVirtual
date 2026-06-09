"""
================================================================================
        ARES — PLN puro (sin LLM externo, sólo análisis de texto)
================================================================================
Reemplaza por completo cualquier llamada a Mistral/Gemini/OpenAI.
ARES NO depende de ninguna IA externa para pensar.
Esta clase únicamente analiza texto y extrae intenciones.
================================================================================
"""

from __future__ import annotations
import re
import unicodedata
from icecream import ic


# ============================== NORMALIZACIÓN DE CONSULTAS ==============================
# Fuente única de verdad: cualquier pregunta sobre un tema ("dime qué es X",
# "cuéntame de X", "explícame X", "qué significa X", "háblame de X"...) se
# reduce a un mismo `tema` para que el lookup de conocimiento sea robusto.

# Wake-words a quitar al inicio.
_WAKE = r"(?:oye|ares|jarvis|asistente|hey|por\s+favor)"

# Verbos/expresiones de pregunta que abren una consulta sobre un tema.
# Importante: incluir "dime", "cuéntame", "háblame", "enséñame", "explícame",
# "me puedes decir", "sabes", "conoces", "tienes idea", "explica" — TODO lo
# que el usuario dice antes del concepto.
_VERBOS_PREGUNTA = (
    r"(?:dime(?:\s+que\s+es|\s+qu\u00e9\s+es|\s+sobre|\s+de)?|"
    r"cu[ée]ntame(?:\s+sobre|\s+de|\s+que\s+es|\s+qu\u00e9\s+es)?|"
    r"h[aá]blame(?:\s+sobre|\s+de)?|"
    r"ens[ée][nñ]ame(?:\s+sobre|\s+de|\s+que\s+es)?|"
    r"expl[ií]came(?:\s+sobre|\s+de|\s+que\s+es|\s+qu\u00e9\s+es)?|"
    r"explica(?:me)?(?:\s+que\s+es|\s+qu\u00e9\s+es|\s+sobre)?|"
    r"def[ií]neme|"
    r"defini[cs]i[óo]n\s+de|definici[oó]n\s+de|significado\s+de|"
    r"qu[eé]\s+significa|qu[eé]\s+es|qu[eé]\s+son|"
    r"qui[eé]n\s+es|qui[eé]n\s+era|"
    r"cu[áa]l\s+es|cu[áa]les\s+son|"
    r"d[oó]nde\s+est[áa]|d[oó]nde\s+queda|"
    r"c[oó]mo\s+(?:funciona|funcionan|es|son|hace|sirve|sirven|trabaja|trabajan|" 
    r"se\s+hace|se\s+usa|se\s+utiliza)|"
    r"para\s+qu[eé]\s+(?:sirve|funciona|se\s+usa)|"
    r"me\s+(?:puedes?\s+|podr[ií]as?\s+)?(?:decir|explicar|contar)(?:\s+qu[eé]\s+es|\s+sobre|\s+de)?|"
    r"(?:puedes?\s+|podr[ií]as?\s+)?(?:decirme|explicarme|contarme)(?:\s+qu[eé]\s+es|\s+sobre|\s+de)?|"
    r"podr[ií]as?\s+(?:decirme|explicarme|contarme)(?:\s+qu[eé]\s+es|\s+sobre|\s+de)?|"
    r"podr[ií]as?\s+(?:decir|explicar|contar)(?:me)?(?:\s+qu[eé]\s+es|\s+sobre|\s+de)?|"
    r"sabes(?:\s+qu[eé]\s+es|\s+algo\s+sobre|\s+de)?|"
    r"conoces(?:\s+qu[eé]\s+es|\s+sobre|\s+de)?|"
    r"tienes\s+idea\s+(?:de\s+qu[eé]\s+es|de|sobre)|"
    r"alguien\s+sabe|alguien\s+conoce|"
    r"qu[ií]zame|informame|"
    r"busca|investiga|averigua|consulta"
    r")"
)

# Conectores opcionales tras el verbo.
_CONECTORES = r"(?:un|una|el|la|los|las|sobre|de(?:l)?|acerca\s+de|para)"

# Compilamos una sola vez (case-insensitive).
# Permitimos hasta DOS wake-words seguidas ("Oye Ares") y consumimos signos
# de apertura/comillas iniciales para que "¿Qué es CSS?" colapse a "css".
_RE_LIMPIAR = re.compile(
    rf"^[\s¿¡\"'`]*(?:{_WAKE}\s+){{0,2}}"   # 0..2 wake-words con espacios/signos
    rf"(?:{_VERBOS_PREGUNTA}\s+)?"          # verbo de pregunta opcional
    rf"(?:{_CONECTORES}\s+)?"               # artículo/preposición opcional
    rf"(?:{_VERBOS_PREGUNTA}\s+)?"          # 2ª pasada (cubre "dime sobre el qué es X")
    rf"(?:{_CONECTORES}\s+)?",
    re.IGNORECASE,
)

_PUNCT = " ¿?¡!.,;:\"'"


# ============================== ENTRADAS NO ÚTILES ==============================
# Muletillas, onomatopeyas y palabras sueltas que no son una pregunta clara.
# Cuando llega algo así, ARES debe ignorarlas para no contaminar la
# conversación ni iniciar búsquedas inútiles.
_MULETILLAS = {
    "ha", "ah", "aha", "ajá", "aja", "ajam", "ahh", "hum", "hmm", "mmm",
    "mm", "uhm", "uhmm", "uh", "uhh", "eh", "ehh", "oh", "ohh", "oy", "oyo",
    "uy", "ay", "ayy", "pf", "pff", "psh", "tsk", "ja", "je", "ji",
    "jaja", "jeje", "jiji", "jum", "ja ja", "je je", "jiji ja",
    "o", "u", "y", "que", "qué", "ke",
    "buf", "bah", "ñe", "ñee", "noh",
}


def es_entrada_basura(texto: str) -> bool:
    """
    True si la entrada es una muletilla / onomatopeya / palabra suelta
    que no constituye una pregunta o instrucción clara.

    Reglas (en orden):
      • Vacío o 1 sola letra → basura.
      • Letras repetidas tipo 'aaaa', 'jjjjj', 'oooo' → basura.
      • Texto está en la lista de muletillas → basura.
      • Una sola palabra muy corta (≤2 chars) que no sea sí/no → basura.
    """
    if not texto:
        return True
    t = re.sub(r"[^\wáéíóúñ\s]", "", texto.lower(), flags=re.UNICODE).strip()
    if not t:
        return True
    if len(t) <= 1:
        return True
    # Letras repetidas: aaaa, jjjj, oooo
    if re.fullmatch(r"(.)\1{2,}", t):
        return True
    # Palabra única en lista de muletillas
    if t in _MULETILLAS:
        return True
    # Una sola palabra de ≤2 caracteres que no sea afirmación/negación
    palabras = t.split()
    if len(palabras) == 1 and len(palabras[0]) <= 2 and \
            palabras[0] not in {"si", "sí", "no", "ok"}:
        return True
    return False


def _quitar_acentos(texto: str) -> str:
    """Convierte 'pythón' → 'python' sin alterar la ñ ortográficamente."""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd
                   if not unicodedata.combining(c) or c == "\u0303")


def normalizar_consulta(texto: str, *, quitar_acentos: bool = False) -> str:
    """
    Reduce una pregunta a su tema esencial.

    Ejemplos:
      "Dime qué es CSS"           → "css"
      "Explícame CSS"              → "css"
      "Cuéntame de Python por favor" → "python"
      "Háblame sobre las clases en python" → "clases en python"
      "Qué significa GraphQL"      → "graphql"
      "Sabes qué es Docker"        → "docker"

    Si `quitar_acentos=True`, también normaliza tildes para comparación.
    """
    if not texto:
        return ""
    t = texto.strip()
    # Pasada 1: quitar prefijos de pregunta/wake-words.
    t = _RE_LIMPIAR.sub("", t)
    t = t.strip(_PUNCT).lower()
    # Pasada 2: artículo suelto al inicio si quedó.
    t = re.sub(r"^(?:un|una|el|la|los|las)\s+", "", t)
    if quitar_acentos:
        t = _quitar_acentos(t)
    # Colapsar espacios.
    t = re.sub(r"\s+", " ", t).strip()
    return t


INTENCIONES = {
    "investigar": [
        "busca", "investiga", "qué es", "que es", "quién es", "quien es",
        "dime sobre", "explícame", "explicame", "averigua", "qué significa",
        "que significa"
    ],
    "ejecutar": [
        "abre", "ejecuta", "lanza", "inicia", "corre", "arranca"
    ],
    "delegar_ia": [
        "kiro", "claude code", "claude-code", "antigravity", "cursor",
        "copilot", "gemini code"
    ],
    "youtube": [
        "youtube", "pon la canción", "pon la cancion", "reproduce", "música",
        "musica", "pon música", "pon musica"
    ],
    "whatsapp": [
        "whatsapp", "manda whatsapp", "manda un whatsapp", "envía whatsapp"
    ],
    "facebook": [
        "facebook", "messenger", "manda mensaje a facebook"
    ],
    "archivo": [
        "abre archivo", "abre el archivo", "edita", "elimina", "borra",
        "crea archivo", "crea el archivo", "guarda en"
    ],
    "saludo": [
        "hola", "buenas", "buenos días", "buenos dias",
        "buenas tardes", "buenas noches"
    ],
    "personal": [
        "quién soy", "quien soy", "como me llamo", "cómo me llamo",
        "qué sabes de mí", "que sabes de mi", "mis datos", "mi historial"
    ],
    "control": [
        "detente", "para", "calla", "silencio", "cállate", "callate"
    ],
    "consultar": [
        "cómo", "como ", "cuándo", "cuando ", "dónde", "donde ",
        "por qué", "por que", "qué ", "que "
    ],
}


class AnalizadorTexto:
    """Análisis ligero de la entrada del usuario."""

    def __init__(self):
        ic(" AnalizadorTexto listo (sin LLM externo)")

    def detectar_intencion(self, texto: str) -> str:
        t = (texto or "").lower()
        # Prioridad: delegación > investigación > ejecución > resto
        orden = [
            "delegar_ia", "investigar", "youtube", "whatsapp", "facebook",
            "archivo", "ejecutar", "control", "saludo", "personal", "consultar"
        ]
        for k in orden:
            for kw in INTENCIONES[k]:
                if kw in t:
                    return k
        return "general"

    def detectar_app_destino(self, texto: str) -> str | None:
        """Cuándo se quiere delegar/abrir una app específica."""
        t = (texto or "").lower()
        for app in ("kiro", "claude code", "claude-code", "antigravity",
                    "cursor", "vscode", "vs code", "code", "terminal",
                    "cmd", "powershell", "chrome", "firefox", "edge",
                    "youtube", "whatsapp", "facebook", "spotify",
                    "discord", "notepad", "explorador"):
            if app in t:
                return app.replace(" ", "_")
        return None

    def extraer_orden_para_ia(self, texto: str) -> str:
        """
        Cuando el usuario dice 'kiro escribe X' o 'dile a kiro que X',
        extrae la X (la orden a inyectar en la IA delegada).
        """
        t = texto
        # Patrones soportados
        patrones = [
            r"(?:dile a|pídele a|pidele a)\s+(?:kiro|claude code|claude-code|antigravity|cursor)\s+(?:que\s+)?(.+)$",
            r"(?:kiro|claude code|claude-code|antigravity|cursor)\s+(?:escribe|escribir|que\s+escriba)\s+(.+)$",
            r"(?:kiro|claude code|claude-code|antigravity|cursor)\s+(?:que\s+)?(.+)$",
        ]
        for p in patrones:
            m = re.search(p, t, re.IGNORECASE)
            if m:
                orden = m.group(1).strip(' "\'.,;:')
                if orden:
                    return orden
        return ""

    def extraer_consulta_busqueda(self, texto: str) -> str:
        """De 'busca qué es python' → 'python'."""
        return re.sub(
            r"^(?:busca|investiga|dime sobre|explícame|explicame|"
            r"qué es|dime que es|que es|quién es|quien es|averigua|"
            r"qué significa|que significa)\s+",
            "", texto.strip(), flags=re.IGNORECASE
        ).strip(" ¿?¡!.,;:")


# Instancia global de análisis de intención (sin LLM externo).
analizador = AnalizadorTexto()

