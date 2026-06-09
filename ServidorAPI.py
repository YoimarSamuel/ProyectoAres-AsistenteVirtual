"""
================================================================================
        ARES v3.0 — Servidor Flask (UI + API + Streaming + Auth)
================================================================================
"""

from __future__ import annotations
import json
import threading
import time
from pathlib import Path
from typing import Generator
from icecream import ic

from flask import (Flask, request, jsonify, send_from_directory,
                   Response, session, abort)
from flask_cors import CORS

# ============================== Backend imports ==============================
from Auth import auth, POLITICA_PRIVACIDAD
from Ares import ares
from CamaraStream import camara
from VozAres import voz
from Telemetria import stats_sistema, uptime, obtener_clima
from BaseDeConocimiento import base_global, base_privada
from MenteCritica import mente_critica
from Donaciones import (crear_donacion, estado_pasarelas,
                          DIVISAS_SOPORTADAS)


BASE_DIR = Path(__file__).parent

app = Flask(__name__,
            static_folder=str(BASE_DIR),
            static_url_path="")
app.secret_key = "ares-v3-local-secret-change-in-production"
CORS(app, supports_credentials=True)


# ============================== Iniciar always-on ==============================
def _bootstrap_async():
    """Levanta cámara siempre. Voz STT requiere PyAudio (opcional)."""
    try:
        camara.iniciar()
    except Exception as e:
        ic(f" Cámara no se pudo iniciar: {e}")


_bootstrap_async()


def _auto_iniciar_voz():
    """Arranca el micrófono apenas el usuario tenga sesión.
    Reintenta hasta que `auth.autenticado` sea True o se den 60 reintentos.
    Se ejecuta en hilo daemon para no bloquear el arranque del servidor.
    """
    def _runner():
        # Esperar a que haya sesión iniciada
        for _ in range(60):
            if auth.autenticado:
                break
            time.sleep(2)
        if not auth.autenticado:
            ic("ℹ Voz: sin login después de 2 min, no se auto-inicia")
            return
        try:
            ok = voz.iniciar_escucha_continua(_voz_on_texto)
            if ok:
                ic(" Mic auto-iniciado para usuario "
                   f"{auth.usuario_actual!r}")
            else:
                ic(" Mic no pudo iniciarse (¿pyaudio?)")
        except Exception as e:
            ic(f" Mic auto-init error: {e}")

    threading.Thread(target=_runner, daemon=True).start()


def _voz_on_texto(texto: str, con_wake: bool) -> None:
    """Callback de STT. Despacha el procesamiento en un hilo aparte para no
    bloquear el callback de `listen_in_background`. Si lo dejamos síncrono,
    mientras `ares.procesar()` consulta la web/escribe al chat de Copilot,
    el reconocedor no entrega la siguiente frase y se pierden preguntas.

    Importante: pasamos `hablar_respuesta=False` porque el frontend (UI web)
    ya lee la respuesta con la Web Speech API del navegador. Si dejáramos
    además que el backend hablase con pyttsx3 oirías la voz dos veces (o,
    si pyttsx3 está silenciado en tu sistema, NO oirías nada por confiar en
    él). Centralizamos la voz en el navegador, que es más fiable.
    """
    ic(f" Voz heard: '{texto}' wake={con_wake}")
    _push_voice_event({
        "tipo": "transcripcion",
        "texto": texto,
        "con_wake": con_wake,
        "ts": time.time(),
    })
    if not (con_wake and texto.strip()):
        return

    def _procesar():
        try:
            res = ares.procesar(texto, hablar_respuesta=False)
            _push_voice_event({
                "tipo": "respuesta",
                "texto": res.get("respuesta", ""),
                "intencion": res.get("intencion", ""),
                "ts": time.time(),
            })
        except Exception as e:
            ic(f" procesar voz: {e}")

    threading.Thread(target=_procesar, daemon=True).start()


# Si ya hay sesión activa al recargar, también lo arranca (caso F5).
_auto_iniciar_voz()


# ============================== STATIC / UI ==============================
@app.route("/")
def index():
    # Si no hay usuario en sesión → mostrar login.html
    if not session.get("username"):
        return send_from_directory(str(BASE_DIR), "login.html")
    return send_from_directory(str(BASE_DIR), "index.html")


