import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useConversao, useMetricasFunil, useMetricasResumo } from "../../api/hooks";
import type { Conversao, ConversaoItem } from "../../api/types";
import { ActiveFilterChips, GlobalFilterBar } from "../../components/GlobalFilterBar";
import { MetricDefinitionTooltip } from "../../components/MetricDefinitionTooltip";
import { Carregando, ErroBox } from "../../components/states";
import { paramsApi, useFiltros } from "../../lib/filtros";
import { pct } from "../../lib/format";

function Kpi({ rotulo, valor, definicao }: { rotulo: string; valor: number | undefined; definicao: string }) {
  return (
    <div className="kpi">
      <div className="kpi-valor">{valor === undefined ? "…" : valor.toLocaleString("pt-BR")}</div>
      <div className="kpi-rotulo">
        {rotulo} <MetricDefinitionTooltip texto={definicao} />
      </div>
    </div>
  );
}

function TabelaConversao({ dados, titulo }: { dados: Conversao | undefined; titulo: string }) {
  if (!dados) return <Carregando />;
  return (
    <>
      <p className="muted">{dados.definicao}</p>
      <div className="tabela-wrap">
        <table className="tabela">
          <caption className="sr-only">{titulo}</caption>
          <thead>
            <tr><th>Grupo</th><th>Empresas (denominador)</th><th>Ganhos (numerador)</th><th>Conversão</th></tr>
          </thead>
          <tbody>
            {dados.itens.map((i: ConversaoItem) => (
              <tr key={i.chave} className={i.sem_dado ? "linha-sem-dado" : ""}>
                <td>{i.rotulo}{i.sem_dado && <span className="muted"> — município não informado</span>}</td>
                <td>{i.empresas.toLocaleString("pt-BR")}</td>
                <td>{i.ganhos.toLocaleString("pt-BR")}</td>
                <td>{i.taxa_pct === null ? <span title="Grupo sem empresas no universo filtrado">N/A</span> : `${pct(i.taxa_pct)} (${i.ganhos}/${i.empresas})`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {dados.truncado && <p className="muted">Mostrando os {dados.itens.length} maiores de {dados.total_grupos} grupos.</p>}
    </>
  );
}

export function MetricsPage() {
  const { filtros } = useFiltros();
  const params = paramsApi(filtros);
  const resumo = useMetricasResumo(params);
  const funil = useMetricasFunil(params);
  const nicho = useConversao("nicho", params);
  const cidade = useConversao("cidade", params);
  const d = resumo.data?.definicoes ?? {};

  return (
    <>
      <GlobalFilterBar extras />
      <ActiveFilterChips />
      {resumo.error && <ErroBox erro={resumo.error} onTentar={() => resumo.refetch()} />}

      <h2>Visão geral</h2>
      <div className="kpis">
        <Kpi rotulo="Empresas" valor={resumo.data?.total_empresas} definicao={d.total_empresas ?? ""} />
        <Kpi rotulo="Com email confirmado" valor={resumo.data?.com_email_confirmado} definicao={d.com_email_confirmado ?? ""} />
        <Kpi rotulo="Com formulário" valor={resumo.data?.com_formulario} definicao={d.com_formulario ?? ""} />
        <Kpi rotulo="Telefone apto (WhatsApp não verificado)" valor={resumo.data?.com_telefone_apto} definicao={d.com_telefone_apto ?? ""} />
        <Kpi rotulo="Com score" valor={resumo.data?.com_score} definicao={d.com_score ?? ""} />
        <Kpi rotulo="Empresas com email enviado" valor={resumo.data?.empresas_com_email_enviado} definicao={d.empresas_com_email_enviado ?? ""} />
        <Kpi rotulo="Mensagens de email enviadas" valor={resumo.data?.mensagens_email_enviadas} definicao={d.mensagens_email_enviadas ?? ""} />
        <Kpi rotulo="Em Ganho (atual)" valor={resumo.data?.em_ganho_atual} definicao={d.em_ganho_atual ?? ""} />
      </div>

      <div className="graficos">
        <section>
          <h2>Onde os leads estão hoje <MetricDefinitionTooltip texto={funil.data?.definicoes.atual ?? ""} /></h2>
          {funil.data ? (
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={funil.data.atual} layout="vertical" margin={{ left: 30, right: 30 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" allowDecimals={false} />
                <YAxis type="category" dataKey="rotulo" width={110} />
                <Tooltip />
                <Bar dataKey="total" name="Empresas (atual)" fill="#2b6cb0"><LabelList dataKey="total" position="right" /></Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : <Carregando />}
          <p className="muted">Estoque atual — não é taxa de progressão entre etapas.</p>
        </section>

        <section>
          <h2>Já passaram por cada estágio <MetricDefinitionTooltip texto={funil.data?.definicoes.historico_passagem ?? ""} /></h2>
          {funil.data ? (
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={funil.data.historico_passagem} layout="vertical" margin={{ left: 30, right: 30 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" allowDecimals={false} />
                <YAxis type="category" dataKey="rotulo" width={110} />
                <Tooltip />
                <Bar dataKey="empresas_distintas" name="Empresas distintas" fill="#6b46c1"><LabelList dataKey="empresas_distintas" position="right" /></Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : <Carregando />}
          <p className="muted">Trajetória histórica: só mudanças registradas no funil (o estágio inferido de email enviado não conta aqui).</p>
        </section>
      </div>

      <h2>Distribuição por nicho e coluna</h2>
      <div className="tabela-wrap">
        <table className="tabela">
          <thead><tr><th>Nicho</th>{["Novo", "Qualificado", "Contatado", "Ganho", "Descartado"].map((c) => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>
            {(resumo.data?.por_nicho_e_coluna ?? []).map((n) => (
              <tr key={n.nicho_slug}>
                <td>{n.nicho_nome}</td>
                {(["novo", "qualificado", "contatado", "ganho", "descartado"] as const).map((c) => <td key={c}>{n.colunas[c].toLocaleString("pt-BR")}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>Conversão comercial por nicho <MetricDefinitionTooltip texto={nicho.data?.definicao ?? ""} /></h2>
      {nicho.error ? <ErroBox erro={nicho.error} /> : <TabelaConversao dados={nicho.data} titulo="Conversão por nicho" />}

      <h2>Conversão comercial por cidade</h2>
      <details>
        <summary>
          Mostrar tabela por cidade{cidade.data ? ` (${cidade.data.itens.length} de ${cidade.data.total_grupos} grupos)` : ""}
        </summary>
        {cidade.error ? <ErroBox erro={cidade.error} /> : <TabelaConversao dados={cidade.data} titulo="Conversão por cidade" />}
      </details>
    </>
  );
}
