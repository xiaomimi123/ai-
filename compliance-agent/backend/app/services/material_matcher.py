"""材料 → 指标 智能匹配（基于文件名 / 路径的关键词反查）。

应用场景：
1. 文件夹批量上传时，材料无显式绑定 → 用本模块自动绑定到指标
2. orchestrator 跑核查时，未绑定材料按子类筛选只送给"相关指标"
   避免共享池 N × 55 的 LLM 调用爆炸

匹配两层：
- **subcategory 级**：根据文件路径里的「（一）」「预算」等关键词，定位到所属
  子类（一共 9 个：组织层面 / 6 个业务子类 / 内部监督 / 补充指标）
- **indicator 级**：在子类内根据指标名关键词（"三重一大"、"轮岗"、"票据"…）
  二次匹配到唯一指标；找不到唯一就回退到子类层

设计原则：匹配不到就 None（不强行绑定，保留共享池兜底）。
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional

from app.models import Indicator


# ============================================================
# 子类关键词字典（路径里出现任一即视为命中）
# 顺序很重要：业务子类前缀比"组织层面"等宽泛词更优先
# ============================================================
SUBCATEGORY_HINTS: list[tuple[str, list[str]]] = [
    # (subcategory_canonical_name, [关键词列表])
    ("（一）预算业务控制",        ["（一）", "(一)", "预算业务", "预算管理", "预算"]),
    ("（二）收支业务控制",        ["（二）", "(二)", "收支业务", "收支管理", "收支", "票据"]),
    ("（三）政府采购业务控制",     ["（三）", "(三)", "政府采购", "采购业务", "采购管理", "采购"]),
    ("（四）资产控制",            ["（四）", "(四)", "资产控制", "资产管理", "资产", "印章", "账户", "盘点"]),
    ("（五）建设项目控制",        ["（五）", "(五)", "建设项目", "工程项目", "基建", "项目管理"]),
    ("（六）合同控制",            ["（六）", "(六)", "合同管理", "合同控制", "合同"]),
    ("内部监督",                  ["内部监督", "监督检查", "内控检查", "整改"]),
    ("补充指标",                  ["补充指标", "其他"]),
    # 组织层面放最后兜底（"组织"在很多路径里都可能出现）
    ("组织层面内部控制",          ["组织层面", "三重一大", "分事行权", "分岗设权", "分级授权",
                                  "轮岗", "内控组织", "组织架构", "内控会议", "会计核算",
                                  "信息化", "信息系统"]),
]


# ============================================================
# 指标级关键词（一对一精准匹配，仅当唯一命中才绑定）
# 同一关键词只能出现在一条指标上，否则会冲突
# ============================================================
INDICATOR_HINTS: dict[str, list[str]] = {
    # 组织层面
    "I-01": ["三重一大决策制度", "三重一大制度", "三重一大机制"],
    "I-02": ["三重一大会议纪要", "三重一大执行"],
    "I-03": ["分事行权", "决策执行监督"],
    "I-04": ["分岗设权", "岗位说明书"],
    "I-05": ["分级授权", "审批权限"],
    "I-06": ["轮岗制度"],
    "I-07": ["轮岗执行", "轮岗记录"],
    "I-08": ["内控组织架构", "内控领导小组"],
    "I-09": ["内控会议", "内控专题会"],
    "I-10": ["会计核算", "会计科目", "财务报告"],
    "I-11": ["信息化覆盖", "信息化建设"],
    "I-12": ["信息系统管控", "运维管理", "系统安全"],

    # 预算
    "I-13": ["预算管理制度", "预算制度"],
    "I-15": ["预算编制"],
    "I-16": ["预算执行", "预算公开"],
    "I-17": ["预算预警", "预算整改"],
    "I-18": ["决算"],
    "I-19": ["预算绩效", "绩效管理"],

    # 收支
    "I-20": ["收支管理制度", "收支制度"],
    "I-22": ["收入管理", "收入凭证", "收入台账"],
    "I-23": ["票据管理", "票据台账"],
    "I-24": ["支出管理", "支出审批"],

    # 采购
    "I-25": ["采购管理制度", "采购制度"],
    "I-27": ["采购预算", "采购计划"],
    "I-28": ["采购方式"],
    "I-29": ["采购变更", "变更审批"],
    "I-30": ["采购信息公开", "中标公告"],
    "I-31": ["履约验收", "采购验收"],

    # 资产
    "I-32": ["资产管理制度"],
    "I-34": ["印章管理", "账户管理"],
    "I-35": ["资产盘点", "银行存款余额调节表"],
    "I-36": ["资产处置", "资产配置"],

    # 建设项目
    "I-37": ["建设项目管理制度", "项目管理制度"],
    "I-39": ["可行性研究", "可研报告", "项目决策"],
    "I-40": ["项目评审", "评审意见"],
    "I-41": ["工程变更"],
    "I-42": ["资金专款", "专款专用"],
    "I-43": ["竣工验收", "资产交付", "竣工决算"],

    # 合同
    "I-44": ["合同管理制度"],
    "I-46": ["合同归口管理"],
    "I-47": ["合同订立", "合同审批"],
    "I-48": ["合同履行监督", "合同跟踪"],
    "I-49": ["合同台账"],
    "I-50": ["合同印章"],

    # 内部监督
    "I-52": ["内部会计监督"],
    "I-53": ["内控检查报告", "内控自查"],
    "I-54": ["问题整改", "整改台账"],

    # 补充
    "I-55": ["补充指标"],
}


def _normalize(s: str) -> str:
    """统一全/半角括号、去多余空白，便于匹配。"""
    return (s or "").replace("(", "（").replace(")", "）").strip()


def match_subcategory(file_name: str) -> Optional[str]:
    """返回 subcategory 规范名（如「（一）预算业务控制」），找不到返回 None。"""
    s = _normalize(file_name)
    if not s:
        return None
    for canonical, kws in SUBCATEGORY_HINTS:
        for kw in kws:
            if kw in s:
                return canonical
    return None


def match_indicator(file_name: str,
                    indicators: Iterable[Indicator]) -> Optional[Indicator]:
    """v1.2 起：兼容包装 → match_indicator_by_content(file_name, "", indicators)。

    保留此函数避免破坏旧调用方。新代码请直接用 match_indicator_by_content。
    """
    return match_indicator_by_content(file_name, "", list(indicators))


def filter_materials_by_subcategory(materials: list,
                                    indicator: Indicator) -> list:
    """从材料列表中筛出与指标"子类相关"的（用于 orchestrator 共享池退化）。"""
    target = _normalize(indicator.subcategory or indicator.category or "")
    if not target:
        return materials
    out = []
    for m in materials:
        s = _normalize((m.file_name or ""))
        sub = match_subcategory(s)
        if sub and _normalize(sub) == target:
            out.append(m)
    return out


# ============================================================
# subcategory 兜底（v1.1 新增）：AI / 关键词都没命中时，
# 把材料硬绑到该子类的「制度类指标」，保证 0 未绑定
# ============================================================
SUBCATEGORY_FALLBACK: dict[str, str] = {
    "组织层面内部控制":           "I-01",
    "（一）预算业务控制":         "I-13",
    "（二）收支业务控制":         "I-20",
    "（三）政府采购业务控制":     "I-25",
    "（四）资产控制":             "I-32",
    "（五）建设项目控制":         "I-37",
    "（六）合同控制":             "I-44",
    "内部监督":                   "I-53",
    "补充指标":                   "I-55",
}


def fallback_indicator_for_subcategory(subcategory: str,
                                       indicators: Iterable[Indicator]) -> Optional[Indicator]:
    """子类 → 该子类制度类指标的兜底映射。

    优先用 SUBCATEGORY_FALLBACK 表里的 code 找指标；
    找不到时退化到 I-55「补充指标」；I-55 也没有则返回 None。
    空字符串 / None 输入直接返回 None（防止 caller 失误时误绑到补充指标）。
    """
    if not subcategory:
        return None
    code = SUBCATEGORY_FALLBACK.get(_normalize(subcategory))
    code2ind = {ind.indicator_code: ind for ind in indicators}
    if code and code in code2ind:
        return code2ind[code]
    return code2ind.get("I-55")


# ============================================================
# v1.2 新增：基于 required_materials JSON 的内容匹配
# ============================================================
def match_indicator_by_content(
    file_name: str,
    parsed_text: str,
    indicators: Iterable[Indicator],
) -> Optional[Indicator]:
    """匹配范围 = 文件名 + parsed_text 前 1000 字。

    规则：
    - 对每个指标，从其 required_materials JSON 数组拿关键词
    - haystack = file_name + parsed_text[:1000]
    - 任一关键词被 haystack 包含 → 计 1 分
    - 命中分数最高的指标返回；并列时返回 indicator_code 最小的
    - 0 分（无任何指标关键词命中）→ 返回 None
    """
    import json as _json
    haystack = _normalize(file_name) + " " + _normalize((parsed_text or "")[:1000])
    if not haystack.strip():
        return None
    scores: list[tuple[int, Indicator]] = []
    for ind in indicators:
        try:
            keywords = _json.loads(ind.required_materials or "[]")
        except Exception:
            continue
        score = sum(1 for kw in keywords if kw and str(kw) in haystack)
        if score > 0:
            scores.append((score, ind))
    if not scores:
        return None
    scores.sort(key=lambda x: (-x[0], x[1].indicator_code))
    return scores[0][1]


# ============================================================
# v1.5：子类 → 该子类「制度类」指标的默认映射（路径兜底用）
# ============================================================
SUBCATEGORY_TO_PROTOCOL_INDICATOR: dict[str, str] = {
    "（一）议事决策机制":           "I-01",
    "（一）预算业务控制":           "I-13",
    "（一）内部监督机制建立情况":   "I-51",
    "（二）内部权力运行":           "I-04",
    "（二）收支业务控制":           "I-20",
    "（三）政府采购业务控制":       "I-25",
    "（三）组织架构":               "I-08",
    "（四）财务信息":               "I-10",
    "（四）资产控制":               "I-32",
    "（五）建设项目控制":           "I-37",
    "（六）合同控制":               "I-44",
}


def match_indicator_by_path_and_content(
    relative_path: str,
    file_name: str,
    parsed_text: str,
    indicators: Iterable[Indicator],
) -> tuple[Optional[Indicator], str, str]:
    """v1.5 路径感知匹配，返回 (indicator, confidence, source) 三元组。

    confidence: "high" | "medium" | "none"
    source: "path+keyword" | "path+protocol_fallback" | "keyword_global" | "none"

    优先级：
    1. 路径含子类 + 文件名/内容命中候选指标关键词 → high / path+keyword
    2. 路径含子类 + 候选无命中 → 子类制度类指标 → medium / path+protocol_fallback
    3. 路径无子类 + 全库关键词命中 → medium / keyword_global
    4. 都不命中 → (None, "none", "none")
    """
    indicators = list(indicators)
    # 只对目录部分（去除最后的文件名）做子类匹配，避免文件名里的关键词误触发
    import posixpath as _posixpath
    dir_part = _posixpath.dirname((relative_path or "").replace("\\", "/"))
    subcategory = match_subcategory(_normalize(dir_part))
    if subcategory:
        candidates = [
            ind for ind in indicators
            if _normalize(ind.subcategory or ind.category or "") == _normalize(subcategory)
        ]
        if candidates:
            hit = match_indicator_by_content(file_name, parsed_text, candidates)
            if hit:
                return (hit, "high", "path+keyword")
            protocol_code = SUBCATEGORY_TO_PROTOCOL_INDICATOR.get(_normalize(subcategory))
            if protocol_code:
                protocol_ind = next(
                    (ind for ind in indicators if ind.indicator_code == protocol_code),
                    None,
                )
                if protocol_ind:
                    return (protocol_ind, "medium", "path+protocol_fallback")
    hit = match_indicator_by_content(file_name, parsed_text, indicators)
    if hit:
        return (hit, "medium", "keyword_global")
    return (None, "none", "none")
