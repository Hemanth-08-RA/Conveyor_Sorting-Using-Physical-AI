@echo off
title Conveyor Sorting Vision Dashboard
echo ======================================================================
echo 📦 Launching Conveyor Sorting Vision Dashboard on Port 7000...
echo ======================================================================

:: Open default browser immediately to the live dashboard
start "" "http://127.0.0.1:7000"

:: Start the Python Vision & Web Server
python python/main.py

pause
