# LLM 余额不足友好提示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 AI 核查任务因 DeepSeek 余额不足（HTTP 402）失败时，`AuditTask.summary` 显示明确的中文提示"LLM 服务余额不足，请联系管理员充值后重新运行任务。"，而不是当前的技术错误串。

**Architecture:** 在 `orchestrator.run_audit` 现有的 `except Exception` 兜底里加一层错误分类 helper（`_classify_run_audit_error`），基于 `str(exc).lower()` contains 匹配一组 needle 关键词（`insufficient balance` / `error code: 402` 等）。命中 → 写友好文案 + 打分类 log；未命中 → 保持现有 `f"核查失败：{exc}"`。

**Tech Stack:** Python 3.11 + pytest + SQLAlchemy（服务器 stub LLM 测试环境）。

## Global Constraints

- 仅改 backend `orchestrator.py`（+ 新测试文件），不改前端 / API schema / DB schema
- 不新增 `task.status` 枚举值（复用现有 `"failed"`）
- 不改 LLM client 层的 exception class（openai SDK 版本升级会换 class 名字，字符串匹配抗版本变动）
- summary 文案固定为 **`"LLM 服务余额不足，请联系管理员充值后重新运行任务。"`**（复制自 spec，一字不改）
- 6 个 needle 大小写不敏感：`"insufficient balance"`、`"insufficient_balance"`、`"error code: 402"`、`"payment required"`、`"余额不足"`、`"账户欠费"`

---

## File Structure

| 文件 | 变更 | 责任 |
|------|-----|------|
| `compliance-agent/backend/app/engine/orchestrator.py` | Modify | 加 `_INSUFFICIENT_BALANCE_NEEDLES` 常量 + `_classify_run_audit_error()` 函数 + 改 `run_audit()` 内 except 块（`orchestrator.py:283-286` 段） |
| `compliance-agent/backend/tests/test_v22_llm_insufficient_balance.py` | Create | 3 条单元 + 1 条集成，共 4 条 case |

---

## Task 1：写单元测试（RED）

**Files:**
- Create: `compliance-agent/backend/tests/test_v22_llm_insufficient_balance.py`

**Interfaces:**
- Consumes: 无（需要 `_classify_run_audit_error` 在 Task 2 才存在）
- Produces: `test_v22_llm_insufficient_balance.py::test_classify_insufficient_balance_deepseek_style` 等 3 条单元 case

- [ ] **Step 1: 创建测试文件（只写 3 条单元 case，集成 case 放 Task 4）**

`compliance-agent/backend/tests/test_v22_llm_insufficient_balance.py`：

```python
"""v2.2 LLM 余额不足友好提示测试。

单元测试直接验证 orchestrator._classify_run_audit_error 分类逻辑；
集成测试在 Task 4 追加，通过 monkeypatch LLM 让 run_audit 走 402 分支。
"""
from __future__ import annotations

import pytest


# ============================================================
# 单元：_classify_run_audit_error 分类逻辑
# ============================================================
def test_classify_insufficient_balance_deepseek_style():
    """DeepSeek 官方 402 报文的字符串形式，应归类为 insufficient_balance。"""
    from app.engine.orchestrator import _classify_run_audit_error

    exc = Exception(
        "Error code: 402 - {'error': "
        "{'message': 'Insufficient Balance', 'type': 'authentication_error', "
        "'code': 'insufficient_balance'}}"
    )
    kind, summary = _classify_run_audit_error(exc)
    assert kind == "insufficient_balance", f"kind={kind!r}"
    assert "余额不足" in summary, f"summary={summary!r}"
    assert "联系管理员" in summary
    assert "重新运行" in summary


def test_classify_generic_error():
    """非余额类的通用异常应回退到 generic 分类 + 保留技术错误信息。"""
    from app.engine.orchestrator import _classify_run_audit_error

    exc = Exception("网络超时 timeout after 30s")
    kind, summary = _classify_run_audit_error(exc)
    assert kind == "generic"
    assert summary.startswith("核查失败：")
    assert "网络超时" in summary


def test_classify_case_insensitive_and_chinese_needles():
    """匹配应大小写不敏感；中文 needle（余额不足 / 账户欠费）也应命中。"""
    from app.engine.orchestrator import _classify_run_audit_error

    # 大写变种
    kind1, _ = _classify_run_audit_error(Exception("INSUFFICIENT BALANCE!!!"))
    assert kind1 == "insufficient_balance"

    # 中文变种
    kind2, s2 = _classify_run_audit_error(Exception("请求失败：账户欠费"))
    assert kind2 == "insufficient_balance"
    assert "余额不足" in s2

    # payment required 变种
    kind3, _ = _classify_run_audit_error(Exception("HTTP 402 Payment Required"))
    assert kind3 == "insufficient_balance"
```

