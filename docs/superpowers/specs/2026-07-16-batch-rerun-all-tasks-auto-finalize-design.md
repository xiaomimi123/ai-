# 全量任务重跑 + 自动定稿（v2.12）

**日期**：2026-07-16
**范围**：backend LLM usage 埋点 + 批量重跑脚本 + 自动定稿逻辑
**动机**：用户需要把系统里所有含材料的任务重新跑一遍 AI 核查、生成底稿、直接定稿（跳过人工复核）。用系统当前配的大模型（不切换），成本上限 ¥500。

## 目标

1. 遍历所有 **含材料** 的任务（含已 finalized 重跑）→ 重新跑 AI 核查 → 生成 findings + worksheet → 直接推到 `finalized`
2. 累计 LLM 费用达到 ¥500 停止（在飞的等它跑完）
3. 断点可续跑：checkpoint 记录已完成 task_id，中途 Ctrl+C / 服务器重启后能从上次断点继续
4. 保留 worker 现有并发（2），不改 docker-compose

## 非目标（YAGNI）

- 不加人工复核（用户明确同意跳过 → 直接 finalize）
- 不改 LLM 模型或参数（用系统当前"后台管理→大语言模型"里配的）
- 不 pre-count token 做精确预算（后估：实际调用后累加 usage）
- 不做前端 UI 展示进度（脚本 stdout + tail -f checkpoint 就够）
- 不做多任务并发排他锁（worker=2 顺序消费，脚本 enqueue 完等结果）
- 不做失败任务自动重试（失败 → 记录跳过 → 用户看日志决定）

## 设计

### 1. LLM Usage 埋点（`app/llm/deepseek.py`）

在 `complete()` 和 `extract_json()` 里，`resp = client.chat.completions.create(...)` 之后，把 `resp.usage` 追加到 jsonl 文件。

**新增常量**（DeepSeek 官方价格，2026-01）：
```python
# 单价：元 / 1M tokens（deepseek-v4-flash 缓存未命中；命中价更低本次不区分）
_PRICE_PER_M_INPUT = {
    "deepseek-v4-flash":  0.10,
    "deepseek-v4-pro":    0.50,
    "deepseek-chat":      0.10,   # 兼容名
    "deepseek-reasoner":  0.50,
}
_PRICE_PER_M_OUTPUT = {
    "deepseek-v4-flash":  0.50,
    "deepseek-v4-pro":    2.00,
    "deepseek-chat":      0.50,
    "deepseek-reasoner":  2.00,
}
_USAGE_LOG_PATH = "/app/data/llm_usage.jsonl"
```

**新增 helper**：
```python
def _log_usage(model: str, usage) -> None:
    """把一次调用的 usage 追加到 jsonl。usage 为 openai SDK 的 CompletionUsage 对象。"""
    if usage is None:
        return
    try:
        pt = int(getattr(usage, "prompt_tokens", 0) or 0)
        ct = int(getattr(usage, "completion_tokens", 0) or 0)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "prompt_tokens": pt,
            "completion_tokens": ct,
        }
        # 目录不存在则退化到 /tmp
        path = _USAGE_LOG_PATH
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except OSError:
            path = "/tmp/llm_usage.jsonl"
        with open(path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 埋点不能影响主流程
```

**在两个方法末尾插入**：
```python
resp = self._client.chat.completions.create(**kwargs)
_log_usage(self._model, resp.usage)  # v2.12: 埋点
return resp.choices[0].message.content or ""
```

**Sum helper**（供批量脚本 import）：
```python
def sum_usage_cost(path: str = _USAGE_LOG_PATH) -> tuple[int, int, float]:
    """扫描 jsonl，返回 (total_prompt_tokens, total_completion_tokens, cost_yuan)。"""
    if not os.path.exists(path):
        return (0, 0, 0.0)
    tp = tc = 0
    cost = 0.0
    with open(path) as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            model = e.get("model", "")
            pt = int(e.get("prompt_tokens", 0))
            ct = int(e.get("completion_tokens", 0))
            in_rate = _PRICE_PER_M_INPUT.get(model, 0.5)  # 未知模型按贵档兜底
            out_rate = _PRICE_PER_M_OUTPUT.get(model, 2.0)
            tp += pt
            tc += ct
            cost += (pt / 1_000_000 * in_rate) + (ct / 1_000_000 * out_rate)
    return (tp, tc, cost)
```

