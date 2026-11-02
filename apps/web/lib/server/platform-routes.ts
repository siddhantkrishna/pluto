import { HttpError, first, page, pick, requireUuid, rows, userContext, uuid } from "./db";
import { emailAddress } from "./auth";
import { Context, admin, auditAction, pageParams, result } from "./api";

export async function platformRoutes(ctx:Context,parts:string[]) {
  const {db,me,req,body}=ctx;
  if(parts[0]!=="platform" || parts.length<2) return null;
  await admin(db,me);
  const method=req.method, key=parts[1],{offset,limit,search}=pageParams(req);
  if(key==="institutions") {
    if(parts.length===2 && method==="GET") {
      const q=search.get("q")||"";
      if(q.length>160) throw new HttpError(422,"Invalid filter.");
      const params:unknown[]=[];
      let where="";
      if(q){params.push("%"+q+"%");where="WHERE name ILIKE $1";}
      return result(await page(db,"SELECT * FROM institutions "+where+" ORDER BY created_at DESC,id",params,offset,limit));
    }
    if(parts.length===3 && method==="PATCH") {
      const id=requireUuid(parts[2]);
      const status=pick(body.status,["active","suspended"] as const,"institution status");
      const row=await first(db,"UPDATE institutions SET status=$1,updated_at=now() WHERE id=$2 RETURNING *",[status,id]);
      if(!row) throw new HttpError(404,"Institution not found.");
      await auditAction(db,me,"platform.institution."+status,id);
      return result(row);
    }
  }
  if(key==="administrators") {
    if(parts.length===2 && method==="GET")
      return result(await rows(db,`SELECT u.id,u.email,u.name,u.status,u.created_at,u.updated_at
        FROM users u JOIN platform_admins p ON p.user_id=u.id ORDER BY u.email`));
    if(parts.length===2 && method==="POST") {
      const email=emailAddress(body.email);
      await db.query("SELECT pg_advisory_xact_lock(481513)");
      const target=await first(db,"SELECT id FROM users WHERE email=$1 AND status='active'",[email]);
      if(!target) throw new HttpError(404,"Active account not found.");
      await db.query("INSERT INTO platform_admins (id,user_id) VALUES ($1,$2) ON CONFLICT (user_id) DO NOTHING",[uuid(),target.id]);
      await auditAction(db,me,"platform.administrator.added",target.id);
      return result({message:"Administrator added"});
    }
    if(parts.length===3 && method==="DELETE") {
      const id=requireUuid(parts[2]);
      await db.query("SELECT pg_advisory_xact_lock(481513)");
      const count=await first(db,"SELECT count(*)::int AS n FROM platform_admins");
      if(Number(count?.n)<=1) throw new HttpError(409,"At least one platform administrator must remain.");
      await db.query("DELETE FROM platform_admins WHERE user_id=$1",[id]);
      await auditAction(db,me,"platform.administrator.removed",id);
      return result({message:"Administrator removed"});
    }
  }
  if(key==="users") {
    if(parts.length===2 && method==="GET") {
      const q=search.get("q")||"";
      if(q.length>160) throw new HttpError(422,"Invalid filter.");
      const params:unknown[]=[];
      let where="";
      if(q){params.push("%"+q+"%");where="WHERE email ILIKE $1";}
      return result(await page(db,`SELECT id,email,name,status,created_at,updated_at
        FROM users `+where+" ORDER BY created_at DESC,id",params,offset,limit));
    }
    if(parts.length===3 && method==="PATCH") {
      const id=requireUuid(parts[2]);
      const status=pick(body.status,["active","disabled"] as const,"account status");
      await db.query("SELECT pg_advisory_xact_lock(481513)");
      const existing=await first(db,"SELECT id FROM users WHERE id=$1 FOR UPDATE",[id]);
      if(!existing) throw new HttpError(404,"Account not found.");
      const isAdmin=await first(db,"SELECT id FROM platform_admins WHERE user_id=$1",[id]);
      if(isAdmin) throw new HttpError(409,"Remove platform administrator privileges first.");
      if(status==="disabled") {
        // Rows subject to own-membership RLS must be read in the target user's context.
        await userContext(db,id);
        const memberships=await rows(db,"SELECT * FROM memberships WHERE user_id=$1 ORDER BY institution_id",[id]);
        for(const membership of memberships) {
          await db.query("SELECT id FROM institutions WHERE id=$1 FOR UPDATE",[membership.institution_id]);
          await db.query("SELECT set_config('pluto.tenant',$1,true)",[membership.institution_id]);
          if(membership.role==="owner") {
            const others=await first(db,`SELECT count(*)::int AS n FROM memberships m JOIN users u ON u.id=m.user_id
              WHERE m.institution_id=$1 AND m.role='owner' AND u.status='active'`,[membership.institution_id]);
            if(Number(others?.n)<=1)
              throw new HttpError(409,"Transfer institution ownership before disabling this account.");
          }
        }
        await userContext(db,me.user.id);
        await db.query("DELETE FROM auth_sessions WHERE user_id=$1",[id]);
      }
      await db.query("UPDATE users SET status=$1,updated_at=now() WHERE id=$2",[status,id]);
      await auditAction(db,me,"platform.account."+status,id);
      return result({message:"Account status updated"});
    }
  }
  if(key==="audit" && parts.length===2 && method==="GET")
    return result(await page(db,`SELECT id,institution_id,actor_id,action,target,request_id,created_at,updated_at
      FROM audit_events WHERE institution_id IS NULL AND action LIKE 'platform.%'
      ORDER BY created_at DESC,id`,[],offset,limit));
  return null;
}
