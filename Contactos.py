"""
================================================================================
        ARES — Libreta de contactos privada por usuario
================================================================================
Permite enviar WhatsApp/Messenger por NOMBRE en vez de número.

Almacenamiento: la base privada del usuario (cifrada con su clave Fernet).
WhatsApp Web NO expone API pública para resolver contactos por nombre, así
que ARES mantiene su propio mapa nombre→telefono. Si el usuario pide enviar
a un nombre desconocido, ARES lo pregunta una vez y lo guarda para siempre.
================================================================================
"""

from __future__ import annotations
import re
from typing import Optional, Dict, Any, List
from icecream import ic

from Auth import auth
from BaseDeConocimiento import base_privada


def _norm(nombre: str) -> str:
    return re.sub(r"\s+", " ", (nombre or "").strip().lower())


def guardar_contacto(nombre: str, telefono: str,
                     extras: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Guarda un contacto en la base privada cifrada del usuario."""
    if not auth.autenticado:
        return {"ok": False, "error": "Sin sesión activa"}
    nombre = (nombre or "").strip()
    telefono = re.sub(r"[^\d+]", "", telefono or "")
    if not nombre or not telefono:
        return {"ok": False, "error": "Nombre y teléfono requeridos"}

    datos = {"telefono": telefono, **(extras or {})}
    base_privada.guardar_persona(nombre, datos)
    ic(f" Contacto guardado: {nombre} ({telefono})")
    return {"ok": True, "nombre": nombre, "telefono": telefono}


def buscar_contacto(nombre: str) -> Optional[Dict[str, str]]:
    """Devuelve {'nombre','telefono'} si encuentra al contacto."""
    if not auth.autenticado:
        return None
    persona = base_privada.buscar_persona(nombre)
    if not persona:
        return None
    datos = persona.get("datos") or ""
    m = re.search(r"telefono=([\+\d]+)", datos)
    if not m:
        return None
    return {"nombre": persona.get("nombre") or nombre,
            "telefono": m.group(1)}


def extraer_telefono(texto: str) -> Optional[str]:
    """Si el usuario incluyó un teléfono en el mensaje, devuélvelo."""
    m = re.search(r"(\+?\d{6,15})", texto or "")
    return m.group(1) if m else None
