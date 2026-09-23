"""Erros com formato estável: {"erro": {"codigo", "mensagem", "detalhes"}}."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status: int, codigo: str, mensagem: str, detalhes: Optional[Any] = None):
        self.status = status
        self.codigo = codigo
        self.mensagem = mensagem
        self.detalhes = detalhes


def _resposta(status: int, codigo: str, mensagem: str, detalhes: Any = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"erro": {"codigo": codigo, "mensagem": mensagem, "detalhes": detalhes}},
    )


def registrar_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return _resposta(exc.status, exc.codigo, exc.mensagem, exc.detalhes)

    @app.exception_handler(RequestValidationError)
    async def _validacao(_: Request, exc: RequestValidationError):
        detalhes = [
            {"campo": ".".join(str(p) for p in e["loc"] if p != "query"), "mensagem": e["msg"]}
            for e in exc.errors()
        ]
        return _resposta(422, "validacao", "Parâmetros inválidos.", detalhes)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        codigo = {404: "nao_encontrado", 405: "metodo_nao_permitido"}.get(exc.status_code, "http_error")
        return _resposta(exc.status_code, codigo, str(exc.detail))

    @app.exception_handler(Exception)
    async def _inesperado(_: Request, exc: Exception):
        # Não vaza detalhe interno (stack, SQL) para o cliente.
        return _resposta(500, "erro_interno", "Erro interno inesperado.")
