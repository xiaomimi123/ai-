"""异步任务定义（v3）。

eager 模式下 .delay() 同步执行；生产由 worker 进程消费。
"""
from __future__ import annotations

import json

from app.tasks.celery_app import celery_app


@celery_app.task(name="audit.run")
def run_audit_task(task_id: int) -> int:
    from app.engine import run_audit
    from app.models import AuditTask, SessionLocal

    db = SessionLocal()
    try:
        task = db.get(AuditTask, task_id)
        if task is not None:
            run_audit(db, task)
    finally:
        db.close()
    return task_id


# ============================================================
# v1.9：material 异步增强（OCR + 形式审查），不阻塞上传响应
# ============================================================
@celery_app.task(name="material.enrich")
def enrich_material_task(material_id: int) -> dict:
    """v1.9：把 v1.3 的扫描件 OCR 和 v1.5 的形式审查搬到异步执行。

    流程（任何步骤抛异常都吞掉，不阻塞主上传）：
    1. 扫描件 PDF + 视觉模型已配置 → 调 Qwen-VL OCR，合并 text / key_elements
    2. 跑形式审查（公章/日期/文号/草稿），按规则写 Finding

    返回 {"ocr_applied": bool, "form_findings_created": int, "skipped": str}
    """
    from app.models import AuditTask, Material, SessionLocal

    result = {"ocr_applied": False, "form_findings_created": 0, "skipped": ""}
    db = SessionLocal()
    try:
        m = db.get(Material, material_id)
        if not m:
            result["skipped"] = "material_not_found"
            return result

        # ---- 1) 扫描件 OCR ----
        if m.is_scanned and m.storage_path:
            try:
                from app.parsers import ocr_qwen_vl
                client = ocr_qwen_vl.get_vision_client(db)
                if client is not None:
                    ocr = ocr_qwen_vl.ocr_pdf_first_and_last_page(
                        m.storage_path, client,
                    )
                    if ocr:
                        _merge_ocr_into_material(m, ocr)
                        result["ocr_applied"] = True
                        db.commit()
            except Exception as exc:
                print(f"[enrich#{material_id}] OCR 失败（已降级）: {exc}")

        # ---- 2) 形式审查 ----
        try:
            from app.services.settings_service import (
                get_auto_form_review_enabled,
            )
            if (get_auto_form_review_enabled(db)
                    and m.indicator_id
                    and len(m.parsed_text or "") >= 50):
                from app.services.audit_service import (
                    _create_form_review_findings,
                )
                try:
                    ke_dict = json.loads(m.key_elements or "{}")
                except Exception:
                    ke_dict = {}
                task = db.get(AuditTask, m.task_id) if m.task_id else None
                if task is not None:
                    created = _create_form_review_findings(
                        db, task, m, ke_dict,
                    )
                    result["form_findings_created"] = created
        except Exception as exc:
            print(f"[enrich#{material_id}] 形式审查失败（已降级）: {exc}")

    finally:
        db.close()
    return result


def _merge_ocr_into_material(material, ocr: dict) -> None:
    """把 ocr 字典合并到 Material 实体（parsed_text 追加 + key_elements 填空字段）。"""
    text = (ocr.get("text") or "").strip()
    if text:
        existing = material.parsed_text or ""
        # parsed_text 字段截断 200000 字以防爆（与 upload_material 一致）
        merged = (existing + "\n" + text).strip()[:200000]
        material.parsed_text = merged

    try:
        ke = json.loads(material.key_elements or "{}")
    except Exception:
        ke = {}
    if ocr.get("has_seal"):
        ke["has_official_seal"] = True
        if ocr.get("seal_text") and not ke.get("seal_text"):
            ke["seal_text"] = str(ocr["seal_text"])
    for key in ("issue_date", "document_number", "issuer"):
        val = ocr.get(key)
        if val and not ke.get(key):
            ke[key] = str(val)
    if ke.get("issue_date") and not ke.get("issue_year"):
        try:
            ke["issue_year"] = int(ke["issue_date"][:4])
        except Exception:
            pass
    material.key_elements = json.dumps(ke, ensure_ascii=False, default=str)
