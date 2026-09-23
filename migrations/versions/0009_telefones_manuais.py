"""Origem de telefones digitados manualmente pelo operador

Revision ID: 0009
Revises: 0008

Aditiva: uma tabela nova.
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

DDL = [
    "CREATE TABLE empresa_telefones_manuais (\n\tid SERIAL NOT NULL, \n\tempresa_id INTEGER NOT NULL, \n\ttelefone VARCHAR(20) NOT NULL, \n\tcampo VARCHAR(10) NOT NULL, \n\torigem VARCHAR(30) DEFAULT 'manual_operador' NOT NULL, \n\tusuario VARCHAR(120) NOT NULL, \n\tcriado_em TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_empresa_telefone_manual UNIQUE (empresa_id, telefone), \n\tCONSTRAINT ck_empresa_telefone_manual_campo CHECK (campo IN ('telefone1','telefone2')), \n\tFOREIGN KEY(empresa_id) REFERENCES empresas (id) ON DELETE CASCADE\n)",
]


def upgrade() -> None:
    for comando in DDL:
        op.execute(comando)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS empresa_telefones_manuais CASCADE")
