import { randomBytes } from "node:crypto";
import type pg from "pg";
import { erroSeguro, transacao } from "./db.js";
import { avaliarEnvio } from "./guard.js";
import { NaoEnviado, type Transport } from "./transport.js";

const ERROS_PARA_PAUSAR = 5;

export interface OpcoesEnvio {
  /** Injetável nos testes. Padrão: `atrasoDeDigitacaoMs`. */
  atraso?: (texto: string, primeiroContato: boolean) => number;
  dormir?: (ms: number) => Promise<void>;
}

const dormirDeVerdade = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/**
 * Ritmo de resposta da IA: tempo de leitura + digitação a ~40 caracteres/segundo, com variação de ±15%,
 * piso de 4 s e teto de 25 s. Leitura: 2,5 s numa resposta (1 s no primeiro contato, que não responde a nada).
 * Exemplos: 100 caracteres ≈ 5 s; 300 caracteres ≈ 10 s; 1000 caracteres → teto de 25 s.
 * É só ritmo de conversa, sem qualquer tentativa de disfarce.
 */
export function atrasoDeDigitacaoMs(texto: string, primeiroContato: boolean, aleatorio: () => number = Math.random): number {
  const leitura = primeiroContato ? 1000 : 2500;
  const digitando = (texto.length / 40) * 1000;
  const variacao = 0.85 + aleatorio() * 0.3;
  return Math.round(Math.min(25_000, Math.max(4_000, (leitura + digitando) * variacao)));
}

/** Mesmo formato dos IDs do WhatsApp Web ("3EB0" + 20 hex): gerado ANTES do envio e persistido para reconciliar eco e recibos. */
export function novoMessageId(): string {
  return "3EB0" + randomBytes(10).toString("hex").toUpperCase();
}

/** Ao subir: envio que ficou "em andamento" com lease vencido NUNCA é reenviado às cegas; vira `incerto`. */
export async function marcarIncertos(pool: pg.Pool, contaId: number): Promise<number> {
  const r = await pool.query(
    `UPDATE whatsapp_outbox SET status='incerto', erro='processo_interrompido_durante_o_envio'
       WHERE conta_id=$1 AND status='envio_em_andamento' AND lease_ate < now() RETURNING id, mensagem_id`, [contaId]);
  for (const linha of r.rows) {
    if (linha.mensagem_id) await pool.query("UPDATE whatsapp_messages SET estado_transporte='incerto' WHERE id=$1", [linha.mensagem_id]);
  }
  return r.rowCount ?? 0;
}

async function registrarFalhaDeTransporte(pool: pg.Pool, contaId: number) {
  const r = await pool.query("UPDATE whatsapp_accounts SET erros_consecutivos = erros_consecutivos + 1 WHERE id=$1 RETURNING erros_consecutivos", [contaId]);
  if (r.rows[0].erros_consecutivos >= ERROS_PARA_PAUSAR) {
    await pool.query(
      `UPDATE whatsapp_accounts SET automacao_habilitada=false, kill_geracao=kill_geracao+1, estado='pausado_por_erro',
         motivo_pausa='erros_consecutivos_de_transporte' WHERE id=$1`, [contaId]);
    await pool.query("UPDATE whatsapp_outbox SET status='cancelado', erro='pausa_por_erros' WHERE conta_id=$1 AND status='aguardando_envio' AND autoria='ia'", [contaId]);
  }
}

