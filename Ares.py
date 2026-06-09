"""
================================================================================
        ARES v3.0 — Orquestador Maestro (auth + learning + voz + RPA)
================================================================================
Pipeline cuando llega un comando (texto o voz):
  1. Verificar autenticación
  2. Detectar intención
  3. Si hay alcance "datos personales" → solo BD privada del usuario
  4. Si hay alcance "conocimiento técnico" → BD global (mente crítica + RAG)
  5. Si pide investigar → Investigador.investigar() + ingestar (mente crítica)
  6. Si pide RPA → OrquestadorAvanzado
  7. Generar respuesta personalizada por tono → hablar (TTS)
  8. Guardar interacción en BD privada (cifrada)
================================================================================
"""

from __future__ import annotations
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from icecream import ic

from Auth import auth
from BaseDeConocimiento import base_global, base_privada
from MenteCritica import mente_critica
from Investigador import investigar
from VozAres import voz
from CamaraStream import camara
from Telemetria import incrementar_comandos

try:
    from ReconocimientoFacial import reconocimiento_facial
    FACE_REC_OK = True
except Exception:
    FACE_REC_OK = False
    reconocimiento_facial = None

try:
    from OrquestadorAvanzado import (
        abrir_url, reproducir_youtube, enviar_whatsapp,
        abrir_facebook_mensaje, abrir_archivo, editar_archivo,
        eliminar_archivo, listar_directorio
    )
    ORQ_OK = True
except Exception as e:
    ic(f"orquestador avanzado no disponible: {e}")
    ORQ_OK = False

try:
    from AppLauncher import abrir_app, cerrar_app, listar_apps_instaladas
    LAUNCHER_OK = True
except Exception as e:
    ic(f"launcher no disponible: {e}")
    LAUNCHER_OK = False

try:
    from DelegadorIA import delegador
    DELEGADOR_OK = True
except Exception as e:
    ic(f"delegador IA no disponible: {e}")
    DELEGADOR_OK = False

try:
    from CopilotRPA import abrir_y_pedir_a_copilot
    COPILOT_RPA_OK = True
except Exception as e:
    ic(f"CopilotRPA no disponible: {e}")
    COPILOT_RPA_OK = False

try:
    from Cognicion import motor as cognicion
    COG_OK = True
except Exception as e:
    ic(f"Motor cognitivo no disponible: {e}")
    cognicion = None
    COG_OK = False


# ======================== TONOS / ESTILOS ========================
TONOS_PROMPT = {
    "tranquilo":  "Responde con calma, voz pausada y cercana. Frases cortas.",
    "balanceado": "Responde directo y profesional. Sin relleno. 2 frases máx.",
    "analitico":  "Responde con precisión técnica, datos y razonamiento breve.",
    "directo":    "Responde en una sola frase, sin adornos."
}

INTENCIONES = {
    # Identidad de ARES: cualquier pregunta sobre el propio asistente.
    # Va PRIMERO para que "qué es ares", "quién eres", "qué puedes hacer"
    # no caigan en 'investigar' ni en 'consultar'.
    "identidad":   ["qué eres tú", "que eres tu", "qué eres", "que eres",
                    "quién eres tú", "quien eres tu", "quién eres", "quien eres",
                    "cómo te llamas", "como te llamas", "cuál es tu nombre",
                    "cual es tu nombre", "tu nombre", "te llamas",
                    "qué es ares", "que es ares", "quién es ares", "quien es ares",
                    "qué significa ares", "que significa ares",
                    "qué puedes hacer", "que puedes hacer",
                    "qué sabes hacer", "que sabes hacer",
                    "para qué sirves", "para que sirves",
                    "cómo funcionas", "como funcionas",
                    "cómo trabajas", "como trabajas",
                    "quién te creó", "quien te creo", "quién te hizo", "quien te hizo",
                    "tu creador", "quién te programó", "quien te programo",
                    "tus límites", "tus limites", "tus capacidades",
                    "qué tipo de asistente", "que tipo de asistente",
                    "eres una ia", "eres un bot", "eres humano",
                    "háblame de ti", "hablame de ti", "preséntate", "presentate"],
    "investigar":  ["busca", "investiga", "qué es", "quién es", "dime sobre",
                    "explícame", "explicame", "averigua"],
    # Aceptar/rechazar la edición que Copilot acaba de proponer.
    # Va ANTES que 'delegar_ia' para que "dale al keep" no caiga en Copilot.
    "copilot_decision": [
        "dale siguiente", "siguiente en copilot", "dale al keep",
        "dale keep", "dale al siguiente", "presiona keep", "presiona el keep",
        "haz clic en keep", "click en keep", "clickea keep",
        "acepta los cambios", "acepta el cambio",
        "aprueba los cambios", "aprueba el cambio",
        "aceptar copilot", "guarda los cambios de copilot",
        "mantén los cambios", "manten los cambios",
        # Variantes naturales adicionales
        "dale a keep", "dale al boton keep", "dale al botón keep",
        "presiona el boton keep", "presiona el botón keep",
        "haz keep", "haz el keep", "tocale al keep", "tócale al keep",
        "clic en keep", "clickeale al keep", "clickéale al keep",
        "acéptalo", "aceptalo", "acepta copilot", "guardar los cambios",
        "ok keep", "ok al keep",
        # Rechazar
        "dale al undo", "dale undo", "presiona undo", "click en undo",
        "rechaza los cambios", "rechaza el cambio",
        "deshaz los cambios", "deshaz el cambio",
        "descarta los cambios", "descarta el cambio",
        "dale a undo", "dale al boton undo", "dale al botón undo",
        "haz undo", "haz el undo", "tocale al undo", "tócale al undo",
        "deshazlo", "rechazalo", "recházalo", "descártalo", "descartalo",
    ],
    # Abrir un proyecto/carpeta en un editor (sin pedir nada a Copilot).
    # Va ANTES que 'delegar_ia' y 'editor' para que "abre el proyecto X en
    # vs code" no caiga en otro flujo.
    "abrir_proyecto": ["abre el proyecto", "abre la carpeta del proyecto",
                       "abre la carpeta", "abre el repositorio",
                       "abre el repo", "abre el directorio",
                       "abrir proyecto", "abrir el proyecto",
                       "abrir la carpeta", "abrir repositorio",
                       "abre el workspace", "abrir workspace"],
    # Delegar a IA: gana cuando hay "en el chat" o nombre de IA explícito.
    # Va ANTES que 'editor' para que "abre visual y escribe en el chat" no
    # se interprete como crear archivo.
    "delegar_ia":  ["en el chat", "antigravity", "claude code", "claude-code",
                    "kiro escribe", "kiro que", "dile a kiro", "dile a claude",
                    "dile a antigravity", "dile a copilot",
                    "pídele a kiro", "pídele a claude",
                    # Copilot — variantes naturales del usuario
                    "copilot",  "en copilot", "y copilot",
                    "copilot escribe", "copilot que",
                    "con copilot", "con copilot escribe",
                    "escribe en copilot", "abre copilot",
                    "abre el chat", "manda al chat",
                    # Crear módulo nuevo (también va por delegar_ia para que
                    # entre el flujo de Copilot)
                    "crea un nuevo modulo", "crea un nuevo módulo",
                    "crea un modulo", "crea un módulo",
                    "crea un nuevo archivo en el proyecto",
                    "crear modulo", "crear módulo",
                    "nuevo modulo llamado", "nuevo módulo llamado",
                    "escribe en el chat de copilot",
                    "escribe en el chat de cursor",
                    "escribe en el chat de windsurf",
                    "escribe en el chat de antigravity",
                    "escribe en el chat de claude",
                    "escribe en el chat de kiro",
                    "escribe en el chat de visual",
                    "escribe en el chat de vs code",
                    "escribe en el chat de vscode"],
    # Editores: "crea archivo X", "abre visual y crea/escribe", "edita …"
    "editor":      ["crea archivo", "crea el archivo", "crea un archivo",
                    "nuevo archivo",
                    "abre visual", "abre vs code", "abre vscode",
                    "abre cursor", "abre windsurf", "abre sublime",
                    "abre notepad", "edita el archivo", "edita archivo",
                    "escribe en el archivo", "escribe en archivo",
                    "guarda el archivo", "agrega al archivo",
                    "añade al archivo", "anade al archivo"],
    "ejecutar":    ["abre", "ejecuta", "lanza", "inicia", "corre"],
    "youtube":     ["youtube", "pon la canción", "pon la cancion",
                    "reproduce", "música", "musica",
                    "pon música", "pon musica", "pon una canción",
                    "pon una cancion"],
    "whatsapp":    ["whatsapp", "manda whatsapp", "mensaje a whatsapp",
                    "guarda el contacto", "guardar contacto",
                    "mándale", "mandale", "mensaje a", "manda un mensaje",
                    "manda mensaje"],
    "facebook":    ["facebook", "messenger", "manda mensaje a facebook"],
    "archivo":     ["abre archivo", "edita", "elimina", "borra"],
    "saludo":      ["hola", "buenas", "buenos días", "buenas tardes", "buenas noches"],
    "personal":    ["quién soy", "como me llamo", "qué sabes de mí", "mis datos",
                    "mi historial"],
    # Onboarding personalizado: ARES hace preguntas para conocer al usuario.
    "onboarding":  ["aprende sobre mí", "aprende sobre mi",
                    "aprende sobre mi", "aprende cosas de mí",
                    "configúrame", "configurame", "personalízate",
                    "personalizate", "quiero contarte sobre mí",
                    "quiero contarte sobre mi",
                    "preséntate conmigo", "conoceme", "conóceme",
                    "conocer al usuario"],
    # Matemáticas (ganan a 'consultar' y 'general' por orden del dict).
    "matematica":  ["calcula", "calcúlame", "calculame", "cálculo",
                    "cuánto es", "cuanto es", "cuánto da", "cuanto da",
                    "resuelve", "resuélveme", "resuelveme",
                    "el resultado de", "qué resulta", "que resulta",
                    "raíz cuadrada", "raiz cuadrada", "factorial",
                    "logaritmo", "porciento de", "por ciento de",
                    "elevado a", "al cuadrado", "al cubo"],
    # Hora y fecha
    "hora":        ["qué hora", "que hora", "hora es", "qué hora es",
                    "que hora es", "dime la hora", "qué día", "que dia",
                    "qué fecha", "que fecha", "fecha de hoy",
                    "qué día es hoy", "que dia es hoy"],
    # Clima
    "clima":       ["clima", "temperatura", "qué tiempo", "que tiempo",
                    "tiempo hace", "está lloviendo", "esta lloviendo",
                    "hace frío", "hace frio", "hace calor", "pronóstico",
                    "pronostico"],
    "control":     ["detente", "para", "calla", "silencio"],
    # Registro de usuario: cuando Ares pregunta el nombre de una persona nueva
    "registrar_usuario": ["me llamo", "soy", "mi nombre es", "llámame"],
    # Charla casual / cortesía / agradecimientos: no debe ir a investigar.
    "charla":      ["cómo estás", "como estas", "qué tal", "que tal",
                    "qué cuentas", "que cuentas", "qué haces", "que haces",
                    "gracias", "muchas gracias", "te quiero",
                    "perdón", "perdon", "lo siento", "ok ", "vale ",
                    "jaja", "jeje", "jiji", "jum", "ah",
                    "buen día", "buen dia", "feliz día", "feliz dia",
                    "nos vemos", "adiós", "adios", "chao", "chau", "bye",
                    "okey", "ok", "okay", "super", "perfecto", "perfecta",
                    "bueno", "buena", "excelente", "genial", "fantástico",
                    "fantastica", "increíble", "increible", "bien", "muy bien",
                    "estupendo", "estupenda", "brillante", "chévere", "chévere"],
    "consultar":   ["cómo", "cuándo", "dónde", "por qué", "qué"]
}


def detectar_intencion(texto: str) -> str:
    t = (texto or "").lower()
    for intent, keys in INTENCIONES.items():
        for k in keys:
            if k in t:
                return intent
    return "general"


# Respuestas de confirmación / negación para seguimiento conversacional
_AFIRMACIONES = {
    "si", "sí", "claro", "dale", "ok", "okay", "vale", "bueno", "hazlo",
    "busca", "búscalo", "buscalo", "investiga", "investígalo", "investigalo",
    "por favor", "porfa", "obvio", "afirmativo", "sip", "sí claro", "si claro",
    "adelante", "hágalo", "hagalo", "claro que si", "claro que sí"
}
_NEGACIONES = {
    "no", "nop", "negativo", "déjalo", "dejalo", "no gracias", "no hace falta",
    "olvídalo", "olvidalo", "mejor no", "después", "despues"
}


def _normaliza(texto: str) -> str:
    return re.sub(r"[^\wáéíóúñ\s]", "", (texto or "").lower()).strip()


