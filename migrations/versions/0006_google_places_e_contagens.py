"""Google Places como fonte e contagens reais dos lotes

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lotes_prospeccao", sa.Column("total_encontrado", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("lotes_prospeccao", sa.Column("total_duplicado", sa.Integer(), nullable=False, server_default="0"))
    op.execute("""
        UPDATE lotes_prospeccao l
        SET total_encontrado = (
            SELECT count(*) FROM lotes_prospeccao_empresas e WHERE e.lote_id = l.id
        )
    """)
    op.drop_constraint("ck_lote_prospeccao_fonte", "lotes_prospeccao", type_="check")
    op.create_check_constraint(
        "ck_lote_prospeccao_fonte", "lotes_prospeccao",
        "fonte IN ('apify', 'osm', 'google_places')",
    )


def downgrade() -> None:
    raise RuntimeError("Migração de Google Places é aditiva e não possui downgrade automático.")
