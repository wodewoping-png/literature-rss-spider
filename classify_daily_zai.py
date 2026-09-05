# -*- coding: utf-8 -*-
"""Classify one daily literature CSV with GLM-5.2 and Google Translate.

This is intentionally separate from the retained Gemini weekly program.  It
reuses the mature rule, embedding, checkpoint, and Excel formatting helpers,
but replaces the final model call with Z.AI and writes XLSX only.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

import classify_weekly_onefile as pipeline
from zai_client import DEFAULT_MODEL, ZAIChatClient


DEFAULT_OUTPUT_DIR = Path("output/daily_classified")
DAILY_PREFIX = "news_with_abstract_"


def pick_latest_daily_csv(folder: Path | str = "output") -> Path:
    folder = Path(folder)
    if not folder.exists():
        raise FileNotFoundError(f"Daily output folder not found: {folder.resolve()}")

    candidates = [
        path
        for path in folder.glob(f"{DAILY_PREFIX}*.csv")
        if "_translated" not in path.stem and "_classified" not in path.stem
    ]
    if not candidates:
        raise FileNotFoundError(f"No {DAILY_PREFIX}*.csv found in {folder.resolve()}")

    dated = []
    for path in candidates:
        file_date = pipeline._extract_date_from_name(path.name)
        date_key = file_date.toordinal() if file_date is not None else 0
        dated.append((date_key, path.stat().st_mtime, path))
    return max(dated, key=lambda value: (value[0], value[1]))[2]


def _build_zai_client() -> ZAIChatClient:
    return ZAIChatClient(
        model=os.getenv("ZAI_MODEL", DEFAULT_MODEL),
        timeout=int(os.getenv("ZAI_TIMEOUT", "180")),
        max_tokens=int(os.getenv("ZAI_MAX_TOKENS", "8192")),
        temperature=float(os.getenv("ZAI_TEMPERATURE", "0")),
    )


def _zai_generate_content(
    client: ZAIChatClient,
    messages: List[Dict[str, Any]],
    json_object: bool = True,
) -> str:
    return client.generate(messages, json_object=json_object)


def _call_zai_with_retries(
    client: ZAIChatClient,
    messages: List[Dict[str, Any]],
    label: str,
    json_object: bool = True,
    max_retries: Optional[int] = None,
) -> str:
    attempts = max_retries or int(os.getenv("ZAI_MAX_RETRIES", "3"))
    base_seconds = float(os.getenv("ZAI_RETRY_BASE_SECONDS", "4"))
    max_seconds = float(os.getenv("ZAI_RETRY_MAX_SECONDS", "30"))
    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            return _zai_generate_content(client, messages, json_object=json_object)
        except Exception as exc:
            last_error = exc
            if attempt == attempts:
                break
            wait = min(max_seconds, base_seconds * (2 ** (attempt - 1)))
            wait += random.uniform(0, min(3.0, wait * 0.25))
            print(f"[zai:{label}] attempt {attempt} failed: {exc} (wait {wait:.1f}s)", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"Z.AI request failed after {attempts} attempts: {last_error}")


def install_zai_backend() -> None:
    """Inject the Z.AI backend into the copied classification pipeline."""
    pipeline._build_gemini_client = _build_zai_client
    pipeline._gemini_generate_content = _zai_generate_content
    pipeline._call_with_retries = _call_zai_with_retries
    pipeline.GEMINI_CLASSIFY_MAX_RETRIES = int(os.getenv("ZAI_CLASSIFY_MAX_RETRIES", "3"))


def classify_daily(
    csv_path: Path,
    classification_path: Path,
    output_dir: Path,
    checkpoint_dir: Path,
    debug_dir: Path,
    translation_provider: str = "google",
    skip_llm: bool = False,
    no_resume: bool = False,
) -> Path:
    install_zai_backend()
    output_dir.mkdir(parents=True, exist_ok=True)

    output_xlsx = output_dir / f"{csv_path.stem}_zai_classified.xlsx"
    checkpoint_base = checkpoint_dir / f"{csv_path.stem}_zai_classified"
    translation_checkpoint: Optional[Path] = checkpoint_base.with_name(
        checkpoint_base.name + "_translation.csv"
    )
    classification_checkpoint: Optional[Path] = checkpoint_base.with_name(
        checkpoint_base.name + "_classification.json"
    )
    if no_resume:
        translation_checkpoint = None
        classification_checkpoint = None

    print(f"[io] daily input: {csv_path}", flush=True)
    frame = pd.read_csv(csv_path, encoding="utf-8-sig", keep_default_na=False)
    frame = pipeline.ensure_base_columns(frame)
    print(f"[io] loaded rows: {len(frame)}", flush=True)

    rules = pipeline.load_classification_rules(str(classification_path))
    ordered_categories = [rule.name for rule in rules]

    if translation_provider != "none" and not frame.empty:
        frame = pipeline.enrich_translation(
            frame,
            provider=translation_provider,
            checkpoint_path=translation_checkpoint,
        )

    if frame.empty:
        classified = pipeline.ensure_stable_id_column(frame)
        labels: List[List[str]] = []
        still_missing: List[str] = []
    else:
        classified, labels, still_missing = pipeline.classify_hybrid(
            df=frame,
            rules=rules,
            debug_dir=debug_dir,
            skip_gpt=skip_llm,
            checkpoint_path=classification_checkpoint,
        )

    pipeline.write_grouped_xlsx(
        classified,
        labels,
        ordered_categories,
        still_missing,
        str(output_xlsx),
    )
    signature_path = output_xlsx.with_suffix(output_xlsx.suffix + ".source.sha256")
    signature_path.write_text(
        hashlib.sha256(csv_path.read_bytes()).hexdigest() + "\n",
        encoding="ascii",
    )
    print(f"[io] wrote daily classified XLSX: {output_xlsx}", flush=True)
    return output_xlsx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", default="", help="Daily CSV; default is latest output/news_with_abstract_*.csv")
    parser.add_argument("-c", "--classification", default="classification.txt")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--checkpoint-dir", default="output/checkpoints")
    parser.add_argument("--debug-dir", default="output/debug/zai_daily")
    parser.add_argument("--translation-provider", choices=["google", "none"], default="google")
    parser.add_argument("--skip-llm", action="store_true", help="Test mode: use only keyword and embedding layers")
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()

    csv_path = Path(args.input) if args.input else pick_latest_daily_csv()
    if not csv_path.exists():
        raise FileNotFoundError(f"Daily CSV not found: {csv_path.resolve()}")

    classify_daily(
        csv_path=csv_path,
        classification_path=Path(args.classification),
        output_dir=Path(args.output_dir),
        checkpoint_dir=Path(args.checkpoint_dir),
        debug_dir=Path(args.debug_dir),
        translation_provider=args.translation_provider,
        skip_llm=args.skip_llm,
        no_resume=args.no_resume,
    )


if __name__ == "__main__":
    main()
