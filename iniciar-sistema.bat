@echo off
rem Duplo clique: sobe Docker/Postgres + PM2 (API, worker, gateway) e abre http://127.0.0.1:8000
rem Pode rodar de novo a qualquer momento: nao reinicia o que ja esta rodando.
title Sales Engine - iniciando
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\iniciar-sistema.ps1" %*
if errorlevel 1 (
  echo.
  echo Algo deu errado - veja a mensagem acima. Pressione uma tecla para fechar.
  pause >nul
)
