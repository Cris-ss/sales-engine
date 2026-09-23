"""Aplicação FastAPI. Camada de leitura/operação comercial sobre o mesmo banco
do pipeline; NÃO executa etapas do pipeline nem dispara emails.

Rodar (a partir da raiz do projeto):
    uvicorn api.app:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import os

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api import settings
from api.errors import registrar_handlers
from api.routers import filtros, health, kanban, leads, prospeccoes, sistema

PREFIXO = "/api/v1"


def create_app() -> FastAPI:
    app = FastAPI(title="Sales Engine — interface web", version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
    registrar_handlers(app)

    api = APIRouter(prefix=PREFIXO)
    for r in (health.router, filtros.router, leads.router, kanban.router, prospeccoes.router, sistema.router):
        api.include_router(r)
    _registrar_opcionais(api)
    app.include_router(api)

    _servir_frontend(app)
    return app


def _registrar_opcionais(api: APIRouter) -> None:
    # Registra os routers opcionais (fases posteriores e a etapa 7, que depende de
    # etapa7_whatsapp/politica.py): se o módulo não estiver presente, a API sobe
    # sem esse router.
    for nome in ("metricas", "mapa", "exportacoes", "whatsapp"):
        try:
            modulo = __import__(f"api.routers.{nome}", fromlist=["router"])
        except ModuleNotFoundError as exc:
            if exc.name not in (f"api.routers.{nome}", "etapa7_whatsapp.politica"):
                raise
            continue
        api.include_router(modulo.router)


def _servir_frontend(app: FastAPI) -> None:
    dist = settings.WEB_DIST
    if not os.path.isdir(dist):
        return
    app.mount("/assets", StaticFiles(directory=os.path.join(dist, "assets")), name="assets")

    @app.get("/{caminho:path}", include_in_schema=False)
    def spa(caminho: str):
        if caminho.startswith("api/"):
            from api.errors import ApiError

            raise ApiError(404, "nao_encontrado", "Rota de API inexistente.")
        arquivo = os.path.join(dist, caminho)
        if caminho and os.path.isfile(arquivo):
            return FileResponse(arquivo)
        return FileResponse(os.path.join(dist, "index.html"))


app = create_app()
