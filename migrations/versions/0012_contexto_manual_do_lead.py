"""Contexto manual do operador no lead

Revision ID: 0012
Revises: 0011

Aditiva: uma coluna de texto anulável em empresas.
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE empresas ADD COLUMN contexto_manual TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE empresas DROP COLUMN contexto_manual")
