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
    def test_listener_uses_actual_upstream_workflow_names(self):
        workflow = load_workflow("daily_classification_zai.yaml")
        names = workflow["on"]["workflow_run"]["workflows"]
        self.assertIn("RSS Spider + Weekly Aggregate with Abstracts", names)
        self.assertIn("Daily RSS Gap Check and Backfill", names)
        self.assertNotIn("Daily Gap Backfill and Alert", names)

    def test_both_upstreams_explicitly_dispatch_daily_zai(self):
        for filename in ("rss_abs.yaml", "daily_gap_backfill.yaml"):
            with self.subTest(filename=filename):
                workflow = load_workflow(filename)
                self.assertEqual(workflow["permissions"]["actions"], "write")
                workflow_text = (WORKFLOWS / filename).read_text(encoding="utf-8")
                self.assertIn("gh workflow run daily_classification_zai.yaml", workflow_text)
                self.assertIn("-f task=daily", workflow_text)


if __name__ == "__main__":
    unittest.main()