### 2. 批量脚本 `app/scripts/rerun_all_tasks_v212.py`

**用法**：
```
python -m app.scripts.rerun_all_tasks_v212 --dry-run
python -m app.scripts.rerun_all_tasks_v212 --pilot 10
python -m app.scripts.rerun_all_tasks_v212 --run --budget 500
```

**参数**：
- `--dry-run`：只列出会处理的任务 + 累计估费（如 checkpoint 已有历史数据）；不 enqueue
- `--pilot N`：只跑 N 个任务（默认 10），完成后打印统计（帮助校准 avg cost/task）
- `--run`：全量跑
- `--budget <元>`：预算上限（默认 500）；仅 `--run` 有意义
- `--checkpoint <path>`：断点文件路径（默认 `/app/data/v2.12_rerun_checkpoint.jsonl`）
- `--batch-size <N>`：每批 enqueue 数（默认 20）
- `--poll-interval <秒>`：轮询任务状态间隔（默认 5）

**主流程**：

```python
def main(args):
    db = SessionLocal()
    # 1. 收集候选任务：所有 status != running（避免误踢正在跑的）+ 有材料
    done_ids = _load_checkpoint(args.checkpoint)
    all_tasks = (
        db.query(AuditTask.id)
        .join(Material, Material.task_id == AuditTask.id)
        .filter(AuditTask.status != "running")
        .filter(AuditTask.id.notin_(done_ids) if done_ids else True)
        .distinct()
        .order_by(AuditTask.id.asc())
        .all()
    )
    task_ids = [t.id for t in all_tasks]

    print(f"待处理: {len(task_ids)} 个任务（已完成 checkpoint: {len(done_ids)}）")

    if args.dry_run:
        tp, tc, cost = sum_usage_cost()
        print(f"当前累计 LLM 费用: ¥{cost:.2f} (prompt {tp}, completion {tc})")
        return

    if args.pilot is not None:
        task_ids = task_ids[:args.pilot]
        print(f"pilot 模式：只跑前 {len(task_ids)} 个")

    # 2. 分批处理
    _process_batches(db, task_ids, args)


def _process_batches(db, task_ids, args):
    from app.tasks import run_audit_task
    from app.llm.deepseek import sum_usage_cost

    _, _, cost_start = sum_usage_cost()
    total_processed = 0
    for i in range(0, len(task_ids), args.batch_size):
        # 预算检查（每批前一次）
        _, _, cost_now = sum_usage_cost()
        if args.run and (cost_now - cost_start) >= args.budget:
            print(f"⚠️ 达到预算 ¥{args.budget}（累计 ¥{cost_now:.2f}），停止 enqueue")
            break

        batch = task_ids[i:i + args.batch_size]
        # enqueue 一批
        for tid in batch:
            _reset_task_for_rerun(db, tid)  # 清 findings + 底稿 + status=pending
            run_audit_task.delay(tid)

        # 等这批全部跑完（status 变 ai_done 或异常终态）
        pending = set(batch)
        while pending:
            time.sleep(args.poll_interval)
            still_pending = set()
            for tid in pending:
                t = db.query(AuditTask).get(tid)
                if not t:
                    continue
                if t.status == "ai_done":
                    # auto-finalize
                    _auto_finalize(db, t)
                    _append_checkpoint(args.checkpoint, tid, "finalized")
                    total_processed += 1
                elif t.status in ("running", "pending"):
                    still_pending.add(tid)
                else:
                    # 异常终态（可能 LLM 报错或 skipped）
                    _append_checkpoint(args.checkpoint, tid, f"skipped:{t.status}")
                    total_processed += 1
            pending = still_pending
            db.expire_all()  # 强制下次 query 刷新

        # 打印进度
        _, _, cost_now = sum_usage_cost()
        print(f"已处理 {total_processed}/{len(task_ids)}，累计 ¥{cost_now - cost_start:.2f}")


def _reset_task_for_rerun(db, task_id: int):
    """v2.12: 重跑前清空 findings + worksheet + 状态回 pending。"""
    from app.models import Finding, Worksheet, WorksheetRow
    task = db.get(AuditTask, task_id)
    db.query(Finding).filter(Finding.task_id == task_id).delete()
    ws = db.query(Worksheet).filter(Worksheet.task_id == task_id).first()
    if ws:
        db.query(WorksheetRow).filter(WorksheetRow.worksheet_id == ws.id).delete()
        db.delete(ws)
    task.status = "pending"
    task.progress_current = 0
    task.progress_total = 0
    task.progress_text = ""
    task.summary = ""
    task.stats = ""
    task.completed_at = None
    db.commit()


def _auto_finalize(db, task):
    """v2.12: 跳过人工复核，AI 完成后直接设 finalized（复用 finalize_worksheet 语义）。"""
    from app.models import Worksheet
    ws = db.query(Worksheet).filter(Worksheet.task_id == task.id).first()
    if ws:
        ws.status = "finalized"
    task.status = "finalized"
    task.completed_at = datetime.now(timezone.utc)
    db.commit()


def _load_checkpoint(path: str) -> set[int]:
    """读 checkpoint jsonl，返回已完成 task_id 集合。"""
    if not os.path.exists(path):
        return set()
    ids = set()
    with open(path) as f:
        for line in f:
            try:
                e = json.loads(line)
                ids.add(int(e["task_id"]))
            except Exception:
                continue
    return ids


def _append_checkpoint(path: str, task_id: int, status: str):
    entry = {
        "task_id": task_id,
        "status": status,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    with open(path, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
```

