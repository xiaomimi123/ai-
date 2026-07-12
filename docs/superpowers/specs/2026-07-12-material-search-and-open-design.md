# 材料绑定页 —— 搜索 + 点击打开（v2.9）

**日期**：2026-07-12
**范围**：纯前端（`app.js` + `index.html` cache-buster）
**动机**：材料绑定表当前 36+ 份材料只能滚动翻阅、复审无检索；文件名是纯文本无法快速核对内容。核查员在复审 rebind 后的绑定结果时急需按关键词过滤 + 一键打开原文。

## 目标

1. 材料表上方加一条 filter bar，即时按 file_name / 已绑定指标名/编号过滤显示
2. 文件名变可点击链接 → 新 tab 打开（PDF/图片内联，Office 文件下载）
3. 计数动态反映："共 X 份 · 当前显示 Y 份"

## 非目标（YAGNI）

- 不改后端（`GET /api/materials/{id}/preview` 已存在，覆盖所有主流文件类型）
- 不加分页（几十到几百材料量级客户端全渲染够用）
- 不做全文/向量检索 parsed_text（overkill）
- 不做 key_elements（文号/年份）搜索（先解决高频需求）
- 不改 CSS 文件，用现有类 + 内联 style
- 不加后端搜索 API（数据已全在 State 内存里）
- 不加自动化前端测试（项目当前无前端测试基础设施，靠手工 checklist 验证）

## 设计

### 1. Filter bar（**静态**注入到 `index.html`，位于 tw-bind-banner 之后、materials table 之前）

**放在 index.html 而非 renderMaterials 里注入**，这样搜索输入值在 renderMaterials 重跑时不会被清空（batch delete / AI 绑定后会重跑）。

```html
<!-- v2.9: 材料搜索 filter bar，位于 <div id="tw-bind-banner"> 之后 -->
<div class="tw-material-filter" style="display:flex;align-items:center;gap:8px;margin:8px 0;padding:8px 12px;background:#f5f5f7;border-radius:6px">
  <span style="color:#6e6e73">🔍</span>
  <input id="tw-material-search" type="text"
         class="form-control"
         placeholder="搜索文件名 / 绑定指标（支持指标编号如 I-45）"
         style="flex:1;min-width:200px" />
  <button type="button" class="btn btn-outline" id="tw-material-search-clear"
          title="清空搜索">清空</button>
  <span id="tw-material-count" style="color:#6e6e73;font-size:13px;white-space:nowrap">
    共 <strong>0</strong> 份 · 显示 <strong>0</strong> 份
  </span>
</div>
```

**事件绑定放 app.js 顶层一次性 attachOnce 或 DOMContentLoaded**（不放 renderMaterials，避免重复绑定）。

### 2. 过滤逻辑（纯 DOM 层，不动 State）

新增 `_filterMaterialRows(keyword: string)`：

```javascript
function _filterMaterialRows(keyword) {
  const kw = (keyword || "").trim().toLowerCase();
  const tbody = document.getElementById("tw-materials-tbody");
  if (!tbody) return;
  const rows = Array.from(tbody.querySelectorAll("tr"));
  let shown = 0;
  rows.forEach(row => {
    if (!kw) {
      row.style.display = "";
      shown++;
      return;
    }
    // 匹配串 = file_name + 已绑定指标的 name + code（都拼在 data-* 属性里）
    const haystack = (row.dataset.searchIndex || "").toLowerCase();
    if (haystack.includes(kw)) {
      row.style.display = "";
      shown++;
    } else {
      row.style.display = "none";
    }
  });
  // 更新计数
  const total = rows.length;
  const countEl = document.getElementById("tw-material-count");
  if (countEl) {
    countEl.innerHTML = `共 <strong>${total}</strong> 份 · 显示 <strong>${shown}</strong> 份`;
  }
  // 无命中显示空态
  const emptyRow = tbody.querySelector("tr.tw-material-empty-hit");
  if (kw && shown === 0) {
    if (!emptyRow) {
      const tr = document.createElement("tr");
      tr.className = "tw-material-empty-hit";
      tr.innerHTML = `<td colspan="5" class="empty-state" style="padding:24px">
        <div>🔍 无匹配材料</div>
        <div style="font-size:13px;color:#6e6e73;margin-top:4px">试试其他关键词，或清空搜索</div>
      </td>`;
      tbody.appendChild(tr);
    } else {
      emptyRow.style.display = "";
    }
  } else if (emptyRow) {
    emptyRow.style.display = "none";
  }
}
```

