from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from api.dependencies import FiltrosLeads, filtros_compartilhados, get_session
from api.services import export_service

router = APIRouter(prefix="/exportacoes", tags=["exportacoes"])

_TIPOS = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@router.get("/leads")
def exportar(
    formato: str = Query("csv", pattern="^(csv|xlsx)$"),
    f: FiltrosLeads = Depends(filtros_compartilhados),
    session: Session = Depends(get_session),
):
    """Exporta TODOS os leads do universo filtrado (não só a página atual)."""
    dados = export_service.linhas(session, f)
    conteudo = export_service.gerar_csv(dados) if formato == "csv" else export_service.gerar_xlsx(dados)
    nome = f"leads_{datetime.now():%Y%m%d_%H%M}.{formato}"
    return Response(
        content=conteudo,
        media_type=_TIPOS[formato],
        headers={
            "Content-Disposition": f'attachment; filename="{nome}"',
            "X-Total-Linhas": str(len(dados)),
            "Access-Control-Expose-Headers": "Content-Disposition, X-Total-Linhas",
        },
    )
