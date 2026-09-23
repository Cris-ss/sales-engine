export function formatarCnpj(v: string | null): string {
  const d = (v ?? "").replace(/\D/g, "");
  return d.length === 14 ? `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5, 8)}/${d.slice(8, 12)}-${d.slice(12)}` : v ?? "";
}

export function formatarTelefone(v: string | null): string {
  const d = (v ?? "").replace(/\D/g, "");
  if (d.length === 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
  if (d.length === 11) return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
  return v ?? "";
}

export function formatarCep(v: string | null): string {
  const d = (v ?? "").replace(/\D/g, "");
  return d.length === 8 ? `${d.slice(0, 5)}-${d.slice(5)}` : v ?? "";
}

export function formatarDataHora(v: string | null): string {
  if (!v) return "—";
  return new Date(v).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

/** "CIDADE EXEMPLO" -> "Cidade Exemplo" (a Receita entrega tudo em maiúsculas). */
export function titulo(v: string | null): string {
  if (!v) return "";
  const conectivos = new Set(["de", "da", "do", "das", "dos", "e"]);
  return v
    .toLowerCase()
    .split(" ")
    .map((p, i) => (i > 0 && conectivos.has(p) ? p : p.charAt(0).toUpperCase() + p.slice(1)))
    .join(" ");
}

export function localidade(municipio: string | null, uf: string | null): string {
  if (!municipio && !uf) return "—";
  return `${titulo(municipio) || "?"}${uf ? ` / ${uf}` : ""}`;
}

export function pct(v: number | null): string {
  return v === null ? "N/A" : `${v.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}%`;
}
