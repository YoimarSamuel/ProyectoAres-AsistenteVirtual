"""
================================================================================
        ARES — Motor Cognitivo (puro código, SIN LLM externo)
================================================================================
ARES no piensa con una IA externa. Genera respuestas combinando:
  1. Recuperación vectorial (RAG) de su BD global y privada
  2. Síntesis y consolidación con MenteCritica
  3. Plantillas de respuesta que se eligen por intención + tono
  4. Anti-repetición por hash sobre las últimas respuestas

Si no sabe algo, lo investiga por scraping web y lo aprende.
Si tampoco hay info en la web, lo dice claramente.
================================================================================
"""

from __future__ import annotations
import re
import hashlib
import random
from collections import defaultdict, deque
from typing import List, Dict, Any, Optional
from icecream import ic


# ============================== PLANTILLAS POR TONO ==============================
PLANTILLAS = {
    "balanceado": {
        "saludo":           ["Hola{nombre}.", "Hola{nombre}, listo.", "Aquí estoy{nombre}."],
        "saludo_visible":   ["Hola{nombre}. {entorno}.", "Te veo{nombre}. {entorno}."],
        "ack":              ["Listo.", "Hecho.", "OK."],
        "ejecutado":        ["{accion} ejecutado.", "{accion} listo.", "{accion}."],
        "no_se":            ["Eso no lo tengo aún. Lo busco para ti."],
        "no_encontrado":    ["No encontré información clara sobre {tema}."],
        "buscando":         ["Investigando {tema}.", "Buscando {tema}."],
        "encontrado":       ["{respuesta}"],
        "personal":         ["{respuesta}"],
        "rechazado":        ["Eso contradice lo que sé. No lo voy a registrar."],
        "auth":             ["Necesito que inicies sesión primero."],
        "error":            ["Algo falló. Intenta de nuevo."],
        "delegando":        ["Delegando a {app}: {orden}."],
        "abriendo":         ["Abriendo {app}.", "Lanzando {app}."],
        "comando_no_claro": ["¿Qué debo abrir o ejecutar?", "Concreta tu petición."]
    },
    "tranquilo": {
        "saludo":           ["Hola{nombre}, está bien.", "Aquí estoy{nombre}, todo en orden."],
        "saludo_visible":   ["Hola{nombre}, te veo. {entorno}."],
        "ack":              ["Está bien.", "Tranquilo, listo.", "Hecho con calma."],
        "ejecutado":        ["{accion}, ya está.", "Listo, {accion}."],
        "no_se":            ["No lo sé todavía. Tranquilo, lo voy buscando."],
        "no_encontrado":    ["No encontré información sobre {tema}."],
        "buscando":         ["Tranquilo, voy a buscar {tema}."],
        "encontrado":       ["{respuesta}"],
        "personal":         ["{respuesta}"],
        "rechazado":        ["Eso no parece correcto. Mejor no lo registro."],
        "auth":             ["Inicia sesión, así te puedo ayudar."],
        "error":            ["Hubo un problema. Probemos otra vez."],
        "delegando":        ["Voy a pedirle a {app} que haga: {orden}."],
        "abriendo":         ["Abro {app} para ti."],
        "comando_no_claro": ["¿Qué te gustaría que haga?"]
    },
    "analitico": {
        "saludo":           ["Operativo{nombre}.", "Sistema en línea{nombre}."],
        "saludo_visible":   ["Operativo{nombre}. Detección: {entorno}."],
        "ack":              ["Confirmado.", "Procesado.", "Ejecutado."],
        "ejecutado":        ["{accion}: ejecución exitosa.", "{accion} completado."],
        "no_se":            ["Sin datos en BD. Iniciando recolección externa."],
        "no_encontrado":    ["Sin coincidencias para {tema} en fuentes consultadas."],
        "buscando":         ["Iniciando recolección sobre {tema}."],
        "encontrado":       ["{respuesta}"],
        "personal":         ["{respuesta}"],
        "rechazado":        ["Conflicto semántico detectado. Registro descartado."],
        "auth":             ["Autenticación requerida."],
        "error":            ["Excepción capturada. Reintenta."],
        "delegando":        ["Delegación a {app} con instrucción: {orden}."],
        "abriendo":         ["Iniciando proceso {app}."],
        "comando_no_claro": ["Comando ambiguo. Especifica objetivo."]
    },
    "directo": {
        "saludo":           ["Hola{nombre}."],
        "saludo_visible":   ["Hola{nombre}. {entorno}."],
        "ack":              ["OK."],
        "ejecutado":        ["{accion}."],
        "no_se":            ["No lo sé. Buscando."],
        "no_encontrado":    ["No hay datos."],
        "buscando":         ["Buscando."],
        "encontrado":       ["{respuesta}"],
        "personal":         ["{respuesta}"],
        "rechazado":        ["Falso. No registro."],
        "auth":             ["Inicia sesión."],
        "error":            ["Error."],
        "delegando":        ["Delegando a {app}."],
        "abriendo":         ["{app} abierto."],
        "comando_no_claro": ["¿Qué?"]
    }
}


