@echo off
rem Lets "sal start" work from cmd or a double-click without changing PowerShell's execution policy.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sal.ps1" %*
