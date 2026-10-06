@echo off
rem Inicia Neji POS en Windows. La primera vez prepara Python y las dependencias.
cd /d "%~dp0"
if not exist ".venv\instalado.txt" (
  echo Preparando Neji POS por primera vez, espera un momento...
  if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv 2>nul || python -m venv .venv
  )
  if not exist ".venv\Scripts\python.exe" (
    echo.
    echo No se encontro Python. Instalalo desde https://www.python.org/downloads/
    echo y marca la opcion "Add Python to PATH". Luego vuelve a abrir este archivo.
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || (pause & exit /b 1)
  echo ok> ".venv\instalado.txt"
)
".venv\Scripts\python.exe" run.py %*
pause
