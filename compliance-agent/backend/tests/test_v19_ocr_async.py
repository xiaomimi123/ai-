"""v1.9 改动测试：

1. OCR PDF 渲染长边 ≤ 1600px，体积控制在 dashscope 大小限制内（A 部分）
2. upload_material 不再同步触发 OCR 与 form_review（B 部分）
3. 新增 enrich_material_task：异步跑扫描件 OCR + form_review，
   失败静默降级（B 部分）

设计目标：扫描件上传不再因 OCR 同步阻塞 5-20 秒。
"""
from __future__ import annotations

import json
import struct
import tempfile
import uuid
from pathlib import Path

import pytest


# ============================================================
# Section 1：渲染长边 / 体积控制（A）
# ============================================================
def _png_dimensions(png: bytes) -> tuple[int, int]:
    """PNG 文件 header 偏移 16..24 是 width / height (BE 32-bit)。"""
    assert png[:8] == b"\x89PNG\r\n\x1a\n", "非 PNG"
    w = struct.unpack(">I", png[16:20])[0]
    h = struct.unpack(">I", png[20:24])[0]
    return w, h


def test_render_pdf_pages_caps_long_dim_at_1600px(tmp_path):
    """v1.9：A4 PDF 渲染输出 PNG 长边 ≤ 1600px。"""
    import fitz

    from app.parsers.ocr_qwen_vl import _render_pdf_pages_to_png

    # 用 fitz 造一份 A4 PDF
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 100), "v1.9 render test page content")
    pdf_path = tmp_path / "a4.pdf"
    doc.save(str(pdf_path))
    doc.close()

    images = _render_pdf_pages_to_png(str(pdf_path), [0])
    assert len(images) == 1
    w, h = _png_dimensions(images[0])
    assert max(w, h) <= 1600, f"长边 {max(w, h)}px 超过 1600px 上限"
    # dashscope 实际限制约 4MB base64 后 → 原始 < 3MB 是安全的
    assert len(images[0]) < 3 * 1024 * 1024, (
        f"PNG 体积 {len(images[0])} 字节超过 3MB"
    )


def test_render_pdf_pages_handles_letter_size(tmp_path):
    """非 A4（Letter 612x792）页面同样应被限制在 1600px 长边内。"""
    import fitz

    from app.parsers.ocr_qwen_vl import _render_pdf_pages_to_png

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((50, 100), "letter size test")
    pdf_path = tmp_path / "letter.pdf"
    doc.save(str(pdf_path))
    doc.close()

    images = _render_pdf_pages_to_png(str(pdf_path), [0])
    w, h = _png_dimensions(images[0])
    assert max(w, h) <= 1600


# ============================================================
# Section 2：upload_material 不再同步触发 OCR / form review（B）
# ============================================================
def test_upload_material_does_not_pass_db_to_parse():
    """v1.9：upload_material 调 parse(...) 不应传 db=db
    （传了就会触发 dispatcher 同步 OCR）。"""
    src = (Path(__file__).resolve().parents[1]
           / "app" / "services" / "audit_service.py")
    text = src.read_text(encoding="utf-8")
    assert "parse(dest_path, db=db)" not in text, (
        "v1.9 upload_material 不应再向 parse() 传 db 参数；"
        "OCR 已移到 enrich_material_task 异步执行"
    )


def test_upload_material_does_not_call_form_review_inline():
    """v1.9：upload_material 不再同步调 _create_form_review_findings
    （已挪到 enrich_material_task 内）。"""
    src = (Path(__file__).resolve().parents[1]
           / "app" / "services" / "audit_service.py")
    text = src.read_text(encoding="utf-8")
    # 旧实现里 upload_material 函数体里直接调 _create_form_review_findings(db, task, material, ke_dict)
    # 新实现应改为 enqueue task
    inline_idx = text.find("_create_form_review_findings(db, task, material")
    assert inline_idx == -1, (
        "v1.9 upload_material 不应同步调 _create_form_review_findings；"
        "应改成 enrich_material_task.delay(material.id)"
    )


