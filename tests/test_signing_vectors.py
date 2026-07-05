from __future__ import annotations

from pascal_quickstart.crypto import public_key_from_private_key, sign_message_base58
from pascal_quickstart.signing import (
    RequestAuthInputs,
    cancel_order_message,
    create_trading_key_message,
    place_order_message,
    register_deposit_address_message,
    signed_place_order_request,
    signed_register_deposit_address_request,
)

OWNER_PRIVATE_KEY_HEX = "07" * 32
OWNER_PUBLIC_KEY = "GmaDrppBC7P5ARKV8g3djiwP89vz1jLK23V2GBjuAEGB"
TRADING_PRIVATE_KEY_HEX = "08" * 32
TRADING_PUBLIC_KEY = "2KW2XRd9kwqet15Aha2oK3tYvd3nWbTFH1MBiRAv1BE1"
PLACE_ORDER_MESSAGE_HEX = (
    "01010300881300000094962793010000"
    "ea4a6c63e29c520abef5507b132ec5f9954776aebebe7b92421eea691446d22c"
    "1398f62c6d1a457c51ba6a4b5f3dbd2f69fca93216218dc8997e416bd17d93ca"
    "0a0000000000000070640800000000002a000000000000002b00000000000000"
    "8082cd279301000000000000000000000000000000000000000000000000000000"
    "0000000000000053494d5f4556454e545f312e4d41524b45545f310000000000"
    "0000000000000000000000dcaf53738f1d5f06164660498a75888e7f0c78ed"
    "5f1bc17be1dd1cb3ccf53ce3020000010300000000000000"
)
PLACE_ORDER_SIGNATURE = (
    "3uG7HnnR2j3R26LoW3VNSJzKUfs16M9kXc58JbhkACwm2KmBXQuozLCQvREuAoxuHQjzADdBTV7NkgNrqRANgaZN"
)
CANCEL_ORDER_MESSAGE_HEX = (
    "01020300881300000094962793010000"
    "ea4a6c63e29c520abef5507b132ec5f9954776aebebe7b92421eea691446d22c"
    "1398f62c6d1a457c51ba6a4b5f3dbd2f69fca93216218dc8997e416bd17d93ca"
    "00020000000000002a00000000000000"
)
CANCEL_ORDER_SIGNATURE = (
    "CZMtBC9qYUExsoWAvjoXCwavWqpzKJdgTwGXypJYRFVs9cgzdRGhgJBSinCS814mJrfyattRVNdnnfcPE36ptMi"
)
CREATE_TRADING_KEY_MESSAGE_UTF8 = (
    '["create_trading_key","api-doc-key","2KW2XRd9kwqet15Aha2oK3tYvd3nWbTFH1MBiRAv1BE1",'
    "1732140800000,1,3,5000,1731536000000,"
    '"GmaDrppBC7P5ARKV8g3djiwP89vz1jLK23V2GBjuAEGB",'
    '"GmaDrppBC7P5ARKV8g3djiwP89vz1jLK23V2GBjuAEGB"]'
)
CREATE_TRADING_KEY_SIGNATURE = (
    "kyc2KdqPTeEWqoK3pXR2rgPUiK4zXg9QdQffPUWk8eALpFy7uaHBEsASt7RQyVzDeubHVsPqQAHXrt8m8KZ78Ep"
)
REGISTER_DEPOSIT_ADDRESS_MESSAGE_UTF8 = (
    '["register_deposit_address","GmaDrppBC7P5ARKV8g3djiwP89vz1jLK23V2GBjuAEGB",'
    "1,3,5000,1731536000000,"
    '"GmaDrppBC7P5ARKV8g3djiwP89vz1jLK23V2GBjuAEGB",'
    '"GmaDrppBC7P5ARKV8g3djiwP89vz1jLK23V2GBjuAEGB"]'
)
REGISTER_DEPOSIT_ADDRESS_SIGNATURE = (
    "5xWT1auD2tHfqw3arxJqQC4XdZVXYMcT382wCLAHPdequru7LZJ9Dsb8umpvCGGJV2h23ZgP2JwjBqgpi4KZHfCq"
)
INVITE_CODE = "4PHPW-S4BM2-U9MS6-KP2JF"
REGISTER_DEPOSIT_ADDRESS_WITH_INVITE_MESSAGE_UTF8 = (
    '["register_deposit_address","GmaDrppBC7P5ARKV8g3djiwP89vz1jLK23V2GBjuAEGB",'
    "1,3,5000,1731536000000,"
    '"GmaDrppBC7P5ARKV8g3djiwP89vz1jLK23V2GBjuAEGB",'
    '"GmaDrppBC7P5ARKV8g3djiwP89vz1jLK23V2GBjuAEGB",'
    '"4PHPW-S4BM2-U9MS6-KP2JF"]'
)
REGISTER_DEPOSIT_ADDRESS_WITH_INVITE_SIGNATURE = (
    "3y43tLaBWdQyxkj7BAbbSEmGfd6Fu3Xop5ATyWcLiC4XYFgNJSmoKXmyC8Qnu7oRUzAnEycmfSLzdyAV5L3cxecc"
)


