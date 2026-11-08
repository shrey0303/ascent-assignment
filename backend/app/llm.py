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


def chat(messages: list[dict], tools: list[dict] | None = None, json_mode: bool = False, *,
         model: str | None = None, temperature: float | None = 0, reasoning_effort: str | None = None,
         prices: tuple[float, float] | None = None, attempts: int = 4,
         base_url: str | None = None, api_key: str | None = None, max_tokens: int | None = None) -> LLMResult:
    """Defaults are the agent model's settings; the classifier passes its own model, sampling and prices,
    and the injection scan its own endpoint, key and output cap. attempts: tries in total; per-minute rate
    limits are waited out, a daily cap fails at once."""
    base_url, api_key = base_url or config.LLM_BASE_URL, api_key or config.LLM_API_KEY
    if not api_key:
        raise LLMError("LLM_API_KEY is not set")
    body = {"model": model or config.LLM_MODEL, "messages": messages,
            "max_tokens": max_tokens or config.LLM_MAX_OUTPUT_TOKENS}
    if config.LLM_PROVIDER and base_url == config.LLM_BASE_URL:
        body["provider"] = {"order": [config.LLM_PROVIDER], "allow_fallbacks": False}
    if temperature is not None:
        body["temperature"] = temperature
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    effort = config.LLM_REASONING_EFFORT if reasoning_effort is None else reasoning_effort
    if effort:
        body["reasoning_effort"] = effort
    price_in, price_out = prices or (config.LLM_PRICE_IN_PER_M, config.LLM_PRICE_OUT_PER_M)

    for attempt in range(attempts):
        started = time.perf_counter()
        try:
            response = httpx.post(
                f"{base_url.rstrip('/')}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=config.LLM_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            if attempt == attempts - 1:
                raise LLMError(f"LLM request failed: {exc}") from exc
            time.sleep(min(2 ** attempt, 30))
            continue
        if response.status_code in _RETRY_STATUS and attempt < attempts - 1:
            wait = float(response.headers.get("retry-after", min(2 ** attempt, 30)))
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
            model=data.get("model", body["model"]),
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            cost_usd=(tokens_in * price_in + tokens_out * price_out) / 1e6,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
    raise LLMError("LLM request failed after retries")
