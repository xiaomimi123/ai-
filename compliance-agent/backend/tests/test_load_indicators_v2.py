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
