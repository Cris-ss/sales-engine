"""Cliente para o actor Apify `memo23/cnpj-scraper`.

Fonte de dados aberta da Receita Federal, acessada via API REST do Apify.
Comportamento conhecido do actor:
- Não retorna email.
- Retorna telefone e/ou endereço na maioria dos casos.

O maxItems é limitado a 100 por execução no plano gratuito da Apify. Isso
é tratado aqui como uma constante de plano conhecida (MAX_ITEMS_PER_RUN),
não como um bug a ser contornado silenciosamente.

Filtro de natureza jurídica: "Empresário (Individual)" e EIRELI raramente
têm ficha comercial indexável no Google Places, ao contrário de formas
societárias (LTDA, Sociedade Simples). Esses registros são descartados aqui,
antes de entrarem no banco — o actor suporta um parâmetro nativo `naturezaJuridica`, mas só como filtro de
*inclusão* (busca só os códigos informados), não de exclusão, então o
filtro é aplicado no código, sobre a resposta.
"""

from __future__ import annotations

import time
from typing import Any, Iterator, Optional

import httpx

APIFY_API_BASE = "https://api.apify.com/v2"
ACTOR_ID = "memo23~cnpj-scraper"

MAX_ITEMS_PER_RUN = 100

DEFAULT_TIMEOUT = httpx.Timeout(300.0, connect=30.0)

_UFS_BRASIL = [
    "SP", "RJ", "MG", "RS", "PR", "SC", "BA", "GO", "PE", "CE",
    "DF", "ES", "PA", "AM", "MT", "MS", "MA", "PB", "RN", "AL",
    "PI", "SE", "RO", "TO", "AC", "AP", "RR",
]

# Códigos IBGE de natureza jurídica (campo `natureza_juridica_codigo` no
# retorno do actor) excluídos por raramente terem ficha comercial indexável:
#   2135 - Empresário (Individual)
#   2305 - Empresa Individual de Responsabilidade Limitada (EIRELI, natureza empresária)
#   2313 - Empresa Individual de Responsabilidade Limitada (EIRELI, natureza simples)
NATUREZA_JURIDICA_EXCLUIDA = {"2135", "2305", "2313"}


class ApifyCnpjClientError(RuntimeError):
    pass


def _codigo_natureza_juridica(item: dict[str, Any]) -> Optional[str]:
    codigo = item.get("natureza_juridica_codigo")
    return str(codigo).strip() if codigo is not None else None


def _filtrar_natureza_juridica_excluida(
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Descarta Empresário (Individual) e EIRELI (ver NATUREZA_JURIDICA_EXCLUIDA)."""
    aceitos = []
    descartados = 0
    for item in items:
        if _codigo_natureza_juridica(item) in NATUREZA_JURIDICA_EXCLUIDA:
            descartados += 1
        else:
            aceitos.append(item)
    return aceitos, descartados


class CnpjClient:
    def __init__(self, api_token: str, timeout: httpx.Timeout = DEFAULT_TIMEOUT):
        if not api_token:
            raise ValueError("APIFY_TOKEN não configurado")
        self._token = api_token
        self._timeout = timeout

    def buscar_por_cnae(
        self,
        cnae: str,
        max_items: int = MAX_ITEMS_PER_RUN,
        situacao_cadastral: str = "ATIVA",
        uf: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Roda o actor de forma síncrona e retorna os itens do dataset.

        `max_items` é truncado para MAX_ITEMS_PER_RUN caso passado maior
        que isso, deixando explícito o limite do plano gratuito da Apify
        em vez de deixar a API truncar silenciosamente.
        """
        max_items = min(max_items, MAX_ITEMS_PER_RUN)

        run_input: dict[str, Any] = {
            "cnae": cnae,
            "situacaoCadastral": situacao_cadastral,
            "maxItems": max_items,
        }
        if uf:
            run_input["uf"] = uf

        url = f"{APIFY_API_BASE}/acts/{ACTOR_ID}/run-sync-get-dataset-items"
        params = {"token": self._token}

        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(url, params=params, json=run_input)

        if response.status_code >= 400:
            raise ApifyCnpjClientError(
                f"Apify actor retornou erro {response.status_code}: {response.text[:500]}"
            )

        try:
            items = response.json()
        except ValueError as exc:
            raise ApifyCnpjClientError("Resposta do Apify não é JSON válido") from exc

        if not isinstance(items, list):
            raise ApifyCnpjClientError(f"Formato de resposta inesperado: {type(items)}")

        itens_filtrados, descartados = _filtrar_natureza_juridica_excluida(items)
        print(
            f"[cnpj_client] CNAE {cnae}{f'/{uf}' if uf else ''}: {len(items)} retornados, "
            f"{descartados} descartados por natureza jurídica (Empresário Individual/EIRELI), "
            f"{len(itens_filtrados)} seguem para deduplicação/inserção"
        )

        return itens_filtrados

    def buscar_por_cnae_paginado(
        self,
        cnae: str,
        total_desejado: int,
        situacao_cadastral: str = "ATIVA",
        ufs_para_paginar: Optional[list[str]] = None,
        pausa_entre_runs_seg: float = 1.0,
    ) -> Iterator[dict[str, Any]]:
        """Contorna o limite de MAX_ITEMS_PER_RUN paginando por UF.

        O actor não expõe offset/cursor no plano gratuito, então a
        estratégia é rodar uma vez por UF (cada run já devolve até
        MAX_ITEMS_PER_RUN itens) até atingir `total_desejado` ou esgotar
        a lista de UFs.
        """
        ufs = ufs_para_paginar or _UFS_BRASIL

        emitidos = 0
        for uf_atual in ufs:
            if emitidos >= total_desejado:
                return
            itens = self.buscar_por_cnae(
                cnae=cnae,
                situacao_cadastral=situacao_cadastral,
                uf=uf_atual,
            )
            for item in itens:
                if emitidos >= total_desejado:
                    return
                yield item
                emitidos += 1
            time.sleep(pausa_entre_runs_seg)