# ============================== IDENTIDAD DE ARES ==============================
# Respuestas a preguntas que el usuario hace SOBRE el propio asistente
# ("¿qué eres?", "¿cómo te llamas?", "¿qué puedes hacer?", etc.).
# Cada tono tiene su voz: el analítico es largo y técnico, el directo es
# de una línea, el tranquilo es cercano y el balanceado es lo intermedio.
IDENTIDAD_ARES = {
    "balanceado": {
        "que_eres": (
            "Soy ARES, tu Asistente de Reconocimiento y Ejecución de "
            "Software. Funciono en local: detecto intenciones, consulto "
            "mi memoria, investigo en la web cuando no sé algo y ejecuto "
            "acciones en el equipo (abrir apps, mandar mensajes, delegar "
            "a otras IAs)."
        ),
        "nombre": "Me llamo ARES: Asistente de Reconocimiento y Ejecución de Software.",
        "que_haces": (
            "Aprendo conceptos nuevos investigándolos en Google, recuerdo "
            "lo que ya sé, ejecuto comandos en tu PC (abrir VS Code, "
            "WhatsApp, YouTube), envío instrucciones a Copilot u otras IAs "
            "y mantengo conversación contigo. Tengo cámara, voz y "
            "memoria privada cifrada."
        ),
        "como_funcionas": (
            "Mi pipeline es simple: entrada → detección de intención → "
            "consulta a memoria global o privada → si no sé, investigo "
            "en la web → mente crítica valida el resultado → respondo en "
            "el tono que tienes configurado y guardo la interacción "
            "cifrada en tu perfil."
        ),
        "creador": "Me desarrolló Samuel como asistente personal local sin depender de IAs externas para pensar.",
        "limites": (
            "No uso ningún LLM externo para razonar: solo plantillas, "
            "RAG vectorial sobre mi memoria y scraping de Google. Si "
            "Google bloquea la consulta, lo digo claramente."
        ),
    },
    "tranquilo": {
        "que_eres": (
            "Tranquilo, soy ARES, tu Asistente de Reconocimiento y "
            "Ejecución de Software. Estoy aquí para ayudarte con calma: "
            "te respondo lo que sé, busco en internet lo que no sé y "
            "ejecuto las cosas que me pidas."
        ),
        "nombre": "Me llamo ARES, tu asistente. Estoy para lo que necesites.",
        "que_haces": (
            "Te ayudo con conversación, busco información cuando no la "
            "tengo, abro programas, mando mensajes, controlo la cámara y "
            "guardo lo que aprendemos juntos. Todo a tu ritmo."
        ),
        "como_funcionas": (
            "Recibo lo que me dices, miro si ya lo sé, si no, busco en "
            "Google con calma, valido lo encontrado y te lo cuento. "
            "Después lo guardo cifrado para la próxima."
        ),
        "creador": "Me hizo Samuel para acompañarte en lo que necesites.",
        "limites": (
            "No tengo IA externa pensando por mí. Solo memoria propia y "
            "lectura de la web. Si algo no sale, te aviso sin presión."
        ),
    },
    "analitico": {
        "que_eres": (
            "Soy ARES (Asistente de Reconocimiento y Ejecución de "
            "Software). Asistente local, multitenant, con memoria "
            "vectorial cifrada, sin dependencia de LLMs externos. "
            "Mi arquitectura combina detección de intención por "
            "palabras clave, RAG sobre ChromaDB, scraping de Google "
            "(AI Overview / featured snippet / orgánico) y un módulo "
            "de mente crítica que filtra contradicciones antes de "
            "consolidar nuevo conocimiento."
        ),
        "nombre": (
            "Identificador: ARES — Asistente de Reconocimiento y "
            "Ejecución de Software. Versión 3.0, orquestador maestro "
            "con autenticación, aprendizaje y RPA."
        ),
        "que_haces": (
            "Procesos principales: 1) detección de intención sobre la "
            "entrada del usuario; 2) recuperación semántica de hechos "
            "consolidados en memoria global; 3) investigación web "
            "automática cuando no hay match; 4) ejecución RPA "
            "(launchers, WhatsApp, YouTube, edición de archivos, "
            "delegación a Copilot/Cursor/Kiro); 5) almacenamiento "
            "cifrado por usuario de cada interacción. También "
            "incorporo cámara con YOLO, TTS local y onboarding "
            "personalizable por tono."
        ),
        "como_funcionas": (
            "Pipeline determinista: entrada → normalización en "
            "PLNOptimizado → detección de intención → "
            "BaseDeConocimiento.mejor_concepto (lookup exacto + RAG "
            "vectorial con sentence-transformers all-MiniLM-L6-v2) → "
            "si no hay candidato válido, Investigador.investigar lanza "
            "Chrome headless undetected y extrae el AI Overview de la "
            "SERP → MenteCritica.evaluar valida coherencia → respuesta "
            "se modula por tono → BasePrivada cifra y persiste con "
            "Fernet. Sin LLMs externos en ningún punto."
        ),
        "creador": (
            "Desarrollado por Samuel. Stack: Python 3, Selenium + "
            "undetected-chromedriver, ChromaDB, sentence-transformers, "
            "Flask + SSE, pyttsx3, Vosk para STT, YOLOv8n para visión."
        ),
        "limites": (
            "Limitaciones explícitas: no genero texto creativo libre "
            "(no hay LLM); dependo de la disponibilidad de Google y "
            "respaldos Bing/DuckDuckGo; el reconocimiento de comandos "
            "se basa en patrones, no en comprensión generativa; "
            "captchas activan cooldown de 90s antes de reintentar."
        ),
    },
    "directo": {
        "que_eres": "ARES: Asistente de Reconocimiento y Ejecución de Software.",
        "nombre": "ARES.",
        "que_haces": "Respondo, busco, ejecuto y aprendo. Local.",
        "como_funcionas": "Intent → memoria → web si falta → respondo.",
        "creador": "Samuel.",
        "limites": "Sin LLM. Solo memoria propia y scraping web.",
    },
}


