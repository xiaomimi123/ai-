# Vision api_key 不回显明文（v2.5）

**日期**：2026-07-02
**范围**：backend `settings_routes.py` + `settings_service.py` + frontend `app.js`
**动机**：安全治理，对齐 LLM 端已有的 `has_api_key: bool` 模式，消除本次会话中已发生 3 次的 dashscope key 泄露路径

## 根因

看当前实现，**明文泄露不只是 GET 一处** —— 是 4 处协同设计错误：

1. **`GET /api/settings/vision`**（`settings_routes.py:93-97`）返 `{enabled, api_key: "sk-xxx", model}` 含明文
2. **`POST /api/settings/vision`**（`settings_routes.py:100-108`）的 `VisionConfigIn.api_key: str` 是**required 字段**
3. **`save_vision_config`**（`settings_service.py:92-106`）**无条件 upsert 全 3 字段**（api_key 必传）
4. **前端 vision 保存表单**（`app.js:3583-3590`）**为了"不改 key 只改开关或模型"，必须先 GET 拿明文再回填一起 POST** — 这直接把明文塞进 JS 变量、Network 面板、curl 响应

只改 GET 不够 —— POST 端强制要求 api_key 会让前端保存流程崩溃或必须持续持有明文。**必须 4 处联动改**才能彻底消除明文回传链路。

对比参考：LLM 端已经做对了（`settings_routes.py:16-23` 的 `_to_response` + `settings_service.update_llm_config` 用 `Optional[str] = None`），本次改动就是把 vision 端对齐。

## 目标

改完后：

- `GET /api/settings/vision` 响应体**不含 `api_key` 字段**，改为 `has_api_key: bool`
- `POST /api/settings/vision` 的 `api_key` 是**可选字段**（`Optional[str] = None`），前端不传或传 null 时保留 DB 中的旧值
- 前端保存 vision 表单时**不再 GET 明文回填**，若输入框留空则 POST 时省略 `api_key` 字段
- `POST /vision/test` 保留现有行为（request 里 api_key 空则从 DB 拿明文调 dashscope）— 只在服务端内部使用，不外泄
- 服务端内部 `settings_service.get_vision_config(db)` 仍返回明文 api_key（供 `ocr_qwen_vl.get_vision_client` 调 dashscope），只是 HTTP 层不再暴露

## 非目标（YAGNI）

- 不加密存储 api_key（DB 里仍明文，改动大且现有 LLM 端也是明文存的 —— 一致性优先，加密留给未来做统一的 secret vault）
- 不做审计日志（保存时的 log_action 已经写"vision 配置已更新"）
- 不改 LLM 端（已经对了）
- 不改 dashscope key 值本身（那是用户运维，跟代码无关）

## 实现设计

### 改动 1：`settings_service.py` — `save_vision_config` 支持 partial update

```python
# 原有：
def save_vision_config(db: Session, enabled: bool,
                       api_key: str, model: str) -> None:
    pairs = [
        ("vision_enabled", "true" if enabled else "false"),
        ("vision_api_key", api_key),
        ("vision_model", model or "qwen-vl-plus"),
    ]
    for key, val in pairs:
        ...  # 无条件 upsert 全 3 个
    db.commit()

# 改为（对齐 update_llm_config 的 Optional 模式）：
from typing import Optional as _Optional

def save_vision_config(db: Session,
                       enabled: _Optional[bool] = None,
                       api_key: _Optional[str] = None,
                       model: _Optional[str] = None) -> None:
    """Partial update：字段为 None 时不改，非 None 时 upsert。
    api_key="" (空字符串) 视为"清空"（跟 LLM 端一致）。
    """
    pairs = []
    if enabled is not None:
        pairs.append(("vision_enabled", "true" if enabled else "false"))
    if api_key is not None:
        pairs.append(("vision_api_key", api_key.strip()))
    if model is not None:
        pairs.append(("vision_model", model.strip() or "qwen-vl-plus"))
    for key, val in pairs:
        row = db.query(AppSetting).filter_by(key=key).first()
        if row:
            row.value = val
        else:
            db.add(AppSetting(key=key, value=val))
    db.commit()
```

### 改动 2：`settings_routes.py` — GET 只返 has_api_key，POST 用 Optional

```python
# GET /vision 改成走一个 to_response 函数（对齐 LLM 的 _to_response）
def _vision_to_response(cfg: dict) -> dict:
    return {
        "enabled": bool(cfg.get("enabled")),
        "model": cfg.get("model", "qwen-vl-plus"),
        "has_api_key": bool(cfg.get("api_key", "")),
    }


@settings_router.get("/vision", response_model=dict)
def get_vision_settings(db: Session = Depends(get_db),
                        _: User = Depends(require_admin)):
    """读取 Qwen-VL OCR 配置（管理员）。api_key 不回显明文，
    改回 has_api_key: bool（对齐 /api/settings/llm 端）。"""
    return _vision_to_response(settings_service.get_vision_config(db))


# VisionConfigIn 里 api_key 改成 Optional
from typing import Optional as _Optional

class VisionConfigIn(_BaseModel):
    enabled: _Optional[bool] = None
    api_key: _Optional[str] = None    # None / 缺失 → 不动 DB 里的 key
    model: _Optional[str] = None


@settings_router.post("/vision", response_model=dict)
def save_vision_settings(req: VisionConfigIn, ...):
    settings_service.save_vision_config(
        db, enabled=req.enabled, api_key=req.api_key, model=req.model,
    )
    return {"ok": True}
```

