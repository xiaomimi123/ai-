"""v2.14 unit region import 脚本测试。"""
import pytest
from openpyxl import Workbook

from app.models import (
    AuditUnit,
    Base,
    SessionLocal,
    engine,
)


@pytest.fixture
def db_session():
    Base.metadata.create_all(engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.query(AuditUnit).delete()
        s.commit()
        s.close()


def _make_excel(tmp_path, rows):
    """rows = [(code, name, region), ...]；返 xlsx 路径。"""
    p = tmp_path / "units.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["代码", "单位名称", "地区"])
    for r in rows:
        ws.append(r)
    wb.save(p)
    return str(p)


def test_match_by_code_updates_region(db_session, tmp_path):
    """按 code 匹到 → region 写入。"""
    from app.scripts.import_unit_regions_v214 import (
        _load_excel_rows, _match_and_update,
    )
    u = AuditUnit(name="v214-code-match", code="C001", region="")
    db_session.add(u); db_session.commit()

    xlsx = _make_excel(tmp_path, [("C001", "任意名字（不用来匹）", "成都市")])
    rows = _load_excel_rows(xlsx)
    stats = _match_and_update(db_session, rows, dry_run=False)

    db_session.refresh(u)
    assert u.region == "成都市"
    assert stats["matched_by_code"] == 1
    assert stats["matched_by_name"] == 0
    assert stats["updated"] == 1


def test_match_by_name_fallback_when_code_missing(db_session, tmp_path):
    """code 匹不到 → fallback 按 name 匹。"""
    from app.scripts.import_unit_regions_v214 import (
        _load_excel_rows, _match_and_update,
    )
    u = AuditUnit(name="v214-name-only-unit", code="", region="")
    db_session.add(u); db_session.commit()

    # Excel 里 code 是新的，name 一致
    xlsx = _make_excel(tmp_path, [
        ("C_NEW_9999", "v214-name-only-unit", "达州市")
    ])
    rows = _load_excel_rows(xlsx)
    stats = _match_and_update(db_session, rows, dry_run=False)

    db_session.refresh(u)
    assert u.region == "达州市"
    assert stats["matched_by_code"] == 0
    assert stats["matched_by_name"] == 1
    assert stats["updated"] == 1


def test_already_has_region_is_skipped(db_session, tmp_path):
    """已有 region 值的 unit 不被覆盖；stats.already_had_region+=1。"""
    from app.scripts.import_unit_regions_v214 import (
        _load_excel_rows, _match_and_update,
    )
    u = AuditUnit(name="v214-preserved-region", code="C_PRE",
                  region="省级")  # 已有
    db_session.add(u); db_session.commit()

    xlsx = _make_excel(tmp_path, [("C_PRE", "v214-preserved-region", "成都市")])
    rows = _load_excel_rows(xlsx)
    stats = _match_and_update(db_session, rows, dry_run=False)

    db_session.refresh(u)
    assert u.region == "省级"  # 未被覆盖
    assert stats["already_had_region"] == 1
    assert stats["updated"] == 0
