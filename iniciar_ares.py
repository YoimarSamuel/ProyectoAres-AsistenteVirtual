#!/usr/bin/env python3
"""
ARES — Script de Inicio Rápido
Menú interactivo: conversación CLI, estado del sistema y lanzamiento de la UI.
"""

import sys
from pathlib import Path
from icecream import ic

# Forzar UTF-8 en consola (evita que logs con acentos/IPA/emojis fallen en Windows)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Agregar ruta actual al path
sys.path.insert(0, str(Path(__file__).parent))


def main():
    """Punto de entrada del menú interactivo."""
    ic(" ARES — Asistente Autónomo Inteligente")

    # Verificar dependencias núcleo
    ic("Verificando dependencias...")
    try:
        import chromadb            # noqa: F401
        import sentence_transformers  # noqa: F401
        ic(" Dependencias núcleo disponibles\n")
    except ImportError as e:
        ic(f" Falta dependencia: {e}")
        ic("Instalar con: pip install -r requirements.txt")
        return False

    # Importar ARES
    ic("Cargando módulos ARES...")
    try:
        from Ares import ares
        ic(" ARES cargado\n")
    except ImportError as e:
        ic(f" Error cargando ARES: {e}")
        return False

    # Iniciar cámara para reconocimiento facial
    ic("Iniciando cámara para reconocimiento facial...")
    try:
        from CamaraStream import camara
        camara.iniciar()
        ic(" Cámara iniciada\n")
    except Exception as e:
        ic(f" Advertencia: No se pudo iniciar la cámara: {e}")
        ic(" El reconocimiento facial no estará disponible\n")

    # Menú
    ic("Opciones:")
    ic("  1. Iniciar conversación interactiva (CLI)")
    ic("  2. Ver estado del sistema")
    ic("  3.  Lanzar UI Web (Neo-Glass)")
    ic("  4. Salir\n")

    while True:
        try:
            opcion = input("Selecciona opción (1-4): ").strip()

            if opcion == "1":
                _conversacion_interactiva(ares)
            elif opcion == "2":
                _mostrar_estado(ares)
            elif opcion == "3":
                _lanzar_ui_web()
            elif opcion == "4":
                ic(" Hasta luego!")
                break
            else:
                ic(" Opción no válida")

        except KeyboardInterrupt:
            ic("\n Sesión interrumpida")
            break
        except Exception as e:
            ic(f"Error: {e}")


def _conversacion_interactiva(ares):
    """Conversación interactiva por consola."""
    ic("\n" + "=" * 70)
    ic("ARES — Modo Conversación Interactiva")
    ic("Escribe 'salir' para terminar, 'estado' para ver el sistema")
    ic("=" * 70 + "\n")

    while True:
        try:
            entrada = input(" Tú: ").strip()

            if not entrada:
                continue
            if entrada.lower() == "salir":
                break
            if entrada.lower() == "estado":
                _mostrar_estado(ares)
                continue

            res = ares.procesar(entrada, hablar_respuesta=False)
            ic(f" ARES: {res.get('respuesta', '')}\n")

        except KeyboardInterrupt:
            ic("\n Conversación terminada")
            break
        except Exception as e:
            ic(f"Error: {e}")


def _mostrar_estado(ares):
    """Muestra el estado completo del sistema."""
    ic("\n" + "=" * 70)
    ic("ESTADO DEL SISTEMA ARES")
    ic("=" * 70)

    estado = ares.estado_completo()
    sistema = estado.get("sistema", {})
    uptime = estado.get("uptime", {})
    base_global = estado.get("base_global", {})

    ic(f"\n Usuario: {(estado.get('usuario') or {}).get('nombre_real', 'sin sesión')}")
    ic(f"  Uptime: {uptime.get('formateado', 'N/A')} "
       f"({uptime.get('comandos_ejecutados', 0)} comandos)")

    if "cpu" in sistema:
        ic(f"\n Sistema")
        ic(f"  CPU: {sistema['cpu'].get('percent', 0):.1f}%")
        ic(f"  RAM: {sistema['ram'].get('percent', 0):.1f}%")
        ic(f"  Disco: {sistema['disco'].get('percent', 0):.1f}%")

    ic(f"\n Conocimiento global: "
       f"{base_global.get('total_conceptos', 0)} conceptos, "
       f"{base_global.get('total_rechazados', 0)} rechazados")
    ic(f" Historial de sesión: {estado.get('historial_sesion', 0)} interacciones")
    ic("\n" + "=" * 70 + "\n")


def _lanzar_ui_web():
    """Lanza el servidor web con la UI Neo-Glass."""
    ic("\n" + "=" * 70)
    ic(" LANZANDO UI WEB ARES (Neo-Glass / Cyber-Dark)")
    ic("=" * 70 + "\n")

    try:
        from ServidorAPI import iniciar_servidor
    except Exception as e:
        ic(f" Error importando servidor: {e}")
        return

    host, port = "127.0.0.1", 5000
    ic(f" Servidor corriendo en: http://{host}:{port}/")
    ic("Presiona Ctrl+C para detener\n")

    try:
        iniciar_servidor(host=host, port=port, debug=False)
    except KeyboardInterrupt:
        ic("\n Servidor detenido\n")


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        ic("\n\n Programa interrumpido")
        sys.exit(0)
    except Exception as e:
        ic(f"\n Error fatal: {e}")
        sys.exit(1)
