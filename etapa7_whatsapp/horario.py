"""Janela de envio (dias/horas no fuso da conta). Puro, sem banco."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


def _hm(texto: str) -> time:
    h, m = texto.split(":")
    return time(int(h), int(m))


def dentro_da_janela(agora_utc: datetime, tz: str, limites: dict) -> bool:
    local = agora_utc.astimezone(ZoneInfo(tz))
    return (
        local.weekday() in limites["dias_semana"]
        and _hm(limites["hora_inicio"]) <= local.time().replace(second=0, microsecond=0) < _hm(limites["hora_fim"])
    )


def proximo_inicio(agora_utc: datetime, tz: str, limites: dict) -> datetime:
    """Primeiro instante (UTC) com a janela aberta; se já aberta, o próprio `agora_utc`."""
    if dentro_da_janela(agora_utc, tz, limites):
        return agora_utc
    zona = ZoneInfo(tz)
    local = agora_utc.astimezone(zona)
    inicio = _hm(limites["hora_inicio"])
    for dias in range(0, 9):
        dia = (local + timedelta(days=dias)).date()
        candidato = datetime.combine(dia, inicio, tzinfo=zona)
        if candidato > local and candidato.weekday() in limites["dias_semana"]:
            return candidato.astimezone(agora_utc.tzinfo)
    raise ValueError("Nenhum dia da semana habilitado na janela de envio")
