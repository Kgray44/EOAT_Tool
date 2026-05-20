from __future__ import annotations

from pathlib import Path

from core.constants import TOOLKIT_ROOT


def launcher_text() -> str:
    toolkit = str(TOOLKIT_ROOT)
    return f"""@echo off
setlocal
set "TOOLKIT_ROOT={toolkit}"
set "PREFERRED_PYTHON=%TOOLKIT_ROOT%\\.venv\\Scripts\\python.exe"

if exist "%TOOLKIT_ROOT%\\run_dashboard.py" goto find_python
echo EOAT Command Center toolkit was not found:
echo %TOOLKIT_ROOT%
pause
exit /b 1

:find_python
if exist "%PREFERRED_PYTHON%" (
  set "PYTHON_EXE=%PREFERRED_PYTHON%"
  goto run_app
)

where py.exe >nul 2>nul
if %ERRORLEVEL%==0 (
  set "PYTHON_EXE=py -3"
  goto run_app
)

where python.exe >nul 2>nul
if %ERRORLEVEL%==0 (
  for /f "delims=" %%P in ('where python.exe') do (
    echo %%P | findstr /i "WindowsApps" >nul
    if errorlevel 1 (
      set "PYTHON_EXE=%%P"
      goto run_app
    )
  )
)

echo No usable Python interpreter was found.
echo The Windows Store Python alias is not enough to launch this app.
echo Install Python or edit this launcher with a python.exe path.
pause
exit /b 1

:run_app
pushd "%USERPROFILE%" >nul
%PYTHON_EXE% "%TOOLKIT_ROOT%\\run_dashboard.py"
set "EXITCODE=%ERRORLEVEL%"
popd >nul
if not "%EXITCODE%"=="0" (
  echo.
  echo EOAT Command Center exited with code %EXITCODE%.
  pause
)
exit /b %EXITCODE%
"""


def main() -> int:
    desktop = Path.home() / "Desktop"
    target = desktop / "EOAT Command Center.cmd"
    target.write_text(launcher_text(), encoding="utf-8")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
