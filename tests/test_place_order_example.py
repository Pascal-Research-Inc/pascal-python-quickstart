from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

import pytest

from pascal_quickstart import config, http
from pascal_quickstart.config import PascalConfig, environment_from_name

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "02_place_order.py"
BUILDER_PUBLIC_KEY = "J2xccRtuG43drESLYznHhLhQkLTdfepcKYbiQ9BsJVaf"


def test_builder_order_example_is_a_dry_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_load_config(env_name: str | None = None) -> PascalConfig:
        return PascalConfig(
            environment_from_name(env_name),
            "GmaDrppBC7P5ARKV8g3djiwP89vz1jLK23V2GBjuAEGB",
            "08" * 32,
        )

    def unexpected_post(*args: object, **kwargs: object) -> None:
        pytest.fail("The example must not send an order without --send")

    monkeypatch.setattr(config, "load_config", fake_load_config)
    monkeypatch.setattr(http, "post_json", unexpected_post)
    monkeypatch.syspath_prepend(str(EXAMPLE.parent))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(EXAMPLE),
            "--symbol",
            "SIM_EVENT_1.MARKET_1",
            "--price",
            "0.500000",
            "--size",
            "100",
            "--builder-pubkey",
            BUILDER_PUBLIC_KEY,
            "--builder-fee-rate",
            "0.010000",
        ],
    )

    runpy.run_path(str(EXAMPLE), run_name="__main__")

    output = capsys.readouterr().out
    body, _ = json.JSONDecoder().raw_decode(output.removeprefix("Request JSON:\n"))
    assert body[0]["builder_info"] == {
        "builder_pubkey": BUILDER_PUBLIC_KEY,
        "builder_fee_rate": "0.010000",
    }
    assert body[0]["size"] == "100"
    assert "Dry run only" in output


@pytest.mark.parametrize(
    "builder_args",
    [["--builder-pubkey", BUILDER_PUBLIC_KEY], ["--builder-fee-rate", "0.010000"]],
)
def test_builder_order_example_requires_both_flags(
    builder_args: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.syspath_prepend(str(EXAMPLE.parent))
    monkeypatch.setattr(sys, "argv", [str(EXAMPLE), *builder_args])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(EXAMPLE), run_name="__main__")

    assert exc_info.value.code == 2
    assert (
        "--builder-pubkey and --builder-fee-rate must be provided together"
        in capsys.readouterr().err
    )
