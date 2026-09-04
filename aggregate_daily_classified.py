# -*- coding: utf-8 -*-
"""Merge already-classified daily XLSX files into one weekly XLSX.

No translation, embeddings, or LLM calls are made here.  Duplicate papers are
merged by stable id/link/title and category labels are unioned.
"""

from __future__ import annotations

import argparse
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

import pandas as pd

from classify_weekly_onefile import (
    _normalize_cell,
    ensure_base_columns,
    ensure_stable_id_column,
    load_classification_rules,
    write_grouped_xlsx,
)


DAILY_PATTERN = "news_with_abstract_*_zai_classified.xlsx"


def _date_from_daily_name(path: Path) -> date | None:
    match = re.search(r"news_with_abstract_(\d{4}-\d{2}-\d{2})_zai_classified$", path.stem)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def select_daily_files(
    input_dir: Path,
    end_date: date | None = None,
    days: int = 7,
) -> tuple[List[Path], date]:
    if days < 1:
        raise ValueError("days must be at least 1")
    dated = sorted(
        (file_date, path)
        for path in input_dir.glob(DAILY_PATTERN)
        if (file_date := _date_from_daily_name(path)) is not None
    )
    if not dated:
        raise FileNotFoundError(f"No daily classified workbooks found in {input_dir.resolve()}")

    effective_end = end_date or dated[-1][0]
    start = effective_end - timedelta(days=days - 1)
    selected = [path for file_date, path in dated if start <= file_date <= effective_end]
    if not selected:
        raise FileNotFoundError(f"No daily classified workbooks found from {start} through {effective_end}")
    return selected, effective_end


def _labels(value: object) -> List[str]:
    return [part.strip() for part in str(value or "").split(";") if part.strip()]


def _first_longest(values: Iterable[object]) -> str:
    clean = [_normalize_cell(value) for value in values]
    return max(clean, key=len, default="")


def _merge_group(group: pd.DataFrame, ordered_categories: Sequence[str]) -> Dict[str, str]:
    merged: Dict[str, str] = {}
    for column in group.columns:
        if column == "categories":
            seen = {label for value in group[column] for label in _labels(value)}
            ordered = [category for category in ordered_categories if category in seen]
            extras = sorted(seen.difference(ordered_categories))
            merged[column] = ";".join(ordered + extras)
        elif column == "daily_source_date":
            merged[column] = ";".join(sorted({_normalize_cell(value) for value in group[column] if _normalize_cell(value)}))
        else:
            merged[column] = _first_longest(group[column])
    return merged


def merge_daily_frames(frames: Sequence[pd.DataFrame], ordered_categories: Sequence[str]) -> pd.DataFrame:
    if not frames:
        return ensure_stable_id_column(ensure_base_columns(pd.DataFrame()))

    combined = pd.concat(frames, ignore_index=True, sort=False).fillna("")
    combined = ensure_base_columns(combined)
    combined = ensure_stable_id_column(combined)
    rows = [
        _merge_group(group, ordered_categories)
        for _, group in combined.groupby("stable_id", sort=False, dropna=False)
    ]
    return pd.DataFrame(rows, columns=combined.columns).fillna("")


def aggregate_daily_workbooks(
    input_dir: Path,
    output_dir: Path,
    classification_path: Path,
    end_date: date | None = None,
    days: int = 7,
    force: bool = False,
) -> Path:
    rules = load_classification_rules(str(classification_path))
    ordered_categories = [rule.name for rule in rules]
    files, effective_end = select_daily_files(input_dir, end_date=end_date, days=days)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"weekly_daily_classified_{effective_end.isoformat()}.xlsx"
    if output_path.exists() and not force:
        print(f"[weekly] output already exists; no repeated aggregation: {output_path}", flush=True)
        return output_path

    frames: List[pd.DataFrame] = []
    for path in files:
        frame = pd.read_excel(path, sheet_name="ALL", dtype=str, keep_default_na=False)
        frame["daily_source_date"] = _date_from_daily_name(path).isoformat()
        frames.append(frame)
        print(f"[weekly] read {len(frame)} rows from {path.name}", flush=True)

    merged = merge_daily_frames(frames, ordered_categories)
    labels_list = [_labels(value) for value in merged.get("categories", pd.Series(dtype=str)).tolist()]
    write_grouped_xlsx(
        merged,
        labels_list,
        ordered_categories,
        still_missing_ids=[],
        output_xlsx=str(output_path),
    )
    print(f"[weekly] merged {len(files)} daily files into {len(merged)} unique papers: {output_path}", flush=True)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default="output/daily_classified")
    parser.add_argument("--output-dir", default="output/weekly_classified")
    parser.add_argument("-c", "--classification", default="classification.txt")
    parser.add_argument("--end-date", default="", help="YYYY-MM-DD; default is latest daily workbook date")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    parsed_end = datetime.strptime(args.end_date, "%Y-%m-%d").date() if args.end_date else None
    aggregate_daily_workbooks(
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir),
        classification_path=Path(args.classification),
        end_date=parsed_end,
        days=args.days,
        force=args.force,
    )


if __name__ == "__main__":
    main()
