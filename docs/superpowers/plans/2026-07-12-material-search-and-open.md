# v2.9 材料搜索 + 文件点击打开 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 材料绑定页加即时搜索（文件名 + 已绑定指标 name/code）+ 文件名点击新 tab 打开预览。

**Architecture:** 纯前端改动。Filter bar 静态注入到 `index.html` 材料表格上方（保证 renderMaterials 重跑不清空搜索值）。过滤在 DOM 层：每行渲染时把 `file_name + 指标 name/code` 拼进 `data-search-index` 属性，input 事件读该属性做 `includes()` 匹配隐藏/显示行。文件名 `<td>` 变 `<a href="/api/materials/{id}/preview" target="_blank">` — 后端 preview endpoint 已就位（`audit_routes.py:731`）。

**Tech Stack:** Vanilla JS + 单页 HTML（无 build 系统）。无前端自动化测试基础设施 → 手工浏览器验证。

## Global Constraints

- 纯前端，不改后端（`GET /api/materials/{id}/preview` 已支持 PDF/图片/text inline + Office 下载）
- Filter bar HTML 放 `index.html`，不放 `renderMaterials()` 动态注入（搜索值必须跨 tbody 重渲染存活）
- 过滤在 DOM 层（`row.style.display`），不改 `State.taskDetail.materials`，不影响 checkbox 选中状态和绑定下拉功能
- `data-search-index` 属性值必须 `esc()` 转义（防 XSS）
- 事件绑定用 `_materialSearchInited` module-level flag 保证 idempotent
- index.html 里的 static asset cache-buster `?v=2.7` → `?v=2.9`（跳过 v2.8）
- 部署：Workbench 拖 app.js + index.html 到 `/opt/audit/compliance-agent/frontend/`，浏览器强刷即可（frontend 是 bind mount，无需 restart nginx）
- 中文注释 + commit 消息

---

## File Structure

| 文件 | 责任 | 状态 |
|---|---|---|
| `compliance-agent/frontend/index.html` | Filter bar 静态 HTML 注入到"已上传材料"表格 header 之后、`<table>` 之前 + cache-buster 从 v2.7 → v2.9 | 修改 |
| `compliance-agent/frontend/app.js` | 新增 `_filterMaterialRows(kw)` 和 `_initMaterialSearch()`；改 `renderMaterials()` 里的 tr 加 `data-search-index`、文件名 td 改 `<a>`、结尾调 `_initMaterialSearch()` + `_filterMaterialRows(currentValue)` | 修改 |
| `compliance-agent/README.md` | 更新日志加 v2.9 一行 | 修改 |

---

## Task 1: 前端全部代码改动（index.html + app.js）

**Files:**
- Modify: `compliance-agent/frontend/index.html:370-392`（filter bar HTML 插入 + `?v=2.7` → `?v=2.9`）
- Modify: `compliance-agent/frontend/app.js:1556-1637`（renderMaterials 三处 + 新增两个函数）

**Interfaces:**
- Consumes:
  - `State.taskDetail.materials` — 数组，每项含 `id`, `file_name`, `indicator_id`
  - `State.indicators` — 数组，每项含 `id`, `indicator_code`, `name`
  - 后端 `GET /api/materials/{id}/preview`（已就位，inline PDF/图片/text，Office 下载）
  - 现有 helper `esc(s)` — HTML escape
- Produces:
  - JS 函数 `_filterMaterialRows(keyword: string)` — 纯 DOM 层过滤 tbody 中的 `<tr>`，更新计数 span 和空态行
  - JS 函数 `_initMaterialSearch()` — idempotent，绑定 input 和 clear button 事件
  - DOM element ids：`tw-material-search`（input）、`tw-material-search-clear`（button）、`tw-material-count`（span）
  - `<tr>` data attribute：`data-search-index="<file_name> <ind_code> <ind_name>"`

- [ ] **Step 1: 在 index.html 加 filter bar HTML**

打开 `compliance-agent/frontend/index.html`。定位到第 382 行（`</div>` 关闭 header 的 flex）与第 383 行（`<table class="table">`）之间。在 `</div>` 之后、`<table>` 之前插入：

