import json
import os
import tempfile
import unittest
import io
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

import classify_weekly_onefile as weekly
from gemini_client import build_gemini_client, generate_content


class GeminiClientTests(unittest.TestCase):
    def test_network_guard_fails_before_http_call(self):
        post = Mock()
        with patch.dict(os.environ, {"GEMINI_NETWORK_DISABLED": "1"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "network access is disabled"):
                generate_content(
                    {"api_key": "test-only", "model": "gemini-test"},
                    [{"role": "user", "content": "classify"}],
                    base_url="https://example.invalid",
                    temperature=0,
                    timeout=1,
                    post=post,
                )
        post.assert_not_called()

    def test_client_requires_key_without_contacting_network(self):
        with patch.dict(
            os.environ,
            {"GOOGLE_AI_API_KEY": "", "GEMINI_API_KEY": ""},
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "Missing GOOGLE_AI_API_KEY"):
                build_gemini_client("gemini-2.5-flash")

    def test_response_parsing_uses_injected_http_transport(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": '{"by_id":{}}'}]}}]
        }
        post = Mock(return_value=response)
        with patch.dict(os.environ, {"GEMINI_NETWORK_DISABLED": "0"}, clear=False):
            result = generate_content(
                {"api_key": "test-only", "model": "gemini-test"},
                [
                    {"role": "system", "content": "rules"},
                    {"role": "user", "content": "items"},
                ],
                base_url="https://example.invalid/v1beta",
                temperature=0,
                timeout=1,
                post=post,
            )
        self.assertEqual('{"by_id":{}}', result)
        self.assertEqual(1, post.call_count)
        self.assertEqual(
            "application/json",
            post.call_args.kwargs["json"]["generationConfig"]["responseMimeType"],
        )


class GeminiClassificationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.rules_path = self.root / "classification.txt"
        self.rules_path.write_text(
            "储能：包括电池储能，不包括建筑储能。\nCCUS：包括碳捕集、碳封存。\n",
            encoding="utf-8",
        )
        self.rules = weekly.load_classification_rules(str(self.rules_path))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_gemini_result_is_mocked_and_unknown_labels_are_removed(self):
        mocked_json = json.dumps(
            {
                "by_id": {
                    "paper-1": {
                        "labels": ["储能", "未知类别", "储能"],
                        "confidence": 0.9,
                    }
                }
            },
            ensure_ascii=False,
        )
        with patch.object(weekly, "_call_with_retries", return_value=mocked_json):
            labels = weekly.gemini_classify_by_id(
                {"api_key": "unused", "model": "unused"},
                self.rules,
                [{"id": "paper-1", "title": "Battery", "text": "Battery storage"}],
                "offline-test",
            )
        self.assertEqual({"paper-1": ["储能"]}, labels)

    def test_hybrid_pipeline_uses_mocked_gemini_and_exports_reports(self):
        frame = pd.DataFrame(
            [
                {
                    "title": "Battery paper",
                    "abstract": "Energy storage study",
                    "link": "https://example.com/1",
                    "source": "Journal",
                },
                {
                    "title": "Carbon capture paper",
                    "abstract": "Capture and geological storage",
                    "link": "https://example.com/2",
                    "source": "Journal",
                },
            ]
        )

        class FakeEmbedder:
            def encode(self, texts, **_kwargs):
                import numpy as np

                return np.ones((len(texts), 2), dtype=float) / (2 ** 0.5)

        def fake_classify(_client, _rules, items, label=None):
            return {
                item["id"]: (["CCUS"] if "capture" in item["title"].lower() else ["储能"])
                for item in items
            }

        with (
            patch.object(weekly, "_load_embedder", return_value=FakeEmbedder()),
            patch.object(weekly, "_build_gemini_client", return_value={"api_key": "unused", "model": "unused"}),
            patch.object(weekly, "gemini_classify_by_id", side_effect=fake_classify) as model_call,
            patch.object(weekly, "KEYWORD_STRONG_HITS", 99),
            patch.object(weekly, "EMB_STRONG_THRESHOLD", 2.0),
            patch.object(weekly, "EMB_WEAK_THRESHOLD", -1.0),
            redirect_stdout(io.StringIO()),
        ):
            classified, labels, missing = weekly.classify_hybrid(
                frame,
                self.rules,
                self.root / "debug",
                checkpoint_path=self.root / "checkpoint.json",
            )

        self.assertTrue(model_call.called)
        self.assertEqual([['储能'], ['CCUS']], labels)
        self.assertEqual([], missing)
        self.assertEqual(["储能", "CCUS"], classified["categories"].tolist())

        xlsx = self.root / "report.xlsx"
        docx = self.root / "report.docx"
        weekly.write_grouped_xlsx(classified, labels, ["储能", "CCUS"], missing, str(xlsx))
        weekly.df_to_word_bilingual_grouped(
            classified,
            labels,
            ["储能", "CCUS"],
            str(docx),
            "Offline Gemini mock report",
        )
        self.assertGreater(xlsx.stat().st_size, 0)
        self.assertGreater(docx.stat().st_size, 0)

    def test_real_csv_dry_run_uses_mocked_models_only(self):
        weekly_dir = Path(__file__).parent / "output" / "weekly"
        candidates = sorted(
            path
            for path in weekly_dir.glob("weekly_news_with_abstract_*.csv")
            if "_translated" not in path.stem and "_offline_test" not in path.stem
        )
        if not candidates:
            self.skipTest("No real weekly CSV fixture is present in this checkout")

        frame = pd.read_csv(candidates[-1], encoding="utf-8-sig", keep_default_na=False)

        class FakeEmbedder:
            def encode(self, texts, **_kwargs):
                import numpy as np

                return np.ones((len(texts), 2), dtype=float) / (2 ** 0.5)

        gemini_rows = 0

        def fake_classify(_client, _rules, items, label=None):
            nonlocal gemini_rows
            gemini_rows += len(items)
            return {item["id"]: [] for item in items}

        with (
            patch.object(weekly, "_load_embedder", return_value=FakeEmbedder()),
            patch.object(weekly, "_build_gemini_client", return_value={"api_key": "unused", "model": "unused"}),
            patch.object(weekly, "gemini_classify_by_id", side_effect=fake_classify),
            patch.object(weekly, "KEYWORD_STRONG_HITS", 99),
            patch.object(weekly, "EMB_STRONG_THRESHOLD", 2.0),
            patch.object(weekly, "EMB_WEAK_THRESHOLD", -1.0),
            redirect_stdout(io.StringIO()),
        ):
            classified, labels, missing = weekly.classify_hybrid(
                frame,
                weekly.load_classification_rules(
                    str(Path(__file__).parent / "classification.txt")
                ),
                self.root / "real-data-debug",
            )

        self.assertEqual(len(frame), len(classified))
        self.assertEqual(len(frame), len(labels))
        self.assertEqual(len(frame), gemini_rows)
        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
