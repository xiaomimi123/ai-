"""v1.5 关键词清单迁移脚本测试。"""
import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def isolated_db(tmp_path):
    from app.models.base import Base
    db_path = tmp_path / "v15.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    yield db
    db.close()


def test_load_v15_keywords_merges_not_overwrites(isolated_db):
    """已有 required_materials 内容应保留，新关键词追加合并。"""
    from app.models import Indicator
    from app.seeds.load_v15_keywords import apply

    ind = Indicator(
        indicator_code="I-20", name="收支制度",
        category="经济活动", subcategory="（二）收支业务控制",
        max_score=2.0,
        required_materials=json.dumps(["原关键词A"], ensure_ascii=False),
    )
    isolated_db.add(ind)
    isolated_db.commit()

    result = apply(isolated_db)
    assert result["updated"] >= 1

    isolated_db.refresh(ind)
    kws = json.loads(ind.required_materials)
    assert "原关键词A" in kws
    assert "收支管理办法" in kws


def test_load_v15_keywords_skips_missing_codes(isolated_db):
    """DB 缺某 indicator → apply 跳过不报错。"""
    from app.models import Indicator
    from app.seeds.load_v15_keywords import apply
    isolated_db.add(Indicator(
        indicator_code="I-01", name="决策制度",
        category="", subcategory="", max_score=2.0,
    ))
    isolated_db.commit()

    result = apply(isolated_db)
    assert result["updated"] == 1
