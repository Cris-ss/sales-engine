"""Mudança de estágio do funil.

Regras:
- Histórico é APPEND-ONLY: cada mudança insere uma linha nova em funil_status;
  nenhuma linha existente é atualizada ou apagada.
- Concorrência otimista: o cliente informa o id do histórico vigente que viu
  (null se não havia). Dentro da transação a empresa é travada (FOR UPDATE),
  o histórico vigente é relido e, se mudou, responde 409.
- Isso serializa apenas escritas feitas por esta API. Escritores que não usam
  este bloqueio (ex.: uma futura etapa do pipeline) só têm a garantia de
  "sempre acrescentar linhas"; o controle otimista detecta a mudança na
  próxima tentativa, mas não há exclusão mútua com eles.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from api.dominio import ESTAGIOS
from api.errors import ApiError
from db.models import ContatoEnviado, CanalContato, Empresa, EstagioFunil, FunilStatus


def _estagio_efetivo(session: Session, empresa_id: int, atual: Optional[FunilStatus]) -> str:
    if atual is not None:
        return atual.estagio.value
    enviados = session.execute(
        select(func.count()).select_from(ContatoEnviado).where(
            and_(
                ContatoEnviado.empresa_id == empresa_id,
                ContatoEnviado.canal == CanalContato.EMAIL,
                ContatoEnviado.status_envio == "enviado",
                ContatoEnviado.sucesso_envio.is_(True),
            )
        )
    ).scalar_one()
    return "contatada" if enviados > 0 else "encontrada"


def registrar_transicao(
    session: Session,
    empresa_id: int,
    estagio_destino: str,
    id_historico_esperado: Optional[int],
    observacao: Optional[str],
) -> FunilStatus:
    if estagio_destino not in ESTAGIOS:
        raise ApiError(422, "estagio_invalido", f"Estágio inválido: {estagio_destino!r}", {"validos": ESTAGIOS})

    empresa = session.execute(select(Empresa.id).where(Empresa.id == empresa_id).with_for_update()).first()
    if empresa is None:
        raise ApiError(404, "lead_nao_encontrado", f"Lead {empresa_id} não existe.")

    atual = session.execute(
        select(FunilStatus)
        .where(FunilStatus.empresa_id == empresa_id)
        .order_by(FunilStatus.criado_em.desc().nulls_last(), FunilStatus.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    atual_id = atual.id if atual else None

    if atual_id != id_historico_esperado:
        raise ApiError(
            409,
            "conflito_concorrencia",
            "O estágio deste lead mudou desde que você o carregou. Recarregue e tente de novo.",
            {"id_historico_atual": atual_id, "estagio_atual": atual.estagio.value if atual else None},
        )

    efetivo = _estagio_efetivo(session, empresa_id, atual)
    if efetivo == estagio_destino:
        raise ApiError(422, "sem_mudanca", f"O lead já está em '{estagio_destino}'.", {"estagio_atual": efetivo})

    nova = FunilStatus(
        empresa_id=empresa_id,
        estagio=EstagioFunil(estagio_destino),
        observacao=(observacao or "").strip() or None,
        # clock_timestamp() (instante real do INSERT) em vez do now() padrão da
        # tabela (início da transação): garante que a linha nova ordene depois
        # das anteriores mesmo se a transação esperou o bloqueio.
        criado_em=func.clock_timestamp(),
    )
    session.add(nova)
    session.commit()
    return nova
