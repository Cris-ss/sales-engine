"""Kanban persistente. Rodam só no banco _test."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select

from db.models import FunilStatus


def _post(client, eid, destino, esperado, obs=None):
    return client.post(
        f"/api/v1/leads/{eid}/transicoes",
        json={"estagio_destino": destino, "id_historico_esperado": esperado, "observacao": obs},
    )


def test_mudanca_persiste_e_e_nova_linha_sem_alterar_as_anteriores(client, fab, db):
    e = fab.empresa("Alfa")
    f1 = fab.funil(e, "qualificada", dias=-2)
    db.commit()
    antes = db.execute(select(FunilStatus.id, FunilStatus.estagio, FunilStatus.criado_em, FunilStatus.observacao)).all()

    r = _post(client, e.id, "contatada", f1.id, "primeiro contato")
    assert r.status_code == 200
    j = r.json()
    assert j["lead"]["estagio"] == "contatada" and j["lead"]["coluna"] == "contatado" and j["lead"]["estagio_derivado"] is False
    assert j["funil_id"] == j["lead"]["funil_id"] != f1.id

    db.expire_all()
    depois = db.execute(select(FunilStatus.id, FunilStatus.estagio, FunilStatus.criado_em, FunilStatus.observacao).order_by(FunilStatus.id)).all()
    assert depois[: len(antes)] == antes                      # linhas antigas intactas
    assert len(depois) == len(antes) + 1                      # exatamente uma nova linha

    # "recarregar": nova leitura vê o estágio persistido, e o histórico tem as duas linhas
    assert client.get(f"/api/v1/leads/{e.id}").json()["estagio"] == "contatada"
    hist = client.get(f"/api/v1/leads/{e.id}/funil").json()
    assert [i["estagio"] for i in hist["itens"]] == ["contatada", "qualificada"]
    assert hist["itens"][0]["observacao"] == "primeiro contato"


def test_lead_sem_historico_aceita_esperado_null(client, fab, db):
    e = fab.empresa("Beta")
    db.commit()
    r = _post(client, e.id, "qualificada", None)
    assert r.status_code == 200 and r.json()["lead"]["estagio"] == "qualificada"


def test_derivado_de_email_enviado_pode_ser_movido_sem_gravar_antes(client, fab, db):
    e = fab.empresa("Gama", email_final="g@g.com", tem_pelo_menos_um_canal=True)
    fab.contato(e, status="enviado", ok=True)
    db.commit()
    lead = client.get(f"/api/v1/leads/{e.id}").json()
    assert lead["coluna"] == "contatado" and lead["funil_id"] is None
    assert _post(client, e.id, "contatada", None).status_code == 422       # já está lá (derivado)
    r = _post(client, e.id, "venda", lead["funil_id"])
    assert r.status_code == 200 and r.json()["lead"]["coluna"] == "ganho"


def test_conflito_de_duas_abas_retorna_409(client, fab, db):
    e = fab.empresa("Delta")
    f1 = fab.funil(e, "encontrada", dias=-1)
    db.commit()
    assert _post(client, e.id, "qualificada", f1.id).status_code == 200      # aba 1
    r = _post(client, e.id, "perdida", f1.id)                                # aba 2, ainda com o id antigo
    assert r.status_code == 409
    err = r.json()["erro"]
    assert err["codigo"] == "conflito_concorrencia" and err["detalhes"]["estagio_atual"] == "qualificada"
    db.expire_all()
    assert db.execute(select(func.count()).select_from(FunilStatus)).scalar_one() == 2   # a aba 2 não gravou nada


def test_corrida_real_apenas_uma_escrita_vence(client, fab, db):
    e = fab.empresa("Epsilon")
    f1 = fab.funil(e, "encontrada", dias=-1)
    db.commit()
    with ThreadPoolExecutor(max_workers=6) as ex:
        resultados = list(ex.map(lambda d: _post(client, e.id, d, f1.id).status_code,
                                 ["qualificada", "contatada", "venda", "perdida", "proposta", "respondeu"]))
    assert sorted(resultados) == [200, 409, 409, 409, 409, 409]
    db.expire_all()
    assert db.execute(select(func.count()).select_from(FunilStatus)).scalar_one() == 2


def test_validacoes(client, fab, db):
    e = fab.empresa("Zeta")
    f1 = fab.funil(e, "qualificada")
    db.commit()
    assert _post(client, e.id, "inexistente", f1.id).json()["erro"]["codigo"] == "estagio_invalido"
    assert _post(client, e.id, "qualificada", f1.id).json()["erro"]["codigo"] == "sem_mudanca"
    assert _post(client, 999999, "venda", None).status_code == 404
    r = client.post(f"/api/v1/leads/{e.id}/transicoes", json={"estagio_destino": "venda"})
    assert r.status_code == 422                                # id_historico_esperado é obrigatório (pode ser null)


def test_sequencia_de_subestagios_preserva_historico_completo(client, fab, db):
    e = fab.empresa("Eta")
    db.commit()
    atual = None
    for destino in ["qualificada", "contatada", "respondeu", "proposta", "venda"]:
        r = _post(client, e.id, destino, atual)
        assert r.status_code == 200
        atual = r.json()["funil_id"]
    hist = client.get(f"/api/v1/leads/{e.id}/funil?page_size=10").json()
    assert [i["estagio"] for i in hist["itens"]] == ["venda", "proposta", "respondeu", "contatada", "qualificada"]
    assert client.get(f"/api/v1/leads/{e.id}").json()["coluna"] == "ganho"
