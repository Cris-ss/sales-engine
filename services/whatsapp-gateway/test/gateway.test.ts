import assert from "node:assert/strict";
import fs from "node:fs";
import { after, before, beforeEach, describe, it } from "node:test";
import { BufferJSON } from "@whiskeysockets/baileys";
import type pg from "pg";
import { usarAuthStateNoBanco } from "../src/authState.js";
import { chaveDoAmbiente, cifrar, decifrar } from "../src/crypto.js";
import { extrairConteudo, gravarEventoMensagem, gravarRecibo, jidIndividual } from "../src/eventos.js";
import { ARQUIVO_PAUSA, dentroDaJanela, avaliarEnvio } from "../src/guard.js";
import { atrasoDeDigitacaoMs, marcarIncertos, processarUmaSaida as processar } from "../src/outbox.js";
import { destinoDoAmbiente, processarUmaNotificacao, recuperarNotificacoes } from "../src/notificacoes.js";
import { NaoEnviado, type Transport } from "../src/transport.js";
import { LIMITES, novaSaida, poolDeTeste, semear, type Semente } from "./util.js";

// Nos testes a espera de digitação é instantânea, salvo nos testes de ritmo.
const processarUmaSaida = (pool: pg.Pool, contaId: number, t: Transport, agora?: Date) => processar(pool, contaId, t, agora, { dormir: async () => undefined });
const SEG = new Date("2026-09-21T14:00:00Z"); // segunda 11:00 em São Paulo
const SAB = new Date("2026-09-19T14:00:00Z");
const CHAVE = chaveDoAmbiente("ab".repeat(32));

class Falso implements Transport {
  enviados: { jid: string; texto: string; id: string }[] = [];
  resolvidos = 0;
  ligado = true;
  falha: Error | null = null;
  antesDeEnviar: (() => Promise<void>) | null = null;
  digitando?: (jid: string, ativo: boolean) => Promise<void>;
  jid: string | null = "5511991234567@s.whatsapp.net";
  conectado() { return this.ligado; }
  async resolverJid() { this.resolvidos++; return this.jid; }
  async enviarTexto(jid: string, texto: string, id: string) {
    if (this.antesDeEnviar) await this.antesDeEnviar();
    if (this.falha) throw this.falha;
    this.enviados.push({ jid, texto, id });
  }
}

let pool: pg.Pool;
let s: Semente;
before(() => { pool = poolDeTeste(); });
after(async () => { await pool.end(); });
beforeEach(async () => { s = await semear(pool); if (fs.existsSync(ARQUIVO_PAUSA)) fs.rmSync(ARQUIVO_PAUSA); });
const status = async (id: number) => (await pool.query("SELECT status, erro, provider_msg_id FROM whatsapp_outbox WHERE id=$1", [id])).rows[0];

describe("criptografia e sessão", () => {
  it("cifra e decifra; chave errada ou adulteração falham", () => {
    const blob = cifrar(CHAVE, Buffer.from("segredo"));
    assert.equal(decifrar(CHAVE, blob).toString(), "segredo");
    assert.throws(() => decifrar(chaveDoAmbiente("cd".repeat(32)), blob));
    blob[blob.length - 1] ^= 1;
    assert.throws(() => decifrar(CHAVE, blob));
    assert.throws(() => chaveDoAmbiente("curta"));
  });

  it("auth state: persiste chaves binárias, apaga, sobrevive a 'reinício' e não guarda texto claro", async () => {
    const a = await usarAuthStateNoBanco(pool, s.contaId, CHAVE);
    assert.equal(a.temSessaoPareada(), false);
    await a.state.keys.set({ "pre-key": { "1": { public: Buffer.from([1, 2, 3]), private: Buffer.from([4, 5, 6]) } }, session: { "x@s.whatsapp.net": Buffer.from("sess") } });
    a.state.creds.me = { id: "5511999999999:1@s.whatsapp.net" };
    await a.saveCreds();
    const b = await usarAuthStateNoBanco(pool, s.contaId, CHAVE); // novo "processo"
    assert.equal(b.temSessaoPareada(), true);
    const k = await b.state.keys.get("pre-key", ["1"]);
    assert.deepEqual(Buffer.from(k["1"].private), Buffer.from([4, 5, 6]));
    const bruto = (await pool.query("SELECT conteudo FROM whatsapp_auth_state WHERE tipo='session'")).rows[0].conteudo as Buffer;
    assert.ok(!bruto.toString("latin1").includes("sess"));
    await b.state.keys.set({ "pre-key": { "1": null } });
    assert.equal((await b.state.keys.get("pre-key", ["1"]))["1"], null);
    assert.ok(JSON.stringify({ a: Buffer.from("x") }, BufferJSON.replacer).length > 0);
  });
});

