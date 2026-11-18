@echo off
chcp 936 >nul
setlocal
set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"
set "MEDNEXUS_LOCAL_ONLY=1"
echo.
echo  医枢 MedNexus - 本机模式
echo  答疑只用教材原文摘录；文献检索、云同步、外部模型调用全部关闭。
echo  界面左下角应显示：本机模式 · 数据不出本机
echo.
start "" /b cmd /c "cd /d "%REPO%\mednexus" && python server.py"
timeout /t 3 >nul
start "" http://127.0.0.1:7860/
endlocal