- [ ] **Step 2: 跑测试确认 RED**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/backend
.venv/bin/python -m pytest tests/test_v22_llm_insufficient_balance.py -v
```

期望：3 条 case 都 FAIL，报错类似 `ImportError: cannot import name '_classify_run_audit_error' from 'app.engine.orchestrator'`。

- [ ] **Step 3: Commit RED**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/backend/tests/test_v22_llm_insufficient_balance.py
git commit -m "test(v2.2): _classify_run_audit_error unit tests (RED)"
```

---

## Task 2：实现 `_classify_run_audit_error`（Task 1 变 GREEN）

**Files:**
- Modify: `compliance-agent/backend/app/engine/orchestrator.py`（顶部导入段之后，`_ke_from_json` 之前加常量 + 函数）

**Interfaces:**
- Consumes: 无（纯 stdlib）
- Produces: `_classify_run_audit_error(exc: Exception) -> tuple[str, str]`
  - 输入任意异常，返回 (kind, summary)
  - kind ∈ {"insufficient_balance", "generic"}
  - summary 为已归一化好的中文字符串

- [ ] **Step 1: 读现有 orchestrator.py 顶部段落，找到最佳插入位置**

```bash
sed -n '1,35p' /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/backend/app/engine/orchestrator.py
```

期望看到 imports 到第 20 行，`_ke_from_json` 在 line 22。计划把新常量和函数插在 line 20 imports 之后、line 22 `_ke_from_json` 之前。

- [ ] **Step 2: 用 Edit 插入常量 + 函数**

找到 orchestrator.py 里第一个函数 `_ke_from_json` 的定义（`def _ke_from_json(raw: str) -> KeyElements:`），在它之前插入以下代码块。用 Edit 工具的 old_string / new_string 精确定位（old_string 包含 imports 尾行 + 空行 + `_ke_from_json` 起始行以保证唯一）：

```python
# v2.2：LLM 余额不足 / 402 类异常分类，输出用户友好的 task.summary
_INSUFFICIENT_BALANCE_NEEDLES = (
    "insufficient balance",
    "insufficient_balance",
    "error code: 402",
    "payment required",
    "余额不足",
    "账户欠费",
)


def _classify_run_audit_error(exc: Exception) -> tuple[str, str]:
    """把 run_audit 主循环抛出的异常分类成 (kind, user_facing_summary)。

    kind: "insufficient_balance" 或 "generic"，用于 log 分类。
    user_facing_summary: 显示在 AuditTask.summary 里的中文文案。
    """
    text = str(exc).lower()
    if any(needle in text for needle in _INSUFFICIENT_BALANCE_NEEDLES):
        return (
            "insufficient_balance",
            "LLM 服务余额不足，请联系管理员充值后重新运行任务。",
        )
    return ("generic", f"核查失败：{exc}")
```

具体 Edit 调用（把这段放在 `_ke_from_json` 上方）：

```
old_string:
    return ke


def _retrieve_legal_basis(indicator: Optional[Indicator]) -> str:
```

改成：

