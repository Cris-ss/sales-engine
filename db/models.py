"""Modelos SQLAlchemy (Postgres) do sales-engine.

Fluxo de dados: Nicho -> Empresa (1 CNPJ) -> Validacao (1:1, canal de
contato) -> LeadScore (N, versionado) -> ContatoEnviado (N, um por canal
tentado) -> Resposta (N) -> FunilStatus (N, histórico append-only).
"""

import enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    func,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()


class CanalContato(str, enum.Enum):
    EMAIL = "email"
    FORMULARIO_SITE = "formulario_site"


class EstagioFunil(str, enum.Enum):
    ENCONTRADA = "encontrada"
    QUALIFICADA = "qualificada"
    CONTATADA = "contatada"
    RESPONDEU = "respondeu"
    EM_NEGOCIACAO = "em_negociacao"
    PROPOSTA = "proposta"
    VENDA = "venda"
    PERDIDA = "perdida"


class Nicho(Base):
    __tablename__ = "nichos"

    id = Column(Integer, primary_key=True)
    slug = Column(String(50), unique=True, nullable=False)
    nome = Column(String(120), nullable=False)
    cnae = Column(String(10), nullable=False)

    contexto_dores = Column(Text)
    argumentos_venda = Column(Text)
    tom_abordagem = Column(Text)

    criado_em = Column(DateTime(timezone=True), server_default=func.now())

    empresas = relationship("Empresa", back_populates="nicho")


class Empresa(Base):
    __tablename__ = "empresas"

    id = Column(Integer, primary_key=True)
    nicho_id = Column(Integer, ForeignKey("nichos.id"), nullable=False)

    # Leads OSM não têm CNPJ confiável. Registros Receita existentes permanecem
    # inalterados; Postgres permite múltiplos NULLs no índice único.
    cnpj = Column(String(14), unique=True, nullable=True, index=True)
    fonte = Column(String(30))  # receita_apify | openstreetmap
    fonte_externo_id = Column(String(80), unique=True)
    razao_social = Column(String(255))
    nome_fantasia = Column(String(255))
    situacao_cadastral = Column(String(30))
    data_situacao_cadastral = Column(String(10))
    data_inicio_atividade = Column(String(10))
    cnae_principal = Column(String(10))
    natureza_juridica_codigo = Column(String(10))
    natureza_juridica = Column(String(120))

    logradouro = Column(String(255))
    numero = Column(String(20))
    complemento = Column(String(120))
    bairro = Column(String(120))
    municipio = Column(String(120))
    uf = Column(String(2))
    cep = Column(String(9))

    telefone1 = Column(String(20))
    telefone2 = Column(String(20))
    # Quase sempre nulo (0% de preenchimento confirmado na fonte Receita
    # via Apify); mantido apenas por completude do schema.
    email_receita = Column(String(255))

    capital_social = Column(Float)
    porte = Column(String(30))
    # Observações do operador sobre o lead (ex.: achados de outra ferramenta). Só apoio para a IA; nunca fonte de preço/catálogo.
    contexto_manual = Column(Text)

    criado_em = Column(DateTime(timezone=True), server_default=func.now())

    nicho = relationship("Nicho", back_populates="empresas")
    validacao = relationship(
        "Validacao", back_populates="empresa", uselist=False, cascade="all, delete-orphan"
    )
    lead_scores = relationship("LeadScore", back_populates="empresa", cascade="all, delete-orphan")
    contatos_enviados = relationship(
        "ContatoEnviado", back_populates="empresa", cascade="all, delete-orphan"
    )
    respostas = relationship("Resposta", back_populates="empresa", cascade="all, delete-orphan")
    funil_status = relationship(
        "FunilStatus",
        back_populates="empresa",
        order_by="FunilStatus.criado_em",
        cascade="all, delete-orphan",
    )


