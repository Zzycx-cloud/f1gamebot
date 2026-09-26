"""Wallet: the only place allowed to touch a player's cash or gold.

Every movement writes a :class:`Transaction` row, and a balance can never go
below zero — the guard lives here so no handler can forget it.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Purchase, Transaction, User

CASH = "cash"
GOLD = "gold"


class NotEnoughFunds(ValueError):
    """Raised when a payment would push a wallet below zero."""


def _record(
    db: Session,
    user: User,
    currency: str,
    amount: int,
    reason: str,
    note: str = "",
    admin_id: int | None = None,
) -> Transaction:
    balance = user.balance if currency == CASH else user.gold
    txn = Transaction(
        user_id=user.id,
        currency=currency,
        amount=amount,
        balance_after=balance,
        reason=reason[:48],
        note=(note or "")[:160],
        admin_id=admin_id,
    )
    db.add(txn)
    db.flush()  # autoflush is off: the ledger must be readable inside the same session
    return txn


# --------------------------------------------------------------------------- #
# Cash
# --------------------------------------------------------------------------- #
def add_cash(
    db: Session,
    user: User,
    amount: int,
    reason: str,
    note: str = "",
    admin_id: int | None = None,
) -> int:
    """Credit cash. ``amount`` must be positive; returns the new balance."""
    amount = int(amount)
    if amount <= 0:
        raise ValueError("Amount must be a positive number.")
    user.balance = int(user.balance) + amount
    user.total_earnings = int(user.total_earnings) + amount
    db.flush()
    _record(db, user, CASH, amount, reason, note, admin_id)
    return user.balance


def spend_cash(
    db: Session,
    user: User,
    amount: int,
    reason: str,
    note: str = "",
    admin_id: int | None = None,
) -> int:
    """Debit cash, refusing to go negative. Returns the new balance."""
    amount = int(amount)
    if amount <= 0:
        raise ValueError("Amount must be a positive number.")
    if int(user.balance) < amount:
        raise NotEnoughFunds("Not enough money for this.")
    user.balance = int(user.balance) - amount
    user.total_spending = int(user.total_spending) + amount
    db.flush()
    _record(db, user, CASH, -amount, reason, note, admin_id)
    return user.balance


# --------------------------------------------------------------------------- #
# Gold
# --------------------------------------------------------------------------- #
def add_gold(
    db: Session,
    user: User,
    amount: int,
    reason: str,
    note: str = "",
    admin_id: int | None = None,
) -> int:
    amount = int(amount)
    if amount <= 0:
        raise ValueError("Amount must be a positive number.")
    user.gold = int(user.gold) + amount
    db.flush()
    _record(db, user, GOLD, amount, reason, note, admin_id)
    return user.gold


def spend_gold(
    db: Session,
    user: User,
    amount: int,
    reason: str,
    note: str = "",
    admin_id: int | None = None,
) -> int:
    amount = int(amount)
    if amount <= 0:
        raise ValueError("Amount must be a positive number.")
    if int(user.gold) < amount:
        raise NotEnoughFunds("Not enough gold for this.")
    user.gold = int(user.gold) - amount
    db.flush()
    _record(db, user, GOLD, -amount, reason, note, admin_id)
    return user.gold


# --------------------------------------------------------------------------- #
# Queries
# --------------------------------------------------------------------------- #
def history(
    db: Session, user_id: int, currency: str | None = None, limit: int = 12, offset: int = 0
) -> list[Transaction]:
    stmt = select(Transaction).where(Transaction.user_id == user_id)
    if currency:
        stmt = stmt.where(Transaction.currency == currency)
    stmt = stmt.order_by(Transaction.id.desc()).offset(offset).limit(limit)
    return list(db.scalars(stmt))


def history_count(db: Session, user_id: int, currency: str | None = None) -> int:
    stmt = select(func.count(Transaction.id)).where(Transaction.user_id == user_id)
    if currency:
        stmt = stmt.where(Transaction.currency == currency)
    return int(db.scalar(stmt) or 0)


def totals(db: Session) -> dict[str, int]:
    """Economy counters aggregated live from the transaction ledger."""

    def _sum(currency: str, positive: bool) -> int:
        stmt = select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.currency == currency
        )
        stmt = stmt.where(Transaction.amount > 0 if positive else Transaction.amount < 0)
        return int(db.scalar(stmt) or 0)

    return {
        "cash_created": _sum(CASH, True),
        "cash_spent": abs(_sum(CASH, False)),
        "gold_created": _sum(GOLD, True),
        "gold_spent": abs(_sum(GOLD, False)),
        "total_cash": int(db.scalar(select(func.coalesce(func.sum(User.balance), 0))) or 0),
        "total_gold": int(db.scalar(select(func.coalesce(func.sum(User.gold), 0))) or 0),
        "transactions": int(db.scalar(select(func.count(Transaction.id))) or 0),
        "purchases": int(db.scalar(select(func.count(Purchase.id))) or 0),
    }


def log_purchase(
    db: Session,
    user: User,
    category: str,
    item_key: str,
    item_name: str,
    price: int,
    currency: str = CASH,
) -> Purchase:
    row = Purchase(
        user_id=user.id,
        category=category,
        item_key=str(item_key)[:48],
        item_name=(item_name or "")[:80],
        price=int(price),
        currency=currency,
    )
    db.add(row)
    db.flush()
    return row
