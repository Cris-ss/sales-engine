"""Descoberta e verificação de empresas via Google Places API.

Pipeline:
    Empresa (CNPJ: nome, município, UF, telefone, logradouro)
        -> Places Text Search (acha o place_id mais provável)
        -> Places Details (telefone, endereço, website do place_id)
        -> verificação: telefone OU rua batem contra o dado da Receita?
            sim -> aceita o resultado (website utilizável)
            não -> descarta (não confiável)

Verificação é obrigatória: parte dos resultados do Places são falsos
positivos (nome parecido, endereço/telefone diferentes, às vezes até em
cidade diferente).
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

import httpx

PLACES_TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

_ABREVIACOES_LOGRADOURO = {
    "r.": "rua",
    "r": "rua",
    "av.": "avenida",
    "av": "avenida",
    "al.": "alameda",
    "al": "alameda",
    "trav.": "travessa",
    "trav": "travessa",
    "rod.": "rodovia",
    "rod": "rodovia",
    "pca.": "praca",
    "pc.": "praca",
    "praça": "praca",
}


@dataclass
class DadosCnpj:
    """Dados de referência vindos da Receita Federal (etapa1_busca)."""

    nome_fantasia: Optional[str]
    razao_social: str
    municipio: str
    uf: str
    logradouro: Optional[str]
    telefone1: Optional[str]
    telefone2: Optional[str] = None


@dataclass
class ResultadoPlaces:
    verificado: bool
    place_id: Optional[str] = None
    telefone_confirmado: Optional[str] = None
    endereco_confirmado: Optional[str] = None
    website: Optional[str] = None
    telefone_bateu: bool = False
    endereco_bateu: bool = False
    motivo: Optional[str] = None


def _normalizar_telefone(telefone: Optional[str]) -> Optional[str]:
    """Remove formatação e normaliza o prefixo '9' de celular BR.

    Ex.: "+55 (11) 91234-5678" e "(11) 1234-5678" devem ser comparáveis.
    Removemos o DDI 55 quando presente e o dígito '9' extra de celular
    (DDD + 9 + 8 dígitos -> DDD + 8 dígitos) para comparar com formatos
    de telefone fixo.
    """
    if not telefone:
        return None

    digitos = re.sub(r"\D", "", telefone)

    if digitos.startswith("55") and len(digitos) > 11:
        digitos = digitos[2:]

    if len(digitos) == 11 and digitos[2] == "9":
        digitos = digitos[:2] + digitos[3:]

    return digitos or None


def _telefones_batem(tel_a: Optional[str], tel_b: Optional[str]) -> bool:
    norm_a = _normalizar_telefone(tel_a)
    norm_b = _normalizar_telefone(tel_b)
    if not norm_a or not norm_b:
        return False
    return norm_a == norm_b


def _normalizar_logradouro(texto: Optional[str]) -> str:
    if not texto:
        return ""
    texto = texto.lower().strip()
    texto = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    for abrev, completo in _ABREVIACOES_LOGRADOURO.items():
        texto = re.sub(rf"\b{re.escape(abrev)}\b", completo, texto)
    texto = re.sub(r"[^a-z0-9 ]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def _extrair_nome_rua(logradouro: Optional[str]) -> str:
    """Extrai só o nome da via, descartando o tipo de logradouro
    (rua/avenida/...) do início, para comparar apenas o "nome próprio"."""
    norm = _normalizar_logradouro(logradouro)
    partes = norm.split(" ", 1)
    tipos_conhecidos = set(_ABREVIACOES_LOGRADOURO.values())
    if len(partes) == 2 and partes[0] in tipos_conhecidos:
        return partes[1]
    return norm


LIMIAR_SIMILARIDADE_RUA = 0.82


def _extrair_rua_do_endereco_places(endereco_completo: Optional[str]) -> str:
    """Isola o nome da via a partir do `formatted_address` do Places, que
    vem como "R. Exemplo, 100 - Bairro, Cidade Exemplo, UF, ...": pega só o
    trecho antes da primeira vírgula e reaplica a mesma extração usada
    para o logradouro da Receita."""
    if not endereco_completo:
        return ""
    primeira_parte = endereco_completo.split(",")[0]
    return _extrair_nome_rua(primeira_parte)


def _similaridade(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _ruas_batem(logradouro_cnpj: Optional[str], endereco_places: Optional[str]) -> bool:
    """Compara o nome da rua da Receita contra o endereço do Places.

    Aceita por substring exata (caso comum) ou por similaridade textual
    (difflib) comparando só os nomes das vias isoladamente — necessário
    porque a base da Receita tem variações/erros de grafia comuns (ex.:
    "Esemplo" vs "Exemplo" da Silva) que não são meras abreviações.
    """
    rua_cnpj = _extrair_nome_rua(logradouro_cnpj)
    if not rua_cnpj:
        return False

    endereco_norm = _normalizar_logradouro(endereco_places)
    if rua_cnpj in endereco_norm:
        return True

    rua_places = _extrair_rua_do_endereco_places(endereco_places)
    if not rua_places:
        return False
    return _similaridade(rua_cnpj, rua_places) >= LIMIAR_SIMILARIDADE_RUA


class PlacesDiscovery:
    def __init__(self, api_key: str, timeout: httpx.Timeout = DEFAULT_TIMEOUT):
        if not api_key:
            raise ValueError("GOOGLE_PLACES_API_KEY não configurado")
        self._api_key = api_key
        self._timeout = timeout

    def _montar_query(self, dados: DadosCnpj) -> str:
        nome = dados.nome_fantasia or dados.razao_social
        return f"{nome} {dados.municipio} {dados.uf}"

    def _text_search(self, query: str) -> Optional[str]:
        params = {"query": query, "key": self._api_key, "language": "pt-BR", "region": "br"}
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.get(PLACES_TEXT_SEARCH_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

        status = data.get("status")
        if status not in ("OK", "ZERO_RESULTS"):
            raise RuntimeError(
                f"Google Places Text Search retornou status={status}: {data.get('error_message')}"
            )

        resultados = data.get("results") or []
        if not resultados:
            return None
        return resultados[0].get("place_id")

    def _place_details(self, place_id: str) -> dict:
        params = {
            "place_id": place_id,
            "key": self._api_key,
            "language": "pt-BR",
            "fields": "formatted_phone_number,international_phone_number,formatted_address,website,name",
        }
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.get(PLACES_DETAILS_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

        status = data.get("status")
        if status != "OK":
            raise RuntimeError(
                f"Google Places Details retornou status={status}: {data.get('error_message')}"
            )
        return data.get("result") or {}

    def descobrir(self, dados: DadosCnpj) -> ResultadoPlaces:
        """Busca a empresa no Google Places e verifica o match contra a
        Receita. Só marca verificado=True se telefone OU rua baterem.

        Observação: verificar só pela rua (`places_telefone_confirmado=False`
        com `places_endereco_confirmado=True`) é mais vulnerável a empresas
        vizinhas no mesmo prédio/quadra. Uma alternativa é tratar a
        verificação "só por rua" com confiança menor do que "por telefone"
        (ex.: não usar o site automaticamente nesse caso sem checagem
        extra); hoje as duas contam igual para `verificado=True`.
        """
        query = self._montar_query(dados)

        place_id = self._text_search(query)
        if not place_id:
            return ResultadoPlaces(verificado=False, motivo="nenhum_resultado_places")

        detalhes = self._place_details(place_id)

        telefone_places = detalhes.get("formatted_phone_number") or detalhes.get(
            "international_phone_number"
        )
        endereco_places = detalhes.get("formatted_address")
        website = detalhes.get("website")

        telefone_bateu = _telefones_batem(dados.telefone1, telefone_places) or _telefones_batem(
            dados.telefone2, telefone_places
        )
        endereco_bateu = _ruas_batem(dados.logradouro, endereco_places)

        verificado = telefone_bateu or endereco_bateu

        return ResultadoPlaces(
            verificado=verificado,
            place_id=place_id,
            telefone_confirmado=telefone_places if verificado else None,
            endereco_confirmado=endereco_places if verificado else None,
            website=website if verificado else None,
            telefone_bateu=telefone_bateu,
            endereco_bateu=endereco_bateu,
            motivo=None if verificado else "nao_verificado_telefone_e_endereco_diferentes",
        )
