@rem SPDX-License-Identifier: GPL-3.0-or-later
@echo off
rem Starts the CANOPY node editor (python -m canopysynth) with the package that sits next to this file; nothing needs installing.
rem   run_editor.bat                       an empty graph
rem   run_editor.bat my_graph.json         opens a saved graph
rem   run_editor.bat --audio null          the preview plays nowhere (for a machine without sound hardware)
rem It needs 64-bit Python 3.9 or newer with tkinter (the python.org installer has both). The editor runs without a console window; set
rem CANOPY_CONSOLE=1 first to keep the console and see its messages.
setlocal
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
set "CHECK=import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 9) and sys.maxsize > 2**32 else 1)"
set "RUN="
set "RUNW="
py -3 -c "%CHECK%" >nul 2>nul
if not errorlevel 1 (
    set "RUN=py -3"
    set "RUNW=pyw -3"
) else (
    python -c "%CHECK%" >nul 2>nul
    if not errorlevel 1 (
        set "RUN=python"
        set "RUNW=pythonw"
    )
)
if not defined RUN (
    echo CANOPY needs 64-bit Python 3.9 or newer with tkinter, and none was found.
    echo Install it from https://www.python.org/downloads/ ^(leave "tcl/tk and IDLE" ticked^) and run this file again.
    pause
    exit /b 1
)
if "%CANOPY_CONSOLE%"=="1" goto console
start "" %RUNW% -m canopysynth %*
exit /b 0
:console
%RUN% -m canopysynth %*
exit /b %errorlevel%