describe("janela de envio", () => {
  it("segunda 11h abre; sábado e 18h fecham", () => {
    assert.equal(dentroDaJanela(SEG, "America/Sao_Paulo", LIMITES), true);
    assert.equal(dentroDaJanela(SAB, "America/Sao_Paulo", LIMITES), false);
    assert.equal(dentroDaJanela(new Date("2026-09-21T21:00:00Z"), "America/Sao_Paulo", LIMITES), false);
  });
});

describe("outbox e guard", () => {
  it("envia e persiste o id do provedor ANTES de chamar o transporte", async () => {
    const t = new Falso();
    const id = await novaSaida(pool, s);
    let visto: string | null = null;
    t.antesDeEnviar = async () => { visto = (await status(id)).provider_msg_id; };
    assert.equal(await processarUmaSaida(pool, s.contaId, t, SEG), "enviado");
    assert.equal(t.enviados.length, 1);
    assert.equal(visto, t.enviados[0].id);
    assert.equal((await status(id)).status, "aceita");
    assert.equal((await pool.query("SELECT estado_transporte, provider_msg_id FROM whatsapp_messages WHERE outbox_id=$1", [id])).rows[0].provider_msg_id, t.enviados[0].id);
    const jid = (await pool.query("SELECT identificador, origem FROM whatsapp_contact_identifiers")).rows[0];
    assert.deepEqual(jid, { identificador: "5511991234567@s.whatsapp.net", origem: "onWhatsApp" });
  });

  it("kill switch: nada é enviado e a saída é cancelada", async () => {
    const t = new Falso();
    const id = await novaSaida(pool, s);
    await pool.query("UPDATE whatsapp_accounts SET automacao_habilitada=false, kill_geracao=kill_geracao+1");
    assert.equal(await processarUmaSaida(pool, s.contaId, t, SEG), "cancelado");
    assert.equal(t.enviados.length, 0);
    assert.equal((await status(id)).erro, "automacao_pausada");
  });

  it("revogação bloqueia; supressão bloqueia; operador também respeita ambas", async () => {
    const t = new Falso();
    const a = await novaSaida(pool, s);
    await pool.query("UPDATE whatsapp_authorizations SET status='revogada'");
    assert.equal(await processarUmaSaida(pool, s.contaId, t, SEG), "cancelado");
    assert.equal((await status(a)).erro, "sem_autorizacao_ativa");
    await pool.query("UPDATE whatsapp_authorizations SET status='ativa'");
    await pool.query("INSERT INTO whatsapp_suppressions (conta_id, contato_id, motivo, origem) VALUES ($1,$2,'descadastro','teste')", [s.contaId, s.contatoId]);
    const b = await novaSaida(pool, s, { autoria: "operador" });
    assert.equal(await processarUmaSaida(pool, s.contaId, t, SEG), "cancelado");
    assert.equal((await status(b)).erro, "contato_suprimido");
    assert.equal(t.enviados.length, 0);
  });

  it("versões: conversa que mudou ou autorização nova invalidam a resposta antiga", async () => {
    const t = new Falso();
    const id = await novaSaida(pool, s);
    await pool.query("UPDATE whatsapp_conversations SET versao=versao+1");
    assert.equal(await processarUmaSaida(pool, s.contaId, t, SEG), "cancelado");
    assert.equal((await status(id)).erro, "conversa_mudou");
  });

  it("IA fora do horário é adiada; mensagem do operador não sofre a janela", async () => {
    const t = new Falso();
    const ia = await novaSaida(pool, s);
    assert.equal(await processarUmaSaida(pool, s.contaId, t, SAB), "adiado");
    assert.equal((await status(ia)).status, "aguardando_envio");
    await pool.query("UPDATE whatsapp_outbox SET status='cancelado' WHERE id=$1", [ia]);
    await novaSaida(pool, s, { autoria: "operador" });
    assert.equal(await processarUmaSaida(pool, s.contaId, t, SAB), "enviado");
  });

  it("limite de saídas por minuto adia", async () => {
    const t = new Falso();
    for (let i = 0; i < 6; i++) {
      const o = await novaSaida(pool, s, { autoria: "operador" });
      await pool.query("UPDATE whatsapp_outbox SET status='aceita', enviado_em=$2 WHERE id=$1", [o, new Date(SEG.getTime() - 10_000)]);
    }
    const nova = await novaSaida(pool, s, { autoria: "operador" });
    assert.equal(await processarUmaSaida(pool, s.contaId, t, SEG), "adiado");
    assert.equal((await status(nova)).erro, "limite_saidas_por_minuto");
  });

  it("primeiros contatos respeitam o intervalo mínimo", async () => {
    const t = new Falso();
    const anterior = await novaSaida(pool, s, { primeiro: true });
    await pool.query("UPDATE whatsapp_outbox SET status='aceita', enviado_em=$2 WHERE id=$1", [anterior, new Date(SEG.getTime() - 60_000)]);
    const novo = await novaSaida(pool, s, { primeiro: true });
    assert.equal(await processarUmaSaida(pool, s.contaId, t, SEG), "adiado");
    assert.equal((await status(novo)).erro, "intervalo_entre_primeiros_contatos");
  });

  it("envio INCERTO: erro depois de iniciar o envio nunca é repetido automaticamente", async () => {
    const t = new Falso();
    t.falha = new Error("socket fechou no meio");
    const id = await novaSaida(pool, s);
    assert.equal(await processarUmaSaida(pool, s.contaId, t, SEG), "incerto");
    assert.equal((await status(id)).status, "incerto");
    t.falha = null;
    assert.equal(await processarUmaSaida(pool, s.contaId, t, SEG), "vazio");
    assert.equal(t.enviados.length, 0);
  });

  it("falha com CERTEZA de não envio (sem conexão) volta para a fila", async () => {
    const t = new Falso();
    t.falha = new NaoEnviado("sem conexão");
    const id = await novaSaida(pool, s);
    assert.equal(await processarUmaSaida(pool, s.contaId, t, SEG), "nao_enviado");
    assert.equal((await status(id)).status, "aguardando_envio");
    assert.equal(await processarUmaSaida(pool, s.contaId, t, SEG), "vazio"); // espera do backoff ainda não venceu
    await pool.query("UPDATE whatsapp_outbox SET agendado_para = now()");
    t.ligado = false;
    assert.equal(await processarUmaSaida(pool, s.contaId, t, SEG), "sem_conexao");
    assert.equal((await status(id)).status, "aguardando_envio");
  });

  it("processo morto durante o envio: ao subir, vira incerto e não é reenviado", async () => {
    const t = new Falso();
    const id = await novaSaida(pool, s);
    await pool.query("UPDATE whatsapp_outbox SET status='envio_em_andamento', lease_ate = now() - interval '1 minute' WHERE id=$1", [id]);
    assert.equal(await marcarIncertos(pool, s.contaId), 1);
    assert.equal(await processarUmaSaida(pool, s.contaId, t, SEG), "vazio");
    assert.equal((await status(id)).status, "incerto");
  });

  it("cinco falhas seguidas de transporte pausam a automação", async () => {
    const t = new Falso();
    t.falha = new Error("boom");
    for (let i = 0; i < 5; i++) { await novaSaida(pool, s, { autoria: "operador" }); await processarUmaSaida(pool, s.contaId, t, SEG); }
    const c = (await pool.query("SELECT automacao_habilitada, estado FROM whatsapp_accounts")).rows[0];
    assert.deepEqual(c, { automacao_habilitada: false, estado: "pausado_por_erro" });
  });

  it("número sem WhatsApp falha explicitamente, sem enviar", async () => {
    const t = new Falso();
    t.jid = null;
    const id = await novaSaida(pool, s);
    assert.equal(await processarUmaSaida(pool, s.contaId, t, SEG), "numero_sem_whatsapp");
    assert.equal((await status(id)).status, "falhou");
  });

  it("parada local (arquivo PAUSA) bloqueia mesmo com a API fora do ar", async () => {
    const t = new Falso();
    fs.writeFileSync(ARQUIVO_PAUSA, "");
    await novaSaida(pool, s, { autoria: "operador" });
    const id = (await pool.query("SELECT id FROM whatsapp_outbox")).rows[0].id;
    assert.equal((await avaliarEnvio(pool, id, SEG)).motivo, "pausa_local_do_gateway");
    assert.equal(await processarUmaSaida(pool, s.contaId, t, SEG), "cancelado");
    fs.rmSync(ARQUIVO_PAUSA);
  });
});

