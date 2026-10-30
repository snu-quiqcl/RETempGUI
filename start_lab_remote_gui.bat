@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title RETempUI V1.00

rem =============================================
rem Settings: update only when server IP or env changes
rem =============================================
set "CONDA_ENV=uniqcon"
set "CONDA_BAT=C:\Anaconda\condabin\conda.bat"
set "SERVER_IP="
set "SERVER_PORT="
set "IS_ROOT="
if exist "%~dp0local_settings.bat" call "%~dp0local_settings.bat"

if not exist "%CONDA_BAT%" (
    echo [ERROR] Conda activation script is missing:
    echo         "%CONDA_BAT%"
    echo Edit CONDA_BAT in local_settings.bat to match your Conda installation.
    pause
    exit /b 1
)
call "%CONDA_BAT%" activate "%CONDA_ENV%"
if errorlevel 1 (
    echo [ERROR] Unable to activate Conda environment "%CONDA_ENV%".
    pause
    exit /b 1
)

if not exist "%~dp0lab_remote_gui.py" (
    echo [ERROR] lab_remote_gui.py not found next to this batch file.
    pause
    exit /b 1
)

rem Find sibling instrumentserver source checkout automatically.
rem Handles either QCODES\Lab_Remote_Client or QCODES\subfolder\Lab_Remote_Client.
if not defined IS_ROOT for %%D in ("%~dp0.." "%~dp0..\.." "%~dp0..\..\.." "%~dp0..\..\..\..") do (
    if exist "%%~fD\instrumentserver-remote_entanglement\instrumentserver-remote_entanglement\instrumentserver\__init__.py" (
        set "IS_ROOT=%%~fD\instrumentserver-remote_entanglement\instrumentserver-remote_entanglement"
    )
)
if not defined IS_ROOT (
    for %%D in ("%~dp0.." "%~dp0..\.." "%~dp0..\..\.." "%~dp0..\..\..\..") do (
        if exist "%%~fD\instrumentserver-remote_entanglement\instrumentserver\__init__.py" (
            set "IS_ROOT=%%~fD\instrumentserver-remote_entanglement"
        )
    )
)
if defined IS_ROOT (
    set "PYTHONPATH=%IS_ROOT%;%PYTHONPATH%"
) else (
    echo [INFO] No nearby instrumentserver source checkout detected.
    echo        Will attempt importing instrumentserver from Conda environment.
)

set "SERVER_ARGS="
if defined SERVER_IP set SERVER_ARGS=--host "%SERVER_IP%"
if defined SERVER_PORT set SERVER_ARGS=%SERVER_ARGS% --port %SERVER_PORT%
python "%~dp0lab_remote_gui.py" %SERVER_ARGS%
if errorlevel 1 pause
