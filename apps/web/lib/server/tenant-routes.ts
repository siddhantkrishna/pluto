import { HttpError, first, nonEmpty, optional, page, pick, requireUuid, rows, tenantContext, uuid } from "./db";
import { emailAddress, hashToken, newToken, sendMail } from "./auth";
import { Context, auditAction, pageParams, result, tenant } from "./api";

const roles=["owner","administrator","analyst","viewer"] as const;
async function guardOwner(ctx: Context, member:Record<string,any>, nextRole?:string) {
  if (member.role!=="owner" || nextRole==="owner") return;
  const record=await first(ctx.db,`SELECT count(*)::int AS n FROM memberships m JOIN users u ON u.id=m.user_id
    WHERE m.institution_id=$1 AND m.role='owner' AND u.status='active'`,[member.institution_id]);
  if (Number(record?.n)<=1) throw new HttpError(409,"An institution must retain at least one active owner.");
}
export async function tenantRoutes(ctx: Context, parts:string[]) {
  const {db,me,req,body}=ctx;
  const method=req.method;
  const {offset,limit}=pageParams(req);
  if (parts.length===1 && parts[0]==="institutions") {
    if (method==="GET") {
      const items=await rows(db,`SELECT row_to_json(i) AS institution, m.role
        FROM institutions i JOIN memberships m ON m.institution_id=i.id
        WHERE m.user_id=$1 ORDER BY i.name`,[me.user.id]);
      return result(items);
    }
    if (method==="POST") {
      const name=nonEmpty(body.name,"institution name");
      const id=uuid();
      const record=await first(db,`INSERT INTO institutions (id,name,status,created_by)
        VALUES ($1,$2,'active',$3) RETURNING *`,[id,name,me.user.id]);
      await tenantContext(db,id);
      await db.query("INSERT INTO memberships (id,institution_id,user_id,role) VALUES ($1,$2,$3,'owner')",[uuid(),id,me.user.id]);
      await db.query("INSERT INTO institution_settings (id,institution_id,description) VALUES ($1,$2,'')",[uuid(),id]);
      await auditAction(db,me,"institution.created",id,id);
      return result(record,201);
    }
  }
  if (parts[0]==="institutions" && parts.length===3 && parts[2]==="settings") {
    const id=requireUuid(parts[1]);
    await tenant(db,me,id,method==="GET"?"read":"settings");
    if (method==="GET") {
      const record=await first(db,`SELECT i.name,s.description FROM institutions i
        JOIN institution_settings s ON s.institution_id=i.id WHERE i.id=$1`,[id]);
      if (!record) throw new HttpError(404,"Settings not found.");
      return result(record);
    }
    if (method==="PUT") {
      const name=nonEmpty(body.name,"institution name");
      const description=optional(body.description,"description");
      await db.query("SELECT id FROM institutions WHERE id=$1 FOR UPDATE",[id]);
      await db.query("UPDATE institutions SET name=$1,updated_at=now() WHERE id=$2",[name,id]);
      await db.query("UPDATE institution_settings SET description=$1,updated_at=now() WHERE institution_id=$2",[description,id]);
      await auditAction(db,me,"settings.updated",id,id);
      return result({name,description});
    }
  }
  if (parts[0]==="memberships" && parts.length>=2 && parts.length<=3) {
    const id=requireUuid(parts[1]);
    const permission=parts.length===2 && method==="GET"?"read":"members";
    const role=await tenant(db,me,id,permission);
    if (parts.length===2 && method==="GET") {
      const items=await page(db,`SELECT m.id,m.user_id,m.role,u.name,u.email,u.status
        FROM memberships m JOIN users u ON u.id=m.user_id
        WHERE m.institution_id=$1 ORDER BY m.created_at,m.id`,[id],offset,limit);
      return result(items);
    }
    if (parts.length===3 && (method==="PATCH"||method==="DELETE")) {
      const memberId=requireUuid(parts[2]);
      await db.query("SELECT id FROM institutions WHERE id=$1 FOR UPDATE",[id]);
      const member=await first(db,"SELECT * FROM memberships WHERE id=$1 AND institution_id=$2 FOR UPDATE",[memberId,id]);
      if (!member) throw new HttpError(404,"Membership not found.");
      const nextRole=method==="PATCH"?pick(body.role,roles,"role"):undefined;
      if (role!=="owner" && (["owner","administrator"].includes(member.role) ||
        (nextRole && ["owner","administrator"].includes(nextRole))))
        throw new HttpError(403,"Only owners can manage administrators and owners.");
      await guardOwner(ctx,member,nextRole);
      if (method==="PATCH") {
        await db.query("UPDATE memberships SET role=$1,updated_at=now() WHERE id=$2",[nextRole,memberId]);
        await auditAction(db,me,"membership.role_changed",memberId,id);
        return result({message:"Role updated"});
      }
      const attached=await first(db,"SELECT id FROM datasets WHERE institution_id=$1 AND owner_id=$2 LIMIT 1",[id,member.user_id]);
      if (attached) throw new HttpError(409,"Reassign this member's datasets before removal.");
      await db.query("DELETE FROM memberships WHERE id=$1 AND institution_id=$2",[memberId,id]);
      await auditAction(db,me,"membership.removed",memberId,id);
      return result({message:"Member removed"});
    }
  }
  if (parts[0]==="invitations") {
    if (parts.length===2 && parts[1]==="accept" && method==="POST") {
      const token=nonEmpty(body.token,"invitation token",128);
      if (token.length<32) throw new HttpError(400,"Invalid or expired invitation.");
      const digest=hashToken(token);
      await db.query("SELECT set_config('pluto.invitation',$1,true)",[digest]);
      const inv=await first(db,"SELECT * FROM invitations WHERE token_hash=$1 AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at>now()",[digest]);
      if (!inv || inv.email!==me.user.email) throw new HttpError(400,"Invalid or expired invitation.");
      const institutionId=requireUuid(inv.institution_id);
      const org=await first(db,"SELECT * FROM institutions WHERE id=$1 FOR UPDATE",[institutionId]);
      if (org?.status!=="active") throw new HttpError(403,"Institution is suspended.");
      await tenantContext(db,institutionId);
      const claimed=await first(db,`UPDATE invitations SET accepted_at=now(),updated_at=now()
        WHERE id=$1 AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at>now() RETURNING id`,[inv.id]);
      if (!claimed) throw new HttpError(400,"Invalid or expired invitation.");
      const existing=await first(db,"SELECT id FROM memberships WHERE institution_id=$1 AND user_id=$2",[institutionId,me.user.id]);
      if (existing) throw new HttpError(409,"Already a member.");
      await db.query("INSERT INTO memberships (id,institution_id,user_id,role) VALUES ($1,$2,$3,$4)",[uuid(),institutionId,me.user.id,inv.role]);
      await auditAction(db,me,"invitation.accepted",inv.id,institutionId);
      return result(org);
    }
    if (parts.length>=2 && parts.length<=3) {
      const id=requireUuid(parts[1]);
      const role=await tenant(db,me,id,"members");
      if (parts.length===2 && method==="GET")
        return result(await page(db,`SELECT id,email,role,expires_at,accepted_at,revoked_at,created_at,updated_at
          FROM invitations WHERE institution_id=$1 ORDER BY created_at DESC,id`,[id],offset,limit));
      if (parts.length===2 && method==="POST") {
        const email=emailAddress(body.email);
        const inviteRole=pick(body.role,roles,"role");
        if (role!=="owner" && ["owner","administrator"].includes(inviteRole))
          throw new HttpError(403,"Only owners can invite administrators and owners.");
        await db.query("SELECT id FROM institutions WHERE id=$1 FOR UPDATE",[id]);
        const existing=await first(db,`SELECT m.id FROM memberships m JOIN users u ON m.user_id=u.id
          WHERE m.institution_id=$1 AND u.email=$2`,[id,email]);
        if (existing) throw new HttpError(409,"This account is already a member.");
        const token=newToken(), invId=uuid();
        await db.query(`UPDATE invitations SET revoked_at=now(),updated_at=now()
          WHERE institution_id=$1 AND email=$2 AND accepted_at IS NULL AND revoked_at IS NULL`,[id,email]);
        const record=await first(db,`INSERT INTO invitations (id,institution_id,email,role,token_hash,expires_at,invited_by)
          VALUES ($1,$2,$3,$4,$5,now()+interval '7 days',$6) RETURNING
          id,email,role,expires_at,accepted_at,revoked_at,created_at,updated_at`,
          [invId,id,email,inviteRole,hashToken(token),me.user.id]);
        await sendMail(email,"invitation",token);
        await auditAction(db,me,"invitation.created",invId,id);
        return result(record,201);
      }
      if (parts.length===3 && method==="DELETE") {
        const inviteId=requireUuid(parts[2]);
        const inv=await first(db,"SELECT * FROM invitations WHERE id=$1 AND institution_id=$2 FOR UPDATE",[inviteId,id]);
        if (!inv) throw new HttpError(404,"Invitation not found.");
        if (role!=="owner" && ["owner","administrator"].includes(inv.role))
          throw new HttpError(403,"Only owners can revoke this invitation.");
        await db.query("UPDATE invitations SET revoked_at=now(),updated_at=now() WHERE id=$1",[inviteId]);
        await auditAction(db,me,"invitation.revoked",inviteId,id);
        return result({message:"Invitation revoked"});
      }
    }
  }
  if (parts[0]==="audit" && parts.length===2 && method==="GET") {
    const id=requireUuid(parts[1]);
    await tenant(db,me,id,"audit");
    return result(await page(db,`SELECT id,institution_id,actor_id,action,target,request_id,created_at,updated_at
      FROM audit_events WHERE institution_id=$1 ORDER BY created_at DESC,id`,[id],offset,limit));
  }
  return null;
}