describe("ritmo de resposta", () => {
  it("fórmula: proporcional ao tamanho, com piso de 4 s e teto de 25 s", () => {
    const fixo = () => 0.5; // sem variação (fator 1,0)
    assert.equal(atrasoDeDigitacaoMs("oi", false, fixo), 4000); // piso
    assert.equal(atrasoDeDigitacaoMs("x".repeat(100), false, fixo), 5000); // 2,5 s leitura + 2,5 s digitação
    assert.equal(atrasoDeDigitacaoMs("x".repeat(300), false, fixo), 10000);
    assert.equal(atrasoDeDigitacaoMs("x".repeat(100), true, fixo), 4000); // 1 s + 2,5 s -> piso
    assert.equal(atrasoDeDigitacaoMs("x".repeat(5000), false, fixo), 25000); // teto
    for (let i = 0; i < 50; i++) { const v = atrasoDeDigitacaoMs("x".repeat(300), false); assert.ok(v >= 8500 && v <= 11500); }
  });

  it("IA espera (com 'digitando...') antes de enviar; operador não espera", async () => {
    const esperas: number[] = [];
    const presenca: boolean[] = [];
    const t = new Falso();
    t.digitando = async (_jid: string, ativo: boolean) => { presenca.push(ativo); };
    await novaSaida(pool, s, { texto: "x".repeat(200) });
    assert.equal(await processar(pool, s.contaId, t, SEG, { dormir: async (ms) => { esperas.push(ms); }, atraso: () => 7000 }), "enviado");
    assert.deepEqual(esperas, [7000]);
    assert.deepEqual(presenca, [true]);
    await novaSaida(pool, s, { autoria: "operador" });
    assert.equal(await processar(pool, s.contaId, t, SEG, { dormir: async (ms) => { esperas.push(ms); }, atraso: () => 7000 }), "enviado");
    assert.deepEqual(esperas, [7000]); // operador: nenhuma espera adicional
  });

  it("kill switch DURANTE a espera: nada é enviado e o 'digitando' é desligado", async () => {
    const presenca: boolean[] = [];
    const t = new Falso();
    t.digitando = async (_j: string, ativo: boolean) => { presenca.push(ativo); };
    const id = await novaSaida(pool, s);
    const r = await processar(pool, s.contaId, t, SEG, {
      atraso: () => 5000,
      dormir: async () => { await pool.query("UPDATE whatsapp_accounts SET automacao_habilitada=false, kill_geracao=kill_geracao+1"); },
    });
    assert.equal(r, "cancelado_na_revalidacao");
    assert.equal(t.enviados.length, 0);
    assert.deepEqual(presenca, [true, false]);
    assert.equal((await status(id)).erro, "automacao_pausada");
  });
});

