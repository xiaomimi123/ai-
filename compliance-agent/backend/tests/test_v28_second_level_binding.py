"""v2.8 二级文件夹语义识别测试。

背景：v1.5 后生产 52003 份材料错绑，二级文件夹 "XX业务/岗位职责说明书"
被 match_indicator_by_path_and_content 只识别到一级子类，走 protocol_fallback
绑到 "XX制度"（I-13/20/25/32/37/44）而非 "XX岗位分离"（I-14/21/26/33/38/45）。
"""
import json as _json


def _fake_ind(code, sub, materials, name=None):
    """轻量 Indicator 替身（与 test_path_binding.py 保持一致）。"""
    class FakeInd:
        pass
    f = FakeInd()
    f.id = int(code.split("-")[1]) if "-" in code else 0
    f.indicator_code = code
    f.subcategory = sub
    f.category = sub
    f.name = name or code
    f.required_materials = _json.dumps(materials, ensure_ascii=False)
    return f


def test_second_level_gangwei_binding_contract():
    """路径 "（六）合同控制/合同管理的岗位职责说明书/" → I-45 岗位分离，high。"""
    from app.services.material_matcher import match_indicator_by_path_and_content
    inds = [
        _fake_ind("I-44", "（六）合同控制", ["合同管理制度"], "合同制度"),
        _fake_ind("I-45", "（六）合同控制", [], "合同岗位分离"),
    ]
    # I-45 required_materials=[] → candidate keyword 匹配返回 None → 走 second_level 分支
    ind, conf, src = match_indicator_by_path_and_content(
        "某单位/（六）合同控制/合同管理的岗位职责说明书/xx.pdf",
        "xx.pdf",
        "",
        inds,
    )
    assert ind is not None and ind.indicator_code == "I-45"
    assert conf == "high"
    assert src == "path+second_level"


def test_second_level_gangwei_budget():
    """预算子类 + 岗位职责说明 → I-14 预算岗位分离。"""
    from app.services.material_matcher import match_indicator_by_path_and_content
    inds = [
        _fake_ind("I-13", "（一）预算业务控制", ["预算管理制度"], "预算制度"),
        _fake_ind("I-14", "（一）预算业务控制", [], "预算岗位分离"),
    ]
    # I-14 required_materials=[] → candidate keyword 匹配返回 None → 走 second_level 分支
    ind, conf, src = match_indicator_by_path_and_content(
        "某单位/（一）预算业务控制/预算业务的岗位职责说明书/yy.pdf",
        "yy.pdf",
        "",
        inds,
    )
    assert ind is not None and ind.indicator_code == "I-14"
    assert conf == "high"
    assert src == "path+second_level"


def test_second_level_zhidu_still_works():
    """路径含"内部控制制度"→ 走 zhidu semantic → I-44 合同制度。"""
    from app.services.material_matcher import match_indicator_by_path_and_content
    inds = [
        _fake_ind("I-44", "（六）合同控制", ["合同管理制度"], "合同制度"),
        _fake_ind("I-45", "（六）合同控制", [], "合同岗位分离"),
    ]
    ind, conf, src = match_indicator_by_path_and_content(
        "某单位/（六）合同控制/合同管理的内部控制制度/zz.pdf",
        "zz.pdf",
        "",
        inds,
    )
    assert ind is not None and ind.indicator_code == "I-44"
    assert conf == "high"
    assert src == "path+second_level"


def test_second_level_unknown_falls_back_to_protocol():
    """二级文件夹名不含任何关键词 → 走原 protocol_fallback → I-44。"""
    from app.services.material_matcher import match_indicator_by_path_and_content
    inds = [
        _fake_ind("I-44", "（六）合同控制", ["合同管理制度"], "合同制度"),
        _fake_ind("I-45", "（六）合同控制", [], "合同岗位分离"),
    ]
    ind, conf, src = match_indicator_by_path_and_content(
        "某单位/（六）合同控制/某未知子文件夹/qq.pdf",
        "qq.pdf",
        "",
        inds,
    )
    assert ind is not None and ind.indicator_code == "I-44"
    assert conf == "medium"
    assert src == "path+protocol_fallback"


def test_second_level_tiebreak_gangwei_wins_over_zhidu():
    """路径同时含"岗位职责说明"和"管理制度"→ SECOND_LEVEL_KEYWORDS 顺序优先，gangwei 先命中。

    保护 SECOND_LEVEL_KEYWORDS 顺序：如未来有人调整顺序把 zhidu 放到 gangwei 前，
    这个测试会失败，明确警告不能改变优先级。
    """
    from app.services.material_matcher import match_indicator_by_path_and_content
    inds = [
        _fake_ind("I-44", "（六）合同控制", ["合同管理制度"], "合同制度"),
        _fake_ind("I-45", "（六）合同控制", [], "合同岗位分离"),
    ]
    ind, conf, src = match_indicator_by_path_and_content(
        "某单位/（六）合同控制/合同管理制度的岗位职责说明/mixed.pdf",
        "mixed.pdf",
        "",
        inds,
    )
    # 岗位职责说明在 SECOND_LEVEL_KEYWORDS 里排在管理制度前 → gangwei 先命中 → I-45
    assert ind is not None and ind.indicator_code == "I-45"
    assert src == "path+second_level"
