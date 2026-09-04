# -*- coding: utf-8 -*-
"""Make one minimal authenticated GLM request against every configured route."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zai_client import (
    DEFAULT_FALLBACK_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_PRIMARY_BASE_URL,
    DEFAULT_SECONDARY_BASE_URL,
    ZAIChatClient,
    ZAIEndpoint,
)


def main() -> int:
    api_key = os.getenv("ZAI_API_KEY", "").strip()
    if not api_key:
        print("[probe] ZAI_API_KEY is not configured", flush=True)
        return 2

    endpoints = [
        ZAIEndpoint("z.ai-openai", DEFAULT_PRIMARY_BASE_URL, "openai", api_key),
        ZAIEndpoint("bigmodel-openai", DEFAULT_SECONDARY_BASE_URL, "openai", api_key),
        ZAIEndpoint("bigmodel-anthropic", DEFAULT_FALLBACK_BASE_URL, "anthropic", api_key),
    ]
    messages = [
        {"role": "system", "content": "Return only valid JSON."},
        {"role": "user", "content": 'Return exactly {"ok":true}.'},
    ]

    success_count = 0
    for endpoint in endpoints:
        client = ZAIChatClient(
            endpoints=[endpoint],
            model=os.getenv("ZAI_MODEL", DEFAULT_MODEL),
            timeout=int(os.getenv("ZAI_TIMEOUT", "60")),
            max_tokens=64,
            temperature=0,
        )
        try:
            content = client.generate(messages, json_object=True)
            success_count += 1
            print(f"[probe] {endpoint.name}: OK response={content[:200]!r}", flush=True)
        except Exception as exc:
            print(f"[probe] {endpoint.name}: FAILED {exc}", flush=True)

    print(f"[probe] successful routes: {success_count}/{len(endpoints)}", flush=True)
    return 0 if success_count else 1


if __name__ == "__main__":
    sys.exit(main())
