from __future__ import annotations

import argparse
import sys

from pascal_quickstart.config import load_config
from pascal_quickstart.crypto import KeyParseError, public_key_from_private_key
from pascal_quickstart.http import pretty_json
from pascal_quickstart.market_data import get_trading_keys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check whether the configured trading key is active for the owner."
    )
    parser.add_argument("--env", default="prod", help="Pascal environment name.")
    args = parser.parse_args()

    config = load_config(args.env)
    try:
        signer_public_key = public_key_from_private_key(config.trading_private_key)
    except KeyParseError as exc:
        parser.error(str(exc))

    trading_keys = get_trading_keys(config.environment, config.owner_public_key)
    matching_keys = [
        trading_key
        for trading_key in trading_keys
        if trading_key.get("trading_key") == signer_public_key
    ]

    print(f"Environment: {config.environment.name}")
    print(f"Owner: {config.owner_public_key}")
    print(f"Configured signer: {signer_public_key}")
    print()
    print("Active trading keys:")
    print(pretty_json(trading_keys))
    print()

    if matching_keys:
        print("Configured trading key is active for this owner.")
        return

    print("Configured trading key was not returned for this owner.")
    print("Use the private key matching one of the active trading keys, or register this key.")
    sys.exit(1)


if __name__ == "__main__":
    main()
