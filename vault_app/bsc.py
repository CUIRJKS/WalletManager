from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from web3 import Web3

try:
    from web3.middleware.proof_of_authority import ExtraDataToPOAMiddleware
except ImportError:
    from web3.middleware import ExtraDataToPOAMiddleware


WEI_PER_BNB = Decimal("1000000000000000000")
ERC20_ABI_PATH = Path(__file__).resolve().parent / "contracts" / "bep20_transfer_abi.json"

with ERC20_ABI_PATH.open("r", encoding="utf-8") as abi_file:
    ERC20_ABI = json.load(abi_file)


class BSCTransferError(ValueError):
    pass


class BSCConfigurationError(BSCTransferError):
    pass


class BSCValidationError(BSCTransferError):
    pass


class BSCConnectionError(BSCTransferError):
    pass


class BSCInsufficientFundsError(BSCTransferError):
    pass


@dataclass
class BroadcastResult:
    tx_hash: str
    from_wallet_address: str
    to_wallet_address: str
    amount_decimal: Decimal
    amount_display: str
    asset_symbol: str
    chain_id: int
    gas_limit: int
    gas_price_wei: int
    token_contract: str | None = None
    token_decimals: int | None = None


def parse_asset_amount(raw_value: str, decimals: int, asset_symbol: str) -> Decimal:
    cleaned = raw_value.strip()
    if not cleaned:
        raise BSCValidationError("Amount is required.")

    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise BSCValidationError("Enter a valid BNB amount.") from exc

    if amount <= 0:
        raise BSCValidationError("Amount must be greater than zero.")

    if abs(amount.as_tuple().exponent) > decimals:
        raise BSCValidationError(
            f"{asset_symbol} amount supports at most {decimals} decimal places."
        )

    return amount.normalize()


def parse_bnb_amount(raw_value: str) -> Decimal:
    return parse_asset_amount(raw_value=raw_value, decimals=18, asset_symbol="BNB")


def validate_token_decimals(raw_value: str | int, token_symbol: str) -> int:
    try:
        decimals = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise BSCValidationError(f"{token_symbol} decimals must be a whole number.") from exc

    if decimals < 0 or decimals > 36:
        raise BSCValidationError(f"{token_symbol} decimals must be between 0 and 36.")

    return decimals


def to_units(amount_decimal: Decimal, decimals: int, asset_symbol: str) -> int:
    multiplier = Decimal(10) ** decimals
    scaled_amount = amount_decimal * multiplier
    integral = scaled_amount.to_integral_value()
    if integral != scaled_amount:
        raise BSCValidationError(
            f"{asset_symbol} amount could not be converted cleanly to base units."
        )
    return int(integral)


def format_bnb_amount(amount_wei: int) -> str:
    amount_bnb = Decimal(amount_wei) / WEI_PER_BNB
    return format(amount_bnb.normalize(), "f")


def format_asset_amount(amount_decimal: Decimal) -> str:
    return format(amount_decimal.normalize(), "f")


def make_web3(rpc_url: str) -> Web3:
    if not rpc_url:
        raise BSCConfigurationError("BSC_RPC_URL is not configured.")

    client = Web3(
        Web3.HTTPProvider(
            rpc_url,
            request_kwargs={"timeout": 20},
        )
    )

    try:
        is_connected = client.is_connected()
    except Exception as exc:
        raise BSCConnectionError("Could not connect to the configured BSC RPC endpoint.") from exc

    if not is_connected:
        raise BSCConnectionError("Could not connect to the configured BSC RPC endpoint.")

    try:
        client.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    except ValueError:
        pass

    return client


