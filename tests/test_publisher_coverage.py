"""Regression checks for publisher fallbacks and missing-day backfills."""
import ast
import csv
from datetime import date
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import check_crossref_fallback_sources as crossref
from scripts import check_feed_endpoints as feeds
from scripts import check_nature_sustainability as nature


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["title", "link", "doi", "source"])
        writer.writeheader()
        writer.writerows(rows)


class PublisherCoverageTests(unittest.TestCase):
    def test_missing_date_is_backfilled_before_publisher_repair(self):
        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/daily_gap_backfill.yaml").read_text()
        )
        steps = [step["name"] for step in workflow["jobs"]["check-and-backfill"]["steps"]]
        self.assertLess(
            steps.index("Attempt each missing date once"),
            steps.index("Detect direct Nature journal omissions"),
        )
        for publisher in ("RSC", "Cell Press"):
            self.assertLess(
                steps.index("Attempt each missing date once"),
                steps.index(f"Attempt high-priority {publisher} repair once"),
            )

    def test_every_spider_crossref_fallback_is_audited(self):
        tree = ast.parse((ROOT / "spider0301.py").read_text())
        mapping = next(
            node.value for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "CROSSREF_FALLBACK_FEEDS"
                    for t in node.targets)
        )
        configured_issns = {
            ast.literal_eval(value)["issn"] for value in mapping.values
        }
        audited_issns = {issn for issn, _, _ in crossref.SOURCES}
        self.assertEqual(configured_issns, audited_issns)
        urls = (ROOT / "feeds1211.txt").read_text().splitlines()
        feed_fallbacks = {feeds.fallback_issn(url) for url in urls} - {""}
        self.assertEqual(feed_fallbacks, audited_issns)

    def test_late_registered_paper_in_next_output_is_not_missing(self):
        end = date(2026, 11, 15)
        doi = "10.1039/d6ee06785a"
        expected = {"doi:" + doi: {
            "doi": doi, "title": "Energy storage study",
            "source": "Energy & Environmental Science", "link": "https://doi.org/" + doi,
        }}
        with tempfile.TemporaryDirectory() as tempdir:
            out = Path(tempdir)
            write_rows(out / "news_with_abstract_2026-11-15.csv", [])
            write_rows(out / "news_with_abstract_2026-11-16.csv",
                       [dict(title="Energy storage study", link="https://doi.org/" + doi,
                             doi=doi, source="Energy & Environmental Science")])
            args = ["check", "--output-dir", str(out), "--end-date",
                    end.isoformat(), "--days", "1", "--only-rsc", "--fail-on-missing"]
            with patch.object(sys, "argv", args), patch.object(crossref, "fetch_expected",
                    return_value=expected):
                self.assertEqual(crossref.main(), 0)

    def test_nature_paper_in_next_output_is_not_missing(self):
        doi = "10.1038/s41893-026-01984-8"
        expected = {"doi:" + doi: {
            "doi": doi, "title": "Late addition",
            "source": "Nature Sustainability", "link": "https://doi.org/" + doi,
        }}
        with tempfile.TemporaryDirectory() as tempdir:
            out = Path(tempdir)
            write_rows(out / "news_with_abstract_2026-11-16.csv",
                       [dict(title="Late addition", link="https://doi.org/" + doi,
                             doi=doi, source="Nature Sustainability")])
            args = ["check", "--output-dir", str(out), "--end-date",
                    "2026-11-15", "--days", "1", "--fail-on-missing"]
            with patch.object(sys, "argv", args), patch.object(nature, "fetch_expected_items",
                    return_value=expected):
                self.assertEqual(nature.main(), 0)

    def test_missing_paper_is_still_repaired(self):
        doi = "10.1039/d6ee06785a"
        expected = {"doi:" + doi: {
            "doi": doi, "title": "Energy storage study",
            "source": "Energy & Environmental Science", "link": "https://doi.org/" + doi,
        }}
        with tempfile.TemporaryDirectory() as tempdir:
            out = Path(tempdir)
            target = out / "news_with_abstract_2026-11-15.csv"
            write_rows(target, [])
            args = ["check", "--output-dir", str(out), "--end-date", "2026-11-15",
                    "--repair-date", "2026-11-15", "--days", "1",
                    "--only-rsc", "--fail-on-missing"]
            with patch.object(sys, "argv", args), patch.object(crossref, "fetch_expected",
                    return_value=expected):
                self.assertEqual(crossref.main(), 0)
            with target.open(encoding="utf-8-sig") as stream:
                self.assertEqual([row["doi"] for row in csv.DictReader(stream)], [doi])


if __name__ == "__main__":
    unittest.main()
