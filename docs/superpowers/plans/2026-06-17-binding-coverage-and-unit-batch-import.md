# 绑定覆盖率优化 + 单位批量导入 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ① 让材料自动绑定后 `still_unbound` 恒为 0；② 后台单位列表支持 Excel 批量导入并跳过同名。

**Architecture:** 后端 Python (FastAPI + SQLAlchemy)，前端原生 HTML/JS。绑定优化在 `audit_service.auto_bind_materials` 末尾新增 subcategory 兜底阶段，并改造 LLM prompt + 加批次完整性校验。单位导入新建 `unit_import_service.py` + 新增 `POST /api/units/import-from-file` 路由，前端复用现有"评价指标导入"对话框。

**Tech Stack:** Python 3.11 · FastAPI · SQLAlchemy 2.x · pytest · openpyxl 3.1.2 · 原生 ES2022。

**Spec:** `docs/superpowers/specs/2026-06-17-binding-coverage-and-unit-batch-import-design.md`

**约束：** 全部本地通过后再推服务器；保留每个 commit 可独立回滚。

---

## File Map

### 创建文件
- `backend/app/services/unit_import_service.py` — 单位 Excel/CSV 解析 + 入库
- `backend/tests/test_auto_bind_fallback.py` — 绑定兜底阶段测试
- `backend/tests/test_unit_import.py` — 单位批量导入测试
- `backend/tests/fixtures/units_sample.xlsx` — 测试用样本（运行时生成）

### 修改文件
- `backend/app/services/ai_material_classifier.py` — prompt 改造 / batch 参数 / 完整性校验补单
- `backend/app/services/material_matcher.py` — 新增 `SUBCATEGORY_FALLBACK` + `fallback_indicator_for_subcategory`
- `backend/app/services/audit_service.py` — `auto_bind_materials` 加第 3 阶段 + `fallback_bound` 字段
- `backend/app/api/audit_routes.py` — 新增 `POST /api/units/import-from-file` 路由
- `frontend/app.js` — 自动绑定结果显示 `fallback_bound` + 单位列表加「批量导入」按钮

---

## Phase 0: 准备本地测试环境

### Task 0.1: 确保 backend 本地虚拟环境可跑测试

**Files:**
- Check: `compliance-agent/backend/.venv`

- [ ] **Step 1: 检查 venv 是否存在 / 创建并装依赖**

Run:
```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/backend
[ -d .venv ] || /usr/bin/python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

Expected: 安装完无错误，`pip show fastapi sqlalchemy openpyxl pytest` 全部能找到。

- [ ] **Step 2: 跑现有测试套件作为基线**

Run:
```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/backend
source .venv/bin/activate
pytest -q
```

Expected: 全绿（如有红，记录数量，后续改动不应再增加红色）。

- [ ] **Step 3: 没有 commit（环境准备不计入版本）**

---

## Phase 1: 绑定覆盖率优化

### Task 1.1: material_matcher 新增 subcategory 兜底（TDD）

**Files:**
- Modify: `compliance-agent/backend/app/services/material_matcher.py`
- Test: `compliance-agent/backend/tests/test_material_matcher.py`

- [ ] **Step 1: 在 test_material_matcher.py 末尾追加失败测试**

```python
def test_fallback_indicator_for_subcategory_returns_canonical_code():
    from app.services.material_matcher import fallback_indicator_for_subcategory

    class FakeInd:
        def __init__(self, code, sub):
            self.indicator_code = code
            self.subcategory = sub
            self.category = sub
            self.name = code

    inds = [
        FakeInd("I-13", "（一）预算业务控制"),
        FakeInd("I-15", "（一）预算业务控制"),
        FakeInd("I-44", "（六）合同控制"),
        FakeInd("I-55", "补充指标"),
    ]
    assert fallback_indicator_for_subcategory("（一）预算业务控制", inds).indicator_code == "I-13"
    assert fallback_indicator_for_subcategory("（六）合同控制", inds).indicator_code == "I-44"
    # 子类不在 fallback 表 → 退到 I-55
    assert fallback_indicator_for_subcategory("（七）某未知子类", inds).indicator_code == "I-55"
    # 连 I-55 都没有 → None
    no_i55 = [FakeInd("I-13", "（一）预算业务控制")]
    assert fallback_indicator_for_subcategory("（七）某未知子类", no_i55) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd compliance-agent/backend && source .venv/bin/activate && pytest tests/test_material_matcher.py::test_fallback_indicator_for_subcategory_returns_canonical_code -v`
Expected: FAIL with `AttributeError` 或 `ImportError: cannot import name 'fallback_indicator_for_subcategory'`

- [ ] **Step 3: 在 material_matcher.py 末尾追加实现**

```python
# ============================================================
# subcategory 兜底（v1.1 新增）：AI / 关键词都没命中时，
# 把材料硬绑到该子类的「制度类指标」，保证 0 未绑定
# ============================================================
SUBCATEGORY_FALLBACK: dict[str, str] = {
    "组织层面内部控制":           "I-01",
    "（一）预算业务控制":         "I-13",
    "（二）收支业务控制":         "I-20",
    "（三）政府采购业务控制":     "I-25",
    "（四）资产控制":             "I-32",
    "（五）建设项目控制":         "I-37",
    "（六）合同控制":             "I-44",
    "内部监督":                   "I-53",
    "补充指标":                   "I-55",
}


