import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

import weekly_aggrerate_with_abs as weekly


class WeeklyAggregateWindowTest(unittest.TestCase):
    def test_weekly_aggregate_keeps_seven_publication_dates(self):
        run_date = date(2026, 7, 17)

        with tempfile.TemporaryDirectory() as temp_dir:
            original_output_dir = weekly.OUTPUT_DIR
            original_weekly_dir = weekly.WEEKLY_DIR
            try:
                weekly.OUTPUT_DIR = Path(temp_dir) / "output"
                weekly.WEEKLY_DIR = weekly.OUTPUT_DIR / "weekly"
                weekly.WEEKLY_DIR.mkdir(parents=True)

                # Daily files are named after their run date, but their newest
                # publication date is the previous day.
                for offset in range(7):
                    input_date = run_date - timedelta(days=6 - offset)
                    publication_date = input_date - timedelta(days=1)
                    frame = pd.DataFrame(
                        [
                            {
                                "title": f"Paper {offset}",
                                "link": f"https://example.com/paper-{offset}",
                                "source": "Test Journal",
                                "pub_date": f"{publication_date.isoformat()}T12:00:00Z",
                                "abstract": f"Abstract {offset}",
                            }
                        ]
                    )
                    frame.to_csv(
                        weekly.OUTPUT_DIR
                        / f"news_with_abstract_{input_date.isoformat()}.csv",
                        index=False,
                        encoding="utf-8-sig",
                    )

                weekly.aggregate_rolling7_dedupe_by_link(run_date=run_date)

                result = pd.read_csv(
                    weekly.WEEKLY_DIR
                    / f"weekly_news_with_abstract_{run_date.isoformat()}.csv",
                    encoding="utf-8-sig",
                )
                publication_dates = pd.to_datetime(result["pub_date"], utc=True).dt.date

                self.assertEqual(len(result), 7)
                self.assertEqual(publication_dates.min(), run_date - timedelta(days=7))
                self.assertEqual(publication_dates.max(), run_date - timedelta(days=1))
                self.assertEqual(len(set(publication_dates)), 7)
            finally:
                weekly.OUTPUT_DIR = original_output_dir
                weekly.WEEKLY_DIR = original_weekly_dir

    def test_weekly_aggregate_deduplicates_same_doi_with_different_links(self):
        run_date = date(2026, 9, 25)

        with tempfile.TemporaryDirectory() as temp_dir:
            original_output_dir = weekly.OUTPUT_DIR
            original_weekly_dir = weekly.WEEKLY_DIR
            try:
                weekly.OUTPUT_DIR = Path(temp_dir) / "output"
                weekly.WEEKLY_DIR = weekly.OUTPUT_DIR / "weekly"
                weekly.WEEKLY_DIR.mkdir(parents=True)

                rows = [
                    {
                        "title": "Paper",
                        "link": "https://publisher.example/article/one",
                        "source": "Publisher RSS",
                        "pub_date": "2026-09-23T12:00:00Z",
                        "doi": "10.1002/AENM.202506744",
                        "abstract": "",
                    },
                    {
                        "title": "Paper with complete metadata",
                        "link": "https://doi.org/10.1002/aenm.202506744?source=crossref",
                        "source": "Crossref",
                        "pub_date": "2026-09-23T12:00:00Z",
                        "doi": "https://doi.org/10.1002/aenm.202506744.",
                        "abstract": "Complete abstract",
                    },
                ]
                for offset, row in enumerate(rows):
                    input_date = run_date - timedelta(days=offset)
                    pd.DataFrame([row]).to_csv(
                        weekly.OUTPUT_DIR
                        / f"news_with_abstract_{input_date.isoformat()}.csv",
                        index=False,
                        encoding="utf-8-sig",
                    )

                weekly.aggregate_rolling7_dedupe_by_link(run_date=run_date)

                result = pd.read_csv(
                    weekly.WEEKLY_DIR
                    / f"weekly_news_with_abstract_{run_date.isoformat()}.csv",
                    encoding="utf-8-sig",
                )
                self.assertEqual(len(result), 1)
                self.assertEqual(result.iloc[0]["doi"], "10.1002/aenm.202506744")
                self.assertEqual(result.iloc[0]["abstract"], "Complete abstract")
            finally:
                weekly.OUTPUT_DIR = original_output_dir
                weekly.WEEKLY_DIR = original_weekly_dir


if __name__ == "__main__":
    unittest.main()