/** Reivindica uma mensagem pronta e a envia, repetindo as checagens de segurança imediatamente antes do transporte. */
export async function processarUmaSaida(
  pool: pg.Pool, contaId: number, transporte: Transport, agora: Date = new Date(), opcoes: OpcoesEnvio = {},
): Promise<string> {
  const reivindicada = await transacao(pool, async (c) => {
    const r = await c.query(
      `SELECT id FROM whatsapp_outbox WHERE conta_id=$1 AND status='aguardando_envio' AND agendado_para <= now()
         ORDER BY agendado_para, id FOR UPDATE SKIP LOCKED LIMIT 1`, [contaId]);
    if (!r.rowCount) return "vazio" as const;
    const id: number = r.rows[0].id;
    const v = await avaliarEnvio(c, id, agora);
    if (v.acao === "cancelar") {
      await c.query("UPDATE whatsapp_outbox SET status='cancelado', erro=$2 WHERE id=$1", [id, v.motivo]);
      await c.query("UPDATE whatsapp_messages SET estado_transporte='cancelado' WHERE outbox_id=$1", [id]);
      return "cancelado" as const;
    }
    if (v.acao === "adiar") {
      await c.query("UPDATE whatsapp_outbox SET agendado_para = now() + make_interval(secs => $2), erro=$3 WHERE id=$1", [id, v.ateSegundos ?? 15, v.motivo]);
      return "adiado" as const;
    }
    if (!transporte.conectado()) return "sem_conexao" as const; // sem sessão: nada é marcado; tenta de novo depois
    const messageId = novoMessageId();
    // O id é persistido ANTES do envio: o eco (fromMe) chega já reconciliado e não vira "intervenção humana".
    await c.query(
      `UPDATE whatsapp_outbox SET status='envio_em_andamento', provider_msg_id=$2, tentativas=tentativas+1, lease_ate=now()+interval '2 minutes' WHERE id=$1`, [id, messageId]);
    await c.query("UPDATE whatsapp_messages SET provider_msg_id=$2, estado_transporte='envio_em_andamento' WHERE outbox_id=$1", [id, messageId]);
    return id;
  });
  if (typeof reivindicada === "string") return reivindicada;
  const outboxId = reivindicada;

  const o = (await pool.query("SELECT * FROM whatsapp_outbox WHERE id=$1", [outboxId])).rows[0];
  let jid: string | null = null;
  try {
    const aut = (await pool.query("SELECT telefone_exato FROM whatsapp_authorizations WHERE conta_id=$1 AND contato_id=$2 AND status='ativa'", [contaId, o.contato_id])).rows[0];
    jid = (await pool.query(
      "SELECT identificador FROM whatsapp_contact_identifiers WHERE conta_id=$1 AND contato_id=$2 AND tipo='jid' ORDER BY id LIMIT 1", [contaId, o.contato_id])).rows[0]?.identificador ?? null;
    if (!jid) {
      jid = await transporte.resolverJid(aut.telefone_exato);
      if (!jid) {
        await pool.query("UPDATE whatsapp_outbox SET status='falhou', erro='numero_sem_whatsapp' WHERE id=$1", [outboxId]);
        await pool.query("UPDATE whatsapp_messages SET estado_transporte='falhou' WHERE outbox_id=$1", [outboxId]);
        return "numero_sem_whatsapp";
      }
      await pool.query(
        `INSERT INTO whatsapp_contact_identifiers (conta_id, contato_id, tipo, identificador, origem) VALUES ($1,$2,'jid',$3,'onWhatsApp')
           ON CONFLICT ON CONSTRAINT uq_wa_identificador DO NOTHING`, [contaId, o.contato_id, jid]);
      await pool.query("UPDATE whatsapp_contacts SET identidade_resolvida=true WHERE id=$1", [o.contato_id]);
    }

    // Ritmo de conversa: só respostas da IA esperam (leitura + digitação). O operador envia na hora.
    if (o.autoria === "ia") {
      const espera = opcoes.atraso ? opcoes.atraso(o.texto, Boolean(o.primeiro_contato)) : atrasoDeDigitacaoMs(o.texto, Boolean(o.primeiro_contato));
      if (espera > 0) {
        await transporte.digitando?.(jid, true);
        await (opcoes.dormir ?? dormirDeVerdade)(espera);
      }
    }
    // Checagem final, imediatamente antes de chamar o transporte (kill switch ou revogação durante a espera).
    const ultima = await avaliarEnvio(pool, outboxId, agora);
    if (ultima.acao === "cancelar") {
      await transporte.digitando?.(jid, false);
      await pool.query("UPDATE whatsapp_outbox SET status='cancelado', erro=$2 WHERE id=$1", [outboxId, ultima.motivo]);
      await pool.query("UPDATE whatsapp_messages SET estado_transporte='cancelado' WHERE outbox_id=$1", [outboxId]);
      return "cancelado_na_revalidacao";
    }
    await transporte.enviarTexto(jid, o.texto, o.provider_msg_id);
  } catch (e) {
    if (e instanceof NaoEnviado) { // certeza de que nada saiu: volta para a fila, com espera
      await pool.query(
        `UPDATE whatsapp_outbox SET status='aguardando_envio', erro=$2, agendado_para = now() + make_interval(secs => 30 * tentativas) WHERE id=$1`, [outboxId, erroSeguro(e)]);
      await pool.query("UPDATE whatsapp_messages SET estado_transporte='aguardando_envio', provider_msg_id=NULL WHERE outbox_id=$1", [outboxId]);
      await registrarFalhaDeTransporte(pool, contaId);
      return "nao_enviado";
    }
    // Qualquer outro erro depois de iniciar o envio: resultado INCERTO. Sem repetição automática.
    await pool.query("UPDATE whatsapp_outbox SET status='incerto', erro=$2 WHERE id=$1", [outboxId, erroSeguro(e)]);
    await pool.query("UPDATE whatsapp_messages SET estado_transporte='incerto' WHERE outbox_id=$1", [outboxId]);
    await registrarFalhaDeTransporte(pool, contaId);
    return "incerto";
  }
  await pool.query("UPDATE whatsapp_outbox SET status='aceita', enviado_em=now(), erro=NULL WHERE id=$1", [outboxId]);
  await pool.query("UPDATE whatsapp_messages SET estado_transporte='aceita' WHERE outbox_id=$1", [outboxId]);
  await pool.query("UPDATE whatsapp_conversations SET ultima_enviada_em=now() WHERE id=$1", [o.conversa_id]);
  await pool.query("UPDATE whatsapp_accounts SET erros_consecutivos=0 WHERE id=$1", [contaId]);
  return "enviado";
}
