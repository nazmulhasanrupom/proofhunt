"""DeepSeek client (OpenAI-compatible). JSON output, validation, retry, budget."""
import asyncio
import json
import re
from pathlib import Path

from openai import AsyncOpenAI, BadRequestError
from pydantic import BaseModel, ValidationError

from ..config import settings
from . import usage

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
_sem = asyncio.Semaphore(5)
_client: AsyncOpenAI | None = None


def load_prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text()


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not settings.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not set")
        _client = AsyncOpenAI(api_key=settings.deepseek_api_key, base_url="https://api.deepseek.com")
    return _client


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
    model_name = settings.deepseek_model_fast if model == "fast" else settings.deepseek_model_smart
    use_json_mode = True  # if the model rejects JSON mode we drop it below and parse ourselves
    system = system + "\n\nReturn ONLY one valid JSON object. No text outside the JSON."
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    last_err = None
    for attempt in range(2):
        usage.check_llm_budget(run_id)
        kwargs = {"model": model_name, "messages": messages}
        kwargs["temperature"] = temperature
        if use_json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        async with _sem:
            try:
                resp = await _get_client().chat.completions.create(**kwargs)
            except BadRequestError:
                if not use_json_mode:
                    raise
                use_json_mode = False  # model does not accept response_format: ask in the prompt instead
                kwargs.pop("response_format", None)
                resp = await _get_client().chat.completions.create(**kwargs)
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
