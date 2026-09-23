from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import cast, func, select, String
from sqlalchemy.orm import Session

from api.adapters.whatsapp_adapter import link_whatsapp
from api.dependencies import FiltrosLeads, Paginacao, filtros_compartilhados, get_session, paginacao
from api.dominio import ESTAGIO_COLUNA, faixa_score
from api.schemas.comum import Pagina
from api.schemas.leads import (
    ContatoItem,
    FunilItem,
    LeadDetalhe,
    LeadResumo,
    ScoreItem,
    TransicaoEntrada,
    TransicaoResposta,
    WhatsAppLink,
)
from api.services import funil_service, lead_service
from db.models import ContatoEnviado, FunilStatus, LeadScore

router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("", response_model=Pagina[LeadResumo])
def listar(
    f: FiltrosLeads = Depends(filtros_compartilhados),
    pag: Paginacao = Depends(paginacao),
    session: Session = Depends(get_session),
):
    itens, total = lead_service.listar_leads(session, f, pag)
    return Pagina[LeadResumo](itens=itens, total=total, page=pag.page, page_size=pag.page_size)


@router.get("/{empresa_id}", response_model=LeadDetalhe)
def detalhe(empresa_id: int, session: Session = Depends(get_session)):
    return lead_service.obter_detalhe(session, empresa_id)


@router.get("/{empresa_id}/scores", response_model=Pagina[ScoreItem])
def scores(empresa_id: int, pag: Paginacao = Depends(paginacao), session: Session = Depends(get_session)):
    lead_service.exigir_empresa(session, empresa_id)
    base = select(LeadScore).where(LeadScore.empresa_id == empresa_id)
    total = session.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    rows = session.execute(
        base.order_by(LeadScore.criado_em.desc().nulls_last(), LeadScore.id.desc()).limit(pag.page_size).offset(pag.offset)
    ).scalars().all()
    itens = [
        ScoreItem(
            id=r.id, score=r.score, faixa_score=faixa_score(r.score), modelo_usado=r.modelo_usado,
            prompt_versao=r.prompt_versao, dores_identificadas=r.dores_identificadas,
            justificativa=r.justificativa, criado_em=r.criado_em,
        )
        for r in rows
    ]
    return Pagina[ScoreItem](itens=itens, total=total, page=pag.page, page_size=pag.page_size)


def _status_normalizado(c: ContatoEnviado) -> str:
    if c.status_envio == "enviado" and c.sucesso_envio:
        return "enviado"
    if c.status_envio == "pendente" and c.erro:
        return "falhou"
    return c.status_envio


@router.get("/{empresa_id}/contatos", response_model=Pagina[ContatoItem])
def contatos(
    empresa_id: int,
    canal: Optional[str] = Query(None, pattern="^(email|formulario_site)$"),
    pag: Paginacao = Depends(paginacao),
    session: Session = Depends(get_session),
):
    lead_service.exigir_empresa(session, empresa_id)
    base = select(ContatoEnviado).where(ContatoEnviado.empresa_id == empresa_id)
    if canal:
        base = base.where(func.lower(cast(ContatoEnviado.canal, String)) == canal)
    total = session.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    rows = session.execute(
        base.order_by(ContatoEnviado.data_envio.desc().nulls_last(), ContatoEnviado.id.desc())
        .limit(pag.page_size)
        .offset(pag.offset)
    ).scalars().all()
    itens = [
        ContatoItem(
            id=r.id, canal=r.canal.value, destino=r.destino, assunto=r.assunto, corpo=r.corpo,
            status=_status_normalizado(r), status_envio=r.status_envio, sucesso_envio=r.sucesso_envio,
            erro=r.erro, gerado_em=r.enviado_em, enviado_em=r.data_envio,
        )
        for r in rows
    ]
    return Pagina[ContatoItem](itens=itens, total=total, page=pag.page, page_size=pag.page_size)


@router.get("/{empresa_id}/funil", response_model=Pagina[FunilItem])
def funil(empresa_id: int, pag: Paginacao = Depends(paginacao), session: Session = Depends(get_session)):
    lead_service.exigir_empresa(session, empresa_id)
    base = select(FunilStatus).where(FunilStatus.empresa_id == empresa_id)
    total = session.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    rows = session.execute(
        base.order_by(FunilStatus.criado_em.desc().nulls_last(), FunilStatus.id.desc())
        .limit(pag.page_size)
        .offset(pag.offset)
    ).scalars().all()
    itens = [
        FunilItem(
            id=r.id, estagio=r.estagio.value, coluna=ESTAGIO_COLUNA[r.estagio.value],
            observacao=r.observacao, criado_em=r.criado_em,
        )
        for r in rows
    ]
    return Pagina[FunilItem](itens=itens, total=total, page=pag.page, page_size=pag.page_size)


@router.get("/{empresa_id}/whatsapp-link", response_model=WhatsAppLink)
def whatsapp(empresa_id: int, session: Session = Depends(get_session)):
    """Só leitura: gera o link, não registra envio, não move o funil, não cria ContatoEnviado."""
    row = lead_service.obter_detalhe_row(session, empresa_id)
    empresa = SimpleNamespace(
        nome_fantasia=row["nome_fantasia"], razao_social=row["razao_social"], municipio=row["municipio"],
        uf=row["uf"], telefone1=row["telefone1"], telefone2=row["telefone2"],
    )
    return link_whatsapp(empresa, row["nicho_slug"], row["dores_identificadas"])


@router.post("/{empresa_id}/transicoes", response_model=TransicaoResposta)
def transicao(empresa_id: int, corpo: TransicaoEntrada, session: Session = Depends(get_session)):
    """Acrescenta uma linha em funil_status (nunca altera as anteriores).
    409 se o histórico vigente mudou desde que o cliente o carregou."""
    nova = funil_service.registrar_transicao(
        session, empresa_id, corpo.estagio_destino, corpo.id_historico_esperado, corpo.observacao
    )
    session.expire_all()
    lead = lead_service.linha_para_modelo(lead_service.obter_detalhe_row(session, empresa_id))
    return TransicaoResposta(funil_id=nova.id, lead=lead)
