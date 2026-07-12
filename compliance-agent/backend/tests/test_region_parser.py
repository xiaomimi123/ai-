"""v2.11 region_parser 单测。"""


def test_parse_normal_city_district():
    """省+市+区县 → (市, 区县)。"""
    from app.services.region_parser import parse_region
    assert parse_region("四川省达州市达川区幺塘乡人民政府") == ("达州市", "达川区")


def test_parse_municipality_beijing():
    """直辖市：北京市海淀区 → (北京市, 海淀区)。"""
    from app.services.region_parser import parse_region
    assert parse_region("北京市海淀区某单位") == ("北京市", "海淀区")


def test_parse_only_city_no_district():
    """只有市：达州市财政局 → (达州市, None)。"""
    from app.services.region_parser import parse_region
    assert parse_region("达州市财政局") == ("达州市", None)


def test_parse_autonomous_prefecture():
    """自治州：凉山彝族自治州西昌市 → (凉山彝族自治州, None)。

    注意：正则贪婪匹配到"自治州"就停；"西昌市"作为县级市不作为区县。
    """
    from app.services.region_parser import parse_region
    city, district = parse_region("凉山彝族自治州西昌市某单位")
    assert city == "凉山彝族自治州"
    # 区县可能为 None（西昌市是县级市，不匹配 区|县|自治县|旗）
    assert district is None


def test_parse_empty_returns_none_none():
    """空字符串 / None → (None, None)。"""
    from app.services.region_parser import parse_region
    assert parse_region("") == (None, None)
    assert parse_region(None) == (None, None)


def test_parse_no_city_pattern():
    """无市字样：某某局 → (None, None)。"""
    from app.services.region_parser import parse_region
    assert parse_region("某某局") == (None, None)
