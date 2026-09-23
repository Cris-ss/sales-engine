"""Atalho de inicialização (Windows): confere que os arquivos existem e que o PowerShell não tem erro de sintaxe. Nada é executado."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
PS1 = RAIZ / "scripts" / "iniciar-sistema.ps1"
BAT = RAIZ / "iniciar-sistema.bat"

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="atalho de Windows")


def test_arquivos_existem_e_o_bat_chama_o_script_sem_reiniciar_nada():
    assert PS1.exists() and BAT.exists()
    bat = BAT.read_text(encoding="utf-8")
    assert "scripts\\iniciar-sistema.ps1" in bat and "ExecutionPolicy Bypass" in bat
    assert "(" not in bat.split("echo Algo deu errado", 1)[1].splitlines()[0]  # parêntese dentro do bloco `if (...)` quebra o cmd


def test_powershell_tem_bom_utf8_para_os_acentos_e_sintaxe_valida():
    assert PS1.read_bytes().startswith(b"\xef\xbb\xbf")  # PowerShell 5.1 lê UTF-8 sem BOM como ANSI
    cmd = ("$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile("
           f"'{PS1}',[ref]$null,[ref]$e); if($e){{ $e | ForEach-Object {{ $_.Message }}; exit 1 }}")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


def test_o_script_e_idempotente_por_desenho_so_sobe_o_que_nao_esta_no_ar():
    ps1 = PS1.read_text(encoding="utf-8-sig")
    assert "já estava rodando (não foi reiniciado)" in ps1 and "pm2 pid" in ps1.replace("`pm2 pid <nome>`", "pm2 pid")
    assert "restart" not in ps1.lower().replace("reinici", "")  # nunca chama `pm2 restart`
    assert "docker start $Container" in ps1 and "Docker Desktop.exe" in ps1  # sobe Docker e o container se faltarem
    assert "$NaoAbrirNavegador" in ps1 and "http://127.0.0.1:8000" in ps1
