"""Registros aditivos da prospecção web.

As tabelas aqui não substituem `validacoes`: preservam toda a evidência
legada e registram separadamente a descoberta feita via DuckDuckGo.
"""

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import relationship

from db.models import Base


class LoteProspeccao(Base):
    __tablename__ = "lotes_prospeccao"

    id = Column(Integer, primary_key=True)
    nicho_id = Column(Integer, ForeignKey("nichos.id"), nullable=False)
    uf = Column(String(2), nullable=False)
    fonte = Column(String(20), nullable=False, server_default="apify")
    cidade = Column(String(120))
    raio_km = Column(Integer)
    limite = Column(Integer, nullable=False)
    total_encontrado = Column(Integer, nullable=False, server_default="0")
    total_duplicado = Column(Integer, nullable=False, server_default="0")
    status = Column(String(20), nullable=False, server_default="pendente")
    erro = Column(Text)
    criado_em = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    iniciado_em = Column(DateTime(timezone=True))
    concluido_em = Column(DateTime(timezone=True))

    empresas = relationship("LoteProspeccaoEmpresa", back_populates="lote", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("limite BETWEEN 1 AND 500", name="ck_lote_prospeccao_limite"),
        CheckConstraint("status IN ('pendente', 'executando', 'concluido', 'falhou')", name="ck_lote_prospeccao_status"),
        CheckConstraint("fonte IN ('apify', 'osm', 'google_places')", name="ck_lote_prospeccao_fonte"),
    )


class LoteProspeccaoEmpresa(Base):
    __tablename__ = "lotes_prospeccao_empresas"

    lote_id = Column(Integer, ForeignKey("lotes_prospeccao.id", ondelete="CASCADE"), primary_key=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id", ondelete="CASCADE"), primary_key=True)
    criado_em = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    lote = relationship("LoteProspeccao", back_populates="empresas")


class ValidacaoSiteDdg(Base):
    __tablename__ = "validacoes_site_ddg"

    id = Column(Integer, primary_key=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False)
    lote_id = Column(Integer, ForeignKey("lotes_prospeccao.id", ondelete="CASCADE"), nullable=False)
    consulta = Column(Text, nullable=False)
    resultado = Column(String(20), nullable=False)
    dominio_candidato = Column(String(255))
    site_url = Column(String(500))
    posicao_resultado = Column(Integer)
    confianca = Column(String(20))
    site_ativo = Column(Boolean)
    email_final = Column(String(255))
    formulario_contato_url = Column(String(500))
    resultados_resumo = Column(Text)
    erro = Column(Text)
    consultado_em = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("empresa_id", name="uq_validacao_site_ddg_empresa"),
        CheckConstraint("resultado IN ('site_osm', 'encontrado', 'sem_site', 'ambiguo', 'erro', 'rate_limit')", name="ck_ddg_resultado"),
        CheckConstraint("confianca IS NULL OR confianca IN ('alta', 'media', 'baixa')", name="ck_ddg_confianca"),
    )
