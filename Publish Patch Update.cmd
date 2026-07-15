@echo off
setlocal
pushd "%~dp0" || (
  echo FAILED: Could not enter the EOAT Atlas project folder.
  pause
  exit /b 1
)
set "PYTHON_EXE=%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"
"%PYTHON_EXE%" scripts\publish_release.py %*
set "RESULT=%ERRORLEVEL%"
if "%RESULT%"=="0" (
  echo.
  echo ===== EOAT ATLAS RELEASE SUCCEEDED =====
) else (
  echo.
  echo ===== EOAT ATLAS RELEASE FAILED - NOTHING NEW WAS ACTIVATED =====
)
popd
if /i not "%EOAT_ATLAS_NO_PAUSE%"=="1" pause
exit /b %RESULT%
