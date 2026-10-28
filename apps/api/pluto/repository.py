from fastapi import HTTPException
from sqlalchemy import func, select


def scoped(db, model, institution_id, record_id):
    value = db.scalar(
        select(model).where(model.institution_id == institution_id, model.id == record_id)
    )
    if value is None:
        raise HTTPException(404, "Record not found")
    return value


def page(db, query, offset, limit):
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    return {
        "items": db.scalars(query.offset(offset).limit(limit)).all(),
        "total": total,
        "offset": offset,
        "limit": limit,
    }
