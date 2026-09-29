@echo off
rem Launch the MaidAI desktop widget without a console window.
cd /d "%~dp0"
start "" pyw -3.13 -m rino_launcher