@app.route("/login")
def login_page():
    return send_from_directory(str(BASE_DIR), "login.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(str(BASE_DIR), filename)


# ============================== AUTH ==============================
@app.route("/api/auth/politica", methods=["GET"])
def politica():
    return jsonify({"politica": POLITICA_PRIVACIDAD, "version": "1.0"})


@app.route("/api/auth/registrar", methods=["POST"])
def registrar():
    data = request.get_json(silent=True) or {}
    res = auth.registrar(
        username=data.get("username", ""),
        password=data.get("password", ""),
        nombre_real=data.get("nombre_real", ""),
        acepta_politica=bool(data.get("acepta_politica", False)),
        tono=data.get("tono", "balanceado")
    )
    return jsonify(res), (200 if res.get("ok") else 400)


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    res = auth.login(data.get("username", ""), data.get("password", ""))
    if res.get("ok"):
        session["username"] = res["username"]
        # Auto-iniciar el micrófono al loguearse
        try:
            _auto_iniciar_voz()
        except Exception as e:
            ic(f" auto mic post-login: {e}")
    return jsonify(res), (200 if res.get("ok") else 401)


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    auth.logout()
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/auth/perfil", methods=["GET", "PATCH"])
def perfil():
    if not auth.autenticado:
        return jsonify({"error": "No autenticado"}), 401

    if request.method == "PATCH":
        data = request.get_json(silent=True) or {}
        if "tono" in data:
            ok = auth.actualizar_tono(data["tono"])
            if not ok:
                return jsonify({"error": "tono inválido"}), 400
        return jsonify(auth.perfil_actual())

    return jsonify(auth.perfil_actual())


def _require_auth():
    """Helper: rechaza si no autenticado."""
    if not auth.autenticado:
        return jsonify({"error": "No autenticado"}), 401
    return None


# ============================== ESTADO GENERAL ==============================
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "ares_activo": True,
        "autenticado": auth.autenticado,
        "version": "3.0"
    })


@app.route("/api/estado", methods=["GET"])
def estado():
    err = _require_auth()
    if err: return err
    return jsonify(ares.estado_completo())


# ============================== CHAT ==============================
@app.route("/api/chat", methods=["POST"])
def chat():
    err = _require_auth()
    if err: return err

    data = request.get_json(silent=True) or {}
    mensaje = (data.get("mensaje") or "").strip()
    hablar  = bool(data.get("hablar", True))

    if not mensaje:
        return jsonify({"error": "Mensaje vacío"}), 400

    res = ares.procesar(mensaje, hablar_respuesta=hablar)
    return jsonify(res)


@app.route("/api/historial", methods=["GET"])
def historial():
    err = _require_auth()
    if err: return err
    return jsonify({"historial": ares.historial_sesion})


# ============================== TELEMETRÍA WIDGETS ==============================
@app.route("/api/sistema", methods=["GET"])
def sistema():
    return jsonify(stats_sistema())


@app.route("/api/uptime", methods=["GET"])
def uptime_api():
    return jsonify(uptime())


@app.route("/api/clima", methods=["GET"])
def clima():
    ciudad = request.args.get("ciudad", "auto")
    return jsonify(obtener_clima(ciudad))


# ============================== CÁMARA ==============================
@app.route("/api/camara/estado", methods=["GET"])
def camara_estado():
    return jsonify(camara.estado())


