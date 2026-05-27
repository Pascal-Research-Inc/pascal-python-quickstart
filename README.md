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

### Step 1: Hit the public API

Run a read-only market data example:

```sh
uv run python examples/01_market_context.py
```

### Step 2: Choose Your Onboarding Path

Before placing orders, choose exactly one onboarding path:

- Use [docs/onboarding_web_app.md](docs/onboarding_web_app.md) if you are
  connecting a wallet in the Pascal web app and generating a trading key there.
- Use [docs/onboarding_solana_key.md](docs/onboarding_solana_key.md) if you
  already have a Solana private key and want to register the deposit address 
  and trading key from the command line.

Both paths end with the same `.env` shape:

```sh
PASCAL_OWNER_PUBLIC_KEY=<owner-wallet-public-key>
PASCAL_TRADING_PRIVATE_KEY=<authorized-trading-private-key>
```

Do not use your owner wallet private key as `PASCAL_TRADING_PRIVATE_KEY`.
Order and cancel requests are signed by a separate trading key. The owner
wallet key is only for owner-wallet actions such as registering a deposit
address, registering trading keys, or withdrawing.

After either onboarding path, verify the configured signer:

```sh
uv run pytest tests/test_signing_vectors.py
uv run python examples/07_check_trading_key.py
```

If you are writing your own signing code, use the test signing vectors to
verify its correctness.

### Step 3: Place and Cancel an Order

Build a signed order request. By default this prints the JSON request without
sending it.

```sh
uv run python examples/02_place_order.py
```

The example defaults to prod, selects the first available market if you do
not pass `--symbol`, uses `123` as the default `client_order_id`, and builds a
one-contract post-only bid. Use `--help` to see the fields you can override.

Send the order only when you are ready to place the order:

```sh
uv run python examples/02_place_order.py --send
```

Cancel the order by `client_order_id`:

```sh
uv run python examples/03_cancel_order.py --send
```

The cancel example uses `123` as the default `client_order_id`, matching the
place example. You can also pass `--client-order-id` or `--order-id`
explicitly.

### More

- See `examples/04_simple_market_maker.py` for a looped market maker.
It picks a market, fetches account state and the order book once per second,
maintains three post-only bid and ask levels sized `1`, `3`, and `5`
contracts, bounds exposure to `+/-10` contracts by default, and cancels its
open orders when interrupted with `Ctrl+C`.

- See `examples/05_register_deposit_address.py` and
`examples/06_register_trading_key.py` for the owner-wallet flow that registers
a deposit address, waits for funding, then registers a trading key.

- See `examples/07_check_trading_key.py` for a read-only check that derives the
configured trading key's public key and confirms it is active for the configured
owner.

## FAQ

### Troubleshooting `unauthorized_signer`

`unauthorized_signer` usually means the request's `auth.signer` is not an
active trading key for the request's `auth.owner` in that environment. First
verify that your local signing code still matches Pascal's public API examples:

```sh
uv run pytest tests/test_signing_vectors.py
```

Then confirm your configured private key derives to one of the owner's active
trading keys:

```sh
uv run python examples/07_check_trading_key.py
```

If the derived signer is missing from the active trading-key list, use the
private key that matches an active trading key, register the configured key with
`examples/06_register_trading_key.py`, or confirm that `--env` and
`PASCAL_OWNER_PUBLIC_KEY` refer to the same account. 

### Troubleshooting `TRADING_KEY_NAME_ALREADY_USED`

A `TRADING_KEY_NAME_ALREADY_USED` response means the label is already taken; it
does not prove that the private key in `.env` matches that registered signer.


# Developers

Run checks:

```sh
uv run ruff format --check .
uv run ruff check .
uv run basedpyright
uv run pytest
```
