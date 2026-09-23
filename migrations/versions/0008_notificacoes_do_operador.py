"""Etapa 7: notificações internas ao operador (aceite)

Revision ID: 0008
Revises: 0007

Aditiva: uma tabela nova.
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

DDL = [
    "CREATE TABLE whatsapp_operator_notifications (\n\tid SERIAL NOT NULL, \n\tconta_id INTEGER NOT NULL, \n\ttipo VARCHAR(20) DEFAULT 'aceite' NOT NULL, \n\taceite_id INTEGER, \n\tconversa_id INTEGER, \n\ttexto TEXT NOT NULL, \n\tstatus VARCHAR(12) DEFAULT 'pendente' NOT NULL, \n\ttentativas INTEGER DEFAULT '0' NOT NULL, \n\tproximo_envio_em TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tprovider_msg_id VARCHAR(120), \n\terro TEXT, \n\tcriado_em TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tenviado_em TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_wa_notif_status CHECK (status IN ('pendente','enviando','enviada','falhou')), \n\tFOREIGN KEY(conta_id) REFERENCES whatsapp_accounts (id) ON DELETE CASCADE, \n\tUNIQUE (aceite_id), \n\tFOREIGN KEY(aceite_id) REFERENCES commercial_acceptances (id) ON DELETE SET NULL, \n\tFOREIGN KEY(conversa_id) REFERENCES whatsapp_conversations (id) ON DELETE SET NULL\n)",
    'CREATE INDEX ix_wa_notif_pendente ON whatsapp_operator_notifications (status, proximo_envio_em)',
]


def upgrade() -> None:
    for comando in DDL:
        op.execute(comando)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS whatsapp_operator_notifications CASCADE")
