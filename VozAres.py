"""
================================================================================
        ARES v2.2 — Sistema de Voz (TTS Jarvis-like + STT continuo)
================================================================================
Cambios v2.2:
  • TTS gestionado por UN SOLO worker-thread con cola FIFO. El engine de
    pyttsx3 se crea DENTRO de ese hilo y nunca se toca desde fuera. Esto
    evita el bug clásico en Windows/SAPI5 donde el segundo `runAndWait()`
    cuelga indefinidamente cuando se llama desde hilos distintos. Síntoma:
    primera respuesta hablada OK, micrófono "muerto" después porque
    `self._hablando` quedaba pegado en True.
  • Watchdog: si `_hablando` lleva > TTS_WATCHDOG_S segundos en True (engine
    colgado), se libera el flag para que el STT no quede sordo.
  • `interrumpir_tts()` para cortar la cola y abortar el habla en curso.
Cambios v2.1:
  • STT con `listen_in_background()` → el micrófono queda abierto SIEMPRE.
  • Modo conversacional con ventana `MODO_CONV_S`.
  • Pausa "TTS aware" anti-eco.
================================================================================
"""

from __future__ import annotations
import queue
import threading
import time
from typing import Callable, Optional
from icecream import ic

import pyttsx3

try:
    import speech_recognition as sr
    SR_OK = True
except Exception:
    SR_OK = False

# Voces preferidas (masculinas, latinas, "confianza"). Coincidencia parcial.
PREFERENCIAS_VOZ = [
    "spanish (mexico)", "spanish (latin)", "spanish (us)",
    "sabina", "pablo", "diego", "jorge", "carlos",
    "helena", "spanish",  # fallbacks
]

WAKE_WORDS = {"ares", "jarvis", "arez", "aris"}

# Frases enteras que también activan a ARES (se eliminan al inicio de la frase
# antes de procesar). Permite "oye ares hazme X" o "hola jarvis pon música".
WAKE_PHRASES = (
    "oye ares", "oye", "oye arez", "oye aris",
    "hola ares", "hola jarvis", "hey ares", "hey jarvis",
    "ok ares", "ok jarvis", "ola ares",
)

# Ventana de modo conversacional: tras procesar un comando válido, durante
# este tiempo cualquier transcripción se considera dirigida a ARES (sin
# necesidad de wake-word). Se renueva en cada interacción.
MODO_CONV_S = 25.0

# Si pones esto en True, ARES procesa SIEMPRE lo que escuche (sin wake-word
# nunca). Más cómodo si tienes el chat abierto en primer plano y poco ruido.
SIEMPRE_ESCUCHANDO = True

# Tope máximo (segundos) que `_hablando` puede estar en True. Si el engine
# de pyttsx3 se cuelga (ocurre en Windows con SAPI5 a veces), liberamos el
# flag para que el STT no quede sordo permanentemente.
TTS_WATCHDOG_S = 8.0