def _es_afirmacion(texto: str) -> bool:
    t = _normaliza(texto)
    if not t:
        return False
    if t in _AFIRMACIONES:
        return True
    # frases cortas que empiezan por una afirmación ("si busca eso", "dale")
    primera = t.split()[0]
    return primera in {"si", "sí", "claro", "dale", "ok", "vale", "hazlo",
                       "adelante", "obvio", "sip"}


def _es_negacion(texto: str) -> bool:
    t = _normaliza(texto)
    if not t:
        return False
    if t in _NEGACIONES:
        return True
    return t.split()[0] in {"no", "nop", "negativo"}


# Frases que aluden al tema previo y deben rellenarse con `_ultimo_tema`.
# "y de eso", "cuéntame más", "dame más detalles", "amplía", "explícame más"...
_RE_REFERENCIA_TEMA = re.compile(
    r"^(?:y\s+|y\s+de\s+|y\s+sobre\s+|sobre\s+eso|sobre\s+esto|de\s+eso|"
    r"cu[ée]ntame\s+m[áa]s|dame\s+m[áa]s|m[áa]s\s+(?:info|detalles|sobre)|"
    r"ampl[ií]a|prof[uú]ndiza|"
    # "explica más", "explícame más", "explicame mas", "expli camas" (typos)
    r"expl[ií]ca(?:me)?\s+m[áa]s|"
    r"dime\s+m[áa]s|h[áa]blame\s+m[áa]s|"
    r"otra\s+cosa\s+sobre|"
    r"y\s+(?:eso|esto|aquello))",
    re.IGNORECASE
)

# Detecta pronombres posesivos que se refieren al tema anterior
# "sus funciones", "su funcionamiento", "lo que hace", "la característica"
_RE_PRONOMBRE_POSESIVO = re.compile(
    r"^(?:cu[áa]les?\s+(?:son|es)|qu[ée]\s+(?:es|son)|c[óo]mo\s+(?:es|funciona)|"
    r"qu[ée]\s+hace|para\s+qu[ée]\s+(?:sirve|es)|dime\s+(?:m[áa]s|sobre)|"
    r"expl[íi]came|m[áa]s\s+info(?:rmaci[óo]n)?)\s+"
    r"(?:sus|su|lo|la|el|los|las)\s+",
    re.IGNORECASE
)


def _es_referencia_tema_previo(texto: str) -> bool:
    """¿Es una frase que apela al último tema sin nombrarlo?
    Ej.: "y de eso?", "cuéntame más", "amplía sobre eso", "dame detalles"."""
    if not texto:
        return False
    t = texto.strip().lower()
    if not t:
        return False
    if _RE_REFERENCIA_TEMA.match(t):
        return True
    # "eso", "ese tema", "esto" sueltos
    if t in {"eso", "esto", "ese tema", "este tema", "lo mismo", "más",
             "mas", "y?", "y eso?", "amplía", "amplia"}:
        return True
    return False


def _tiene_pronombre_referencial(texto: str) -> bool:
    """¿Es una pregunta que usa pronombres (sus, su, lo, la, el) que podrían
    referirse al tema anterior? Ej.: "¿Cuáles son sus funciones principales?"
    """
    if not texto:
        return False
    t = texto.strip().lower()
    if not t:
        return False
    return bool(_RE_PRONOMBRE_POSESIVO.match(t))


def _sustituir_pronombre_con_tema(texto: str, tema: str) -> str:
    """Sustituye pronombres referenciales (sus, su, lo, la, el) con el tema anterior.
    Ej.: "¿Cuáles son sus funciones?" + "sistema operativo" 
         → "¿Cuáles son las funciones del sistema operativo?"
    """
    if not texto or not tema:
        return texto
    
    t = texto.strip()
    
    # Para "sus" o "su", necesitamos mover el tema al final de la frase
    # Ej: "¿Cuáles son sus funciones principales?" 
    #     → "¿Cuáles son las funciones del sistema operativo?"
    
    # Detectar si hay pronombre posesivo
    if re.search(r"\b(sus|su)\s+", t, re.IGNORECASE):
        # Extraer la parte antes del pronombre y después
        match = re.search(r"^(.+?)\b(sus|su)\s+(.+)$", t, re.IGNORECASE)
        if match:
            antes = match.group(1).strip()
            despues = match.group(3).strip()
            # Construir nueva frase: antes + despues + "del" + tema
            # Eliminar signos de puntuación del final para reorganizar
            despues_limpio = re.sub(r"[¿?¡!.,;:]$", "", despues).strip()
            resultado = f"{antes} {despues_limpio} del {tema}"
            # Restaurar signos de puntuación si los había
            if re.search(r"[¿?¡!.,;:]$", t):
                resultado += "?"
            return resultado
    
    return t


def _menciona_a_ares(texto: str) -> bool:
    """¿La pregunta es sobre el propio asistente (no para activarlo)?
    Detecta frases como 'qué es ares', 'cuéntame de ares', 'háblame sobre
    ares' donde 'ares' aparece como sujeto, no como wake-word inicial.
    """
    if not texto:
        return False
    t = (texto or "").lower()
    # Patrones donde 'ares' es sujeto/objeto, no wake-word inicial.
    patrones = [
        r"\bque\s+es\s+ares\b", r"\bqu[eé]\s+es\s+ares\b",
        r"\bquien\s+es\s+ares\b", r"\bqui[eé]n\s+es\s+ares\b",
        r"\bsobre\s+ares\b", r"\bde\s+ares\b",
        r"\bh[áa]blame\s+(?:de|sobre)\s+ares\b",
        r"\bcu[eé]ntame\s+(?:de|sobre)\s+ares\b",
        r"\bque\s+significa\s+ares\b", r"\bqu[eé]\s+significa\s+ares\b",
        r"\bquien\s+te\s+(?:cre[oó]|hizo|programo|program[oó])\b",
    ]
    return any(re.search(p, t) for p in patrones)


# Frases cortas de seguimiento que tras un envío a Copilot significan
# "acepta lo que propuso" (Keep). Se evalúan SOLO cuando hay una edición
# pendiente reciente, así no contaminan el resto de la conversación.
_SEGUIMIENTO_COPILOT = {
    "siguiente", "next", "dale", "dale ya", "dale dale", "ok", "okay",
    "listo", "ya", "vale", "perfecto", "bien", "continua", "continúa",
    "sigue", "adelante", "avanza", "siguenle", "síguele", "go",
    "mantenlo", "mantenlos", "déjalo", "dejalo", "déjalos", "dejalos",
}


def _es_seguimiento_copilot(texto: str) -> bool:
    """¿Es una frase corta del estilo 'siguiente'/'dale'/'ok' que tras un
    envío a Copilot significa 'pulsa Keep'? Solo dispara con frases ≤3
    palabras para no atrapar 'dale a esto otro' u otras intenciones."""
    t = _normaliza(texto)
    if not t:
        return False
    palabras = t.split()
    if len(palabras) > 3:
        return False
    if t in _SEGUIMIENTO_COPILOT:
        return True
    return palabras[0] in _SEGUIMIENTO_COPILOT


def _extraer_tema(texto: str) -> str:
    """Reduce la pregunta a su tema esencial. Delega en PLNOptimizado para
    que TODOS los puntos del sistema (intent_general, investigador, BD)
    compartan la misma lógica de normalización."""
    try:
        from PLNOptimizado import normalizar_consulta
        tema = normalizar_consulta(texto)
        if tema:
            return tema
    except Exception as e:
        ic(f"normalizar_consulta no disponible: {e}")
    # Fallback (legacy) si PLN no está cargado todavía
    t = (texto or "").strip()
    t = re.sub(
        r"^(?:oye\s+|ares\s+|jarvis\s+)?"
        r"(?:qué|que|cuál|cual|quién|quien|cómo|como|dónde|donde|cuándo|cuando|"
        r"dime|cuéntame|cuentame|háblame|hablame|explícame|explicame|"
        r"enséñame|ensename)\s+"
        r"(?:es|son|era|significa|funciona|hace|sirve|quiere decir|sobre|de)?\s*"
        r"(?:un|una|el|la|los|las|para)?\s*",
        "", t, flags=re.IGNORECASE
    )
    return t.strip(" ¿?¡!.,;:")


