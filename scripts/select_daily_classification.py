"""Select a missing/stale industry workbook, starting at the dated cutover.

Standard library only: this runs before dependency installation in Actions.
The switch date applies to automated selection; explicit CLI inputs can test
historical data without reclassifying the historical production files.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

START_DATE = "2026-10-17"


def expected_markers(root: Path) -> dict[str, str]:
    # Read literal constants without importing pandas before setup-python.
    tree = ast.parse((root / "industry_classification.py").read_text(encoding="utf-8"))
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = node.value.value
    payload = json.loads((root / "config/monthly/industry_taxonomy.json").read_text(encoding="utf-8"))
    leaves = sorted({tuple(p) for p in payload["paths"]})
    return {"classification_schema": constants["SCHEMA_VERSION"],
            "taxonomy_sha256": hashlib.sha256(json.dumps(leaves, ensure_ascii=False).encode()).hexdigest(),
            "prompt_sha256": hashlib.sha256(constants["SYSTEM_PROMPT"].encode()).hexdigest()}


def workbook_current(source: Path, output: Path, markers: dict[str, str]) -> bool:
    try:
        with zipfile.ZipFile(output) as workbook:
            metadata = workbook.read("docProps/core.xml").decode("utf-8")
        expected = {**markers, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
        return all(re.search(r"\b" + re.escape(key + "=" + value) + r"(?=[;\s<]|$)", metadata)
                   for key, value in expected.items())
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return False


def select_pending(root: Path, start_date: str = START_DATE, force: bool = False,
                   today: str | None = None) -> tuple[Path, Path] | None:
    today = today or datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    markers = expected_markers(root)
    for source in sorted((root / "output").glob("news_with_abstract_*.csv"), reverse=True):
        match = re.fullmatch(r"news_with_abstract_(\d{4}-\d{2}-\d{2})\.csv", source.name)
        if not match or not start_date <= match[1] <= today:
            continue
        output = root / "output/daily_classified" / f"{source.stem}_zai_classified.xlsx"
        if force or not workbook_current(source, output, markers):
            return source, output
    return None


def main():
    root = Path.cwd()
    selected = select_pending(root, os.getenv("DAILY_CLASSIFICATION_START_DATE", START_DATE),
                              os.getenv("FORCE_RECLASSIFY", "false").lower() == "true")
    result = {"run": str(bool(selected)).lower(),
              "check": str(bool(selected) or os.getenv("CHECK_WHEN_IDLE") == "true").lower()}
    if selected:
        result.update(input=str(selected[0].relative_to(root)), output=str(selected[1].relative_to(root)))
    print(f"[industry] pending: {result.get('input', 'none')}; automatic cutover {START_DATE} (Asia/Shanghai)")
    content = "".join(f"{k}={v}\n" for k, v in result.items())
    if os.getenv("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
            stream.write(content)
    else:
        print(content, end="")


if __name__ == "__main__":
    main()
