from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class LeadResumo(BaseModel):
    id: int
    cnpj: Optional[str] = None  # Leads OpenStreetMap não têm CNPJ confiável.
    nome: str
    nicho_id: int
    nicho_slug: str
    nicho_nome: str
    municipio: Optional[str] = None
    uf: Optional[str] = None
    fonte: Optional[str] = None  # origem do registro: openstreetmap, manual_operador...; None = pipeline Receita/Apify legado
    consulta_busca: str  # texto do botão "Buscar" (Google): "nome" endereço, ou nicho quando não há endereço
    score: Optional[float] = None  # None = "Sem score" (nunca 0)
    faixa_score: str
    estagio: str
    estagio_derivado: bool  # True = sem histórico em funil_status; estágio inferido na leitura
    coluna: str
    funil_id: Optional[int] = None  # id do histórico vigente (usado no controle de concorrência)
    email_confirmado: bool
    formulario_confirmado: bool
    whatsapp_apto: bool  # formato de celular; NÃO é WhatsApp verificado
    telefone: Optional[str] = None
    site_url: Optional[str] = None
    site_ddg_status: str
    motivo_reprovacao: Optional[str] = None
    email_status: str
    qtd_emails_enviados: int
    email_enviado_em: Optional[datetime] = None
    tem_localizacao: bool = False
    precisao_geo: Optional[str] = None  # "municipio" = sede do município (não é o endereço) | "cep" = ponto aproximado do CEP


class Localizacao(BaseModel):
    latitude: float
    longitude: float
    precisao: str
    fonte: str


class LeadDetalhe(LeadResumo):
    razao_social: Optional[str] = None
    nome_fantasia: Optional[str] = None
    logradouro: Optional[str] = None
    numero: Optional[str] = None
    complemento: Optional[str] = None
    bairro: Optional[str] = None
    cep: Optional[str] = None
    telefone1: Optional[str] = None
    telefone2: Optional[str] = None
    porte: Optional[str] = None
    natureza_juridica: Optional[str] = None
    cnae_principal: Optional[str] = None
    data_inicio_atividade: Optional[str] = None
    criado_em: Optional[datetime] = None
    email_final: Optional[str] = None
    formulario_contato_url: Optional[str] = None
    site_ativo: Optional[bool] = None
    places_verificado: Optional[bool] = None
    places_telefone_confirmado: Optional[bool] = None
    places_endereco_confirmado: Optional[bool] = None
    tem_pelo_menos_um_canal: Optional[bool] = None
    score_em: Optional[datetime] = None
    modelo_usado: Optional[str] = None
    prompt_versao: Optional[str] = None
    dores_identificadas: Optional[str] = None
    justificativa: Optional[str] = None
    localizacao: Optional[Localizacao] = None


class ScoreItem(BaseModel):
    id: int
    score: float
    faixa_score: str
    modelo_usado: str
    prompt_versao: str
    dores_identificadas: Optional[str] = None
    justificativa: Optional[str] = None
    criado_em: Optional[datetime] = None


class ContatoItem(BaseModel):
    id: int
    canal: str
    destino: str
    assunto: Optional[str] = None
    corpo: Optional[str] = None
    status: str  # normalizado: enviado | pendente | falhou
    status_envio: str  # valor bruto do banco
    sucesso_envio: Optional[bool] = None
    erro: Optional[str] = None
    gerado_em: Optional[datetime] = None  # ContatoEnviado.enviado_em = geração (etapa4), não envio
    enviado_em: Optional[datetime] = None  # ContatoEnviado.data_envio = envio real (etapa5)


class FunilItem(BaseModel):
    id: int
    estagio: str
    coluna: str
    observacao: Optional[str] = None
    criado_em: Optional[datetime] = None


class WhatsAppLink(BaseModel):
    apto: bool
    verificado: bool
    telefone_original: Optional[str] = None
    telefone_normalizado: Optional[str] = None
    tipo_telefone: str
    nono_digito_acrescentado: bool
    motivo_inapto: Optional[str] = None
    mensagem: Optional[str] = None
    link: Optional[str] = None


class TransicaoEntrada(BaseModel):
    estagio_destino: str
    # Obrigatório mas anulável: null = "o lead não tinha histórico quando carreguei".
    id_historico_esperado: Optional[int]
    observacao: Optional[str] = None


class TransicaoResposta(BaseModel):
    funil_id: int
    lead: LeadResumo
