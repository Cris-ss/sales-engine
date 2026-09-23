"""Mapa: API e dados."""

from __future__ import annotations

import sys

import pytest
from sqlalchemy.exc import IntegrityError

from api import dominio
from api.persistence.geo_models import EmpresaGeolocalizacao


def _geo(db, e, lat, lng, precisao="municipio", status="localizada", **kw):
    g = EmpresaGeolocalizacao(
        empresa_id=e.id, latitude=lat if status == "localizada" else None, longitude=lng if status == "localizada" else None,
        fonte="teste", precisao=precisao, status=status, **kw,
    )
    db.add(g)
    db.flush()
    return g


def _dados(fab, db):
    a = fab.empresa("Cidade Um", municipio="CIDADE EXEMPLO", uf="PR")
    fab.score(a, 75)
    _geo(db, a, -25.43, -49.27, "cep")
    b = fab.empresa("Cidade Dois", municipio="CIDADE EXEMPLO", uf="PR")
    fab.score(b, 55)
    _geo(db, b, -25.42, -49.26, "municipio")
    c = fab.empresa("Rio Um", nicho=fab.nicho_i, municipio="RIO DE JANEIRO", uf="RJ")
    _geo(db, c, -22.90, -43.20, "municipio")
    d = fab.empresa("Sem Coordenada", municipio="LUGAR NENHUM", uf="SP")
    _geo(db, d, None, None, "municipio", status="nao_encontrada")
    e = fab.empresa("Sem Linha De Geo", municipio="OUTRO", uf="SP")           # nem chegou a ser geocodificada
    db.commit()
    return a, b, c, d, e


def test_bbox_filtra_por_area_visivel_e_informa_totais(client, fab, db):
    _dados(fab, db)
    r = client.get("/api/v1/mapa/leads").json()                                # sem bbox: tudo que tem coordenada
    assert {i["nome"] for i in r["itens"]} == {"Cidade Um", "Cidade Dois", "Rio Um"}
    assert r["total_filtrado"] == 5 and r["com_coordenadas"] == 3 and r["sem_coordenadas"] == 2
    assert r["por_precisao"] == {"municipio": 2, "cep": 1, "estabelecimento": 0}
    assert "NÃO é o endereço" in r["legenda_precisao"]["municipio"]

    sul = client.get("/api/v1/mapa/leads?min_lat=-27&max_lat=-24&min_lng=-51&max_lng=-48").json()
    assert {i["nome"] for i in sul["itens"]} == {"Cidade Um", "Cidade Dois"}
    assert sul["total_no_recorte"] == 2
    assert sul["sem_coordenadas"] == 2                                          # contagem é do universo filtrado, não do recorte


def test_pontos_carregam_precisao_score_e_estagio(client, fab, db):
    _dados(fab, db)
    itens = {i["nome"]: i for i in client.get("/api/v1/mapa/leads").json()["itens"]}
    assert itens["Cidade Um"]["precisao"] == "cep" and itens["Cidade Um"]["faixa_score"] == "alto"
    assert itens["Cidade Dois"]["precisao"] == "municipio" and itens["Cidade Dois"]["faixa_score"] == "neutro"
    assert itens["Rio Um"]["faixa_score"] == "sem_score" and itens["Rio Um"]["score"] is None     # cinza no mapa, nunca 0
    assert itens["Rio Um"]["coluna"] == "novo" and itens["Rio Um"]["estagio"] == "encontrada"


def test_filtros_compartilhados_valem_no_mapa(client, fab, db):
    _dados(fab, db)
    r = client.get("/api/v1/mapa/leads?uf=PR").json()
    assert r["total_filtrado"] == 2 and len(r["itens"]) == 2
    r = client.get("/api/v1/mapa/leads?nicho_id=2").json()
    assert [i["nome"] for i in r["itens"]] == ["Rio Um"]
    assert client.get("/api/v1/mapa/leads?faixa=alto").json()["itens"][0]["nome"] == "Cidade Um"


def test_limite_excedido_nao_trunca_em_silencio(client, fab, db, monkeypatch):
    _dados(fab, db)
    monkeypatch.setattr(dominio, "MAPA_MAX_PONTOS", 2)
    r = client.get("/api/v1/mapa/leads").json()
    assert r["excedeu_limite"] is True and r["itens"] == [] and r["total_no_recorte"] == 3 and r["limite"] == 2
    ok = client.get("/api/v1/mapa/leads?min_lat=-27&max_lat=-24&min_lng=-51&max_lng=-48").json()   # aproximou: cabe
    assert ok["excedeu_limite"] is False and len(ok["itens"]) == 2


def test_bbox_invalida(client):
    assert client.get("/api/v1/mapa/leads?min_lat=-27").json()["erro"]["codigo"] == "bbox_incompleta"
    assert client.get("/api/v1/mapa/leads?min_lat=1&max_lat=0&min_lng=0&max_lng=1").json()["erro"]["codigo"] == "bbox_invalida"
    assert client.get("/api/v1/mapa/leads?min_lat=-200&max_lat=0&min_lng=0&max_lng=1").status_code == 422


def test_detalhe_expoe_localizacao_com_precisao_e_lista_marca_tem_localizacao(client, fab, db):
    a, _, _, d, e = _dados(fab, db)
    det = client.get(f"/api/v1/leads/{a.id}").json()
    assert det["localizacao"]["precisao"] == "cep" and det["tem_localizacao"] is True
    assert client.get(f"/api/v1/leads/{d.id}").json()["localizacao"] is None      # nao_encontrada
    assert client.get(f"/api/v1/leads/{e.id}").json()["tem_localizacao"] is False  # sem linha de geo
    # o join com a tabela de geo não multiplica linhas
    assert client.get("/api/v1/leads?page_size=100").json()["total"] == 5


def test_constraints_do_banco_recusam_dado_incoerente(fab, db):
    e = fab.empresa("X")
    db.commit()
    casos = [
        dict(latitude=None, longitude=None, status="localizada"),                 # localizada sem coordenadas
        dict(latitude=10.0, longitude=10.0, status="nao_encontrada"),             # coordenada com status não localizado
        dict(latitude=95.0, longitude=10.0, status="localizada"),                 # latitude inválida
        dict(latitude=10.0, longitude=190.0, status="localizada"),                # longitude inválida
        dict(latitude=1.0, longitude=1.0, status="localizada", precisao="rua"),   # precisão desconhecida
    ]
    for kw in casos:
        base = dict(empresa_id=e.id, fonte="t", precisao="municipio")
        base.update(kw)
        db.add(EmpresaGeolocalizacao(**base))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_empresa_so_pode_ter_uma_linha_de_geo(fab, db):
    e = fab.empresa("Y")
    _geo(db, e, 1.0, 1.0)
    db.commit()
    db.add(EmpresaGeolocalizacao(empresa_id=e.id, latitude=2.0, longitude=2.0, fonte="t", precisao="cep", status="localizada"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_consultar_o_mapa_nao_geocodifica_nem_importa_o_geocodificador(client, fab, db):
    _dados(fab, db)
    client.get("/api/v1/mapa/leads")
    client.get("/api/v1/leads")
    assert not [m for m in sys.modules if m.startswith("maintenance")]
