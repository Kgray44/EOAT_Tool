@echo off
setlocal EnableDelayedExpansion
set "SCRIPT_DIR=%~dp0"
set "LOCAL_WORKDIR=%USERPROFILE%"

if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" (
  pushd "%LOCAL_WORKDIR%" >nul
  "%SCRIPT_DIR%.venv\Scripts\python.exe" "%SCRIPT_DIR%run_dashboard.py"
  set "EXITCODE=!ERRORLEVEL!"
  popd >nul
  if not "!EXITCODE!"=="0" pause
  exit /b !EXITCODE!
)

where py.exe >nul 2>nul
if %ERRORLEVEL%==0 (
  pushd "%LOCAL_WORKDIR%" >nul
  py -3 "%SCRIPT_DIR%run_dashboard.py"
  set "EXITCODE=!ERRORLEVEL!"
  popd >nul
  if not "!EXITCODE!"=="0" pause
  exit /b !EXITCODE!
)

where python.exe >nul 2>nul
if %ERRORLEVEL%==0 (
  for /f "delims=" %%P in ('where python.exe') do (
    echo %%P | findstr /i "WindowsApps" >nul
    if errorlevel 1 (
      pushd "%LOCAL_WORKDIR%" >nul
      "%%P" "%SCRIPT_DIR%run_dashboard.py"
      set "EXITCODE=!ERRORLEVEL!"
      popd >nul
      if not "!EXITCODE!"=="0" pause
      exit /b !EXITCODE!
    )
  )
)

echo No usable Python interpreter was found.
echo Install Python, disable the Windows Store Python alias, or edit this launcher with your python.exe path.
pause
exit /b 1