# ============================================================
# Section 3：enrich_material_task（B）
# ============================================================
@pytest.fixture(scope="module", autouse=True)
def _seed_indicators_for_v19():
    """v1.9 测试需要 I-13 等指标存在。"""
    from app.models import SessionLocal
    from app.seeds.load_indicators_55 import load
    from app.seeds.load_v15_keywords import apply as apply_kws
    load(replace=False)
    db = SessionLocal()
    try:
        apply_kws(db)
    finally:
        db.close()
    yield


def test_enrich_material_task_runs_ocr_for_scanned_pdf(monkeypatch):
    """celery eager 下，enrich_material_task 对 is_scanned=True 的 PDF
    调 ocr_pdf_first_and_last_page 并把 OCR 文本合并到 parsed_text，
    把识别到的 key_elements 写回。"""
    from app.models import AuditTask, AuditUnit, Material, SessionLocal
    from app.parsers import ocr_qwen_vl
    from app.tasks.jobs import enrich_material_task

    # 让 get_vision_client 返回一个非 None 的 client（模拟 OCR 已配置）
    monkeypatch.setattr(
        ocr_qwen_vl,
        "get_vision_client",
        lambda db: {"model": "test", "_sdk": None},
    )
    fake_ocr = {
        "text": "OCR 识别正文 abc",
        "has_seal": True,
        "seal_text": "测试财政厅章",
        "issue_date": "2026-01-01",
        "document_number": "",
        "issuer": "",
    }
    monkeypatch.setattr(
        ocr_qwen_vl, "ocr_pdf_first_and_last_page",
        lambda path, client: fake_ocr,
    )

    suffix = uuid.uuid4().hex[:6]
    db = SessionLocal()
    try:
        unit = AuditUnit(name=f"v19ocr-{suffix}", code=f"V19O{suffix}")
        db.add(unit); db.flush()
        task = AuditTask(
            unit_id=unit.id, name=f"v19ocr-{suffix}",
            eval_year=2026, scope="all",
        )
        db.add(task); db.flush()
        m = Material(
            task_id=task.id, indicator_id=None,
            file_name="扫描件.pdf",
            storage_path="/nonexistent/path.pdf",
            file_type="pdf", is_scanned=True,
            parsed_text="fitz 抽到的零碎几个字",
            key_elements="{}",
        )
        db.add(m); db.commit(); mid = m.id
    finally:
        db.close()

    # 直接调用 task（celery eager 模式 .delay 也是同步）
    enrich_material_task(mid)

    db = SessionLocal()
    try:
        m2 = db.get(Material, mid)
        assert "OCR 识别正文 abc" in (m2.parsed_text or ""), (
            f"parsed_text 应追加 OCR 文本，实际: {m2.parsed_text!r}"
        )
        ke = json.loads(m2.key_elements or "{}")
        assert ke.get("has_official_seal") is True, ke
        assert ke.get("issue_date") == "2026-01-01"
    finally:
        db.close()


def test_enrich_material_task_runs_form_review(monkeypatch):
    """v1.9：enrich_material_task 完成 OCR 后跑形式审查写 Finding。
    非扫描件也应执行形式审查（v1.5 行为保留）。"""
    from app.models import (
        AuditTask, AuditUnit, Finding, Indicator, Material, SessionLocal,
    )
    from app.tasks.jobs import enrich_material_task

    # 强制开启自动形式审查
    import app.services.settings_service as ss
    monkeypatch.setattr(ss, "get_auto_form_review_enabled", lambda db: True)

    suffix = uuid.uuid4().hex[:6]
    db = SessionLocal()
    try:
        unit = AuditUnit(name=f"v19fr-{suffix}", code=f"V19F{suffix}")
        db.add(unit); db.flush()
        task = AuditTask(
            unit_id=unit.id, name=f"v19fr-{suffix}",
            eval_year=2026, scope="all",
        )
        db.add(task); db.flush()
        ind = db.query(Indicator).filter_by(indicator_code="I-13").first()
        # key_elements 全 false → 应触发 3 条形式性 finding（公章/日期/文号）
        m = Material(
            task_id=task.id, indicator_id=ind.id,
            file_name=f"v19fr-doc-{suffix}.docx",
            storage_path=f"/tmp/v19fr-{suffix}",
            file_type="docx", is_scanned=False,
            parsed_text="x" * 100,  # >= 50 字阈值
            key_elements=json.dumps({
                "has_official_seal": False, "issue_date": "",
                "document_number": "", "is_draft": False,
            }),
        )
        db.add(m); db.commit(); mid = m.id
    finally:
        db.close()

    enrich_material_task(mid)

    db = SessionLocal()
    try:
        fs = db.query(Finding).filter_by(material_id=mid, source="rule").all()
        assert len(fs) >= 1, f"应写入形式审查 finding，实际：{fs}"
        assert all(f.finding_type == "形式性" for f in fs)
    finally:
        db.close()


