"""Offline regressions for the November 15/16 daily failures."""
import ast
import csv
import importlib.util
from datetime import date, datetime, timezone
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


class CacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Exercise production functions without launching browser/network imports.
        wanted = {"load_yesterday_cache", "within_days", "in_target_dates",
                  "parse_date_strict"}
        tree = ast.parse((ROOT / "spider0301.py").read_text())
        tree.body = [n for n in tree.body
                     if isinstance(n, ast.FunctionDef) and n.name in wanted]
        cls.ns = dict(pd=pd, Path=Path, datetime=datetime, timezone=timezone,
                      today_utc=date(2026, 11, 15),
                      TARGET_DATES={date(2026, 11, 14)},
                      record_key=lambda doi, link: doi or link)
        exec(compile(tree, "spider0301.py", "exec"), cls.ns)

    def test_missing_dates(self):
        for value in [None, pd.NaT]:
            self.assertFalse(self.ns["within_days"](value, 3))
            self.assertFalse(self.ns["in_target_dates"](value))
        for value in ["", "NaT", "nan", "not-a-date"]:
            self.assertIsNone(self.ns["parse_date_strict"](value))

    def test_valid_date(self):
        value = datetime(2026, 11, 14, tzinfo=timezone.utc)
        self.assertTrue(self.ns["within_days"](value, 3))
        self.assertTrue(self.ns["in_target_dates"](value))

    def test_cache_blank_invalid_and_valid_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.csv"
            with path.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "doi", "pub_date", "abstract", "discovery_date"])
                writer.writeheader()
                for i, value in enumerate(["", "bad-date", "2026-11-14"]):
                    writer.writerow(dict(doi=str(i), pub_date=value,
                                         abstract="", discovery_date="2026-11-14"))
                writer.writerow(dict(doi="cached", pub_date="", abstract="kept"))
            records, cached, retry = self.ns["load_yesterday_cache"](path)
            self.assertIsNone(records["0"]["pub_date"])
            self.assertIsNone(records["1"]["pub_date"])
            self.assertEqual(records["0"]["discovery_date"], "2026-11-14")
            self.assertEqual(cached, {"cached"})
            self.assertEqual(retry, {"2"})


class DispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "dispatch", ROOT / "scripts/dispatch_workflow.py")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def result(self, status):
        return subprocess.CompletedProcess([], 0 if status == 204 else 1,
                                           "", "" if status == 204 else f"HTTP {status}: error")

    def test_transient_recovers(self):
        run = Mock(side_effect=[self.result(500), self.result(502), self.result(204)])
        sleep = Mock()
        self.assertEqual(self.module.dispatch(["gap.yaml", "--ref", "main"], run, sleep), 0)
        self.assertEqual(run.call_count, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [10, 20])
        self.assertEqual(run.call_args.args[0],
                         ["gh", "workflow", "run", "gap.yaml", "--ref", "main"])

    def test_exhausted_retries_fail(self):
        for status in [429, 500, 503]:
            run, sleep = Mock(return_value=self.result(status)), Mock()
            self.assertEqual(self.module.dispatch(["gap.yaml"], run, sleep), 1)
            self.assertEqual(run.call_count, 4)
            self.assertEqual(sleep.call_count, 3)

    def test_permanent_errors_do_not_retry(self):
        for status in [401, 403, 404, 422]:
            run, sleep = Mock(return_value=self.result(status)), Mock()
            self.assertEqual(self.module.dispatch(["gap.yaml"], run, sleep), 1)
            self.assertEqual(run.call_count, 1)
            sleep.assert_not_called()

    def test_success_no_retry(self):
        run, sleep = Mock(return_value=self.result(204)), Mock()
        self.assertEqual(self.module.dispatch(["gap.yaml"], run, sleep), 0)
        self.assertEqual(run.call_count, 1)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
