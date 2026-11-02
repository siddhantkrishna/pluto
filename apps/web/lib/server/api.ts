import { NextRequest, NextResponse } from "next/server";
import { HttpError, DB, audit, first, requireUuid, rows, transaction, uuid } from "./db";
import { Identity, checkPassword, emailAddress, hashPassword, hashToken, identity,
  login, newToken, rateLimit, register, sendMail, sessionCookie } from "./auth";
import { tenantRoutes } from "./tenant-routes";
import { catalogRoutes } from "./catalog-routes";
import { platformRoutes } from "./platform-routes";

export type Context = { db: DB; me: Identity; req: NextRequest; body: Record<string, unknown> };
export const result = (data: unknown, status=200) => NextResponse.json(data, { status, headers: { "Cache-Control": "no-store" } });
export function pageParams(req: NextRequest) {
  const u = new URL(req.url);
  const offset = Number(u.searchParams.get("offset") || 0);
  const limit = Number(u.searchParams.get("limit") || 50);
  if (!Number.isSafeInteger(offset) || offset < 0 || !Number.isSafeInteger(limit) || limit < 1 || limit > 100)
    throw new HttpError(422, "Invalid pagination.");
  return { offset, limit, search: u.searchParams };
}
export async function tenant(db: DB, me: Identity, id: string, permission="read") {
  requireUuid(id);
  await db.query("SELECT set_config('pluto.tenant', $1, true)", [id]);
  const row = await first(db, `SELECT m.role,i.name,i.status FROM memberships m
    JOIN institutions i ON i.id=m.institution_id WHERE m.user_id=$1 AND m.institution_id=$2`, [me.user.id,id]);
  if (!row) throw new HttpError(404, "Workspace not found.");
  if (row.status !== "active") throw new HttpError(403, "Institution suspended.");
  const allowed: Record<string,string[]> = {
    owner: ["read","catalog","members","owners","settings","audit"],
    administrator: ["read","catalog","members","settings","audit"],
    analyst: ["read"],
    viewer: ["read"],
  };
  if (!allowed[row.role]?.includes(permission)) throw new HttpError(403, "Permission denied.");
  return row.role as string;
}
export async function admin(db: DB, me: Identity) {
  if (!me.platform_admin) throw new HttpError(403, "Platform administrator required.");
  await db.query("SELECT set_config('pluto.platform','true',true)");
}
export async function auditAction(db: DB, me: Identity, action: string, target: string, org: string|null = null) {
  await audit(db, me.user.id, action, target, org);
}
function assertCsrf(req: NextRequest, me: Identity) {
  if (req.method === "GET" || req.method === "HEAD" || req.method === "OPTIONS") return;
  const sent = req.headers.get("X-CSRF-Token") || "";
  if (!sent || sent !== me.csrf) throw new HttpError(403, "CSRF validation failed.");
}
async function handleAuthorized({db,me,req,body}:Context, parts:string[]) {
  const method=req.method;
  const path=parts.join("/");
  if (method==="GET" && path==="auth/me") return result({user:me.user,csrf:me.csrf,platform_admin:me.platform_admin});
  if (method==="POST" && path==="auth/logout") {
    await db.query("DELETE FROM auth_sessions WHERE id=$1 AND user_id=$2",[me.sessionId,me.user.id]);
    await auditAction(db,me,"session.revoked",me.sessionId);
    const response=result({message:"Signed out"});
    response.cookies.delete("pluto_session");
    return response;
  }
  if (method==="GET" && path==="users/sessions") {
    const list=await rows(db,"SELECT id,created_at,updated_at,expires_at FROM auth_sessions WHERE user_id=$1 AND expires_at>now() ORDER BY created_at DESC",[me.user.id]);
    return result(list);
  }
  if (method==="DELETE" && parts[0]==="users" && parts[1]==="sessions" && parts.length===3) {
    const sessionId=requireUuid(parts[2]);
    await db.query("DELETE FROM auth_sessions WHERE id=$1 AND user_id=$2",[sessionId,me.user.id]);
    await auditAction(db,me,"session.revoked",sessionId);
    return result({message:"Session revoked"});
  }
  if (method==="POST" && path==="users/password") {
    if (typeof body.password!=="string" || typeof body.current_password!=="string") throw new HttpError(422,"Invalid password.");
    const old=await first(db,"SELECT password_hash FROM users WHERE id=$1 FOR UPDATE",[me.user.id]);
    if (!old || !await checkPassword(old.password_hash,body.current_password)) throw new HttpError(400,"Current password is incorrect.");
    const hashed=await hashPassword(body.password);
    await db.query("UPDATE users SET password_hash=$1,updated_at=now() WHERE id=$2",[hashed,me.user.id]);
    await db.query("UPDATE recoveries SET used_at=now() WHERE user_id=$1 AND used_at IS NULL",[me.user.id]);
    await db.query("DELETE FROM auth_sessions WHERE user_id=$1",[me.user.id]);
    await auditAction(db,me,"password.changed",me.user.id);
    const response=result({message:"Password changed. Sign in again."});
    response.cookies.delete("pluto_session");
    return response;
  }
  return (
    await tenantRoutes({db,me,req,body},parts) ??
    await catalogRoutes({db,me,req,body},parts) ??
    await platformRoutes({db,me,req,body},parts)
  );
}
async function publicRoute(db: DB, req: NextRequest, path:string, body:Record<string,unknown>) {
  if (path==="auth/register" && req.method==="POST") return result(await register(db,body),201);
  if (path==="auth/login" && req.method==="POST") {
    const data=await login(db,body);
    const response=result(data.me);
    response.cookies.set("pluto_session",data.token,sessionCookie());
    return response;
  }
  if (path==="auth/recovery" && req.method==="POST") {
    const email=emailAddress(body.email);
    const account=await first(db,"SELECT id FROM users WHERE email=$1 AND status='active' FOR UPDATE",[email]);
    if (account) {
      const token=newToken();
      await db.query("INSERT INTO recoveries (id,user_id,token_hash,expires_at) VALUES ($1,$2,$3,now()+interval '30 minutes')",[uuid(),account.id,hashToken(token)]);
      await sendMail(email,"recovery",token);
    }
    return result({message:"If the account exists, a recovery link will be delivered."});
  }
  if (path==="auth/reset-password" && req.method==="POST") {
    const token=typeof body.token==="string" ? body.token : "";
    const password=typeof body.password==="string" ? body.password : "";
    if (token.length<32||token.length>128) throw new HttpError(400,"Invalid or expired link.");
    const hash=await hashPassword(password);
    const recovery=await first(db,"SELECT r.id,r.user_id FROM recoveries r JOIN users u ON r.user_id=u.id WHERE r.token_hash=$1 AND r.used_at IS NULL AND r.expires_at>now() AND u.status='active' FOR UPDATE OF r",[hashToken(token)]);
    if (!recovery) throw new HttpError(400,"Invalid or expired link.");
    await db.query("UPDATE users SET password_hash=$1,updated_at=now() WHERE id=$2",[hash,recovery.user_id]);
    await db.query("UPDATE recoveries SET used_at=now() WHERE user_id=$1 AND used_at IS NULL",[recovery.user_id]);
    await db.query("DELETE FROM auth_sessions WHERE user_id=$1",[recovery.user_id]);
    await audit(db,recovery.user_id,"password.recovered",recovery.user_id);
    return result({message:"Password reset. Sign in with your new password."});
  }
  return null;
}
export async function handleApi(req:NextRequest, parts:string[]) {
  try {
    if (req.method!=="GET" && req.method!=="HEAD" && req.method!=="OPTIONS") {
      const origin=req.headers.get("origin");
      const expected=process.env.WEB_ORIGIN || (process.env.NODE_ENV==="production"?"https://pluto.vogon.in":"http://localhost:3000");
      if (origin!==expected) throw new HttpError(403,"Origin validation failed.");
    }
    // Reject oversized metadata requests. Binary ingestion is not supported by this API.
    const path=parts.join("/");
    if (path==="health" && req.method==="GET") {
      return transaction(async db => {
        const check=await first(db,`SELECT current_user AS role, r.rolsuper, r.rolbypassrls,
          (SELECT count(*)::int FROM pg_tables WHERE schemaname='public'
            AND tableowner=current_user) AS owned_tables
          FROM pg_roles r WHERE r.rolname=current_user`);
        if (!check || check.role!=="pluto_app" || check.rolsuper || check.rolbypassrls ||
            Number(check.owned_tables)>0)
          throw new HttpError(503,"PLUTO database application role is not safe.");
        return result({status:"ok"});
      });
    }
    let body:Record<string,unknown>={};
    if (["POST","PUT","PATCH"].includes(req.method)) {
      const len=Number(req.headers.get("content-length")||0);
      if (len>65536) throw new HttpError(413,"Request is too large.");
      const type=req.headers.get("content-type")||"";
      if (!type.toLowerCase().startsWith("application/json")) throw new HttpError(415,"JSON request required.");
      const raw=await req.text();
      if (raw.length>65536) throw new HttpError(413,"Request is too large.");
      try {
        const value=JSON.parse(raw);
        if (!value || typeof value!=="object" || Array.isArray(value)) throw new Error("Expected object");
        body=value as Record<string,unknown>;
      } catch { throw new HttpError(400,"Invalid JSON body."); }
    }
    const isPublic=["auth/register","auth/login","auth/recovery","auth/reset-password"].includes(path) && req.method==="POST";
    if (isPublic) {
      const key=(typeof body.email==="string" ? body.email.toLowerCase(): "unknown");
      await transaction(db=>rateLimit(db,path+":"+key, path==="auth/login"?10:20));
      return await transaction(db=>publicRoute(db,req,path,body)) || result({error:{message:"Not found"}},404);
    }
    const response=await transaction(async db=>{
      const me=await identity(db,req.cookies.get("pluto_session")?.value);
      assertCsrf(req,me);
      return handleAuthorized({db,me,req,body},parts);
    });
    if (response) return response;
    if (["ingestion","connectors"].includes(parts[0])) throw new HttpError(501,"Data processing and external connectors are not yet available on the Next.js backend.");
    throw new HttpError(404,"Endpoint not found.");
  } catch(error) {
    if (error instanceof HttpError)
      return NextResponse.json({error:{message:error.message}},{status:error.status,headers:{"Cache-Control":"no-store"}});
    const name=error instanceof Error ? error.name:"UnknownError";
    console.error("PLUTO API failure:",name);
    return NextResponse.json({error:{message:"Request could not be completed."}},{status:500,headers:{"Cache-Control":"no-store"}});
  }
}
