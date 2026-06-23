"""KeyElements 字段扩展测试（v1.3 新增 seal_text + issuer）。"""


def test_key_elements_defaults_include_new_fields():
    from app.parsers.base import KeyElements
    ke = KeyElements()
    # v1.3 新增 2 个字段
    assert hasattr(ke, "seal_text")
    assert hasattr(ke, "issuer")
    assert ke.seal_text == ""
    assert ke.issuer == ""


def test_key_elements_to_dict_includes_new_fields():
    from app.parsers.base import KeyElements, ParsedDocument
    pd = ParsedDocument(text="x")
    d = pd.to_dict()
    assert "seal_text" in d["key_elements"]
    assert "issuer" in d["key_elements"]
