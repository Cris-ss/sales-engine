"""Envio dos emails gerados na etapa4 via SMTP (Zoho), respeitando o
limite diário de warm-up.

Uso:
    python -m etapa5_envio.smtp_sender --dry-run
    python -m etapa5_envio.smtp_sender
    python -m etapa5_envio.smtp_sender --limite-manual 2

Escopo: só o canal "email" (ContatoEnviado.canal == EMAIL). Registros
com canal "formulario_site" exigiriam submissão de formulário web, que
não é implementada aqui — ficam pendentes até essa etapa existir.

Segurança: a senha SMTP nunca é logada/impressa, nem em erro. Falha de
envio (SMTPException) não trava o lote — o registro fica "pendente" e o
próximo é tentado.
"""

from __future__ import annotations

import argparse
import os
import random
import smtplib
import sys
import time
from datetime import date, datetime, time as dtime, timezone
from email.message import EmailMessage
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from db.models import (
    CanalContato,
    ContatoEnviado,
    Empresa,
    LeadScore,
    get_session_factory,
    init_db,
)
from etapa5_envio.warmup import limite_diario_hoje

PAUSA_MIN_SEG = 20
PAUSA_MAX_SEG = 40


def enviados_hoje(session) -> int:
    """Conta envios de HOJE no fuso local, não em UTC.

    `data_envio` é gravado com `datetime.now(timezone.utc)`. Comparar com
    `func.date(data_envio) == date.today()` truncaria a data em UTC no
    lado do Postgres — perto da meia-noite local (Brasil = UTC-3), UTC já
    virou o dia seguinte e a contagem dá 0 mesmo com envios feitos há
    minutos, o que faria o warm-up mandar de novo além do limite do dia.
    Em vez disso comparamos contra o intervalo [meia-noite, meia-noite)
    local convertido para instante absoluto — correto independente de
    fuso, tanto do lado do Python quanto do Postgres.
    """
    hoje = date.today()
    inicio = datetime.combine(hoje, dtime.min).astimezone()
    fim = datetime.combine(hoje, dtime.max).astimezone()
    return (
        session.query(ContatoEnviado)
        .filter(
            ContatoEnviado.status_envio == "enviado",
            ContatoEnviado.data_envio >= inicio,
            ContatoEnviado.data_envio <= fim,
        )
        .count()
    )


def _score_da_empresa(session, empresa_id: int) -> float:
    lead_score = (
        session.query(LeadScore)
        .filter_by(empresa_id=empresa_id)
        .order_by(LeadScore.id.desc())
        .first()
    )
    return lead_score.score if lead_score else 0.0


def _buscar_pendentes_ordenados(session, limite: int) -> list[ContatoEnviado]:
    pendentes = (
        session.query(ContatoEnviado)
        .filter(
            ContatoEnviado.status_envio == "pendente",
            ContatoEnviado.canal == CanalContato.EMAIL,
        )
        .all()
    )
    pendentes.sort(key=lambda c: _score_da_empresa(session, c.empresa_id), reverse=True)
    return pendentes[:limite]


def _montar_mensagem(smtp_user: str, contato: ContatoEnviado) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = contato.assunto
    msg["From"] = smtp_user
    msg["To"] = contato.destino
    msg.set_content(contato.corpo)
    return msg


def enviar_lote(limite_manual: Optional[int] = None, dry_run: bool = False) -> None:
    engine = init_db(os.environ["DATABASE_URL"])
    Session = get_session_factory(engine)
    session = Session()

    try:
        if limite_manual is not None:
            limite = limite_manual
            print(f"[envio] limite manual definido: {limite}")
        else:
            limite_dia = limite_diario_hoje()
            ja_enviados = enviados_hoje(session)
            limite = limite_dia - ja_enviados
            print(
                f"[envio] warm-up hoje: limite_do_dia={limite_dia}, "
                f"ja_enviados_hoje={ja_enviados}, restante={limite}"
            )

        if limite <= 0:
            print("[envio] limite diário de warm-up já atingido. Nada a fazer agora.")
            return

        pendentes = _buscar_pendentes_ordenados(session, limite)
        print(
            f"[envio] {len(pendentes)} email(s) selecionado(s) para "
            f"{'simulação (dry-run)' if dry_run else 'envio'}."
        )

        if dry_run:
            for contato in pendentes:
                empresa = session.query(Empresa).filter_by(id=contato.empresa_id).one()
                score = _score_da_empresa(session, contato.empresa_id)
                nome = empresa.nome_fantasia or empresa.razao_social
                print(
                    f"  [DRY-RUN] score={score:.0f} | {nome} -> {contato.destino} "
                    f"| assunto: {contato.assunto}"
                )
            print("[envio] dry-run: nada foi enviado, nada foi alterado no banco.")
            return

        if not pendentes:
            print("[envio] nenhum pendente de canal email no momento.")
            return

        smtp_host = os.environ["SMTP_HOST"]
        smtp_port = int(os.environ["SMTP_PORT"])
        smtp_user = os.environ["SMTP_USER"]
        smtp_password = os.environ["SMTP_PASSWORD"]

        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(smtp_user, smtp_password)

            for i, contato in enumerate(pendentes):
                empresa = session.query(Empresa).filter_by(id=contato.empresa_id).one()
                nome = empresa.nome_fantasia or empresa.razao_social
                msg = _montar_mensagem(smtp_user, contato)

                try:
                    server.send_message(msg)
                except smtplib.SMTPException as exc:
                    print(f"[envio] FALHA ao enviar para {nome} ({contato.destino}): {exc}")
                    contato.erro = str(exc)
                    session.commit()
                    continue

                contato.status_envio = "enviado"
                contato.sucesso_envio = True
                contato.data_envio = datetime.now(timezone.utc)
                contato.erro = None
                session.commit()
                print(f"[envio] OK: {nome} ({contato.destino})")

                if i < len(pendentes) - 1:
                    pausa = random.uniform(PAUSA_MIN_SEG, PAUSA_MAX_SEG)
                    time.sleep(pausa)
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Envia os emails da etapa4 via SMTP, respeitando o warm-up por data."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simula o envio (mostra quem seria enviado) sem mandar email nem alterar o banco.",
    )
    parser.add_argument(
        "--limite-manual",
        type=int,
        default=None,
        help="Sobrescreve o cálculo de warm-up com um limite fixo (para teste, ex.: 1 ou 2).",
    )
    args = parser.parse_args()

    try:
        enviar_lote(limite_manual=args.limite_manual, dry_run=args.dry_run)
    except RuntimeError as exc:
        print(f"[envio] ERRO: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
