from __future__ import annotations

import re

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError

from . import db
from .bsc import (
    BSCConfigurationError,
    BSCConnectionError,
    BSCInsufficientFundsError,
    BSCTransferError,
    BSCValidationError,
    send_bep20_token,
    send_native_bnb,
    validate_token_decimals,
)
from .crypto import DecryptionError, decrypt_private_key, encrypt_private_key
from .models import TransferEntry, WalletEntry
from .secret_store import delete_secret, get_secret, mask_secret, stash_secret
from .wallets import format_private_key, generate_bep20_wallet, normalize_private_key, wallet_from_private_key


main_bp = Blueprint("main", __name__)

EVM_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
BNB_BECH32_RE = re.compile(r"^bnb1[023456789acdefghjklmnpqrstuvwxyz]{20,80}$")
PRIVATE_KEY_RE = re.compile(r"^[a-fA-F0-9]{64}$")


def is_valid_wallet_address(value: str) -> bool:
    return bool(EVM_ADDRESS_RE.fullmatch(value) or BNB_BECH32_RE.fullmatch(value))


def is_valid_private_key(value: str) -> bool:
    return bool(PRIVATE_KEY_RE.fullmatch(normalize_private_key(value)))


def get_wallets() -> list[WalletEntry]:
    return WalletEntry.query.order_by(
        WalletEntry.created_at.desc(),
        WalletEntry.id.desc(),
    ).all()


def get_send_wallets() -> list[WalletEntry]:
    return [wallet for wallet in get_wallets() if EVM_ADDRESS_RE.fullmatch(wallet.wallet_address)]


def render_home(form_data: dict[str, str] | None = None, status_code: int = 200):
    return (
        render_template(
            "index.html",
            wallets=get_wallets(),
            form_data=form_data or {},
            active_tab="vault",
        ),
        status_code,
    )


def render_send(form_data: dict[str, str] | None = None, status_code: int = 200):
    effective_form_data = dict(form_data or {})
    if not effective_form_data.get("asset_symbol"):
        effective_form_data["asset_symbol"] = "BNB"
    if not effective_form_data.get("rpc_url"):
        effective_form_data["rpc_url"] = current_app.config["BSC_RPC_URL"]
    if not effective_form_data.get("token_contract"):
        effective_form_data["token_contract"] = current_app.config["BSC_USDT_CONTRACT"]
    if not effective_form_data.get("token_decimals"):
        effective_form_data["token_decimals"] = str(current_app.config["BSC_USDT_DECIMALS"])

    transfers = TransferEntry.query.order_by(
        TransferEntry.created_at.desc(),
        TransferEntry.id.desc(),
    ).limit(20).all()
    return (
        render_template(
            "send.html",
            wallets=get_send_wallets(),
            transfers=transfers,
            form_data=effective_form_data,
            rpc_configured=bool(effective_form_data.get("rpc_url")),
            chain_id=current_app.config["BSC_CHAIN_ID"],
            active_tab="send",
        ),
        status_code,
    )


@main_bp.get("/")
def home():
    return render_home()


@main_bp.get("/send")
def send_view():
    return render_send()


@main_bp.post("/wallets/generate")
def generate_wallet():
    form_data = {
        "label": request.form.get("label", "").strip() or "Generated BSC Wallet",
        "wallet_address": request.form.get("wallet_address", "").strip(),
        "private_key_mode": "generated",
        "notes": request.form.get("notes", "").strip(),
    }
    generated_wallet = generate_bep20_wallet()
    form_data["wallet_address"] = generated_wallet["address"]
    form_data["private_key_mask"] = mask_secret(generated_wallet["private_key"]) or "*****"
    form_data["private_key_token"] = stash_secret(generated_wallet["private_key"])

    flash(
        "Generated a new BEP20-compatible wallet. Add a passphrase, then save it to the vault.",
        "success",
    )
    return render_home(form_data=form_data)


