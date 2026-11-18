import json
import os
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from agent import prompt

client = OpenAI(base_url=os.environ["LLM_URL"], api_key=os.environ["LLM_KEY"], max_retries=4, timeout=60)
model = os.environ.get("LLM_MODEL", "deepseek-flash")
spent = {"in": 0, "hit": 0, "out": 0, "calls": 0}


class Decision(BaseModel):
    language: Literal["nl", "en", "de"]
    category: Literal["bug", "billing", "feature_request", "question", "other"]
    priority: Literal["P1", "P2", "P3", "P4"]
    action: Literal["reply", "handoff", "close"]
    sensitive: Literal["refund", "cancel", "gdpr", "security", "legal", "churn", "none"]
    faq: list[str] = []
    reason: str
    draft_reply: str = ""
    handoff_note: str = ""
    confidence: float = Field(ge=0, le=1)


class Check(BaseModel):
    english: str
    language: Literal["nl", "en", "de"]
    answers: bool
    grounded: bool
    safe: bool
    problems: str = ""


def ask(system, user, shape, tries=2):
    err = None
    for _ in range(tries):
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=1200,
            extra_body={"thinking": {"type": "disabled"}},
        )
        u = r.usage
        hit = getattr(u, "prompt_cache_hit_tokens", 0) or 0
        spent["in"] += u.prompt_tokens - hit
        spent["hit"] += hit
        spent["out"] += u.completion_tokens
        spent["calls"] += 1
        try:
            return shape.model_validate(json.loads(r.choices[0].message.content or ""))
        except (json.JSONDecodeError, ValidationError) as e:
            err = e
    raise ValueError(f"bad model output: {err}")


def decide(t):
    return ask(prompt.decide, prompt.ticket(t), Decision)


def check(t, draft):
    return ask(prompt.check, prompt.review(t, draft), Check)


def cost():
    return (spent["in"] * 0.30 + spent["hit"] * 0.006 + spent["out"] * 1.20) / 1e6
