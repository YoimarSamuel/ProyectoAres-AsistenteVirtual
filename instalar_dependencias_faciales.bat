@echo off
REM Instalación de dependencias para reconocimiento facial y análisis de expresiones
REM para ARES v3.0

echo ========================================
echo Instalando dependencias de reconocimiento facial...
echo ========================================
echo.

REM Instalar face_recognition (requiere dlib y cmake)
echo Instalando face_recognition...
pip install face_recognition
if %errorlevel% neq 0 (
    echo ERROR: No se pudo instalar face_recognition
    echo Este paquete requiere CMake y Visual Studio C++ build tools
    echo Visita: https://github.com/zhaoweicai/face_recognition
    pause
    exit /b 1
)

REM Instalar DeepFace para análisis de expresiones
echo Instalando DeepFace...
pip install deepface
if %errorlevel% neq 0 (
    echo ERROR: No se pudo instalar DeepFace
    pause
    exit /b 1
)

REM Instalar dependencias adicionales para DeepFace
echo Instalando dependencias adicionales...
pip install tensorflow
pip install opencv-python
pip install tf-keras

echo.
echo ========================================
echo Instalación completada exitosamente!
echo ========================================
echo.
echo Las siguientes características ahora están disponibles:
echo - Detección de rostros
echo - Reconocimiento de usuarios conocidos
echo - Análisis de expresiones faciales (feliz, enojado, triste, molesto, normal)
echo - Registro automático de nuevos usuarios
echo - Saludos personalizados basados en el usuario detectado
echo - Respuestas adaptativas según la expresión facial
echo.
pause
