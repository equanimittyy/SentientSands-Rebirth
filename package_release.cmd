@echo off
python "%~dp0scripts\package_release.py" --confirm %*
if errorlevel 1 (
    echo.
    echo Packaging failed.
)
echo.
choice /c X /n /m "Press X to close."
