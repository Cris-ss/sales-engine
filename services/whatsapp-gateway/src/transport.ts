/** Fronteira com o WhatsApp. O gateway só conhece esta interface: os testes usam um transporte falso. */
export class NaoEnviado extends Error {
  /** Falha com CERTEZA de que nada foi entregue ao WhatsApp (ex.: sem conexão). Só estas podem ser repetidas. */
  constructor(mensagem: string) {
    super(mensagem);
    this.name = "NaoEnviado";
  }
}

export interface Transport {
  conectado(): boolean;
  /** JID real do número (via onWhatsApp), ou null se o número não tem WhatsApp. */
  resolverJid(telefoneE164: string): Promise<string | null>;
  enviarTexto(jid: string, texto: string, messageId: string): Promise<void>;
  /** Indicador "digitando..." durante a espera. Melhor esforço: nunca lança erro. */
  digitando?(jid: string, ativo: boolean): Promise<void>;
}
