"""Daily industry classification; retains the legacy classifier as a manual tool."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import pandas as pd

from industry_classification import (
    DEFAULT_TAXONOMY, Taxonomy, deduplicate_records,
    semantic_classify, write_industry_workbook,
)


def classify_daily(csv_path: Path, output_dir: Path = Path("output/daily_classified"),
                   checkpoint_dir: Path = Path("output/checkpoints"),
                   taxonomy_path: Path = DEFAULT_TAXONOMY, translation_provider: str = "google",
                   batch_size: int = 8, client=None) -> Path:
    taxonomy = Taxonomy(taxonomy_path)
    source_hash = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    frame = pd.read_csv(csv_path, encoding="utf-8-sig", keep_default_na=False, dtype=str)
    for required in ("title", "abstract"):
        if required not in frame.columns:
            raise ValueError(f"Missing source column: {required}")
    frame["input_row_numbers"] = [str(i) for i in range(2, len(frame) + 2)]
    frame["source_csv"] = csv_path.name
    input_count = len(frame)
    records = deduplicate_records(frame.to_dict(orient="records"))
    if translation_provider != "none" and records:
        # Reuse translation/checkpoint helpers only. No legacy rules,
        # embeddings or classify_hybrid calls participate in this pipeline.
        from classify_daily_zai import install_zai_backend
        from classify_weekly_onefile import enrich_translation
        install_zai_backend()
        translation_checkpoint = checkpoint_dir / f"{csv_path.stem}_zai_classified_translation.csv"
        frame = enrich_translation(pd.DataFrame(records), provider=translation_provider,
                                   checkpoint_path=translation_checkpoint)
        records = deduplicate_records(frame.to_dict(orient="records"))
    if client is None and records:
        from classify_daily_zai import _build_zai_client
        client = _build_zai_client()
    classified = semantic_classify(records, taxonomy, client,
        checkpoint_dir / "industry_classification.json", batch_size=batch_size)
    output = output_dir / f"{csv_path.stem}_zai_classified.xlsx"
    counts = write_industry_workbook(classified, output, taxonomy, source_hash,
                                     csv_path.name, input_count)
    print(f"[industry] wrote {output}; {counts}", flush=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-i", "--input", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    parser.add_argument("--output-dir", type=Path, default=Path("output/daily_classified"))
    parser.add_argument("--checkpoint-dir", type=Path, default=Path("output/checkpoints"))
    parser.add_argument("--translation-provider", choices=("google", "none"), default="google")
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()
    classify_daily(args.input, args.output_dir, args.checkpoint_dir, args.taxonomy,
                   args.translation_provider, args.batch_size)


if __name__ == "__main__":
    main()