def fallback_indicator_for_subcategory(subcategory: str,
                                       indicators: Iterable[Indicator]) -> Optional[Indicator]:
    """子类 → 该子类制度类指标的兜底映射。

    优先用 SUBCATEGORY_FALLBACK 表里的 code 找指标；
    找不到时退化到 I-55「补充指标」；I-55 也没有则返回 None。
    """
    code = SUBCATEGORY_FALLBACK.get(_normalize(subcategory))
    code2ind = {ind.indicator_code: ind for ind in indicators}
    if code and code in code2ind:
        return code2ind[code]
    return code2ind.get("I-55")
```

- [ ] **Step 4: 再跑测试确认通过**

Run: `pytest tests/test_material_matcher.py::test_fallback_indicator_for_subcategory_returns_canonical_code -v`
Expected: PASS

- [ ] **Step 5: 跑整个 test_material_matcher.py 确认没破现有用例**

Run: `pytest tests/test_material_matcher.py -v`
Expected: 全 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/material_matcher.py backend/tests/test_material_matcher.py
git commit -m "feat(binding): subcategory fallback table + fallback_indicator_for_subcategory"
```

---

### Task 1.2: ai_material_classifier prompt 改造（禁止 LLM 省略）

**Files:**
- Modify: `compliance-agent/backend/app/services/ai_material_classifier.py:25-36`
- Test: `compliance-agent/backend/tests/test_ai_classifier.py`（追加）

- [ ] **Step 1: 在 test_ai_classifier.py 追加 prompt 内容测试**

```python
def test_system_prompt_forbids_skipping():
    from app.services.ai_material_classifier import SYSTEM_PROMPT, _build_prompt

    # 系统提示词必须强制 LLM 给每份材料返回结果
    assert "禁止省略" in SYSTEM_PROMPT or "必须为每份材料" in SYSTEM_PROMPT
    assert "省略该材料" not in SYSTEM_PROMPT  # 旧的"实在判断不出来就省略"已删

    # 用户提示词同样强制全覆盖
    class FakeMat:
        def __init__(self, mid):
            self.id = mid
            self.file_name = f"f{mid}.pdf"
            self.parsed_text = "x"
    class FakeInd:
        def __init__(self, c):
            self.indicator_code = c
            self.subcategory = ""
            self.category = ""
            self.name = c
    p = _build_prompt([FakeMat(1), FakeMat(2)], [FakeInd("I-13"), FakeInd("I-55")])
    assert "必须" in p and "省略" not in p
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_ai_classifier.py::test_system_prompt_forbids_skipping -v`
Expected: FAIL（旧 prompt 含"省略"）

- [ ] **Step 3: 替换 SYSTEM_PROMPT 与 _build_prompt**

```python
SYSTEM_PROMPT = (
    "你是内控评价审计的资深辅助员。任务：根据用户提供的材料内容，"
    "把每份材料映射到对应的「评价指标」编号（I-01 ~ I-55）。"
    "判断依据：材料的主题、制度名称、章节、关键词。"
    "严格要求：① 必须为每份材料返回 1 个 indicator_code，禁止省略任何一份 "
    "② 把握不大时也要选最接近的一项，宁可猜也要给 "
    "③ 只能用提供的 indicator_code，严禁臆造。"
)


BATCH_SIZE = 10
TEXT_PREVIEW = 1500
```

并把 `_build_prompt` 末尾的提示改为：