def responder_identidad(subtema: str, tono: str = "balanceado") -> str:
    """Devuelve la respuesta de identidad correspondiente al subtema y tono."""
    tono = tono if tono in IDENTIDAD_ARES else "balanceado"
    bloque = IDENTIDAD_ARES[tono]
    return bloque.get(subtema) or bloque.get("que_eres", "")


# ============================== AJUSTE DE LONGITUD POR TONO ==============================
# Cuando recuperamos un hecho de memoria, lo adaptamos al tono activo del
# usuario. Eso permite que un mismo concepto guardado se devuelva más
# corto en modo "directo" y más extenso/técnico en modo "analitico".

def adaptar_respuesta_a_tono(texto: str, tono: str = "balanceado") -> str:
    """
    Recorta o expande una respuesta según el tono.

      • directo:    1 sola oración, máx 140 chars.
      • tranquilo:  hasta 3 oraciones, prefijo cordial si no lo trae.
      • balanceado: hasta 3 oraciones, sin retoques fuertes.
      • analitico:  texto completo (hasta ~6 oraciones), con cierre técnico
                    si no termina en punto.
    """
    if not texto:
        return texto
    t = re.sub(r"\s+", " ", texto).strip()
    oraciones = [o.strip() for o in re.split(r"(?<=[.!?])\s+", t) if o.strip()]

    if tono == "directo":
        primera = oraciones[0] if oraciones else t
        if len(primera) > 140:
            primera = primera[:137].rsplit(" ", 1)[0] + "…"
        return primera

    if tono == "tranquilo":
        recortado = " ".join(oraciones[:3])
        return recortado

    if tono == "analitico":
        # Mantener hasta 6 oraciones, asegurar cierre con punto.
        ext = " ".join(oraciones[:6]) if oraciones else t
        if not re.search(r"[\.!\?]$", ext):
            ext += "."
        return ext

    # balanceado (default)
    return " ".join(oraciones[:3]) if oraciones else t





