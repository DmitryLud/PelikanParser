@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
  echo Сначала запустите setup.bat.
  exit /b 1
)
if not exist config.yaml (
  echo Нет config.yaml. Скопируйте config.example.yaml в config.yaml.
  exit /b 1
)
if not exist .env (
  echo Нет .env. Скопируйте .env.example в .env и заполните логин и пароль.
  exit /b 1
)

.venv\Scripts\python.exe -m pelikan_parser run --config config.yaml --env .env
