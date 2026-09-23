import { useEffect, useState } from "react";
import { useCidades, useCriarLoteProspeccao, useLotesProspeccao, useNichos } from "../../api/hooks";
import { ErroBox } from "../../components/states";

const UFS = [
  ["AC", "Acre"], ["AL", "Alagoas"], ["AP", "Amapá"], ["AM", "Amazonas"], ["BA", "Bahia"],
  ["CE", "Ceará"], ["DF", "Distrito Federal"], ["ES", "Espírito Santo"], ["GO", "Goiás"],
  ["MA", "Maranhão"], ["MT", "Mato Grosso"], ["MS", "Mato Grosso do Sul"], ["MG", "Minas Gerais"],
  ["PA", "Pará"], ["PB", "Paraíba"], ["PR", "Paraná"], ["PE", "Pernambuco"], ["PI", "Piauí"],
  ["RJ", "Rio de Janeiro"], ["RN", "Rio Grande do Norte"], ["RS", "Rio Grande do Sul"],
  ["RO", "Rondônia"], ["RR", "Roraima"], ["SC", "Santa Catarina"], ["SP", "São Paulo"],
  ["SE", "Sergipe"], ["TO", "Tocantins"],
] as const;

export function ProspeccaoPage() {
  const { data: nichos } = useNichos();
  const lotes = useLotesProspeccao();
  const criar = useCriarLoteProspeccao();
  const [nichoId, setNichoId] = useState("");
  const [fonte, setFonte] = useState<"osm" | "apify">("osm");
  const [uf, setUf] = useState("");
  const [cidade, setCidade] = useState("");
  const [termoCidade, setTermoCidade] = useState("");
  const [raio, setRaio] = useState("10");
  const [limite, setLimite] = useState("50");
  const [confirmar, setConfirmar] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setTermoCidade(cidade.trim()), 150);
    return () => clearTimeout(timer);
  }, [cidade]);
  const cidades = useCidades(termoCidade);

  const mudarCidade = (valor: string) => {
    const escolhida = cidades.data?.find((item) => item.rotulo === valor);
    if (escolhida) {
      setCidade(escolhida.nome);
      setUf(escolhida.uf);
    } else {
      setCidade(valor);
    }
  };

  return <section>
    <h2>Procurar novos leads</h2>
    <p className="aviso">OpenStreetMap é gratuito; Apify continua disponível; ambos seguem para descoberta de site via DuckDuckGo. Nenhum lead legado é alterado.</p>
    <form className="filtros" onSubmit={(e) => { e.preventDefault(); criar.mutate({ nicho_id: Number(nichoId), uf, fonte, cidade: fonte !== "apify" ? cidade : undefined, raio_km: fonte === "osm" ? Number(raio) : undefined, limite: Number(limite), confirmar }); }}>
      <label className="campo"><span>Nicho</span><select required value={nichoId} onChange={(e) => setNichoId(e.target.value)}><option value="">Selecione</option>{(nichos ?? []).map((n) => <option key={n.id} value={n.id}>{n.nome}</option>)}</select></label>
      <label className="campo"><span>Fonte</span><select value={fonte} onChange={(e) => setFonte(e.target.value as "osm" | "apify")}><option value="osm">OpenStreetMap + DuckDuckGo</option><option value="apify">Apify + DuckDuckGo</option></select></label>
      <label className="campo"><span>UF</span><input required list="ufs-brasil" minLength={2} maxLength={2} value={uf} onChange={(e) => setUf(e.target.value.toUpperCase())} placeholder="Digite a sigla" autoComplete="off" /><datalist id="ufs-brasil">{UFS.map(([sigla, nome]) => <option key={sigla} value={sigla}>{nome}</option>)}</datalist></label>
      {fonte !== "apify" && <label className="campo"><span>Cidade</span><input required list="cidades-osm" value={cidade} onChange={(e) => mudarCidade(e.target.value)} placeholder="Digite para ver opções" autoComplete="off" />{cidades.isFetching && <small>Buscando cidades…</small>}<datalist id="cidades-osm">{(cidades.data ?? []).map((item) => <option key={`${item.nome}-${item.uf}`} value={item.rotulo} />)}</datalist></label>}
      {fonte === "osm" && <label className="campo"><span>Raio (km)</span><input required type="number" min="1" max="50" value={raio} onChange={(e) => setRaio(e.target.value)} /></label>}
      <label className="campo"><span>Limite</span><input required type="number" min="1" max={500} value={limite} onChange={(e) => setLimite(e.target.value)} /></label>
      <label className="auto"><input type="checkbox" checked={confirmar} onChange={(e) => setConfirmar(e.target.checked)} /> Confirmo as consultas deste lote.</label>
      <button className="btn btn-primario" disabled={!confirmar || criar.isPending}>{criar.isPending ? "Iniciando…" : "Buscar leads"}</button>
    </form>
    {criar.error && <ErroBox erro={criar.error} />}
    <p className="muted">A busca inicia automaticamente. Esta tabela atualiza a cada 2 segundos enquanto houver processamento.</p>
    <h2>Lotes recentes</h2>
    {lotes.error && <ErroBox erro={lotes.error} />}
    <div className="tabela-wrap"><table className="tabela"><thead><tr><th>ID</th><th>Nicho</th><th>Fonte</th><th>Área</th><th>Limite</th><th>Encontrados</th><th>Novos</th><th>Duplicados</th><th>Sites verificados</th><th>Status</th><th>Erro</th></tr></thead><tbody>{(lotes.data ?? []).map((l) => <tr key={l.id}><td>{l.id}</td><td>{nichos?.find((n) => n.id === l.nicho_id)?.nome ?? l.nicho_id}</td><td>{l.fonte}</td><td>{l.cidade ? `${l.cidade}/${l.uf}${l.raio_km ? ` · ${l.raio_km} km` : ""}` : l.uf}</td><td>{l.limite}</td><td>{l.total_encontrado}</td><td>{l.empresas_novas}</td><td>{l.total_duplicado}</td><td>{l.validacoes_concluidas}/{l.empresas_novas}</td><td>{l.status}</td><td>{l.erro ?? "—"}</td></tr>)}</tbody></table></div>
  </section>;
}
