"""amplia precisão geográfica para estabelecimento

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("empresa_geolocalizacoes", "precisao", existing_type=sa.String(length=12), type_=sa.String(length=20), existing_nullable=False)


def downgrade() -> None:
    op.alter_column("empresa_geolocalizacoes", "precisao", existing_type=sa.String(length=20), type_=sa.String(length=12), existing_nullable=False)
