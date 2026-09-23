from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import Iterator, Optional

from fastapi import Query
from sqlalchemy.orm import Session, sessionmaker

from api import settings
from api.dominio import (
    CANAL_CODIGOS,
    COLUNAS_ORDEM,
    EMAIL_STATUS_CODIGOS,
    ESTAGIOS,
    FAIXA_CODIGOS,
    PAGE_SIZE_DEFAULT,
    PAGE_SIZE_MAX,
)
from api.errors import ApiError
from db.models import get_engine


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker:
    return sessionmaker(bind=get_engine(settings.database_url()), future=True)


def get_session() -> Iterator[Session]:
    """Uma sessão por requisição."""
    session = _session_factory()()
    try:
        yield session
    finally:
        session.close()


@dataclass
class Paginacao:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def paginacao(
    page: int = Query(1, ge=1),
    page_size: int = Query(PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
) -> Paginacao:
    return Paginacao(page, page_size)


@dataclass
class FiltrosLeads:
    q: Optional[str] = None
    nicho_id: Optional[int] = None
    uf: Optional[str] = None
    municipio: Optional[str] = None
    score_min: Optional[float] = None
    score_max: Optional[float] = None
    sem_score: Optional[bool] = None
    faixa: Optional[str] = None
    canal: Optional[str] = None
    coluna: Optional[str] = None
    estagio: Optional[str] = None
    email_status: Optional[str] = None
    site_ddg: Optional[str] = None
    data_inicio_de: Optional[date] = None
    data_inicio_ate: Optional[date] = None
    sort: str = "score"
    order: str = "desc"


def _validar(nome: str, valor: Optional[str], validos: list[str]) -> Optional[str]:
    if valor is not None and valor not in validos:
        raise ApiError(422, "filtro_invalido", f"Valor inválido para '{nome}': {valor!r}", {"validos": validos})
    return valor


SORT_CAMPOS = ["nome", "score", "uf", "municipio", "nicho", "estagio", "email_enviado_em", "criado_em", "data_inicio_atividade"]
SITE_DDG_CODIGOS = ["legado", "site_osm", "encontrado", "sem_site", "ambiguo", "erro", "rate_limit"]


def filtros_compartilhados(
    q: Optional[str] = Query(None, description="nome, CNPJ ou telefone"),
    nicho_id: Optional[int] = None,
    uf: Optional[str] = Query(None, min_length=2, max_length=2),
    municipio: Optional[str] = None,
    score_min: Optional[float] = None,
    score_max: Optional[float] = None,
    sem_score: Optional[bool] = None,
    faixa: Optional[str] = None,
    canal: Optional[str] = None,
    coluna: Optional[str] = None,
    estagio: Optional[str] = None,
    email_status: Optional[str] = None,
    site_ddg: Optional[str] = None,
    data_inicio_de: Optional[date] = None,
    data_inicio_ate: Optional[date] = None,
    sort: str = "score",
    order: str = "desc",
) -> FiltrosLeads:
    _validar("faixa", faixa, FAIXA_CODIGOS)
    _validar("canal", canal, CANAL_CODIGOS)
    _validar("coluna", coluna, COLUNAS_ORDEM)
    _validar("estagio", estagio, ESTAGIOS)
    _validar("email_status", email_status, EMAIL_STATUS_CODIGOS)
    _validar("site_ddg", site_ddg, SITE_DDG_CODIGOS)
    _validar("sort", sort, SORT_CAMPOS)
    _validar("order", order, ["asc", "desc"])
    return FiltrosLeads(
        q=(q or "").strip() or None,
        nicho_id=nicho_id,
        uf=uf.upper() if uf else None,
        municipio=(municipio or "").strip() or None,
        score_min=score_min,
        score_max=score_max,
        sem_score=sem_score,
        faixa=faixa,
        canal=canal,
        coluna=coluna,
        estagio=estagio,
        email_status=email_status,
        site_ddg=site_ddg,
        data_inicio_de=data_inicio_de,
        data_inicio_ate=data_inicio_ate,
        sort=sort,
        order=order,
    )


def so_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto)
