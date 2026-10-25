```bat
@echo off
title Build Kothaify
cd /d "%~dp0"

echo =====================================
echo          BUILDING KOTHAIFY
echo =====================================
echo.

REM Check that the required files exist
if not exist "%~dp0main.py" (
    echo ERROR: main.py not found!
    pause
    exit /b 1
)

if not exist "%~dp0icon.ico" (
    echo ERROR: icon.ico not found!
    echo Put icon.ico beside main.py and build.bat.
    pause
    exit /b 1
)

echo Installing required packages...
py -m pip install -r requirements.txt
if errorlevel 1 (
    echo Package installation failed!
    pause
    exit /b 1
)

echo.
echo Removing old build files...
if exist "%~dp0build" rmdir /s /q "%~dp0build"
if exist "%~dp0dist" rmdir /s /q "%~dp0dist"
if exist "%~dp0Kothaify.spec" del /f /q "%~dp0Kothaify.spec"

echo.
echo Building Kothaify with the custom icon...
py -m PyInstaller --noconfirm --clean --onefile --windowed --name Kothaify --icon "%~dp0icon.ico" --add-data "%~dp0icon.ico;." "%~dp0main.py"

if errorlevel 1 (
    echo.
    echo BUILD FAILED!
    pause
    exit /b 1
)

echo.
echo =====================================
echo BUILD SUCCESSFUL!
echo EXE: %~dp0dist\Kothaify.exe
echo =====================================
pause
```