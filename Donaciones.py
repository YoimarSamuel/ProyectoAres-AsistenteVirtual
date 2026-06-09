"""
================================================================================
        ARES v2.0 — Módulo de Donaciones (multi-divisa)
================================================================================
Soporta dos pasarelas:
  - Stripe   → Stripe Checkout Sessions (multi-país, multi-divisa)
  - PayPal   → enlace directo paypal.me (fallback sin API key)

Ambas son configurables vía variables de entorno:
  STRIPE_API_KEY        → sk_live_... o sk_test_...
  STRIPE_SUCCESS_URL    → URL post-éxito (opcional)
  STRIPE_CANCEL_URL     → URL post-cancelación (opcional)
  PAYPAL_ME_HANDLE      → "tuusuario" (sin @)
================================================================================
"""

from __future__ import annotations
import os
import urllib.parse
from typing import Dict, Any, List
from icecream import ic

try:
    import stripe
    STRIPE_OK = True
except Exception:
    STRIPE_OK = False


# Divisas soportadas (Stripe acepta muchísimas más; éstas son las más comunes)
DIVISAS_SOPORTADAS: List[str] = [
    "usd", "eur", "gbp", "mxn", "cop", "ars", "clp", "pen", "brl",
    "cad", "aud", "jpy", "cny", "inr", "vef", "uyu", "bob", "pyg"
]

# Montos mínimos por divisa (Stripe requiere mínimos)
MONTO_MIN = {"usd": 0.50, "eur": 0.50, "mxn": 10, "cop": 2000, "ars": 50}


def _stripe_listo() -> bool:
    return STRIPE_OK and bool(os.getenv("STRIPE_API_KEY"))


def crear_donacion_stripe(monto: float, divisa: str = "usd",
                           username: str = "anon") -> Dict[str, Any]:
    """
    Crea una sesión de Checkout en Stripe.
    Devuelve {'ok', 'url', 'id'} o {'ok': False, 'error'}.
    """
    if not _stripe_listo():
        return {"ok": False,
                "error": "Stripe no configurado (falta STRIPE_API_KEY)"}

    divisa = divisa.lower()
    if divisa not in DIVISAS_SOPORTADAS:
        return {"ok": False, "error": f"Divisa no soportada: {divisa}"}

    if monto < MONTO_MIN.get(divisa, 0.50):
        return {"ok": False,
                "error": f"Monto mínimo para {divisa.upper()} es {MONTO_MIN.get(divisa, 0.5)}"}

    stripe.api_key = os.getenv("STRIPE_API_KEY")
    success_url = os.getenv("STRIPE_SUCCESS_URL",
                            "http://127.0.0.1:5000/?donacion=ok")
    cancel_url  = os.getenv("STRIPE_CANCEL_URL",
                            "http://127.0.0.1:5000/?donacion=cancelada")

    try:
        # Stripe maneja montos en la unidad mínima (centavos)
        amount_cents = int(round(monto * 100))

        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": divisa,
                    "product_data": {
                        "name": "Donación voluntaria a ARES",
                        "description": (
                            "Gracias por apoyar el desarrollo de ARES. "
                            "ARES es 100% gratuito."
                        ),
                    },
                    "unit_amount": amount_cents,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"username": username, "tipo": "donacion"}
        )
        ic(f" Stripe checkout creado por {username}: {monto} {divisa}")
        return {
            "ok": True,
            "url": session.url,
            "id":  session.id,
            "pasarela": "stripe"
        }
    except Exception as e:
        ic(f" Stripe error: {e}")
        return {"ok": False, "error": str(e)}


def crear_donacion_paypal(monto: float, divisa: str = "USD",
                           username: str = "anon") -> Dict[str, Any]:
    """Genera un enlace paypal.me (no requiere API key)."""
    handle = os.getenv("PAYPAL_ME_HANDLE", "").strip().lstrip("@")
    if not handle:
        return {"ok": False,
                "error": "PayPal no configurado (falta PAYPAL_ME_HANDLE)"}

    monto_str = f"{monto:.2f}".rstrip("0").rstrip(".")
    url = f"https://paypal.me/{urllib.parse.quote(handle)}/{monto_str}{divisa.upper()}"

    ic(f" PayPal link generado por {username}: {url}")
    return {"ok": True, "url": url, "pasarela": "paypal"}


def crear_donacion(monto: float, divisa: str = "usd",
                    username: str = "anon",
                    pasarela: str = "auto") -> Dict[str, Any]:
    """
    Punto de entrada. Si pasarela='auto', usa Stripe si está configurado;
    de lo contrario, intenta PayPal.
    """
    pasarela = (pasarela or "auto").lower()

    if pasarela == "stripe" or (pasarela == "auto" and _stripe_listo()):
        res = crear_donacion_stripe(monto, divisa, username)
        if res.get("ok"):
            return res
        # fallback automático a paypal
        if pasarela == "auto":
            return crear_donacion_paypal(monto, divisa, username)
        return res

    return crear_donacion_paypal(monto, divisa, username)


def estado_pasarelas() -> Dict[str, Any]:
    return {
        "stripe": {
            "disponible": _stripe_listo(),
            "modo": "configurado" if _stripe_listo() else "no_configurado"
        },
        "paypal": {
            "disponible": bool(os.getenv("PAYPAL_ME_HANDLE")),
            "handle": os.getenv("PAYPAL_ME_HANDLE", "")
        },
        "divisas": DIVISAS_SOPORTADAS
    }
