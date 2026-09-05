from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import openpyxl
import pandas as pd

from monthly_literature_stats import (
    daily_classified_files_for_month,
    fill_sheet,
    normalize_source,
    weekly_files_for_month,
)


class MonthlyLiteratureStatsTests(unittest.TestCase):
    def test_rsc_crossref_sources_use_monthly_mapping_labels(self):
        self.assertEqual(
            normalize_source("Chemical Society Reviews"),
            "RSC - Chem. Soc. Rev. latest articles",
        )
        self.assertEqual(
            normalize_source("Energy & Environmental Science"),
            "RSC - Energy Environ. Sci. latest articles",
        )

    def test_count_and_journal_are_each_one_merged_range(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["出版商", "期刊名", "标题", "通讯作者", "发表日期", "DOI", "数量"])
        ws.append(["RSC", "Energy & Environment Science", "", "", "", "", 0])
        articles = pd.DataFrame(
            [
                {
                    "出版社": "RSC",
                    "期刊名": "Energy & Environment Science",
                    "title": "Paper one",
                    "pub_date": pd.Timestamp("2026-08-10", tz="UTC"),
                    "doi": "10.1/one",
                    "last_author": "A",
                },
                {
                    "出版社": "RSC",
                    "期刊名": "Energy & Environment Science",
                    "title": "Paper two",
                    "pub_date": pd.Timestamp("2026-08-11", tz="UTC"),
                    "doi": "10.1/two",
                    "last_author": "B",
                },
            ]
        )

        fill_sheet(ws, articles)

        merged = {str(cell_range) for cell_range in ws.merged_cells.ranges}
        self.assertIn("B2:B3", merged)
        self.assertIn("G2:G3", merged)
        self.assertEqual(ws["G2"].value, 2)

    def test_file_selection_includes_cross_month_and_late_backfill(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            weekly = root / "weekly"
            daily = root / "daily"
            weekly.mkdir()
            daily.mkdir()
            for name in [
                "weekly_news_with_abstract_2026-08-28_translated.xlsx",
                "weekly_news_with_abstract_2026-09-04_translated.xlsx",
                "weekly_news_with_abstract_2026-09-08_translated.xlsx",
            ]:
                (weekly / name).touch()
            for name in [
                "news_with_abstract_2026-09-04_zai_classified.xlsx",
                "news_with_abstract_2026-09-05_rsc_backfill_zai_classified.xlsx",
                "news_with_abstract_2026-10-02_zai_classified.xlsx",
            ]:
                (daily / name).touch()

            weekly_names = {path.name for path in weekly_files_for_month(weekly, "2026-08", False)}
            daily_names = {path.name for path in daily_classified_files_for_month(daily, "2026-08")}

            self.assertIn("weekly_news_with_abstract_2026-09-04_translated.xlsx", weekly_names)
            self.assertNotIn("weekly_news_with_abstract_2026-09-08_translated.xlsx", weekly_names)
            self.assertIn("news_with_abstract_2026-09-04_zai_classified.xlsx", daily_names)
            self.assertIn("news_with_abstract_2026-09-05_rsc_backfill_zai_classified.xlsx", daily_names)
            self.assertNotIn("news_with_abstract_2026-10-02_zai_classified.xlsx", daily_names)


if __name__ == "__main__":
    unittest.main()
