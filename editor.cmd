@echo off
rem The level editor for the imported Banana Mania stages (mania\editor.py): opens a page in the browser.
cd /d "%~dp0"
if not exist "build\venv\Scripts\python.exe" (
    echo Run setup.cmd first.
    pause
    exit /b 1
)
"build\venv\Scripts\python.exe" "mania\editor.py" %*
if errorlevel 1 pause