@main_bp.post("/wallets")
def create_wallet():
    private_key_mode = request.form.get("private_key_mode", "manual").strip() or "manual"
    private_key_token = request.form.get("private_key_token", "").strip()
    resolved_private_key = request.form.get("private_key", "").strip()

    if private_key_mode == "generated":
        resolved_private_key = get_secret(private_key_token) or ""

    form_data = {
        "label": request.form.get("label", "").strip(),
        "wallet_address": request.form.get("wallet_address", "").strip(),
        "private_key": resolved_private_key,
        "private_key_mode": private_key_mode,
        "private_key_token": private_key_token,
        "notes": request.form.get("notes", "").strip(),
    }
    if private_key_mode == "generated":
        form_data["private_key_mask"] = mask_secret(resolved_private_key) or "*****"

    passphrase = request.form.get("passphrase", "")
    confirm_passphrase = request.form.get("confirm_passphrase", "")

    if not form_data["label"]:
        flash("Wallet label is required.", "error")
        return render_home(form_data=form_data, status_code=422)

    if not is_valid_wallet_address(form_data["wallet_address"]):
        flash("Enter a valid BNB address. EVM 0x... and bnb1... formats are supported.", "error")
        return render_home(form_data=form_data, status_code=422)

    if not is_valid_private_key(form_data["private_key"]):
        if private_key_mode == "generated":
            flash("The generated private key expired from memory. Generate it again and retry.", "error")
        else:
            flash("Private key must be a 64-character hex value, with or without 0x.", "error")
        return render_home(form_data=form_data, status_code=422)

    canonical_private_key = format_private_key(form_data["private_key"])
    canonical_wallet_address = form_data["wallet_address"]

    if EVM_ADDRESS_RE.fullmatch(form_data["wallet_address"]):
        derived_wallet = wallet_from_private_key(canonical_private_key)
        if derived_wallet["address"].lower() != form_data["wallet_address"].lower():
            flash(
                "The BEP20/BSC address does not match the provided private key.",
                "error",
            )
            return render_home(form_data=form_data, status_code=422)
        canonical_wallet_address = derived_wallet["address"]

    if not passphrase:
        flash("A passphrase is required to encrypt the private key.", "error")
        return render_home(form_data=form_data, status_code=422)

    if passphrase != confirm_passphrase:
        flash("The passphrase confirmation does not match.", "error")
        return render_home(form_data=form_data, status_code=422)

    encrypted = encrypt_private_key(
        private_key=canonical_private_key,
        passphrase=passphrase,
        wallet_address=canonical_wallet_address,
        pepper=current_app.config["ENCRYPTION_PEPPER"],
    )

    wallet = WalletEntry(
        label=form_data["label"],
        wallet_address=canonical_wallet_address,
        encrypted_private_key=encrypted["ciphertext"],
        salt=encrypted["salt"],
        nonce=encrypted["nonce"],
        notes=form_data["notes"] or None,
    )

    db.session.add(wallet)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        if private_key_mode == "generated":
            form_data["private_key_mask"] = mask_secret(canonical_private_key) or "*****"
        flash("That wallet address is already stored.", "error")
        return render_home(form_data=form_data, status_code=409)

    if private_key_token:
        delete_secret(private_key_token)

    flash("Wallet saved. The private key is stored only in encrypted form.", "success")
    return redirect(url_for("main.home"))


