import { flexRender, getCoreRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";
import { useMemo } from "react";
import type { LeadResumo } from "../../api/types";
import { ChannelBadges, EmailStatusBadge, ScoreBadge, StageBadge } from "../../components/badges";
import { useToast } from "../../components/states";
import { useFiltros } from "../../lib/filtros";
import { formatarDataHora, localidade, titulo } from "../../lib/format";
import { abrirWhatsapp } from "../../lib/whatsapp";

function urlPesquisa(lead: LeadResumo): string {
  return `https://www.google.com/search?q=${encodeURIComponent(lead.consulta_busca)}`;
}

/** Ações rápidas de uma linha/cartão: detalhes, pesquisa, site e WhatsApp manual. */
export function AcoesRapidas({ lead }: { lead: LeadResumo }) {
  const { setLocal } = useFiltros();
  const toast = useToast();
  return (
    <span className="acoes">
      <button className="btn btn-pequeno" onClick={() => setLocal("lead", lead.id)}>Detalhes</button>
      <a
        className="btn btn-pequeno"
        href={urlPesquisa(lead)}
        target="_blank"
        rel="noopener noreferrer"
        title="Pesquisar no Google"
        aria-label={`Buscar ${lead.nome} no Google`}
      >
        🔍 Buscar
      </a>
      {lead.site_url && (
        <a className="btn btn-pequeno" href={lead.site_url} target="_blank" rel="noopener noreferrer" aria-label={`Abrir site de ${lead.nome}`}>Site ↗</a>
      )}
      <button
        className="btn btn-pequeno"
        disabled={!lead.whatsapp_apto}
        title={lead.whatsapp_apto ? "Abre o WhatsApp para você enviar manualmente (número não verificado)" : "Sem telefone apto a link (fixo, inválido ou ausente)"}
        onClick={async () => {
          try {
            const r = await abrirWhatsapp(lead.id);
            if (!r.ok) toast("aviso", r.motivo ?? "Não foi possível abrir o WhatsApp.");
          } catch (e) {
            toast("erro", (e as Error).message);
          }
        }}
      >
        WhatsApp
      </button>
    </span>
  );
}

const ORDENAVEIS: Record<string, string> = {
  nome: "nome", nicho: "nicho", local: "municipio", score: "score", estagio: "estagio", email: "email_enviado_em",
};

export function LeadTable({ itens }: { itens: LeadResumo[] }) {
  const { filtros, setFiltros, setLocal } = useFiltros();
  const sort = filtros.sort ?? "score";
  const order = filtros.order ?? "desc";

  const colunas = useMemo<ColumnDef<LeadResumo>[]>(
    () => [
      { id: "nome", header: "Empresa", cell: ({ row }) => (
        <>
        <button className="link" onClick={() => setLocal("lead", row.original.id)}>{titulo(row.original.nome)}</button>
          {row.original.fonte === "manual_operador" && <span className="tag-origem" title="Cadastrado manualmente pelo operador (atalho do WhatsApp)"> manual</span>}
        </>
      ) },
      { id: "nicho", header: "Nicho", cell: ({ row }) => row.original.nicho_nome },
      { id: "local", header: "Município / UF", cell: ({ row }) => localidade(row.original.municipio, row.original.uf) },
      { id: "score", header: "Score", cell: ({ row }) => <ScoreBadge score={row.original.score} faixa={row.original.faixa_score} /> },
      { id: "estagio", header: "Estágio", cell: ({ row }) => <StageBadge lead={row.original} /> },
      { id: "canais", header: "Canais", cell: ({ row }) => <ChannelBadges lead={row.original} /> },
      { id: "email", header: "Email enviado", cell: ({ row }) => (
        <>
          <EmailStatusBadge status={row.original.email_status} qtd={row.original.qtd_emails_enviados} />
          {row.original.email_enviado_em && <div className="muted">{formatarDataHora(row.original.email_enviado_em)}</div>}
        </>
      ) },
      { id: "acoes", header: "Ações", cell: ({ row }) => <AcoesRapidas lead={row.original} /> },
    ],
    [setLocal],
  );

  const tabela = useReactTable({ data: itens, columns: colunas, getCoreRowModel: getCoreRowModel(), manualSorting: true, manualPagination: true });

  return (
    <div className="tabela-wrap">
      <table className="tabela">
        <thead>
          {tabela.getHeaderGroups().map((g) => (
            <tr key={g.id}>
              {g.headers.map((h) => {
                const campo = ORDENAVEIS[h.column.id];
                const ativo = campo && sort === campo;
                return (
                  <th key={h.id} aria-sort={ativo ? (order === "asc" ? "ascending" : "descending") : undefined}>
                    {campo ? (
                      <button
                        className="th-btn"
                        onClick={() => setFiltros({ sort: campo, order: ativo && order === "desc" ? "asc" : "desc" })}
                      >
                        {flexRender(h.column.columnDef.header, h.getContext())}
                        <span aria-hidden="true">{ativo ? (order === "asc" ? " ▲" : " ▼") : ""}</span>
                      </button>
                    ) : (
                      flexRender(h.column.columnDef.header, h.getContext())
                    )}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {tabela.getRowModel().rows.map((r) => (
            <tr key={r.id}>
              {r.getVisibleCells().map((c) => (
                <td key={c.id}>{flexRender(c.column.columnDef.cell, c.getContext())}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
