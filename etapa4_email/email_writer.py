"""Escrita do primeiro email de contato via DeepSeek (`deepseek-chat`).

Todas as regras estruturais (tamanho, estrutura em 4 partes, tom, o que
não pode ser mencionado) estão embutidas no prompt de sistema — validadas
contra benchmarks reais de cold email B2B fora deste código. O modelo só
executa: não decide estrutura, só preenche o conteúdo específico da
empresa dentro do molde já definido.

Não faz nenhuma chamada ao Google Places. Usa só dados já persistidos
(Empresa, Validacao, LeadScore).

Escopo desta etapa: SÓ o primeiro contato. Não menciona stack técnica,
linguagem de programação, senioridade nem credencial pessoal — isso é
para quando o lead responder interessado, fora de escopo aqui.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

from openai import OpenAI

from db.models import CanalContato, ContatoEnviado, Empresa, LeadScore, Nicho, Validacao

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
MODELO = "deepseek-chat"

SYSTEM_PROMPT_TEMPLATE = """Você escreve emails de primeiro contato (cold email B2B) para o nicho de {nicho_nome}, no seguinte tom: {tom_abordagem}

REGRAS ESTRUTURAIS OBRIGATÓRIAS (não-negociáveis):
1. Corpo do email: entre 50 e 90 palavras. Nunca ultrapasse 100 palavras.
2. Estrutura em 4 partes, nesta ordem, sem títulos ou marcadores visíveis, como parágrafos corridos:
   a) Gancho personalizado: cite um dado REAL da empresa (nome da empresa, cidade, ramo específico, ou algo do resumo da análise abaixo). NUNCA usar saudação genérica tipo "Espero que esteja bem".
   b) Dor específica do nicho, reescrita de forma natural a partir do contexto abaixo — nunca copiada literalmente.
   c) Proposta de valor: 1 frase curta conectando à solução, usando os argumentos de venda abaixo, sem jargão de vendas.
   d) CTA de baixo atrito: uma pergunta simples de responder. NUNCA peça algo como "podemos agendar uma call de 30 min?". Prefira um formato como "faz sentido uma conversa rápida, ou tem outra pessoa que cuida disso na [empresa]?" — qualifica o contato sem pressão.
3. Assunto: em letras minúsculas, específico ao contexto da empresa. NUNCA genérico como "oportunidade de parceria" ou "proposta comercial".
4. NUNCA invente nenhum dado sobre a empresa que não esteja nos "Dados da empresa" abaixo. Se não houver nome de uma pessoa de contato, NÃO use saudação nominal — comece direto pela referência à empresa/cidade/ramo. Sobre tempo de existência da empresa: só mencione "há X anos" se esse número aparecer literalmente no resumo da análise abaixo — nunca calcule ou estime esse número por conta própria. Se o resumo não trouxer essa informação, não mencione tempo de atividade; use outro dado real (cidade, ramo específico, algo do resumo) como gancho.
5. Este é o PRIMEIRO contato: NÃO mencione stack técnica, linguagem de programação, nível de experiência (júnior/sênior) nem qualquer credencial ou currículo pessoal. O foco é 100% na dor da empresa e na proposta de valor, nunca em provar capacidade técnica — isso fica para uma eventual resposta futura, fora de escopo agora.

Contexto de dores do nicho:
{contexto_dores}

Argumentos de venda disponíveis:
{argumentos_venda}

Exemplo de referência (calibração de tom/tamanho/estrutura — NÃO copie o conteúdo, é sobre uma empresa específica diferente da que você vai escrever agora):

Assunto: contabilidade em Cidade Exemplo — prazo fiscal

Ana, vi que a Exemplo Contábil atende contabilidade em Cidade Exemplo há mais de 10 anos. Escritórios desse porte geralmente perdem tempo real cobrando documento de cliente por WhatsApp e controlando prazo em planilha separada.

Ajudo escritórios de contabilidade a automatizar esse acompanhamento — lembrete automático de prazo, sem trocar de sistema.

Faz sentido uma conversa rápida, ou tem outra pessoa que cuida disso na Exemplo Contábil?

(Note que o exemplo não menciona nenhuma tecnologia nem currículo — só o problema e a solução em termos gerais. Este exemplo traz um nome de contato e um "há mais de 10 anos" apenas para ilustrar; se os dados abaixo não trouxerem nome de pessoa ou tempo de atividade, não invente esses elementos.)

Retorne APENAS um JSON, sem texto antes ou depois, com exatamente estas chaves:
- "assunto": string
- "corpo": string (parágrafos separados por quebra de linha dupla, como no exemplo)"""

USER_PROMPT_TEMPLATE = """Dados da empresa (não invente nada além disso):
- Nome da empresa: {nome}
- Cidade/UF: {municipio}/{uf}
- Dores identificadas na análise prévia desta empresa: {dores_identificadas}
- Resumo da análise prévia: {resumo_analise}"""


@dataclass
class ResultadoEmail:
    assunto: str
    corpo: str


def criar_client_deepseek(api_key: Optional[str] = None) -> OpenAI:
    api_key = api_key or os.environ["DEEPSEEK_API_KEY"]
    return OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)


def montar_mensagens(
    nicho: Nicho, empresa: Empresa, lead_score: LeadScore
) -> list[dict]:
    system = SYSTEM_PROMPT_TEMPLATE.format(
        nicho_nome=nicho.nome,
        tom_abordagem=nicho.tom_abordagem,
        contexto_dores=nicho.contexto_dores,
        argumentos_venda=nicho.argumentos_venda,
    )
    user = USER_PROMPT_TEMPLATE.format(
        nome=empresa.nome_fantasia or empresa.razao_social,
        municipio=empresa.municipio,
        uf=empresa.uf,
        dores_identificadas=lead_score.dores_identificadas,
        resumo_analise=lead_score.justificativa,
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def gerar_email(client: OpenAI, nicho: Nicho, empresa: Empresa, lead_score: LeadScore) -> ResultadoEmail:
    mensagens = montar_mensagens(nicho, empresa, lead_score)
    resposta = client.chat.completions.create(
        model=MODELO,
        messages=mensagens,
        response_format={"type": "json_object"},
        temperature=0.5,
    )
    dados = json.loads(resposta.choices[0].message.content)
    return ResultadoEmail(assunto=str(dados["assunto"]), corpo=str(dados["corpo"]))


def processar_empresa(
    session,
    client: OpenAI,
    empresa: Empresa,
    nicho: Nicho,
    validacao: Validacao,
    lead_score: LeadScore,
) -> ContatoEnviado:
    resultado = gerar_email(client, nicho, empresa, lead_score)

    if validacao.email_final:
        canal = CanalContato.EMAIL
        destino = validacao.email_final
    else:
        canal = CanalContato.FORMULARIO_SITE
        destino = validacao.formulario_contato_url

    contato = ContatoEnviado(
        empresa_id=empresa.id,
        canal=canal,
        destino=destino,
        assunto=resultado.assunto,
        corpo=resultado.corpo,
        status_envio="pendente",
    )
    session.add(contato)
    session.commit()
    return contato
