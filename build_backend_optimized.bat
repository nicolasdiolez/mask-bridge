@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
if not defined MASKBRIDGE_PYTHON set "MASKBRIDGE_PYTHON=%~dp0.venv-release\Scripts\python.exe"
"%MASKBRIDGE_PYTHON%" tools\release\release.py build
exit /b %errorlevel%
