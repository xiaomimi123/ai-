"""Qwen-VL 视觉模型配置 CRUD 测试。"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def isolated_db(tmp_path):
    """每个测试一个独立 SQLite，避免污染 module-level SessionLocal。"""
    from app.models.base import Base
    db_path = tmp_path / "vision.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    yield db
    db.close()


def test_get_vision_config_defaults_when_unset(isolated_db):
    from app.services.settings_service import get_vision_config
    cfg = get_vision_config(isolated_db)
    assert cfg == {"enabled": False, "api_key": "", "model": "qwen-vl-plus"}


def test_save_and_get_vision_config_roundtrip(isolated_db):
    from app.services.settings_service import save_vision_config, get_vision_config
    save_vision_config(isolated_db, enabled=True, api_key="sk-test", model="qwen-vl-max-latest")
    cfg = get_vision_config(isolated_db)
    assert cfg == {"enabled": True, "api_key": "sk-test", "model": "qwen-vl-max-latest"}


def test_save_vision_config_upserts_existing(isolated_db):
    from app.services.settings_service import save_vision_config, get_vision_config
    from app.models import AppSetting
    # 第一次保存
    save_vision_config(isolated_db, enabled=True, api_key="sk-1", model="qwen-vl-plus")
    # 第二次保存（修改）
    save_vision_config(isolated_db, enabled=False, api_key="sk-2", model="qwen-vl-max-latest")
    # 不重复插入：3 个 key 各 1 条
    rows = isolated_db.query(AppSetting).filter(
        AppSetting.key.in_(["vision_enabled", "vision_api_key", "vision_model"])
    ).all()
    assert len(rows) == 3
    cfg = get_vision_config(isolated_db)
    assert cfg["enabled"] is False and cfg["api_key"] == "sk-2"
