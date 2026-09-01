"""Thin LLM client supporting two wire formats.

``MT_LLM_API_FORMAT`` selects ``openai-compatible`` or ``anthropic``. Old
model-id routing remains as a migration fallback: ``ark:`` and slash-bearing
ids use the compatible channel, while a bare id uses Anthropic.

Network failures (this machine reaches providers through a local proxy that
can flap) surface as LLMUnavailable so endpoints can answer with an explicit,
user-facing state instead of a bare 500."""
import json
from collections.abc import Iterator

import anthropic
import httpx

from memtranslator.config import project_env

_client: anthropic.Anthropic | None = None
_or_client: httpx.Client | None = None

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
ARK_BASE_DEFAULT = "https://ark.cn-beijing.volces.com/api/coding/v3"

# Reasoning tokens bill against max_tokens on both channels; a thinking
# writer needs headroom or content starves (measured on ling: 1024 budget,
# ~1100 reasoning tokens, empty content on every call).
THINK_HEADROOM = 2500
# glm-5.x on Ark Coding Plan rejects thinking.type=disabled and still
# thinks when the field is omitted. A large translator prompt spent
# ~2700 completion tokens on reasoning before any JSON; 700 starved
# content to empty (finish=length). 4000 still left most E1 gold
# stores unparseable (185/209). Cap is the only lever; 10000 headroom
# left 55/209 empty, so the translator budget is a flat 12000.
GLM_MAX_TOKENS = 12000


def _is_glm(model: str) -> bool:
    name = model.split(":")[-1].removesuffix(":think").lower()
    return name.startswith("glm")


def budget_for(model: str, base: int) -> int:
    """Output budget for `model`: base, plus headroom when the model will
    spend completion tokens on reasoning before content."""
    if _is_glm(model):
        return GLM_MAX_TOKENS
    return base + (THINK_HEADROOM if model.endswith(":think") else 0)

# Reasoning is OFF by default on this channel. Measured on ling-3.0-flash:
# the model spends 1000-1200 reasoning tokens on every call regardless of
# prompt size, OpenRouter bills them against max_tokens, and our output
# floor is 1024 — so the budget is exhausted before a single content token
# is emitted (finish_reason=length, empty content) even on a 900-token
# prompt. Backbone evaluations flip this flag; the product does not.
OPENROUTER_REASONING = False


class LLMUnavailable(Exception):
    """The model endpoint could not be reached (network/proxy down)."""


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        kwargs = {"api_key": (project_env("LLM_API_KEY")
                              or project_env("ANTHROPIC_API_KEY"))}
        base_url = (project_env("LLM_BASE_URL")
                    or project_env("ANTHROPIC_BASE_URL"))
        if base_url:
            kwargs["base_url"] = base_url
        _client = anthropic.Anthropic(**kwargs)
    return _client


def reset_clients() -> None:
    """Drop cached provider clients after a live settings change."""
    global _client, _or_client
    for client in (_client, _or_client):
        close = getattr(client, "close", None)
        if close is not None:
            try:
                close()
            except Exception:
                pass
    _client = None
    _or_client = None


def _openrouter_complete(model: str, system: str, user: str,
                         max_tokens: int, temperature: float | None) -> str:
    key = (project_env("LLM_API_KEY")
           or project_env("OPENROUTER_API_KEY"))
    if not key:
        raise LLMUnavailable("LLM_API_KEY not set")
    base = (project_env("LLM_BASE_URL")
            or project_env("OPENROUTER_BASE_URL", OPENROUTER_BASE))
    return _compatible_complete(
        model, base, key, system, user, max_tokens, temperature)


def _compatible_extra(model: str, base: str, thinking: bool,
                      ark_compatible: bool = False) -> dict:
    lowered = base.casefold()
    if (ark_compatible or "volces.com" in lowered
            or "volcengine" in lowered):
        if _is_glm(model):
            return {"thinking": {"type": "enabled"}}
        return {"thinking": {
            "type": "enabled" if thinking else "disabled"}}
    if "openrouter.ai" in lowered and not OPENROUTER_REASONING:
        return {"reasoning": {"enabled": False}}
    return {}


def _compatible_complete(model: str, base: str, key: str, system: str,
                         user: str, max_tokens: int,
                         temperature: float | None,
                         thinking: bool = False,
                         ark_compatible: bool = False) -> str:
    global _or_client
    if _or_client is None:
        _or_client = httpx.Client(timeout=300)
    payload = {"model": model, "max_tokens": max_tokens,
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": user}],
               **_compatible_extra(
                   model, base, thinking, ark_compatible)}
    if temperature is not None:
        payload["temperature"] = temperature
    try:
        resp = _or_client.post(f"{base.rstrip('/')}/chat/completions",
                               headers={"Authorization": f"Bearer {key}"},
                               json=payload)
    except httpx.HTTPError as e:
        raise LLMUnavailable("connection") from e
    if resp.status_code != 200:
        # Keep the server's explanation — a bare status once sent a session
        # chasing a prompt bug when the cause was quota.
        raise LLMUnavailable(
            f"status:{resp.status_code} {resp.text[:200]}")
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as e:
        raise LLMUnavailable(f"malformed response {str(data)[:200]}") from e


