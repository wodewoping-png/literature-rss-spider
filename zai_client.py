# -*- coding: utf-8 -*-
"""Small resilient client for Z.AI GLM text generation.

The primary route uses Z.AI's general OpenAI-compatible API, which the
official documentation recommends for custom applications. If that route
fails, requests try BigModel's OpenAI-compatible API and then its
Anthropic-compatible API.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import requests


DEFAULT_MODEL = "glm-5.2"
DEFAULT_PRIMARY_BASE_URL = "https://api.z.ai/api/paas/v4"
DEFAULT_SECONDARY_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_FALLBACK_BASE_URL = "https://open.bigmodel.cn/api/anthropic"


@dataclass(frozen=True)
class ZAIEndpoint:
    name: str
    base_url: str
    protocol: str
    api_key: str


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def endpoints_from_env() -> List[ZAIEndpoint]:
    api_key = _env("ZAI_API_KEY")
    endpoints: List[ZAIEndpoint] = []

    if api_key:
        endpoints.append(
            ZAIEndpoint(
                name="z.ai",
                base_url=_env("ZAI_BASE_URL", DEFAULT_PRIMARY_BASE_URL).rstrip("/"),
                protocol=_env("ZAI_PROTOCOL", "openai").lower(),
                api_key=api_key,
            )
        )
        endpoints.append(
            ZAIEndpoint(
                name="bigmodel-openai",
                base_url=_env("BIGMODEL_BASE_URL", DEFAULT_SECONDARY_BASE_URL).rstrip("/"),
                protocol="openai",
                api_key=api_key,
            )
        )
        endpoints.append(
            ZAIEndpoint(
                name="bigmodel-anthropic",
                base_url=_env("ZAI_FALLBACK_BASE_URL", DEFAULT_FALLBACK_BASE_URL).rstrip("/"),
                protocol=_env("ZAI_FALLBACK_PROTOCOL", "anthropic").lower(),
                api_key=api_key,
            )
        )

    if not endpoints:
        raise RuntimeError(
            "Missing ZAI_API_KEY. Add ZAI_API_KEY to "
            "GitHub repository Settings -> Secrets and variables -> Actions."
        )
    return endpoints


def _join_url(base_url: str, suffix: str) -> str:
    suffix = suffix.lstrip("/")
    if base_url.rstrip("/").endswith("/" + suffix):
        return base_url.rstrip("/")
    return f"{base_url.rstrip('/')}/{suffix}"


def _split_system_messages(messages: Iterable[Dict[str, Any]]) -> tuple[str, List[Dict[str, str]]]:
    systems: List[str] = []
    regular: List[Dict[str, str]] = []
    for message in messages:
        role = str(message.get("role", "user"))
        content = str(message.get("content", ""))
        if role == "system":
            systems.append(content)
        else:
            regular.append({"role": role, "content": content})
    return "\n\n".join(systems), regular


class ZAIChatClient:
    def __init__(
        self,
        endpoints: Optional[List[ZAIEndpoint]] = None,
        model: str = DEFAULT_MODEL,
        timeout: int = 180,
        max_tokens: int = 8192,
        temperature: float = 0.0,
    ) -> None:
        self.endpoints = endpoints if endpoints is not None else endpoints_from_env()
        self.model = model.strip() or DEFAULT_MODEL
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature

    def generate(self, messages: List[Dict[str, Any]], json_object: bool = True) -> str:
        errors: List[str] = []
        for endpoint in self.endpoints:
            try:
                if endpoint.protocol == "openai":
                    return self._call_openai(endpoint, messages, json_object)
                if endpoint.protocol == "anthropic":
                    return self._call_anthropic(endpoint, messages)
                raise RuntimeError(f"unsupported protocol: {endpoint.protocol}")
            except Exception as exc:
                errors.append(f"{endpoint.name}: {exc}")
                print(f"[zai] endpoint {endpoint.name} failed; trying next route: {exc}", flush=True)
        raise RuntimeError("All Z.AI endpoints failed: " + " | ".join(errors))

    def _call_openai(
        self,
        endpoint: ZAIEndpoint,
        messages: List[Dict[str, Any]],
        json_object: bool,
    ) -> str:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "thinking": {"type": "disabled"},
        }
        if json_object:
            payload["response_format"] = {"type": "json_object"}

        response = requests.post(
            _join_url(endpoint.base_url, "chat/completions"),
            headers={
                "Authorization": f"Bearer {endpoint.api_key}",
                "Content-Type": "application/json",
                "Accept-Language": "en-US,en",
            },
            json=payload,
            timeout=self.timeout,
        )
        self._raise_for_status(response, endpoint)
        data = response.json()
        choices = data.get("choices") or []
        content = choices[0].get("message", {}).get("content", "") if choices else ""
        if not str(content).strip():
            raise RuntimeError(f"empty OpenAI-compatible response: {json.dumps(data, ensure_ascii=False)[:1000]}")
        return str(content).strip()

    def _call_anthropic(self, endpoint: ZAIEndpoint, messages: List[Dict[str, Any]]) -> str:
        system, regular_messages = _split_system_messages(messages)
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": regular_messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if system:
            payload["system"] = system

        response = requests.post(
            _join_url(endpoint.base_url, "v1/messages"),
            headers={
                "x-api-key": endpoint.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        self._raise_for_status(response, endpoint)
        data = response.json()
        blocks = data.get("content") or []
        content = "".join(
            str(block.get("text", ""))
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
        if not content:
            raise RuntimeError(f"empty Anthropic-compatible response: {json.dumps(data, ensure_ascii=False)[:1000]}")
        return content

    @staticmethod
    def _raise_for_status(response: requests.Response, endpoint: ZAIEndpoint) -> None:
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            body = response.text[:1000]
            raise RuntimeError(f"{endpoint.name} HTTP {response.status_code}: {body}") from exc