def test_public_key_derivation_matches_docs_vectors() -> None:
    assert public_key_from_private_key(OWNER_PRIVATE_KEY_HEX) == OWNER_PUBLIC_KEY
    assert public_key_from_private_key(TRADING_PRIVATE_KEY_HEX) == TRADING_PUBLIC_KEY


def test_place_order_signing_vector() -> None:
    auth = RequestAuthInputs(
        deployment_id=3,
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
        deployment_id=3,
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
        deployment_id=3,
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
        deployment_id=3,
        owner_public_key=OWNER_PUBLIC_KEY,
        signer_public_key=OWNER_PUBLIC_KEY,
        client_ts_ms=1731536000000,
        recv_window_ms=5000,
    )

    message = register_deposit_address_message(auth=auth)

    assert message.decode() == REGISTER_DEPOSIT_ADDRESS_MESSAGE_UTF8
    assert sign_message_base58(OWNER_PRIVATE_KEY_HEX, message) == REGISTER_DEPOSIT_ADDRESS_SIGNATURE


def test_register_deposit_address_with_invite_code_signs_invite_code() -> None:
    auth = RequestAuthInputs(
        deployment_id=3,
        owner_public_key=OWNER_PUBLIC_KEY,
        signer_public_key=OWNER_PUBLIC_KEY,
        client_ts_ms=1731536000000,
        recv_window_ms=5000,
    )

    message = register_deposit_address_message(auth=auth, invite_code=INVITE_CODE)

    assert message.decode() == REGISTER_DEPOSIT_ADDRESS_WITH_INVITE_MESSAGE_UTF8
    assert (
        sign_message_base58(OWNER_PRIVATE_KEY_HEX, message)
        == REGISTER_DEPOSIT_ADDRESS_WITH_INVITE_SIGNATURE
    )


def test_signed_register_deposit_address_request_signs_invite_code() -> None:
    request = signed_register_deposit_address_request(
        deployment_id=3,
        owner_private_key=OWNER_PRIVATE_KEY_HEX,
        invite_code=INVITE_CODE,
        client_ts_ms=1731536000000,
        recv_window_ms=5000,
    )

    assert list(request) == ["owner", "invite_code", "auth"]
    assert request["owner"] == OWNER_PUBLIC_KEY
    assert request["invite_code"] == INVITE_CODE
    assert request["auth"]["signature"] == REGISTER_DEPOSIT_ADDRESS_WITH_INVITE_SIGNATURE


def test_signed_market_order_request_includes_market_type() -> None:
    request = signed_place_order_request(
        deployment_id=3,
        owner_public_key=OWNER_PUBLIC_KEY,
        trading_private_key=TRADING_PRIVATE_KEY_HEX,
        client_order_id=42,
        symbol="SIM_EVENT_1.MARKET_1",
        side="BID",
        price="1.000000",
        size=10,
        tif="IOC",
        order_type="MARKET",
        client_ts_ms=1731536000000,
        recv_window_ms=5000,
    )

    assert request["type"] == "MARKET"
    assert request["tif"] == "IOC"
    assert request["auth"]["signer"] == TRADING_PUBLIC_KEY


def test_allow_missing_replace_sets_signed_flag_and_request_field() -> None:
    auth = RequestAuthInputs(
        deployment_id=3,
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
        tif="GTC",
        allow_missing_replace=True,
    )
    request = signed_place_order_request(
        deployment_id=3,
        owner_public_key=OWNER_PUBLIC_KEY,
        trading_private_key=TRADING_PRIVATE_KEY_HEX,
        client_order_id=42,
        replace_client_order_id=43,
        symbol="SIM_EVENT_1.MARKET_1",
        side="BID",
        price="0.550000",
        size=10,
        allow_missing_replace=True,
        client_ts_ms=1731536000000,
        recv_window_ms=5000,
    )

    assert message[224] == 4
    assert request["allow_missing_replace"] is True
