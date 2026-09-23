"""Prompt e chamada ao DeepSeek (mesma integração da etapa 4: SDK OpenAI apontado para api.deepseek.com).

`LlmFn` é injetável: os testes usam um falso e NUNCA chamam a API real.
"""

from __future__ import annotations

import json
from typing import Callable

from etapa7_whatsapp.roteiro import tarefa, texto_sistema

PROMPT_VERSAO = "wa-v5"
LlmFn = Callable[[list[dict]], tuple[str, int, int]]  # mensagens -> (json, tokens_entrada, tokens_saida)


def montar_mensagens(config: dict, lead: dict, estado: dict, proposta_vigente: dict | None, resumo: str | None,
                     historico: list[dict], novas: list[str], primeiro_contato: bool) -> list[dict]:
    empresa = config["empresa_nome"]
    ident = config["identificacao"].format(empresa_nome=empresa)
    sistema = texto_sistema(config, empresa, ident)
    contexto = {
        "lead": lead,
        "estado_comercial": estado,
        "proposta_vigente": proposta_vigente,
        "resumo_das_mensagens_antigas": resumo,
        "ultimas_mensagens": historico,
        "novas_mensagens_do_cliente": novas,
        "tarefa": tarefa(primeiro_contato),
    }
    return [{"role": "system", "content": sistema}, {"role": "user", "content": json.dumps(contexto, ensure_ascii=False)}]


def criar_llm_deepseek() -> LlmFn:
    from etapa4_email.email_writer import MODELO, criar_client_deepseek

    client = criar_client_deepseek()

    def _chamar(mensagens: list[dict]) -> tuple[str, int, int]:
        resposta = client.chat.completions.create(
            model=MODELO, messages=mensagens, response_format={"type": "json_object"}, temperature=0.6,
        )
        uso = resposta.usage
        return resposta.choices[0].message.content or "", getattr(uso, "prompt_tokens", 0) or 0, getattr(uso, "completion_tokens", 0) or 0

    return _chamar
