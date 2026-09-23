import pg from "pg";

export type Db = pg.Pool | pg.PoolClient;

export function criarPool(url: string): pg.Pool {
  return new pg.Pool({ connectionString: url, max: 5 });
}

export async function transacao<T>(pool: pg.Pool, fn: (c: pg.PoolClient) => Promise<T>): Promise<T> {
  const c = await pool.connect();
  try {
    await c.query("BEGIN");
    const r = await fn(c);
    await c.query("COMMIT");
    return r;
  } catch (e) {
    await c.query("ROLLBACK").catch(() => undefined);
    throw e;
  } finally {
    c.release();
  }
}

/** Mensagem de erro sem dados sensíveis (sem stack, sem conteúdo de mensagens). */
export function erroSeguro(e: unknown): string {
  const m = e instanceof Error ? `${e.name}: ${e.message}` : String(e);
  return m.replace(/\s+/g, " ").slice(0, 300);
}
