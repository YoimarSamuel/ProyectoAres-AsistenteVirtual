"""
================================================================================
        ARES — Delegador de IAs externas (Kiro / Claude Code / Antigravity)
================================================================================
ARES no piensa con IA, pero puede ABRIR otras IAs y delegarles trabajo.
Modos soportados:

  1) Modo CLI (preferido por instrucciones.md):
     - Lanza la IA por subprocess (kiro, claude, etc.)
     - Inyecta la instrucción a su stdin
     - Escucha stdout/stderr en background y notifica cuando termina

  2) Modo App de escritorio:
     - Abre la app (PATH o ejecutable conocido)
     - Sólo abre — la interacción la hace el usuario o un comando RPA aparte

ARES NUNCA hace movimientos de ratón ni pulsaciones para interactuar con
terminales (regla de instrucciones.md §7.1).
================================================================================
"""

from __future__ import annotations
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from icecream import ic


# ============================== CATÁLOGO DE IAs ==============================
# CLI canónica + alternativas conocidas. ARES intentará en orden.
IA_REGISTRY: Dict[str, Dict[str, Any]] = {
    "kiro": {
        "cli":      ["kiro", "kiro.exe"],
        "exe":      [
            r"%LOCALAPPDATA%\Programs\Kiro\Kiro.exe",
            r"%LOCALAPPDATA%\Kiro\Kiro.exe",
            r"%PROGRAMFILES%\Kiro\Kiro.exe"
        ],
        "args_cli_chat": ["chat"],   # subcomando si existe
        "stdin_supported": True
    },
    "claude_code": {
        "cli":      ["claude", "claude-code"],
        "exe":      [],
        "args_cli_chat": [],
        "stdin_supported": True
    },
    "antigravity": {
        "cli":      ["antigravity"],
        "exe":      [
            r"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe"
        ],
        "args_cli_chat": [],
        "stdin_supported": True
    },
    "cursor": {
        "cli":      ["cursor"],
        "exe":      [
            r"%LOCALAPPDATA%\Programs\cursor\Cursor.exe"
        ],
        "args_cli_chat": [],
        "stdin_supported": False
    },
    "vscode": {
        "cli":      ["code"],
        "exe":      [
            r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
            r"%PROGRAMFILES%\Microsoft VS Code\Code.exe"
        ],
        "args_cli_chat": [],
        "stdin_supported": False
    }
}


def _expandir(p: str) -> str:
    return os.path.expandvars(p)


def _localizar_cli(nombres: list[str]) -> Optional[str]:
    """Devuelve el comando CLI si está en PATH."""
    for n in nombres:
        cmd = shutil.which(n)
        if cmd:
            return cmd
    return None


def _localizar_exe(rutas: list[str]) -> Optional[str]:
    """Devuelve la ruta absoluta del .exe si existe."""
    for r in rutas:
        ruta = Path(_expandir(r))
        if ruta.exists():
            return str(ruta)
    return None


