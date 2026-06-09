"""
================================================================================
        ARES v3.0 — Sistema de Reconocimiento Facial y Análisis de Expresiones
================================================================================
Funcionalidades:
  - Detección de rostros en tiempo real
  - Reconocimiento de usuarios conocidos
  - Análisis de expresiones faciales (feliz, enojado, triste, molesto, normal)
  - Registro de nuevos usuarios con fotos
  - Saludos personalizados basados en el usuario detectado
  - Respuestas adaptativas según la expresión facial
================================================================================
"""

from __future__ import annotations
import cv2
import numpy as np
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Tuple, Any
from icecream import ic
import threading
import time

try:
    import face_recognition
    FACE_REC_OK = True
except ImportError:
    FACE_REC_OK = False
    ic("face_recognition no disponible, usando OpenCV Haar Cascade")

try:
    from deepface import DeepFace
    DEEPFACE_OK = True
except ImportError:
    DEEPFACE_OK = False
    ic("DeepFace no disponible, usando análisis básico de expresiones")


class ReconocimientoFacial:
    """Sistema completo de reconocimiento facial y análisis de expresiones."""
    
    def __init__(self, db_path: str = "rostros_aprendidos"):
        self.db_path = Path(db_path)
        self.db_path.mkdir(exist_ok=True)
        
        # Base de datos de rostros
        self.usuarios_db: Dict[str, Dict[str, Any]] = {}
        self.encodings_known: List[np.ndarray] = []
        self.names_known: List[str] = []
        
        # Estado actual
        self.usuario_actual: Optional[str] = None
        self.expresion_actual: str = "normal"
        self.confianza_reconocimiento: float = 0.0
        self.ultima_deteccion: Optional[datetime] = None
        self.nuevo_usuario_detectado: bool = False
        self.esperando_nombre: bool = False
        self.rostro_para_guardar: Optional[np.ndarray] = None
        
        # Lock para thread safety
        self._lock = threading.Lock()
        
        # Modelos de detección
        self.face_cascade = None
        self._cargar_modelos()
        
        # Cargar base de datos existente
        self._cargar_base_datos()
        
        ic("ReconocimientoFacial inicializado")
    
    def _cargar_modelos(self):
        """Carga los modelos de detección facial."""
        try:
            # Haar Cascade para detección de rostros
            cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            self.face_cascade = cv2.CascadeClassifier(cascade_path)
            if self.face_cascade.empty():
                ic("Error cargando Haar Cascade")
            else:
                ic("Haar Cascade cargado correctamente")
        except Exception as e:
            ic(f"Error cargando modelos: {e}")
    
    def _cargar_base_datos(self):
        """Carga la base de datos de usuarios conocidos."""
        db_file = self.db_path / "usuarios_db.json"
        if db_file.exists():
            try:
                with open(db_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.usuarios_db = data
                    
                    # Cargar encodings si face_recognition está disponible
                    if FACE_REC_OK:
                        for nombre, info in self.usuarios_db.items():
                            if 'encoding' in info and info['encoding']:
                                encoding = np.array(info['encoding'])
                                self.encodings_known.append(encoding)
                                self.names_known.append(nombre)
                    
                    ic(f"Base de datos cargada: {len(self.usuarios_db)} usuarios")
            except Exception as e:
                ic(f"Error cargando base de datos: {e}")
    
    def _guardar_base_datos(self):
        """Guarda la base de datos de usuarios."""
        db_file = self.db_path / "usuarios_db.json"
        try:
            with open(db_file, 'w', encoding='utf-8') as f:
                json.dump(self.usuarios_db, f, ensure_ascii=False, indent=2)
            ic("Base de datos guardada")
        except Exception as e:
            ic(f"Error guardando base de datos: {e}")
    
    def detectar_rostros(self, frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """Detecta rostros en el frame usando Haar Cascade."""
        if self.face_cascade is None:
            return []
        
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        rostros = self.face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(30, 30)
        )
        return rostros
    
    def reconocer_usuario(self, frame: np.ndarray, bbox: Tuple[int, int, int, int]) -> Optional[str]:
        """Reconoce un usuario a partir de un rostro detectado."""
        if not FACE_REC_OK or not self.encodings_known:
            return None
        
        x, y, w, h = bbox
        rostro = frame[y:y+h, x:x+w]
        
        try:
            # Convertir a RGB (face_recognition usa RGB)
            rostro_rgb = cv2.cvtColor(rostro, cv2.COLOR_BGR2RGB)
            
            # Obtener encoding
            encoding = face_recognition.face_encodings(rostro_rgb, num_jitters=1)
            if not encoding:
                return None
            
            encoding = encoding[0]
            
            # Comparar con encodings conocidos
            matches = face_recognition.compare_faces(self.encodings_known, encoding, tolerance=0.6)
            if True in matches:
                best_match_index = matches.index(True)
                return self.names_known[best_match_index]
            
            return None
        except Exception as e:
            ic(f"Error en reconocimiento: {e}")
            return None
    
    def analizar_expresion(self, frame: np.ndarray, bbox: Tuple[int, int, int, int]) -> str:
        """Analiza la expresión facial del rostro detectado."""
        x, y, w, h = bbox
        rostro = frame[y:y+h, x:x+w]
        
        if DEEPFACE_OK:
            try:
                # Usar DeepFace para análisis de emociones
                resultado = DeepFace.analyze(
                    rostro,
                    actions=['emotion'],
                    enforce_detection=False,
                    verbose=False
                )
                
                if resultado and isinstance(resultado, list):
                    resultado = resultado[0]
                
                emociones = resultado.get('dominant_emotion', 'neutral')
                
                # Mapear emociones de DeepFace a nuestras categorías
                mapeo = {
                    'happy': 'feliz',
                    'sad': 'triste',
                    'angry': 'enojado',
                    'disgust': 'molesto',
                    'fear': 'molesto',
                    'surprise': 'normal',
                    'neutral': 'normal'
                }
                
                return mapeo.get(emociones, 'normal')
            except Exception as e:
                ic(f"Error DeepFace: {e}")
        
        # Análisis básico usando OpenCV si DeepFace no está disponible
        return self._analisis_expresion_basico(rostro)
    
    def _analisis_expresion_basico(self, rostro: np.ndarray) -> str:
        """Análisis básico de expresiones usando características geométricas."""
        try:
            gray = cv2.cvtColor(rostro, cv2.COLOR_BGR2GRAY)
            
            # Detectar boca
            mouth_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_smile.xml')
            smiles = mouth_cascade.detectMultiScale(gray, scaleFactor=1.7, minNeighbors=22, minSize=(25, 25))
            
            if len(smiles) > 0:
                return 'feliz'
            
            # Análisis de brillo y contraste para detectar otras emociones
            brightness = np.mean(gray)
            
            if brightness < 80:
                return 'triste'
            elif brightness > 180:
                return 'enojado'
            
            return 'normal'
        except Exception as e:
            ic(f"Error análisis básico: {e}")
            return 'normal'
    
    def registrar_nuevo_usuario(self, nombre: str, frame: np.ndarray, bbox: Tuple[int, int, int, int]) -> bool:
        """Registra un nuevo usuario con su foto."""
        try:
            x, y, w, h = bbox
            rostro = frame[y:y+h, x:x+w]
            
            # Guardar foto
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            foto_path = self.db_path / f"{nombre}_{timestamp}.jpg"
            cv2.imwrite(str(foto_path), rostro)
            
            # Obtener encoding si está disponible
            encoding = None
            if FACE_REC_OK:
                try:
                    rostro_rgb = cv2.cvtColor(rostro, cv2.COLOR_BGR2RGB)
                    encodings = face_recognition.face_encodings(rostro_rgb, num_jitters=1)
                    if encodings:
                        encoding = encodings[0].tolist()
                        self.encodings_known.append(encodings[0])
                        self.names_known.append(nombre)
                except Exception as e:
                    ic(f"Error obteniendo encoding: {e}")
            
            # Guardar en base de datos
            self.usuarios_db[nombre] = {
                'nombre': nombre,
                'foto_path': str(foto_path),
                'encoding': encoding,
                'fecha_registro': datetime.now().isoformat(),
                'ultima_deteccion': None
            }
            
            self._guardar_base_datos()
            ic(f"Usuario {nombre} registrado correctamente")
            return True
            
        except Exception as e:
            ic(f"Error registrando usuario: {e}")
            return False
    
    def actualizar_ultima_deteccion(self, nombre: str):
        """Actualiza la última vez que se detectó a un usuario."""
        if nombre in self.usuarios_db:
            self.usuarios_db[nombre]['ultima_deteccion'] = datetime.now().isoformat()
            self._guardar_base_datos()
    
    def procesar_frame(self, frame: np.ndarray) -> Dict[str, Any]:
        """Procesa un frame completo y devuelve información del rostro detectado."""
        with self._lock:
            resultado = {
                'rostro_detectado': False,
                'usuario': None,
                'expresion': 'normal',
                'confianza': 0.0,
                'bbox': None,
                'es_nuevo': False,
                'mensaje': None
            }
            
            # Detectar rostros
            rostros = self.detectar_rostros(frame)
            
            if len(rostros) > 0:
                # Tomar el rostro más grande (asumimos que es el principal)
                rostros_ordenados = sorted(rostros, key=lambda x: x[2]*x[3], reverse=True)
                bbox = rostros_ordenados[0]
                x, y, w, h = bbox
                
                resultado['rostro_detectado'] = True
                resultado['bbox'] = bbox
                
                # Reconocer usuario
                usuario = self.reconocer_usuario(frame, bbox)
                
                if usuario:
                    resultado['usuario'] = usuario
                    resultado['confianza'] = 0.8  # Valor simulado
                    self.usuario_actual = usuario
                    self.actualizar_ultima_deteccion(usuario)
                else:
                    # Usuario no reconocido
                    resultado['usuario'] = None
                    resultado['es_nuevo'] = True
                    self.nuevo_usuario_detectado = True
                    self.rostro_para_guardar = frame.copy()
                
                # Analizar expresión
                expresion = self.analizar_expresion(frame, bbox)
                resultado['expresion'] = expresion
                self.expresion_actual = expresion
                
                self.ultima_deteccion = datetime.now()
            
            return resultado
    
    def obtener_usuario_actual(self) -> Optional[str]:
        """Devuelve el usuario actualmente detectado."""
        with self._lock:
            return self.usuario_actual
    
    def obtener_expresion_actual(self) -> str:
        """Devuelve la expresión facial actual."""
        with self._lock:
            return self.expresion_actual
    
    def confirmar_registro(self, nombre: str) -> bool:
        """Confirma el registro de un nuevo usuario."""
        if self.rostro_para_guardar is not None and self.nuevo_usuario_detectado:
            # Necesitamos el bbox del rostro, usamos detección nuevamente
            rostros = self.detectar_rostros(self.rostro_para_guardar)
            if len(rostros) > 0:
                bbox = sorted(rostros, key=lambda x: x[2]*x[3], reverse=True)[0]
                exito = self.registrar_nuevo_usuario(nombre, self.rostro_para_guardar, bbox)
                if exito:
                    self.nuevo_usuario_detectado = False
                    self.rostro_para_guardar = None
                    return True
        return False
    
    def cancelar_registro(self):
        """Cancela el registro de un nuevo usuario."""
        with self._lock:
            self.nuevo_usuario_detectado = False
            self.rostro_para_guardar = None
            self.esperando_nombre = False
    
    def obtener_saludo_personalizado(self) -> str:
        """Genera un saludo personalizado basado en el usuario y expresión."""
        usuario = self.obtener_usuario_actual()
        expresion = self.obtener_expresion_actual()
        
        if usuario:
            # Saludos según expresión
            saludos_expresion = {
                'feliz': f"¡Hola {usuario}! Veo que estás de buen ánimo.",
                'enojado': f"Hola {usuario}. Noto que algo te molesta, ¿en qué puedo ayudarte?",
                'triste': f"Hola {usuario}. Noto que estás triste, ¿quieres conversar?",
                'molesto': f"Hola {usuario}. Parece que algo te incomoda.",
                'normal': f"Hola {usuario}, ¿en qué te puedo ayudar hoy?"
            }
            return saludos_expresion.get(expresion, f"Hola {usuario}")
        else:
            return "Un gusto, ¿quién eres?"
    
    def obtener_respuesta_adaptativa(self, respuesta_base: str) -> str:
        """Adapta una respuesta base según la expresión facial del usuario."""
        expresion = self.obtener_expresion_actual()
        usuario = self.obtener_usuario_actual()
        
        # Prefijos según expresión
        prefijos = {
            'feliz': "¡Me alegra verte así! ",
            'enojado': "Entiendo tu frustración. ",
            'triste': "Lamento que te sientas así. ",
            'molesto': "Comprendo tu molestia. ",
            'normal': ""
        }
        
        prefijo = prefijos.get(expresion, "")
        
        if usuario:
            return f"{prefijo}{respuesta_base}"
        else:
            return respuesta_base


# Instancia global
reconocimiento_facial = ReconocimientoFacial()
