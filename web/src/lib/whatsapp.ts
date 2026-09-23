import { get } from "../api/client";
import type { WhatsAppLink } from "../api/types";

/**
 * Abre o wa.me numa nova aba. NÃO registra envio, NÃO move o funil, NÃO cria contato:
 * o operador é quem envia a mensagem, manualmente, no WhatsApp.
 * A aba é aberta de forma síncrona (antes do fetch) para não ser barrada pelo bloqueador de pop-up.
 */
export async function abrirWhatsapp(id: number): Promise<{ ok: boolean; motivo?: string }> {
  const aba = window.open("about:blank", "_blank");
  try {
    const r = await get<WhatsAppLink>(`/leads/${id}/whatsapp-link`);
    if (!r.link) {
      aba?.close();
      return { ok: false, motivo: r.motivo_inapto ?? "Sem telefone apto." };
    }
    if (!aba) return { ok: false, motivo: "O navegador bloqueou a nova aba. Libere pop-ups para este endereço." };
    aba.opener = null;
    aba.location.href = r.link;
    return { ok: true };
  } catch (e) {
    aba?.close();
    throw e;
  }
}

export async function copiar(texto: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(texto);
    return true;
  } catch {
    return false;
  }
}
