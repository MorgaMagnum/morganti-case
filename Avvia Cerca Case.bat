@echo off
rem Doppio clic per avviare Morganti Cerca Case (si apre il browser da solo).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0avvia.ps1" %*
if errorlevel 1 pause