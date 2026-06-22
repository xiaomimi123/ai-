"""新指标数据迁移脚本测试。"""
from pathlib import Path


def test_parse_new_indicators_basic():
    from app.seeds.load_indicators_54_v2 import parse_new_indicators
    fixture = Path(__file__).parent / "fixtures" / "sample_new_indicators.txt"
    items = parse_new_indicators(str(fixture))
    assert len(items) == 2
    assert items[0]["indicator_code"] == "I-01"
    assert items[0]["name"] == "决策制度"
    assert items[0]["required_materials"] == [
        "\"三重一大\"决策制度", "三重一大议事规则",
    ]
    assert items[1]["indicator_code"] == "I-02"
    assert items[1]["name"] == "决策执行"
    assert items[1]["required_materials"] == [
        "\"三重一大\"会议记录", "决策会议纪要",
    ]


def test_parse_handles_full_width_comma(tmp_path):
    """全角逗号 / 半角逗号 / 顿号 都要切分。"""
    from app.seeds.load_indicators_54_v2 import parse_new_indicators
    f = tmp_path / "mixed.txt"
    f.write_text("03 分事行权\n部门职能,内设机构职能、部门职责分工\n", encoding="utf-8")
    items = parse_new_indicators(str(f))
    assert items[0]["required_materials"] == [
        "部门职能", "内设机构职能", "部门职责分工",
    ]


def test_parse_strips_utf8_bom(tmp_path):
    """Windows 记事本导出的 txt 带 BOM (﻿) → 不应进入 indicator_code。"""
    from app.seeds.load_indicators_54_v2 import parse_new_indicators
    f = tmp_path / "bom.txt"
    # 写入带 BOM 的内容：第一字节是
    content = "﻿04 分岗设权\n岗位职责、岗位说明书\n"
    f.write_text(content, encoding="utf-8")
    items = parse_new_indicators(str(f))
    assert len(items) == 1
    assert items[0]["indicator_code"] == "I-04"  # 不带
    assert items[0]["name"] == "分岗设权"


def _make_session(db_path: str):
    """为测试创建独立的 engine + session，不依赖模块级单例。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.base import Base
    import app.models.entities  # noqa: F401

    eng = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    Session = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False, future=True)
    return Session


def test_apply_updates_existing(tmp_path):
    """已 seed 5 项 indicator → apply 后 name + required_materials 被覆盖。"""
    from app.models import Indicator
    Session = _make_session(str(tmp_path / "d.db"))
    with Session() as db:
        # 预 seed 几条指标占位
        for code in ("I-01", "I-02", "I-03", "I-55"):
            db.add(Indicator(
                indicator_code=code, name=f"老名字 {code}",
                category="", subcategory="", max_score=2.0,
            ))
        db.commit()

        from app.seeds.load_indicators_54_v2 import apply
        items = [
            {"indicator_code": "I-01", "name": "决策制度",
             "required_materials": ["三重一大决策制度", "议事规则"]},
            {"indicator_code": "I-02", "name": "决策执行",
             "required_materials": ["会议纪要"]},
        ]
        result = apply(db, items)
        assert result["updated"] == 2
        assert result["skipped"] == []
        assert result["i55_renamed"] is True

        # 验证 DB 真的更新了
        i01 = db.query(Indicator).filter_by(indicator_code="I-01").first()
        assert i01.name == "决策制度"
        import json as _json
        assert _json.loads(i01.required_materials) == ["三重一大决策制度", "议事规则"]

        i55 = db.query(Indicator).filter_by(indicator_code="I-55").first()
        assert i55.name == "未分类/人工复核"


def test_apply_skips_missing_codes(tmp_path):
    """如某 indicator_code 不在 DB → 记录到 skipped 列表，不报错。"""
    from app.models import Indicator
    Session = _make_session(str(tmp_path / "d2.db"))
    with Session() as db:
        db.add(Indicator(
            indicator_code="I-01", name="old", category="",
            subcategory="", max_score=2.0,
        ))
        db.commit()

        from app.seeds.load_indicators_54_v2 import apply
        result = apply(db, [
            {"indicator_code": "I-01", "name": "决策制度", "required_materials": []},
            {"indicator_code": "I-99", "name": "不存在", "required_materials": []},
        ])
        assert result["updated"] == 1
        assert result["skipped"] == ["I-99"]
        assert result["i55_renamed"] is False  # 库里没有 I-55
