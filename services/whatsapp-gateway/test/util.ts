import fs from "node:fs";
import pg from "pg";

/** Os testes só rodam em banco cujo nome termina em `_test` (mesma trava dos testes Python). */
export function urlDeTeste(): string {
  let url = process.env.TEST_DATABASE_URL;
  if (!url) {
    for (const caminho of ["../../.env", ".env"]) {
      if (!fs.existsSync(caminho)) continue;
      const m = /^DATABASE_URL=(.*)$/m.exec(fs.readFileSync(caminho, "utf8"));
      if (m) url = m[1].trim().replace(/\/[^/]+$/, "/sales_engine_test");
    }
  }
  if (!url || !/_test(\?.*)?$/.test(url)) throw new Error(`RECUSADO: ${url} não parece banco de teste (o nome deve terminar em _test).`);
  return url;
}

export function poolDeTeste(): pg.Pool {
  return new pg.Pool({ connectionString: urlDeTeste(), max: 4 });
}

const TABELAS = [
  "whatsapp_message_events", "whatsapp_ai_runs", "whatsapp_messages", "whatsapp_outbox", "whatsapp_jobs", "commercial_acceptances",
  "commercial_proposals", "commercial_demands", "whatsapp_conversations", "whatsapp_suppressions", "whatsapp_authorizations",
  "whatsapp_contact_identifiers", "whatsapp_contacts", "whatsapp_inbound_events", "whatsapp_auth_state", "whatsapp_audit_events",
  "whatsapp_accounts", "commercial_policies",
];

export async function limpar(pool: pg.Pool) {
  await pool.query(`TRUNCATE ${TABELAS.join(", ")} RESTART IDENTITY CASCADE`);
}

export const LIMITES = {
  dias_semana: [0, 1, 2, 3, 4], hora_inicio: "09:00", hora_fim: "18:00", novos_contatos_dia: 10, intervalo_primeiros_contatos_seg: 180,
  saidas_por_minuto: 6, respostas_por_conversa_hora: 12, espera_agrupamento_seg: 8, espera_agrupamento_max_seg: 20,
};

export interface Semente { contaId: number; contatoId: number; conversaId: number; autId: number }

export async function semear(pool: pg.Pool, opcoes: { automacao?: boolean; config?: Record<string, unknown> } = {}): Promise<Semente> {
  await limpar(pool);
  await pool.query("INSERT INTO commercial_policies (versao, ativa, config, criado_por) VALUES (1, true, $1, 'teste')",
    [JSON.stringify({ limites: LIMITES, pacotes: {}, ...(opcoes.config ?? { modo_envio: "automatico" }) })]);
  const conta = (await pool.query("INSERT INTO whatsapp_accounts (estado, automacao_habilitada) VALUES ('conectado', $1) RETURNING id", [opcoes.automacao ?? true])).rows[0].id;
  const contato = (await pool.query("INSERT INTO whatsapp_contacts (telefone_e164) VALUES ('+5511991234567') RETURNING id")).rows[0].id;
  const conversa = (await pool.query("INSERT INTO whatsapp_conversations (conta_id, contato_id, controle, versao) VALUES ($1,$2,'automatizada',1) RETURNING id", [conta, contato])).rows[0].id;
  const aut = (await pool.query(
    `INSERT INTO whatsapp_authorizations (conta_id, contato_id, autorizado_por, telefone_exato, status, versao, politica_versao, expira_em)
       VALUES ($1,$2,'teste','+5511991234567','ativa',1,1, now() + interval '90 days') RETURNING id`, [conta, contato])).rows[0].id;
  return { contaId: conta, contatoId: contato, conversaId: conversa, autId: aut };
}

export async function novaSaida(pool: pg.Pool, s: Semente, o: { autoria?: "ia" | "operador"; primeiro?: boolean; texto?: string } = {}): Promise<number> {
  const conta = (await pool.query("SELECT kill_geracao FROM whatsapp_accounts WHERE id=$1", [s.contaId])).rows[0];
  const msg = (await pool.query(
    `INSERT INTO whatsapp_messages (conta_id, conversa_id, contato_id, direcao, autoria, texto, estado_transporte, origem, provider_from_me)
       VALUES ($1,$2,$3,'saida',$4,$5,'aguardando_envio','sistema',true) RETURNING id`,
    [s.contaId, s.conversaId, s.contatoId, o.autoria ?? "ia", o.texto ?? "Olá!"])).rows[0].id;
  const out = (await pool.query(
    `INSERT INTO whatsapp_outbox (conta_id, conversa_id, contato_id, autoria, texto, primeiro_contato, versao_autorizacao, versao_politica,
       versao_conversa, kill_geracao, mensagem_id) VALUES ($1,$2,$3,$4,$5,$6,1,1,1,$7,$8) RETURNING id`,
    [s.contaId, s.conversaId, s.contatoId, o.autoria ?? "ia", o.texto ?? "Olá!", o.primeiro ?? false, conta.kill_geracao, msg])).rows[0].id;
  await pool.query("UPDATE whatsapp_messages SET outbox_id=$2 WHERE id=$1", [msg, out]);
  return out;
}
