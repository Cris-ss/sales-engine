from __future__ import annotations

from dataclasses import replace
from typing import Optional, Type

from sqlalchemy.orm import Session

from api.adapters.whatsapp_adapter import ids_com_telefone_apto, telefone_apto
from api.dependencies import FiltrosLeads, Paginacao
from api.errors import ApiError
from api.queries.lead_filters import condicoes, precisa_ids_whatsapp
from api.queries.lead_projection import LeadProjection
from api.schemas.leads import LeadDetalhe, LeadResumo


def linha_para_modelo(row, modelo: Type[LeadResumo] = LeadResumo):
    d = dict(row)
    d["whatsapp_apto"] = telefone_apto(d.get("telefone1"), d.get("telefone2"))
    d["telefone"] = d.get("telefone1") or d.get("telefone2")
    d["qtd_emails_enviados"] = int(d.get("qtd_emails_enviados") or 0)
    if d.get("latitude") is not None and d.get("longitude") is not None:
        d["localizacao"] = {
            "latitude": d["latitude"], "longitude": d["longitude"],
            "precisao": d.get("precisao_geo"), "fonte": d.get("fonte_geo"),
        }
    return modelo.model_validate(d)


def montar_condicoes(session: Session, p: LeadProjection, f: FiltrosLeads, ignorar=()):
    ids = ids_com_telefone_apto(session) if precisa_ids_whatsapp(f) else None
    return condicoes(p, f, ids, ignorar)


def listar_leads(
    session: Session, f: FiltrosLeads, pag: Paginacao, ignorar=()
) -> tuple[list[LeadResumo], int]:
    p = LeadProjection()
    conds = montar_condicoes(session, p, f, ignorar)
    total = session.execute(p.count().where(*conds)).scalar_one()
    stmt = (
        p.select()
        .where(*conds)
        .order_by(*p.ordenacao(f.sort, f.order))
        .limit(pag.page_size)
        .offset(pag.offset)
    )
    rows = session.execute(stmt).mappings().all()
    return [linha_para_modelo(r) for r in rows], total


def obter_detalhe_row(session: Session, empresa_id: int):
    p = LeadProjection()
    row = session.execute(p.select(p.colunas_detalhe()).where(p.E.id == empresa_id)).mappings().first()
    if row is None:
        raise ApiError(404, "lead_nao_encontrado", f"Lead {empresa_id} não existe.")
    return row


def obter_detalhe(session: Session, empresa_id: int) -> LeadDetalhe:
    return linha_para_modelo(obter_detalhe_row(session, empresa_id), LeadDetalhe)


def exigir_empresa(session: Session, empresa_id: int) -> None:
    from db.models import Empresa

    if session.get(Empresa, empresa_id) is None:
        raise ApiError(404, "lead_nao_encontrado", f"Lead {empresa_id} não existe.")


def com_coluna(f: FiltrosLeads, coluna: Optional[str]) -> FiltrosLeads:
    return replace(f, coluna=coluna)