```
new_string:
    return ke


# v2.2：LLM 余额不足 / 402 类异常分类，输出用户友好的 task.summary
_INSUFFICIENT_BALANCE_NEEDLES = (
    "insufficient balance",
    "insufficient_balance",
    "error code: 402",
    "payment required",
    "余额不足",
    "账户欠费",
)


def _classify_run_audit_error(exc: Exception) -> tuple[str, str]:
    """把 run_audit 主循环抛出的异常分类成 (kind, user_facing_summary)。

    kind: "insufficient_balance" 或 "generic"，用于 log 分类。
    user_facing_summary: 显示在 AuditTask.summary 里的中文文案。
    """
    text = str(exc).lower()
    if any(needle in text for needle in _INSUFFICIENT_BALANCE_NEEDLES):
        return (
            "insufficient_balance",
            "LLM 服务余额不足，请联系管理员充值后重新运行任务。",
        )
    return ("generic", f"核查失败：{exc}")


def _retrieve_legal_basis(indicator: Optional[Indicator]) -> str:
```

- [ ] **Step 3: 跑单元测试确认 3/3 GREEN**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/backend
.venv/bin/python -m pytest tests/test_v22_llm_insufficient_balance.py -v
```

期望：3 条全过。

- [ ] **Step 4: Commit GREEN**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/backend/app/engine/orchestrator.py
git commit -m "feat(v2.2): _classify_run_audit_error helper for balance errors"
```

---

## Task 3：把新 helper 接入 `run_audit` 的 except 块

**Files:**
- Modify: `compliance-agent/backend/app/engine/orchestrator.py:283-286`

**Interfaces:**
- Consumes: Task 2 的 `_classify_run_audit_error`
- Produces: `run_audit` 的 except 块现在写 summary 走分类逻辑；旧行为（`f"核查失败：{exc}"`）依然是 fallback（Task 1 的 `test_classify_generic_error` 已覆盖）

- [ ] **Step 1: 读现有 except 块（`orchestrator.py:283-286`）**

```bash
sed -n '280,295p' /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/backend/app/engine/orchestrator.py
```

期望看到：

```python
    except Exception as exc:
        task.status = "failed"
        task.summary = f"核查失败：{exc}"
        task.progress_text = f"失败：{exc}"[:256]

    db.commit()
```

- [ ] **Step 2: 用 Edit 替换 except 块**

```
old_string:
    except Exception as exc:
        task.status = "failed"
        task.summary = f"核查失败：{exc}"
        task.progress_text = f"失败：{exc}"[:256]

    db.commit()
```

改成：

```
new_string:
    except Exception as exc:
        task.status = "failed"
        kind, summary = _classify_run_audit_error(exc)
        task.summary = summary
        task.progress_text = summary[:256]
        # v2.2：分类打 log 便于运维定位（余额不足 vs 其它错误）
        print(f"[run_audit] task {task.id} 失败 kind={kind} raw={exc}")

    db.commit()
```

- [ ] **Step 3: 跑单元测试（应仍 GREEN，本次改动只影响 except 内部）**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/backend
.venv/bin/python -m pytest tests/test_v22_llm_insufficient_balance.py -v
```

期望：3 条继续全过。

- [ ] **Step 4: 跑与 orchestrator 相关的现有回归测试**

```bash
.venv/bin/python -m pytest tests/test_audit_flow.py tests/test_v17_scoring_changes.py tests/test_v18_binding_fixes.py -q 2>&1 | tail -5
```

期望：这些 orchestrator 相关测试没有回归失败。

- [ ] **Step 5: Commit**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/backend/app/engine/orchestrator.py
git commit -m "feat(v2.2): route run_audit exceptions through classifier"
```

---

## Task 4：加集成测试（monkeypatch LLM 让 run_audit 走 402 分支）

**Files:**
- Modify: `compliance-agent/backend/tests/test_v22_llm_insufficient_balance.py`（追加 1 条集成 case）

**Interfaces:**
- Consumes: Task 2/3 完成后 `run_audit` 会在 LLM 抛 402 时把友好 summary 写进 task
- Produces: `test_run_audit_insufficient_balance_end_to_end` — 端到端验证

- [ ] **Step 1: 读现有测试文件确认末尾位置**

```bash
tail -5 /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/backend/tests/test_v22_llm_insufficient_balance.py
```

期望看到 `test_classify_case_insensitive_and_chinese_needles` 函数末尾。

- [ ] **Step 2: 追加集成测试**

在文件末尾追加：

