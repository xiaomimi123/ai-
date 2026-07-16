"""v2.12 全量重跑 + 自动定稿脚本测试。"""
import json

import pytest

from app.models import (
    AuditTask,
    AuditUnit,
    Base,
    Finding,
    Indicator,
    Material,
    SessionLocal,
    Worksheet,
    WorksheetRow,
    engine,
)


@pytest.fixture
def db_session():
    """每测独立 session；清空所有相关表避免跨测污染。"""
    Base.metadata.create_all(engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.query(WorksheetRow).delete()
        s.query(Worksheet).delete()
        s.query(Finding).delete()
        s.query(Material).delete()
        s.query(AuditTask).delete()
        s.query(AuditUnit).delete()
        s.query(Indicator).delete()
        s.commit()
        s.close()


def test_load_checkpoint_returns_done_ids(tmp_path):
    """写 3 条 checkpoint，_load_checkpoint 读回 3 个 task_id。"""
    from app.scripts.rerun_all_tasks_v212 import _load_checkpoint, _append_checkpoint
    cp = tmp_path / "cp.jsonl"
    _append_checkpoint(str(cp), 101, "finalized")
    _append_checkpoint(str(cp), 202, "finalized")
    _append_checkpoint(str(cp), 303, "skipped:failed")
    done = _load_checkpoint(str(cp))
    assert done == {101, 202, 303}


def test_reset_task_for_rerun_clears_findings_and_worksheet(db_session):
    """已有 findings + worksheet 的任务被 reset → 表清空 + status=pending。"""
    from app.scripts.rerun_all_tasks_v212 import _reset_task_for_rerun
    # seed
    u = AuditUnit(name="RESET-U", code="R")
    db_session.add(u); db_session.commit()
    ind = Indicator(
        indicator_code="I-01",
        name="test indicator",
        category="test",
        subcategory="test",
        required_materials="[]",
    )
    db_session.add(ind)
    db_session.commit()
    t = AuditTask(unit_id=u.id, name="reset test", eval_year=2025,
                  scope="all", status="finalized",
                  summary="旧摘要", stats='{"a":1}',
                  progress_current=100, progress_total=100,
                  progress_text="完成")
    db_session.add(t); db_session.commit()
    ws = Worksheet(task_id=t.id, status="finalized")
    db_session.add(ws); db_session.commit()
    ws_row = WorksheetRow(worksheet_id=ws.id, indicator_id=ind.id,
                          original_score=10.0, audited_score=8.0)
    db_session.add(ws_row); db_session.commit()
    f = Finding(task_id=t.id, indicator_id=ind.id,
                finding_type="完整性", severity="中",
                description="旧疑点")
    db_session.add(f); db_session.commit()

    _reset_task_for_rerun(db_session, t.id)
    db_session.refresh(t)

    assert t.status == "pending"
    assert t.progress_current == 0
    assert t.summary == ""
    assert db_session.query(Finding).filter(Finding.task_id == t.id).count() == 0
    assert db_session.query(Worksheet).filter(Worksheet.task_id == t.id).count() == 0
    assert db_session.query(WorksheetRow).filter(WorksheetRow.worksheet_id == ws.id).count() == 0


def test_auto_finalize_sets_task_and_worksheet_status(db_session):
    """ai_done 任务 + worksheet → 跑 _auto_finalize → 两者都 finalized。"""
    from app.scripts.rerun_all_tasks_v212 import _auto_finalize
    u = AuditUnit(name="FIN-U", code="F")
    db_session.add(u); db_session.commit()
    t = AuditTask(unit_id=u.id, name="finalize test", eval_year=2025,
                  scope="all", status="ai_done")
    db_session.add(t); db_session.commit()
    ws = Worksheet(task_id=t.id, status="draft")
    db_session.add(ws); db_session.commit()

    _auto_finalize(db_session, t)
    db_session.refresh(t)
    db_session.refresh(ws)

    assert t.status == "finalized"
    assert ws.status == "finalized"
    assert t.completed_at is not None


def test_discover_candidate_tasks_filters_correctly(db_session):
    """候选任务：有材料 + status!=running + 不在 done_ids。"""
    from app.scripts.rerun_all_tasks_v212 import _discover_candidate_tasks
    u = AuditUnit(name="DISC-U", code="D")
    db_session.add(u); db_session.commit()
    # A: 有材料 + finalized → 应命中
    tA = AuditTask(unit_id=u.id, name="A", eval_year=2025,
                   scope="all", status="finalized")
    # B: 有材料 + running → 应过滤（避开在跑）
    tB = AuditTask(unit_id=u.id, name="B", eval_year=2025,
                   scope="all", status="running")
    # C: 无材料 → 应过滤（没材料没意义）
    tC = AuditTask(unit_id=u.id, name="C", eval_year=2025,
                   scope="all", status="pending")
    # D: 有材料 + pending，但已在 done_ids → 应过滤（断点续跑）
    tD = AuditTask(unit_id=u.id, name="D", eval_year=2025,
                   scope="all", status="pending")
    db_session.add_all([tA, tB, tC, tD]); db_session.commit()
    for t in [tA, tB, tD]:
        m = Material(task_id=t.id, indicator_id=None,
                     file_name=f"m_{t.name}.pdf", storage_path="/tmp/x.pdf")
        db_session.add(m)
    db_session.commit()

    candidates = _discover_candidate_tasks(db_session, done_ids={tD.id})
    assert set(candidates) == {tA.id}
