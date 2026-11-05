@echo off
chcp 65001 >nul
title spaceLimbo
cd /d "%~dp0"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if exist "%VENV_PY%" goto run

echo.
echo  Primeira vez: preparando o spaceLimbo. Isso so acontece uma vez.
echo.
call :find_python
if defined PY goto make_venv

echo  Python nao encontrado. Instalando o Python automaticamente...
where winget >nul 2>nul
if errorlevel 1 goto no_winget
winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
call :find_python
if not defined PY goto no_python

:make_venv
echo  Criando a pasta de trabalho do bot...
%PY% -m venv .venv
if errorlevel 1 goto fail

:run
"%VENV_PY%" launcher.py %*
if errorlevel 1 goto fail
exit /b 0

:find_python
set "PY="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY exit /b 0
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY exit /b 0
for %%V in (314 313 312 311 310) do if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
exit /b 0

:no_winget
:no_python
echo.
echo  Nao consegui instalar o Python sozinho.
echo  1. Baixe em https://www.python.org/downloads/
echo  2. Na instalacao, MARQUE a opcao "Add python.exe to PATH".
echo  3. Depois abra este INICIAR de novo.
start "" https://www.python.org/downloads/
pause
exit /b 1

:fail
echo.
echo  O spaceLimbo parou. Leia a mensagem acima para saber o motivo.
pause
exit /b 1
