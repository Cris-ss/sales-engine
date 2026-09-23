import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { ApiErro } from "../api/client";

export function Carregando({ texto = "Carregando…" }: { texto?: string }) {
  return (
    <div className="estado" role="status" aria-live="polite">
      {texto}
    </div>
  );
}

export function ErroBox({ erro, onTentar }: { erro: unknown; onTentar?: () => void }) {
  const msg = erro instanceof ApiErro ? erro.message : erro instanceof Error ? erro.message : "Erro desconhecido.";
  return (
    <div className="estado erro" role="alert">
      <strong>Algo deu errado.</strong> {msg}
      {onTentar && (
        <>
          {" "}
          <button className="btn" onClick={onTentar}>Tentar de novo</button>
        </>
      )}
    </div>
  );
}

export function Vazio({ texto, children }: { texto: string; children?: ReactNode }) {
  return (
    <div className="estado vazio">
      <p>{texto}</p>
      {children}
    </div>
  );
}

/* ---------- Toasts (feedback de ações) ---------- */
interface Toast { id: number; tipo: "ok" | "erro" | "aviso"; texto: string }
const ToastCtx = createContext<(tipo: Toast["tipo"], texto: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [itens, setItens] = useState<Toast[]>([]);
  const mostrar = useCallback((tipo: Toast["tipo"], texto: string) => {
    const id = Date.now() + Math.random();
    setItens((v) => [...v, { id, tipo, texto }]);
    setTimeout(() => setItens((v) => v.filter((t) => t.id !== id)), 6000);
  }, []);
  return (
    <ToastCtx.Provider value={mostrar}>
      {children}
      <div className="toasts" aria-live="polite">
        {itens.map((t) => (
          <div key={t.id} className={`toast toast-${t.tipo}`} role={t.tipo === "erro" ? "alert" : "status"}>
            {t.texto}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
