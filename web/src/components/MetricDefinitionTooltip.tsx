import { useId, useState } from "react";

/** "ⓘ" acessível: abre com foco, hover ou clique; a definição fica sempre acessível ao leitor de tela. */
export function MetricDefinitionTooltip({ texto }: { texto: string }) {
  const id = useId();
  const [aberto, setAberto] = useState(false);
  return (
    <span className="tip" onMouseEnter={() => setAberto(true)} onMouseLeave={() => setAberto(false)}>
      <button
        type="button"
        className="tip-btn"
        aria-describedby={id}
        aria-expanded={aberto}
        aria-label="Ver definição da métrica"
        onClick={() => setAberto((v) => !v)}
        onFocus={() => setAberto(true)}
        onBlur={() => setAberto(false)}
      >
        ⓘ
      </button>
      <span id={id} role="tooltip" className={`tip-box ${aberto ? "aberto" : ""}`}>
        {texto}
      </span>
    </span>
  );
}
