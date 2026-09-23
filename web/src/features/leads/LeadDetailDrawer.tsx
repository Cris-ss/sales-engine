import { useEffect } from "react";
import { useLead } from "../../api/hooks";
import { ChannelBadges, EmailStatusBadge, ScoreBadge, StageBadge } from "../../components/badges";
import { Carregando, ErroBox, useToast } from "../../components/states";
import { useFiltros } from "../../lib/filtros";
import { formatarCep, formatarCnpj, formatarDataHora, formatarTelefone, localidade, titulo } from "../../lib/format";
import { copiar } from "../../lib/whatsapp";
import { ContactHistory, FunnelHistory, ScoreHistory } from "./Historicos";
import { StageChangeMenu } from "./StageChangeMenu";
import { WhatsAppAction } from "./WhatsAppAction";
import { WhatsappAutorizar } from "../whatsapp/WhatsappAutorizar";

const MOTIVOS: Record<string, string> = {
  site_nao_confirmado_marca_ausente:
    "Retirado do fluxo ativo: o site encontrado não confirma que pertence a esta empresa (a marca não aparece no conteúdo). O registro foi mantido para revisão manual.",
  sem_email_ou_formulario: "Nenhum email ou formulário de contato foi encontrado no site.",
  nao_verificado_telefone_e_endereco_diferentes: "O Google Places não confirmou a empresa (telefone e endereço não batem).",
  nenhum_resultado_places: "Nenhum resultado no Google Places.",
};

export function LeadDetailDrawer() {
  const { leadAberto, setLocal } = useFiltros();
  const { data: l, isLoading, error, refetch } = useLead(leadAberto);
  const toast = useToast();

  useEffect(() => {
    if (leadAberto === null) return;
    const fechar = (e: KeyboardEvent) => e.key === "Escape" && setLocal("lead", null);
    window.addEventListener("keydown", fechar);
    return () => window.removeEventListener("keydown", fechar);
  }, [leadAberto, setLocal]);

  if (leadAberto === null) return null;

  const cp = async (texto: string, o: string) => {
    const ok = await copiar(texto);
    toast(ok ? "ok" : "aviso", ok ? `${o} copiado.` : `Não foi possível copiar ${o}.`);
  };

  return (
    <aside className="drawer" role="complementary" aria-label="Detalhes do lead">
      <div className="drawer-topo">
        <h2>{l ? titulo(l.nome) : "Lead"}{l?.fonte === "manual_operador" && <span className="tag-origem" title="Cadastrado manualmente pelo operador"> manual</span>}</h2>
        <button className="btn" onClick={() => setLocal("lead", null)} aria-label="Fechar detalhes">Fechar ✕</button>
      </div>

      {isLoading && <Carregando />}
      {error && <ErroBox erro={error} onTentar={() => refetch()} />}

      {l && (
        <div className="drawer-corpo">
          <p className="muted">
            {l.cnpj ? `CNPJ ${formatarCnpj(l.cnpj)}` : "Sem CNPJ (origem OSM)"} · {l.nicho_nome} · {localidade(l.municipio, l.uf)}
          </p>
          <div className="badges">
            <ScoreBadge score={l.score} faixa={l.faixa_score} />
            <StageBadge lead={l} />
            <ChannelBadges lead={l} />
            <EmailStatusBadge status={l.email_status} qtd={l.qtd_emails_enviados} />
          </div>

          {l.motivo_reprovacao && MOTIVOS[l.motivo_reprovacao] && (
            <p className="aviso">{MOTIVOS[l.motivo_reprovacao]}</p>
          )}

          <div className="acoes-rapidas">
            {l.site_url && <a className="btn" href={l.site_url} target="_blank" rel="noopener noreferrer">Abrir site ↗</a>}
            {l.email_confirmado && l.email_final && <button className="btn" onClick={() => cp(l.email_final!, "Email")}>Copiar email</button>}
            {(l.telefone1 || l.telefone2) && <button className="btn" onClick={() => cp(formatarTelefone(l.telefone1 || l.telefone2), "Telefone")}>Copiar telefone</button>}
          </div>

          <h3>WhatsApp (manual)</h3>
          <WhatsAppAction leadId={l.id} />

          <h3>WhatsApp automatizado</h3>
          <WhatsappAutorizar leadId={l.id} />

          <h3>Mudar estágio</h3>
          <StageChangeMenu lead={l} />

          <h3>Score</h3>
          {l.score !== null ? (
            <>
              {l.dores_identificadas && <p><strong>Dores identificadas:</strong> {l.dores_identificadas}</p>}
              {l.justificativa && <p><strong>Análise:</strong> {l.justificativa}</p>}
              <p className="muted">{l.modelo_usado} · prompt {l.prompt_versao} · {formatarDataHora(l.score_em)}</p>
            </>
          ) : (
            <p className="muted">Sem score.</p>
          )}
          <details>
            <summary>Histórico de scores</summary>
            <ScoreHistory leadId={l.id} />
          </details>

          <h3>Canais e validação</h3>
          <ul className="lista-simples">
            <li>Email: {l.email_confirmado ? <strong>{l.email_final}</strong> : <span className="muted">não confirmado{l.email_final ? " (existe um endereço guardado, mas o canal não foi aprovado)" : ""}</span>}</li>
            <li>Formulário: {l.formulario_confirmado && l.formulario_contato_url ? <a href={l.formulario_contato_url} target="_blank" rel="noopener noreferrer">{l.formulario_contato_url}</a> : <span className="muted">não confirmado</span>}</li>
            <li>Telefones (Receita): {[l.telefone1, l.telefone2].filter(Boolean).map((t) => formatarTelefone(t)).join(" · ") || "—"}</li>
            <li>Google Places: {l.places_verificado ? `verificado (${[l.places_telefone_confirmado && "telefone", l.places_endereco_confirmado && "rua"].filter(Boolean).join(" + ")})` : "não verificado"}</li>
            <li>Site ativo: {l.site_ativo === null ? "—" : l.site_ativo ? "sim" : "não"}</li>
          </ul>

          <h3>Endereço</h3>
          <p>
            {[l.logradouro, l.numero, l.complemento, l.bairro].filter(Boolean).map((x) => titulo(x)).join(", ") || "—"}
            <br />
            {localidade(l.municipio, l.uf)} · CEP {formatarCep(l.cep) || "—"}
            {l.localizacao && (
              <>
                <br />
                <span className="muted">
                  Coordenadas: {l.localizacao.latitude.toFixed(5)}, {l.localizacao.longitude.toFixed(5)} (precisão: {l.localizacao.precisao})
                </span>
              </>
            )}
          </p>

          <h3>Mensagens (email / formulário)</h3>
          <ContactHistory leadId={l.id} />

          <h3>Histórico do funil</h3>
          <FunnelHistory leadId={l.id} derivado={l.estagio_derivado} estagio={l.estagio} />

          <h3>Empresa</h3>
          <ul className="lista-simples">
            <li>Razão social: {l.razao_social ?? "—"}</li>
            <li>Porte: {l.porte ?? "—"} · Natureza jurídica: {l.natureza_juridica ?? "—"}</li>
            <li>CNAE: {l.cnae_principal ?? "—"} · Início: {l.data_inicio_atividade ?? "—"}</li>
          </ul>
        </div>
      )}
    </aside>
  );
}
