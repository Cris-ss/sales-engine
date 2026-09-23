"""OSM como fonte opcional de leads

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("empresas", "cnpj", existing_type=sa.String(length=14), nullable=True)
    op.add_column("empresas", sa.Column("fonte", sa.String(length=30)))
    op.add_column("empresas", sa.Column("fonte_externo_id", sa.String(length=80)))
    op.create_unique_constraint("uq_empresas_fonte_externo_id", "empresas", ["fonte_externo_id"])
    op.add_column("lotes_prospeccao", sa.Column("fonte", sa.String(length=20), nullable=False, server_default="apify"))
    op.add_column("lotes_prospeccao", sa.Column("cidade", sa.String(length=120)))
    op.add_column("lotes_prospeccao", sa.Column("raio_km", sa.Integer()))
    op.create_check_constraint("ck_lote_prospeccao_fonte", "lotes_prospeccao", "fonte IN ('apify', 'osm')")
    op.drop_constraint("ck_ddg_resultado", "validacoes_site_ddg", type_="check")
    op.create_check_constraint("ck_ddg_resultado", "validacoes_site_ddg", "resultado IN ('site_osm', 'encontrado', 'sem_site', 'ambiguo', 'erro', 'rate_limit')")
    op.drop_constraint("ck_geo_precisao", "empresa_geolocalizacoes", type_="check")
    op.create_check_constraint("ck_geo_precisao", "empresa_geolocalizacoes", "precisao IN ('municipio', 'cep', 'estabelecimento')")


def downgrade() -> None:
    raise RuntimeError("Migração de fonte OSM é aditiva e não possui downgrade automático.")
