# LLM 余额不足友好提示（v2.2）

**日期**：2026-07-01
**范围**：仅 backend；无 DB 变更；无前端变更

## 目标

AI 核查任务因 DeepSeek 余额不足（HTTP 402）而失败时，`AuditTask.summary` 显示明确的中文提示"LLM 服务余额不足，请联系管理员充值后重新运行任务。"，而不是当前技术错误 `"核查失败：Error code: 402 - {...}"`，让审查员一眼理解原因并知道找谁处理。

## 动机

- 现有 `orchestrator.run_audit` 的 except 块（`orchestrator.py:283-286`）把裸 exception 塞进 summary，用户看不懂
- 402 场景是**可恢复**（充值后重跑），跟"程序崩溃"应该区分
- 前端任务列表第 6 列已展示 summary，不需要新加 UI；改后端 summary 内容即可让用户看到

## 非目标（YAGNI）

- 不处理 Qwen-VL 视觉模型 402（用户明确排除）
- 不做触发核查前的余额预检查
- 不在任务详情页加醒目 banner（现有 summary 已足够）
- 不新增 task.status 值（复用现有 "failed"）
- 不改 LLM client 抛特定 exception 类（openai SDK 版本升级会换 exception class 名字；字符串匹配更稳）
- 不改 admin audit log（现有 print 到 stdout 已能被 docker log 抓到；日志系统不改）

## 实现设计

### 新增函数

`backend/app/engine/orchestrator.py` 顶部（跟 `_materials_for_indicator` 等现有 helper 同级）加：

```python
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

    kind: "insufficient_balance" 或 "generic"，用于 log 分类和后续可能的差异化处理。
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

### 改动位置

`backend/app/engine/orchestrator.py:283-286` 的 except 块，从：

```python
except Exception as exc:
    task.status = "failed"
    task.summary = f"核查失败：{exc}"
    task.progress_text = f"失败：{exc}"[:256]
```

改为：

```python
except Exception as exc:
    task.status = "failed"
    kind, summary = _classify_run_audit_error(exc)
    task.summary = summary
    task.progress_text = summary[:256]
    print(f"[run_audit] task {task.id} 失败 kind={kind} raw={exc}")
```

### 判断规则详解

字符串匹配对 `str(exc).lower()` 做 `contains`。命中任一即认为是"余额不足"：

| Needle | 覆盖场景 |
|--------|---------|
| `insufficient balance` / `insufficient_balance` | DeepSeek 官方 error code |
| `error code: 402` | openai SDK 抛 `APIStatusError` 时的字符串表征 |
| `payment required` | HTTP 402 的标准 reason phrase，某些 SDK 会带 |
| `余额不足` / `账户欠费` | 某些国内 API 直译中文 message |

**为什么字符串匹配而不是 exception type**：openai SDK 版本升级会换 exception class（`APIError` → `APIStatusError` → 未来可能又变）；DeepSeek 后端返回 body 里的 `insufficient_balance` 字面量则跨版本稳定。

### 涉及文件

| 文件 | 变更类型 | 责任 |
|------|---------|------|
| `backend/app/engine/orchestrator.py` | Modify | 加 `_INSUFFICIENT_BALANCE_NEEDLES` 常量 + `_classify_run_audit_error` 函数 + 改 except 块 |
| `backend/tests/test_v22_llm_insufficient_balance.py` | Create | 3 条 case |

## 测试计划

### 单元测试

1. `test_classify_insufficient_balance_deepseek_style`：
   - 输入 `Exception("Error code: 402 - {'error':{'message':'Insufficient Balance','code':'insufficient_balance'}}")`
   - 期望 kind=`insufficient_balance`, summary 含 "余额不足"

2. `test_classify_generic_error`：
   - 输入 `Exception("网络超时 timeout")`
   - 期望 kind=`generic`, summary 含 "核查失败：网络超时"

3. `test_classify_case_insensitive`：
   - 输入 `Exception("INSUFFICIENT BALANCE!!!")`  （大写）
   - 期望 kind=`insufficient_balance`

### 集成测试

4. `test_run_audit_insufficient_balance_end_to_end`：
   - 建一个 unit + task + 一份 material（`Material.parsed_text` 非空，让 orchestrator 进入 LLM 分支）
   - Monkeypatch `app.llm.factory.get_llm_client` 返回 fake client，其 `complete` / `extract_json` 抛 `Exception("Error code: 402 - Insufficient Balance")`
   - 调 `run_audit(db, task)`
   - 断言 `task.status == "failed"` 且 `task.summary` 含 "余额不足"

## 部署

后端代码改动，前端不动。走标准 cp + restart：

```bash
scp compliance-agent/backend/app/engine/orchestrator.py root@8.163.75.9:/opt/audit/compliance-agent/backend/app/engine/orchestrator.py
scp compliance-agent/backend/tests/test_v22_llm_insufficient_balance.py root@8.163.75.9:/opt/audit/compliance-agent/backend/tests/test_v22_llm_insufficient_balance.py

# 服务器
cd /opt/audit/compliance-agent
# orchestrator 由 worker 里的 run_audit_task 调用；backend 也 import 但仅通过 celery 触发
for c in backend worker enrich_worker; do
  docker compose cp backend/app/engine/orchestrator.py $c:/app/app/engine/orchestrator.py
done
docker compose cp backend/tests/test_v22_llm_insufficient_balance.py backend:/app/tests/test_v22_llm_insufficient_balance.py

docker compose restart worker
# backend 和 enrich_worker 不需要 restart（不直接调用 run_audit）；但为了三容器代码一致可选 restart

# 验证
docker compose exec backend python -m pytest tests/test_v22_llm_insufficient_balance.py -v
```

## 回滚

如果 needle 匹配过宽误判（例如某种"generic 401"错误里也含 "insufficient" 但不是 402）：

- 缩减 `_INSUFFICIENT_BALANCE_NEEDLES` 常量里的宽泛项
- 或整个 revert 该 commit，回到 `task.summary = f"核查失败：{exc}"`

## 与其它模块的关系

- `run_audit_task` (celery task, `jobs.py:11`) 只是把 db 传给 `run_audit`，本改动不影响
- 前端任务列表已经显示 `AuditTask.summary`（`app.js` renderTasksBody 里 `${esc(t.summary || "—")}`）——**无需前端改动**
- `AuditTaskOut` schema 也已经 return `summary`——**无需 API 改动**
