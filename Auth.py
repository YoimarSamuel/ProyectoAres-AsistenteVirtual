"""
================================================================================
                    ARES v2.0 — Autenticación + Aislamiento de Usuarios
================================================================================
- Registro local con hash bcrypt
- Cifrado simétrico (Fernet) por usuario derivado de su contraseña
- Aceptación obligatoria de Política de Privacidad
- Aislamiento de datos privados (rostros, perfiles, hist. conversación, tono)
================================================================================
"""

from __future__ import annotations
import json
import os
import base64
import secrets
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

import bcrypt
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from icecream import ic

# ============================== RUTAS ==============================
BASE_DIR     = Path(__file__).parent
USUARIOS_DIR = BASE_DIR / "data" / "usuarios"
USERS_DB     = BASE_DIR / "data" / "usuarios.json"

USUARIOS_DIR.mkdir(parents=True, exist_ok=True)
USERS_DB.parent.mkdir(parents=True, exist_ok=True)


# ============================== POLÍTICA ==============================
POLITICA_PRIVACIDAD = """
ARES v2.0 — POLÍTICA DE PRIVACIDAD Y CONSENTIMIENTO

Al registrarte aceptas explícitamente que ARES:

1. Mantendrá la CÁMARA encendida en segundo plano para aprender de tu entorno
   (objetos, escenas, rostros con tu permiso).
2. Mantendrá el MICRÓFONO encendido para detección continua de wake-word
   y comandos hablados.
3. Tendrá CONTROL TOTAL DEL EQUIPO: abrir, leer, editar y eliminar archivos,
   ejecutar aplicaciones, navegar la web y operar otras herramientas.
4. Almacenará localmente:
   • Datos GLOBALES (compartidos): conocimiento técnico/académico depurado.
   • Datos PRIVADOS (cifrados, no compartidos): rostros, perfiles personales,
     configuración de tono y historial conversacional propio.
5. APLICARÁ Mente Crítica: rechazará información absurda o falaz que intenten
   inyectar usuarios, protegiendo el conocimiento global.
6. Datos personales NUNCA se comparten entre usuarios.

Este consentimiento se acepta UNA sola vez al registrarte y queda firmado en
tu archivo de cuenta local con timestamp.
""".strip()


