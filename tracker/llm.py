"""The one place that talks to an LLM. Swap providers here without touching extraction.

Uses Gemini's generateContent REST API with a response schema, so the model
must answer with JSON in the shape we ask for.
"""

from __future__ import annotations

import json
import time
from typing import Callable, Protocol

import httpx

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"
# Free tier: 500 requests/day (Oct 2026); gemini-3.5-flash and newer Flash models allow only ~20.
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
MIN_INTERVAL = 7.0  # seconds between calls, to stay well inside free-tier per-minute limits
MAX_RETRIES = 3


class LLMError(Exception):
    """The model call failed or returned something unusable."""


class JsonLLM(Protocol):
    model: str

    def generate_json(self, system: str, prompt: str, schema: dict) -> dict: ...


class GeminiClient:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_GEMINI_MODEL,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        min_interval: float = MIN_INTERVAL,
    ) -> None:
        self.model = model
        self._client = client or httpx.Client(base_url=GEMINI_API, timeout=120.0)
        self._headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
        self._sleep = sleep
        self._clock = clock
        self._min_interval = min_interval
        self._last_call: float | None = None

    def generate_json(self, system: str, prompt: str, schema: dict) -> dict:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        }
        response = self._post(f"/models/{self.model}:generateContent", body)
        return _parse(response)

    def _post(self, path: str, body: dict) -> dict:
        for attempt in range(MAX_RETRIES + 1):
            self._pace()
            try:
                response = self._client.post(path, json=body, headers=self._headers)
            except httpx.HTTPError as exc:
                if attempt == MAX_RETRIES:
                    raise LLMError(f"network error: {type(exc).__name__}") from exc
                self._sleep(10 * (attempt + 1))
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if response.status_code == 429 and _daily_quota_used_up(response):
                    raise LLMError(f"daily quota used up: {_error_message(response)}")
                if attempt == MAX_RETRIES:
                    raise LLMError(f"HTTP {response.status_code} after {MAX_RETRIES} retries: {_error_message(response)}")
                retry_after = response.headers.get("retry-after")
                self._sleep(float(retry_after) if retry_after and retry_after.isdigit() else 30 * (attempt + 1))
                continue
            if response.status_code >= 400:
                raise LLMError(f"HTTP {response.status_code}: {_error_message(response)}")
            return response.json()
        raise LLMError("unreachable")

    def _pace(self) -> None:
        if self._last_call is not None:
            wait = self._last_call + self._min_interval - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last_call = self._clock()


def _parse(data: dict) -> dict:
    block = (data.get("promptFeedback") or {}).get("blockReason")
    if block:
        raise LLMError(f"prompt blocked: {block}")
    candidates = data.get("candidates") or []
    if not candidates:
        raise LLMError("no candidates in response")
    candidate = candidates[0]
    if candidate.get("finishReason") not in (None, "STOP"):
        raise LLMError(f"generation stopped early: {candidate.get('finishReason')}")
    parts = (candidate.get("content") or {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"response was not valid JSON: {text[:200]!r}") from exc
    if not isinstance(result, dict):
        raise LLMError("response JSON was not an object")
    return result


def _violations(response: httpx.Response) -> list[dict]:
    try:
        details = response.json()["error"].get("details", [])
    except (ValueError, KeyError, TypeError, AttributeError):
        return []
    return [v for d in details if isinstance(d, dict) for v in d.get("violations", []) if isinstance(v, dict)]


def _daily_quota_used_up(response: httpx.Response) -> bool:
    """A per-day limit won't reset for hours, so retrying only burns more quota."""
    return any("PerDay" in str(v.get("quotaId", "")) for v in _violations(response))


def _error_message(response: httpx.Response) -> str:
    try:
        message = " ".join(response.json()["error"]["message"].split())[:600]
    except (ValueError, KeyError, TypeError, AttributeError):
        return response.text[:600]
    for v in _violations(response):
        if v.get("quotaId"):
            message += f" [quota: {v['quotaId']}, limit: {v.get('quotaValue', '?')}]"
    return message
