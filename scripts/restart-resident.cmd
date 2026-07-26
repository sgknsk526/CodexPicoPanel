@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart-resident.ps1" %*
