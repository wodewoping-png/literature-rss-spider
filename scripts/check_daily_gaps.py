#!/usr/bin/env python3
"""Validate that each expected daily RSS CSV exists and contains records."""

from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


EXPECTED_COLUMNS = {"title", "link", "pub_date"}


def parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}; expected YYYY-MM-DD") from exc


def expected_dates(end_date: date, days: int) -> list[date]:
    return [end_date - timedelta(days=offset) for offset in reversed(range(days))]


def validate_daily_file(output_dir: Path, day: date) -> tuple[bool, str]:
    path = output_dir / f"news_with_abstract_{day.isoformat()}.csv"
    if not path.is_file():
        return False, "missing"
    if path.stat().st_size == 0:
        return False, "empty file"

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = set(reader.fieldnames or [])
            missing_columns = sorted(EXPECTED_COLUMNS - columns)
            if missing_columns:
                return False, f"missing columns: {','.join(missing_columns)}"
            if next(reader, None) is None:
                return False, "no data rows"
    except (OSError, UnicodeError, csv.Error) as exc:
        return False, f"unreadable CSV: {exc}"

    return True, "ok"


def write_github_outputs(path: Path, missing: list[str], details: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"missing_dates={' '.join(missing)}\n")
        handle.write(f"missing_count={len(missing)}\n")
        handle.write(f"details_json={json.dumps(details, ensure_ascii=False, separators=(',', ':'))}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--end-date", type=parse_iso_date)
    parser.add_argument("--dates", nargs="*", type=parse_iso_date)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--fail-on-gap", action="store_true")
    args = parser.parse_args()

    if args.days < 1:
        parser.error("--days must be at least 1")
    if args.dates is not None and args.end_date is not None:
        parser.error("--dates and --end-date cannot be used together")

    end_date = args.end_date or datetime.now(timezone.utc).date()
    days = args.dates if args.dates is not None else expected_dates(end_date, args.days)

    details: dict[str, str] = {}
    missing: list[str] = []
    for day in days:
        ok, reason = validate_daily_file(args.output_dir, day)
        label = day.isoformat()
        details[label] = reason
        print(f"{'OK' if ok else 'GAP'} {label}: {reason}")
        if not ok:
            missing.append(label)

    github_output = args.github_output
    if github_output is None and os.getenv("GITHUB_OUTPUT"):
        github_output = Path(os.environ["GITHUB_OUTPUT"])
    if github_output is not None:
        write_github_outputs(github_output, missing, details)

    if missing:
        print(f"Missing/invalid daily outputs: {' '.join(missing)}")
    else:
        print("All expected daily outputs are present and non-empty.")
    return 1 if missing and args.fail_on_gap else 0


if __name__ == "__main__":
    raise SystemExit(main())
