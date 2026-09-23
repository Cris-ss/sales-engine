"""Etapa 7 (WhatsApp): controle e leitura. A API NÃO abre a conexão Baileys nem conversa com o modelo:
grava comandos/autorizações e lê estado; quem envia é o gateway (Node), quem decide é o worker (Python).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.dependencies import get_session
from api.errors import ApiError
from api.persistence.whatsapp_models import (
    AceiteComercial, CONTROLES, DemandaComercial, EmpresaTelefoneManual, PoliticaComercial, PropostaComercial, WhatsappAutorizacao, WhatsappConta, WhatsappContato,
    WhatsappConversa, WhatsappEventoEntrada, WhatsappJob, WhatsappMensagem, WhatsappNotificacaoOperador, WhatsappOutbox,
)
from db.models import Empresa
from etapa7_whatsapp import servico
from etapa7_whatsapp.bloqueios import bloqueios_da_conversa
from etapa7_whatsapp.guards import agora_utc, autorizacao_ativa, suprimido
from etapa7_whatsapp.politica import modo_envio, politica_ativa, publicar_politica, validar_config

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])
OPERADOR = "operador"  # aplicação local de um único operador, sem login (ver docs)


def _erro(exc: servico.ServicoErro) -> ApiError:
    return ApiError(exc.status, exc.codigo, exc.mensagem)


def _executar(session: Session, fn):
    try:
        resultado = fn()
        session.commit()
        return resultado
    except servico.ServicoErro as exc:
        session.rollback()
        raise _erro(exc) from exc


# ---------------------------------------------------------------- conta / conexão

def _primeiros_contatos_hoje(session: Session, conta: WhatsappConta) -> int:
    """Lembrete (não bloqueia nada): primeiros contatos que o operador confirmou ter enviado hoje (dia local da conta)."""
    from zoneinfo import ZoneInfo

    inicio = agora_utc().astimezone(ZoneInfo(conta.timezone)).replace(hour=0, minute=0, second=0, microsecond=0)
    return session.execute(
        select(func.count()).select_from(WhatsappMensagem).where(
            WhatsappMensagem.estado_transporte.in_(("enviada_manual", "aceita", "entregue", "lida")),
            WhatsappMensagem.meta["sugestao"]["primeiro_contato"].astext == "true", WhatsappMensagem.ts_provedor >= inicio,
        )
    ).scalar_one()


def _conta_dict(session: Session, conta: WhatsappConta) -> dict[str, Any]:
    pol = politica_ativa(session)
    agora = agora_utc()
    heartbeat = conta.heartbeat_em
    return {
        "id": conta.id, "numero": conta.numero, "estado": conta.estado,
        "gateway_ativo": bool(heartbeat and agora - heartbeat < timedelta(seconds=30)),
        "qr_disponivel": bool(conta.qr_atual) and conta.estado == "aguardando_qr",
        "automacao_habilitada": conta.automacao_habilitada, "motivo_pausa": conta.motivo_pausa,
        "vendas_ativas": bool(pol.config.get("vendas_ativas")), "politica_versao": pol.versao,
        "modo_envio": modo_envio(pol.config),
        "primeiros_contatos_hoje": _primeiros_contatos_hoje(session, conta),
        "aceites_pendentes": session.execute(select(func.count()).select_from(AceiteComercial).where(AceiteComercial.tratado_em.is_(None))).scalar_one(),
        "sugestoes_pendentes": session.execute(select(func.count()).select_from(WhatsappMensagem).where(WhatsappMensagem.estado_transporte == "sugerida")).scalar_one(),
        "limites": pol.config["limites"],
        "notificacoes_operador": {
            "pendentes": session.execute(select(func.count()).select_from(WhatsappNotificacaoOperador).where(WhatsappNotificacaoOperador.status.in_(("pendente", "enviando")))).scalar_one(),
            "falhas": session.execute(select(func.count()).select_from(WhatsappNotificacaoOperador).where(WhatsappNotificacaoOperador.status == "falhou")).scalar_one(),
        },
        "fila": {
            "jobs_pendentes": session.execute(select(func.count()).select_from(WhatsappJob).where(WhatsappJob.status.in_(("pendente", "em_execucao")))).scalar_one(),
            "outbox_pendente": session.execute(select(func.count()).select_from(WhatsappOutbox).where(WhatsappOutbox.status == "aguardando_envio")).scalar_one(),
            "eventos_nao_processados": session.execute(select(func.count()).select_from(WhatsappEventoEntrada).where(WhatsappEventoEntrada.processado.is_(False))).scalar_one(),
        },
    }


@router.get("/status")
def status(session: Session = Depends(get_session)):
    conta = servico.obter_conta(session)
    politica_ativa(session)  # cria a versão 1 (se faltar) e COMMITA antes das leituras: nada fica pendente durante o resto da consulta
    session.commit()
    return _conta_dict(session, conta)


@router.get("/qr")
def qr(session: Session = Depends(get_session)):
    conta = servico.obter_conta(session)
    if conta.estado != "aguardando_qr" or not conta.qr_atual:
        raise ApiError(404, "qr_indisponivel", "Não há QR code aguardando leitura.")
    return {"qr": conta.qr_atual}


class ComandoConexao(BaseModel):
    confirmar: bool = False


@router.post("/conectar")
def conectar(corpo: ComandoConexao, session: Session = Depends(get_session)):
    """Pede ao gateway que inicie a sessão. Conecta o WhatsApp REAL: exige confirmação explícita."""
    if not corpo.confirmar:
        raise ApiError(422, "confirmacao_necessaria", "Confirme: isto conecta um número de WhatsApp real ao sistema.")
    conta = servico.obter_conta(session)
    conta.comando_pendente = "conectar"
    servico.auditar(session, conta.id, OPERADOR, "comando_conectar")
    session.commit()
    return _conta_dict(session, conta)


@router.post("/desconectar")
def desconectar(session: Session = Depends(get_session)):
    conta = servico.obter_conta(session)
    conta.comando_pendente = "desconectar"
    servico.auditar(session, conta.id, OPERADOR, "comando_desconectar")
    session.commit()
    return _conta_dict(session, conta)


class KillSwitch(BaseModel):
    pausar: bool
    motivo: Optional[str] = Field(default=None, max_length=200)


@router.post("/kill-switch")
def kill_switch(corpo: KillSwitch, session: Session = Depends(get_session)):
    conta = _executar(session, lambda: servico.alternar_kill_switch(session, corpo.pausar, OPERADOR, corpo.motivo))
    return _conta_dict(session, conta)


# ---------------------------------------------------------------- política comercial

def _politica_dict(p: PoliticaComercial) -> dict:
    return {"id": p.id, "versao": p.versao, "ativa": p.ativa, "config": p.config, "criado_por": p.criado_por, "criado_em": p.criado_em}


@router.get("/politica")
def politica(session: Session = Depends(get_session)):
    ativa = politica_ativa(session)
    session.commit()
    historico = session.execute(select(PoliticaComercial).order_by(PoliticaComercial.versao.desc()).limit(10)).scalars().all()
    return {"ativa": _politica_dict(ativa), "historico": [{"versao": h.versao, "ativa": h.ativa, "criado_por": h.criado_por, "criado_em": h.criado_em} for h in historico]}


class NovaPolitica(BaseModel):
    config: dict
    confirmar_ativacao_vendas: bool = False
    confirmar_envio_automatico: bool = False


@router.put("/politica")
def publicar(corpo: NovaPolitica, session: Session = Depends(get_session)):
    """Cria uma NOVA versão (a anterior é preservada). Ligar `vendas_ativas` exige confirmação explícita."""
    atual = politica_ativa(session)
    liga = bool(corpo.config.get("vendas_ativas")) and not atual.config.get("vendas_ativas")
    if liga and not corpo.confirmar_ativacao_vendas:
        raise ApiError(422, "confirmacao_necessaria", "Ativar a conversa de venda automática exige confirmar_ativacao_vendas=true "
                       "(revise os valores e faça o teste supervisionado antes).")
    if modo_envio(corpo.config) == "automatico" and modo_envio(atual.config) != "automatico" and not corpo.confirmar_envio_automatico:
        raise ApiError(422, "confirmacao_necessaria", "Ativar o envio AUTOMÁTICO exige confirmar_envio_automatico=true: o gateway "
                       "passará a enviar mensagens pelo Baileys.")
    try:
        validar_config(corpo.config)
    except ValueError as exc:
        raise ApiError(422, "politica_invalida", str(exc)) from exc
    nova = publicar_politica(session, corpo.config, OPERADOR)
    servico.auditar(session, None, OPERADOR, "publicar_politica", "politica", nova.id, {"versao": nova.versao, "vendas_ativas": bool(corpo.config.get("vendas_ativas"))})
    session.commit()
    return _politica_dict(nova)


# ---------------------------------------------------------------- lead: autorização

class AutorizarLead(BaseModel):
    telefone: str
    confirmar: bool = False


def _aut_dict(a: WhatsappAutorizacao) -> dict:
    return {"id": a.id, "telefone": a.telefone_exato, "status": a.status, "expira_em": a.expira_em, "criado_em": a.criado_em, "autorizado_por": a.autorizado_por}


@router.get("/leads/{empresa_id}")
def do_lead(empresa_id: int, session: Session = Depends(get_session)):
    empresa = session.get(Empresa, empresa_id)
    if empresa is None:
        raise ApiError(404, "lead_nao_encontrado", "Lead inexistente.")
    conta = servico.obter_conta(session)
    session.commit()
    agora = agora_utc()
    telefones = []
    manuais = {t for (t,) in session.execute(select(EmpresaTelefoneManual.telefone).where(EmpresaTelefoneManual.empresa_id == empresa.id))}
    for bruto in (empresa.telefone1, empresa.telefone2):
        e164 = servico.normalizar_telefone_e164(bruto)
        if e164 and e164 not in [t["telefone"] for t in telefones]:
            contato = session.execute(select(WhatsappContato).where(WhatsappContato.telefone_e164 == e164)).scalars().first()
            aut = autorizacao_ativa(session, conta.id, contato.id, agora) if contato else None
            conversa = session.execute(select(WhatsappConversa).where(WhatsappConversa.contato_id == contato.id)).scalars().first() if contato else None
            telefones.append({
                "bloqueios": bloqueios_da_conversa(session, conversa) if conversa else [],
                "telefone": e164, "original": bruto, "origem": "manual_operador" if e164[3:] in manuais else None, "autorizacao": _aut_dict(aut) if aut else None,
                "suprimido": bool(contato and suprimido(session, conta.id, contato.id)),
                "conversa_id": conversa.id if conversa else None, "controle": conversa.controle if conversa else None,
            })
    session.commit()
    return {"empresa_id": empresa.id, "nome": empresa.nome_fantasia or empresa.razao_social, "telefones": telefones,
            "contexto_manual": empresa.contexto_manual,
            "pode_adicionar_telefone": not (empresa.telefone1 or "").strip() or not (empresa.telefone2 or "").strip(),
            "conta": {"estado": conta.estado, "automacao_habilitada": conta.automacao_habilitada, "modo_envio": modo_envio(politica_ativa(session).config)}}


@router.post("/leads/{empresa_id}/autorizar", status_code=201)
def autorizar(empresa_id: int, corpo: AutorizarLead, session: Session = Depends(get_session)):
    if not corpo.confirmar:
        raise ApiError(422, "confirmacao_necessaria", "Confirme: as respostas seguintes serão automáticas para este número.")
    aut, conversa, criada = _executar(session, lambda: servico.autorizar_lead(session, empresa_id, corpo.telefone, OPERADOR))
    return {"autorizacao": _aut_dict(aut), "conversa_id": conversa.id, "criada": criada}


class AutorizarNovo(BaseModel):
    telefone: str
    nome: str = Field(min_length=2, max_length=255)
    nicho_id: int
    contexto: Optional[str] = Field(default=None, max_length=4000)
    confirmar: bool = False


class ContextoManual(BaseModel):
    contexto: Optional[str] = Field(default=None, max_length=4000)


@router.put("/leads/{empresa_id}/contexto")
def contexto_manual(empresa_id: int, corpo: ContextoManual, session: Session = Depends(get_session)):
    """Contexto livre do operador sobre o lead (vazio = limpar). Só apoio para a IA; nunca preço/catálogo."""
    empresa = _executar(session, lambda: servico.definir_contexto(session, empresa_id, corpo.contexto, OPERADOR))
    return {"empresa_id": empresa.id, "contexto_manual": empresa.contexto_manual}


class TelefoneManual(BaseModel):
    telefone: str


@router.put("/leads/{empresa_id}/telefone")
def telefone_manual(empresa_id: int, corpo: TelefoneManual, session: Session = Depends(get_session)):
    """Preenche um telefone vazio de um lead existente (origem registrada como manual_operador). Não autoriza nada."""
    empresa, alterado = _executar(session, lambda: servico.definir_telefone_manual(session, empresa_id, corpo.telefone, OPERADOR))
    return {"empresa_id": empresa.id, "alterado": alterado}


@router.post("/leads/{empresa_id}/telefone/remover")
def telefone_manual_remover(empresa_id: int, corpo: TelefoneManual, session: Session = Depends(get_session)):
    """Remove um telefone digitado manualmente (nunca Receita/OSM) e revoga a autorização daquele número. Histórico mantido."""
    empresa, revogada = _executar(session, lambda: servico.remover_telefone_manual(session, empresa_id, corpo.telefone, OPERADOR))
    return {"empresa_id": empresa.id, "removido": True, "autorizacao_revogada": revogada is not None}


@router.post("/autorizar-novo", status_code=201)
def autorizar_novo(corpo: AutorizarNovo, session: Session = Depends(get_session)):
    """Atalho: cria a empresa (fonte=manual_operador) e autoriza o número de uma vez. Continua sendo autorização explícita do operador."""
    if not corpo.confirmar:
        raise ApiError(422, "confirmacao_necessaria", "Confirme: as respostas seguintes serão automáticas para este número.")
    empresa, aut, conversa, empresa_criada, criada = _executar(
        session, lambda: servico.criar_e_autorizar(session, corpo.telefone, corpo.nome, corpo.nicho_id, OPERADOR, contexto=corpo.contexto))
    return {"empresa_id": empresa.id, "empresa_criada": empresa_criada, "autorizacao": _aut_dict(aut), "conversa_id": conversa.id, "criada": criada}


@router.post("/autorizacoes/{autorizacao_id}/revogar")
def revogar(autorizacao_id: int, session: Session = Depends(get_session)):
    aut = _executar(session, lambda: servico.revogar_autorizacao(session, autorizacao_id, OPERADOR))
    return _aut_dict(aut)


# ---------------------------------------------------------------- caixa de entrada / conversas

def _nome_conversa(session: Session, c: WhatsappConversa) -> dict:
    contato = session.get(WhatsappContato, c.contato_id)
    empresa = session.get(Empresa, c.empresa_id) if c.empresa_id else None
    return {"contato_nome": contato.nome_exibido if contato else None, "telefone": contato.telefone_e164 if contato else None,
            "empresa_id": c.empresa_id, "empresa_nome": (empresa.nome_fantasia or empresa.razao_social) if empresa else None}


@router.get("/conversas")
def conversas(controle: Optional[str] = Query(default=None), problemas: bool = False, sugestoes: bool = False, aceites: bool = False, limite: int = Query(default=50, ge=1, le=200),
              session: Session = Depends(get_session)):
    if controle is not None and controle not in CONTROLES:
        raise ApiError(422, "filtro_invalido", f"controle inválido: {controle}")
    conta = servico.obter_conta(session)
    session.commit()
    q = select(WhatsappConversa).where(WhatsappConversa.conta_id == conta.id)
    if controle:
        q = q.where(WhatsappConversa.controle == controle)
    if aceites:
        q = q.where(WhatsappConversa.id.in_(
            select(PropostaComercial.conversa_id).join(AceiteComercial, AceiteComercial.proposta_id == PropostaComercial.id).where(AceiteComercial.tratado_em.is_(None))))
    if sugestoes:
        q = q.where(WhatsappConversa.id.in_(select(WhatsappMensagem.conversa_id).where(WhatsappMensagem.estado_transporte == "sugerida")))
    if problemas:  # mensagens com falha ou envio incerto
        q = q.where(WhatsappConversa.id.in_(select(WhatsappOutbox.conversa_id).where(WhatsappOutbox.status.in_(("falhou", "incerto")))))
    itens = session.execute(q.order_by(WhatsappConversa.ultima_recebida_em.desc().nulls_last(), WhatsappConversa.id.desc()).limit(limite)).scalars().all()
    resumo = dict(session.execute(select(WhatsappConversa.controle, func.count()).where(WhatsappConversa.conta_id == conta.id).group_by(WhatsappConversa.controle)).all())
    problemas_n = session.execute(select(func.count(func.distinct(WhatsappOutbox.conversa_id))).where(WhatsappOutbox.status.in_(("falhou", "incerto")))).scalar_one()
    saida = []
    for c in itens:
        ultima = session.execute(select(WhatsappMensagem).where(WhatsappMensagem.conversa_id == c.id).order_by(WhatsappMensagem.id.desc()).limit(1)).scalar_one_or_none()
        bloq = bloqueios_da_conversa(session, c)
        sug = session.execute(select(WhatsappMensagem.id).where(WhatsappMensagem.conversa_id == c.id, WhatsappMensagem.estado_transporte == "sugerida").limit(1)).first() is not None
        aceite_pend = session.execute(
            select(AceiteComercial.id).join(PropostaComercial, AceiteComercial.proposta_id == PropostaComercial.id)
            .where(PropostaComercial.conversa_id == c.id, AceiteComercial.tratado_em.is_(None)).limit(1)).first() is not None
        saida.append({"id": c.id, "controle": c.controle, "bloqueios": bloq, "sugestao_pendente": sug, "aceite_pendente": aceite_pend, "estagio": c.estagio, "motivo_escalada": c.motivo_escalada,
                      "ultima_mensagem": ultima.texto if ultima else None, "ultima_autoria": ultima.autoria if ultima else None,
                      "ultima_recebida_em": c.ultima_recebida_em, **_nome_conversa(session, c)})
    com_sugestao = session.execute(select(func.count(func.distinct(WhatsappMensagem.conversa_id))).where(WhatsappMensagem.estado_transporte == "sugerida")).scalar_one()
    return {"itens": saida, "resumo": {**{k: 0 for k in CONTROLES}, **resumo, "com_problema": problemas_n, "com_sugestao": com_sugestao,
                                                                                 "com_aceite": session.execute(select(func.count()).select_from(AceiteComercial).where(AceiteComercial.tratado_em.is_(None))).scalar_one()}}


@router.get("/conversas/{conversa_id}")
def conversa(conversa_id: int, session: Session = Depends(get_session)):
    c = session.get(WhatsappConversa, conversa_id)
    if c is None:
        raise ApiError(404, "conversa_nao_encontrada", "Conversa inexistente.")
    msgs = session.execute(select(WhatsappMensagem).where(WhatsappMensagem.conversa_id == c.id).order_by(WhatsappMensagem.id.desc()).limit(200)).scalars().all()[::-1]
    proposta = session.execute(select(PropostaComercial).where(PropostaComercial.conversa_id == c.id).order_by(PropostaComercial.id.desc()).limit(1)).scalar_one_or_none()
    demandas = session.execute(select(DemandaComercial).where(DemandaComercial.conversa_id == c.id)).scalars().all()
    aut = autorizacao_ativa(session, c.conta_id, c.contato_id, agora_utc())
    session.commit()
    return {
        "id": c.id, "controle": c.controle, "estagio": c.estagio, "motivo_escalada": c.motivo_escalada, "resumo": c.resumo,
        "estado_comercial": {k: v for k, v in (c.estado_comercial or {}).items() if k != "primeira_pergunta_msg_id"},
        **_nome_conversa(session, c), "autorizacao": _aut_dict(aut) if aut else None,
        "suprimido": suprimido(session, c.conta_id, c.contato_id),
        "bloqueios": bloqueios_da_conversa(session, c),
        "aceites": [{"id": a.id, "criado_em": a.criado_em, "tratado_em": a.tratado_em}
                    for a in session.execute(select(AceiteComercial).join(PropostaComercial, AceiteComercial.proposta_id == PropostaComercial.id)
                                             .where(PropostaComercial.conversa_id == c.id).order_by(AceiteComercial.id)).scalars()],
        "sugestoes": [{"id": m.id, "texto": m.texto, "primeiro_contato": bool(((m.meta or {}).get("sugestao") or {}).get("primeiro_contato")),
                       "acao": ((m.meta or {}).get("sugestao") or {}).get("acao"), "criada_em": m.recebida_em}
                      for m in msgs if m.estado_transporte == "sugerida"],
        "mensagens": [{"id": m.id, "direcao": m.direcao, "autoria": m.autoria, "tipo": m.tipo, "texto": m.texto,
                       "estado": m.estado_transporte, "origem": m.origem, "em": m.ts_provedor or m.recebida_em} for m in msgs],
        "proposta": ({"id": proposta.id, "pacote": proposta.pacote, "itens": proposta.itens, "setup_centavos": proposta.setup_centavos,
                      "mensalidade_centavos": proposta.mensalidade_centavos, "status": proposta.status} if proposta else None),
        "demandas": [{"id": d.id, "descricao": d.descricao, "revisada": d.revisada} for d in demandas],
    }


class EnvioManual(BaseModel):
    texto: str = Field(min_length=1, max_length=4000)


@router.post("/conversas/{conversa_id}/mensagens", status_code=201)
def enviar(conversa_id: int, corpo: EnvioManual, session: Session = Depends(get_session)):
    out = _executar(session, lambda: servico.enviar_manual(session, conversa_id, corpo.texto, OPERADOR))
    return {"outbox_id": out.id, "status": out.status}


class TextoEnviado(BaseModel):
    texto: Optional[str] = Field(default=None, max_length=4000)


@router.post("/mensagens/{mensagem_id}/enviada")
def sugestao_enviada(mensagem_id: int, corpo: TextoEnviado, session: Session = Depends(get_session)):
    """Modo copiloto: confirma que a sugestão foi enviada FORA do sistema (texto exato, ou `texto` com a versão que você enviou)."""
    m = _executar(session, lambda: servico.confirmar_sugestao(session, mensagem_id, OPERADOR, corpo.texto))
    return {"id": m.id, "estado": m.estado_transporte, "editada": bool((m.meta or {}).get("manual", {}).get("editada"))}


@router.post("/mensagens/{mensagem_id}/descartar")
def sugestao_descartar(mensagem_id: int, session: Session = Depends(get_session)):
    m = _executar(session, lambda: servico.descartar_sugestao(session, mensagem_id, OPERADOR))
    return {"id": m.id, "estado": m.estado_transporte}


@router.post("/conversas/{conversa_id}/registrar-envio", status_code=201)
def registrar_envio(conversa_id: int, corpo: EnvioManual, session: Session = Depends(get_session)):
    """Modo copiloto: registra no histórico uma mensagem que você escreveu e enviou por conta própria, fora do sistema."""
    m = _executar(session, lambda: servico.registrar_envio_manual(session, conversa_id, corpo.texto, OPERADOR))
    return {"id": m.id, "estado": m.estado_transporte}


@router.post("/aceites/{aceite_id}/tratado")
def aceite_tratado(aceite_id: int, session: Session = Depends(get_session)):
    """Marca que você já tratou este aceite (entrou em contato para os próximos passos): sai do contador."""
    a = session.get(AceiteComercial, aceite_id)
    if a is None:
        raise ApiError(404, "aceite_nao_encontrado", "Aceite inexistente.")
    if a.tratado_em is None:
        a.tratado_em = agora_utc()
        servico.auditar(session, None, OPERADOR, "aceite_tratado", "aceite", a.id)
    session.commit()
    return {"id": a.id, "tratado_em": a.tratado_em}


@router.post("/conversas/{conversa_id}/assumir")
def assumir(conversa_id: int, session: Session = Depends(get_session)):
    c = _executar(session, lambda: servico.mudar_controle(session, conversa_id, "humano", OPERADOR))
    return {"id": c.id, "controle": c.controle}


@router.post("/conversas/{conversa_id}/pausar")
def pausar(conversa_id: int, session: Session = Depends(get_session)):
    c = _executar(session, lambda: servico.mudar_controle(session, conversa_id, "pausada", OPERADOR))
    return {"id": c.id, "controle": c.controle}


@router.post("/conversas/{conversa_id}/retomar-ia")
def retomar(conversa_id: int, session: Session = Depends(get_session)):
    c = _executar(session, lambda: servico.mudar_controle(session, conversa_id, "automatizada", OPERADOR))
    return {"id": c.id, "controle": c.controle, "tarefa_recriada": getattr(c, "tarefa_recriada", None)}


@router.get("/demandas")
def demandas(session: Session = Depends(get_session)):
    linhas = session.execute(select(DemandaComercial).order_by(DemandaComercial.id.desc()).limit(100)).scalars().all()
    return [{"id": d.id, "conversa_id": d.conversa_id, "descricao": d.descricao, "revisada": d.revisada, "criado_em": d.criado_em} for d in linhas]


@router.post("/demandas/{demanda_id}/revisada")
def demanda_revisada(demanda_id: int, session: Session = Depends(get_session)):
    d = session.get(DemandaComercial, demanda_id)
    if d is None:
        raise ApiError(404, "demanda_nao_encontrada", "Demanda inexistente.")
    d.revisada = True
    session.commit()
    return {"id": d.id, "revisada": True}
