import { useState } from "react";
import { urlExportacao } from "../api/client";
import { paramsApi, useFiltros } from "../lib/filtros";

/** Exporta TODOS os resultados do universo filtrado (não só a página visível). */
export function ExportButton() {
  const { filtros } = useFiltros();
  const [aberto, setAberto] = useState(false);
  const params = paramsApi(filtros);

  return (
    <div className="menu-wrap">
      <button className="btn" aria-haspopup="menu" aria-expanded={aberto} onClick={() => setAberto((v) => !v)}>
        Exportar ▾
      </button>
      {aberto && (
        <div className="menu" role="menu" onMouseLeave={() => setAberto(false)}>
          <p className="menu-nota">Todos os leads dos filtros atuais, não só a página.</p>
          {(["csv", "xlsx"] as const).map((f) => (
            <a key={f} role="menuitem" className="menu-item" href={urlExportacao(f, params)} download onClick={() => setAberto(false)}>
              {f === "csv" ? "CSV (Excel em português)" : "Excel (.xlsx)"}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
