import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from aggregate_daily_classified import aggregate_daily_workbooks


class AggregateDailyClassifiedTests(unittest.TestCase):
    def test_merges_and_deduplicates_without_model_calls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            daily_dir = root / "daily"
            weekly_dir = root / "weekly"
            daily_dir.mkdir()
            rules = root / "classification.txt"
            rules.write_text("正极：电池正极\nCCUS：碳捕集与利用\n", encoding="utf-8")

            first = pd.DataFrame(
                [
                    {"title": "Paper A", "link": "https://example/a", "abstract": "short", "categories": "正极"},
                    {"title": "Paper B", "link": "https://example/b", "categories": "CCUS"},
                ]
            )
            second = pd.DataFrame(
                [
                    {
                        "title": "Paper A",
                        "link": "https://example/a",
                        "abstract": "a much longer abstract",
                        "categories": "CCUS",
                    }
                ]
            )
            first.to_excel(daily_dir / "news_with_abstract_2026-09-01_zai_classified.xlsx", sheet_name="ALL", index=False)
            second.to_excel(daily_dir / "news_with_abstract_2026-09-02_zai_classified.xlsx", sheet_name="ALL", index=False)

            output = aggregate_daily_workbooks(
                input_dir=daily_dir,
                output_dir=weekly_dir,
                classification_path=rules,
                end_date=date(2026, 9, 2),
            )

            merged = pd.read_excel(output, sheet_name="ALL", keep_default_na=False)
            self.assertEqual(len(merged), 2)
            paper_a = merged.loc[merged["link"] == "https://example/a"].iloc[0]
            self.assertEqual(paper_a["abstract"], "a much longer abstract")
            self.assertEqual(paper_a["categories"], "正极;CCUS")
            self.assertEqual(paper_a["daily_source_date"], "2026-09-01;2026-09-02")
            with pd.ExcelFile(output) as workbook:
                self.assertIn("正极", workbook.sheet_names)
                self.assertIn("CCUS", workbook.sheet_names)

            self.assertEqual(
                aggregate_daily_workbooks(
                    input_dir=daily_dir,
                    output_dir=weekly_dir,
                    classification_path=rules,
                    end_date=date(2026, 9, 2),
                ),
                output,
            )


if __name__ == "__main__":
    unittest.main()
