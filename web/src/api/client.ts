export class ApiErro extends Error {
  status: number;
  codigo: string;
  detalhes: unknown;
  constructor(status: number, codigo: string, mensagem: string, detalhes?: unknown) {
    super(mensagem);
    this.status = status;
    this.codigo = codigo;
    this.detalhes = detalhes;
  }
}

const BASE = "/api/v1";

export type Params = Record<string, string | number | boolean | null | undefined>;

export function qs(params: Params): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === "") continue;
    u.set(k, String(v));
  }
  const s = u.toString();
  return s ? `?${s}` : "";
}

async function tratar(resp: Response): Promise<never> {
  let corpo: any = null;
  try {
    corpo = await resp.json();
  } catch {
    /* corpo não-JSON */
  }
  const e = corpo?.erro;
  throw new ApiErro(resp.status, e?.codigo ?? "http_error", e?.mensagem ?? `Erro HTTP ${resp.status}`, e?.detalhes);
}

export async function get<T>(caminho: string, params: Params = {}, signal?: AbortSignal): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${BASE}${caminho}${qs(params)}`, { signal });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiErro(0, "rede", "Não foi possível falar com a API. Ela está rodando?");
  }
  if (!resp.ok) return tratar(resp);
  return resp.json() as Promise<T>;
}

export async function post<T>(caminho: string, corpo: unknown): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${BASE}${caminho}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(corpo),
    });
  } catch {
    throw new ApiErro(0, "rede", "Não foi possível falar com a API. Ela está rodando?");
  }
  if (!resp.ok) return tratar(resp);
  return resp.json() as Promise<T>;
}

export async function put<T>(caminho: string, corpo: unknown): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${BASE}${caminho}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo) });
  } catch {
    throw new ApiErro(0, "rede", "Não foi possível falar com a API. Ela está rodando?");
  }
  if (!resp.ok) return tratar(resp);
  return resp.json() as Promise<T>;
}

export function urlExportacao(formato: "csv" | "xlsx", params: Params): string {
  return `${BASE}/exportacoes/leads${qs({ ...params, formato })}`;
}
