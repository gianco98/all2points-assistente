@echo off
rem Installa l'Assistente All2Points su Windows. Serve una volta sola: poi si apre dall'icona e si aggiorna da solo.
chcp 65001 >nul
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
echo Installo l'Assistente All2Points...
where uv >nul 2>nul
if errorlevel 1 (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
)
uv run --script https://raw.githubusercontent.com/gianco98/all2points-assistente/main/avvia.py --installa
echo.
echo Fatto. D'ora in poi apri l'app dall'icona Assistente All2Points sulla Scrivania o nel menu Start.
pause
