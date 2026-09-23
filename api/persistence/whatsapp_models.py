"""Tabelas aditivas da Etapa 7 (WhatsApp automatizado). Não alteram nenhuma tabela existente.

Contrato entre processos:
- API FastAPI: autorizações, política comercial, comandos (conectar, pausar), leitura da caixa de entrada.
- Worker Python (etapa7_whatsapp): ingere eventos brutos, decide escopo, chama DeepSeek, grava outbox.
- Gateway Node (services/whatsapp-gateway): sessão Baileys, grava eventos BRUTOS de entrada/recibos e consome a outbox.
"""

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text,
    UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB

from db.models import Base

ESTADOS_CONEXAO = (
    "desconectado", "aguardando_qr", "conectando", "conectado", "reconectando", "requer_pareamento", "pausado_por_erro",
)
CONTROLES = ("automatizada", "humano", "pausada", "encerrada", "fora_escopo")
ESTAGIOS_COMERCIAIS = ("abordagem", "qualificacao", "proposta", "negociacao", "aceita", "perdida")
ESTADOS_OUTBOX = (
    "aguardando_envio", "envio_em_andamento", "aceita", "entregue", "lida", "falhou", "incerto", "cancelado",
)


def _agora():
    return DateTime(timezone=True)


class WhatsappConta(Base):
    __tablename__ = "whatsapp_accounts"

    id = Column(Integer, primary_key=True)
    numero = Column(String(20))
    estado = Column(String(30), nullable=False, server_default="desconectado")
    comando_pendente = Column(String(20))  # conectar | desconectar (API -> gateway)
    qr_atual = Column(Text)  # transitório: sobrescrito e apagado ao conectar; nunca logado
    automacao_habilitada = Column(Boolean, nullable=False, server_default=text("false"))
    motivo_pausa = Column(Text)
    kill_geracao = Column(Integer, nullable=False, server_default="0")
    heartbeat_em = Column(_agora())
    gateway_lease_id = Column(String(64))
    gateway_lease_ate = Column(_agora())
    timezone = Column(String(60), nullable=False, server_default="America/Sao_Paulo")
    limites = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    erros_consecutivos = Column(Integer, nullable=False, server_default="0")
    criado_em = Column(_agora(), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "estado IN ('" + "','".join(ESTADOS_CONEXAO) + "')", name="ck_wa_conta_estado"
        ),
    )


class WhatsappAuthState(Base):
    __tablename__ = "whatsapp_auth_state"

    conta_id = Column(Integer, ForeignKey("whatsapp_accounts.id", ondelete="CASCADE"), primary_key=True)
    tipo = Column(String(60), primary_key=True)
    item_id = Column(String(255), primary_key=True)
    conteudo = Column(LargeBinary, nullable=False)  # AES-256-GCM; chave fora do banco
    versao = Column(Integer, nullable=False, server_default="1")
    atualizado_em = Column(_agora(), server_default=func.now(), nullable=False)


class WhatsappContato(Base):
    __tablename__ = "whatsapp_contacts"

    id = Column(Integer, primary_key=True)
    telefone_e164 = Column(String(20))
    nome_exibido = Column(String(255))
    identidade_resolvida = Column(Boolean, nullable=False, server_default=text("false"))
    criado_em = Column(_agora(), server_default=func.now(), nullable=False)


class WhatsappContatoIdentificador(Base):
    __tablename__ = "whatsapp_contact_identifiers"

    id = Column(Integer, primary_key=True)
    conta_id = Column(Integer, ForeignKey("whatsapp_accounts.id", ondelete="CASCADE"), nullable=False)
    contato_id = Column(Integer, ForeignKey("whatsapp_contacts.id", ondelete="CASCADE"), nullable=False)
    tipo = Column(String(10), nullable=False)  # telefone | jid | lid
    identificador = Column(String(255), nullable=False)
    origem = Column(String(40), nullable=False)
    criado_em = Column(_agora(), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("conta_id", "tipo", "identificador", name="uq_wa_identificador"),
        CheckConstraint("tipo IN ('telefone','jid','lid')", name="ck_wa_identificador_tipo"),
    )


