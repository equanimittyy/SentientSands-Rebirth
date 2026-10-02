@echo off
python "%~dp0scripts\package_release.py" --confirm %*
if errorlevel 1 (
    echo.
    echo Packaging failed.
)
echo.
echo Press any key to close.
pause >nul