### 3. 测试 `tests/test_rerun_all_tasks_v212.py`

3-4 条 pytest：
- `test_load_checkpoint_returns_done_ids`：写一个 checkpoint jsonl，_load_checkpoint 能读到全部 task_id
- `test_reset_task_for_rerun_clears_findings_and_worksheet`：seed 一个含 finding + worksheet 的任务，跑 _reset_task_for_rerun，验证 findings 表空 + worksheet 表空 + status=pending
- `test_auto_finalize_sets_status`：seed 一个 ai_done 任务 + worksheet，跑 _auto_finalize，验证 task.status == "finalized" + ws.status == "finalized"
- `test_sum_usage_cost_basic`：写 3 条 usage 到临时文件，验证 sum_usage_cost 返回值

### 4. 部署顺序

```
1. 本地 code + tests 通过
2. push origin/main
3. Workbench 上传到 ECS：
   - backend/app/llm/deepseek.py（改）
   - backend/app/scripts/rerun_all_tasks_v212.py（新）
4. ssh 服务器：
   cd /opt/audit/compliance-agent
   docker compose cp backend/app/llm/deepseek.py backend:/app/app/llm/deepseek.py
   docker compose cp backend/app/llm/deepseek.py worker:/app/app/llm/deepseek.py
   docker compose cp backend/app/llm/deepseek.py enrich_worker:/app/app/llm/deepseek.py
   docker compose cp backend/app/scripts/rerun_all_tasks_v212.py backend:/app/app/scripts/rerun_all_tasks_v212.py
   docker compose restart backend worker enrich_worker
5. 备份 pg_dump（重要！）：
   docker compose exec -T postgres pg_dump -U compliance -d compliance \
       -t audit_tasks -t findings -t worksheets -t worksheet_rows \
       > /opt/audit/backup_v2.12_before_$(date +%Y%m%d_%H%M%S).sql
   ls -lh /opt/audit/backup_v2.12_before_*.sql | tail -1
6. --dry-run 看总任务数：
   docker compose exec -T backend python -m app.scripts.rerun_all_tasks_v212 --dry-run
7. --pilot 10 跑 10 个校准：
   docker compose exec -T backend python -m app.scripts.rerun_all_tasks_v212 --pilot 10
   （约 30-50 分钟，取决于任务大小）
8. 用户看 pilot 结果 → 确认 avg cost/task → 决定 budget 是否够
9. --run --budget 500 全量跑（服务器上 nohup 或 tmux 后台）：
   nohup docker compose exec -T backend \
       python -m app.scripts.rerun_all_tasks_v212 --run --budget 500 \
       > /opt/audit/v2.12_rerun.log 2>&1 &
10. 中途查看：
    tail -f /opt/audit/v2.12_rerun.log
    wc -l /app/data/v2.12_rerun_checkpoint.jsonl（本机在容器内看）
    或 docker compose exec backend cat /app/data/v2.12_rerun_checkpoint.jsonl | wc -l
```

