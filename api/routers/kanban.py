from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.dependencies import FiltrosLeads, Paginacao, filtros_compartilhados, get_session, paginacao
from api.dominio import COLUNA_ESTAGIOS, COLUNA_ROTULOS, COLUNAS_ORDEM
from api.errors import ApiError
from api.queries.lead_projection import LeadProjection
from api.schemas.comum import Pagina
from api.schemas.leads import LeadResumo
from api.services import lead_service

router = APIRouter(prefix="/kanban", tags=["kanban"])


@router.get("/resumo")
def resumo(f: FiltrosLeads = Depends(filtros_compartilhados), session: Session = Depends(get_session)):
    """Totais das 5 colunas dentro do universo filtrado (coluna/estágio do filtro
    são ignorados aqui, senão só uma coluna teria número)."""
    p = LeadProjection()
    conds = lead_service.montar_condicoes(session, p, f, ignorar=("coluna", "estagio"))
    linhas = session.execute(
        select(p.coluna, p.estagio, func.count()).select_from(p.join).where(*conds).group_by(p.coluna, p.estagio)
    ).all()
    totais = {c: 0 for c in COLUNAS_ORDEM}
    detalhe = {c: {e: 0 for e in COLUNA_ESTAGIOS[c]} for c in COLUNAS_ORDEM}
    for coluna, estagio, n in linhas:
        totais[coluna] += n
        detalhe[coluna][estagio] = n
    return {
        "colunas": [
            {"codigo": c, "rotulo": COLUNA_ROTULOS[c], "total": totais[c], "por_estagio": detalhe[c]}
            for c in COLUNAS_ORDEM
        ],
        "total": sum(totais.values()),
    }


@router.get("/colunas/{coluna_codigo}/leads", response_model=Pagina[LeadResumo])
def leads_da_coluna(
    coluna_codigo: str,
    f: FiltrosLeads = Depends(filtros_compartilhados),
    pag: Paginacao = Depends(paginacao),
    session: Session = Depends(get_session),
):
    if coluna_codigo not in COLUNAS_ORDEM:
        raise ApiError(404, "coluna_invalida", f"Coluna desconhecida: {coluna_codigo}", {"validas": COLUNAS_ORDEM})
    itens, total = lead_service.listar_leads(session, lead_service.com_coluna(f, coluna_codigo), pag)
    return Pagina[LeadResumo](itens=itens, total=total, page=pag.page, page_size=pag.page_size)
