import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post, put } from "./client";

export interface WaStatus {
  id: number; numero: string | null; estado: string; gateway_ativo: boolean; qr_disponivel: boolean;
  automacao_habilitada: boolean; motivo_pausa: string | null; vendas_ativas: boolean; politica_versao: number;
  limites: Record<string, unknown>;
  modo_envio: "manual" | "automatico"; primeiros_contatos_hoje: number; sugestoes_pendentes: number; aceites_pendentes: number;
  notificacoes_operador: { pendentes: number; falhas: number };
  fila: { jobs_pendentes: number; outbox_pendente: number; eventos_nao_processados: number };
}
export interface WaAutorizacao { id: number; telefone: string; status: string; expira_em: string | null; criado_em: string; autorizado_por: string }
export interface WaBloqueio { codigo: string; texto: string; nivel: "alerta" | "info" }
export interface WaLeadTelefone {
  bloqueios: WaBloqueio[];
  origem: string | null;
  telefone: string; original: string | null; autorizacao: WaAutorizacao | null; suprimido: boolean; conversa_id: number | null; controle: string | null;
}
export interface WaLead { empresa_id: number; nome: string; contexto_manual: string | null; pode_adicionar_telefone: boolean; telefones: WaLeadTelefone[]; conta: { estado: string; automacao_habilitada: boolean; modo_envio: "manual" | "automatico" } }
export interface WaConversaResumo {
  sugestao_pendente: boolean;
  aceite_pendente: boolean;
  bloqueios: WaBloqueio[];
  id: number; controle: string; estagio: string; motivo_escalada: string | null; ultima_mensagem: string | null; ultima_autoria: string | null;
  ultima_recebida_em: string | null; contato_nome: string | null; telefone: string | null; empresa_id: number | null; empresa_nome: string | null;
}
export interface WaConversas { itens: WaConversaResumo[]; resumo: Record<string, number> }
export interface WaMensagem { id: number; direcao: string; autoria: string; tipo: string; texto: string | null; estado: string; origem: string; em: string | null }
export interface WaConversa extends WaConversaResumo {
  resumo: string | null; estado_comercial: Record<string, unknown>; autorizacao: WaAutorizacao | null; suprimido: boolean; mensagens: WaMensagem[];
  proposta: { id: number; pacote: string; itens: { nome: string; centavos: number }[]; setup_centavos: number; mensalidade_centavos: number; status: string } | null;
  demandas: { id: number; descricao: string; revisada: boolean }[];
  aceites: { id: number; criado_em: string; tratado_em: string | null }[];
  sugestoes: { id: number; texto: string; primeiro_contato: boolean; acao: string | null; criada_em: string }[];
}
export interface WaPolitica { ativa: { versao: number; config: any; criado_por: string; criado_em: string }; historico: { versao: number; ativa: boolean; criado_por: string; criado_em: string }[] }
export interface WaDemanda { id: number; conversa_id: number; descricao: string; revisada: boolean; criado_em: string }

const REFRESH = 3000;

export const useWaStatus = () => useQuery({ queryKey: ["wa", "status"], queryFn: () => get<WaStatus>("/whatsapp/status"), refetchInterval: REFRESH });
export const useWaQr = (ligado: boolean) =>
  useQuery({ queryKey: ["wa", "qr"], queryFn: () => get<{ qr: string }>("/whatsapp/qr"), enabled: ligado, refetchInterval: 2000, retry: false });
export const useWaLead = (id: number) => useQuery({ queryKey: ["wa", "lead", id], queryFn: () => get<WaLead>(`/whatsapp/leads/${id}`), refetchInterval: 5000 });
export const useWaConversas = (controle: string | null, problemas: boolean, sugestoes = false, aceites = false) =>
  useQuery({
    queryKey: ["wa", "conversas", controle, problemas, sugestoes, aceites],
    queryFn: () => get<WaConversas>("/whatsapp/conversas", { controle, problemas: problemas || undefined, sugestoes: sugestoes || undefined, aceites: aceites || undefined }),
    refetchInterval: REFRESH,
  });
export const useWaConversa = (id: number | null) =>
  useQuery({ queryKey: ["wa", "conversa", id], queryFn: () => get<WaConversa>(`/whatsapp/conversas/${id}`), enabled: id !== null, refetchInterval: REFRESH });