**关键**：每行渲染时把 `file_name + 绑定指标 name + code` 拼进 `data-search-index` 属性，过滤时读这个字符串，避免每次 keyup 重新 join 字段。

### 3. renderMaterials 三处改动

**改动 A**：`m` 循环里，把 `data-search-index` 塞到 `<tr>`：

```javascript
const boundInd = State.indicators.find(i => i.id === m.indicator_id);
const bindLabel = boundInd ? `${boundInd.indicator_code} ${boundInd.name}` : "";
const searchIdx = `${m.file_name || ""} ${bindLabel}`;
// <tr data-search-index="${esc(searchIdx)}">
```

**改动 B**：文件名 `<td>` 变链接：

```javascript
<td style="font-weight:500;word-break:break-all">
  <a href="/api/materials/${m.id}/preview" target="_blank" rel="noopener"
     style="color:#0071e3;text-decoration:none"
     onmouseover="this.style.textDecoration='underline'"
     onmouseout="this.style.textDecoration='none'"
     title="点击在新标签页打开 / 下载">
    ${esc(m.file_name)}
  </a>
</td>
```

**改动 C**：`renderMaterials` 结尾调用 `_filterMaterialRows` 重新应用当前搜索值（tbody 重新渲染后要复用现有搜索）：

```javascript
// v2.9：tbody 重新渲染后，重新应用当前搜索值 + 刷计数
const searchInput = document.getElementById("tw-material-search");
_filterMaterialRows(searchInput ? searchInput.value : "");
```

**改动 D**：新增一次性事件绑定 `_initMaterialSearch()`，在 app.js 里跟其它 `DOMContentLoaded` 挂钩或首次进 materials tab 时调一次（用一个 module-level flag 保证只绑一次）：

```javascript
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
```

在 `renderMaterials` 开头调 `_initMaterialSearch()`（首次进 materials tab 时元素已存在于 index.html 中；idempotent）。

### 4. index.html cache-buster

`?v=2.7` → `?v=2.9`（跳过 v2.8，因为 v2.8 是后端-only）。

## 涉及文件

| 文件 | 变更 |
|------|------|
| `compliance-agent/frontend/app.js` | `renderMaterials()` 加 filter bar HTML + `data-search-index` 属性 + 文件名 `<a>` 链接 + 事件绑定；新增 `_filterMaterialRows(kw)` 函数 |
| `compliance-agent/frontend/index.html` | `?v=2.7` → `?v=2.9` |
| `compliance-agent/README.md` | 更新日志加 v2.9 一行 |

## 部署

1. Workbench 拖两个前端文件到 `/opt/audit/compliance-agent/frontend/`
2. 浏览器 Cmd+Shift+R 强刷（frontend 是 bind mount，无需 restart nginx）

## 手工验证 checklist（无自动化测试）

- [ ] 搜索"合同" → 只显示 file_name 或绑定指标含"合同"的行
- [ ] 搜索"I-45" → 只显示当前绑到 I-45 的行
- [ ] 搜索"岗位职责" → 只显示 file_name 或绑定指标含"岗位职责"的行（v2.8 rebind 后的场景）
- [ ] 搜索空串 → 恢复显示全部
- [ ] 搜索"asdfghjkl" → 显示 "🔍 无匹配材料"空态 + 计数 "显示 0 份"
- [ ] 点击 clear 按钮 → 输入框空 + 恢复全部
- [ ] 点击 PDF 文件名 → 新 tab 打开 PDF 预览
- [ ] 点击 docx 文件名 → 触发下载
- [ ] 计数动态更新："共 N 份 · 显示 M 份"
- [ ] Filter 不影响 checkbox 选中状态（选中一行后搜索 → 该行隐藏但仍选中；清空搜索后恢复显示，checkbox 仍勾选）
- [ ] Filter 不影响绑定下拉的功能（能过滤显示的行仍能改绑）

## 风险 & 缓解

| 风险 | 概率 | 缓解 |
|---|---|---|
| Filter 隐藏行破坏 batch delete 选中语义 | 低 | 明确文档"搜索只影响显示，不影响 checkbox 选中状态" |
| 大量材料时 `input` 事件每次全扫 rows 慢 | 低 | 几十到几百量级 DOM 遍历 <10ms；如未来到千级再加 debounce |
| 文件名极长撑破列宽 | 低 | 加 `word-break: break-all` |
| Office 文件点了没反应（用户以为坏了） | 中 | 加 `title="点击在新标签页打开 / 下载"` 提示 |

## 回滚

git revert 1 个 commit → cp 老 app.js/index.html 回容器 → 浏览器 F5。
