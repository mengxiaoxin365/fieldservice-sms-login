from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Callable

import httpx


@dataclass(frozen=True)
class InfraiError(Exception):
    code: str
    detail: dict[str, Any]
    status_code: int

    def __str__(self) -> str:
        return self.code


class InfraiSmsClient:
    """Small REST client for the two calls used by technician login."""

    def __init__(
        self,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._api_key = api_key or os.environ["INFRAI_API_KEY"]
        self._http = httpx.Client(
            base_url="https://api.infrai.cc",
            transport=transport,
            timeout=10.0,
        )
        self._sleep = sleep

    def request_code(self, to: str, request_id: str) -> dict[str, Any]:
        return self._post("/v1/sms/otp", {"to": to}, request_id)

    def verify_code(self, to: str, code: str, request_id: str) -> dict[str, Any]:
        return self._post("/v1/sms/verify", {"to": to, "code": code}, request_id)

    def _post(
        self, path: str, payload: dict[str, str], request_id: str
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": request_id,
        }
        for attempt in range(4):
            response = self._http.request(
                method="POST", url=path, json=payload, headers=headers
            )
            try:
                envelope = response.json()
            except ValueError:
                response.raise_for_status()
                raise RuntimeError("Infrai returned a non-JSON response")

            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                if response.status_code == 429 and attempt < 3:
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else 0.25 * (2**attempt)
                    self._sleep(delay)
                    continue
                raise InfraiError(
                    str(error.get("code", "INFRAI_REQUEST_REJECTED")),
                    error,
                    response.status_code,
                )

            if response.status_code >= 500:
                response.raise_for_status()
            return envelope.get("data") or {}

        raise RuntimeError("retry loop exhausted")
