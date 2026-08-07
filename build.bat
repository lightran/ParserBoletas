@echo off
setlocal

rem Genera el ejecutable portable de Windows (ParserBoletas.exe) con PyInstaller.
rem Correr desde la raiz del repo, con el venv activado (o pasando la ruta
rem completa a python.exe/pip.exe abajo si preferis no activarlo).
rem
rem Modo por defecto: one-file (un solo .exe). Para one-folder (arranca mas
rem rapido, reparte varios archivos en una carpeta):
rem   set PARSERBOLETAS_ONEDIR=1
rem   build.bat

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] No se encontro "python" en el PATH. Activa el venv primero:
    echo     venv\Scripts\activate
    exit /b 1
)

echo Instalando dependencias de runtime + build...
python -m pip install -r requirements.txt -r requirements-build.txt
if errorlevel 1 exit /b 1

echo.
echo Corriendo pyinstaller (app.spec)...
python -m PyInstaller app.spec --noconfirm --clean
if errorlevel 1 exit /b 1

echo.
if defined PARSERBOLETAS_ONEDIR (
    echo Listo: dist\ParserBoletas\ParserBoletas.exe
) else (
    echo Listo: dist\ParserBoletas.exe
)

endlocal
