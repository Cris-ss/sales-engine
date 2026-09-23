"""Warm-up de envio: calcula quantos emails podem sair HOJE, com base em
há quantos dias o warm-up começou (`WARMUP_START_DATE`, formato YYYY-MM-DD).

Curva (dias desde o início, inclusive):
    0-2   -> 5/dia
    3-6   -> 10/dia
    7-9   -> 15/dia
    10-13 -> 25/dia
    14-17 -> 35/dia
    18+   -> 50/dia
"""

from __future__ import annotations

import os
from datetime import date, datetime

# (dias_maximo_do_degrau, limite_de_envios_no_degrau), verificados em ordem;
# o primeiro degrau cujo teto cobre `dias_desde_inicio` vence.
_DEGRAUS = [
    (2, 5),
    (6, 10),
    (9, 15),
    (13, 25),
    (17, 35),
]
_LIMITE_MAXIMO = 50


def _data_inicio() -> date:
    valor = os.getenv("WARMUP_START_DATE")
    if not valor:
        raise RuntimeError(
            "WARMUP_START_DATE não configurada no .env. Defina a data do primeiro "
            "envio real (formato YYYY-MM-DD) antes de rodar o envio de verdade — "
            "isso existe justamente para não mandar em volume alto sem o warm-up "
            "ter começado. Para testar sem essa trava, use --limite-manual."
        )
    try:
        return datetime.strptime(valor, "%Y-%m-%d").date()
    except ValueError as exc:
        raise RuntimeError(
            f"WARMUP_START_DATE inválida: {valor!r}. Use o formato YYYY-MM-DD."
        ) from exc


def limite_diario_hoje() -> int:
    inicio = _data_inicio()
    dias_desde_inicio = (date.today() - inicio).days

    if dias_desde_inicio < 0:
        raise RuntimeError(
            f"WARMUP_START_DATE ({inicio.isoformat()}) está no futuro. Corrija a "
            "data no .env antes de enviar."
        )

    for teto_dias, limite in _DEGRAUS:
        if dias_desde_inicio <= teto_dias:
            return limite
    return _LIMITE_MAXIMO
