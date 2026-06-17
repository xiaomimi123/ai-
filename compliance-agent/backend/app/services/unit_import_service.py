"""单位 Excel/CSV 批量解析 + 入库服务（v1.1）。"""
from __future__ import annotations

import csv
import io
from typing import Tuple

import openpyxl

from sqlalchemy.orm import Session

from app.models.entities import AuditUnit, User
from app.core.auth import log_action


NAME_ALIASES = {"单位名称", "名称", "机构名称", "name"}
CODE_ALIASES = {"代码", "编号", "code", "机构代码", "统一信用代码"}


def _norm(s) -> str:
    return str(s or "").strip().lower()


def _pick_col(header: list, aliases: set[str]) -> int | None:
    for i, h in enumerate(header):
        if _norm(h) in {_norm(a) for a in aliases}:
            return i
    return None


def _parse_units_file(file_bytes: bytes, file_name: str) -> Tuple[list[dict], str]:
    """解析 Excel 或 CSV → [{name, code}], note。

    raise ValueError 当表头无法识别 / 文件格式不支持时。
    """
    name = (file_name or "").lower()
    if name.endswith(".csv"):
        text = file_bytes.decode("utf-8-sig", errors="ignore")
        reader = csv.reader(io.StringIO(text))
        rows = [r for r in reader if any(c.strip() for c in r)]
    elif name.endswith((".xlsx", ".xls")):
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = [list(r) for r in ws.iter_rows(values_only=True)
                if any(v not in (None, "") for v in r)]
    else:
        raise ValueError(f"不支持的文件格式：{file_name}")

    if not rows:
        raise ValueError("文件为空")

    header = rows[0]
    name_idx = _pick_col(header, NAME_ALIASES)
    code_idx = _pick_col(header, CODE_ALIASES)
    if name_idx is None:
        raise ValueError("Excel 表头无法识别，请确保含「名称」列（如：单位名称 / 名称 / 机构名称）")

    out: list[dict] = []
    for r in rows[1:]:
        nm = str(r[name_idx] or "").strip() if name_idx < len(r) else ""
        cd = ""
        if code_idx is not None and code_idx < len(r):
            cd = str(r[code_idx] or "").strip()
        if nm:
            out.append({"name": nm, "code": cd})

    note = f"表头识别：{header[name_idx]}" + (f" / {header[code_idx]}" if code_idx is not None else "")
    return out, note
