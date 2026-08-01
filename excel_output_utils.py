# -*- coding: utf-8 -*-
"""Shared Excel formatting helpers for generated literature workbooks."""

from __future__ import annotations

from copy import copy
from datetime import date, datetime
from typing import Any

import pandas as pd


DATE_NUMBER_FORMAT = "yyyy/mm/dd"
DATE_HEADERS = {
    "pub_date",
    "published",
    "published_str",
    "date",
    "日期",
    "发表日期",
}
DOI_HEADERS = {"doi", "DOI"}
LINK_HEADERS = {"link", "链接", "url", "URL"}
HYPERLINK_FONT_COLOR = "0563C1"


def _format_hyperlink_font(cell) -> None:
    """Apply hyperlink typography without replacing the cell's existing fill or border."""
    font = copy(cell.font)
    font.color = HYPERLINK_FONT_COLOR
    font.underline = "single"
    cell.font = font


def doi_to_url(doi: Any, link: Any = "") -> str:
    """Return an Excel-friendly URL for a DOI cell, falling back to the article link."""
    doi_text = "" if doi is None else str(doi).strip()
    link_text = "" if link is None else str(link).strip()

    if doi_text and doi_text.lower() not in {"nan", "nat", "none"}:
        if doi_text.lower().startswith(("http://", "https://")):
            return doi_text
        if doi_text.lower().startswith("doi:"):
            doi_text = doi_text[4:].strip()
        if doi_text.startswith("10."):
            return f"https://doi.org/{doi_text}"

    if link_text and link_text.lower() not in {"nan", "nat", "none"}:
        return link_text
    return ""


def _coerce_excel_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return None

    parsed = pd.to_datetime(text, errors="coerce", utc=True)
    if pd.isna(parsed):
        parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def format_literature_worksheet(ws) -> None:
    """Make DOI/link cells clickable and date columns real Excel date cells."""
    headers = {
        str(cell.value).strip(): cell.column
        for cell in ws[1]
        if cell.value is not None and str(cell.value).strip()
    }
    date_cols = [col for header, col in headers.items() if header in DATE_HEADERS]
    link_cols = [col for header, col in headers.items() if header in LINK_HEADERS]
    doi_cols = [col for header, col in headers.items() if header in DOI_HEADERS]
    primary_link_col = link_cols[0] if link_cols else None

    for row_idx in range(2, ws.max_row + 1):
        for col_idx in date_cols:
            cell = ws.cell(row=row_idx, column=col_idx)
            parsed_date = _coerce_excel_date(cell.value)
            if parsed_date:
                cell.value = parsed_date
                cell.number_format = DATE_NUMBER_FORMAT

        link_value = ws.cell(row=row_idx, column=primary_link_col).value if primary_link_col else ""
        for col_idx in doi_cols:
            cell = ws.cell(row=row_idx, column=col_idx)
            url = doi_to_url(cell.value, link_value)
            if url:
                cell.value = url
                cell.hyperlink = url
                _format_hyperlink_font(cell)

        for col_idx in link_cols:
            cell = ws.cell(row=row_idx, column=col_idx)
            url = doi_to_url("", cell.value)
            if url:
                cell.hyperlink = url
                _format_hyperlink_font(cell)
