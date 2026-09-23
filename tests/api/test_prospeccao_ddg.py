from datetime import date

from api.persistence.prospeccao_models import LoteProspeccao, ValidacaoSiteDdg
from db.models import Validacao


def test_criar_lote_exige_confirmacao(client, fab):
    resposta = client.post("/api/v1/prospeccoes", json={"nicho_id": fab.nicho_c.id, "uf": "pr", "limite": 10})
    assert resposta.status_code == 422
    assert resposta.json()["erro"]["codigo"] == "confirmacao_necessaria"


def test_criar_lote_nao_altera_dados_existentes(client, fab, db):
    empresa = fab.empresa("Legado", site_url="https://legado.example", tem_pelo_menos_um_canal=True, email_final="contato@legado.example")
    validacao_antes = db.query(Validacao).filter_by(empresa_id=empresa.id).one()
    db.commit()

    resposta = client.post("/api/v1/prospeccoes", json={"nicho_id": fab.nicho_c.id, "uf": "pr", "fonte": "apify", "limite": 10, "confirmar": True})
    assert resposta.status_code == 201
    assert db.get(Validacao, validacao_antes.id).site_url == "https://legado.example"
    assert db.query(ValidacaoSiteDdg).count() == 0


def test_lote_osm_exige_cidade_e_raio(client, fab, db):
    db.commit()
    resposta = client.post("/api/v1/prospeccoes", json={"nicho_id": fab.nicho_c.id, "uf": "PR", "fonte": "osm", "limite": 10, "confirmar": True})
    assert resposta.status_code == 422
    assert resposta.json()["erro"]["codigo"] == "cidade_e_raio_necessarios"


def test_lote_google_places_e_recusado_e_nada_e_criado(client, fab, db):
    db.commit()
    for limite in (50, 61):
        resposta = client.post("/api/v1/prospeccoes", json={
            "nicho_id": fab.nicho_c.id, "uf": "SP", "fonte": "google_places",
            "cidade": "Cidade Exemplo", "limite": limite, "confirmar": True,
        })
        assert resposta.status_code == 422
        assert resposta.json()["erro"]["codigo"] == "google_places_proibido"
    assert client.get("/api/v1/prospeccoes").json() == []


def test_autocomplete_de_cidades(client):
    resposta = client.get("/api/v1/prospeccoes/cidades", params={"q": "campinas"})
    assert resposta.status_code == 200
    cidade = next(item for item in resposta.json() if item["nome"] == "Campinas")
    assert cidade["uf"] == "SP"
    assert cidade["rotulo"] == "Campinas, SP"


def test_filtros_ddg_e_data_inicio(client, fab, db):
    antigo = fab.empresa("Legado")
    novo = fab.empresa("Novo DDG")
    antigo.data_inicio_atividade = "2018-03-01"
    novo.data_inicio_atividade = "15/06/2024"
    lote = LoteProspeccao(nicho_id=fab.nicho_c.id, uf="PR", limite=10)
    db.add(lote)
    db.flush()
    db.add(ValidacaoSiteDdg(empresa_id=novo.id, lote_id=lote.id, consulta='"Novo" "Cidade Exemplo" site', resultado="sem_site"))
    db.commit()

    por_site = client.get("/api/v1/leads", params={"site_ddg": "sem_site"}).json()
    assert [i["id"] for i in por_site["itens"]] == [novo.id]
    por_data = client.get("/api/v1/leads", params={"data_inicio_de": str(date(2024, 1, 1))}).json()
    assert [i["id"] for i in por_data["itens"]] == [novo.id]
