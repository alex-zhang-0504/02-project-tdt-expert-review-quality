@echo off
setlocal
cd /d "%~dp0"

if not exist "pyproject.toml" goto :incomplete
if not exist "src\tdt_scoring\api.py" goto :incomplete

if not exist ".venv\Scripts\python.exe" goto :find_python

".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
if errorlevel 1 goto :invalid_venv
goto :dependencies

:find_python
set "PYTHON_COMMAND="

where py >nul 2>nul
if errorlevel 1 goto :try_python
py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
if errorlevel 1 goto :try_python
set "PYTHON_COMMAND=py -3"
goto :create_venv

:try_python
where python >nul 2>nul
if errorlevel 1 goto :try_python3
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
if errorlevel 1 goto :try_python3
set "PYTHON_COMMAND=python"
goto :create_venv

:try_python3
where python3 >nul 2>nul
if errorlevel 1 goto :python_missing
python3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
if errorlevel 1 goto :python_missing
set "PYTHON_COMMAND=python3"

:create_venv
echo [SETUP] Using compatible Python runtime:
%PYTHON_COMMAND% --version
echo [SETUP] Creating local Python environment...
%PYTHON_COMMAND% -m venv .venv
if errorlevel 1 goto :failed

:dependencies
".venv\Scripts\python.exe" -c "import fastapi, openpyxl, uvicorn" >nul 2>nul
if errorlevel 1 (
  echo [SETUP] Installing project dependencies...
  ".venv\Scripts\python.exe" -m pip install -e .
  if errorlevel 1 goto :failed
)

set "LAUNCH_ACTION="
set "APP_PORT="
set "APP_BUILD_ID="
for /f "tokens=1,2,3" %%A in ('.venv\Scripts\python.exe -m tdt_scoring.launcher') do (
  set "LAUNCH_ACTION=%%A"
  set "APP_PORT=%%B"
  set "APP_BUILD_ID=%%C"
)
if not defined LAUNCH_ACTION goto :failed
if not defined APP_PORT goto :failed
if not defined APP_BUILD_ID goto :failed
if "%LAUNCH_ACTION%"=="reuse" goto :reuse_current
if not "%LAUNCH_ACTION%"=="launch" goto :failed
goto :launch

:reuse_current
echo [RUNNING] The latest local build is already running on port %APP_PORT%.
start "" "http://127.0.0.1:%APP_PORT%/?build=%APP_BUILD_ID%"
exit /b 0

:launch
if not exist "output" mkdir "output"
set "SERVICE_LOG=output\local-service-%APP_PORT%-%APP_BUILD_ID%-%RANDOM%.log"
".venv\Scripts\python.exe" -c "from pathlib import Path; Path(r'%SERVICE_LOG%').write_text('==== Starting build %APP_BUILD_ID% on port %APP_PORT% ====\n', encoding='utf-8')"
if errorlevel 1 goto :log_failed
echo [RUNNING] Starting the current build on http://127.0.0.1:%APP_PORT%/
echo [RUNNING] Service log: %CD%\%SERVICE_LOG%
start "" /b powershell.exe -NoProfile -WindowStyle Hidden -Command "$url='http://127.0.0.1:%APP_PORT%/?build=%APP_BUILD_ID%'; $healthUrl='http://127.0.0.1:%APP_PORT%/api/health'; for ($attempt=0; $attempt -lt 40; $attempt++) { try { $health=Invoke-RestMethod -Uri $healthUrl -TimeoutSec 1; if ($health.project_id -eq 'tdt-expert-review-quality' -and $health.build_id -eq '%APP_BUILD_ID%') { Start-Process $url; exit 0 } } catch {}; Start-Sleep -Milliseconds 250 }; exit 1" >nul 2>nul
echo [RUNNING] Keep this window open while using the scoring system.
".venv\Scripts\python.exe" -u -m uvicorn tdt_scoring.api:app --host 127.0.0.1 --port %APP_PORT% >>"%SERVICE_LOG%" 2>&1
set "SERVER_EXIT_CODE=%ERRORLEVEL%"
echo.
if "%SERVER_EXIT_CODE%"=="0" (
  echo [STOPPED] Local scoring service stopped.
) else (
  echo [ERROR] Local scoring service exited with code %SERVER_EXIT_CODE%.
)
echo Log: %CD%\%SERVICE_LOG%
echo Restart start.cmd and use the newly opened page.
echo Re-import the review workbook before scoring.
pause
exit /b %SERVER_EXIT_CODE%

:log_failed
echo [ERROR] Cannot create the service log: %CD%\%SERVICE_LOG%
echo Check whether the output folder is writable, then restart start.cmd.
pause
exit /b 5

:incomplete
echo [ERROR] Project files are incomplete.
echo Do not run start.cmd inside the ZIP preview window.
echo Right-click the ZIP file, choose "Extract All", then run start.cmd in the extracted folder.
echo Current folder: %CD%
pause
exit /b 2

:python_missing
echo [ERROR] Python 3.12 or newer was not found.
echo Install a current 64-bit Python release, then run start.cmd again.
echo Python 3.12, 3.13 and 3.14 are supported by this launcher.
pause
exit /b 3

:invalid_venv
echo [ERROR] The existing .venv cannot run Python 3.12 or newer.
echo It may have been copied from another computer or created with an older Python.
echo Remove or rename the .venv folder, then run start.cmd again.
pause
exit /b 4

:failed
echo [ERROR] Setup failed. Check the message above.
pause
exit /b 1
