@echo off
chcp 65001 >nul
rem AI:直接使用项目Python，启动不依赖系统PowerShell的文本编码。
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo 项目运行环境不存在，请先按软件使用说明完成安装。
  pause
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -m mcutool.cli start --data-dir "%~dp0.mcutool" %*
if errorlevel 1 pause