```python


# ============================================================
# 集成：run_audit 在 LLM 抛 402 时应把友好 summary 写进 task
# ============================================================
def test_run_audit_insufficient_balance_end_to_end(monkeypatch):
    """
    monkeypatch app.engine.orchestrator.get_llm_client 让它返回一个总是抛
    "Error code: 402" 的假 client；再对 run_audit 传入一个含材料的任务，
    断言最终 task.status='failed' 且 task.summary 走友好文案。
    """
    import uuid

    from app.engine import orchestrator
    from app.models import (
        AuditTask, AuditUnit, Indicator, Material, SessionLocal,
    )

    class _FakeLLM402:
        """所有 API 都抛 402 的假 LLM client。"""
        def complete(self, *args, **kwargs):
            raise Exception(
                "Error code: 402 - {'error': {'message': 'Insufficient Balance', "
                "'code': 'insufficient_balance'}}"
            )
        def extract_json(self, *args, **kwargs):
            raise Exception(
                "Error code: 402 - {'error': {'message': 'Insufficient Balance', "
                "'code': 'insufficient_balance'}}"
            )

    monkeypatch.setattr(
        orchestrator, "get_llm_client",
        lambda db: _FakeLLM402(),
    )

    suffix = uuid.uuid4().hex[:6]
    db = SessionLocal()
    try:
        # 造最小可跑 orchestrator 的数据
        unit = AuditUnit(name=f"v22-{suffix}", code=f"V22{suffix}")
        db.add(unit); db.flush()

        # 选一条已存在的指标（种子里应有 I-13）
        ind = db.query(Indicator).filter_by(indicator_code="I-13").first()
        assert ind is not None, "种子指标 I-13 缺失，先跑 load_indicators_55"

        import json as _json
        task = AuditTask(
            unit_id=unit.id, name=f"v22-{suffix}",
            eval_year=2026, scope="selected",
            selected_indicator_ids=_json.dumps([ind.id]),
        )
        db.add(task); db.flush()

        # 一份含足够 parsed_text 的材料，触发 LLM 分支
        m = Material(
            task_id=task.id, indicator_id=ind.id,
            file_name=f"v22-{suffix}.txt",
            storage_path=f"/tmp/v22-{suffix}",
            file_type="txt", is_scanned=False,
            parsed_text="预算管理办法第一条 " * 30,  # 够长，避免被裁剪掉
        )
        db.add(m); db.commit()
        task_id = task.id
    finally:
        db.close()

    # 触发核查
    db = SessionLocal()
    try:
        task = db.get(AuditTask, task_id)
        orchestrator.run_audit(db, task)
    finally:
        db.close()

    # 验证
    db = SessionLocal()
    try:
        t = db.get(AuditTask, task_id)
        assert t.status == "failed", f"status={t.status!r}"
        assert "余额不足" in (t.summary or ""), f"summary={t.summary!r}"
        assert "联系管理员" in t.summary
    finally:
        db.close()
```

- [ ] **Step 3: 跑集成测试单独确认 GREEN**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/backend
.venv/bin/python -m pytest tests/test_v22_llm_insufficient_balance.py::test_run_audit_insufficient_balance_end_to_end -v 2>&1 | tail -10
```

期望：`1 passed`。

**注意**：如果集成测试 fail，最可能的原因是 orchestrator 在到达 LLM 之前的规则检查阶段就出错（比如缺 seed 指标）或者 `get_llm_client` 被别处 import 了但没被 monkeypatch 到（比如 `from app.llm.factory import get_llm_client` 直接引用）。这种情况看 orchestrator.py 里 `get_llm_client` 的 import 位置调整 monkeypatch 目标。

- [ ] **Step 4: 跑全量回归**

```bash
.venv/bin/python -m pytest tests/ -q --tb=line 2>&1 | tail -6
```

期望：`214 passed`（原 210 + v2.2 的 3 单元 + 1 集成）。

- [ ] **Step 5: Commit**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/backend/tests/test_v22_llm_insufficient_balance.py
git commit -m "test(v2.2): integration - run_audit 402 → friendly summary"
```

---

## Task 5：Push + 服务器部署 + 手动验证

**Files:** 无代码改动

**Interfaces:** 无

