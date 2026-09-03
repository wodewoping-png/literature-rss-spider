#!/usr/bin/env python3
"""Check and optionally repair Nature Sustainability coverage in daily CSVs."""

from __future__ import annotations

import argparse
import csv
import html
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import feedparser
import requests


FEED_URL = "https://www.nature.com/natsustain.rss"
SOURCE_NAME = "Nature Sustainability"
DOI_PREFIX = "10.1038/s41893-"
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
RSS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; literature-rss-spider/1.0; +https://github.com/)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}
TAG_RE = re.compile(r"<[^>]+>")
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


def parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}; expected YYYY-MM-DD") from exc


def normalize_doi(value: str) -> str:
    raw = html.unescape(str(value or "")).strip()
    raw = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", raw, flags=re.IGNORECASE)
    match = re.search(r"10\.\d{4,9}/[^\s?#<>]+", raw, flags=re.IGNORECASE)
    return match.group(0).rstrip(".,;)").lower() if match else ""


def normalize_link(value: str) -> str:
    parts = urlsplit(str(value or "").strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, "", ""))


def record_key(doi: str, link: str) -> str:
    normalized_doi = normalize_doi(doi)
    return f"doi:{normalized_doi}" if normalized_doi else f"url:{normalize_link(link)}"


def clean_text(value: str) -> str:
    text = TAG_RE.sub("", html.unescape(str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def entry_date(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime(*parsed[:6], tzinfo=timezone.utc)
    for key in ("published", "updated", "date", "dc_date", "prism_publicationdate"):
        value = str(entry.get(key) or "").strip()
        if not value:
            continue
        try:
            parsed_dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed_dt.astimezone(timezone.utc) if parsed_dt.tzinfo else parsed_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def entry_doi(entry) -> str:
    for key in ("prism_doi", "doi", "dc_identifier", "id", "link"):
        doi = normalize_doi(entry.get(key) or "")
        if doi:
            return doi
    return ""


def entry_abstract(entry) -> str:
    raw = str(entry.get("summary") or entry.get("description") or "")
    if "</p>" in raw.lower():
        raw = re.split(r"</p>", raw, maxsplit=1, flags=re.IGNORECASE)[-1]
    return clean_text(raw)


def entry_last_author(entry) -> str:
    authors = entry.get("authors") or []
    if isinstance(authors, list) and authors:
        last = authors[-1]
        if isinstance(last, dict):
            return clean_text(last.get("name") or "")
    return clean_text(entry.get("author") or "")


def is_direct_nature_feed(url: str) -> bool:
    parts = urlsplit(url)
    return (
        parts.netloc.lower() in {"nature.com", "www.nature.com"}
        and bool(re.fullmatch(r"/[^/]+\.rss", parts.path.lower()))
    )


def fetch_expected_items(
    start_date: date,
    end_date: date,
    feed_url: str = FEED_URL,
    doi_prefix: str = DOI_PREFIX,
    source_name: str | None = SOURCE_NAME,
) -> dict[str, dict[str, str]]:
    last_error = ""
    feed = None
    for attempt in range(1, 4):
        try:
            response = requests.get(feed_url, headers=RSS_HEADERS, timeout=30)
            response.raise_for_status()
            encoding = response.encoding or "utf-8"
            xml_text = response.content.decode(encoding, errors="replace")
            feed = feedparser.parse(xml_text)
            if feed.entries:
                break
            last_error = str(getattr(feed, "bozo_exception", "empty RSS feed"))
        except Exception as exc:
            last_error = str(exc)
        if attempt < 3:
            import time

            time.sleep(attempt)
    if feed is None or not feed.entries:
        raise RuntimeError(f"RSS returned no entries after 3 attempts: {last_error}")

    resolved_source_name = source_name or clean_text(feed.feed.get("title") or feed_url)

    items: dict[str, dict[str, str]] = {}
    for entry in feed.entries:
        pub_dt = entry_date(entry)
        doi = entry_doi(entry)
        title = clean_text(entry.get("title") or "")
        if not pub_dt or not (start_date <= pub_dt.date() <= end_date):
            continue
        if doi_prefix and not doi.startswith(doi_prefix.lower()):
            continue
        if not title or any(keyword in title.lower() for keyword in DROP_TITLE_KEYWORDS):
            continue
        link = normalize_link(entry.get("link") or entry.get("prism_url") or f"https://doi.org/{doi}")
        key = record_key(doi, link)
        items[key] = {
            "title": title,
            "link": link,
            "source": resolved_source_name,
            "published_str": pub_dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "pub_date": pub_dt.strftime("%Y-%m-%d %H:%M:%S+00:00"),
            "doi": doi,
            "last_author": entry_last_author(entry),
            "abstract": entry_abstract(entry),
            "abstract_source": "rss_nature",
            "must_have_abstract": "0",
        }
    return items


def date_range(end_date: date, days: int) -> list[date]:
    return [end_date - timedelta(days=offset) for offset in reversed(range(days))]


def load_observed_keys(output_dir: Path, days: list[date]) -> set[str]:
    observed: set[str] = set()
    for day in days:
        path = output_dir / f"news_with_abstract_{day.isoformat()}.csv"
        if not path.is_file():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                key = record_key(row.get("doi", ""), row.get("link", ""))
                if key not in {"doi:", "url:"}:
                    observed.add(key)
    return observed


def missing_items(expected: dict[str, dict[str, str]], observed: set[str]) -> dict[str, dict[str, str]]:
    return {key: item for key, item in expected.items() if key not in observed}


def repair_daily_file(path: Path, items: dict[str, dict[str, str]]) -> int:
    if not path.is_file():
        raise FileNotFoundError(f"repair target does not exist: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or DEFAULT_FIELDS)
        rows = list(reader)

    for field in DEFAULT_FIELDS:
        if field not in fieldnames:
            fieldnames.append(field)

    existing = {record_key(row.get("doi", ""), row.get("link", "")) for row in rows}
    added = 0
    for key, item in items.items():
        if key in existing:
            continue
        rows.append({field: item.get(field, "") for field in fieldnames})
        existing.add(key)
        added += 1

    if added:
        rows.sort(key=lambda row: row.get("pub_date", ""))
        temp_path = path.with_suffix(path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        temp_path.replace(path)
    return added


def write_github_outputs(path: Path, values: dict[str, str | int]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            safe_value = str(value).replace("\r", " ").replace("\n", " ")
            handle.write(f"{key}={safe_value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--end-date", type=parse_iso_date, required=True)
    parser.add_argument("--repair-date", type=parse_iso_date)
    parser.add_argument("--all-direct-nature", action="store_true")
    parser.add_argument("--feed-list", type=Path, default=Path("feeds1211.txt"))
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--fail-on-missing", action="store_true")
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be at least 1")

    days = date_range(args.end_date, args.days)
    github_output = args.github_output or (Path(os.environ["GITHUB_OUTPUT"]) if os.getenv("GITHUB_OUTPUT") else None)
    try:
        if args.all_direct_nature:
            feed_urls = [
                line.strip()
                for line in args.feed_list.read_text(encoding="utf-8").splitlines()
                if line.strip() and is_direct_nature_feed(line.strip())
            ]
            with ThreadPoolExecutor(max_workers=min(6, max(1, len(feed_urls)))) as pool:
                batches = list(
                    pool.map(
                        lambda url: fetch_expected_items(
                            days[0],
                            days[-1],
                            feed_url=url,
                            doi_prefix="",
                            source_name=None,
                        ),
                        feed_urls,
                    )
                )
            expected = {}
            for batch in batches:
                expected.update(batch)
            coverage_label = f"{len(feed_urls)} direct Nature journals"
        else:
            expected = fetch_expected_items(days[0], days[-1])
            coverage_label = SOURCE_NAME
        observed = load_observed_keys(args.output_dir, days)
        missing = missing_items(expected, observed)
        initially_missing = len(missing)
        added = 0
        if args.repair_date and missing:
            target = args.output_dir / f"news_with_abstract_{args.repair_date.isoformat()}.csv"
            added = repair_daily_file(target, missing)
            observed = load_observed_keys(args.output_dir, days)
            missing = missing_items(expected, observed)

        missing_dois = " ".join(item["doi"] for item in missing.values())
        print(
            f"{coverage_label} coverage {days[0]}..{days[-1]}: "
            f"expected={len(expected)} initially_missing={initially_missing} repaired={added} remaining={len(missing)}"
        )
        for item in missing.values():
            print(f"MISSING {item['doi']}: {item['title']}")
        values: dict[str, str | int] = {
            "source_healthy": "true",
            "expected_count": len(expected),
            "initial_missing_count": initially_missing,
            "repaired_count": added,
            "missing_count": len(missing),
            "missing_dois": missing_dois,
            "error": "",
        }
        if github_output:
            write_github_outputs(github_output, values)
        return 1 if args.fail_on_missing and missing else 0
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        print(f"Nature journal health check failed: {message}")
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
                    "error": message,
                },
            )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
