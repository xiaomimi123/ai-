# 核查发现按指标聚合显示（v1.6） — 设计文档

**日期**：2026-06-24
**模块**：工作底稿 → 核查发现 子页
**版本**：v1.6
**作者**：内控评价 AI 智能体（与用户共同 brainstorm）

---

## 1. 背景与问题

当前一个任务上传 N 份材料 × 5 维度审查 → 平铺产出 N×K 条 finding（实测最多 476 条）。
工作底稿"核查发现" tab 顺序列出所有 finding，单位审计师无法在一屏内把握全貌，逐条复核效率极低。

用户原话：
> N 个材料对应同一个指标，一个指标 N 份材料检查五个方面有无问题（真实性 / 完整性 / 规范性 / 重复性 / 匹配性），把 N 份材料存在的问题集中在一个指标可以 N 个问题来描述附对应 N 个材料，一个单位最多 55 个问题。

目标：从"finding 平铺列表"切换为"指标卡片列表"，把 476 条压缩到最多 ~55 张可一键操作的卡片。

---

## 2. 目标与非目标

### 2.1 目标

- 工作底稿"核查发现" tab：按 `indicator_id` 聚合显示 finding，每个指标一张卡片。
- 卡片头展示：指标编号 + 名称 + 该指标下 finding 总数 + 5 维度分项小计。
- 卡片操作：**「该指标全部确认」**「该指标全部忽略」**两键**（仅作用于未复核条目）。
- 卡片展开：列出该指标下所有 finding，按 5 维度二级分组，每条仍保留单条「✓ ✗」按钮。
- 顶部维度级批量按钮（"忽略所有 真实性问题"等）**保留**，作为跨指标横切操作。
- 默认全部折叠；点击卡 header 切换展开/折叠。

### 2.1.1 维度命名映射（重要）

用户原话用"规范性"，DB 中实际字段值是 `合规性`（沿用 v1.5 之前的 `finding_type` 取值）。
本方案**沿用 DB 命名**，前端 5 维度顺序与文案统一为：

```
真实性 → 完整性 → 合规性 → 重复性 → 匹配性
```

不改 `finding_type` 取值，避免污染历史数据与评分公式。UI 上展示文案与 DB 字段值一致。

### 2.2 非目标

- 不改 DB schema（不动 `findings` 表）。
- 不改 finding 生成逻辑（数量、内容、severity、source 都不动）。
- 不改 finding 详情面板（右侧详情视图保持原样）。
- 不改其他 tab（材料 / 工作底稿正表 / 评分）。
- 不动评分公式。

---

## 3. 设计概览

### 3.1 数据流

```
GET /api/tasks/{id}
  → resp.findings: [Finding, ...]   ← 既有，不动
  → resp.indicators: [Indicator, ...]   ← 既有，不动

前端 renderFindings():
  filtered = findings.filter(applyFilters)
  grouped = groupBy(filtered, f => f.indicator_id || "__unbound__")
  render(grouped):
    sortedKeys = indicator_id 按 code 升序，未绑放最后
    for each indicator:
      <div class="finding-indicator-card">
        header: code + name + 总数 + 5 类 badge + [全部确认][全部忽略]
        body (默认 hidden):
          for each 维度 in [真实性, 完整性, 合规性, 重复性, 匹配性]:
            <div class="finding-dim-group">
              for each finding in this dim:
                <div class="finding-row">...</div>
```

### 3.2 后端 API 变化

| Endpoint | 状态 | 说明 |
|---|---|---|
| `GET /api/tasks/{task_id}` | **不动** | 已返回 findings + indicators，完全够用 |
| `POST /api/findings/{id}/review` | **不动** | 现有单条接口 |
| `POST /api/tasks/{task_id}/findings/batch-review` | **新增** | 按 indicator_id 或 finding_type 批量复核 |

#### 新增接口规格

```
POST /api/tasks/{task_id}/findings/batch-review
Body: {
  "status": "confirmed" | "ignored" | "adjusted",
  "note": string,
  "indicator_id": int | null,      # 限定该指标下
  "finding_type": string | null,   # 限定该类型
  "only_pending": bool = true      # 只更新未复核条目（避免覆盖已审）
}
Response: { "updated": int, "skipped": int }
```