- [ ] **Step 1: Push 到 origin**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git push origin main 2>&1 | tail -3
```

期望：`main -> main` 推送成功。

- [ ] **Step 2: 打 v2.2 tar 包放 scratchpad**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent
tar -czf /private/tmp/claude-501/-Users-lizhishaoniange-Documents-ai-----/cd58db16-3297-4435-b223-ced9268d3256/scratchpad/v2.2.tar.gz \
  backend/app/engine/orchestrator.py \
  backend/tests/test_v22_llm_insufficient_balance.py
ls -la /private/tmp/claude-501/-Users-lizhishaoniange-Documents-ai-----/cd58db16-3297-4435-b223-ced9268d3256/scratchpad/v2.2.tar.gz
```

- [ ] **Step 3: 告诉用户走标准部署流程**

给用户以下命令（他 mac + Workbench 手动执行）：

**mac 本地：**
```bash
scp /private/tmp/claude-501/-Users-lizhishaoniange-Documents-ai-----/cd58db16-3297-4435-b223-ced9268d3256/scratchpad/v2.2.tar.gz \
    root@8.163.75.9:/opt/audit/compliance-agent/v2.2.tar.gz
```

**服务器 Workbench：**
```bash
cd /opt/audit/compliance-agent
tar -xzf v2.2.tar.gz

# orchestrator 主要由 worker 里的 run_audit_task 调用，也 cp 到 backend + enrich_worker 保持一致
for c in backend worker enrich_worker; do
  docker compose cp backend/app/engine/orchestrator.py $c:/app/app/engine/orchestrator.py
done
docker compose cp backend/tests/test_v22_llm_insufficient_balance.py backend:/app/tests/test_v22_llm_insufficient_balance.py

docker compose restart worker
sleep 5

# 容器内单测
docker compose exec -T backend python -m pytest tests/test_v22_llm_insufficient_balance.py -v 2>&1 | tail -10
# 期望：4 passed

# 收尾
rm v2.2.tar.gz
```

- [ ] **Step 4: 生产手动验证（Optional / 用户可选）**

用户可以在系统「后台管理 → 大语言模型」把 `api_key` 换成一个无效或已欠费的 key，然后跑一次 AI 核查，观察任务列表结论摘要列是否显示"LLM 服务余额不足，请联系管理员充值后重新运行任务。"。

**注意**：改完 api_key 别忘了换回真实 key，否则真实业务无法核查。

---

## Self-Review

**Spec coverage 核对**：

| Spec 章节 | 对应任务 |
|-----------|---------|
| 目标：summary 显示友好中文 | Task 3（改 except 块 + summary 归一化） |
| 动机：现有 except 塞裸 exception → 友好化 | Task 3 |
| 非目标：不含 Qwen-VL / 预检查 / banner / 新 status 值 / 改 LLM client | 未在任何 task 出现 ✓ |
| `_INSUFFICIENT_BALANCE_NEEDLES` 常量 + 6 个 needle | Task 2 |
| `_classify_run_audit_error(exc) -> (kind, summary)` 函数 | Task 2 |
| 大小写不敏感（`.lower()`） | Task 2 实现 + Task 1 的 `test_classify_case_insensitive_and_chinese_needles` case |
| except 块改动位置 `orchestrator.py:283-286` | Task 3 |
| 分类打 log | Task 3 的 print 行 |
| 单元测试 3 条 | Task 1 |
| 集成测试 1 条（monkeypatch） | Task 4 |
| 部署 cp 3 容器 + restart worker | Task 5 |
| 前端 / API / DB 不改 | 未在任何 task 出现 ✓ |

无遗漏。

**Placeholder scan**：无 TBD / TODO / "add error handling"。所有代码块都是可直接粘贴的完整实现。

**Type consistency**：
- `_classify_run_audit_error(exc: Exception) -> tuple[str, str]` — 声明与 Task 2 实现一致
- `kind` 取值 `"insufficient_balance"` / `"generic"` — Task 1 / Task 2 / Task 4 里一致
- summary 固定字面量 `"LLM 服务余额不足，请联系管理员充值后重新运行任务。"` — Task 2 / Task 4 一致
- monkeypatch target `app.engine.orchestrator.get_llm_client` — 与 orchestrator.py 顶部 `from app.llm import get_llm_client` 一致（module-level attribute）
