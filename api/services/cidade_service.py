"""Autocomplete local dos 5.570 municípios brasileiros."""

from __future__ import annotations

import csv
import os
import unicodedata
from functools import lru_cache

from api import settings

CACHE = os.path.join(settings.RAIZ, "maintenance", "geolocation", "cache")


def _normalizar(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in base if not unicodedata.combining(c)).casefold()


@lru_cache(maxsize=1)
def _municipios() -> list[dict]:
    with open(os.path.join(CACHE, "estados.csv"), encoding="utf-8-sig", newline="") as arquivo:
        ufs = {linha["codigo_uf"]: linha["uf"] for linha in csv.DictReader(arquivo)}
    with open(os.path.join(CACHE, "municipios.csv"), encoding="utf-8-sig", newline="") as arquivo:
        return [
            {
                "nome": linha["nome"], "uf": ufs[linha["codigo_uf"]],
                "rotulo": f'{linha["nome"]}, {ufs[linha["codigo_uf"]]}',
                "latitude": float(linha["latitude"]), "longitude": float(linha["longitude"]),
                "capital": linha["capital"] == "1",
            }
            for linha in csv.DictReader(arquivo)
        ]


def buscar_cidades(termo: str, limite: int = 12) -> list[dict]:
    procurado = _normalizar(termo.strip())
    if not procurado:
        return []
    candidatas = [item for item in _municipios() if procurado in _normalizar(item["nome"])]
    candidatas.sort(key=lambda item: (
        not _normalizar(item["nome"]).startswith(procurado), not item["capital"],
        _normalizar(item["nome"]), item["uf"],
    ))
    return candidatas[:limite]