def send_native_bnb(
    *,
    rpc_url: str,
    chain_id: int,
    gas_buffer_percent: int,
    from_wallet_address: str,
    to_wallet_address: str,
    amount_bnb_raw: str,
    private_key: str,
) -> BroadcastResult:
    if chain_id <= 0:
        raise BSCConfigurationError("BSC_CHAIN_ID must be a positive integer.")

    if gas_buffer_percent < 100:
        raise BSCConfigurationError("BSC_SEND_GAS_BUFFER_PERCENT must be at least 100.")

    try:
        checksum_from = Web3.to_checksum_address(from_wallet_address)
        checksum_to = Web3.to_checksum_address(to_wallet_address)
    except ValueError as exc:
        raise BSCValidationError("Enter valid BSC `0x...` addresses for the transfer.") from exc

    if checksum_from == checksum_to:
        raise BSCValidationError("Source and destination addresses must be different.")

    amount_bnb = parse_bnb_amount(amount_bnb_raw)
    value_wei = to_units(amount_bnb, 18, "BNB")
    client = make_web3(rpc_url)

    try:
        gas_price = int(client.eth.gas_price)
        nonce = int(client.eth.get_transaction_count(checksum_from, "pending"))
        gas_estimate = int(
            client.eth.estimate_gas(
                {
                    "from": checksum_from,
                    "to": checksum_to,
                    "value": value_wei,
                }
            )
        )
        gas_limit = max(21000, (gas_estimate * gas_buffer_percent + 99) // 100)
        balance_wei = int(client.eth.get_balance(checksum_from))
    except Exception as exc:
        raise BSCTransferError("Could not prepare the BNB transfer with the RPC endpoint.") from exc

    total_cost_wei = value_wei + gas_limit * gas_price
    if balance_wei < total_cost_wei:
        needed_amount = format_bnb_amount(total_cost_wei)
        raise BSCInsufficientFundsError(
            f"Insufficient BNB balance. Need about {needed_amount} BNB including gas."
        )

    transaction = {
        "chainId": chain_id,
        "nonce": nonce,
        "from": checksum_from,
        "to": checksum_to,
        "value": value_wei,
        "gas": gas_limit,
        "gasPrice": gas_price,
    }

    try:
        signed = client.eth.account.sign_transaction(transaction, private_key=private_key)
        raw_transaction = getattr(signed, "raw_transaction", None)
        if raw_transaction is None:
            raw_transaction = signed.rawTransaction
        tx_hash = client.eth.send_raw_transaction(raw_transaction)
    except Exception as exc:
        raise BSCTransferError("The BNB transfer could not be signed or broadcast.") from exc

    return BroadcastResult(
        tx_hash=client.to_hex(tx_hash),
        from_wallet_address=checksum_from,
        to_wallet_address=checksum_to,
        amount_decimal=amount_bnb,
        amount_display=format_asset_amount(amount_bnb),
        asset_symbol="BNB",
        chain_id=chain_id,
        gas_limit=gas_limit,
        gas_price_wei=gas_price,
    )


def send_bep20_token(
    *,
    rpc_url: str,
    chain_id: int,
    gas_buffer_percent: int,
    from_wallet_address: str,
    to_wallet_address: str,
    token_contract: str,
    token_decimals: int,
    token_symbol: str,
    amount_token_raw: str,
    private_key: str,
) -> BroadcastResult:
    if chain_id <= 0:
        raise BSCConfigurationError("BSC_CHAIN_ID must be a positive integer.")

    if gas_buffer_percent < 100:
        raise BSCConfigurationError("BSC_SEND_GAS_BUFFER_PERCENT must be at least 100.")

    validated_decimals = validate_token_decimals(token_decimals, token_symbol)

    try:
        checksum_from = Web3.to_checksum_address(from_wallet_address)
        checksum_to = Web3.to_checksum_address(to_wallet_address)
        checksum_token = Web3.to_checksum_address(token_contract)
    except ValueError as exc:
        raise BSCValidationError(
            f"Enter valid BSC `0x...` addresses for the {token_symbol} transfer."
        ) from exc

    if checksum_from == checksum_to:
        raise BSCValidationError("Source and destination addresses must be different.")

    amount_decimal = parse_asset_amount(
        raw_value=amount_token_raw,
        decimals=validated_decimals,
        asset_symbol=token_symbol,
    )
    amount_units = to_units(amount_decimal, validated_decimals, token_symbol)
    client = make_web3(rpc_url)
    contract = client.eth.contract(address=checksum_token, abi=ERC20_ABI)

    try:
        gas_price = int(client.eth.gas_price)
        nonce = int(client.eth.get_transaction_count(checksum_from, "pending"))
        token_balance = int(contract.functions.balanceOf(checksum_from).call())
        gas_estimate = int(
            contract.functions.transfer(checksum_to, amount_units).estimate_gas(
                {"from": checksum_from}
            )
        )
        gas_limit = max(50000, (gas_estimate * gas_buffer_percent + 99) // 100)
        bnb_balance_wei = int(client.eth.get_balance(checksum_from))
    except Exception as exc:
        raise BSCTransferError(
            f"Could not prepare the {token_symbol} transfer with the RPC endpoint."
        ) from exc

    if token_balance < amount_units:
        raise BSCInsufficientFundsError(
            f"Insufficient {token_symbol} balance for this transfer."
        )

    total_gas_cost_wei = gas_limit * gas_price
    if bnb_balance_wei < total_gas_cost_wei:
        needed_amount = format_bnb_amount(total_gas_cost_wei)
        raise BSCInsufficientFundsError(
            f"Insufficient BNB balance for gas. Need about {needed_amount} BNB."
        )

    transaction = contract.functions.transfer(checksum_to, amount_units).build_transaction(
        {
            "chainId": chain_id,
            "from": checksum_from,
            "nonce": nonce,
            "gas": gas_limit,
            "gasPrice": gas_price,
        }
    )

    try:
        signed = client.eth.account.sign_transaction(transaction, private_key=private_key)
        raw_transaction = getattr(signed, "raw_transaction", None)
        if raw_transaction is None:
            raw_transaction = signed.rawTransaction
        tx_hash = client.eth.send_raw_transaction(raw_transaction)
    except Exception as exc:
        raise BSCTransferError(
            f"The {token_symbol} transfer could not be signed or broadcast."
        ) from exc

    return BroadcastResult(
        tx_hash=client.to_hex(tx_hash),
        from_wallet_address=checksum_from,
        to_wallet_address=checksum_to,
        amount_decimal=amount_decimal,
        amount_display=format_asset_amount(amount_decimal),
        asset_symbol=token_symbol,
        chain_id=chain_id,
        gas_limit=gas_limit,
        gas_price_wei=gas_price,
        token_contract=checksum_token,
        token_decimals=validated_decimals,
    )
