"""Dispatch with bounded retries for GitHub 429/5xx errors.

Permanent errors (including permission failures) fail immediately. A failed
response can be ambiguous, so downstream jobs must remain idempotent.
"""
import re
import subprocess
import sys
import time


def dispatch(args, run=subprocess.run, sleep=time.sleep):
    for attempt in range(4):
        result = run(
            ["gh", "workflow", "run", *args],
            capture_output=True, text=True,
        )
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        if result.returncode == 0:
            return 0
        transient = re.search(r"HTTP (429|5\d\d)\b", result.stderr or "")
        if not transient or attempt == 3:
            print("::error::Downstream workflow dispatch failed.")
            return result.returncode
        delay = 10 * (2 ** attempt)
        print(f"::warning::GitHub dispatch transient failure; retry in {delay}s")
        sleep(delay)
    return 1


if __name__ == "__main__":
    sys.exit(dispatch(sys.argv[1:]))
