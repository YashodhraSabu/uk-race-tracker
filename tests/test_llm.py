import json

import httpx
import pytest

from tracker.llm import GEMINI_API, GeminiClient, LLMError


def gemini_reply(payload: dict, finish: str = "STOP") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {"parts": [{"text": "thinking...", "thought": True}, {"text": json.dumps(payload)}]},
                    "finishReason": finish,
                }
            ]
        },
    )


def make_client(handler):
    slept = []
    client = httpx.Client(base_url=GEMINI_API, transport=httpx.MockTransport(handler))
    return GeminiClient("test-key", model="test-model", client=client, sleep=slept.append, min_interval=0), slept


def test_sends_schema_and_parses_json():
    seen = []

    def handler(request):
        seen.append(request)
        return gemini_reply({"race_date": {"value": "2027-04-25", "quote": "25 April 2027"}})

    llm, _ = make_client(handler)
    result = llm.generate_json("system text", "prompt text", {"type": "OBJECT"})
    assert result["race_date"]["value"] == "2027-04-25"

    request = seen[0]
    assert request.url.path == "/v1beta/models/test-model:generateContent"
    assert request.headers["x-goog-api-key"] == "test-key"
    body = json.loads(request.content)
    assert body["systemInstruction"]["parts"][0]["text"] == "system text"
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["responseSchema"] == {"type": "OBJECT"}
    assert body["generationConfig"]["temperature"] == 0


def test_retries_rate_limits_then_succeeds():
    replies = [httpx.Response(429, headers={"retry-after": "5"}, json={"error": {"message": "slow down"}}),
               gemini_reply({"ok": True})]
    llm, slept = make_client(lambda request: replies.pop(0))
    assert llm.generate_json("s", "p", {}) == {"ok": True}
    assert slept == [5.0]


def test_gives_up_after_repeated_rate_limits():
    llm, _ = make_client(lambda request: httpx.Response(429, json={"error": {"message": "quota"}}))
    with pytest.raises(LLMError, match="HTTP 429 after 3 retries: quota"):
        llm.generate_json("s", "p", {})


def test_client_errors_are_not_retried():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(404, json={"error": {"message": "model not found"}})

    llm, _ = make_client(handler)
    with pytest.raises(LLMError, match="HTTP 404: model not found"):
        llm.generate_json("s", "p", {})
    assert len(calls) == 1


@pytest.mark.parametrize(
    "response, message",
    [
        (gemini_reply({"a": 1}, finish="MAX_TOKENS"), "stopped early: MAX_TOKENS"),
        (httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}), "blocked: SAFETY"),
        (httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}), "not valid JSON"),
    ],
)
def test_unusable_responses_raise(response, message):
    llm, _ = make_client(lambda request: response)
    with pytest.raises(LLMError, match=message):
        llm.generate_json("s", "p", {})
