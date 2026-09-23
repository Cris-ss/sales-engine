"""Cria UM registro de teste isolado para validar o envio SMTP da etapa5,
sem arriscar mandar email para um lead real.

Cria os registros mínimos necessários:
- Empresa (FK obrigatória de ContatoEnviado), claramente marcada como
  teste (cnpj fictício, nome "TESTE - NAO USAR")
- LeadScore com score=999 — acima de qualquer score real, para garantir que
  a ordenação por score DESC escolha este registro primeiro
- ContatoEnviado com destino=teste@example.com, status_envio="pendente"

Não usa nenhum Nicho novo — reaproveita um já existente no banco (é só
uma categoria, não some dado real).

Uso: python scripts/criar_teste_envio.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from db.models import (
    CanalContato,
    ContatoEnviado,
    Empresa,
    LeadScore,
    Nicho,
    get_session_factory,
    init_db,
)

CNPJ_TESTE = "99999999000199"
NOME_TESTE = "TESTE - NAO USAR"
EMAIL_DESTINO_TESTE = "teste@example.com"


def main() -> None:
    engine = init_db(os.environ["DATABASE_URL"])
    Session = get_session_factory(engine)
    session = Session()

    nicho = session.query(Nicho).first()
    if nicho is None:
        raise RuntimeError(
            "Nenhum Nicho encontrado no banco. Rode main.py (ou sincronize "
            "config/nichos.yaml) antes de criar o registro de teste."
        )

    empresa_existente = session.query(Empresa).filter_by(cnpj=CNPJ_TESTE).one_or_none()
    if empresa_existente is not None:
        print(
            f"AVISO: já existe uma empresa de teste (id={empresa_existente.id}, "
            f"cnpj={CNPJ_TESTE}). Rode scripts/limpar_teste_envio.py antes de criar outra."
        )
        session.close()
        return

    empresa = Empresa(
        nicho_id=nicho.id,
        cnpj=CNPJ_TESTE,
        razao_social=NOME_TESTE,
        nome_fantasia=NOME_TESTE,
        situacao_cadastral="TESTE",
        municipio="TESTE",
        uf="SP",
    )
    session.add(empresa)
    session.flush()  # garante empresa.id sem precisar commitar ainda

    lead_score = LeadScore(
        empresa_id=empresa.id,
        score=999,
        modelo_usado="teste",
        prompt_versao="teste",
        dores_identificadas=NOME_TESTE,
        justificativa="Registro de teste para validar o envio SMTP da etapa5_envio.",
    )
    session.add(lead_score)

    contato = ContatoEnviado(
        empresa_id=empresa.id,
        canal=CanalContato.EMAIL,
        destino=EMAIL_DESTINO_TESTE,
        assunto="[TESTE] Sales Engine - Validação de envio",
        corpo=(
            "Este é um email de teste do pipeline sales-engine. Se você recebeu "
            "isso, o envio SMTP está funcionando corretamente."
        ),
        status_envio="pendente",
    )
    session.add(contato)
    session.commit()

    print(f"Empresa de teste criada: id={empresa.id}, cnpj={empresa.cnpj}")
    print(f"LeadScore de teste criado: id={lead_score.id}, score={lead_score.score}")
    print(f"ContatoEnviado de teste criado: id={contato.id}")
    print()
    print(f"Para limpar depois: python scripts/limpar_teste_envio.py {empresa.id}")
    print("(ou sem argumento — o script busca automaticamente por nome_fantasia='TESTE - NAO USAR')")

    session.close()


if __name__ == "__main__":
    main()
