#!/usr/bin/env python3
"""
ARES v2.0 - Lanzador Directo de UI Web
Inicia el servidor Flask y abre el navegador automáticamente.

Uso: python lanzar_web.py
"""

import sys
import time
import threading
import webbrowser
from pathlib import Path
from icecream import ic

# Forzar UTF-8 en consola para que los logs ic() con caracteres especiales
# (acentos, IPA de Wikipedia, emojis) no tumben el servidor en Windows.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parent))

HOST = "127.0.0.1"
PORT = 5000
URL  = f"http://{HOST}:{PORT}/"


def _abrir_navegador():
    """Abre el navegador después de que el servidor arranca"""
    time.sleep(1.8)
    try:
        webbrowser.open(URL)
        ic(f" Navegador abierto en: {URL}")
    except Exception as e:
        ic(f" No se pudo abrir navegador: {e}")
        ic(f"   Abre manualmente: {URL}")


def main():
    ic("\n" + "=" * 70)
    ic(" ARES v2.0 - UI Web (Neo-Glass / Cyber-Dark)")
    ic("=" * 70 + "\n")

    # Importar servidor
    try:
        from ServidorAPI import iniciar_servidor
        ic(" Servidor API cargado")
    except Exception as e:
        ic(f" Error cargando servidor: {e}")
        return 1

    # Lanzar navegador en hilo aparte
    threading.Thread(target=_abrir_navegador, daemon=True).start()

    ic(f" Servidor corriendo en {URL}")
    ic("Presiona Ctrl+C para detener\n")

    try:
        iniciar_servidor(host=HOST, port=PORT, debug=False)
    except KeyboardInterrupt:
        ic("\n Servidor detenido")
    return 0


if __name__ == "__main__":
    sys.exit(main())
