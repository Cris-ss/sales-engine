import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";

/** AES-256-GCM. Formato: [versão(1)] [iv(12)] [tag(16)] [cifrado]. A chave vem do ambiente, nunca do banco. */
export const FORMATO_VERSAO = 1;

export function chaveDoAmbiente(valor: string | undefined): Buffer {
  if (!valor || !/^[0-9a-fA-F]{64}$/.test(valor)) {
    throw new Error("WHATSAPP_AUTH_KEY ausente ou inválida: informe 64 caracteres hexadecimais (32 bytes).");
  }
  return Buffer.from(valor, "hex");
}

export function cifrar(chave: Buffer, texto: Buffer): Buffer {
  const iv = randomBytes(12);
  const c = createCipheriv("aes-256-gcm", chave, iv);
  const corpo = Buffer.concat([c.update(texto), c.final()]);
  return Buffer.concat([Buffer.from([FORMATO_VERSAO]), iv, c.getAuthTag(), corpo]);
}

export function decifrar(chave: Buffer, blob: Buffer): Buffer {
  if (blob[0] !== FORMATO_VERSAO) throw new Error(`Formato de sessão desconhecido: ${blob[0]}`);
  const d = createDecipheriv("aes-256-gcm", chave, blob.subarray(1, 13));
  d.setAuthTag(blob.subarray(13, 29));
  return Buffer.concat([d.update(blob.subarray(29)), d.final()]);
}
