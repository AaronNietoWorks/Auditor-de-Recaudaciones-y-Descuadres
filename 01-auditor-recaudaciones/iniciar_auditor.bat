@echo off
setlocal EnableExtensions
REM ==========================================================================
REM  TRUSS y CYTILAND - Auditoria de Recaudaciones - lanzador para Windows
REM  Doble clic: crea el entorno virtual, instala dependencias si faltan
REM  y abre la aplicacion en el navegador.
REM ==========================================================================
cd /d "%~dp0"
title TRUSS ^& CYTILAND - Auditoria de Recaudaciones

echo.
echo  ===============================================
echo    TRUSS ^& CYTILAND - AUDITORIA DE RECAUDACIONES
echo  ===============================================
echo.

REM ---- 1. Localizar Python 3.10 o superior ---------------------------------
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo  [ERROR] No se ha encontrado Python 3.10 o superior.
    echo.
    echo  1. Descargalo de https://www.python.org/downloads/
    echo  2. Durante la instalacion marca la casilla "Add python.exe to PATH".
    echo  3. Vuelve a hacer doble clic en este archivo.
    echo.
    start "" "https://www.python.org/downloads/"
    pause
    exit /b 1
)
echo  [OK] Python encontrado: %PY%

REM ---- 2. Crear entorno virtual si no existe -------------------------------
set "VPY=%~dp0.venv\Scripts\python.exe"
if not exist "%VPY%" (
    echo  [..] Creando entorno virtual .venv ^(solo la primera vez^)...
    %PY% -m venv "%~dp0.venv"
    if errorlevel 1 (
        echo  [ERROR] No se pudo crear el entorno virtual.
        pause
        exit /b 1
    )
)

REM ---- 3. Instalar dependencias si faltan o si requirements.txt cambio -----
set "MARCA=%~dp0.venv\requirements.instalado"
set "INSTALAR=0"
if not exist "%MARCA%" set "INSTALAR=1"
if exist "%MARCA%" (
    fc /b "%~dp0requirements.txt" "%MARCA%" >nul 2>&1
    if errorlevel 1 set "INSTALAR=1"
)
"%VPY%" -c "import streamlit, pandas, plotly, openpyxl, xlsxwriter, xlrd" >nul 2>&1
if errorlevel 1 set "INSTALAR=1"

if "%INSTALAR%"=="1" (
    echo  [..] Instalando dependencias ^(puede tardar 1-3 minutos la primera vez^)...
    "%VPY%" -m pip install --upgrade pip --disable-pip-version-check -q
    "%VPY%" -m pip install -r "%~dp0requirements.txt" --disable-pip-version-check -q
    if errorlevel 1 (
        echo.
        echo  [ERROR] Fallo la instalacion de dependencias. Revisa tu conexion a Internet
        echo          o el proxy de la empresa y vuelve a intentarlo.
        pause
        exit /b 1
    )
    copy /y "%~dp0requirements.txt" "%MARCA%" >nul
)
echo  [OK] Dependencias listas

REM ---- 4. Generar datos de ejemplo si no existen ---------------------------
if not exist "%~dp0datos_ejemplo_ips.xlsx" (
    "%VPY%" "%~dp0sample_data.py"
)

REM ---- 5. Arrancar la aplicacion (puerto libre + navegador automatico) ----
echo.
echo  Deja esta ventana abierta mientras uses la aplicacion.
echo  Para cerrarla, cierra esta ventana o pulsa Ctrl+C.
echo.
"%VPY%" "%~dp0lanzador.py"
if errorlevel 1 (
    echo.
    echo  [ERROR] La aplicacion se ha detenido con un error. Revisa los mensajes de arriba.
    pause
)
endlocal
