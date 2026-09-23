import { useDroppable } from "@dnd-kit/core";
import type { Params } from "../../api/client";
import { useKanbanColuna } from "../../api/hooks";
import type { Coluna, LeadResumo, OpcoesFiltros } from "../../api/types";
import { Carregando, ErroBox } from "../../components/states";
import { KanbanCard } from "./KanbanCard";

interface Props {
  coluna: Coluna;
  rotulo: string;
  total: number | undefined;
  params: Params;
  opcoes?: OpcoesFiltros;
  onMover: (lead: LeadResumo, destino: Coluna) => void;
}

export function KanbanColumn({ coluna, rotulo, total, params, opcoes, onMover }: Props) {
  const { setNodeRef, isOver } = useDroppable({ id: coluna });
  const q = useKanbanColuna(coluna, params);
  const itens = q.data?.pages.flatMap((p) => p.itens) ?? [];
  const totalReal = q.data?.pages[0]?.total ?? total ?? 0;

  return (
    <section ref={setNodeRef} className={`kcol ${isOver ? "sobre" : ""}`} aria-label={`Coluna ${rotulo}`} data-coluna={coluna}>
      <h3>
        {rotulo} <span className="contagem" aria-label={`${totalReal} leads`}>{totalReal.toLocaleString("pt-BR")}</span>
      </h3>
      <div className="kcol-corpo">
        {q.isLoading && <Carregando />}
        {q.error && <ErroBox erro={q.error} onTentar={() => q.refetch()} />}
        {!q.isLoading && itens.length === 0 && !q.error && <p className="muted">Nenhum lead nesta coluna.</p>}
        {itens.map((l) => <KanbanCard key={l.id} lead={l} opcoes={opcoes} onMover={onMover} />)}
        {q.hasNextPage && (
          <button className="btn" disabled={q.isFetchingNextPage} onClick={() => q.fetchNextPage()}>
            {q.isFetchingNextPage ? "Carregando…" : `Carregar mais (mostrando ${itens.length} de ${totalReal})`}
          </button>
        )}
      </div>
    </section>
  );
}
