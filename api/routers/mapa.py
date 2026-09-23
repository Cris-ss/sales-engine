"""Mapa: só LÊ coordenadas já gravadas em empresa_geolocalizacoes.

Nunca geocodifica (nem chama API externa) ao ser consultado: o enriquecimento é
um comando de manutenção separado (maintenance/geolocation).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api import dominio
from api.dependencies import FiltrosLeads, filtros_compartilhados, get_session
from api.errors import ApiError
from api.queries.lead_projection import LeadProjection
from api.services.lead_service import montar_condicoes

router = APIRouter(prefix="/mapa", tags=["mapa"])


@router.get("/leads")
def leads_no_mapa(
    min_lat: Optional[float] = Query(None, ge=-90, le=90),
    min_lng: Optional[float] = Query(None, ge=-180, le=180),
    max_lat: Optional[float] = Query(None, ge=-90, le=90),
    max_lng: Optional[float] = Query(None, ge=-180, le=180),
    f: FiltrosLeads = Depends(filtros_compartilhados),
    session: Session = Depends(get_session),
):
    """Pontos dos leads filtrados dentro da área visível (bbox).

    Se houver mais pontos que o limite, NÃO trunca em silêncio: devolve
    `excedeu_limite=true` e nenhum ponto, pedindo para aproximar o mapa.
    Sempre informa quantas empresas do universo filtrado não têm coordenadas.
    """
    caixa = (min_lat, min_lng, max_lat, max_lng)
    if any(v is not None for v in caixa) and any(v is None for v in caixa):
        raise ApiError(422, "bbox_incompleta", "Informe min_lat, min_lng, max_lat e max_lng juntos.")
    if min_lat is not None and (min_lat > max_lat or min_lng > max_lng):
        raise ApiError(422, "bbox_invalida", "min_* não pode ser maior que max_*.")

    p = LeadProjection()
    conds = montar_condicoes(session, p, f)
    g = p.geo

    total_filtrado = session.execute(select(func.count(p.E.id)).select_from(p.join).where(*conds)).scalar_one()
    por_precisao = dict(
        session.execute(
            select(g.c.precisao, func.count()).select_from(p.join).where(*conds, p.tem_localizacao).group_by(g.c.precisao)
        ).all()
    )
    com_coordenadas = sum(por_precisao.values())

    recorte = [*conds, p.tem_localizacao]
    if min_lat is not None:
        recorte += [g.c.latitude.between(min_lat, max_lat), g.c.longitude.between(min_lng, max_lng)]

    total_no_recorte = session.execute(select(func.count(p.E.id)).select_from(p.join).where(*recorte)).scalar_one()
    limite = dominio.MAPA_MAX_PONTOS
    excedeu = total_no_recorte > limite

    itens = []
    if not excedeu:
        rows = session.execute(
            select(
                p.E.id.label("id"), p.nome.label("nome"), g.c.latitude.label("latitude"), g.c.longitude.label("longitude"),
                g.c.precisao.label("precisao"), p.score.label("score"), p.faixa.label("faixa_score"),
                p.coluna.label("coluna"), p.estagio.label("estagio"), p.N.slug.label("nicho_slug"),
                p.E.municipio.label("municipio"), p.E.uf.label("uf"),
            )
            .select_from(p.join)
            .where(*recorte)
            .order_by(p.score.desc().nulls_last(), p.E.id)
        ).mappings().all()
        itens = [dict(r) for r in rows]

    return {
        "itens": itens,
        "total_no_recorte": total_no_recorte,
        "excedeu_limite": excedeu,
        "limite": limite,
        "total_filtrado": total_filtrado,
        "com_coordenadas": com_coordenadas,
        "sem_coordenadas": total_filtrado - com_coordenadas,
        "por_precisao": {"municipio": por_precisao.get("municipio", 0), "cep": por_precisao.get("cep", 0), "estabelecimento": por_precisao.get("estabelecimento", 0)},
        "legenda_precisao": {
            "municipio": "Centro (sede) do município — NÃO é o endereço da empresa.",
            "cep": "Ponto aproximado do CEP — não é o endereço exato do estabelecimento.",
            "estabelecimento": "Posição cadastrada no OpenStreetMap para o estabelecimento.",
        },
    }
