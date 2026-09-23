import { BufferJSON, initAuthCreds, proto } from "@whiskeysockets/baileys";
import type { AuthenticationCreds, AuthenticationState, SignalDataTypeMap } from "@whiskeysockets/baileys";
import type pg from "pg";
import { cifrar, decifrar, FORMATO_VERSAO } from "./crypto.js";
import { transacao } from "./db.js";

/**
 * Estado de autenticação do Baileys no PostgreSQL, criptografado em repouso.
 * Persiste TODAS as atualizações de chaves (não só as credenciais): `keys.set` grava/apaga cada item
 * em uma única transação.
 */
export async function usarAuthStateNoBanco(pool: pg.Pool, contaId: number, chave: Buffer) {
  const serializar = (valor: unknown) => cifrar(chave, Buffer.from(JSON.stringify(valor, BufferJSON.replacer)));
  const desserializar = (blob: Buffer) => JSON.parse(decifrar(chave, blob).toString("utf8"), BufferJSON.reviver);

  const ler = async (tipo: string, itemId: string) => {
    const r = await pool.query("SELECT conteudo FROM whatsapp_auth_state WHERE conta_id=$1 AND tipo=$2 AND item_id=$3", [contaId, tipo, itemId]);
    return r.rows[0] ? desserializar(r.rows[0].conteudo as Buffer) : null;
  };
  const gravar = async (c: pg.PoolClient | pg.Pool, tipo: string, itemId: string, valor: unknown) => {
    await c.query(
      `INSERT INTO whatsapp_auth_state (conta_id, tipo, item_id, conteudo, versao, atualizado_em) VALUES ($1,$2,$3,$4,$5, now())
       ON CONFLICT (conta_id, tipo, item_id) DO UPDATE SET conteudo=EXCLUDED.conteudo, versao=EXCLUDED.versao, atualizado_em=now()`,
      [contaId, tipo, itemId, serializar(valor), FORMATO_VERSAO],
    );
  };

  const creds: AuthenticationCreds = (await ler("creds", "creds")) ?? initAuthCreds();
  const state: AuthenticationState = {
    creds,
    keys: {
      get: async (tipo, ids) => {
        const data: { [id: string]: SignalDataTypeMap[typeof tipo] } = {};
        for (const id of ids) {
          let valor = await ler(tipo, id);
          if (tipo === "app-state-sync-key" && valor) valor = proto.Message.AppStateSyncKeyData.fromObject(valor);
          data[id] = valor;
        }
        return data;
      },
      set: async (dados) => {
        await transacao(pool, async (c) => {
          for (const [tipo, itens] of Object.entries(dados)) {
            for (const [id, valor] of Object.entries(itens ?? {})) {
              if (valor) await gravar(c, tipo, id, valor);
              else await c.query("DELETE FROM whatsapp_auth_state WHERE conta_id=$1 AND tipo=$2 AND item_id=$3", [contaId, tipo, id]);
            }
          }
        });
      },
    },
  };
  return {
    state,
    saveCreds: async () => gravar(pool, "creds", "creds", state.creds),
    /** true quando já existe uma sessão pareada (permite reiniciar sem novo QR). */
    temSessaoPareada: () => Boolean(state.creds.me),
    apagarTudo: async () => { await pool.query("DELETE FROM whatsapp_auth_state WHERE conta_id=$1", [contaId]); },
  };
}
