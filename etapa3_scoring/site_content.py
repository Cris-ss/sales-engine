"""Extração leve de conteúdo textual de um site já confirmado, para dar
contexto real ao prompt de scoring (etapa3_scoring/scoring.py).

Não usa Google Places — só busca o HTML da home via requests (httpx) e
extrai o texto visível. Se o site não carregar ou vier vazio, retorna
string vazia: o prompt de scoring é instruído a lidar com esse caso
dando um score conservador, em vez de inventar conteúdo.
"""

from __future__ import annotations

from typing import Optional

import httpx
from bs4 import BeautifulSoup

TIMEOUT = httpx.Timeout(15.0, connect=8.0)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
MAX_CARACTERES = 1500


def obter_conteudo_site(url: Optional[str]) -> str:
    if not url:
        return ""
    try:
        with httpx.Client(
            timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as client:
            resp = client.get(url)
        if resp.status_code >= 400:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        texto = soup.get_text(" ", strip=True)
        return texto[:MAX_CARACTERES]
    except httpx.HTTPError:
        return ""
