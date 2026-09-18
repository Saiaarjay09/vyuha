"""Model backends. Open-weight only by default.

Vyuha runs entirely on models you can download and host: Llama, Qwen,
DeepSeek, Mistral, Gemma, Phi. There is no hosted-API dependency in the default
path, which matters here for three reasons -- cost at the volume a council
implies, reproducibility of a forecast you may have to defend later, and not
shipping a portfolio's positions to a third party.

Two transports cover essentially every local runtime:

  OllamaProvider     the easy path -- `ollama serve`, `ollama pull qwen2.5:32b`
  OpenAICompatible   llama.cpp --server, vLLM, LM Studio, TGI, or any hosted
                     endpoint speaking the OpenAI schema (OpenRouter, Together,
                     Groq) if you deliberately choose to use one
"""

from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from vyuha.config import settings


@dataclass(slots=True)
class LLMResponse:
    text: str
    model: str
    latency_s: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.text.strip())


class Provider(ABC):
    name: str = "provider"

    @abstractmethod
    def generate(
        self, system: str, user: str, model: str, temperature: float = 0.3,
        max_tokens: int = 1600, json_mode: bool = True,
    ) -> LLMResponse: ...

    @abstractmethod
    def available_models(self) -> list[str]: ...

    def resolve_model(self, preferred: tuple[str, ...] | list[str]) -> str | None:
        """First preferred model that is actually installed.

        Matching is prefix-based so `qwen2.5:32b` matches an installed
        `qwen2.5:32b-instruct-q4_K_M`.
        """
        have = self.available_models()
        for want in preferred:
            for h in have:
                if h == want or h.startswith(want.split(":")[0] + ":") and want.split(":")[-1] in h:
                    return h
            for h in have:
                if h.split(":")[0] == want.split(":")[0]:
                    return h
        return have[0] if have else None


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, host: str | None = None, timeout: float = 300.0):
        self.host = (host or settings.ollama_host).rstrip("/")
        self.timeout = timeout
        self._models: list[str] | None = None

    def available_models(self) -> list[str]:
        if self._models is not None:
            return self._models
        try:
            r = httpx.get(f"{self.host}/api/tags", timeout=10.0)
            r.raise_for_status()
            self._models = [m["name"] for m in r.json().get("models", [])]
        except Exception:
            self._models = []
        return self._models

    def generate(
        self, system: str, user: str, model: str, temperature: float = 0.3,
        max_tokens: int = 1600, json_mode: bool = True,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": model,
            "system": system,
            "prompt": user,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if json_mode:
            payload["format"] = "json"

        t0 = time.perf_counter()
        try:
            r = httpx.post(f"{self.host}/api/generate", json=payload, timeout=self.timeout)
            r.raise_for_status()
            d = r.json()
            return LLMResponse(
                text=d.get("response", ""), model=model,
                latency_s=time.perf_counter() - t0,
                prompt_tokens=d.get("prompt_eval_count"),
                completion_tokens=d.get("eval_count"),
            )
        except Exception as exc:  # noqa: BLE001
            return LLMResponse("", model, time.perf_counter() - t0, error=str(exc))


class OpenAICompatible(Provider):
    name = "openai_compatible"

    def __init__(self, base_url: str, api_key: str = "not-needed", timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._models: list[str] | None = None

    def available_models(self) -> list[str]:
        if self._models is not None:
            return self._models
        try:
            r = httpx.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"}, timeout=10.0,
            )
            r.raise_for_status()
            self._models = [m["id"] for m in r.json().get("data", [])]
        except Exception:
            self._models = []
        return self._models

    def generate(
        self, system: str, user: str, model: str, temperature: float = 0.3,
        max_tokens: int = 1600, json_mode: bool = True,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        t0 = time.perf_counter()
        try:
            r = httpx.post(
                f"{self.base_url}/chat/completions", json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"}, timeout=self.timeout,
            )
            r.raise_for_status()
            d = r.json()
            usage = d.get("usage", {})
            return LLMResponse(
                text=d["choices"][0]["message"]["content"], model=model,
                latency_s=time.perf_counter() - t0,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
            )
        except Exception as exc:  # noqa: BLE001
            return LLMResponse("", model, time.perf_counter() - t0, error=str(exc))


class EchoProvider(Provider):
    """Deterministic stub for tests and CI -- no model, no network.

    Returns a fixed, schema-valid forecast so the whole council pipeline can be
    exercised without a GPU.
    """

    name = "echo"

    def __init__(self, probability: float = 0.5):
        self.probability = probability

    def available_models(self) -> list[str]:
        return ["echo"]

    def generate(self, system, user, model="echo", temperature=0.3, max_tokens=1600, json_mode=True):
        return LLMResponse(
            text=json.dumps({
                "probability": self.probability,
                "confidence": 0.5,
                "reasoning": "stub response from EchoProvider",
                "key_driver": "none",
                "would_change_mind_if": "n/a",
                "citations": [],
            }),
            model=model, latency_s=0.0,
        )


# ------------------------------------------------------------------ JSON rescue

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> tuple[dict | None, str | None]:
    """Pull a JSON object out of a model response.

    Small open models ignore `format: json` often enough that this is not
    optional. Tries, in order: the raw string, a fenced block, the outermost
    brace-balanced span, and finally a few targeted repairs for the mistakes
    these models actually make (trailing commas, single quotes, Python
    True/False/None, unquoted NaN).
    """
    if not text or not text.strip():
        return None, "empty response"

    candidates: list[str] = [text.strip()]
    if m := _FENCE.search(text):
        candidates.append(m.group(1).strip())

    start = text.find("{")
    if start != -1:
        depth, in_str, esc = 0, False, False
        for i, ch in enumerate(text[start:], start):
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
            elif ch == '"':
                in_str = not in_str
            elif not in_str:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidates.append(text[start:i + 1])
                        break

    errors: list[str] = []
    for c in candidates:
        try:
            v = json.loads(c)
            if isinstance(v, dict):
                return v, None
        except json.JSONDecodeError as e:
            errors.append(str(e))
        repaired = re.sub(r",\s*([}\]])", r"\1", c)
        repaired = re.sub(r"\bTrue\b", "true", repaired)
        repaired = re.sub(r"\bFalse\b", "false", repaired)
        repaired = re.sub(r"\b(None|NaN)\b", "null", repaired)
        try:
            v = json.loads(repaired)
            if isinstance(v, dict):
                return v, None
        except json.JSONDecodeError as e:
            errors.append(str(e))

    return None, f"no parseable JSON object ({errors[0] if errors else 'unknown'})"


def default_provider() -> Provider:
    p = OllamaProvider()
    return p if p.available_models() else EchoProvider()