```python
def _build_prompt(batch: List[Material], indicators: List[Indicator]) -> str:
    return (
        "请阅读以下 N 份内控评价材料，把每份材料分类到对应指标。\n\n"
        "【指标库】（共 55 项，必须使用其中的 indicator_code）\n"
        f"{_format_indicator_list(indicators)}\n\n"
        "【待分类材料】\n"
        f"{_format_materials(batch)}\n\n"
        "请返回严格 JSON：\n"
        '{"mappings": [{"material_id": 数字, "indicator_code": "I-XX", "reason": "≤40字理由"}]}\n'
        "必须覆盖所有传入的 material_id，禁止遗漏；把握不大时也要选最接近的一项。"
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_ai_classifier.py -v`
Expected: 全 PASS（包括既有 + 新加的）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai_material_classifier.py backend/tests/test_ai_classifier.py
git commit -m "feat(binding): prompt forces LLM to return mapping for every material"
```

---

### Task 1.3: ai_classify_materials 加批次完整性校验 + 补单重试

**Files:**
- Modify: `compliance-agent/backend/app/services/ai_material_classifier.py:73-120`
- Test: `compliance-agent/backend/tests/test_ai_classifier.py`（追加）

- [ ] **Step 1: 追加失败测试（mock LLM 模拟漏处理）**

```python
def test_ai_classify_retries_missing_materials():
    """LLM 第一次只返回部分映射 → 触发对漏的材料单独补问一次。"""
    from app.services.ai_material_classifier import ai_classify_materials
    from app.llm.base import LLMClient

    class FakeMat:
        def __init__(self, mid):
            self.id = mid
            self.file_name = f"f{mid}.pdf"
            self.parsed_text = "内容"

    class FakeInd:
        def __init__(self, c):
            self.indicator_code = c
            self.id = int(c.split("-")[1])
            self.subcategory = ""
            self.category = ""
            self.name = c

    inds = [FakeInd("I-01"), FakeInd("I-13"), FakeInd("I-55")]

    calls = []

    class FakeLLM(LLMClient):
        thinking_mode = "off"
        def chat(self, *a, **k): raise NotImplementedError
        def extract_json(self, prompt, system=None, max_tokens=4096):
            calls.append(prompt)
            # 第一次只返回 1/3 → 漏 2 个 → 应触发补单
            if len(calls) == 1:
                return {"mappings": [{"material_id": 1, "indicator_code": "I-01"}]}
            # 补单：把剩下的也给出来
            return {"mappings": [
                {"material_id": 2, "indicator_code": "I-13"},
                {"material_id": 3, "indicator_code": "I-55"},
            ]}

    mats = [FakeMat(1), FakeMat(2), FakeMat(3)]
    result = ai_classify_materials(db=None, task=None, llm=FakeLLM(),
                                   materials=mats, indicators=inds)
    assert result == {1: 1, 2: 13, 3: 55}
    assert len(calls) == 2  # 1 次批量 + 1 次补单
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_ai_classifier.py::test_ai_classify_retries_missing_materials -v`
Expected: FAIL（现版本不补单，只会返回 {1: 1}）

- [ ] **Step 3: 改写 ai_classify_materials**

替换 `ai_classify_materials` 整个函数为：

```python
def ai_classify_materials(db: Session, task: AuditTask,
                          llm: LLMClient,
                          materials: List[Material],
                          indicators: List[Indicator]) -> Dict[int, int]:
    """让 LLM 阅读材料决定绑定。返回 {material_id: indicator.id}。

    v1.1 改动：
    - 缩小 batch、加大文本预览、加大 max_tokens
    - 批次返回数量 < batch 数量 → 对漏的材料补问 1 次
    """
    if isinstance(llm, StubLLMClient):
        return {}
    if not materials:
        return {}

    if hasattr(llm, "thinking_mode"):
        try:
            llm.thinking_mode = "off"
        except Exception:
            pass

    code2id = {ind.indicator_code: ind.id for ind in indicators}
    results: Dict[int, int] = {}

    def _call_once(sub_batch: List[Material]) -> Dict[int, int]:
        prompt = _build_prompt(sub_batch, indicators)
        try:
            data = llm.extract_json(prompt, system=SYSTEM_PROMPT, max_tokens=8192)
        except Exception as exc:
            print(f"[ai_classify] LLM 失败: {exc}")
            return {}
        if not isinstance(data, dict):
            return {}
        out: Dict[int, int] = {}
        for item in data.get("mappings", []) or []:
            if not isinstance(item, dict):
                continue
            try:
                mid = int(item.get("material_id"))
            except (TypeError, ValueError):
                continue
            code = str(item.get("indicator_code", "")).strip()
            iid = code2id.get(code)
            if iid is None:
                continue
            if not any(m.id == mid for m in sub_batch):
                continue
            out[mid] = iid
        return out

    for i in range(0, len(materials), BATCH_SIZE):
        batch = materials[i:i + BATCH_SIZE]
        got = _call_once(batch)
        results.update(got)
        missing = [m for m in batch if m.id not in got]
        if missing:
            # 漏的材料单独再问 1 次（最多 1 轮重试）
            retry = _call_once(missing)
            results.update(retry)

    return results
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_ai_classifier.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai_material_classifier.py backend/tests/test_ai_classifier.py
git commit -m "feat(binding): batch completeness check + retry missing materials once"
```

---

### Task 1.4: audit_service.auto_bind_materials 加第 3 阶段兜底

**Files:**
- Modify: `compliance-agent/backend/app/services/audit_service.py:150-235`
- Test: `compliance-agent/backend/tests/test_auto_bind_fallback.py`（新建）

- [ ] **Step 1: 新建 test_auto_bind_fallback.py**

```python
"""auto_bind_materials 第 3 阶段（subcategory 兜底）测试。

测试使用 stub LLM（conftest 已设环境变量）→ ai_classify 直接返回 {}，
因此能纯净地测「关键词 + 兜底」两条路径，验证 still_unbound == 0。
"""
import io
from fastapi.testclient import TestClient


