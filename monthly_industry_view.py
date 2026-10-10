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
HEADERS = ("出版商", "期刊名", "标题", "通讯作者", "发表日期", "DOI", "五级分类", "数量")
BATTERY = {"正极", "负极", "电解质", "非活性材料等", "其他储能器件"}
BATTERY_FIFTH = {
    "正极": "正极", "负极": "负极", "电解质": "电解质",
    "非活性材料等": "非活性材料/检测技术",
    "其他储能器件": "其他储能器件",
}


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


def classify_five(topic: str, title: str) -> tuple[str, ...]:
    """Return the taxonomy path through level five (or its deepest parent)."""
    root, second, third = classify(topic, title)
    t = title.casefold()
    base = (root, second, third)
    if root == "AI与智能科技":
        return base
    if root == "通用技术":
        if third == "物质运输":
            if re.search(r"aviation|aircraft|flight", t):
                return base + ("航空",)
            return base + ("陆路运输",)
        return base
    if second == "能量转化" and third == "能量存储":
        if topic in BATTERY:
            if "supercapacitor" in t:
                return base + ("电化学储能", "超级电容器")
            if topic == "其他储能器件" and not re.search(
                r"\b(batter\w*|cathode|anode|electrolyte|zinc.air|lithium.oxygen|li.o2|flow batter\w*)\b", t
            ):
                return base + ("其它储能技术",)
            return base + ("电化学储能", BATTERY_FIFTH[topic])
        if topic == "热能":
            if "molten salt" in t or "liquid thermal" in t:
                return base + ("储热", "液态储热")
            return base + ("储热", "其他储热技术")
        return base + ("化学能", "氢基能源")
    if third == "能量分配与运输":
        return base + ("能源载体管网", "氢气管网")
    if third == "能源测":
        if topic == "光伏":
            return base + ("一次能源转化", "太阳能转化")
        if topic == "核能":
            return base + ("一次能源转化", "核电")
        if topic == "氢基能源":
            return base + ("二次能源利用", "燃料电池")
        if re.search(r"cooling|refrigerat|air.condition", t):
            return base + ("二次能源利用", "制冷散热技术")
        return base + ("一次能源转化", "其他发电技术")
    if third == "资源获取":
        return base + ("开采技术",)
    if third == "资源回收利用与排放治理":
        if topic == "塑料回收":
            return base + ("物质回收",)
        if re.search(r"membrane.*(co2|carbon)|carbon.*membrane", t):
            return base + ("碳捕集", "膜分离")
        if re.search(r"amine|adsorb|framework.*capture", t):
            return base + ("碳捕集", "固态胺吸附") if "amine" in t else base + ("碳捕集",)
        if re.search(r"mineraliz|carbonate", t):
            return base + ("碳捕集", "矿化技术")
        return base + ("碳捕集",)
    if third == "资源加工":
        if re.search(r"cement|concrete|glass|ceramic", t):
            return base + ("无机物", "非金属")
        if re.search(r"steel|iron|alumin|copper", t):
            return base + ("无机物", "金属")
        if re.search(r"petrochem|methanol|syngas|alkene|olefin|fuel|ammonia", t):
            return base + ("有机物", "平台化工品")
        return base
    return base


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
    prefixes = {p[:n] for p in allowed for n in range(3, min(5, len(p)) + 1)}
    wb = openpyxl.load_workbook(path)
    if tuple(wb.sheetnames) == ROOTS:
        return {name: sum(bool(wb[name].cell(r, 3).value) for r in range(2, wb[name].max_row + 1)) for name in ROOTS}

    # Preserve every source row, including the repeated titles in the original
    # reports. This is a layout and taxonomy change, not a collection edit.
    grouped = defaultdict(list)
    template_header = wb.worksheets[0]
    publisher_styles = {}
    journal_order = {}
    publisher_order = {}
    journal_styles = {}
    for source_ws in wb.worksheets:
        current_publisher = ""
        for source_row in source_ws.iter_rows(min_row=2):
            if source_row[0].value:
                current_publisher = str(source_row[0].value).strip()
                if current_publisher not in publisher_styles:
                    publisher_styles[current_publisher] = source_row
                    publisher_order[current_publisher] = len(publisher_order)
            if source_row[1].value:
                journal = str(source_row[1].value).strip()
                journal_order.setdefault((current_publisher, journal), len(journal_order))
                journal_styles.setdefault((current_publisher, journal), source_row)
    for ws in wb.worksheets:
        headers = [str(c.value or "").strip() for c in ws[1]]
        if tuple(headers) != HEADERS[:6] + HEADERS[7:]:
            raise ValueError(f"Unexpected monthly layout in {ws.title}: {headers}")
        publisher = journal = ""
        for row in ws.iter_rows(min_row=2):
            publisher = str(row[0].value or publisher).strip()
            journal = str(row[1].value or journal).strip()
            title = row[2].value
            if not title:
                continue
            path5 = classify_five(ws.title, str(title))
            if path5 not in prefixes:
                raise ValueError(f"Industry path missing from taxonomy: {path5}")
            grouped[(path5[0], publisher, journal)].append(
                (title, row[3].value, row[4].value, row[5].value, path5[-1]))

    output = openpyxl.Workbook()
    output.remove(output.active)
    output.loaded_theme = wb.loaded_theme
    result = {}
    for root in ROOTS:
        ws = output.create_sheet(root)
        ws.freeze_panes = template_header.freeze_panes
        ws.sheet_view.showGridLines = template_header.sheet_view.showGridLines
        for col, heading in enumerate(HEADERS, 1):
            target = ws.cell(1, col, heading)
            source_col = col if col <= 6 else 7
            _copy_style(template_header.cell(1, source_col), target)
        for col in range(1, 7):
            letter = openpyxl.utils.get_column_letter(col)
            ws.column_dimensions[letter].width = template_header.column_dimensions[letter].width or 18
        ws.column_dimensions["G"].width = 18
        ws.column_dimensions["H"].width = template_header.column_dimensions["G"].width or 8
        ws.row_dimensions[1].height = template_header.row_dimensions[1].height or 24

        count = 0
        ordered_journals = sorted(journal_order, key=journal_order.get)
        for publisher in sorted(publisher_order, key=publisher_order.get):
            start_publisher = ws.max_row + 1
            for pub, journal in ordered_journals:
                if pub != publisher:
                    continue
                entries = grouped.get((root, publisher, journal), [])
                begin = ws.max_row + 1
                source_row = journal_styles[(publisher, journal)]
                for title, author, date, doi, category in entries or [(None, None, None, None, None)]:
                    row_idx = ws.max_row + 1
                    values = (publisher, journal, title, author, date, doi, category, len(entries))
                    for col, value in enumerate(values, 1):
                        cell = ws.cell(row_idx, col, value)
                        source_col = col if col <= 6 else 3 if col == 7 else 7
                        _copy_style(source_row[source_col - 1], cell)
                        cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
                    if title:
                        count += 1
                    ws.row_dimensions[row_idx].height = min(96, max(18, 16 * (1 + len(str(title or "")) // 64)))
                if len(entries) > 1:
                    for col in (2, 8):
                        ws.merge_cells(start_row=begin, start_column=col,
                                       end_row=ws.max_row, end_column=col)
            if ws.max_row > start_publisher:
                ws.merge_cells(start_row=start_publisher, start_column=1,
                               end_row=ws.max_row, end_column=1)
        format_literature_worksheet(ws)
        result[root] = count
    wb.close()
    output.save(path)
    return result