筛选语义：`indicator_id` 与 `finding_type` 取交集；都为 null 时报 400（拒绝"任务下全选"误操作）。

> **为何要新加接口**：现有"忽略所有 X 类问题"是前端 `for { await PATCH }` N 次串行调用（见 `app.js:1858-1865`），477 条 finding 会跑近 1 分钟。新接口一次 DB UPDATE + 一条 audit log，秒级返回，且并发安全。

### 3.3 前端模块改动

| 文件 | 改动 |
|---|---|
| `frontend/app.js` | 1. 重写 `renderFindings()`（约 line 1760-1810）<br>2. 新增 `_groupFindingsByIndicator()` 工具<br>3. 新增 `toggleIndicatorCard(indicator_id)` / `bulkReviewIndicator(indicator_id, status)`<br>4. 改造现有 `bulkIgnoreFindings(dim)` 调新批量接口（性能提升） |
| `frontend/index.html` | `#finding-list` 容器结构不变（卡片在 JS 内渲染） |
| `frontend/style.css` | 新增 `.finding-indicator-card / .finding-indicator-header / .finding-dim-group` 等样式 |

### 3.4 错误处理

- 批量接口失败 → toast 红字 + console 详细错误 + 不刷新；用户可单条手动处理。
- 部分 finding 已被他人复核 → `only_pending=true` 跳过，返回 `skipped > 0`，toast 友好提示。
- 未绑指标的 finding（`indicator_id IS NULL`）：在 UI 单独"未绑指标"分组，卡 header 不显示 code，操作行为相同。

---

## 4. UI 设计细节

### 4.1 卡片折叠态（默认）

```
┌───────────────────────────────────────────────────────────┐
│  ▶ I-04 分岗设权与定期轮岗      共 12 条 · 待复核 12       │
│     真实 4 │ 完整 3 │ 合规 2 │ 重复 0 │ 匹配 3            │
│                              [✓ 全部确认]  [✗ 全部忽略]   │
└───────────────────────────────────────────────────────────┘
```

- 卡片整行点击 = 展开/折叠（除右侧两按钮）；按钮自身阻止冒泡。
- 5 类 badge：颜色与现有 `_BULK_DIMS` chip 一致（真实=橙、完整=蓝、合规=红、重复=灰、匹配=紫）；零计数维度灰显或省略。
- "待复核 N"：仅 `review_status == 'pending'` 计数；全部已复核时 header 自动变浅灰。

### 4.2 卡片展开态

```
┌───────────────────────────────────────────────────────────┐
│  ▼ I-04 分岗设权与定期轮岗      共 12 条 · 待复核 8        │
│     真实 4 │ 完整 3 │ 合规 2 │ 重复 0 │ 匹配 3            │
│                              [✓ 全部确认]  [✗ 全部忽略]   │
│  ──────────────────────────────────────────────────────── │
│  ▸ 真实性问题（4）                                        │
│    · 材料未识别公章 — 岗位职责说明书.pdf   [✓][✗]        │
│    · 材料疑似草稿 — 内控岗位.docx          [✓][✗]✓       │
│    · ...                                                  │
│  ▸ 完整性问题（3）                                        │
│    · ...                                                  │
└───────────────────────────────────────────────────────────┘
```

- 二级 5 类分组始终展开（已经在一级折叠了，不需要再折一层）。
- 单条 finding 行：左侧描述（截 100 字）+ 右侧 [✓ 确认][✗ 忽略] 单条按钮；已复核显示状态徽章。
- 点击单条 → 右侧详情面板显示完整 finding（沿用现有逻辑）。

### 4.3 排序

- 一级（指标卡）：`indicator.code` 升序（I-01 → I-54 → I-55）；未绑指标的 `__unbound__` 分组永远放最末。
- 二级（维度组）：固定 `[真实性, 完整性, 合规性, 重复性, 匹配性]` 顺序。
- 三级（finding 行）：按 severity 倒序（高 → 中 → 低），同 severity 按 id 升序。

### 4.4 顶部维度横切按钮

