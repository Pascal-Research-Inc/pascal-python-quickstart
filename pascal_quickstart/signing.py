from __future__ import annotations

import json
import struct
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pascal_quickstart.crypto import b58decode, public_key_from_private_key, sign_message_base58

Side = Literal["BID", "ASK"]
TimeInForce = Literal["GTC", "GTT", "IOC"]
OrderType = Literal["LIMIT", "MARKET"]
CancelBy = Literal["client_order_id", "order_id"]

PERMIT_VERSION = 1
PLACE_ORDER_CMD_TYPE = 1
CANCEL_ORDER_CMD_TYPE = 2
CREATE_TRADING_KEY_COMMAND_TYPE = "create_trading_key"
REGISTER_DEPOSIT_ADDRESS_COMMAND_TYPE = "register_deposit_address"
OMITTED_REPLACE_CLIENT_ORDER_ID = (1 << 64) - 1
PLACE_ORDER_OFFCHAIN_FIELDS_DIGEST = bytes.fromhex(
    "dcaf53738f1d5f06164660498a75888e7f0c78ed5f1bc17be1dd1cb3ccf53ce3"
)


@dataclass(frozen=True)
class RequestAuthInputs:
    deployment_id: int
    owner_public_key: str
    signer_public_key: str
    client_ts_ms: int
    recv_window_ms: int


def now_ms() -> int:
    return int(time.time() * 1000)


def price_to_micro_dollars(price: str) -> int:
    try:
        decimal = Decimal(price)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid decimal price {price!r}") from exc

    scaled = decimal * Decimal(1_000_000)
    if scaled != scaled.to_integral_value():
        raise ValueError(f"Price must have at most 6 fractional digits: {price!r}")
    value = int(scaled)
    if value < 0 or value > 1_000_000:
        raise ValueError("Price must be between 0.000000 and 1.000000")
    return value


def fixed_symbol_bytes(symbol: str) -> bytes:
    encoded = symbol.encode("ascii")
    if len(encoded) > 32:
        raise ValueError("Pascal symbols must fit in 32 ASCII bytes")
    return encoded.ljust(32, b"\x00")


def permit_header(auth: RequestAuthInputs, *, cmd_type: int) -> bytes:
    owner = b58decode(auth.owner_public_key)
    signer = b58decode(auth.signer_public_key)
    if len(owner) != 32:
        raise ValueError("Owner public key must decode to 32 bytes")
    if len(signer) != 32:
        raise ValueError("Signer public key must decode to 32 bytes")
    if not 0 <= auth.deployment_id <= 255:
        raise ValueError("deployment_id must fit in one byte")
    if not 0 <= auth.recv_window_ms <= 60_000:
        raise ValueError("recv_window_ms must be between 0 and 60000")

    return struct.pack(
        "<BBBBIQ32s32s",
        PERMIT_VERSION,
        cmd_type,
        auth.deployment_id,
        0,
        auth.recv_window_ms,
        auth.client_ts_ms,
        owner,
        signer,
    )


def place_order_message(
    *,
    auth: RequestAuthInputs,
    client_order_id: int,
    symbol: str,
    side: Side,
    price: str,
    size: int,
    replace_client_order_id: int | None = None,
    tif: TimeInForce = "GTC",
    expires_ts_ms: int | None = None,
    post_only: bool = False,
    reduce_only: bool = False,
    order_type: OrderType = "LIMIT",
) -> bytes:
    side_value = {"BID": 0, "ASK": 1}[side]
    tif_value = {"GTC": 0, "GTT": 1, "IOC": 2}[tif]
    order_type_value = {"LIMIT": 0, "MARKET": 1}[order_type]
    replace_value = (
        replace_client_order_id
        if replace_client_order_id is not None
        else OMITTED_REPLACE_CLIENT_ORDER_ID
    )
    expires_value = expires_ts_ms if expires_ts_ms is not None else 0
    flags = (1 if post_only else 0) | (2 if reduce_only else 0)

    if tif == "GTT" and expires_ts_ms is None:
        raise ValueError("expires_ts_ms is required for GTT orders")
    if tif != "GTT" and expires_ts_ms is not None:
        raise ValueError("expires_ts_ms is only valid for GTT orders")

    body = b"".join(
        [
            struct.pack(
                "<QQQQQ",
                size,
                price_to_micro_dollars(price),
                client_order_id,
                replace_value,
                expires_value,
            ),
            b"\x00" * 32,
            fixed_symbol_bytes(symbol),
            b"\x00" * 4,
            PLACE_ORDER_OFFCHAIN_FIELDS_DIGEST,
            b"\x00",
            struct.pack("<BBBB", side_value, order_type_value, tif_value, flags),
            b"\x00" * 7,
        ]
    )
    return permit_header(auth, cmd_type=PLACE_ORDER_CMD_TYPE) + body