def test_enrich_material_task_skips_ocr_for_non_scanned(monkeypatch):
    """非扫描件不应调 OCR（只跑 form review）。"""
    from app.models import AuditTask, AuditUnit, Material, SessionLocal
    from app.parsers import ocr_qwen_vl
    from app.tasks.jobs import enrich_material_task

    ocr_call_count = [0]

    def fake_ocr(*a, **kw):
        ocr_call_count[0] += 1
        return None

    monkeypatch.setattr(ocr_qwen_vl, "ocr_pdf_first_and_last_page", fake_ocr)
    monkeypatch.setattr(
        ocr_qwen_vl, "get_vision_client",
        lambda db: {"model": "test", "_sdk": None},
    )

    suffix = uuid.uuid4().hex[:6]
    db = SessionLocal()
    try:
        unit = AuditUnit(name=f"v19no-{suffix}", code=f"V19N{suffix}")
        db.add(unit); db.flush()
        task = AuditTask(
            unit_id=unit.id, name=f"v19no-{suffix}",
            eval_year=2026, scope="all",
        )
        db.add(task); db.flush()
        m = Material(
            task_id=task.id, indicator_id=None,
            file_name=f"normal-{suffix}.docx",
            storage_path=f"/tmp/v19no-{suffix}",
            file_type="docx", is_scanned=False,
            parsed_text="正常 docx 文本",
        )
        db.add(m); db.commit(); mid = m.id
    finally:
        db.close()

    enrich_material_task(mid)

    assert ocr_call_count[0] == 0, (
        f"非扫描件不应调 OCR，实际调了 {ocr_call_count[0]} 次"
    )


def test_enrich_material_task_silent_on_ocr_failure(monkeypatch):
    """v1.9：OCR 抛异常时 task 不应崩溃；material 保留原 parsed_text。"""
    from app.models import AuditTask, AuditUnit, Material, SessionLocal
    from app.parsers import ocr_qwen_vl
    from app.tasks.jobs import enrich_material_task

    monkeypatch.setattr(
        ocr_qwen_vl, "get_vision_client",
        lambda db: {"model": "test", "_sdk": None},
    )

    def raising_ocr(*a, **kw):
        raise RuntimeError("dashscope 模拟 400")

    monkeypatch.setattr(
        ocr_qwen_vl, "ocr_pdf_first_and_last_page", raising_ocr,
    )

    suffix = uuid.uuid4().hex[:6]
    db = SessionLocal()
    try:
        unit = AuditUnit(name=f"v19err-{suffix}", code=f"V19E{suffix}")
        db.add(unit); db.flush()
        task = AuditTask(
            unit_id=unit.id, name=f"v19err-{suffix}",
            eval_year=2026, scope="all",
        )
        db.add(task); db.flush()
        m = Material(
            task_id=task.id, indicator_id=None,
            file_name=f"scan-{suffix}.pdf",
            storage_path=f"/tmp/v19err-{suffix}",
            file_type="pdf", is_scanned=True,
            parsed_text="原始文本",
        )
        db.add(m); db.commit(); mid = m.id
    finally:
        db.close()

    # 不应抛
    enrich_material_task(mid)

    db = SessionLocal()
    try:
        m2 = db.get(Material, mid)
        assert m2.parsed_text == "原始文本", "OCR 失败时不应改 parsed_text"
    finally:
        db.close()
