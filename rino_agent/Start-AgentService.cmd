@echo off
pushd "%~dp0.."
py -3.13 -m uvicorn rino_agent.main:app --host 127.0.0.1 --port 8766
