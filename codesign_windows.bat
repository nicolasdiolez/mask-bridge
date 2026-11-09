@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
if /I "%~1"=="--verify-only" (
    "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -File "%~dp0tools\release\sign_windows.ps1" -VerifyOnly
) else (
    "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -File "%~dp0tools\release\sign_windows.ps1"
)
exit /b %errorlevel%
