"""lotes de prospecção e validações DuckDuckGo

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lotes_prospeccao",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nicho_id", sa.Integer(), sa.ForeignKey("nichos.id"), nullable=False),
        sa.Column("uf", sa.String(length=2), nullable=False),
        sa.Column("limite", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pendente"),
        sa.Column("erro", sa.Text()),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("iniciado_em", sa.DateTime(timezone=True)),
        sa.Column("concluido_em", sa.DateTime(timezone=True)),
        sa.CheckConstraint("limite BETWEEN 1 AND 500", name="ck_lote_prospeccao_limite"),
        sa.CheckConstraint("status IN ('pendente', 'executando', 'concluido', 'falhou')", name="ck_lote_prospeccao_status"),
    )
    op.create_table(
        "lotes_prospeccao_empresas",
        sa.Column("lote_id", sa.Integer(), sa.ForeignKey("lotes_prospeccao.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("empresa_id", sa.Integer(), sa.ForeignKey("empresas.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "validacoes_site_ddg",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("empresa_id", sa.Integer(), sa.ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lote_id", sa.Integer(), sa.ForeignKey("lotes_prospeccao.id", ondelete="CASCADE"), nullable=False),
        sa.Column("consulta", sa.Text(), nullable=False),
        sa.Column("resultado", sa.String(length=20), nullable=False),
        sa.Column("dominio_candidato", sa.String(length=255)),
        sa.Column("site_url", sa.String(length=500)),
        sa.Column("posicao_resultado", sa.Integer()),
        sa.Column("confianca", sa.String(length=20)),
        sa.Column("site_ativo", sa.Boolean()),
        sa.Column("email_final", sa.String(length=255)),
        sa.Column("formulario_contato_url", sa.String(length=500)),
        sa.Column("resultados_resumo", sa.Text()),
        sa.Column("erro", sa.Text()),
        sa.Column("consultado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("empresa_id", name="uq_validacao_site_ddg_empresa"),
        sa.CheckConstraint("resultado IN ('encontrado', 'sem_site', 'ambiguo', 'erro', 'rate_limit')", name="ck_ddg_resultado"),
        sa.CheckConstraint("confianca IS NULL OR confianca IN ('alta', 'media', 'baixa')", name="ck_ddg_confianca"),
    )


def downgrade() -> None:
    op.drop_table("validacoes_site_ddg")
    op.drop_table("lotes_prospeccao_empresas")
    op.drop_table("lotes_prospeccao")
