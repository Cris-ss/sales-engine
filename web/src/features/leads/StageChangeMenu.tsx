import { useState } from "react";
import { useOpcoes, useTransicao } from "../../api/hooks";
import type { LeadResumo } from "../../api/types";
import { useToast } from "../../components/states";

/** Mudança de estágio por menu (acessível por teclado; alternativa ao arrastar no Kanban). */
export function StageChangeMenu({ lead }: { lead: Pick<LeadResumo, "id" | "funil_id" | "coluna" | "nome" | "estagio"> }) {
  const { data: opcoes } = useOpcoes();
  const toast = useToast();
  const [destino, setDestino] = useState("");
  const [obs, setObs] = useState("");
  const mut = useTransicao({
    onErro: (msg, conflito) =>
      toast("erro", conflito ? "Este lead foi alterado em outro lugar. Os dados foram recarregados — confira e tente de novo." : msg),
    onSucesso: () => {
      toast("ok", "Estágio atualizado.");
      setDestino("");
      setObs("");
    },
  });

  return (
    <form
      className="stage-menu"
      onSubmit={(e) => {
        e.preventDefault();
        const est = opcoes?.estagios.find((s) => s.codigo === destino);
        if (!est) return;
        mut.mutate({ lead, estagioDestino: est.codigo, colunaDestino: est.coluna, observacao: obs });
      }}
    >
      <label className="campo">
        <span>Mover para</span>
        <select value={destino} onChange={(e) => setDestino(e.target.value)} aria-label="Novo estágio">
          <option value="">Escolha o estágio…</option>
          {(opcoes?.estagios ?? []).filter((s) => s.codigo !== lead.estagio).map((s) => (
            <option key={s.codigo} value={s.codigo}>{s.rotulo}</option>
          ))}
        </select>
      </label>
      <label className="campo">
        <span>Observação (opcional)</span>
        <input value={obs} onChange={(e) => setObs(e.target.value)} maxLength={300} />
      </label>
      <button className="btn btn-primario" disabled={!destino || mut.isPending}>
        {mut.isPending ? "Movendo…" : "Mover"}
      </button>
    </form>
  );
}