def _ark_complete(model: str, system: str, user: str,
                  max_tokens: int, temperature: float | None,
                  thinking: bool) -> str:
    """Ark (Volcano) OpenAI-compatible channel — the 2026-07-31 main-model
    ruling: deepseek-v4-flash, thinking disabled on the latency-bound read
    path, enabled where the caller says so (the write path is async, its
    latency is free)."""
    key = project_env("LLM_API_KEY") or project_env("ARK_API_KEY")
    if not key:
        raise LLMUnavailable("LLM_API_KEY not set")
    base = project_env("LLM_BASE_URL", ARK_BASE_DEFAULT)
    return _compatible_complete(
        model, base, key, system, user, max_tokens, temperature, thinking,
        ark_compatible=True)


def _api_format(model: str) -> str:
    configured = project_env("MT_LLM_API_FORMAT").strip().casefold()
    if configured in {"openai-compatible", "anthropic"}:
        return configured
    return ("openai-compatible"
            if model.startswith("ark:") or "/" in model else "anthropic")


def _compatible_connection(model: str) -> tuple[str, str]:
    key = project_env("LLM_API_KEY")
    base = project_env("LLM_BASE_URL")
    if model.startswith("ark:"):
        return (key or project_env("ARK_API_KEY"),
                base or project_env("ARK_BASE_URL") or ARK_BASE_DEFAULT)
    if "/" in model:
        return (key or project_env("OPENROUTER_API_KEY"),
                base or project_env("OPENROUTER_BASE_URL")
                or OPENROUTER_BASE)
    return key, base or ARK_BASE_DEFAULT


def complete(model: str, system: str, user: str, max_tokens: int = 1024,
             temperature: float | None = None) -> str:
    """One-shot completion. `temperature=None` leaves the SDK default (1.0);
    product paths pass an explicit value — see config.GEN_TEMPERATURE.

    ``MT_LLM_API_FORMAT`` routes the channel. Legacy model-id inference remains
    for old stores, and the ``:think`` suffix still enables reasoning on
    compatible endpoints that support it."""
    if _api_format(model) == "openai-compatible":
        rest = (model.removeprefix("ark:")
                .removeprefix("openrouter:"))
        thinking = rest.endswith(":think")
        if thinking:
            rest = rest[:-len(":think")]
        key, base = _compatible_connection(model)
        if not key:
            raise LLMUnavailable("LLM_API_KEY not set")
        return _compatible_complete(
            rest, base, key, system, user, max_tokens, temperature, thinking,
            ark_compatible=model.startswith("ark:"))
    extra = {} if temperature is None else {"temperature": temperature}
    try:
        resp = _get_client().messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            **extra,
        )
    except anthropic.APIConnectionError as e:
        raise LLMUnavailable("connection") from e
    except anthropic.APIStatusError as e:
        # Keep the server's explanation: "400" alone sent a debugging session
        # chasing a prompt bug when the real cause was an exhausted balance.
        detail = getattr(getattr(e, "body", None), "get", lambda _k: None)("error")
        why = (detail or {}).get("message") if isinstance(detail, dict) else None
        raise LLMUnavailable(
            f"status:{e.status_code} {why or str(e)[:200]}") from e
    return "".join(b.text for b in resp.content if b.type == "text")


def stream_text(model: str, system: str, messages: list[dict],
                max_tokens: int = 2048,
                temperature: float | None = None) -> Iterator[str]:
    global _or_client
    if _api_format(model) == "openai-compatible":
        rest = (model.removeprefix("ark:")
                .removeprefix("openrouter:"))
        thinking = rest.endswith(":think")
        if thinking:
            rest = rest[:-len(":think")]
        key, base = _compatible_connection(model)
        if not key:
            raise LLMUnavailable("LLM_API_KEY not set")
        yield from _compatible_stream(
            rest, base, key, system, messages, max_tokens,
            extra=_compatible_extra(
                rest, base, thinking, model.startswith("ark:")),
            temperature=temperature)
        return
    extra = {} if temperature is None else {"temperature": temperature}
    try:
        with _get_client().messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            **extra,
        ) as stream:
            yield from stream.text_stream
    except anthropic.APIConnectionError as e:
        raise LLMUnavailable("connection") from e
    except anthropic.APIStatusError as e:
        # Keep the server's explanation: "400" alone sent a debugging session
        # chasing a prompt bug when the real cause was an exhausted balance.
        detail = getattr(getattr(e, "body", None), "get", lambda _k: None)("error")
        why = (detail or {}).get("message") if isinstance(detail, dict) else None
        raise LLMUnavailable(
            f"status:{e.status_code} {why or str(e)[:200]}") from e


def _compatible_stream(model: str, base: str, key: str, system: str,
                       messages: list[dict], max_tokens: int,
                       extra: dict | None = None,
                       temperature: float | None = None) -> Iterator[str]:
    """Stream text from an OpenAI-compatible chat-completions endpoint."""
    global _or_client
    if _or_client is None:
        _or_client = httpx.Client(timeout=180)
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "stream": True,
        "messages": [{"role": "system", "content": system}, *messages],
        **(extra or {}),
    }
    if temperature is not None:
        payload["temperature"] = temperature
    try:
        with _or_client.stream(
                "POST", f"{base.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json=payload) as response:
            if response.status_code != 200:
                response.read()
                raise LLMUnavailable(
                    f"status:{response.status_code} "
                    f"{response.text[:200]}")
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[len("data: "):]
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                    content = event["choices"][0]["delta"].get("content")
                except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                    continue
                if isinstance(content, str) and content:
                    yield content
    except LLMUnavailable:
        raise
    except httpx.HTTPError as e:
        raise LLMUnavailable("connection") from e