def cancel_order_message(
    *,
    auth: RequestAuthInputs,
    cancel_by: CancelBy,
    order_id: int,
) -> bytes:
    cancel_by_value = {"client_order_id": 0, "order_id": 1}[cancel_by]
    body = b"".join(
        [struct.pack("<BB", cancel_by_value, 0), b"\x00" * 6, struct.pack("<Q", order_id)]
    )
    return permit_header(auth, cmd_type=CANCEL_ORDER_CMD_TYPE) + body


def create_trading_key_message(
    *,
    auth: RequestAuthInputs,
    name: str,
    trading_key_public_key: str,
    expiration_ts_ms: int,
) -> bytes:
    """Return the exact UTF-8 JSON array signed by wallet-key requests."""
    if auth.owner_public_key != auth.signer_public_key:
        raise ValueError("Wallet-signed requests require signer_public_key == owner_public_key")
    if not 0 <= auth.deployment_id <= 255:
        raise ValueError("deployment_id must fit in one byte")
    if not 0 <= auth.recv_window_ms <= 60_000:
        raise ValueError("recv_window_ms must be between 0 and 60000")
    if len(b58decode(auth.owner_public_key)) != 32:
        raise ValueError("Owner public key must decode to 32 bytes")
    if len(b58decode(trading_key_public_key)) != 32:
        raise ValueError("Trading key public key must decode to 32 bytes")
    if len(name.encode("utf-8")) > 16:
        raise ValueError("Trading key name must fit in 16 UTF-8 bytes")
    if expiration_ts_ms < 0:
        raise ValueError("expiration_ts_ms must be non-negative")

    fields: list[Any] = [
        CREATE_TRADING_KEY_COMMAND_TYPE,
        name,
        trading_key_public_key,
        expiration_ts_ms,
        PERMIT_VERSION,
        auth.deployment_id,
        auth.recv_window_ms,
        auth.client_ts_ms,
        auth.owner_public_key,
        auth.signer_public_key,
    ]
    return json.dumps(fields, separators=(",", ":"), ensure_ascii=False).encode()


def register_deposit_address_message(*, auth: RequestAuthInputs) -> bytes:
    """Return the exact UTF-8 JSON array signed for deposit-address registration."""
    if auth.owner_public_key != auth.signer_public_key:
        raise ValueError("Wallet-signed requests require signer_public_key == owner_public_key")
    if not 0 <= auth.deployment_id <= 255:
        raise ValueError("deployment_id must fit in one byte")
    if not 0 <= auth.recv_window_ms <= 60_000:
        raise ValueError("recv_window_ms must be between 0 and 60000")
    if len(b58decode(auth.owner_public_key)) != 32:
        raise ValueError("Owner public key must decode to 32 bytes")

    fields: list[Any] = [
        REGISTER_DEPOSIT_ADDRESS_COMMAND_TYPE,
        auth.owner_public_key,
        PERMIT_VERSION,
        auth.deployment_id,
        auth.recv_window_ms,
        auth.client_ts_ms,
        auth.owner_public_key,
        auth.signer_public_key,
    ]
    return json.dumps(fields, separators=(",", ":"), ensure_ascii=False).encode()


def build_auth(
    *,
    deployment_id: int,
    owner_public_key: str,
    trading_private_key: str,
    client_ts_ms: int | None = None,
    recv_window_ms: int = 5000,
) -> RequestAuthInputs:
    return RequestAuthInputs(
        deployment_id=deployment_id,
        owner_public_key=owner_public_key,
        signer_public_key=public_key_from_private_key(trading_private_key),
        client_ts_ms=client_ts_ms if client_ts_ms is not None else now_ms(),
        recv_window_ms=recv_window_ms,
    )


def auth_json(auth: RequestAuthInputs, signature: str) -> dict[str, str]:
    return {
        "client_ts_ms": str(auth.client_ts_ms),
        "recv_window_ms": str(auth.recv_window_ms),
        "owner": auth.owner_public_key,
        "signer": auth.signer_public_key,
        "signature": signature,
    }