class WhatsappAutorizacao(Base):
    __tablename__ = "whatsapp_authorizations"

    id = Column(Integer, primary_key=True)
    conta_id = Column(Integer, ForeignKey("whatsapp_accounts.id"), nullable=False)
    contato_id = Column(Integer, ForeignKey("whatsapp_contacts.id"), nullable=False)
    empresa_id = Column(Integer, ForeignKey("empresas.id"))
    autorizado_por = Column(String(120), nullable=False)
    telefone_exato = Column(String(20), nullable=False)
    status = Column(String(12), nullable=False, server_default="ativa")
    versao = Column(Integer, nullable=False, server_default="1")
    politica_versao = Column(Integer, nullable=False)
    expira_em = Column(_agora())
    revogado_em = Column(_agora())
    motivo_revogacao = Column(Text)
    criado_em = Column(_agora(), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('ativa','revogada','expirada')", name="ck_wa_autorizacao_status"),
        Index("uq_wa_autorizacao_ativa", "conta_id", "contato_id", unique=True, postgresql_where=text("status = 'ativa'")),
    )


class WhatsappSupressao(Base):
    __tablename__ = "whatsapp_suppressions"

    id = Column(Integer, primary_key=True)
    conta_id = Column(Integer, ForeignKey("whatsapp_accounts.id"), nullable=False)
    contato_id = Column(Integer, ForeignKey("whatsapp_contacts.id"), nullable=False)
    motivo = Column(String(30), nullable=False)  # descadastro | numero_errado | bloqueio_manual
    origem = Column(String(60), nullable=False)
    criado_em = Column(_agora(), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("conta_id", "contato_id", name="uq_wa_supressao"),)


class WhatsappConversa(Base):
    __tablename__ = "whatsapp_conversations"

    id = Column(Integer, primary_key=True)
    conta_id = Column(Integer, ForeignKey("whatsapp_accounts.id"), nullable=False)
    contato_id = Column(Integer, ForeignKey("whatsapp_contacts.id"), nullable=False)
    empresa_id = Column(Integer, ForeignKey("empresas.id"))
    autorizacao_id = Column(Integer, ForeignKey("whatsapp_authorizations.id"))
    controle = Column(String(20), nullable=False, server_default="fora_escopo")
    estagio = Column(String(20), nullable=False, server_default="abordagem")
    motivo_escalada = Column(Text)
    ultima_recebida_em = Column(_agora())
    ultima_enviada_em = Column(_agora())
    versao = Column(Integer, nullable=False, server_default="1")
    resumo = Column(Text)
    resumo_ate_msg_id = Column(Integer)
    estado_comercial = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    criado_em = Column(_agora(), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("conta_id", "contato_id", name="uq_wa_conversa_contato"),
        CheckConstraint("controle IN ('" + "','".join(CONTROLES) + "')", name="ck_wa_conversa_controle"),
        CheckConstraint("estagio IN ('" + "','".join(ESTAGIOS_COMERCIAIS) + "')", name="ck_wa_conversa_estagio"),
    )


