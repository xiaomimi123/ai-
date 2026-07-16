"""v2.12 DeepSeek usage 埋点测试。"""
import json
import tempfile


def test_sum_usage_cost_missing_file_returns_zero():
    """文件不存在 → (0, 0, 0.0)。"""
    from app.llm.deepseek import sum_usage_cost
    tp, tc, cost = sum_usage_cost("/tmp/nonexistent_v2.12_usage.jsonl")
    assert tp == 0
    assert tc == 0
    assert cost == 0.0


def test_log_and_sum_roundtrip(tmp_path, monkeypatch):
    """写 3 条不同模型的 usage，sum 返回正确的 token 和 cost。"""
    import app.llm.deepseek as ds
    log_file = tmp_path / "usage.jsonl"
    monkeypatch.setattr(ds, "_USAGE_LOG_PATH", str(log_file))

    class FakeUsage:
        def __init__(self, p, c):
            self.prompt_tokens = p
            self.completion_tokens = c

    ds._log_usage("deepseek-v4-flash", FakeUsage(1_000_000, 500_000))
    ds._log_usage("deepseek-v4-flash", FakeUsage(2_000_000, 1_000_000))
    ds._log_usage("deepseek-v4-pro", FakeUsage(100_000, 50_000))

    tp, tc, cost = ds.sum_usage_cost(str(log_file))
    # v4-flash: (1+2)M in × 0.10 + (0.5+1)M out × 0.50 = 0.30 + 0.75 = 1.05
    # v4-pro:   0.1M in × 0.50 + 0.05M out × 2.00     = 0.05 + 0.10 = 0.15
    # total: 1.20
    assert tp == 3_100_000
    assert tc == 1_550_000
    assert abs(cost - 1.20) < 0.001


def test_log_usage_with_none_does_not_crash(tmp_path, monkeypatch):
    """usage=None 不写文件也不抛（openai SDK 有时返回 None）。"""
    import app.llm.deepseek as ds
    log_file = tmp_path / "usage.jsonl"
    monkeypatch.setattr(ds, "_USAGE_LOG_PATH", str(log_file))

    ds._log_usage("deepseek-v4-flash", None)  # 不应抛
    assert not log_file.exists()  # 也不应创建文件
