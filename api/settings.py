"""Configuração da API. A URL do banco vem do ambiente; testes de escrita usam
API_DATABASE_URL apontando para um banco cujo nome termina em `_test`."""

from __future__ import annotations

import os

from dotenv import load_dotenv

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(RAIZ, ".env"))

HOST_PADRAO = "127.0.0.1"
PORTA_PADRAO = 8000
WEB_DIST = os.path.join(RAIZ, "web", "dist")


def database_url() -> str:
    return os.environ.get("API_DATABASE_URL") or os.environ["DATABASE_URL"]


def nome_do_banco(url: str) -> str:
    return url.rsplit("/", 1)[-1].split("?", 1)[0]


def banco_eh_de_teste(url: str) -> bool:
    return nome_do_banco(url).endswith("_test")
