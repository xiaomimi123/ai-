"""字段抽取器：正则优先（离线可用），LLM 补充缺失字段。

正则能可靠抽取的字段（金额、编号、人名标签）直接提取；
自由文本字段（项目名称、期限描述）用 LLM JSON mode 补充。
"""
from __future__ import annotations

import re
from typing import Optional

from app.crosscheck.schemas import BidFields, ContractFields, EvalFields, TenderFields
from app.parsers.base import ParsedDocument
from app.rules.utils import parse_arabic_amount, parse_cn_amount

# ── 正则工具 ──────────────────────────────────────────────
_NUM_RE = re.compile(r"[0-9][0-9,]*(?:\.[0-9]+)?")
_CN_AMOUNT_RUN = re.compile(r"[零壹贰叁肆伍陆柒捌玖拾佰仟万亿圆元角分整]{3,}")
_PROJECT_LABEL = re.compile(r"项目名称\s*[:：]\s*([^\n，,。；;]{2,30})")
_ANGLE_BRACKET = re.compile(r"《([^》]{2,30})》")
_TENDER_NO = re.compile(r"(招标|项目|采购)\s*编号\s*[:：]?\s*([A-Za-z0-9\-_（）()〔〕\[\]]+)")
_DEADLINE = re.compile(
    r"(投标截止|递交截止|开标)\s*[时日期]?\s*[:：]?\s*([^\n，,。；;]{4,30})"
)
_BUDGET_LABEL = re.compile(
    r"(预算金额|招标控制价|最高限价|采购预算|招标预算)[^:：\n]{0,15}[:：][ \t]*"
)
_BID_PRICE_LABEL = re.compile(
    r"(投标报价|投标总价|报价金额|投标价)[^:：\n]{0,15}[:：][ \t]*"
)
_BIDDER_RE = re.compile(r"投标人\s*[（(]?\s*(名称)?\s*[：:][ \t]*([^\n，,。；;]{2,30})")
_VALIDITY_RE = re.compile(r"投标有效期[^\d]*(\d+)\s*[天日]")
_WINNER_RE = re.compile(
    r"(第一候选人|中标候选人[第一1]|推荐中标人|中标人)\s*[为：:是]?\s*([^\n，,。；;]{2,30})"
)
_COMMITTEE_RE = re.compile(r"共\s*(\d+)\s*[名人]|评标委员会\s*[共由]\s*(\d+)")
_PARTY_A = re.compile(r"甲方\s*[（(]?[^:\n：]*[)）]?\s*[:：][ \t]*([^\n，,。；;]{2,30})")
_PARTY_B = re.compile(r"乙方\s*[（(]?[^:\n：]*[)）]?\s*[:：][ \t]*([^\n，,。；;]{2,30})")
_PURCHASER_RE = re.compile(r"(招标人|采购人)\s*[（(]?\s*[)）]?\s*[:：][ \t]*([^\n，,。；;]{2,20})")


def _first_amount(text: str, after_label_re: re.Pattern) -> tuple[Optional[float], str]:
    """在 label 正则匹配处之后提取第一个金额（先找大写，再找阿拉伯）。"""
    m = after_label_re.search(text)
    if not m:
        return None, ""
    snippet = text[m.end(): m.end() + 60]
    cn = _CN_AMOUNT_RUN.search(snippet)
    if cn:
        val = parse_cn_amount(cn.group())
        if val:
            return val, cn.group()
    ar = _NUM_RE.search(snippet)
    if ar:
        try:
            return round(float(ar.group().replace(",", "")), 2), ar.group()
        except ValueError:
            pass
    return None, ""


def _project_name(text: str) -> Optional[str]:
    m = _PROJECT_LABEL.search(text[:500])
    if m:
        return m.group(1).strip()
    # 退化：首个《xxx》引号内容
    m2 = _ANGLE_BRACKET.search(text[:300])
    return m2.group(1).strip() if m2 else None


def _llm_supplement(doc: ParsedDocument, partial: dict, doc_type: str) -> dict:
    """用 LLM 补充正则未能填充的字段（项目名称等自由文本）。

    离线 stub 返回空，不影响已有正则结果。
    """
    missing = [k for k, v in partial.items() if v is None or v == ""]
    if not missing:
        return partial
    try:
        from app.llm import get_llm_client

        llm = get_llm_client()
        fields_desc = "、".join(missing)
        schema_parts = ['"{}": "..."'.format(k) for k in missing]
        json_schema = "{" + ", ".join(schema_parts) + "}"
        prompt = (
            f"从以下【{doc_type}】文本中抽取：{fields_desc}。"
            f"只输出 JSON，格式 {json_schema}。\n\n"
            f"文本（节选）：\n{doc.text[:3000]}"
        )
        result = llm.extract_json(prompt)
        if isinstance(result, dict):
            for k in missing:
                if k in result and result[k] and result[k] != "null":
                    partial[k] = result[k]
    except Exception:
        pass
    return partial