def _make_task(client, headers, unit_name="测试单位 A"):
    r = client.post("/api/units", json={"name": unit_name, "code": "T-001"},
                    headers=headers)
    assert r.status_code == 200, r.text
    unit_id = r.json()["id"]
    r = client.post("/api/tasks",
                    json={"unit_id": unit_id, "title": "fallback 测试任务", "scope": "all"},
                    headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _upload(client, headers, task_id, filename, content=b"%PDF-1.4\n%test\n"):
    files = {"file": (filename, io.BytesIO(content), "application/pdf")}
    r = client.post(f"/api/tasks/{task_id}/materials", files=files, headers=headers)
    assert r.status_code == 200, r.text


def test_auto_bind_fallback_zero_unbound(auth_headers):
    """端到端：上传一批文件名不含任何指标关键词的材料，
    经过关键词 + AI(stub返回空) + subcategory 兜底后 still_unbound 必须为 0。"""
    from app.main import app
    with TestClient(app) as client:
        task_id = _make_task(client, auth_headers, unit_name="兜底测试单位 1")
        # 子类关键词命中 但 indicator 关键词不命中 → 走第 3 阶段
        for fn in [
            "（一）预算公开报告 2025.pdf",
            "（六）合同签订记录 2025.pdf",
            "完全不带关键词的材料 abc.pdf",  # 这条连子类都没 → 应落到 I-55
        ]:
            _upload(client, auth_headers, task_id, fn)

        r = client.post(f"/api/tasks/{task_id}/materials/auto-bind",
                        headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["still_unbound"] == 0, body
        assert body["fallback_bound"] >= 1


def test_auto_bind_result_has_fallback_field(auth_headers):
    """返回 JSON 必须包含 fallback_bound 字段（向后兼容前端读取）。"""
    from app.main import app
    with TestClient(app) as client:
        task_id = _make_task(client, auth_headers, unit_name="兜底测试单位 2")
        _upload(client, auth_headers, task_id, "随便起的名.pdf")
        r = client.post(f"/api/tasks/{task_id}/materials/auto-bind",
                        headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        for k in ("checked", "keyword_bound", "ai_bound", "fallback_bound", "still_unbound"):
            assert k in body, f"缺字段 {k}: {body}"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_auto_bind_fallback.py -v`
Expected: FAIL（`fallback_bound` 字段不存在 / still_unbound > 0）

- [ ] **Step 3: 修改 auto_bind_materials 末尾加第 3 阶段**

在 `audit_service.py` 中定位 `auto_bind_materials` 函数，把 `# 第 2 阶段：AI 阅读分类（可选）` 之后到 `if keyword_bound or ai_bound:` 之间替换为：

```python
    # 第 2 阶段：AI 阅读分类（可选）
    ai_bound = 0
    ai_used = False
    if use_ai and still_unbound:
        try:
            from app.llm.factory import get_llm_client
            from app.llm.stub import StubLLMClient
            from app.services.ai_material_classifier import ai_classify_materials
            llm = get_llm_client(db)
            ai_used = not isinstance(llm, StubLLMClient)
            mapping = ai_classify_materials(db, task, llm, still_unbound, indicators)
            new_still: list[Material] = []
            for m in still_unbound:
                iid = mapping.get(m.id)
                if iid is None:
                    new_still.append(m)
                    continue
                m.indicator_id = iid
                ai_bound += 1
                if len(samples) < 10:
                    ind = next((x for x in indicators if x.id == iid), None)
                    samples.append({
                        "file": m.file_name[:60],
                        "indicator_code": ind.indicator_code if ind else "?",
                        "source": "ai",
                    })
            still_unbound = new_still
        except Exception as exc:
            print(f"[auto_bind] AI 分类失败（仅关键词生效）: {exc}")

    # 第 3 阶段：subcategory 兜底（v1.1 新增）—— 保证 still_unbound == 0
    from app.services.material_matcher import (
        match_subcategory, fallback_indicator_for_subcategory,
    )
    fallback_bound = 0
    for m in list(still_unbound):
        signal = (m.file_name or "") + " " + (m.parsed_text or "")[:500]
        sub = match_subcategory(signal) or "补充指标"
        ind = fallback_indicator_for_subcategory(sub, indicators)
        if not ind:
            continue
        m.indicator_id = ind.id
        fallback_bound += 1
        still_unbound.remove(m)
        if len(samples) < 15:
            samples.append({
                "file": m.file_name[:60],
                "indicator_code": ind.indicator_code,
                "source": "fallback",
            })

    db.flush()

    if keyword_bound or ai_bound or fallback_bound:
        log_action(db, user, "material.auto_bind",
                   target_type="task", target_id=task.id,
                   detail=(f"自动绑定 关键词 {keyword_bound} + AI {ai_bound} "
                           f"+ 兜底 {fallback_bound} / 共 {checked}"))
    db.commit()
    return {
        "checked": checked,
        "keyword_bound": keyword_bound,
        "ai_bound": ai_bound,
        "fallback_bound": fallback_bound,
        "bound_now": keyword_bound + ai_bound + fallback_bound,
        "still_unbound": len(still_unbound),
        "ai_used": ai_used,
        "samples": samples,
    }
```

注意：把原函数末尾原有的 `if keyword_bound or ai_bound:` / `db.commit()` / `return {...}` 这段一并删除（已被上面替代）。

- [ ] **Step 4: 跑新测试确认通过**

Run: `pytest tests/test_auto_bind_fallback.py -v`
Expected: 全 PASS

- [ ] **Step 5: 跑既有相关测试，确认没破**

Run: `pytest tests/test_ai_classifier.py tests/test_material_matcher.py tests/test_audit_flow.py -v`
Expected: 全 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/audit_service.py backend/tests/test_auto_bind_fallback.py
git commit -m "feat(binding): stage-3 subcategory fallback so still_unbound is always 0"
```

---

### Task 1.5: 前端显示 fallback_bound

**Files:**
- Modify: `compliance-agent/frontend/app.js`

- [ ] **Step 1: 定位自动绑定结果展示位置**

Run: `grep -n "keyword_bound\|ai_bound\|自动绑定" compliance-agent/frontend/app.js | head -10`
找到一处类似 `关键词 ${r.keyword_bound} · AI ${r.ai_bound}` 的字符串拼接。

- [ ] **Step 2: 在该处把 `fallback_bound` 加入展示**

把现有的：
```js
`关键词 ${r.keyword_bound} · AI ${r.ai_bound} · 未绑 ${r.still_unbound}`
```
改为：
```js
`关键词 ${r.keyword_bound} · AI ${r.ai_bound} · 兜底 ${r.fallback_bound || 0} · 未绑 ${r.still_unbound}`
```

（如现有展示字符串不完全一致，按上下文同样追加 `· 兜底 X` 字段。）

- [ ] **Step 3: 手动验证（暂只看代码改对，端到端测放在 Phase 3）**

Run: `grep -n "fallback_bound" compliance-agent/frontend/app.js`
Expected: 至少 1 处命中。

- [ ] **Step 4: Commit**

```bash
git add frontend/app.js
git commit -m "ui(binding): show fallback_bound in auto-bind result banner"
```

---

## Phase 2: 单位 Excel 批量导入

### Task 2.1: unit_import_service 表头识别（TDD 纯函数）

**Files:**
- Create: `compliance-agent/backend/app/services/unit_import_service.py`
- Create: `compliance-agent/backend/tests/test_unit_import.py`

- [ ] **Step 1: 新建 test_unit_import.py，先写表头识别测试**

```python
"""单位批量导入服务测试。"""
import io
import openpyxl


def _make_xlsx(rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_units_xlsx_standard_header():
    from app.services.unit_import_service import _parse_units_file
    raw = _make_xlsx([
        ["代码", "单位名称"],
        ["A001", "甲单位"],
        ["A002", "乙单位"],
    ])
    rows, note = _parse_units_file(raw, "u.xlsx")
    assert rows == [{"name": "甲单位", "code": "A001"},
                    {"name": "乙单位", "code": "A002"}]
    assert "代码" in note and "单位名称" in note


def test_parse_units_xlsx_alias_header():
    from app.services.unit_import_service import _parse_units_file
    raw = _make_xlsx([
        ["编号", "机构名称"],
        ["X1", "丙机构"],
    ])
    rows, _ = _parse_units_file(raw, "u.xlsx")
    assert rows == [{"name": "丙机构", "code": "X1"}]


def test_parse_units_csv():
    from app.services.unit_import_service import _parse_units_file
    raw = "code,name\nC01,丁单位\n".encode("utf-8")
    rows, _ = _parse_units_file(raw, "u.csv")
    assert rows == [{"name": "丁单位", "code": "C01"}]


def test_parse_units_invalid_header_raises():
    from app.services.unit_import_service import _parse_units_file
    raw = _make_xlsx([
        ["列A", "列B"],
        ["x", "y"],
    ])
    import pytest
    with pytest.raises(ValueError):
        _parse_units_file(raw, "u.xlsx")
```

- [ ] **Step 2: 跑测试确认失败（模块不存在）**

Run: `pytest tests/test_unit_import.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: 新建 unit_import_service.py 实现 _parse_units_file**

```python
"""单位 Excel/CSV 批量解析 + 入库服务（v1.1）。"""
from __future__ import annotations

import csv
import io
from typing import Tuple

import openpyxl

from sqlalchemy.orm import Session

from app.models import AuditUnit, User
from app.core.audit_log import log_action


NAME_ALIASES = {"单位名称", "名称", "机构名称", "name"}
CODE_ALIASES = {"代码", "编号", "code", "机构代码", "统一信用代码"}


def _norm(s) -> str:
    return str(s or "").strip().lower()


def _pick_col(header: list, aliases: set[str]) -> int | None:
    for i, h in enumerate(header):
        if _norm(h) in {_norm(a) for a in aliases}:
            return i
    return None


def _parse_units_file(file_bytes: bytes, file_name: str) -> Tuple[list[dict], str]:
    """解析 Excel 或 CSV → [{name, code}], note。

    raise ValueError 当表头无法识别 / 文件格式不支持时。
    """
    name = (file_name or "").lower()
    if name.endswith(".csv"):
        text = file_bytes.decode("utf-8-sig", errors="ignore")
        reader = csv.reader(io.StringIO(text))
        rows = [r for r in reader if any(c.strip() for c in r)]
    elif name.endswith((".xlsx", ".xls")):
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = [list(r) for r in ws.iter_rows(values_only=True)
                if any(v not in (None, "") for v in r)]
    else:
        raise ValueError(f"不支持的文件格式：{file_name}")

    if not rows:
        raise ValueError("文件为空")

    header = rows[0]
    name_idx = _pick_col(header, NAME_ALIASES)
    code_idx = _pick_col(header, CODE_ALIASES)
    if name_idx is None:
        raise ValueError("Excel 表头无法识别，请确保含「名称」列（如：单位名称 / 名称 / 机构名称）")

    out: list[dict] = []
    for r in rows[1:]:
        nm = str(r[name_idx] or "").strip() if name_idx < len(r) else ""
        cd = ""
        if code_idx is not None and code_idx < len(r):
            cd = str(r[code_idx] or "").strip()
        if nm:
            out.append({"name": nm, "code": cd})

    note = f"表头识别：{header[name_idx]}" + (f" / {header[code_idx]}" if code_idx is not None else "")
    return out, note
```

注意：`log_action` 与 `AuditUnit` 的引入用于下一个 task；先放上不报错（unused import 暂可忽略，因下一个 task 立即用到）。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_unit_import.py -v`
Expected: 4 个 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/unit_import_service.py backend/tests/test_unit_import.py
git commit -m "feat(unit-import): xlsx/csv header detection with alias support"
```

---

### Task 2.2: unit_import_service 入库 + dry_run（TDD）

**Files:**
- Modify: `compliance-agent/backend/app/services/unit_import_service.py`
- Modify: `compliance-agent/backend/tests/test_unit_import.py`

- [ ] **Step 1: 在 test_unit_import.py 追加 DB 行为测试**

```python
def test_import_units_inserts_new(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/d.db")
    from app.models import init_db, AuditUnit
    from app.core.db import SessionLocal
    init_db()
    raw = _make_xlsx([
        ["代码", "单位名称"],
        ["X1", "已存在单位"],
        ["X2", "新单位 A"],
        ["X3", "新单位 B"],
    ])
    with SessionLocal() as db:
        db.add(AuditUnit(name="已存在单位", code="OLD"))
        db.commit()
        from app.services.unit_import_service import import_units_from_file
        result = import_units_from_file(db, raw, "u.xlsx")
        assert result["total"] == 3
        assert result["inserted"] == 2
        assert result["skipped"] == 1
        names = {u.name for u in db.query(AuditUnit).all()}
        assert {"已存在单位", "新单位 A", "新单位 B"} <= names
        # 跳过的不被改 code
        assert db.query(AuditUnit).filter_by(name="已存在单位").first().code == "OLD"


def test_import_units_dry_run_does_not_write(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/d.db")
    from app.models import init_db, AuditUnit
    from app.core.db import SessionLocal
    init_db()
    raw = _make_xlsx([
        ["代码", "单位名称"],
        ["X9", "干跑单位"],
    ])
    with SessionLocal() as db:
        from app.services.unit_import_service import import_units_from_file
        result = import_units_from_file(db, raw, "u.xlsx", dry_run=True)
        assert result["total"] == 1
        assert result["preview"][0]["name"] == "干跑单位"
        # 库里没真写
        assert db.query(AuditUnit).filter_by(name="干跑单位").first() is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_unit_import.py::test_import_units_inserts_new tests/test_unit_import.py::test_import_units_dry_run_does_not_write -v`
Expected: FAIL with `ImportError: cannot import name 'import_units_from_file'`

- [ ] **Step 3: 在 unit_import_service.py 末尾追加 import_units_from_file**

```python
def import_units_from_file(db: Session,
                           file_bytes: bytes,
                           file_name: str,
                           dry_run: bool = False,
                           user: User | None = None) -> dict:
    """解析 → 跳过同名 → 入库。dry_run=True 不写库。"""
    rows, note = _parse_units_file(file_bytes, file_name)
    preview = rows[:10]
    if dry_run:
        return {
            "preview": preview,
            "total": len(rows),
            "note": note,
        }

    existing = {n for (n,) in db.query(AuditUnit.name).all()}
    inserted, skipped = 0, 0
    errors: list[str] = []
    for i, row in enumerate(rows, start=2):
        nm = (row.get("name") or "").strip()
        if not nm:
            errors.append(f"第 {i} 行 name 为空")
            continue
        if nm in existing:
            skipped += 1
            continue
        db.add(AuditUnit(name=nm, code=row.get("code", "")[:64], level="单位"))
        existing.add(nm)
        inserted += 1

    if user is not None:
        try:
            log_action(db, user, "unit.batch_import",
                       target_type="unit", target_id=0,
                       detail=f"批量导入 总{len(rows)} 入{inserted} 跳{skipped} 错{len(errors)}")
        except Exception:
            pass
    db.commit()
    return {
        "preview": preview,
        "total": len(rows),
        "inserted": inserted,
        "skipped": skipped,
        "errors": errors[:20],
        "note": note,
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_unit_import.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/unit_import_service.py backend/tests/test_unit_import.py
git commit -m "feat(unit-import): import_units_from_file with dedup + dry_run"
```

---

### Task 2.3: 新增 API 路由 POST /api/units/import-from-file

**Files:**
- Modify: `compliance-agent/backend/app/api/audit_routes.py`
- Modify: `compliance-agent/backend/tests/test_unit_import.py`

- [ ] **Step 1: 在 test_unit_import.py 追加 e2e 路由测试**

```python
def test_api_import_units_endpoint(auth_headers):
    from fastapi.testclient import TestClient
    from app.main import app
    raw = _make_xlsx([
        ["代码", "单位名称"],
        ["E1", "API 测试单位 1"],
        ["E2", "API 测试单位 2"],
    ])
    with TestClient(app) as c:
        files = {"file": ("u.xlsx", io.BytesIO(raw),
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        r = c.post("/api/units/import-from-file?dry_run=true",
                   files=files, headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 2
        assert "preview" in body

        # 真正入库
        files = {"file": ("u.xlsx", io.BytesIO(raw),
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        r = c.post("/api/units/import-from-file", files=files, headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["inserted"] == 2
        assert body["skipped"] == 0

        # 第二次同样文件 → 全部跳过
        files = {"file": ("u.xlsx", io.BytesIO(raw),
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        r = c.post("/api/units/import-from-file", files=files, headers=auth_headers)
        assert r.json()["inserted"] == 0
        assert r.json()["skipped"] == 2


def test_api_import_units_bad_header_returns_400(auth_headers):
    from fastapi.testclient import TestClient
    from app.main import app
    raw = _make_xlsx([["列A", "列B"], ["x", "y"]])
    with TestClient(app) as c:
        files = {"file": ("u.xlsx", io.BytesIO(raw), "application/octet-stream")}
        r = c.post("/api/units/import-from-file", files=files, headers=auth_headers)
        assert r.status_code == 400
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_unit_import.py::test_api_import_units_endpoint -v`
Expected: FAIL with 404（路由不存在）

- [ ] **Step 3: 在 audit_routes.py 的 units_router DELETE 之后加新路由**

定位 `@units_router.delete("/{unit_id}")` 函数末尾，紧接其后追加：

```python
@units_router.post("/import-from-file", response_model=dict)
async def import_units_from_file_api(
    file: UploadFile = File(...),
    dry_run: bool = Query(False, description="true 仅返回预览不入库"),
    db: Session = Depends(get_db),
    user: User = Depends(require_auditor),
):
    """Excel / CSV 批量导入被检查单位（已存在同名 → 跳过）。"""
    from app.services.unit_import_service import import_units_from_file
    raw = await file.read()
    try:
        return import_units_from_file(db, raw, file.filename or "u.xlsx",
                                      dry_run=dry_run, user=user)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_unit_import.py -v`
Expected: 全 PASS

- [ ] **Step 5: 跑全套测试确认没破**

Run: `pytest -q`
Expected: 与 Phase 0 基线相比，绿色数量增加，红色不增加。

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/audit_routes.py backend/tests/test_unit_import.py
git commit -m "feat(unit-import): POST /api/units/import-from-file endpoint"
```

---

### Task 2.4: 前端单位列表加「批量导入」按钮

**Files:**
- Modify: `compliance-agent/frontend/app.js`

- [ ] **Step 1: 找到单位列表渲染的位置**

Run: `grep -n "单位\|units" compliance-agent/frontend/app.js | grep -iE "render|list|toolbar|新增|button" | head -10`

定位渲染"单位列表"顶部工具栏的代码段（与"评价指标"列表风格一致）。

- [ ] **Step 2: 找到现有"评价指标 → 批量导入"按钮的实现作为参考**

Run: `grep -n "indicators/import\|批量导入" compliance-agent/frontend/app.js | head -10`

记录现有按钮调用的辅助函数名（通常类似 `openImportDialog('indicators', '/api/indicators/import-from-file')`）。

- [ ] **Step 3: 在单位列表工具栏处复用同样的函数**

在单位列表工具栏的「新增单位」按钮旁加：

```js
// 与"评价指标批量导入"完全相同的对话框，仅 endpoint 改为单位
const importBtn = document.createElement('button');
importBtn.className = 'btn btn-default';
importBtn.textContent = '批量导入';
importBtn.onclick = () => openImportDialog({
  title: '批量导入被检查单位',
  endpoint: '/api/units/import-from-file',
  onSuccess: () => loadUnits(),  // 现有列表刷新函数
});
toolbar.appendChild(importBtn);
```

（按现有代码风格命名/挂载方式调整；如 `openImportDialog` 名字不同，用现有同等函数。）

- [ ] **Step 4: 若现有没有通用 openImportDialog 函数，直接在按钮 onclick 写一个最小实现**

最小内联实现（仅在没有通用对话框时使用）：

```js
importBtn.onclick = async () => {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.xlsx,.xls,.csv';
  input.onchange = async () => {
    const f = input.files[0];
    if (!f) return;
    const fd = new FormData();
    fd.append('file', f);
    const r = await fetch('/api/units/import-from-file', {
      method: 'POST',
      body: fd,
      headers: { Authorization: `Bearer ${getToken()}` },  // 用现有 getToken
    });
    const j = await r.json();
    if (!r.ok) { alert(j.detail || '导入失败'); return; }
    alert(`总 ${j.total} · 入库 ${j.inserted} · 跳过 ${j.skipped} · 错误 ${j.errors.length}`);
    loadUnits();
  };
  input.click();
};
```

- [ ] **Step 5: Commit**

```bash
git add frontend/app.js
git commit -m "ui(unit-import): batch import button on units admin page"
```

---

## Phase 3: 本地端到端验证 + 推送服务器

### Task 3.1: 全套 pytest 跑一遍

- [ ] **Step 1: 跑 backend 全部测试**

Run:
```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent/backend
source .venv/bin/activate
pytest -v 2>&1 | tail -40
```

Expected:
- Phase 0 时记录的红色用例数 → **不增加**
- 新增至少 8 个绿色用例（material_matcher 1 + ai_classifier 2 + auto_bind_fallback 2 + unit_import 5+）

- [ ] **Step 2: 如有红，按报错定位修复，再跑直到绿**

### Task 3.2: 本地启动后端 + 前端，端到端验证

- [ ] **Step 1: 启动后端**

Run:
```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体/compliance-agent
docker compose up -d
docker compose ps
```

Expected: 7 个容器都 healthy。

或如不想用 docker，本地最简启动：
```bash
cd compliance-agent/backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

- [ ] **Step 2: 浏览器打开 http://localhost:18080/（docker）或 http://localhost:8000/（本地）**

- [ ] **Step 3: 验证绑定覆盖率**
  - 登录 admin / admin123
  - 新建一个被检查单位 + 任务
  - 上传 30+ 份混杂材料（含一些文件名不带任何关键词的）
  - 点「自动绑定」
  - 期望结果 banner：`关键词 X · AI Y · 兜底 Z · 未绑 0`

- [ ] **Step 4: 验证单位批量导入**
  - 进入后台管理 → 单位
  - 点右上「批量导入」
  - 上传 `/Users/lizhishaoniange/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/wxid_ul5ul7wtnltn22_581e/temp/drag/评价单位5267(2).xlsx`
  - 期望 banner：`总 5267 · 入库 5267 · 跳过 0`
  - 再点同一文件二次上传 → 期望 `入库 0 · 跳过 5267`

- [ ] **Step 5: 如发现问题回到对应 Task 修复后重测**

### Task 3.3: 推送服务器

- [ ] **Step 1: 看 git 状态确认所有改动都已提交**

Run: `git status` → Expected: `nothing to commit, working tree clean`

- [ ] **Step 2: 推送到远程**

Run:
```bash
git push origin main
```

- [ ] **Step 3: 在阿里云 ECS 上拉取并热更新**

按现有部署流程（参考 `deploy.sh`），ssh 到服务器执行：
```bash
cd /path/to/compliance-agent
git pull
docker compose up -d --build backend worker
```

- [ ] **Step 4: 在生产环境复跑 Task 3.2 第 3 / 4 步的端到端检查**

Expected: 行为与本地一致。

---

## 完工标准

- [ ] backend pytest 全绿（基线红线不增加，新增至少 8 个绿）
- [ ] 自动绑定 banner 显示 4 段：关键词 / AI / 兜底 / 未绑，且未绑恒为 0
- [ ] 单位批量导入：5267 行 xlsx 一次入库成功，重复导入全跳过
- [ ] 所有改动都已 commit + push 到远程
- [ ] 生产环境复测一致