describe("modo copiloto: o gateway não envia nada", () => {
  it("padrão (sem modo_envio) e 'manual' cancelam TUDO: IA, operador e aviso ao operador", async () => {
    for (const config of [{}, { modo_envio: "manual" }, { modo_envio: "qualquer coisa" }]) {
      s = await semear(pool, { config });
      const t = new Falso();
      const ia = await novaSaida(pool, s);
      const op = await novaSaida(pool, s, { autoria: "operador" });
      await pool.query("INSERT INTO whatsapp_operator_notifications (conta_id, texto) VALUES ($1, 'aviso')", [s.contaId]);
      assert.equal(await processarUmaSaida(pool, s.contaId, t, SEG), "cancelado");
      assert.equal(await processarUmaSaida(pool, s.contaId, t, SEG), "cancelado");
      assert.equal((await status(ia)).erro, "modo_envio_manual");
      assert.equal((await status(op)).erro, "modo_envio_manual");
      assert.equal(await processarUmaNotificacao(pool, s.contaId, t, "5511999990000"), "modo_envio_manual");
      assert.equal(t.enviados.length, 0);
    }
  });

  it("só 'automatico' libera o envio", async () => {
    s = await semear(pool, { config: { modo_envio: "automatico" } });
    const t = new Falso();
    await novaSaida(pool, s, { autoria: "operador" });
    assert.equal(await processarUmaSaida(pool, s.contaId, t, SEG), "enviado");
  });
});

