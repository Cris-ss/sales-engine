"""Tela "Sistema": status, reinício e logs dos processos gerenciados pelo PM2.

ATENÇÃO — SEGURANÇA: estes endpoints executam comandos no sistema operacional (pm2). Sem autenticação porque a aplicação é de uso local
de um único operador em 127.0.0.1. Se o sistema for exposto além do localhost, ESTA tela precisa de proteção extra antes de tudo.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from api.errors import ApiError
from api.services import sistema_service as sv

router = APIRouter(prefix="/sistema", tags=["sistema"])


def _nome(nome: str) -> str:
    if nome not in sv.PROCESSOS:  # lista fixa: nada digitado chega à linha de comando
        raise ApiError(404, "processo_desconhecido", f"Processo desconhecido: {nome}", {"validos": list(sv.PROCESSOS)})
    return nome


def _pm2(fn, *args):
    try:
        return fn(*args)
    except sv.Pm2Indisponivel as exc:
        raise ApiError(503, "pm2_indisponivel", str(exc)) from exc


@router.get("/processos")
def processos():
    """Nunca falha por PM2 ausente: devolve `pm2_disponivel=false` com o motivo, para a tela explicar."""
    try:
        return {"pm2_disponivel": True, "erro": None, "processos": sv.listar_processos()}
    except sv.Pm2Indisponivel as exc:
        return {"pm2_disponivel": False, "erro": str(exc), "processos": []}


@router.get("/processos/{nome}/logs")
def logs(nome: str, linhas: int = Query(default=100, ge=10, le=1000)):
    return sv.ler_logs(_nome(nome), linhas)


@router.post("/processos/{nome}/reiniciar")
def reiniciar(nome: str):
    _nome(nome)
    if nome == sv.API:
        # Caso especial: a API reinicia a si mesma. Confirma ANTES de morrer; o reinício é disparado por um helper desacoplado.
        if not sv.api_esta_sob_pm2(_pm2(sv.listar_processos)):
            raise ApiError(409, "api_fora_do_pm2", "A API não está rodando sob o PM2; reinicie-a manualmente (veja docs/pm2.md).")
        _pm2(sv.agendar_reinicio_da_api)
        return {"ok": True, "reiniciando": True, "processo": nome,
                "mensagem": "Reinício da API disparado. Ela cai por alguns segundos; a página reconecta sozinha."}
    r = _pm2(sv.reiniciar, nome)
    return {**r, "reiniciando": False, "processo": nome}


@router.post("/processos/{nome}/parar")
def parar(nome: str):
    _nome(nome)
    if nome == sv.API:  # parar a API pela própria tela deixaria você sem tela para religá-la
        raise ApiError(409, "nao_pode_parar_a_api", "A API não pode ser parada por esta tela (você perderia o acesso). Use o reinício, ou `pm2 stop sales-api` no terminal.")
    return {**_pm2(sv.parar, nome), "processo": nome}


@router.post("/processos/{nome}/iniciar")
def iniciar(nome: str):
    return {**_pm2(sv.iniciar, _nome(nome)), "processo": nome}


@router.post("/tudo/parar")
def parar_tudo():
    """Para o worker e o gateway. A API fica no ar de propósito (é ela que serve esta tela)."""
    return {"resultados": {n: _pm2(sv.parar, n) for n in sv.PROCESSOS if n != sv.API}, "api_mantida": True}


@router.post("/tudo/iniciar")
def iniciar_tudo():
    return {"resultados": {n: _pm2(sv.iniciar, n) for n in sv.PROCESSOS if n != sv.API}}
