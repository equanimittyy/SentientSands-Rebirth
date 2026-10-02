@echo off
setlocal
echo Select one:
echo 1. Rebuild and repackage
echo 2. Rebuild only
echo 3. Repackage
echo 4. Exit
choice /c 1234 /n
set "OPTION=%errorlevel%"
if %OPTION%==4 exit /b
if %OPTION%==3 goto package

set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
for /f "usebackq delims=" %%i in (`"%VSWHERE%" -latest -requires Microsoft.Component.MSBuild -find MSBuild\**\Bin\MSBuild.exe`) do set "MSBUILD=%%i"
if not defined MSBUILD (
    echo MSBuild not found. See docs\info\plugin_build_setup.md, section 2.
    goto end
)
"%MSBUILD%" "%~dp0plugin\SentientSands.vcxproj" -nologo -verbosity:minimal
if errorlevel 1 (
    echo.
    echo Build failed.
    goto end
)
if %OPTION%==2 goto end

:package
python "%~dp0scripts\package_release.py" --confirm %*
if errorlevel 1 (
    echo.
    echo Packaging failed.
)
:end
echo.
echo Press any key to close.
pause >nul
