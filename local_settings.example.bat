@echo off
rem Copy this file to local_settings.bat and edit it on each computer.
rem local_settings.bat is ignored by Git and survives pull.
set "CONDA_ENV=uniqcon"
set "CONDA_BAT=C:\Anaconda\condabin\conda.bat"
rem Network endpoints normally come from labremote/config/local_hardware.json.
rem Optional explicit overrides:
rem set "SERVER_IP=127.0.0.1"
rem set "SERVER_PORT=5555"
rem Optional: directory CONTAINING the instrumentserver package.
rem set "IS_ROOT=D:\coding\QCODES\instrumentserver-remote_entanglement\instrumentserver-remote_entanglement"
