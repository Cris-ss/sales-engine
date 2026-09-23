import { PAGE_SIZE, useLeads } from "../../api/hooks";
import { ActiveFilterChips, GlobalFilterBar } from "../../components/GlobalFilterBar";
import { Carregando, ErroBox, Vazio } from "../../components/states";
import { paramsApi, useFiltros } from "../../lib/filtros";
import { LeadCard } from "./LeadCard";
import { LeadTable } from "./LeadTable";

export function LeadPagination({ page, total }: { page: number; total: number }) {
  const { setLocal } = useFiltros();
  const paginas = Math.max(1, Math.ceil(total / PAGE_SIZE));
  return (
    <nav className="paginacao" aria-label="Paginação">
      <button className="btn" disabled={page <= 1} onClick={() => setLocal("page", 1)}>« Primeira</button>
      <button className="btn" disabled={page <= 1} onClick={() => setLocal("page", page - 1)}>‹ Anterior</button>
      <span aria-live="polite">Página {page} de {paginas} · {total.toLocaleString("pt-BR")} leads</span>
      <button className="btn" disabled={page >= paginas} onClick={() => setLocal("page", page + 1)}>Próxima ›</button>
      <button className="btn" disabled={page >= paginas} onClick={() => setLocal("page", paginas)}>Última »</button>
    </nav>
  );
}

export function LeadListPage() {
  const { filtros, page, vista, setLocal, limparFiltros } = useFiltros();
  const { data, isLoading, isFetching, error, refetch } = useLeads(paramsApi(filtros), page);

  return (
    <>
      <GlobalFilterBar extras />
      <ActiveFilterChips />
      <div className="barra-lista">
        <span className="muted" aria-live="polite">
          {data ? `${data.total.toLocaleString("pt-BR")} leads` : ""} {isFetching && !isLoading ? "· atualizando…" : ""}
        </span>
        <div role="group" aria-label="Modo de exibição" className="segmentado">
          <button className={vista === "tabela" ? "ativo" : ""} aria-pressed={vista === "tabela"} onClick={() => setLocal("vista", "tabela")}>Tabela</button>
          <button className={vista === "cards" ? "ativo" : ""} aria-pressed={vista === "cards"} onClick={() => setLocal("vista", "cards")}>Cards</button>
        </div>
      </div>

      {isLoading && <Carregando texto="Carregando leads…" />}
      {error && <ErroBox erro={error} onTentar={() => refetch()} />}
      {data && data.itens.length === 0 && (
        <Vazio texto="Nenhum lead encontrado com esses filtros.">
          <button className="btn" onClick={limparFiltros}>Limpar filtros</button>
        </Vazio>
      )}
      {data && data.itens.length > 0 && (
        <>
          {vista === "tabela" ? (
            <LeadTable itens={data.itens} />
          ) : (
            <div className="grade-cards">{data.itens.map((l) => <LeadCard key={l.id} lead={l} />)}</div>
          )}
          <LeadPagination page={data.page} total={data.total} />
        </>
      )}
    </>
  );
}