def signed_place_order_request(
    *,
    deployment_id: int,
    owner_public_key: str,
    trading_private_key: str,
    client_order_id: int,
    symbol: str,
    side: Side,
    price: str,
    size: int,
    replace_client_order_id: int | None = None,
    tif: TimeInForce = "GTC",
    expires_ts_ms: int | None = None,
    post_only: bool = False,
    reduce_only: bool = False,
    client_ts_ms: int | None = None,
    recv_window_ms: int = 5000,
) -> dict[str, Any]:
    auth = build_auth(
        deployment_id=deployment_id,
        owner_public_key=owner_public_key,
        trading_private_key=trading_private_key,
        client_ts_ms=client_ts_ms,
        recv_window_ms=recv_window_ms,
    )
    message = place_order_message(
        auth=auth,
        client_order_id=client_order_id,
        replace_client_order_id=replace_client_order_id,
        symbol=symbol,
        side=side,
        price=price,
        size=size,
        tif=tif,
        expires_ts_ms=expires_ts_ms,
        post_only=post_only,
        reduce_only=reduce_only,
    )
    request: dict[str, Any] = {
        "client_order_id": str(client_order_id),
        "symbol": symbol,
        "side": side,
        "price": price,
        "size": str(size),
    }
    if replace_client_order_id is not None:
        request["replace_client_order_id"] = str(replace_client_order_id)
    if tif != "GTC":
        request["tif"] = tif
    if post_only:
        request["post_only"] = True
    if reduce_only:
        request["reduce_only"] = True
    if expires_ts_ms is not None:
        request["expires_ts_ms"] = str(expires_ts_ms)
    request["auth"] = auth_json(auth, sign_message_base58(trading_private_key, message))
    return request


def signed_create_trading_key_request(
    *,
    deployment_id: int,
    owner_private_key: str,
    trading_key_public_key: str,
    name: str,
    expiration_ts_ms: int,
    client_ts_ms: int | None = None,
    recv_window_ms: int = 5000,
) -> dict[str, Any]:
    owner_public_key = public_key_from_private_key(owner_private_key)
    auth = RequestAuthInputs(
        deployment_id=deployment_id,
        owner_public_key=owner_public_key,
        signer_public_key=owner_public_key,
        client_ts_ms=client_ts_ms if client_ts_ms is not None else now_ms(),
        recv_window_ms=recv_window_ms,
    )
    message = create_trading_key_message(
        auth=auth,
        name=name,
        trading_key_public_key=trading_key_public_key,
        expiration_ts_ms=expiration_ts_ms,
    )
    return {
        "trading_key": trading_key_public_key,
        "name": name,
        "expiration_ts_ms": str(expiration_ts_ms),
        "auth": auth_json(auth, sign_message_base58(owner_private_key, message)),
    }


def signed_register_deposit_address_request(
    *,
    deployment_id: int,
    owner_private_key: str,
    invite_code: str | None = None,
    client_ts_ms: int | None = None,
    recv_window_ms: int = 5000,
) -> dict[str, Any]:
    owner_public_key = public_key_from_private_key(owner_private_key)
    auth = RequestAuthInputs(
        deployment_id=deployment_id,
        owner_public_key=owner_public_key,
        signer_public_key=owner_public_key,
        client_ts_ms=client_ts_ms if client_ts_ms is not None else now_ms(),
        recv_window_ms=recv_window_ms,
    )
    message = register_deposit_address_message(auth=auth)
    request: dict[str, Any] = {
        "owner": owner_public_key,
        "auth": auth_json(auth, sign_message_base58(owner_private_key, message)),
    }
    if invite_code is not None:
        request["invite_code"] = invite_code
    return request


def signed_cancel_order_request(
    *,
    deployment_id: int,
    owner_public_key: str,
    trading_private_key: str,
    client_order_id: int | None = None,
    order_id: int | None = None,
    client_ts_ms: int | None = None,
    recv_window_ms: int = 5000,
) -> dict[str, Any]:
    if (client_order_id is None) == (order_id is None):
        raise ValueError("Provide exactly one of client_order_id or order_id")

    auth = build_auth(
        deployment_id=deployment_id,
        owner_public_key=owner_public_key,
        trading_private_key=trading_private_key,
        client_ts_ms=client_ts_ms,
        recv_window_ms=recv_window_ms,
    )
    cancel_by: CancelBy
    target_id: int
    request: dict[str, Any]
    if client_order_id is not None:
        cancel_by = "client_order_id"
        target_id = client_order_id
        request = {"client_order_id": str(client_order_id)}
    else:
        cancel_by = "order_id"
        target_id = order_id if order_id is not None else 0
        request = {"order_id": str(target_id)}

    message = cancel_order_message(auth=auth, cancel_by=cancel_by, order_id=target_id)
    request["auth"] = auth_json(auth, sign_message_base58(trading_private_key, message))
    return request
