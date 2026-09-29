@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher py.exe не найден. Установите Python 3.11 или новее.
  exit /b 1
)

if not exist .venv\Scripts\python.exe (
  py -3.11 -c "import sys" >nul 2>nul
  if errorlevel 1 (
    py -3 -m venv .venv
  ) else (
    py -3.11 -m venv .venv
  )
  if errorlevel 1 exit /b 1
)

.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install -e .
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m playwright install chromium
if errorlevel 1 exit /b 1

if not exist config.yaml copy /Y config.example.yaml config.yaml >nul
if not exist .env copy /Y .env.example .env >nul

echo.
echo Установка завершена. Заполните config.yaml и .env, затем запустите run.bat.
