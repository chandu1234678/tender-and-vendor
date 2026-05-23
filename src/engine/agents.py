from __future__ import annotations

from typing import Any, Dict
import json
import os
import re
import urllib.parse
import urllib.request

from src.engine.prompts import FALLBACK_AGENT_PROMPT, RISK_AGENT_PROMPT, TECHNICAL_AGENT_PROMPT


def _collect_web_search_snippets(query: str, limit: int = 3) -> str:
    """Return short snippets from an optional web search API.

    Supported env vars:
    - WEB_SEARCH_API_URL: JSON endpoint that accepts `?q=` or POST `{query: ...}`.
    - WEB_SEARCH_API_KEY: bearer token or x-api-key depending on provider.
    - WEB_SEARCH_API_HEADER: optional header name, defaults to `Authorization` when a key exists.
    - WEB_SEARCH_API_TIMEOUT: request timeout in seconds.

    If not configured or any request fails, returns an empty string.
    """
    api_url = os.environ.get("WEB_SEARCH_API_URL", "").strip()
    if not api_url:
        return ""

    timeout = float(os.environ.get("WEB_SEARCH_API_TIMEOUT", "10"))
    api_key = os.environ.get("WEB_SEARCH_API_KEY", "").strip()
    header_name = os.environ.get("WEB_SEARCH_API_HEADER", "Authorization").strip() or "Authorization"
    headers = {"Accept": "application/json"}
    if api_key:
        if header_name.lower() == "authorization":
            headers[header_name] = f"Bearer {api_key}"
        else:
            headers[header_name] = api_key

    payload = None
    if "{query}" in api_url:
        url = api_url.format(query=urllib.parse.quote_plus(query))
    else:
        url = f"{api_url}{'&' if '?' in api_url else '?'}q={urllib.parse.quote_plus(query)}"
        payload = json.dumps({"query": query}).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=payload, headers=headers, method="POST" if payload else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
        data = json.loads(body)
    except Exception:
        return ""

    items = data.get("items") or data.get("results") or data.get("data") or []
    snippets = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or "").strip()
        snippet = str(item.get("snippet") or item.get("summary") or item.get("text") or "").strip()
        url_text = str(item.get("url") or item.get("link") or "").strip()
        parts = [part for part in [title, snippet, url_text] if part]
        if parts:
            snippets.append(" | ".join(parts))
    return "\n".join(snippets)


def _heuristic_result(context: str, requirement: str, mode: str) -> Dict[str, Any]:
    text = f"{requirement}\n{context}".lower()
    numbers = re.findall(r"\d+\.?\d*", requirement)
    citation = ""
    status = "NO"
    reasoning = "No matching evidence found."
    confidence = 0.0

    if mode == "risk" and any(word in text for word in ["warranty", "delivery", "penalty", "certificate", "certification"]):
        status = "NEARLY OK"
        reasoning = "Risk-related terms were found and need human review."
        confidence = 0.45
        citation = context[:500]
    elif any(keyword in text for keyword in ["meets", "complies", "supports", "warranty", "guarantee", "certified"]):
        status = "YES"
        reasoning = f"{mode.title()} heuristic found compliance language."
        confidence = 0.78
        citation = context[:500]
    elif numbers and any(number in context for number in numbers):
        status = "NEARLY OK"
        reasoning = "Numeric evidence was found, but strict matching still needs review."
        confidence = 0.58
        citation = context[:500]

    return {"status": status, "citation": citation, "reasoning": reasoning, "confidence": confidence}


def _call_ollama(prompt: str, model_name: str, temperature: float) -> Dict[str, Any] | None:
    try:
        from ollama import generate

        response = generate(model=model_name, prompt=prompt, options={"temperature": temperature})
        text = response.get("response") if isinstance(response, dict) else str(response)
        payload = json.loads(text.strip())
        return {
            "status": payload.get("status", "NO"),
            "citation": payload.get("citation", ""),
            "reasoning": payload.get("reasoning", ""),
            "confidence": float(payload.get("confidence", 0.0)),
        }
    except Exception:
        return None


def _call_grok(prompt: str, model_name: str, temperature: float) -> Dict[str, Any] | None:
    """Call the xAI Grok API using the OpenAI-compatible chat completions format."""
    api_key = os.environ.get("XAI_API_KEY", "").strip()
    if not api_key:
        return None

    base_url = os.environ.get("XAI_API_BASE", "https://api.x.ai/v1").strip().rstrip("/")
    endpoint = f"{base_url}/chat/completions"
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "Return JSON only with keys status, citation, reasoning, confidence."},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=float(os.environ.get("XAI_API_TIMEOUT", "20"))) as response:
            body = response.read().decode("utf-8", errors="replace")
        data = json.loads(body)
        content = data["choices"][0]["message"]["content"]
        payload = json.loads(content.strip())
        return {
            "status": payload.get("status", "NO"),
            "citation": payload.get("citation", ""),
            "reasoning": payload.get("reasoning", ""),
            "confidence": float(payload.get("confidence", 0.0)),
        }
    except Exception:
        return None


def run_technical_agent(context: str, requirement: str = "", model_name: str = "llama3") -> Dict[str, Any]:
    prompt = f"{TECHNICAL_AGENT_PROMPT}\n\nRequirement:\n{requirement}\n\nContext:\n{context}"
    result = _call_ollama(prompt, model_name, 0.0)
    if result:
        return result
    grok_result = _call_grok(prompt, os.environ.get("GROK_MODEL", "grok-2"), 0.0)
    return grok_result or _heuristic_result(context, requirement, "technical")


def run_risk_agent(context: str, requirement: str = "", model_name: str = "llama3") -> Dict[str, Any]:
    prompt = f"{RISK_AGENT_PROMPT}\n\nRequirement:\n{requirement}\n\nContext:\n{context}"
    result = _call_ollama(prompt, model_name, 0.0)
    if result:
        return result
    grok_result = _call_grok(prompt, os.environ.get("GROK_MODEL", "grok-2"), 0.0)
    return grok_result or _heuristic_result(context, requirement, "risk")


def run_fallback_agent(context: str, requirement: str = "", model_name: str = "llama3") -> Dict[str, Any]:
    search_query = f"{requirement} acceptable alternative equivalent vendor specification"
    search_snippets = _collect_web_search_snippets(search_query)
    enriched_context = context if not search_snippets else f"{context}\n\nWeb search evidence:\n{search_snippets}"
    prompt = f"{FALLBACK_AGENT_PROMPT}\n\nRequirement:\n{requirement}\n\nContext:\n{enriched_context}"
    result = _call_ollama(prompt, model_name, 0.1)
    if result:
        return result
    grok_result = _call_grok(prompt, os.environ.get("GROK_MODEL", "grok-2"), 0.1)
    if grok_result:
        return grok_result
    fallback = _heuristic_result(enriched_context, requirement, "fallback")
    if search_snippets and not fallback.get("citation"):
        fallback["citation"] = search_snippets[:500]
        fallback["reasoning"] = f"Fallback used web search evidence for equivalence checking: {fallback['reasoning']}"
    return fallback
