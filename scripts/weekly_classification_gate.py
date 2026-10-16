"""Publish one weekly workbook after the current Friday's daily file is ready."""

from __future__ import annotations

import hashlib
import os
import re
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def weekly_report_status(root: Path, now: datetime | None = None) -> tuple[bool, str, str]:
    local_now = (now or datetime.now(ZoneInfo("Asia/Shanghai"))).astimezone(
        ZoneInfo("Asia/Shanghai")
    )
    report_date = local_now.date().isoformat()
    if local_now.weekday() != 4:
        return False, report_date, "Weekly aggregation runs on Friday (Asia/Shanghai)."

    source = root / "output" / f"news_with_abstract_{report_date}.csv"
    daily = root / "output/daily_classified" / f"news_with_abstract_{report_date}_zai_classified.xlsx"
    if not source.is_file() or not daily.is_file():
        return False, report_date, "Waiting for the current Friday's daily classification."
    try:
        with zipfile.ZipFile(daily) as workbook:
            metadata = workbook.read("docProps/core.xml").decode("utf-8")
        match = re.search(r"source_sha256=([0-9a-f]{64})", metadata)
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return False, report_date, "Waiting for a readable daily classification workbook."
    if not match or match[1] != hashlib.sha256(source.read_bytes()).hexdigest():
        return False, report_date, "Waiting for classification of the latest Friday source."

    weekly = root / "output/weekly_classified" / f"weekly_daily_classified_{report_date}.xlsx"
    if weekly.exists():
        return False, report_date, "This Friday's weekly workbook already exists."
    return True, report_date, "Friday daily classification is current; weekly aggregation is due."


def main() -> None:
    run, report_date, reason = weekly_report_status(Path.cwd())
    print(reason, flush=True)
    output = f"run={str(run).lower()}\nend_date={report_date}\n"
    if os.getenv("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
            stream.write(output)
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
