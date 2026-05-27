from __future__ import annotations

import argparse

from pascal_quickstart.config import environment_from_name
from pascal_quickstart.crypto import KeyParseError
from pascal_quickstart.http import post_json, pretty_json
from pascal_quickstart.signing import signed_register_deposit_address_request


def main() -> None:
    """Register a wallet-facing deposit address for an owner wallet.

    This is the first owner-wallet step for agents that already have a Solana
    private key. The script derives the owner public key, signs Pascal's
    documented register_deposit_address payload, signs the invite code when one
    is supplied, prints the exact request JSON, and posts it only when --send is
    present. The response includes the deposit address to fund before
    registering a trading key.
    """
    parser = argparse.ArgumentParser(description="Register a Pascal deposit address.")
    parser.add_argument("owner_private_key", help="Owner wallet private key.")
    parser.add_argument("--env", default="prod", help="Pascal environment name.")
    parser.add_argument("--send", action="store_true", help="Actually post the write request.")
    parser.add_argument("--invite-code", help="Invite code for account onboarding.")
    parser.add_argument("--recv-window-ms", type=int, default=5000)
    args = parser.parse_args()

    environment = environment_from_name(args.env)
    try:
        request = signed_register_deposit_address_request(
            deployment_id=environment.deployment_id,
            owner_private_key=args.owner_private_key,
            invite_code=args.invite_code,
            recv_window_ms=args.recv_window_ms,
        )
    except (KeyParseError, ValueError) as exc:
        parser.error(str(exc))

    print("Request JSON:")
    print(pretty_json(request))

    if not args.send:
        print()
        print("Dry run only. Re-run with --send to register this deposit address.")
        return

    response = post_json(f"{environment.write_base_url}/api/v1/deposit-addresses", request)
    print()
    print("Response JSON:")
    print(pretty_json(response))


if __name__ == "__main__":
    main()
