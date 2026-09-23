import type pg from "pg";

/** Evento bruto de mensagem. O gateway só transporta: escopo, contato e resposta são decididos no worker Python. */
export interface EventoMensagem {
  providerMsgId: string;
  fromMe: boolean;
  jid: string;
  jidAlt?: string | null;
  pushName?: string | null;
  tipoMsg: string;
  texto: string | null;
  origem: "tempo_real" | "historico" | "dispositivo_proprio";
  ts: Date | null;
}

const IGNORAR_SUFIXOS = ["@g.us", "@broadcast", "@newsletter"];

/** Grupos, status, canais e listas de transmissão ficam fora da automação comercial. */
export function jidIndividual(jid: string | null | undefined): jid is string {
  return Boolean(jid) && !IGNORAR_SUFIXOS.some((s) => jid!.endsWith(s)) && jid !== "status@broadcast";
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function extrairConteudo(message: any): { tipoMsg: string; texto: string | null } {
  if (!message) return { tipoMsg: "outro", texto: null };
  const m = message.ephemeralMessage?.message ?? message.viewOnceMessage?.message ?? message;
  const texto = m.conversation ?? m.extendedTextMessage?.text ?? m.imageMessage?.caption ?? m.videoMessage?.caption ?? m.documentMessage?.caption ?? null;
  if (m.audioMessage) return { tipoMsg: "audio", texto: null };
  if (m.imageMessage) return { tipoMsg: "imagem", texto };
  if (m.videoMessage) return { tipoMsg: "video", texto };
  if (m.documentMessage) return { tipoMsg: "documento", texto };
  if (m.stickerMessage) return { tipoMsg: "sticker", texto: null };
  if (m.conversation !== undefined || m.extendedTextMessage) return { tipoMsg: "texto", texto };
  return { tipoMsg: "outro", texto: null }; // reações, protocolo, enquetes etc.
}

export async function gravarEventoMensagem(pool: pg.Pool, contaId: number, ev: EventoMensagem): Promise<boolean> {
  const r = await pool.query(
    `INSERT INTO whatsapp_inbound_events
       (conta_id, tipo, provider_msg_id, from_me, jid, jid_alt, push_name, tipo_msg, texto, origem, ts_provedor)
     VALUES ($1,'mensagem',$2,$3,$4,$5,$6,$7,$8,$9,$10)
     ON CONFLICT (conta_id, provider_msg_id, from_me, tipo) WHERE tipo = 'mensagem' AND provider_msg_id IS NOT NULL DO NOTHING`,
    [contaId, ev.providerMsgId, ev.fromMe, ev.jid, ev.jidAlt ?? null, ev.pushName ?? null, ev.tipoMsg, ev.texto, ev.origem, ev.ts],
  );
  return (r.rowCount ?? 0) > 0;
}

export async function gravarRecibo(pool: pg.Pool, contaId: number, providerMsgId: string, status: string, jid: string | null): Promise<void> {
  await pool.query(
    `INSERT INTO whatsapp_inbound_events (conta_id, tipo, provider_msg_id, from_me, jid, dados, origem)
     VALUES ($1,'recibo',$2,true,$3,$4,'tempo_real')`,
    [contaId, providerMsgId, jid, JSON.stringify({ status })],
  );
}

/** Mapeamento PN<->LID informado pela própria biblioteca (nunca deduzido). */
export async function gravarMapeamentoLid(pool: pg.Pool, contaId: number, pn: string, lid: string): Promise<void> {
  await pool.query(
    `INSERT INTO whatsapp_contact_identifiers (conta_id, contato_id, tipo, identificador, origem)
       SELECT conta_id, contato_id, 'lid', $3, 'lid-mapping.update' FROM whatsapp_contact_identifiers
        WHERE conta_id=$1 AND identificador=$2 LIMIT 1
     ON CONFLICT ON CONSTRAINT uq_wa_identificador DO NOTHING`,
    [contaId, pn, lid],
  );
}
