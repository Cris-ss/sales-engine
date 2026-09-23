"""Tabela adicional de geolocalização (mesmo Base do db/models.py).

Fica separada de Empresa/Validacao de propósito: não muda a responsabilidade
das tabelas do pipeline e pode ser recalculada sem tocar nelas.

Uma linha por empresa guarda a MELHOR posição disponível:
  - precisao="municipio": ponto da sede do município (NÃO é o endereço);
    - precisao="cep": ponto devolvido para o CEP (aproximado; em cidades de CEP
    único pode coincidir com o centro da cidade).
Os campos cep_* controlam o refinamento por CEP (retomável, sem repetir consulta
que já falhou de forma definitiva).
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, DateTime, Float, ForeignKey, Integer, String, Text, func

from db.models import Base

FONTE_MUNICIPIO = "municipios_ibge_sede"
FONTE_CEP = "awesomeapi_cep"

PRECISOES = ("municipio", "cep", "estabelecimento")
STATUS = ("localizada", "nao_encontrada", "ambigua", "erro")
CEP_STATUS = ("pendente", "localizada", "nao_encontrada", "ambigua", "invalida", "erro")


def _in(coluna: str, valores) -> str:
    return f"{coluna} IN ({', '.join(repr(v) for v in valores)})"


class EmpresaGeolocalizacao(Base):
    __tablename__ = "empresa_geolocalizacoes"

    id = Column(Integer, primary_key=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False, unique=True)

    latitude = Column(Float)
    longitude = Column(Float)
    fonte = Column(String(40), nullable=False)
    precisao = Column(String(20), nullable=False)
    status = Column(String(16), nullable=False)
    endereco_hash = Column(String(64))  # hash da entrada usada (município|UF ou CEP)
    consultado_em = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    cep_status = Column(String(16), nullable=False, server_default="pendente")
    cep_tentativas = Column(Integer, nullable=False, server_default="0")
    cep_consultado_em = Column(DateTime(timezone=True))
    cep_erro = Column(Text)

    __table_args__ = (
        CheckConstraint("latitude IS NULL OR (latitude BETWEEN -90 AND 90)", name="ck_geo_latitude"),
        CheckConstraint("longitude IS NULL OR (longitude BETWEEN -180 AND 180)", name="ck_geo_longitude"),
        CheckConstraint(_in("precisao", PRECISOES), name="ck_geo_precisao"),
        CheckConstraint(_in("status", STATUS), name="ck_geo_status"),
        CheckConstraint(_in("cep_status", CEP_STATUS), name="ck_geo_cep_status"),
        # coerência: localizada <=> tem coordenadas
        CheckConstraint(
            "(status = 'localizada' AND latitude IS NOT NULL AND longitude IS NOT NULL) "
            "OR (status <> 'localizada' AND latitude IS NULL AND longitude IS NULL)",
            name="ck_geo_status_coordenadas",
        ),
    )
