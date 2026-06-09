@echo off
echo ========================================
echo Instalando dependencias del proyecto Ares
echo ========================================
echo.

REM Dependencias básicas
echo [1/2] Instalando dependencias básicas...
pip install -U pyserial pyttsx3 SpeechRecognition pytz psutil numpy requests beautifulsoup4 opencv-python wikipedia deep-translator TTS sounddevice num2words

echo.
echo [2/2] Instalando dependencias especializadas (esto puede tomar varios minutos)...
pip install -U face-recognition ultralytics mediapipe yt-dlp

echo.
echo ========================================
echo  Instalación completada
echo ========================================
pause
