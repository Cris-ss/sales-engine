import "node:process";
import { randomUUID } from "node:crypto";
import fs from "node:fs";
import { chaveDoAmbiente } from "./crypto.js";
import { criarPool, erroSeguro } from "./db.js";
import { SessaoBaileys } from "./baileys.js";
import { destinoDoAmbiente, processarUmaNotificacao, recuperarNotificacoes } from "./notificacoes.js";
import { marcarIncertos, processarUmaSaida } from "./outbox.js";

/** Carrega o .env da raiz do projeto (mesmo arquivo do restante do sales-engine). */
function carregarEnv() {
  for (const caminho of ["../../.env", ".env"]) {
    if (!fs.existsSync(caminho)) continue;
    for (const linha of fs.readFileSync(caminho, "utf8").split(/\r?\n/)) {
      const m = /^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/.exec(linha);
      if (m && process.env[m[1]] === undefined) process.env[m[1]] = m[2].replace(/^["']|["']$/g, "");
    }
  }
}

async function main() {
  carregarEnv();
  const url = process.env.DATABASE_URL;
  if (!url) throw new Error("DATABASE_URL ausente");
  const chave = chaveDoAmbiente(process.env.WHATSAPP_AUTH_KEY);
  const pool = criarPool(url);
  const leaseId = randomUUID();

  const conta = (await pool.query("SELECT id FROM whatsapp_accounts ORDER BY id LIMIT 1")).rows[0];
  if (!conta) throw new Error("Conta WhatsApp inexistente: abra a tela WhatsApp na interface (ou rode o worker) para criá-la.");
  const contaId: number = conta.id;

  // Uma conta = uma instância ativa. Lease no banco evita duas conexões disputando a mesma sessão.
  const renovar = async () => (await pool.query(
    `UPDATE whatsapp_accounts SET gateway_lease_id=$2, gateway_lease_ate=now()+interval '30 seconds', heartbeat_em=now()
       WHERE id=$1 AND (gateway_lease_id IS NULL OR gateway_lease_id=$2 OR gateway_lease_ate < now()) RETURNING id`, [contaId, leaseId])).rowCount;
  // Depois de um kill/restart (ex.: PM2 no Windows não envia sinal de encerramento) o lease do processo anterior leva até ~30 s para
  // vencer: espera em vez de falhar na hora, para o reinício automático não esgotar as tentativas.
  for (let tentativa = 0; !(await renovar()); tentativa++) {
    if (tentativa >= 15) throw new Error("Outra instância do gateway já está ativa para esta conta (lease não venceu em 45 s).");
    if (tentativa === 0) console.warn("[gateway] lease em uso por outra instância (ou por uma que acabou de cair): aguardando até 45 s...");
    await new Promise((r) => setTimeout(r, 3000));
  }
  setInterval(() => { renovar().then((n) => { if (!n) { console.error("[gateway] lease perdido; encerrando"); process.exit(1); } }).catch(() => undefined); }, 10_000);

  const incertos = await marcarIncertos(pool, contaId);
  if (incertos) console.warn(`[gateway] ${incertos} envio(s) interrompido(s) marcados como INCERTOS (não serão reenviados automaticamente).`);

  const destinoOperador = destinoDoAmbiente(process.env.WHATSAPP_NOTIFICACAO_OPERADOR);
  await recuperarNotificacoes(pool, contaId);
  console.log(destinoOperador
    ? "[gateway] avisos de aceite serão enviados ao número definido em WHATSAPP_NOTIFICACAO_OPERADOR."
    : "[gateway] WHATSAPP_NOTIFICACAO_OPERADOR não definida (ou inválida): avisos de aceite ficam PENDENTES até você defini-la e reiniciar.");

  const sessao = new SessaoBaileys(pool, contaId, chave);
  if (await sessao.temSessaoPareada()) {
    console.log("[gateway] sessão pareada encontrada: reconectando sem novo QR.");
    await sessao.iniciar();
  } else {
    console.log("[gateway] sem sessão pareada: aguardando o comando 'Conectar' da interface (nada é conectado sozinho).");
  }

  let ocupado = false;
  setInterval(() => {
    if (ocupado) return;
    ocupado = true;
    (async () => {
      const c = (await pool.query("SELECT comando_pendente FROM whatsapp_accounts WHERE id=$1", [contaId])).rows[0];
      if (c?.comando_pendente) {
        await pool.query("UPDATE whatsapp_accounts SET comando_pendente=NULL WHERE id=$1", [contaId]);
        if (c.comando_pendente === "conectar") {
          const estado = (await pool.query("SELECT estado FROM whatsapp_accounts WHERE id=$1", [contaId])).rows[0].estado;
          if (estado === "requer_pareamento") await sessao.limparSessao(); // logout anterior: sessão inútil; novo QR
          await sessao.iniciar();
        } else if (c.comando_pendente === "desconectar") await sessao.parar();
      }
      // Avisos internos ao operador: fluxo separado, sem os limites/autorizações dos leads.
      for (let i = 0; i < 3; i++) {
        const n = await processarUmaNotificacao(pool, contaId, sessao, destinoOperador);
        if (n !== "enviada" && n !== "tentara_de_novo" && n !== "destino_sem_whatsapp" && n !== "falhou") break;
      }
      for (let i = 0; i < 5; i++) { // no máximo 5 por ciclo; os limites por minuto ficam no guard
        const r = await processarUmaSaida(pool, contaId, sessao);
        if (r === "vazio" || r === "sem_conexao") break;
      }
    })().catch((e) => console.error("[gateway] ciclo:", erroSeguro(e))).finally(() => { ocupado = false; });
  }, 500);

  const sair = async () => {
    await sessao.parar().catch(() => undefined);
    await pool.query("UPDATE whatsapp_accounts SET gateway_lease_id=NULL, gateway_lease_ate=NULL WHERE id=$1 AND gateway_lease_id=$2", [contaId, leaseId]).catch(() => undefined);
    process.exit(0);
  };
  process.on("SIGINT", sair);
  process.on("SIGTERM", sair);
}

main().catch((e) => { console.error("[gateway] falha fatal:", erroSeguro(e)); process.exit(1); });
