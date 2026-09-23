"""Adaptador da etapa6_whatsapp para a API. Reaproveita `whatsapp_link` (módulo
puro, sem banco/IO) — nenhuma lógica de telefone/link é duplicada aqui.

"apto" significa apenas formato de celular brasileiro: NUNCA WhatsApp verificado.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Empresa
from etapa6_whatsapp.whatsapp_link import escolher_telefone, gerar_para_empresa


def telefone_apto(telefone1: Optional[str], telefone2: Optional[str]) -> bool:
    return escolher_telefone(SimpleNamespace(telefone1=telefone1, telefone2=telefone2)).apto


def ids_com_telefone_apto(session: Session) -> set[int]:
    """Ids de empresas com telefone apto a link. Calculado em Python porque a
    regra vive na etapa6 (fonte única); custo desprezível."""
    linhas = session.execute(select(Empresa.id, Empresa.telefone1, Empresa.telefone2)).all()
    return {i for i, t1, t2 in linhas if telefone_apto(t1, t2)}


def link_whatsapp(empresa: Any, nicho_slug: Optional[str], dores: Optional[str]) -> dict:
    r = gerar_para_empresa(empresa, nicho_slug, dores)
    tel = r.telefone
    return {
        "apto": r.apto,
        "verificado": False,
        "telefone_original": tel.original if tel else None,
        "telefone_normalizado": tel.normalizado if tel else None,
        "tipo_telefone": tel.tipo if tel else "ausente",
        "nono_digito_acrescentado": bool(tel and tel.nono_digito_adicionado),
        "motivo_inapto": r.motivo_inapto,
        "mensagem": r.mensagem,
        "link": r.link,
    }