### 改动 3：`app.js` — 保存表单不再 GET 明文回填

```javascript
// 原有（3578-3595 段）：
document.getElementById("vision-form").addEventListener("submit", async ev => {
  ...
  const newKey = document.getElementById("vision-api-key").value.trim();
  let existingKey = "";
  if (!newKey) {
    try {
      const cur = await api("/settings/vision");
      existingKey = cur.api_key || "";     // ← 明文回填源
    } catch {}
  }
  const payload = {
    enabled: ...,
    api_key: newKey || existingKey,
    model: ...,
  };
  ...

// 改为：
document.getElementById("vision-form").addEventListener("submit", async ev => {
  ...
  const newKey = document.getElementById("vision-api-key").value.trim();
  const payload = {
    enabled: document.getElementById("vision-enabled").checked,
    model: document.getElementById("vision-model").value,
  };
  // 只有用户填了新 key 才发送 api_key 字段（backend Optional，缺则保留旧值）
  if (newKey) {
    payload.api_key = newKey;
  }
  ...
});
```

同时 `loadVisionConfig` 里的 placeholder 逻辑要基于新字段 `has_api_key`：

```javascript
// 原有 3568-3570：
document.getElementById("vision-api-key").placeholder = cfg.api_key
  ? "✓ 已配置 · 留空表示不修改"
  : "尚未配置 · 填入 dashscope sk-...";

// 改为：
document.getElementById("vision-api-key").placeholder = cfg.has_api_key
  ? "✓ 已配置 · 留空表示不修改"
  : "尚未配置 · 填入 dashscope sk-...";
```

### 改动 4：`?v=2.4` → `?v=2.5` 刷缓存

`index.html` 3 处静态资源 query。

### 改动 5：静态资源版本号常量 `PROMPT_VERSION`（无 — 不涉及）

无。

## 涉及文件

| 文件 | 变更 | 责任 |
|------|-----|------|
| `backend/app/services/settings_service.py` | Modify | `save_vision_config` 改为 partial update |
| `backend/app/api/settings_routes.py` | Modify | GET 用 `_vision_to_response`；POST 用 `Optional[bool/str]` |
| `backend/tests/test_v25_vision_no_echo.py` | Create | 4 条 pytest：GET 无 api_key、POST 保留旧值、POST 显式改 key、内部 service 仍返明文（供 ocr 用） |
| `frontend/app.js` | Modify | `loadVisionConfig` 用 `has_api_key`；save 表单空 key 时省略字段 |
| `frontend/index.html` | Modify | 3 处 `?v=2.4` → `?v=2.5` |

## 测试计划

### Backend pytest 4 条

1. **`test_get_vision_returns_no_api_key_field`**：GET 响应必须**不含** `api_key` 字段，含 `has_api_key: bool`
2. **`test_get_vision_has_api_key_true_when_configured`**：DB 有 key 时 `has_api_key=true`；无 key 时 `false`
3. **`test_post_vision_without_api_key_preserves_existing`**：先保存一个 key，然后 POST 只带 `{enabled: false}`（不带 api_key），DB 里原 key 应保留
4. **`test_post_vision_with_api_key_updates`**：POST 显式带 `{api_key: "sk-new"}`，DB 里应更新为新值
5. **`test_service_get_vision_config_still_returns_plaintext`**：内部 `settings_service.get_vision_config(db)` 仍返 `{enabled, api_key: "sk-xxx", model}`（明文），供 `ocr_qwen_vl.get_vision_client` 调 dashscope 使用

### 前端手动 verify

服务器部署 + 硬刷后：

1. 后台管理 → 视觉模型 → 打开 Network 面板 → 观察 `GET /api/settings/vision` **response body 无 `api_key` 字段**，只有 `enabled/model/has_api_key`
2. 输入框显示 placeholder `"✓ 已配置 · 留空表示不修改"`（依赖 `has_api_key`）
3. **不填 api_key**，只改 model 或 enabled → 保存 → 应成功 + toast success
4. Network 面板看 `POST /api/settings/vision` request body **不含 api_key 字段**（只有 enabled/model）
5. 再刷新页面 → api_key 保留了 DB 里的旧值（因为 partial update 没动它） — 测试连接仍能通
6. **输入新 key** → 保存 → 应成功，DB 里 key 变为新值

## 部署

标准 scp + docker cp：

```bash
scp v2.5.tar.gz root@8.163.75.9:/opt/audit/compliance-agent/
cd /opt/audit/compliance-agent
tar -xzf v2.5.tar.gz

for c in backend worker enrich_worker; do
  docker compose cp backend/app/services/settings_service.py $c:/app/app/services/settings_service.py
  docker compose cp backend/app/api/settings_routes.py $c:/app/app/api/settings_routes.py
done
docker compose cp backend/tests/test_v25_vision_no_echo.py backend:/app/tests/test_v25_vision_no_echo.py

# 前端 bind mount，tar 解已生效
docker compose restart backend
```

## 回滚

单个 commit revert；或 backend 3 个 python 文件 + frontend 2 个文件手动恢复。DB 数据不动（backward-compatible：现有 vision_api_key 记录仍能读）。
