#!/usr/bin/env python3
"""
Descargar modelos necesarios de manera más rápida
"""

print("Descargando modelo YOLO (solo necesario una vez)...")
try:
    from ultralytics import YOLO
    print("  Cargando yolov8n.pt...")
    modelo = YOLO("yolov8n.pt")
    print(" YOLO descargado")
except Exception as e:
    print(f" Error: {e}")
    import sys
    sys.exit(1)

print("\n Todos los modelos listos")
