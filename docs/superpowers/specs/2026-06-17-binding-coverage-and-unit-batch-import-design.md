# 优化设计：材料绑定覆盖率 + 单位 Excel 批量导入

- 日期：2026-06-17
- 涉及模块：`backend/app/services/ai_material_classifier.py` · `backend/app/services/audit_service.py` · `backend/app/services/material_matcher.py` · `backend/app/api/audit_routes.py` · `frontend/app.js`
- 关联讨论：用户反馈 — ① 材料过多时部分材料未绑定到任何指标；② 后台单位管理希望支持 Excel 批量导入

## 一、背景与目标

### 1.1 问题 1：材料 → 指标 绑定覆盖率不足

当前 `auto_bind_materials` 流程分两阶段：

1. **关键词匹配**（`material_matcher.match_indicator`）：基于文件名命中子类 + 指标关键词，未命中则保留为"未绑定"
2. **AI 阅读分类**（`ai_classify_materials`）：按 batch=15 喂给 LLM，prompt 明示"实在判断不出来就省略该材料"

材料量大时（如 50+ 份）出现两类痛点（用户反馈确认）：

- **AI 漏处理**：LLM 单批返回的 mapping 数量 < batch 实际数量，部分材料没被分类
- **覆盖率不足**：经过两阶段后仍有材料保持"未绑定"，用户期望"所有材料都能绑上某个指标"

### 1.2 问题 2：单位列表不支持批量导入

后台管理 → 单位 模块目前仅支持「单条新增」（`POST /api/units`）。用户实际场景：从财政部 / 编办拿到一个含 5267 行的 Excel（两列：代码、单位名称），需要一次性入库。

### 1.3 目标

- **目标 1**：材料自动绑定后，"未绑定材料数" → 0（强兜底）
- **目标 2**：后台管理 → 单位 列表页支持上传 Excel 批量入库，已存在的同名单位跳过

## 二、问题 1 设计：双层兜底绑定（方案 B）

### 2.1 现状回顾

```
unbound_materials
   └─ [阶段1] match_indicator(file_name)  → keyword_bound
        └─ still_unbound
              └─ [阶段2] ai_classify_materials(LLM)  → ai_bound
                    └─ 残留 still_unbound  ← 当前直接放任不管
```

### 2.2 方案 B 关键改动

#### 2.2.1 改 prompt（去掉"可省略"开关）

`ai_material_classifier.py` 的 `SYSTEM_PROMPT` 与 `_build_prompt`：

- 删除"实在判断不出来就省略该材料"
- 改为"必须为每份材料返回 1 个 indicator_code，**即使把握不大也必须选最接近的一项**，禁止省略"
- prompt 末尾追加：返回必须覆盖**所有传入的 material_id**，校验项

#### 2.2.2 批次参数与完整性校验

- `BATCH_SIZE` 15 → **10**（缩小批次降低漏处理）
- `TEXT_PREVIEW` 800 → **1500**（给 LLM 更多判断信号）
- `max_tokens` 4096 → **8192**
- 单批返回后校验 `mapping 行数 == batch 长度`
  - 如不等：把缺失的 material_id 单独再问一次 LLM（同样 prompt 模板，最多 1 次重试）
  - 重试仍失败的材料 → 落到第 3 阶段处理

#### 2.2.3 新增第 3 阶段：subcategory 兜底（`audit_service.auto_bind_materials`）

```
经过阶段1+2仍 still_unbound 的材料
   ├─ match_subcategory(file_name + parsed_text[:500])  → 子类
   │     └─ 找到 → 绑到该子类的「制度类指标」（fallback table）
   └─ 未找到子类 → 绑到 I-55「补充指标」（最终兜底）
```

子类 → 制度类指标的 fallback 表（写在 `material_matcher.py`，与 `INDICATOR_HINTS` 并列）：

| subcategory | fallback indicator_code |
|---|---|
| 组织层面内部控制 | I-01 三重一大决策制度 |
| （一）预算业务控制 | I-13 预算管理制度 |
| （二）收支业务控制 | I-20 收支管理制度 |
| （三）政府采购业务控制 | I-25 采购管理制度 |
| （四）资产控制 | I-32 资产管理制度 |
| （五）建设项目控制 | I-37 建设项目管理制度 |
| （六）合同控制 | I-44 合同管理制度 |
| 内部监督 | I-53 内控检查报告 |
| 补充指标 / 未识别 | I-55 补充指标 |

