#!/usr/bin/env python3
"""Send a text alert to a DingTalk custom robot webhook."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import time
from urllib import error, parse, request


def signed_webhook_url(webhook: str, secret: str) -> str:
    if not secret:
        return webhook
    timestamp = str(round(time.time() * 1000))
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}\n{secret}".encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    sign = parse.quote_plus(base64.b64encode(digest))
    separator = "&" if "?" in webhook else "?"
    return f"{webhook}{separator}timestamp={timestamp}&sign={sign}"


def send_alert(webhook: str, secret: str, content: str) -> None:
    payload = json.dumps(
        {"msgtype": "text", "text": {"content": content}},
        ensure_ascii=False,
    ).encode("utf-8")
    req = request.Request(
        signed_webhook_url(webhook, secret),
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            body = response.read().decode("utf-8", errors="replace")
    except (error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"DingTalk webhook request failed: {exc}") from exc

    try:
        result = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"DingTalk returned a non-JSON response: {body[:200]}") from exc
    if result.get("errcode", 0) != 0:
        raise RuntimeError(f"DingTalk rejected the alert: {result}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", default="Literature RSS Spider alert")
    parser.add_argument("--message", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    content = f"{args.title}\n{args.message}"
    if args.dry_run:
        print(content)
        return 0

    webhook = os.getenv("DINGTALK_WEBHOOK", "").strip()
    if not webhook:
        raise RuntimeError("DINGTALK_WEBHOOK is not configured")
    send_alert(webhook, os.getenv("DINGTALK_SECRET", "").strip(), content)
    print("DingTalk alert sent successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
