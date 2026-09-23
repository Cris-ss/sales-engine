"""Saída estruturada do modelo e validação em código. O modelo SUGERE; o código decide e executa.

O texto do cliente, sites e histórico são dados não confiáveis: nada disto muda regras, preços ou limites.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from etapa7_whatsapp.politica import EscalarPorPolitica, Orcamento, calcular_orcamento, formatar_reais, valores_do_catalogo


class Decisao(BaseModel):
    acao: Literal["responder", "perguntar", "propor", "registrar_aceite", "escalar", "encerrar"]
    texto: Optional[str] = None
    caminho: Literal["sdr", "site", "fora_catalogo", "indefinido"] = "indefinido"
    pacote: Optional[Literal["sdr", "site"]] = None
    extras: list[str] = Field(default_factory=list)
    desconto_pct: float = 0
    desconto_solicitado_pct: Optional[float] = None
    necessidade_texto: Optional[str] = None
    motivo_escalada: Optional[str] = None
    motivo_encerramento: Optional[Literal["descadastro", "numero_errado", "sem_interesse", "outro"]] = None
    estagio_sugerido: Optional[Literal["abordagem", "qualificacao", "proposta", "negociacao", "aceita", "perdida"]] = None


class DecisaoInvalida(Exception):
    pass


_PROIBIDO_IDENTIDADE = re.compile(r"\bj[uú]nior\b|estagi[aá]ri|iniciante|pouca experi[eê]ncia|sem experi[eê]ncia|primeiro projeto", re.I)
_PAGAMENTO = re.compile(
    r"pagamento (foi )?(confirmado|recebido|aprovado|identificado)|recebemos (o|seu) pagamento|confirmamos (o|seu) pagamento|"
    r"pagamento (j[aá] )?(caiu|compensou)", re.I,
)
_REAIS_POR_EXTENSO = re.compile(r"(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{2}))?\s*(?:reais|conto)", re.I)
_PERCENTUAL = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
# Prazos e garantias não existem no catálogo: a IA nunca os promete.
_PRAZO_GARANTIA = re.compile(r"\bgaranti\w*|\b\d+\s*(?:dias|semanas|meses)\b|\bprazo\s+de\b", re.I)
_OFERTA_DE_EXTRA = re.compile(r"\bextras?\b|\badicional(is)?\b|\bincluo\b|\bincluir\b", re.I)
_VALOR = re.compile(r"R\$\s*([\d]{1,3}(?:\.\d{3})*|\d+)(?:,(\d{2}))?")


def sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", t or "") if not unicodedata.combining(c)).lower()


def valores_citados(texto: str) -> list[int]:
    out = []
    for m in _VALOR.finditer(texto or ""):
        reais = int(m.group(1).replace(".", ""))
        out.append(reais * 100 + int(m.group(2) or 0))
    return out


def parse_decisao(bruto: str) -> Decisao:
    try:
        return Decisao.model_validate_json(bruto)
    except ValidationError as exc:
        raise DecisaoInvalida(f"saida_fora_do_esquema: {exc.errors()[0]['msg']}") from exc


def validar_decisao(d: Decisao, config: dict, descoberta_ok: bool, proposta_vigente: bool,
                    primeira_proposta: bool = False) -> tuple[Decisao, Optional[Orcamento]]:
    """Devolve a decisão (possivelmente convertida em escalada) e o orçamento calculado, se houver.

    Levanta DecisaoInvalida quando o TEXTO viola regra (o worker tenta de novo; falhando duas vezes, escala).
    """
    texto = d.texto or ""
    if texto and _PROIBIDO_IDENTIDADE.search(texto):
        raise DecisaoInvalida("texto_menciona_nivel_de_experiencia")
    if texto and _PAGAMENTO.search(texto):
        raise DecisaoInvalida("texto_afirma_pagamento")
    if d.acao in ("responder", "perguntar", "propor") and not texto.strip():
        raise DecisaoInvalida("texto_ausente")

    # Pedido de desconto acima do limite: escalada objetiva, sem negociar por conta própria.
    maximo = max(p["desconto_max_pct"] for p in config["pacotes"].values())
    if (d.desconto_solicitado_pct or 0) > maximo or d.desconto_pct > maximo:
        return _escalar(d, f"desconto_acima_do_limite:{max(d.desconto_solicitado_pct or 0, d.desconto_pct)}"), None

    if d.caminho == "fora_catalogo" or (d.necessidade_texto and d.acao == "escalar"):
        if valores_citados(texto):
            raise DecisaoInvalida("fora_do_catalogo_nao_pode_citar_preco")
        if not (d.necessidade_texto or "").strip():
            raise DecisaoInvalida("fora_do_catalogo_sem_descricao_da_necessidade")
        return _escalar(d, d.motivo_escalada or "necessidade_fora_do_catalogo"), None

    orcamento: Optional[Orcamento] = None
    if d.acao == "propor":
        if not descoberta_ok:
            raise DecisaoInvalida("proposta_antes_da_descoberta")
        if d.pacote is None:
            raise DecisaoInvalida("proposta_sem_pacote")
        try:
            orcamento = calcular_orcamento(config, d.pacote, d.extras, d.desconto_pct)
        except EscalarPorPolitica as exc:
            return _escalar(d, exc.motivo), None
    if d.acao == "registrar_aceite" and not proposta_vigente:
        raise DecisaoInvalida("aceite_sem_proposta_vigente")

    permitidos = valores_do_catalogo(config)
    if orcamento is not None:
        permitidos |= orcamento.valores_permitidos()
    fora = [v for v in valores_citados(texto) if v not in permitidos]
    if fora:
        raise DecisaoInvalida("valor_citado_fora_da_politica:" + ",".join(formatar_reais(v) for v in fora))
    # Valores escritos sem "R$" ("1500 reais") também precisam estar no catálogo/proposta.
    for m in _REAIS_POR_EXTENSO.finditer(texto):
        v = int(m.group(1).replace(".", "")) * 100 + int(m.group(2) or 0)
        if v not in permitidos:
            raise DecisaoInvalida(f"valor_citado_fora_da_politica:{formatar_reais(v)}")
    # Percentuais: só descontos dentro do limite da política (0% a max%).
    for m in _PERCENTUAL.finditer(texto):
        if float(m.group(1).replace(",", ".")) > maximo:
            raise DecisaoInvalida(f"percentual_fora_da_politica:{m.group(0)}")
    if texto and _PRAZO_GARANTIA.search(texto):
        raise DecisaoInvalida("texto_promete_prazo_ou_garantia_fora_do_catalogo")
    if orcamento is None and d.acao == "propor":
        raise DecisaoInvalida("proposta_sem_orcamento")
    if d.acao == "propor" and primeira_proposta:
        # Validações específicas da primeira proposta.
        if d.extras:
            raise DecisaoInvalida("primeira_proposta_so_pacote_base:sem_extras")
        base = {orcamento.setup_centavos, orcamento.mensalidade_centavos, orcamento.base_com_desconto_centavos,
                config["pacotes"][d.pacote]["setup_centavos"]}
        fora_da_base = [v for v in valores_citados(texto) if v not in base]
        if fora_da_base:
            raise DecisaoInvalida("primeira_proposta_so_pacote_base:sem_preco_de_extra")
        if _OFERTA_DE_EXTRA.search(texto):
            raise DecisaoInvalida("primeira_proposta_so_pacote_base:sem_sugerir_extra")
    return d, orcamento


def _escalar(d: Decisao, motivo: str) -> Decisao:
    texto = d.texto if d.acao == "escalar" else None
    if not texto or valores_citados(texto):
        texto = "Vou pedir para um especialista da nossa equipe entrar em contato para tratar disso com você."
    return d.model_copy(update={"acao": "escalar", "motivo_escalada": motivo, "texto": texto})


# Gatilhos determinísticos avaliados ANTES de qualquer chamada ao modelo.
_PARAR = re.compile(
    r"^\s*(pare|parar|para de (me )?(enviar|mandar)|stop|sair|cancelar|descadastr\w*|remov\w+|me tir\w+|"
    r"n[aã]o (quero|desejo) (mais )?(receber|contato|mensagens?)|n[aã]o me (envie|mande|chame)|"
    r"n[uú]mero (errado|incorreto)|engano|(voc[eê]s? )?erraram|n[aã]o sou (eu|essa pessoa))\b",
    re.I,
)
_HUMANO = re.compile(r"(falar|conversar|atendimento|atendente|quero) .{0,20}(com )?(uma )?(pessoa|humano|atendente|algu[eé]m de verdade)|atendente humano|falar com (um )?humano", re.I)


def pedido_de_parar(texto: str) -> bool:
    return bool(_PARAR.search(sem_acento(texto or "").strip()))


def pedido_de_humano(texto: str) -> bool:
    return bool(_HUMANO.search(sem_acento(texto or "")))
