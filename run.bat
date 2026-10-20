@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul && (start "" pythonw "%~dp0tokenmon.pyw" & exit /b)
where pyw >nul 2>nul && (start "" pyw "%~dp0tokenmon.pyw" & exit /b)
echo Python 3 is required: https://www.python.org/downloads/
pause
