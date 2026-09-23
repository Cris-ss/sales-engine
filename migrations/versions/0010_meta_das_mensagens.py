"""Modo copiloto: coluna meta nas mensagens do WhatsApp

Revision ID: 0010
Revises: 0009

Aditiva: uma coluna JSONB anulável. Guarda os dados da sugestão da IA e do envio manual confirmado.
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE whatsapp_messages ADD COLUMN meta JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE whatsapp_messages DROP COLUMN meta")
