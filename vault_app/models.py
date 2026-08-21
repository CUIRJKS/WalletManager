from __future__ import annotations

from datetime import datetime, timezone

from . import db


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class WalletEntry(db.Model):
    __tablename__ = "wallet_entries"

    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(120), nullable=False)
    wallet_address = db.Column(db.String(120), unique=True, nullable=False, index=True)
    encrypted_private_key = db.Column(db.Text, nullable=False)
    salt = db.Column(db.String(64), nullable=False)
    nonce = db.Column(db.String(64), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utcnow_naive,
        onupdate=utcnow_naive,
    )


class TransferEntry(db.Model):
    __tablename__ = "transfer_entries"

    id = db.Column(db.Integer, primary_key=True)
    wallet_id = db.Column(db.Integer, nullable=False, index=True)
    wallet_label = db.Column(db.String(120), nullable=False)
    from_wallet_address = db.Column(db.String(120), nullable=False)
    to_wallet_address = db.Column(db.String(120), nullable=False)
    amount_bnb = db.Column(db.Numeric(36, 18), nullable=False)
    asset_symbol = db.Column(db.String(20), nullable=False, default="BNB")
    token_contract = db.Column(db.String(120), nullable=True)
    token_decimals = db.Column(db.Integer, nullable=True)
    tx_hash = db.Column(db.String(90), unique=True, nullable=False, index=True)
    chain_id = db.Column(db.Integer, nullable=False)
    gas_limit = db.Column(db.Integer, nullable=False)
    gas_price_wei = db.Column(db.String(40), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
