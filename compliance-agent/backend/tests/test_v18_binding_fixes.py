"""v1.8 改动测试：

1. SUBCATEGORY_HINTS 兼容 v1.5 评价表子类（"（二）内部权力运行" 不应被
   "（二）收支业务控制" 抢匹配）
2. auto_bind_materials 加 rebind 参数 + 路径感知匹配
3. worksheet_service：无材料指标不再写"匹配性问题/重复性问题" finding
4. 清理脚本：删除历史"未上传任何佐证材料"finding
"""
from __future__ import annotations

import io
import json
import uuid

import pytest
from fastapi.testclient import TestClient


# ============================================================
# 模块级 fixture：seed 指标 + v1.5 关键词
# ============================================================
@pytest.fixture(scope="module", autouse=True)
def _seed_v18(auth_headers):
    from app.main import app  # noqa: F401  (触发 app/DB 初始化)
    from app.models import SessionLocal
    from app.seeds.load_indicators_55 import load as load_indicators
    from app.seeds.load_v15_keywords import apply as apply_keywords

    load_indicators(replace=False)
    db = SessionLocal()
    try:
        apply_keywords(db)
    finally:
        db.close()
    yield


# ============================================================
# Section 1：v1.5 子类识别（match_subcategory 单元测试）
# ============================================================
def test_subcategory_recognizes_v15_internal_power():
    """目录 '(二) 内部权力运行/...' 应识别为 '（二）内部权力运行'，
    不应被 '（二）收支业务控制' 抢先命中。"""
    from app.services.material_matcher import match_subcategory
    sub = match_subcategory(
        "207469379830/单位内部评价/(二) 内部权力运行/"
        "关键岗位干部交流或定期轮岗相关制度"
    )
    assert sub == "（二）内部权力运行", f"实际命中 {sub!r}"


def test_subcategory_recognizes_v15_decision():
    """'(一)议事决策机制' 不应被 '(一)预算业务控制' 抢命中。"""
    from app.services.material_matcher import match_subcategory
    sub = match_subcategory("某单位/单位内部评价/(一)议事决策机制/三重一大议事规则.pdf")
    assert sub == "（一）议事决策机制"


def test_subcategory_recognizes_v15_internal_supervision():
    """'(一)内部监督机制建立情况' 不应被 '(一)预算业务控制' 抢命中。"""
    from app.services.material_matcher import match_subcategory
    sub = match_subcategory(
        "某单位/单位内部评价/(一)内部监督机制建立情况/内部控制基本制度.pdf"
    )
    assert sub == "（一）内部监督机制建立情况"


def test_subcategory_recognizes_v15_org_structure():
    """'(三)组织架构' 不应被 '(三)政府采购业务控制' 抢命中。"""
    from app.services.material_matcher import match_subcategory
    sub = match_subcategory("某单位/(三)组织架构/内控领导小组成立文件.pdf")
    assert sub == "（三）组织架构"


# ============================================================
# Section 2：路径感知匹配 — 用户实际 case
# ============================================================
def test_path_aware_rotation_under_internal_power(auth_headers):
    """v1.5 路径 '(二) 内部权力运行/.../定期轮岗工作制度.pdf' 应匹配到
    I-06(轮岗制度建立) 或 I-04(分岗设权，protocol fallback)；
    绝不能落到 I-13(预算) / I-20(收支)。"""
    from app.models import Indicator, SessionLocal
    from app.services.material_matcher import match_indicator_by_path_and_content

    db = SessionLocal()
    try:
        inds = db.query(Indicator).all()
        ind, conf, src = match_indicator_by_path_and_content(
            "207469379830/单位内部评价/(二) 内部权力运行/"
            "关键岗位干部交流或定期轮岗相关制度/",
            "定期轮岗工作制度.pdf",
            "",  # 无解析文本
            inds,
        )
        assert ind is not None, f"应能匹配，实际 None；src={src}"
        assert ind.indicator_code not in ("I-13", "I-20"), (
            f"不应落到预算/收支，实际={ind.indicator_code}"
        )
        assert ind.indicator_code in ("I-06", "I-04"), (
            f"应落到 I-06(轮岗制度建立) 或 I-04(protocol fallback)，"
            f"实际={ind.indicator_code} src={src}"
        )
    finally:
        db.close()


