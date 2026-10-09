# -*- coding: utf-8 -*-
"""Rearrange a completed monthly report into the first three industry levels.

The established monthly collector still fills its journal template. This step
only changes the presentation after collection, and works on old workbooks too.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from copy import copy
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment
from excel_output_utils import format_literature_worksheet


ROOTS = ("零碳产业", "AI与智能科技", "通用技术")
TAXONOMY = Path(__file__).parent / "config/monthly/industry_taxonomy.json"
HEADERS = ("二级分类", "三级分类", "出版商", "期刊名", "标题", "通讯作者", "发表日期", "DOI", "数量")
BATTERY = {"正极", "负极", "电解质", "非活性材料等", "其他储能器件"}


def classify(topic: str, title: str) -> tuple[str, str, str]:
    """Use the established topic as the prior; override only explicit title signals."""
    t = title.casefold()
    if re.search(r"\b(ai|artificial intelligence|large language model|llm|foundation model)\b", t):
        if re.search(r"data cent(er|re)|hyperscale|powering.*data", t):
            return "AI与智能科技", "AI硬件层", "数据中心"
        return "AI与智能科技", "AI软件层", "AI4S"
    if re.search(r"\b(data cent(er|re)|hyperscale)\b", t):
        return "AI与智能科技", "AI硬件层", "数据中心"
    if re.search(r"\b(robot|embodied)\b", t) and topic != "产业降碳":
        return "AI与智能科技", "具身智能", "硬件和控制"
    if re.search(r"\b(quantum computing|quantum information|brain.computer interface)\b", t):
        return ("AI与智能科技", "其它智能科技",
                "量子信息和量子计算" if "quantum" in t else "脑机接口和神经科学")
    if re.search(r"\b(sensor|sensing|photodetector)\b", t) and topic not in {"光伏", "氢基能源", "CCUS"}:
        return "通用技术", "检测和表征", "传感器"
    if re.search(r"\b(electric vehicle|robotaxi|aircraft|shipping)\b", t) and topic == "产业降碳":
        return "通用技术", "通信和运输", "物质运输"

    if topic in BATTERY:
        return "零碳产业", "能量转化", "能量存储"
    if topic == "光伏":
        return "零碳产业", "能量转化", "能源测"
    if topic == "核能":
        if re.search(r"uranium.*(extract|seawater)|mineralization.*wastewater", t):
            return "零碳产业", "物质循环", "资源获取"
        return "零碳产业", "能量转化", "能源测"
    if topic == "热能":
        if re.search(r"thermal energy stor|heat stor|molten salt stor", t):
            return "零碳产业", "能量转化", "能量存储"
        return "零碳产业", "能量转化", "能源测"
    if topic == "氢基能源":
        if "pipeline" in t:
            return "零碳产业", "能量转化", "能量分配与运输"
        if re.search(r"fuel cell|water electrolysis|water splitting|electrolyzer|electrolyser", t):
            return "零碳产业", "能量转化", "能源测"
        return "零碳产业", "能量转化", "能量存储"
    if topic == "CCUS":
        return "零碳产业", "物质循环", "资源回收利用与排放治理"
    if topic == "塑料回收":
        return "零碳产业", "物质循环", "资源回收利用与排放治理"
    if topic == "产业降碳":
        return "零碳产业", "物质循环", "资源加工"
    raise ValueError(f"Unmapped source topic: {topic}")


def _key(doi: object, title: object) -> str:
    value = str(doi or "").strip().casefold()
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value)
    return value or re.sub(r"\s+", " ", str(title or "").strip().casefold())


def _copy_style(src, dst) -> None:
    if src.has_style:
        dst.font = copy(src.font)
        dst.fill = copy(src.fill)
        dst.border = copy(src.border)
        dst.alignment = copy(src.alignment)
        dst.number_format = src.number_format
        dst.protection = copy(src.protection)
    if src.hyperlink:
        dst.hyperlink = copy(src.hyperlink)


def reclassify_monthly_workbook(path: Path, taxonomy_path: Path = TAXONOMY) -> dict[str, int]:
    with taxonomy_path.open(encoding="utf-8") as f:
        allowed = {tuple(x) for x in json.load(f)["paths"]}
    wb = openpyxl.load_workbook(path)
    if tuple(wb.sheetnames) == ROOTS:
        return {name: sum(bool(wb[name].cell(r, 7).value) for r in range(2, wb[name].max_row + 1)) for name in ROOTS}

    # Keep the first instance of a DOI across the former topical tabs. The old
    # report can repeat a DOI inside a tab and across different topic tabs.
    articles = {}
    template_header = wb.worksheets[0]
    sample = next((ws for ws in wb if ws.max_row >= 3), template_header)
    for ws in wb.worksheets:
        headers = [str(c.value or "").strip() for c in ws[1]]
        if tuple(headers) != HEADERS[2:]:
            raise ValueError(f"Unexpected monthly layout in {ws.title}: {headers}")
        publisher = journal = ""
        for row in ws.iter_rows(min_row=2):
            publisher = str(row[0].value or publisher).strip()
            journal = str(row[1].value or journal).strip()
            title = row[2].value
            if not title:
                continue
            category = classify(ws.title, str(title))
            if category not in allowed:
                raise ValueError(f"Industry path missing from taxonomy: {category}")
            key = _key(row[5].value, title)
            if key not in articles:
                articles[key] = (category, publisher, journal, title,
                                 row[3].value, row[4].value, row[5].value)

    grouped = defaultdict(list)
    for category, publisher, journal, title, author, date, doi in articles.values():
        grouped[(category, publisher, journal)].append((title, author, date, doi))

    output = openpyxl.Workbook()
    output.remove(output.active)
    result = {}
    for root in ROOTS:
        ws = output.create_sheet(root)
        ws.freeze_panes = "E2"
        ws.sheet_view.showGridLines = template_header.sheet_view.showGridLines
        for col, heading in enumerate(HEADERS, 1):
            target = ws.cell(1, col, heading)
            _copy_style(template_header.cell(1, min(max(col - 2, 1), 7)), target)
        for col in range(3, 10):
            old = openpyxl.utils.get_column_letter(col - 2)
            new = openpyxl.utils.get_column_letter(col)
            ws.column_dimensions[new].width = template_header.column_dimensions[old].width or 18
        ws.column_dimensions["A"].width = 17
        ws.column_dimensions["B"].width = 25
        ws.row_dimensions[1].height = template_header.row_dimensions[1].height or 24

        groups = sorted((key for key in grouped if key[0][0] == root),
                        key=lambda x: (x[0][1], x[0][2], x[1], x[2]))
        count = 0
        for (category, publisher, journal) in groups:
            entries = grouped[(category, publisher, journal)]
            begin = ws.max_row + 1
            for title, author, date, doi in entries:
                count += 1
                values = (category[1], category[2], publisher, journal,
                          title, author, date, doi, len(entries))
                row_idx = ws.max_row + 1
                for col, value in enumerate(values, 1):
                    cell = ws.cell(row_idx, col, value)
                    _copy_style(sample.cell(2, min(max(col - 2, 1), 7)), cell)
                    cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
                ws.row_dimensions[row_idx].height = min(96, max(30, 16 * (1 + len(str(title)) // 64)))
            if len(entries) > 1:
                for col in (3, 4, 9):
                    ws.merge_cells(start_row=begin, start_column=col,
                                   end_row=ws.max_row, end_column=col)
        format_literature_worksheet(ws)
        # Grouped cells remain visibly organized by the same publisher/journal
        # convention as the source, while category columns stay readable.
        result[root] = count
    wb.close()
    output.save(path)
    return result
