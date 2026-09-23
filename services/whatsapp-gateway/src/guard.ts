import fs from "node:fs";
import type { Db } from "./db.js";

export interface Veredito {
  acao: "enviar" | "cancelar" | "adiar";
  motivo?: string;
  ateSegundos?: number;
}

interface Limites {
  dias_semana: number[];
  hora_inicio: string;
  hora_fim: string;
  novos_contatos_dia: number;
  intervalo_primeiros_contatos_seg: number;
  saidas_por_minuto: number;
  respostas_por_conversa_hora: number;
}

/** Só "automatico" libera o envio. Qualquer outro valor (ou ausência) = modo copiloto: falha do lado seguro. */
export function modoAutomatico(config: { modo_envio?: string }): boolean {
  return config?.modo_envio === "automatico";
}

/** Parada local: a existência deste arquivo bloqueia qualquer envio, mesmo com a API fora do ar. */
export const ARQUIVO_PAUSA = process.env.WHATSAPP_PAUSA_FILE ?? "PAUSA";

/** Janela de envio no fuso da conta. */
export function dentroDaJanela(agora: Date, tz: string, l: Pick<Limites, "dias_semana" | "hora_inicio" | "hora_fim">): boolean {
  const partes = new Intl.DateTimeFormat("en-US", { timeZone: tz, weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
    .formatToParts(agora);
  const dia = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].indexOf(partes.find((p) => p.type === "weekday")!.value);
  const hhmm = `${partes.find((p) => p.type === "hour")!.value}:${partes.find((p) => p.type === "minute")!.value}`;
  return l.dias_semana.includes(dia) && hhmm >= l.hora_inicio && hhmm < l.hora_fim;
}

const ENVIADOS = "('envio_em_andamento','aceita','entregue','lida')";

/**
 * Repete, em SQL, as verificações de segurança do lado Python (etapa7_whatsapp/guards.py).
 * O gateway não autoriza nem altera regras: só lê e decide enviar, adiar ou cancelar.
 */
export async function avaliarEnvio(db: Db, outboxId: number, agora: Date = new Date()): Promise<Veredito> {
  if (fs.existsSync(ARQUIVO_PAUSA)) return { acao: "cancelar", motivo: "pausa_local_do_gateway" };
  const o = (await db.query("SELECT * FROM whatsapp_outbox WHERE id=$1", [outboxId])).rows[0];
  if (!o) return { acao: "cancelar", motivo: "outbox_inexistente" };
  const conta = (await db.query("SELECT * FROM whatsapp_accounts WHERE id=$1", [o.conta_id])).rows[0];
  const conversa = (await db.query("SELECT * FROM whatsapp_conversations WHERE id=$1", [o.conversa_id])).rows[0];
  if (!conta || !conversa) return { acao: "cancelar", motivo: "conta_ou_conversa_inexistente" };
  const ia = o.autoria === "ia";

  const sup = await db.query("SELECT 1 FROM whatsapp_suppressions WHERE conta_id=$1 AND contato_id=$2", [conta.id, o.contato_id]);
  if (sup.rowCount) return { acao: "cancelar", motivo: "contato_suprimido" };
  const aut = (await db.query(
    "SELECT * FROM whatsapp_authorizations WHERE conta_id=$1 AND contato_id=$2 AND status='ativa'", [conta.id, o.contato_id])).rows[0];
  if (!aut || (aut.expira_em && new Date(aut.expira_em) <= agora)) return { acao: "cancelar", motivo: "sem_autorizacao_ativa" };

  const pol = (await db.query("SELECT versao, config FROM commercial_policies WHERE ativa")).rows[0];
  const lim: Limites = pol.config.limites;
  // Garantia dupla do modo copiloto: com modo_envio diferente de "automatico" (inclusive ausente) o gateway NÃO envia nada,
  // nem da IA nem do operador, mesmo que um bug no worker tenha gravado algo na outbox.
  if (!modoAutomatico(pol.config)) return { acao: "cancelar", motivo: "modo_envio_manual" };
  if (ia) {
    if (!conta.automacao_habilitada) return { acao: "cancelar", motivo: "automacao_pausada" };
    if (o.kill_geracao !== conta.kill_geracao) return { acao: "cancelar", motivo: "kill_switch_acionado" };
    if (o.versao_autorizacao !== aut.versao) return { acao: "cancelar", motivo: "autorizacao_mudou" };
    if (!o.mensagem_de_transicao) {
      if (conversa.controle !== "automatizada") return { acao: "cancelar", motivo: `controle_${conversa.controle}` };
      if (o.versao_conversa !== conversa.versao) return { acao: "cancelar", motivo: "conversa_mudou" };
    }
    if (o.versao_politica !== pol.versao) return { acao: "cancelar", motivo: "politica_mudou" };
    if (!dentroDaJanela(agora, conta.timezone, lim)) return { acao: "adiar", motivo: "fora_do_horario", ateSegundos: 300 };
  }

  const porMin = (await db.query(
    `SELECT count(*)::int n FROM whatsapp_outbox WHERE conta_id=$1 AND status IN ${ENVIADOS} AND enviado_em > $2`,
    [conta.id, new Date(agora.getTime() - 60_000)])).rows[0].n;
  if (porMin >= lim.saidas_por_minuto) return { acao: "adiar", motivo: "limite_saidas_por_minuto", ateSegundos: 15 };

  if (ia && !o.primeiro_contato) {
    const naHora = (await db.query(
      `SELECT count(*)::int n FROM whatsapp_outbox WHERE conversa_id=$1 AND autoria='ia' AND status IN ${ENVIADOS} AND enviado_em > $2`,
      [conversa.id, new Date(agora.getTime() - 3_600_000)])).rows[0].n;
    if (naHora >= lim.respostas_por_conversa_hora) return { acao: "cancelar", motivo: "limite_respostas_hora" };
  }
  if (ia && o.primeiro_contato) {
    const dia = new Intl.DateTimeFormat("en-CA", { timeZone: conta.timezone }).format(agora); // AAAA-MM-DD local
    const hoje = (await db.query(
      `SELECT count(*)::int n FROM whatsapp_outbox WHERE conta_id=$1 AND primeiro_contato AND status IN ${ENVIADOS}
         AND (enviado_em AT TIME ZONE $2)::date = $3::date`, [conta.id, conta.timezone, dia])).rows[0].n;
    if (hoje >= lim.novos_contatos_dia) return { acao: "adiar", motivo: "limite_novos_contatos_dia", ateSegundos: 3600 };
    const ultimo = (await db.query(
      `SELECT max(enviado_em) t FROM whatsapp_outbox WHERE conta_id=$1 AND primeiro_contato AND status IN ${ENVIADOS}`, [conta.id])).rows[0].t;
    if (ultimo) {
      const falta = new Date(ultimo).getTime() + lim.intervalo_primeiros_contatos_seg * 1000 - agora.getTime();
      if (falta > 0) return { acao: "adiar", motivo: "intervalo_entre_primeiros_contatos", ateSegundos: Math.ceil(falta / 1000) };
    }
  }
  return { acao: "enviar" };
}
