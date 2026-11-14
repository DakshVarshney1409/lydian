"""
Model providers for the judge.

Lydian is not tied to one model vendor. The judge needs exactly one thing from a
provider: send a system prompt and a user prompt, get text back. Two backends
cover almost everything:

  anthropic   Anthropic's Messages API.
  openai      Any OpenAI-compatible chat-completions endpoint: OpenAI itself,
              and via LYDIAN_BASE_URL also Ollama, vLLM, LM Studio, OpenRouter,
              Groq, Together, DeepSeek, Mistral, Gemini's compatibility endpoint,
              and most self-hosted servers.

Configuration (environment, .env, or run_experiment.py flags):

  LYDIAN_PROVIDER      anthropic | openai            (default: anthropic)
  LYDIAN_JUDGE_MODEL   model name                     (required for openai)
  LYDIAN_JUDGE_EFFORT  reasoning effort, e.g. high    (optional)
  LYDIAN_BASE_URL      endpoint for OpenAI-compatible servers (optional)

API keys use each SDK's usual variable: ANTHROPIC_API_KEY or OPENAI_API_KEY. A
local server reached through LYDIAN_BASE_URL needs no key.

Only the SDK for the provider you use has to be installed.

To add a provider, write a class with a `name` and a `complete(system, prompt)`
method that returns (text, refused), and register it in PROVIDERS.
"""

import os

DEFAULT_MODELS = {"anthropic": "claude-sonnet-5"}
DEFAULT_EFFORT = {"anthropic": "high"}


class AnthropicProvider:
    name = "anthropic"
    # Models that accept the server-side refusal fallback parameter.
    _FALLBACK_OK = ("claude-fable-5", "claude-mythos-5", "claude-opus-5")

    def __init__(self, model, effort=None, base_url=None):
        try:
            from anthropic import Anthropic
        except ImportError:
            raise SystemExit("Provider 'anthropic' needs its SDK: pip install anthropic")
        self.model, self.effort = model, effort
        self.client = Anthropic(base_url=base_url) if base_url else Anthropic()

    def complete(self, system, prompt):
        kwargs = dict(model=self.model, max_tokens=8000, system=system,
                      messages=[{"role": "user", "content": prompt}])
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        if self.model.startswith(self._FALLBACK_OK):
            # On a policy decline the request is re-run on a fallback model inside
            # the same call, so one refusal does not punch a hole in the run.
            msg = self.client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
        else:
            msg = self.client.messages.create(**kwargs)
        text = "".join(b.text for b in msg.content if b.type == "text")
        return text, getattr(msg, "stop_reason", None) == "refusal"


class OpenAICompatibleProvider:
    name = "openai"

    def __init__(self, model, effort=None, base_url=None):
        try:
            from openai import OpenAI
        except ImportError:
            raise SystemExit("Provider 'openai' needs its SDK: pip install openai")
        self.model, self.effort = model, effort
        kwargs = {}
        if base_url:
            kwargs["base_url"] = base_url
            # Local servers ignore the key, but the SDK insists one is set.
            kwargs["api_key"] = os.environ.get("OPENAI_API_KEY") or "not-needed"
        self.client = OpenAI(**kwargs)

    def complete(self, system, prompt):
        kwargs = dict(model=self.model,
                      messages=[{"role": "system", "content": system},
                                {"role": "user", "content": prompt}])
        if self.effort:
            # Only reasoning models accept this, so it is sent only when asked for.
            kwargs["reasoning_effort"] = self.effort
        resp = self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        return msg.content or "", bool(getattr(msg, "refusal", None))


PROVIDERS = {p.name: p for p in (AnthropicProvider, OpenAICompatibleProvider)}


def resolve(provider=None, model=None, effort=None, base_url=None):
    """Fill in anything not given from the environment and per-provider defaults.
    Returns a dict describing the judge, so results can record exactly what ran."""
    provider = (provider or os.environ.get("LYDIAN_PROVIDER") or "anthropic").lower()
    if provider not in PROVIDERS:
        raise SystemExit(f"Unknown provider '{provider}'. "
                         f"Choose one of: {', '.join(PROVIDERS)}.")
    model = model or os.environ.get("LYDIAN_JUDGE_MODEL") or DEFAULT_MODELS.get(provider)
    if not model:
        raise SystemExit(f"Provider '{provider}' has no default model. "
                         "Set LYDIAN_JUDGE_MODEL or pass --model.")
    effort = effort or os.environ.get("LYDIAN_JUDGE_EFFORT") or DEFAULT_EFFORT.get(provider)
    base_url = base_url or os.environ.get("LYDIAN_BASE_URL") or None
    return dict(provider=provider, model=model, effort=effort, base_url=base_url)


def check_credentials(cfg):
    """Fail early, with a useful message, instead of 108 identical API errors."""
    if cfg["base_url"]:
        return  # custom endpoint: may legitimately need no key
    var = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}[cfg["provider"]]
    key = os.environ.get(var, "")
    if not key or "REPLACE_ME" in key:
        raise SystemExit(f"No {var} found for provider '{cfg['provider']}'.\n"
                         f"Put it in the .env file next to this script:\n"
                         f"    {var}=...\n"
                         f"or export it in your shell.")


def make(cfg):
    return PROVIDERS[cfg["provider"]](cfg["model"], cfg["effort"], cfg["base_url"])
