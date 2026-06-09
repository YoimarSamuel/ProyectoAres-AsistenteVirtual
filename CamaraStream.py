"""
================================================================================
        ARES v2.0 — Cámara Always-On (single capture + multicasting)
================================================================================
Una única instancia que:
  - Captura frames de la webcam continuamente en un hilo.
  - Analiza con YOLO cada N frames y guarda snapshots en memoria global.
  - Expone el último JPEG para streaming MJPEG a la UI.
================================================================================
"""

from __future__ import annotations
import threading
import time
import asyncio
from typing import Optional, List, Dict, Any
from icecream import ic

import cv2
import numpy as np

try:
    from ultralytics import YOLO
    YOLO_OK = True
except Exception:
    YOLO_OK = False

try:
    from ReconocimientoFacial import reconocimiento_facial
    FACE_REC_OK = True
except Exception:
    FACE_REC_OK = False
    reconocimiento_facial = None


class CamaraStream:
    """Cámara siempre encendida, productora central de frames."""

    def __init__(self, camera_index: int = 0,
                 ancho: int = 640, alto: int = 480,
                 intervalo_yolo_seg: float = 5.0):
        self.camera_index = camera_index
        self.ancho = ancho
        self.alto = alto
        self.intervalo_yolo_seg = intervalo_yolo_seg

        self._cap: Optional[cv2.VideoCapture] = None
        self._frame: Optional[np.ndarray] = None
        self._jpeg: Optional[bytes] = None
        self._lock = threading.Lock()

        self._activa = False
        self._hilo: Optional[threading.Thread] = None

        # YOLO (lazy)
        self._modelo: Optional[YOLO] = None

        # Estado de análisis
        self.objetos_actuales: List[Dict[str, Any]] = []
        self.descripcion_entorno: str = ""
        self.frames_procesados = 0
        self.ultimo_yolo_ts = 0.0

        # Estado de reconocimiento facial
        self.rostro_detectado = False
        self.usuario_detectado: Optional[str] = None
        self.expresion_detectada: str = "normal"
        self.ultimo_face_rec_ts = 0.0
        self.intervalo_face_rec_seg = 0.5  # Análisis facial más frecuente que YOLO

        ic(" CamaraStream construida (no iniciada todavía)")

    def _cargar_yolo(self):
        if self._modelo is None and YOLO_OK:
            try:
                ic("Cargando YOLOv8n…")
                self._modelo = YOLO("yolov8n.pt")
                ic(" YOLOv8n listo")
            except Exception as e:
                ic(f" Error cargando YOLO: {e}")

    # -------------------- LIFECYCLE --------------------
    def iniciar(self) -> bool:
        if self._activa:
            return True

        self._cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        if not self._cap.isOpened():
            # Fallback sin DSHOW
            self._cap = cv2.VideoCapture(self.camera_index)

        if not self._cap.isOpened():
            ic(f" No pude abrir cámara índice {self.camera_index}")
            self._cap = None
            return False

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.ancho)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.alto)
        self._cap.set(cv2.CAP_PROP_FPS, 24)

        self._cargar_yolo()

        self._activa = True
        self._hilo = threading.Thread(target=self._loop, daemon=True)
        self._hilo.start()
        ic(" Cámara always-on iniciada")
        return True

    def detener(self) -> None:
        ic(" Deteniendo cámara…")
        self._activa = False
        if self._hilo:
            self._hilo.join(timeout=2)
        if self._cap:
            self._cap.release()
            self._cap = None

    # -------------------- LOOP --------------------
    def _loop(self) -> None:
        while self._activa and self._cap is not None:
            ok, frame = self._cap.read()
            if not ok:
                time.sleep(0.05)
                continue

            self.frames_procesados += 1

            # Reflejar (espejo, más natural en webcam)
            frame = cv2.flip(frame, 1)

            # YOLO periódico
            ahora = time.time()
            if (self._modelo is not None
                    and ahora - self.ultimo_yolo_ts >= self.intervalo_yolo_seg):
                self._analizar_yolo(frame)
                self.ultimo_yolo_ts = ahora

            # Reconocimiento facial (más frecuente que YOLO)
            if FACE_REC_OK and reconocimiento_facial is not None:
                if ahora - self.ultimo_face_rec_ts >= self.intervalo_face_rec_seg:
                    self._analizar_rostro(frame)
                    self.ultimo_face_rec_ts = ahora

            # Dibujar overlays de objetos actuales (para feedback visual)
            self._dibujar_overlays(frame)
            
            # Dibujar overlays de reconocimiento facial
            if FACE_REC_OK:
                self._dibujar_overlays_rostro(frame)

            # Codificar JPEG
            ok2, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ok2:
                with self._lock:
                    self._frame = frame
                    self._jpeg = buf.tobytes()

            time.sleep(0.03)

    def _analizar_yolo(self, frame: np.ndarray) -> None:
        try:
            res = self._modelo.predict(frame, imgsz=320, conf=0.45, verbose=False)
            objetos = []
            for r in res:
                for box in r.boxes:
                    try:
                        cls = int(box.cls[0])
                        nombre = self._modelo.names.get(cls, str(cls))
                        conf = float(box.conf[0])
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        objetos.append({
                            "nombre": nombre,
                            "confianza": conf,
                            "bbox": (x1, y1, x2, y2)
                        })
                    except Exception:
                        pass
            self.objetos_actuales = objetos

            # Descripción
            if objetos:
                contador: Dict[str, int] = {}
                for o in objetos:
                    contador[o["nombre"]] = contador.get(o["nombre"], 0) + 1
                partes = [
                    f"{n} {k}" if n > 1 else f"un {k}"
                    for k, n in contador.items()
                ]
                self.descripcion_entorno = "Detecté: " + ", ".join(partes)
            else:
                self.descripcion_entorno = "Sin objetos visibles"

            # Guardar snapshot del entorno en BD privada del usuario activo
            try:
                from Auth import auth
                from BaseDeConocimiento import base_privada
                if auth.autenticado and objetos:
                    base_privada.guardar_interaccion(
                        entrada=f"[entorno-snapshot]",
                        respuesta=self.descripcion_entorno,
                        metadatos={
                            "tipo": "entorno",
                            "objetos": ",".join(o["nombre"] for o in objetos)
                        }
                    )
            except Exception as e:
                ic(f" snapshot privado: {e}")

        except Exception as e:
            ic(f" YOLO predict error: {e}")

    def _dibujar_overlays(self, frame: np.ndarray) -> None:
        """Dibuja bboxes con estética cyber (azul/rojo)."""
        for obj in self.objetos_actuales:
            x1, y1, x2, y2 = obj["bbox"]
            cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 136, 0), 2)
            label = f"{obj['nombre']} {obj['confianza']:.0%}"
            cv2.putText(frame, label, (x1, max(20, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        (255, 255, 255), 2, cv2.LINE_AA)

    def _analizar_rostro(self, frame: np.ndarray) -> None:
        """Analiza rostros usando el sistema de reconocimiento facial."""
        if reconocimiento_facial is None:
            return
        
        try:
            resultado = reconocimiento_facial.procesar_frame(frame)
            self.rostro_detectado = resultado['rostro_detectado']
            self.usuario_detectado = resultado['usuario']
            self.expresion_detectada = resultado['expresion']
        except Exception as e:
            ic(f"Error en análisis de rostro: {e}")

    def _dibujar_overlays_rostro(self, frame: np.ndarray) -> None:
        """Dibuja overlays de reconocimiento facial."""
        if not self.rostro_detectado:
            return
        
        # Dibujar indicador de rostro detectado
        color = (0, 255, 0)  # Verde para rostro detectado
        
        # Dibujar rectángulo alrededor del rostro (simulado, ya que el bbox viene del reconocimiento)
        # En una implementación completa, usaríamos el bbox real del reconocimiento
        h, w = frame.shape[:2]
        cv2.rectangle(frame, (w//2 - 150, h//2 - 200), (w//2 + 150, h//2 + 200), color, 2)
        
        # Mostrar información del usuario
        if self.usuario_detectado:
            label = f"{self.usuario_detectado} - {self.expresion_detectada}"
            cv2.putText(frame, label, (w//2 - 100, h//2 - 220),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)
        else:
            label = f"Desconocido - {self.expresion_detectada}"
            cv2.putText(frame, label, (w//2 - 100, h//2 - 220),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2, cv2.LINE_AA)

    # -------------------- API PÚBLICA --------------------
    def obtener_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._jpeg

    def estado(self) -> Dict[str, Any]:
        estado = {
            "activa": self._activa,
            "frames_procesados": self.frames_procesados,
            "objetos_actuales": [
                {"nombre": o["nombre"], "confianza": o["confianza"]}
                for o in self.objetos_actuales[:10]
            ],
            "descripcion_entorno": self.descripcion_entorno,
            "ultimo_yolo_ts": self.ultimo_yolo_ts
        }
        
        # Agregar información de reconocimiento facial
        if FACE_REC_OK:
            estado.update({
                "rostro_detectado": self.rostro_detectado,
                "usuario_detectado": self.usuario_detectado,
                "expresion_detectada": self.expresion_detectada,
                "ultimo_face_rec_ts": self.ultimo_face_rec_ts
            })
        
        return estado


# ============================== INSTANCIA ==============================
camara = CamaraStream()
