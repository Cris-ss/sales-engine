from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.dependencies import get_session
from api.errors import ApiError
from api.persistence.prospeccao_models import LoteProspeccao, LoteProspeccaoEmpresa, ValidacaoSiteDdg
from api.schemas.prospeccoes import CidadeSugestao, CriarLoteProspeccao, LoteProspeccaoResposta
from api.services.cidade_service import buscar_cidades
from api.services.prospeccao_service import iniciar_worker
from db.models import Nicho

router = APIRouter(prefix="/prospeccoes", tags=["prospecções"])


@router.get("/cidades", response_model=list[CidadeSugestao])
def cidades(q: str = Query(min_length=1, max_length=100)):
    try:
        return buscar_cidades(q)
    except Exception as exc:
        raise ApiError(502, "geocodificacao_indisponivel", "Não foi possível consultar cidades agora.", {"tipo": type(exc).__name__}) from exc


@router.get("", response_model=list[LoteProspeccaoResposta])
def listar(session: Session = Depends(get_session)):
    empresas = select(func.count()).where(LoteProspeccaoEmpresa.lote_id == LoteProspeccao.id).correlate(LoteProspeccao).scalar_subquery()
    validacoes = select(func.count()).where(ValidacaoSiteDdg.lote_id == LoteProspeccao.id).correlate(LoteProspeccao).scalar_subquery()
    rows = session.execute(
        select(LoteProspeccao, empresas.label("empresas_novas"), validacoes.label("validacoes_concluidas"))
        .order_by(LoteProspeccao.id.desc()).limit(20)
    ).all()
    return [
        LoteProspeccaoResposta.model_validate({
            **{c.name: getattr(lote, c.name) for c in LoteProspeccao.__table__.columns},
            "empresas_novas": total, "validacoes_concluidas": concluidas,
        })
        for lote, total, concluidas in rows
    ]


@router.post("", response_model=LoteProspeccaoResposta, status_code=201)
def criar(entrada: CriarLoteProspeccao, session: Session = Depends(get_session)):
    if entrada.fonte == "google_places":
        # Fonte desativada.
        raise ApiError(422, "google_places_proibido", "A fonte Google Places está desativada neste projeto.")
    if not entrada.confirmar:
        raise ApiError(422, "confirmacao_necessaria", "Confirme a criação do lote e as consultas externas escolhidas.")
    if session.get(Nicho, entrada.nicho_id) is None:
        raise ApiError(404, "nicho_nao_encontrado", f"Nicho {entrada.nicho_id} não existe.")
    em_andamento = session.execute(
        select(LoteProspeccao.id).where(LoteProspeccao.status.in_(("pendente", "executando"))).limit(1)
    ).scalar_one_or_none()
    if em_andamento is not None:
        raise ApiError(409, "lote_em_andamento", "Já há um lote pendente ou em execução.", {"lote_id": em_andamento})
    if entrada.fonte == "osm" and (not entrada.cidade or not entrada.raio_km):
        raise ApiError(422, "cidade_e_raio_necessarios", "Busca OSM exige cidade e raio.")
    lote = LoteProspeccao(
        nicho_id=entrada.nicho_id, uf=entrada.uf.upper(), limite=entrada.limite,
        fonte=entrada.fonte, cidade=entrada.cidade.strip() if entrada.cidade else None, raio_km=entrada.raio_km,
    )
    session.add(lote)
    session.commit()
    session.refresh(lote)
    iniciar_worker()
    return LoteProspeccaoResposta.model_validate({
        **{c.name: getattr(lote, c.name) for c in LoteProspeccao.__table__.columns},
        "empresas_novas": 0, "validacoes_concluidas": 0,
    })
