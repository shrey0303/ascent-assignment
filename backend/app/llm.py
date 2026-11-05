"""OpenAI-compatible chat-completions client (Groq, OpenRouter, vLLM, Ollama ...).

Switching provider or model is configuration only: LLM_BASE_URL, LLM_MODEL, LLM_API_KEY and
the two price settings used for the spend report.
"""
import time
from dataclasses import dataclass

import httpx

from . import config

_RETRY_STATUS = {429, 500, 502, 503}


class LLMError(Exception):
    pass


@dataclass
class LLMResult:
    message: dict
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int


def chat(messages: list[dict], tools: list[dict] | None = None, json_mode: bool = False) -> LLMResult:
    if not config.LLM_API_KEY:
        raise LLMError("LLM_API_KEY is not set")
    body = {"model": config.LLM_MODEL, "messages": messages, "temperature": 0}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if config.LLM_REASONING_EFFORT:
        body["reasoning_effort"] = config.LLM_REASONING_EFFORT

    attempts = 4
    for attempt in range(attempts):
        started = time.perf_counter()
        try:
            response = httpx.post(
                f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
                timeout=config.LLM_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            if attempt == attempts - 1:
                raise LLMError(f"LLM request failed: {exc}") from exc
            time.sleep(2 ** attempt)
            continue
        if response.status_code in _RETRY_STATUS and attempt < attempts - 1:
            wait = float(response.headers.get("retry-after", 2 ** attempt))
            if wait <= config.LLM_MAX_RETRY_WAIT_SECONDS:  # never hold a chat open for a daily-cap wait
                time.sleep(wait)
                continue
        if response.status_code >= 400:
            raise LLMError(f"LLM error {response.status_code}: {response.text[:300]}")
        data = response.json()
        usage = data.get("usage") or {}
        tokens_in, tokens_out = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        return LLMResult(
            message=data["choices"][0]["message"],
            model=data.get("model", config.LLM_MODEL),
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            cost_usd=(tokens_in * config.LLM_PRICE_IN_PER_M + tokens_out * config.LLM_PRICE_OUT_PER_M) / 1e6,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
    raise LLMError("LLM request failed after retries")
