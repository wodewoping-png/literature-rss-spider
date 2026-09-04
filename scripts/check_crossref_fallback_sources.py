#!/usr/bin/env python3
"""Check and optionally repair seven-day DOI coverage for RSS fallback journals."""

from __future__ import annotations

import argparse
import csv
import html
import os
import re
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

import requests

try:
    from scripts.check_nature_sustainability import (
        clean_text,
        date_range,
        load_observed_keys,
        normalize_doi,
        record_key,
        repair_daily_file,
        write_github_outputs,
    )
except ModuleNotFoundError:  # Direct execution: python scripts/check_....py
    from check_nature_sustainability import (
        clean_text,
        date_range,
        load_observed_keys,
        normalize_doi,
        record_key,
        repair_daily_file,
        write_github_outputs,
    )


# One entry per unique journal. The main spider owns the URL-to-journal mapping;
# this compact list independently audits what the fallback discovery channel
# should have contributed during the prior week.
SOURCES = (
    ("0009-2665", "Chemical Reviews", "10.1021/"),
    ("2380-8195", "ACS Energy Letters", "10.1021/"),
    ("0002-7863", "Journal of the American Chemical Society", "10.1021/"),
    ("1944-8244", "ACS Applied Materials & Interfaces", "10.1021/"),
    ("0306-0012", "Chemical Society Reviews", "10.1039/"),
    ("1754-5692", "Energy & Environmental Science", "10.1039/"),
    ("1521-3773", "Angewandte Chemie International Edition", "10.1002/"),
    ("1614-6840", "Advanced Energy Materials", "10.1002/"),
    ("1521-4095", "Advanced Materials", "10.1002/"),
    ("2451-9294", "Chem", "10.1016/"),
    ("2542-4351", "Joule", "10.1016/"),
    ("2590-3322", "One Earth", "10.1016/"),
    ("2590-2385", "Matter", "10.1016/"),
    ("1941-0050", "IEEE Transactions on Industrial Informatics", "10.1109/"),
    ("1949-3037", "IEEE Transactions on Sustainable Energy", "10.1109/"),
    ("1558-0059", "IEEE Transactions on Energy Conversion", "10.1109/"),
    ("1949-3061", "IEEE Transactions on Smart Grid", "10.1109/"),
    ("1558-0679", "IEEE Transactions on Power Systems", "10.1109/"),
    ("1937-4208", "IEEE Transactions on Power Delivery", "10.1109/"),
    ("2375-2548", "Science Advances", "10.1126/"),
    ("0036-8075", "Science", "10.1126/"),
)
RSC_ISSNS = {"0306-0012", "1754-5692"}
DEFAULT_FIELDS = [
    "title",
    "link",
    "source",
    "published_str",
    "pub_date",
    "doi",
    "last_author",
    "abstract",
    "abstract_source",
    "must_have_abstract",
]
DROP_TITLE_KEYWORDS = {
    "editorial",
    "masthead",
    "issue information",
    "publication information",
    "information for authors",
    "society information",
    "table of contents",
    "cover",
}
HEADERS = {
    "User-Agent": "literature-rss-spider/1.0 (mailto:qiaochuzhang@outlook.com)",
    "Accept": "application/json",
}


def parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}; expected YYYY-MM-DD") from exc


def crossref_date(message: dict, preferred_field: str = "") -> datetime | None:
    def parse_parts(value) -> datetime | None:
        try:
            parts = value["date-parts"][0]
            return datetime(
                int(parts[0]),
                int(parts[1]) if len(parts) > 1 else 1,
                int(parts[2]) if len(parts) > 2 else 1,
                tzinfo=timezone.utc,
            )
        except (KeyError, IndexError, TypeError, ValueError):
            return None

    if preferred_field:
        preferred = parse_parts(message.get(preferred_field))
        try:
            has_full_date = len(message.get(preferred_field, {}).get("date-parts", [[]])[0]) >= 3
        except (IndexError, TypeError):
            has_full_date = False
        if preferred and has_full_date:
            return preferred

    for key in ("published-online", "published-print", "issued", "created"):
        parsed = parse_parts(message.get(key))
        if parsed:
            return parsed
    return None


def first_text(value) -> str:
    if isinstance(value, list):
        return next((clean_text(item) for item in value if clean_text(item)), "")
    return clean_text(value)


def title_key(value: str) -> str:
    normalized = re.sub(r"[^0-9a-z]+", " ", clean_text(value).casefold()).strip()
    return f"title:{normalized}" if normalized else ""


def load_observed_aliases(output_dir: Path, days: list[date]) -> set[str]:
    observed = load_observed_keys(output_dir, days)
    for day in days:
        path = output_dir / f"news_with_abstract_{day.isoformat()}.csv"
        if not path.is_file():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                key = title_key(row.get("title", ""))
                if key:
                    observed.add(key)
    return observed


def find_missing(expected: dict[str, dict[str, str]], observed: set[str]) -> dict[str, dict[str, str]]:
    return {
        key: item
        for key, item in expected.items()
        if key not in observed and title_key(item.get("title", "")) not in observed
    }


def last_author(message: dict) -> str:
    authors = message.get("author")
    if not isinstance(authors, list) or not authors:
        return ""
    author = authors[-1]
    if not isinstance(author, dict):
        return ""
    return clean_text(f"{author.get('given', '')} {author.get('family', '')}".strip() or author.get("name", ""))


