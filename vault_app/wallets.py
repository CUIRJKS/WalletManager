from __future__ import annotations

from eth_account import Account


def normalize_private_key(value: str) -> str:
    normalized = value.strip()
    if normalized.lower().startswith("0x"):
        normalized = normalized[2:]
    return normalized.lower()


def format_private_key(value: str) -> str:
    return f"0x{normalize_private_key(value)}"


def generate_bep20_wallet() -> dict[str, str]:
    account = Account.create()
    return {
        "address": account.address,
        "private_key": format_private_key(account.key.hex()),
    }


def wallet_from_private_key(private_key: str) -> dict[str, str]:
    account = Account.from_key(bytes.fromhex(normalize_private_key(private_key)))
    return {
        "address": account.address,
        "private_key": format_private_key(private_key),
    }