describe("avisos ao operador", () => {
  const DESTINO = "5511999990000";
  const criarAviso = async () => (await pool.query(
    "INSERT INTO whatsapp_operator_notifications (conta_id, texto) VALUES ($1, 'Aceite registrado: Alfa') RETURNING id", [s.contaId])).rows[0].id as number;
  const linha = async (id: number) => (await pool.query("SELECT status, tentativas, provider_msg_id, erro FROM whatsapp_operator_notifications WHERE id=$1", [id])).rows[0];

  it("destino vem só do ambiente e precisa ser um número com DDI", () => {
    assert.equal(destinoDoAmbiente("+55 (11) 99999-0000"), "5511999990000");
    assert.equal(destinoDoAmbiente(""), null);
    assert.equal(destinoDoAmbiente(undefined), null);
    assert.equal(destinoDoAmbiente("123"), null);
  });

  it("envia o aviso ao operador, com o id gravado antes do envio, sem tocar a outbox dos leads", async () => {
    const t = new Falso();
    t.jid = `${DESTINO}@s.whatsapp.net`;
    const id = await criarAviso();
    let visto: string | null = null;
    t.antesDeEnviar = async () => { visto = (await linha(id)).provider_msg_id; };
    assert.equal(await processarUmaNotificacao(pool, s.contaId, t, DESTINO), "enviada");
    assert.equal(t.enviados[0].jid, `${DESTINO}@s.whatsapp.net`);
    assert.equal(t.enviados[0].texto, "Aceite registrado: Alfa");
    assert.equal(visto, t.enviados[0].id);
    assert.equal((await linha(id)).status, "enviada");
    assert.equal((await pool.query("SELECT count(*)::int n FROM whatsapp_outbox")).rows[0].n, 0);
  });

  it("não depende de autorização, política, kill switch, janela de horário nem limites de saída", async () => {
    const t = new Falso();
    await pool.query("UPDATE whatsapp_accounts SET automacao_habilitada=false, kill_geracao=kill_geracao+1");
    await pool.query("DELETE FROM whatsapp_authorizations");
    for (let i = 0; i < 6; i++) { // 6 saídas no último minuto: limite dos leads esgotado
      const o = await novaSaida(pool, s, { autoria: "operador" });
      await pool.query("UPDATE whatsapp_outbox SET status='aceita', enviado_em=now() WHERE id=$1", [o]);
    }
    const id = await criarAviso();
    assert.equal(await processarUmaNotificacao(pool, s.contaId, t, DESTINO), "enviada");
    assert.equal((await linha(id)).status, "enviada");
  });

  it("gateway desconectado: o aviso fica pendente (nada é perdido nem marcado como enviado)", async () => {
    const t = new Falso();
    t.ligado = false;
    const id = await criarAviso();
    assert.equal(await processarUmaNotificacao(pool, s.contaId, t, DESTINO), "sem_conexao");
    assert.equal((await linha(id)).status, "pendente");
    t.ligado = true;
    assert.equal(await processarUmaNotificacao(pool, s.contaId, t, DESTINO), "enviada");
  });

  it("sem WHATSAPP_NOTIFICACAO_OPERADOR: nada é enviado e o aviso continua pendente", async () => {
    const t = new Falso();
    const id = await criarAviso();
    assert.equal(await processarUmaNotificacao(pool, s.contaId, t, null), "sem_destino");
    assert.equal((await linha(id)).status, "pendente");
    assert.equal(t.enviados.length, 0);
  });

  it("falha de envio: tenta de novo com espera; depois de 5 tentativas marca como falhou", async () => {
    const t = new Falso();
    t.falha = new Error("socket caiu");
    const id = await criarAviso();
    assert.equal(await processarUmaNotificacao(pool, s.contaId, t, DESTINO), "tentara_de_novo");
    assert.equal((await linha(id)).status, "pendente");
    assert.equal(await processarUmaNotificacao(pool, s.contaId, t, DESTINO), "vazio"); // espera do backoff ainda não venceu
    for (let i = 0; i < 4; i++) {
      await pool.query("UPDATE whatsapp_operator_notifications SET proximo_envio_em = now()");
      await processarUmaNotificacao(pool, s.contaId, t, DESTINO);
    }
    assert.equal((await linha(id)).status, "falhou");
    assert.equal((await linha(id)).tentativas, 5);
  });

  it("destino sem WhatsApp falha explicitamente; parada local (PAUSA) bloqueia; recuperação volta 'enviando' para a fila", async () => {
    const t = new Falso();
    t.jid = null;
    const id = await criarAviso();
    assert.equal(await processarUmaNotificacao(pool, s.contaId, t, DESTINO), "destino_sem_whatsapp");
    assert.equal((await linha(id)).status, "falhou");
    const id2 = await criarAviso();
    fs.writeFileSync(ARQUIVO_PAUSA, "");
    assert.equal(await processarUmaNotificacao(pool, s.contaId, new Falso(), DESTINO), "pausa_local");
    fs.rmSync(ARQUIVO_PAUSA);
    await pool.query("UPDATE whatsapp_operator_notifications SET status='enviando' WHERE id=$1", [id2]);
    assert.equal(await recuperarNotificacoes(pool, s.contaId), 1);
    assert.equal((await linha(id2)).status, "pendente");
  });
});

