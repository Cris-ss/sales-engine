"""Fontes de coordenadas. Nada aqui é chamado ao abrir a interface: só o comando
de manutenção `python -m maintenance.geolocation.geocodificar` usa estas funções.

- Município: dataset público derivado do IBGE (kelvins/municipios-brasileiros),
  com a coordenada da SEDE do município. Não é o endereço da empresa nem um
  centroide geométrico do polígono — por isso a precisão é rotulada "municipio".
- CEP: AwesomeAPI (gratuita, sem chave, sem SLA). Devolve ponto aproximado do CEP.
"""

from __future__ import annotations

import csv
import io
import math
import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

import httpx

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
URL_MUNICIPIOS = "https://raw.githubusercontent.com/kelvins/municipios-brasileiros/main/csv/municipios.csv"
URL_ESTADOS = "https://raw.githubusercontent.com/kelvins/municipios-brasileiros/main/csv/estados.csv"
URL_CEP = "https://cep.awesomeapi.com.br/json/{cep}"
USER_AGENT = "sales-engine-geocoder/1.0 (uso local, baixo volume)"

# caixa aproximada do Brasil (inclui ilhas oceânicas próximas): descarta lixo como 0,0
BRASIL_LAT = (-34.0, 6.0)
BRASIL_LNG = (-74.5, -28.0)
DISTANCIA_MAX_KM_CEP_X_MUNICIPIO = 60.0


def normalizar(texto: Optional[str]) -> str:
    if not texto:
        return ""
    t = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    t = re.sub(r"[^A-Za-z0-9]+", " ", t).upper()
    return re.sub(r"\s+", " ", t).strip()


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def dentro_do_brasil(lat: float, lng: float) -> bool:
    return BRASIL_LAT[0] <= lat <= BRASIL_LAT[1] and BRASIL_LNG[0] <= lng <= BRASIL_LNG[1]


def _baixar_com_cache(url: str, nome: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    caminho = os.path.join(CACHE_DIR, nome)
    if not os.path.exists(caminho):
        r = httpx.get(url, timeout=60, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        with open(caminho, "wb") as f:
            f.write(r.content)
    with open(caminho, "r", encoding="utf-8-sig") as f:
        return f.read()


def carregar_indice_municipios() -> dict[tuple[str, str], tuple[float, float]]:
    """{(NOME NORMALIZADO, UF): (lat, lng)} da sede de cada município brasileiro."""
    estados = {row["codigo_uf"]: row["uf"] for row in csv.DictReader(io.StringIO(_baixar_com_cache(URL_ESTADOS, "estados.csv")))}
    indice: dict[tuple[str, str], tuple[float, float]] = {}
    for row in csv.DictReader(io.StringIO(_baixar_com_cache(URL_MUNICIPIOS, "municipios.csv"))):
        uf = estados.get(row["codigo_uf"])
        if uf:
            indice[(normalizar(row["nome"]), uf)] = (float(row["latitude"]), float(row["longitude"]))
    return indice


@dataclass
class ResultadoCep:
    status: str  # localizada | nao_encontrada | invalida | erro
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    erro: Optional[str] = None
    fatal: bool = False  # True = parar o lote (ex.: limite de requisições)


def consultar_cep(cep: Optional[str], cliente: httpx.Client) -> ResultadoCep:
    digitos = re.sub(r"\D", "", cep or "")
    if len(digitos) != 8:
        return ResultadoCep("invalida", erro=f"CEP com {len(digitos)} dígitos")
    try:
        r = cliente.get(URL_CEP.format(cep=digitos), timeout=20)
    except httpx.HTTPError as exc:
        return ResultadoCep("erro", erro=f"{type(exc).__name__}: {exc}")
    if r.status_code == 404:
        return ResultadoCep("nao_encontrada", erro="CEP não encontrado na fonte")
    if r.status_code == 429:
        return ResultadoCep("erro", erro="429 limite de requisições", fatal=True)
    if r.status_code != 200:
        return ResultadoCep("erro", erro=f"HTTP {r.status_code}")
    try:
        j = r.json()
        lat, lng = float(j.get("lat")), float(j.get("lng"))
    except (ValueError, TypeError):
        return ResultadoCep("nao_encontrada", erro="fonte sem coordenadas")
    if lat == 0.0 and lng == 0.0:
        return ResultadoCep("nao_encontrada", erro="fonte devolveu 0,0")
    if not dentro_do_brasil(lat, lng):
        return ResultadoCep("nao_encontrada", erro=f"coordenada fora do Brasil ({lat}, {lng})")
    return ResultadoCep("localizada", lat, lng)
