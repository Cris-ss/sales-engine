import fs from "node:fs";
import type pg from "pg";
import { erroSeguro } from "./db.js";
import { ARQUIVO_PAUSA, modoAutomatico } from "./guard.js";
import { novoMessageId } from "./outbox.js";
import type { Transport } from "./transport.js";

const MAX_TENTATIVAS = 5;

/** Só dígitos com DDI (ex.: 5511999999999). Vazio/inválido = notificações ficam pendentes. */
export function destinoDoAmbiente(valor: string | undefined): string | null {
  const d = (valor ?? "").replace(/\D/g, "");
  return d.length >= 12 && d.length <= 13 ? d : null;
}

/**
 * Avisos INTERNOS ao operador (ex.: aceite registrado). Fluxo separado da outbox dos leads, de propósito:
 * não passa por autorização de lead, política comercial nem limites de saída (que protegem o número nos leads) e não
 * usa IA (texto já pronto, gravado pelo worker). O destino vem SÓ do ambiente deste processo: nenhuma linha de banco,
 * API ou mensagem recebida consegue mudar para onde o aviso vai. Só a parada local (arquivo PAUSA) bloqueia.
 * Uma falha aqui nunca mexe no aceite (já salvo) e não afeta a outbox dos leads.
 */
export async function processarUmaNotificacao(pool: pg.Pool, contaId: number, transporte: Transport, destino: string | null): Promise<string> {
  if (!destino) return "sem_destino";
  if (fs.existsSync(ARQUIVO_PAUSA)) return "pausa_local";
  if (!transporte.conectado()) return "sem_conexao";
  // Modo copiloto: avisos ao operador também NÃO saem pelo Baileys (o aceite aparece só na tela).
  const pol = (await pool.query("SELECT config FROM commercial_policies WHERE ativa")).rows[0];
  if (!pol || !modoAutomatico(pol.config)) return "modo_envio_manual";

  const messageId = novoMessageId();
  const n = (await pool.query(
    `UPDATE whatsapp_operator_notifications SET status='enviando', tentativas=tentativas+1, provider_msg_id=$2
       WHERE id = (SELECT id FROM whatsapp_operator_notifications WHERE conta_id=$1 AND status='pendente' AND proximo_envio_em <= now()
                   ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING id, texto, tentativas`, [contaId, messageId])).rows[0];
  if (!n) return "vazio";
  try {
    const jid = await transporte.resolverJid(destino);
    if (!jid) {
      await pool.query("UPDATE whatsapp_operator_notifications SET status='falhou', erro='destino_sem_whatsapp' WHERE id=$1", [n.id]);
      return "destino_sem_whatsapp";
    }
    await transporte.enviarTexto(jid, n.texto, messageId);
  } catch (e) {
    const definitivo = n.tentativas >= MAX_TENTATIVAS;
    await pool.query(
      `UPDATE whatsapp_operator_notifications SET status=$2, erro=$3, proximo_envio_em = now() + make_interval(secs => 60 * $4::int) WHERE id=$1`,
      [n.id, definitivo ? "falhou" : "pendente", erroSeguro(e), n.tentativas]);
    return definitivo ? "falhou" : "tentara_de_novo";
  }
  await pool.query("UPDATE whatsapp_operator_notifications SET status='enviada', enviado_em=now(), erro=NULL WHERE id=$1", [n.id]);
  return "enviada";
}

/** Ao subir: aviso que ficou "enviando" (processo caiu no meio) volta para a fila; duplicar um aviso interno é inofensivo. */
export async function recuperarNotificacoes(pool: pg.Pool, contaId: number): Promise<number> {
  const r = await pool.query("UPDATE whatsapp_operator_notifications SET status='pendente' WHERE conta_id=$1 AND status='enviando'", [contaId]);
  return r.rowCount ?? 0;
}
