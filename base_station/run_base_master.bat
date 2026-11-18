@echo off
cd /d "%~dp0"
echo ==========================================================
echo Starting Base Station Master Router (Single XBee Radio Owner)
echo ==========================================================
python base_master.py %*
pause
