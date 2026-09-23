import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { AutoRefreshContext } from "../api/hooks";
import { useWaStatus } from "../api/whatsapp";
import { buscaSoFiltros } from "../lib/filtros";
import { ExportButton } from "./ExportButton";

const ABAS = [
  { to: "/", rotulo: "Lista", fim: true },
  { to: "/kanban", rotulo: "Kanban" },
  { to: "/mapa", rotulo: "Mapa" },
  { to: "/metricas", rotulo: "Métricas" },
  { to: "/prospeccao", rotulo: "Procurar leads" },
  { to: "/whatsapp", rotulo: "WhatsApp" },
  { to: "/sistema", rotulo: "Sistema" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const { search } = useLocation();
  const aceites = useWaStatus().data?.aceites_pendentes ?? 0;
  useEffect(() => {
    // Aviso visível mesmo com outra aba do navegador aberta: "(2) ..." no título.
    document.title = aceites > 0 ? `(${aceites}) Sales Engine` : "Sales Engine";
  }, [aceites]);
  const [auto, setAuto] = useState<boolean>(() => localStorage.getItem("auto-refresh") === "1");
  useEffect(() => localStorage.setItem("auto-refresh", auto ? "1" : "0"), [auto]);

  return (
    <AutoRefreshContext.Provider value={auto ? 30_000 : false}>
      <div className="app">
        <header className="topo">
          <h1>Sales Engine</h1>
          <nav aria-label="Telas" className="abas">
            {ABAS.map((a) => (
              // os filtros acompanham o usuário ao trocar de tela
              <NavLink key={a.to} to={{ pathname: a.to, search: buscaSoFiltros(search) }} end={a.fim} className={({ isActive }) => (isActive ? "aba ativa" : "aba")}>
                {a.rotulo}{a.to === "/whatsapp" && aceites > 0 && <span className="badge-nav" title="Aceites aguardando você">{aceites}</span>}
              </NavLink>
            ))}
          </nav>
          <div className="topo-acoes">
            <label className="auto" title="Recarrega os dados a cada 30 s (útil enquanto o pipeline roda no terminal)">
              <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> Auto-atualizar
            </label>
            <button className="btn" onClick={() => qc.invalidateQueries()}>Atualizar</button>
            <ExportButton />
          </div>
        </header>
        <main>{children}</main>
      </div>
    </AutoRefreshContext.Provider>
  );
}
