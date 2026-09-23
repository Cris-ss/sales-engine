"""Operações da Etapa 7 compartilhadas por API e worker: autorização, revogação, supressão, kill switch,
envio manual e ingestão dos eventos brutos gravados pelo gateway.

Regras invariantes:
- Autorização é sempre por CONTATO/NÚMERO exato, nunca herdada da empresa.
- Uma mensagem recebida nunca autoriza nada.
- Supressão prevalece sobre autorização.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from api.persistence.whatsapp_models import (
    WhatsappAuditoria, WhatsappAutorizacao, WhatsappConta, WhatsappContato, WhatsappContatoIdentificador,
    WhatsappConversa, WhatsappEventoEntrada, WhatsappJob, WhatsappMensagem, WhatsappMensagemEvento, WhatsappOutbox,
    DemandaComercial, EmpresaTelefoneManual, WhatsappAiRun, WhatsappNotificacaoOperador, WhatsappSupressao,
)
from db.models import Empresa, Nicho
from api.persistence.whatsapp_models import PropostaComercial
from etapa7_whatsapp.guards import agora_utc, autorizacao_ativa, suprimido
from etapa7_whatsapp.politica import formatar_reais, modo_envio, politica_ativa


class ServicoErro(Exception):
    def __init__(self, codigo: str, mensagem: str, status: int = 422):
        super().__init__(mensagem)
        self.codigo, self.mensagem, self.status = codigo, mensagem, status


def auditar(session: Session, conta_id: int | None, ator: str, acao: str, alvo_tipo: str | None = None,
            alvo_id: int | None = None, detalhes: dict | None = None) -> None:
    session.add(WhatsappAuditoria(conta_id=conta_id, ator=ator, acao=acao, alvo_tipo=alvo_tipo, alvo_id=alvo_id, detalhes=detalhes))


def obter_conta(session: Session) -> WhatsappConta:
    conta = session.execute(select(WhatsappConta).order_by(WhatsappConta.id).limit(1)).scalar_one_or_none()
    if conta is None:
        session.execute(text("SELECT pg_advisory_xact_lock(70002)"))  # evita duas contas criadas por requisições simultâneas
        conta = session.execute(select(WhatsappConta).order_by(WhatsappConta.id).limit(1)).scalar_one_or_none()
        if conta is None:
            conta = WhatsappConta(estado="desconectado", automacao_habilitada=False)
            session.add(conta)
            session.flush()
    return conta


def normalizar_telefone_e164(texto: str | None) -> str | None:
    """Só normaliza formato (DDI 55). NÃO acrescenta nono dígito: identidade de destinatário
    automatizado vem do que o operador escolheu e do mapeamento que o WhatsApp devolve (onWhatsApp)."""
    digitos = "".join(c for c in (texto or "") if c.isdigit())
    if digitos.startswith("55") and len(digitos) in (12, 13):
        digitos = digitos[2:]
    if len(digitos) not in (10, 11):
        return None
    return "+55" + digitos


def _contato_por_telefone(session: Session, e164: str) -> WhatsappContato:
    contato = session.execute(select(WhatsappContato).where(WhatsappContato.telefone_e164 == e164)).scalars().first()
    if contato is None:
        contato = WhatsappContato(telefone_e164=e164, identidade_resolvida=False)
        session.add(contato)
        session.flush()
    return contato


def _cancelar_pendentes(session: Session, conta_id: int, conversa_id: int, motivo: str, so_ia: bool = False) -> None:
    filtros = [WhatsappOutbox.conversa_id == conversa_id, WhatsappOutbox.status == "aguardando_envio"]
    if so_ia:
        filtros.append(WhatsappOutbox.autoria == "ia")
    session.execute(update(WhatsappOutbox).where(*filtros).values(status="cancelado", erro=motivo))
    session.execute(
        update(WhatsappJob).where(
            WhatsappJob.conversa_id == conversa_id, WhatsappJob.status.in_(("pendente", "em_execucao"))
        ).values(status="cancelado", erro=motivo)
    )


def autorizar_lead(session: Session, empresa_id: int, telefone: str, usuario: str, agora: datetime | None = None):
    """Autoriza UM número e cria (de forma idempotente) a conversa e o job de primeiro contato."""
    agora = agora or agora_utc()
    empresa = session.get(Empresa, empresa_id)
    if empresa is None:
        raise ServicoErro("empresa_nao_encontrada", "Empresa inexistente.", 404)
    escolhido = normalizar_telefone_e164(telefone)
    candidatos = {normalizar_telefone_e164(empresa.telefone1), normalizar_telefone_e164(empresa.telefone2)} - {None}
    if escolhido is None or escolhido not in candidatos:
        raise ServicoErro("telefone_invalido", "O número precisa ser um dos telefones cadastrados desta empresa.")

    conta = obter_conta(session)
    contato = _contato_por_telefone(session, escolhido)
    if suprimido(session, conta.id, contato.id):
        raise ServicoErro("contato_suprimido", "Este número pediu para não ser contatado (supressão ativa).", 409)

    aut = autorizacao_ativa(session, conta.id, contato.id, agora)
    criada = aut is None
    pol = politica_ativa(session)
    if aut is None:
        aut = WhatsappAutorizacao(
            conta_id=conta.id, contato_id=contato.id, empresa_id=empresa.id, autorizado_por=usuario,
            telefone_exato=escolhido, status="ativa", versao=1, politica_versao=pol.versao,
            expira_em=agora + timedelta(days=pol.config["autorizacao_validade_dias"]),
        )
        session.add(aut)
        session.flush()

    conversa = session.execute(
        select(WhatsappConversa).where(WhatsappConversa.conta_id == conta.id, WhatsappConversa.contato_id == contato.id).with_for_update()
    ).scalar_one_or_none()
    if conversa is None:
        conversa = WhatsappConversa(conta_id=conta.id, contato_id=contato.id, empresa_id=empresa.id)
        session.add(conversa)
    if criada:
        conversa.controle, conversa.estagio, conversa.motivo_escalada = "automatizada", "abordagem", None
        conversa.empresa_id, conversa.autorizacao_id = empresa.id, aut.id
        conversa.versao = (conversa.versao or 0) + 1
    session.flush()

    session.execute(
        pg_insert(WhatsappJob).values(
            tipo="primeiro_contato", conta_id=conta.id, conversa_id=conversa.id, chave_idempotencia=f"primeiro:{aut.id}",
            status="pendente",
        ).on_conflict_do_nothing(index_elements=["chave_idempotencia"])
    )
    if criada:
        auditar(session, conta.id, "operador", "autorizar_contato", "autorizacao", aut.id,
                {"empresa_id": empresa.id, "telefone": escolhido, "usuario": usuario})
    else:
        garantir_trabalho_pendente(session, conversa, agora)
    session.flush()
    return aut, conversa, criada


FONTE_MANUAL = "manual_operador"
CONTEXTO_MAX = 4000


def _limpar_contexto(contexto: str | None) -> str | None:
    texto = (contexto or "").strip()
    if len(texto) > CONTEXTO_MAX:
        raise ServicoErro("contexto_longo", f"Contexto longo demais (máximo {CONTEXTO_MAX} caracteres).")
    return texto or None


def definir_contexto(session: Session, empresa_id: int, contexto: str | None, usuario: str):
    """Grava (ou limpa, se vazio) o contexto livre do operador no lead. É só apoio para a IA."""
    empresa = session.get(Empresa, empresa_id, with_for_update=True)
    if empresa is None:
        raise ServicoErro("empresa_nao_encontrada", "Empresa inexistente.", 404)
    empresa.contexto_manual = _limpar_contexto(contexto)
    auditar(session, obter_conta(session).id, "operador", "contexto_manual_atualizado", "empresa", empresa.id,
            {"caracteres": len(empresa.contexto_manual or ""), "usuario": usuario})
    session.flush()
    return empresa


def criar_e_autorizar(session: Session, telefone: str, nome: str, nicho_id: int, usuario: str, agora: datetime | None = None,
                      contexto: str | None = None):
    """Atalho do operador: cria uma Empresa simplificada (fonte='manual_operador') e autoriza o número no mesmo passo.

    Reaproveita `normalizar_telefone_e164` e `autorizar_lead`. Se o telefone já pertence a uma empresa existente, NÃO duplica:
    autoriza a existente. Tudo numa transação: se a autorização for recusada (ex.: supressão), a empresa nem é criada."""
    contexto = _limpar_contexto(contexto)  # valida antes de criar qualquer coisa
    nome = " ".join((nome or "").split())
    if not (2 <= len(nome) <= 255):
        raise ServicoErro("nome_invalido", "Informe o nome da empresa (2 a 255 caracteres).")
    e164 = normalizar_telefone_e164(telefone)
    if e164 is None:
        raise ServicoErro("telefone_invalido", "Telefone inválido: use DDI 55 + DDD + número (10 ou 11 dígitos).")
    if session.get(Nicho, nicho_id) is None:
        raise ServicoErro("nicho_nao_encontrado", "Nicho inexistente.", 404)

    nacional = e164[3:]  # mesmo formato de dígitos usado nos telefones da Receita
    existente = session.execute(
        select(Empresa).where((Empresa.telefone1 == nacional) | (Empresa.telefone2 == nacional)).order_by(Empresa.id).limit(1)
    ).scalar_one_or_none()
    criada = existente is None
    empresa = existente
    if empresa is None:
        empresa = Empresa(nicho_id=nicho_id, nome_fantasia=nome, telefone1=nacional, fonte=FONTE_MANUAL, contexto_manual=contexto)
        session.add(empresa)
        session.flush()
    if not criada and contexto:  # empresa já existia: só substitui o contexto se você informou um
        empresa.contexto_manual = contexto
    aut, conversa, autorizacao_criada = autorizar_lead(session, empresa.id, e164, usuario, agora)
    if criada:
        auditar(session, aut.conta_id, "operador", "criar_empresa_manual", "empresa", empresa.id, {"usuario": usuario})
    return empresa, aut, conversa, criada, autorizacao_criada


def definir_telefone_manual(session: Session, empresa_id: int, telefone: str, usuario: str):
    """Preenche um telefone VAZIO de uma empresa existente, registrando que veio de edição manual do operador.

    Nunca sobrescreve telefone já cadastrado (Receita/OSM). Mesmo número de novo = idempotente."""
    empresa = session.get(Empresa, empresa_id, with_for_update=True)
    if empresa is None:
        raise ServicoErro("empresa_nao_encontrada", "Empresa inexistente.", 404)
    e164 = normalizar_telefone_e164(telefone)
    if e164 is None:
        raise ServicoErro("telefone_invalido", "Telefone inválido: use DDD + número (10 ou 11 dígitos), com ou sem DDI 55.")
    nacional = e164[3:]
    atuais = {normalizar_telefone_e164(empresa.telefone1), normalizar_telefone_e164(empresa.telefone2)} - {None}
    if e164 in atuais:
        return empresa, False
    if not (empresa.telefone1 or "").strip():
        campo = "telefone1"
    elif not (empresa.telefone2 or "").strip():
        campo = "telefone2"
    else:
        raise ServicoErro("sem_campo_livre", "A empresa já tem dois telefones cadastrados; não sobrescrevo dados existentes.", 409)
    setattr(empresa, campo, nacional)
    session.add(EmpresaTelefoneManual(empresa_id=empresa.id, telefone=nacional, campo=campo, usuario=usuario))
    conta = obter_conta(session)
    auditar(session, conta.id, "operador", "telefone_manual", "empresa", empresa.id, {"campo": campo, "usuario": usuario})
    session.flush()
    return empresa, True


def remover_telefone_manual(session: Session, empresa_id: int, telefone: str, usuario: str):
    """Desfaz `definir_telefone_manual`: tira do lead SÓ um telefone digitado à mão (nunca Receita/OSM) e revoga a autorização
    daquele número. O histórico da conversa é mantido. Devolve (empresa, autorizacao_revogada)."""
    empresa = session.get(Empresa, empresa_id, with_for_update=True)
    if empresa is None:
        raise ServicoErro("empresa_nao_encontrada", "Empresa inexistente.", 404)
    e164 = normalizar_telefone_e164(telefone)
    if e164 is None:
        raise ServicoErro("telefone_invalido", "Telefone inválido.")
    nacional = e164[3:]
    registro = session.execute(
        select(EmpresaTelefoneManual).where(EmpresaTelefoneManual.empresa_id == empresa.id, EmpresaTelefoneManual.telefone == nacional)
    ).scalar_one_or_none()
    if registro is None:
        raise ServicoErro("telefone_nao_e_manual", "Só é possível remover telefones digitados manualmente; este veio da Receita/OSM ou não pertence ao lead.", 409)

    # 1) revoga a autorização deste número (mantém a conversa como histórico) e invalida sugestões pendentes
    contato = session.execute(select(WhatsappContato).where(WhatsappContato.telefone_e164 == e164)).scalars().first()
    revogada = None
    if contato is not None:
        conta = obter_conta(session)
        aut = session.execute(
            select(WhatsappAutorizacao).where(
                WhatsappAutorizacao.conta_id == conta.id, WhatsappAutorizacao.contato_id == contato.id, WhatsappAutorizacao.status == "ativa"
            )
        ).scalar_one_or_none()
        if aut is not None:
            revogada = revogar_autorizacao(session, aut.id, usuario, "telefone_manual_removido")
        conversa = session.execute(
            select(WhatsappConversa).where(WhatsappConversa.conta_id == conta.id, WhatsappConversa.contato_id == contato.id)
        ).scalar_one_or_none()
        if conversa is not None:
            obsoletar_sugestoes(session, conversa.id)

    # 2) tira o número do lead e apaga o registro de origem (o histórico das mensagens não é tocado)
    for campo in ("telefone1", "telefone2"):
        if normalizar_telefone_e164(getattr(empresa, campo)) == e164:
            setattr(empresa, campo, None)
    session.delete(registro)
    auditar(session, obter_conta(session).id, "operador", "telefone_manual_removido", "empresa", empresa.id,
            {"campo": registro.campo, "usuario": usuario, "autorizacao_revogada": revogada is not None})
    session.flush()
    return empresa, revogada


def revogar_autorizacao(session: Session, autorizacao_id: int, usuario: str, motivo: str = "revogada_pelo_operador"):
    aut = session.get(WhatsappAutorizacao, autorizacao_id, with_for_update=True)
    if aut is None:
        raise ServicoErro("autorizacao_nao_encontrada", "Autorização inexistente.", 404)
    if aut.status != "ativa":
        return aut
    aut.status, aut.revogado_em, aut.motivo_revogacao, aut.versao = "revogada", agora_utc(), motivo, aut.versao + 1
    conversa = session.execute(
        select(WhatsappConversa).where(WhatsappConversa.conta_id == aut.conta_id, WhatsappConversa.contato_id == aut.contato_id).with_for_update()
    ).scalar_one_or_none()
    if conversa is not None:
        conversa.controle, conversa.versao = "fora_escopo", conversa.versao + 1
        _cancelar_pendentes(session, aut.conta_id, conversa.id, "autorizacao_revogada")
    auditar(session, aut.conta_id, "operador", "revogar_autorizacao", "autorizacao", aut.id, {"motivo": motivo, "usuario": usuario})
    session.flush()
    return aut


def suprimir(session: Session, conta_id: int, contato_id: int, motivo: str, origem: str) -> None:
    """Descadastro / número errado / bloqueio: persiste supressão, revoga autorização e encerra a conversa."""
    session.execute(
        pg_insert(WhatsappSupressao).values(conta_id=conta_id, contato_id=contato_id, motivo=motivo, origem=origem)
        .on_conflict_do_nothing(index_elements=["conta_id", "contato_id"])
    )
    aut = session.execute(
        select(WhatsappAutorizacao).where(
            WhatsappAutorizacao.conta_id == conta_id, WhatsappAutorizacao.contato_id == contato_id, WhatsappAutorizacao.status == "ativa"
        )
    ).scalar_one_or_none()
    if aut is not None:
        aut.status, aut.revogado_em, aut.motivo_revogacao, aut.versao = "revogada", agora_utc(), f"supressao:{motivo}", aut.versao + 1
    conversa = session.execute(
        select(WhatsappConversa).where(WhatsappConversa.conta_id == conta_id, WhatsappConversa.contato_id == contato_id)
    ).scalar_one_or_none()
    if conversa is not None:
        conversa.controle, conversa.versao = "encerrada", conversa.versao + 1
        conversa.motivo_escalada = f"supressao:{motivo}"
        _cancelar_pendentes(session, conta_id, conversa.id, f"supressao:{motivo}")
    auditar(session, conta_id, "worker" if origem.startswith("cliente") else "operador", "suprimir_contato", "contato", contato_id,
            {"motivo": motivo, "origem": origem})
    session.flush()


def alternar_kill_switch(session: Session, pausar: bool, ator: str, motivo: str | None = None) -> WhatsappConta:
    conta = session.execute(select(WhatsappConta).order_by(WhatsappConta.id).limit(1).with_for_update()).scalar_one_or_none()
    if conta is None:
        conta = obter_conta(session)
    if pausar:
        conta.automacao_habilitada = False
        conta.motivo_pausa = motivo or "pausa_manual"
        conta.kill_geracao += 1  # invalida tudo que foi gerado até agora
        session.execute(
            update(WhatsappOutbox).where(
                WhatsappOutbox.conta_id == conta.id, WhatsappOutbox.status == "aguardando_envio", WhatsappOutbox.autoria == "ia"
            ).values(status="cancelado", erro="kill_switch")
        )
        auditar(session, conta.id, ator, "kill_switch_pausar", "conta", conta.id, {"motivo": conta.motivo_pausa})
    else:
        conta.automacao_habilitada, conta.motivo_pausa = True, None
        auditar(session, conta.id, ator, "kill_switch_retomar", "conta", conta.id)
    session.flush()
    return conta


def _nova_saida(session: Session, conta: WhatsappConta, conversa: WhatsappConversa, aut: WhatsappAutorizacao, texto: str,
                autoria: str, primeiro_contato: bool, agendado_para: datetime | None = None,
                transicao: bool = False) -> WhatsappOutbox:
    pol = politica_ativa(session)
    msg = WhatsappMensagem(
        conta_id=conta.id, conversa_id=conversa.id, contato_id=conversa.contato_id, direcao="saida", autoria=autoria,
        tipo="texto", texto=texto, estado_transporte="aguardando_envio", origem="sistema", provider_from_me=True,
    )
    session.add(msg)
    session.flush()
    out = WhatsappOutbox(
        conta_id=conta.id, conversa_id=conversa.id, contato_id=conversa.contato_id, autoria=autoria, texto=texto,
        primeiro_contato=primeiro_contato, mensagem_de_transicao=transicao, versao_autorizacao=aut.versao, versao_politica=pol.versao,
        versao_conversa=conversa.versao, kill_geracao=conta.kill_geracao, agendado_para=agendado_para or agora_utc(),
        mensagem_id=msg.id,
    )
    session.add(out)
    session.flush()
    msg.outbox_id = out.id
    return out


# ---------------------------------------------------------------- modo copiloto (a IA sugere, o operador envia fora do sistema)

def modo_de_envio(session: Session) -> str:
    return modo_envio(politica_ativa(session).config)


def obsoletar_sugestoes(session: Session, conversa_id: int) -> int:
    """Sugestões pendentes ficam desatualizadas quando o cliente escreve de novo (ou o operador envia algo por conta própria)."""
    pend = session.execute(
        select(WhatsappMensagem).where(WhatsappMensagem.conversa_id == conversa_id, WhatsappMensagem.estado_transporte == "sugerida")
    ).scalars().all()
    for m in pend:
        m.estado_transporte = "obsoleta"
        pid = ((m.meta or {}).get("sugestao") or {}).get("proposta_id")
        if pid:
            prop = session.get(PropostaComercial, pid)
            if prop is not None and prop.status == "sugerida":
                prop.status = "descartada"
    return len(pend)


def nova_sugestao(session: Session, conversa: WhatsappConversa, texto: str, *, acao: str, primeiro_contato: bool = False,
                  transicao: bool = False, pergunta: bool = False, proposta_id: int | None = None) -> WhatsappMensagem:
    """Grava a resposta da IA como SUGESTÃO (nada é enfileirado nem enviado)."""
    obsoletar_sugestoes(session, conversa.id)
    msg = WhatsappMensagem(
        conta_id=conversa.conta_id, conversa_id=conversa.id, contato_id=conversa.contato_id, direcao="saida", autoria="ia", tipo="texto",
        texto=texto, estado_transporte="sugerida", origem="sugestao",
        meta={"sugestao": {"primeiro_contato": primeiro_contato, "transicao": transicao, "pergunta": pergunta, "acao": acao, "proposta_id": proposta_id}},
    )
    session.add(msg)
    session.flush()
    return msg


def confirmar_sugestao(session: Session, mensagem_id: int, usuario: str, texto: str | None = None,
                       provider_msg_id: str | None = None, agora: datetime | None = None) -> WhatsappMensagem:
    """O operador confirma que enviou (o texto exato ou outra versão) FORA do sistema. Só a partir daqui a mensagem
    entra no histórico como enviada e produz os efeitos (proposta enviada, contagem de descoberta)."""
    agora = agora or agora_utc()
    msg = session.get(WhatsappMensagem, mensagem_id, with_for_update=True)
    if msg is None:
        raise ServicoErro("mensagem_nao_encontrada", "Mensagem inexistente.", 404)
    if msg.estado_transporte != "sugerida" or msg.autoria != "ia":
        raise ServicoErro("sugestao_indisponivel", "Esta sugestão não está mais aguardando envio (já confirmada, descartada ou desatualizada).", 409)
    conversa = session.get(WhatsappConversa, msg.conversa_id, with_for_update=True)
    novo = (texto if texto is not None else msg.texto or "").strip()
    if not novo:
        raise ServicoErro("texto_vazio", "Informe o texto que você enviou.")
    editada = " ".join(novo.split()) != " ".join((msg.texto or "").split())
    meta = dict(msg.meta or {})
    sug = dict(meta.get("sugestao") or {})
    meta["manual"] = {"editada": editada, "texto_sugerido": msg.texto if editada else None}
    msg.texto, msg.meta, msg.estado_transporte, msg.ts_provedor = novo, meta, "enviada_manual", agora
    if provider_msg_id:
        msg.provider_msg_id, msg.provider_from_me = provider_msg_id, True
    conversa.ultima_enviada_em = agora
    if sug.get("proposta_id"):
        session.execute(update(PropostaComercial).where(PropostaComercial.conversa_id == conversa.id, PropostaComercial.status == "enviada").values(status="substituida"))
        prop = session.get(PropostaComercial, sug["proposta_id"])
        if prop is not None and prop.status == "sugerida":
            prop.status = "enviada"
            conversa.estagio = "proposta"
    if sug.get("pergunta"):
        estado = dict(conversa.estado_comercial or {})
        estado["perguntas_descoberta"] = estado.get("perguntas_descoberta", 0) + 1
        estado.setdefault("primeira_pergunta_msg_id", msg.id)
        conversa.estado_comercial = estado
    auditar(session, msg.conta_id, "operador", "sugestao_enviada_manual", "mensagem", msg.id, {"editada": editada, "usuario": usuario})
    session.flush()
    return msg


def descartar_sugestao(session: Session, mensagem_id: int, usuario: str) -> WhatsappMensagem:
    msg = session.get(WhatsappMensagem, mensagem_id, with_for_update=True)
    if msg is None:
        raise ServicoErro("mensagem_nao_encontrada", "Mensagem inexistente.", 404)
    if msg.estado_transporte != "sugerida":
        raise ServicoErro("sugestao_indisponivel", "Esta sugestão não está mais aguardando envio.", 409)
    msg.estado_transporte = "descartada"
    pid = ((msg.meta or {}).get("sugestao") or {}).get("proposta_id")
    if pid:
        prop = session.get(PropostaComercial, pid)
        if prop is not None and prop.status == "sugerida":
            prop.status = "descartada"
    auditar(session, msg.conta_id, "operador", "sugestao_descartada", "mensagem", msg.id, {"usuario": usuario})
    session.flush()
    return msg


def registrar_envio_manual(session: Session, conversa_id: int, texto: str, usuario: str, agora: datetime | None = None) -> WhatsappMensagem:
    """Modo copiloto: registra no histórico uma mensagem que o operador escreveu e enviou por conta própria, fora do sistema."""
    texto = (texto or "").strip()
    if not texto:
        raise ServicoErro("texto_vazio", "Mensagem vazia.")
    conversa = session.get(WhatsappConversa, conversa_id, with_for_update=True)
    if conversa is None:
        raise ServicoErro("conversa_nao_encontrada", "Conversa inexistente.", 404)
    agora = agora or agora_utc()
    obsoletar_sugestoes(session, conversa.id)
    msg = WhatsappMensagem(
        conta_id=conversa.conta_id, conversa_id=conversa.id, contato_id=conversa.contato_id, direcao="saida", autoria="operador", tipo="texto",
        texto=texto, estado_transporte="enviada_manual", origem="manual_registrado", ts_provedor=agora, meta={"manual": {"editada": False}},
    )
    session.add(msg)
    conversa.ultima_enviada_em = agora
    auditar(session, conversa.conta_id, "operador", "envio_manual_registrado", "conversa", conversa.id, {"usuario": usuario})
    session.flush()
    return msg


def enviar_manual(session: Session, conversa_id: int, texto: str, usuario: str) -> WhatsappOutbox:
    """Envio pelo operador. Assume a conversa (a IA fica pausada até `retomar_ia`)."""
    if modo_de_envio(session) != "automatico":
        raise ServicoErro("modo_envio_manual", "Modo copiloto: o sistema não envia nada. Envie pelo WhatsApp e use “Registrar mensagem enviada”.", 409)
    texto = (texto or "").strip()
    if not texto:
        raise ServicoErro("texto_vazio", "Mensagem vazia.")
    conversa = session.get(WhatsappConversa, conversa_id, with_for_update=True)
    if conversa is None:
        raise ServicoErro("conversa_nao_encontrada", "Conversa inexistente.", 404)
    conta = session.get(WhatsappConta, conversa.conta_id)
    if suprimido(session, conta.id, conversa.contato_id):
        raise ServicoErro("contato_suprimido", "Contato suprimido: não é possível enviar.", 409)
    aut = autorizacao_ativa(session, conta.id, conversa.contato_id, agora_utc())
    if aut is None:
        raise ServicoErro("sem_autorizacao", "Número não autorizado: autorize o contato antes de enviar.", 409)
    if conversa.controle != "humano":
        conversa.controle = "humano"
        conversa.motivo_escalada = conversa.motivo_escalada or "assumida_pelo_operador"
        conversa.versao += 1
        _cancelar_pendentes(session, conta.id, conversa.id, "operador_assumiu", so_ia=True)
    out = _nova_saida(session, conta, conversa, aut, texto, "operador", primeiro_contato=False)
    auditar(session, conta.id, "operador", "envio_manual", "conversa", conversa.id, {"usuario": usuario, "outbox_id": out.id})
    session.flush()
    return out


_ENVIADAS = ("envio_em_andamento", "aceita", "entregue", "lida", "incerto", "enviada_manual")


def estado_do_trabalho(session: Session, conversa: WhatsappConversa) -> dict:
    """Foto do que a conversa tem pendente e do que já aconteceu (base do aviso na tela e da recriação de tarefas)."""
    pendente_job = session.execute(
        select(WhatsappJob.id).where(WhatsappJob.conversa_id == conversa.id, WhatsappJob.status.in_(("pendente", "em_execucao"))).limit(1)
    ).first() is not None
    pendente_saida = session.execute(
        select(WhatsappOutbox.id).where(WhatsappOutbox.conversa_id == conversa.id, WhatsappOutbox.status == "aguardando_envio").limit(1)
    ).first() is not None
    sugestao = session.execute(
        select(WhatsappMensagem.id).where(WhatsappMensagem.conversa_id == conversa.id, WhatsappMensagem.estado_transporte == "sugerida").limit(1)
    ).first() is not None
    pendente_saida = pendente_saida or sugestao
    ultima_saida = session.execute(
        select(func.max(WhatsappMensagem.id)).where(
            WhatsappMensagem.conversa_id == conversa.id, WhatsappMensagem.direcao == "saida", WhatsappMensagem.estado_transporte.in_(_ENVIADAS)
        )
    ).scalar_one()
    sem_resposta = session.execute(
        select(WhatsappMensagem.id).where(
            WhatsappMensagem.conversa_id == conversa.id, WhatsappMensagem.direcao == "entrada", WhatsappMensagem.origem != "historico",
            WhatsappMensagem.id > (ultima_saida or 0),
        ).limit(1)
    ).first() is not None
    return {"pendente": pendente_job or pendente_saida, "sugestao": sugestao, "enviou_algo": ultima_saida is not None, "cliente_sem_resposta": sem_resposta}


def garantir_trabalho_pendente(session: Session, conversa: WhatsappConversa, agora: datetime | None = None) -> str | None:
    """Uma conversa automatizada nunca deve ficar 'viva' sem nada a fazer. Se não há tarefa nem mensagem pendente:
    - cliente escreveu e ficou sem resposta -> recria o job de RESPOSTA;
    - nada foi enviado ainda -> recria o job de PRIMEIRO CONTATO;
    - já enviamos e só falta o cliente responder -> nada a fazer (estado normal).
    Devolve 'resposta', 'primeiro_contato' ou None. Só cria com autorização ativa e sem supressão."""
    agora = agora or agora_utc()
    if conversa.controle != "automatizada":
        return None
    if suprimido(session, conversa.conta_id, conversa.contato_id) or autorizacao_ativa(session, conversa.conta_id, conversa.contato_id, agora) is None:
        return None
    estado = estado_do_trabalho(session, conversa)
    if estado["pendente"]:
        return None
    if estado["cliente_sem_resposta"]:
        tipo, rotulo = "processar_entrada", "resposta"
    elif not estado["enviou_algo"]:
        tipo, rotulo = "primeiro_contato", "primeiro_contato"
    else:
        return None
    session.execute(
        pg_insert(WhatsappJob).values(
            tipo=tipo, conta_id=conversa.conta_id, conversa_id=conversa.id, chave_idempotencia=f"retomada:{conversa.id}:v{conversa.versao}:{tipo}",
            status="pendente", primeira_entrada_em=agora, proxima_execucao_em=agora,
        ).on_conflict_do_nothing(index_elements=["chave_idempotencia"])
    )
    auditar(session, conversa.conta_id, "sistema", f"tarefa_recriada_{rotulo}", "conversa", conversa.id)
    return rotulo


def mudar_controle(session: Session, conversa_id: int, novo: str, usuario: str) -> WhatsappConversa:
    conversa = session.get(WhatsappConversa, conversa_id, with_for_update=True)
    if conversa is None:
        raise ServicoErro("conversa_nao_encontrada", "Conversa inexistente.", 404)
    conta = session.get(WhatsappConta, conversa.conta_id)
    if novo == "automatizada":
        if suprimido(session, conta.id, conversa.contato_id):
            raise ServicoErro("contato_suprimido", "Contato suprimido.", 409)
        if autorizacao_ativa(session, conta.id, conversa.contato_id, agora_utc()) is None:
            raise ServicoErro("sem_autorizacao", "Sem autorização ativa: autorize o contato para retomar a IA.", 409)
        conversa.motivo_escalada = None
    elif novo not in ("humano", "pausada"):
        raise ServicoErro("controle_invalido", "Controle inválido.")
    conversa.controle, conversa.versao = novo, conversa.versao + 1
    if novo != "automatizada":
        _cancelar_pendentes(session, conta.id, conversa.id, f"controle_{novo}", so_ia=True)
    auditar(session, conta.id, "operador", f"controle_{novo}", "conversa", conversa.id, {"usuario": usuario})
    session.flush()
    conversa.tarefa_recriada = garantir_trabalho_pendente(session, conversa) if novo == "automatizada" else None  # atributo transitório p/ a API
    return conversa


# ---------------------------------------------------------------- notificação interna ao operador

def texto_notificacao_aceite(session: Session, conversa: WhatsappConversa, proposta) -> str:
    """Template fixo (sem IA) com os dados do aceite."""
    cfg = politica_ativa(session).config
    pacote = cfg["pacotes"].get(proposta.pacote, {})
    empresa = session.get(Empresa, conversa.empresa_id) if conversa.empresa_id else None
    contato = session.get(WhatsappContato, conversa.contato_id)
    extras = sum(i["centavos"] for i in proposta.itens)
    base_final = proposta.setup_centavos - extras
    linhas = [
        f"Aceite registrado: {(empresa.nome_fantasia or empresa.razao_social) if empresa else (contato.nome_exibido or 'contato sem cadastro')}",
        f"Pacote: {pacote.get('nome', proposta.pacote)}",
    ]
    base_tabela = pacote.get("setup_centavos")
    if proposta.desconto_pct and base_tabela:
        linhas.append(f"Base: {formatar_reais(base_final)} (tabela {formatar_reais(base_tabela)}, desconto de {proposta.desconto_pct / 100:g}%)")
    else:
        linhas.append(f"Base: {formatar_reais(base_final)}")
    if proposta.itens:
        linhas.append("Extras: " + "; ".join(f"{i['nome']} {formatar_reais(i['centavos'])}" for i in proposta.itens))
    linhas.append(f"Setup total: {formatar_reais(proposta.setup_centavos)}")
    if proposta.mensalidade_centavos:
        linhas.append(f"Mensalidade: {formatar_reais(proposta.mensalidade_centavos)}")
    if contato and contato.telefone_e164:
        linhas.append(f"Contato do cliente: {contato.telefone_e164}")
    linhas.append("ATENÇÃO: pagamento e contrato NÃO foram confirmados automaticamente. Entre em contato manualmente para os próximos passos.")
    linhas.append(f"(conversa {conversa.id}, aba WhatsApp)")
    return chr(10).join(linhas)


def notificar_aceite(session: Session, conta: WhatsappConta, conversa: WhatsappConversa, proposta, aceite_id: int) -> None:
    """Enfileira o aviso ao operador. NUNCA propaga erro: o aceite já está salvo e não pode ser revertido por isto.
    Usa SAVEPOINT; em falha registra a auditoria e segue."""
    if modo_de_envio(session) != "automatico":
        return  # modo copiloto: o aviso não sai pelo WhatsApp (o aceite aparece na tela)
    try:
        with session.begin_nested():
            session.execute(
                pg_insert(WhatsappNotificacaoOperador).values(
                    conta_id=conta.id, tipo="aceite", aceite_id=aceite_id, conversa_id=conversa.id,
                    texto=texto_notificacao_aceite(session, conversa, proposta),
                ).on_conflict_do_nothing(index_elements=["aceite_id"])
            )
    except Exception as exc:  # noqa: BLE001
        auditar(session, conta.id, "worker", "falha_ao_enfileirar_notificacao_de_aceite", "proposta", proposta.id,
                {"erro": f"{type(exc).__name__}: {str(exc)[:200]}"})


# ---------------------------------------------------------------- ingestão

def _variantes_nono_digito(digitos_pn: str) -> list[str]:
    """Só para RECONHECER a mesma linha telefônica em duas grafias (celular brasileiro com ou sem o 9 após o DDD).

    Vale APENAS para telefones informados pelo próprio WhatsApp (remoteJid/remoteJidAlt), nunca para o que o operador digita, e serve
    só para achar um contato que JÁ existe. Nunca cria nem estende autorização. Fixo (8 dígitos começando com 2-5) não tem equivalente."""
    if not digitos_pn.startswith("55"):
        return []
    nacional = digitos_pn[2:]
    if len(nacional) == 10 and nacional[2] in "6789":
        return ["55" + nacional[:2] + "9" + nacional[2:]]
    if len(nacional) == 11 and nacional[2] == "9" and nacional[3] in "6789":
        return ["55" + nacional[:2] + nacional[3:]]
    return []


def _digitos_do_jid(jid: str) -> str:
    return jid.split("@")[0].split(":")[0]


def _escolher_principal(session: Session, ids: list[int]) -> int:
    """Prefere quem tem autorização ativa, depois quem tem telefone resolvido, depois o mais antigo."""
    def chave(cid: int):
        contato = session.get(WhatsappContato, cid)
        autorizado = session.execute(
            select(WhatsappAutorizacao.id).where(WhatsappAutorizacao.contato_id == cid, WhatsappAutorizacao.status == "ativa").limit(1)
        ).first() is not None
        return (0 if autorizado else 1, 0 if contato.telefone_e164 else 1, cid)
    return min(ids, key=chave)


def unir_contatos(session: Session, principal_id: int, outro_id: int, motivo: str = "identidade_confirmada") -> dict:
    """Une `outro` em `principal` (mesma pessoa vista por LID e por telefone). Preserva TODO o histórico: mensagens, tarefas, propostas,
    demandas e avisos passam para a conversa do principal; nada é apagado além da linha duplicada do contato/conversa.

    Autorização: nunca é criada aqui. As existentes migram; se ambos tinham uma ativa, mantém a do principal e revoga a outra.
    Supressão prevalece (migra para o principal)."""
    if principal_id == outro_id:
        return {}
    principal = session.get(WhatsappContato, principal_id, with_for_update=True)
    outro = session.get(WhatsappContato, outro_id, with_for_update=True)
    if principal is None or outro is None:
        raise ServicoErro("contato_nao_encontrado", "Contato inexistente.", 404)
    st = {"identificadores": 0, "conversas_unidas": 0, "mensagens": 0, "autorizacoes": 0, "supressoes": 0}

    st["identificadores"] = session.execute(
        update(WhatsappContatoIdentificador).where(WhatsappContatoIdentificador.contato_id == outro_id).values(contato_id=principal_id)
    ).rowcount or 0

    for sup in session.execute(select(WhatsappSupressao).where(WhatsappSupressao.contato_id == outro_id)).scalars().all():
        ja = session.execute(select(WhatsappSupressao.id).where(WhatsappSupressao.conta_id == sup.conta_id, WhatsappSupressao.contato_id == principal_id)).first()
        if ja:
            session.delete(sup)
        else:
            sup.contato_id = principal_id
            st["supressoes"] += 1
    session.flush()

    for aut in session.execute(select(WhatsappAutorizacao).where(WhatsappAutorizacao.contato_id == outro_id)).scalars().all():
        if aut.status == "ativa" and session.execute(
            select(WhatsappAutorizacao.id).where(WhatsappAutorizacao.conta_id == aut.conta_id, WhatsappAutorizacao.contato_id == principal_id,
                                                 WhatsappAutorizacao.status == "ativa")
        ).first():
            aut.status, aut.revogado_em, aut.motivo_revogacao, aut.versao = "revogada", agora_utc(), "contatos_unidos", aut.versao + 1
        aut.contato_id = principal_id
        st["autorizacoes"] += 1
    session.flush()

    for cv in session.execute(select(WhatsappConversa).where(WhatsappConversa.contato_id == outro_id).with_for_update()).scalars().all():
        cp = session.execute(
            select(WhatsappConversa).where(WhatsappConversa.conta_id == cv.conta_id, WhatsappConversa.contato_id == principal_id).with_for_update()
        ).scalar_one_or_none()
        if cp is None:  # só o outro tinha conversa: ela passa para o principal
            cv.contato_id = principal_id
            cv.versao += 1
            session.execute(update(WhatsappMensagem).where(WhatsappMensagem.conversa_id == cv.id).values(contato_id=principal_id))
            session.execute(update(WhatsappOutbox).where(WhatsappOutbox.conversa_id == cv.id).values(contato_id=principal_id))
            continue
        st["mensagens"] += session.execute(
            update(WhatsappMensagem).where(WhatsappMensagem.conversa_id == cv.id).values(conversa_id=cp.id, contato_id=principal_id)
        ).rowcount or 0
        session.execute(update(WhatsappOutbox).where(WhatsappOutbox.conversa_id == cv.id).values(conversa_id=cp.id, contato_id=principal_id))
        for modelo in (WhatsappJob, WhatsappAiRun, PropostaComercial, DemandaComercial, WhatsappNotificacaoOperador):
            session.execute(update(modelo).where(modelo.conversa_id == cv.id).values(conversa_id=cp.id))
        for campo in ("ultima_recebida_em", "ultima_enviada_em"):
            a, b = getattr(cp, campo), getattr(cv, campo)
            if b is not None and (a is None or b > a):
                setattr(cp, campo, b)
        cp.empresa_id = cp.empresa_id or cv.empresa_id
        cp.versao += 1  # tarefas em andamento reavaliam com o histórico completo
        session.flush()
        session.delete(cv)
        st["conversas_unidas"] += 1
    session.execute(update(WhatsappMensagem).where(WhatsappMensagem.contato_id == outro_id).values(contato_id=principal_id))
    session.execute(update(WhatsappOutbox).where(WhatsappOutbox.contato_id == outro_id).values(contato_id=principal_id))

    principal.telefone_e164 = principal.telefone_e164 or outro.telefone_e164
    principal.nome_exibido = principal.nome_exibido or outro.nome_exibido
    principal.identidade_resolvida = bool(principal.identidade_resolvida or outro.identidade_resolvida)
    session.flush()
    session.delete(outro)
    auditar(session, None, "sistema", "contatos_unidos", "contato", principal_id, {"unido": outro_id, "motivo": motivo, **st})
    session.flush()
    return st


def _resolver_contato(session: Session, conta_id: int, jid: str | None, jid_alt: str | None, push_name: str | None) -> WhatsappContato:
    """Identifica o contato de uma mensagem recebida. Considera TODOS os identificadores que o WhatsApp informou (LID e telefone):
    se eles apontarem para contatos diferentes, são a mesma pessoa e os contatos são UNIDOS.

    Nunca deduz telefone a partir de um LID. Telefone só vem de `@s.whatsapp.net` (informado pelo WhatsApp). Achar o contato nunca
    autoriza nada: a autorização continua sendo do clique explícito do operador, verificada depois por contato."""
    def tipo_de(identificador: str) -> str:
        return "lid" if identificador.endswith("@lid") else "jid"

    ids = [(tipo_de(i), i) for i in (jid, jid_alt) if i]
    achados: list[int] = []

    def somar(contato_id: int | None) -> None:
        if contato_id and contato_id not in achados:
            achados.append(contato_id)

    for tipo, ident in ids:
        somar(session.execute(
            select(WhatsappContatoIdentificador.contato_id).where(
                WhatsappContatoIdentificador.conta_id == conta_id, WhatsappContatoIdentificador.tipo == tipo,
                WhatsappContatoIdentificador.identificador == ident,
            )
        ).scalar_one_or_none())

    telefones = [i for _, i in ids if i.endswith("@s.whatsapp.net")]
    for pn in telefones:
        digitos = _digitos_do_jid(pn)
        for d in [digitos, *_variantes_nono_digito(digitos)]:  # equivalência do 9: só para RECONHECER quem já existe
            for cid in session.execute(select(WhatsappContato.id).where(WhatsappContato.telefone_e164 == "+" + d)).scalars().all():
                somar(cid)
            somar(session.execute(
                select(WhatsappContatoIdentificador.contato_id).where(
                    WhatsappContatoIdentificador.conta_id == conta_id, WhatsappContatoIdentificador.tipo == "jid",
                    WhatsappContatoIdentificador.identificador == d + "@s.whatsapp.net",
                ).limit(1)
            ).scalar_one_or_none())

    if achados:
        contato_id = _escolher_principal(session, achados) if len(achados) > 1 else achados[0]
        for outro in achados:
            if outro != contato_id:
                unir_contatos(session, contato_id, outro, "lid_e_telefone_da_mesma_pessoa")
    else:
        if telefones:
            contato = WhatsappContato(telefone_e164="+" + _digitos_do_jid(telefones[0]), nome_exibido=push_name, identidade_resolvida=True)
        else:  # só LID, sem par de telefone: identidade NÃO resolvida
            contato = WhatsappContato(nome_exibido=push_name, identidade_resolvida=False)
        session.add(contato)
        session.flush()
        contato_id = contato.id
    for tipo, ident in ids:
        session.execute(
            pg_insert(WhatsappContatoIdentificador).values(
                conta_id=conta_id, contato_id=contato_id, tipo=tipo, identificador=ident, origem="evento_recebido"
            ).on_conflict_do_nothing(constraint="uq_wa_identificador")
        )
    contato = session.get(WhatsappContato, contato_id)
    if push_name and not contato.nome_exibido:
        contato.nome_exibido = push_name
    return contato


def agendar_job_entrada(session: Session, conversa: WhatsappConversa, mensagem_id: int, agora: datetime, limites: dict) -> None:
    """Agrupa mensagens seguidas: espera ~8 s após a última, no máximo 20 s desde a primeira."""
    espera = timedelta(seconds=limites["espera_agrupamento_seg"])
    maximo = timedelta(seconds=limites["espera_agrupamento_max_seg"])
    job = session.execute(
        select(WhatsappJob).where(
            WhatsappJob.conversa_id == conversa.id, WhatsappJob.tipo == "processar_entrada", WhatsappJob.status == "pendente"
        ).with_for_update()
    ).scalars().first()
    if job is not None:
        primeira = job.primeira_entrada_em or job.criado_em
        job.proxima_execucao_em = min(agora + espera, primeira + maximo)
        return
    session.add(WhatsappJob(
        tipo="processar_entrada", conta_id=conversa.conta_id, conversa_id=conversa.id,
        chave_idempotencia=f"entrada:{conversa.id}:{mensagem_id}", primeira_entrada_em=agora, proxima_execucao_em=agora + espera,
    ))


_ORDEM_TRANSPORTE = {"aguardando_envio": 0, "envio_em_andamento": 1, "aceita": 2, "entregue": 3, "lida": 4}
_STATUS_RECIBO = {"sent": "aceita", "server_ack": "aceita", "delivered": "entregue", "delivery_ack": "entregue", "read": "lida", "played": "lida"}


def _aplicar_recibo(session: Session, ev: WhatsappEventoEntrada) -> None:
    msg = session.execute(
        select(WhatsappMensagem).where(
            WhatsappMensagem.conta_id == ev.conta_id, WhatsappMensagem.provider_msg_id == ev.provider_msg_id, WhatsappMensagem.provider_from_me.is_(True)
        )
    ).scalar_one_or_none()
    if msg is None:
        return
    status = (ev.dados or {}).get("status")
    novo = _STATUS_RECIBO.get(status)
    if status in ("error", "failed"):
        novo = "falhou"
    if novo is None:
        return
    atual = msg.estado_transporte
    if novo == "falhou" or _ORDEM_TRANSPORTE.get(novo, 0) > _ORDEM_TRANSPORTE.get(atual, 0):
        msg.estado_transporte = novo
        if msg.outbox_id:
            session.execute(update(WhatsappOutbox).where(WhatsappOutbox.id == msg.outbox_id).values(status=novo))
    session.add(WhatsappMensagemEvento(mensagem_id=msg.id, evento=novo, ocorrido_em=ev.ts_provedor or agora_utc(), metadados=ev.dados))


def ingerir_eventos(session: Session, agora: datetime | None = None, limite: int = 200) -> int:
    """Interpreta os eventos brutos do gateway. NENHUMA chamada ao DeepSeek acontece aqui; só decide
    escopo e agenda o job. Mensagem de número sem autorização ativa vira `fora_escopo`, sem job e sem resposta."""
    agora = agora or agora_utc()
    eventos = session.execute(
        select(WhatsappEventoEntrada).where(WhatsappEventoEntrada.processado.is_(False)).order_by(WhatsappEventoEntrada.id)
        .limit(limite).with_for_update(skip_locked=True)
    ).scalars().all()
    config_pol = politica_ativa(session).config
    limites = config_pol["limites"]
    manual = modo_envio(config_pol) != "automatico"
    for ev in eventos:
        if ev.tipo == "recibo":
            _aplicar_recibo(session, ev)
            ev.processado = True
            continue
        if ev.from_me and ev.provider_msg_id and session.execute(
            select(WhatsappNotificacaoOperador.id).where(WhatsappNotificacaoOperador.provider_msg_id == ev.provider_msg_id)
        ).first():  # eco do aviso interno ao operador: não é conversa com lead
            ev.processado = True
            continue
        conta = session.get(WhatsappConta, ev.conta_id)
        contato = _resolver_contato(session, conta.id, ev.jid, ev.jid_alt, ev.push_name)
        conversa = session.execute(
            select(WhatsappConversa).where(WhatsappConversa.conta_id == conta.id, WhatsappConversa.contato_id == contato.id).with_for_update()
        ).scalar_one_or_none()
        if conversa is None:
            conversa = WhatsappConversa(conta_id=conta.id, contato_id=contato.id, controle="fora_escopo")
            session.add(conversa)
            session.flush()

        if manual and ev.from_me and ev.origem != "historico" and ev.texto:
            # Modo copiloto: o operador enviou pelo app. Se o texto bate com uma sugestão pendente, reconcilia sozinho.
            alvo = " ".join(ev.texto.split()).casefold()
            pendentes = session.execute(
                select(WhatsappMensagem).where(WhatsappMensagem.conversa_id == conversa.id, WhatsappMensagem.estado_transporte == "sugerida")
                .order_by(WhatsappMensagem.id.desc())
            ).scalars().all()
            achada = next((m for m in pendentes if " ".join((m.texto or "").split()).casefold() == alvo), None)
            if achada is not None:
                confirmar_sugestao(session, achada.id, "dispositivo", provider_msg_id=ev.provider_msg_id, agora=ev.ts_provedor or agora)
                ev.processado = True
                continue
        fila = session.execute(
            pg_insert(WhatsappMensagem).values(
                conta_id=conta.id, conversa_id=conversa.id, contato_id=contato.id,
                direcao="saida" if ev.from_me else "entrada", autoria="operador" if ev.from_me else "cliente",
                tipo=ev.tipo_msg or "texto", texto=ev.texto, provider_msg_id=ev.provider_msg_id, provider_from_me=ev.from_me,
                provider_jid=ev.jid, ts_provedor=ev.ts_provedor, estado_transporte="entregue",
                origem="dispositivo_proprio" if ev.from_me and ev.origem != "historico" else ev.origem,
            ).on_conflict_do_nothing(index_elements=["conta_id", "provider_msg_id", "provider_from_me"],
                                     index_where=WhatsappMensagem.provider_msg_id.is_not(None)).returning(WhatsappMensagem.id)
        ).scalar_one_or_none()
        ev.processado = True
        if fila is None:  # duplicata (evento repetido) ou eco de mensagem enviada pelo próprio sistema
            continue
        msg_id = fila
        if ev.from_me:
            if manual:  # copiloto: tudo que sai é do operador; não pausa a IA, só invalida sugestões desatualizadas
                if ev.origem != "historico":
                    obsoletar_sugestoes(session, conversa.id)
                continue
            if ev.origem != "historico" and conversa.controle == "automatizada":
                conversa.controle, conversa.motivo_escalada = "humano", "intervencao_no_aparelho"
                conversa.versao += 1
                _cancelar_pendentes(session, conta.id, conversa.id, "intervencao_no_aparelho", so_ia=True)
            continue
        conversa.ultima_recebida_em = ev.ts_provedor or agora
        conversa.versao += 1
        if ev.origem == "historico":  # sincronização de histórico nunca dispara contato retroativo
            continue
        obsoletar_sugestoes(session, conversa.id)  # o cliente escreveu: qualquer sugestão pendente ficou desatualizada
        if suprimido(session, conta.id, contato.id):
            continue
        aut = autorizacao_ativa(session, conta.id, contato.id, agora)
        if aut is None:
            if conversa.controle not in ("encerrada",):
                conversa.controle = "fora_escopo"
            continue
        if conversa.controle == "automatizada":
            agendar_job_entrada(session, conversa, msg_id, agora, limites)
    session.flush()
    return len(eventos)