# ============================================================
# Section 3：auto_bind_materials 加 rebind 参数
# ============================================================
def test_auto_bind_without_rebind_keeps_existing_binding(auth_headers):
    """默认 rebind=False 时，auto_bind 不动已绑定材料（保留 v1.5 之前的行为）。"""
    from app.main import app
    from app.models import Material, SessionLocal

    suffix = uuid.uuid4().hex[:6]
    with TestClient(app, headers=auth_headers) as client:
        unit_id = client.post(
            "/api/units",
            json={"name": f"v18-keep-{suffix}", "code": f"V18K{suffix}"},
        ).json()["id"]
        task_id = client.post("/api/tasks", json={
            "unit_id": unit_id, "name": f"v18-keep-{suffix}",
            "eval_year": 2026, "scope": "all",
        }).json()["id"]

        inds = client.get("/api/indicators").json()
        i13 = next(i for i in inds if i["indicator_code"] == "I-13")
        i06 = next(i for i in inds if i["indicator_code"] == "I-06")

        # 直接 DB 插一份已绑 I-13 但实际是轮岗制度的材料
        db = SessionLocal()
        m = Material(
            task_id=task_id, indicator_id=i13["id"],
            file_name=(
                "(二) 内部权力运行/关键岗位干部交流或定期轮岗相关制度/"
                "定期轮岗工作制度.pdf"
            ),
            storage_path=f"/tmp/v18keep-{suffix}", file_type="pdf",
        )
        db.add(m); db.commit(); mid = m.id; db.close()

        r = client.post(f"/api/tasks/{task_id}/materials/auto-bind", json={})
        assert r.status_code == 200, r.text

        db = SessionLocal()
        m_after = db.get(Material, mid)
        assert m_after.indicator_id == i13["id"], (
            f"未带 rebind 不应改变已绑定，实际={m_after.indicator_id}"
        )
        db.close()


def test_auto_bind_with_rebind_overrides_wrong_binding(auth_headers):
    """rebind=True 时，已绑定到错误指标的材料应被重新匹配。"""
    from app.main import app
    from app.models import Material, SessionLocal

    suffix = uuid.uuid4().hex[:6]
    with TestClient(app, headers=auth_headers) as client:
        unit_id = client.post(
            "/api/units",
            json={"name": f"v18-re-{suffix}", "code": f"V18R{suffix}"},
        ).json()["id"]
        task_id = client.post("/api/tasks", json={
            "unit_id": unit_id, "name": f"v18-re-{suffix}",
            "eval_year": 2026, "scope": "all",
        }).json()["id"]

        inds = client.get("/api/indicators").json()
        i13 = next(i for i in inds if i["indicator_code"] == "I-13")

        db = SessionLocal()
        m = Material(
            task_id=task_id, indicator_id=i13["id"],
            file_name=(
                "(二) 内部权力运行/关键岗位干部交流或定期轮岗相关制度/"
                "定期轮岗工作制度.pdf"
            ),
            storage_path=f"/tmp/v18re-{suffix}", file_type="pdf",
        )
        db.add(m); db.commit(); mid = m.id; db.close()

        r = client.post(
            f"/api/tasks/{task_id}/materials/auto-bind",
            json={"rebind": True},
        )
        assert r.status_code == 200, r.text

        db = SessionLocal()
        m_after = db.get(Material, mid)
        assert m_after.indicator_id != i13["id"], (
            f"rebind=True 应改变错绑材料，实际仍为 indicator_id={m_after.indicator_id}"
        )
        db.close()


# ============================================================
# Section 4：worksheet_service 无材料指标不写 finding
# ============================================================
def test_worksheet_no_material_indicator_no_match_finding(auth_headers):
    """指标无任何绑定材料 → build_worksheet_draft 不应写 '匹配性问题' finding。"""
    from app.models import (
        AuditTask, AuditUnit, Finding, Indicator, SessionLocal,
    )
    from app.services.worksheet_service import build_worksheet_draft

    suffix = uuid.uuid4().hex[:6]
    db = SessionLocal()
    try:
        unit = AuditUnit(name=f"v18-ws-{suffix}", code=f"V18W{suffix}")
        db.add(unit); db.flush()
        ind = db.query(Indicator).filter_by(indicator_code="I-51").first()
        assert ind is not None, "种子里应有 I-51"

        task = AuditTask(
            unit_id=unit.id, name=f"v18-ws-{suffix}",
            eval_year=2026, scope="selected",
            selected_indicator_ids=json.dumps([ind.id]),
        )
        db.add(task); db.commit()

        build_worksheet_draft(db, task)

        fs = db.query(Finding).filter_by(task_id=task.id).all()
        bad = [(f.finding_type, f.description) for f in fs
               if f.finding_type in ("匹配性问题", "重复性问题")]
        assert not bad, f"无材料指标不应写匹配/重复 finding，实际：{bad}"
    finally:
        db.close()


