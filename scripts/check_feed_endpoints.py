#!/usr/bin/env python3
"""Check every configured RSS endpoint and its configured fallback channel."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import feedparser
import requests


RSS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; literature-rss-spider/1.0; +https://github.com/)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}
CROSSREF_HEADERS = {"User-Agent": "literature-rss-spider/1.0"}
RSC_FALLBACKS = {
    "http://feeds.rsc.org/rss/cs": "0306-0012",
    "http://feeds.rsc.org/rss/ee": "1754-5692",
}
EXPLICIT_FALLBACKS = {
    "https://onlinelibrary.wiley.com/feed/15213773/most-recent": ("1521-3773", "10.1002"),
    "https://advanced.onlinelibrary.wiley.com/feed/16146840/most-recent": ("1614-6840", "10.1002"),
    "https://advanced.onlinelibrary.wiley.com/feed/15214095/most-recent": ("1521-4095", "10.1002"),
    "https://www.cell.com/chem/inpress.rss": ("2451-9294", "10.1016"),
    "https://www.cell.com/joule/inpress.rss": ("2542-4351", "10.1016"),
    "https://www.cell.com/oneear/inpress.rss": ("2590-3322", "10.1016"),
    "https://www.cell.com/matter/inpress.rss": ("2590-2385", "10.1016"),
    "https://ieeexplore.ieee.org/rss/toc9424.xml": ("1941-0050", "10.1109"),
    "https://ieeexplore.ieee.org/rss/toc5165391.xml": ("1949-3037", "10.1109"),
    "https://ieeexplore.ieee.org/rss/toc60.xml": ("1558-0059", "10.1109"),
    "https://ieeexplore.ieee.org/rss/toc5165411.xml": ("1949-3061", "10.1109"),
    "https://ieeexplore.ieee.org/rss/toc59.xml": ("1558-0679", "10.1109"),
    "https://ieeexplore.ieee.org/rss/toc61.xml": ("1937-4208", "10.1109"),
    "https://www.science.org/action/showfeed?type=etoc&feed=rss&jc=sciadv": ("2375-2548", "10.1126"),
    "https://www.science.org/action/showfeed?type=etoc&feed=rss&jc=science": ("0036-8075", "10.1126"),
}
ACS_ISSNS = {
    "chreay": "0009-2665",
    "aelccp": "2380-8195",
    "jacsat": "0002-7863",
    "aamick": "1944-8244",
}
RSC_MAX_STALENESS_DAYS = 30
NATURE_MAX_STALENESS_DAYS = 21


def parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}; expected YYYY-MM-DD") from exc


def entry_date(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime(*parsed[:6], tzinfo=timezone.utc)
    for key in ("published", "updated", "date", "dc_date", "prism_publicationdate"):
        raw = str(entry.get(key) or "").strip()
        if not raw:
            continue
        try:
            parsed_dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed_dt = parsedate_to_datetime(raw)
            except (TypeError, ValueError):
                continue
        return parsed_dt.astimezone(timezone.utc) if parsed_dt.tzinfo else parsed_dt.replace(tzinfo=timezone.utc)
    return None


def fallback_issn(url: str) -> str:
    normalized = url.rstrip("/").lower()
    if normalized in EXPLICIT_FALLBACKS:
        return EXPLICIT_FALLBACKS[normalized][0]
    if normalized in RSC_FALLBACKS:
        return RSC_FALLBACKS[normalized]
    parts = urlsplit(url)
    if parts.netloc.lower() == "pubs.acs.org":
        journal_code = (parse_qs(parts.query).get("jc") or [""])[0].lower()
        return ACS_ISSNS.get(journal_code, "")
    return ""


def fallback_prefix(url: str) -> str:
    normalized = url.rstrip("/").lower()
    if normalized in EXPLICIT_FALLBACKS:
        return EXPLICIT_FALLBACKS[normalized][1]
    if normalized in RSC_FALLBACKS:
        return "10.1039"
    if urlsplit(url).netloc.lower() == "pubs.acs.org" and fallback_issn(url):
        return "10.1021"
    return ""


def is_direct_nature_feed(url: str) -> bool:
    parts = urlsplit(url)
    return (
        parts.netloc.lower() in {"nature.com", "www.nature.com"}
        and bool(re.fullmatch(r"/[^/]+\.rss", parts.path.lower()))
    )


def crossref_available(prefix: str = "") -> tuple[bool, str]:
    last_error = ""
    for attempt in range(1, 4):
        try:
            response = requests.get(
                "https://api.crossref.org/works",
                params={"rows": 0},
                headers=CROSSREF_HEADERS,
                timeout=30,
            )
            response.raise_for_status()
            return True, "Crossref API reachable"
        except Exception as exc:
            last_error = str(exc)
            if attempt < 3:
                time.sleep(attempt * 2)
    return False, f"Crossref API failed after 3 attempts: {last_error}"


def rsc_crossref_recent(issn: str, end_date: date) -> tuple[bool, str]:
    start_date = end_date - timedelta(days=14)
    last_error = ""
    for attempt in range(1, 4):
        try:
            response = requests.get(
                f"https://api.crossref.org/journals/{issn}/works",
                params={
                    "filter": (
                        f"from-created-date:{start_date},until-created-date:{end_date},"
                        "type:journal-article"
                    ),
                    "rows": 0,
                },
                headers=CROSSREF_HEADERS,
                timeout=30,
            )
            response.raise_for_status()
            count = int(response.json().get("message", {}).get("total-results", 0))
            if count:
                return True, f"Crossref has {count} RSC records created in the last 14 days"
            return False, "Crossref returned zero RSC records created in the last 14 days"
        except Exception as exc:
            last_error = str(exc)
            if attempt < 3:
                time.sleep(attempt * 2)
    return False, f"RSC Crossref coverage query failed after 3 attempts: {last_error}"


def fetch_feed(url: str) -> tuple[list, str, str]:
    last_error = ""
    for attempt in range(1, 4):
        try:
            response = requests.get(url, headers=RSS_HEADERS, timeout=25)
            response.raise_for_status()
            xml_text = response.content.decode(response.encoding or "utf-8", errors="replace")
            parsed = feedparser.parse(xml_text)
            if parsed.entries:
                return list(parsed.entries), str(parsed.feed.get("title") or url), ""
            last_error = str(getattr(parsed, "bozo_exception", "RSS returned no entries"))
        except Exception as exc:
            last_error = str(exc)
        if attempt < 3:
            time.sleep(attempt)
    return [], url, last_error or "RSS returned no entries"


def check_one(
    url: str,
    end_date: date,
    fallback_status: dict[str, tuple[bool, str]] | None = None,
) -> dict[str, str | int]:
    entries, title, error = fetch_feed(url)
    newest = max((dt for dt in (entry_date(entry) for entry in entries) if dt), default=None)
    stale_limit = 0
    if url.rstrip("/").lower() in RSC_FALLBACKS:
        stale_limit = RSC_MAX_STALENESS_DAYS
    elif is_direct_nature_feed(url):
        stale_limit = NATURE_MAX_STALENESS_DAYS

    problem = error
    if not problem and stale_limit:
        if newest is None:
            problem = "RSS entries have no parseable dates"
        else:
            age = (end_date - newest.date()).days
            if age > stale_limit:
                problem = f"RSS is stale by {age} days (limit {stale_limit})"

    status = "ok"
    fallback_note = ""
    if problem:
        prefix = fallback_prefix(url)
        if prefix:
            normalized = url.rstrip("/").lower()
            if normalized in RSC_FALLBACKS:
                available, fallback_note = rsc_crossref_recent(RSC_FALLBACKS[normalized], end_date)
            else:
                available, fallback_note = (
                    fallback_status[prefix]
                    if fallback_status is not None and prefix in fallback_status
                    else crossref_available(prefix)
                )
            status = "fallback_ok" if available else "unhealthy"
        else:
            status = "unhealthy"

    return {
        "url": url,
        "title": title,
        "status": status,
        "entries": len(entries),
        "newest": newest.date().isoformat() if newest else "",
        "problem": problem,
        "fallback": fallback_note,
    }


def write_github_outputs(path: Path, values: dict[str, str | int]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            safe_value = str(value).replace("\r", " ").replace("\n", " ")
            handle.write(f"{key}={safe_value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed-list", type=Path, default=Path("feeds1211.txt"))
    parser.add_argument("--end-date", type=parse_iso_date, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--fail-on-unhealthy", action="store_true")
    args = parser.parse_args()
    urls = [line.strip() for line in args.feed_list.read_text(encoding="utf-8").splitlines() if line.strip()]

    # Every configured fallback uses the same Crossref service. Probe it once
    # to avoid self-inflicted 429 responses on shared GitHub runner IPs.
    fallback_status: dict[str, tuple[bool, str]] = {}
    prefixes = sorted({fallback_prefix(url) for url in urls} - {""})
    if prefixes:
        crossref_status = crossref_available()
        fallback_status = {prefix: crossref_status for prefix in prefixes}

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        results = list(pool.map(lambda url: check_one(url, args.end_date, fallback_status), urls))

    unhealthy = [result for result in results if result["status"] == "unhealthy"]
    fallback = [result for result in results if result["status"] == "fallback_ok"]
    for result in results:
        print(
            f"{str(result['status']).upper()} entries={result['entries']} newest={result['newest'] or '-'} "
            f"{result['url']} {result['problem']} {result['fallback']}".rstrip()
        )

    values: dict[str, str | int] = {
        "checked_count": len(results),
        "unhealthy_count": len(unhealthy),
        "unhealthy_feeds": " ".join(str(result["url"]) for result in unhealthy),
        "fallback_count": len(fallback),
        "fallback_feeds": " ".join(str(result["url"]) for result in fallback),
        "details_json": json.dumps(results, ensure_ascii=True, separators=(",", ":")),
    }
    github_output = args.github_output or (Path(os.environ["GITHUB_OUTPUT"]) if os.getenv("GITHUB_OUTPUT") else None)
    if github_output:
        write_github_outputs(github_output, values)

    print(f"Feed health summary: checked={len(results)} fallback={len(fallback)} unhealthy={len(unhealthy)}")
    return 1 if args.fail_on_unhealthy and unhealthy else 0


if __name__ == "__main__":
    raise SystemExit(main())
