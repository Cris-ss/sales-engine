import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { createContext, useContext } from "react";
import { get, post, type Params } from "./client";
import type {
  Bbox, CidadeSugestao, Coluna, ContatoItem, Conversao, FunilItem, KanbanResumo, LeadDetalhe, LeadResumo, LoteProspeccao, MetricasFunil,
  MetricasResumo, Nicho, OpcoesFiltros, Pagina, RespostaMapa, ScoreItem, TransicaoResposta, WhatsAppLink,
} from "./types";

/** Atualização automática opcional (leve) para refletir alterações feitas pelo CLI. */
export const AutoRefreshContext = createContext<number | false>(false);
const useIntervalo = () => useContext(AutoRefreshContext);

export const PAGE_SIZE = 50;
export const KANBAN_PAGE_SIZE = 20;

export function useOpcoes(uf?: string) {
  return useQuery({
    queryKey: ["opcoes", uf ?? null],
    queryFn: ({ signal }) => get<OpcoesFiltros>("/filtros/opcoes", { uf }, signal),
    staleTime: 5 * 60_000,
  });
}

export function useNichos() {
  return useQuery({ queryKey: ["nichos"], queryFn: ({ signal }) => get<Nicho[]>("/nichos", {}, signal), staleTime: 5 * 60_000 });
}

export function useLotesProspeccao() {
  return useQuery({
    queryKey: ["prospeccoes"],
    queryFn: ({ signal }) => get<LoteProspeccao[]>("/prospeccoes", {}, signal),
    refetchInterval: (q) => (q.state.data?.some((l) => l.status === "pendente" || l.status === "executando") ? 2_000 : false),
  });
}

export function useCidades(termo: string) {
  return useQuery({
    queryKey: ["prospeccoes", "cidades", termo],
    queryFn: ({ signal }) => get<CidadeSugestao[]>("/prospeccoes/cidades", { q: termo }, signal),
    enabled: termo.trim().length >= 1,
    staleTime: 10 * 60_000,
  });
}

export function useCriarLoteProspeccao() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (dados: { nicho_id: number; uf: string; fonte: "osm" | "apify"; cidade?: string; raio_km?: number; limite: number; confirmar: boolean }) => post<LoteProspeccao>("/prospeccoes", dados),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["prospeccoes"] }),
  });
}

export function useLeads(params: Params, page: number) {
  const refetchInterval = useIntervalo();
  return useQuery({
    queryKey: ["leads", params, page],
    queryFn: ({ signal }) => get<Pagina<LeadResumo>>("/leads", { ...params, page, page_size: PAGE_SIZE }, signal),
    placeholderData: keepPreviousData,
    refetchInterval,
  });
}

export function useLead(id: number | null) {
  const refetchInterval = useIntervalo();
  return useQuery({
    queryKey: ["lead", id],
    queryFn: ({ signal }) => get<LeadDetalhe>(`/leads/${id}`, {}, signal),
    enabled: id !== null,
    refetchInterval,
  });
}

export const useScores = (id: number | null) =>
  useQuery({ queryKey: ["lead", id, "scores"], queryFn: ({ signal }) => get<Pagina<ScoreItem>>(`/leads/${id}/scores`, { page_size: 20 }, signal), enabled: id !== null });

export const useContatos = (id: number | null) =>
  useQuery({ queryKey: ["lead", id, "contatos"], queryFn: ({ signal }) => get<Pagina<ContatoItem>>(`/leads/${id}/contatos`, { page_size: 20 }, signal), enabled: id !== null });

export const useFunilHistorico = (id: number | null) =>
  useQuery({ queryKey: ["lead", id, "funil"], queryFn: ({ signal }) => get<Pagina<FunilItem>>(`/leads/${id}/funil`, { page_size: 50 }, signal), enabled: id !== null });

export const useWhatsappLink = (id: number | null) =>
  useQuery({ queryKey: ["lead", id, "whatsapp"], queryFn: ({ signal }) => get<WhatsAppLink>(`/leads/${id}/whatsapp-link`, {}, signal), enabled: id !== null, staleTime: 60_000 });

export function useKanbanResumo(params: Params) {
  const refetchInterval = useIntervalo();
  return useQuery({
    queryKey: ["kanban", "resumo", params],
    queryFn: ({ signal }) => get<KanbanResumo>("/kanban/resumo", params, signal),
    placeholderData: keepPreviousData,
    refetchInterval,
  });
}

export function useKanbanColuna(coluna: Coluna, params: Params) {
  const refetchInterval = useIntervalo();
  return useInfiniteQuery({
    queryKey: ["kanban", "coluna", coluna, params],
    queryFn: ({ pageParam, signal }) =>
      get<Pagina<LeadResumo>>(`/kanban/colunas/${coluna}/leads`, { ...params, page: pageParam, page_size: KANBAN_PAGE_SIZE }, signal),
    initialPageParam: 1,
    getNextPageParam: (ult) => (ult.page * ult.page_size < ult.total ? ult.page + 1 : undefined),
    refetchInterval,
  });
}