class WhatsappMensagem(Base):
    __tablename__ = "whatsapp_messages"

    id = Column(Integer, primary_key=True)
    conta_id = Column(Integer, ForeignKey("whatsapp_accounts.id"), nullable=False)
    conversa_id = Column(Integer, ForeignKey("whatsapp_conversations.id"), nullable=False)
    contato_id = Column(Integer, ForeignKey("whatsapp_contacts.id"), nullable=False)
    direcao = Column(String(8), nullable=False)  # entrada | saida
    autoria = Column(String(10), nullable=False)  # cliente | ia | operador
    tipo = Column(String(20), nullable=False, server_default="texto")
    texto = Column(Text)
    provider_msg_id = Column(String(120))
    provider_from_me = Column(Boolean, nullable=False, server_default=text("false"))
    provider_jid = Column(String(255))
    respondida_id = Column(Integer, ForeignKey("whatsapp_messages.id"))
    ts_provedor = Column(_agora())
    recebida_em = Column(_agora(), server_default=func.now(), nullable=False)
    estado_transporte = Column(String(20), nullable=False, server_default="entregue")
    origem = Column(String(20), nullable=False, server_default="tempo_real")  # tempo_real | historico | dispositivo_proprio | sistema | sugestao | manual_registrado
    outbox_id = Column(Integer)
    # Modo copiloto. Sugestão: {"sugestao": {"primeiro_contato", "transicao", "pergunta", "acao", "proposta_id"}}.
    # Confirmada como enviada: {"manual": {"editada": bool, "texto_sugerido": str|None}}.
    meta = Column(JSONB)

    __table_args__ = (
        Index(
            "uq_wa_mensagem_provider", "conta_id", "provider_msg_id", "provider_from_me",
            unique=True, postgresql_where=text("provider_msg_id IS NOT NULL"),
        ),
        CheckConstraint("direcao IN ('entrada','saida')", name="ck_wa_msg_direcao"),
        CheckConstraint("autoria IN ('cliente','ia','operador')", name="ck_wa_msg_autoria"),
    )


class WhatsappMensagemEvento(Base):
    __tablename__ = "whatsapp_message_events"

    id = Column(Integer, primary_key=True)
    mensagem_id = Column(Integer, ForeignKey("whatsapp_messages.id", ondelete="CASCADE"), nullable=False)
    evento = Column(String(20), nullable=False)
    ocorrido_em = Column(_agora(), server_default=func.now(), nullable=False)
    metadados = Column(JSONB)


class WhatsappEventoEntrada(Base):
    """Evento BRUTO gravado pelo gateway (transporte). O worker Python interpreta: escopo, contato, conversa."""

    __tablename__ = "whatsapp_inbound_events"

    id = Column(BigInteger, primary_key=True)
    conta_id = Column(Integer, ForeignKey("whatsapp_accounts.id"), nullable=False)
    tipo = Column(String(12), nullable=False)  # mensagem | recibo
    provider_msg_id = Column(String(120))
    from_me = Column(Boolean, nullable=False, server_default=text("false"))
    jid = Column(String(255))
    jid_alt = Column(String(255))  # par PN/LID quando o Baileys informa
    push_name = Column(String(255))
    tipo_msg = Column(String(20))
    texto = Column(Text)
    origem = Column(String(20), nullable=False, server_default="tempo_real")  # tempo_real | historico | dispositivo_proprio
    ts_provedor = Column(_agora())
    dados = Column(JSONB)
    processado = Column(Boolean, nullable=False, server_default=text("false"))
    criado_em = Column(_agora(), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index(
            "uq_wa_evento_msg", "conta_id", "provider_msg_id", "from_me", "tipo",
            unique=True, postgresql_where=text("tipo = 'mensagem' AND provider_msg_id IS NOT NULL"),
        ),
        Index("ix_wa_evento_pendente", "processado", "id"),
    )


class WhatsappJob(Base):
    __tablename__ = "whatsapp_jobs"

    id = Column(Integer, primary_key=True)
    tipo = Column(String(20), nullable=False)  # primeiro_contato | processar_entrada
    conta_id = Column(Integer, ForeignKey("whatsapp_accounts.id"), nullable=False)
    conversa_id = Column(Integer, ForeignKey("whatsapp_conversations.id"), nullable=False)
    chave_idempotencia = Column(String(120), nullable=False, unique=True)
    status = Column(String(15), nullable=False, server_default="pendente")
    tentativas = Column(Integer, nullable=False, server_default="0")
    proxima_execucao_em = Column(_agora(), server_default=func.now(), nullable=False)
    primeira_entrada_em = Column(_agora())
    lease_ate = Column(_agora())
    erro = Column(Text)
    criado_em = Column(_agora(), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('pendente','em_execucao','concluido','falhou','cancelado')", name="ck_wa_job_status"),
        Index("ix_wa_job_pronto", "status", "proxima_execucao_em"),
    )


