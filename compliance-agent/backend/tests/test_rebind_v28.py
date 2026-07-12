"""v2.8 rebind_wrong_bindings 脚本单测。

conftest.py 已把 DATABASE_URL 指向临时 SQLite，本文件用 SessionLocal 直接建/清数据。
覆盖：
- dry-run 只统计不改
- --apply 实际改 material.indicator_id
- --apply 同步改 finding.indicator_id
- 幂等：跑两次第二次 updated=0
- 非目标材料不动
"""
import pytest

from app.models import SessionLocal, Base, engine, Material, Finding, Indicator


@pytest.fixture
def db_session():
    """每测独立 session；跑完清空相关五张表，避免跨测污染（AuditUnit.name 有 UNIQUE 约束）。"""
    from app.models import AuditTask, AuditUnit
    Base.metadata.create_all(engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.query(Finding).delete()
        s.query(Material).delete()
        s.query(Indicator).delete()
        s.query(AuditTask).delete()
        s.query(AuditUnit).delete()
        s.commit()
        s.close()


def _seed_indicators(db):
    """建 I-44 合同制度 + I-45 合同岗位分离两条。"""
    i44 = Indicator(indicator_code="I-44", name="合同制度",
                    category="（六）合同控制", subcategory="（六）合同控制",
                    required_materials="[]")
    i45 = Indicator(indicator_code="I-45", name="合同岗位分离",
                    category="（六）合同控制", subcategory="（六）合同控制",
                    required_materials="[]")
    db.add_all([i44, i45])
    db.commit()
    return i44, i45


def _seed_task(db):
    """建一个最小 AuditUnit + AuditTask，返回 task_id 用于 Material.task_id 外键。"""
    from app.models import AuditUnit, AuditTask
    u = AuditUnit(name="TEST-U", code="T")
    db.add(u); db.commit()
    t = AuditTask(unit_id=u.id, name="test", eval_year=2025, scope="all")
    db.add(t); db.commit()
    return t.id


def test_dry_run_does_not_modify(db_session):
    """dry-run 只报告不改 material.indicator_id。"""
    from app.scripts.rebind_wrong_bindings_v28 import run
    i44, i45 = _seed_indicators(db_session)
    tid = _seed_task(db_session)
    m = Material(
        task_id=tid, indicator_id=i44.id,
        file_name="（六）合同控制/合同管理的岗位职责说明书/xx.pdf",
        storage_path="/tmp/xx.pdf",
    )
    db_session.add(m)
    db_session.commit()
    original_id = m.indicator_id

    result = run(db_session, dry_run=True)
    db_session.refresh(m)
    assert result["matched"] == 1
    assert result["updated_materials"] == 0
    assert m.indicator_id == original_id  # 没改


def test_apply_updates_material_indicator(db_session):
    """--apply 实际改 material.indicator_id。"""
    from app.scripts.rebind_wrong_bindings_v28 import run
    i44, i45 = _seed_indicators(db_session)
    tid = _seed_task(db_session)
    m = Material(
        task_id=tid, indicator_id=i44.id,
        file_name="（六）合同控制/合同管理的岗位职责说明书/xx.pdf",
        storage_path="/tmp/xx.pdf",
    )
    db_session.add(m)
    db_session.commit()

    result = run(db_session, dry_run=False)
    db_session.refresh(m)
    assert result["updated_materials"] == 1
    assert m.indicator_id == i45.id


def test_apply_syncs_finding_indicator(db_session):
    """--apply 同步改 finding.indicator_id 到新的岗位分离指标。"""
    from app.scripts.rebind_wrong_bindings_v28 import run
    i44, i45 = _seed_indicators(db_session)
    tid = _seed_task(db_session)
    m = Material(
        task_id=tid, indicator_id=i44.id,
        file_name="（六）合同控制/合同管理的岗位职责说明书/xx.pdf",
        storage_path="/tmp/xx.pdf",
    )
    db_session.add(m)
    db_session.commit()
    f = Finding(
        task_id=tid, indicator_id=i44.id, material_id=m.id,
        finding_type="完整性", severity="中", description="test",
    )
    db_session.add(f)
    db_session.commit()

    result = run(db_session, dry_run=False)
    db_session.refresh(f)
    assert result["updated_findings"] == 1
    assert f.indicator_id == i45.id


def test_idempotent_second_run_zero(db_session):
    """跑第二遍 matched=0 updated=0。"""
    from app.scripts.rebind_wrong_bindings_v28 import run
    i44, i45 = _seed_indicators(db_session)
    tid = _seed_task(db_session)
    m = Material(
        task_id=tid, indicator_id=i44.id,
        file_name="（六）合同控制/合同管理的岗位职责说明书/xx.pdf",
        storage_path="/tmp/xx.pdf",
    )
    db_session.add(m)
    db_session.commit()
    run(db_session, dry_run=False)

    result2 = run(db_session, dry_run=False)
    assert result2["matched"] == 0
    assert result2["updated_materials"] == 0


def test_non_target_material_untouched(db_session):
    """file_name 不含"岗位" or 不含子类前缀的材料不动。"""
    from app.scripts.rebind_wrong_bindings_v28 import run
    i44, _ = _seed_indicators(db_session)
    tid = _seed_task(db_session)
    # 场景 A：不含"岗位"
    m1 = Material(task_id=tid, indicator_id=i44.id,
                  file_name="（六）合同控制/合同管理制度.pdf",
                  storage_path="/tmp/m1.pdf")
    # 场景 B：含"岗位"但不含子类前缀
    m2 = Material(task_id=tid, indicator_id=i44.id,
                  file_name="别的目录/岗位职责说明.pdf",
                  storage_path="/tmp/m2.pdf")
    db_session.add_all([m1, m2])
    db_session.commit()

    result = run(db_session, dry_run=False)
    db_session.refresh(m1)
    db_session.refresh(m2)
    assert result["updated_materials"] == 0
    assert m1.indicator_id == i44.id
    assert m2.indicator_id == i44.id
