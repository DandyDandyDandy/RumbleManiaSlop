@echo off
rem One-time setup: builds the PC game in game\ from your own Switch dump in input\. See README.md.
setlocal
cd /d "%~dp0"

rem ---- find Python 3.10 or newer
set "PY="
where py >nul 2>nul && for %%V in (3.13 3.12 3.11 3.10) do if not defined PY (py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V")
if not defined PY (python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=python")
if not defined PY (
    echo Python 3.10 or newer ^(64-bit^) is needed. Install it from https://www.python.org/downloads/windows/
    echo ^(tick "Add python.exe to PATH"^), then run setup.cmd again.
    pause
    exit /b 1
)

rem ---- a private environment for the Python packages the build uses
if not exist "build\venv\Scripts\python.exe" (
    echo Creating the Python environment ...
    %PY% -m venv "build\venv" || goto :fail
)
"build\venv\Scripts\python.exe" -c "import UnityPy, numpy, etcpak, texture2ddecoder, lz4, Crypto, zstandard, PIL" >nul 2>nul
if errorlevel 1 (
    echo Installing Python packages ...
    "build\venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r "setup\requirements.txt" || goto :fail
)

"build\venv\Scripts\python.exe" "setup\setup.py" %*
set "RC=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %RC%

:fail
echo.
echo Setup could not prepare Python. See the messages above.
pause
exit /b 1
