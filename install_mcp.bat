@echo off
cd /d "%~dp0"
where python >nul 2>nul && (python "%~dp0install_mcp.py" %* & exit /b)
where py >nul 2>nul && (py -3 "%~dp0install_mcp.py" %* & exit /b)
echo Python 3 is required: https://www.python.org/downloads/
pause
