"""v1.5 路径感知绑定测试。"""
import json as _json


def _fake_ind(code, sub, materials, name=None):
    """轻量 Indicator 替身。"""
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


def test_match_path_subcategory_plus_keyword_high():
    """路径含「（二）收支业务控制」+ 文件名含「收支管理办法」→ I-20, high。"""
    from app.services.material_matcher import match_indicator_by_path_and_content
    inds = [
        _fake_ind("I-20", "（二）收支业务控制", ["收支管理办法", "收支制度"], "收支制度"),
        _fake_ind("I-24", "（二）收支业务控制", ["支出报销审批表"], "支出管理"),
        _fake_ind("I-44", "（六）合同控制", ["合同管理制度"], "合同制度"),
    ]
    ind, conf, src = match_indicator_by_path_and_content(
        "某单位/（二）收支业务控制/收支管理办法.pdf",
        "收支管理办法.pdf",
        "",
        inds,
    )
    assert ind is not None and ind.indicator_code == "I-20"
    assert conf == "high"
    assert src == "path+keyword"


def test_match_path_subcategory_no_keyword_falls_to_protocol():
    """路径子类命中 + 文件名/内容无关键词 → 子类制度类指标兜底, medium。"""
    from app.services.material_matcher import match_indicator_by_path_and_content
    inds = [
        _fake_ind("I-20", "（二）收支业务控制", ["收支管理办法"], "收支制度"),
        _fake_ind("I-24", "（二）收支业务控制", ["支出报销审批表"], "支出管理"),
    ]
    ind, conf, src = match_indicator_by_path_and_content(
        "某单位/（二）收支业务控制/不知道是啥的杂项材料.pdf",
        "不知道是啥的杂项材料.pdf",
        "",
        inds,
    )
    assert ind is not None and ind.indicator_code == "I-20"
    assert conf == "medium"
    assert src == "path+protocol_fallback"


def test_match_no_path_global_keyword_hits():
    """路径未识别子类 + 文件名含关键词 → 全库匹配, medium。"""
    from app.services.material_matcher import match_indicator_by_path_and_content
    inds = [
        _fake_ind("I-44", "（六）合同控制", ["合同管理制度"], "合同制度"),
    ]
    ind, conf, src = match_indicator_by_path_and_content(
        "随便起的目录名/合同管理制度2025.pdf",
        "合同管理制度2025.pdf",
        "",
        inds,
    )
    assert ind is not None and ind.indicator_code == "I-44"
    assert conf == "medium"
    assert src == "keyword_global"


def test_match_no_path_no_keyword_returns_none():
    """路径未识别 + 内容/文件名都没关键词 → (None, none, none)。"""
    from app.services.material_matcher import match_indicator_by_path_and_content
    inds = [
        _fake_ind("I-44", "（六）合同控制", ["合同管理制度"], "合同制度"),
    ]
    ind, conf, src = match_indicator_by_path_and_content(
        "随便起的目录/未知文件.pdf",
        "未知文件.pdf",
        "里面是无关内容",
        inds,
    )
    assert ind is None
    assert conf == "none"
    assert src == "none"
