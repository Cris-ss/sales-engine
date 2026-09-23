"""Interface que `etapa7_whatsapp/politica.py` deve implementar.

`politica.py` concentra a política comercial versionada e o cálculo de
preço: estrutura de pacotes, extras, descontos e limites. Este arquivo
documenta o CONTRATO que os demais módulos da etapa 7 esperam
(`decisao.py`, `worker.py`, `servico.py`, `guards.py`, `bloqueios.py`,
`llm.py`, `api/routers/whatsapp.py`), como um esqueleto de interface
sem implementação.

Para usar a etapa 7, copie este arquivo para `politica.py` e implemente
a política do seu negócio, mantendo as mesmas assinaturas de função e o
mesmo contrato descrito abaixo.

Regra que vale independente da implementação: o modelo de linguagem
NUNCA calcula preço — ele escolhe pacote e itens; o valor sai sempre de
`calcular_orcamento`, e qualquer preço citado no texto gerado é validado
contra `valores_do_catalogo` antes de sair.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from api.persistence.whatsapp_models import PoliticaComercial

# Configuração mínima de exemplo. Precisa ter pelo menos
# a forma abaixo ("pacotes" com um "desconto_max_pct" e "piso_setup_centavos"
# por pacote, "limites" com uma janela de horário) para `validar_config`
# e o restante do código funcionarem.
DEFAULT_CONFIG: dict = {
    "empresa_nome": "Empresa Exemplo",
    "identificacao": "equipe {empresa_nome}",
    "vendas_ativas": False,
    "modo_envio": "manual",
    "autorizacao_validade_dias": 90,
    "pacotes": {
        "exemplo": {
            "nome": "Pacote de exemplo",
            "descricao": "Placeholder — defina seus próprios pacotes.",
            "setup_centavos": 0,
            "desconto_max_pct": 0,
            "piso_setup_centavos": 1,
        },
    },
    "limites": {
        "dias_semana": [0, 1, 2, 3, 4],
        "hora_inicio": "09:00",
        "hora_fim": "18:00",
        "novos_contatos_dia": 1,
        "intervalo_primeiros_contatos_seg": 0,
        "saidas_por_minuto": 1,
        "respostas_por_conversa_hora": 1,
        "espera_agrupamento_seg": 0,
        "espera_agrupamento_max_seg": 0,
        "deepseek_max_chamadas_dia": 1,
        "deepseek_max_tokens_dia": 1,
    },
}


class EscalarPorPolitica(Exception):
    """A solicitação foge do que a política permite decidir sozinho: vai para o operador."""

    def __init__(self, motivo: str):
        super().__init__(motivo)
        self.motivo = motivo


@dataclass
class Orcamento:
    pacote: str
    itens: list[dict] = field(default_factory=list)
    setup_centavos: int = 0
    mensalidade_centavos: int = 0
    desconto_bp: int = 0  # pontos-base (5% = 500)
    base_com_desconto_centavos: int = 0

    def valores_permitidos(self) -> set[int]:
        vals = {self.setup_centavos, self.mensalidade_centavos, self.base_com_desconto_centavos}
        vals |= {i["centavos"] for i in self.itens}
        return {v for v in vals if v}


def formatar_reais(centavos: int) -> str:
    """Formata centavos como 'R$ 1.234,56'. Utilitário genérico, sem lógica de negócio."""
    reais, cent = divmod(centavos, 100)
    milhar = f"{reais:,}".replace(",", ".")
    return f"R$ {milhar}" + (f",{cent:02d}" if cent else "")


def calcular_orcamento(config: dict, pacote: str, itens: list[str] | None = None, desconto_pct: float = 0.0) -> Orcamento:
    """Contrato: preço determinístico a partir de `config`, `pacote` e `itens`.

    - Nunca lê preço de fora de `config` (o LLM não escolhe valor, só pacote/itens).
    - Levanta `EscalarPorPolitica` para qualquer caso fora da autonomia automática
      (pacote/item inexistente, desconto acima do limite, itens além do permitido).
    - Implementação esperada: aplica desconto só sobre o setup, respeitando um piso
      mínimo por pacote, e soma os itens/extras escolhidos.
    """
    raise NotImplementedError("implemente conforme o contrato acima")


def valores_do_catalogo(config: dict) -> set[int]:
    """Contrato: retorna o conjunto de valores (em centavos) que o texto gerado
    pela IA pode citar — usado para rejeitar qualquer preço inventado."""
    raise NotImplementedError("implemente conforme o contrato acima")


def modo_envio(config: dict) -> str:
    """Qualquer valor diferente de "automatico" (inclusive ausente) é tratado como "manual"."""
    return "automatico" if config.get("modo_envio") == "automatico" else "manual"


def politica_ativa(session: Session) -> PoliticaComercial:
    """Lê a versão ativa da política no banco; semeia a versão 1 a partir de
    `DEFAULT_CONFIG` na primeira vez (com lock para evitar duas seeds concorrentes)."""
    pol = session.execute(select(PoliticaComercial).where(PoliticaComercial.ativa.is_(True))).scalar_one_or_none()
    if pol is None:
        session.execute(text("SELECT pg_advisory_xact_lock(70001)"))
        pol = session.execute(select(PoliticaComercial).where(PoliticaComercial.ativa.is_(True))).scalar_one_or_none()
        if pol is None:
            pol = PoliticaComercial(versao=1, ativa=True, config=copy.deepcopy(DEFAULT_CONFIG), criado_por="sistema")
            session.add(pol)
            session.flush()
    return pol


def publicar_politica(session: Session, config: dict, criado_por: str) -> PoliticaComercial:
    """Cria uma nova versão ativa (a anterior é preservada, só marcada inativa),
    validando a estrutura mínima antes de publicar."""
    validar_config(config)
    atual = politica_ativa(session)
    atual.ativa = False
    session.flush()
    nova = PoliticaComercial(versao=atual.versao + 1, ativa=True, config=config, criado_por=criado_por)
    session.add(nova)
    session.flush()
    return nova


def validar_config(config: dict) -> None:
    """Contrato: falha explícita (ValueError) para configuração incoerente
    (ex.: piso acima do preço-base, desconto fora de 0–100%, faixa de horário invertida)."""
    raise NotImplementedError("implemente conforme o contrato acima")
