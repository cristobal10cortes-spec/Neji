@echo off
rem Generador de licencias de Neji POS (solo para quien vende Neji POS). Necesita Python con cryptography.
chcp 65001 >nul
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%~dp0licencias.py" %*
) else (
  python "%~dp0licencias.py" %*
)
echo.
pause