describe("eventos de entrada", () => {
  it("extrai texto e tipos; ignora grupos, status e canais", () => {
    assert.deepEqual(extrairConteudo({ conversation: "oi" }), { tipoMsg: "texto", texto: "oi" });
    assert.deepEqual(extrairConteudo({ extendedTextMessage: { text: "link" } }), { tipoMsg: "texto", texto: "link" });
    assert.equal(extrairConteudo({ audioMessage: {} }).tipoMsg, "audio");
    assert.equal(extrairConteudo({ reactionMessage: {} }).tipoMsg, "outro");
    assert.equal(jidIndividual("5511999999999@s.whatsapp.net"), true);
    assert.equal(jidIndividual("1203@g.us"), false);
    assert.equal(jidIndividual("status@broadcast"), false);
    assert.equal(jidIndividual("x@newsletter"), false);
  });

  it("evento repetido é descartado pelo índice único; recibo é gravado", async () => {
    const ev = { providerMsgId: "ABC", fromMe: false, jid: "5511991234567@s.whatsapp.net", tipoMsg: "texto", texto: "oi", origem: "tempo_real" as const, ts: SEG };
    assert.equal(await gravarEventoMensagem(pool, s.contaId, ev), true);
    assert.equal(await gravarEventoMensagem(pool, s.contaId, ev), false);
    await gravarRecibo(pool, s.contaId, "ABC", "delivered", ev.jid);
    const n = (await pool.query("SELECT tipo, count(*)::int n FROM whatsapp_inbound_events GROUP BY tipo ORDER BY tipo")).rows;
    assert.deepEqual(n, [{ tipo: "mensagem", n: 1 }, { tipo: "recibo", n: 1 }]);
  });
});
