"""Tela Sistema no navegador. As chamadas de /sistema são SIMULADAS (route): nenhum comando real do PM2 é executado."""

from __future__ import annotations

import json

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def _proc(nome, rotulo, estado="rodando", pid=100, uptime=125, reinicios=0, mem=42.5):
    return {"nome": nome, "rotulo": rotulo, "registrado": estado != "nao_iniciado", "estado": estado, "status_pm2": estado, "pid": pid,
            "uptime_seg": uptime if estado == "rodando" else None, "reinicios": reinicios, "memoria_mb": mem, "cpu_pct": 0.5}


class Falso:
    """Estado simulado dos processos + registro do que a tela pediu."""

    def __init__(self):
        self.api_pid = 100
        self.processos_ok = True
        self.posts = []

    def processos(self):
        return {"pm2_disponivel": True, "erro": None, "processos": [
            _proc("sales-api", "API (interface e endpoints)", pid=self.api_pid),
            _proc("sales-worker", "Worker (IA e tarefas do WhatsApp)", estado="parado", pid=None, reinicios=2),
            _proc("sales-gateway", "Gateway (conexão com o WhatsApp)", estado="erro", pid=None, reinicios=10),
        ]}


def _instalar(pagina, falso: Falso):
    def tratar(rota):
        req = rota.request
        caminho = req.url.split("/api/v1/sistema", 1)[1].split("?")[0]
        if req.method == "GET" and caminho == "/processos":
            return rota.fulfill(status=200, content_type="application/json", body=json.dumps(falso.processos()))
        if req.method == "GET" and caminho.endswith("/logs"):
            nome = caminho.split("/")[2]
            corpo = {"saida": [f"[{nome}] linha de saída 1", f"[{nome}] linha de saída 2"], "erros": [f"[{nome}] ERRO simulado"],
                     "arquivos": {"saida": f"logs/{nome}.out.log", "erros": f"logs/{nome}.err.log"}}
            return rota.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))
        if req.method == "POST":
            falso.posts.append(caminho)
            if caminho == "/processos/sales-api/reiniciar":
                falso.api_pid = 555  # "reiniciou": o pid muda
                return rota.fulfill(status=200, content_type="application/json",
                                    body=json.dumps({"ok": True, "reiniciando": True, "processo": "sales-api", "mensagem": "Reinício da API disparado."}))
            return rota.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "saida": "ok", "reiniciando": False, "resultados": {}}))
        return rota.continue_()

    pagina.route("**/api/v1/sistema/**", tratar)


def test_cartoes_mostram_status_e_so_oferecem_as_acoes_certas(servidor, pagina):
    falso = Falso()
    _instalar(pagina, falso)
    pagina.goto(f"{servidor}/sistema")
    api = pagina.locator('[data-processo="sales-api"]')
    worker = pagina.locator('[data-processo="sales-worker"]')
    gateway = pagina.locator('[data-processo="sales-gateway"]')
    expect(api).to_contain_text("Rodando")
    expect(api).to_contain_text("2min 5s")
    expect(worker).to_contain_text("Parado")
    expect(gateway).to_contain_text("COM ERRO")
    expect(gateway).to_contain_text("O PM2 desistiu após várias falhas")
    # API: só reiniciar (nunca parar); parado: iniciar; com erro: iniciar/reiniciar
    expect(api.get_by_role("button", name="Parar", exact=True)).to_have_count(0)
    expect(api.get_by_role("button", name="Reiniciar", exact=True)).to_be_visible()
    expect(worker.get_by_role("button", name="Iniciar", exact=True)).to_be_visible()
    expect(pagina.get_by_role("link", name="Sistema")).to_be_visible()


def test_reiniciar_worker_e_iniciar_chamam_os_endpoints(servidor, pagina):
    falso = Falso()
    _instalar(pagina, falso)
    pagina.goto(f"{servidor}/sistema")
    pagina.locator('[data-processo="sales-worker"]').get_by_role("button", name="Reiniciar", exact=True).click()
    expect(pagina.get_by_text("reiniciado.")).to_be_visible()
    pagina.locator('[data-processo="sales-worker"]').get_by_role("button", name="Iniciar", exact=True).click()
    pagina.once("dialog", lambda d: d.accept())
    pagina.get_by_role("button", name="Parar tudo (worker e gateway)").click()
    pagina.wait_for_timeout(500)
    assert "/processos/sales-worker/reiniciar" in falso.posts and "/processos/sales-worker/iniciar" in falso.posts
    assert "/tudo/parar" in falso.posts


def test_logs_do_processo_escolhido_com_saida_e_erros(servidor, pagina):
    falso = Falso()
    _instalar(pagina, falso)
    pagina.goto(f"{servidor}/sistema")
    pre = pagina.get_by_label("Logs de sales-worker")
    expect(pre).to_contain_text("[sales-worker] linha de saída 2")
    pagina.locator('[data-processo="sales-gateway"]').get_by_role("button", name="Ver logs").click()
    expect(pagina.get_by_label("Logs de sales-gateway")).to_contain_text("[sales-gateway] linha de saída 1")
    pagina.get_by_label("Arquivo").select_option("erros")
    expect(pagina.get_by_label("Logs de sales-gateway")).to_contain_text("ERRO simulado")


def test_reiniciar_a_api_mostra_aviso_reconecta_sozinho_e_some(servidor, pagina):
    falso = Falso()
    _instalar(pagina, falso)
    pagina.goto(f"{servidor}/sistema")
    pagina.locator('[data-processo="sales-api"]').get_by_role("button", name="Reiniciar", exact=True).click()
    expect(pagina.get_by_text("Reiniciando a API…")).to_be_visible()  # a resposta confirmou ANTES do restart
    expect(pagina.get_by_text("API reiniciada e reconectada.")).to_be_visible(timeout=10_000)  # pid novo + /health ok
    expect(pagina.get_by_text("Reiniciando a API…")).to_have_count(0)
    assert falso.posts == ["/processos/sales-api/reiniciar"]


def test_sem_pm2_a_tela_explica_como_instalar(servidor, pagina):
    pagina.route("**/api/v1/sistema/processos", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(
        {"pm2_disponivel": False, "erro": "PM2 não encontrado. Instale com `npm install -g pm2`", "processos": []})))
    pagina.goto(f"{servidor}/sistema")
    expect(pagina.get_by_text("PM2 indisponível.")).to_be_visible()
    expect(pagina.get_by_text("pm2 start ecosystem.config.cjs")).to_be_visible()
