"""Manutenção da Etapa 7 (uso pontual, sempre com --dry-run primeiro).

    python -m etapa7_whatsapp.manutencao unir-contatos --principal 3 --outro 4            # só mostra o que faria
    python -m etapa7_whatsapp.manutencao unir-contatos --principal 3 --outro 4 --aplicar  # grava
"""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from api.persistence.whatsapp_models import (
    WhatsappAutorizacao, WhatsappContato, WhatsappContatoIdentificador, WhatsappConversa, WhatsappMensagem,
)
from db.models import get_engine
from etapa7_whatsapp import servico


def _resumo(session, cid: int) -> str:
    c = session.get(WhatsappContato, cid)
    if c is None:
        return f"contato {cid}: NÃO EXISTE"
    ids = session.execute(select(WhatsappContatoIdentificador.tipo, WhatsappContatoIdentificador.identificador).where(WhatsappContatoIdentificador.contato_id == cid)).all()
    convs = session.execute(select(WhatsappConversa.id, WhatsappConversa.controle).where(WhatsappConversa.contato_id == cid)).all()
    msgs = session.execute(select(func.count()).select_from(WhatsappMensagem).where(WhatsappMensagem.contato_id == cid)).scalar_one()
    auts = session.execute(select(WhatsappAutorizacao.id, WhatsappAutorizacao.status).where(WhatsappAutorizacao.contato_id == cid)).all()
    return (f"contato {cid}: nome={c.nome_exibido!r} telefone={c.telefone_e164!r} identificadores={[tuple(i) for i in ids]} "
            f"conversas={[tuple(x) for x in convs]} mensagens={msgs} autorizacoes={[tuple(a) for a in auts]}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("unir-contatos")
    u.add_argument("--principal", type=int, required=True)
    u.add_argument("--outro", type=int, required=True)
    u.add_argument("--aplicar", action="store_true", help="sem isto, nada é gravado (dry-run)")
    args = ap.parse_args(argv)

    load_dotenv()
    fabrica = sessionmaker(bind=get_engine(os.environ["DATABASE_URL"]), future=True)
    with fabrica() as s:
        print("ANTES")
        print(" ", _resumo(s, args.principal))
        print(" ", _resumo(s, args.outro))
        estatisticas = servico.unir_contatos(s, args.principal, args.outro, "correcao_manual")
        if not args.aplicar:
            s.rollback()
            print(f"\nDRY-RUN (nada gravado). Faria: {estatisticas}")
            return 0
        s.commit()
        print(f"\nGRAVADO: {estatisticas}")
    with fabrica() as s:
        print("DEPOIS")
        print(" ", _resumo(s, args.principal))
        print(" ", _resumo(s, args.outro))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
