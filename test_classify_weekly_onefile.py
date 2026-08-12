import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

import classify_weekly_onefile as weekly


class WeeklyCodexPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.rules_path = self.root / "classification.txt"
        self.rules_path.write_text("储能：电池研究\nCCUS：碳捕集研究\n", encoding="utf-8")
        self.frame = weekly.ensure_stable_ids(
            weekly.ensure_base_columns(
                pd.DataFrame(
                    [
                        {
                            "title": "Battery paper",
                            "link": "https://example.com/1",
                            "abstract": "A study of battery electrolytes.",
                            "source": "Journal",
                            "pub_date": "2026-08-01",
                        },
                        {
                            "title": "Capture paper",
                            "link": "https://example.com/2",
                            "abstract": "A study of carbon capture.",
                            "source": "Journal",
                            "pub_date": "2026-08-02",
                        },
                    ]
                )
            )
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_prepare_and_export_are_fully_offline(self):
        input_path = self.root / "input.json"
        schema_path = self.root / "schema.json"
        result_path = self.root / "result.json"
        batches = weekly.prepare_codex_classification(
            self.frame,
            self.rules_path,
            input_path,
            schema_path,
        )
        payload = json.loads(batches[0].read_text(encoding="utf-8"))
        result_path.write_text(
            json.dumps(
                {
                    "classifications": [
                        {"id": payload["items"][0]["id"], "labels": ["储能"]},
                        {"id": payload["items"][1]["id"], "labels": ["CCUS"]},
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        classified, labels, categories = weekly.apply_codex_result(
            self.frame,
            self.rules_path,
            result_path,
        )
        xlsx_path = self.root / "report.xlsx"
        docx_path = self.root / "report.docx"
        weekly.write_grouped_xlsx(classified, labels, categories, xlsx_path)
        weekly.write_grouped_docx(classified, labels, categories, docx_path, "Test report")

        self.assertEqual([["储能"], ["CCUS"]], labels)
        self.assertTrue(xlsx_path.exists())
        self.assertTrue(docx_path.exists())

    def test_prepare_splits_large_inputs_into_bounded_batches(self):
        large = pd.concat([self.frame] * 3, ignore_index=True)
        large["link"] = [f"https://example.com/{index}" for index in range(len(large))]
        large = weekly.ensure_stable_ids(large.drop(columns=["stable_id"]))

        batches = weekly.prepare_codex_classification(
            large,
            self.rules_path,
            self.root / "classification-input.json",
            self.root / "classification-schema.json",
            batch_size=2,
        )

        self.assertEqual(3, len(batches))
        self.assertEqual([2, 2, 2], [len(json.loads(path.read_text(encoding="utf-8"))["items"]) for path in batches])

    def test_stable_ids_are_deterministic(self):
        first = weekly.ensure_stable_ids(self.frame.drop(columns=["stable_id"]))
        second = weekly.ensure_stable_ids(self.frame.drop(columns=["stable_id"]))
        self.assertEqual(first["stable_id"].tolist(), second["stable_id"].tolist())


if __name__ == "__main__":
    unittest.main()
