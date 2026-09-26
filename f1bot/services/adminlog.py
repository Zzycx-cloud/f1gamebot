"""Admin action log — every privileged operation writes one row."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AdminLog


def log(
    db: Session,
    admin_id: int,
    action: str,
    target_user: int | None = None,
    amount: int = 0,
    detail: str = "",
    result: str = "OK",
) -> AdminLog:
    row = AdminLog(
        admin_id=int(admin_id or 0),
        action=str(action)[:32],
        target_user=target_user,
        amount=int(amount or 0),
        detail=(detail or "")[:200],
        result=str(result)[:24],
    )
    db.add(row)
    db.flush()
    return row


def recent(db: Session, limit: int = 12, offset: int = 0) -> list[AdminLog]:
    stmt = (
        select(AdminLog).order_by(AdminLog.id.desc()).offset(offset).limit(limit)
    )
    return list(db.scalars(stmt))


def count(db: Session) -> int:
    from sqlalchemy import func

    return int(db.scalar(select(func.count(AdminLog.id))) or 0)
