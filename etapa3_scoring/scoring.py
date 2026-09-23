"""Scoring de fit via IA (DeepSeek, modelo `deepseek-chat`).

O raciocínio de negócio já foi feito fora do modelo: o prompt embute o
contexto do nicho e a regra de conservadorismo quando falta dado. O
modelo só executa — classifica o fit e devolve JSON estruturado, sem
espaço para interpretação livre de formato ou de critério.

Não faz nenhuma chamada ao Google Places. `obter_conteudo_site` só lê o
HTML público do site já confirmado pela etapa2.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

from openai import OpenAI

from db.models import Empresa, LeadScore, Nicho, Validacao
from etapa3_scoring.site_content import obter_conteudo_site

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
MODELO = "deepseek-chat"
PROMPT_VERSAO = "v1"

SYSTEM_PROMPT_TEMPLATE = """Você analisa empresas de {nicho_nome} para determinar fit com um serviço de automação/consultoria.

Contexto do nicho:
{contexto_dores}

Retorne APENAS um JSON, sem texto antes ou depois, com exatamente estas chaves:
- "score_fit": inteiro de 0 a 100
- "dores_identificadas": string curta, até 2 dores específicas
- "resumo_analise": string, 1 frase objetiva

Regra obrigatória: não invente informação que não está nos dados fornecidos. Se o conteúdo do site não disser nada específico sobre a empresa, baseie-se só no contexto geral do nicho acima e dê um score conservador, entre 40 e 60."""

USER_PROMPT_TEMPLATE = """Dados da empresa:
- Nome: {nome}
- Cidade/UF: {municipio}/{uf}
- Conteúdo do site: {conteudo_site}"""


@dataclass
class ResultadoScore:
    score_fit: int
    dores_identificadas: str
    resumo_analise: str


def criar_client_deepseek(api_key: Optional[str] = None) -> OpenAI:
    api_key = api_key or os.environ["DEEPSEEK_API_KEY"]
    return OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)


def montar_mensagens(nicho: Nicho, empresa: Empresa, conteudo_site: str) -> list[dict]:
    system = SYSTEM_PROMPT_TEMPLATE.format(
        nicho_nome=nicho.nome,
        contexto_dores=nicho.contexto_dores,
    )
    user = USER_PROMPT_TEMPLATE.format(
        nome=empresa.nome_fantasia or empresa.razao_social,
        municipio=empresa.municipio,
        uf=empresa.uf,
        conteudo_site=conteudo_site or "(não disponível)",
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def gerar_score(client: OpenAI, nicho: Nicho, empresa: Empresa, conteudo_site: str) -> ResultadoScore:
    mensagens = montar_mensagens(nicho, empresa, conteudo_site)
    resposta = client.chat.completions.create(
        model=MODELO,
        messages=mensagens,
        response_format={"type": "json_object"},
        temperature=0.3,
    )
    dados = json.loads(resposta.choices[0].message.content)
    return ResultadoScore(
        score_fit=int(dados["score_fit"]),
        dores_identificadas=str(dados["dores_identificadas"]),
        resumo_analise=str(dados["resumo_analise"]),
    )


def processar_empresa(
    session, client: OpenAI, empresa: Empresa, nicho: Nicho, validacao: Validacao
) -> LeadScore:
    conteudo_site = obter_conteudo_site(validacao.site_url)
    resultado = gerar_score(client, nicho, empresa, conteudo_site)

    lead_score = LeadScore(
        empresa_id=empresa.id,
        score=resultado.score_fit,
        modelo_usado=MODELO,
        prompt_versao=PROMPT_VERSAO,
        dores_identificadas=resultado.dores_identificadas,
        justificativa=resultado.resumo_analise,
    )
    session.add(lead_score)
    session.commit()
    return lead_score
