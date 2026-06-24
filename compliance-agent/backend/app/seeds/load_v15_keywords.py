"""v1.5 关键词清单：补充到 Indicator.required_materials（合并，不覆盖）。

来源：用户提供的 54 项指标关键词规则。
策略：UPDATE 已存在的 indicator_code；缺失的跳过；保留原 required_materials 中的人工关键词。
"""
from __future__ import annotations

import json
from typing import Dict, List

from sqlalchemy.orm import Session

from app.models import Indicator, SessionLocal


KEYWORDS_BY_CODE: Dict[str, List[str]] = {
    "I-01": ["三重一大决策制度", "三重一大议事规则", "三重一大决策办法", "三重一大制度"],
    "I-02": ["三重一大会议记录", "决策会议纪要", "三重一大议题"],
    "I-03": ["部门职能职责", "部门职能", "内设机构职能", "部门职责分工", "内部机构设置"],
    "I-04": ["岗位职责说明", "岗位说明书", "岗位职责"],
    "I-05": ["分级授权制度", "分级授权办法"],
    "I-06": ["轮岗制度", "轮岗办法", "干部定期交流", "定期轮岗制度", "轮岗交流办法"],
    "I-07": ["轮岗通知", "轮岗表", "轮岗记录", "干部交流文件"],
    "I-08": ["成立领导小组", "内部控制工作方案", "内部控制领导小组", "内控牵头部门"],
    "I-09": ["内部控制领导小组会议纪要", "内控会议"],
    "I-10": ["财务报告", "决算报告", "科目余额表", "财务会计"],
    "I-11": ["信息系统功能截图", "内部控制信息系统功能"],
    "I-12": ["信息化控制措施", "信息化管理制度", "信息化管理办法", "信息系统管理"],
    "I-13": ["预算管理办法", "预算管理制度", "预算制度"],
    "I-15": ["预算编制说明"],
    "I-16": ["预算公开审批", "决算公开审批", "预算公开文件", "决算公开文件"],
    "I-17": ["预算执行预警处理说明", "预算预警"],
    "I-18": ["决算编制审批", "决算分析说明"],
    "I-19": ["绩效评估", "绩效监控", "绩效评价", "绩效管理"],
    "I-20": ["收支管理办法", "收支管理制度", "收支制度"],
    "I-22": ["非税收入上缴说明", "其他收入管理"],
    "I-23": ["财政票据申请审批表", "财政电子票据管理台账", "一体化票据管理"],
    "I-24": ["支出报销审批表", "支出管理"],
    "I-25": ["政府采购制度", "政府采购管理办法", "采购管理办法", "采购制度"],
    "I-27": ["政府采购预算审批表", "政府采购实施计划"],
    "I-28": ["采购方式审批表"],
    "I-29": ["采购方式变更审批表", "采购变更"],
    "I-30": ["采购信息公开"],
    "I-31": ["采购验收证明", "履约验收"],
    "I-32": ["国有资产管理办法", "资产管理制度", "资产管理办法",
             "资产配置", "资产使用", "资产处置"],
    "I-34": ["银行账户开立", "银行账户变更", "银行账户注销", "银行印章保管"],
    "I-35": ["资产盘点表"],
    "I-36": ["资产处置审批表", "资产领用表"],
    "I-37": ["基本建设管理制度", "基本建设制度", "基建管理办法"],
    "I-39": ["可行性研究报告"],
    "I-40": ["基建项目评审报告"],
    "I-41": ["工程变更审批表"],
    "I-42": ["基建项目资金支付审批表"],
    "I-43": ["竣工决算表", "资产移交表"],
    "I-44": ["合同管理制度", "合同管理办法", "合同制度"],
    "I-46": ["合同审批表"],
    "I-47": ["合同订立法律意见书"],
    "I-48": ["合同履行检查表"],
    "I-49": ["合同台账"],
    "I-50": ["合同印章保管"],
    "I-51": ["内部控制基本制度", "内部控制工作方案"],
    "I-52": ["内部会计监督", "监督制度"],
    "I-53": ["内部控制检查表", "内部控制检查报告", "审计报告", "检查报告"],
    "I-54": ["整改报告", "整改情况说明", "问题整改"],
}


def apply(db: Session) -> dict:
    """按 indicator_code 合并关键词到 required_materials。

    返回 {updated: int, skipped: list[str]}
    """
    updated = 0
    skipped: list[str] = []
    for code, new_kws in KEYWORDS_BY_CODE.items():
        ind = db.query(Indicator).filter_by(indicator_code=code).first()
        if not ind:
            skipped.append(code)
            continue
        try:
            existing = json.loads(ind.required_materials or "[]")
        except Exception:
            existing = []
        merged = list(existing)
        for kw in new_kws:
            if kw not in merged:
                merged.append(kw)
        ind.required_materials = json.dumps(merged, ensure_ascii=False)
        updated += 1
    db.commit()
    return {"updated": updated, "skipped": skipped}


if __name__ == "__main__":
    print("v1.5 关键词清单迁移开始 ...")
    with SessionLocal() as db:
        r = apply(db)
    print(f"更新 {r['updated']} / 跳过 {len(r['skipped'])}（{r['skipped'][:5]}…）")
