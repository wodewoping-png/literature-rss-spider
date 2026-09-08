from pathlib import Path
import unittest

import yaml


WORKFLOWS = Path(".github/workflows")


def load_workflow(name: str):
    return yaml.load(
        (WORKFLOWS / name).read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )


class ZAIDailyWorkflowTriggerTests(unittest.TestCase):
    def test_single_automatic_chain_is_spider_gap_check_then_zai(self):
        daily = load_workflow("daily_classification_zai.yaml")
        self.assertNotIn("workflow_run", daily["on"])

        gap = load_workflow("daily_gap_backfill.yaml")
        self.assertNotIn("workflow_run", gap["on"])
        self.assertNotIn("schedule", gap["on"])
        self.assertEqual(gap["permissions"]["actions"], "write")

        rss_text = (WORKFLOWS / "rss_abs.yaml").read_text(encoding="utf-8")
        gap_text = (WORKFLOWS / "daily_gap_backfill.yaml").read_text(encoding="utf-8")
        self.assertNotIn("gh workflow run daily_classification_zai.yaml", rss_text)
        self.assertEqual(rss_text.count("gh workflow run daily_gap_backfill.yaml"), 1)
        self.assertEqual(gap_text.count("gh workflow run daily_classification_zai.yaml"), 1)
        self.assertIn("-f task=daily", gap_text)

    def test_daily_selector_can_drain_a_backlog(self):
        workflow_text = (WORKFLOWS / "daily_classification_zai.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn("sort -r", workflow_text)
        self.assertIn("newest pending content", workflow_text)
        self.assertIn("candidate_output", workflow_text)
        self.assertIn("source_sha256=", workflow_text)
        self.assertIn("legacy_is_current", workflow_text)
        self.assertNotIn(".source.sha256", workflow_text)


if __name__ == "__main__":
    unittest.main()
