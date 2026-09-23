from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api import dominio as d
from api.dependencies import get_session
from db.models import Empresa, Nicho

router = APIRouter(tags=["filtros"])


@router.get("/nichos")
def nichos(session: Session = Depends(get_session)):
    linhas = session.execute(
        select(Nicho.id, Nicho.slug, Nicho.nome, func.count(Empresa.id))
        .select_from(Nicho)
        .outerjoin(Empresa, Empresa.nicho_id == Nicho.id)
        .group_by(Nicho.id)
        .order_by(Nicho.nome)
    ).all()
    return [{"id": i, "slug": s, "nome": n, "total": t} for i, s, n, t in linhas]


@router.get("/filtros/opcoes")
def opcoes(uf: Optional[str] = Query(None, min_length=2, max_length=2), session: Session = Depends(get_session)):
    ufs = session.execute(
        select(Empresa.uf, func.count()).where(Empresa.uf.isnot(None)).group_by(Empresa.uf).order_by(Empresa.uf)
    ).all()

    q = select(Empresa.municipio, Empresa.uf, func.count()).where(Empresa.municipio.isnot(None))
    if uf:
        q = q.where(Empresa.uf == uf.upper())
    municipios = session.execute(q.group_by(Empresa.municipio, Empresa.uf).order_by(Empresa.uf, Empresa.municipio)).all()
    sem_municipio = session.execute(
        select(func.count()).select_from(Empresa).where(Empresa.municipio.is_(None) | (Empresa.municipio == ""))
    ).scalar_one()

    return {
        "ufs": [{"codigo": u, "rotulo": u, "total": t} for u, t in ufs],
        "municipios": [{"municipio": m, "uf": u, "total": t} for m, u, t in municipios],
        "empresas_sem_municipio": sem_municipio,
        "faixas": [{"codigo": c, "rotulo": r} for c, r in d.FAIXAS],
        "cortes_score": {"neutro": d.SCORE_NEUTRO, "alto_min": d.SCORE_ALTO_MIN},
        "canais": [{"codigo": c, "rotulo": r} for c, r in d.CANAIS],
        "colunas": [
            {"codigo": c, "rotulo": d.COLUNA_ROTULOS[c], "estagios": d.COLUNA_ESTAGIOS[c], "estagio_canonico": d.ESTAGIO_CANONICO_DA_COLUNA[c]}
            for c in d.COLUNAS_ORDEM
        ],
        "estagios": [{"codigo": e, "rotulo": d.ESTAGIO_ROTULOS[e], "coluna": d.ESTAGIO_COLUNA[e]} for e in d.ESTAGIOS],
        "email_status": [{"codigo": c, "rotulo": r} for c, r in d.EMAIL_STATUS],
        "site_ddg": [
            {"codigo": "legado", "rotulo": "Histórico (sem DuckDuckGo)"},
            {"codigo": "site_osm", "rotulo": "Site informado pelo OpenStreetMap"},
            {"codigo": "encontrado", "rotulo": "Site encontrado (DuckDuckGo)"},
            {"codigo": "sem_site", "rotulo": "Sem site nos 5 resultados (DuckDuckGo)"},
            {"codigo": "ambiguo", "rotulo": "Resultado ambíguo (DuckDuckGo)"},
            {"codigo": "erro", "rotulo": "Erro na busca DuckDuckGo"},
            {"codigo": "rate_limit", "rotulo": "Rate limit DuckDuckGo"},
        ],
        "page_size_max": d.PAGE_SIZE_MAX,
    }