def fetch_source(
    issn: str,
    journal: str,
    doi_prefix: str,
    start_date: date,
    end_date: date,
) -> dict[str, dict[str, str]]:
    url = f"https://api.crossref.org/journals/{issn}/works"
    use_created_date = issn in RSC_ISSNS
    filter_name = "created-date" if use_created_date else "pub-date"
    sort_name = "created" if use_created_date else "published"
    params = {
        "filter": f"from-{filter_name}:{start_date},until-{filter_name}:{end_date},type:journal-article",
        "rows": 1000,
        "sort": sort_name,
        "order": "desc",
    }
    last_error = ""
    response = None
    for attempt in range(1, 4):
        try:
            response = requests.get(url, params=params, headers=HEADERS, timeout=45)
            response.raise_for_status()
            break
        except Exception as exc:
            response = None
            last_error = str(exc)
            if attempt < 3:
                time.sleep(attempt * 3)
    if response is None:
        raise RuntimeError(f"Crossref query failed for {journal} ({issn}): {last_error}")

    payload = response.json().get("message", {})
    total = int(payload.get("total-results", 0))
    if total > 1000:
        raise RuntimeError(f"Crossref returned {total} recent items for {journal}; rows limit would truncate coverage")

    items: dict[str, dict[str, str]] = {}
    for message in payload.get("items", []):
        doi = normalize_doi(message.get("DOI", ""))
        pub_dt = crossref_date(message, "created" if use_created_date else "")
        title = first_text(message.get("title"))
        if not doi.startswith(doi_prefix.lower()) or not pub_dt:
            continue
        if not start_date <= pub_dt.date() <= end_date:
            continue
        if not title or any(keyword in title.lower() for keyword in DROP_TITLE_KEYWORDS):
            continue
        abstract = clean_text(html.unescape(str(message.get("abstract") or "")))
        link = str(message.get("URL") or f"https://doi.org/{doi}").strip()
        key = record_key(doi, link)
        items[key] = {
            "title": title,
            "link": link,
            "source": first_text(message.get("container-title")) or journal,
            "published_str": pub_dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "pub_date": pub_dt.strftime("%Y-%m-%d %H:%M:%S+00:00"),
            "doi": doi,
            "last_author": last_author(message),
            "abstract": abstract,
            "abstract_source": "crossref" if abstract else "",
            "must_have_abstract": "0",
        }
    return items


def fetch_expected(
    start_date: date,
    end_date: date,
    sources: tuple[tuple[str, str, str], ...] = SOURCES,
) -> dict[str, dict[str, str]]:
    expected: dict[str, dict[str, str]] = {}
    for index, source in enumerate(sources):
        batch = fetch_source(*source, start_date, end_date)
        expected.update(batch)
        print(f"Crossref source {source[1]}: {len(batch)} relevant records")
        if index + 1 < len(sources):
            time.sleep(0.6)
    return expected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--end-date", type=parse_iso_date, required=True)
    parser.add_argument("--repair-date", type=parse_iso_date)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--fail-on-missing", action="store_true")
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument("--only-rsc", action="store_true")
    source_group.add_argument("--exclude-rsc", action="store_true")
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be at least 1")

    days = date_range(args.end_date, args.days)
    github_output = args.github_output or (Path(os.environ["GITHUB_OUTPUT"]) if os.getenv("GITHUB_OUTPUT") else None)
    try:
        sources = SOURCES
        if args.only_rsc:
            sources = tuple(source for source in SOURCES if source[0] in RSC_ISSNS)
        elif args.exclude_rsc:
            sources = tuple(source for source in SOURCES if source[0] not in RSC_ISSNS)
        expected = fetch_expected(days[0], days[-1], sources)
        observed = load_observed_aliases(args.output_dir, days)
        missing = find_missing(expected, observed)
        initially_missing = len(missing)
        added = 0
        if args.repair_date and missing:
            target = args.output_dir / f"news_with_abstract_{args.repair_date.isoformat()}.csv"
            added = repair_daily_file(target, missing)
            observed = load_observed_aliases(args.output_dir, days)
            missing = find_missing(expected, observed)

        missing_dois = " ".join(item["doi"] for item in missing.values())
        missing_counts = Counter(item.get("source") or "unknown" for item in missing.values())
        missing_journals = "; ".join(
            f"{journal}={count}" for journal, count in sorted(missing_counts.items())
        )
        missing_sample = " ".join(item["doi"] for item in list(missing.values())[:20])
        if len(missing) > 20:
            missing_sample += f" ...(+{len(missing) - 20} more)"
        print(
            f"Crossref fallback coverage {days[0]}..{days[-1]}: expected={len(expected)} "
            f"initially_missing={initially_missing} repaired={added} remaining={len(missing)}"
        )
        for item in missing.values():
            print(f"MISSING {item['source']} {item['doi']}: {item['title']}")
        values: dict[str, str | int] = {
            "source_healthy": "true",
            "expected_count": len(expected),
            "initial_missing_count": initially_missing,
            "repaired_count": added,
            "missing_count": len(missing),
            "missing_dois": missing_dois,
            "missing_sample": missing_sample,
            "missing_journals": missing_journals,
            "error": "",
        }
        if github_output:
            write_github_outputs(github_output, values)
        return 1 if args.fail_on_missing and missing else 0
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        print(f"Crossref fallback coverage check failed: {message}")
        if github_output:
            write_github_outputs(
                github_output,
                {
                    "source_healthy": "false",
                    "expected_count": 0,
                    "initial_missing_count": 0,
                    "repaired_count": 0,
                    "missing_count": 1,
                    "missing_dois": "source-check-failed",
                    "missing_sample": "source-check-failed",
                    "missing_journals": "source-check-failed",
                    "error": message,
                },
            )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