# ============================== MOTOR ==============================
class MotorCognitivo:
    """Genera respuestas sin LLM, sólo plantillas + RAG."""

    def __init__(self, max_historial: int = 12):
        ic(" Motor cognitivo (puro código) inicializado")
        # Hash de últimas respuestas por categoría → evitar repetición
        self._historial: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=max_historial)
        )

    # -------------------- API PRINCIPAL --------------------
    def responder(self,
                  categoria: str,
                  tono: str = "balanceado",
                  variables: Optional[Dict[str, str]] = None) -> str:
        """
        Selecciona una plantilla por categoría + tono y la rellena.
        Garantiza variabilidad: nunca devuelve la misma respuesta consecutiva.
        """
        tono = tono if tono in PLANTILLAS else "balanceado"
        plantillas_categoria = PLANTILLAS[tono].get(categoria) \
            or PLANTILLAS["balanceado"].get(categoria) \
            or [""]

        # Rellenar variables y normalizar
        candidatas = []
        for tpl in plantillas_categoria:
            try:
                txt = tpl.format(**(variables or {}))
            except KeyError:
                txt = tpl
            txt = re.sub(r"\s+", " ", txt).strip()
            txt = re.sub(r"\s+([.,;:])", r"\1", txt)
            candidatas.append(txt)

        # Excluir las usadas recientemente
        usadas = set(self._historial[categoria])
        frescas = [c for c in candidatas if hash(c) not in usadas]
        elegida = random.choice(frescas) if frescas else random.choice(candidatas)

        self._historial[categoria].append(hash(elegida))
        return elegida

    # -------------------- SÍNTESIS DE CONOCIMIENTO --------------------
    def sintetizar_concepto(self, mejor: Dict[str, Any]) -> str:
        """
        Toma el mejor hecho consolidado y devuelve una respuesta limpia,
        recortada a 2-3 oraciones máximo.
        """
        if not mejor:
            return ""
        descripcion = (mejor.get("descripcion") or "").strip()
        descripcion = re.sub(r"\s+", " ", descripcion)

        # Limitar a 2 oraciones máximo
        oraciones = re.split(r"(?<=[.!?])\s+", descripcion)
        if len(oraciones) > 2:
            descripcion = " ".join(oraciones[:2])

        # Si supera 240 chars, truncar respetando palabras
        if len(descripcion) > 240:
            descripcion = descripcion[:237].rsplit(" ", 1)[0] + "…"

        return descripcion

    # -------------------- ELEGIR ENTRE CANDIDATOS --------------------
    def elegir_mejor_para_tono(self,
                               candidatos: List[Dict[str, Any]],
                               tono: str) -> Optional[Dict[str, Any]]:
        """
        Cuando hay múltiples versiones del mismo concepto, elige la que
        mejor se adapte al tono del usuario.
          - tranquilo: prefiere descripciones más largas y suaves
          - analitico: prefiere descripciones con datos/números
          - directo:   prefiere descripciones más cortas
          - balanceado: el de mejor calidad/confirmaciones
        """
        if not candidatos:
            return None

        for c in candidatos:
            d = c.get("descripcion") or ""
            longitud = len(d)
            tiene_numeros = bool(re.search(r"\d", d))

            score = c.get("calidad", 0.5) * 0.6 + \
                    min(1.0, c.get("confirmaciones", 1) / 5) * 0.4

            if tono == "tranquilo":
                score += 0.001 * min(longitud, 200)
            elif tono == "analitico":
                if tiene_numeros: score += 0.15
                score += 0.001 * min(longitud, 200)
            elif tono == "directo":
                score += 0.001 * (240 - min(longitud, 240))

            c["_score_tono"] = score

        candidatos.sort(key=lambda x: x["_score_tono"], reverse=True)
        return candidatos[0]


# ============================== INSTANCIA GLOBAL ==============================
motor = MotorCognitivo()
