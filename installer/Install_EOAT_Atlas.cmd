@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PS_SCRIPT=%SCRIPT_DIR%Install_EOAT_Atlas.ps1"

if not exist "%PS_SCRIPT%" (
  echo EOAT Atlas installer script was not found:
  echo   %PS_SCRIPT%
  exit /b 2
)

powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File "%PS_SCRIPT%" %*
set "INSTALL_RC=%ERRORLEVEL%"

if "%~1"=="" (
  echo.
  echo EOAT Atlas installer finished with exit code %INSTALL_RC%.
  pause
)

exit /b %INSTALL_RC%
