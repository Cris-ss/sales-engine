"""Descoberta de estabelecimentos por nicho usando Google Places Text Search."""

from __future__ import annotations

import time

import httpx

from etapa1_busca.osm_client import EmpresaOsm
from etapa2_validacao.places_discovery import PLACES_DETAILS_URL, PLACES_TEXT_SEARCH_URL


class GooglePlacesClient:
    def __init__(self, api_key: str, transport: httpx.BaseTransport | None = None):
        if not api_key:
            raise ValueError("GOOGLE_PLACES_API_KEY não configurado")
        self._api_key = api_key
        self._transport = transport

    @staticmethod
    def _endereco(componentes: list[dict], tipo: str) -> str | None:
        for componente in componentes:
            if tipo in componente.get("types", []):
                return componente.get("short_name") or componente.get("long_name")
        return None

    def _detalhes(self, client: httpx.Client, place_id: str) -> dict:
        resposta = client.get(PLACES_DETAILS_URL, params={
            "place_id": place_id, "key": self._api_key, "language": "pt-BR",
            "fields": "name,formatted_address,address_component,geometry,formatted_phone_number,international_phone_number,website",
        })
        resposta.raise_for_status()
        dados = resposta.json()
        if dados.get("status") != "OK":
            return {}
        return dados.get("result") or {}

    def buscar(self, termo: str, cidade: str, uf: str, limite: int) -> list[EmpresaOsm]:
        limite = min(limite, 60)
        resultados: list[dict] = []
        token: str | None = None
        with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), transport=self._transport) as client:
            while len(resultados) < limite:
                params = {"key": self._api_key, "language": "pt-BR", "region": "br"}
                if token:
                    params["pagetoken"] = token
                else:
                    params["query"] = f"{termo} {cidade} {uf}"
                resposta = client.get(PLACES_TEXT_SEARCH_URL, params=params)
                resposta.raise_for_status()
                dados = resposta.json()
                status = dados.get("status")
                if status == "ZERO_RESULTS":
                    break
                if status != "OK":
                    raise RuntimeError(f"Google Places Text Search retornou status={status}: {dados.get('error_message')}")
                resultados.extend(dados.get("results") or [])
                token = dados.get("next_page_token")
                if not token or len(resultados) >= limite:
                    break
                time.sleep(2)

            empresas: list[EmpresaOsm] = []
            vistos: set[str] = set()
            for resumo in resultados[:limite]:
                place_id = resumo.get("place_id")
                if not place_id or place_id in vistos:
                    continue
                vistos.add(place_id)
                detalhes = self._detalhes(client, place_id)
                dados = {**resumo, **detalhes}
                geometria = (dados.get("geometry") or {}).get("location") or {}
                if not dados.get("name") or "lat" not in geometria or "lng" not in geometria:
                    continue
                componentes = dados.get("address_components") or []
                empresas.append(EmpresaOsm(
                    externo_id=f"google/{place_id}", nome=dados["name"],
                    municipio=self._endereco(componentes, "administrative_area_level_2") or self._endereco(componentes, "locality") or cidade,
                    uf=self._endereco(componentes, "administrative_area_level_1") or uf,
                    logradouro=self._endereco(componentes, "route"), numero=self._endereco(componentes, "street_number"),
                    bairro=self._endereco(componentes, "sublocality_level_1") or self._endereco(componentes, "sublocality"),
                    cep=self._endereco(componentes, "postal_code"),
                    telefone=dados.get("formatted_phone_number") or dados.get("international_phone_number"),
                    website=dados.get("website"), latitude=float(geometria["lat"]), longitude=float(geometria["lng"]),
                ))
        return empresas