export const useMetricasResumo = (params: Params) =>
  useQuery({ queryKey: ["metricas", "resumo", params], queryFn: ({ signal }) => get<MetricasResumo>("/metricas/resumo", params, signal), placeholderData: keepPreviousData, refetchInterval: useIntervalo() });

export const useMetricasFunil = (params: Params) =>
  useQuery({ queryKey: ["metricas", "funil", params], queryFn: ({ signal }) => get<MetricasFunil>("/metricas/funil", params, signal), placeholderData: keepPreviousData, refetchInterval: useIntervalo() });

export const useConversao = (nivel: "nicho" | "cidade", params: Params) =>
  useQuery({ queryKey: ["metricas", "conversao", nivel, params], queryFn: ({ signal }) => get<Conversao>("/metricas/conversao", { ...params, nivel, limite: nivel === "cidade" ? 100 : undefined }, signal), placeholderData: keepPreviousData, refetchInterval: useIntervalo() });

/** Pontos do mapa dentro da área visível. Nunca dispara geocodificação: só lê coordenadas já gravadas. */
export function useMapaLeads(params: Params, bbox: Bbox | null) {
  const refetchInterval = useIntervalo();
  return useQuery({
    queryKey: ["mapa", params, bbox],
    queryFn: ({ signal }) => get<RespostaMapa>("/mapa/leads", { ...params, ...(bbox ?? {}) }, signal),
    placeholderData: keepPreviousData,
    refetchInterval,
  });
}

export interface TransicaoVars {
  lead: Pick<LeadResumo, "id" | "funil_id" | "coluna" | "nome">;
  estagioDestino: string;
  colunaDestino: Coluna;
  observacao?: string;
}

type Infinito = { pages: Pagina<LeadResumo>[]; pageParams: unknown[] };

const semCard = (d: Infinito, id: number): Infinito => ({
  ...d,
  pages: d.pages.map((p) => ({ ...p, itens: p.itens.filter((i) => i.id !== id), total: Math.max(0, p.total - 1) })),
});

const comCardNoTopo = (d: Infinito, card: LeadResumo | undefined): Infinito => ({
  ...d,
  pages: d.pages.map((p, idx) => ({
    ...p,
    itens: idx === 0 && card ? [card, ...p.itens] : p.itens,
    total: p.total + 1,
  })),
});

/**
 * Muda o estágio. Atualização otimista nos cards do Kanban; se a API recusar
 * (409 de concorrência, erro de rede, etc.) o snapshot é restaurado e tudo é
 * recarregado do servidor.
 */
export function useTransicao(opcoes?: { onErro?: (mensagem: string, conflito: boolean) => void; onSucesso?: () => void }) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: TransicaoVars) =>
      post<TransicaoResposta>(`/leads/${v.lead.id}/transicoes`, {
        estagio_destino: v.estagioDestino,
        id_historico_esperado: v.lead.funil_id, // null quando o lead não tinha histórico
        observacao: v.observacao ?? null,
      }),
    onMutate: async (v) => {
      await qc.cancelQueries({ queryKey: ["kanban"] });
      const snapshot = qc.getQueriesData({ queryKey: ["kanban"] });
      if (v.lead.coluna !== v.colunaDestino) {
        const original = snapshot
          .filter(([k]) => k[1] === "coluna" && k[2] === v.lead.coluna)
          .flatMap(([, d]) => (d ? (d as Infinito).pages.flatMap((p) => p.itens) : []))
          .find((i) => i.id === v.lead.id);
        const atualizado = original
          ? { ...original, coluna: v.colunaDestino, estagio: v.estagioDestino, estagio_derivado: false }
          : undefined;

        for (const [chave, dados] of snapshot) {
          if (!dados) continue;
          if (chave[1] === "coluna" && chave[2] === v.lead.coluna) qc.setQueryData(chave, semCard(dados as Infinito, v.lead.id));
          else if (chave[1] === "coluna" && chave[2] === v.colunaDestino) qc.setQueryData(chave, comCardNoTopo(dados as Infinito, atualizado));
          else if (chave[1] === "resumo") {
            const r = dados as KanbanResumo;
            qc.setQueryData(chave, {
              ...r,
              colunas: r.colunas.map((c) =>
                c.codigo === v.lead.coluna ? { ...c, total: c.total - 1 } : c.codigo === v.colunaDestino ? { ...c, total: c.total + 1 } : c,
              ),
            });
          }
        }
      }
      return { snapshot };
    },
    onError: (err: Error & { status?: number }, _v, ctx) => {
      ctx?.snapshot.forEach(([chave, dados]) => qc.setQueryData(chave, dados)); // desfaz o otimista
      opcoes?.onErro?.(err.message, err.status === 409);
    },
    onSuccess: () => opcoes?.onSucesso?.(),
    onSettled: (_d, _e, v) => {
      // Recarrega tudo o que depende do estágio, mesmo em erro (reflete o estado real do servidor).
      for (const raiz of ["leads", "kanban", "metricas", "mapa"]) qc.invalidateQueries({ queryKey: [raiz] });
      qc.invalidateQueries({ queryKey: ["lead", v.lead.id] });
    },
  });
}
