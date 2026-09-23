"""Verificações que valem ANTES de gerar, ao gravar na outbox e imediatamente antes de enviar.

O gateway Node repete o subconjunto de segurança (autorização, supressão, pausa, versões) em SQL;
esta é a versão de referência, testada. Um envio só acontece se TODAS as checagens passarem no
instante do envio: uma resposta gerada antes de uma revogação/pausa nunca sai depois dela.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.persistence.whatsapp_models import (
    WhatsappAutorizacao, WhatsappConta, WhatsappConversa, WhatsappOutbox, WhatsappSupressao,
)
from etapa7_whatsapp.horario import dentro_da_janela, proximo_inicio
from etapa7_whatsapp.politica import politica_ativa

ENVIADOS = ("envio_em_andamento", "aceita", "entregue", "lida")


@dataclass
class Veredito:
    acao: str  # enviar | cancelar | adiar
    motivo: str | None = None
    ate: datetime | None = None
    pausar_conversa: bool = False

    @property
    def ok(self) -> bool:
        return self.acao == "enviar"


def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def autorizacao_ativa(session: Session, conta_id: int, contato_id: int, agora: datetime) -> WhatsappAutorizacao | None:
    aut = session.execute(
        select(WhatsappAutorizacao).where(
            WhatsappAutorizacao.conta_id == conta_id,
            WhatsappAutorizacao.contato_id == contato_id,
            WhatsappAutorizacao.status == "ativa",
        )
    ).scalar_one_or_none()
    if aut is None:
        return None
    if aut.expira_em is not None and aut.expira_em <= agora:
        aut.status = "expirada"
        session.flush()
        return None
    return aut


def suprimido(session: Session, conta_id: int, contato_id: int) -> bool:
    return session.execute(
        select(WhatsappSupressao.id).where(WhatsappSupressao.conta_id == conta_id, WhatsappSupressao.contato_id == contato_id)
    ).first() is not None


def avaliar_outbox(session: Session, outbox: WhatsappOutbox, agora: datetime | None = None) -> Veredito:
    agora = agora or agora_utc()
    conta = session.get(WhatsappConta, outbox.conta_id)
    conversa = session.get(WhatsappConversa, outbox.conversa_id)
    if conta is None or conversa is None:
        return Veredito("cancelar", "conta_ou_conversa_inexistente")
    ia = outbox.autoria == "ia"

    if suprimido(session, conta.id, outbox.contato_id):
        return Veredito("cancelar", "contato_suprimido")
    aut = autorizacao_ativa(session, conta.id, outbox.contato_id, agora)
    if aut is None:
        return Veredito("cancelar", "sem_autorizacao_ativa")
    if ia:
        if not conta.automacao_habilitada:
            return Veredito("cancelar", "automacao_pausada")
        if outbox.kill_geracao != conta.kill_geracao:
            return Veredito("cancelar", "kill_switch_acionado")
        if outbox.versao_autorizacao != aut.versao:
            return Veredito("cancelar", "autorizacao_mudou")
        if not outbox.mensagem_de_transicao:
            if conversa.controle != "automatizada":
                return Veredito("cancelar", f"controle_{conversa.controle}")
            if outbox.versao_conversa != conversa.versao:
                return Veredito("cancelar", "conversa_mudou")
        pol = politica_ativa(session)
        if outbox.versao_politica != pol.versao:
            return Veredito("cancelar", "politica_mudou")
        lim = pol.config["limites"]
        if not dentro_da_janela(agora, conta.timezone, lim):
            return Veredito("adiar", "fora_do_horario", proximo_inicio(agora, conta.timezone, lim))
    else:
        lim = politica_ativa(session).config["limites"]

    # Limites de saída da conta (valem para IA e operador: protegem o número).
    ultimo_min = session.execute(
        select(func.count()).select_from(WhatsappOutbox).where(
            WhatsappOutbox.conta_id == conta.id, WhatsappOutbox.status.in_(ENVIADOS),
            WhatsappOutbox.enviado_em > agora - timedelta(seconds=60),
        )
    ).scalar_one()
    if ultimo_min >= lim["saidas_por_minuto"]:
        return Veredito("adiar", "limite_saidas_por_minuto", agora + timedelta(seconds=15))

    if ia and not outbox.primeiro_contato:
        na_hora = session.execute(
            select(func.count()).select_from(WhatsappOutbox).where(
                WhatsappOutbox.conversa_id == conversa.id, WhatsappOutbox.autoria == "ia",
                WhatsappOutbox.status.in_(ENVIADOS), WhatsappOutbox.enviado_em > agora - timedelta(hours=1),
            )
        ).scalar_one()
        if na_hora >= lim["respostas_por_conversa_hora"]:
            return Veredito("cancelar", "limite_respostas_hora", pausar_conversa=True)

    if ia and outbox.primeiro_contato:
        zona = ZoneInfo(conta.timezone)
        inicio_dia = agora.astimezone(zona).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        hoje = session.execute(
            select(func.count()).select_from(WhatsappOutbox).where(
                WhatsappOutbox.conta_id == conta.id, WhatsappOutbox.primeiro_contato.is_(True),
                WhatsappOutbox.status.in_(ENVIADOS), WhatsappOutbox.enviado_em >= inicio_dia,
            )
        ).scalar_one()
        if hoje >= lim["novos_contatos_dia"]:
            amanha = (inicio_dia.astimezone(zona) + timedelta(days=1)).astimezone(timezone.utc)
            return Veredito("adiar", "limite_novos_contatos_dia", proximo_inicio(amanha, conta.timezone, lim))
        ultimo = session.execute(
            select(func.max(WhatsappOutbox.enviado_em)).where(
                WhatsappOutbox.conta_id == conta.id, WhatsappOutbox.primeiro_contato.is_(True), WhatsappOutbox.status.in_(ENVIADOS)
            )
        ).scalar_one()
        if ultimo is not None and agora < ultimo + timedelta(seconds=lim["intervalo_primeiros_contatos_seg"]):
            return Veredito("adiar", "intervalo_entre_primeiros_contatos", ultimo + timedelta(seconds=lim["intervalo_primeiros_contatos_seg"]))
    return Veredito("enviar")
