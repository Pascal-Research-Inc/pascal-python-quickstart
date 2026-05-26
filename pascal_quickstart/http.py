from __future__ import annotations

import json
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import certifi

JsonValue = dict[str, Any] | list[Any]


class PascalHTTPError(RuntimeError):
    pass


def pretty_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=False, separators=(",", ": "))


def get_json(url: str, params: dict[str, str] | None = None) -> JsonValue:
    full_url = url if not params else f"{url}?{urlencode(params)}"
    request = Request(full_url, headers={"Accept": "application/json"}, method="GET")
    return _send(request)


def post_json(url: str, body: JsonValue) -> JsonValue:
    encoded = json.dumps(body, separators=(",", ":")).encode()
    request = Request(
        url,
        data=encoded,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    return _send(request)


def _send(request: Request) -> JsonValue:
    context = ssl.create_default_context(cafile=certifi.where())
    try:
        with urlopen(request, timeout=20, context=context) as response:
            raw = response.read()
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise PascalHTTPError(f"HTTP {exc.code} from {request.full_url}: {body}") from exc
    except URLError as exc:
        raise PascalHTTPError(f"Could not reach {request.full_url}: {exc.reason}") from exc

    parsed = json.loads(raw)
    if not isinstance(parsed, dict | list):
        raise PascalHTTPError(f"Expected JSON object or array from {request.full_url}")
    return parsed


def unwrap_envelope(envelope: JsonValue, *, context: str) -> Any:
    if not isinstance(envelope, dict):
        raise PascalHTTPError(f"{context}: expected response envelope object")
    if envelope.get("status") != "success":
        raise PascalHTTPError(f"{context}: {pretty_json(envelope)}")
    return envelope.get("data")
