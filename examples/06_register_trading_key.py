from __future__ import annotations

import argparse

from pascal_quickstart.config import environment_from_name
from pascal_quickstart.crypto import KeyParseError, generate_keypair, public_key_from_private_key
from pascal_quickstart.http import post_json, pretty_json
from pascal_quickstart.signing import now_ms, signed_create_trading_key_request

MS_PER_DAY = 86_400_000
MAX_VALID_DAYS = 365


def main() -> None:
    """Generate and register a trading key after the account is funded.

    This is the second owner-wallet step for agents that already have a Solana
    private key. Run 05_register_deposit_address.py first, deposit to the
    returned address, then use this script to authorize a generated Ed25519
    trading key. The script can generate a new key or register a provided one,
    prints the exact request JSON, and posts it only when --send is present.
    """
    parser = argparse.ArgumentParser(description="Register a Pascal trading key.")
    parser.add_argument("owner_private_key", help="Owner wallet private key.")
    parser.add_argument("--env", default="prod", help="Pascal environment name.")
    parser.add_argument("--send", action="store_true", help="Actually post the write request.")
    parser.add_argument(
        "--name",
        default="agent-key",
        help="Public onchain trading-key label. Must fit in 16 UTF-8 bytes.",
    )
    parser.add_argument(
        "--valid-days",
        type=int,
        default=30,
        help="Trading-key lifetime when --expiration-ts-ms is omitted.",
    )
    parser.add_argument("--expiration-ts-ms", type=int, help="Explicit expiration timestamp.")
    parser.add_argument(
        "--trading-private-key",
        help="Existing trading private key to register. Defaults to generating a fresh key.",
    )
    parser.add_argument("--recv-window-ms", type=int, default=5000)
    parser.add_argument(
        "--print-trading-private-key",
        action="store_true",
        help="Print the generated trading private key after successful registration.",
    )
    args = parser.parse_args()

    environment = environment_from_name(args.env)
    client_ts_ms = now_ms()
    expiration_ts_ms = (
        args.expiration_ts_ms
        if args.expiration_ts_ms is not None
        else client_ts_ms + (args.valid_days * MS_PER_DAY)
    )

    if args.expiration_ts_ms is None and not 1 <= args.valid_days <= MAX_VALID_DAYS:
        parser.error(f"--valid-days must be between 1 and {MAX_VALID_DAYS}")

    generated_private_key = args.trading_private_key is None
    trading_private_key = args.trading_private_key
    if trading_private_key is None:
        trading_private_key, trading_public_key = generate_keypair()
    else:
        try:
            trading_public_key = public_key_from_private_key(trading_private_key)
        except KeyParseError as exc:
            parser.error(str(exc))

    try:
        request = signed_create_trading_key_request(
            deployment_id=environment.deployment_id,
            owner_private_key=args.owner_private_key,
            trading_key_public_key=trading_public_key,
            name=args.name,
            expiration_ts_ms=expiration_ts_ms,
            client_ts_ms=client_ts_ms,
            recv_window_ms=args.recv_window_ms,
        )
    except (KeyParseError, ValueError) as exc:
        parser.error(str(exc))

    print("Request JSON:")
    print(pretty_json(request))

    if not args.send:
        print()
        print("Dry run only. Re-run with --send to register this trading key.")
        print("The generated private key is only printed when --print-trading-private-key is set.")
        return

    response = post_json(f"{environment.write_base_url}/api/v1/trading-keys", request)
    print()
    print("Response JSON:")
    print(pretty_json(response))
    print()
    print("Trading key:")
    key_output = {"trading_public_key": trading_public_key}
    if args.print_trading_private_key and generated_private_key:
        key_output["trading_private_key"] = trading_private_key
    print(pretty_json(key_output))


if __name__ == "__main__":
    main()
