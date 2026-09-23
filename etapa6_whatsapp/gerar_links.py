"""CLI: lista empresas com telefone apto e gera o link wa.me de cada uma.

Só LEITURA no banco. Não envia nada, não grava nada. O link é para abertura
manual pelo operador.

Uso:
    python -m etapa6_whatsapp.gerar_links
    python -m etapa6_whatsapp.gerar_links --nicho contabilidade --amostra 10
    python -m etapa6_whatsapp.gerar_links --csv links_whatsapp.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from db.models import Empresa, LeadScore, Nicho, get_session_factory, init_db
from etapa6_whatsapp.whatsapp_link import gerar_para_empresa


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera links wa.me (uso manual, sem envio).")
    parser.add_argument("--nicho", default=None, help="slug do nicho (veja config/nichos.yaml)")
    parser.add_argument("--amostra", type=int, default=5, help="quantos exemplos imprimir")
    parser.add_argument("--csv", default=None, help="caminho de um CSV para gravar todos os links")
    args = parser.parse_args()

    session = get_session_factory(init_db(os.environ["DATABASE_URL"]))()
    try:
        nichos = {n.id: n for n in session.query(Nicho).all()}
        query = session.query(Empresa)
        if args.nicho:
            alvo = next((n for n in nichos.values() if n.slug == args.nicho), None)
            if alvo is None:
                print(f"Nicho desconhecido: {args.nicho}")
                sys.exit(1)
            query = query.filter(Empresa.nicho_id == alvo.id)

        contagem: Counter = Counter()
        aptas: list[tuple[Empresa, object]] = []
        for empresa in query.order_by(Empresa.id).all():
            score: Optional[LeadScore] = (
                session.query(LeadScore)
                .filter_by(empresa_id=empresa.id)
                .order_by(LeadScore.criado_em.desc(), LeadScore.id.desc())
                .first()
            )
            resultado = gerar_para_empresa(
                empresa, nichos[empresa.nicho_id].slug, score.dores_identificadas if score else None
            )
            contagem[resultado.telefone.tipo if resultado.telefone else "ausente"] += 1
            if resultado.apto:
                aptas.append((empresa, resultado))

        total = sum(contagem.values())
        print(f"Empresas analisadas: {total}")
        print(f"  com telefone apto a link (celular): {len(aptas)}")
        for tipo in ("fixo", "invalido", "ausente"):
            print(f"  {tipo}: {contagem[tipo]}")
        print("(apto = formato de celular; NÃO significa WhatsApp verificado)")

        for empresa, r in aptas[: args.amostra]:
            print()
            print(f"{empresa.nome_fantasia or empresa.razao_social} — {empresa.municipio}/{empresa.uf}")
            print(f"  telefone: {r.telefone.original} -> {r.telefone.normalizado}"
                  f"{' (9º dígito acrescentado)' if r.telefone.nono_digito_adicionado else ''}")
            print(f"  mensagem: {r.mensagem}")
            print(f"  link: {r.link}")

        if args.csv:
            with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["empresa_id", "cnpj", "nome", "municipio", "uf", "telefone_original",
                            "telefone_normalizado", "nono_digito_acrescentado", "mensagem", "link"])
                for empresa, r in aptas:
                    w.writerow([empresa.id, f"'{empresa.cnpj}", empresa.nome_fantasia or empresa.razao_social,
                                empresa.municipio, empresa.uf, r.telefone.original, r.telefone.normalizado,
                                "sim" if r.telefone.nono_digito_adicionado else "não", r.mensagem, r.link])
            print(f"\nCSV gravado: {args.csv} ({len(aptas)} linhas)")
    finally:
        session.close()


if __name__ == "__main__":
    main()
