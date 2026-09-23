import { useState } from "react";
import { Link } from "react-router-dom";
import { useWaAutorizar, useWaContexto, useWaLead, useWaRemoverTelefone, useWaRevogar, useWaTelefoneManual } from "../../api/whatsapp";
import { Carregando, ErroBox, useToast } from "../../components/states";
import { formatarTelefone } from "../../lib/format";

/** Autorização EXPLÍCITA por número. Sem esta ação, nenhuma mensagem automática é enviada nem respondida. */
export function WhatsappAutorizar({ leadId }: { leadId: number }) {
  const { data, isLoading, error, refetch } = useWaLead(leadId);
  const autorizar = useWaAutorizar();
  const revogar = useWaRevogar();
  const remover = useWaRemoverTelefone();
  const [removendo, setRemovendo] = useState<string | null>(null);
  const toast = useToast();
  const [confirmando, setConfirmando] = useState<string | null>(null);
  const [ciente, setCiente] = useState(false);

  if (isLoading) return <Carregando texto="Carregando…" />;
  if (error) return <ErroBox erro={error} onTentar={() => refetch()} />;
  if (!data) return null;
  return (
    <div className="wa-autorizar">
      {data.telefones.length === 0 && <p className="muted">Sem telefone cadastrado para autorizar.</p>}
      {data.pode_adicionar_telefone && <AdicionarTelefone leadId={leadId} semTelefone={data.telefones.length === 0} />}
      <ContextoDoLead leadId={leadId} atual={data.contexto_manual ?? ""} />
      <p className="muted">Estado do WhatsApp: <strong>{data.conta.estado}</strong>{data.conta.automacao_habilitada ? "" : " · automação pausada"}</p>
      {data.telefones.map((t) => (
        <div key={t.telefone} className="wa-tel">
          <strong>{formatarTelefone(t.original ?? t.telefone)}</strong>
          {t.origem === "manual_operador" && <span className="tag-origem" title="Telefone digitado manualmente por você (não veio da Receita nem do OSM)"> manual</span>}
          {t.origem === "manual_operador" && removendo !== t.telefone && (
            <button className="btn btn-pequeno" onClick={() => setRemovendo(t.telefone)}>Remover telefone</button>
          )}
          {removendo === t.telefone && (
            <div className="aviso wa-confirma" role="alert">
              <p>Remover <strong>{formatarTelefone(t.original ?? t.telefone)}</strong> deste lead? {t.autorizacao ? "A autorização de WhatsApp deste número será revogada. " : ""}
                O histórico da conversa é mantido. Só telefones digitados manualmente podem ser removidos.</p>
              <button className="btn btn-perigo" disabled={remover.isPending}
                onClick={() => remover.mutate({ empresaId: leadId, telefone: t.telefone }, {
                  onSuccess: (r) => { setRemovendo(null); toast("ok", r.autorizacao_revogada ? "Telefone removido e autorização revogada." : "Telefone removido."); },
                  onError: (e) => toast("erro", (e as Error).message),
                })}>{remover.isPending ? "Removendo…" : "Sim, remover"}</button>
              <button className="btn" onClick={() => setRemovendo(null)}>Cancelar</button>
            </div>
          )}
          {t.suprimido && <span className="aviso">Pediu para não ser contatado (supressão). Não pode ser autorizado.</span>}
          {t.autorizacao ? (
            <>
              <span className="muted"> autorizado por {t.autorizacao.autorizado_por} · válido até {t.autorizacao.expira_em?.slice(0, 10)}</span>
              {t.bloqueios.length > 0 && (
                <div className={t.bloqueios.some((b) => b.nivel === "alerta") ? "wa-bloqueio" : "wa-info"} role="status">
                  <strong>{t.bloqueios.some((b) => b.nivel === "alerta") ? "Parada, aguardando:" : "Situação:"}</strong>
                  <ul>{t.bloqueios.map((b) => <li key={b.codigo}>{b.texto}</li>)}</ul>
                </div>
              )}
              {t.conversa_id && <Link className="btn btn-pequeno" to={`/whatsapp?conversa=${t.conversa_id}`}>Abrir conversa</Link>}
              <button className="btn btn-pequeno" disabled={revogar.isPending}
                onClick={() => revogar.mutate(t.autorizacao!.id, { onSuccess: () => toast("aviso", "Autorização revogada."), onError: (e) => toast("erro", (e as Error).message) })}>
                Revogar
              </button>
            </>
          ) : !t.suprimido && confirmando !== t.telefone ? (
            <button className="btn btn-primario" onClick={() => { setConfirmando(t.telefone); setCiente(false); }}>Autorizar e iniciar conversa</button>
          ) : null}
          {confirmando === t.telefone && !t.autorizacao && (
            <div className="aviso wa-confirma">
              <p>
                <strong>{data.nome}</strong> · número <strong>{formatarTelefone(t.original ?? t.telefone)}</strong>.<br />
                {data.conta.modo_envio === "manual" ? (
                  <>Modo copiloto: a IA vai <strong>sugerir</strong> o primeiro contato e as respostas neste número; <strong>você as envia manualmente</strong> pelo
                  WhatsApp e confirma aqui. O sistema não envia nada. Você pode pausar ou revogar a qualquer momento.</>
                ) : (
                  <>A IA enviará o primeiro contato e <strong>continuará respondendo automaticamente</strong> neste número, dentro da política comercial
                  vigente, sem aprovar mensagem a mensagem. Você pode pausar, assumir ou revogar a qualquer momento.</>
                )}
              </p>
              <label><input type="checkbox" checked={ciente} onChange={(e) => setCiente(e.target.checked)} /> Estou ciente e autorizo este número.</label>
              <div>
                <button className="btn btn-primario" disabled={!ciente || autorizar.isPending}
                  onClick={() => autorizar.mutate({ empresaId: leadId, telefone: t.telefone }, {
                    onSuccess: () => { setConfirmando(null); toast("ok", data.conta.modo_envio === "manual" ? "Número autorizado. A IA vai sugerir o primeiro contato: ele aparece na aba WhatsApp para você enviar." : "Número autorizado. O primeiro contato entra na fila (respeita horário e limites)."); },
                    onError: (e) => toast("erro", (e as Error).message),
                  })}>
                  {autorizar.isPending ? "Autorizando…" : "Autorizar"}
                </button>
                <button className="btn" onClick={() => setConfirmando(null)}>Cancelar</button>
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

/** Preenche um telefone vazio do lead. Fica registrado como origem "manual" (diferente de Receita/OSM). Não autoriza nada sozinho. */
function AdicionarTelefone({ leadId, semTelefone }: { leadId: number; semTelefone: boolean }) {
  const salvar = useWaTelefoneManual();
  const toast = useToast();
  const [aberto, setAberto] = useState(semTelefone);
  const [valor, setValor] = useState("");
  if (!aberto) return <button className="btn btn-pequeno" onClick={() => setAberto(true)}>+ Adicionar telefone</button>;
  return (
    <form className="wa-tel" onSubmit={(e) => {
      e.preventDefault();
      salvar.mutate({ empresaId: leadId, telefone: valor }, {
        onSuccess: () => { setValor(""); setAberto(false); toast("ok", "Telefone salvo (origem: manual). Agora você pode autorizá-lo."); },
        onError: (er) => toast("erro", (er as Error).message),
      });
    }}>
      <label className="campo"><span>Telefone (DDD + número, com ou sem 55)</span>
        <input required value={valor} onChange={(e) => setValor(e.target.value)} placeholder="11999998888" inputMode="tel" /></label>
      <button className="btn btn-primario" disabled={salvar.isPending || !valor.trim()}>{salvar.isPending ? "Salvando…" : "Salvar telefone"}</button>
      {!semTelefone && <button type="button" className="btn" onClick={() => setAberto(false)}>Cancelar</button>}
    </form>
  );
}

/** Contexto livre do operador sobre o lead. A IA usa como apoio (sem citar); nunca vira preço/catálogo. */
function ContextoDoLead({ leadId, atual }: { leadId: number; atual: string }) {
  const salvar = useWaContexto();
  const toast = useToast();
  const [texto, setTexto] = useState<string | null>(null);
  const valor = texto ?? atual;
  return (
    <div className="wa-contexto-lead">
      <label className="campo"><span>Contexto para a IA (opcional)</span>
        <textarea rows={4} maxLength={4000} value={valor} onChange={(e) => setTexto(e.target.value)}
          placeholder="Achados que você já tem sobre esta empresa. A IA usa como apoio, sem citar literalmente; não vira preço nem catálogo." />
      </label>
      <button className="btn btn-pequeno" disabled={texto === null || salvar.isPending}
        onClick={() => salvar.mutate({ empresaId: leadId, contexto: valor }, {
          onSuccess: () => { setTexto(null); toast("ok", "Contexto salvo."); },
          onError: (e) => toast("erro", (e as Error).message),
        })}>{salvar.isPending ? "Salvando…" : "Salvar contexto"}</button>
    </div>
  );
}
