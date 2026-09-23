import { useEffect, useRef, useState } from "react";
import { useNichos, useOpcoes } from "../api/hooks";
import { CHAVES_FILTRO, temFiltroAtivo, useFiltros, type Filtros } from "../lib/filtros";
import { titulo } from "../lib/format";

function useDebounced<T>(valor: T, ms: number): T {
  const [v, setV] = useState(valor);
  useEffect(() => {
    const t = setTimeout(() => setV(valor), ms);
    return () => clearTimeout(t);
  }, [valor, ms]);
  return v;
}

function SearchInput() {
  const { filtros, setFiltros } = useFiltros();
  const [texto, setTexto] = useState(filtros.q ?? "");
  const debounced = useDebounced(texto, 300);
  const enviado = useRef(filtros.q ?? ""); // último valor que ESTE campo colocou na URL

  // URL -> campo, só quando a mudança veio de fora (limpar filtros, botão voltar, chip removido).
  useEffect(() => {
    const naUrl = filtros.q ?? "";
    if (naUrl !== enviado.current) {
      enviado.current = naUrl;
      setTexto(naUrl);
    }
  }, [filtros.q]);

  // campo -> URL, com debounce (evita uma consulta por tecla).
  useEffect(() => {
    const novo = debounced.trim();
    if (novo !== enviado.current) {
      enviado.current = novo;
      setFiltros({ q: novo });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced]);

  return (
    <label className="campo campo-busca">
      <span>Buscar</span>
      <input
        type="search"
        placeholder="Nome, CNPJ ou telefone"
        value={texto}
        onChange={(e) => setTexto(e.target.value)}
        aria-label="Buscar por nome, CNPJ ou telefone"
      />
    </label>
  );
}

interface Props {
  /** Mostra filtros que só fazem sentido na lista (coluna, estágio, status de email). */
  extras?: boolean;
}

export function GlobalFilterBar({ extras = false }: Props) {
  const { filtros, setFiltros, limparFiltros } = useFiltros();
  const { data: nichos } = useNichos();
  const { data: opcoes } = useOpcoes(filtros.uf);
  const { data: todasOpcoes } = useOpcoes();

  const sel = (k: keyof Filtros, label: string, itens: { v: string; l: string }[], vazio = "Todos") => (
    <label className="campo">
      <span>{label}</span>
      <select
        value={filtros[k] ?? ""}
        // trocar a UF invalida o município escolhido (pertencia à UF anterior)
        onChange={(e) => setFiltros(k === "uf" ? { uf: e.target.value, municipio: "" } : { [k]: e.target.value })}
      >
        <option value="">{vazio}</option>
        {itens.map((i) => (
          <option key={i.v} value={i.v}>{i.l}</option>
        ))}
      </select>
    </label>
  );

  return (
    <section className="filtros" aria-label="Filtros">
      <SearchInput />
      {sel("nicho_id", "Nicho", (nichos ?? []).map((n) => ({ v: String(n.id), l: `${n.nome} (${n.total})` })))}
      {sel("uf", "UF", (todasOpcoes?.ufs ?? []).map((u) => ({ v: u.codigo, l: `${u.codigo} (${u.total})` })))}
      <label className="campo">
        <span>Município</span>
        <select
          value={filtros.municipio ?? ""}
          disabled={!filtros.uf}
          title={!filtros.uf ? "Escolha uma UF primeiro" : undefined}
          onChange={(e) => setFiltros({ municipio: e.target.value })}
        >
          <option value="">{filtros.uf ? "Todos" : "Escolha a UF"}</option>
          {(opcoes?.municipios ?? []).map((m) => (
            <option key={`${m.municipio}|${m.uf}`} value={m.municipio}>{titulo(m.municipio)} ({m.total})</option>
          ))}
        </select>
      </label>

      {sel("faixa", "Faixa do score", (todasOpcoes?.faixas ?? []).map((f) => ({ v: f.codigo, l: f.rotulo })))}
      <label className="campo campo-num">
        <span>Score mín.</span>
        <input type="number" min={0} max={100} value={filtros.score_min ?? ""} onChange={(e) => setFiltros({ score_min: e.target.value })} />
      </label>
      <label className="campo campo-num">
        <span>Score máx.</span>
        <input type="number" min={0} max={100} value={filtros.score_max ?? ""} onChange={(e) => setFiltros({ score_max: e.target.value })} />
      </label>

      {sel("canal", "Canal", (todasOpcoes?.canais ?? []).map((c) => ({ v: c.codigo, l: c.rotulo })))}
      {sel("site_ddg", "Status do site", (todasOpcoes?.site_ddg ?? []).map((s) => ({ v: s.codigo, l: s.rotulo })))}
      <label className="campo">
        <span>Início da atividade, de</span>
        <input type="date" value={filtros.data_inicio_de ?? ""} onChange={(e) => setFiltros({ data_inicio_de: e.target.value })} />
      </label>
      <label className="campo">
        <span>Início da atividade, até</span>
        <input type="date" value={filtros.data_inicio_ate ?? ""} onChange={(e) => setFiltros({ data_inicio_ate: e.target.value })} />
      </label>

      {extras && (
        <>
          {sel("coluna", "Coluna do funil", (todasOpcoes?.colunas ?? []).map((c) => ({ v: c.codigo, l: c.rotulo })))}
          {sel("estagio", "Estágio", (todasOpcoes?.estagios ?? []).map((e) => ({ v: e.codigo, l: e.rotulo })))}
          {sel("email_status", "Status do email", (todasOpcoes?.email_status ?? []).map((e) => ({ v: e.codigo, l: e.rotulo })))}
        </>
      )}

      <button className="btn" onClick={limparFiltros} disabled={!temFiltroAtivo(filtros)}>
        Limpar filtros
      </button>
    </section>
  );
}

/** Chips dos filtros ativos, cada um removível. */
export function ActiveFilterChips({ ocultar = [] as string[] }: { ocultar?: string[] }) {
  const { filtros, setFiltros } = useFiltros();
  const { data: nichos } = useNichos();
  const { data: opcoes } = useOpcoes();

  const rotulo = (k: string, v: string): string => {
    if (k === "nicho_id") return `Nicho: ${nichos?.find((n) => String(n.id) === v)?.nome ?? v}`;
    if (k === "faixa") return `Score: ${opcoes?.faixas.find((f) => f.codigo === v)?.rotulo ?? v}`;
    if (k === "canal") return `Canal: ${opcoes?.canais.find((c) => c.codigo === v)?.rotulo ?? v}`;
    if (k === "coluna") return `Coluna: ${opcoes?.colunas.find((c) => c.codigo === v)?.rotulo ?? v}`;
    if (k === "estagio") return `Estágio: ${opcoes?.estagios.find((e) => e.codigo === v)?.rotulo ?? v}`;
    if (k === "email_status") return `Email: ${opcoes?.email_status.find((e) => e.codigo === v)?.rotulo ?? v}`;
    if (k === "site_ddg") return `Site: ${opcoes?.site_ddg.find((s) => s.codigo === v)?.rotulo ?? v}`;
    if (k === "data_inicio_de") return `Atividade desde: ${v}`;
    if (k === "data_inicio_ate") return `Atividade até: ${v}`;
    if (k === "municipio") return `Município: ${titulo(v)}`;
    if (k === "score_min") return `Score ≥ ${v}`;
    if (k === "score_max") return `Score ≤ ${v}`;
    if (k === "q") return `Busca: “${v}”`;
    return `${k.toUpperCase()}: ${v}`;
  };

  const ativos = CHAVES_FILTRO.filter((k) => k !== "sort" && k !== "order" && filtros[k] && !ocultar.includes(k));
  if (!ativos.length) return null;
  return (
    <ul className="chips" aria-label="Filtros ativos">
      {ativos.map((k) => (
        <li key={k} className="chip">
          {rotulo(k, filtros[k]!)}
          <button aria-label={`Remover filtro ${rotulo(k, filtros[k]!)}`} onClick={() => setFiltros({ [k]: "" })}>×</button>
        </li>
      ))}
    </ul>
  );
}
