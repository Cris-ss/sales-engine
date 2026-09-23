import type { LeadResumo } from "../../api/types";
import { ChannelBadges, EmailStatusBadge, ScoreBadge, StageBadge } from "../../components/badges";
import { useFiltros } from "../../lib/filtros";
import { formatarDataHora, localidade, titulo } from "../../lib/format";
import { AcoesRapidas } from "./LeadTable";

export function LeadCard({ lead }: { lead: LeadResumo }) {
  const { setLocal } = useFiltros();
  return (
    <article className="card-lead">
      <header>
        <button className="link" onClick={() => setLocal("lead", lead.id)}>{titulo(lead.nome)}</button>
        <div className="muted">{lead.nicho_nome} · {localidade(lead.municipio, lead.uf)}</div>
      </header>
      <div className="badges">
        <ScoreBadge score={lead.score} faixa={lead.faixa_score} />
        <StageBadge lead={lead} />
      </div>
      <ChannelBadges lead={lead} />
      <div>
        <EmailStatusBadge status={lead.email_status} qtd={lead.qtd_emails_enviados} />
        {lead.email_enviado_em && <span className="muted"> {formatarDataHora(lead.email_enviado_em)}</span>}
      </div>
      <AcoesRapidas lead={lead} />
    </article>
  );
}
