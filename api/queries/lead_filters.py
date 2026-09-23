"""Filtros compartilhados: mesma semântica em lista, Kanban, métricas, mapa e
exportação. `ignorar` permite ao Kanban/métricas desconsiderar coluna/estágio
(para contar todas as colunas dentro do mesmo universo filtrado)."""

from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import and_, false, func, not_, or_, true

from api.dominio import COLUNA_ESTAGIOS
from api.dependencies import FiltrosLeads, so_digitos
from api.queries.lead_projection import LeadProjection


def precisa_ids_whatsapp(f: FiltrosLeads) -> bool:
    return f.canal in ("whatsapp", "ambos", "sem_canal")


def condicoes(
    p: LeadProjection,
    f: FiltrosLeads,
    ids_whatsapp: Optional[set[int]] = None,
    ignorar: Iterable[str] = (),
) -> list:
    ignorar = set(ignorar)
    E, V = p.E, p.V
    c: list = []

    if f.q:
        termo = f.q
        opcoes = [E.nome_fantasia.icontains(termo, autoescape=True), E.razao_social.icontains(termo, autoescape=True)]
        digitos = so_digitos(termo)
        if len(digitos) >= 3:
            opcoes.append(E.cnpj.contains(digitos, autoescape=True))
            for tel in (E.telefone1, E.telefone2):
                opcoes.append(func.regexp_replace(tel, r"\D", "", "g").contains(digitos, autoescape=True))
        c.append(or_(*opcoes))

    if f.nicho_id is not None:
        c.append(E.nicho_id == f.nicho_id)
    if f.uf:
        c.append(E.uf == f.uf)
    if f.municipio:
        c.append(func.lower(E.municipio) == f.municipio.lower())

    if f.score_min is not None:
        c.append(p.score >= f.score_min)
    if f.score_max is not None:
        c.append(p.score <= f.score_max)
    if f.sem_score is True:
        c.append(p.score.is_(None))
    elif f.sem_score is False:
        c.append(p.score.isnot(None))
    if f.faixa:
        c.append(p.faixa == f.faixa)

    if f.canal:
        wpp = E.id.in_(ids_whatsapp) if ids_whatsapp else false()
        if f.canal == "email":
            c.append(p.email_confirmado)
        elif f.canal == "formulario":
            c.append(p.formulario_confirmado)
        elif f.canal == "whatsapp":
            c.append(wpp)
        elif f.canal == "ambos":
            c.append(and_(p.email_confirmado, wpp))
        elif f.canal == "sem_canal":
            c.append(and_(not_(p.email_confirmado), not_(p.formulario_confirmado), not_(wpp)))

    if f.coluna and "coluna" not in ignorar:
        c.append(p.estagio.in_(COLUNA_ESTAGIOS[f.coluna]))
    if f.estagio and "estagio" not in ignorar:
        c.append(p.estagio == f.estagio)
    if f.email_status:
        c.append(p.email_status == f.email_status)
    if f.site_ddg:
        c.append(p.site_ddg == f.site_ddg)
    if f.data_inicio_de:
        c.append(p.data_inicio_atividade >= f.data_inicio_de)
    if f.data_inicio_ate:
        c.append(p.data_inicio_atividade <= f.data_inicio_ate)

    return c
