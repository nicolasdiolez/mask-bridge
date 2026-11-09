@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
if not defined MASKBRIDGE_PYTHON set "MASKBRIDGE_PYTHON=%~dp0.venv-release\Scripts\python.exe"
if "%~1"=="--candidate" (
    "%MASKBRIDGE_PYTHON%" tools\release\release.py package --candidate
) else (
    "%MASKBRIDGE_PYTHON%" tools\release\release.py package
)
exit /b %errorlevel%
