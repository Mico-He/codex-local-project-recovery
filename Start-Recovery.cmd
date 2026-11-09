@echo off
where pyw.exe >nul 2>&1
if not errorlevel 1 (
  start "" pyw.exe -3 "%~dp0project_recovery_panel.pyw"
  exit /b
)
where pythonw.exe >nul 2>&1
if not errorlevel 1 (
  start "" pythonw.exe "%~dp0project_recovery_panel.pyw"
  exit /b
)
echo Python 3 with Tkinter is required.
pause
