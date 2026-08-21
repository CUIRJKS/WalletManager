from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


KEY_SIZE = 32
NONCE_SIZE = 12
SALT_SIZE = 16


class DecryptionError(ValueError):
    pass


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("utf-8")


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode("utf-8"))


def _derive_key(passphrase: str, pepper: str, salt: bytes) -> bytes:
    if not passphrase:
        raise ValueError("A passphrase is required.")

    material = f"{pepper}:{passphrase}".encode("utf-8")
    kdf = Scrypt(salt=salt, length=KEY_SIZE, n=2**14, r=8, p=1)
    return kdf.derive(material)


def encrypt_private_key(
    private_key: str,
    passphrase: str,
    wallet_address: str,
    pepper: str,
) -> dict[str, str]:
    salt = os.urandom(SALT_SIZE)
    nonce = os.urandom(NONCE_SIZE)
    key = _derive_key(passphrase=passphrase, pepper=pepper, salt=salt)

    ciphertext = AESGCM(key).encrypt(
        nonce=nonce,
        data=private_key.encode("utf-8"),
        associated_data=wallet_address.encode("utf-8"),
    )

    return {
        "ciphertext": _b64encode(ciphertext),
        "salt": _b64encode(salt),
        "nonce": _b64encode(nonce),
    }


def decrypt_private_key(
    ciphertext: str,
    passphrase: str,
    wallet_address: str,
    pepper: str,
    salt: str,
    nonce: str,
) -> str:
    derived_key = _derive_key(
        passphrase=passphrase,
        pepper=pepper,
        salt=_b64decode(salt),
    )

    try:
        plaintext = AESGCM(derived_key).decrypt(
            nonce=_b64decode(nonce),
            data=_b64decode(ciphertext),
            associated_data=wallet_address.encode("utf-8"),
        )
    except InvalidTag as exc:
        raise DecryptionError(
            "Decryption failed. Check the passphrase or stored data."
        ) from exc

    return plaintext.decode("utf-8")