新增函数：`material_matcher.fallback_indicator_for_subcategory(subcategory: str, indicators) -> Optional[Indicator]`

#### 2.2.4 统计返回新增字段

`auto_bind_materials` 返回值新增：

```python
{
    "checked": int,
    "keyword_bound": int,
    "ai_bound": int,
    "fallback_bound": int,        # 新增：第 3 阶段兜底数
    "still_unbound": 0,            # 新增方案后应恒为 0
    "samples": [...],              # 新增 source="fallback" 标记
    "ai_used": bool,
}
```

前端文案：`关键词 X · AI Y · 兜底 Z · 仍未绑 0`

### 2.3 错误处理与回退

- **LLM 整体不可用（StubLLMClient / API 异常）**：跳过阶段 2，直接进入阶段 3 兜底，仍能保证全绑
- **LLM 返回坏 JSON**：现有 `try/except continue` 模式保留，残留材料落到阶段 3
- **第 3 阶段 fallback 表里某 indicator_code 在库中找不到**（如尚未 seed I-13）：再退化绑到 I-55；I-55 也找不到 → 绑到子类内 indicator_code 最小的那条

### 2.4 数据流时序

```
用户点击「自动绑定」
   └─ POST /api/tasks/{id}/materials/auto-bind
        └─ audit_service.auto_bind_materials(task)
              ├─ stage1: keyword (sync)
              ├─ stage2: ai_classify_materials(llm)
              │     ├─ batch 1 → 检查完整性 → 漏的补单问
              │     ├─ batch 2 → ...
              │     └─ ...
              └─ stage3: fallback_indicator_for_subcategory
        └─ 返回 {checked, keyword_bound, ai_bound, fallback_bound, still_unbound=0, samples}
```

### 2.5 测试

`backend/tests/test_auto_bind.py` 新增/扩展用例：

1. `test_prompt_forbids_skip` — 单元测试：构造 mock LLM 返回 mapping 数 < batch 数，验证补单调用发起
2. `test_fallback_for_subcategory` — 给一份文件名只有"预算公开 2025.pdf"、indicator_code 关键词未命中、AI 返回空时，确保最终绑到 I-13
3. `test_fallback_for_unmatched` — 给文件名"未知文件.pdf"且 parsed_text 为空，最终落到 I-55
4. `test_still_unbound_zero_after_v11` — 端到端：传入 20 份混合材料，跑完三阶段后 `still_unbound == 0`
5. `test_stub_llm_falls_through_to_fallback` — LLM 停用模式下也能 100% 绑定

## 三、问题 2 设计：单位 Excel 批量导入

### 3.1 后端 API

新接口：`POST /api/units/import-from-file`

| 字段 | 说明 |
|---|---|
| `file` (multipart) | .xlsx / .xls / .csv 任一 |
| `dry_run` (query, bool) | true 仅返回前 10 行预览不入库 |

返回：

```json
{
  "preview": [{"name": "...", "code": "..."}, ...],   // 前 10 行
  "total": 5267,
  "inserted": 5260,
  "skipped": 7,                                        // 同名已存在
  "errors": ["第 234 行 name 为空"],
  "note": "Excel 表头识别：代码 / 单位名称"
}
```

权限：`Depends(require_admin)`（与"评价指标导入"一致）。

### 3.2 服务层

新增 `backend/app/services/unit_import_service.py`：

```python
def import_units_from_xlsx(db, file_bytes, file_name, dry_run=False, user=None) -> dict:
    rows = _parse_units_file(file_bytes, file_name)  # 自动识别表头
    preview = rows[:10]
    if dry_run:
        return {"preview": preview, "total": len(rows), "note": header_note}
    existing_names = {u.name for u in db.query(AuditUnit.name).all()}
    inserted, skipped, errors = 0, 0, []
    for i, row in enumerate(rows, start=2):  # 2 = Excel 数据起始行
        name = (row.get("name") or "").strip()
        if not name:
            errors.append(f"第 {i} 行 name 为空")
            continue
        if name in existing_names:
            skipped += 1
            continue
        db.add(AuditUnit(name=name, code=row.get("code", ""), level="单位"))
        existing_names.add(name)  # 防本批内重名
        inserted += 1
    log_action(db, user, "unit.batch_import", target_type="unit", target_id=0,
               detail=f"批量导入 总{len(rows)} 入{inserted} 跳{skipped} 错{len(errors)}")
    db.commit()
    return {"total": len(rows), "inserted": inserted, "skipped": skipped, "errors": errors[:20]}
```

