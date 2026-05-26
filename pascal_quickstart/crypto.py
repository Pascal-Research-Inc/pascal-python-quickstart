from __future__ import annotations

import json
from typing import Any

from nacl.signing import SigningKey

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BASE58_INDEX = {char: index for index, char in enumerate(BASE58_ALPHABET)}


class KeyParseError(ValueError):
    pass


def b58encode(data: bytes) -> str:
    leading_zeroes = len(data) - len(data.lstrip(b"\x00"))
    value = int.from_bytes(data, "big")
    encoded = ""
    while value:
        value, remainder = divmod(value, 58)
        encoded = BASE58_ALPHABET[remainder] + encoded
    return ("1" * leading_zeroes) + encoded


def b58decode(text: str) -> bytes:
    value = 0
    for char in text:
        try:
            digit = BASE58_INDEX[char]
        except KeyError as exc:
            raise ValueError(f"Invalid base58 character: {char!r}") from exc
        value = (value * 58) + digit

    leading_zeroes = len(text) - len(text.lstrip("1"))
    decoded = value.to_bytes((value.bit_length() + 7) // 8, "big") if value else b""
    return (b"\x00" * leading_zeroes) + decoded


def parse_private_key_bytes(text: str) -> bytes:
    stripped = text.strip()
    if not stripped:
        raise KeyParseError("Private key is empty")

    if stripped.startswith("["):
        parsed: Any = json.loads(stripped)
        if not isinstance(parsed, list) or not all(isinstance(item, int) for item in parsed):
            raise KeyParseError("JSON private key must be a list of byte values")
        raw = bytes(parsed)
    elif len(stripped) == 64:
        try:
            raw = bytes.fromhex(stripped)
        except ValueError:
            raw = b58decode(stripped)
    else:
        raw = b58decode(stripped)

    if len(raw) == 32:
        return raw
    if len(raw) == 64:
        return raw[:32]
    raise KeyParseError(
        f"Expected a 32-byte Ed25519 seed or 64-byte Solana secret key, got {len(raw)} bytes"
    )


def signing_key_from_private_key(text: str) -> SigningKey:
    return SigningKey(parse_private_key_bytes(text))


def generate_keypair() -> tuple[str, str]:
    """Generate a base58 Ed25519 seed and its matching base58 public key."""
    signing_key = SigningKey.generate()
    return b58encode(bytes(signing_key)), b58encode(bytes(signing_key.verify_key))


def public_key_from_private_key(text: str) -> str:
    signing_key = signing_key_from_private_key(text)
    return b58encode(bytes(signing_key.verify_key))


def sign_message_base58(private_key: str, message: bytes) -> str:
    signing_key = signing_key_from_private_key(private_key)
    signed = signing_key.sign(message)
    return b58encode(bytes(signed.signature))