class GestorVoz:
    """Maneja síntesis y reconocimiento continuo en hilos independientes."""

    def __init__(self):
        ic("Inicializando GestorVoz…")

        # ----- TTS worker thread -----
        # El engine se crea DENTRO del worker para evitar problemas de
        # afinidad de hilo en Windows/SAPI5. Aquí solo dejamos la cola.
        self._tts_q: "queue.Queue[Optional[str]]" = queue.Queue()
        self._tts_ready = threading.Event()
        self._tts_engine = None  # se setea dentro del worker

        self._hablando = False
        self._hablando_desde: float = 0.0  # para el watchdog
        self._activo = False
        self._on_texto: Optional[Callable[[str, bool], None]] = None
        # Callback recibe (texto_reconocido, viene_con_wake_word_o_seguimiento)

        # Stop function devuelta por listen_in_background
        self._stop_listening: Optional[Callable[[bool], None]] = None

        # Marca temporal del último input válido (para modo conversacional)
        self._ultimo_input_ts: float = 0.0
        self._modo_conv_s: float = MODO_CONV_S
        self._siempre_escuchando: bool = SIEMPRE_ESCUCHANDO

        # Lanzar worker TTS y esperar a que el engine esté listo
        self._tts_thread = threading.Thread(
            target=self._tts_worker, daemon=True, name="ARES-TTS"
        )
        self._tts_thread.start()
        self._tts_ready.wait(timeout=5.0)

        # STT
        if SR_OK:
            self._recognizer = sr.Recognizer()
            self._recognizer.dynamic_energy_threshold = True
            self._recognizer.pause_threshold = 0.7
            # phrase_threshold: cuánto silencio considera "fin de frase"
            self._recognizer.non_speaking_duration = 0.4
            try:
                self._mic = sr.Microphone()
            except Exception as e:
                ic(f" Micrófono no disponible: {e}")
                self._mic = None
        else:
            self._recognizer = None
            self._mic = None

        ic(" GestorVoz listo")

    # -------------------- CONFIGURACIÓN VOZ --------------------
    def _configurar_voz_masculina_latina(self, engine) -> None:
        """Selecciona la mejor voz disponible. Se llama DENTRO del worker
        TTS, así el engine es siempre el mismo hilo que lo creó."""
        try:
            voces = engine.getProperty("voices")
        except Exception as e:
            ic(f" No pude listar voces: {e}")
            return

        elegida = None
        for pref in PREFERENCIAS_VOZ:
            for v in voces:
                nombre = (v.name or "").lower()
                idv    = (v.id or "").lower()
                if pref in nombre or pref in idv:
                    elegida = v
                    break
            if elegida:
                break

        if elegida:
            engine.setProperty("voice", elegida.id)
            ic(f" Voz seleccionada: {elegida.name}")
        else:
            ic(" Sin voz latina disponible — usando default del sistema")

    # -------------------- TTS (worker dedicado) --------------------
    def _tts_worker(self) -> None:
        """Hilo único que maneja TODO el ciclo de vida del engine pyttsx3.

        En Windows/SAPI5, llamar a `runAndWait()` desde hilos distintos al
        de creación del engine cuelga el engine en el segundo turno. Aquí
        creamos el engine en este hilo y consumimos una cola FIFO.

        IMPORTANTE: SAPI5 es COM. Cada hilo que lo use debe llamar a
        CoInitialize antes de tocar el engine, o `runAndWait()` puede
        retornar al instante sin reproducir audio (síntoma: ARES "responde"
        pero no se oye nada). Con `pythoncom` lo hacemos explícito.
        """
        # Inicializar COM en este hilo (Windows). En otros sistemas no aplica.
        com_inicializado = False
        try:
            import pythoncom  # type: ignore
            pythoncom.CoInitialize()
            com_inicializado = True
            ic(" COM inicializado en hilo TTS")
        except Exception as e:
            ic(f"ℹ pythoncom no disponible (no-Windows o no instalado): {e}")

        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", 178)
            engine.setProperty("volume", 1.0)
            self._configurar_voz_masculina_latina(engine)
            self._tts_engine = engine
        except Exception as e:
            ic(f" TTS init falló: {e}")
            self._tts_ready.set()
            if com_inicializado:
                try:
                    import pythoncom  # type: ignore
                    pythoncom.CoUninitialize()
                except Exception:
                    pass
            return

        self._tts_ready.set()

        while True:
            texto = self._tts_q.get()
            try:
                if texto is None:        # señal de cierre
                    break
                if not texto:
                    continue
                try:
                    self._hablando = True
                    self._hablando_desde = time.time()
                    engine.say(texto)
                    engine.runAndWait()
                except RuntimeError as e:
                    # 'run loop already started' → recrear engine y reintentar
                    ic(f" TTS RuntimeError, reiniciando engine: {e}")
                    try:
                        engine.stop()
                    except Exception:
                        pass
                    try:
                        engine = pyttsx3.init()
                        engine.setProperty("rate", 178)
                        engine.setProperty("volume", 1.0)
                        self._configurar_voz_masculina_latina(engine)
                        self._tts_engine = engine
                    except Exception as e2:
                        ic(f" TTS no se pudo recrear: {e2}")
                except Exception as e:
                    ic(f" Error TTS: {e}")
                finally:
                    self._hablando = False
                    self._hablando_desde = 0.0
                    # Renovar la ventana conversacional cuando ARES termina:
                    # la próxima frase del usuario cuenta como continuación.
                    self._ultimo_input_ts = time.time()
            finally:
                # Imprescindible para que `_tts_q.join()` desbloquee al
                # llamador que pidió `hablar(async_=False)`.
                try:
                    self._tts_q.task_done()
                except ValueError:
                    pass

        # Cierre limpio
        if com_inicializado:
            try:
                import pythoncom  # type: ignore
                pythoncom.CoUninitialize()
            except Exception:
                pass

    def hablar(self, texto: str, async_: bool = True) -> None:
        """Encola el texto para el worker TTS. `async_` se mantiene por
        compatibilidad con la API anterior pero ya no crea hilos extra:
        el worker garantiza orden y libera al llamador inmediatamente."""
        if not texto:
            return
        ic(f"  ARES → {texto[:90]}")
        try:
            self._tts_q.put_nowait(texto)
        except Exception as e:
            ic(f" TTS queue: {e}")
        if not async_:
            # Espera (con timeout duro) a que la cola se drene, para que un
            # `hablar(...,async_=False)` no quede colgado si el engine TTS
            # falla en silencio. 30 s cubre frases largas + cualquier
            # reinicialización del engine.
            deadline = time.time() + 30.0
            while time.time() < deadline:
                if self._tts_q.unfinished_tasks == 0:
                    return
                time.sleep(0.05)
            ic(" hablar(async_=False) timeout esperando drenaje de cola")

    def interrumpir_tts(self) -> None:
        """Vacía la cola y detiene el habla actual."""
        try:
            while True:
                self._tts_q.get_nowait()
                try:
                    self._tts_q.task_done()
                except ValueError:
                    pass
        except queue.Empty:
            pass
        try:
            if self._tts_engine:
                self._tts_engine.stop()
        except Exception as e:
            ic(f" stop engine: {e}")
        self._hablando = False
        self._hablando_desde = 0.0

    @property
    def hablando(self) -> bool:
        # Watchdog: si lleva demasiado tiempo "hablando" es que el engine
        # se colgó. Liberamos para no dejar al STT sordo.
        if self._hablando and self._hablando_desde > 0:
            if (time.time() - self._hablando_desde) > TTS_WATCHDOG_S:
                ic(" TTS watchdog: liberando flag _hablando (engine colgado)")
                self._hablando = False
                self._hablando_desde = 0.0
        return self._hablando

    # -------------------- STT continuo --------------------
    def iniciar_escucha_continua(self,
                                 on_texto: Callable[[str, bool], None]) -> bool:
        """
        Inicia escucha en background con `listen_in_background()`. El micro
        queda abierto permanentemente, sin reabrirlo en cada iteración.

        on_texto(texto, con_wake) se llama desde un hilo del SDK. Para no
        bloquear ese hilo (y por tanto la escucha), lo ideal es que
        `on_texto` despache su trabajo en un hilo aparte.
        """
        if not SR_OK or not self._mic:
            ic(" STT no disponible (instala pyaudio + speech_recognition)")
            return False

        if self._activo:
            ic("ℹ Escucha continua ya activa")
            return True

        self._on_texto = on_texto
        self._activo = True

        # Calibración inicial (una sola vez)
        try:
            with self._mic as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.7)
            ic(f" Energy threshold: {self._recognizer.energy_threshold:.0f}")
        except Exception as e:
            ic(f" Calibración micro: {e}")

        # Lanzar la escucha en background. listen_in_background mantiene un
        # hilo interno que llama _on_audio cada vez que detecta una frase.
        try:
            self._stop_listening = self._recognizer.listen_in_background(
                self._mic, self._on_audio, phrase_time_limit=10
            )
            ic(" Escucha continua iniciada (background)")
            return True
        except Exception as e:
            ic(f" listen_in_background error: {e}")
            self._activo = False
            return False

    def detener_escucha(self) -> None:
        ic(" Deteniendo escucha continua")
        self._activo = False
        if self._stop_listening:
            try:
                self._stop_listening(wait_for_stop=False)
            except Exception as e:
                ic(f" stop_listening: {e}")
            self._stop_listening = None

    def _on_audio(self, recognizer: "sr.Recognizer", audio: "sr.AudioData") -> None:
        """Callback que ejecuta `listen_in_background` por cada frase oída."""
        # Si ARES está hablando, descartamos para evitar auto-realimentar el
        # TTS al STT. El reconocedor sigue activo igualmente.
        # Usamos la propiedad (con watchdog) en lugar del atributo crudo
        # para que un engine TTS colgado no deje al STT sordo para siempre.
        if self.hablando:
            return

        try:
            texto = recognizer.recognize_google(audio, language="es-ES").strip()
        except sr.UnknownValueError:
            return
        except sr.RequestError as e:
            ic(f" STT request error: {e}")
            return
        except Exception as e:
            ic(f" STT error: {e}")
            return

        if not texto:
            return

        ic(f" Heard: {texto}")

        t_low = texto.lower()
        con_wake = False

        # 1) Frases-wake completas ("oye ares X", "hola jarvis Y")
        for frase in WAKE_PHRASES:
            if t_low.startswith(frase):
                texto = texto[len(frase):].strip(" ,.;:")
                con_wake = True
                break

        # 2) Si no, palabras-wake sueltas como prefijo
        if not con_wake:
            for w in WAKE_WORDS:
                if t_low.startswith(w):
                    texto = texto[len(w):].strip(" ,.;:")
                    con_wake = True
                    break

        # 3) Si la palabra wake aparece en cualquier posición
        if not con_wake and any(w in t_low.split() for w in WAKE_WORDS):
            con_wake = True

        # 4) Modo conversacional: si hace poco hubo interacción, sigue
        #    escuchando sin exigir wake-word. Esto permite encadenar
        #    preguntas naturalmente tras la primera respuesta.
        if not con_wake:
            if self._siempre_escuchando:
                con_wake = True
            elif (time.time() - self._ultimo_input_ts) <= self._modo_conv_s \
                    and self._ultimo_input_ts > 0:
                con_wake = True
                ic(" Continuación conversacional sin wake-word")

        if not texto:
            return

        # Marcar timestamp del input válido para mantener la ventana abierta
        if con_wake:
            self._ultimo_input_ts = time.time()

        try:
            if self._on_texto:
                self._on_texto(texto, con_wake)
        except Exception as e:
            ic(f" on_texto callback error: {e}")

    # -------------------- AJUSTES EN CALIENTE --------------------
    def configurar_modo(self,
                        siempre_escuchando: Optional[bool] = None,
                        ventana_conv_s: Optional[float] = None) -> dict:
        """Cambia los parámetros de escucha sin reiniciar."""
        if siempre_escuchando is not None:
            self._siempre_escuchando = bool(siempre_escuchando)
        if ventana_conv_s is not None and ventana_conv_s >= 0:
            self._modo_conv_s = float(ventana_conv_s)
        return {
            "siempre_escuchando": self._siempre_escuchando,
            "ventana_conv_s": self._modo_conv_s,
            "activo": self._activo,
        }


# ============================== INSTANCIA ==============================
voz = GestorVoz()
