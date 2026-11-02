import { HttpError, first, nonEmpty, optional, page, pick, requireUuid, uuid } from "./db";
import { Context, auditAction, pageParams, result, tenant } from "./api";
const categories=["google_drive","database","api","file_storage","local_file"] as const;
const statuses=["draft","registered","archived"] as const;
const classes=["public","internal","confidential","restricted"] as const;
function reference(value:unknown,label:string) {
  const text=optional(value,label,500);
  if (/[?@#]/.test(text)) throw new HttpError(422,"Do not enter credentials or query parameters in metadata.");
  return text;
}
function count(value:unknown,label:string) {
  if (value===null || value===undefined || value==="") return null;
  if (typeof value!=="number" || !Number.isSafeInteger(value) || value<0)
    throw new HttpError(422,"Invalid "+label+".");
  return value;
}
function sourceBody(body:Record<string,unknown>) {
  return {
    name:nonEmpty(body.name,"source name"),
    category:pick(body.category,categories,"source category"),
    description:optional(body.description,"description"),
    reference:reference(body.reference,"reference"),
  };
}
function datasetBody(body:Record<string,unknown>) {
  const tags=body.tags===undefined?[]:body.tags;
  if (!Array.isArray(tags)||tags.length>30||
    tags.some(t=>typeof t!=="string"||t.trim().length<1||t.trim().length>40))
    throw new HttpError(422,"Invalid tags.");
  return {
    name:nonEmpty(body.name,"dataset name"),
    description:optional(body.description,"description"),
    source_category:pick(body.source_category,categories,"source category"),
    file_type:optional(body.file_type,"file type",80),
    classification:pick(body.classification??"internal",classes,"classification"),
    status:pick(body.status??"draft",statuses,"status"),
    tags:tags.map(t=>(t as string).trim()),
    record_count:count(body.record_count,"record count"),
    storage_bytes:count(body.storage_bytes,"storage bytes"),
    source_reference:reference(body.source_reference,"source reference"),
    owner_id:requireUuid(typeof body.owner_id==="string"?body.owner_id:undefined),
    source_id:body.source_id?requireUuid(typeof body.source_id==="string"?body.source_id:undefined):null,
  };
}
async function validateOwner(ctx:Context,id:string,body:ReturnType<typeof datasetBody>) {
  const owner=await first(ctx.db,`SELECT m.id FROM memberships m JOIN users u ON u.id=m.user_id
    WHERE m.institution_id=$1 AND m.user_id=$2 AND u.status='active'`,[id,body.owner_id]);
  if (!owner) throw new HttpError(422,"Owner must be an active institution member.");
  if (body.source_id) {
    const source=await first(ctx.db,"SELECT category FROM data_sources WHERE institution_id=$1 AND id=$2",[id,body.source_id]);
    if (!source) throw new HttpError(404,"Source not found.");
    if (source.category!==body.source_category)
      throw new HttpError(422,"Source category must match the associated source.");
  }
}
export async function catalogRoutes(ctx:Context,parts:string[]) {
  const {db,me,req,body}=ctx;
  const method=req.method;
  if (!["catalog","data-sources"].includes(parts[0]) || parts.length<2 || parts.length>3) return null;
  const id=requireUuid(parts[1]);
  await tenant(db,me,id,method==="GET"?"read":"catalog");
  const {offset,limit,search}=pageParams(req);
  if (parts[0]==="catalog") {
    if (parts.length===2 && method==="GET") {
      const params:unknown[]=[id];
      let where="WHERE institution_id=$1";
      const q=search.get("q")||"",status=search.get("status")||"",
        classification=search.get("classification")||"",tag=search.get("tag")||"";
      if(q.length>160||status.length>30||classification.length>30||tag.length>40)
        throw new HttpError(422,"Invalid search filter.");
      if(q) { params.push("%"+q.replace(/[!%_]/g, v=>"!"+v)+"%");where+=" AND (name ILIKE $"+params.length+" ESCAPE '!' OR description ILIKE $"+params.length+" ESCAPE '!')"; }
      if(status){params.push(status);where+=" AND status=$"+params.length;}
      if(classification){params.push(classification);where+=" AND classification=$"+params.length;}
      if(tag){params.push(JSON.stringify([tag]));where+=" AND tags @> $"+params.length+"::jsonb";}
      return result(await page(db,"SELECT * FROM datasets "+where+" ORDER BY updated_at DESC,id",params,offset,limit));
    }
    if(parts.length===3 && method==="GET") {
      const row=await first(db,"SELECT * FROM datasets WHERE institution_id=$1 AND id=$2",[id,requireUuid(parts[2])]);
      if(!row) throw new HttpError(404,"Dataset not found.");
      return result(row);
    }
    if(method==="POST"||method==="PUT") {
      const d=datasetBody(body);
      await db.query("SELECT id FROM institutions WHERE id=$1 FOR UPDATE",[id]);
      await validateOwner(ctx,id,d);
      if(method==="POST" && parts.length===2) {
        const recordId=uuid();
        const row=await first(db,`INSERT INTO datasets (id,institution_id,name,description,source_category,
          file_type,classification,status,tags,record_count,storage_bytes,source_reference,owner_id,source_id)
          VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11,$12,$13,$14) RETURNING *`,
          [recordId,id,d.name,d.description,d.source_category,d.file_type,d.classification,d.status,
          JSON.stringify(d.tags),d.record_count,d.storage_bytes,d.source_reference,d.owner_id,d.source_id]);
        await auditAction(db,me,"dataset.created",recordId,id);
        return result(row,201);
      }
      if(method==="PUT"&&parts.length===3) {
        const recordId=requireUuid(parts[2]);
        const row=await first(db,`UPDATE datasets SET name=$1,description=$2,source_category=$3,
          file_type=$4,classification=$5,status=$6,tags=$7::jsonb,record_count=$8,
          storage_bytes=$9,source_reference=$10,owner_id=$11,source_id=$12,updated_at=now()
          WHERE institution_id=$13 AND id=$14 RETURNING *`,
          [d.name,d.description,d.source_category,d.file_type,d.classification,d.status,
          JSON.stringify(d.tags),d.record_count,d.storage_bytes,d.source_reference,d.owner_id,d.source_id,id,recordId]);
        if(!row) throw new HttpError(404,"Dataset not found.");
        await auditAction(db,me,"dataset.updated",recordId,id);
        return result(row);
      }
    }
    if(method==="DELETE"&&parts.length===3) {
      const recordId=requireUuid(parts[2]);
      const existing=await first(db,"SELECT id FROM datasets WHERE id=$1 AND institution_id=$2",[recordId,id]);
      if(!existing) throw new HttpError(404,"Dataset not found.");
      await db.query("DELETE FROM ingest_files WHERE institution_id=$1 AND dataset_id=$2",[id,recordId]);
      await db.query("DELETE FROM datasets WHERE institution_id=$1 AND id=$2",[id,recordId]);
      await auditAction(db,me,"dataset.deleted",recordId,id);
      return result({message:"Dataset metadata deleted"});
    }
  }
  if(parts[0]==="data-sources") {
    if(parts.length===2 && method==="GET") {
      const q=search.get("q")||"";
      if(q.length>160) throw new HttpError(422,"Invalid search query.");
      const params:unknown[]=[id];
      let where="WHERE institution_id=$1";
      if(q) {params.push("%"+q.replace(/[!%_]/g,v=>"!"+v)+"%");where+=" AND name ILIKE $2 ESCAPE '!'";}
      return result(await page(db,"SELECT * FROM data_sources "+where+" ORDER BY created_at DESC,id",params,offset,limit));
    }
    if(parts.length===2 && method==="POST") {
      const d=sourceBody(body), recordId=uuid();
      await db.query("SELECT id FROM institutions WHERE id=$1 FOR UPDATE",[id]);
      const row=await first(db,`INSERT INTO data_sources
        (id,institution_id,name,category,description,reference,status,created_by)
        VALUES ($1,$2,$3,$4,$5,$6,'not_configured',$7) RETURNING *`,
        [recordId,id,d.name,d.category,d.description,d.reference,me.user.id]);
      await auditAction(db,me,"source.created",recordId,id);
      return result(row,201);
    }
    if(parts.length===3 && (method==="PUT"||method==="DELETE")) {
      const recordId=requireUuid(parts[2]);
      await db.query("SELECT id FROM institutions WHERE id=$1 FOR UPDATE",[id]);
      const existing=await first(db,"SELECT * FROM data_sources WHERE institution_id=$1 AND id=$2 FOR UPDATE",[id,recordId]);
      if(!existing) throw new HttpError(404,"Source not found.");
      const used=await first(db,"SELECT id FROM datasets WHERE institution_id=$1 AND source_id=$2 LIMIT 1",[id,recordId]);
      if(method==="DELETE") {
        if(used) throw new HttpError(409,"Remove dataset associations before deleting this source.");
        await db.query("DELETE FROM data_sources WHERE institution_id=$1 AND id=$2",[id,recordId]);
        await auditAction(db,me,"source.deleted",recordId,id);
        return result({message:"Source definition deleted"});
      }
      const d=sourceBody(body);
      if(used && d.category!==existing.category)
        throw new HttpError(409,"Remove dataset associations before changing category.");
      const row=await first(db,`UPDATE data_sources SET name=$1,category=$2,description=$3,
        reference=$4,updated_at=now() WHERE institution_id=$5 AND id=$6 RETURNING *`,
        [d.name,d.category,d.description,d.reference,id,recordId]);
      await auditAction(db,me,"source.updated",recordId,id);
      return result(row);
    }
  }
  return null;
}
