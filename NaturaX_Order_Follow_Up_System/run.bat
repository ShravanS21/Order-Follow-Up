@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    py -m venv .venv
    if errorlevel 1 goto :error
)

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

".venv\Scripts\python.exe" manage.py migrate
if errorlevel 1 goto :error

".venv\Scripts\python.exe" manage.py runserver
goto :eof

:error
echo.
echo Setup failed. Check the message above, then try again.
pause
exit /b 1
