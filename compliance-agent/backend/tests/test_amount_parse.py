"""中文大写金额解析单元测试。"""
from app.rules.utils import parse_arabic_amount, parse_cn_amount


def test_parse_cn_simple():
    assert parse_cn_amount("人民币壹拾万元整") == 100000.0


def test_parse_cn_with_decimal():
    assert parse_cn_amount("壹佰贰拾叁元肆角伍分") == 123.45


def test_parse_cn_thousands():
    assert parse_cn_amount("玖万元整") == 90000.0


def test_parse_arabic():
    assert parse_arabic_amount("¥100,000.00元") == 100000.0
    assert parse_arabic_amount("总金额 90000 元") == 90000.0


def test_parse_cn_invalid():
    assert parse_cn_amount("没有金额") is None
