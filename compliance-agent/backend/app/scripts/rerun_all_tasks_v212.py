"""v2.12：全量任务重跑 + 自动定稿。

支持：
- --dry-run: 列出候选任务数 + 当前累计费用，不 enqueue
- --pilot N: 只跑前 N 个（默认 10），完成后打印统计校准 avg cost
- --run --budget 500: 全量跑，累计费用达 ¥500 停止

断点续跑：checkpoint jsonl 每完成一任务写一行，重启后跳过已完成 task_id
Auto-finalize：AI 完成后直接 SQL 改 status=finalized（跳过人工复核）
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.auth import log_action
from app.llm.deepseek import sum_usage_cost
from app.models import (
    AuditTask,
    Finding,
    Material,
    SessionLocal,
    Worksheet,
    WorksheetRow,
    get_db,
)

DEFAULT_CHECKPOINT = "/app/data/v2.12_rerun_checkpoint.jsonl"


def _load_checkpoint(path: str) -> set[int]:
    """读 checkpoint jsonl，返回已完成 task_id 集合。"""
    if not os.path.exists(path):
        return set()
    ids: set[int] = set()
    with open(path) as f:
        for line in f:
            try:
                e = json.loads(line)
                ids.add(int(e["task_id"]))
            except Exception:
                continue
    return ids


def _append_checkpoint(path: str, task_id: int, status: str) -> None:
    """追加一行 checkpoint（task_id + 最终状态 + 时间戳）。"""
    entry = {
        "task_id": task_id,
        "status": status,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except OSError:
        pass
    with open(path, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _reset_task_for_rerun(db: Session, task_id: int) -> None:
    """v2.12: 重跑前清空 findings + worksheet + 状态回 pending。

    幂等：重复调用只是把状态从 pending 重置为 pending，无副作用。
    """
    task = db.get(AuditTask, task_id)
    if not task:
        return
    # 删 findings（cascade 不一定配好，显式删）
    db.query(Finding).filter(Finding.task_id == task_id).delete()
    # 删 worksheet + rows
    ws = db.query(Worksheet).filter(Worksheet.task_id == task_id).first()
    if ws:
        db.query(WorksheetRow).filter(WorksheetRow.worksheet_id == ws.id).delete()
        db.delete(ws)
    # 重置任务字段
    task.status = "pending"
    task.progress_current = 0
    task.progress_total = 0
    task.progress_text = ""
    task.summary = ""
    task.stats = ""
    task.completed_at = None
    db.commit()


def _auto_finalize(db: Session, task: AuditTask) -> None:
    """v2.12: 跳过人工复核，AI 完成后直接设 finalized。

    - task.status = "finalized"
    - worksheet.status = "finalized"
    - completed_at 更新
    - 无 audit_log 用户（脚本运行不带 user 上下文），仅打印
    """
    ws = db.query(Worksheet).filter(Worksheet.task_id == task.id).first()
    if ws:
        ws.status = "finalized"
    task.status = "finalized"
    task.completed_at = datetime.now(timezone.utc)
    db.commit()


def _discover_candidate_tasks(db: Session, done_ids: set[int]) -> list[int]:
    """列出所有候选 task_id：有材料 + 不在 done_ids + status != running。

    避开 running 是防误踢正在跑的任务（避免与其它用户竞争）。
    按 id asc 排序保证跨批次的确定性。
    """
    q = (
        db.query(AuditTask.id)
        .join(Material, Material.task_id == AuditTask.id)
        .filter(AuditTask.status != "running")
    )
    if done_ids:
        q = q.filter(AuditTask.id.notin_(done_ids))
    rows = q.distinct().order_by(AuditTask.id.asc()).all()
    return [r[0] for r in rows]


def _process_batches(db: Session, task_ids: list[int], args) -> None:
    """按 batch_size 分批 enqueue + 轮询完成 + auto-finalize。"""
    from app.tasks import run_audit_task

    tp_start, tc_start, cost_start = sum_usage_cost()
    total_processed = 0

    for i in range(0, len(task_ids), args.batch_size):
        # 每批前查累计（仅 --run 模式检查预算）
        _, _, cost_now = sum_usage_cost()
        delta = cost_now - cost_start
        if args.run and delta >= args.budget:
            print(f"⚠️ 达到预算 ¥{args.budget}（本次累计 ¥{delta:.2f}），停止 enqueue 新任务")
            break

        batch = task_ids[i:i + args.batch_size]
        print(f"批次 {i // args.batch_size + 1}：enqueue {len(batch)} 个任务")
        for tid in batch:
            _reset_task_for_rerun(db, tid)
            run_audit_task.delay(tid)

        # 等这批全部跑完
        pending = set(batch)
        while pending:
            time.sleep(args.poll_interval)
            db.expire_all()
            still = set()
            for tid in pending:
                t = db.get(AuditTask, tid)
                if not t:
                    _append_checkpoint(args.checkpoint, tid, "missing")
                    total_processed += 1
                    continue
                if t.status == "ai_done":
                    _auto_finalize(db, t)
                    _append_checkpoint(args.checkpoint, tid, "finalized")
                    total_processed += 1
                elif t.status in ("running", "pending"):
                    still.add(tid)
                else:
                    # failed / archived / 其它异常终态
                    _append_checkpoint(args.checkpoint, tid, f"skipped:{t.status}")
                    total_processed += 1
            pending = still

        _, _, cost_now = sum_usage_cost()
        print(f"进度 {total_processed}/{len(task_ids)}，本次累计 ¥{cost_now - cost_start:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="v2.12 全量任务重跑 + 自动定稿"
    )
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--dry-run", action="store_true", help="只列任务不 enqueue")
    grp.add_argument("--pilot", type=int, metavar="N",
                     help="只跑前 N 个（默认 10）")
    grp.add_argument("--run", action="store_true", help="全量跑")

    parser.add_argument("--budget", type=float, default=500.0,
                        help="预算上限（元），仅 --run 生效")
    parser.add_argument("--checkpoint", default=DEFAULT_CHECKPOINT)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--poll-interval", type=int, default=5,
                        help="轮询 task.status 的间隔秒数")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        done_ids = _load_checkpoint(args.checkpoint)
        candidates = _discover_candidate_tasks(db, done_ids)
        print(f"候选任务: {len(candidates)}（已完成 checkpoint: {len(done_ids)}）")

        tp, tc, cost = sum_usage_cost()
        print(f"当前累计 LLM 费用: ¥{cost:.2f}"
              f" (prompt {tp:,}, completion {tc:,})")

        if args.dry_run:
            print("--dry-run: 不 enqueue，退出。")
            return

        if args.pilot is not None:
            n = args.pilot if args.pilot > 0 else 10
            candidates = candidates[:n]
            print(f"pilot 模式：只跑前 {len(candidates)} 个")

        _process_batches(db, candidates, args)

        # summary
        _, _, cost_end = sum_usage_cost()
        print()
        print(f"完成。本次累计 LLM 费用: ¥{cost_end - cost:.2f}")
        print(f"总累计: ¥{cost_end:.2f}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
