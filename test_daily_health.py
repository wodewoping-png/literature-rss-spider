import csv
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import spider0301
from scripts.check_daily_gaps import expected_dates, validate_daily_file
from scripts.check_nature_sustainability import (
    load_observed_keys,
    missing_items,
    repair_daily_file,
)
from scripts.send_dingtalk_alert import signed_webhook_url


class DailyGapCheckTests(unittest.TestCase):
    def test_expected_dates_are_in_ascending_order(self):
        self.assertEqual(
            expected_dates(date(2026, 8, 21), 3),
            [date(2026, 8, 19), date(2026, 8, 20), date(2026, 8, 21)],
        )

    def test_valid_daily_csv_requires_a_data_row(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            path = output_dir / "news_with_abstract_2026-08-19.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["title", "link", "pub_date"])
                writer.writeheader()
                writer.writerow({"title": "Paper", "link": "https://example.com", "pub_date": "2026-08-18"})

            self.assertEqual(validate_daily_file(output_dir, date(2026, 8, 19)), (True, "ok"))

    def test_header_only_csv_is_a_gap(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            path = output_dir / "news_with_abstract_2026-08-19.csv"
            path.write_text("title,link,pub_date\n", encoding="utf-8")

            self.assertEqual(validate_daily_file(output_dir, date(2026, 8, 19)), (False, "no data rows"))


class BackfillDateTests(unittest.TestCase):
    def test_run_date_override(self):
        with mock.patch.dict(os.environ, {"RUN_DATE": "2026-08-19"}):
            self.assertEqual(spider0301.get_run_date(), date(2026, 8, 19))

    def test_invalid_run_date_is_rejected(self):
        with mock.patch.dict(os.environ, {"RUN_DATE": "08/19/2026"}):
            with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
                spider0301.get_run_date()

    def test_nature_sustainability_uses_seven_day_late_arrival_window(self):
        pub_date = spider0301.datetime(2026, 8, 28, tzinfo=spider0301.timezone.utc)
        with mock.patch.object(spider0301, "today_utc", date(2026, 9, 3)):
            self.assertTrue(
                spider0301.in_feed_date_window(spider0301.NATURE_SUSTAINABILITY_FEED, pub_date)
            )
            self.assertFalse(spider0301.in_feed_date_window("https://example.com/feed", pub_date))

    def test_rss_fetch_tolerates_invalid_utf8_bytes(self):
        response = mock.Mock()
        response.encoding = "utf-8"
        response.content = (
            b"<?xml version='1.0' encoding='UTF-8'?><rss><channel><title>Journal</title>"
            b"<description>Copyright \xa9 publisher</description><item><title>Paper</title>"
            b"<link>https://example.com/paper</link></item></channel></rss>"
        )
        response.raise_for_status.return_value = None
        with mock.patch("spider0301.requests.get", return_value=response):
            parsed = spider0301.parse_rss_feed("https://example.com/feed")
        self.assertEqual(len(parsed.entries), 1)
        self.assertEqual(parsed.entries[0].title, "Paper")


class NatureSustainabilityCoverageTests(unittest.TestCase):
    def test_nonempty_daily_csv_still_reports_missing_source_doi(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            day = date(2026, 9, 2)
            path = output_dir / f"news_with_abstract_{day.isoformat()}.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["title", "link", "source", "pub_date", "doi"])
                writer.writeheader()
                writer.writerow(
                    {
                        "title": "Unrelated paper",
                        "link": "https://example.com/paper",
                        "source": "Other Journal",
                        "pub_date": "2026-09-01 00:00:00+00:00",
                        "doi": "10.1000/example",
                    }
                )

            expected = {
                "doi:10.1038/s41893-026-01932-6": {
                    "doi": "10.1038/s41893-026-01932-6",
                    "title": "Seagrass fisheries",
                }
            }
            observed = load_observed_keys(output_dir, [day])
            self.assertEqual(set(missing_items(expected, observed)), set(expected))

    def test_repair_adds_missing_nature_record_without_replacing_existing_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "news_with_abstract_2026-09-02.csv"
            fields = ["title", "link", "source", "published_str", "pub_date", "doi"]
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow(
                    {
                        "title": "Existing paper",
                        "link": "https://example.com/existing",
                        "source": "Other Journal",
                        "published_str": "2026-09-01 00:00:00 UTC",
                        "pub_date": "2026-09-01 00:00:00+00:00",
                        "doi": "10.1000/existing",
                    }
                )

            item = {
                "title": "Seagrass fisheries",
                "link": "https://www.nature.com/articles/s41893-026-01932-6",
                "source": "Nature Sustainability",
                "published_str": "2026-09-01 00:00:00 UTC",
                "pub_date": "2026-09-01 00:00:00+00:00",
                "doi": "10.1038/s41893-026-01932-6",
                "last_author": "Leanne C. Cullen-Unsworth",
                "abstract": "Abstract text",
                "abstract_source": "rss_nature",
                "must_have_abstract": "0",
            }
            self.assertEqual(repair_daily_file(path, {"doi:10.1038/s41893-026-01932-6": item}), 1)
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[-1]["source"], "Nature Sustainability")


class DingTalkAlertTests(unittest.TestCase):
    @mock.patch("scripts.send_dingtalk_alert.time.time", return_value=1.0)
    def test_signed_webhook_does_not_expose_secret(self, _mock_time):
        url = signed_webhook_url("https://example.com/robot?access_token=token", "secret-value")
        self.assertIn("timestamp=1000", url)
        self.assertIn("&sign=", url)
        self.assertNotIn("secret-value", url)


if __name__ == "__main__":
    unittest.main()
