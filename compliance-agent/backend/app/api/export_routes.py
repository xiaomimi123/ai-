"""v2.11：批量导出已定稿工作底稿（按地区）。

端点：
- GET /api/exports/region-summary   → 按市聚合的 finalized 任务统计
- GET /api/exports/worksheets/city/{city}.zip → 该市所有已定稿底稿 zip
"""
from __future__ import annotations

import io
import logging
import zipfile
from collections import defaultdict
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.models import AuditTask, AuditUnit, User, get_db
from app.services.region_parser import parse_region
from app.services.worksheet_export import build_worksheet_xlsx
from app.services.worksheet_service import get_worksheet

logger = logging.getLogger(__name__)

exports_router = APIRouter(prefix="/api/exports", tags=["exports"])

# "未分类"桶标识（前后端共用）
UNCLASSIFIED = "未分类"


def _list_finalized_by_city(db: Session) -> list[dict]:
    """按市聚合 finalized 任务。"""
    rows = (
        db.query(AuditTask, AuditUnit.name)
        .join(AuditUnit, AuditTask.unit_id == AuditUnit.id)
        .filter(AuditTask.status == "finalized")
        .all()
    )
    grouped: dict[str, dict] = defaultdict(
        lambda: {"task_count": 0, "unit_ids": set(), "unknown": False}
    )
    for task, unit_name in rows:
        city, _ = parse_region(unit_name)
        key = city or UNCLASSIFIED
        grouped[key]["task_count"] += 1
        grouped[key]["unit_ids"].add(task.unit_id)
        if not city:
            grouped[key]["unknown"] = True
    return [
        {"city": k, "task_count": v["task_count"],
         "unit_count": len(v["unit_ids"]), "unknown": v["unknown"]}
        for k, v in sorted(
            grouped.items(),
            key=lambda kv: (kv[1]["unknown"], -kv[1]["task_count"]),
        )
    ]


@exports_router.get("/region-summary")
def region_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """列出已定稿任务按市分组的统计。"""
    return _list_finalized_by_city(db)


@exports_router.get("/worksheets/city/{city}.zip")
def download_city_zip(
    city: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """下载某市所有已定稿任务的工作底稿 zip。

    Zip 内目录：<市>/<区县>/<单位名>_<年度>_<任务id>.xlsx；
    区县缺失时归 <市>/_未分类/。
    """
    if not city:
        raise HTTPException(400, "city 参数必填")

    all_rows = (
        db.query(AuditTask, AuditUnit.name)
        .join(AuditUnit, AuditTask.unit_id == AuditUnit.id)
        .filter(AuditTask.status == "finalized")
        .all()
    )
    match_rows = []
    for task, unit_name in all_rows:
        parsed_city, district = parse_region(unit_name)
        actual_city = parsed_city or UNCLASSIFIED
        if actual_city == city:
            match_rows.append((task, unit_name, district))
    if not match_rows:
        raise HTTPException(404, f"'{city}' 下无已定稿任务")

    buf = io.BytesIO()
    written = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for task, unit_name, district in match_rows:
            ws = get_worksheet(db, task.id)
            if not ws:
                logger.warning(
                    "finalized task %s (unit=%s) has no worksheet, skipped",
                    task.id, unit_name,
                )
                continue
            xlsx_bytes = build_worksheet_xlsx(db, task, ws)
            dist_dir = district or "_未分类"
            # 路径注入防御：sanitize 单位名
            safe_unit = unit_name.replace("/", "_").replace("\\", "_")
            entry = f"{city}/{dist_dir}/{safe_unit}_{task.eval_year}_{task.id}.xlsx"
            zf.writestr(entry, xlsx_bytes)
            written += 1
    buf.seek(0)
    filename = f"{city}_已定稿工作底稿_{written}份.zip"
    filename_quoted = quote(filename)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition":
                f'attachment; filename="worksheets_{quote(city)}.zip"; '
                f"filename*=UTF-8''{filename_quoted}",
        },
    )