@main_bp.post("/send")
def send_wallet():
    form_data = {
        "asset_symbol": request.form.get("asset_symbol", "BNB").strip().upper(),
        "rpc_url": request.form.get("rpc_url", "").strip(),
        "wallet_id": request.form.get("wallet_id", "").strip(),
        "to_wallet_address": request.form.get("to_wallet_address", "").strip(),
        "amount_value": request.form.get("amount_value", "").strip(),
        "token_contract": request.form.get("token_contract", "").strip(),
        "token_decimals": request.form.get("token_decimals", "").strip(),
    }
    passphrase = request.form.get("passphrase", "")
    effective_rpc_url = form_data["rpc_url"] or current_app.config["BSC_RPC_URL"]
    effective_token_contract = (
        form_data["token_contract"] or current_app.config["BSC_USDT_CONTRACT"]
    )
    effective_token_decimals_raw = (
        form_data["token_decimals"] or str(current_app.config["BSC_USDT_DECIMALS"])
    )

    if not effective_rpc_url:
        flash("Provide an RPC URL in the form or set BSC_RPC_URL in your environment.", "error")
        return render_send(form_data=form_data, status_code=422)

    if form_data["asset_symbol"] not in {"BNB", "USDT"}:
        flash("Choose either BNB or USDT for the transfer asset.", "error")
        return render_send(form_data=form_data, status_code=422)

    if not form_data["wallet_id"]:
        flash("Choose a source wallet.", "error")
        return render_send(form_data=form_data, status_code=422)

    try:
        wallet_id = int(form_data["wallet_id"])
    except ValueError:
        flash("Choose a valid source wallet.", "error")
        return render_send(form_data=form_data, status_code=422)

    wallet = WalletEntry.query.get(wallet_id)
    if wallet is None or not EVM_ADDRESS_RE.fullmatch(wallet.wallet_address):
        flash("The selected source wallet is not available for BSC sending.", "error")
        return render_send(form_data=form_data, status_code=404)

    if not EVM_ADDRESS_RE.fullmatch(form_data["to_wallet_address"]):
        flash("Destination address must be a BSC `0x...` address.", "error")
        return render_send(form_data=form_data, status_code=422)

    if not passphrase:
        flash("Enter the wallet passphrase so the app can sign the transfer.", "error")
        return render_send(form_data=form_data, status_code=422)

    try:
        private_key = decrypt_private_key(
            ciphertext=wallet.encrypted_private_key,
            passphrase=passphrase,
            wallet_address=wallet.wallet_address,
            pepper=current_app.config["ENCRYPTION_PEPPER"],
            salt=wallet.salt,
            nonce=wallet.nonce,
        )
    except DecryptionError as exc:
        flash(str(exc), "error")
        return render_send(form_data=form_data, status_code=422)

    try:
        if form_data["asset_symbol"] == "USDT":
            if not effective_token_contract:
                flash(
                    "Provide the USDT contract address in the form or set BSC_USDT_CONTRACT in your environment.",
                    "error",
                )
                return render_send(form_data=form_data, status_code=422)

            validated_token_decimals = validate_token_decimals(
                effective_token_decimals_raw,
                "USDT",
            )
            form_data["token_contract"] = effective_token_contract
            form_data["token_decimals"] = str(validated_token_decimals)

            result = send_bep20_token(
                rpc_url=effective_rpc_url,
                chain_id=current_app.config["BSC_CHAIN_ID"],
                gas_buffer_percent=current_app.config["BSC_SEND_GAS_BUFFER_PERCENT"],
                from_wallet_address=wallet.wallet_address,
                to_wallet_address=form_data["to_wallet_address"],
                token_contract=effective_token_contract,
                token_decimals=validated_token_decimals,
                token_symbol="USDT",
                amount_token_raw=form_data["amount_value"],
                private_key=private_key,
            )
        else:
            result = send_native_bnb(
                rpc_url=effective_rpc_url,
                chain_id=current_app.config["BSC_CHAIN_ID"],
                gas_buffer_percent=current_app.config["BSC_SEND_GAS_BUFFER_PERCENT"],
                from_wallet_address=wallet.wallet_address,
                to_wallet_address=form_data["to_wallet_address"],
                amount_bnb_raw=form_data["amount_value"],
                private_key=private_key,
            )
    except (
        BSCConfigurationError,
        BSCConnectionError,
        BSCInsufficientFundsError,
        BSCTransferError,
        BSCValidationError,
    ) as exc:
        flash(str(exc), "error")
        return render_send(form_data=form_data, status_code=422)

    transfer = TransferEntry(
        wallet_id=wallet.id,
        wallet_label=wallet.label,
        from_wallet_address=result.from_wallet_address,
        to_wallet_address=result.to_wallet_address,
        amount_bnb=result.amount_decimal,
        asset_symbol=result.asset_symbol,
        token_contract=result.token_contract,
        token_decimals=result.token_decimals,
        tx_hash=result.tx_hash,
        chain_id=result.chain_id,
        gas_limit=result.gas_limit,
        gas_price_wei=str(result.gas_price_wei),
    )
    db.session.add(transfer)
    db.session.commit()

    flash(
        f"Broadcasted {result.amount_display} {result.asset_symbol} to {result.to_wallet_address}. Tx hash: {result.tx_hash}",
        "success",
    )
    return redirect(url_for("main.send_view"))


@main_bp.route("/wallets/<int:wallet_id>/decrypt", methods=["GET", "POST"])
def decrypt_wallet_view(wallet_id: int):
    wallet = WalletEntry.query.get_or_404(wallet_id)
    decrypted_private_key_mask: str | None = None
    decrypted_private_key_token: str | None = None

    if request.method == "POST":
        passphrase = request.form.get("passphrase", "")

        if not passphrase:
            flash("Enter the encryption passphrase to decrypt this wallet.", "error")
        else:
            try:
                decrypted_private_key = decrypt_private_key(
                    ciphertext=wallet.encrypted_private_key,
                    passphrase=passphrase,
                    wallet_address=wallet.wallet_address,
                    pepper=current_app.config["ENCRYPTION_PEPPER"],
                    salt=wallet.salt,
                    nonce=wallet.nonce,
                )
                decrypted_private_key_mask = mask_secret(decrypted_private_key)
                decrypted_private_key_token = stash_secret(decrypted_private_key)
                flash("Private key decrypted and masked on screen. Use Copy for the full value.", "success")
            except DecryptionError as exc:
                flash(str(exc), "error")

    return render_template(
        "decrypt.html",
        wallet=wallet,
        decrypted_private_key_mask=decrypted_private_key_mask,
        decrypted_private_key_token=decrypted_private_key_token,
        active_tab="vault",
    )


@main_bp.post("/secrets/<token>/copy")
def copy_secret(token: str):
    secret = get_secret(token)
    if not secret:
        return jsonify({"error": "This secret is no longer available. Generate or decrypt it again."}), 410
    return jsonify({"secret": secret})


@main_bp.post("/wallets/<int:wallet_id>/delete")
def delete_wallet(wallet_id: int):
    wallet = WalletEntry.query.get_or_404(wallet_id)
    db.session.delete(wallet)
    db.session.commit()
    flash(f"Deleted wallet record for {wallet.label}.", "success")
    return redirect(url_for("main.home"))
