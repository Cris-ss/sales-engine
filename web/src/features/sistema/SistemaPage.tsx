import { useEffect, useRef, useState } from "react";
import { apiRespondendo, useAcaoProcesso, useAcaoTudo, useLogsProcesso, useProcessos, type Processo } from "../../api/sistema";
import { Carregando, useToast } from "../../components/states";

/*
 * Tela SISTEMA: controla os processos do PM2 (API, worker, gateway) pelo navegador.
 * SEGURANÇA: estes botões executam comandos no sistema operacional (via API -> pm2). Só é aceitável porque o sistema é de uso local,
 * de um operador, em 127.0.0.1 e sem login. Se um dia for exposto além do localhost, esta tela PRECISA de proteção extra.
 */

const ROTULO_ESTADO: Record<string, string> = {
  rodando: "Rodando", parado: "Parado", parando: "Parando…", erro: "COM ERRO", iniciando: "Iniciando…", nao_iniciado: "Não iniciado",
};
const CLASSE_ESTADO: Record<string, string> = {
  rodando: "sis-ok", parado: "sis-parado", parando: "sis-aviso", erro: "sis-erro", iniciando: "sis-aviso", nao_iniciado: "sis-parado",
};

function duracao(seg: number | null): string {
  if (seg === null) return "—";
  const d = Math.floor(seg / 86400), h = Math.floor((seg % 86400) / 3600), m = Math.floor((seg % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}min` : m ? `${m}min ${seg % 60}s` : `${seg}s`;
}

export function SistemaPage() {
  const proc = useProcessos();
  const acao = useAcaoProcesso();
  const tudo = useAcaoTudo();
  const toast = useToast();
  const [reiniciandoApi, setReiniciandoApi] = useState(false);
  const pidAntes = useRef<number | null>(null);
  const [selecionado, setSelecionado] = useState("sales-worker");

  // Reinício da própria API: a resposta HTTP confirma ANTES de a API cair. A página espera ela cair e voltar e reconecta sozinha.
  useEffect(() => {
    if (!reiniciandoApi) return;
    let caiu = false;
    const inicio = Date.now();
    const timer = setInterval(async () => {
      const ok = await apiRespondendo();
      const decorrido = (Date.now() - inicio) / 1000;
      if (!ok) caiu = true;
      // A queda pode durar menos que o intervalo da consulta: o pid do processo mudar também prova que reiniciou.
      let trocouPid = false;
      if (ok && pidAntes.current !== null) {
        try {
          const r = await fetch("/api/v1/sistema/processos", { cache: "no-store" });
          const api = (await r.json()).processos?.find((x: Processo) => x.nome === "sales-api");
          trocouPid = Boolean(api?.pid) && api.pid !== pidAntes.current && api.estado === "rodando";
        } catch { /* ainda reiniciando */ }
      }
      if (ok && (caiu || trocouPid || decorrido > 25)) {
        clearInterval(timer);
        setReiniciandoApi(false);
        toast("ok", "API reiniciada e reconectada.");
        proc.refetch();
      } else if (decorrido > 120) {
        clearInterval(timer);
        setReiniciandoApi(false);
        toast("erro", "A API não voltou em 2 minutos. Veja os logs da API abaixo (ou rode `pm2 status` no terminal).");
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [reiniciandoApi]); // eslint-disable-line react-hooks/exhaustive-deps

  const executar = (p: Processo, verbo: "reiniciar" | "parar" | "iniciar") => {
    if (verbo === "parar" && !window.confirm(`Parar ${p.rotulo}? ${p.nome === "sales-gateway" ? "Você deixa de RECEBER mensagens do WhatsApp até iniciar de novo." : "Nenhuma tarefa da IA será processada até iniciar de novo."}`)) return;
    acao.mutate({ nome: p.nome, verbo }, {
      onSuccess: (r) => {
        if (r.reiniciando) { pidAntes.current = dados?.processos.find((x) => x.nome === "sales-api")?.pid ?? null; setReiniciandoApi(true); return; }
        toast(r.ok ? "ok" : "erro", r.ok ? `${p.rotulo}: ${verbo === "reiniciar" ? "reiniciado" : verbo === "parar" ? "parado" : "iniciado"}.` : `Falhou: ${r.saida ?? ""}`);
      },
      onError: (e) => toast("erro", (e as Error).message),
    });
  };

  const dados = proc.data;
  return (
    <section>
      <h2>Sistema</h2>
      <p className="muted">Controle dos processos (PM2) sem terminal. Atualiza sozinho a cada poucos segundos.</p>

      {reiniciandoApi && (
        <div className="aviso sis-banner" role="status">
          <strong>Reiniciando a API…</strong> ela fica fora do ar por alguns segundos e esta página reconecta sozinha. Não precisa recarregar.
        </div>
      )}
      {proc.isLoading && <Carregando />}
      {dados && !dados.pm2_disponivel && (
        <div className="wa-bloqueio" role="alert">
          <strong>PM2 indisponível.</strong> {dados.erro}
          <p className="muted">Para usar esta tela, instale (uma vez) com <code>npm install -g pm2</code> e suba tudo com <code>pm2 start ecosystem.config.cjs</code> (veja docs/pm2.md).</p>
        </div>
      )}
      {proc.error && !reiniciandoApi && !dados && <div className="wa-bloqueio" role="alert">Não foi possível falar com a API.</div>}

      {dados?.pm2_disponivel && (
        <>
          <div className="sis-grade">
            {dados.processos.map((p) => (
              <div key={p.nome} className={`sis-cartao ${CLASSE_ESTADO[p.estado] ?? ""}`} data-processo={p.nome}>
                <div className="sis-topo">
                  <strong>{p.rotulo}</strong>
                  <span className="sis-selo">{ROTULO_ESTADO[p.estado] ?? p.estado}</span>
                </div>
                <div className="muted">{p.nome}</div>
                <ul className="sis-dados">
                  <li>Rodando há: <strong>{duracao(p.uptime_seg)}</strong></li>
                  <li>Reinícios: <strong>{p.reinicios ?? "—"}</strong></li>
                  <li>Memória: <strong>{p.memoria_mb !== null ? `${p.memoria_mb} MB` : "—"}</strong> · CPU: <strong>{p.cpu_pct ?? "—"}%</strong></li>
                </ul>
                {p.estado === "erro" && <p className="sis-dica">O PM2 desistiu após várias falhas seguidas. Veja os logs, corrija e reinicie.</p>}
                <div className="wa-botoes">
                  <button className="btn btn-primario" disabled={acao.isPending || reiniciandoApi} onClick={() => executar(p, "reiniciar")}>Reiniciar</button>
                  {p.nome !== "sales-api" && p.estado !== "rodando" && (
                    <button className="btn" disabled={acao.isPending} onClick={() => executar(p, "iniciar")}>Iniciar</button>
                  )}
                  {p.nome !== "sales-api" && p.estado === "rodando" && (
                    <button className="btn btn-perigo" disabled={acao.isPending} onClick={() => executar(p, "parar")}>Parar</button>
                  )}
                  <button className="btn" onClick={() => setSelecionado(p.nome)}>Ver logs</button>
                </div>
                {p.nome === "sales-gateway" && <p className="muted">Reiniciar o gateway pode levar até ~30 s para voltar a “conectado”: é normal.</p>}
                {p.nome === "sales-api" && <p className="muted">A API só pode ser reiniciada por aqui (parar deixaria você sem esta tela).</p>}
              </div>
            ))}
          </div>

          <div className="wa-botoes">
            <button className="btn btn-perigo" disabled={tudo.isPending}
              onClick={() => { if (window.confirm("Parar o worker e o gateway? A API (esta tela) continua no ar. Você deixa de receber mensagens e a IA para de processar.")) tudo.mutate("parar", { onSuccess: () => toast("aviso", "Worker e gateway parados (a API continua no ar)."), onError: (e) => toast("erro", (e as Error).message) }); }}>
              Parar tudo (worker e gateway)
            </button>
            <button className="btn btn-primario" disabled={tudo.isPending}
              onClick={() => tudo.mutate("iniciar", { onSuccess: () => toast("ok", "Worker e gateway iniciados."), onError: (e) => toast("erro", (e as Error).message) })}>
              Iniciar tudo
            </button>
          </div>

          <Logs nome={selecionado} aoMudar={setSelecionado} processos={dados.processos} />
        </>
      )}
    </section>
  );
}

function Logs({ nome, aoMudar, processos }: { nome: string; aoMudar: (n: string) => void; processos: Processo[] }) {
  const [linhas, setLinhas] = useState(100);
  const [fluxo, setFluxo] = useState<"saida" | "erros">("saida");
  const [auto, setAuto] = useState(true);
  const logs = useLogsProcesso(nome, linhas, auto);
  const area = useRef<HTMLPreElement>(null);
  const texto = (logs.data?.[fluxo] ?? []).join("\n");
  useEffect(() => { // rola para o fim quando chegam linhas novas
    const el = area.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [texto, nome, fluxo]);
  return (
    <div className="sis-logs">
      <h3>Logs</h3>
      <div className="filtros">
        <label className="campo"><span>Processo</span>
          <select value={nome} onChange={(e) => aoMudar(e.target.value)}>{processos.map((p) => <option key={p.nome} value={p.nome}>{p.rotulo}</option>)}</select></label>
        <label className="campo"><span>Arquivo</span>
          <select value={fluxo} onChange={(e) => setFluxo(e.target.value as "saida" | "erros")}>
            <option value="saida">Saída normal</option><option value="erros">Erros (stderr)</option></select></label>
        <label className="campo"><span>Linhas</span>
          <select value={linhas} onChange={(e) => setLinhas(Number(e.target.value))}>{[50, 100, 300, 1000].map((n) => <option key={n} value={n}>{n}</option>)}</select></label>
        <label className="auto"><input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> Atualizar sozinho</label>
        <button className="btn" onClick={() => logs.refetch()}>Atualizar agora</button>
      </div>
      <pre className="sis-pre" ref={area} tabIndex={0} aria-label={`Logs de ${nome}`}>{texto || (logs.isLoading ? "Carregando…" : "(sem linhas neste arquivo ainda)")}</pre>
      <p className="muted">{logs.data?.arquivos[fluxo]}</p>
    </div>
  );
}
