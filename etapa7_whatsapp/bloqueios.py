"""Por que uma conversa 'automatizada' ainda não enviou nada: explica, em linguagem clara, o que está segurando o trabalho pendente.

Só leitura. Não decide nada: o worker e o gateway continuam sendo a única fonte das regras (este módulo só as descreve).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.persistence.whatsapp_models import WhatsappConta, WhatsappConversa, WhatsappJob, WhatsappOutbox
from etapa7_whatsapp.guards import agora_utc
from etapa7_whatsapp.servico import estado_do_trabalho
from etapa7_whatsapp.horario import dentro_da_janela, proximo_inicio
from etapa7_whatsapp.politica import modo_envio, politica_ativa

_MOTIVOS_ADIAMENTO = {
    "fora_do_horario": "fora do horário permitido",
    "limite_saidas_por_minuto": "limite de saídas por minuto",
    "limite_novos_contatos_dia": "limite de novos contatos por dia",
    "intervalo_entre_primeiros_contatos": "intervalo mínimo entre primeiros contatos",
}


def _local(dt: datetime, tz: str) -> str:
    return dt.astimezone(ZoneInfo(tz)).strftime("%d/%m às %H:%M")


def bloqueios_da_conversa(session: Session, conversa: WhatsappConversa, agora: datetime | None = None) -> list[dict]:
    """Lista de {codigo, texto}. Vazia quando não há trabalho pendente ou nada o está segurando."""
    if conversa.controle != "automatizada":
        return []  # nos demais controles o próprio estado já explica (humano, pausada, fora do escopo...)
    agora = agora or agora_utc()
    job = session.execute(
        select(WhatsappJob.id).where(WhatsappJob.conversa_id == conversa.id, WhatsappJob.status.in_(("pendente", "em_execucao"))).limit(1)
    ).first()
    saidas = session.execute(
        select(WhatsappOutbox).where(WhatsappOutbox.conversa_id == conversa.id, WhatsappOutbox.status == "aguardando_envio")
    ).scalars().all()
    e = estado_do_trabalho(session, conversa)
    aviso_sugestao = [{"codigo": "sugestao_aguardando_envio", "nivel": "info", "texto":
                       "Há uma RESPOSTA SUGERIDA aguardando o seu envio manual (modo copiloto): copie, envie pelo WhatsApp e confirme aqui."}] if e["sugestao"] else []
    if not job and not saidas:
        if aviso_sugestao:
            return aviso_sugestao
        if e["cliente_sem_resposta"]:
            return [{"codigo": "sem_tarefa_cliente_sem_resposta", "nivel": "alerta", "texto":
                     "ATENÇÃO: há mensagem do cliente SEM resposta e nenhuma tarefa programada para responder: nada será enviado. "
                     "Clique em “Retomar IA” para recriar a tarefa."}]
        if not e["enviou_algo"]:
            return [{"codigo": "sem_tarefa_nada_enviado", "nivel": "alerta", "texto":
                     "ATENÇÃO: controle automatizado, mas não há nenhuma tarefa pendente ou programada e nada foi enviado: NADA será enviado. "
                     "Clique em “Retomar IA” para recriar o primeiro contato."}]
        return [{"codigo": "aguardando_cliente", "nivel": "info", "texto":
                 "Nenhuma tarefa pendente: a IA já enviou e está aguardando o cliente. Ela responde quando ele escrever."}]

    conta = session.get(WhatsappConta, conversa.conta_id)
    pol = politica_ativa(session)
    lim = pol.config["limites"]
    out: list[dict] = list(aviso_sugestao)
    automatico = modo_envio(pol.config) == "automatico"

    if not conta.automacao_habilitada:
        motivo = f" (motivo: {conta.motivo_pausa})" if conta.motivo_pausa else ""
        out.append({"codigo": "automacao_pausada", "nivel": "alerta", "texto":
                    f"Automação PAUSADA{motivo}: nada será gerado nem enviado até você clicar em “Retomar automação” (barra no topo da aba WhatsApp)."})
    if job and not pol.config.get("vendas_ativas"):
        out.append({"codigo": "vendas_desativadas", "nivel": "alerta", "texto":
                    "A conversa de venda automática está desativada na política: ao processar, esta conversa passa para atendimento humano, sem IA."})
    if automatico and not dentro_da_janela(agora, conta.timezone, lim):  # horário só limita ENVIO automático
        prox = proximo_inicio(agora, conta.timezone, lim)
        out.append({"codigo": "fora_do_horario", "nivel": "alerta", "texto":
                    f"Fora do horário permitido ({lim['hora_inicio']}–{lim['hora_fim']}): a IA só gera e envia a partir de {_local(prox, conta.timezone)}."})
    if saidas:
        conectado = conta.estado == "conectado" and conta.heartbeat_em is not None and agora - conta.heartbeat_em < timedelta(seconds=30)
        if not conectado:
            out.append({"codigo": "gateway_indisponivel", "nivel": "alerta", "texto":
                        f"Há mensagem pronta, mas o gateway não está conectado (estado: {conta.estado}): ela sai assim que a conexão voltar."})
        for s in saidas:
            if s.erro in _MOTIVOS_ADIAMENTO and s.agendado_para and s.agendado_para > agora:
                out.append({"codigo": s.erro, "nivel": "alerta", "texto":
                            f"Envio adiado ({_MOTIVOS_ADIAMENTO[s.erro]}): previsto para {_local(s.agendado_para, conta.timezone)}."})
                break
    return out
