import { Pool } from "@neondatabase/serverless";
import { randomUUID } from "node:crypto";

// The PostgreSQL login MUST be pluto_app, never the table owner.
// All tenant-scoped statements run in a single transaction, using SET LOCAL.
type Client = Awaited<ReturnType<Pool["connect"]>>;
let sharedPool: Pool | undefined;

export class HttpError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}
export function dbPool(): Pool {
  const url = process.env.DATABASE_URL;
  if (!url) throw new HttpError(503, "PLUTO database has not been configured.");
  if (!/^postgres(ql)?:\/\//.test(url))
    throw new HttpError(503, "PLUTO requires a PostgreSQL connection string.");
  const parsed = new URL(url);
  if (decodeURIComponent(parsed.username) !== "pluto_app")
    throw new HttpError(503, "PLUTO must connect using its restricted pluto_app database role.");
  return (sharedPool ??= new Pool({
    connectionString: url,
    max: 4,
    connectionTimeoutMillis: 10000,
    idleTimeoutMillis: 15000,
  }));
}
export async function transaction<T>(fn: (db: Client) => Promise<T>): Promise<T> {
  const client = await dbPool().connect();
  try {
    await client.query("BEGIN");
    const result = await fn(client);
    await client.query("COMMIT");
    return result;
  } catch (error) {
    await client.query("ROLLBACK").catch(() => undefined);
    throw error;
  } finally {
    client.release();
  }
}
export type DB = Client;
export async function rows(db: DB, query: string, params: unknown[] = []) {
  const result = await db.query(query, params);
  return result.rows as Record<string, any>[];
}
export async function first(db: DB, query: string, params: unknown[] = []) {
  return (await rows(db, query, params))[0] as Record<string, any> | undefined;
}
export const uuid = () => randomUUID();
export function requireUuid(input?: string): string {
  if (!input || !/^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(input))
    throw new HttpError(400, "Invalid resource identifier.");
  return input;
}
export async function tenantContext(db: DB, id: string): Promise<void> {
  await db.query("SELECT set_config('pluto.tenant', $1, true)", [id]);
}
export async function userContext(db: DB, id: string): Promise<void> {
  await db.query("SELECT set_config('pluto.user', $1, true)", [id]);
}
export async function audit(db: DB, actor: string | null, action: string, target: string, institution: string | null = null) {
  await db.query("INSERT INTO audit_events (id,actor_id,institution_id,action,target,request_id) VALUES ($1,$2,$3,$4,$5,$6)",
    [uuid(), actor, institution, action, target, uuid()]);
}
export function nonEmpty(value: unknown, label: string, max = 160): string {
  if (typeof value !== "string" || !value.trim() || value.trim().length > max)
    throw new HttpError(422, "Invalid " + label + ".");
  return value.trim();
}
export function optional(value: unknown, label: string, max = 5000): string {
  if (value === undefined || value === null) return "";
  if (typeof value !== "string" || value.length > max)
    throw new HttpError(422, "Invalid " + label + ".");
  return value;
}
export function pick<T extends string>(value: unknown, allowed: readonly T[], label: string): T {
  if (typeof value !== "string" || !allowed.includes(value as T))
    throw new HttpError(422, "Invalid " + label + ".");
  return value as T;
}
export async function page(db: DB, base: string, params: unknown[], offset: number, limit: number) {
  const [count] = await rows(db, "SELECT count(*)::int AS total FROM (" + base + ") AS filtered", params);
  const items = await rows(db, base + " LIMIT $" + (params.length + 1) + " OFFSET $" + (params.length + 2), [...params, limit, offset]);
  return { items, total: Number(count.total), offset, limit };
}
