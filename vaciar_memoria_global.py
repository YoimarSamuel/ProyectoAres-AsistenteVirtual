#!/usr/bin/env python3
"""
ARES — Vaciar la base de conocimiento GLOBAL.

Borra todos los conceptos aprendidos y los rechazos. NO toca:
  • Las cuentas de usuario (data/usuarios.json).
  • Las bases privadas cifradas de cada usuario.

Pide confirmación antes de proceder. Pásale --yes para saltar la confirmación.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def main(force: bool = False) -> int:
    from BaseDeConocimiento import base_global

    stats = base_global.estadisticas()
    total = stats.get("total_conceptos", 0)
    rech  = stats.get("total_rechazados", 0)

    print("=" * 60)
    print("ARES — Vaciar base de conocimiento GLOBAL")
    print("=" * 60)
    print(f"  Conceptos aprendidos: {total}")
    print(f"  Rechazos auditados : {rech}")
    print()

    if total == 0 and rech == 0:
        print("La base global ya está vacía. Nada que borrar.")
        return 0

    if not force:
        respuesta = input("¿Borrar todo el conocimiento global? "
                          "(escribe 'si' para confirmar): ").strip().lower()
        if respuesta not in {"si", "sí", "s", "yes", "y"}:
            print("Cancelado. No se borró nada.")
            return 1

    # Borrado lógico: eliminar todos los IDs de cada colección
    borrados_total = 0
    for nombre, col in (("conceptos", base_global.conceptos),
                        ("rechazados", base_global.rechazados)):
        try:
            data = col.get()
            ids = data.get("ids", []) or []
            if ids:
                col.delete(ids=ids)
                borrados_total += len(ids)
                print(f"   {len(ids):4d} entradas borradas de '{nombre}'")
            else:
                print(f"  · '{nombre}' ya estaba vacía")
        except Exception as e:
            print(f"   Error vaciando '{nombre}': {e}")

    # Verificar
    stats_final = base_global.estadisticas()
    print()
    print(f"Resultado final → conceptos: {stats_final['total_conceptos']}, "
          f"rechazados: {stats_final['total_rechazados']}")
    print(f"Total entradas borradas: {borrados_total}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    force = "--yes" in sys.argv or "-y" in sys.argv
    raise SystemExit(main(force=force))
