#!/usr/bin/env python3
"""
ARES — Refresca el perfil de Chrome usado por el Investigador.

Borra la copia local del perfil clonado y la vuelve a copiar desde tu
Chrome real. Útil si renovaste tu contraseña de Google, cambiaste de
cuenta o tu sesión expiró.

  IMPORTANTE: Cierra Chrome antes de ejecutar este script. Algunos
archivos del perfil (como Cookies) están bloqueados mientras Chrome
está abierto y la copia podría fallar.

Uso:  python refrescar_perfil_chrome.py
"""
import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from Investigador import PERFIL_CHROME, _clonar_perfil_real


def main() -> int:
    print("=" * 60)
    print("ARES — Refrescar perfil de Chrome")
    print("=" * 60)
    print(f"Perfil de ARES: {PERFIL_CHROME}")

    if PERFIL_CHROME.exists():
        respuesta = input(
            "El perfil clonado ya existe. ¿Borrar y rehacer? "
            "(escribe 'si' para confirmar): "
        ).strip().lower()
        if respuesta not in {"si", "sí", "s", "yes", "y"}:
            print("Cancelado.")
            return 1
        try:
            shutil.rmtree(PERFIL_CHROME)
            print(" Perfil anterior borrado")
        except Exception as e:
            print(f" No pude borrar el perfil anterior: {e}")
            print("  Cierra Chrome y vuelve a intentarlo.")
            return 1

    print("\nClonando desde tu Chrome real...")
    if _clonar_perfil_real(forzar=True):
        print(f" Perfil clonado en {PERFIL_CHROME}")
        print("  Ahora ARES usará tu sesión de Google al buscar.")
        return 0
    else:
        print(" No se pudo clonar el perfil. Verifica que Chrome esté")
        print("  instalado y que tengas al menos una cuenta iniciada.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
