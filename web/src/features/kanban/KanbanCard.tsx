import { useDraggable } from "@dnd-kit/core";
import type { Coluna, LeadResumo, OpcoesFiltros } from "../../api/types";
import { ChannelBadges, EmailStatusBadge, ScoreBadge, StageBadge } from "../../components/badges";
import { useFiltros } from "../../lib/filtros";
import { localidade, titulo } from "../../lib/format";

interface Props {
  lead: LeadResumo;
  opcoes?: OpcoesFiltros;
  onMover: (lead: LeadResumo, destino: Coluna) => void;
  sobreposicao?: boolean; // renderização dentro do DragOverlay
}

export function KanbanCard({ lead, opcoes, onMover, sobreposicao }: Props) {
  const { setLocal } = useFiltros();
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: lead.id, data: { lead }, disabled: sobreposicao });

  return (
    <article
      ref={sobreposicao ? undefined : setNodeRef}
      className={`kcard ${isDragging ? "arrastando" : ""} ${sobreposicao ? "sobreposicao" : ""}`}
      data-lead-id={lead.id}
    >
      <div className="kcard-topo">
        {/* alça de arraste separada: o resto do cartão continua clicável e acessível */}
        <button className="alca" aria-label={`Arrastar ${titulo(lead.nome)} (ou use o menu "Mover para")`} {...(sobreposicao ? {} : { ...listeners, ...attributes })}>⠿</button>
        <button className="link" onClick={() => setLocal("lead", lead.id)}>{titulo(lead.nome)}</button>
      </div>
      <div className="muted">{lead.nicho_nome} · {localidade(lead.municipio, lead.uf)}</div>
      <div className="badges">
        <ScoreBadge score={lead.score} faixa={lead.faixa_score} />
        <StageBadge lead={lead} />
      </div>
      <ChannelBadges lead={lead} />
      <EmailStatusBadge status={lead.email_status} qtd={lead.qtd_emails_enviados} />
      {!sobreposicao && (
        <label className="mover">
          <span className="sr-only">Mover {lead.nome} para</span>
          <select
            value=""
            aria-label={`Mover ${titulo(lead.nome)} para outra coluna`}
            onChange={(e) => e.target.value && onMover(lead, e.target.value as Coluna)}
          >
            <option value="">Mover para…</option>
            {(opcoes?.colunas ?? []).filter((c) => c.codigo !== lead.coluna).map((c) => (
              <option key={c.codigo} value={c.codigo}>{c.rotulo}</option>
            ))}
          </select>
        </label>
      )}
    </article>
  );
}
