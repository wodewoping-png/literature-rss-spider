import json
import tempfile
import unittest
from pathlib import Path

from classification_io import (
    build_codex_output_schema,
    build_codex_payload,
    load_classification_rules,
    load_codex_label_batches,
    load_codex_labels,
    write_codex_files,
)


class ClassificationIOTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.rules_path = self.root / "classification.txt"
        self.rules_path.write_text(
            "储能：包括电池、电解质\nCCUS：包括碳捕集，不包括氢氨醇\n",
            encoding="utf-8",
        )
        self.rules = load_classification_rules(self.rules_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_payload_and_schema_preserve_exact_categories(self):
        payload = build_codex_payload(
            [{"id": "paper-1", "title": "Title", "abstract": "Abstract"}],
            self.rules,
        )
        schema = build_codex_output_schema(self.rules)

        self.assertEqual(["储能", "CCUS"], [item["name"] for item in payload["categories"]])
        enum = schema["properties"]["classifications"]["items"]["properties"]["labels"]["items"]["enum"]
        self.assertEqual(["储能", "CCUS"], enum)

    def test_write_codex_files_creates_valid_utf8_json(self):
        input_path = self.root / "nested" / "input.json"
        schema_path = self.root / "nested" / "schema.json"
        payload = build_codex_payload([], self.rules)
        schema = build_codex_output_schema(self.rules)

        write_codex_files(payload, schema, input_path, schema_path)

        self.assertEqual(payload, json.loads(input_path.read_text(encoding="utf-8")))
        self.assertEqual(schema, json.loads(schema_path.read_text(encoding="utf-8")))

    def test_load_codex_labels_rejects_missing_ids(self):
        result = self.root / "result.json"
        result.write_text(
            json.dumps({"classifications": [{"id": "paper-1", "labels": ["储能"]}]}, ensure_ascii=False),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "missing 1 ids"):
            load_codex_labels(result, ["paper-1", "paper-2"], ["储能", "CCUS"])

    def test_load_codex_labels_rejects_unknown_categories(self):
        result = self.root / "result.json"
        result.write_text(
            json.dumps({"classifications": [{"id": "paper-1", "labels": ["未知"]}]}, ensure_ascii=False),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "unknown category"):
            load_codex_labels(result, ["paper-1"], ["储能", "CCUS"])

    def test_load_codex_labels_accepts_fenced_json(self):
        result = self.root / "result.json"
        result.write_text(
            '```json\n{"classifications":[{"id":"paper-1","labels":[]}]}\n```',
            encoding="utf-8",
        )

        self.assertEqual({"paper-1": []}, load_codex_labels(result, ["paper-1"], ["储能"]))

    def test_load_codex_label_batches_merges_complete_result(self):
        first = self.root / "result-000.json"
        second = self.root / "result-001.json"
        first.write_text('{"classifications":[{"id":"paper-1","labels":["储能"]}]}', encoding="utf-8")
        second.write_text('{"classifications":[{"id":"paper-2","labels":["CCUS"]}]}', encoding="utf-8")

        self.assertEqual(
            {"paper-1": ["储能"], "paper-2": ["CCUS"]},
            load_codex_label_batches([first, second], ["paper-1", "paper-2"], ["储能", "CCUS"]),
        )


if __name__ == "__main__":
    unittest.main()
