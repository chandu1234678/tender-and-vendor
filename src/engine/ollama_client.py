"""LLM client for Ollama or LM Studio (company server).

Engine code imports `ollama_generate` and `is_healthy` from here.
Set LLM_BACKEND=lmstudio and OLLAMA_HOST=http://10.5.65.131:1234 for the
company LM Studio server.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import urllib.error
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── tunables ─────────────────────────────────────────────────────────────────
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://10.5.65.131:1234").rstrip("/")
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "120"))
CACHE_ENABLED = os.environ.get("OLLAMA_CACHE", "1").strip() in {"1", "true", "yes"}
CACHE_MAX = int(os.environ.get("OLLAMA_CACHE_MAX", "2000"))
KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "30m")
NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "1536"))
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "").strip()

_backend = os.environ.get("LLM_BACKEND", "").strip().lower()
if not _backend:
    _backend = "lmstudio" if ":1234" in OLLAMA_HOST else "ollama"
LLM_BACKEND = _backend

JSON_SYSTEM = (
    "You are a procurement compliance assistant. "
    "Respond with valid JSON only — no markdown fences, no analysis, no extra text."
)

# Prefer larger instruct/reasoning models; skip embeddings and tiny models.
_MODEL_PRIORITY = (
    "qwen3.6-35b-a3b",
    "qwen3-30b-a3b-instruct-2507",
    "qwen3.6-27b",
    "minimax-m2.7",
    "gemma-4-31b-it",
    "qwen3.5-9b-sft-claude-opus-reasoning-unsloth",
    "glm-4.7-flash",
    "gemma-4-e4b-it",
    "gemma-4-e2b-it",
    "phi-4-mini-reasoning",
    "phi-3-mini-4k-instruct",
    "nvidia-nemotron-3-nano-4b",
)

# Limit concurrent remote LLM calls (one GPU cannot serve many 35B requests at once).
_LLM_MAX_CONCURRENT = max(
    1,
    int(os.environ.get("LLM_MAX_CONCURRENT", "2" if LLM_BACKEND == "lmstudio" else "4")),
)
_llm_semaphore = threading.Semaphore(_LLM_MAX_CONCURRENT)

# ── module-level state ────────────────────────────────────────────────────────
_lock = threading.Lock()
_cache_lock = threading.Lock()
_client = None
_cache: dict[str, str] = {}
_healthy: Optional[bool] = None
_cached_models: list[str] = []
_resolved_model: Optional[str] = None


def pick_best_model(models: list[str]) -> str:
    """Pick the best available chat model from a server model list."""
    available = {m for m in models if m and "embed" not in m.lower()}
    for preferred in _MODEL_PRIORITY:
        if preferred in available:
            return preferred
    for model_id in sorted(available):
        if "embed" not in model_id.lower():
            return model_id
    return models[0] if models else "qwen3.6-27b"


def default_model() -> str:
    """Resolved model name (env override, else best available on server)."""
    global _resolved_model
    if OLLAMA_MODEL:
        return OLLAMA_MODEL
    if _resolved_model:
        return _resolved_model
    if _cached_models:
        _resolved_model = pick_best_model(_cached_models)
        return _resolved_model
    return "qwen3.6-27b"


def _http_json(method: str, url: str, payload: Optional[dict] = None) -> Any:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _list_models_lmstudio() -> list[str]:
    payload = _http_json("GET", f"{OLLAMA_HOST}/v1/models")
    if isinstance(payload, dict) and "data" in payload:
        return [str(m.get("id", "")) for m in payload["data"] if m.get("id")]
    return []


def _extract_lmstudio_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return str(payload or "").strip()

    # 1) LM Studio "output" list format: prefer all items with type=="message"
    output = payload.get("output")
    if isinstance(output, list):
        msgs: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, str) and content.strip():
                if item.get("type") == "message":
                    msgs.append(content.strip())
        if msgs:
            return msgs[-1]

    # 2) OpenAI-compatible "choices" format
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        # collect all non-empty message.content or text fields
        collected: list[str] = []
        for ch in choices:
            if not isinstance(ch, dict):
                continue
            # message may be under choice['message']
            msg = ch.get("message") or ch.get("delta") or {}
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str) and content.strip():
                    collected.append(content.strip())
                    continue
            text = ch.get("text")
            if isinstance(text, str) and text.strip():
                collected.append(text.strip())
        if collected:
            return collected[-1]

    # 3) Fallback simple keys
    for key in ("content", "response", "text", "result"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    # 4) nested message
    message = payload.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()

    return ""


def _generate_lmstudio(model: str, prompt: str, temperature: float, max_tokens: int) -> Optional[str]:
    # Use the OpenAI-compatible completions endpoint which supports
    # `max_tokens` and predictable response shapes (choices[0].message.content).
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": JSON_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": int(max_tokens) if max_tokens is not None else None,
    }

    try:
        response = _http_json("POST", f"{OLLAMA_HOST}/v1/chat/completions", payload)
        text = _extract_lmstudio_text(response)
        return text or None
    except Exception as exc:
        logger.debug("lmstudio_generate failed (model=%s): %s", model, exc)
        return None


def _get_client():
    global _client
    if _client is not None:
        return _client
    with _lock:
        if _client is not None:
            return _client
        try:
            import ollama

            _client = ollama.Client(host=OLLAMA_HOST, timeout=OLLAMA_TIMEOUT)
            logger.info(
                "Ollama client initialised → %s (timeout=%ss)",
                OLLAMA_HOST,
                OLLAMA_TIMEOUT,
            )
        except Exception as exc:
            logger.warning("Could not create Ollama client: %s", exc)
            _client = None
    return _client


def _list_models_ollama() -> list[str]:
    client = _get_client()
    if client is None:
        return []
    models = client.list()
    return [m.model for m in models.models]


def _generate_ollama(model: str, prompt: str, temperature: float, max_tokens: int) -> Optional[str]:
    client = _get_client()
    if client is None:
        return None
    try:
        response = client.generate(
            model=model,
            prompt=prompt,
            format="json",
            keep_alive=KEEP_ALIVE,
            options={
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": NUM_CTX,
            },
        )
        if hasattr(response, "response"):
            text = response.response
        elif isinstance(response, dict):
            text = str(response.get("response", ""))
        elif hasattr(response, "get"):
            text = str(response.get("response", ""))
        else:
            text = str(response)
        return (text or "").strip() or None
    except Exception as exc:
        logger.debug("ollama_generate failed (model=%s): %s", model, exc)
        return None


def is_healthy() -> bool:
    """Return True if the LLM server is reachable and has at least one model."""
    global _healthy, _cached_models, _resolved_model
    if _healthy is not None:
        return _healthy
    try:
        if LLM_BACKEND == "lmstudio":
            names = _list_models_lmstudio()
        else:
            names = _list_models_ollama()
        _cached_models = names
        _healthy = len(names) > 0
        if _healthy:
            if not OLLAMA_MODEL:
                _resolved_model = pick_best_model(names)
            logger.info(
                "LLM healthy (%s) — models: %s; using %s",
                LLM_BACKEND,
                names,
                default_model(),
            )
        else:
            logger.warning("LLM reachable but no models available at %s", OLLAMA_HOST)
    except Exception as exc:
        logger.warning("LLM health check failed (%s): %s", LLM_BACKEND, exc)
        _healthy = False
    return bool(_healthy)


def _cache_key(model: str, prompt: str) -> str:
    return hashlib.sha256(f"{model}\x00{prompt}".encode()).hexdigest()[:16]


def ollama_generate(
    model: str,
    prompt: str,
    temperature: float = 0.0,
    max_tokens: int = 256,
) -> Optional[str]:
    """Call the configured LLM backend and return response text, or None on failure."""
    if not model:
        model = default_model()

    key = ""
    if CACHE_ENABLED:
        key = _cache_key(model, prompt)
        with _cache_lock:
            if key in _cache:
                return _cache[key]

    with _llm_semaphore:
        if LLM_BACKEND == "lmstudio":
            text = _generate_lmstudio(model, prompt, temperature, max_tokens)
        else:
            text = _generate_ollama(model, prompt, temperature, max_tokens)

    if CACHE_ENABLED and text:
        with _cache_lock:
            if len(_cache) >= CACHE_MAX:
                for k in list(_cache.keys())[: CACHE_MAX // 10]:
                    del _cache[k]
            _cache[key] = text
    return text


def list_models() -> list[str]:
    """Return cached model ids from the last health check, or refresh."""
    global _cached_models
    if _cached_models:
        return list(_cached_models)
    try:
        if LLM_BACKEND == "lmstudio":
            _cached_models = _list_models_lmstudio()
        else:
            _cached_models = _list_models_ollama()
    except Exception:
        pass
    return list(_cached_models)


def reset_health_cache() -> None:
    """Force re-check on next call (useful after server restart)."""
    global _healthy, _client, _cached_models, _resolved_model
    _healthy = None
    _client = None
    _cached_models = []
    _resolved_model = None
    with _cache_lock:
        _cache.clear()
