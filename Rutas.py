"""
================================================================================
        ARES — Rutas nativas del sistema operativo
================================================================================
Storage centralizado:
  Windows: %APPDATA%/ARES/storage/...
  macOS:   ~/Library/Application Support/ARES/storage/...
  Linux:   ~/.config/ares/storage/...
================================================================================
"""

from __future__ import annotations
from pathlib import Path
import appdirs
from icecream import ic

_DIRS = appdirs.AppDirs(appname="ARES", appauthor="ARES", roaming=True)

ROOT     = Path(_DIRS.user_data_dir)
STORAGE  = ROOT / "storage"
PRIVATE  = STORAGE / "private"   # por usuario (cifrado)
GLOBAL   = STORAGE / "global"    # conocimiento técnico compartido
LOGS     = ROOT / "logs"

USERS_DB         = PRIVATE / "users.json"
GLOBAL_VECTORDB  = GLOBAL  / "vector"
USERS_DIR        = PRIVATE / "users"

# Crear estructura
for p in (ROOT, STORAGE, PRIVATE, GLOBAL, LOGS,
          GLOBAL_VECTORDB, USERS_DIR):
    p.mkdir(parents=True, exist_ok=True)


def ruta_usuario(username: str) -> Path:
    """Carpeta privada de un usuario."""
    p = USERS_DIR / username.strip().lower()
    p.mkdir(parents=True, exist_ok=True)
    (p / "vector").mkdir(parents=True, exist_ok=True)
    return p


def ruta_vector_usuario(username: str) -> Path:
    return ruta_usuario(username) / "vector"


def ruta_sqlite_usuario(username: str) -> Path:
    return ruta_usuario(username) / "private_data.db"


ic(f" ARES storage root: {ROOT}")
