from __future__ import annotations

import argparse

from example_defaults import DEFAULT_CLIENT_ORDER_ID

from pascal_quickstart.config import load_config
from pascal_quickstart.http import post_json, pretty_json
from pascal_quickstart.signing import signed_cancel_order_request


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build and optionally send a signed Pascal cancel."
    )
    parser.add_argument("--env", default="prod", help="Pascal environment name.")
    parser.add_argument("--send", action="store_true", help="Actually post the write request.")
    parser.add_argument("--client-order-id", type=int)
    parser.add_argument("--order-id", type=int)
    parser.add_argument("--recv-window-ms", type=int, default=5000)
    args = parser.parse_args()

    client_order_id = args.client_order_id
    if client_order_id is None and args.order_id is None:
        client_order_id = DEFAULT_CLIENT_ORDER_ID

    config = load_config(args.env)
    request = signed_cancel_order_request(
        deployment_id=config.environment.deployment_id,
        owner_public_key=config.owner_public_key,
        trading_private_key=config.trading_private_key,
        client_order_id=client_order_id,
        order_id=args.order_id,
        recv_window_ms=args.recv_window_ms,
    )
    body = [request]

    print("Request JSON:")
    print(pretty_json(body))

    if not args.send:
        print()
        print("Dry run only. Re-run with --send to post this cancel.")
        return

    response = post_json(f"{config.environment.write_base_url}/api/v1/cancels", body)
    print()
    print("Response JSON:")
    print(pretty_json(response))


if __name__ == "__main__":
    main()
