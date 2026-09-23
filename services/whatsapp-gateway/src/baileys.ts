import makeWASocket, { Browsers, DisconnectReason, proto } from "@whiskeysockets/baileys";
import type { WASocket } from "@whiskeysockets/baileys";
import type pg from "pg";
import pino from "pino";
import { usarAuthStateNoBanco } from "./authState.js";
import { erroSeguro } from "./db.js";
import { extrairConteudo, gravarEventoMensagem, gravarMapeamentoLid, gravarRecibo, jidIndividual } from "./eventos.js";
import { NaoEnviado, type Transport } from "./transport.js";

const STATUS: Record<number, string> = { 0: "error", 1: "pending", 2: "server_ack", 3: "delivered", 4: "read", 5: "read" };

type Sessao = Awaited<ReturnType<typeof usarAuthStateNoBanco>>;

/**
 * Sessão Baileys. Nada aqui decide regra comercial. QR nunca vai para log: só para a linha da conta (transitório).
 * NÃO conecta sozinho sem sessão pareada: o pareamento real é sempre um comando explícito do operador.
 */
export class SessaoBaileys implements Transport {
  private sock: WASocket | null = null;
  private aberta = false;
  private tentativas = 0;
  private encerrando = false;
  private timer: NodeJS.Timeout | null = null;

  constructor(private pool: pg.Pool, private contaId: number, private chave: Buffer, private log = pino({ level: "warn" })) {}

  conectado() {
    return this.aberta;
  }

  async resolverJid(telefoneE164: string): Promise<string | null> {
    if (!this.sock || !this.aberta) throw new NaoEnviado("sem conexão com o WhatsApp");
    const r = await this.sock.onWhatsApp(telefoneE164.replace(/\D/g, ""));
    const achado = r?.find((x) => x.exists);
    return achado ? achado.jid : null;
  }

  async enviarTexto(jid: string, texto: string, messageId: string): Promise<void> {
    if (!this.sock || !this.aberta) throw new NaoEnviado("sem conexão com o WhatsApp");
    await this.sock.sendMessage(jid, { text: texto }, { messageId });
  }

  async digitando(jid: string, ativo: boolean): Promise<void> {
    try {
      if (this.sock && this.aberta) await this.sock.sendPresenceUpdate(ativo ? "composing" : "paused", jid);
    } catch { /* indicador é opcional: falhar aqui não pode impedir nem alterar o envio */ }
  }

  async temSessaoPareada(): Promise<boolean> {
    return (await usarAuthStateNoBanco(this.pool, this.contaId, this.chave)).temSessaoPareada();
  }

  /** Apaga a sessão salva (só a pedido explícito do operador, depois de logout/requer_pareamento). */
  async limparSessao() {
    await (await usarAuthStateNoBanco(this.pool, this.contaId, this.chave)).apagarTudo();
  }

  async iniciar(): Promise<void> {
    this.encerrando = false;
    await this.estado("conectando");
    const sessao: Sessao = await usarAuthStateNoBanco(this.pool, this.contaId, this.chave);
    const sock = makeWASocket({
      auth: sessao.state, logger: this.log, browser: Browsers.appropriate("Sales Engine"),
      syncFullHistory: false, markOnlineOnConnect: false,
    });
    this.sock = sock;
    sock.ev.on("creds.update", () => { sessao.saveCreds().catch((e) => this.log.error({ e: erroSeguro(e) }, "falha ao salvar credenciais")); });
    sock.ev.on("connection.update", (u) => { this.aoMudarConexao(u).catch((e) => this.log.error({ e: erroSeguro(e) }, "connection.update")); });
    sock.ev.on("messages.upsert", ({ messages, type }) => {
      for (const m of messages) {
        const jid = m.key.remoteJid;
        if (!jidIndividual(jid) || !m.key.id) continue;
        const { tipoMsg, texto } = extrairConteudo(m.message);
        if (tipoMsg === "outro") continue;
        const ts = m.messageTimestamp ? new Date(Number(m.messageTimestamp) * 1000) : null;
        const origem = type === "notify" ? (m.key.fromMe ? "dispositivo_proprio" : "tempo_real") : "historico";
        gravarEventoMensagem(this.pool, this.contaId, {
          providerMsgId: m.key.id, fromMe: Boolean(m.key.fromMe), jid, jidAlt: m.key.remoteJidAlt ?? null,
          pushName: m.pushName ?? null, tipoMsg, texto, origem, ts,
        }).catch((e) => this.log.error({ e: erroSeguro(e) }, "gravar mensagem"));
      }
    });
    sock.ev.on("messaging-history.set", ({ messages }) => {
      for (const m of messages) {
        const jid = m.key.remoteJid;
        if (!jidIndividual(jid) || !m.key.id) continue;
        const { tipoMsg, texto } = extrairConteudo(m.message);
        if (tipoMsg === "outro") continue;
        gravarEventoMensagem(this.pool, this.contaId, {
          providerMsgId: m.key.id, fromMe: Boolean(m.key.fromMe), jid, jidAlt: m.key.remoteJidAlt ?? null, pushName: m.pushName ?? null,
          tipoMsg, texto, origem: "historico", ts: m.messageTimestamp ? new Date(Number(m.messageTimestamp) * 1000) : null,
        }).catch((e) => this.log.error({ e: erroSeguro(e) }, "gravar histórico"));
      }
    });
    sock.ev.on("messages.update", (updates) => {
      for (const u of updates) {
        if (!u.key.fromMe || !u.key.id || u.update.status == null) continue;
        const status = STATUS[u.update.status as proto.WebMessageInfo.Status];
        if (status) gravarRecibo(this.pool, this.contaId, u.key.id, status, u.key.remoteJid ?? null).catch(() => undefined);
      }
    });
    sock.ev.on("lid-mapping.update", (m) => {
      gravarMapeamentoLid(this.pool, this.contaId, m.pn, m.lid).catch(() => undefined);
    });
  }

