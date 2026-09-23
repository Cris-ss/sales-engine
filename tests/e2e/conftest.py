"""E2E de navegador: sobe a API (uvicorn) apontando para o banco `_test` e serve
o build do frontend (web/dist). NUNCA usa o banco real."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request

import pytest

from tests.conftest import RAIZ, _url_teste  # noqa: F401  (reusa a trava do banco de teste)

PORTA = 8765
BASE = f"http://127.0.0.1:{PORTA}"


@pytest.fixture(scope="session")
def servidor(engine):
    dist = os.path.join(RAIZ, "web", "dist", "index.html")
    if not os.path.exists(dist):
        pytest.skip("Rode `npm run build` em web/ antes dos testes E2E.")
    env = {**os.environ, "API_DATABASE_URL": _url_teste()}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.app:app", "--host", "127.0.0.1", "--port", str(PORTA), "--log-level", "warning"],
        cwd=RAIZ, env=env,
    )
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{BASE}/api/v1/health", timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    else:
        proc.kill()
        raise RuntimeError("API de teste não subiu")
    yield BASE
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="session")
def navegador():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture()
def contexto(navegador):
    c = navegador.new_context(
        locale="pt-BR", timezone_id="America/Sao_Paulo", accept_downloads=True, viewport={"width": 1500, "height": 950}
    )
    # nunca sair para a internet: wa.me é interceptado
    c.route("https://wa.me/**", lambda r: r.fulfill(status=200, body="wa.me (interceptado no teste)"))
    yield c
    c.close()


@pytest.fixture()
def pagina(contexto):
    return contexto.new_page()