@app.route("/api/camara/stream")
def camara_stream():
    """MJPEG streaming endpoint."""
    def gen() -> Generator[bytes, None, None]:
        last_id = 0
        while True:
            frame = camara.obtener_jpeg()
            if frame is not None:
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
            time.sleep(1 / 24)

    return Response(gen(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/camara/iniciar", methods=["POST"])
def camara_iniciar():
    ok = camara.iniciar()
    return jsonify({"ok": ok, "estado": camara.estado()})


@app.route("/api/camara/detener", methods=["POST"])
def camara_detener():
    camara.detener()
    return jsonify({"ok": True})


# ============================== VOZ ==============================
@app.route("/api/voz/hablar", methods=["POST"])
def voz_hablar():
    err = _require_auth()
    if err: return err
    data = request.get_json(silent=True) or {}
    texto = (data.get("texto") or "").strip()
    if not texto:
        return jsonify({"error": "Texto vacío"}), 400
    voz.hablar(texto)
    return jsonify({"ok": True})


@app.route("/api/voz/escucha/iniciar", methods=["POST"])
def voz_escucha_iniciar():
    err = _require_auth()
    if err: return err
    ok = voz.iniciar_escucha_continua(_voz_on_texto)
    return jsonify({"ok": ok})


@app.route("/api/voz/escucha/detener", methods=["POST"])
def voz_escucha_detener():
    voz.detener_escucha()
    return jsonify({"ok": True})


# --- Bus simple en memoria para empujar eventos de voz al frontend (SSE) ---
import queue as _queue

_voice_subscribers: list = []
_voice_subs_lock = threading.Lock()


def _push_voice_event(evt: dict) -> None:
    """Encola un evento de voz para todos los clientes SSE conectados."""
    with _voice_subs_lock:
        muertos = []
        for q in _voice_subscribers:
            try:
                q.put_nowait(evt)
            except Exception:
                muertos.append(q)
        for q in muertos:
            try:
                _voice_subscribers.remove(q)
            except ValueError:
                pass


@app.route("/api/voz/eventos", methods=["GET"])
def voz_eventos():
    """Stream SSE: cada cliente abre esta conexión y recibe transcripciones
    y respuestas en tiempo real."""
    err = _require_auth()
    if err:
        return err

    q: "_queue.Queue[dict]" = _queue.Queue(maxsize=64)
    with _voice_subs_lock:
        _voice_subscribers.append(q)

    def _gen():
        # Notifica al cliente que el canal está abierto
        yield f"data: {json.dumps({'tipo': 'hello'})}\n\n"
        try:
            while True:
                try:
                    evt = q.get(timeout=15)
                    yield f"data: {json.dumps(evt)}\n\n"
                except _queue.Empty:
                    # Heartbeat para que el navegador no cierre la conexión
                    yield ": ping\n\n"
        except GeneratorExit:
            pass
        finally:
            with _voice_subs_lock:
                if q in _voice_subscribers:
                    _voice_subscribers.remove(q)

    return Response(_gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                            "X-Accel-Buffering": "no"})


# ============================== CONOCIMIENTO ==============================
@app.route("/api/conocimiento/buscar", methods=["POST"])
def conocimiento_buscar():
    err = _require_auth()
    if err: return err
    data = request.get_json(silent=True) or {}
    q = (data.get("query") or "").strip()
    if not q:
        return jsonify({"error": "query vacío"}), 400
    return jsonify({
        "global":  base_global.buscar_concepto(q, n=5),
        "privado": base_privada.buscar_interacciones(q, n=3)
    })


@app.route("/api/conocimiento/ensenar", methods=["POST"])
def conocimiento_ensenar():
    """Permite al usuario enseñar manualmente con validación de mente crítica."""
    err = _require_auth()
    if err: return err

    data = request.get_json(silent=True) or {}
    tema = (data.get("tema") or "").strip()
    descripcion = (data.get("descripcion") or "").strip()
    privado = bool(data.get("privado", False))

    if not tema or not descripcion:
        return jsonify({"error": "tema y descripcion requeridos"}), 400

    if privado:
        # No pasa por mente crítica (es personal del usuario)
        base_privada.guardar_persona(tema, {"descripcion": descripcion,
                                              "fuente": "manual"})
        return jsonify({"ok": True, "destino": "privado"})

    # Global → mente crítica
    ev = mente_critica.evaluar(tema, descripcion)
    if ev["aceptado"]:
        doc_id = base_global.agregar_hecho(
            tema, descripcion,
            autor_username=auth.usuario_actual,
            calidad=ev["calidad"],
            fuente="manual"
        )
        return jsonify({"ok": True, "destino": "global",
                        "id": doc_id, "calidad": ev["calidad"]})
    else:
        base_global.registrar_rechazo(
            tema, descripcion,
            autor_username=auth.usuario_actual,
            razon=ev["razon"]
        )
        return jsonify({"ok": False, "razon": ev["razon"]}), 400


@app.route("/api/conocimiento/stats", methods=["GET"])
def conocimiento_stats():
    err = _require_auth()
    if err: return err
    return jsonify({
        "global":  base_global.estadisticas(),
        "privado": base_privada.estadisticas() if auth.autenticado else None
    })


# ============================== DONACIONES ==============================
@app.route("/api/donaciones/estado", methods=["GET"])
def donaciones_estado():
    return jsonify(estado_pasarelas())


@app.route("/api/donaciones/crear", methods=["POST"])
def donaciones_crear():
    data = request.get_json(silent=True) or {}
    try:
        monto = float(data.get("monto", 0))
    except Exception:
        return jsonify({"ok": False, "error": "monto inválido"}), 400
    divisa = (data.get("divisa") or "usd").lower()
    pasarela = data.get("pasarela", "auto")

    if monto <= 0:
        return jsonify({"ok": False, "error": "monto debe ser > 0"}), 400

    res = crear_donacion(monto, divisa,
                         username=auth.usuario_actual or "anon",
                         pasarela=pasarela)
    return jsonify(res), (200 if res.get("ok") else 400)


# ============================== MAIN ==============================
def iniciar_servidor(host: str = "127.0.0.1", port: int = 5000,
                     debug: bool = False):
    ic(f" Servidor ARES v3 → http://{host}:{port}")
    app.run(host=host, port=port, debug=debug,
            use_reloader=False, threaded=True)


if __name__ == "__main__":
    iniciar_servidor(debug=False)
