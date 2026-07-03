@echo off
title Universal Downloader Launcher
cd /d "%~dp0"

echo ==================================================
echo         Starting Universal Downloader...
echo ==================================================
echo.

:: 0. Check custom Python path from config.jsonc
set CUSTOM_PY=
if exist "%~dp0config.jsonc" (
    for /f "tokens=2 delims=:" %%i in ('findstr /i "\"python_path\"" "%~dp0config.jsonc"') do (
        set val=%%i
        goto PARSE_PY
    )
)
goto DETECT_PY

:PARSE_PY
set val=%val: =%
set val=%val:"=%
set val=%val:,=%
if "%val%"=="" goto DETECT_PY

for /f "tokens=1 delims=/" %%a in ("%val%") do set val=%%a
set val=%val: =%
if "%val%"=="" goto DETECT_PY

if exist "%val%" (
    echo [INFO] Using custom Python path from config.jsonc: %val%
    set PYTHON_EXE="%val%"
    goto RUN
) else (
    echo [WARN] Custom Python path not found: %val%
    echo [WARN] Falling back to auto-detection...
)

:DETECT_PY
:: 1. Check local virtual environment (venv)
if exist "%~dp0venv\Scripts\python.exe" (
    echo [INFO] Using local virtual environment venv...
    set PYTHON_EXE="%~dp0venv\Scripts\python.exe"
    goto RUN
)

:: 2. Check local portable python directory (python_env)
if exist "%~dp0python_env\python.exe" (
    echo [INFO] Using portable python environment python_env...
    set PYTHON_EXE="%~dp0python_env\python.exe"
    goto RUN
)

:: 3. Check local portable python directory (python)
if exist "%~dp0python\python.exe" (
    echo [INFO] Using portable python environment python...
    set PYTHON_EXE="%~dp0python\python.exe"
    goto RUN
)

:: 4. Fallback to system Python
where python >nul 2>nul
if %errorlevel% equ 0 (
    echo [INFO] Using system Python...
    set PYTHON_EXE=python
    goto RUN
)

echo ==================================================
echo [ERROR] Python not found!
echo Please install Python, create a 'venv' folder, or 
echo place a portable 'python_env' folder in this directory.
echo ==================================================
pause
exit /b

:RUN
%PYTHON_EXE% main.py

if %errorlevel% neq 0 (
    echo.
    echo ==================================================
    echo [ERROR] The application crashed or exited with error code: %errorlevel%
    echo Please see the error messages above for details.
    echo ==================================================
    pause
)
