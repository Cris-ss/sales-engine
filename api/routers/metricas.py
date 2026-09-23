from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.dependencies import FiltrosLeads, filtros_compartilhados, get_session
from api.services import metricas_service

router = APIRouter(prefix="/metricas", tags=["metricas"])


@router.get("/resumo")
def resumo(f: FiltrosLeads = Depends(filtros_compartilhados), session: Session = Depends(get_session)):
    return metricas_service.resumo(session, f)


@router.get("/funil")
def funil(f: FiltrosLeads = Depends(filtros_compartilhados), session: Session = Depends(get_session)):
    return metricas_service.funil(session, f)


@router.get("/conversao")
def conversao(
    nivel: str = Query("nicho", pattern="^(nicho|cidade)$"),
    limite: Optional[int] = Query(None, ge=1, le=1000),
    f: FiltrosLeads = Depends(filtros_compartilhados),
    session: Session = Depends(get_session),
):
    return metricas_service.conversao(session, f, nivel, limite)
