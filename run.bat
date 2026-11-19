@echo off
setlocal
cd /d "%~dp0"

set "PYW=C:\Python314\pythonw.exe"
if not exist "%PYW%" for %%P in (pythonw.exe) do set "PYW=%%~$PATH:P"

if not exist "%PYW%" (
  echo [ERROR] Python 3.9+ with tkinter is required.
  pause
  exit /b 1
)

set "NODE=%~dp0runtime\node.exe"
if not exist "%NODE%" for %%P in (node.exe) do set "NODE=%%~$PATH:P"
if not exist "%NODE%" if exist "C:\Program Files\nodejs\node.exe" set "NODE=C:\Program Files\nodejs\node.exe"

if not exist "%NODE%" (
  echo [ERROR] Node.js 18+ is required.
  pause
  exit /b 1
)

set "APP_NODE=%NODE%"
start "" "%PYW%" "app\main.py"
