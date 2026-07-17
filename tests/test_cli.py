import pytest

from pascal_quickstart import cli
from pascal_quickstart.config import PascalConfig, PascalEnvironment

ENVIRONMENT = PascalEnvironment(
    name="test",
    deployment_id=3,
    read_base_url="https://data.example.test",
    write_base_url="https://trade.example.test",
    ws_url="wss://data.example.test/ws",
)
OWNER_PUBLIC_KEY = "GmaDrppBC7P5ARKV8g3djiwP89vz1jLK23V2GBjuAEGB"
TRADING_PRIVATE_KEY_HEX = "08" * 32


def test_markets_prints_all_markets_when_limit_is_omitted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_load_config(env_name: str | None = None, *, require_keys: bool = True) -> PascalConfig:
        return PascalConfig(ENVIRONMENT, "", "")

    def fake_list_markets(environment: PascalEnvironment) -> list[dict[str, object]]:
        return [{"symbol": f"MARKET_{number}"} for number in range(25)]

    monkeypatch.setattr(cli, "load_config", fake_load_config)
    monkeypatch.setattr(cli, "list_markets", fake_list_markets)

    parser = cli.build_markets_parser()
    args = parser.parse_args([])
    cli.handle_markets(parser, args)

    output = capsys.readouterr().out
    assert "Markets: 25" in output
    assert "- MARKET_0 " in output
    assert "- MARKET_24 " in output


def test_markets_limit_caps_printed_markets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_load_config(env_name: str | None = None, *, require_keys: bool = True) -> PascalConfig:
        return PascalConfig(ENVIRONMENT, "", "")

    def fake_list_markets(environment: PascalEnvironment) -> list[dict[str, object]]:
        return [{"symbol": f"MARKET_{number}"} for number in range(25)]

    monkeypatch.setattr(cli, "load_config", fake_load_config)
    monkeypatch.setattr(cli, "list_markets", fake_list_markets)

    parser = cli.build_markets_parser()
    args = parser.parse_args(["--limit", "2"])
    cli.handle_markets(parser, args)

    output = capsys.readouterr().out
    assert "Markets: 2" in output
    assert "- MARKET_0 " in output
    assert "- MARKET_1 " in output
    assert "- MARKET_2 " not in output


def test_markets_limit_must_be_positive(capsys: pytest.CaptureFixture[str]) -> None:
    parser = cli.build_markets_parser()
    args = parser.parse_args(["--limit", "0"])

    with pytest.raises(SystemExit) as exc_info:
        cli.handle_markets(parser, args)
    assert exc_info.value.code == 2
    assert "--limit must be at least 1" in capsys.readouterr().err


def test_signed_order_requests_from_specs_builds_batch() -> None:
    config = PascalConfig(ENVIRONMENT, OWNER_PUBLIC_KEY, TRADING_PRIVATE_KEY_HEX)
    specs = [
        {
            "symbol": "SIM_EVENT_1.MARKET_1",
            "side": "BID",
            "price": "0.45",
            "size": "2",
            "post_only": True,
        },
        {
            "type": "MARKET",
            "symbol": "SIM_EVENT_1.MARKET_1",
            "side": "ASK",
            "size": 1,
            "reduce_only": True,
        },
    ]

    requests = cli.signed_order_requests_from_specs(
        config,
        specs,
        base_client_order_id=1000,
        client_ts_ms=1731536000000,
    )

    assert len(requests) == 2
    assert requests[0]["client_order_id"] == "1000"
    assert requests[0]["price"] == "0.450000"
    assert requests[0]["size"] == "2"
    assert requests[0]["post_only"] is True
    assert "type" not in requests[0]
    assert requests[1]["client_order_id"] == "1001"
    assert requests[1]["type"] == "MARKET"
    assert requests[1]["tif"] == "IOC"
    assert requests[1]["price"] == "0.010000"
    assert requests[1]["reduce_only"] is True


def test_signed_order_requests_from_specs_rejects_duplicate_client_ids() -> None:
    config = PascalConfig(ENVIRONMENT, OWNER_PUBLIC_KEY, TRADING_PRIVATE_KEY_HEX)
    specs = [
        {
            "client_order_id": "42",
            "symbol": "SIM_EVENT_1.MARKET_1",
            "side": "BID",
            "price": "0.450000",
            "size": 1,
        },
        {
            "client_order_id": 42,
            "symbol": "SIM_EVENT_1.MARKET_1",
            "side": "ASK",
            "price": "0.550000",
            "size": 1,
        },
    ]

    with pytest.raises(ValueError, match="Duplicate client_order_id"):
        cli.signed_order_requests_from_specs(
            config,
            specs,
            client_ts_ms=1731536000000,
        )


def test_parse_id_values_accepts_repeated_and_comma_delimited_ids() -> None:
    assert cli.parse_id_values(
        [["42", "43,44"], ["45"]],
        name="--client-order-id",
        maximum=100,
    ) == [42, 43, 44, 45]


def test_signed_cancel_requests_from_ids_builds_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    config = PascalConfig(ENVIRONMENT, OWNER_PUBLIC_KEY, TRADING_PRIVATE_KEY_HEX)
    monkeypatch.setattr(cli, "now_ms", lambda: 1731536000000)

    requests = cli.signed_cancel_requests_from_ids(
        config,
        client_order_ids=[42, 43],
        order_ids=[185499743],
    )

    assert len(requests) == 3
    assert requests[0]["client_order_id"] == "42"
    assert requests[1]["client_order_id"] == "43"
    assert requests[2]["order_id"] == "185499743"
    assert {request["metadata"] for request in requests} == {"2"}
    assert {request["auth"]["client_ts_ms"] for request in requests} == {"1731536000000"}


def test_signed_cancel_requests_from_ids_rejects_empty_batch() -> None:
    config = PascalConfig(ENVIRONMENT, OWNER_PUBLIC_KEY, TRADING_PRIVATE_KEY_HEX)

    with pytest.raises(ValueError, match="at least one"):
        cli.signed_cancel_requests_from_ids(config, client_order_ids=[], order_ids=[])
