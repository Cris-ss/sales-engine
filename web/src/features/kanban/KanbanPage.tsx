import { DndContext, DragOverlay, KeyboardSensor, PointerSensor, useSensor, useSensors, type DragEndEvent, type DragStartEvent } from "@dnd-kit/core";
import { useState } from "react";
import { useKanbanResumo, useOpcoes, useTransicao } from "../../api/hooks";
import type { Coluna, LeadResumo } from "../../api/types";
import { ActiveFilterChips, GlobalFilterBar } from "../../components/GlobalFilterBar";
import { ErroBox, useToast } from "../../components/states";
import { paramsApi, useFiltros } from "../../lib/filtros";
import { KanbanCard } from "./KanbanCard";
import { KanbanColumn } from "./KanbanColumn";

export function KanbanPage() {
  const { filtros } = useFiltros();
  // coluna/estágio não filtram o Kanban: as colunas SÃO o estágio
  const params = paramsApi(filtros, ["coluna", "estagio"]);
  const { data: opcoes } = useOpcoes();
  const resumo = useKanbanResumo(params);
  const toast = useToast();
  const [ativo, setAtivo] = useState<LeadResumo | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor),
  );

  const mut = useTransicao({
    onErro: (msg, conflito) =>
      toast(
        "erro",
        conflito
          ? "Conflito: este lead foi alterado em outra aba/processo. A mudança foi desfeita e os dados recarregados."
          : `Não foi possível mover: ${msg}. A mudança foi desfeita.`,
      ),
    onSucesso: () => toast("ok", "Lead movido."),
  });

  const mover = (lead: LeadResumo, destino: Coluna) => {
    // Mesma coluna: nada a fazer (não sobrescreve um subestágio como "proposta").
    if (lead.coluna === destino) return;
    const canonico = opcoes?.colunas.find((c) => c.codigo === destino)?.estagio_canonico;
    if (!canonico) return;
    mut.mutate({ lead, estagioDestino: canonico, colunaDestino: destino });
  };

  const aoSoltar = (e: DragEndEvent) => {
    setAtivo(null);
    const lead = e.active.data.current?.lead as LeadResumo | undefined;
    if (lead && e.over) mover(lead, e.over.id as Coluna);
  };

  return (
    <>
      <GlobalFilterBar />
      <ActiveFilterChips />
      <p className="muted nota-kanban">
        Arraste o cartão pela alça (⠿) ou use o menu “Mover para…”. Cada mudança acrescenta uma linha no histórico do funil; nada é sobrescrito.
        “Contatado” agrupa contatada, respondeu, em negociação e proposta — o estágio detalhado aparece no cartão.
      </p>
      {resumo.error && <ErroBox erro={resumo.error} onTentar={() => resumo.refetch()} />}
      <DndContext
        sensors={sensors}
        onDragStart={(e: DragStartEvent) => setAtivo((e.active.data.current?.lead as LeadResumo) ?? null)}
        onDragEnd={aoSoltar}
        onDragCancel={() => setAtivo(null)}
      >
        <div className="kanban">
          {(opcoes?.colunas ?? []).map((c) => (
            <KanbanColumn
              key={c.codigo}
              coluna={c.codigo}
              rotulo={c.rotulo}
              total={resumo.data?.colunas.find((x) => x.codigo === c.codigo)?.total}
              params={params}
              opcoes={opcoes}
              onMover={mover}
            />
          ))}
        </div>
        <DragOverlay>{ativo ? <KanbanCard lead={ativo} onMover={() => {}} sobreposicao /> : null}</DragOverlay>
      </DndContext>
    </>
  );
}