# ============================== DELEGADOR ==============================
class DelegadorIA:
    """Lanza IAs externas y les inyecta instrucciones por stdin."""

    def __init__(self):
        self._procesos: Dict[str, subprocess.Popen] = {}
        ic(" DelegadorIA listo")

    # -------------------- DETECCIÓN --------------------
    def disponible(self, alias: str) -> Dict[str, Any]:
        """¿La IA está instalada? Devuelve dónde se encontró."""
        info = IA_REGISTRY.get(alias.lower().replace(" ", "_").replace("-", "_"))
        if not info:
            return {"alias": alias, "disponible": False, "razon": "no registrada"}

        cli = _localizar_cli(info["cli"])
        exe = _localizar_exe(info["exe"])
        return {
            "alias": alias,
            "cli": cli,
            "exe": exe,
            "disponible": bool(cli or exe),
            "stdin_supported": info["stdin_supported"]
        }

    def listar_disponibles(self) -> Dict[str, Any]:
        return {alias: self.disponible(alias) for alias in IA_REGISTRY}

    # -------------------- ABRIR (sin instrucción) --------------------
    def abrir(self, alias: str,
              proyecto: Optional[str] = None) -> Dict[str, Any]:
        """Abre la IA en su modo natural (escritorio o CLI)."""
        info_disp = self.disponible(alias)
        if not info_disp["disponible"]:
            return {"ok": False, "error": f"{alias} no encontrado en este equipo"}

        # Preferir GUI (.exe) si está; si no, CLI
        target = info_disp["exe"] or info_disp["cli"]
        args = [target]
        if proyecto:
            args.append(str(Path(proyecto).expanduser()))

        try:
            subprocess.Popen(
                args,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
            ic(f" {alias} abierto: {target}")
            return {"ok": True, "alias": alias, "target": target,
                    "proyecto": proyecto}
        except Exception as e:
            ic(f" Error abriendo {alias}: {e}")
            return {"ok": False, "error": str(e)}

    # -------------------- DELEGAR (instrucción → stdin) --------------------
    def delegar(self, alias: str, instruccion: str,
                proyecto: Optional[str] = None,
                on_output: Optional[Callable[[str], None]] = None,
                on_done: Optional[Callable[[int], None]] = None
                ) -> Dict[str, Any]:
        """
        Lanza la IA en modo CLI y le inyecta `instruccion` por stdin.
        Lee stdout/stderr de forma asíncrona en hilos separados.

        Si la IA no soporta stdin, sólo se abre con el proyecto y se devuelve
        un mensaje informativo (el usuario completa la interacción a mano).
        """
        info = IA_REGISTRY.get(
            alias.lower().replace(" ", "_").replace("-", "_")
        )
        info_disp = self.disponible(alias)
        if not info_disp["disponible"]:
            return {"ok": False, "error": f"{alias} no encontrado"}

        if not info or not info["stdin_supported"] or not info_disp["cli"]:
            # Fallback: sólo abrir con el proyecto
            self.abrir(alias, proyecto)
            return {
                "ok": True,
                "modo": "abrir_solo",
                "mensaje": f"{alias} abierto. La instrucción debe enviarse manualmente."
            }

        cli = info_disp["cli"]
        args = [cli] + (info["args_cli_chat"] or [])
        cwd = str(Path(proyecto).expanduser()) if proyecto else None

        try:
            proc = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1
            )
        except Exception as e:
            ic(f" Error iniciando {alias}: {e}")
            return {"ok": False, "error": str(e)}

        self._procesos[alias] = proc
        ic(f" Delegando a {alias} (PID {proc.pid}): {instruccion[:80]}")

        # 1) Inyectar la instrucción por stdin
        try:
            proc.stdin.write(instruccion.rstrip() + "\n")
            proc.stdin.flush()
        except Exception as e:
            ic(f" stdin {alias}: {e}")

        # 2) Hilos de lectura asíncrona
        def _leer(stream, etiqueta):
            try:
                for linea in iter(stream.readline, ""):
                    if not linea:
                        break
                    linea = linea.rstrip()
                    if linea:
                        ic(f"[{alias}/{etiqueta}] {linea}")
                        if on_output:
                            try:
                                on_output(linea)
                            except Exception:
                                pass
            except Exception as e:
                ic(f" leer {alias}/{etiqueta}: {e}")

        threading.Thread(target=_leer, args=(proc.stdout, "out"), daemon=True).start()
        threading.Thread(target=_leer, args=(proc.stderr, "err"), daemon=True).start()

        # 3) Hilo que detecta finalización
        def _esperar():
            code = proc.wait()
            ic(f" {alias} terminó (exit {code})")
            self._procesos.pop(alias, None)
            if on_done:
                try:
                    on_done(code)
                except Exception:
                    pass

        threading.Thread(target=_esperar, daemon=True).start()

        return {
            "ok": True,
            "modo": "delegar_cli",
            "alias": alias,
            "pid": proc.pid,
            "instruccion": instruccion,
            "proyecto": proyecto
        }

    # -------------------- DETENER --------------------
    def detener(self, alias: str) -> Dict[str, Any]:
        proc = self._procesos.get(alias)
        if not proc:
            return {"ok": False, "error": "no hay proceso activo"}
        try:
            proc.terminate()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}


# ============================== INSTANCIA GLOBAL ==============================
delegador = DelegadorIA()