```html
            <!-- v2.9: 材料搜索 filter bar -->
            <div class="tw-material-filter" style="display:flex;align-items:center;gap:8px;padding:12px 24px;background:#fafafa;border-bottom:1px solid var(--divider)">
              <span style="color:#6e6e73">🔍</span>
              <input id="tw-material-search" type="text"
                     class="form-control"
                     placeholder="搜索文件名 / 绑定指标（支持指标编号如 I-45）"
                     style="flex:1;min-width:200px" />
              <button type="button" class="btn btn-secondary btn-sm" id="tw-material-search-clear"
                      title="清空搜索">清空</button>
              <span id="tw-material-count" style="color:#6e6e73;font-size:13px;white-space:nowrap">
                共 <strong>0</strong> 份 · 显示 <strong>0</strong> 份
              </span>
            </div>
```

**注意样式选择**：
- 背景色 `#fafafa` + `border-bottom` 让 filter bar 视觉上属于 card 内的第二段（跟 header 分开又协调）
- padding 用 `12px 24px` 跟 header 的 `16px 24px` 左右对齐
- 按钮用 `btn btn-secondary btn-sm`（不是 spec 里写的 `btn-outline`，因为 index.html 现有代码用的是 `btn-secondary`）

- [ ] **Step 2: bump cache-buster**

在 `compliance-agent/frontend/index.html` 里找 `?v=2.7`（应该在 `<script src="/static/app.js?v=2.7">` 和/或 `<link ... href=".../style.css?v=2.7">` 处），改成 `?v=2.9`。

```bash
# 定位所有 v=2.7 出现的地方
grep -n "?v=2\." compliance-agent/frontend/index.html
```

用 Edit 工具把每处 `?v=2.7` 改成 `?v=2.9`（如有多处，`replace_all=true`）。

- [ ] **Step 3: 在 app.js 加 `_filterMaterialRows` 和 `_initMaterialSearch`**

打开 `compliance-agent/frontend/app.js`。在 `renderMaterials()` 函数（第 1556 行开始）**之前**插入两个新函数：

```javascript
// v2.9: 材料表搜索初始化（idempotent，只绑一次事件）
let _materialSearchInited = false;
function _initMaterialSearch() {
  if (_materialSearchInited) return;
  const searchInput = document.getElementById("tw-material-search");
  const searchClear = document.getElementById("tw-material-search-clear");
  if (!searchInput || !searchClear) return;
  searchInput.addEventListener("input", (ev) => _filterMaterialRows(ev.target.value));
  searchClear.addEventListener("click", () => {
    searchInput.value = "";
    _filterMaterialRows("");
    searchInput.focus();
  });
  _materialSearchInited = true;
}

// v2.9: 纯 DOM 层过滤材料行 + 更新计数 + 空态
function _filterMaterialRows(keyword) {
  const kw = (keyword || "").trim().toLowerCase();
  const tbody = document.getElementById("tw-materials-tbody");
  if (!tbody) return;
  // 空态行不参与匹配，先隔离
  const emptyHit = tbody.querySelector("tr.tw-material-empty-hit");
  const rows = Array.from(tbody.querySelectorAll("tr")).filter(r => r !== emptyHit);
  let shown = 0;
  rows.forEach(row => {
    if (!kw) {
      row.style.display = "";
      shown++;
    } else {
      const haystack = (row.dataset.searchIndex || "").toLowerCase();
      if (haystack.includes(kw)) {
        row.style.display = "";
        shown++;
      } else {
        row.style.display = "none";
      }
    }
  });
  // 更新计数
  const countEl = document.getElementById("tw-material-count");
  if (countEl) {
    countEl.innerHTML = `共 <strong>${rows.length}</strong> 份 · 显示 <strong>${shown}</strong> 份`;
  }
  // 空态处理：搜索有关键词但零命中 → 显示；否则隐藏
  if (kw && shown === 0) {
    if (emptyHit) {
      emptyHit.style.display = "";
    } else {
      const tr = document.createElement("tr");
      tr.className = "tw-material-empty-hit";
      tr.innerHTML = `<td colspan="5" class="empty-state" style="padding:24px">
        <div>🔍 无匹配材料</div>
        <div style="font-size:13px;color:#6e6e73;margin-top:4px">试试其他关键词，或清空搜索</div>
      </td>`;
      tbody.appendChild(tr);
    }
  } else if (emptyHit) {
    emptyHit.style.display = "none";
  }
}
```

