"""baseline schema existente

Revision ID: 0001
Revises: 
Create Date: 2026-09-19 01:10:49.342853

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Baseline vazio de propósito: o schema já existia (criado por create_all +
    ALTERs manuais). O banco real é só carimbado com `alembic stamp 0001`.
    Um banco novo/de teste deve ser criado com Base.metadata.create_all e então
    carimbado; migrações aditivas a partir da 0002 assumem essa base."""


def downgrade() -> None:
    raise RuntimeError("Baseline não é reversível (não há schema anterior a ele).")
