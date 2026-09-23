"""Controle dos processos gerenciados pelo PM2 (API, worker, gateway).

ATENÇÃO — SEGURANÇA: este módulo EXECUTA COMANDOS NO SISTEMA OPERACIONAL (pm2). Hoje isso é aceitável porque a aplicação é de uso local,
de um único operador, e só escuta em 127.0.0.1, sem autenticação. Se este sistema um dia for exposto além do localhost, os endpoints de
/sistema PRECISAM de proteção própria (autenticação forte + autorização) antes de qualquer outra coisa.
Mitigação atual: os nomes de processo vêm de uma lista fixa (PROCESSOS); nada digitado pelo usuário vai para a linha de comando.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
ECOSSISTEMA = RAIZ / "ecosystem.config.cjs"
LOGS = RAIZ / "logs"

# nome no PM2 -> prefixo dos arquivos de log (definido no ecosystem.config.cjs)
PROCESSOS: dict[str, dict[str, str]] = {
    "sales-api": {"rotulo": "API (interface e endpoints)", "log": "api"},
    "sales-worker": {"rotulo": "Worker (IA e tarefas do WhatsApp)", "log": "worker"},
    "sales-gateway": {"rotulo": "Gateway (conexão com o WhatsApp)", "log": "gateway"},
}
API = "sales-api"
TIMEOUT_PM2 = 30
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class Pm2Indisponivel(Exception):
    pass


def localizar_pm2() -> str | None:
    """PM2_BIN (se definido) > PATH > pasta global do npm no Windows."""
    candidatos = [os.environ.get("PM2_BIN"), shutil.which("pm2"), shutil.which("pm2.cmd")]
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidatos.append(str(Path(appdata) / "npm" / "pm2.cmd"))
    return next((c for c in candidatos if c and Path(c).exists()), None)


def executar_pm2(args: list[str], timeout: int = TIMEOUT_PM2) -> subprocess.CompletedProcess:
    """Único ponto que chama o pm2. Os testes trocam esta função por uma falsa."""
    pm2 = localizar_pm2()
    if pm2 is None:
        raise Pm2Indisponivel("PM2 não encontrado. Instale com `npm install -g pm2` (veja docs/pm2.md) ou defina PM2_BIN.")
    return subprocess.run([pm2, *args], cwd=str(RAIZ), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def _json_do_jlist(texto: str) -> list[dict[str, Any]]:
    """O PM2 pode imprimir linhas como "[PM2] Spawning daemon" antes/depois do JSON: tenta cada "[" até achar uma LISTA JSON válida."""
    decoder = json.JSONDecoder()
    pos = texto.find("[")
    while pos != -1:
        try:
            obj, _ = decoder.raw_decode(texto, pos)
            if isinstance(obj, list):
                return obj
        except ValueError:
            pass
        pos = texto.find("[", pos + 1)
    return []


_ESTADOS = {"online": "rodando", "stopped": "parado", "stopping": "parando", "errored": "erro", "launching": "iniciando",
            "waiting restart": "iniciando", "one-launch-status": "rodando"}


def listar_processos(agora_ms: float | None = None) -> list[dict[str, Any]]:
    """Status dos 3 processos (sempre devolve os 3, mesmo os que o PM2 não conhece)."""
    r = executar_pm2(["jlist"])
    if r.returncode != 0:
        raise Pm2Indisponivel((r.stderr or r.stdout or "pm2 jlist falhou").strip()[:300])
    por_nome = {p.get("name"): p for p in _json_do_jlist(r.stdout)}
    agora_ms = agora_ms if agora_ms is not None else time.time() * 1000
    saida = []
    for nome, meta in PROCESSOS.items():
        p = por_nome.get(nome)
        item: dict[str, Any] = {"nome": nome, "rotulo": meta["rotulo"], "registrado": p is not None, "estado": "nao_iniciado", "status_pm2": None,
                                "pid": None, "uptime_seg": None, "reinicios": None, "memoria_mb": None, "cpu_pct": None}
        if p:
            env = p.get("pm2_env", {})
            status = env.get("status")
            item.update(estado=_ESTADOS.get(status, status or "desconhecido"), status_pm2=status, pid=p.get("pid") or None,
                        reinicios=env.get("restart_time"), memoria_mb=round((p.get("monit", {}).get("memory") or 0) / 1_048_576, 1),
                        cpu_pct=p.get("monit", {}).get("cpu"))
            if status == "online" and env.get("pm_uptime"):
                item["uptime_seg"] = max(0, int((agora_ms - env["pm_uptime"]) / 1000))
        saida.append(item)
    return saida


def _resultado(r: subprocess.CompletedProcess) -> dict[str, Any]:
    texto = _ANSI.sub("", (r.stdout or "") + (r.stderr or "")).strip()
    return {"ok": r.returncode == 0, "saida": texto[-600:]}


def iniciar(nome: str) -> dict[str, Any]:
    """Sobe (ou volta a subir) um processo a partir do ecosystem.config.cjs, esteja ele registrado ou não."""
    return _resultado(executar_pm2(["start", str(ECOSSISTEMA), "--only", nome]))


def parar(nome: str) -> dict[str, Any]:
    return _resultado(executar_pm2(["stop", nome]))


def reiniciar(nome: str) -> dict[str, Any]:
    r = executar_pm2(["restart", nome])
    if r.returncode != 0:  # nunca registrado (ou apagado): sobe pelo ecosystem
        return iniciar(nome)
    return _resultado(r)


def agendar_reinicio_da_api(atraso_seg: int = 2) -> None:
    """A API reiniciar A SI MESMA: a resposta HTTP sai antes; o reinício é disparado por um processo DESACOPLADO.

    O helper é criado via `Start-Process` do PowerShell, que o deixa órfão (sem parentesco com esta API). Assim, quando o PM2
    mata a árvore de processos da API, o helper não morre junto no meio do comando."""
    pm2 = localizar_pm2()
    if pm2 is None:
        raise Pm2Indisponivel("PM2 não encontrado.")
    comando = f'timeout /t {int(atraso_seg)} /nobreak >nul & "{pm2}" restart {API}'
    ps = f"Start-Process -WindowStyle Hidden -FilePath cmd.exe -ArgumentList '/c','{comando}'"
    subprocess.Popen(["powershell", "-NoProfile", "-Command", ps], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _ultimas_linhas(caminho: Path, n: int, max_bytes: int = 600_000) -> list[str]:
    if not caminho.exists():
        return []
    with open(caminho, "rb") as f:
        f.seek(0, os.SEEK_END)
        tamanho = f.tell()
        f.seek(max(0, tamanho - max_bytes))
        bruto = f.read()
    linhas = bruto.decode("utf-8", errors="replace").splitlines()
    if tamanho > max_bytes:
        linhas = linhas[1:]  # a primeira pode ter sido cortada no meio
    return [_ANSI.sub("", l) for l in linhas[-n:]]


def ler_logs(nome: str, linhas: int, logs_dir: Path | None = None) -> dict[str, Any]:
    base = (logs_dir or LOGS) / PROCESSOS[nome]["log"]
    return {
        "saida": _ultimas_linhas(Path(f"{base}.out.log"), linhas),
        "erros": _ultimas_linhas(Path(f"{base}.err.log"), linhas),
        "arquivos": {"saida": f"{base}.out.log", "erros": f"{base}.err.log"},
    }


def api_esta_sob_pm2(processos: list[dict[str, Any]]) -> bool:
    return any(p["nome"] == API and p["estado"] == "rodando" for p in processos)
