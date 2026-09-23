import { QRCodeSVG } from "qrcode.react";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  useWaAceiteTratado, useWaAutorizarNovo, useWaConfirmarEnvio, useWaDescartarSugestao, useWaRegistrarEnvio, useWaConectar, useWaControle, useWaConversa, useWaConversas, useWaDemandaRevisada, useWaDemandas, useWaDesconectar, useWaEnviar,
  useWaKillSwitch, useWaPolitica, useWaPublicarPolitica, useWaQr, useWaStatus,
} from "../../api/whatsapp";
import { useNichos } from "../../api/hooks";
import { Carregando, ErroBox, useToast } from "../../components/states";
import { formatarDataHora } from "../../lib/format";

const CONTROLES: [string | null, string][] = [
  [null, "Todas"], ["automatizada", "Automatizadas"], ["humano", "Aguardando humano"], ["fora_escopo", "Fora do escopo automatizado"],
  ["pausada", "Pausadas"], ["encerrada", "Encerradas"],
];
const reais = (c: number) => (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

interface Rascunho { texto: string; base: number }
const CHAVE_RASCUNHO = "wa-politica-rascunho";

function lerRascunho(): Rascunho | null {
  try {
    const bruto = sessionStorage.getItem(CHAVE_RASCUNHO);
    return bruto ? (JSON.parse(bruto) as Rascunho) : null;
  } catch { return null; }
}

export function WhatsappPage() {
  const [aba, setAba] = useState<"caixa" | "conexao" | "politica">("caixa");
  const navigate = useNavigate();
  // O rascunho da política e o erro de salvar ficam AQUI (e não na aba) para não se perderem ao trocar de aba.
  const [rascunho, setRascunhoEstado] = useState<Rascunho | null>(lerRascunho);
  const [erroPolitica, setErroPolitica] = useState<string | null>(null);
  const setRascunho = (r: Rascunho | null) => {
    setRascunhoEstado(r);
    try { if (r) sessionStorage.setItem(CHAVE_RASCUNHO, JSON.stringify(r)); else sessionStorage.removeItem(CHAVE_RASCUNHO); } catch { /* sem armazenamento: só perde no reload */ }
  };
  const status = useWaStatus();
  const kill = useWaKillSwitch();
  const toast = useToast();
  const s = status.data;
  return (
    <section>
      <h2>WhatsApp automatizado</h2>
      {status.error && <ErroBox erro={status.error} onTentar={() => status.refetch()} />}
      {s && (
        <div className={s.automacao_habilitada ? "wa-barra" : "wa-barra wa-pausada"}>
          <span>Conexão: <strong>{s.estado}</strong>{s.numero ? ` (${s.numero})` : ""}{!s.gateway_ativo && " · gateway offline"}</span>
          {s.aceites_pendentes > 0 && (
            <a className="wa-aceites" href="/whatsapp?aceites=1" onClick={(e) => { e.preventDefault(); setAba("caixa"); navigate("/whatsapp?aceites=1"); }}>
              🔔 {s.aceites_pendentes} aceite{s.aceites_pendentes > 1 ? "s" : ""} aguardando você
            </a>
          )}
          <span className={s.modo_envio === "manual" ? "wa-modo" : "wa-modo wa-modo-auto"}>
            Modo: <strong>{s.modo_envio === "manual" ? "COPILOTO (a IA sugere; você envia; nada é enviado pelo sistema)" : "AUTOMÁTICO (o sistema envia)"}</strong>
          </span>
          {s.modo_envio === "manual" && (
            <span title="Lembrete: não bloqueia nada. É só para você controlar o ritmo dos primeiros contatos.">
              Primeiros contatos que você enviou hoje: <strong>{s.primeiros_contatos_hoje}</strong> (lembrete: até {String((s.limites as { novos_contatos_dia?: number }).novos_contatos_dia ?? 10)}/dia)
            </span>
          )}
          <span>Automação: <strong>{s.automacao_habilitada ? "ligada" : "PAUSADA"}</strong>{s.motivo_pausa ? ` (${s.motivo_pausa})` : ""}</span>
          {(s.notificacoes_operador.pendentes > 0 || s.notificacoes_operador.falhas > 0) && (
            <span className="aviso">Avisos de aceite ao operador: {s.notificacoes_operador.pendentes} pendente(s), {s.notificacoes_operador.falhas} com falha</span>
          )}
          <span>Conversa de venda: <strong>{s.vendas_ativas ? "ativa" : "desativada"}</strong></span>
          <button className={s.automacao_habilitada ? "btn btn-perigo" : "btn btn-primario"} disabled={kill.isPending}
            onClick={() => kill.mutate({ pausar: s.automacao_habilitada, motivo: "pausa manual pela interface" }, {
              onSuccess: () => toast("aviso", s.automacao_habilitada ? "Toda a automação foi pausada." : "Automação retomada (mensagens antigas não são liberadas)."),
              onError: (e) => toast("erro", (e as Error).message),
            })}>
            {s.automacao_habilitada ? "Pausar toda a automação WhatsApp" : "Retomar automação"}
          </button>
        </div>
      )}
      <div className="abas-locais" role="tablist">
        {([["caixa", "Caixa de entrada"], ["conexao", "Conexão"], ["politica", "Política comercial e demandas"]] as const).map(([k, r]) => (
          <button key={k} role="tab" aria-selected={aba === k} className={aba === k ? "aba ativa" : "aba"} onClick={() => setAba(k)}>
            {r}{k === "politica" && rascunho ? " ●" : ""}
          </button>
        ))}
      </div>
      {aba === "caixa" && <Caixa />}
      {aba === "conexao" && <Conexao />}
      {aba === "politica" && <Politica rascunho={rascunho} setRascunho={setRascunho} erro={erroPolitica} setErro={setErroPolitica} />}
    </section>
  );
}

function Caixa() {
  const [params, setParams] = useSearchParams();
  const [controle, setControle] = useState<string | null>(null);
  const [problemas, setProblemas] = useState(false);
  const [sugestoes, setSugestoes] = useState(false);
  const [aceites, setAceites] = useState(params.get("aceites") === "1");
  useEffect(() => { if (params.get("aceites") === "1") { setAceites(true); setControle(null); setProblemas(false); setSugestoes(false); } }, [params]);
  const lista = useWaConversas(controle, problemas, sugestoes, aceites);
  const selecionada = params.get("conversa") ? Number(params.get("conversa")) : null;
  return (
    <div className="wa-caixa">
      <div>
        <AutorizarNovo aoCriar={(id) => setParams({ conversa: String(id) })} />
        <div className="filtros">
          {CONTROLES.map(([k, r]) => (
            <button key={r} className={controle === k && !problemas && !sugestoes && !aceites ? "btn btn-primario" : "btn"} onClick={() => { setControle(k); setProblemas(false); setSugestoes(false); setAceites(false); }}>
              {r}{k && lista.data ? ` (${lista.data.resumo[k] ?? 0})` : ""}
            </button>
          ))}
          <button className={aceites ? "btn btn-primario" : "btn"} onClick={() => { setAceites(true); setSugestoes(false); setProblemas(false); setControle(null); }}>
            Aceites aguardando você{lista.data ? ` (${lista.data.resumo.com_aceite ?? 0})` : ""}
          </button>
          <button className={sugestoes ? "btn btn-primario" : "btn"} onClick={() => { setSugestoes(true); setAceites(false); setProblemas(false); setControle(null); }}>
            Aguardando meu envio{lista.data ? ` (${lista.data.resumo.com_sugestao ?? 0})` : ""}
          </button>
          <button className={problemas ? "btn btn-primario" : "btn"} onClick={() => { setProblemas(true); setSugestoes(false); setAceites(false); setControle(null); }}>
            Com falha/incerteza{lista.data ? ` (${lista.data.resumo.com_problema ?? 0})` : ""}
          </button>
        </div>
        {lista.isLoading && <Carregando />}
        {lista.error && <ErroBox erro={lista.error} onTentar={() => lista.refetch()} />}
        {lista.data && lista.data.itens.length === 0 && <p className="muted">Nenhuma conversa nesta visão.</p>}
        <ul className="wa-lista">
          {lista.data?.itens.map((c) => (
            <li key={c.id} className={selecionada === c.id ? "ativa" : ""}>
              <button onClick={() => setParams({ conversa: String(c.id) })}>
                <strong>{c.empresa_nome ?? c.contato_nome ?? c.telefone ?? `Contato ${c.id}`}</strong>
                <span className="muted"> · {c.controle}{c.controle === "fora_escopo" ? " (sem resposta automática)" : ""}</span>
                {c.aceite_pendente && <span className="tag-aceite"> 🔔 aceite</span>}
                {c.sugestao_pendente && <span className="tag-sugestao"> ✎ resposta sugerida</span>}
                {c.bloqueios.some((b) => b.nivel === "alerta") && <span className="tag-parada" title={c.bloqueios.map((b) => b.texto).join(" ")}> ⏸ parada</span>}
                <br /><span className="muted">{c.ultima_autoria === "cliente" ? "Cliente: " : c.ultima_autoria ? "Nós: " : ""}{(c.ultima_mensagem ?? "—").slice(0, 80)}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
      <Conversa id={selecionada} />
    </div>
  );
}

/** Atalho: número descoberto fora do sistema. Cria a empresa (origem "manual") e autoriza o número no mesmo clique. */
function AutorizarNovo({ aoCriar }: { aoCriar: (conversaId: number) => void }) {
  const [aberto, setAberto] = useState(false);
  const { data: nichos } = useNichos();
  const autorizar = useWaAutorizarNovo();
  const modoNovo = useWaStatus().data?.modo_envio ?? "manual";
  const toast = useToast();
  const [telefone, setTelefone] = useState("");
  const [nome, setNome] = useState("");
  const [nichoId, setNichoId] = useState("");
  const [contexto, setContexto] = useState("");
  const [ciente, setCiente] = useState(false);
  if (!aberto) return <button className="btn btn-primario" onClick={() => setAberto(true)}>+ Autorizar novo número</button>;
  return (
    <form className="aviso wa-novo" onSubmit={(e) => {
      e.preventDefault();
      autorizar.mutate({ telefone, nome, nicho_id: Number(nichoId), contexto: contexto.trim() || undefined }, {
        onSuccess: (r) => {
          toast("ok", r.empresa_criada ? "Empresa criada (origem: manual) e número autorizado." : "Número já cadastrado em uma empresa existente: autorizado.");
          setAberto(false); setTelefone(""); setNome(""); setNichoId(""); setContexto(""); setCiente(false); aoCriar(r.conversa_id);
        },
        onError: (er) => toast("erro", (er as Error).message),
      });
    }}>
      <strong>Autorizar novo número</strong>
      <div className="filtros">
        <label className="campo"><span>Telefone (DDI+DDD+número)</span><input required value={telefone} onChange={(e) => setTelefone(e.target.value)} placeholder="5511999998888" inputMode="tel" /></label>
        <label className="campo"><span>Nome da empresa</span><input required minLength={2} value={nome} onChange={(e) => setNome(e.target.value)} /></label>
        <label className="campo"><span>Nicho</span>
          <select required value={nichoId} onChange={(e) => setNichoId(e.target.value)}><option value="">Selecione</option>{(nichos ?? []).map((n) => <option key={n.id} value={n.id}>{n.nome}</option>)}</select>
        </label>
      </div>
      <label className="campo wa-contexto"><span>Contexto adicional (opcional)</span>
        <textarea rows={4} maxLength={4000} value={contexto} onChange={(e) => setContexto(e.target.value)}
          placeholder="Cole aqui o que você já sabe sobre esta empresa (ex.: achados de outra ferramenta). A IA usa como apoio, sem citar literalmente; não vira preço nem catálogo." />
      </label>
      <label><input type="checkbox" checked={ciente} onChange={(e) => setCiente(e.target.checked)} /> {modoNovo === "manual"
          ? "Autorizo este número: a IA vai SUGERIR o primeiro contato e as respostas; você as envia manualmente pelo WhatsApp (o sistema não envia nada)."
          : "Autorizo este número: a IA enviará o primeiro contato e continuará respondendo automaticamente (dentro da política, com horário e limites)."}</label>
      <div>
        <button className="btn btn-primario" disabled={!ciente || autorizar.isPending}>{autorizar.isPending ? "Autorizando…" : "Criar empresa e autorizar"}</button>
        <button type="button" className="btn" onClick={() => setAberto(false)}>Cancelar</button>
      </div>
    </form>
  );
}

function Conversa({ id }: { id: number | null }) {
  const { data: c, error, isLoading } = useWaConversa(id);
  const controle = useWaControle();
  const enviar = useWaEnviar();
  const registrar = useWaRegistrarEnvio();
  const tratado = useWaAceiteTratado();
  const modo = useWaStatus().data?.modo_envio ?? "manual";
  const toast = useToast();
  const [texto, setTexto] = useState("");
  if (id === null) return <div className="wa-conversa muted">Selecione uma conversa.</div>;
  if (isLoading) return <div className="wa-conversa"><Carregando /></div>;
  if (error || !c) return <div className="wa-conversa"><ErroBox erro={error} /></div>;
  const acao = (a: "assumir" | "pausar" | "retomar-ia") => controle.mutate({ id: c.id, acao: a }, {
    onSuccess: (r) => {
      if (a !== "retomar-ia") return;
      toast(r.tarefa_recriada ? "ok" : "aviso", r.tarefa_recriada === "primeiro_contato" ? "IA retomada: o primeiro contato voltou para a fila."
        : r.tarefa_recriada === "resposta" ? "IA retomada: a resposta ao cliente voltou para a fila."
        : "IA retomada. Não havia tarefa a recriar (já existe uma pendente, ou só falta o cliente responder).");
    },
    onError: (e) => toast("erro", (e as Error).message),
  });
  const semTarefa = c.bloqueios.some((b) => b.codigo.startsWith("sem_tarefa"));
  return (
    <div className="wa-conversa">
      <h3>{c.empresa_nome ?? c.contato_nome ?? c.telefone}</h3>
      <p className="muted">{c.telefone} · controle <strong>{c.controle}</strong> · estágio {c.estagio}{c.suprimido ? " · SUPRIMIDO" : ""}</p>
      {c.aceites.filter((a) => !a.tratado_em).map((a) => (
        <div key={a.id} className="wa-aceite" role="alert">
          <strong>🔔 O cliente aceitou a proposta.</strong> Pagamento e contrato NÃO foram confirmados: entre em contato manualmente para os próximos passos.{" "}
          <button className="btn btn-primario" disabled={tratado.isPending}
            onClick={() => tratado.mutate(a.id, { onSuccess: () => toast("ok", "Aceite marcado como tratado."), onError: (e) => toast("erro", (e as Error).message) })}>Marcar como tratado</button>
        </div>
      ))}
      {c.bloqueios.length > 0 && (
        <div className={c.bloqueios.some((b) => b.nivel === "alerta") ? "wa-bloqueio" : "wa-info"} role={c.bloqueios.some((b) => b.nivel === "alerta") ? "alert" : "status"}>
          <strong>{c.bloqueios.some((b) => b.nivel === "alerta") ? "Parada, aguardando:" : "Situação:"}</strong>
          <ul>{c.bloqueios.map((b) => <li key={b.codigo}>{b.texto}</li>)}</ul>
        </div>
      )}
      {c.motivo_escalada && <p className="aviso">Motivo: {c.motivo_escalada}</p>}
      {c.controle === "fora_escopo" && <p className="aviso">Fora do escopo automatizado: o número não está autorizado. Nenhuma resposta automática é enviada.</p>}
      {c.proposta && (
        <div className="aviso">
          Proposta ({c.proposta.status}): pacote <strong>{c.proposta.pacote}</strong> — setup {reais(c.proposta.setup_centavos)}
          {c.proposta.mensalidade_centavos ? ` + ${reais(c.proposta.mensalidade_centavos)}/mês` : ""}
          {c.proposta.itens.length ? ` · extras: ${c.proposta.itens.map((i) => i.nome).join(", ")}` : ""}
          {c.proposta.status === "aceita" && <><br /><strong>Aceite registrado.</strong> Pagamento e contrato NÃO são confirmados automaticamente.</>}
        </div>
      )}
      {c.demandas.map((d) => <p key={d.id} className="aviso">Necessidade fora do catálogo: “{d.descricao}”</p>)}
      <div className="wa-botoes">
        <button className="btn" onClick={() => acao("assumir")} disabled={c.controle === "humano"}>Assumir atendimento</button>
        <button className="btn" onClick={() => acao("pausar")} disabled={c.controle === "pausada"}>Pausar IA</button>
        <button className="btn" onClick={() => acao("retomar-ia")} disabled={(c.controle === "automatizada" && !semTarefa) || !c.autorizacao}
          title={c.autorizacao ? "Retoma a IA e recria a tarefa que estiver faltando" : "Sem autorização ativa"}>{semTarefa ? "Retomar IA (recriar tarefa)" : "Retomar IA"}</button>
      </div>
      {c.sugestoes.map((sg) => <CartaoSugestao key={sg.id} sugestao={sg} telefone={c.telefone} />)}
      <div className="wa-msgs">
        {c.mensagens.filter((m) => m.estado !== "sugerida").map((m) => (
          <div key={m.id} className={`wa-msg wa-${m.autoria}`}>
            <span className="muted">{m.autoria === "cliente" ? "Cliente" : m.autoria === "ia" ? "IA" : "Operador"} · {formatarDataHora(m.em)}
              {m.direcao === "saida" ? ` · ${ROTULO_ESTADO[m.estado] ?? m.estado}` : ""}{m.origem !== "tempo_real" && m.origem !== "sistema" ? ` · ${m.origem}` : ""}</span>
            <div>{m.texto ?? `[${m.tipo}]`}</div>
          </div>
        ))}
      </div>
      {modo === "manual" ? (
        <form onSubmit={(e) => { e.preventDefault(); if (!texto.trim()) return;
          registrar.mutate({ id: c.id, texto }, { onSuccess: () => { setTexto(""); toast("ok", "Registrado no histórico (nada foi enviado pelo sistema)."); }, onError: (er) => toast("erro", (er as Error).message) }); }}>
          <textarea value={texto} onChange={(e) => setTexto(e.target.value)} rows={2}
            placeholder="Escreveu e enviou algo por conta própria pelo WhatsApp? Cole aqui para registrar no histórico. O sistema NÃO envia nada." />
          <button className="btn" disabled={!texto.trim() || registrar.isPending}>Registrar mensagem enviada</button>
        </form>
      ) : (
      <form onSubmit={(e) => { e.preventDefault(); if (!texto.trim()) return;
        enviar.mutate({ id: c.id, texto }, { onSuccess: () => setTexto(""), onError: (er) => toast("erro", (er as Error).message) }); }}>
        <textarea value={texto} onChange={(e) => setTexto(e.target.value)} placeholder="Enviar mensagem manual (assume o atendimento)" rows={2} disabled={!c.autorizacao || c.suprimido} />
        <button className="btn btn-primario" disabled={!texto.trim() || enviar.isPending || !c.autorizacao || c.suprimido}>Enviar</button>
        {!c.autorizacao && <span className="muted"> Autorize o número no lead para enviar.</span>}
      </form>
      )}
    </div>
  );
}

const ROTULO_ESTADO: Record<string, string> = {
  enviada_manual: "enviada por você", obsoleta: "sugestão desatualizada", descartada: "sugestão descartada",
};

/** Modo copiloto: a IA SUGERE; o operador envia pelo WhatsApp e confirma aqui. Nada é enviado pelo sistema. */
function CartaoSugestao({ sugestao, telefone }: { sugestao: { id: number; texto: string; primeiro_contato: boolean }; telefone: string | null }) {
  const confirmar = useWaConfirmarEnvio();
  const descartar = useWaDescartarSugestao();
  const toast = useToast();
  const [editando, setEditando] = useState(false);
  const [versao, setVersao] = useState(sugestao.texto);
  const digitos = (telefone ?? "").replace(/\D/g, "");
  const falha = (e: unknown) => toast("erro", (e as Error).message);
  const copiar = async () => {
    try { await navigator.clipboard.writeText(editando ? versao : sugestao.texto); toast("ok", "Texto copiado."); }
    catch { toast("aviso", "Não consegui copiar automaticamente: selecione o texto e copie."); }
  };
  return (
    <div className="wa-sugestao" role="group" aria-label="Resposta sugerida">
      <strong>Resposta sugerida — aguardando envio manual</strong>{sugestao.primeiro_contato && <span className="tag-origem"> primeiro contato</span>}
      {editando
        ? <textarea className="wa-sugestao-edit" rows={5} value={versao} onChange={(e) => setVersao(e.target.value)} aria-label="Texto que você enviou" />
        : <pre className="wa-sugestao-texto">{sugestao.texto}</pre>}
      <div className="wa-botoes">
        <button className="btn" onClick={copiar}>Copiar</button>
        {digitos && (
          <a className="btn" href={`https://wa.me/${digitos}?text=${encodeURIComponent(editando ? versao : sugestao.texto)}`} target="_blank" rel="noopener noreferrer">Abrir no WhatsApp</a>
        )}
        {!editando ? (
          <>
            <button className="btn btn-primario" disabled={confirmar.isPending}
              onClick={() => confirmar.mutate({ id: sugestao.id }, { onSuccess: () => toast("ok", "Registrado como enviado (texto exato)."), onError: falha })}>Enviei (texto exato)</button>
            <button className="btn" onClick={() => { setVersao(sugestao.texto); setEditando(true); }}>Enviei outra versão</button>
          </>
        ) : (
          <>
            <button className="btn btn-primario" disabled={confirmar.isPending || !versao.trim()}
              onClick={() => confirmar.mutate({ id: sugestao.id, texto: versao }, { onSuccess: () => toast("ok", "Registrado o que você realmente enviou."), onError: falha })}>Confirmar a versão que enviei</button>
            <button className="btn" onClick={() => setEditando(false)}>Voltar</button>
          </>
        )}
        <button className="btn btn-perigo" disabled={descartar.isPending}
          onClick={() => descartar.mutate(sugestao.id, { onSuccess: () => toast("aviso", "Sugestão descartada."), onError: falha })}>Descartar</button>
      </div>
      <p className="muted">A IA só considera que isto foi dito depois que você confirmar “Enviei”. Se o cliente escrever antes, a sugestão fica desatualizada e uma nova é gerada.</p>
    </div>
  );
}

function Conexao() {
  const s = useWaStatus().data;
  const conectar = useWaConectar();
  const desconectar = useWaDesconectar();
  const qr = useWaQr(Boolean(s?.qr_disponivel));
  const toast = useToast();
  const [ciente, setCiente] = useState(false);
  if (!s) return <Carregando />;
  return (
    <div className="wa-conexao">
      <p>Estado: <strong>{s.estado}</strong> · gateway: <strong>{s.gateway_ativo ? "rodando" : "parado"}</strong></p>
      {!s.gateway_ativo && (
        <p className="aviso">O gateway não está rodando. Em outro terminal: <code>cd services/whatsapp-gateway && npm run build && npm start</code> (precisa de <code>WHATSAPP_AUTH_KEY</code> no .env).</p>
      )}
      <p className="muted">Fila: {s.fila.jobs_pendentes} tarefas · {s.fila.outbox_pendente} mensagens aguardando envio · {s.fila.eventos_nao_processados} eventos por processar.</p>
      {s.qr_disponivel && qr.data && (
        <div className="wa-qr"><QRCodeSVG value={qr.data.qr} size={240} /><p className="muted">WhatsApp → Aparelhos conectados → Conectar um aparelho. O QR expira sozinho e não é guardado em log.</p></div>
      )}
      <div className="aviso">
        <p>Conectar pareia um número de WhatsApp <strong>real</strong> (use o aparelho dedicado). Depois disso o gateway consegue enviar mensagens por ele, sempre dentro das autorizações e limites.</p>
        <label><input type="checkbox" checked={ciente} onChange={(e) => setCiente(e.target.checked)} /> Estou ciente: este é o número dedicado ao atendimento.</label>
      </div>
      <button className="btn btn-primario" disabled={!ciente || conectar.isPending || !s.gateway_ativo}
        onClick={() => conectar.mutate(undefined, { onSuccess: () => toast("ok", "Comando enviado ao gateway."), onError: (e) => toast("erro", (e as Error).message) })}>
        {s.estado === "requer_pareamento" ? "Parear novamente" : "Conectar / gerar QR"}
      </button>
      <button className="btn" disabled={desconectar.isPending} onClick={() => desconectar.mutate()}>Desconectar (mantém o pareamento)</button>
      <h3>Limites em vigor (política v{s.politica_versao})</h3>
      <pre className="wa-json">{JSON.stringify(s.limites, null, 2)}</pre>
    </div>
  );
}

function Politica({ rascunho, setRascunho, erro, setErro }: {
  rascunho: Rascunho | null; setRascunho: (r: Rascunho | null) => void; erro: string | null; setErro: (e: string | null) => void;
}) {
  const pol = useWaPolitica();
  const publicar = useWaPublicarPolitica();
  const demandas = useWaDemandas();
  const revisada = useWaDemandaRevisada();
  const toast = useToast();
  const [confirmar, setConfirmar] = useState(false);
  const [publicada, setPublicada] = useState<number | null>(null);
  const [confirmarAuto, setConfirmarAuto] = useState(false);  // hooks sempre ANTES dos returns condicionais
  if (pol.isLoading) return <Carregando />;
  if (pol.error || !pol.data) return <ErroBox erro={pol.error} />;
  const ativa = pol.data.ativa;
  const texto = rascunho?.texto ?? null;
  const setTexto = (t: string) => { setPublicada(null); setRascunho({ texto: t, base: rascunho?.base ?? ativa.versao }); };
  const editado = texto ?? JSON.stringify(ativa.config, null, 2);
  let invalido: string | null = null;
  let novo: any = null;
  try { novo = JSON.parse(editado); } catch (e) { invalido = (e as Error).message; }
  const ligando = novo && novo.vendas_ativas && !ativa.config.vendas_ativas;
  const voltandoAutomatico = Boolean(novo) && novo.modo_envio === "automatico" && ativa.config.modo_envio !== "automatico";
  return (
    <div className="wa-politica">
      <p>Política ativa: <strong>versão {ativa.versao}</strong> (criada por {ativa.criado_por} em {formatarDataHora(ativa.criado_em)}). Salvar cria uma <strong>nova versão</strong>; as anteriores ficam guardadas.</p>
      <p className="aviso">
        <strong>vendas_ativas</strong> está {ativa.config.vendas_ativas ? "true" : "false"}. Com <code>false</code> a IA <strong>não conduz conversa de venda</strong>: toda conversa autorizada
        vai direto para atendimento humano. Só ative depois de revisar os valores e fazer um teste supervisionado.
      </p>
      {publicada !== null && <p className="wa-ok" role="status">Nova versão publicada: <strong>versão {publicada}</strong> (agora ativa).</p>}
      {rascunho && (
        <p className="aviso">
          Você tem <strong>alterações não salvas</strong> (o rascunho fica guardado ao trocar de aba). Nada muda até clicar em “Salvar como nova versão”.
          {rascunho.base !== ativa.versao && <> Atenção: este rascunho foi começado sobre a versão {rascunho.base}, e a ativa agora é a {ativa.versao}.</>}{" "}
          <button className="btn btn-pequeno" onClick={() => { setRascunho(null); setConfirmar(false); }}>Descartar rascunho</button>
        </p>
      )}
      {erro && (
        <div className="wa-bloqueio" role="alert">
          <strong>Não foi possível salvar:</strong> {erro}
          <button className="btn btn-pequeno" onClick={() => setErro(null)} aria-label="Fechar aviso de erro">Fechar</button>
        </div>
      )}
      <textarea className="wa-json-edit" rows={28} value={editado} onChange={(e) => setTexto(e.target.value)} spellCheck={false} />
      {invalido && <p className="aviso">JSON inválido: {invalido}</p>}
      {voltandoAutomatico && (
        <label className="wa-bloqueio"><input type="checkbox" checked={confirmarAuto} onChange={(e) => setConfirmarAuto(e.target.checked)} /> Confirmo: <strong>ativar o envio AUTOMÁTICO</strong> faz o gateway
          enviar mensagens pelo Baileys.</label>
      )}
      {ligando && <label className="aviso"><input type="checkbox" checked={confirmar} onChange={(e) => setConfirmar(e.target.checked)} /> Confirmo que revisei os valores e fiz o teste supervisionado: <strong>ativar a conversa de venda automática</strong>.</label>}
      <button className="btn btn-primario" disabled={Boolean(invalido) || publicar.isPending || texto === null || (ligando && !confirmar) || (voltandoAutomatico && !confirmarAuto)}
        onClick={() => publicar.mutate({ config: novo, confirmar, confirmarEnvioAutomatico: confirmarAuto }, {
          onSuccess: (r) => {
            setRascunho(null); setConfirmar(false); setConfirmarAuto(false); setErro(null);
            setPublicada((r as { versao: number }).versao);
            toast("ok", "Nova versão da política publicada.");
          },
          onError: (e) => setErro((e as Error).message), // fica visível até fechar ou salvar com sucesso
        })}>Salvar como nova versão</button>
      <h3>Necessidades fora do catálogo (para você decidir novos serviços)</h3>
      {demandas.data?.length === 0 && <p className="muted">Nenhuma até agora.</p>}
      <ul>
        {demandas.data?.map((d) => (
          <li key={d.id}>{d.descricao} <span className="muted">· conversa {d.conversa_id} · {formatarDataHora(d.criado_em)}</span>
            {!d.revisada && <button className="btn btn-pequeno" onClick={() => revisada.mutate(d.id)}>Marcar como revisada</button>}</li>
        ))}
      </ul>
    </div>
  );
}
