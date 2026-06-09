"""
================================================================================
        ARES — RPA de editores (VS Code, Cursor, Windsurf, Antigravity…)
================================================================================
Acciones soportadas SIN pyautogui (alineado con el requisito de RPA invisible):

  1. crear_archivo(ruta, contenido)
       Crea o sobreescribe un archivo en disco.

  2. abrir_en_editor(editor, ruta)
       Abre el archivo (o carpeta) en el editor solicitado vía CLI.
       Editores con CLI estable que aceptan paths:
         • code        → VS Code / VS Code Insiders
         • cursor      → Cursor
         • windsurf    → Windsurf
         • subl        → Sublime
         • notepad++   → Notepad++ (notepad++.exe)

  3. delegar_instruccion_ia(alias, instruccion, proyecto)
       Reusa DelegadorIA: lanza la CLI de una IA de desarrollo
       (Claude Code, Antigravity, Aider...) y le inyecta la instrucción
       por stdin. Ideal para "abre Antigravity y escribe en el chat: …".

LIMITACIÓN HONESTA — NO se incluye:
   Escribir en el cuadro de chat de Copilot dentro de VS Code/Cursor/Windsurf
    cuando la app ya está abierta. Esos chats son UI WebView privadas sin API
    pública, y la única forma sería pyautogui/teclas en pantalla, lo cual
    contradice el requisito de RPA invisible.
================================================================================
"""

from __future__ import annotations
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List
from icecream import ic


# Mapeo alias → ejecutable CLI esperado en PATH
EDITORES_CLI: Dict[str, List[str]] = {
    "code":        ["code", "code-insiders", "code.cmd"],
    "vscode":      ["code", "code-insiders", "code.cmd"],
    "visual":      ["code", "code-insiders", "code.cmd"],
    "visual studio code": ["code", "code-insiders", "code.cmd"],
    "cursor":      ["cursor", "cursor.cmd"],
    "windsurf":    ["windsurf", "windsurf.cmd"],
    "sublime":     ["subl", "subl.exe"],
    "notepad++":   ["notepad++", "notepad++.exe"],
    "notepad":     ["notepad"],
}


def _resolver_editor(alias: str) -> Optional[str]:
    """Devuelve el comando CLI real disponible en PATH para un alias."""
    nombres = EDITORES_CLI.get(alias.lower().strip())
    if not nombres:
        return None
    for n in nombres:
        cmd = shutil.which(n)
        if cmd:
            return cmd
    return None


# ========================== CREAR / EDITAR ARCHIVOS ==========================
def crear_archivo(ruta: str, contenido: str = "",
                  sobrescribir: bool = True) -> Dict[str, Any]:
    """Crea (o sobreescribe) un archivo con el contenido dado."""
    p = Path(ruta).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and not sobrescribir:
        return {"ok": False, "error": f"Ya existe: {p}"}
    try:
        p.write_text(contenido, encoding="utf-8")
        ic(f" Archivo creado: {p} ({len(contenido)} chars)")
        return {"ok": True, "ruta": str(p)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def abrir_en_editor(editor: str, ruta: str = "",
                    nueva_ventana: bool = False) -> Dict[str, Any]:
    """Abre `ruta` en el editor indicado (alias o nombre de CLI)."""
    cmd = _resolver_editor(editor) or shutil.which(editor)
    if not cmd:
        return {"ok": False, "error": f"Editor '{editor}' no está en PATH."}

    args = [cmd]
    # Flags conocidos para "nueva ventana"
    if nueva_ventana and Path(cmd).name.startswith(("code", "cursor", "windsurf")):
        args.append("--new-window")
    if ruta:
        args.append(str(Path(ruta).expanduser()))

    try:
        subprocess.Popen(args)
        ic(f" {editor} abierto: {' '.join(args)}")
        return {"ok": True, "editor": editor, "comando": cmd, "args": args[1:]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def crear_y_abrir(editor: str, ruta: str, contenido: str = "") -> Dict[str, Any]:
    """Atajo: crea el archivo y lo abre en el editor pedido."""
    res_c = crear_archivo(ruta, contenido)
    if not res_c.get("ok"):
        return res_c
    res_a = abrir_en_editor(editor, ruta)
    return {"ok": res_a.get("ok"),
            "ruta": res_c["ruta"],
            "editor": editor,
            "abierto": res_a.get("ok"),
            "error_apertura": res_a.get("error")}


# ========================== DELEGAR A IA POR CLI ==========================
def delegar_instruccion_ia(alias: str, instruccion: str,
                            proyecto: Optional[str] = None) -> Dict[str, Any]:
    """
    Lanza la CLI de la IA y le inyecta la instrucción por stdin.
    Usa DelegadorIA (Kiro/Claude Code/Antigravity/Cursor/VSCode).
    """
    try:
        from DelegadorIA import delegador
    except Exception as e:
        return {"ok": False, "error": f"DelegadorIA no disponible: {e}"}

    return delegador.delegar(alias, instruccion, proyecto=proyecto)
