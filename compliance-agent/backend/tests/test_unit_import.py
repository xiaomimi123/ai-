"""单位批量导入服务测试。"""
import io
import openpyxl


def _make_xlsx(rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_units_xlsx_standard_header():
    from app.services.unit_import_service import _parse_units_file
    raw = _make_xlsx([
        ["代码", "单位名称"],
        ["A001", "甲单位"],
        ["A002", "乙单位"],
    ])
    rows, note = _parse_units_file(raw, "u.xlsx")
    assert rows == [{"name": "甲单位", "code": "A001"},
                    {"name": "乙单位", "code": "A002"}]
    assert "代码" in note and "单位名称" in note


def test_parse_units_xlsx_alias_header():
    from app.services.unit_import_service import _parse_units_file
    raw = _make_xlsx([
        ["编号", "机构名称"],
        ["X1", "丙机构"],
    ])
    rows, _ = _parse_units_file(raw, "u.xlsx")
    assert rows == [{"name": "丙机构", "code": "X1"}]


def test_parse_units_csv():
    from app.services.unit_import_service import _parse_units_file
    raw = "code,name\nC01,丁单位\n".encode("utf-8")
    rows, _ = _parse_units_file(raw, "u.csv")
    assert rows == [{"name": "丁单位", "code": "C01"}]


def test_parse_units_invalid_header_raises():
    from app.services.unit_import_service import _parse_units_file
    raw = _make_xlsx([
        ["列A", "列B"],
        ["x", "y"],
    ])
    import pytest
    with pytest.raises(ValueError):
        _parse_units_file(raw, "u.xlsx")


def test_import_units_inserts_new(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/d.db")
    from app.models import init_db, AuditUnit, SessionLocal
    init_db()
    raw = _make_xlsx([
        ["代码", "单位名称"],
        ["X1", "已存在单位"],
        ["X2", "新单位 A"],
        ["X3", "新单位 B"],
    ])
    with SessionLocal() as db:
        db.add(AuditUnit(name="已存在单位", code="OLD"))
        db.commit()
        from app.services.unit_import_service import import_units_from_file
        result = import_units_from_file(db, raw, "u.xlsx")
        assert result["total"] == 3
        assert result["inserted"] == 2
        assert result["skipped"] == 1
        names = {u.name for u in db.query(AuditUnit).all()}
        assert {"已存在单位", "新单位 A", "新单位 B"} <= names
        # 跳过的不被改 code
        assert db.query(AuditUnit).filter_by(name="已存在单位").first().code == "OLD"


def test_import_units_dry_run_does_not_write(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/d.db")
    from app.models import init_db, AuditUnit, SessionLocal
    init_db()
    raw = _make_xlsx([
        ["代码", "单位名称"],
        ["X9", "干跑单位"],
    ])
    with SessionLocal() as db:
        from app.services.unit_import_service import import_units_from_file
        result = import_units_from_file(db, raw, "u.xlsx", dry_run=True)
        assert result["total"] == 1
        assert result["preview"][0]["name"] == "干跑单位"
        # 库里没真写
        assert db.query(AuditUnit).filter_by(name="干跑单位").first() is None
