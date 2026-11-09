@echo off
chcp 65001 >nul
title 大肥鱼 · 电脑端部署
echo.
echo  ================================
echo   大肥鱼 Fatfish  ·  电脑端部署
echo  ================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy.ps1" %*
echo.
pause
