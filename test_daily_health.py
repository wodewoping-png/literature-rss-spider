import csv
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import spider0301
from scripts.check_daily_gaps import expected_dates, validate_daily_file
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


class DingTalkAlertTests(unittest.TestCase):
    @mock.patch("scripts.send_dingtalk_alert.time.time", return_value=1.0)
    def test_signed_webhook_does_not_expose_secret(self, _mock_time):
        url = signed_webhook_url("https://example.com/robot?access_token=token", "secret-value")
        self.assertIn("timestamp=1000", url)
        self.assertIn("&sign=", url)
        self.assertNotIn("secret-value", url)


if __name__ == "__main__":
    unittest.main()
