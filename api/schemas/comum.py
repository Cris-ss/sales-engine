from __future__ import annotations

from datetime import datetime
from typing import Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Pagina(BaseModel, Generic[T]):
    itens: list[T]
    total: int
    page: int
    page_size: int


class ErroDetalhe(BaseModel):
    codigo: str
    mensagem: str
    detalhes: Optional[object] = None


class ErroResposta(BaseModel):
    erro: ErroDetalhe


class Opcao(BaseModel):
    codigo: str
    rotulo: str
    total: Optional[int] = None


__all__ = ["Pagina", "ErroResposta", "Opcao", "datetime"]
