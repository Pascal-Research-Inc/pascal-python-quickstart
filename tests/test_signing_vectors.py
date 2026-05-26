from __future__ import annotations

from pascal_quickstart.crypto import public_key_from_private_key, sign_message_base58
from pascal_quickstart.signing import (
    RequestAuthInputs,
    cancel_order_message,
    create_trading_key_message,
    place_order_message,
    register_deposit_address_message,
)

OWNER_PRIVATE_KEY_HEX = "07" * 32
OWNER_PUBLIC_KEY = "GmaDrppBC7P5ARKV8g3djiwP89vz1jLK23V2GBjuAEGB"
TRADING_PRIVATE_KEY_HEX = "08" * 32
TRADING_PUBLIC_KEY = "2KW2XRd9kwqet15Aha2oK3tYvd3nWbTFH1MBiRAv1BE1"
PLACE_ORDER_MESSAGE_HEX = (
    "01010200881300000094962793010000"
    "ea4a6c63e29c520abef5507b132ec5f9954776aebebe7b92421eea691446d22c"
    "1398f62c6d1a457c51ba6a4b5f3dbd2f69fca93216218dc8997e416bd17d93ca"
    "0a0000000000000070640800000000002a000000000000002b00000000000000"
    "8082cd279301000000000000000000000000000000000000000000000000000000"
    "0000000000000053494d5f4556454e545f312e4d41524b45545f310000000000"
    "0000000000000000000000dcaf53738f1d5f06164660498a75888e7f0c78ed"
    "5f1bc17be1dd1cb3ccf53ce3000000010300000000000000"
)
PLACE_ORDER_SIGNATURE = (
    "32q4js875BeFhj23TEm6u7CrGW1U9r7esuSAURZNUTCGcRm7Mkr6UN6kwCuvVusfWhGqoFoGcGSa7hTk8Qvwsud3"
)
CANCEL_ORDER_MESSAGE_HEX = (
    "01020200881300000094962793010000"
    "ea4a6c63e29c520abef5507b132ec5f9954776aebebe7b92421eea691446d22c"
    "1398f62c6d1a457c51ba6a4b5f3dbd2f69fca93216218dc8997e416bd17d93ca"
    "00000000000000002a00000000000000"
)
CANCEL_ORDER_SIGNATURE = (
    "3WxYm8hw7esTpRLxjVRkY3HssMbp6t6s1HykHDagpDnnZH88Re62k6qLNZWFzDg1CM5x3DH2csnWMUqbzH8fRiZB"
)
CREATE_TRADING_KEY_MESSAGE_UTF8 = (
    '["create_trading_key","api-doc-key","2KW2XRd9kwqet15Aha2oK3tYvd3nWbTFH1MBiRAv1BE1",'
    "1732140800000,1,2,5000,1731536000000,"
    '"GmaDrppBC7P5ARKV8g3djiwP89vz1jLK23V2GBjuAEGB",'
    '"GmaDrppBC7P5ARKV8g3djiwP89vz1jLK23V2GBjuAEGB"]'
)
CREATE_TRADING_KEY_SIGNATURE = (
    "27ZXesvQMpSKiQDMTZQ9XXyy1Wvv853TPzVVQKxHV6dcZhgjhzzncbes3FmCrRJMFwHc3b84JnK87pNHvUUz8NQT"
)
REGISTER_DEPOSIT_ADDRESS_MESSAGE_UTF8 = (
    '["register_deposit_address","GmaDrppBC7P5ARKV8g3djiwP89vz1jLK23V2GBjuAEGB",'
    "1,2,5000,1731536000000,"
    '"GmaDrppBC7P5ARKV8g3djiwP89vz1jLK23V2GBjuAEGB",'
    '"GmaDrppBC7P5ARKV8g3djiwP89vz1jLK23V2GBjuAEGB"]'
)
REGISTER_DEPOSIT_ADDRESS_SIGNATURE = (
    "SmycN1kHAggVjooQvGSKCkqUMtk17h5ZZZudtoqBVGvjQyZxEutXTHVG7bZEYurfT4jmrBc7wFFW6pL9yvJbyMc"
)


def test_public_key_derivation_matches_docs_vectors() -> None:
    assert public_key_from_private_key(OWNER_PRIVATE_KEY_HEX) == OWNER_PUBLIC_KEY
    assert public_key_from_private_key(TRADING_PRIVATE_KEY_HEX) == TRADING_PUBLIC_KEY


def test_place_order_signing_vector() -> None:
    auth = RequestAuthInputs(
        deployment_id=2,
        owner_public_key=OWNER_PUBLIC_KEY,
        signer_public_key=TRADING_PUBLIC_KEY,
        client_ts_ms=1731536000000,
        recv_window_ms=5000,
    )

    message = place_order_message(
        auth=auth,
        client_order_id=42,
        replace_client_order_id=43,
        symbol="SIM_EVENT_1.MARKET_1",
        side="BID",
        price="0.550000",
        size=10,
        tif="GTT",
        post_only=True,
        reduce_only=True,
        expires_ts_ms=1731539600000,
    )

    assert message.hex() == PLACE_ORDER_MESSAGE_HEX
    assert sign_message_base58(TRADING_PRIVATE_KEY_HEX, message) == PLACE_ORDER_SIGNATURE


def test_cancel_order_signing_vector() -> None:
    auth = RequestAuthInputs(
        deployment_id=2,
        owner_public_key=OWNER_PUBLIC_KEY,
        signer_public_key=TRADING_PUBLIC_KEY,
        client_ts_ms=1731536000000,
        recv_window_ms=5000,
    )

    message = cancel_order_message(auth=auth, cancel_by="client_order_id", order_id=42)

    assert message.hex() == CANCEL_ORDER_MESSAGE_HEX
    assert sign_message_base58(TRADING_PRIVATE_KEY_HEX, message) == CANCEL_ORDER_SIGNATURE


def test_create_trading_key_signing_vector() -> None:
    auth = RequestAuthInputs(
        deployment_id=2,
        owner_public_key=OWNER_PUBLIC_KEY,
        signer_public_key=OWNER_PUBLIC_KEY,
        client_ts_ms=1731536000000,
        recv_window_ms=5000,
    )

    message = create_trading_key_message(
        auth=auth,
        name="api-doc-key",
        trading_key_public_key=TRADING_PUBLIC_KEY,
        expiration_ts_ms=1732140800000,
    )

    assert message.decode() == CREATE_TRADING_KEY_MESSAGE_UTF8
    assert sign_message_base58(OWNER_PRIVATE_KEY_HEX, message) == CREATE_TRADING_KEY_SIGNATURE


def test_register_deposit_address_signing_vector() -> None:
    auth = RequestAuthInputs(
        deployment_id=2,
        owner_public_key=OWNER_PUBLIC_KEY,
        signer_public_key=OWNER_PUBLIC_KEY,
        client_ts_ms=1731536000000,
        recv_window_ms=5000,
    )

    message = register_deposit_address_message(auth=auth)

    assert message.decode() == REGISTER_DEPOSIT_ADDRESS_MESSAGE_UTF8
    assert sign_message_base58(OWNER_PRIVATE_KEY_HEX, message) == REGISTER_DEPOSIT_ADDRESS_SIGNATURE
