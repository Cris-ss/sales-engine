"""Worker comercial: ingere eventos do gateway, decide escopo, conduz a conversa via DeepSeek e grava a outbox.

Uso: python -m etapa7_whatsapp.worker            (loop contínuo)
     python -m etapa7_whatsapp.worker --uma-vez  (um ciclo)

Nada aqui envia mensagem: só o gateway envia, e só depois de repetir as checagens de segurança.
Nenhuma transação fica aberta durante a chamada ao DeepSeek.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from api.persistence.whatsapp_models import (
    AceiteComercial, DemandaComercial, PropostaComercial, WhatsappAiRun, WhatsappConta, WhatsappConversa, WhatsappJob,
    WhatsappMensagem, WhatsappOutbox,
)
from db.models import Empresa, LeadScore, Nicho
from etapa7_whatsapp import servico
from etapa7_whatsapp.decisao import (
    Decisao, DecisaoInvalida, parse_decisao, pedido_de_humano, pedido_de_parar, validar_decisao,
)
from etapa7_whatsapp.guards import agora_utc, autorizacao_ativa, avaliar_outbox, suprimido
from etapa7_whatsapp.horario import dentro_da_janela, proximo_inicio
from etapa7_whatsapp.llm import PROMPT_VERSAO, LlmFn, montar_mensagens
from etapa7_whatsapp.politica import politica_ativa

LEASE = timedelta(minutes=5)
MAX_TENTATIVAS_JOB = 5
# Mensagens NOSSAS que não chegaram ao cliente: não contam como resposta nem entram no histórico do prompt.
NAO_ENVIADAS = ("cancelado", "falhou", "aguardando_envio", "sugerida", "descartada", "obsoleta")
TEXTO_HANDOFF = "Vou pedir para um especialista da nossa equipe entrar em contato para tratar disso com você."


def recuperar_leases(session: Session, agora: datetime) -> None:
    """Job cujo worker morreu volta para a fila (sem rajada: só o que está com lease vencido)."""
    session.execute(
        update(WhatsappJob).where(WhatsappJob.status == "em_execucao", WhatsappJob.lease_ate < agora)
        .values(status="pendente", proxima_execucao_em=agora)
    )


def reivindicar_job(session: Session, agora: datetime) -> WhatsappJob | None:
    ocupadas = select(WhatsappJob.conversa_id).where(WhatsappJob.status == "em_execucao")
    job = session.execute(
        select(WhatsappJob).where(
            WhatsappJob.status == "pendente", WhatsappJob.proxima_execucao_em <= agora, WhatsappJob.conversa_id.not_in(ocupadas),
        ).order_by(WhatsappJob.proxima_execucao_em, WhatsappJob.id).with_for_update(skip_locked=True).limit(1)
    ).scalar_one_or_none()
    if job is None:
        return None
    job.status, job.lease_ate, job.tentativas = "em_execucao", agora + LEASE, job.tentativas + 1
    session.commit()
    return job


def _concluir(job: WhatsappJob, status: str = "concluido", erro: str | None = None) -> None:
    job.status, job.erro = status, erro


def _lead_para_prompt(session: Session, conversa: WhatsappConversa) -> dict:
    lead: dict = {"telefone_conversa": None}
    if conversa.empresa_id:
        e = session.get(Empresa, conversa.empresa_id)
        if e is not None:
            nicho = session.get(Nicho, e.nicho_id)
            score = session.execute(
                select(LeadScore).where(LeadScore.empresa_id == e.id).order_by(LeadScore.criado_em.desc(), LeadScore.id.desc()).limit(1)
            ).scalar_one_or_none()
            lead.update({
                "nome": e.nome_fantasia or e.razao_social, "nicho": nicho.nome if nicho else None,
                "municipio": e.municipio, "uf": e.uf,
                "dores_identificadas": getattr(score, "dores_identificadas", None) if score else None,
                "contexto_manual": (e.contexto_manual or "")[:3000] or None,
            })
    return {k: v for k, v in lead.items() if v}


def _descoberta_ok(session: Session, conversa: WhatsappConversa) -> bool:
    primeira = (conversa.estado_comercial or {}).get("primeira_pergunta_msg_id")
    if not primeira:
        return False
    return session.execute(
        select(WhatsappMensagem.id).where(
            WhatsappMensagem.conversa_id == conversa.id, WhatsappMensagem.direcao == "entrada", WhatsappMensagem.id > primeira
        ).limit(1)
    ).first() is not None


def _turno_da_qualificacao(session: Session, conversa: WhatsappConversa) -> int:
    """0 = o cliente ainda não respondeu à 1ª pergunta; N = número de "rodadas" de resposta do cliente desde então
    (mensagens seguidas do cliente contam como uma rodada só)."""
    primeira = (conversa.estado_comercial or {}).get("primeira_pergunta_msg_id")
    if not primeira:
        return 0
    msgs = session.execute(
        select(WhatsappMensagem).where(WhatsappMensagem.conversa_id == conversa.id, WhatsappMensagem.id > primeira).order_by(WhatsappMensagem.id)
    ).scalars().all()
    rodadas, anterior_era_cliente = 0, False
    for m in msgs:
        if m.direcao == "saida":
            if m.estado_transporte not in NAO_ENVIADAS:
                anterior_era_cliente = False
        elif not anterior_era_cliente:
            rodadas += 1
            anterior_era_cliente = True
    return rodadas


def _dia_local_inicio(agora: datetime, tz: str) -> datetime:
    from zoneinfo import ZoneInfo
    from datetime import timezone
    return agora.astimezone(ZoneInfo(tz)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def _orcamento_deepseek_esgotado(session: Session, conta: WhatsappConta, limites: dict, agora: datetime) -> bool:
    inicio = _dia_local_inicio(agora, conta.timezone)
    chamadas, tokens = session.execute(
        select(func.count(), func.coalesce(func.sum(WhatsappAiRun.tokens_entrada + WhatsappAiRun.tokens_saida), 0))
        .where(WhatsappAiRun.criado_em >= inicio, WhatsappAiRun.modelo.is_not(None))
    ).one()
    return chamadas >= limites["deepseek_max_chamadas_dia"] or tokens >= limites["deepseek_max_tokens_dia"]


def _saida(session: Session, conta, conversa, aut, texto: str, *, acao: str, primeiro: bool = False, transicao: bool = False,
           pergunta: bool = False, proposta_id: int | None = None):
    """Modo automático: enfileira na outbox (o gateway envia). Modo copiloto: só grava a SUGESTÃO (nada é enviado)."""
    if servico.modo_de_envio(session) == "automatico":
        return servico._nova_saida(session, conta, conversa, aut, texto, "ia", primeiro_contato=primeiro, transicao=transicao)
    return servico.nova_sugestao(session, conversa, texto, acao=acao, primeiro_contato=primeiro, transicao=transicao,
                                 pergunta=pergunta, proposta_id=proposta_id)


def _escalar(session: Session, conta, conversa, aut, job, motivo: str, texto: str | None, necessidade: str | None = None) -> None:
    conversa.controle, conversa.motivo_escalada = "humano", motivo
    conversa.versao += 1
    if necessidade:
        session.add(DemandaComercial(conversa_id=conversa.id, descricao=necessidade))
    if texto:
        _saida(session, conta, conversa, aut, texto, acao="escalar", transicao=True)
    servico.auditar(session, conta.id, "worker", "escalar_para_humano", "conversa", conversa.id, {"motivo": motivo})


def processar_job(session_factory: sessionmaker, job_id: int, llm: LlmFn, agora: datetime | None = None) -> str:
    """Processa um job já reivindicado. Devolve um rótulo do resultado (útil nos testes)."""
    agora = agora or agora_utc()
    with session_factory() as s:
        job = s.get(WhatsappJob, job_id)
        conversa = s.get(WhatsappConversa, job.conversa_id, with_for_update=True)
        conta = s.get(WhatsappConta, job.conta_id)
        pol = politica_ativa(s)
        cfg, lim = pol.config, pol.config["limites"]
        aut = autorizacao_ativa(s, conta.id, conversa.contato_id, agora)

        if aut is None or suprimido(s, conta.id, conversa.contato_id):
            _concluir(job, "cancelado", "sem_autorizacao_ativa_ou_suprimido")
            s.commit()
            return "cancelado_sem_autorizacao"
        if conversa.controle != "automatizada":
            _concluir(job, "cancelado", f"controle_{conversa.controle}")
            s.commit()
            return "cancelado_controle"
        if not conta.automacao_habilitada:  # pausado: mantém a fila; ao retomar, tudo é reavaliado
            job.status, job.proxima_execucao_em = "pendente", agora + timedelta(seconds=30)
            s.commit()
            return "adiado_pausa"
        if not cfg.get("vendas_ativas"):
            # Conversa de venda ainda NÃO liberada pelo operador: nenhuma chamada ao modelo, atendimento humano.
            conversa.controle, conversa.motivo_escalada = "humano", "automacao_de_venda_desativada"
            conversa.versao += 1
            servico.auditar(s, conta.id, "worker", "automacao_de_venda_desativada", "conversa", conversa.id)
            _concluir(job)
            s.commit()
            return "humano_venda_desativada"
        # Horário e limites só valem para ENVIO automático; no copiloto a sugestão é gerada a qualquer hora.
        if servico.modo_de_envio(s) == "automatico" and not dentro_da_janela(agora, conta.timezone, lim):
            job.status, job.proxima_execucao_em = "pendente", proximo_inicio(agora, conta.timezone, lim)
            s.commit()
            return "adiado_horario"
        if _orcamento_deepseek_esgotado(s, conta, lim, agora):
            servico.alternar_kill_switch(s, True, "sistema", "orcamento_deepseek_esgotado")
            job.status, job.proxima_execucao_em = "pendente", agora + timedelta(minutes=30)
            s.commit()
            return "pausado_orcamento"

        primeiro = job.tipo == "primeiro_contato"
        versao_lida = conversa.versao
        ultima_saida = s.execute(
            select(func.max(WhatsappMensagem.id)).where(
                WhatsappMensagem.conversa_id == conversa.id, WhatsappMensagem.direcao == "saida",
                WhatsappMensagem.estado_transporte.not_in(NAO_ENVIADAS),
            )
        ).scalar_one() or 0
        novas = s.execute(
            select(WhatsappMensagem).where(
                WhatsappMensagem.conversa_id == conversa.id, WhatsappMensagem.direcao == "entrada", WhatsappMensagem.id > ultima_saida
            ).order_by(WhatsappMensagem.id)
        ).scalars().all()
        texto_novo = "\n".join(m.texto or "" for m in novas if (m.texto or "").strip())

        # Gatilhos determinísticos: não dependem do modelo.
        if not primeiro:
            textos = [m.texto or "" for m in novas]
            if any(pedido_de_parar(t) for t in textos):  # qualquer mensagem do lote basta
                servico.suprimir(s, conta.id, conversa.contato_id, "descadastro", "cliente_pediu_para_parar")
                _concluir(job)
                s.commit()
                return "suprimido"
            if any(m.tipo != "texto" for m in novas):
                _escalar(s, conta, conversa, aut, job, "midia_nao_suportada", "Recebi seu arquivo/áudio, mas por aqui só consigo ler texto. "
                         "Vou pedir para alguém da nossa equipe olhar e retornar.")
                _concluir(job)
                s.commit()
                return "escalado_midia"
            if any(pedido_de_humano(t) for t in textos):
                _escalar(s, conta, conversa, aut, job, "pedido_de_atendimento_humano", TEXTO_HANDOFF)
                _concluir(job)
                s.commit()
                return "escalado_pedido_humano"

        proposta = s.execute(
            select(PropostaComercial).where(PropostaComercial.conversa_id == conversa.id, PropostaComercial.status == "enviada")
            .order_by(PropostaComercial.id.desc()).limit(1)
        ).scalar_one_or_none()
        recentes = s.execute(
            select(WhatsappMensagem).where(WhatsappMensagem.conversa_id == conversa.id, WhatsappMensagem.id <= (novas[0].id - 1 if novas else 10**9))
            .order_by(WhatsappMensagem.id.desc()).limit(20)
        ).scalars().all()[::-1]
        historico = [{"de": {"cliente": "cliente", "ia": "nos", "operador": "nos"}[m.autoria], "texto": m.texto} for m in recentes
                     if m.texto and not (m.direcao == "saida" and m.estado_transporte in NAO_ENVIADAS)]
        lead = _lead_para_prompt(s, conversa)
        estado = dict(conversa.estado_comercial or {})
        mensagens = montar_mensagens(
            cfg, lead, {**{k: v for k, v in estado.items() if k != "primeira_pergunta_msg_id"}, "turno_da_qualificacao": _turno_da_qualificacao(s, conversa)},
            {"pacote": proposta.pacote, "itens": proposta.itens, "setup_centavos": proposta.setup_centavos,
             "mensalidade_centavos": proposta.mensalidade_centavos} if proposta else None,
            conversa.resumo, historico, [m.texto for m in novas if m.texto], primeiro,
        )
        descoberta = _descoberta_ok(s, conversa)
        primeira_proposta = s.execute(
            select(PropostaComercial.id).where(PropostaComercial.conversa_id == conversa.id,
                                               PropostaComercial.status.in_(("enviada", "substituida", "aceita"))).limit(1)
        ).first() is None  # sugerida/descartada não conta: o cliente nunca viu
        conversa_id, conta_id, contato_id = conversa.id, conta.id, conversa.contato_id
        s.commit()  # libera o lock ANTES de chamar o modelo

    decisao, orcamento, runs = None, None, []
    ultimo_erro = None
    rejeitada_pelo_validador = False  # texto do modelo violou regra (≠ falha de rede/API)
    for tentativa in range(2):
        t0 = time.monotonic()
        try:
            bruto, tin, tout = llm(mensagens if ultimo_erro is None else mensagens + [
                {"role": "user", "content": f"Sua resposta anterior foi rejeitada ({ultimo_erro}). Corrija e responda só com o JSON."}
            ])
            d = parse_decisao(bruto)
            with session_factory() as s2:
                cfg2 = politica_ativa(s2).config
            decisao, orcamento = validar_decisao(d, cfg2, descoberta, proposta is not None, primeira_proposta)
            if primeiro and decisao.acao not in ("responder", "perguntar"):
                raise DecisaoInvalida("primeiro_contato_deve_ser_mensagem_de_abordagem")
            runs.append((tin, tout, int((time.monotonic() - t0) * 1000), decisao.model_dump(), "ok", None))
            break
        except DecisaoInvalida as exc:
            ultimo_erro, rejeitada_pelo_validador = str(exc), True
            runs.append((0, 0, int((time.monotonic() - t0) * 1000), None, "rejeitada", ultimo_erro))
        except Exception as exc:  # falha de rede/API: registra, nunca inventa resposta
            ultimo_erro, rejeitada_pelo_validador = f"{type(exc).__name__}: {str(exc)[:200]}", False
            runs.append((0, 0, int((time.monotonic() - t0) * 1000), None, "erro", ultimo_erro))
            break

    with session_factory() as s:
        job = s.get(WhatsappJob, job_id)
        conversa = s.get(WhatsappConversa, conversa_id, with_for_update=True)
        conta = s.get(WhatsappConta, conta_id)
        pol = politica_ativa(s)
        for tin, tout, ms, dec, val, erro in runs:
            s.add(WhatsappAiRun(conversa_id=conversa_id, job_id=job_id, modelo="deepseek-chat", prompt_versao=PROMPT_VERSAO,
                                politica_versao=pol.versao, tokens_entrada=tin, tokens_saida=tout, latencia_ms=ms, decisao=dec,
                                validacao=val, erro=erro))
        aut = autorizacao_ativa(s, conta_id, contato_id, agora)

        # A conversa mudou enquanto o modelo pensava (nova mensagem, pausa, revogação...): descarta e recalcula.
        if conversa.versao != versao_lida or aut is None or conversa.controle != "automatizada" or not conta.automacao_habilitada:
            s.add(WhatsappAiRun(conversa_id=conversa_id, job_id=job_id, validacao="descartada", erro="conversa_mudou_durante_a_geracao"))
            if aut is not None and conversa.controle == "automatizada" and conta.automacao_habilitada:
                pendente = s.execute(
                    select(WhatsappJob.id).where(WhatsappJob.conversa_id == conversa_id, WhatsappJob.status == "pendente", WhatsappJob.id != job_id)
                ).first()
                if pendente is None:  # ninguém vai reprocessar: reagenda este
                    job.status, job.proxima_execucao_em = "pendente", agora
                else:
                    _concluir(job, "cancelado", "superado_por_nova_mensagem")
            else:
                _concluir(job, "cancelado", "conversa_mudou_durante_a_geracao")
            s.commit()
            return "descartado_conversa_mudou"

        if decisao is None:
            falhas = (conversa.estado_comercial or {}).get("falhas_geracao", 0) + 1
            conversa.estado_comercial = {**(conversa.estado_comercial or {}), "falhas_geracao": falhas}
            if job.tentativas >= 2 or rejeitada_pelo_validador:
                _escalar(s, conta, conversa, aut, job, f"falha_repetida_de_geracao:{ultimo_erro}", None)
                _concluir(job, "concluido", ultimo_erro)
                s.commit()
                return "escalado_falha_geracao"
            job.status, job.proxima_execucao_em, job.erro = "pendente", agora + timedelta(seconds=30 * job.tentativas), ultimo_erro
            s.commit()
            return "reagendado_erro"

        return _aplicar(s, conta, conversa, aut, job, decisao, orcamento, pol, primeiro, agora)


def _aplicar(s: Session, conta, conversa, aut, job, d: Decisao, orcamento, pol, primeiro: bool, agora: datetime) -> str:
    estado = dict(conversa.estado_comercial or {})
    estado["falhas_geracao"] = 0
    if d.caminho != "indefinido":
        estado["caminho"] = d.caminho
    if d.estagio_sugerido and d.acao in ("responder", "perguntar"):
        conversa.estagio = d.estagio_sugerido if d.estagio_sugerido not in ("aceita", "proposta") else conversa.estagio
    resultado = d.acao

    if d.acao == "escalar":
        conversa.estado_comercial = estado
        _escalar(s, conta, conversa, aut, job, d.motivo_escalada or "escalada_pelo_modelo", d.texto, d.necessidade_texto)
        _concluir(job)
        s.commit()
        return "escalado"

    if d.acao == "encerrar":
        motivo = d.motivo_encerramento or "outro"
        if motivo in ("descadastro", "numero_errado"):
            servico.suprimir(s, conta.id, conversa.contato_id, motivo, "cliente_via_modelo")
        else:
            conversa.controle, conversa.versao = "encerrada", conversa.versao + 1
            conversa.estagio = "perdida"
            if d.texto:
                _saida(s, conta, conversa, aut, d.texto, acao="encerrar", transicao=True)
        conversa.estado_comercial = estado
        _concluir(job)
        s.commit()
        return "encerrado"

    automatico = servico.modo_de_envio(s) == "automatico"
    conversa.versao += 1  # a saída carrega a versão pós-decisão; qualquer entrada nova a invalida
    if d.acao == "perguntar" and automatico:
        estado["perguntas_descoberta"] = estado.get("perguntas_descoberta", 0) + 1  # no copiloto conta ao confirmar o envio
    nova_prop = None
    if d.acao == "propor" and orcamento is not None:
        if automatico:
            s.execute(update(PropostaComercial).where(PropostaComercial.conversa_id == conversa.id, PropostaComercial.status == "enviada").values(status="substituida"))
        nova_prop = PropostaComercial(
            conversa_id=conversa.id, politica_versao=pol.versao, pacote=orcamento.pacote, itens=orcamento.itens,
            setup_centavos=orcamento.setup_centavos, mensalidade_centavos=orcamento.mensalidade_centavos, desconto_pct=orcamento.desconto_bp,
            status="enviada" if automatico else "sugerida",  # no copiloto só vira "enviada" quando o operador confirma o envio
        )
        s.add(nova_prop)
        s.flush()
        if automatico:
            conversa.estagio = "proposta"
    if d.acao == "registrar_aceite":
        prop = s.execute(
            select(PropostaComercial).where(PropostaComercial.conversa_id == conversa.id, PropostaComercial.status == "enviada")
            .order_by(PropostaComercial.id.desc()).limit(1)
        ).scalar_one()
        prop.status = "aceita"
        aceite = AceiteComercial(proposta_id=prop.id)
        s.add(aceite)
        s.flush()
        servico.notificar_aceite(s, conta, conversa, prop, aceite.id)  # falha aqui nunca desfaz o aceite
        conversa.estagio = "aceita"
        conversa.motivo_escalada = "aceite_registrado_aguardando_operador"  # pagamento/contrato seguem com o operador
        servico.auditar(s, conta.id, "worker", "aceite_registrado", "proposta", prop.id)
    if not automatico:
        _saida(s, conta, conversa, aut, d.texto or "", acao=d.acao, primeiro=primeiro, pergunta=(d.acao == "perguntar" or primeiro),
               proposta_id=nova_prop.id if nova_prop else None)
        conversa.estado_comercial = estado
        _concluir(job)
        s.commit()
        return f"sugestao_{resultado}"
    out = servico._nova_saida(s, conta, conversa, aut, d.texto or "", "ia", primeiro_contato=primeiro)
    if d.acao == "perguntar" and "primeira_pergunta_msg_id" not in estado:
        estado["primeira_pergunta_msg_id"] = out.mensagem_id
    if primeiro and "primeira_pergunta_msg_id" not in estado:
        estado["primeira_pergunta_msg_id"] = out.mensagem_id  # a abordagem termina com pergunta de descoberta
    conversa.estado_comercial = estado

    veredito = avaliar_outbox(s, out, agora)
    if veredito.acao == "cancelar":
        out.status, out.erro = "cancelado", veredito.motivo
        if veredito.pausar_conversa:
            conversa.controle, conversa.motivo_escalada = "humano", veredito.motivo
    elif veredito.acao == "adiar" and veredito.ate:
        out.agendado_para = veredito.ate
    _concluir(job)
    s.commit()
    return f"outbox_{resultado}"


def executar_ciclo(session_factory: sessionmaker, llm: LlmFn, agora: datetime | None = None, max_jobs: int = 20) -> int:
    agora = agora or agora_utc()
    with session_factory() as s:
        servico.obter_conta(s)
        politica_ativa(s)
        s.commit()
        recuperar_leases(s, agora)
        s.commit()
        servico.ingerir_eventos(s, agora)
        s.commit()
    feitos = 0
    for _ in range(max_jobs):
        with session_factory() as s:
            job = reivindicar_job(s, agora)
            job_id = job.id if job else None
        if job_id is None:
            break
        try:
            processar_job(session_factory, job_id, llm, agora)
        except Exception as exc:
            with session_factory() as s:
                j = s.get(WhatsappJob, job_id)
                j.status = "falhou" if j.tentativas >= MAX_TENTATIVAS_JOB else "pendente"
                j.proxima_execucao_em, j.erro = agora + timedelta(seconds=30 * j.tentativas), f"{type(exc).__name__}: {str(exc)[:300]}"
                s.commit()
            print(f"[worker] job {job_id} falhou: {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr)
        feitos += 1
    return feitos


def main(argv: list[str]) -> int:
    from dotenv import load_dotenv
    import os
    from db.models import get_engine
    from etapa7_whatsapp.llm import criar_llm_deepseek

    load_dotenv()
    session_factory = sessionmaker(bind=get_engine(os.environ["DATABASE_URL"]), future=True)
    llm = criar_llm_deepseek()
    print("[worker] etapa7 iniciado (a conversa de venda só roda se `vendas_ativas` estiver true na política).")
    while True:
        executar_ciclo(session_factory, llm)
        if "--uma-vez" in argv:
            return 0
        time.sleep(1.0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
