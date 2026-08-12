# -*- coding: utf-8 -*-
"""Codex classification payloads, schemas, and strict result validation."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class CategoryRule:
    """A category name and its complete human-authored definition."""

    name: str
    description: str


def load_classification_rules(path: str | Path) -> list[CategoryRule]:
    """Parse ``name: description`` rules while preserving definition text."""
    rule_path = Path(path)
    if not rule_path.exists():
        raise FileNotFoundError(f"classification file not found: {rule_path.resolve()}")

    rules: list[CategoryRule] = []
    for raw in rule_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "：" in line:
            name, description = line.split("：", 1)
        elif ":" in line:
            name, description = line.split(":", 1)
        else:
            name, description = line, ""
        name = name.strip()
        if name:
            rules.append(CategoryRule(name=name, description=description.strip()))

    if not rules:
        raise RuntimeError(f"No valid category lines parsed from {rule_path.resolve()}")

    names = [rule.name for rule in rules]
    if len(names) != len(set(names)):
        raise RuntimeError("Classification rules contain duplicate category names")
    return rules


def build_codex_payload(
    items: Sequence[Mapping[str, Any]],
    rules: Sequence[CategoryRule],
) -> dict[str, Any]:
    """Build the only input Codex needs for a deterministic classification run."""
    normalized_items = []
    for item in items:
        item_id = str(item.get("id", "")).strip()
        if not item_id:
            raise ValueError("Every classification item must have a non-empty id")
        normalized_items.append(
            {
                "id": item_id,
                "title": str(item.get("title", "")).strip(),
                "abstract": str(item.get("abstract", "")).strip(),
            }
        )

    ids = [item["id"] for item in normalized_items]
    if len(ids) != len(set(ids)):
        raise ValueError("Classification item ids must be unique")

    return {
        "instructions": {
            "language": "zh-CN",
            "use_abstract_first": True,
            "title_is_fallback": True,
            "multi_label_allowed": True,
            "empty_labels_when_no_match": True,
            "category_names_must_be_exact": True,
            "exclusions_override_broad_keyword_matches": True,
        },
        "categories": [asdict(rule) for rule in rules],
        "items": normalized_items,
    }


def build_codex_output_schema(rules: Sequence[CategoryRule]) -> dict[str, Any]:
    """Return a JSON Schema accepted by ``codex exec --output-schema``."""
    category_names = [rule.name for rule in rules]
    return {
        "type": "object",
        "properties": {
            "classifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "labels": {
                            "type": "array",
                            "items": {"type": "string", "enum": category_names},
                        },
                    },
                    "required": ["id", "labels"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["classifications"],
        "additionalProperties": False,
    }


def write_codex_files(
    payload: Mapping[str, Any],
    schema: Mapping[str, Any],
    input_path: str | Path,
    schema_path: str | Path,
) -> None:
    """Atomically write the Codex input and output schema."""
    _atomic_write_json(Path(input_path), payload)
    _atomic_write_json(Path(schema_path), schema)


def load_codex_labels(
    result_path: str | Path,
    expected_ids: Iterable[str],
    allowed_labels: Iterable[str],
) -> dict[str, list[str]]:
    """Validate Codex output and return an id-to-label mapping.

    The export deliberately fails when Codex omits or invents an id/category. Silent
    partial classification is worse than a failed workflow because it produces a
    plausible-looking but incomplete weekly report.
    """
    return load_codex_label_batches([result_path], expected_ids, allowed_labels)


def load_codex_label_batches(
    result_paths: Iterable[str | Path],
    expected_ids: Iterable[str],
    allowed_labels: Iterable[str],
) -> dict[str, list[str]]:
    """Merge one or more Codex result files, then validate global completeness."""

    expected = [str(value) for value in expected_ids]
    expected_set = set(expected)
    if len(expected) != len(expected_set):
        raise ValueError("Expected classification ids must be unique")
    allowed = set(allowed_labels)

    paths = [Path(path) for path in result_paths]
    if not paths:
        raise FileNotFoundError("No Codex classification result files were provided")

    labels_by_id: dict[str, list[str]] = {}
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"Codex classification result not found: {path.resolve()}")
        data = json.loads(_clean_json_text(path.read_text(encoding="utf-8")))
        rows = data.get("classifications") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise ValueError(f"Codex result must contain a classifications array: {path}")

        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Each Codex classification must be an object")
            item_id = str(row.get("id", "")).strip()
            labels = row.get("labels")
            if not item_id or not isinstance(labels, list):
                raise ValueError("Each Codex classification requires id and labels")
            if item_id in labels_by_id:
                raise ValueError(f"Codex result contains duplicate id: {item_id}")
            if item_id not in expected_set:
                raise ValueError(f"Codex result contains unknown id: {item_id}")

            clean_labels: list[str] = []
            for label in labels:
                label_text = str(label).strip()
                if label_text not in allowed:
                    raise ValueError(f"Codex result contains unknown category: {label_text}")
                if label_text not in clean_labels:
                    clean_labels.append(label_text)
            labels_by_id[item_id] = clean_labels

    missing = [item_id for item_id in expected if item_id not in labels_by_id]
    if missing:
        preview = ", ".join(missing[:5])
        raise ValueError(f"Codex result is missing {len(missing)} ids: {preview}")
    return labels_by_id


def _clean_json_text(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
