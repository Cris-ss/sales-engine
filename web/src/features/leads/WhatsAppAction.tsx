import { useState } from "react";
import { useWhatsappLink } from "../../api/hooks";
import { Carregando, ErroBox, useToast } from "../../components/states";
import { abrirWhatsapp } from "../../lib/whatsapp";

/** Botão manual de WhatsApp. Abrir o link NÃO registra envio nem muda o funil. */
export function WhatsAppAction({ leadId }: { leadId: number }) {
  const { data, isLoading, error, refetch } = useWhatsappLink(leadId);
  const toast = useToast();
  const [abrindo, setAbrindo] = useState(false);

  if (isLoading) return <Carregando texto="Preparando link…" />;
  if (error) return <ErroBox erro={error} onTentar={() => refetch()} />;
  if (!data) return null;

  if (!data.apto) {
    return (
      <div className="wpp">
        <button className="btn" disabled aria-describedby={`wpp-motivo-${leadId}`}>Abrir WhatsApp</button>
        <p id={`wpp-motivo-${leadId}`} className="muted">
          Indisponível: {data.motivo_inapto ?? "sem telefone apto"}.
        </p>
      </div>
    );
  }

  return (
    <div className="wpp">
      <button
        className="btn btn-wpp"
        disabled={abrindo}
        onClick={async () => {
          setAbrindo(true);
          try {
            const r = await abrirWhatsapp(leadId);
            if (!r.ok) toast("aviso", r.motivo ?? "Não foi possível abrir o WhatsApp.");
          } catch (e) {
            toast("erro", (e as Error).message);
          } finally {
            setAbrindo(false);
          }
        }}
      >
        Abrir WhatsApp
      </button>
      <p className="muted">
        Número {data.telefone_normalizado}
        {data.nono_digito_acrescentado ? " (9º dígito acrescentado)" : ""} — <strong>não verificado</strong>: o telefone
        vem da Receita e não comprova que existe WhatsApp. Abrir o link não registra envio nem move o lead no funil.
      </p>
      <details>
        <summary>Mensagem pré-preenchida</summary>
        <p className="mensagem">{data.mensagem}</p>
      </details>
    </div>
  );
}
