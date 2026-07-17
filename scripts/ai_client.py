#!/usr/bin/env python3
"""
ai_client.py — provider-agnostic chat wrapper.

Lets the bot switch between Anthropic (Claude) and NVIDIA NIM
(build.nvidia.com, OpenAI-compatible) without touching call sites.

Provider selection (highest priority first):
  1. explicit `provider` arg to chat()
  2. per-user config.json  {"ai_provider": "anthropic"|"nvidia"}
  3. AI_PROVIDER env var
  4. default "anthropic"

Keys:
  ANTHROPIC_API_KEY   — for provider "anthropic"
  NVIDIA_API_KEY      — for provider "nvidia" (nvapi-...)

Model overrides (env):
  NVIDIA_CHAT_MODEL, NVIDIA_PLAN_MODEL
"""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from strava_api import urlopen_with_retry

PROVIDERS = ("anthropic", "nvidia")
DEFAULT_PROVIDER = "anthropic"

# task -> model per provider. Anthropic ids are the canonical ones used before
# the abstraction existed; NVIDIA ids are OpenAI-style "vendor/model" slugs.
DEFAULT_MODELS = {
    "anthropic": {
        "chat": "claude-sonnet-4-5",
        "plan": "claude-haiku-4-5-20251001",
    },
    "nvidia": {
        "chat": os.environ.get("NVIDIA_CHAT_MODEL", "meta/llama-3.3-70b-instruct"),
        "plan": os.environ.get("NVIDIA_PLAN_MODEL", "meta/llama-3.3-70b-instruct"),
    },
}

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"


def resolve_provider(config: dict | None = None) -> str:
    """Pick provider from per-user config, then env, then default."""
    if config:
        p = str(config.get("ai_provider", "")).lower()
        if p in PROVIDERS:
            return p
    p = os.environ.get("AI_PROVIDER", "").lower()
    return p if p in PROVIDERS else DEFAULT_PROVIDER


def model_for(task: str, provider: str) -> str:
    """Default model id for a task ('chat' | 'plan') under a provider."""
    return DEFAULT_MODELS.get(provider, DEFAULT_MODELS[DEFAULT_PROVIDER]).get(task, "")


def api_key_for(provider: str) -> str:
    if provider == "nvidia":
        return os.environ.get("NVIDIA_API_KEY", "")
    return os.environ.get("ANTHROPIC_API_KEY", "")


def has_key(provider: str) -> bool:
    return bool(api_key_for(provider))


def is_free(provider: str) -> bool:
    """NVIDIA calls are treated as zero-cost for quota purposes."""
    return provider == "nvidia"


def chat(
    provider: str,
    model: str,
    system,
    user_message: str,
    max_tokens: int = 250,
    cache_system: bool = False,
    timeout: int = 60,
) -> dict:
    """
    One chat completion. Returns:
      {"text": str, "input_tokens": int, "output_tokens": int}

    `system` may be a plain string, or (Anthropic only) a list of system blocks
    for prompt caching. For NVIDIA, block lists are flattened to plain text.
    """
    if provider == "nvidia":
        return _nvidia(model, system, user_message, max_tokens, timeout)
    return _anthropic(model, system, user_message, max_tokens, cache_system, timeout)


def _anthropic(model, system, user_message, max_tokens, cache_system, timeout) -> dict:
    payload = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_message}],
    }).encode()
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key_for("anthropic"),
        "anthropic-version": "2023-06-01",
    }
    if cache_system:
        headers["anthropic-beta"] = "prompt-caching-2024-07-31"
    req = urllib.request.Request(ANTHROPIC_URL, data=payload, headers=headers, method="POST")
    data = json.loads(urlopen_with_retry(req, timeout=timeout))
    usage = data.get("usage", {})
    return {
        "text": data["content"][0]["text"],
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
    }


def _nvidia(model, system, user_message, max_tokens, timeout) -> dict:
    if isinstance(system, list):
        system = "\n".join(b.get("text", "") for b in system if isinstance(b, dict))
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_message})
    payload = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }).encode()
    req = urllib.request.Request(
        NVIDIA_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key_for('nvidia')}",
        },
        method="POST",
    )
    data = json.loads(urlopen_with_retry(req, timeout=timeout))
    usage = data.get("usage", {})
    return {
        "text": data["choices"][0]["message"]["content"],
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
    }