#### 表头识别（`_parse_units_file`）

支持的别名（不区分大小写、忽略空白）：

- name 列：`单位名称` / `名称` / `机构名称` / `name`
- code 列：`代码` / `编号` / `code` / `机构代码` / `统一信用代码`

实现：用 openpyxl 读第 1 行作为表头，逐列在别名表里找命中。.csv 走 `csv.DictReader`。

未识别表头 → 抛 `ValueError("Excel 表头无法识别，请确保含『名称』和『代码』列")`，路由层转 400。

### 3.3 前端

`frontend/app.js`：

1. 后台管理 → 单位 列表页顶部加按钮「批量导入」
2. 点击 → 走与"评价指标导入"完全相同的对话框组件（已抽象为 `openBatchImportDialog`），传入 endpoint = `/api/units/import-from-file`
3. 弹层展示：
   - 文件选择
   - 上传按钮（先 `dry_run=true` 拉预览）
   - 预览前 10 行 + 表头识别提示
   - 「确认导入」按钮（`dry_run=false`）
   - 结果 banner：`✓ 入库 5260 / 跳过 7 / 错误 0`

### 3.4 错误处理

- 文件格式不支持 (.docx 等) → 400 `Excel 文件格式不支持`
- 表头无法识别 → 400 `Excel 表头无法识别...`
- 单行 name 空 → 计入 errors，继续处理
- 整体事务失败（DB 错误） → 500 + log

### 3.5 测试

`backend/tests/test_unit_import.py`：

1. `test_xlsx_standard_header` — 上传用户给的样本 5267 行，验证 inserted=5267 skipped=0
2. `test_skip_duplicate_names` — 库里已有 100 条 → inserted=5167 skipped=100
3. `test_header_aliases` — 「编号 / 机构名称」表头也能识别
4. `test_invalid_header_returns_400` — 表头为「a / b」抛 400
5. `test_csv_input` — 同样数据走 CSV 也能导入
6. `test_dry_run_returns_preview_only` — DB 不被写

## 四、依赖 / 兼容性

- `openpyxl==3.1.2` 已在 `requirements.txt`（用于工作底稿导出）
- 数据库结构无改动（`AuditUnit` 字段全部够用）
- 现有 API 行为 100% 向后兼容（只**新增**接口和返回字段，不删 / 不改语义）
- 现有"自动绑定"对外 API 不变（`POST /api/tasks/{id}/materials/auto-bind` 返回多了 `fallback_bound` 字段）

## 五、风险与回退

| 风险 | 缓解 |
|---|---|
| 第 3 阶段兜底硬塞到"制度类指标"，可能与材料实际语义不符 | 兜底材料在工作底稿上仍由审计师人工复核改正；统计返回 `fallback_bound` 让用户感知比例；可加 `enable_fallback` 开关由前端控制 |
| LLM batch 缩到 10、prompt 加长，调用成本可能上升 ~30% | DeepSeek/Claude 实测可接受；后续可调回 batch=15 用流式校验 |
| 5267 行单事务 commit 可能慢 / 锁表 | 实测 5000 行 INSERT 在 PG < 5 秒；如未来量级到 5w+ 再改批 commit |

回退策略：所有改动均在新分支，若上线后用户反馈"误绑严重"，可一键回滚到改前版本，DB 结构无需变更。

## 六、验收标准

- [ ] 用户上传 ≥50 份材料 → 点「自动绑定」→ 结果显示 `still_unbound = 0`
- [ ] 工作底稿每条指标至少能从兜底来源拉到 1 份关联材料
- [ ] 后台管理 → 单位 → 批量导入 → 选用户给的 5267 行 xlsx → 成功导入，banner 显示 `入库 5267 / 跳过 0`
- [ ] 重复导入同份 xlsx → 第二次 banner 显示 `入库 0 / 跳过 5267`
- [ ] 上传 .csv 同字段也能导入
- [ ] backend pytest 全部新增用例通过
- [ ] 现有 pytest 用例全部不变红