  private async estado(estado: string, extra: string = "") {
    await this.pool.query(`UPDATE whatsapp_accounts SET estado=$2 ${extra} WHERE id=$1`, [this.contaId, estado]);
  }

  private async aoMudarConexao(u: { connection?: string; lastDisconnect?: { error?: unknown }; qr?: string }) {
    if (u.qr) {
      await this.pool.query("UPDATE whatsapp_accounts SET estado='aguardando_qr', qr_atual=$2 WHERE id=$1", [this.contaId, u.qr]);
    }
    if (u.connection === "open") {
      this.aberta = true;
      this.tentativas = 0;
      const numero = this.sock?.user?.id?.split(":")[0]?.split("@")[0] ?? null;
      await this.pool.query("UPDATE whatsapp_accounts SET estado='conectado', qr_atual=NULL, numero=COALESCE($2, numero), erros_consecutivos=0 WHERE id=$1", [this.contaId, numero]);
    }
    if (u.connection === "close") {
      this.aberta = false;
      if (this.encerrando) return;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const codigo: number | undefined = (u.lastDisconnect?.error as any)?.output?.statusCode;
      if (codigo === DisconnectReason.loggedOut) {
        // Sessão revogada: suspende envios e pede novo pareamento. Credenciais NÃO são apagadas sozinhas.
        await this.pool.query(
          `UPDATE whatsapp_accounts SET estado='requer_pareamento', qr_atual=NULL, automacao_habilitada=false, kill_geracao=kill_geracao+1,
             motivo_pausa='sessao_revogada' WHERE id=$1`, [this.contaId]);
        await this.pool.query("UPDATE whatsapp_outbox SET status='cancelado', erro='sessao_revogada' WHERE conta_id=$1 AND status='aguardando_envio' AND autoria='ia'", [this.contaId]);
        return;
      }
      if (codigo === DisconnectReason.connectionReplaced) {
        await this.pool.query(
          `UPDATE whatsapp_accounts SET estado='pausado_por_erro', automacao_habilitada=false, kill_geracao=kill_geracao+1,
             motivo_pausa='sessao_substituida_por_outra_conexao' WHERE id=$1`, [this.contaId]);
        return;
      }
      await this.estado("reconectando");
      const espera = codigo === DisconnectReason.restartRequired ? 500 : Math.min(60_000, 1000 * 2 ** this.tentativas++);
      this.timer = setTimeout(() => { this.iniciar().catch((e) => this.log.error({ e: erroSeguro(e) }, "reconexão")); }, espera);
    }
  }

  /** Desconecta sem deslogar (o pareamento continua válido). */
  async parar() {
    this.encerrando = true;
    if (this.timer) clearTimeout(this.timer);
    this.aberta = false;
    try { this.sock?.end(undefined); } catch { /* já fechado */ }
    this.sock = null;
    await this.pool.query("UPDATE whatsapp_accounts SET estado='desconectado', qr_atual=NULL WHERE id=$1", [this.contaId]);
  }
}
