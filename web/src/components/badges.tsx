import type { EmailStatus, Faixa, LeadResumo } from "../api/types";

const ROTULO_FAIXA: Record<Faixa, string> = {
  sem_score: "Sem score",
  baixo: "Baixo",
  neutro: "Neutro",
  medio: "Médio",
  alto: "Alto",
};

const ICONE_FAIXA: Record<Faixa, string> = { sem_score: "○", baixo: "▼", neutro: "■", medio: "◆", alto: "▲" };

const AJUDA_FAIXA: Record<Faixa, string> = {
  sem_score: "Ainda não há score para este lead (não é zero).",
  baixo: "Avaliado abaixo do padrão conservador (< 55).",
  neutro:
    "Padrão conservador do modelo (55): o site não trouxe sinal específico. NÃO é uma avaliação real de fit médio.",
  medio: "Avaliado acima do padrão conservador e abaixo de 65.",
  alto: "Avaliado com fit alto (≥ 65).",
};

/** Sempre número + rótulo + ícone: a cor nunca é a única informação (daltonismo/impressão). */
export function ScoreBadge({ score, faixa }: { score: number | null; faixa: Faixa }) {
  return (
    <span className={`badge faixa-${faixa}`} title={AJUDA_FAIXA[faixa]}>
      <span aria-hidden="true">{ICONE_FAIXA[faixa]}</span>{" "}
      {score === null ? ROTULO_FAIXA.sem_score : `${Math.round(score)} · ${ROTULO_FAIXA[faixa]}`}
    </span>
  );
}

export function ChannelBadges({ lead }: { lead: Pick<LeadResumo, "email_confirmado" | "formulario_confirmado" | "whatsapp_apto"> }) {
  const algum = lead.email_confirmado || lead.formulario_confirmado || lead.whatsapp_apto;
  return (
    <span className="badges">
      {lead.email_confirmado && <span className="badge canal-email" title="Email confirmado pelo pipeline">✉ Email</span>}
      {lead.formulario_confirmado && <span className="badge canal-form" title="Formulário de contato confirmado">▤ Formulário</span>}
      {lead.whatsapp_apto && (
        <span className="badge canal-wpp" title="Telefone em formato de celular. Isto NÃO comprova que há WhatsApp neste número.">
          ☏ WhatsApp? <small>(não verificado)</small>
        </span>
      )}
      {!algum && <span className="badge canal-nenhum">Sem canal</span>}
    </span>
  );
}

const ROTULO_EMAIL: Record<EmailStatus, string> = {
  enviado: "Enviado (aceito pelo SMTP)",
  pendente: "Pendente",
  falhou: "Falha (segue pendente)",
  nenhum: "—",
};

export function EmailStatusBadge({ status, qtd }: { status: EmailStatus; qtd?: number }) {
  if (status === "nenhum") return <span className="muted">—</span>;
  return (
    <span
      className={`badge email-${status}`}
      title={
        status === "enviado"
          ? "O servidor SMTP aceitou a mensagem. Isso não comprova entrega, leitura nem resposta."
          : undefined
      }
    >
      {ROTULO_EMAIL[status]}
      {status === "enviado" && qtd && qtd > 1 ? ` ×${qtd}` : ""}
    </span>
  );
}

export function StageBadge({ lead }: { lead: Pick<LeadResumo, "estagio" | "estagio_derivado" | "coluna"> }) {
  const nome = lead.estagio.replace("_", " ");
  return (
    <span className={`badge coluna-${lead.coluna}`} title={lead.estagio_derivado ? "Sem histórico no funil: estágio inferido (email enviado ⇒ contatada; senão encontrada). Nada foi gravado." : undefined}>
      {nome}
      {lead.estagio_derivado && <span aria-label="derivado"> ᵈ</span>}
    </span>
  );
}
