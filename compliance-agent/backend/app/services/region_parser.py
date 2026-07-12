"""从单位名解析行政区划（市 + 区县）。

覆盖模式：
- 省级 + 市 + 区县：如"四川省达州市达川区幺塘乡..." → ("达州市", "达川区")
- 直辖市 + 区：如"北京市海淀区..." → ("北京市", "海淀区")
- 只有市 + 区县：如"达州市达川区..." → ("达州市", "达川区")
- 只有市：如"达州市财政局" → ("达州市", None)
- 解析不出：→ (None, None)

匹配失败的单位在导出时归入"未分类"桶。
"""
from __future__ import annotations

import re
from typing import Optional

# 直辖市（跳过省级匹配）
MUNICIPALITIES = {"北京市", "上海市", "天津市", "重庆市"}

# 省级前缀（省 / 自治区）—— 剥离后再匹配市，避免非贪婪 _CITY_RE
# 在 "四川省达州市..." 上把整段 "四川省达州市" 吞成 city 的 bug
_PROVINCE_RE = re.compile(r"^[一-龥]{2,10}?(?:省|自治区)")
# 市匹配：XX市 / XX自治州 / XX地区 / XX盟；限 2-6 字防过匹配
_CITY_RE = re.compile(r"([一-龥]{2,6}?(?:市|自治州|地区|盟))")
# 区县匹配：XX区 / XX县 / XX自治县 / XX旗
_DISTRICT_RE = re.compile(r"([一-龥]{2,6}?(?:区|县|自治县|旗))")


def parse_region(unit_name: str) -> tuple[Optional[str], Optional[str]]:
    """从单位名提取 (市, 区县)。"""
    if not unit_name:
        return (None, None)
    # 直辖市优先（多个直辖市 substring 命中时按首次出现位置最早的赢，避免 set 迭代序不确定性）
    found_muni = min(
        (m for m in MUNICIPALITIES if m in unit_name),
        key=lambda m: unit_name.index(m),
        default=None,
    )
    if found_muni:
        after_muni = unit_name.split(found_muni, 1)[-1]
        m = _DISTRICT_RE.search(after_muni)
        return (found_muni, m.group(1) if m else None)
    # 剥离省级前缀（如"四川省"、"内蒙古自治区"），再匹配市
    remaining = _PROVINCE_RE.sub("", unit_name)
    city_m = _CITY_RE.search(remaining)
    if not city_m:
        return (None, None)
    city = city_m.group(1)
    after_city = remaining[city_m.end():]
    dist_m = _DISTRICT_RE.search(after_city)
    return (city, dist_m.group(1) if dist_m else None)
