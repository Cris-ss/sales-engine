"""Fixtures de teste. Testes de escrita rodam SOMENTE em banco cujo nome termina
em `_test` (trava abaixo) — nunca no banco real."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
load_dotenv(os.path.join(RAIZ, ".env"))

from api import settings  # noqa: E402
from api.persistence import geo_models  # noqa: E402,F401  (registra a tabela no metadata)
from api.persistence import prospeccao_models  # noqa: E402,F401
from api.persistence import whatsapp_models  # noqa: E402,F401
from db.models import (  # noqa: E402
    Base, CanalContato, ContatoEnviado, Empresa, EstagioFunil, FunilStatus, LeadScore, Nicho, Validacao, get_engine,
)


def _url_teste() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        base = os.environ["DATABASE_URL"]
        url = base.rsplit("/", 1)[0] + "/sales_engine_test"
    if not settings.banco_eh_de_teste(url):
        raise RuntimeError(f"RECUSADO: {url!r} não parece banco de teste (nome deve terminar em _test).")
    return url


@pytest.fixture(scope="session")
def engine():
    eng = get_engine(_url_teste())
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def db(engine):
    # A aba WhatsApp consulta /status a cada poucos segundos (selo de aceites); um deadlock ocasional com o TRUNCATE é repetido.
    import time
    from sqlalchemy.exc import OperationalError

    for tentativa in range(4):
        try:
            with engine.begin() as c:
                c.execute(text("TRUNCATE whatsapp_message_events, whatsapp_ai_runs, whatsapp_messages, whatsapp_outbox, whatsapp_jobs, commercial_acceptances, commercial_proposals, commercial_demands, whatsapp_conversations, whatsapp_suppressions, whatsapp_authorizations, whatsapp_contact_identifiers, whatsapp_contacts, whatsapp_inbound_events, whatsapp_auth_state, whatsapp_audit_events, whatsapp_accounts, commercial_policies, validacoes_site_ddg, lotes_prospeccao_empresas, lotes_prospeccao, empresa_geolocalizacoes, respostas, contatos_enviados, funil_status, lead_scores, validacoes, empresas, nichos RESTART IDENTITY CASCADE"))
            break
        except OperationalError:
            if tentativa == 3:
                raise
            time.sleep(0.5)
    S = sessionmaker(bind=engine, future=True)
    s = S()
    yield s
    s.close()


@pytest.fixture()
def client(engine, db):
    from fastapi.testclient import TestClient

    from api.app import create_app
    from api.dependencies import get_session

    S = sessionmaker(bind=engine, future=True)

    def _override():
        s = S()
        try:
            yield s
        finally:
            s.close()

    app = create_app()
    app.dependency_overrides[get_session] = _override
    return TestClient(app)


T0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


class Fabrica:
    """Cria dados mínimos e claramente sintéticos."""

    def __init__(self, s):
        self.s = s
        self.n = 0
        self.nicho_c = Nicho(slug="contabilidade", nome="Escritórios de Contabilidade", cnae="6920601")
        self.nicho_i = Nicho(slug="imobiliarias", nome="Imobiliárias e Corretoras", cnae="6821801")
        s.add_all([self.nicho_c, self.nicho_i])
        s.flush()

    def empresa(self, nome="Empresa", nicho=None, municipio="CIDADE EXEMPLO", uf="PR", tel1=None, tel2=None, validacao=True, **val):
        self.n += 1
        e = Empresa(
            nicho_id=(nicho or self.nicho_c).id, cnpj=f"{self.n:014d}", razao_social=f"{nome} LTDA",
            nome_fantasia=nome, municipio=municipio, uf=uf, telefone1=tel1, telefone2=tel2, cep="12345678",
        )
        self.s.add(e)
        self.s.flush()
        if validacao:
            padrao = dict(site_url=None, email_final=None, formulario_contato_url=None, tem_pelo_menos_um_canal=False)
            padrao.update(val)
            self.s.add(Validacao(empresa_id=e.id, **padrao))
        self.s.flush()
        return e

    def score(self, e, valor, dias=0, **kw):
        ls = LeadScore(empresa_id=e.id, score=valor, modelo_usado="deepseek-chat", prompt_versao="v1",
                       criado_em=T0 + timedelta(days=dias), **kw)
        self.s.add(ls)
        self.s.flush()
        return ls

    def contato(self, e, canal=CanalContato.EMAIL, status="pendente", ok=False, erro=None, dias=0, destino="x@y.com"):
        c = ContatoEnviado(empresa_id=e.id, canal=canal, destino=destino, assunto="assunto", corpo="corpo",
                           status_envio=status, sucesso_envio=ok, erro=erro,
                           data_envio=(T0 + timedelta(days=dias)) if status == "enviado" else None)
        self.s.add(c)
        self.s.flush()
        return c

    def funil(self, e, estagio, dias=0):
        f = FunilStatus(empresa_id=e.id, estagio=EstagioFunil(estagio), criado_em=T0 + timedelta(days=dias))
        self.s.add(f)
        self.s.flush()
        return f


@pytest.fixture()
def fab(db):
    return Fabrica(db)