### 5. 涉及文件

| 文件 | 变更 |
|---|---|
| `backend/app/llm/deepseek.py` | 加价格常量 + `_log_usage()` + `sum_usage_cost()` + 两个方法末尾调用 |
| `backend/app/scripts/rerun_all_tasks_v212.py` | 新建，主脚本 |
| `backend/tests/test_rerun_all_tasks_v212.py` | 新建，4 条 pytest |
| `README.md` | v2.12 更新日志 |

## 手工验证

- [ ] `--dry-run` 输出总任务数合理（预期 ~4000+，跟 v2.8 涉及任务数吻合）
- [ ] `--pilot 10` 跑完 checkpoint 里有 10 条 status=finalized
- [ ] pilot 后 `/app/data/llm_usage.jsonl` 有 usage 记录，`sum_usage_cost()` 返回值 > 0
- [ ] 前端进任意"已定稿"pilot 任务，findings + 底稿正常显示
- [ ] 后台 audit_tasks 表 `status='finalized'` 数增加了 pilot 数
- [ ] `--run --budget 0.5` 测试预算触发（跑一批就停，累计 < 1 元）
- [ ] Ctrl+C 中断后再跑 `--run --budget 500` → 跳过 checkpoint 里已有的
- [ ] 前端"工作台批量导出已定稿工作底稿"card 里各市的任务数增加

## 风险 & 缓解

| 风险 | 概率 | 缓解 |
|---|---|---|
| 4000+ finalized 任务被覆盖后 findings 变差（LLM 输出比之前差）| 中 | pg_dump 前备份；任何时候可 psql -f 完整回滚 |
| 预算爆超 | 中 | 每批前查累计，超即停 enqueue（在飞的可能超一点点，最多 20 任务份） |
| worker 崩溃 | 低 | Celery 自动重启；checkpoint 里没记的下次重跑会重复（幂等：先删旧 findings 再跑）|
| deepseek API 429 / 超限 | 低 | worker=2 并发温和；LLM client 已有重试机制（现有代码）|
| `llm_usage.jsonl` 增长过大 | 低 | 一次 4000 任务 × 200 调用 ≈ 80万行，每行 ~200 字节 → ~160MB，可接受 |
| Auto-finalize 破坏 audit_log 语义（没记录人工操作） | 低 | 在 log_action 里传 detail="v2.12 batch auto-finalize (no human review)" 明确标记 |
| Pilot 校准出的 avg cost 与全量偏差大 | 中 | pilot 完打印 min/max/median 让用户判断分布 |

## 回滚

**紧急停止**：`kill <pid>` 或 `docker compose exec backend pkill -f rerun_all_tasks_v212`。checkpoint 保留，下次可续。

**数据回滚**：`psql -U compliance -d compliance -f /opt/audit/backup_v2.12_before_<ts>.sql`（会覆盖 audit_tasks + findings + worksheets + worksheet_rows）。material 表不动。

## 备注

- 使用系统当前配置的模型（`app_setting.llm_model`）；如果是 deepseek-v4-flash 单价便宜，估费 ~¥300-800；如果是 deepseek-v4-pro 会 5-10 倍。用户已选 v4-flash（v2.4 起）
- Auto-finalize 后审计业务上"已定稿"不再代表"人工看过"，需要业务确认可接受