class WhatsappOutbox(Base):
    __tablename__ = "whatsapp_outbox"

    id = Column(Integer, primary_key=True)
    conta_id = Column(Integer, ForeignKey("whatsapp_accounts.id"), nullable=False)
    conversa_id = Column(Integer, ForeignKey("whatsapp_conversations.id"), nullable=False)
    contato_id = Column(Integer, ForeignKey("whatsapp_contacts.id"), nullable=False)
    autoria = Column(String(10), nullable=False)  # ia | operador
    texto = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, server_default="aguardando_envio")
    primeiro_contato = Column(Boolean, nullable=False, server_default=text("false"))
    # Mensagem de encerramento/escalada: sai mesmo depois de a conversa passar ao humano (nunca sem autorização).
    mensagem_de_transicao = Column(Boolean, nullable=False, server_default=text("false"))
    versao_autorizacao = Column(Integer)
    versao_politica = Column(Integer)
    versao_conversa = Column(Integer)
    kill_geracao = Column(Integer, nullable=False, server_default="0")
    agendado_para = Column(_agora(), server_default=func.now(), nullable=False)
    tentativas = Column(Integer, nullable=False, server_default="0")
    lease_ate = Column(_agora())
    provider_msg_id = Column(String(120))
    mensagem_id = Column(Integer)
    erro = Column(Text)
    criado_em = Column(_agora(), server_default=func.now(), nullable=False)
    enviado_em = Column(_agora())

    __table_args__ = (
        CheckConstraint("status IN ('" + "','".join(ESTADOS_OUTBOX) + "')", name="ck_wa_outbox_status"),
        Index("ix_wa_outbox_pronta", "status", "agendado_para"),
    )


class WhatsappAiRun(Base):
    __tablename__ = "whatsapp_ai_runs"

    id = Column(Integer, primary_key=True)
    conversa_id = Column(Integer, ForeignKey("whatsapp_conversations.id"), nullable=False)
    job_id = Column(Integer, ForeignKey("whatsapp_jobs.id"))
    modelo = Column(String(60))
    prompt_versao = Column(String(30))
    politica_versao = Column(Integer)
    tokens_entrada = Column(Integer)
    tokens_saida = Column(Integer)
    latencia_ms = Column(Integer)
    decisao = Column(JSONB)
    validacao = Column(String(12))  # ok | rejeitada | erro
    erro = Column(Text)
    criado_em = Column(_agora(), server_default=func.now(), nullable=False)


class PoliticaComercial(Base):
    __tablename__ = "commercial_policies"

    id = Column(Integer, primary_key=True)
    versao = Column(Integer, nullable=False, unique=True)
    ativa = Column(Boolean, nullable=False, server_default=text("false"))
    config = Column(JSONB, nullable=False)
    criado_por = Column(String(120), nullable=False)
    criado_em = Column(_agora(), server_default=func.now(), nullable=False)

    __table_args__ = (Index("uq_commercial_policy_ativa", "ativa", unique=True, postgresql_where=text("ativa")),)


class PropostaComercial(Base):
    __tablename__ = "commercial_proposals"

    id = Column(Integer, primary_key=True)
    conversa_id = Column(Integer, ForeignKey("whatsapp_conversations.id"), nullable=False)
    politica_versao = Column(Integer, nullable=False)
    pacote = Column(String(10), nullable=False)  # sdr | site
    itens = Column(JSONB, nullable=False)
    setup_centavos = Column(Integer, nullable=False)
    mensalidade_centavos = Column(Integer, nullable=False, server_default="0")
    desconto_pct = Column(Integer, nullable=False, server_default="0")  # em pontos-base (5% = 500)
    status = Column(String(12), nullable=False, server_default="enviada")  # enviada | aceita | substituida
    criado_em = Column(_agora(), server_default=func.now(), nullable=False)


