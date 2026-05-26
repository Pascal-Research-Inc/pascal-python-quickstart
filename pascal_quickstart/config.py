from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PascalEnvironment:
    name: str
    deployment_id: int
    read_base_url: str
    write_base_url: str
    ws_url: str


ENVIRONMENTS: dict[str, PascalEnvironment] = {
    "canary": PascalEnvironment(
        name="canary",
        deployment_id=2,
        read_base_url="https://data.canary.pascal.trade",
        write_base_url="https://trade.canary.pascal.trade",
        ws_url="wss://data.canary.pascal.trade/ws",
    ),
    "prod": PascalEnvironment(
        name="prod",
        deployment_id=3,
        read_base_url="https://data.pascal.trade",
        write_base_url="https://trade.pascal.trade",
        ws_url="wss://data.pascal.trade/ws",
    ),
}


@dataclass(frozen=True)
class PascalConfig:
    environment: PascalEnvironment
    owner_public_key: str
    trading_private_key: str


def environment_from_name(name: str | None) -> PascalEnvironment:
    env_name = (name or "prod").lower()
    try:
        return ENVIRONMENTS[env_name]
    except KeyError as exc:
        known = ", ".join(sorted(ENVIRONMENTS))
        raise ValueError(
            f"Unknown Pascal environment {env_name!r}; expected one of: {known}"
        ) from exc


def load_dotenv(path: Path = Path(".env")) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def env_value(name: str, dotenv_values: dict[str, str]) -> str:
    return os.environ.get(name, dotenv_values.get(name, "")).strip()


def load_config(env_name: str | None = None, *, require_keys: bool = True) -> PascalConfig:
    dotenv_values = load_dotenv()
    environment = environment_from_name(
        env_name or env_value("PASCAL_ENV", dotenv_values) or "prod"
    )
    owner_public_key = env_value("PASCAL_OWNER_PUBLIC_KEY", dotenv_values)
    trading_private_key = env_value("PASCAL_TRADING_PRIVATE_KEY", dotenv_values)

    if require_keys:
        missing = [
            name
            for name, value in (
                ("PASCAL_OWNER_PUBLIC_KEY", owner_public_key),
                ("PASCAL_TRADING_PRIVATE_KEY", trading_private_key),
            )
            if not value
        ]
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"Missing required environment value(s): {joined}")

    return PascalConfig(
        environment=environment,
        owner_public_key=owner_public_key,
        trading_private_key=trading_private_key,
    )