# ============================== ALMACÉN ==============================
def _load_users() -> Dict[str, Any]:
    if USERS_DB.exists():
        try:
            return json.loads(USERS_DB.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_users(users: Dict[str, Any]) -> None:
    USERS_DB.write_text(json.dumps(users, indent=2, ensure_ascii=False),
                        encoding="utf-8")


# ============================== KDF ==============================
def _derivar_clave(password: str, salt: bytes) -> bytes:
    """Deriva una clave Fernet (32 bytes base64) desde una contraseña."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=200_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


# ============================== AUTENTICACIÓN ==============================
class GestorAuth:
    """
    Gestiona registro, login, política y derivación de claves de cifrado.
    El estado de usuario activo se mantiene en memoria.
    """

    def __init__(self):
        self.usuarios = _load_users()
        self.usuario_actual: Optional[str] = None
        self.fernet_actual: Optional[Fernet] = None
        ic(" GestorAuth inicializado")

    # -------------------- API: REGISTRO --------------------
    def usuario_existe(self, username: str) -> bool:
        return username.strip().lower() in self.usuarios

    def registrar(self, username: str, password: str,
                  nombre_real: str = "",
                  acepta_politica: bool = False,
                  tono: str = "balanceado") -> Dict[str, Any]:
        """
        Crea una cuenta. Devuelve {'ok': bool, 'mensaje': str}.
        Falla si la política no está aceptada o el usuario ya existe.
        """
        username = (username or "").strip().lower()

        if not username or not password:
            return {"ok": False, "mensaje": "Usuario y contraseña obligatorios."}

        if self.usuario_existe(username):
            return {"ok": False, "mensaje": "El usuario ya existe."}

        if not acepta_politica:
            return {"ok": False,
                    "mensaje": "Debes aceptar la política de privacidad."}

        # Hash de password (bcrypt)
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(12))

        # Salt para KDF (cifrado de datos privados)
        salt = secrets.token_bytes(16)

        ts = datetime.now().isoformat()

        self.usuarios[username] = {
            "username":      username,
            "nombre_real":   nombre_real or username,
            "password_hash": hashed.decode("utf-8"),
            "salt":          base64.b64encode(salt).decode("ascii"),
            "tono":          tono,
            "creado":        ts,
            "ultimo_login":  None,
            "politica":      {
                "aceptada":  True,
                "timestamp": ts,
                "version":   "1.0"
            },
            "permisos": {
                "camara":  True,
                "micro":   True,
                "control": True
            },
            "comandos_ejecutados": 0
        }
        _save_users(self.usuarios)

        # Crear directorio privado del usuario
        (USUARIOS_DIR / username).mkdir(parents=True, exist_ok=True)

        ic(f" Usuario registrado: {username}")
        return {"ok": True, "mensaje": f"Usuario {username} creado."}

    # -------------------- API: LOGIN --------------------
    def login(self, username: str, password: str) -> Dict[str, Any]:
        username = (username or "").strip().lower()
        if not self.usuario_existe(username):
            return {"ok": False, "mensaje": "Usuario no encontrado."}

        user = self.usuarios[username]
        if not bcrypt.checkpw(password.encode("utf-8"),
                              user["password_hash"].encode("utf-8")):
            return {"ok": False, "mensaje": "Contraseña incorrecta."}

        # Derivar clave Fernet en memoria (no se guarda nunca en disco)
        salt = base64.b64decode(user["salt"])
        clave = _derivar_clave(password, salt)
        self.fernet_actual = Fernet(clave)
        self.usuario_actual = username

        # Actualizar timestamp
        user["ultimo_login"] = datetime.now().isoformat()
        _save_users(self.usuarios)

        ic(f" Login: {username}")
        return {
            "ok": True,
            "username": username,
            "nombre_real": user.get("nombre_real", username),
            "tono": user.get("tono", "balanceado"),
            "mensaje": f"Bienvenido {user.get('nombre_real', username)}"
        }

    def logout(self) -> None:
        ic(f"Logout: {self.usuario_actual}")
        self.usuario_actual = None
        self.fernet_actual = None

    # -------------------- API: PERFIL --------------------
    def perfil_actual(self) -> Optional[Dict[str, Any]]:
        if not self.usuario_actual:
            return None
        u = dict(self.usuarios[self.usuario_actual])
        u.pop("password_hash", None)
        u.pop("salt", None)
        return u

    def actualizar_tono(self, tono: str) -> bool:
        if not self.usuario_actual:
            return False
        if tono not in {"tranquilo", "balanceado", "analitico", "directo"}:
            return False
        self.usuarios[self.usuario_actual]["tono"] = tono
        _save_users(self.usuarios)
        return True

    def actualizar_perfil(self, **campos) -> bool:
        """
        Actualiza campos del perfil del usuario activo.
        Solo se aceptan claves de la whitelist para evitar que el usuario
        modifique campos sensibles (password_hash, salt, política…).
        """
        if not self.usuario_actual:
            return False
        PERMITIDOS = {
            "nombre_real", "tono", "edad", "ciudad", "pais",
            "ocupacion", "idioma_preferido", "tratamiento",
            "como_llamarme", "pronombre", "zona_horaria",
        }
        reg = self.usuarios[self.usuario_actual]
        cambios = 0
        for k, v in campos.items():
            if k in PERMITIDOS and v not in (None, ""):
                if k == "tono" and v not in {"tranquilo", "balanceado",
                                              "analitico", "directo"}:
                    continue
                reg[k] = v
                cambios += 1
        if cambios:
            _save_users(self.usuarios)
            ic(f" Perfil actualizado: {list(campos.keys())}")
        return cambios > 0

    def incrementar_comandos(self) -> None:
        if self.usuario_actual:
            self.usuarios[self.usuario_actual]["comandos_ejecutados"] = \
                self.usuarios[self.usuario_actual].get("comandos_ejecutados", 0) + 1
            _save_users(self.usuarios)

    # -------------------- API: CIFRADO PRIVADO --------------------
    def cifrar(self, texto: str) -> Optional[str]:
        if not self.fernet_actual:
            return None
        return self.fernet_actual.encrypt(texto.encode("utf-8")).decode("utf-8")

    def descifrar(self, token: str) -> Optional[str]:
        if not self.fernet_actual:
            return None
        try:
            return self.fernet_actual.decrypt(token.encode("utf-8")).decode("utf-8")
        except Exception as e:
            ic(f" descifrar falló: {e}")
            return None

    def ruta_privada(self) -> Optional[Path]:
        """Carpeta privada del usuario (creada en registro)."""
        if not self.usuario_actual:
            return None
        p = USUARIOS_DIR / self.usuario_actual
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def autenticado(self) -> bool:
        return self.usuario_actual is not None


# ============================== INSTANCIA GLOBAL ==============================
auth = GestorAuth()