class Validacao(Base):
    """Resultado da etapa de enriquecimento de contato (Places + scraping)."""

    __tablename__ = "validacoes"

    id = Column(Integer, primary_key=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), unique=True, nullable=False)

    place_id = Column(String(255))
    places_verificado = Column(Boolean, default=False)
    places_telefone_confirmado = Column(Boolean, default=False)
    places_endereco_confirmado = Column(Boolean, default=False)

    site_url = Column(String(500))
    site_ativo = Column(Boolean, default=False)

    email_final = Column(String(255))
    formulario_contato_url = Column(String(500))
    formulario_contato_disponivel = Column(Boolean, default=False)

    tem_pelo_menos_um_canal = Column(Boolean, default=False)
    passou_filtro = Column(Boolean, default=False)
    motivo_reprovacao = Column(String(255))

    atualizado_em = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    empresa = relationship("Empresa", back_populates="validacao")


class LeadScore(Base):
    """Score de fit da IA. Versionado: nunca sobrescreve, permite comparar modelos."""

    __tablename__ = "lead_scores"

    id = Column(Integer, primary_key=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), nullable=False)

    score = Column(Float, nullable=False)
    modelo_usado = Column(String(50), nullable=False)
    prompt_versao = Column(String(20), nullable=False)
    dores_identificadas = Column(Text)
    justificativa = Column(Text)

    criado_em = Column(DateTime(timezone=True), server_default=func.now())

    empresa = relationship("Empresa", back_populates="lead_scores")


class ContatoEnviado(Base):
    """Um lead pode ter múltiplas linhas aqui: uma por canal tentado
    (email e/ou formulário de contato do site), de forma independente."""

    __tablename__ = "contatos_enviados"

    id = Column(Integer, primary_key=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), nullable=False)

    canal = Column(SAEnum(CanalContato, name="canal_contato"), nullable=False)
    destino = Column(String(500), nullable=False)  # email ou URL do formulário
    assunto = Column(String(255))
    corpo = Column(Text)
    status_envio = Column(String(20), nullable=False, default="pendente")
    sucesso_envio = Column(Boolean, default=False)
    erro = Column(Text)

    # momento em que o registro foi gerado (etapa4), não quando foi enviado
    enviado_em = Column(DateTime(timezone=True), server_default=func.now())
    # momento do envio real de fato (etapa5); nulo enquanto status_envio="pendente"
    data_envio = Column(DateTime(timezone=True), nullable=True)

    empresa = relationship("Empresa", back_populates="contatos_enviados")
    resposta = relationship("Resposta", back_populates="contato_enviado", uselist=False)


class Resposta(Base):
    __tablename__ = "respostas"

    id = Column(Integer, primary_key=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), nullable=False)
    contato_enviado_id = Column(Integer, ForeignKey("contatos_enviados.id"))

    canal = Column(SAEnum(CanalContato, name="canal_resposta"), nullable=False)
    conteudo = Column(Text)
    sentimento = Column(String(30))

    recebido_em = Column(DateTime(timezone=True), server_default=func.now())

    empresa = relationship("Empresa", back_populates="respostas")
    contato_enviado = relationship("ContatoEnviado", back_populates="resposta")


class FunilStatus(Base):
    """Histórico de estágio do funil. Append-only: cada mudança gera uma
    nova linha, nunca sobrescreve as anteriores."""

    __tablename__ = "funil_status"

    id = Column(Integer, primary_key=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), nullable=False)

    estagio = Column(SAEnum(EstagioFunil, name="estagio_funil"), nullable=False)
    observacao = Column(Text)

    criado_em = Column(DateTime(timezone=True), server_default=func.now())

    empresa = relationship("Empresa", back_populates="funil_status")


def get_engine(database_url: str):
    return create_engine(database_url, future=True)


def get_session_factory(engine):
    return sessionmaker(bind=engine, future=True)


def init_db(database_url: str):
    """Cria o engine e todas as tabelas (idempotente: create_all só cria
    o que ainda não existe)."""
    engine = get_engine(database_url)
    Base.metadata.create_all(engine)
    return engine