class AceiteComercial(Base):
    """Aceite da PROPOSTA exata. Aceite NÃO é pagamento: não existe aqui campo de pagamento confirmado."""

    __tablename__ = "commercial_acceptances"

    id = Column(Integer, primary_key=True)
    proposta_id = Column(Integer, ForeignKey("commercial_proposals.id"), nullable=False, unique=True)
    mensagem_id = Column(Integer, ForeignKey("whatsapp_messages.id"))
    tratado_em = Column(_agora())  # o operador marca quando já entrou em contato para os próximos passos (some do contador)
    criado_em = Column(_agora(), server_default=func.now(), nullable=False)


class DemandaComercial(Base):
    """Terceira via: necessidade real sem pacote no catálogo. Insumo para o operador decidir novos serviços."""

    __tablename__ = "commercial_demands"

    id = Column(Integer, primary_key=True)
    conversa_id = Column(Integer, ForeignKey("whatsapp_conversations.id"), nullable=False)
    descricao = Column(Text, nullable=False)
    revisada = Column(Boolean, nullable=False, server_default=text("false"))
    criado_em = Column(_agora(), server_default=func.now(), nullable=False)


class WhatsappAuditoria(Base):
    __tablename__ = "whatsapp_audit_events"

    id = Column(Integer, primary_key=True)
    conta_id = Column(Integer, ForeignKey("whatsapp_accounts.id"))
    ator = Column(String(60), nullable=False)  # operador | worker | gateway | sistema
    acao = Column(String(60), nullable=False)
    alvo_tipo = Column(String(30))
    alvo_id = Column(Integer)
    detalhes = Column(JSONB)
    criado_em = Column(_agora(), server_default=func.now(), nullable=False)


class WhatsappNotificacaoOperador(Base):
    """Aviso INTERNO ao operador (ex.: aceite registrado). Não passa por autorização de lead, política nem limites de leads:
    fluxo à parte, com template fixo (sem IA). O número de destino vem SÓ do ambiente do gateway
    (WHATSAPP_NOTIFICACAO_OPERADOR); nunca é gravado no banco nem aceito pela API."""

    __tablename__ = "whatsapp_operator_notifications"

    id = Column(Integer, primary_key=True)
    conta_id = Column(Integer, ForeignKey("whatsapp_accounts.id", ondelete="CASCADE"), nullable=False)
    tipo = Column(String(20), nullable=False, server_default="aceite")
    aceite_id = Column(Integer, ForeignKey("commercial_acceptances.id", ondelete="SET NULL"), unique=True)
    conversa_id = Column(Integer, ForeignKey("whatsapp_conversations.id", ondelete="SET NULL"))
    texto = Column(Text, nullable=False)
    status = Column(String(12), nullable=False, server_default="pendente")
    tentativas = Column(Integer, nullable=False, server_default="0")
    proximo_envio_em = Column(_agora(), server_default=func.now(), nullable=False)
    provider_msg_id = Column(String(120))
    erro = Column(Text)
    criado_em = Column(_agora(), server_default=func.now(), nullable=False)
    enviado_em = Column(_agora())

    __table_args__ = (
        CheckConstraint("status IN ('pendente','enviando','enviada','falhou')", name="ck_wa_notif_status"),
        Index("ix_wa_notif_pendente", "status", "proximo_envio_em"),
    )


class EmpresaTelefoneManual(Base):
    """Telefone que o operador digitou à mão para uma empresa. Guarda a ORIGEM do número (não vem da Receita nem do OSM);
    o telefone em si fica em empresas.telefone1/telefone2, como qualquer outro."""

    __tablename__ = "empresa_telefones_manuais"

    id = Column(Integer, primary_key=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False)
    telefone = Column(String(20), nullable=False)  # dígitos nacionais, igual a empresas.telefoneN
    campo = Column(String(10), nullable=False)  # telefone1 | telefone2
    origem = Column(String(30), nullable=False, server_default="manual_operador")
    usuario = Column(String(120), nullable=False)
    criado_em = Column(_agora(), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("empresa_id", "telefone", name="uq_empresa_telefone_manual"),
        CheckConstraint("campo IN ('telefone1','telefone2')", name="ck_empresa_telefone_manual_campo"),
    )
