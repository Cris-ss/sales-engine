import type { Coluna, Faixa } from "../api/types";

/** Cores dos pinos. A legenda sempre mostra o texto; a cor nunca é a única informação. */
export const COR_FAIXA: Record<Faixa, string> = {
  sem_score: "#8a93a3", // cinza: score ausente (nunca tratado como zero)
  baixo: "#d1493f",
  neutro: "#5b7fc0",
  medio: "#e0a100",
  alto: "#1b9b5a",
};

export const ROTULO_FAIXA: Record<Faixa, string> = {
  sem_score: "Sem score",
  baixo: "Baixo (< 55)",
  neutro: "Neutro (55, padrão conservador)",
  medio: "Médio (55–65)",
  alto: "Alto (≥ 65)",
};

export const COR_COLUNA: Record<Coluna, string> = {
  novo: "#6b7688",
  qualificado: "#3b6fd0",
  contatado: "#d58a00",
  ganho: "#1b9b5a",
  descartado: "#a34a4a",
};

export const ROTULO_COLUNA: Record<Coluna, string> = {
  novo: "Novo",
  qualificado: "Qualificado",
  contatado: "Contatado",
  ganho: "Ganho",
  descartado: "Descartado",
};
