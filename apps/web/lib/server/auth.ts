import { cookies } from "next/headers";
import { createHash, randomBytes, scrypt as scryptCb, timingSafeEqual } from "node:crypto";
import { promisify } from "node:util";
import { DB, HttpError, audit, first, nonEmpty, rows, transaction, userContext, uuid } from "./db";

const scrypt = promisify(scryptCb);
const sessionHours = Math.min(168, Math.max(1, Number(process.env.SESSION_HOURS || 12)));
export const hashToken = (s: string) => createHash("sha256").update(s).digest("hex");
export const newToken = () => randomBytes(32).toString("base64url");
export function emailAddress(email: unknown): string {
  const result = nonEmpty(email, "email", 320).toLowerCase();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(result))
    throw new HttpError(422, "Invalid email address.");
  return result;
}
export async function hashPassword(password: string): Promise<string> {
  if (password.length < 12 || password.length > 128)
    throw new HttpError(422, "Password must contain 12 to 128 characters.");
  const salt = randomBytes(16);
  const hash = (await scrypt(password, salt, 64)) as Buffer;
  return "scrypt-v1$" + salt.toString("hex") + "$" + hash.toString("hex");
}
export async function checkPassword(encoded: string, password: string): Promise<boolean> {
  const parts = encoded.split("$");
  if (parts.length !== 3 || parts[0] !== "scrypt-v1") return false;
  if (!/^[0-9a-f]{32}$/.test(parts[1]) || !/^[0-9a-f]{128}$/.test(parts[2])) return false;
  const expected = Buffer.from(parts[2], "hex");
  const found = (await scrypt(password, Buffer.from(parts[1], "hex"), 64)) as Buffer;
  return timingSafeEqual(expected, found);
}
export type Identity = {
  user: { id: string; name: string; email: string; status: string; created_at: string; updated_at: string };
  csrf: string;
  sessionId: string;
  platform_admin: boolean;
};
export async function identity(db: DB, token?: string): Promise<Identity> {
  if (!token) throw new HttpError(401, "Authentication required");
  const row = await first(db, `SELECT u.id,u.name,u.email,u.status,u.created_at,u.updated_at,
      s.csrf, s.id AS session_id,
      EXISTS (SELECT 1 FROM platform_admins p WHERE p.user_id=u.id) AS platform_admin
    FROM auth_sessions s JOIN users u ON u.id=s.user_id
    WHERE s.token_hash=$1 AND s.expires_at>now() AND u.status='active'`, [hashToken(token)]);
  if (!row) throw new HttpError(401, "Authentication required");
  await userContext(db, row.id);
  return {
    user: { id: row.id, name: row.name, email: row.email, status: row.status,
      created_at: row.created_at, updated_at: row.updated_at },
    csrf: row.csrf,
    sessionId: row.session_id,
    platform_admin: row.platform_admin === true,
  };
}
export async function currentIdentity(): Promise<Identity> {
  const token = (await cookies()).get("pluto_session")?.value;
  return transaction(db => identity(db, token));
}
export async function login(db: DB, body: Record<string, unknown>) {
  const email = emailAddress(body.email);
  const password = typeof body.password === "string" ? body.password : "";
  if (!password || password.length > 128) throw new HttpError(401, "Invalid email or password");
  const row = await first(db, "SELECT id,name,email,status,password_hash,created_at,updated_at FROM users WHERE email=$1 FOR UPDATE", [email]);
  const valid = row ? await checkPassword(row.password_hash, password) : false;
  if (!valid || row?.status !== "active") throw new HttpError(401, "Invalid email or password");
  const token = newToken();
  const csrf = newToken();
  await db.query("INSERT INTO auth_sessions (id,user_id,token_hash,csrf,expires_at) VALUES ($1,$2,$3,$4,now()+($5::int * interval '1 hour'))",
    [uuid(), row.id, hashToken(token), csrf, sessionHours]);
  await audit(db, row.id, "session.created", row.id);
  const admin = await first(db, "SELECT id FROM platform_admins WHERE user_id=$1 LIMIT 1", [row.id]);
  const { password_hash: _unused, ...user } = row;
  return { token, me: { user, csrf, platform_admin: Boolean(admin) } };
}
export function sessionCookie() {
  return { httpOnly: true, secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const, path: "/", maxAge: sessionHours * 3600 };
}
export async function register(db: DB, body: Record<string, unknown>) {
  const email = emailAddress(body.email);
  const name = nonEmpty(body.name, "full name", 120);
  const password = typeof body.password === "string" ? body.password : "";
  const passwordHash = await hashPassword(password);
  const id = uuid();
  const inserted = await rows(db,
    "INSERT INTO users (id,email,name,password_hash,status) VALUES ($1,$2,$3,$4,'active') ON CONFLICT (email) DO NOTHING RETURNING id",
    [id, email, name, passwordHash]);
  if (inserted.length) await audit(db, id, "account.registered", id);
  return { message: "If this address is available, your account is ready. Sign in or recover your password." };
}
export async function rateLimit(db: DB, key: string, limit: number) {
  const hashed = hashToken(key);
  const result = await first(db, `INSERT INTO rate_limits (key,"window",count) VALUES ($1,now(),1)
    ON CONFLICT (key) DO UPDATE SET count=CASE WHEN rate_limits."window" < now()-interval '15 minutes'
    THEN 1 ELSE rate_limits.count+1 END,
    "window"=CASE WHEN rate_limits."window" < now()-interval '15 minutes' THEN now() ELSE rate_limits."window" END
    RETURNING count`, [hashed]);
  if (Number(result?.count) > limit) throw new HttpError(429, "Too many attempts. Try again later.");
}
export async function sendMail(email: string, kind: "recovery" | "invitation", token: string) {
  const key = process.env.RESEND_API_KEY;
  const from = process.env.MAIL_FROM;
  if (!key || !from) throw new HttpError(503, "Email delivery has not been configured.");
  const route = kind === "recovery" ? "reset-password" : "accept-invitation";
  const origin = process.env.WEB_ORIGIN || "https://pluto.vogon.in";
  const link = origin + "/" + route + "#token=" + encodeURIComponent(token);
  const response = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: "Bearer " + key, "Content-Type": "application/json" },
    body: JSON.stringify({
      from, to: [email], subject: "PLUTO — " + kind,
      text: "Open this single-use link in PLUTO:\n" + link + "\nIf you did not expect this email, ignore it.",
    }),
  });
  if (!response.ok) throw new HttpError(503, "Email delivery failed. Please retry.");
}
