# Pascal Python Quickstart

This repository is a small, copyable Python quickstart for interacting
with Pascal's public API.

It is not the Pascal Python SDK. The SDK will eventually provide a polished
package, typed models, stable client APIs, and stronger abstractions. This
quickstart should stay close to the wire format so integrators can see exactly
how request signing, order placement, and cancellation work.

Public API reference: <https://docs.pascal.trade/>

## Quickstart

Clone the repository and install dependencies:

```sh
git clone https://github.com/Pascal-Research-Inc/pascal-python-quickstart.git
cd pascal-python-quickstart
uv sync
```

Run a read-only market data example:

```sh
uv run python examples/01_market_context.py
```

### Place and Cancel an Order

1. Copy the example environment file.

```sh
cp .env.example .env
```

2. Add your Pascal keys. Open the [Pascal web app](https://app.pascal.trade), connect, deposit, and generate a trading key.

![](docs/trading_key_0.png)
![](docs/trading_key_1.png)


Set `PASCAL_OWNER_PUBLIC_KEY` to the public key shown in the web app (`B1ufo9vCBU8z8y8fRQoT5gdP3bn11UsFZUFnyxu1H7K2` in the screenshot). 

Set `PASCAL_TRADING_PRIVATE_KEY` to the generated trading key shown by the web app after selecting "Create Key".

3. Build a signed order request. By default this prints the JSON request without sending it.

```sh
uv run python examples/02_place_order.py
```

The example defaults to prod, selects the first available market if you do
not pass `--symbol`, uses `123` as the default `client_order_id`, and builds a
one-contract post-only bid. Use `--help` to see the fields you can override.

4. Send the order only when you are ready to place the order:

```sh
uv run python examples/02_place_order.py --send
```

5. Cancel the order by `client_order_id`:

```sh
uv run python examples/03_cancel_order.py --send
```

The cancel example uses `123` as the default `client_order_id`, matching the
place example. You can also pass `--client-order-id` or `--order-id`
explicitly.

### More

See `examples/04_simple_market_maker.py` for a looped market maker.
It picks a market, fetches account state and the order book once per second,
maintains three post-only bid and ask levels sized `1`, `3`, and `5`
contracts, bounds exposure to `+/-10` contracts by default, and cancels its
open orders when interrupted with `Ctrl+C`.

See `examples/05_register_deposit_address.py` and
`examples/06_register_trading_key.py` for the owner-wallet flow that registers
a deposit address, waits for funding, then registers a trading key.

### Onboarding With A Solana Private Key

If you already have a Solana wallet private key available, you can onboard from
the command line without using the web app to create the account. Both write
examples print the exact request JSON first and require `--send` before
posting.

1. Register the account's deposit address with an invite code.

Invite codes look like `4PHPW-S4BM2-U9MS6-KP2JF`.
When supplied, the invite code is included in the signed registration payload.

```sh
uv run python examples/05_register_deposit_address.py '<owner-private-key>' --invite-code '<invite-code>' --send
```

The response includes `data.deposit_address`. This address is immutable for the
owner account.

2. Send USDC to the returned deposit address.

Wait until the account read endpoint shows the deposit in `collateral_usd`.

3. Register a trading key after the account is funded.

```sh
uv run python examples/06_register_trading_key.py '<owner-private-key>' --send --print-trading-private-key
```

Use the `owner` from the deposit-address request or response as
`PASCAL_OWNER_PUBLIC_KEY`, and use the printed generated key as
`PASCAL_TRADING_PRIVATE_KEY`. If you already have a trading key, pass it instead
of generating a new one:

```sh
uv run python examples/06_register_trading_key.py '<owner-private-key>' --trading-private-key '<trading-private-key>' --send
```

Treat both private keys as secrets. The owner private key is never printed by
either example.


# Developers

Run checks:

```sh
uv run ruff format --check .
uv run ruff check .
uv run basedpyright
uv run pytest
```