# ======================== ARES v3 ========================
class ARES:

    def __init__(self):
        ic("ARES — Iniciando")
        self.historial_sesion: List[Dict[str, Any]] = []
        self._on_event = None  # callback hacia el frontend (SSE / poll)
        self._tema_pendiente: Optional[str] = None  # tema que ARES ofreció buscar
        # Resultado de la última búsqueda exitosa pendiente de confirmar guardado
        self._guardado_pendiente: Optional[Dict[str, Any]] = None
        # Último proyecto usado con Copilot (para no tener que repetirlo)
        self._ultimo_proyecto: Optional[str] = None
        # Mientras está True, frases ambiguas como "siguiente", "dale", "ok"
        # se interpretan como "aceptar la edición de Copilot" (Keep). Lo
        # activa _intent_delegar_ia tras enviar la instrucción a Copilot, y
        # se desactiva cuando se aplica un keep/undo o pasan ~3 minutos.
        self._copilot_pendiente: bool = False
        self._copilot_pendiente_ts: float = 0.0
        # Estado del onboarding "aprende sobre mí" (Q&A multi-turno).
        # Cuando hay estado activo, el siguiente input se interpreta como
        # respuesta a la pregunta actual.
        self._onboarding: Optional[Dict[str, Any]] = None
        # Último tema sobre el que ARES respondió (para mantener hilo de
        # conversación). Se usa para que frases cortas tipo "y de eso?",
        # "cuéntame más", "amplía" se entiendan como referencias al tema
        # anterior. Se actualiza en cada respuesta de tipo investigar/
        # general/identidad.
        self._ultimo_tema: Optional[str] = None
        self._ultimo_tema_ts: float = 0.0
        # Estado de reconocimiento facial: esperando nombre de nuevo usuario
        self._esperando_nombre_usuario: bool = False
        ic(" ARES listo")

    # ------------------------ EVENT BUS ------------------------
    def set_event_callback(self, cb) -> None:
        self._on_event = cb

    def _emit(self, evento: str, payload: Dict[str, Any]) -> None:
        if self._on_event:
            try:
                self._on_event(evento, payload)
            except Exception as e:
                ic(f"event cb error: {e}")

    # ------------------------ ENTRADA PRINCIPAL ------------------------
    def procesar(self, entrada: str, hablar_respuesta: bool = True) -> Dict[str, Any]:
        """
        Procesa una entrada del usuario (texto o transcripción de voz).
        Devuelve dict con {respuesta, intencion, latencia_s, ...}.
        """
        t0 = time.time()
        entrada = (entrada or "").strip()
        ic(f"\n[{auth.usuario_actual or 'anon'}] {entrada}")

        if not entrada:
            return {"respuesta": "", "intencion": "vacio"}

        if not auth.autenticado:
            r = "Debes iniciar sesión para que pueda asistirte."
            if hablar_respuesta: voz.hablar(r)
            return {"respuesta": r, "intencion": "auth_requerida"}

        # ---- Filtro de entrada basura: muletillas/onomatopeyas/letras
        # repetidas tipo "ha", "que", "o", "aaaa". No son una pregunta
        # clara: ARES las ignora silenciosamente para no contaminar el
        # hilo de conversación ni disparar búsquedas absurdas. Solo se
        # ignora si NO hay un estado conversacional pendiente que pueda
        # querer interpretarlas (onboarding, copilot pendiente, etc.).
        try:
            from PLNOptimizado import es_entrada_basura
            es_basura = es_entrada_basura(entrada)
        except Exception:
            es_basura = False
        if es_basura and not self._onboarding \
                and not self._copilot_pendiente_activo() \
                and not self._guardado_pendiente \
                and not self._tema_pendiente:
            ic("Entrada considerada muletilla/basura — ignorada")
            return {"respuesta": "", "intencion": "ignorado"}

        # Si estamos esperando el nombre de un nuevo usuario, intentar registrarlo
        if self._esperando_nombre_usuario and FACE_REC_OK and reconocimiento_facial:
            # Si la entrada es corta y parece un nombre, registrarla
            if len(entrada.split()) <= 3 and not any(k in entrada.lower() for k in ["abre", "busca", "investiga", "qué", "que", "cómo", "como"]):
                # Tratar como nombre
                nombre = entrada.strip()
                import re
                nombre = re.sub(r'[¿?¡!.,;:]', '', nombre).strip().capitalize()
                if nombre and len(nombre) > 1:
                    if reconocimiento_facial.confirmar_registro(nombre):
                        self._esperando_nombre_usuario = False
                        r = f"¡Un gusto, {nombre}! Te he registrado en mi sistema."
                        if hablar_respuesta: voz.hablar(r)
                        return {"respuesta": r, "intencion": "registrar_usuario"}

        intencion = detectar_intencion(entrada)

        # Si la entrada menciona explícitamente a 'ares' como sujeto, la
        # tratamos como pregunta de identidad sin importar lo que detecte
        # el matcher por defecto.
        if _menciona_a_ares(entrada):
            intencion = "identidad"

        # Si la entrada es una referencia al tema previo ("cuéntame más",
        # "y de eso?", "amplía"), reescribimos la consulta sustituyendo
        # la referencia por el último tema. Eso da continuidad al hilo y
        # mejora el filtraje de búsqueda externa y memoria.
        if _es_referencia_tema_previo(entrada) and self._ultimo_tema \
                and intencion in {"general", "consultar", "investigar"}:
            ic(f"Referencia al tema previo: '{self._ultimo_tema}'")
            entrada = f"explícame más sobre {self._ultimo_tema}"
            intencion = "investigar"

        # Si la entrada contiene pronombres referenciales (sus, su, lo, la, el)
        # y hay un tema previo, sustituimos el pronombre con el tema para
        # mantener el contexto. Ej.: "¿Cuáles son sus funciones?" →
        # "¿Cuáles son las funciones del sistema operativo?"
        if _tiene_pronombre_referencial(entrada) and self._ultimo_tema \
                and intencion in {"general", "consultar", "investigar"}:
            ic(f"Pronombre referencial detectado, sustituyendo con tema: '{self._ultimo_tema}'")
            entrada = _sustituir_pronombre_con_tema(entrada, self._ultimo_tema)
            # La intención puede cambiar a "investigar" para buscar específicamente
            # sobre el tema con el contexto aplicado
            if intencion == "general":
                intencion = "investigar"

        ic(f"Intención: {intencion}")

        # ---- Si hace poco delegamos a Copilot, frases ambiguas cortas
        #      ("siguiente", "dale", "ok", "listo") significan "Keep".
        if self._copilot_pendiente_activo() and intencion == "general" \
                and _es_seguimiento_copilot(entrada):
            ic("Reinterpretando como copilot_decision (Copilot pendiente)")
            intencion = "copilot_decision"

        # ---- Si hay onboarding activo, esta entrada es la respuesta a la
        #      pregunta actual (a menos que el usuario diga "cancelar").
        if self._onboarding and not _es_negacion(entrada) and \
                "cancela" not in entrada.lower() and \
                "cancelar" not in entrada.lower():
            data = self._onboarding_responder(entrada)
            intencion = "onboarding"
        elif self._onboarding and (_es_negacion(entrada) or
                                     "cancela" in entrada.lower()):
            self._onboarding = None
            data = {"respuesta": "Vale, dejamos la personalización para otro momento."}
            intencion = "control"
        # ---- Seguimiento conversacional: ¿confirma guardar lo recién encontrado? ----
        elif self._guardado_pendiente and _es_afirmacion(entrada):
            data = self._guardar_pendiente()
            intencion = "guardar"
        elif self._guardado_pendiente and _es_negacion(entrada):
            self._guardado_pendiente = None
            data = {"respuesta": "Ok, no lo guardo."}
            intencion = "control"
        # ---- Si hay 'guardado pendiente' pero el usuario NO contesta sí
        #      ni no, sino que hace una NUEVA pregunta, lo tratamos como
        #      negación implícita: descartamos el pendiente y procesamos
        #      la entrada actual con prioridad.
        elif self._guardado_pendiente:
            ic("Guardado pendiente descartado (el usuario hizo otra pregunta)")
            self._guardado_pendiente = None
            # Cae al despachador normal con la intención original.
            data = self._despachar(intencion, entrada)
        # ---- Seguimiento conversacional: ¿confirma una búsqueda pendiente? ----
        elif self._tema_pendiente and _es_afirmacion(entrada):
            tema = self._tema_pendiente
            self._tema_pendiente = None
            ic(f"Confirmación recibida — buscando tema pendiente: {tema}")
            data = self._intent_investigar(tema, forzar_web=True)
            intencion = "investigar"
        elif self._tema_pendiente and _es_negacion(entrada):
            self._tema_pendiente = None
            data = {"respuesta": "De acuerdo, lo dejamos así."}
            intencion = "control"
        # ---- Si hay 'tema pendiente' pero el usuario hace otra pregunta
        #      sin confirmar, descartamos y procesamos la nueva.
        elif self._tema_pendiente:
            ic("Tema pendiente descartado (el usuario hizo otra pregunta)")
            self._tema_pendiente = None
            data = self._despachar(intencion, entrada)
        # ---- Despachar ----
        else:
            data = self._despachar(intencion, entrada)

        respuesta = data.get("respuesta", "Listo.")

        # Recordar tema pendiente si ARES ofreció buscarlo (para el "sí" siguiente)
        if data.get("tema_pendiente"):
            self._tema_pendiente = data["tema_pendiente"]

        # Recordar el último tema tratado para mantener el hilo de
        # conversación. Aceptamos el `tema` que devolvió el handler o,
        # si no, lo deducimos de la entrada cuando la intención es de
        # tipo informativo (investigar / general).
        tema_actual = data.get("tema")
        if not tema_actual and intencion in {"investigar", "general"}:
            tema_actual = _extraer_tema(entrada) or None
        if tema_actual:
            self._ultimo_tema = tema_actual
            self._ultimo_tema_ts = time.time()

        # Personalizar por tono
        respuesta = self._aplicar_tono(respuesta)

        # Adaptar respuesta según expresión facial si está disponible
        if FACE_REC_OK and reconocimiento_facial:
            respuesta = self._aplicar_expresion(respuesta)

        # Voz
        if hablar_respuesta and respuesta:
            voz.hablar(respuesta)
            self._emit("hablar", {"texto": respuesta})

        # Guardar en BD privada (cifrada)
        try:
            base_privada.guardar_interaccion(entrada, respuesta,
                                              {"intencion": intencion})
        except Exception as e:
            ic(f"guardar privado: {e}")

        # Registrar comando
        auth.incrementar_comandos()
        incrementar_comandos()

        latencia = time.time() - t0
        self.historial_sesion.append({
            "entrada":   entrada,
            "respuesta": respuesta,
            "intencion": intencion,
            "ts":        datetime.now().isoformat(),
            "latencia":  round(latencia, 2)
        })

        ic(f"→ {respuesta}  ({latencia:.2f}s)")

        return {
            "respuesta": respuesta,
            "intencion": intencion,
            "latencia_s": round(latencia, 2),
            **{k: v for k, v in data.items() if k != "respuesta"}
        }

    # ------------------------ DESPACHADOR ------------------------
    def _despachar(self, intencion: str, entrada: str) -> Dict[str, Any]:
        """Mapea una intención a su handler. Centralizado para reutilizar
        desde varios puntos de `procesar` (cuando hay pendientes que se
        descartan)."""
        if intencion == "investigar":
            return self._intent_investigar(entrada)
        if intencion == "copilot_decision":
            return self._intent_copilot_decision(entrada)
        if intencion == "abrir_proyecto":
            return self._intent_abrir_proyecto(entrada)
        if intencion == "editor":
            return self._intent_editor(entrada)
        if intencion == "delegar_ia":
            return self._intent_delegar_ia(entrada)
        if intencion == "identidad":
            return self._intent_identidad(entrada)
        if intencion == "matematica":
            return self._intent_matematica(entrada)
        if intencion == "hora":
            return self._intent_hora(entrada)
        if intencion == "clima":
            return self._intent_clima(entrada)
        if intencion == "onboarding":
            return self._intent_onboarding(entrada)
        if intencion == "ejecutar":
            return self._intent_ejecutar(entrada)
        if intencion == "youtube":
            return self._intent_youtube(entrada)
        if intencion == "whatsapp":
            return self._intent_whatsapp(entrada)
        if intencion == "facebook":
            return self._intent_facebook(entrada)
        if intencion == "archivo":
            return self._intent_archivo(entrada)
        if intencion == "personal":
            return self._intent_personal(entrada)
        if intencion == "saludo":
            return self._intent_saludo()
        if intencion == "charla":
            return self._intent_charla(entrada)
        if intencion == "registrar_usuario":
            return self._intent_registrar_usuario(entrada)
        if intencion == "control":
            return self._intent_control(entrada)
        return self._intent_general(entrada)

    # ------------------------ IDENTIDAD ------------------------
    def _intent_identidad(self, entrada: str) -> Dict[str, Any]:
        """Responde preguntas sobre el propio asistente.

        Las respuestas dependen del tono activo del usuario: el modo
        analítico devuelve descripciones técnicas y largas, el directo
        una sola frase, el tranquilo cercano y el balanceado intermedio.
        """
        try:
            from Cognicion import responder_identidad
        except Exception:
            return {"respuesta":
                    "Soy ARES, Asistente de Reconocimiento y Ejecución de Software."}
        perfil = auth.perfil_actual() or {}
        tono = perfil.get("tono", "balanceado")
        t = (entrada or "").lower()

        # Sub-tema según las palabras clave de la pregunta
        if any(k in t for k in ("cómo te llamas", "como te llamas",
                                  "cuál es tu nombre", "cual es tu nombre",
                                  "tu nombre", "te llamas")):
            sub = "nombre"
        elif any(k in t for k in ("cómo funcionas", "como funcionas",
                                    "cómo trabajas", "como trabajas",
                                    "cómo lo haces", "como lo haces")):
            sub = "como_funcionas"
        elif any(k in t for k in ("qué puedes hacer", "que puedes hacer",
                                    "qué sabes hacer", "que sabes hacer",
                                    "para qué sirves", "para que sirves",
                                    "tus capacidades")):
            sub = "que_haces"
        elif any(k in t for k in ("quién te creó", "quien te creo",
                                    "quién te hizo", "quien te hizo",
                                    "quién te programó", "quien te programo",
                                    "tu creador")):
            sub = "creador"
        elif any(k in t for k in ("tus límites", "tus limites",
                                    "qué no puedes", "que no puedes",
                                    "limitaciones")):
            sub = "limites"
        else:
            sub = "que_eres"

        respuesta = responder_identidad(sub, tono=tono)
        return {"respuesta": respuesta,
                "fuente": "identidad",
                "subtema": sub,
                "tema": "ares"}

    # ------------------------ INTENCIONES ------------------------
    def _intent_investigar(self, entrada: str,
                           forzar_web: bool = False) -> Dict[str, Any]:
        # Limpiar comando con el normalizador centralizado
        consulta = _extraer_tema(entrada) or entrada.strip()

        if not consulta:
            return {"respuesta": "¿Qué quieres que investigue?"}

        perfil = auth.perfil_actual() or {}
        tono = perfil.get("tono", "balanceado")

        # 1) Antes de ir a Google, ¿lo sabe ya? (si no se fuerza la web)
        if not forzar_web:
            ya_se = base_global.mejor_concepto(consulta)
            if ya_se and ya_se.get("calidad", 0) >= 0.65 \
                    and ya_se.get("similitud", 0) >= 0.55:
                ic("Concepto consolidado — usando memoria")
                base_global.confirmar_concepto(ya_se["tema"], ya_se["descripcion"])
                descripcion = base_global.descripcion_para_tono(ya_se, tono)
                return {
                    "respuesta": descripcion,
                    "fuente":    "memoria_global",
                    "tema":      ya_se.get("tema"),
                    "calidad":   ya_se.get("calidad")
                }

        # 2) Ir a la web
        self._emit("estado", {"estado": "investigando"})
        res = investigar(consulta)

        if not res.get("ok"):
            # Recordar el tema para reintentar si el usuario insiste
            return {
                "respuesta": f"No pude encontrar información clara sobre {consulta}. "
                             f"¿Quieres que lo intente de nuevo?",
                "tema_pendiente": consulta,
                "tema": consulta,
                "fuente": "sin_resultado"
            }

        descripcion = res["descripcion"]
        tema        = res["tema"]

        # 3) Mente crítica: evalúa pero NO guarda todavía. El usuario decide.
        ev = mente_critica.evaluar(tema, descripcion)

        if not ev["aceptado"]:
            # La mente crítica lo rechaza: lo registramos como rechazo y
            # respondemos sin ofrecer guardarlo.
            base_global.registrar_rechazo(
                tema, descripcion,
                autor_username=auth.usuario_actual or "anon",
                razon=ev["razon"]
            )
            ic(f"Rechazado por mente crítica: {ev['razon']}")
            return {
                "respuesta": (f"{descripcion}\n\n"
                              f"(Esto no parece correcto: {ev['razon']}. "
                              f"No voy a guardarlo.)"),
                "fuente":    "google",
                "url":       res.get("url"),
                "tema":      tema,
                "ingerido":  False
            }

        # 4) Aceptado por la mente crítica → mostrar y pedir confirmación.
        # La descripción se adapta al tono activo para mantener coherencia.
        try:
            from Cognicion import adaptar_respuesta_a_tono
            descripcion_mostrada = adaptar_respuesta_a_tono(descripcion, tono)
        except Exception:
            descripcion_mostrada = descripcion
        self._guardado_pendiente = {
            "tema":        tema,
            "descripcion": descripcion,   # guardamos la versión completa
            "fuente":      res.get("fuente", "google"),
            "calidad":     ev["calidad"],
            "tono":        tono,
        }
        return {
            "respuesta": f"{descripcion_mostrada}\n\n¿Lo guardo?",
            "fuente":    "google",
            "url":       res.get("url"),
            "tema":      tema,
            "ingerido":  False  # todavía no, espera confirmación
        }

    def _guardar_pendiente(self) -> Dict[str, Any]:
        """Persiste el resultado pendiente cuando el usuario confirma.

        Estrategia de ingesta enriquecida: además del párrafo completo
        (descripción "principal"), partimos el snippet en oraciones y
        guardamos cada una como un hecho adicional sobre el mismo tema con
        calidad ligeramente menor. Así `mejor_concepto` puede consolidar
        múltiples afirmaciones del mismo concepto y dar respuestas más
        precisas cuando alguien pregunta variantes ("dime qué es X",
        "para qué sirve X", "cómo funciona X").
        """
        pend = self._guardado_pendiente
        self._guardado_pendiente = None
        if not pend:
            return {"respuesta": "No tengo nada pendiente de guardar."}
        try:
            tema = pend["tema"]
            descripcion = pend["descripcion"]
            calidad = pend.get("calidad", 0.6)
            fuente = pend.get("fuente", "google")
            tono = pend.get("tono", "balanceado")
            autor = auth.usuario_actual or "anon"

            # 1) Hecho principal (descripción completa)
            base_global.agregar_hecho(
                tema, descripcion, autor_username=autor,
                calidad=calidad, fuente=fuente, tono=tono
            )

            # 2) Hechos atómicos: cada oración relevante como pieza
            #    independiente, con calidad un punto por debajo.
            extras = self._fragmentar_descripcion(descripcion)
            for frag in extras:
                if frag == descripcion:
                    continue  # ya está como principal
                base_global.agregar_hecho(
                    tema, frag, autor_username=autor,
                    calidad=max(0.3, calidad - 0.15),
                    fuente=f"{fuente}_frag",
                    tono=tono
                )

            ic(f"Guardado en memoria global: {tema} "
               f"({1 + len(extras)} versiones)")
            return {"respuesta": f"Guardado. Lo recordaré sobre '{tema}'.",
                    "ingerido": True, "tema": tema,
                    "fragmentos_guardados": 1 + len(extras)}
        except Exception as e:
            ic(f"guardar pendiente: {e}")
            return {"respuesta": "No pude guardar. Inténtalo más tarde."}

    @staticmethod
    def _fragmentar_descripcion(texto: str, max_frags: int = 4) -> List[str]:
        """Parte el texto en oraciones cortas y útiles, dedupea y limita."""
        if not texto:
            return []
        # Cortar por puntos finales / signos de exclamación / interrogación
        crudas = re.split(r"(?<=[\.!?])\s+", texto.strip())
        salida: List[str] = []
        vistos = set()
        for fr in crudas:
            f = fr.strip(" .,;:")
            if not f or len(f) < 25:
                continue  # demasiado corto para ser una afirmación útil
            sig = f.lower()[:80]
            if sig in vistos:
                continue
            vistos.add(sig)
            salida.append(f if f.endswith((".", "!", "?")) else f + ".")
            if len(salida) >= max_frags:
                break
        return salida

    def _intent_ejecutar(self, entrada: str) -> Dict[str, Any]:
        t = entrada.lower()
        if "terminal" in t or "cmd" in t or "powershell" in t:
            if LAUNCHER_OK:
                abrir_app("powershell" if "powershell" in t else "cmd")
            return {"respuesta": "Terminal abierta."}
        if "vscode" in t or "vs code" in t or "código" in t or "codigo" in t:
            if LAUNCHER_OK:
                abrir_app("code")
            return {"respuesta": "VS Code iniciado."}
        if "navegador" in t or "chrome" in t or "browser" in t:
            if ORQ_OK:
                abrir_url("https://www.google.com")
            return {"respuesta": "Navegador abierto."}
        # Apertura genérica: "abre <app>"
        m = re.search(r"(?:abre|ejecuta|lanza|inicia|corre)\s+(.+)$",
                      entrada, re.IGNORECASE)
        if m and LAUNCHER_OK:
            objetivo = m.group(1).strip(" .,;:")
            res = abrir_app(objetivo)
            if res.get("ok"):
                return {"respuesta": f"{objetivo} abierto."}
            return {"respuesta": f"No encontré {objetivo}."}
        return {"respuesta": "¿Qué aplicación quieres que abra?"}

    def _intent_editor(self, entrada: str) -> Dict[str, Any]:
        """
        Crea/abre/edita archivos en editores. Ejemplos soportados:
          • "abre visual y crea un archivo saludo.py con print('Hola mundo')"
          • "abre visual y escribe print('hola') en el archivo prueba.py"
          • "escribe print('hi') en el archivo nuevo.py"
          • "crea archivo C:\\proyectos\\app.py con: from flask import Flask"
          • "abre cursor en C:\\proyectos\\miapp"
          • "agrega print('x') a notas.py"
        """
        from EditorRPA import (crear_archivo, abrir_en_editor, crear_y_abrir,
                                EDITORES_CLI)

        t = entrada.strip()
        t_low = t.lower()

        # Detectar editor mencionado (alias largos primero)
        editor = None
        for alias in sorted(EDITORES_CLI, key=len, reverse=True):
            if alias in t_low:
                editor = alias
                break


        # Detector universal de "archivo X" (acepta nombre.ext o ruta)
        re_archivo = (r"(?:archivo|file)\s+(?:llamado\s+)?"
                      r"([^\s,]+(?:\.[A-Za-z0-9]+)?)")

        # ---- Patrón A: "...escribe/agrega CONTENIDO en/a el archivo NOMBRE"
        m_a = re.search(
            r"(?:escribe|escribir|agrega|añade|anade|inserta|guarda)\s+"
            r"(.+?)\s+(?:en|a|al|en\s+el|al\s+archivo)\s+" + re_archivo,
            t, re.IGNORECASE | re.DOTALL
        )
        if m_a:
            contenido = m_a.group(1).strip().strip(' "\'')
            nombre_archivo = m_a.group(2).strip(' "\'')
            return self._editor_aplicar(editor, nombre_archivo, contenido,
                                         modo="escribir")

        # ---- Patrón B: "crea archivo NOMBRE con/escribe CONTENIDO"
        m_b = re.search(
            r"(?:crea(?:r)?\s+(?:un\s+|el\s+)?archivo|nuevo\s+archivo)\s+"
            r"(?:llamado\s+)?([^\s,]+(?:\.[A-Za-z0-9]+)?)\s*"
            r"(?:y\s+)?(?:escribe|con(?:tenido)?|que\s+contenga|:)\s*(.+)$",
            t, re.IGNORECASE | re.DOTALL
        )
        if m_b:
            nombre_archivo = m_b.group(1).strip(' "\'')
            contenido = m_b.group(2).strip().strip(' "\'')
            return self._editor_aplicar(editor, nombre_archivo, contenido,
                                         modo="escribir")

        # ---- Patrón C: "crea archivo NOMBRE" (sin contenido)
        m_c = re.search(
            r"(?:crea(?:r)?\s+(?:un\s+|el\s+)?archivo|nuevo\s+archivo)\s+"
            r"(?:llamado\s+)?([^\s,]+(?:\.[A-Za-z0-9]+)?)",
            t, re.IGNORECASE
        )
        if m_c:
            nombre_archivo = m_c.group(1).strip(' "\'')
            return self._editor_aplicar(editor, nombre_archivo, "",
                                         modo="crear")

        # ---- Patrón D: "abre <editor> en <ruta>"
        m_d = re.search(
            r"(?:abre|abrir)\s+(?:visual|vscode|vs\s*code|cursor|windsurf|"
            r"sublime|notepad)(?:\s+en\s+(.+))?$",
            t, re.IGNORECASE
        )
        if m_d and editor:
            ruta = (m_d.group(1) or "").strip(' "\'')
            res = abrir_en_editor(editor, ruta) if ruta else abrir_en_editor(editor)
            if res.get("ok"):
                return {"respuesta": f"{editor} abierto."}
            return {"respuesta": f"No pude abrir {editor}: {res.get('error')}"}

        # ---- Patrón E: "abre <editor> y escribe CONTENIDO" (sin nombre archivo)
        m_e = re.search(
            r"(?:abre|abrir)\s+(?:visual|vscode|vs\s*code|cursor|windsurf|"
            r"sublime|notepad)\s+y\s+escribe\s+(.+)$",
            t, re.IGNORECASE | re.DOTALL
        )
        if m_e and editor:
            contenido = m_e.group(1).strip().strip(' "\'')
            # Crear un borrador con timestamp para no pisar nada
            from datetime import datetime as _dt
            nombre = f"borrador_{_dt.now().strftime('%H%M%S')}.py"
            return self._editor_aplicar(editor, nombre, contenido,
                                         modo="escribir")

        return {"respuesta":
                "Dime, por ejemplo: 'abre visual y crea un archivo saludo.py "
                "con print(\"Hola mundo\")', o 'escribe print(\"x\") en el "
                "archivo prueba.py'."}

    def _editor_aplicar(self, editor: Optional[str], nombre_archivo: str,
                        contenido: str, modo: str = "escribir") -> Dict[str, Any]:
        """Crea/sobreescribe el archivo y lo abre en el editor si se indicó."""
        from EditorRPA import crear_archivo, abrir_en_editor, crear_y_abrir

        ruta = self._resolver_ruta_archivo(nombre_archivo)

        if editor:
            res = crear_y_abrir(editor, ruta, contenido)
        else:
            res = crear_archivo(ruta, contenido)

        if not res.get("ok"):
            return {"respuesta": f"No pude: {res.get('error')}"}

        if modo == "crear" and not contenido:
            msg = f"Archivo {Path(ruta).name} creado"
        else:
            msg = f"Archivo {Path(ruta).name} guardado"
        if editor and res.get("abierto", res.get("ok")):
            msg += f" y abierto en {editor}"
        return {"respuesta": f"{msg}.", "ruta": ruta}

    def _resolver_ruta_archivo(self, nombre: str) -> str:
        """Si no es ruta absoluta, ponerla en una carpeta de trabajo del usuario."""
        p = Path(nombre).expanduser()
        if p.is_absolute():
            return str(p)
        # Carpeta por defecto del usuario actual
        from pathlib import Path as _P
        base = _P.home() / "ARES_workspace"
        base.mkdir(parents=True, exist_ok=True)
        return str(base / p)

    # ============================== COPILOT KEEP / UNDO ==============================
    def _intent_copilot_decision(self, entrada: str) -> Dict[str, Any]:
        """
        Acepta o rechaza la edición pendiente de Copilot Chat (botones
        "Keep" / "Undo" que aparecen sobre el archivo modificado).

        Frases reconocidas:
          • Aceptar: "dale siguiente", "dale al keep", "presiona keep",
            "acepta los cambios", "aprueba el cambio", "mantén los cambios".
          • Rechazar: "dale al undo", "rechaza los cambios", "descarta el
            cambio", "deshaz los cambios".

        Estrategia (ver CopilotRPA._aplicar_decision_copilot):
          1) Command Palette → "Chat: Keep All Edits" / "Chat: Undo Edits".
          2) Plantilla PNG en ~/.ares/templates/copilot_keep.png.
          3) OCR con pytesseract si está instalado.
        """
        try:
            from CopilotRPA import (aceptar_edicion_copilot,
                                     descartar_edicion_copilot,
                                     resolver_carpeta_proyecto)
        except Exception as e:
            return {"respuesta": f"Copilot RPA no disponible: {e}"}

        t_low = (entrada or "").lower()
        # Detectar acción
        ACEPTAR = (
            "siguiente", "keep", "acepta", "aprueba", "aceptar copilot",
            "mantén", "manten", "guarda los cambios", "guardar los cambios",
        )
        RECHAZAR = (
            "undo", "rechaza", "descarta", "deshaz", "deshacer", "rechazar",
        )
        if any(k in t_low for k in RECHAZAR):
            accion = "undo"
            etiqueta = "Undo"
        else:
            # Por defecto, aceptar (cubre "dale siguiente", "siguiente",
            # "keep", "acepta", etc.)
            accion = "keep"
            etiqueta = "Keep"

        # Intentar enfocar la ventana del último proyecto si la conocemos
        carpeta = None
        if self._ultimo_proyecto:
            try:
                carpeta = resolver_carpeta_proyecto(self._ultimo_proyecto)
            except Exception:
                carpeta = None

        if accion == "keep":
            res = aceptar_edicion_copilot(carpeta=carpeta)
        else:
            res = descartar_edicion_copilot(carpeta=carpeta)

        # Sea cual sea el resultado, ya no estamos pendientes de aprobación
        self._copilot_pendiente = False
        self._copilot_pendiente_ts = 0.0

        if not res.get("ok"):
            return {"respuesta": (
                f"No pude pulsar {etiqueta}. {res.get('error', '')} "
                f"Si pasa seguido, deja una captura recortada del botón en "
                f"~/.ares/templates/copilot_{accion}.png."
            )}
        via = res.get("via", "")
        msg_via = {
            "ctrl_enter": "con Ctrl+Enter",
            "paleta":     "vía paleta de comandos",
            "plantilla":  "detectando el botón en pantalla",
            "ocr":        "con OCR",
        }.get(via, "")
        msg = f"{etiqueta} aplicado{(' ' + msg_via) if msg_via else ''}."
        return {"respuesta": msg, "accion": accion, "via": via,
                "fuente": "copilot_decision"}

    def _copilot_pendiente_activo(self) -> bool:
        """¿Hay una edición de Copilot pendiente de aprobación reciente?
        Caduca a los 3 minutos para no atrapar comandos no relacionados."""
        if not self._copilot_pendiente:
            return False
        if (time.time() - self._copilot_pendiente_ts) > 180:
            self._copilot_pendiente = False
            self._copilot_pendiente_ts = 0.0
            return False
        return True

    # ============================== ABRIR PROYECTO ==============================
    def _intent_abrir_proyecto(self, entrada: str) -> Dict[str, Any]:
        """
        Abre una carpeta de proyecto en un editor (por defecto VS Code).

        Ejemplos soportados:
          • "abre el proyecto Ares"
          • "abre el proyecto Ares en vs code"
          • "abre la carpeta del proyecto mi-app en cursor"
          • "abre el repositorio C:/dev/foo en windsurf"
          • "abre el proyecto ares en una nueva ventana"
        """
        from CopilotRPA import resolver_carpeta_proyecto, abrir_vscode
        from EditorRPA import abrir_en_editor, EDITORES_CLI

        t = entrada.strip()
        t_low = t.lower()

        # 1) Detectar editor destino (alias largos primero). Por defecto: vscode.
        editor: Optional[str] = None
        for alias in sorted(EDITORES_CLI, key=len, reverse=True):
            if alias in t_low:
                editor = alias
                break
        es_vscode = editor is None or editor in {
            "code", "vscode", "visual", "vs code", "visual studio code"
        }

        # 2) ¿Nueva ventana?
        nueva_ventana = bool(re.search(
            r"\b(?:en\s+)?(?:una\s+)?nueva\s+ventana\b", t_low
        ))

        # 3) Extraer el nombre del proyecto.
        #    Prioridad: patrones explícitos ("el proyecto X", "la carpeta X",
        #    "el repo X", "el repositorio X", "el directorio X").
        nombre: Optional[str] = None
        patrones = [
            # "abre (el|la) (proyecto|carpeta|repo|...) (de|del|llamado)? X"
            r"abre(?:r|me)?\s+(?:el\s+|la\s+)?"
            r"(?:proyecto|carpeta|repositorio|repo|directorio|workspace)"
            r"(?:\s+de(?:l)?|\s+llamado|\s+llamada)?\s+"
            r"['\"]?(?P<nombre>[^,'\"]+?)['\"]?"
            r"(?:\s+(?:en|con)\s+(?:una\s+nueva\s+ventana|"
            r"vs\s*code|vscode|visual(?:\s+studio\s+code)?|code|"
            r"cursor|windsurf|sublime|notepad\+\+|notepad))?\s*\.?$",
            # "abre la carpeta del proyecto X ..."
            r"abre(?:r|me)?\s+la\s+carpeta\s+del\s+proyecto\s+"
            r"['\"]?(?P<nombre>[^,'\"]+?)['\"]?"
            r"(?:\s+(?:en|con)\s+\w+.*)?\s*\.?$",
        ]
        for pat in patrones:
            m = re.search(pat, t, re.IGNORECASE)
            if m:
                nombre = m.group("nombre").strip(" .,;:")
                # Quitar artículos sueltos al inicio
                nombre = re.sub(r"^(?:el|la|los|las|un|una)\s+", "",
                                nombre, flags=re.IGNORECASE).strip()
                # Si terminó capturando "X en vs code" por error, recortar
                nombre = re.sub(
                    r"\s+(?:en|con)\s+(?:una\s+nueva\s+ventana|"
                    r"vs\s*code|vscode|visual(?:\s+studio\s+code)?|"
                    r"cursor|windsurf|sublime|notepad\+\+|notepad)\s*$",
                    "", nombre, flags=re.IGNORECASE
                ).strip()
                if nombre:
                    break

        if not nombre:
            return {"respuesta": "¿Qué proyecto quieres que abra?"}

        # 4) Resolver la carpeta real.
        carpeta = resolver_carpeta_proyecto(nombre)
        if carpeta is None:
            # Si parece una ruta, intentar abrirla aunque resolver no la haya
            # encontrado (puede ser una ruta absoluta válida).
            p = Path(nombre).expanduser()
            if p.is_dir():
                carpeta = p.resolve()
            else:
                return {"respuesta":
                        f"No encontré la carpeta '{nombre}'. "
                        f"Dime la ruta exacta si está fuera de las carpetas "
                        f"de proyectos habituales."}

        # 5) Abrir en el editor elegido.
        if es_vscode:
            res = abrir_vscode(carpeta=carpeta, nueva_ventana=nueva_ventana)
            if not res.get("ok"):
                return {"respuesta": f"No pude abrir VS Code: {res.get('error')}"}
            # Recordar como último proyecto para los siguientes "...con copilot"
            self._ultimo_proyecto = carpeta.name
            destino = "VS Code"
        else:
            res = abrir_en_editor(editor, str(carpeta),
                                   nueva_ventana=nueva_ventana)
            if not res.get("ok"):
                return {"respuesta":
                        f"No pude abrir {editor}: {res.get('error')}"}
            destino = editor

        return {"respuesta": f"Abriendo {carpeta.name} en {destino}.",
                "carpeta": str(carpeta),
                "editor": destino,
                "nueva_ventana": nueva_ventana,
                "fuente": "abrir_proyecto"}

    def _intent_delegar_ia(self, entrada: str) -> Dict[str, Any]:
        """
        Delega instrucciones a IAs de desarrollo.
        Comportamiento por destino:

        • Antigravity / Claude Code / Kiro / Aider: si tienen CLI con stdin,
          se inyecta la instrucción por subprocess (RPA invisible real).

        • VS Code Copilot / Cursor / Windsurf: estos chats NO tienen API
          pública para inyección. ARES escribe la instrucción en un archivo
          `.peticion_<ia>.md` dentro de tu workspace y lo abre en el editor;
          tú la pegas con un Ctrl+V cuando llegues al chat. Es la única
          forma honesta sin teclear sobre la pantalla con pyautogui.
        """
        if not DELEGADOR_OK:
            return {"respuesta": "Delegador IA no disponible."}

        t = entrada.strip()
        t_low = t.lower()

        # Detectar IA destino (alias largos primero para evitar ambigüedad)
        ALIAS = [
            ("antigravity",  ["antigravity"]),
            ("claude_code",  ["claude code", "claude-code", "claude"]),
            ("kiro",         ["kiro"]),
            ("cursor",       ["cursor"]),
            ("windsurf",     ["windsurf"]),
            # Copilot vive dentro de VS Code: si dicen "visual" + "chat" o
            # "copilot", el destino real es VS Code Copilot
            ("copilot",      ["copilot"]),
            ("vscode",       ["vscode", "vs code", "visual"]),
        ]
        ia = None
        for alias, claves in ALIAS:
            if any(k in t_low for k in claves):
                ia = alias
                break

        # "con copilot" / "crea un nuevo modulo ... copilot" → asume Copilot/VSCode
        if ia is None and ("con copilot" in t_low or "copilot" in t_low):
            ia = "copilot"
        if ia is None and any(p in t_low for p in
                              ("crea un nuevo modulo", "crea un nuevo módulo",
                               "crea un modulo", "crea un módulo",
                               "crear modulo", "crear módulo",
                               "nuevo modulo llamado", "nuevo módulo llamado")):
            # Crear un módulo sin mencionar IA → lo manejamos por Copilot igualmente
            ia = "copilot"

        if not ia:
            return {"respuesta": "¿A qué IA delego: copilot, kiro, claude code, "
                                  "cursor, windsurf o antigravity?"}

        # Extraer la instrucción. Hacemos primero una pasada con patrones
        # ESPECÍFICOS (los que dicen "con copilot escribe ..." o
        # "(en|y en) <ia> escribe ..."), porque si dejamos que la regex
        # general gane por aparición temprana, frases como
        # "quiero QUE en X con copilot escribe Y" capturan desde "que" y
        # se llevan por delante toda la frase.
        instruccion = ""
        especificos = [
            r"con\s+copilot\s+escribe\s+(.+)$",
            r"(?:^|\s)(?:y\s+)?en\s+\w+(?:\s+code)?\s+escribe\s+(.+)$",
            r"(?:^|\s)\w+(?:\s+code)?\s+escribe\s+(.+)$",
            r"escribe(?:\s+en(?:\s+el)?(?:\s+chat)?(?:\s+de\s+\w+)?)?\s*[:,]?\s*(.+)$",
            r"manda\s+al\s+chat\s*[:,]?\s*(.+)$",
            r"abre\s+el\s+chat\s+de\s+\w+\s+y\s+escribe\s*[:,]?\s*(.+)$",
            r"diciendo\s+(.+)$",
            r"dile\s+a\s+\w+(?:\s+code)?\s+que\s+(.+)$",
            r"pídele\s+a\s+\w+(?:\s+code)?\s+que\s+(.+)$",
        ]
        for pat in especificos:
            m = re.search(pat, t, re.IGNORECASE | re.DOTALL)
            if m:
                instruccion = m.group(1).strip(' "\'.,;:')
                break
        # Fallback: "...que X" suelto (último recurso)
        if not instruccion:
            m = re.search(r"\bque\s+(.+)$", t, re.IGNORECASE | re.DOTALL)
            if m:
                cand = m.group(1).strip(' "\'.,;:')
                # Filtrar candidatos que solo describen creación de un módulo
                if not re.match(
                    r"^cre[aeéo](?:r|s|n)?\s+(?:un\s+|el\s+|una\s+|la\s+)?"
                    r"(?:nuevo\s+|nueva\s+)?(?:m\u00f3dulo|modulo|archivo|fichero)\b",
                    cand, re.IGNORECASE
                ):
                    instruccion = cand

        # Sin instrucción → solo abrir la app
        if not instruccion:
            res = delegador.abrir(ia if ia != "copilot" else "vscode")
            if res.get("ok"):
                return {"respuesta": f"{ia} abierto."}
            return {"respuesta": f"No pude abrir {ia}: {res.get('error')}"}

        # IAs basadas en EDITOR (chat sin API pública).
        # Para Copilot/VSCode: hacemos el flujo COMPLETAMENTE automático con
        # CopilotRPA (abre VS Code en la carpeta del proyecto detectado,
        # abre el chat, pega y envía con Enter). Para Cursor/Windsurf todavía
        # usamos el fallback de "via archivo + portapapeles".
        EDITORES_CHAT = {"copilot", "vscode", "cursor", "windsurf"}
        if ia in EDITORES_CHAT:
            if ia in {"copilot", "vscode"} and COPILOT_RPA_OK:
                proyecto = self._extraer_proyecto(t)
                modulo = self._extraer_modulo(t)
                modulo_nuevo = self._extraer_modulo_nuevo(t)
                # Reusar el último proyecto si ahora no se mencionó (típico
                # cuando el usuario dice "ahora en X con copilot escribe Y").
                if not proyecto and self._ultimo_proyecto:
                    proyecto = self._ultimo_proyecto
                    ic(f"Reusando último proyecto: {proyecto}")

                # Si pidió crear un módulo nuevo, ese tiene prioridad sobre
                # un módulo existente.
                modulo_para_abrir = modulo_nuevo or modulo
                crear_flag = bool(modulo_nuevo)

                # Si no hay instrucción pero sí un módulo nuevo, pasar una
                # instrucción mínima para que Copilot ofrezca implementarlo.
                instruccion_real = instruccion
                if not instruccion_real and modulo_nuevo:
                    instruccion_real = (
                        f"Acabo de crear el módulo {modulo_nuevo}. "
                        f"Propón una implementación inicial."
                    )

                res = abrir_y_pedir_a_copilot(
                    instruccion_real,
                    proyecto=proyecto,
                    modulo=modulo_para_abrir,
                    crear_modulo_si_falta=crear_flag,
                )
                if not res.get("ok"):
                    return self._delegar_via_archivo(ia, instruccion_real)

                # Recordar el proyecto efectivamente abierto para próximas
                # frases ("ahora en otro modulo con copilot...").
                if res.get("proyecto"):
                    self._ultimo_proyecto = res.get("proyecto")

                # Marcar Copilot como "pendiente de aprobación": durante los
                # siguientes ~3 minutos, frases como "siguiente"/"dale"/"ok"
                # se interpretan como "Keep".
                self._copilot_pendiente = True
                self._copilot_pendiente_ts = time.time()

                # Construir respuesta hablada acorde a lo que sí ocurrió
                partes = []
                if res.get("reutilizando_ventana"):
                    partes.append("ya tenías VS Code abierto")
                elif res.get("carpeta"):
                    partes.append(f"abriendo {Path(res['carpeta']).name}")
                elif proyecto:
                    partes.append(f"no encontré la carpeta '{proyecto}'")
                if res.get("modulo_creado") and res.get("archivo"):
                    partes.append(f"creé {Path(res['archivo']).name}")
                elif res.get("archivo"):
                    partes.append(f"con {Path(res['archivo']).name} abierto")
                elif modulo_para_abrir:
                    partes.append(f"sin localizar el módulo "
                                   f"'{modulo_para_abrir}'")
                detalle = ", ".join(partes) if partes else "abriendo VS Code"
                msg = f"{detalle.capitalize()}. Le mando la petición a Copilot."
                return {"respuesta": msg,
                        "carpeta": res.get("carpeta"),
                        "archivo": res.get("archivo"),
                        "modulo_creado": res.get("modulo_creado"),
                        "reutilizando_ventana": res.get("reutilizando_ventana"),
                        "ia": ia}
            return self._delegar_via_archivo(ia, instruccion)

        # IAs con CLI stdin: delegación real
        res = delegador.delegar(ia, instruccion)
        if not res.get("ok"):
            return {"respuesta": f"No pude delegar a {ia}: {res.get('error')}"}

        modo = res.get("modo")
        if modo == "delegar_cli":
            return {"respuesta": f"Instrucción enviada a {ia}."}
        if modo == "abrir_solo":
            # Fallback: dejar archivo con la petición
            return self._delegar_via_archivo(ia, instruccion)
        return {"respuesta": f"Procesando con {ia}."}

    def _extraer_proyecto(self, entrada: str) -> Optional[str]:
        """
        Saca el nombre/ruta del proyecto a abrir en VS Code.
        Soporta formas como:
          • "abre vs code en el proyecto de Ares y en copilot ..."
          • "abre vs code en la carpeta de mi-app y ..."
          • "abre visual en C:/proyectos/foo y ..."
          • "abre vs code en Ares y en copilot ..."
        Devuelve None si no se reconoce un nombre de proyecto.
        """
        t = entrada.strip()

        # Cortar al primer "y en el modulo / y en copilot" para no mezclar grupos
        patrones = [
            # con "de": "en el proyecto de X", "en la carpeta de X"
            r"en\s+(?:el\s+|la\s+)?(?:proyecto|carpeta|directorio|repo|repositorio)\s+(?:de\s+|del\s+|llamado\s+|llamada\s+)?"
            r"['\"]?(?P<nombre>[^,'\"]+?)['\"]?"
            r"\s+(?:y\s+(?:en\s+)?(?:el\s+(?:modulo|m\u00f3dulo|archivo|fichero)|copilot|vs\s*code|vscode|visual)|$)",
            # "abre <editor> en X y ..."
            r"(?:abre|abrir|abras)\s+(?:visual(?:\s+studio\s+code)?|vs\s*code|vscode)"
            r"\s+en\s+(?!el\s+chat|copilot|el\s+modulo|el\s+m\u00f3dulo|el\s+archivo|el\s+fichero)"
            r"['\"]?(?P<nombre>[^,'\"]+?)['\"]?"
            r"\s+(?:y\s+(?:en\s+)?(?:el\s+(?:modulo|m\u00f3dulo|archivo|fichero)|copilot|vs\s*code|vscode|visual)|$)",
        ]
        for pat in patrones:
            m = re.search(pat, t, re.IGNORECASE)
            if m:
                nombre = m.group("nombre").strip(" .,;:")
                # limpiar artículos sueltos
                nombre = re.sub(r"^(?:el|la|los|las|un|una)\s+", "", nombre,
                                flags=re.IGNORECASE)
                if nombre and nombre.lower() not in {"copilot", "el chat",
                                                       "chat", "vs code",
                                                       "vscode", "visual"}:
                    return nombre
        return None

    def _extraer_modulo(self, entrada: str) -> Optional[str]:
        """
        Saca el nombre del archivo/módulo al que Copilot debería entrar.
        Ejemplos:
          • "... y en el modulo de Ares.py en copilot escribe ..."
          • "... y en el módulo Ares en copilot ..."
          • "... y en el archivo de utils.py y en copilot ..."
          • "... en el fichero login.html y en copilot ..."
          • "quiero que en login.html con copilot escribe ..."
        Devuelve None si no se menciona módulo.
        """
        t = entrada.strip()
        # 1) Forma explícita: "en (el) modulo|archivo|fichero (de) X ..."
        pat = (r"(?:y\s+)?en\s+(?:el\s+)?(?:modulo|m\u00f3dulo|archivo|fichero)"
               r"\s+(?:de\s+|llamado\s+|llamada\s+)?"
               r"['\"]?(?P<nombre>[^,'\"]+?)['\"]?"
               r"\s+(?:y\s+)?(?:en\s+)?(?:copilot|vs\s*code|vscode|visual|escribe|con\s+copilot)\b")
        m = re.search(pat, t, re.IGNORECASE)
        # 2) Forma corta: "en X con copilot ..." o "en X en copilot ..."
        #    (X tiene que parecer nombre de archivo: tener un punto o ser
        #     una sola palabra alfanumérica con guiones/guion bajo)
        if not m:
            pat2 = (r"(?:^|\s)en\s+"
                    r"['\"]?(?P<nombre>[A-Za-z_][\w\-]*\.[A-Za-z0-9]+|"
                    r"[A-Za-z_][\w\-]+)['\"]?"
                    r"\s+(?:con\s+copilot|en\s+copilot)\b")
            m = re.search(pat2, t, re.IGNORECASE)
        if not m:
            return None
        nombre = m.group("nombre").strip(" .,;:")
        nombre = re.sub(r"^(?:el|la|los|las|un|una)\s+", "", nombre,
                        flags=re.IGNORECASE)
        if not nombre or nombre.lower() in {"copilot", "chat", "el chat",
                                              "vs code", "vscode", "visual",
                                              "el", "la"}:
            return None
        return nombre

    def _extraer_modulo_nuevo(self, entrada: str) -> Optional[str]:
        """
        Detecta peticiones de creación de un módulo nuevo. Ejemplos:
          • "crea un nuevo modulo llamado Auth.py"
          • "crea un módulo llamado utils en el proyecto Ares"
          • "crea un nuevo archivo llamado login.html"
          • "que crees un nuevo modulo llamado Telemetria"
          • "quiero que creas un módulo llamado X"
        Devuelve el nombre del módulo (con o sin extensión) o None.
        """
        t = entrada.strip()
        # Acepta: crea, crear, crees, creas, creo, cree
        pat = (r"\bcre[aeéo](?:r|s|n)?\s+(?:un\s+|el\s+|una\s+|la\s+)?"
               r"(?:nuevo\s+|nueva\s+)?"
               r"(?:m\u00f3dulo|modulo|archivo|fichero)\s+"
               r"(?:llamado\s+|llamada\s+|de\s+nombre\s+)?"
               r"['\"]?(?P<nombre>[A-Za-z_][\w\-]*(?:\.[A-Za-z0-9]+)?)['\"]?")
        m = re.search(pat, t, re.IGNORECASE)
        if not m:
            return None
        nombre = m.group("nombre").strip(" .,;:")
        if not nombre or nombre.lower() in {"copilot", "chat"}:
            return None
        return nombre

    def _delegar_via_archivo(self, ia: str, instruccion: str) -> Dict[str, Any]:
        """
        Para IAs cuyo chat no tiene API (Copilot/Cursor/Windsurf): escribe la
        petición en un .md temporal, la copia al portapapeles y abre el editor.
        Así el usuario solo necesita abrir el chat (Ctrl+Alt+I para Copilot
        Chat, Ctrl+L para inline) y pegar con Ctrl+V.
        """
        from EditorRPA import crear_archivo, abrir_en_editor

        EDITOR_DE = {
            "copilot":  "code",
            "vscode":   "code",
            "cursor":   "cursor",
            "windsurf": "windsurf",
        }
        editor = EDITOR_DE.get(ia, "code")

        ws = Path.home() / "ARES_workspace"
        ws.mkdir(parents=True, exist_ok=True)
        ruta = ws / f"_peticion_{ia}.md"
        contenido = (
            f"# Petición para {ia}\n\n"
            f"_(Ya está copiada al portapapeles — abre el chat con "
            f"Ctrl+Alt+I y pega con Ctrl+V)_\n\n"
            f"{instruccion}\n"
        )

        crear_archivo(str(ruta), contenido)
        abrir_en_editor(editor, str(ruta))

        # Copiar la instrucción al portapapeles para que solo haya que pegar
        copiado = self._copiar_portapapeles(instruccion)

        msg_pegado = (
            "Ya está en el portapapeles: abre el chat de Copilot con "
            "Ctrl+Alt+I y pega con Ctrl+V."
            if copiado else
            "Abrí el archivo en " + editor + ". Cópialo y pégalo en el chat "
            "(Ctrl+Alt+I abre Copilot)."
        )

        return {
            "respuesta": f"Petición lista para {ia}. {msg_pegado}",
            "ruta": str(ruta),
            "ia": ia,
            "portapapeles": copiado,
        }

    @staticmethod
    def _copiar_portapapeles(texto: str) -> bool:
        """Copia `texto` al portapapeles del sistema. Devuelve True si lo logró.

        Estrategias en orden:
          1) pyperclip (si está instalado)
          2) `clip` en Windows
          3) `pbcopy` en macOS
          4) `xclip` / `xsel` en Linux
        """
        # 1) pyperclip
        try:
            import pyperclip  # type: ignore
            pyperclip.copy(texto)
            return True
        except Exception:
            pass

        # 2/3/4) Comando del sistema
        import sys as _sys
        import subprocess as _sp
        try:
            if _sys.platform == "win32":
                p = _sp.Popen(["clip"], stdin=_sp.PIPE, shell=False)
                p.communicate(input=texto.encode("utf-16le"))
                return p.returncode == 0
            if _sys.platform == "darwin":
                p = _sp.Popen(["pbcopy"], stdin=_sp.PIPE)
                p.communicate(input=texto.encode("utf-8"))
                return p.returncode == 0
            # Linux
            for cmd in (["xclip", "-selection", "clipboard"], ["xsel", "-b", "-i"]):
                try:
                    p = _sp.Popen(cmd, stdin=_sp.PIPE)
                    p.communicate(input=texto.encode("utf-8"))
                    if p.returncode == 0:
                        return True
                except FileNotFoundError:
                    continue
        except Exception as e:
            ic(f"portapapeles: {e}")
        return False

    def _intent_youtube(self, entrada: str) -> Dict[str, Any]:
        cancion = re.sub(
            r".*?(?:reproduce|pon|youtube|música|cancion|canción)\s+",
            "", entrada, flags=re.IGNORECASE
        ).strip(" .,;:")
        if not cancion:
            return {"respuesta": "¿Qué quieres que reproduzca?"}
        if ORQ_OK:
            reproducir_youtube(cancion)
        return {"respuesta": f"Buscando {cancion} en YouTube."}

    def _intent_whatsapp(self, entrada: str) -> Dict[str, Any]:
        """
        WhatsApp por NOMBRE de contacto (preferente) o número.
        Patrones aceptados:
          • "manda whatsapp a Juan diciendo hola"
          • "envía whatsapp a Juan que llego en 5"
          • "manda whatsapp a +573001234567 diciendo hola"
          • "guarda el contacto Juan +57 350 6299346"
          • "envía el mensaje" (re-disparo del último envío fallido)
        """
        from Contactos import (guardar_contacto, buscar_contacto,
                                extraer_telefono)

        # Atajos rápidos: "envia el mensaje" / "envialo" / "mandalo"
        # → reintenta el último envío de WhatsApp guardado en sesión
        if re.fullmatch(r"\s*(?:env[íi]a(?:lo)?(?:\s+el\s+mensaje)?|"
                        r"m[áa]ndalo|reenv[íi]alo)\s*\.?",
                        entrada, re.IGNORECASE):
            ult = getattr(self, "_ultimo_whatsapp", None)
            if ult and ORQ_OK:
                enviar_whatsapp(ult["telefono"], ult["mensaje"])
                return {"respuesta":
                        f"Reenviando a {ult.get('nombre') or ult['telefono']}."}
            return {"respuesta": "No tengo un mensaje pendiente para reenviar."}

        # Caso 1: el usuario está guardando un contacto.
        # Formato nuevo: "guarda el contacto NUMERO, como NOMBRE"
        # Formato legacy: "guarda el contacto NOMBRE NUMERO" (todavía soportado)
        m_save = re.search(
            r"guarda(?:r)?\s+(?:el\s+)?contacto\s+(?:whatsapp\s+(?:a\s+)?)?"
            r"(\+?\s?\d[\d\s\-\.]{5,20})\s*,\s+como\s+"
            r"([a-záéíóúñ][a-záéíóúñ\s]+)",
            entrada, re.IGNORECASE
        )
        if m_save:
            tel = re.sub(r"[^\d+]", "", m_save.group(1))
            nombre = m_save.group(2).strip(" .,;:")
            res = guardar_contacto(nombre, tel)
            if res.get("ok"):
                return {"respuesta": f"Contacto {nombre} guardado ({tel})."}
            return {"respuesta": f"No pude guardar: {res.get('error')}"}
        
        # Formato legacy por compatibilidad: "guarda el contacto NOMBRE NUMERO"
        m_save_legacy = re.search(
            r"guarda(?:r)?\s+(?:el\s+)?contacto\s+(?:whatsapp\s+(?:a\s+)?)?"
            r"([a-záéíóúñ][a-záéíóúñ\s]*?)\s+"
            r"(\+?\s?\d[\d\s\-\.]{5,20})",
            entrada, re.IGNORECASE
        )
        if m_save_legacy:
            nombre = m_save_legacy.group(1).strip(" .,;:")
            tel = re.sub(r"[^\d+]", "", m_save_legacy.group(2))
            res = guardar_contacto(nombre, tel)
            if res.get("ok"):
                return {"respuesta": f"Contacto {nombre} guardado ({tel})."}
            return {"respuesta": f"No pude guardar: {res.get('error')}"}

        # Caso 2: extraer destinatario y mensaje
        m_msg = re.search(
            r"(?:diciendo|que\s+diga|que\s+|mensaje[:\s]+)\s*(.+)$",
            entrada, re.IGNORECASE
        )
        mensaje = m_msg.group(1).strip(" .,;:") if m_msg else ""

        # Nombre: tras "a/para", saltando "whatsapp" y "el mensaje" si vienen
        # entre medias. Solo letras/espacios, sin palabras-ruido.
        STOP = {"whatsapp", "mensaje", "el", "la", "un", "una",
                "los", "las", "le", "lo"}
        nombre = ""
        candidatos = re.findall(
            r"(?:\b(?:a|para)\s+)"
            r"(?:whatsapp\s+(?:a\s+)?)?"      # absorbe 'whatsapp' / 'whatsapp a'
            r"([a-záéíóúñ][a-záéíóúñ\s]*?)"
            r"(?=\s+(?:diciendo|que|mensaje)|\s*$)",
            entrada, re.IGNORECASE
        )
        for cand in candidatos:
            limpio = " ".join(p for p in cand.split()
                              if p.lower() not in STOP).strip()
            if limpio:
                nombre = limpio
                break
        
        # Si no se encontró nombre con el patrón anterior, intentar patrón más simple
        if not nombre:
            # Patrón: "manda whatsapp a NOMBRE" o "envia whatsapp a NOMBRE"
            m_simple = re.search(
                r"(?:manda|env[íi]a|env[íi]a)\s+whatsapp\s+(?:a|para)\s+"
                r"([a-záéíóúñ][a-záéíóúñ\s]+?)"
                r"(?=\s+(?:diciendo|que|mensaje)|\s*$)",
                entrada, re.IGNORECASE
            )
            if m_simple:
                nombre = m_simple.group(1).strip()

        telefono = extraer_telefono(entrada)

        # Si tengo número directo, usar ese
        if telefono and mensaje:
            if ORQ_OK:
                enviar_whatsapp(telefono, mensaje)
            self._ultimo_whatsapp = {"telefono": telefono,
                                      "mensaje": mensaje, "nombre": None}
            return {"respuesta": f"Enviando: \"{mensaje}\"."}

        # Si tengo nombre, buscar en la libreta privada
        if nombre and not telefono:
            contacto = buscar_contacto(nombre)
            if contacto:
                if not mensaje:
                    return {"respuesta": f"¿Qué le mando a {contacto['nombre']}?"}
                if ORQ_OK:
                    enviar_whatsapp(contacto["telefono"], mensaje)
                self._ultimo_whatsapp = {
                    "telefono": contacto["telefono"],
                    "mensaje":  mensaje,
                    "nombre":   contacto["nombre"]
                }
                return {"respuesta":
                        f"Enviando a {contacto['nombre']}: \"{mensaje}\"."}
            # No conozco el contacto: pedir el número
            return {
                "respuesta": (f"No tengo a {nombre} guardado. "
                              f"Dime: 'guarda el contacto {nombre} +573001234567'.")
            }

        return {"respuesta":
                "Dime el contacto y el mensaje, por ejemplo: "
                "'manda whatsapp a Juan diciendo hola'."}

    def _intent_facebook(self, entrada: str) -> Dict[str, Any]:
        m = re.search(
            r"(?:a|para)\s+([\w\.]+).*?(?:diciendo|que|mensaje)\s+(.+)$",
            entrada, re.IGNORECASE
        )
        if not m:
            if ORQ_OK:
                abrir_facebook_mensaje()
            return {"respuesta": "Messenger abierto."}
        destinatario, mensaje = m.group(1), m.group(2).strip()
        if ORQ_OK:
            abrir_facebook_mensaje(destinatario, mensaje)
        return {"respuesta": f"Enviando a {destinatario} en Messenger."}

    def _intent_archivo(self, entrada: str) -> Dict[str, Any]:
        # Eliminar
        m = re.search(r"(?:elimina|borra)\s+(.+)$", entrada, re.IGNORECASE)
        if m and ORQ_OK:
            res = eliminar_archivo(m.group(1).strip(' "\''))
            return {"respuesta": "Eliminado." if res["ok"]
                    else f"No pude: {res.get('error')}"}
        # Abrir
        m = re.search(r"abre\s+(?:el\s+)?archivo\s+(.+)$", entrada, re.IGNORECASE)
        if m and ORQ_OK:
            res = abrir_archivo(m.group(1).strip(' "\''))
            return {"respuesta": "Archivo abierto." if res["ok"]
                    else f"No pude: {res.get('error')}"}
        return {"respuesta": "Especifica la operación: abre/edita/elimina."}

    def _intent_personal(self, entrada: str) -> Dict[str, Any]:
        """Solo accede a BD privada del usuario actual."""
        perfil = auth.perfil_actual()
        if not perfil:
            return {"respuesta": "Sin sesión activa."}

        nombre = perfil.get("nombre_real", auth.usuario_actual)

        # Buscar en interacciones privadas
        prev = base_privada.buscar_interacciones(entrada, n=2)
        if "qué sabes de mí" in entrada.lower() or "mis datos" in entrada.lower():
            stats = base_privada.estadisticas()
            return {"respuesta": f"Eres {nombre}. Hemos tenido "
                                  f"{stats['total_interacciones']} interacciones."}

        return {"respuesta": f"Hola {nombre}. {len(prev)} recuerdos relacionados."}

    def _intent_saludo(self) -> Dict[str, Any]:
        """Saludo personalizado basado en reconocimiento facial."""
        perfil = auth.perfil_actual()
        
        # Intentar usar reconocimiento facial si está disponible
        if FACE_REC_OK and reconocimiento_facial:
            usuario_detectado = reconocimiento_facial.obtener_usuario_actual()
            expresion = reconocimiento_facial.obtener_expresion_actual()
            
            if usuario_detectado:
                # Usuario reconocido: saludo personalizado con expresión
                saludos_expresion = {
                    'feliz': f"¡Hola {usuario_detectado}! Veo que estás de buen ánimo.",
                    'enojado': f"Hola {usuario_detectado}. Noto que algo te molesta, ¿en qué puedo ayudarte?",
                    'triste': f"Hola {usuario_detectado}. Noto que estás triste, ¿quieres conversar?",
                    'molesto': f"Hola {usuario_detectado}. Parece que algo te incomoda.",
                    'normal': f"Hola {usuario_detectado}, ¿en qué te puedo ayudar hoy?"
                }
                respuesta = saludos_expresion.get(expresion, f"Hola {usuario_detectado}")
                
                # Agregar información del entorno si está disponible
                descp = camara.estado().get("descripcion_entorno", "")
                if descp and "un " in descp:
                    respuesta += f" {descp.replace('Detecté: ', 'Veo ')}."
                
                return {"respuesta": respuesta}
            else:
                # No se reconoce el usuario: preguntar nombre
                estado_camara = camara.estado()
                if estado_camara.get("rostro_detectado"):
                    # Hay un rostro pero no está registrado
                    self._esperando_nombre_usuario = True
                    return {"respuesta": "Un gusto, ¿quién eres?"}
        
        # Fallback al sistema original sin reconocimiento facial
        nombre = (perfil or {}).get("como_llamarme") \
                 or (perfil or {}).get("nombre_real", "")
        descp = camara.estado().get("descripcion_entorno", "")
        if nombre and descp and "un " in descp:
            return {"respuesta": f"Hola {nombre}. {descp.replace('Detecté: ', 'Veo ')}."}
        if nombre:
            return {"respuesta": f"Hola {nombre}."}
        return {"respuesta": "Hola."}

    def _intent_charla(self, entrada: str) -> Dict[str, Any]:
        """Charla casual: cortesía, agradecimientos, despedidas."""
        import random
        t = entrada.lower()
        perfil = auth.perfil_actual() or {}
        nombre = perfil.get("nombre_real", "").split()[0] if perfil.get("nombre_real") else ""

        # Cómo estás / qué tal
        if any(k in t for k in ("como estas", "cómo estás", "qué tal",
                                 "que tal", "qué cuentas", "que cuentas",
                                 "qué haces", "que haces")):
            return {"respuesta": random.choice([
                "Operativo y atento. ¿En qué te ayudo?",
                f"Todo en orden{', ' + nombre if nombre else ''}. ¿Qué necesitas?",
                "Activo. Dime qué hacemos.",
                "Listo para lo que sigue."
            ])}

        # Agradecimientos
        if any(k in t for k in ("gracias", "te agradezco")):
            return {"respuesta": random.choice([
                "Para eso estoy.",
                "Cuando quieras.",
                "Un placer.",
                "A la orden."
            ])}

        # Disculpas
        if any(k in t for k in ("perdón", "perdon", "lo siento", "disculpa")):
            return {"respuesta": "Sin problema. Sigamos."}

        # Despedidas
        if any(k in t for k in ("adiós", "adios", "chao", "chau", "bye",
                                 "nos vemos", "hasta luego", "hasta pronto")):
            return {"respuesta": random.choice([
                f"Hasta luego{', ' + nombre if nombre else ''}.",
                "Aquí estaré.",
                "Cuídate."
            ])}

        # Risas / muletillas
        if any(k in t for k in ("jaja", "jeje", "jiji", "lol")):
            return {"respuesta": random.choice([
                "Me alegra.",
                "Jeje.",
                "¿Seguimos?"
            ])}

        # Afirmaciones cortas que no caen en seguimiento ("ok", "vale")
        if t.strip() in {"ok", "vale", "bueno", "perfecto"}:
            return {"respuesta": "Listo."}

        # Respuestas expresivas positivas (okey, super, excelente, genial, etc.)
        if any(k in t for k in ("okey", "super", "excelente", "genial", 
                                 "fantástico", "fantastico", "increíble",
                                 "increible", "estupendo", "estupenda",
                                 "brillante", "chévere", "muy bien")):
            return {"respuesta": random.choice([
                "¡Me alegra que te guste!",
                "¡Genial!",
                "¡Perfecto!",
                "¡Excelente!",
                "¡Super!",
                "¡Brillante!",
                "¡Estupendo!",
                "¡Fantástico!",
                "¡Increíble!",
                "¡Qué bien!",
                "¡Chévere!",
                "¡Me encanta!",
                "¡Perfecto, seguimos!",
                "¡Excelente, a lo siguiente!"
            ])}

        return {"respuesta": "Te escucho."}

    def _intent_control(self, entrada: str) -> Dict[str, Any]:
        # Detener TTS
        try:
            voz.engine.stop()
        except Exception:
            pass
        return {"respuesta": ""}

    def _intent_registrar_usuario(self, entrada: str) -> Dict[str, Any]:
        """Registra un nuevo usuario cuando proporciona su nombre."""
        if not FACE_REC_OK or not reconocimiento_facial:
            return {"respuesta": "El reconocimiento facial no está disponible."}
        
        # Extraer el nombre de la entrada
        t = entrada.lower().strip()
        nombre = None
        
        # Patrones para extraer el nombre
        if "me llamo" in t:
            nombre = t.replace("me llamo", "").strip()
        elif "soy" in t:
            nombre = t.replace("soy", "").strip()
        elif "mi nombre es" in t:
            nombre = t.replace("mi nombre es", "").strip()
        elif "llámame" in t:
            nombre = t.replace("llámame", "").strip()
        else:
            # Si no hay patrón, usar toda la entrada como nombre
            nombre = entrada.strip()
        
        # Limpiar el nombre (quitar signos de puntuación)
        import re
        nombre = re.sub(r'[¿?¡!.,;:]', '', nombre).strip()
        
        if not nombre:
            return {"respuesta": "No entendí tu nombre. ¿Podrías repetirlo?"}
        
        # Capitalizar primera letra
        nombre = nombre.capitalize()
        
        # Confirmar el registro del usuario
        if reconocimiento_facial.confirmar_registro(nombre):
            self._esperando_nombre_usuario = False
            return {"respuesta": f"¡Un gusto, {nombre}! Te he registrado en mi sistema."}
        else:
            return {"respuesta": "No pude registrar tu rostro. Intenta acercarte un poco más a la cámara."}

    # ============================== MATEMÁTICAS ==============================
    def _intent_matematica(self, entrada: str) -> Dict[str, Any]:
        try:
            from Matematicas import evaluar
        except Exception as e:
            return {"respuesta": f"Calculadora no disponible: {e}"}
        # Quitar prefijos coloquiales antes de evaluar
        t = re.sub(
            r"^\s*(?:oye\s+|ares\s+|por\s+favor\s+)?",
            "", entrada, flags=re.IGNORECASE
        )
        res = evaluar(t)
        if not res.get("ok"):
            return {"respuesta": f"No pude calcular: {res.get('error')}"}
        valor = res["resultado"]
        # Frase amigable
        return {"respuesta": f"El resultado es {valor}.",
                "expresion": res.get("expresion"),
                "resultado": valor,
                "fuente": "calculo"}

    # ============================== HORA / FECHA ==============================
    def _intent_hora(self, entrada: str) -> Dict[str, Any]:
        try:
            from Telemetria import hora_actual, fecha_actual
        except Exception as e:
            return {"respuesta": f"No tengo acceso a la hora: {e}"}
        t = entrada.lower()
        pide_fecha = any(k in t for k in ("fecha", "día", "dia"))
        pide_hora = any(k in t for k in ("hora",))
        if pide_fecha and not pide_hora:
            f = fecha_actual()
            return {"respuesta": f"Hoy es {f['hablado']}.", "fuente": "fecha"}
        h = hora_actual(formato_24h=False)
        if pide_fecha:
            f = fecha_actual()
            return {"respuesta": f"Son las {h['hablado']} del {f['hablado']}.",
                    "fuente": "hora"}
        return {"respuesta": f"Son las {h['hablado']}.", "fuente": "hora"}

    # ============================== CLIMA ==============================
    def _intent_clima(self, entrada: str) -> Dict[str, Any]:
        try:
            from Telemetria import obtener_clima, formato_clima_humano
        except Exception as e:
            return {"respuesta": f"No tengo acceso al clima: {e}"}
        # Extraer ciudad si la mencionan ("clima en Lima", "tiempo de Madrid")
        ciudad = "auto"
        m = re.search(r"\b(?:en|de|para)\s+([A-Za-zÀ-ÿñÑ\s]+?)$",
                      entrada.strip().rstrip("?¿.!"), re.IGNORECASE)
        if m:
            cand = m.group(1).strip()
            # Filtros para evitar capturar verbos sueltos
            if cand.lower() not in {"hoy", "ahora", "este momento",
                                      "este lugar", "tu ciudad", "mi ciudad"}:
                ciudad = cand
        d = obtener_clima(ciudad)
        if d.get("error"):
            return {"respuesta": f"No pude obtener el clima: {d['error']}"}
        return {"respuesta": formato_clima_humano(d),
                "ciudad": d.get("ciudad"),
                "temperatura": d.get("temperatura"),
                "fuente": "clima"}

    # ============================== ONBOARDING ==============================
    # Cola de preguntas. Cada paso tiene clave (campo a guardar) y dónde
    # persistir: "perfil" → auth.actualizar_perfil, "atributo" → base_privada.
    _ONBOARDING_PREGUNTAS = [
        {"clave": "como_llamarme",
         "destino": "perfil",
         "pregunta": "¿Cómo te gustaría que te llame?"},
        {"clave": "tono",
         "destino": "perfil",
         "pregunta": "¿Qué tono prefieres? Tranquilo, balanceado, "
                     "analítico o directo.",
         "validador": "tono"},
        {"clave": "ciudad",
         "destino": "perfil",
         "pregunta": "¿En qué ciudad estás? (así te puedo dar el clima sin pedirlo)"},
        {"clave": "ocupacion",
         "destino": "perfil",
         "pregunta": "¿A qué te dedicas?"},
        {"clave": "hobbies",
         "destino": "atributo",
         "pregunta": "¿Cuáles son tus hobbies o intereses?"},
        {"clave": "gustos",
         "destino": "atributo",
         "pregunta": "¿Qué te gusta? Música, comida, lo que quieras contarme."},
        {"clave": "alergias",
         "destino": "atributo",
         "pregunta": "¿Tienes alguna alergia o algo importante que deba recordar?"},
    ]

    def _intent_onboarding(self, entrada: str) -> Dict[str, Any]:
        """Inicia (o reinicia) la entrevista de personalización."""
        if not auth.autenticado:
            return {"respuesta": "Necesito que inicies sesión primero."}
        self._onboarding = {"paso": 0, "respuestas": {}}
        primera = self._ONBOARDING_PREGUNTAS[0]["pregunta"]
        return {"respuesta": "Genial, te haré algunas preguntas para "
                              "personalizar el chat. " + primera,
                "fuente": "onboarding"}

    def _onboarding_responder(self, entrada: str) -> Dict[str, Any]:
        """Procesa la respuesta del usuario a la pregunta actual y avanza."""
        if not self._onboarding:
            return {"respuesta": "No hay personalización activa."}
        paso = self._onboarding["paso"]
        if paso >= len(self._ONBOARDING_PREGUNTAS):
            self._onboarding = None
            return {"respuesta": "Ya terminamos antes."}
        pregunta_actual = self._ONBOARDING_PREGUNTAS[paso]
        clave = pregunta_actual["clave"]
        destino = pregunta_actual["destino"]
        valor = entrada.strip().rstrip(".,;:")

        # Validador especial para tono
        if pregunta_actual.get("validador") == "tono":
            valor_l = _normaliza(valor).split()[0] if valor else ""
            tonos_validos = {"tranquilo", "balanceado", "analitico",
                              "analítico", "directo"}
            if valor_l not in tonos_validos:
                # No avanzamos, repetimos
                return {"respuesta": ("Elige uno: tranquilo, balanceado, "
                                       "analítico o directo.")}
            valor = "analitico" if valor_l in {"analitico", "analítico"} else valor_l

        # Persistir
        try:
            if destino == "perfil":
                if clave == "como_llamarme":
                    # También actualizamos nombre_real para los saludos
                    auth.actualizar_perfil(nombre_real=valor,
                                            como_llamarme=valor)
                else:
                    auth.actualizar_perfil(**{clave: valor})
            else:  # "atributo" (privado, cifrado)
                base_privada.set_atributo(clave, valor)
            self._onboarding["respuestas"][clave] = valor
        except Exception as e:
            ic(f"onboarding paso {paso}: {e}")

        # Avanzar
        self._onboarding["paso"] = paso + 1
        if self._onboarding["paso"] >= len(self._ONBOARDING_PREGUNTAS):
            datos = self._onboarding["respuestas"]
            self._onboarding = None
            nombre = datos.get("como_llamarme") or auth.usuario_actual
            return {"respuesta": f"Perfecto, {nombre}. Memorizado todo. "
                                  f"Voy a usar esto para personalizar el chat.",
                    "fuente": "onboarding_done"}
        siguiente = self._ONBOARDING_PREGUNTAS[self._onboarding["paso"]]["pregunta"]
        return {"respuesta": siguiente, "fuente": "onboarding"}

    def _intent_general(self, entrada: str) -> Dict[str, Any]:
        # Buscar en conocimiento global usando el tema normalizado para que
        # "dime qué es CSS", "explícame CSS", "qué es CSS" caigan en el mismo
        # concepto y respondan con lo aprendido en lugar de "no sé".
        tema_norm = _extraer_tema(entrada)
        consulta = tema_norm or entrada
        existente = base_global.mejor_concepto(consulta)
        if existente and existente.get("similitud", 0) >= 0.55:
            base_global.confirmar_concepto(existente["tema"],
                                            existente["descripcion"])
            # Adaptar la descripción al tono activo del usuario.
            perfil = auth.perfil_actual() or {}
            tono = perfil.get("tono", "balanceado")
            descripcion = base_global.descripcion_para_tono(existente, tono)
            return {"respuesta": descripcion,
                    "fuente": "memoria_global",
                    "tema": existente.get("tema")}

        # No lo sabe → buscar AUTOMÁTICAMENTE en la web sin pedir
        # confirmación. Antes anunciamos lo que vamos a hacer (con tono
        # adaptado): "Sin datos en BD. Iniciando recolección externa."
        # y a continuación devolvemos el resultado de la investigación.
        ic("Sin match en memoria — disparo búsqueda externa automática")
        return self._intent_investigar(tema_norm or entrada, forzar_web=True)

    # ------------------------ TONO ------------------------
    def _aplicar_tono(self, respuesta: str) -> str:
        if not respuesta:
            return respuesta
        perfil = auth.perfil_actual() or {}
        tono = perfil.get("tono", "balanceado")

        # Las respuestas que ya vienen con sufijo conversacional como
        # "¿Lo guardo?" no se reformulan: cortarlas rompería el flujo de
        # confirmación.
        tiene_sufijo_conversacional = "¿Lo guardo?" in respuesta

        if tono == "directo":
            if tiene_sufijo_conversacional:
                return respuesta
            # Acortar a una sola frase
            try:
                from Cognicion import adaptar_respuesta_a_tono
                return adaptar_respuesta_a_tono(respuesta, "directo")
            except Exception:
                partes = re.split(r"(?<=[\.!?])\s+", respuesta.strip())
                return partes[0] if partes else respuesta

        if tono == "tranquilo":
            if not respuesta.startswith(("Hola", "Está bien", "Claro",
                                          "Tranquilo")):
                return f"Está bien. {respuesta}"
            return respuesta

        if tono == "analitico":
            # Modo analítico: respuestas detalladas y largas. Si la
            # respuesta es muy corta, no la inflamos artificialmente,
            # pero garantizamos cierre con punto final.
            r = respuesta.strip()
            if len(r) > 0 and not re.search(r"[\.!\?…]\s*$", r) \
                    and not tiene_sufijo_conversacional:
                r += "."
            return r

        return respuesta  # balanceado

    def _aplicar_expresion(self, respuesta: str) -> str:
        """Adapta la respuesta según la expresión facial del usuario."""
        if not reconocimiento_facial:
            return respuesta
        
        expresion = reconocimiento_facial.obtener_expresion_actual()
        usuario = reconocimiento_facial.obtener_usuario_actual()
        
        # Prefijos según expresión
        prefijos = {
            'feliz': "¡Me alegra verte así! ",
            'enojado': "Entiendo tu frustración. ",
            'triste': "Lamento que te sientas así. ",
            'molesto': "Comprendo tu molestia. ",
            'normal': ""
        }
        
        prefijo = prefijos.get(expresion, "")
        
        # Si hay un usuario reconocido, personalizar más
        if usuario and expresion != "normal":
            return f"{prefijo}{respuesta}"
        elif prefijo:
            return f"{prefijo}{respuesta}"
        
        return respuesta

    # ------------------------ ESTADO ------------------------
    def estado_completo(self) -> Dict[str, Any]:
        from Telemetria import stats_sistema, uptime, obtener_clima
        return {
            "usuario":   auth.perfil_actual(),
            "sistema":   stats_sistema(),
            "uptime":    uptime(),
            "camara":    camara.estado(),
            "base_global":  base_global.estadisticas(),
            "base_privada": base_privada.estadisticas() if auth.autenticado else None,
            "historial_sesion": len(self.historial_sesion)
        }


# ============================== INSTANCIA GLOBAL ==============================
ares = ARES()
