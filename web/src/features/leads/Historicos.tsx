import { useContatos, useFunilHistorico, useScores } from "../../api/hooks";
import { ScoreBadge } from "../../components/badges";
import { Carregando, ErroBox } from "../../components/states";
import { formatarDataHora } from "../../lib/format";

const ROTULO_STATUS: Record<string, string> = {
  enviado: "Enviado (aceito pelo SMTP)",
  pendente: "Pendente — ainda não enviado",
  falhou: "Falha na tentativa — segue pendente",
};

export function ContactHistory({ leadId }: { leadId: number }) {
  const { data, isLoading, error, refetch } = useContatos(leadId);
  if (isLoading) return <Carregando />;
  if (error) return <ErroBox erro={error} onTentar={() => refetch()} />;
  if (!data?.itens.length) return <p className="muted">Nenhuma mensagem gerada para este lead.</p>;
  return (
    <ul className="historico">
      {data.itens.map((c) => (
        <li key={c.id}>
          <div>
            <strong>{c.canal === "email" ? "Email" : "Formulário"}</strong> → {c.destino}
            <span className={`badge email-${c.status}`}>{ROTULO_STATUS[c.status] ?? c.status}</span>
          </div>
          <div className="muted">
            Gerada em {formatarDataHora(c.gerado_em)} ·{" "}
            {c.enviado_em ? <>Enviada em <strong>{formatarDataHora(c.enviado_em)}</strong></> : "Ainda não enviada"}
          </div>
          {c.assunto && (
            <details>
              <summary>{c.assunto}</summary>
              <pre className="mensagem">{c.corpo}</pre>
            </details>
          )}
        </li>
      ))}
    </ul>
  );
}

export function FunnelHistory({ leadId, derivado, estagio }: { leadId: number; derivado: boolean; estagio: string }) {
  const { data, isLoading, error, refetch } = useFunilHistorico(leadId);
  if (isLoading) return <Carregando />;
  if (error) return <ErroBox erro={error} onTentar={() => refetch()} />;
  return (
    <>
      {derivado && (
        <p className="aviso-derivado">
          Nenhuma mudança registrada no funil. O estágio <strong>{estagio}</strong> é <strong>inferido</strong> (email enviado ⇒
          contatada; caso contrário, encontrada) e não foi gravado.
        </p>
      )}
      {!!data?.itens.length && (
        <ol className="historico">
          {data.itens.map((f) => (
            <li key={f.id}>
              <strong>{f.estagio.replace("_", " ")}</strong> <span className="muted">({f.coluna})</span> · {formatarDataHora(f.criado_em)}
              {f.observacao && <div className="muted">“{f.observacao}”</div>}
            </li>
          ))}
        </ol>
      )}
    </>
  );
}

export function ScoreHistory({ leadId }: { leadId: number }) {
  const { data, isLoading, error, refetch } = useScores(leadId);
  if (isLoading) return <Carregando />;
  if (error) return <ErroBox erro={error} onTentar={() => refetch()} />;
  if (!data?.itens.length) return <p className="muted">Sem score.</p>;
  return (
    <ul className="historico">
      {data.itens.map((s) => (
        <li key={s.id}>
          <ScoreBadge score={s.score} faixa={s.faixa_score} /> <span className="muted">{s.modelo_usado} · prompt {s.prompt_versao} · {formatarDataHora(s.criado_em)}</span>
        </li>
      ))}
    </ul>
  );
}
