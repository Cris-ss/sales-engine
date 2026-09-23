"""Rate limit do DuckDuckGo: pacing + backoff. Sem rede: transporte simulado e sleep falso."""

from __future__ import annotations

import httpx

from etapa2_validacao.duckduckgo_discovery import DuckDuckGoDiscovery
from etapa2_validacao.places_discovery import DadosCnpj

HTML_OK = '<div class="result"><a class="result__a" href="https://www.acme.com.br/">Acme Contabil</a><div class="result__snippet">Acme Contabil site</div></div>'
DADOS = DadosCnpj("Acme Contabil", "Acme LTDA", "Cidade Exemplo", "PR", None, None, None)


def _discovery(statuses, **kw):
    chamadas = []
    esperas = []
    fila = list(statuses)

    def handler(request):
        chamadas.append(request)
        status = fila.pop(0) if fila else fila_final
        return httpx.Response(status, text=HTML_OK if status == 200 else "")

    fila_final = statuses[-1]
    d = DuckDuckGoDiscovery(transport=httpx.MockTransport(handler), sleep=esperas.append, **kw)
    return d, chamadas, esperas


def test_rate_limit_transitorio_se_recupera_com_backoff():
    d, chamadas, esperas = _discovery([429, 202, 200], jitter=0)
    r = d.descobrir(DADOS)
    assert r.resultado == "encontrado" and r.dominio_candidato == "acme.com.br"
    assert len(chamadas) == 3
    assert [e for e in esperas if e >= 15] == [15.0, 30.0]  # exponencial


def test_rate_limit_persistente_devolve_rate_limit_apos_max_tentativas():
    d, chamadas, _ = _discovery([429], max_tentativas=3, jitter=0)
    r = d.descobrir(DADOS)
    assert r.resultado == "rate_limit" and r.erro == "HTTP 429"
    assert len(chamadas) == 3


def test_erro_definitivo_nao_faz_retry():
    d, chamadas, _ = _discovery([500])
    assert d.descobrir(DADOS).resultado == "erro" and len(chamadas) == 1


def test_erro_de_rede_tenta_de_novo():
    n = {"i": 0}

    def handler(request):
        n["i"] += 1
        if n["i"] == 1:
            raise httpx.ConnectError("falhou", request=request)
        return httpx.Response(200, text=HTML_OK)

    d = DuckDuckGoDiscovery(transport=httpx.MockTransport(handler), sleep=lambda s: None, jitter=0)
    assert d.descobrir(DADOS).resultado == "encontrado" and n["i"] == 2


def test_intervalo_minimo_entre_consultas_seguidas():
    t = {"agora": 100.0}
    esperas = []

    def sleep(s):
        esperas.append(s)
        t["agora"] += s

    d = DuckDuckGoDiscovery(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=HTML_OK)),
        sleep=sleep, relogio=lambda: t["agora"], intervalo_min=6.0, jitter=0,
    )
    d.descobrir(DADOS)
    assert esperas == []  # primeira consulta não espera
    d.descobrir(DADOS)
    assert esperas == [6.0]
