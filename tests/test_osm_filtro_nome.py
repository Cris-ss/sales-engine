"""Filtro por nome do OSM, com nomes de exemplo. Sem rede."""

from __future__ import annotations

import pytest

from etapa1_busca.osm_client import FILTRO_EM_TAGS, NOME_EXCLUIR, NOME_REGEX, TAGS, TERMOS_BUSCA, passa_filtro_nome

CLINICAS = [
    "Consultório Médico Exemplo", "Clinica Médica", "Gastroenterologia", "Pneumologia e Alergia", "Proctologia", "Cardiologia",
    "Oftalmologia", "Urologia", "Pediatria", "Ortopedia", "Ginecologia", "Otorrinolaringologia", "MedCidade consultas médicas",
    "Clinica Doutor Certo", "Dr Fulano Exemplo - Cardiologista Intervencionista", "Clínica Otorrino Exemplo", "Clínica Dr. Exemplo",
    "Consultórios Médicos Exemplo",
]
NAO_CLINICAS = ["Laboratório Exemplo", "Laboratório de Analises Clínicas", "UBS Unidade de Saúde 03 - Bairro Exemplo", "Centro de Saúde nº 05 de Bairro Exemplo", "Fisio Exemplo", "Saúde Exemplo"]


@pytest.mark.parametrize("nome", CLINICAS)
def test_clinicas_de_exemplo_passam_em_clinicas_medicas(nome):
    assert passa_filtro_nome("clinicas_medicas", nome)


@pytest.mark.parametrize("nome", CLINICAS + NAO_CLINICAS)
def test_nenhum_dos_nomes_de_exemplo_passa_em_nutricao(nome):
    assert not passa_filtro_nome("nutricao", nome)


@pytest.mark.parametrize("nome", NAO_CLINICAS)
def test_laboratorios_e_unidades_publicas_nao_passam_em_clinicas(nome):
    assert not passa_filtro_nome("clinicas_medicas", nome)


def test_nutricionista_de_exemplo_passa_e_psicologia_fisioterapia_reconhecem_os_seus():
    assert passa_filtro_nome("nutricao", "Fulano Exemplo Nutricionista")
    assert passa_filtro_nome("psicologia", "Psico Exemplo")
    assert passa_filtro_nome("fisioterapia", "Fisio Exemplo")
    assert not passa_filtro_nome("clinicas_medicas", "Centro de psiquiatria e psicologia Exemplo")  # vai para psicologia
    assert passa_filtro_nome("psicologia", "Centro de psiquiatria e psicologia Exemplo")


def test_saloes_e_barbearias_nao_se_sobrepoem_e_nichos_sem_regex_nao_filtram():
    for nome in ("Barbearia do Zé", "Studio Ana Estética", "Espaço Spa Zen", "Ana Cabelos"):
        assert passa_filtro_nome("saloes_beauty", nome) != passa_filtro_nome("barbearias_estetica", nome) or nome == "Ana Cabelos"
    assert passa_filtro_nome("contabilidade", "Silva & Associados")
    assert passa_filtro_nome("saloes_beauty", "Ana Cabelos")


def test_construtoras_sem_tags_de_oficio_e_configuracao_consistente():
    assert ("shop", "trade") not in TAGS["construtoras"] and ("craft", "electrician") not in TAGS["construtoras"]
    assert set(FILTRO_EM_TAGS) <= set(TAGS)
    assert set(NOME_REGEX) | set(NOME_EXCLUIR) <= set(TAGS)
    assert set(TERMOS_BUSCA) <= set(NOME_REGEX)  # todo fallback textual é filtrado
    assert {"nutricao"} and ("amenity", "doctors") not in TAGS["nutricao"]


def test_deduplicacao_por_nome_e_coordenada_no_fallback_nominatim():
    from etapa1_busca.osm_client import OsmClient, chave_local

    def item(osm_type, osm_id, nome, lat, lon):
        return {"osm_type": osm_type, "osm_id": osm_id, "name": nome, "lat": lat, "lon": lon}

    itens = [
        item("node", 1, "Smart Fit", "-23.55001", "-46.63001"),
        item("way", 2, "SMART FIT", "-23.55003", "-46.63004"),   # mesmo local (nó + polígono): duplicata
        item("node", 3, "Smart Fit", "-23.56500", "-46.65000"),   # filial em outro endereço: fica
    ]
    r = OsmClient._converter_nominatim(itens, "Cidade Exemplo", "SP", 50, nicho_slug=None)
    assert [e.externo_id for e in r] == ["node/1", "node/3"]
    assert chave_local("Exemplo Lab", -23.55001, -46.63001) == chave_local("EXEMPLO LAB", -23.55003, -46.63004)
