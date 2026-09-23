"""Métricas comerciais. Todas contam EMPRESAS DISTINTAS (a projeção tem 1 linha
por empresa), então múltiplos contatos/scores/históricos não inflam nada.

Estoque atual x trajetória histórica são coisas diferentes e nunca são
misturadas: `atual` = onde cada empresa está hoje; `historico_passagem` =
quantas empresas distintas já tiveram uma linha em funil_status naquele estágio
(só linhas reais; o estágio derivado de email enviado não entra no histórico).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from api.adapters.whatsapp_adapter import ids_com_telefone_apto
from api.dependencies import FiltrosLeads
from api.dominio import COLUNA_ESTAGIOS, COLUNA_ROTULOS, COLUNAS_ORDEM, ESTAGIO_COLUNA, ESTAGIO_ROTULOS, ESTAGIOS
from api.queries.lead_filters import condicoes
from api.queries.lead_projection import LeadProjection
from db.models import EstagioFunil, FunilStatus, Nicho

DEFINICOES = {
    "total_empresas": "Empresas no universo filtrado.",
    "com_email_confirmado": "Empresas com email confirmado e canal ativo (não inclui as retiradas do fluxo por site não confirmado).",
    "com_formulario": "Empresas com formulário de contato confirmado.",
    "com_telefone_apto": "Empresas com telefone em formato de celular, aptas a gerar link wa.me. NÃO significa WhatsApp verificado.",
    "com_score": "Empresas com pelo menos um score (o vigente é o mais recente).",
    "empresas_com_email_enviado": "Empresas distintas com ao menos um email aceito pelo SMTP (não comprova entrega, leitura ou resposta).",
    "mensagens_email_enviadas": "Quantidade total de emails aceitos pelo SMTP (uma empresa pode ter mais de uma).",
    "em_ganho_atual": "Empresas cujo estágio atual é 'venda'.",
    "atual": "Distribuição ATUAL: onde cada empresa está hoje. Não é taxa de progressão.",
    "historico_passagem": "Empresas distintas que já passaram por cada estágio (linhas reais de funil_status).",
    "conversao": "Conversão comercial = empresas atualmente em 'venda' ÷ empresas do grupo no universo filtrado. Não é validação de canal.",
}


def _conds(session: Session, p: LeadProjection, f: FiltrosLeads, ignorar=()):
    from api.services.lead_service import montar_condicoes

    return montar_condicoes(session, p, f, ignorar)


def resumo(session: Session, f: FiltrosLeads) -> dict:
    p = LeadProjection()
    conds = _conds(session, p, f)
    ids_wpp = ids_com_telefone_apto(session)

    linha = session.execute(
        select(
            func.count(p.E.id),
            func.count().filter(p.email_confirmado),
            func.count().filter(p.formulario_confirmado),
            func.count().filter(p.E.id.in_(ids_wpp)) if ids_wpp else func.count().filter(p.E.id.is_(None)),
            func.count().filter(p.score.isnot(None)),
            func.count().filter(p.qtd_enviados > 0),
            func.coalesce(func.sum(p.qtd_enviados), 0),
            func.count().filter(p.estagio == "venda"),
        )
        .select_from(p.join)
        .where(*conds)
    ).one()

    estagios = {e: 0 for e in ESTAGIOS}
    matriz: dict[str, dict[str, int]] = {}
    for nicho_slug, nicho_nome, coluna, estagio, n in session.execute(
        select(p.N.slug, p.N.nome, p.coluna, p.estagio, func.count())
        .select_from(p.join)
        .where(*conds)
        .group_by(p.N.slug, p.N.nome, p.coluna, p.estagio)
    ).all():
        estagios[estagio] += n
        m = matriz.setdefault(nicho_slug, {"nicho_nome": nicho_nome, **{c: 0 for c in COLUNAS_ORDEM}})
        m[coluna] += n

    return {
        "total_empresas": linha[0],
        "com_email_confirmado": linha[1],
        "com_formulario": linha[2],
        "com_telefone_apto": linha[3],
        "com_score": linha[4],
        "empresas_com_email_enviado": linha[5],
        "mensagens_email_enviadas": int(linha[6]),
        "em_ganho_atual": linha[7],
        "por_estagio": [{"estagio": e, "rotulo": ESTAGIO_ROTULOS[e], "coluna": ESTAGIO_COLUNA[e], "total": estagios[e]} for e in ESTAGIOS],
        "por_nicho_e_coluna": [
            {"nicho_slug": slug, **{"nicho_nome": v["nicho_nome"]}, "colunas": {c: v[c] for c in COLUNAS_ORDEM}}
            for slug, v in sorted(matriz.items())
        ],
        "definicoes": DEFINICOES,
    }


def funil(session: Session, f: FiltrosLeads) -> dict:
    p = LeadProjection()
    conds = _conds(session, p, f)

    atual = {e: 0 for e in ESTAGIOS}
    total = 0
    for estagio, n in session.execute(
        select(p.estagio, func.count()).select_from(p.join).where(*conds).group_by(p.estagio)
    ).all():
        atual[estagio] += n
        total += n

    universo = select(p.E.id).select_from(p.join).where(*conds)
    passagem = {e: 0 for e in ESTAGIOS}
    for estagio, n in session.execute(
        select(FunilStatus.estagio, func.count(distinct(FunilStatus.empresa_id)))
        .where(FunilStatus.empresa_id.in_(universo))
        .group_by(FunilStatus.estagio)
    ).all():
        passagem[estagio.value if isinstance(estagio, EstagioFunil) else str(estagio).lower()] = n

    return {
        "total_empresas": total,
        "atual": [{"estagio": e, "rotulo": ESTAGIO_ROTULOS[e], "total": atual[e]} for e in ESTAGIOS],
        "atual_por_coluna": [
            {"coluna": c, "rotulo": COLUNA_ROTULOS[c], "total": sum(atual[e] for e in COLUNA_ESTAGIOS[c])} for c in COLUNAS_ORDEM
        ],
        "historico_passagem": [{"estagio": e, "rotulo": ESTAGIO_ROTULOS[e], "empresas_distintas": passagem[e]} for e in ESTAGIOS],
        "definicoes": {"atual": DEFINICOES["atual"], "historico_passagem": DEFINICOES["historico_passagem"]},
    }


def conversao(session: Session, f: FiltrosLeads, nivel: str, limite: Optional[int] = None) -> dict:
    p = LeadProjection()
    conds = _conds(session, p, f)
    ganhos = func.count().filter(p.estagio == "venda")

    if nivel == "nicho":
        stmt = (
            select(p.N.slug.label("chave"), p.N.nome.label("rotulo"), func.count().label("total"), ganhos.label("ganhos"))
            .select_from(p.join).where(*conds).group_by(p.N.slug, p.N.nome)
        )
        linhas = session.execute(stmt).all()
        grupos = [(c, r, None, None, t, g) for c, r, t, g in linhas]
        # Nicho sem nenhuma empresa no universo filtrado aparece com 0 => "N/A" (não some da tela).
        presentes = {c for c, *_ in grupos}
        for slug, nome in session.execute(select(Nicho.slug, Nicho.nome)).all():
            if slug not in presentes:
                grupos.append((slug, nome, None, None, 0, 0))
    else:
        stmt = (
            select(p.E.municipio, p.E.uf, func.count().label("total"), ganhos.label("ganhos"))
            .select_from(p.join).where(*conds).group_by(p.E.municipio, p.E.uf)
        )
        grupos = []
        for m, uf, t, g in session.execute(stmt).all():
            sem = m is None or m == ""
            rotulo = "(sem município)" if sem else f"{m} / {uf}"
            grupos.append((f"{m or ''}|{uf or ''}", rotulo, m, uf, t, g))

    itens = [
        {
            "chave": c, "rotulo": r, "municipio": m, "uf": uf, "sem_dado": (nivel == "cidade" and not m),
            "empresas": t, "ganhos": g,
            "taxa_pct": round(100.0 * g / t, 2) if t else None,  # denominador 0 => N/A
        }
        for c, r, m, uf, t, g in grupos
    ]
    itens.sort(key=lambda i: (-i["empresas"], i["rotulo"]))
    total_grupos = len(itens)
    if limite:
        itens = itens[:limite]

    tot_emp = sum(i["empresas"] for i in itens) if not limite else None
    return {
        "nivel": nivel,
        "itens": itens,
        "total_grupos": total_grupos,
        "truncado": bool(limite and total_grupos > limite),
        "definicao": DEFINICOES["conversao"],
        "empresas_no_universo": tot_emp,
    }
