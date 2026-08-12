"""Small, testable Google AI Studio / Gemini HTTP client.

Production code may call Gemini.  Test and dry-run environments can set
``GEMINI_NETWORK_DISABLED=1`` to make any accidental request fail before a
socket is opened.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Mapping, Sequence


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def build_gemini_client(model: str, api_key: str | None = None) -> dict[str, str]:
    """Build the minimal client configuration used by the classifier."""
    resolved_key = (
        api_key
        or os.getenv("GOOGLE_AI_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or ""
    ).strip()
    if not resolved_key:
        raise RuntimeError(
            "Missing GOOGLE_AI_API_KEY or GEMINI_API_KEY in environment. "
            "For GitHub Actions, add it in repo Settings -> Secrets and variables -> Actions."
        )

    resolved_model = (model or "").strip()
    if not resolved_model:
        raise RuntimeError("Gemini model is empty.")
    return {"api_key": resolved_key, "model": resolved_model}


def generate_content(
    client: Mapping[str, str],
    messages: Sequence[Mapping[str, Any]],
    *,
    base_url: str,
    temperature: float,
    timeout: int,
    json_object: bool = True,
    post: Callable[..., Any] | None = None,
) -> str:
    """Call Gemini and return the first candidate's text.

    ``post`` is injectable for unit tests.  The environment guard is checked
    first, so local/CI tests cannot contact Gemini even if a key is present.
    """
    if _truthy(os.getenv("GEMINI_NETWORK_DISABLED")):
        raise RuntimeError("Gemini network access is disabled for this process.")

    if post is None:
        import requests

        post = requests.post

    system_parts: list[str] = []
    user_parts: list[str] = []
    for message in messages:
        content = str(message.get("content", ""))
        if message.get("role", "user") == "system":
            system_parts.append(content)
        else:
            user_parts.append(content)

    model = client["model"]
    model_path = model if model.startswith("models/") else f"models/{model}"
    url = f"{base_url.rstrip('/')}/{model_path}:generateContent"
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": "\n\n".join(user_parts)}]}],
        "generationConfig": {"temperature": temperature},
    }
    if system_parts:
        payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
    if json_object:
        payload["generationConfig"]["responseMimeType"] = "application/json"

    response = post(
        url,
        headers={"Content-Type": "application/json", "x-goog-api-key": client["api_key"]},
        json=payload,
        timeout=timeout,
    )
    try:
        response.raise_for_status()
    except Exception as exc:
        status = getattr(response, "status_code", "unknown")
        body = getattr(response, "text", "")
        raise RuntimeError(f"Gemini API HTTP {status}: {body[:1000]}") from exc

    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError(
            f"Gemini API returned no candidates: {json.dumps(data, ensure_ascii=False)[:1000]}"
        )
    parts = candidates[0].get("content", {}).get("parts") or []
    text = "".join(str(part.get("text", "")) for part in parts).strip()
    if not text:
        raise RuntimeError(
            f"Gemini API returned empty content: {json.dumps(data, ensure_ascii=False)[:1000]}"
        )
    return text