def test_worksheet_with_material_low_match_still_writes_finding(auth_headers):
    """守卫不应误伤：有材料但内容不对口（匹配率<70%）时仍应写'匹配性问题'。"""
    from app.models import (
        AuditTask, AuditUnit, Finding, Indicator, Material, SessionLocal,
    )
    from app.services.worksheet_service import build_worksheet_draft

    suffix = uuid.uuid4().hex[:6]
    db = SessionLocal()
    try:
        unit = AuditUnit(name=f"v18-ws2-{suffix}", code=f"V18W2{suffix}")
        db.add(unit); db.flush()
        ind = db.query(Indicator).filter_by(indicator_code="I-13").first()
        assert ind is not None, "种子里应有 I-13"

        task = AuditTask(
            unit_id=unit.id, name=f"v18-ws2-{suffix}",
            eval_year=2026, scope="selected",
            selected_indicator_ids=json.dumps([ind.id]),
        )
        db.add(task); db.flush()

        # 绑一份完全不相关的材料 → match_ratio = 0%
        m = Material(
            task_id=task.id, indicator_id=ind.id,
            file_name=f"完全不相关的杂项-{suffix}.txt",
            storage_path=f"/tmp/v18low-{suffix}", file_type="txt",
            parsed_text="纯文字内容，没有任何指标关键词。",
        )
        db.add(m); db.commit()

        build_worksheet_draft(db, task)

        fs = db.query(Finding).filter_by(task_id=task.id).all()
        assert any(f.finding_type == "匹配性问题" for f in fs), (
            f"有材料但匹配率低 → 应仍写匹配性问题，实际 finding_type: "
            f"{[f.finding_type for f in fs]}"
        )
    finally:
        db.close()


# ============================================================
# Section 5：历史数据清理脚本
# ============================================================
def test_cleanup_legacy_no_material_findings(auth_headers):
    """清理脚本：删除 description 含'未上传任何佐证材料'的 Finding，不误伤正常 finding。"""
    from app.models import (
        AuditTask, AuditUnit, Finding, Indicator, SessionLocal,
    )

    suffix = uuid.uuid4().hex[:6]
    db = SessionLocal()
    try:
        unit = AuditUnit(name=f"v18-clean-{suffix}", code=f"V18C{suffix}")
        db.add(unit); db.flush()
        task = AuditTask(
            unit_id=unit.id, name=f"v18-clean-{suffix}",
            eval_year=2026, scope="all",
        )
        db.add(task); db.flush()
        ind = db.query(Indicator).filter_by(indicator_code="I-13").first()

        legacy = Finding(
            task_id=task.id, material_id=None, indicator_id=ind.id,
            finding_type="完整性问题", severity="低",
            description="指标【I-13 预算管理制度】未上传任何佐证材料。",
            source="rule",
        )
        normal = Finding(
            task_id=task.id, material_id=None, indicator_id=ind.id,
            finding_type="合规性问题", severity="低",
            description="某条合规问题（不应被误删）。",
            source="rule",
        )
        db.add_all([legacy, normal]); db.commit()
        legacy_id = legacy.id
        normal_id = normal.id

        from app.scripts.clean_legacy_no_material_findings import run as cleanup
        result = cleanup(db)
        assert result["deleted"] >= 1, f"应至少删 1 条，实际：{result}"

        assert db.get(Finding, legacy_id) is None, "历史 finding 应被删除"
        assert db.get(Finding, normal_id) is not None, "正常 finding 不应被误删"

        # 幂等：第二次跑 deleted=0
        result2 = cleanup(db)
        assert result2["deleted"] == 0, f"幂等：第二次跑应为 0，实际：{result2}"
    finally:
        db.close()