export const useWaPolitica = () => useQuery({ queryKey: ["wa", "politica"], queryFn: () => get<WaPolitica>("/whatsapp/politica") });
export const useWaDemandas = () => useQuery({ queryKey: ["wa", "demandas"], queryFn: () => get<WaDemanda[]>("/whatsapp/demandas") });

function useAcao<V, R = unknown>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSettled: () => qc.invalidateQueries({ queryKey: ["wa"] }) });
}

export const useWaConectar = () => useAcao(() => post("/whatsapp/conectar", { confirmar: true }));
export const useWaDesconectar = () => useAcao(() => post("/whatsapp/desconectar", {}));
export const useWaKillSwitch = () => useAcao((v: { pausar: boolean; motivo?: string }) => post("/whatsapp/kill-switch", v));
export const useWaAutorizar = () => useAcao((v: { empresaId: number; telefone: string }) => post(`/whatsapp/leads/${v.empresaId}/autorizar`, { telefone: v.telefone, confirmar: true }));
export const useWaAutorizarNovo = () => useAcao((v: { telefone: string; nome: string; nicho_id: number; contexto?: string }) => post<{ empresa_id: number; empresa_criada: boolean; conversa_id: number }>("/whatsapp/autorizar-novo", { ...v, confirmar: true }));
export function useWaTelefoneManual() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { empresaId: number; telefone: string }) => put<{ empresa_id: number; alterado: boolean }>(`/whatsapp/leads/${v.empresaId}/telefone`, { telefone: v.telefone }),
    onSettled: () => { for (const raiz of ["wa", "lead", "leads", "kanban"]) qc.invalidateQueries({ queryKey: [raiz] }); },
  });
}
export function useWaRemoverTelefone() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { empresaId: number; telefone: string }) =>
      post<{ empresa_id: number; removido: boolean; autorizacao_revogada: boolean }>(`/whatsapp/leads/${v.empresaId}/telefone/remover`, { telefone: v.telefone }),
    onSettled: () => { for (const raiz of ["wa", "lead", "leads", "kanban"]) qc.invalidateQueries({ queryKey: [raiz] }); },
  });
}
export function useWaContexto() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { empresaId: number; contexto: string }) => put<{ empresa_id: number; contexto_manual: string | null }>(`/whatsapp/leads/${v.empresaId}/contexto`, { contexto: v.contexto }),
    onSettled: () => { for (const raiz of ["wa", "lead", "leads"]) qc.invalidateQueries({ queryKey: [raiz] }); },
  });
}
export const useWaRevogar = () => useAcao((id: number) => post(`/whatsapp/autorizacoes/${id}/revogar`, {}));
export const useWaControle = () => useAcao((v: { id: number; acao: "assumir" | "pausar" | "retomar-ia" }) => post<{ id: number; controle: string; tarefa_recriada?: string | null }>(`/whatsapp/conversas/${v.id}/${v.acao}`, {}));
export const useWaEnviar = () => useAcao((v: { id: number; texto: string }) => post(`/whatsapp/conversas/${v.id}/mensagens`, { texto: v.texto }));
export const useWaPublicarPolitica = () => useAcao((v: { config: unknown; confirmar: boolean; confirmarEnvioAutomatico?: boolean }) => put("/whatsapp/politica", { config: v.config, confirmar_ativacao_vendas: v.confirmar, confirmar_envio_automatico: Boolean(v.confirmarEnvioAutomatico) }));
export const useWaConfirmarEnvio = () => useAcao((v: { id: number; texto?: string }) => post(`/whatsapp/mensagens/${v.id}/enviada`, { texto: v.texto ?? null }));
export const useWaAceiteTratado = () => useAcao((id: number) => post(`/whatsapp/aceites/${id}/tratado`, {}));
export const useWaDescartarSugestao = () => useAcao((id: number) => post(`/whatsapp/mensagens/${id}/descartar`, {}));
export const useWaRegistrarEnvio = () => useAcao((v: { id: number; texto: string }) => post(`/whatsapp/conversas/${v.id}/registrar-envio`, { texto: v.texto }));
export const useWaDemandaRevisada = () => useAcao((id: number) => post(`/whatsapp/demandas/${id}/revisada`, {}));