# ── 各类型抽取 ────────────────────────────────────────────

def extract_tender(doc: ParsedDocument) -> TenderFields:
    text = doc.text
    budget, budget_raw = _first_amount(text, _BUDGET_LABEL)
    tn = _TENDER_NO.search(text)
    dl = _DEADLINE.search(text)
    pr = _PURCHASER_RE.search(text)

    f = TenderFields(
        project_name=_project_name(text),
        budget=budget,
        budget_raw=budget_raw,
        deadline=dl.group(2).strip() if dl else "",
        purchaser=pr.group(2).strip() if pr else "",
        tender_number=tn.group(2).strip() if tn else "",
    )
    # LLM 补 project_name（如正则未取到）
    partial = {"project_name": f.project_name}
    filled = _llm_supplement(doc, partial, "招标文件")
    f.project_name = filled.get("project_name") or f.project_name
    return f


def extract_bid(doc: ParsedDocument) -> BidFields:
    text = doc.text
    price, price_raw = _first_amount(text, _BID_PRICE_LABEL)
    bm = _BIDDER_RE.search(text)
    vm = _VALIDITY_RE.search(text)

    f = BidFields(
        project_name=_project_name(text),
        bidder_name=bm.group(2).strip() if bm else "",
        bid_price=price,
        bid_price_raw=price_raw,
        validity_days=int(vm.group(1)) if vm else None,
    )
    partial = {"project_name": f.project_name, "bidder_name": f.bidder_name or None}
    filled = _llm_supplement(doc, partial, "投标文件")
    f.project_name = filled.get("project_name") or f.project_name
    if not f.bidder_name:
        f.bidder_name = filled.get("bidder_name") or ""
    return f


def extract_eval(doc: ParsedDocument) -> EvalFields:
    text = doc.text
    wm = _WINNER_RE.search(text)
    cm = _COMMITTEE_RE.search(text)
    size = None
    if cm:
        size = int(cm.group(1) or cm.group(2))

    # 中标价：Winner 名字后 60 字符内找金额
    winner_price = None
    if wm:
        snippet = text[wm.end(): wm.end() + 80]
        cn = _CN_AMOUNT_RUN.search(snippet)
        winner_price = parse_cn_amount(cn.group()) if cn else parse_arabic_amount(snippet)

    f = EvalFields(
        project_name=_project_name(text),
        winner_name=wm.group(2).strip() if wm else "",
        winner_price=winner_price,
        committee_size=size,
    )
    partial = {"project_name": f.project_name, "winner_name": f.winner_name or None}
    filled = _llm_supplement(doc, partial, "评标报告")
    f.project_name = filled.get("project_name") or f.project_name
    if not f.winner_name:
        f.winner_name = filled.get("winner_name") or ""
    return f


def extract_contract(doc: ParsedDocument) -> ContractFields:
    text = doc.text
    # 合同金额：用已有工具全文扫描
    amount: Optional[float] = None
    amount_raw = ""
    cn = _CN_AMOUNT_RUN.search(text)
    if cn:
        amount = parse_cn_amount(cn.group())
        amount_raw = cn.group()
    if amount is None:
        amount = parse_arabic_amount(text)
        amount_raw = str(amount) if amount else ""

    pa = _PARTY_A.search(text)
    pb = _PARTY_B.search(text)

    # 合同期限
    dur_m = re.search(r"(合同期限|服务期限|履行期限)[^，,\n：:]{0,4}[:：]?([^\n，,。；;]{4,30})", text)

    f = ContractFields(
        project_name=_project_name(text),
        party_a=pa.group(1).strip() if pa else "",
        party_b=pb.group(1).strip() if pb else "",
        amount=amount,
        amount_raw=amount_raw,
        duration=dur_m.group(2).strip() if dur_m else "",
    )
    partial = {"project_name": f.project_name, "party_b": f.party_b or None}
    filled = _llm_supplement(doc, partial, "合同")
    f.project_name = filled.get("project_name") or f.project_name
    if not f.party_b:
        f.party_b = filled.get("party_b") or ""
    return f
