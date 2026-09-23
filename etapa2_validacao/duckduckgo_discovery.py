"""Descoberta de site institucional via HTML público do DuckDuckGo.

Não prova que uma empresa não tem site: `sem_site` significa apenas que os
cinco primeiros resultados não trouxeram domínio institucional confiável.
"""

from __future__ import annotations

import random
import re
import time
import unicodedata
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from etapa2_validacao.places_discovery import DadosCnpj
from etapa2_validacao.website_scraper import USER_AGENT

DDG_HTML_URL = "https://html.duckduckgo.com/html/"
TIMEOUT = httpx.Timeout(20.0, connect=10.0)
DOMINIOS_NAO_INSTITUCIONAIS = (
    "facebook.com", "instagram.com", "linkedin.com", "youtube.com", "google.com",
    "maps.google.", "guiamais.com.br", "apontador.com.br", "telelistas.net",
    "cnpj.biz", "econodata.com.br", "consultacnpj.com", "reclameaqui.com.br",
)
_STOPWORDS = {"ltda", "me", "eireli", "de", "da", "do", "dos", "das", "e"}


@dataclass
class ResultadoDdg:
    consulta: str
    resultado: str
    dominio_candidato: str | None = None
    website: str | None = None
    posicao_resultado: int | None = None
    confianca: str | None = None
    resultados_resumo: str | None = None
    erro: str | None = None


def _normalizar(valor: str | None) -> str:
    texto = unicodedata.normalize("NFKD", valor or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", texto).strip()


def _tokens_nome(dados: DadosCnpj) -> set[str]:
    nome = _normalizar(dados.nome_fantasia or dados.razao_social)
    return {t for t in nome.split() if len(t) >= 4 and t not in _STOPWORDS}


def _dominio_institucional(dominio: str) -> bool:
    d = dominio.lower().removeprefix("www.")
    return bool(d) and not any(bloqueado in d for bloqueado in DOMINIOS_NAO_INSTITUCIONAIS)


class DuckDuckGoDiscovery:
    """Busca conservadora: espaçamento mínimo entre requisições e retry com backoff exponencial.

    Sequência de espera após rate limit (padrão): ~15s, 30s, 60s, 120s (+ jitter),
    até `max_tentativas` tentativas no total; só então devolve `rate_limit`.
    """

    def __init__(
        self,
        timeout: httpx.Timeout = TIMEOUT,
        intervalo_min: float = 6.0,
        max_tentativas: int = 5,
        backoff_base: float = 15.0,
        jitter: float = 0.25,
        sleep=time.sleep,
        relogio=time.monotonic,
        transport: httpx.BaseTransport | None = None,
    ):
        self._timeout = timeout
        self._intervalo_min = intervalo_min
        self._max_tentativas = max(1, max_tentativas)
        self._backoff_base = backoff_base
        self._jitter = jitter
        self._sleep = sleep
        self._relogio = relogio
        self._transport = transport
        self._ultima_requisicao: float | None = None

    @staticmethod
    def montar_consulta(dados: DadosCnpj) -> str:
        nome = dados.nome_fantasia or dados.razao_social
        return f'"{nome}" "{dados.municipio}" site'

    def _aguardar_intervalo(self) -> None:
        if self._ultima_requisicao is None:
            return
        falta = self._intervalo_min * (1 + random.uniform(0, self._jitter)) - (self._relogio() - self._ultima_requisicao)
        if falta > 0:
            self._sleep(falta)

    def _requisitar(self, consulta: str) -> httpx.Response | ResultadoDdg:
        """Faz a requisição com pacing e retries; devolve a resposta OK ou o ResultadoDdg de falha."""
        ultimo: ResultadoDdg | None = None
        for tentativa in range(self._max_tentativas):
            if tentativa:
                espera = self._backoff_base * (2 ** (tentativa - 1))
                self._sleep(espera * (1 + random.uniform(0, self._jitter)))
            self._aguardar_intervalo()
            try:
                with httpx.Client(
                    timeout=self._timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True,
                    transport=self._transport,
                ) as client:
                    resposta = client.get(DDG_HTML_URL, params={"q": consulta})
            except httpx.HTTPError as exc:
                self._ultima_requisicao = self._relogio()
                ultimo = ResultadoDdg(consulta=consulta, resultado="erro", erro=str(exc))
                continue  # erro transitório de rede: tenta de novo com backoff
            self._ultima_requisicao = self._relogio()
            if resposta.status_code in (202, 403, 429):
                ultimo = ResultadoDdg(consulta=consulta, resultado="rate_limit", erro=f"HTTP {resposta.status_code}")
                continue
            if resposta.status_code >= 400:
                return ResultadoDdg(consulta=consulta, resultado="erro", erro=f"HTTP {resposta.status_code}")
            return resposta
        return ultimo  # type: ignore[return-value]

    def descobrir(self, dados: DadosCnpj) -> ResultadoDdg:
        consulta = self.montar_consulta(dados)
        resposta = self._requisitar(consulta)
        if isinstance(resposta, ResultadoDdg):
            return resposta

        soup = BeautifulSoup(resposta.text, "html.parser")
        resultados: list[tuple[str, str, str]] = []
        for item in soup.select(".result")[:5]:
            link = item.select_one(".result__a")
            if not link or not link.get("href"):
                continue
            url = link["href"]
            # O HTML do DuckDuckGo frequentemente encapsula o destino em
            # /l/?uddg=...; a classificação deve olhar o domínio final.
            query_string = parse_qs(urlparse(url).query)
            url = unquote(query_string.get("uddg", [url])[0])
            dominio = urlparse(url).netloc.lower().removeprefix("www.")
            titulo = link.get_text(" ", strip=True)
            resumo = (item.select_one(".result__snippet") or item).get_text(" ", strip=True)
            resultados.append((url, dominio, f"{titulo} — {resumo}"))

        resumo_resultados = "\n".join(f"{i + 1}. {texto}" for i, (_, _, texto) in enumerate(resultados)) or None
        tokens = _tokens_nome(dados)
        primeiro_ambiguo: tuple[int, str, str] | None = None
        for posicao, (url, dominio, texto) in enumerate(resultados, start=1):
            if not _dominio_institucional(dominio):
                continue
            ocorrencias = sum(token in _normalizar(texto) for token in tokens)
            if ocorrencias:
                confianca = "alta" if ocorrencias >= 2 else "media"
                return ResultadoDdg(consulta, "encontrado", dominio, url, posicao, confianca, resumo_resultados)

            if primeiro_ambiguo is None:
                primeiro_ambiguo = (posicao, dominio, url)

        if primeiro_ambiguo:
            posicao, dominio, url = primeiro_ambiguo
            return ResultadoDdg(consulta, "ambiguo", dominio, url, posicao, "baixa", resumo_resultados)

        if resultados:
            return ResultadoDdg(consulta, "sem_site", resultados_resumo=resumo_resultados)
        return ResultadoDdg(consulta, "sem_site", resultados_resumo=None)
