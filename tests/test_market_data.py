from __future__ import annotations

import pytest

from pascal_quickstart import market_data
from pascal_quickstart.config import PascalEnvironment
from pascal_quickstart.http import JsonValue

ENVIRONMENT = PascalEnvironment(
    name="test",
    deployment_id=0,
    read_base_url="https://data.example.test",
    write_base_url="https://trade.example.test",
    ws_url="wss://data.example.test/ws",
)


def test_list_trades_round_trips_next_cursor_as_before_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, str] | None]] = []

    def fake_get_json(url: str, params: dict[str, str] | None = None) -> JsonValue:
        calls.append((url, params))
        return {
            "status": "success",
            "data": {
                "items": [],
                "next_cursor": "00000000000000737841:0000000000",
            },
        }

    monkeypatch.setattr(market_data, "get_json", fake_get_json)

    page = market_data.list_trades(
        ENVIRONMENT,
        ["ME_SEN_2026.REP"],
        limit=5,
        before_cursor="00000000000000737841:0000000000",
    )

    assert page["next_cursor"] == "00000000000000737841:0000000000"
    assert calls == [
        (
            "https://data.example.test/api/v1/trades",
            {
                "symbols": "ME_SEN_2026.REP",
                "limit": "5",
                "before_cursor": "00000000000000737841:0000000000",
            },
        )
    ]
    assert calls[0][1] is not None
    assert "cursor" not in calls[0][1]


def test_list_trades_rejects_two_starting_points() -> None:
    with pytest.raises(ValueError, match="at most one"):
        market_data.list_trades(
            ENVIRONMENT,
            ["ME_SEN_2026.REP"],
            before_cursor="00000000000000737841:0000000000",
            at_or_before_seq=737841,
        )