- [ ] **Step 4: 改 renderMaterials —— tr 加 data-search-index、文件名改 `<a>`**

在 `compliance-agent/frontend/app.js` 定位到 `renderMaterials()` 里生成 tbody.innerHTML 的 `.map(m => {` 循环（约第 1592-1615 行）。

找到当前代码块：

```javascript
  tbody.innerHTML = d.materials.map(m => {
    let ke = {};
    try { ke = JSON.parse(m.key_elements || "{}"); } catch {}
    const badges = [
      ke.has_official_seal ? `<span class="badge badge-green">公章</span>` : `<span class="badge badge-red">无公章</span>`,
      ke.has_signature ? `<span class="badge badge-green">签字</span>` : `<span class="badge badge-orange">无签字</span>`,
      ke.issue_year ? `<span class="tag">${ke.issue_year}</span>` : `<span class="badge badge-red">无日期</span>`,
      ke.is_draft ? `<span class="badge badge-red">草稿</span>` : '',
      ke.document_number ? `<span class="tag">${esc(ke.document_number)}</span>` : '',
    ].filter(Boolean).join(" ");
    const selectClass = m.indicator_id ? "form-select tw-bind-select" : "form-select tw-bind-select tw-bind-unset";
    return `<tr>
      <td><input type="checkbox" class="material-select" data-material-id="${m.id}" /></td>
      <td><span class="code-id">#${pad(m.id)}</span></td>
      <td style="font-weight:500">${esc(m.file_name)}</td>
      <td>
        <select class="${selectClass}" data-material-id="${m.id}" style="min-width:240px">
          <option value="">— 未绑定 —</option>
          ${indOptionsHtml.replace(new RegExp(`value="${m.indicator_id}"`), `value="${m.indicator_id}" selected`)}
        </select>
      </td>
      <td><div class="flex gap-1" style="flex-wrap:wrap">${badges}</div></td>
    </tr>`;
  }).join("");
```

替换为：

```javascript
  tbody.innerHTML = d.materials.map(m => {
    let ke = {};
    try { ke = JSON.parse(m.key_elements || "{}"); } catch {}
    const badges = [
      ke.has_official_seal ? `<span class="badge badge-green">公章</span>` : `<span class="badge badge-red">无公章</span>`,
      ke.has_signature ? `<span class="badge badge-green">签字</span>` : `<span class="badge badge-orange">无签字</span>`,
      ke.issue_year ? `<span class="tag">${ke.issue_year}</span>` : `<span class="badge badge-red">无日期</span>`,
      ke.is_draft ? `<span class="badge badge-red">草稿</span>` : '',
      ke.document_number ? `<span class="tag">${esc(ke.document_number)}</span>` : '',
    ].filter(Boolean).join(" ");
    const selectClass = m.indicator_id ? "form-select tw-bind-select" : "form-select tw-bind-select tw-bind-unset";
    // v2.9: 搜索索引（文件名 + 绑定指标 code + name），拼成 substring 匹配用的 haystack
    const boundInd = State.indicators.find(i => i.id === m.indicator_id);
    const bindLabel = boundInd ? `${boundInd.indicator_code} ${boundInd.name}` : "";
    const searchIdx = `${m.file_name || ""} ${bindLabel}`;
    return `<tr data-search-index="${esc(searchIdx)}">
      <td><input type="checkbox" class="material-select" data-material-id="${m.id}" /></td>
      <td><span class="code-id">#${pad(m.id)}</span></td>
      <td style="font-weight:500;word-break:break-all">
        <a href="/api/materials/${m.id}/preview" target="_blank" rel="noopener"
           style="color:#0071e3;text-decoration:none"
           onmouseover="this.style.textDecoration='underline'"
           onmouseout="this.style.textDecoration='none'"
           title="点击在新标签页打开 / 下载">${esc(m.file_name)}</a>
      </td>
      <td>
        <select class="${selectClass}" data-material-id="${m.id}" style="min-width:240px">
          <option value="">— 未绑定 —</option>
          ${indOptionsHtml.replace(new RegExp(`value="${m.indicator_id}"`), `value="${m.indicator_id}" selected`)}
        </select>
      </td>
      <td><div class="flex gap-1" style="flex-wrap:wrap">${badges}</div></td>
    </tr>`;
  }).join("");
```

- [ ] **Step 5: 改 renderMaterials 结尾 —— init 搜索 + 复用当前值**

