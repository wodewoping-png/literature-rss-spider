import hashlib
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from scripts.weekly_classification_gate import weekly_report_status


class WeeklyClassificationGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "output/news_with_abstract_2026-10-16.csv"
        self.daily = self.root / "output/daily_classified/news_with_abstract_2026-10-16_zai_classified.xlsx"
        self.friday = datetime(2026, 10, 16, 7, tzinfo=timezone.utc)

    def ready_daily(self):
        self.source.parent.mkdir(parents=True, exist_ok=True)
        self.source.write_bytes(b"title,doi\nPaper,10.1000/example\n")
        self.daily.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        with zipfile.ZipFile(self.daily, "w") as workbook:
            workbook.writestr("docProps/core.xml", f"<core>source_sha256={digest}</core>")

    def test_friday_waits_for_its_own_daily_workbook(self):
        self.assertFalse(weekly_report_status(self.root, self.friday)[0])
        self.ready_daily()
        self.assertEqual(weekly_report_status(self.root, self.friday)[:2], (True, "2026-10-16"))

    def test_stale_daily_source_waits_for_reclassification(self):
        self.ready_daily()
        self.source.write_bytes(b"changed")
        self.assertFalse(weekly_report_status(self.root, self.friday)[0])

    def test_already_published_friday_is_not_repeated(self):
        self.ready_daily()
        weekly = self.root / "output/weekly_classified/weekly_daily_classified_2026-10-16.xlsx"
        weekly.parent.mkdir(parents=True)
        weekly.touch()
        self.assertFalse(weekly_report_status(self.root, self.friday)[0])

    def test_uses_shanghai_day_at_both_friday_boundaries(self):
        self.ready_daily()
        for instant, expected in [
            (datetime(2026, 10, 15, 15, 59, tzinfo=timezone.utc), False),
            (datetime(2026, 10, 15, 16, 0, tzinfo=timezone.utc), True),
            (datetime(2026, 10, 16, 15, 59, tzinfo=timezone.utc), True),
            (datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc), False),
        ]:
            with self.subTest(instant=instant):
                self.assertEqual(weekly_report_status(self.root, instant)[0], expected)

    def test_invalid_daily_workbook_is_not_ready(self):
        self.ready_daily()
        self.daily.write_bytes(b"incomplete")
        self.assertFalse(weekly_report_status(self.root, self.friday)[0])

    def test_workflow_checks_latest_checkout_and_passes_friday_cutoff(self):
        workflow = yaml.load(
            Path(".github/workflows/daily_classification_zai.yaml").read_text(),
            Loader=yaml.BaseLoader,
        )
        steps = workflow["jobs"]["aggregate-weekly"]["steps"]
        gate = next(i for i, step in enumerate(steps) if step.get("id") == "weekly_gate")
        self.assertTrue(any("actions/checkout@" in step.get("uses", "") for step in steps[:gate]))
        self.assertEqual(steps[gate]["run"], "python scripts/weekly_classification_gate.py")
        merge = next(step for step in steps if "aggregate_daily_classified.py" in step.get("run", ""))
        self.assertEqual(merge["if"], "steps.weekly_gate.outputs.run == 'true'")
        self.assertIn('--end-date "${{ steps.weekly_gate.outputs.end_date }}"', merge["run"])


if __name__ == "__main__":
    unittest.main()
