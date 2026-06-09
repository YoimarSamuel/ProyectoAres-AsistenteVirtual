"""Limpia entradas corruptas (bot-block) de la BD global."""
from BaseDeConocimiento import base_global

CORRUPTAS = [
    "trouble accessing google",
    "send feedback",
    "tener problemas para acceder"
]

# Recuperar todos
all_data = base_global.conceptos.get()
borrar_ids = []
for id_, meta in zip(all_data["ids"], all_data["metadatas"]):
    desc = (meta.get("descripcion") or "").lower()
    if any(c in desc for c in CORRUPTAS):
        borrar_ids.append(id_)
        print(f"   {id_}: {desc[:80]}")

if borrar_ids:
    base_global.conceptos.delete(ids=borrar_ids)
    print(f"\n Borrados {len(borrar_ids)} conceptos corruptos.")
else:
    print(" No hay conceptos corruptos.")

print(f" BD limpia: {base_global.estadisticas()}")
