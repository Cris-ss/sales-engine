"""Remove o(s) registro(s) de teste criados por scripts/criar_teste_envio.py:
ContatoEnviado, LeadScore e Empresa — sem tocar em nada mais (Nicho
reaproveitado não é removido, dados reais não são tocados).

Uso:
    python scripts/limpar_teste_envio.py            # busca por nome_fantasia="TESTE - NAO USAR"
    python scripts/limpar_teste_envio.py <empresa_id>  # remove uma empresa específica por id
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from db.models import ContatoEnviado, Empresa, LeadScore, Validacao, get_session_factory, init_db

NOME_TESTE = "TESTE - NAO USAR"


def main() -> None:
    engine = init_db(os.environ["DATABASE_URL"])
    Session = get_session_factory(engine)
    session = Session()

    if len(sys.argv) > 1:
        empresa_id = int(sys.argv[1])
        empresas = session.query(Empresa).filter_by(id=empresa_id).all()
    else:
        empresas = (
            session.query(Empresa)
            .filter(
                (Empresa.nome_fantasia == NOME_TESTE) | (Empresa.razao_social == NOME_TESTE)
            )
            .all()
        )

    if not empresas:
        print("Nenhum registro de teste encontrado. Nada a fazer.")
        session.close()
        return

    for empresa in empresas:
        n_contatos = session.query(ContatoEnviado).filter_by(empresa_id=empresa.id).delete()
        n_scores = session.query(LeadScore).filter_by(empresa_id=empresa.id).delete()
        n_validacoes = session.query(Validacao).filter_by(empresa_id=empresa.id).delete()
        empresa_id, empresa_cnpj = empresa.id, empresa.cnpj
        session.delete(empresa)
        session.commit()

        print(
            f"Removido: empresa id={empresa_id} (cnpj={empresa_cnpj}) — "
            f"{n_contatos} ContatoEnviado, {n_scores} LeadScore, {n_validacoes} Validacao"
        )

    session.close()


if __name__ == "__main__":
    main()
