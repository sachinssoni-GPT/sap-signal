"""Centralized CrewAI LLM configuration.

Precedence: MODEL_<ROLE> environment variable > models[role] in config.yaml > MODEL.
A bare model name is interpreted as an OpenAI model; provider/model is passed through.
"""
import os
import re

from crewai import LLM

from ..config import get_config


def _resolve_model(role: str) -> str:
    models = get_config()["models"]
    name = os.environ.get(f"MODEL_{role.upper()}") or models.get(role) or os.environ.get("MODEL")
    if not name:
        raise RuntimeError(
            f"No model configured for role '{role}'. Set models.{role} in config.yaml "
            f"or MODEL_{role.upper()} in .env."
        )
    name = name.strip()
    return name if "/" in name else f"openai/{name}"


_REASONING = re.compile(r"(^|/)(gpt-([5-9]|[1-9]\d)|o[1-9])", re.I)


def is_reasoning_model(model: str) -> bool:
    """GPT-5+ (incl. GPT-6) and o-series: never send `temperature` (reasoning models reject it); send
    `reasoning_effort` instead. CrewAI drops reasoning_effort automatically if a model rejects it."""
    return bool(_REASONING.search(model))


def _effort(cfg: dict, role: str) -> str:
    e = cfg.get("reasoning_effort", "low")
    if isinstance(e, dict):
        return str(e.get(role, e.get("default", "low")))
    return str(e)


def make_llm(role: str, creative: bool = False) -> LLM:
    cfg = get_config()["models"]
    if role not in cfg:
        raise KeyError(f"Unknown LLM role '{role}'. Configure it under models in config.yaml.")
    model = _resolve_model(role)
    # A hung API call must never freeze the daily run: every request has a deadline and bounded retries.
    common = dict(model=model, timeout=float(cfg.get("request_timeout_s", 180)),
                  max_retries=int(cfg.get("max_retries", 2)))
    if is_reasoning_model(model):
        return LLM(**common, reasoning_effort=_effort(cfg, role))
    temperature_key = "temperature_creative" if creative else "temperature_factual"
    return LLM(**common, temperature=float(cfg[temperature_key]))
