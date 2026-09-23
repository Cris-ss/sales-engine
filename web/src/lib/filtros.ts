import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import type { Params } from "../api/client";

/** Filtros compartilhados por todas as telas. Vivem na URL: sobrevivem ao reload e à troca de tela. */
export const CHAVES_FILTRO = [
  "q", "nicho_id", "uf", "municipio", "score_min", "score_max", "faixa",
  "canal", "coluna", "estagio", "email_status", "sort", "order",
  "site_ddg", "data_inicio_de", "data_inicio_ate",
] as const;
export type ChaveFiltro = (typeof CHAVES_FILTRO)[number];
export type Filtros = Partial<Record<ChaveFiltro, string>>;

const CHAVES_LOCAIS = ["page", "lead", "vista"]; // não são filtros da API

export function useFiltros() {
  const [sp, setSp] = useSearchParams();

  const filtros = useMemo(() => {
    const f: Filtros = {};
    for (const k of CHAVES_FILTRO) {
      const v = sp.get(k);
      if (v) f[k] = v;
    }
    return f;
  }, [sp]);

  const page = Math.max(1, Number(sp.get("page")) || 1);
  const leadAberto = sp.get("lead") ? Number(sp.get("lead")) : null;
  const vista = (sp.get("vista") as "tabela" | "cards" | null) ?? "tabela";

  /** Muda filtros; qualquer mudança de filtro volta para a página 1. */
  const setFiltros = useCallback(
    (patch: Filtros) => {
      setSp(
        (prev) => {
          const n = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(patch)) {
            if (v === undefined || v === "") n.delete(k);
            else n.set(k, v);
          }
          n.delete("page");
          return n;
        },
        { replace: true },
      );
    },
    [setSp],
  );

  const limparFiltros = useCallback(() => {
    setSp(
      (prev) => {
        const n = new URLSearchParams();
        for (const k of CHAVES_LOCAIS) {
          const v = prev.get(k);
          if (v && k !== "page") n.set(k, v);
        }
        return n;
      },
      { replace: true },
    );
  }, [setSp]);

  const setLocal = useCallback(
    (chave: "page" | "lead" | "vista", valor: string | number | null) => {
      setSp(
        (prev) => {
          const n = new URLSearchParams(prev);
          if (valor === null || valor === "") n.delete(chave);
          else n.set(chave, String(valor));
          return n;
        },
        { replace: chave === "vista" }, // page e lead entram no histórico (voltar fecha o painel / volta a página)
      );
    },
    [setSp],
  );

  return { filtros, page, leadAberto, vista, setFiltros, limparFiltros, setLocal, searchString: sp.toString() };
}

/** Parâmetros de API a partir dos filtros. `sem` remove chaves que a tela não usa (ex.: kanban ignora coluna/estágio). */
export function paramsApi(f: Filtros, sem: ChaveFiltro[] = []): Params {
  const p: Params = {};
  for (const k of CHAVES_FILTRO) {
    if (sem.includes(k)) continue;
    const v = f[k];
    if (v) p[k] = v;
  }
  return p;
}

export function temFiltroAtivo(f: Filtros): boolean {
  return CHAVES_FILTRO.some((k) => k !== "sort" && k !== "order" && !!f[k]);
}

/** Query string só com os filtros (sem page/lead): usada nos links de navegação entre telas. */
export function buscaSoFiltros(search: string): string {
  const src = new URLSearchParams(search);
  const n = new URLSearchParams();
  for (const k of CHAVES_FILTRO) {
    const v = src.get(k);
    if (v) n.set(k, v);
  }
  const s = n.toString();
  return s ? `?${s}` : "";
}
