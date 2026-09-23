"""Geração de link wa.me a partir do telefone da Receita — SEM envio.

Módulo puro: não importa db nem faz I/O. Recebe objetos "tipo Empresa" por
duck typing (atributos nome_fantasia, razao_social, municipio, uf,
telefone1, telefone2), então pode ser reutilizado tal qual pela API web
como adaptador, sem duplicar a lógica.

Importante: telefone preenchido NÃO comprova que existe WhatsApp naquele
número. `apto=True` significa apenas "formato de celular brasileiro, dá
pra montar um link" — nunca "WhatsApp verificado".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import quote

DDDS_VALIDOS = frozenset(
    {
        11, 12, 13, 14, 15, 16, 17, 18, 19,
        21, 22, 24, 27, 28,
        31, 32, 33, 34, 35, 37, 38,
        41, 42, 43, 44, 45, 46, 47, 48, 49,
        51, 53, 54, 55,
        61, 62, 63, 64, 65, 66, 67, 68, 69,
        71, 73, 74, 75, 77, 79,
        81, 82, 83, 84, 85, 86, 87, 88, 89,
        91, 92, 93, 94, 95, 96, 97, 98, 99,
    }
)

_SUFIXOS_JURIDICOS = re.compile(
    r"\b(ltda|ltda\.|me|epp|eireli|s/?a|s/?s|sociedade simples|slu)\b\.?", re.IGNORECASE
)

_SEGMENTO = {
    "contabilidade": "escritórios de contabilidade",
    "imobiliarias": "imobiliárias",
}
_BENEFICIO = {
    "contabilidade": "automatizar tarefas repetitivas de fechamento e acompanhamento de prazos",
    "imobiliarias": "responder leads mais rápido e converter mais contatos em visita",
}
_LIMITE_DOR_CHARS = 90


@dataclass(frozen=True)
class TelefoneWhatsApp:
    original: Optional[str]
    normalizado: Optional[str]  # "55" + DDD + número, só dígitos; None se inapto
    tipo: str  # "celular" | "fixo" | "invalido" | "ausente"
    apto: bool
    motivo_inapto: Optional[str] = None
    nono_digito_adicionado: bool = False


@dataclass(frozen=True)
class ResultadoWhatsApp:
    apto: bool
    telefone: Optional[TelefoneWhatsApp]
    mensagem: Optional[str]
    link: Optional[str]
    motivo_inapto: Optional[str] = None


def normalizar_telefone(telefone: Optional[str]) -> TelefoneWhatsApp:
    if not telefone or not telefone.strip():
        return TelefoneWhatsApp(telefone, None, "ausente", False, "telefone não preenchido")

    d = re.sub(r"\D", "", telefone)

    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    if d.startswith("0") and len(d) in (11, 12):
        d = d[1:]

    if len(d) not in (10, 11):
        return TelefoneWhatsApp(telefone, None, "invalido", False, f"tamanho inválido ({len(d)} dígitos)")

    ddd, local = int(d[:2]), d[2:]
    if ddd not in DDDS_VALIDOS:
        return TelefoneWhatsApp(telefone, None, "invalido", False, f"DDD inexistente ({d[:2]})")

    if len(local) == 9:
        if local[0] != "9":
            return TelefoneWhatsApp(telefone, None, "invalido", False, "9 dígitos sem iniciar em 9")
        return TelefoneWhatsApp(telefone, f"55{d}", "celular", True)

    # 8 dígitos: formato antigo (Receita). 6-9 = celular sem o nono dígito; 2-5 = fixo.
    if local[0] in "6789":
        return TelefoneWhatsApp(telefone, f"55{d[:2]}9{local}", "celular", True, None, True)
    if local[0] in "2345":
        return TelefoneWhatsApp(
            telefone, None, "fixo", False, "telefone fixo — link de WhatsApp provavelmente não funciona"
        )
    return TelefoneWhatsApp(telefone, None, "invalido", False, "prefixo de número inválido")


def escolher_telefone(empresa: Any) -> TelefoneWhatsApp:
    """Primeiro telefone apto entre telefone1 e telefone2; se nenhum, devolve o
    resultado de telefone1 (ou o de telefone2 quando telefone1 está ausente),
    para o motivo de inaptidão ser o mais informativo possível."""
    candidatos = [normalizar_telefone(getattr(empresa, "telefone1", None)),
                  normalizar_telefone(getattr(empresa, "telefone2", None))]
    for c in candidatos:
        if c.apto:
            return c
    return candidatos[0] if candidatos[0].tipo != "ausente" else candidatos[1]


_CONECTIVOS = {"de", "da", "do", "das", "dos", "e"}


def _titulo(texto: str) -> str:
    palavras = texto.lower().split()
    return " ".join(
        p if (i > 0 and p in _CONECTIVOS) else p.capitalize() for i, p in enumerate(palavras)
    )


def _nome_curto(empresa: Any) -> str:
    nome = getattr(empresa, "nome_fantasia", None) or getattr(empresa, "razao_social", None) or ""
    nome = _SUFIXOS_JURIDICOS.sub("", nome)
    nome = re.sub(r"\s+", " ", nome).strip(" -.,")
    return _titulo(nome)


def _primeira_dor(dores: Optional[str]) -> Optional[str]:
    if not dores:
        return None
    dor = dores.split(";")[0].strip().rstrip(".")
    if not dor or len(dor) > _LIMITE_DOR_CHARS:
        return None
    return dor[0].lower() + dor[1:]


def gerar_mensagem(empresa: Any, nicho_slug: Optional[str], dores_identificadas: Optional[str] = None) -> str:
    """2-3 frases, direto. Só usa dado que existe no banco (nome, cidade/UF e,
    se houver, a primeira dor já identificada na etapa3). Determinístico: não
    chama IA."""
    nome = _nome_curto(empresa)
    cidade = _titulo(getattr(empresa, "municipio", None) or "")
    uf = getattr(empresa, "uf", None) or ""
    local = f" em {cidade}/{uf}" if cidade and uf else ""

    segmento = _SEGMENTO.get(nicho_slug or "", "empresas como a sua")
    dor = _primeira_dor(dores_identificadas)
    if dor:
        oferta = f"Ajudo {segmento} com {dor}."
    else:
        beneficio = _BENEFICIO.get(nicho_slug or "", "ganhar tempo em tarefas repetitivas")
        oferta = f"Ajudo {segmento} a {beneficio}."

    return (
        f"Olá! Vi que a {nome} atua{local}. "
        f"{oferta} "
        f"Faz sentido uma conversa rápida?"
    )


def montar_link(telefone_normalizado: str, mensagem: str) -> str:
    return f"https://wa.me/{telefone_normalizado}?text={quote(mensagem, safe='')}"


def gerar_para_empresa(
    empresa: Any, nicho_slug: Optional[str] = None, dores_identificadas: Optional[str] = None
) -> ResultadoWhatsApp:
    tel = escolher_telefone(empresa)
    if not tel.apto:
        return ResultadoWhatsApp(False, tel, None, None, tel.motivo_inapto)
    mensagem = gerar_mensagem(empresa, nicho_slug, dores_identificadas)
    return ResultadoWhatsApp(True, tel, mensagem, montar_link(tel.normalizado, mensagem))