在 `renderMaterials()` 结尾（约第 1636 行 `renderRunButton(d.task, d.materials);` 之前），加：

```javascript
  // v2.9: init 搜索（idempotent）+ tbody 重渲染后复用当前搜索值
  _initMaterialSearch();
  const _searchInput = document.getElementById("tw-material-search");
  _filterMaterialRows(_searchInput ? _searchInput.value : "");
```

完整的 renderMaterials 结尾片段应该是：

```javascript
  // 绑定下拉变更 → 调 PATCH
  tbody.querySelectorAll("select.tw-bind-select").forEach(sel => {
    sel.addEventListener("change", async ev => {
      const mid = ev.target.dataset.materialId;
      const val = ev.target.value;
      try {
        await api(`/tasks/${State.taskId}/materials/${mid}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ indicator_id: val ? parseInt(val) : null }),
        });
        await loadTaskWorkspace(State.taskId);
      } catch (e) { toast("绑定失败：" + e.message, "error"); }
    });
  });

  // v2.9: init 搜索（idempotent）+ tbody 重渲染后复用当前搜索值
  _initMaterialSearch();
  const _searchInput = document.getElementById("tw-material-search");
  _filterMaterialRows(_searchInput ? _searchInput.value : "");

  // v2.3：抽独立函数，让 loadTaskWorkspace + 轮询回调都能刷按钮
  renderRunButton(d.task, d.materials);
}
```

- [ ] **Step 6: 语法检查 —— node -c parse app.js**

```bash
cd compliance-agent/frontend && node --check app.js && echo "SYNTAX OK"
```

Expected: 输出 `SYNTAX OK`（说明 JS 语法无破坏）

- [ ] **Step 7: HTML 结构检查**

```bash
grep -c 'tw-material-search"' compliance-agent/frontend/index.html
grep -c '?v=2.9' compliance-agent/frontend/index.html
```

Expected:
- 第一个 grep 输出 `1`（filter bar input id 出现 1 次）
- 第二个 grep 输出 `>=1`（至少 app.js 引用带 v=2.9）

- [ ] **Step 8: Commit**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/frontend/index.html compliance-agent/frontend/app.js
git commit -m "$(cat <<'EOF'
feat(v2.9): 材料绑定页 —— 搜索 + 文件点击打开

- index.html: filter bar 静态注入到"已上传材料"表格上方（保证 renderMaterials 重跑不清空搜索值）
- app.js: _filterMaterialRows 纯 DOM 过滤 + _initMaterialSearch idempotent 事件绑定
- 每行渲染时 data-search-index 缓存 "file_name + 指标 code + name"
- 文件名 <td> 改 <a target="_blank"> 指向 /api/materials/{id}/preview
- cache-buster ?v=2.7 → ?v=2.9

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 部署 + 手工验证 + README

**Files:**
- 无代码改动，Task 1 的两个前端文件传到生产
- Modify: `compliance-agent/README.md`（更新日志加 v2.9 一行）

**Interfaces:** 无

- [ ] **Step 1: 给用户 Workbench 上传指令**

Workbench 拖两个文件到 ECS，覆盖：

| 本地 | ECS |
|---|---|
| `compliance-agent/frontend/index.html` | `/opt/audit/compliance-agent/frontend/index.html` |
| `compliance-agent/frontend/app.js` | `/opt/audit/compliance-agent/frontend/app.js` |

Frontend 是 bind mount，**无需** `docker compose cp`，**无需** restart nginx。浏览器强刷即可。

- [ ] **Step 2: 用户浏览器打开 http://8.163.75.9/ 走 checklist**

引导用户逐条验证（每条都必须过）：

- [ ] 硬刷 Cmd+Shift+R（或 F12 → Network → Disable cache → F5），确认加载的 app.js URL 里带 `?v=2.9`
- [ ] 进任意有 20+ 材料的任务 → 材料 tab，filter bar 显示在"已上传材料"标题下、表格之上
- [ ] 搜索"合同" → 只显示 file_name 或绑定指标含"合同"的行；计数变化
- [ ] 搜索"I-45" → 只显示当前绑到 I-45 的行（v2.8 rebind 后应有）
- [ ] 搜索"岗位职责" → 只显示 file_name 或绑定指标含"岗位职责"的行
- [ ] 清空搜索框 → 恢复显示全部；计数恢复
- [ ] 搜索"asdfghjkl" → 显示 "🔍 无匹配材料" 空态 + 计数 "显示 0 份"
- [ ] 点击 clear 按钮 → 输入框清空 + 恢复全部 + 输入框获得 focus
- [ ] 点击 PDF 类型文件名 → 新 tab 打开 PDF 预览
- [ ] 点击 docx / xlsx 类型文件名 → 浏览器触发下载
- [ ] Filter 隐藏一行后，checkbox 选中状态不受影响（选中→隐藏→显示后仍勾）
- [ ] Filter 期间改绑定下拉 → PATCH 正常，重新加载后搜索值保留

**中间任意一条失败** → 报告故障 → 回到 Task 1 修 → 重新部署 → 重跑本 checklist。

- [ ] **Step 3: 前端验证全绿后，写 README 更新日志**

Edit `compliance-agent/README.md`。找到已有的 "## 更新日志（部分）" 段落（在 v2.8 已加过）。在 v2.8 那一行之前插入 v2.9：

```markdown
- **v2.9（2026-07-12）**：材料绑定页加即时搜索框（匹配文件名 + 已绑定指标 name/code）+ 文件名点击新 tab 打开预览。复用后端已有的 `GET /api/materials/{id}/preview` 端点。详见 `docs/superpowers/plans/2026-07-12-material-search-and-open.md`
- **v2.8（2026-07-12）**：`material_matcher` 加二级文件夹语义识别，识别"XX业务/岗位职责说明书"类路径 → 岗位分离指标（I-14/21/26/33/38/45），修复 v1.5 之后 fallback 到"制度"类的错绑；配套 `app/scripts/rebind_wrong_bindings_v28.py` 一次性 rebind 历史存量。详见 `docs/superpowers/plans/2026-07-12-*.md`
```

- [ ] **Step 4: Commit README**

```bash
cd /Users/lizhishaoniange/Documents/ai审计智能体
git add compliance-agent/README.md
git commit -m "$(cat <<'EOF'
docs(v2.9): README 加更新日志

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec coverage check:**
- ✅ Filter bar 静态注入到 index.html（不在 renderMaterials 里注入）→ Task 1 Step 1
- ✅ 客户端 DOM 层过滤 file_name + 已绑定指标 name/code → Task 1 Step 3
- ✅ `data-search-index` 属性缓存 → Task 1 Step 4
- ✅ 文件名 `<a target="_blank">` → Task 1 Step 4
- ✅ idempotent `_initMaterialSearch()` + `_materialSearchInited` flag → Task 1 Step 3
- ✅ renderMaterials 结尾复用当前搜索值 → Task 1 Step 5
- ✅ cache-buster `?v=2.7` → `?v=2.9` → Task 1 Step 2
- ✅ 空态 "无匹配材料" → Task 1 Step 3
- ✅ "共 X · 显示 Y" 计数 → Task 1 Step 3
- ✅ 清空按钮 + focus 回搜索框 → Task 1 Step 3
- ✅ 手工验证 checklist → Task 2 Step 2（覆盖 spec checklist 全部 11 条 + 加 2 条：cache-buster 生效 + 改绑不受搜索影响）
- ✅ README 更新日志 → Task 2 Step 3
- ✅ 部署仅 cp 前端 + F5 无 restart → Task 2 Step 1
- ✅ 回滚：git revert 后重新 Workbench 上传 → Task 2 隐含（spec 里明确）

**Placeholder scan:** 无 TODO/TBD；所有代码块完整；所有命令带 Expected。

**Type consistency:**
- `_filterMaterialRows(keyword: string)` 一致（Task 1 Step 3 + Step 5）
- `_initMaterialSearch()` 一致
- `_materialSearchInited` 全局 flag 一致
- DOM ids `tw-material-search` / `tw-material-search-clear` / `tw-material-count` / `tw-material-empty-hit` 一致
- `data-search-index` attribute 名一致

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-12-material-search-and-open.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — Task 1 派 fresh subagent 跑完 code + syntax check + commit；我 review 后 Task 2 由用户在浏览器跑 checklist（我不能直接开浏览器）

**2. Inline Execution** — 本会话直接改 code + commit（Task 1），然后 hand-off Task 2 checklist 给用户

Which approach?
