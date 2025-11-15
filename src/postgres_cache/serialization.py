"""Encoding helpers for storing cache payloads in PostgreSQL."""

from __future__ import annotations

import json
from typing import Any, Protocol


class Serializer(Protocol):
    """Protocol for encoding/decoding cache values."""

    def dumps(self, value: Any) -> bytes: ...

    def loads(self, data: bytes) -> Any: ...


class JsonSerializer:
    """JSON based serializer suitable for most structured payloads."""

    def dumps(self, value: Any) -> bytes:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    def loads(self, data: bytes) -> Any:
        return json.loads(data.decode("utf-8"))
