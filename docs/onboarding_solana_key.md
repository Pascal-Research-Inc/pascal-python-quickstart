# Onboarding With A Solana Private Key

Use this path when you already have the owner wallet private key and want to
onboard from the command line without using the web app to create the account.

The owner private key is only used by `examples/05_register_deposit_address.py`
and `examples/06_register_trading_key.py`. Do not put the owner private key in
`PASCAL_TRADING_PRIVATE_KEY`. Order and cancel requests use the private key for
an authorized Pascal trading key.

Both write examples print the exact request JSON first and require `--send`
before posting.

## Steps

1. Register the account's deposit address with an invite code.

Invite codes look like `4PHPW-S4BM2-U9MS6-KP2JF`. When supplied, the invite
code is included in the signed registration payload.

Solana CLI keypairs are usually stored as a JSON array with 64 byte values: the
32-byte private seed followed by the 32-byte public key. For example, a keypair
whose private seed repeats the byte `0x01` starts like this:

```json
[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,138,136,227,221,116,9,241,149,253,82,219,45,60,186,93,114,202,103,9,191,29,148,18,27,243,116,136,1,180,15,111,92]
```

Pass that JSON array as `'<owner-private-key>'`. The examples also accept the
32-byte seed by itself as base58 or 64 hex characters.

```sh
uv run python examples/05_register_deposit_address.py '<owner-private-key>' --invite-code '<invite-code>' --send
```

The response includes `data.deposit_address`. This address is immutable for the
owner account.

2. Send USDC to the returned deposit address.

Wait until the account read endpoint shows the deposit in `collateral_usd`.

3. Register a trading key after the account is funded.

To generate and register a fresh trading key:

```sh
uv run python examples/06_register_trading_key.py '<owner-private-key>' --send --print-trading-private-key
```

To register an existing trading key:

```sh
uv run python examples/06_register_trading_key.py '<owner-private-key>' --trading-private-key '<trading-private-key>' --send
```

Use the `owner` from the deposit-address request or response as
`PASCAL_OWNER_PUBLIC_KEY`, and use the generated or supplied trading key as
`PASCAL_TRADING_PRIVATE_KEY`.

Your `.env` should have this shape:

```sh
PASCAL_OWNER_PUBLIC_KEY=<owner-wallet-public-key>
PASCAL_TRADING_PRIVATE_KEY=<authorized-trading-private-key>
```

Treat both private keys as secrets. The owner private key is never printed by
either example.

4. Verify signing and trading-key authorization.

```sh
uv run pytest tests/test_signing_vectors.py
uv run python examples/07_check_trading_key.py
```

The first command checks that the local signing code still matches Pascal's
public API examples. The second command derives the configured signer's public
key and confirms that it is active for the configured owner.

## Place An Order

After onboarding, follow
[Step 3 in the README](../README.md#step-3-place-and-cancel-an-order) to place
and cancel orders.

## Troubleshooting

See the README's FAQ entries for
[`unauthorized_signer`](../README.md#troubleshooting-unauthorized_signer) and
[`TRADING_KEY_NAME_ALREADY_USED`](../README.md#troubleshooting-trading_key_name_already_used).
