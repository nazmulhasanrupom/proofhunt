"""LLM client (OpenAI-compatible). Tries agy, then apifree, then paid DeepSeek. JSON output, validation, retry, budget."""
import asyncio
import json
import logging
import re
import time
from pathlib import Path

from openai import AsyncOpenAI, BadRequestError
from pydantic import BaseModel, ValidationError

from ..config import settings
from . import usage

log = logging.getLogger(__name__)

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
_sem = asyncio.Semaphore(5)
_clients: dict[str, AsyncOpenAI] = {}
_down_until: dict[str, float] = {}   # provider name -> time until we skip it after a failure
COOLDOWN = 60.0


def load_prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text()


def _providers(kind: str) -> list[dict]:
    """In order: free providers first, paid DeepSeek last. Providers with no key or model are left out."""
    chain = [
        {"name": "agy", "base_url": settings.agy_base_url, "api_key": settings.agy_api_key,
         "model": settings.agy_model, "free": True},
        {"name": "apifree", "base_url": settings.apifree_base_url, "api_key": settings.apifree_api_key,
         "model": settings.apifree_model, "free": True},
        {"name": "deepseek", "base_url": "https://api.deepseek.com", "api_key": settings.deepseek_api_key,
         "model": settings.deepseek_model_fast if kind == "fast" else settings.deepseek_model_smart,
         "free": False},
    ]
    return [p for p in chain if p["api_key"] and p["model"]]


def _get_client(p: dict) -> AsyncOpenAI:
    c = _clients.get(p["name"])
    if c is None:
        # Free providers: no hidden retries, so a failure moves on to the next provider fast.
        extra = {"timeout": 120.0, "max_retries": 0} if p["free"] else {}
        c = _clients[p["name"]] = AsyncOpenAI(api_key=p["api_key"], base_url=p["base_url"], **extra)
    return c


async def _create(kind: str, kwargs: dict):
    """Call each provider in order. Return the first answer. Raise the last error if all fail."""
    chain = _providers(kind)
    if not chain:
        raise RuntimeError("No LLM provider is set (need DEEPSEEK_API_KEY, AGY_API_KEY or APIFREE_API_KEY)")
    now = time.monotonic()
    # A provider that just failed is skipped for a while, but never the last one.
    ready = [p for p in chain if _down_until.get(p["name"], 0) <= now] or chain[-1:]
    last_err: Exception | None = None
    for p in ready:
        call = {**kwargs, "model": p["model"]}
        try:
            try:
                resp = await _get_client(p).chat.completions.create(**call)
            except BadRequestError:
                if "response_format" not in call:
                    raise
                call.pop("response_format")  # no JSON mode here: the prompt already asks for JSON
                kwargs.pop("response_format", None)
                resp = await _get_client(p).chat.completions.create(**call)
            if not resp.choices:
                raise RuntimeError("empty answer")
            return resp
        except Exception as e:
            last_err = e
            if p["free"]:
                _down_until[p["name"]] = time.monotonic() + COOLDOWN
            log.warning("LLM provider %s failed (%s: %s). Trying next.", p["name"], type(e).__name__, str(e)[:200])
    raise last_err


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


async def complete_json(task: str, model: str, system: str, user: str,
                        schema_model: type[BaseModel], run_id: str | None = None,
                        temperature: float = 0.1) -> dict:
    """model: 'fast' or 'smart'. Long fixed text goes in `system`, changing data in `user`."""
    system = system + "\n\nReturn ONLY one valid JSON object. No text outside the JSON."
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    last_err = None
    for attempt in range(2):
        usage.check_llm_budget(run_id)
        kwargs = {"messages": messages, "temperature": temperature,
                  "response_format": {"type": "json_object"}}
        async with _sem:
            resp = await _create(model, kwargs)
        u = resp.usage
        tin, tout = (u.prompt_tokens, u.completion_tokens) if u else (0, 0)
        await asyncio.to_thread(usage.add_usage, 0, 1, tin, tout, 0)
        await asyncio.to_thread(usage.bump_run, run_id, 0, 1, tin, tout)
        content = resp.choices[0].message.content or ""
        try:
            return schema_model.model_validate(_parse_json(content)).model_dump()
        except (json.JSONDecodeError, ValidationError) as e:
            last_err = e
            messages = messages + [
                {"role": "assistant", "content": content},
                {"role": "user", "content": f"Your JSON was invalid: {str(e)[:500]}. Return corrected JSON only."},
            ]
    raise ValueError(f"{task}: LLM output invalid after retry: {str(last_err)[:300]}")
