import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "./client";

export interface Processo {
  nome: string; rotulo: string; registrado: boolean;
  estado: "rodando" | "parado" | "parando" | "erro" | "iniciando" | "nao_iniciado" | string;
  status_pm2: string | null; pid: number | null; uptime_seg: number | null; reinicios: number | null; memoria_mb: number | null; cpu_pct: number | null;
}
export interface Processos { pm2_disponivel: boolean; erro: string | null; processos: Processo[] }
export interface LogsProcesso { saida: string[]; erros: string[]; arquivos: { saida: string; erros: string } }
export interface ResultadoAcao { ok: boolean; saida?: string; reiniciando?: boolean; mensagem?: string; processo?: string }

/** Atualiza sozinho; se a API estiver reiniciando a consulta falha e mantém o último valor (sem mostrar erro). */
export const useProcessos = () =>
  useQuery({
    queryKey: ["sistema", "processos"], queryFn: ({ signal }) => get<Processos>("/sistema/processos", {}, signal),
    refetchInterval: 4000, retry: false, placeholderData: keepPreviousData,
  });

export const useLogsProcesso = (nome: string, linhas: number, automatico: boolean) =>
  useQuery({
    queryKey: ["sistema", "logs", nome, linhas], queryFn: ({ signal }) => get<LogsProcesso>(`/sistema/processos/${nome}/logs`, { linhas }, signal),
    refetchInterval: automatico ? 3000 : false, retry: false, placeholderData: keepPreviousData,
  });

export function useAcaoProcesso() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { nome: string; verbo: "reiniciar" | "parar" | "iniciar" }) => post<ResultadoAcao>(`/sistema/processos/${v.nome}/${v.verbo}`, {}),
    onSettled: () => qc.invalidateQueries({ queryKey: ["sistema"] }),
  });
}

export function useAcaoTudo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (verbo: "parar" | "iniciar") => post<{ resultados: Record<string, ResultadoAcao> }>(`/sistema/tudo/${verbo}`, {}),
    onSettled: () => qc.invalidateQueries({ queryKey: ["sistema"] }),
  });
}

export async function apiRespondendo(): Promise<boolean> {
  try {
    const r = await fetch("/api/v1/health", { cache: "no-store" });
    return r.ok;
  } catch {
    return false;
  }
}