保留现有"忽略所有 真实性问题（N）"等按钮（`updateBulkActions` 区块），但内部改调新批量接口（不再 for 循环 PATCH）。

---

## 5. 测试范围

### 5.1 后端 pytest

新增 `backend/tests/test_findings_batch_review.py`：

| Case | 期望 |
|---|---|
| 仅 indicator_id 限定 | 该指标下所有 pending → status，其他不动 |
| 仅 finding_type 限定 | 该类型所有 pending → status |
| 两者都传 | 交集（该指标 + 该类型） |
| 两者都不传 | 400 拒绝 |
| `only_pending=true` 已复核条目 | 跳过，计入 skipped |
| 任务不存在 | 404 |
| 非审计员调用 | 403 |
| audit log 写入 | `finding.batch_review` 一条，含 task_id/筛选条件/updated count |

### 5.2 前端 Playwright e2e

扩展 `/tmp/v15_e2e_test.py` 或新加 `/tmp/v16_e2e_test.py`：

1. 上传 3 份不同指标的材料 → 触发 ≥9 条 finding。
2. 进核查发现 tab → 验证 ≥3 张卡片渲染（按 indicator_code 排序）。
3. 卡片默认折叠 → 截图验证。
4. 点击第 1 张卡 → 展开 → 截图验证 5 类分组显示。
5. 点「该指标全部忽略」→ 验证该卡 finding 全部变 ignored，其他卡不动。
6. 点顶部"忽略所有 真实性问题" → 验证跨卡片真实性条目全 ignored。

### 5.3 回归 pytest

跑全量 `pytest backend/tests/` — 期望 162 + 新增 → 全绿。

---

## 6. 兼容性 / 风险 / 回滚

| 项 | 评估 |
|---|---|
| DB schema | 零改动 → 零风险 |
| 现有 finding API | 不动 → 旧客户端/旧脚本不受影响 |
| 评分公式 | 不动 |
| 用户学习成本 | UI 大变；首次使用 5-10 秒适应（卡片折叠/展开是常见模式） |
| 性能 | 476 条 finding 前端 reduce 分组耗时 < 10ms（实测 V8 引擎），渲染 ~55 张卡片 < 50ms |
| 批量接口安全 | `only_pending=true` 默认开 → 不会误覆盖他人复核结果 |
| 回滚方案 | feature 分支 git revert（前端 + 后端 1 个 commit），1 步回到平铺模式 |

---

## 7. 工作量预估

| 阶段 | 时间 |
|---|---|
| 后端批量接口 + service + audit log | 1 h |
| 后端 pytest（8 个 case） | 1 h |
| 前端聚合渲染 + 卡片样式 | 2 h |
| 前端批量按钮 + 单条按钮交互 | 1 h |
| 前端 Playwright e2e | 1 h |
| 部署 + 端到端冒烟（生产 ECS） | 1 h |
| **合计** | **~7 h（约 1 个工作日）** |

---

## 8. 部署约束

- 阿里云 ECS `/opt/audit/compliance-agent/` **不是 git 仓库**，部署须用 `scp` + `docker compose cp` + `restart`，每次 cp 后必跑 `grep` 验证容器内代码到位。
- 后端改动需 `docker compose restart api worker`；前端只需 cp 静态文件。
- DB 无 schema 改动，不需要 `pg_dump`。

---

## 9. 验收标准

- [ ] 工作底稿"核查发现" tab 显示按指标聚合的卡片列表，最多 ~55 张（实测 task）。
- [ ] 每张卡 header 显示：code + name + 总数 + 5 维度分项 + 两个批量按钮。
- [ ] 点 header 展开 → 看到 5 类二级分组 + 每条 finding 单条按钮。
- [ ] 「该指标全部确认/忽略」一次成功，刷新后只该指标下 pending → status。
- [ ] 顶部"忽略所有 X 问题"仍可用，且响应时间从 ~60s 降到 < 2s（476 条规模）。
- [ ] pytest 全绿（含新增 8 个 case）。
- [ ] Playwright e2e 6 步全通过 + 截图归档。
- [ ] 生产 ECS 上线 + 用现网真实任务验证 ≥ 50 张卡片渲染流畅。
