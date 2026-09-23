"""Constantes de domínio da interface web: mapeamento estágio->coluna, faixas de
score e vocabulários de filtro. Único lugar onde essas regras vivem."""

from __future__ import annotations

from typing import Optional

# --- Funil: 8 estágios do banco -> 5 colunas visuais -------------------------
ESTAGIOS = ["encontrada", "qualificada", "contatada", "respondeu", "em_negociacao", "proposta", "venda", "perdida"]

COLUNAS_ORDEM = ["novo", "qualificado", "contatado", "ganho", "descartado"]
COLUNA_ROTULOS = {
    "novo": "Novo",
    "qualificado": "Qualificado",
    "contatado": "Contatado",
    "ganho": "Ganho",
    "descartado": "Descartado",
}
COLUNA_ESTAGIOS = {
    "novo": ["encontrada"],
    "qualificado": ["qualificada"],
    "contatado": ["contatada", "respondeu", "em_negociacao", "proposta"],
    "ganho": ["venda"],
    "descartado": ["perdida"],
}
ESTAGIO_COLUNA = {est: col for col, ests in COLUNA_ESTAGIOS.items() for est in ests}
# Estágio gravado quando um card é arrastado para uma coluna.
ESTAGIO_CANONICO_DA_COLUNA = {
    "novo": "encontrada",
    "qualificado": "qualificada",
    "contatado": "contatada",
    "ganho": "venda",
    "descartado": "perdida",
}
ESTAGIO_ROTULOS = {
    "encontrada": "Encontrada",
    "qualificada": "Qualificada",
    "contatada": "Contatada",
    "respondeu": "Respondeu",
    "em_negociacao": "Em negociação",
    "proposta": "Proposta",
    "venda": "Venda",
    "perdida": "Perdida",
}

# --- Faixas de score (cortes configuráveis aqui) -----------------------------
# 55 é o valor SENTINELA do prompt da etapa3 (padrão conservador quando o site
# não traz sinal específico), não uma avaliação real de "fit médio". Por isso
# fica numa faixa própria, separada dos scores realmente avaliados.
SCORE_NEUTRO = 55.0
SCORE_ALTO_MIN = 65.0

FAIXAS = [
    ("sem_score", "Sem score"),
    ("baixo", "Baixo"),
    ("neutro", "Neutro (padrão conservador)"),
    ("medio", "Médio"),
    ("alto", "Alto"),
]
FAIXA_CODIGOS = [c for c, _ in FAIXAS]


def faixa_score(score: Optional[float]) -> str:
    if score is None:
        return "sem_score"
    if abs(score - SCORE_NEUTRO) < 1e-9:
        return "neutro"
    if score < SCORE_NEUTRO:
        return "baixo"
    if score >= SCORE_ALTO_MIN:
        return "alto"
    return "medio"


# --- Vocabulários de filtro ---------------------------------------------------
CANAIS = [
    ("email", "Email confirmado"),
    ("whatsapp", "WhatsApp — telefone apto (não verificado)"),
    ("ambos", "Email + WhatsApp (apto)"),
    ("formulario", "Formulário de contato"),
    ("sem_canal", "Sem canal disponível"),
]
CANAL_CODIGOS = [c for c, _ in CANAIS]

EMAIL_STATUS = [
    ("enviado", "Enviado (aceito pelo SMTP)"),
    ("pendente", "Pendente"),
    ("falhou", "Falha na tentativa (segue pendente)"),
    ("nenhum", "Sem mensagem de email"),
]
EMAIL_STATUS_CODIGOS = [c for c, _ in EMAIL_STATUS]

PAGE_SIZE_DEFAULT = 50
PAGE_SIZE_MAX = 100
MAPA_MAX_PONTOS = 5000
