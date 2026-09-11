# -*- coding: utf-8 -*-
"""Check GLM Coding Plan quota and decide whether a deferred job may run.

The quota endpoint and raw Authorization header follow Z.AI's official
``glm-plan-usage`` plugin.  New and legacy quota payloads are both accepted.
If the monitor response cannot be understood, one tiny request against the
Coding Plan endpoint is used as a conservative availability probe.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


QUOTA_URLS = (
    "https://api.z.ai/api/monitor/usage/quota/limit",
    "https://api.z.ai/api/monitor/usage",
)
CODING_PROBE_URL = "https://api.z.ai/api/coding/paas/v4/chat/completions"
MODEL_LIMIT_TYPES = {"TOKENS_LIMIT", "CREDIT_LIMIT"}


@dataclass(frozen=True)
class QuotaWindow:
    label: str
    used_percent: float
    remaining: Optional[float]
    reset_at: str


@dataclass(frozen=True)
class QuotaDecision:
    ready: bool
    reason: str
    session: Optional[QuotaWindow]
    weekly: Optional[QuotaWindow]


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _reset_iso(value: Any) -> str:
    numeric = _number(value)
    if numeric is None:
        return str(value).strip() if value else ""
    # Current payloads use epoch milliseconds; tolerate epoch seconds too.
    seconds = numeric / 1000 if numeric > 10_000_000_000 else numeric
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return ""


def _limits_from_payload(payload: Any) -> List[Dict[str, Any]]:
    value = payload
    if isinstance(value, dict) and "data" in value:
        value = value["data"]
    if isinstance(value, dict):
        value = value.get("limits")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _used_percent(item: Dict[str, Any]) -> Optional[float]:
    limit = _number(item.get("usage"))
    current = _number(item.get("currentValue"))
    remaining = _number(item.get("remaining"))
    if limit is not None and limit > 0:
        if current is not None:
            return max(0.0, min(100.0, current / limit * 100.0))
        if remaining is not None:
            return max(0.0, min(100.0, (limit - remaining) / limit * 100.0))
    percentage = _number(item.get("percentage"))
    if percentage is not None:
        return max(0.0, min(100.0, percentage))
    return None


def _window(item: Dict[str, Any]) -> Optional[Tuple[int, QuotaWindow]]:
    if str(item.get("type", "")).upper() not in MODEL_LIMIT_TYPES:
        return None
    used = _used_percent(item)
    if used is None:
        return None

    unit = int(_number(item.get("unit")) or 0)
    number = int(_number(item.get("number")) or 0)
    if unit == 3:  # hours in the provider payload
        duration_minutes = number * 60
        label = f"{number}-hour" if number else "hourly"
    elif unit == 6:  # weeks in the provider payload
        duration_minutes = number * 7 * 24 * 60
        label = "weekly" if number == 1 else f"{number}-week"
    else:
        duration_minutes = 10**9
        label = f"unit-{unit}-{number}"

    return duration_minutes, QuotaWindow(
        label=label,
        used_percent=used,
        remaining=_number(item.get("remaining")),
        reset_at=_reset_iso(item.get("nextResetTime")),
    )


def evaluate_quota(
    payload: Any,
    session_max_used_percent: float = 15.0,
    weekly_max_used_percent: float = 95.0,
) -> Optional[QuotaDecision]:
    """Return a decision, or ``None`` when the payload is not recognizable."""

    parsed = [result for item in _limits_from_payload(payload) if (result := _window(item))]
    if not parsed:
        return None
    parsed.sort(key=lambda value: value[0])
    session = parsed[0][1]
    weekly = parsed[-1][1] if len(parsed) > 1 else None

    session_empty = session.remaining is not None and session.remaining <= 0
    weekly_empty = weekly is not None and weekly.remaining is not None and weekly.remaining <= 0
    if session_empty or session.used_percent >= 100:
        return QuotaDecision(False, "5-hour Coding Plan window is exhausted", session, weekly)
    if weekly and (weekly_empty or weekly.used_percent >= weekly_max_used_percent):
        return QuotaDecision(False, "weekly Coding Plan window is too low", session, weekly)
    if session.used_percent > session_max_used_percent:
        return QuotaDecision(False, "waiting for a fresh 5-hour Coding Plan window", session, weekly)
    return QuotaDecision(True, "Coding Plan quota is fresh enough", session, weekly)


def _request_json(url: str, api_key: str, timeout: int) -> Any:
    last_error: Optional[Exception] = None
    # The official plugin uses the raw key. Bearer is a compatibility fallback
    # for deployments that enforce the public API authentication convention.
    for authorization in (api_key, f"Bearer {api_key}"):
        request = Request(
            url,
            headers={
                "Authorization": authorization,
                "Accept-Language": "en-US,en",
                "Content-Type": "application/json",
                "User-Agent": "literature-rss-spider-zai-quota-monitor/1.0",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                parsed = json.loads(response.read().decode("utf-8"))
                if (
                    isinstance(parsed, dict)
                    and parsed.get("success") is False
                    and _number(parsed.get("code")) in (401, 403)
                ):
                    last_error = RuntimeError(f"application error {parsed.get('code')}")
                    continue
                return parsed
        except HTTPError as exc:
            last_error = exc
            if exc.code not in (401, 403):
                break
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            break
    raise RuntimeError(f"quota request failed: {last_error}")


def query_quota(api_key: str, timeout: int = 20) -> Tuple[Optional[QuotaDecision], str]:
    errors: List[str] = []
    session_max = float(os.getenv("ZAI_SESSION_MAX_USED_PERCENT", "15"))
    weekly_max = float(os.getenv("ZAI_WEEKLY_MAX_USED_PERCENT", "95"))
    for url in QUOTA_URLS:
        try:
            payload = _request_json(url, api_key, timeout)
            decision = evaluate_quota(payload, session_max, weekly_max)
            if decision is not None:
                return decision, url
            errors.append(f"{url}: no recognized model quota window")
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    print("[quota] monitor inconclusive: " + " | ".join(errors), flush=True)
    return None, ""


def probe_coding_endpoint(api_key: str, timeout: int = 30) -> bool:
    payload = json.dumps(
        {
            "model": os.getenv("ZAI_MODEL", "glm-5.2"),
            "messages": [{"role": "user", "content": "Reply OK."}],
            "temperature": 0,
            "max_tokens": 8,
            "thinking": {"type": "disabled"},
        }
    ).encode("utf-8")
    request = Request(
        CODING_PROBE_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept-Language": "en-US,en",
            "Content-Type": "application/json",
            "User-Agent": "literature-rss-spider-zai-quota-monitor/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            response.read()
            return response.status == 200
    except (HTTPError, URLError, TimeoutError) as exc:
        status = getattr(exc, "code", "network-error")
        print(f"[quota] minimal Coding Plan probe unavailable: HTTP {status}", flush=True)
        return False


def _write_outputs(values: Dict[str, str]) -> None:
    path = os.getenv("GITHUB_OUTPUT", "").strip()
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def main() -> int:
    api_key = os.getenv("ZAI_API_KEY", "").strip()
    if not api_key:
        print("[quota] ZAI_API_KEY is not configured", flush=True)
        _write_outputs({"ready": "false", "reason": "missing API key", "source": "none"})
        return 2

    decision, source = query_quota(api_key)
    if decision is None:
        ready = probe_coding_endpoint(api_key)
        reason = "minimal Coding Plan request succeeded" if ready else "quota and model probes unavailable"
        _write_outputs({"ready": str(ready).lower(), "reason": reason, "source": "model-probe"})
        print(f"[quota] ready={str(ready).lower()} source=model-probe reason={reason}", flush=True)
        return 0 if ready else 2

    session = decision.session
    weekly = decision.weekly
    outputs = {
        "ready": str(decision.ready).lower(),
        "reason": decision.reason,
        "source": source,
        "session_used_percent": f"{session.used_percent:.1f}" if session else "",
        "weekly_used_percent": f"{weekly.used_percent:.1f}" if weekly else "",
        "next_reset_time": session.reset_at if session else "",
    }
    _write_outputs(outputs)
    print(
        "[quota] "
        f"ready={outputs['ready']} session_used={outputs['session_used_percent']}% "
        f"weekly_used={outputs['weekly_used_percent'] or 'unknown'}% "
        f"reset={outputs['next_reset_time'] or 'unknown'} reason={decision.reason}",
        flush=True,
    )
    # A depleted or partly used window is an expected monitor state, not a
    # workflow failure.  The ``ready`` output controls whether retry is sent.
    return 0


if __name__ == "__main__":
    sys.exit(main())
