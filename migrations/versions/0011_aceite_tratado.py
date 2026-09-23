"""Aceites: marca de "tratado" pelo operador

Revision ID: 0011
Revises: 0010

Aditiva: uma coluna anulável. Alimenta o contador "aceites aguardando você".
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE commercial_acceptances ADD COLUMN tratado_em TIMESTAMP WITH TIME ZONE")


def downgrade() -> None:
    op.execute("ALTER TABLE commercial_acceptances DROP COLUMN tratado_em")
