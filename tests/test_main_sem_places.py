"""main.py não exige GOOGLE_PLACES_API_KEY globalmente; só o uso real do Places falha."""

from __future__ import annotations

import pytest

import main as pipeline


def test_import_e_etapa1_nao_exigem_chave_places(monkeypatch):
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    # etapa1 não referencia Places: só o import de main precisa funcionar sem a chave.
    assert callable(pipeline.etapa1_buscar_empresas) and callable(pipeline.etapa1_buscar_empresas_osm)


def test_uso_real_do_places_falha_com_erro_explicito(monkeypatch):
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GOOGLE_PLACES_API_KEY não configurado"):
        pipeline.criar_places_discovery()


class _SessaoVazia:
    def query(self, *a, **k):
        return self

    outerjoin = filter = query

    def all(self):
        return []


def test_etapa2_sem_pendentes_nao_exige_chave(monkeypatch):
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    pipeline.etapa2_validar_contato(_SessaoVazia(), pipeline.criar_places_discovery, scraper=None)


def test_etapa2_com_pendentes_sem_chave_falha_explicito_e_nao_marca_erro_places(monkeypatch):
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)

    class Sessao(_SessaoVazia):
        def all(self):
            return [object()]

        def add(self, *_):
            raise AssertionError("não deve gravar Validacao")

    with pytest.raises(ValueError, match="GOOGLE_PLACES_API_KEY não configurado"):
        pipeline.etapa2_validar_contato(Sessao(), pipeline.criar_places_discovery, scraper=None)
