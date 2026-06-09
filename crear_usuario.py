#!/usr/bin/env python3
"""
ARES — Utilidad para crear una cuenta de usuario local desde la terminal.

Las bases de datos (usuarios + conocimiento) se inicializan automáticamente
al importar Auth. Este script solo registra una cuenta nueva, aceptando la
Política de Privacidad y Términos de Control Total de forma explícita.

Uso:
    python crear_usuario.py
"""

import sys
import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from Auth import auth, POLITICA_PRIVACIDAD  # noqa: E402


def main() -> int:
    print("=" * 64)
    print("ARES — Crear cuenta local")
    print("=" * 64)

    # Listar cuentas existentes
    if auth.usuarios:
        print("\nCuentas ya registradas:")
        for u in auth.usuarios:
            print(f"  • {u}")

    print("\nNueva cuenta:")
    username = input("  Usuario: ").strip().lower()
    if not username:
        print(" El usuario no puede estar vacío.")
        return 1

    if auth.usuario_existe(username):
        print(f" El usuario '{username}' ya existe.")
        return 1

    nombre_real = input("  Nombre real (opcional): ").strip()

    password = getpass.getpass("  Contraseña: ")
    password2 = getpass.getpass("  Repite la contraseña: ")
    if password != password2:
        print(" Las contraseñas no coinciden.")
        return 1
    if len(password) < 6:
        print(" La contraseña debe tener al menos 6 caracteres.")
        return 1

    tono = (input("  Tono [balanceado/tranquilo/analitico/directo] "
                  "(enter=balanceado): ").strip().lower() or "balanceado")

    # Consentimiento explícito
    print("\n" + "-" * 64)
    print(POLITICA_PRIVACIDAD)
    print("-" * 64)
    acepta = input("\n¿Aceptas la política? (escribe 'si' para aceptar): ") \
        .strip().lower() in {"si", "sí", "s", "yes", "y"}

    res = auth.registrar(
        username=username,
        password=password,
        nombre_real=nombre_real,
        acepta_politica=acepta,
        tono=tono,
    )

    if res.get("ok"):
        print(f"\n {res['mensaje']}")
        print(f"  Ya puedes iniciar sesión como '{username}'.")
        return 0

    print(f"\n {res.get('mensaje')}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
