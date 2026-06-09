# Sistema de Reconocimiento Facial - ARES v3.0

## Descripción General

Este sistema añade capacidades de reconocimiento facial y análisis de expresiones en tiempo real a ARES, permitiendo:

- **Detección automática de rostros** cuando la cámara está activa
- **Reconocimiento de usuarios conocidos** previamente registrados
- **Análisis de expresiones faciales**: feliz, enojado, triste, molesto, normal
- **Registro automático de nuevos usuarios** con captura de foto
- **Saludos personalizados** basados en el usuario detectado
- **Respuestas adaptativas** según la expresión facial del usuario

## Instalación

### 1. Instalar dependencias

Ejecuta el script de instalación:

```bash
instalar_dependencias_faciales.bat
```

Este script instalará:
- `face_recognition`: Para reconocimiento de rostros
- `deepface`: Para análisis de expresiones faciales
- `tensorflow`: Dependencia de DeepFace
- `opencv-python`: Para procesamiento de imágenes

### 2. Requisitos previos

- Windows 10/11
- Python 3.8+
- CMake (para compilar dlib)
- Visual Studio C++ Build Tools (para face_recognition)

## Funcionalidades

### 1. Detección de Rostros

La cámara se activa automáticamente al iniciar ARES (tanto en modo CLI como Web UI). El sistema detecta rostros en tiempo real y muestra información en el stream de video.

### 2. Reconocimiento de Usuarios

**Primer encuentro:**
- Cuando ARES detecta un rostro que no conoce, dice: "Un gusto, ¿quién eres?"
- El usuario puede responder de varias formas:
  - "Me llamo Juan"
  - "Soy María"
  - "Mi nombre es Pedro"
  - Simplemente "Juan" (si ARES está esperando un nombre)
- ARES toma una foto del rostro y la guarda en `rostros_aprendidos/`
- El usuario queda registrado en el sistema

**Encuentros posteriores:**
- ARES reconoce automáticamente al usuario
- Saluda por nombre: "¡Hola Juan! Veo que estás de buen ánimo."
- La expresión facial se analiza en tiempo real

### 3. Análisis de Expresiones

El sistema detecta 5 expresiones faciales:

- **Feliz**: "¡Hola Juan! Veo que estás de buen ánimo."
- **Enojado**: "Hola Juan. Noto que algo te molesta, ¿en qué puedo ayudarte?"
- **Triste**: "Hola Juan. Noto que estás triste, ¿quieres conversar?"
- **Molesto**: "Hola Juan. Parece que algo te incomoda."
- **Normal**: "Hola Juan, ¿en qué te puedo ayudar hoy?"

### 4. Respuestas Adaptativas

Todas las respuestas de ARES se adaptan según la expresión facial:

- **Si el usuario está feliz**: "¡Me alegra verte así! [respuesta]"
- **Si el usuario está enojado**: "Entiendo tu frustración. [respuesta]"
- **Si el usuario está triste**: "Lamento que te sientas así. [respuesta]"
- **Si el usuario está molesto**: "Comprendo tu molestia. [respuesta]"
- **Si el usuario está normal**: [respuesta normal]

## Uso

### Modo CLI

1. Ejecuta `python iniciar_ares.py`
2. Selecciona opción 1 para conversación interactiva
3. La cámara se iniciará automáticamente
4. Di "hola" para probar el saludo con reconocimiento facial

### Modo Web UI

1. Ejecuta `python iniciar_ares.py`
2. Selecciona opción 3 para lanzar la UI Web
3. Inicia sesión
4. La cámara se iniciará automáticamente
5. El stream de video está disponible en `/api/camara/stream`

## Base de Datos de Rostros

Los rostros se almacenan en:
- **Directorio**: `rostros_aprendidos/`
- **Archivo JSON**: `rostros_aprendidos/usuarios_db.json`
- **Fotos**: `rostros_aprendidos/{nombre}_{timestamp}.jpg`

### Estructura del JSON:

```json
{
  "Juan": {
    "nombre": "Juan",
    "foto_path": "rostros_aprendidos/Juan_20240606_103045.jpg",
    "encoding": [0.1, 0.2, ...],
    "fecha_registro": "2024-06-06T10:30:45",
    "ultima_deteccion": "2024-06-06T14:22:10"
  }
}
```

## Múltiples Usuarios

El sistema soporta múltiples usuarios:

- Cada usuario tiene su propio registro con foto
- ARES saluda al usuario que detecta en ese momento
- Si varios usuarios se turnan, ARES reconocerá a cada uno individualmente
- Si no reconoce el rostro, asume que es el usuario de la cuenta actual

## Comandos de Voz

- "hola" - Saludo con reconocimiento facial
- "me llamo [nombre]" - Registrar nuevo usuario
- "soy [nombre]" - Registrar nuevo usuario
- "mi nombre es [nombre]" - Registrar nuevo usuario

## Solución de Problemas

### La cámara no se inicia

1. Verifica que no hay otra aplicación usando la cámara
2. Revisa los permisos de cámara en Windows
3. Asegúrate de que OpenCV está instalado: `pip install opencv-python`

### Error instalando face_recognition

1. Instala CMake: https://cmake.org/download/
2. Instala Visual Studio C++ Build Tools
3. Reinstala: `pip uninstall face_recognition` luego `pip install face_recognition`

### DeepFace no funciona

1. Asegúrate de tener TensorFlow instalado
2. El sistema tiene un fallback a análisis básico con OpenCV si DeepFace falla

### No reconoce rostros conocidos

1. Verifica que la iluminación sea adecuada
2. Asegúrate de que el rostro esté bien visible en la cámara
3. El usuario debe estar frente a la cámara, no de perfil

## Archivos Modificados/Creados

### Nuevos archivos:
- `ReconocimientoFacial.py` - Módulo principal de reconocimiento facial
- `instalar_dependencias_faciales.bat` - Script de instalación
- `RECONOCIMIENTO_FACIAL_README.md` - Este documento

### Archivos modificados:
- `CamaraStream.py` - Integración con reconocimiento facial
- `Ares.py` - Saludos y respuestas adaptativas
- `iniciar_ares.py` - Inicio automático de cámara

## Notas Técnicas

- El reconocimiento facial usa `face_recognition` (basado en dlib)
- El análisis de expresiones usa `DeepFace` con fallback a OpenCV
- La base de datos es local y privada (en `rostros_aprendidos/`)
- Los encodings faciales son vectores de 128 dimensiones
- El sistema funciona sin conexión a internet (una vez entrenados los modelos)

## Privacidad

- Las fotos de los rostros se almacenan localmente
- No se envían datos a servidores externos
- El usuario puede eliminar su registro borrando los archivos en `rostros_aprendidos/`
- Los datos están cifrados si se usa la base de datos privada de ARES

## Futuras Mejoras

- Reconocimiento de múltiples rostros simultáneos
- Detección de edad y género
- Análisis de atención/fatiga
- Integración con gestos manuales
- Mejor tolerancia a cambios de apariencia (barba, gafas, etc.)
