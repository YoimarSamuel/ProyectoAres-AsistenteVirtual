"""
================================================================================
        ARES — Lanzador genérico de aplicaciones de escritorio
================================================================================
Permite abrir CUALQUIER app que el usuario tenga instalada:
  1. Si está en PATH (kiro, code, chrome) → la abre por nombre
  2. Si está en el menú inicio (.lnk de Windows) → la abre por shortcut
  3. Si no, intenta `start <app>` (Windows) que delega al sistema
================================================================================
"""

from __future__ import annotations
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, Optional, List
from icecream import ic


# Carpetas estándar del menú inicio de Windows
START_MENU_DIRS = [
    Path(os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs")),
    Path(os.path.expandvars(r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs"))
]


def _buscar_lnk(nombre: str) -> Optional[Path]:
    """Busca un .lnk con ese nombre (case-insensitive) en el menú inicio."""
    nombre_low = nombre.lower().strip()
    for base in START_MENU_DIRS:
        if not base.exists():
            continue
        for lnk in base.rglob("*.lnk"):
            stem = lnk.stem.lower()
            if stem == nombre_low or nombre_low in stem:
                return lnk
    return None


def listar_apps_instaladas(filtro: str = "") -> List[str]:
    """Lista nombres de apps detectables vía menú inicio."""
    nombres = set()
    for base in START_MENU_DIRS:
        if not base.exists():
            continue
        for lnk in base.rglob("*.lnk"):
            n = lnk.stem
            if not filtro or filtro.lower() in n.lower():
                nombres.add(n)
    return sorted(nombres)


def abrir_app(nombre: str, args: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Estrategia de cascada:
      1) shutil.which → ejecutable en PATH
      2) Buscar .lnk en menú inicio
      3) `start "" <nombre>` (Windows shell asociaciones)
    """
    nombre = (nombre or "").strip()
    if not nombre:
        return {"ok": False, "error": "Nombre vacío"}

    args = args or []

    # 1) En PATH
    cli = shutil.which(nombre) or shutil.which(nombre + ".exe")
    if cli:
        try:
            subprocess.Popen([cli] + args)
            ic(f"Abierto desde PATH: {cli}")
            return {"ok": True, "metodo": "path", "ruta": cli}
        except Exception as e:
            ic(f"PATH {nombre}: {e}")

    # 2) .lnk del menú inicio
    lnk = _buscar_lnk(nombre)
    if lnk:
        try:
            os.startfile(str(lnk))
            ic(f"Abierto desde menú inicio: {lnk}")
            return {"ok": True, "metodo": "start_menu", "ruta": str(lnk)}
        except Exception as e:
            ic(f"lnk {nombre}: {e}")

    # 3) Shell de Windows con `start`
    if sys.platform == "win32":
        try:
            subprocess.Popen(["cmd", "/c", "start", "", nombre],
                             creationflags=subprocess.CREATE_NEW_CONSOLE)
            ic(f"Delegado al shell: start {nombre}")
            return {"ok": True, "metodo": "shell"}
        except Exception as e:
            ic(f"shell {nombre}: {e}")

    return {"ok": False, "error": f"No encontré '{nombre}'."}


def cerrar_app(nombre_proceso: str) -> Dict[str, Any]:
    """Cierra una app por nombre de proceso (notepad.exe, chrome.exe, …)."""
    if sys.platform != "win32":
        return {"ok": False, "error": "Sólo Windows"}
    try:
        r = subprocess.run(
            ["taskkill", "/IM", nombre_proceso, "/F"],
            capture_output=True, text=True, timeout=10
        )
        return {"ok": r.returncode == 0, "salida": r.stdout, "error": r.stderr}
    except Exception as e:
        return {"ok": False, "error": str(e)}
