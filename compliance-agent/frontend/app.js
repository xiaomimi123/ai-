// ============================================================
// 内控评价智能审核系统 · 苹果系统级 UI
// ============================================================

const API = "/api";
const TOKEN_KEY = "audit.token";

const State = {
  user: null,
  roleLabel: "",
  units: [],
  indicators: [],
  tasks: [],
  taskId: null,
  taskDetail: null,
  subtab: "overview",
  findingFilter: "all",
  activeFindingId: null,
  consoleTab: "llm",
};

// ============================================================
// Helpers
// ============================================================
function getToken() { return localStorage.getItem(TOKEN_KEY) || ""; }
function setToken(t) { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); }

async function api(path, opts = {}) {
  const headers = new Headers(opts.headers || {});
  const tok = getToken();
  if (tok) headers.set("Authorization", "Bearer " + tok);
  const r = await fetch(API + path, { ...opts, headers });
  if (r.status === 401) {
    setToken(""); State.user = null;
    showLogin("登录已失效，请重新登录");
    throw new Error("401");
  }
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    let msg = text;
    try { msg = JSON.parse(text).detail || text; } catch {}
    throw new Error(msg || r.statusText);
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.blob();
}

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstChild;
}
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function fmtTime(s) {
  if (!s) return "—";
  try {
    // 后端 datetime.utcnow().isoformat() 输出形如 "2026-06-04T08:03:00"
    // 不带时区后缀，JS 默认按本地时区解析会差 8 小时；这里补 "Z" 强制按 UTC 解析
    // 再由 toLocaleString 转成浏览器本地时区显示（中国大陆即 +08:00）
    let iso = String(s);
    if (!/[zZ]|[+-]\d{2}:?\d{2}$/.test(iso)) {
      iso = iso + "Z";
    }
    return new Date(iso).toLocaleString("zh-CN", {
      timeZone: "Asia/Shanghai",
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
    });
  } catch { return s; }
}
function pad(n) { return String(n).padStart(2, "0"); }
function initial(s) { return (s || "?").slice(0, 1).toUpperCase(); }

// ============================================================
// SVG 图标库（替代 emoji，保持苹果风格）
// ============================================================
function icon(name, size = 14) {
  const s = size;
  const paths = {
    view:     `<path d="M1 8s2.5-5 7-5 7 5 7 5-2.5 5-7 5-7-5-7-5z" stroke="currentColor" stroke-width="1.5" fill="none"/><circle cx="8" cy="8" r="2.5" stroke="currentColor" stroke-width="1.5" fill="none"/>`,
    download: `<path d="M8 2v9 M5 8l3 3 3-3 M3 13h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>`,
    upload:   `<path d="M8 13V4 M5 7l3-3 3 3 M3 13h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>`,
    delete:   `<path d="M3 4h10 M5.5 4V2.5h5V4 M5 4l.5 9h5l.5-9 M6.5 6.5v4 M9.5 6.5v4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" fill="none"/>`,
    key:      `<path d="M10.5 8.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z M8.8 7.7L3 13.5 4 14.5 6.5 12 5 10.5l1.5-1.5L8 10.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" fill="none"/>`,
    pause:    `<rect x="4.5" y="3" width="2.5" height="10" stroke="currentColor" stroke-width="1.4" fill="none" rx="0.5"/><rect x="9" y="3" width="2.5" height="10" stroke="currentColor" stroke-width="1.4" fill="none" rx="0.5"/>`,
    play:     `<path d="M4 3v10l9-5z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" fill="none"/>`,
    arrow:    `<path d="M5 3l5 5-5 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>`,
    folder:   `<path d="M2 4a1 1 0 0 1 1-1h3l2 2h5a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V4z" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linejoin="round"/>`,
    plus:     `<path d="M8 3v10 M3 8h10" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>`,
    minus:    `<path d="M3 8h10" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>`,
    check:    `<path d="M3 8l3.5 3.5L13 5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" fill="none"/>`,
    close:    `<path d="M4 4l8 8 M12 4l-8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>`,
    file:     `<path d="M4 2h6l2 2v10H4z M10 2v3h3" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linejoin="round"/>`,
    docs:     `<path d="M4 2h5l3 3v9H4z M9 2v3h3 M6 8h4 M6 10h4" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linejoin="round" stroke-linecap="round"/>`,
    refresh:  `<path d="M2 8a6 6 0 0 1 10-4.3 M14 2v4h-4 M14 8a6 6 0 0 1-10 4.3 M2 14v-4h4" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`,
  };
  const p = paths[name];
  if (!p) return "";
  return `<svg width="${s}" height="${s}" viewBox="0 0 16 16" style="vertical-align:-2px">${p}</svg>`;
}

// 把所有 <span data-icon="X"> 替换为对应 SVG（DOM ready + 动态内容均覆盖）
function renderIcons(root = document) {
  root.querySelectorAll("span[data-icon]:not([data-icon-ready])").forEach(el => {
    const name = el.dataset.icon;
    const size = parseInt(el.dataset.size || "14");
    el.innerHTML = icon(name, size);
    el.dataset.iconReady = "1";
  });
}
// 初始 + 每次 DOM 更新后再扫一次（用 MutationObserver 兜底）
document.addEventListener("DOMContentLoaded", () => renderIcons());
new MutationObserver(() => renderIcons()).observe(
  document.body, { childList: true, subtree: true }
);

function toast(msg, kind = "info") {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "toast" + (kind === "success" ? " toast-success" : kind === "error" ? " toast-error" : "");
  t.classList.remove("hidden");
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => t.classList.add("hidden"), 3000);
}

// ============================================================
// Routing
// ============================================================
const ROUTES = ["dashboard", "tasks", "regulations", "indicators", "check-items", "console"];

function parseHash() {
  const h = (location.hash || "#/dashboard").replace(/^#\/?/, "");
  const [path, query = ""] = h.split("?");
  const qp = new URLSearchParams(query);
  const m = path.match(/^tasks\/(\d+)$/);
  if (m) return {
    route: "task-workspace",
    params: { id: parseInt(m[1]), sub: qp.get("sub") || "overview" }
  };
  const route = ROUTES.includes(path) ? path : "dashboard";
  return { route, params: { tab: qp.get("tab") } };
}

function navigate(hash) {
  if (location.hash !== hash) location.hash = hash;
  else handleRoute();
}

// 路由权限表：列出 route → 允许的角色（不在表中 = 所有登录用户）
const ROUTE_GUARDS = {
  "console":      ["super_admin"],
  "regulations":  ["super_admin", "auditor"],
  "indicators":   ["super_admin", "auditor"],
  "check-items":  ["super_admin", "auditor"],
};

function isRouteAllowed(route, user) {
  const allow = ROUTE_GUARDS[route];
  if (!allow) return true;
  return user && allow.includes(user.role);
}

async function handleRoute() {
  const { route, params } = parseHash();

  // 路由级权限守卫：禁止非授权角色访问敏感路由
  if (!isRouteAllowed(route, State.user)) {
    toast("无权访问此页面，需要更高权限", "error");
    // 重定向回工作台，避免无限循环
    if (location.hash !== "#/dashboard") {
      location.replace("#/dashboard");
      return;
    }
  }

  document.querySelectorAll(".page-section").forEach(s => s.classList.add("hidden"));
  document.querySelectorAll(".nav-link").forEach(b => {
    b.classList.toggle("active", b.dataset.route === route);
  });

  if (route === "task-workspace") {
    document.getElementById("page-task-workspace").classList.remove("hidden");
    document.querySelectorAll('[data-route="tasks"]').forEach(b => b.classList.add("active"));
    State.subtab = params.sub || "overview";
    document.querySelectorAll(".subnav-item").forEach(x =>
      x.classList.toggle("active", x.dataset.subtab === State.subtab));
    await loadTaskWorkspace(params.id);
    return;
  }

  document.getElementById(`page-${route}`).classList.remove("hidden");

  switch (route) {
    case "dashboard": await loadDashboard(); break;
    case "tasks": await loadTasks(); break;
    case "regulations": await loadRegulations(); break;
    case "indicators": await loadIndicators(); break;
    case "check-items": await loadCheckItems(); break;
    case "console":
      if (params.tab) State.consoleTab = params.tab;
      setConsoleTab(State.consoleTab);
      break;
  }
}

window.addEventListener("hashchange", handleRoute);
document.querySelectorAll(".nav-link").forEach(btn => {
  btn.addEventListener("click", () => navigate("#/" + btn.dataset.route));
});

// ============================================================
// 工作台
// ============================================================
async function loadDashboard() {
  try {
    const [health, units, tasks, indicators, items] = await Promise.all([
      api("/health"), api("/units"), api("/tasks"),
      api("/indicators"), api("/check-items"),
    ]);
    State.units = units; State.tasks = tasks; State.indicators = indicators;

    const inProgress = tasks.filter(t => t.status !== "finalized").length;
    const statsBox = document.getElementById("dash-stats");
    statsBox.innerHTML = `
      ${statCard("被检查单位", units.length, "已纳入复核", 1)}
      ${statCard("核查任务", tasks.length, `进行中 ${inProgress}`, 2)}
      ${statCard("评价指标", indicators.length, "已入库", 3)}
      ${statCard("问题清单", items.length, "AI 考题", 4)}
    `;

    const pending = tasks.filter(t => t.status === "ai_done");
    const pendingBox = document.getElementById("dash-pending");
    if (!pending.length) {
      pendingBox.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-glyph">✓</div>
          暂无待复核任务
        </div>`;
    } else {
      pendingBox.innerHTML = pending.slice(0, 6).map(t => {
        const unit = units.find(u => u.id === t.unit_id);
        const stats = parseStats(t.stats);
        return `
          <div class="task-pending-item" onclick="navigate('#/tasks/${t.id}?sub=findings')"
               style="padding:12px 0;border-bottom:1px solid var(--divider);cursor:pointer;display:flex;justify-content:space-between;align-items:center;gap:12px">
            <div style="flex:1;min-width:0">
              <div style="font-weight:600;font-size:14px">${esc(t.name)}</div>
              <div class="text-sm text-muted mt-2">${esc(unit ? unit.name : "—")} · ${t.eval_year} 年度</div>
              <div class="flex gap-2 mt-2" style="flex-wrap:wrap">
                <span class="badge badge-blue">AI 初核完成</span>
                <span class="text-xs text-faint">${stats.findings_total || 0} 条疑点待复核</span>
              </div>
            </div>
            <span class="row-arrow">→</span>
          </div>`;
      }).join("");
    }

    const recentBox = document.getElementById("dash-recent");
    if (!tasks.length) {
      recentBox.innerHTML = `<div class="empty-state"><div class="empty-state-glyph">⊙</div>暂无任务</div>`;
    } else {
      recentBox.innerHTML = tasks.slice(0, 6).map(t => {
        const unit = units.find(u => u.id === t.unit_id);
        return `
          <div onclick="navigate('#/tasks/${t.id}')"
               style="padding:12px 0;border-bottom:1px solid var(--divider);cursor:pointer;display:flex;justify-content:space-between;align-items:center;gap:12px">
            <div style="flex:1;min-width:0">
              <div class="flex items-center gap-2" style="margin-bottom:4px">
                <span class="code-id">#${pad(t.id)}</span>
                ${statusBadge(t.status)}
              </div>
              <div style="font-size:13px;font-weight:500">${esc(unit ? unit.name : "—")}</div>
              <div class="text-sm text-muted mt-2">${esc(t.summary || t.name)}</div>
            </div>
            <span class="row-arrow">→</span>
          </div>`;
      }).join("");
    }

    document.getElementById("dash-system-status").textContent =
      `${health.app} · LLM ${health.llm_default_provider} · 向量库 ${health.vector_store}`;
  } catch (e) { console.error(e); }
}

function parseStats(raw) {
  try { return JSON.parse(raw || "{}"); } catch { return {}; }
}

function statCard(label, value, note, idx) {
  return `
    <div class="card-stat fade-in fade-in-${idx}">
      <div class="stat-label">${esc(label)}</div>
      <div class="stat-value">${value}</div>
      <div class="stat-note">${esc(note)}</div>
    </div>`;
}

function statusBadge(status) {
  const map = {
    pending:    ['badge badge-gray',   '待开始'],
    running:    ['badge badge-orange', '核查中'],
    ai_done:    ['badge badge-blue',   'AI 初核'],
    reviewing:  ['badge badge-orange', '复核中'],
    finalized:  ['badge badge-green',  '已定稿'],
    archived:   ['badge badge-gray',   '已归档'],
    failed:     ['badge badge-red',    '失败'],
  };
  const [cls, label] = map[status] || ['badge badge-gray', status];
  return `<span class="${cls}">${label}</span>`;
}

document.getElementById("quick-create-task").addEventListener("click", openCreateTaskModal);

// ============================================================
// 任务列表
// ============================================================
async function loadTasks() {
  try {
    const [units, tasks] = await Promise.all([api("/units"), api("/tasks")]);
    State.units = units; State.tasks = tasks;
    const tbody = document.getElementById("tasks-tbody");
    if (!tasks.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="empty-state">
        <div class="empty-state-glyph">⊕</div>暂无任务，点击右上角「+ 新建任务」开始。
      </td></tr>`;
      return;
    }
    tbody.innerHTML = tasks.map(t => {
      const unit = units.find(u => u.id === t.unit_id);
      return `
        <tr class="is-row-button">
          <td onclick="navigate('#/tasks/${t.id}')"><span class="code-id">#${pad(t.id)}</span></td>
          <td onclick="navigate('#/tasks/${t.id}')" style="font-weight:500">${esc(unit ? unit.name : "—")}</td>
          <td onclick="navigate('#/tasks/${t.id}')">${esc(t.name)}</td>
          <td onclick="navigate('#/tasks/${t.id}')" class="table-mono">${t.eval_year}</td>
          <td onclick="navigate('#/tasks/${t.id}')">
            ${statusBadge(t.status)}
            ${t.status === "running" && t.progress_total > 0
              ? `<span class="text-xs text-muted" style="margin-left:6px">${t.progress_current}/${t.progress_total}</span>`
              : ""}
            ${t.fast_mode ? `<span class="text-xs" style="margin-left:6px;color:#856404">[快速]</span>` : ""}
          </td>
          <td onclick="navigate('#/tasks/${t.id}')" class="text-sm text-muted">${esc(t.summary || "—")}</td>
          <td class="text-right" style="white-space:nowrap">
            <button class="btn btn-ghost btn-sm" onclick="navigate('#/tasks/${t.id}')" title="查看">${icon("arrow")}</button>
            <button class="btn btn-danger-ghost btn-sm" onclick="deleteTaskFromList(${t.id}, event)" title="删除任务">${icon("delete")}</button>
          </td>
        </tr>`;
    }).join("");
  } catch (e) { console.error(e); }
}

document.getElementById("open-create-task").addEventListener("click", openCreateTaskModal);

// ============================================================
// 创建任务模态
// ============================================================
async function openCreateTaskModal() {
  try {
    const [units, indicators] = await Promise.all([
      api("/units"),
      api("/indicators"),
    ]);
    State.units = units;
    State.indicators = indicators;
    // 给每个单位预算拼音首字母（缓存在 _initials 字段，只算一次）
    units.forEach(u => {
      if (u._initials == null) {
        u._initials = (typeof pinyinInitials === "function")
          ? pinyinInitials(u.name || "")
          : "";
      }
    });
    setupUnitSearch(units);

    // 指标多选列表
    const picker = document.getElementById("ct-indicator-list");
    const countEl = document.getElementById("ct-indicator-count");
    if (!indicators.length) {
      picker.innerHTML = `<div class="text-muted">评价指标库为空，请先在「评价指标」页导入指标。</div>`;
      countEl.textContent = "";
    } else {
      // 按分类分组
      const groups = {};
      indicators.forEach(i => {
        const key = i.category || "其它";
        if (!groups[key]) groups[key] = [];
        groups[key].push(i);
      });
      picker.innerHTML = Object.entries(groups).map(([cat, items]) => `
        <div style="margin-bottom:8px">
          <div class="text-xs text-faint" style="margin-bottom:4px;font-weight:600">${esc(cat)} (${items.length})</div>
          ${items.map(i => `
            <label style="display:flex;align-items:center;gap:6px;padding:3px 0;cursor:pointer">
              <input type="checkbox" name="ct-indicator" value="${i.id}" />
              <span class="code-id" style="min-width:60px">${esc(i.indicator_code)}</span>
              <span style="font-size:13px">${esc(i.name)}</span>
              <span class="text-xs text-faint">满分 ${i.max_score}</span>
            </label>`).join("")}
        </div>`).join("");
      countEl.textContent = `共 ${indicators.length} 个指标可选`;
    }

    document.getElementById("create-task-modal").classList.remove("hidden");
    document.getElementById("ct-new-unit-form").classList.add("hidden");
    document.getElementById("ct-error").classList.add("hidden");
    document.getElementById("task-create-form").reset();
    document.getElementById("ct-unit-input").value = "";
    document.getElementById("ct-unit-id").value = "";
    document.getElementById("ct-unit-dropdown").classList.add("hidden");
    document.getElementById("ct-unit-tip").textContent = "";
    document.getElementById("ct-indicator-picker").classList.add("hidden");
  } catch (e) { toast(e.message, "error"); }
}

// ============================================================
// 单位搜索控件（中文模糊 + 拼音首字母 + 代码精确）
// ============================================================
const UNIT_SEARCH_LIMIT = 50;
function _unitMatches(query, units) {
  if (!query) return units.slice(0, UNIT_SEARCH_LIMIT);
  const q = query.trim();
  if (!q) return units.slice(0, UNIT_SEARCH_LIMIT);
  const qUpper = q.toUpperCase();
  const out = [];
  for (const u of units) {
    if (u.name && u.name.includes(q)) { out.push(u); }
    else if (u.code && u.code.includes(q)) { out.push(u); }
    else if (u._initials && u._initials.includes(qUpper)) { out.push(u); }
    if (out.length >= UNIT_SEARCH_LIMIT) break;
  }
  return out;
}

function _renderUnitDropdown(units, activeIdx, total) {
  const dd = document.getElementById("ct-unit-dropdown");
  if (!units.length) {
    dd.innerHTML = `<div style="padding:12px;color:#999">没找到匹配的单位</div>`;
    return;
  }
  dd.innerHTML = units.map((u, i) => `
    <div class="ct-unit-item" data-id="${u.id}" data-idx="${i}"
         style="padding:8px 12px;cursor:pointer;border-bottom:1px solid #f0f0f0;${i===activeIdx?'background:#e8f0fe':''}">
      <div style="font-size:14px">${esc(u.name)}</div>
      ${u.code ? `<div style="font-size:12px;color:#999">${esc(u.code)}</div>` : ''}
    </div>
  `).join("");
  if (total > units.length) {
    dd.innerHTML += `<div style="padding:6px 12px;font-size:12px;color:#999;text-align:center;border-top:1px solid #eee">仅显示前 ${units.length} 条，继续输入以精确匹配</div>`;
  }
}

function setupUnitSearch(units) {
  const input = document.getElementById("ct-unit-input");
  const hidden = document.getElementById("ct-unit-id");
  const dd = document.getElementById("ct-unit-dropdown");
  const tip = document.getElementById("ct-unit-tip");
  let activeIdx = -1;
  let lastMatches = [];

  function refresh() {
    const matches = _unitMatches(input.value, units);
    lastMatches = matches;
    activeIdx = matches.length ? 0 : -1;
    _renderUnitDropdown(matches, activeIdx, units.length);
    dd.classList.remove("hidden");
    tip.textContent = input.value ? `匹配 ${matches.length} 条 / 库内 ${units.length}` : `库内共 ${units.length} 个单位`;
  }

  input.oninput = () => {
    hidden.value = "";  // 改输入即失效之前的选择
    refresh();
  };
  input.onfocus = refresh;
  input.onkeydown = (ev) => {
    if (dd.classList.contains("hidden")) return;
    if (ev.key === "ArrowDown") {
      ev.preventDefault();
      activeIdx = Math.min(activeIdx + 1, lastMatches.length - 1);
      _renderUnitDropdown(lastMatches, activeIdx, units.length);
    } else if (ev.key === "ArrowUp") {
      ev.preventDefault();
      activeIdx = Math.max(activeIdx - 1, 0);
      _renderUnitDropdown(lastMatches, activeIdx, units.length);
    } else if (ev.key === "Enter") {
      if (activeIdx >= 0 && lastMatches[activeIdx]) {
        ev.preventDefault();
        const u = lastMatches[activeIdx];
        input.value = u.name;
        hidden.value = u.id;
        dd.classList.add("hidden");
        tip.textContent = `已选：${u.name}`;
      }
    } else if (ev.key === "Escape") {
      dd.classList.add("hidden");
    }
  };
  dd.onclick = (ev) => {
    const item = ev.target.closest(".ct-unit-item");
    if (!item) return;
    const id = parseInt(item.dataset.id, 10);
    const u = units.find(x => x.id === id);
    if (!u) return;
    input.value = u.name;
    hidden.value = u.id;
    dd.classList.add("hidden");
    tip.textContent = `已选：${u.name}`;
  };
  // 点外面收起
  document.addEventListener("click", (ev) => {
    if (!document.getElementById("ct-unit-search").contains(ev.target)) {
      dd.classList.add("hidden");
    }
  });
}

// scope radio 切换显隐指标多选区
document.querySelectorAll('input[name="scope"]').forEach(r => {
  r.addEventListener("change", ev => {
    document.getElementById("ct-indicator-picker").classList.toggle(
      "hidden", ev.target.value !== "selected"
    );
  });
});

document.getElementById("ct-new-unit").addEventListener("click", () => {
  document.getElementById("ct-new-unit-form").classList.toggle("hidden");
});

document.getElementById("ct-create-unit").addEventListener("click", async () => {
  const form = document.getElementById("task-create-form");
  const name = form.elements["new_unit_name"].value.trim();
  const code = form.elements["new_unit_code"].value.trim();
  const status = document.getElementById("ct-unit-status");
  if (!name) { status.textContent = "请输入单位名称"; return; }
  try {
    const unit = await api("/units", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, code, level: "单位" }),
    });
    // 新建的单位补进 State.units 并直接选中（搜索框 + hidden）
    unit._initials = (typeof pinyinInitials === "function") ? pinyinInitials(unit.name || "") : "";
    State.units.push(unit);
    document.getElementById("ct-unit-input").value = unit.name;
    document.getElementById("ct-unit-id").value = unit.id;
    document.getElementById("ct-unit-dropdown").classList.add("hidden");
    status.textContent = `✓ 已新建：${unit.name}`;
    form.elements["new_unit_name"].value = "";
    form.elements["new_unit_code"].value = "";
    setTimeout(() => {
      document.getElementById("ct-new-unit-form").classList.add("hidden");
      status.textContent = "";
    }, 1200);
  } catch (e) { status.textContent = "✗ " + e.message; }
});

document.querySelectorAll("[data-close-modal]").forEach(b => {
  b.addEventListener("click", () => {
    document.querySelector(b.dataset.closeModal).classList.add("hidden");
  });
});

document.getElementById("task-create-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const errBox = document.getElementById("ct-error");
  errBox.classList.add("hidden");

  if (!fd.get("unit_id")) {
    errBox.textContent = "请从下拉列表中选择一个被检查单位（仅输入文字不够，要点选或按回车确认）";
    errBox.classList.remove("hidden");
    return;
  }

  const scope = fd.get("scope") || "all";
  let selectedIds = [];
  if (scope === "selected") {
    selectedIds = Array.from(
      document.querySelectorAll('input[name="ct-indicator"]:checked')
    ).map(x => parseInt(x.value));
    if (selectedIds.length === 0) {
      errBox.textContent = "请至少勾选一个评价指标，或选择「全部指标」";
      errBox.classList.remove("hidden");
      return;
    }
  }

  const fastMode = document.getElementById("ct-fast-mode")?.checked || false;
  try {
    const task = await api("/tasks", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        unit_id: parseInt(fd.get("unit_id")),
        name: fd.get("name"),
        eval_year: parseInt(fd.get("eval_year")),
        scope,
        selected_indicator_ids: selectedIds,
        fast_mode: fastMode,
      }),
    });
    document.getElementById("create-task-modal").classList.add("hidden");
    const scopeLbl = scope === "all" ? "全部指标" : `${selectedIds.length} 个指标`;
    const modeLbl = fastMode ? " · 快速模式" : "";
    toast(`✓ 任务 #${pad(task.id)} 已创建（${scopeLbl}${modeLbl}）`, "success");
    navigate(`#/tasks/${task.id}`);
  } catch (e) {
    errBox.textContent = e.message;
    errBox.classList.remove("hidden");
  }
});

// ============================================================
// 任务工作台
// ============================================================
async function loadTaskWorkspace(taskId) {
  State.taskId = taskId;
  try {
    const [detail, indicators] = await Promise.all([
      api(`/tasks/${taskId}`), api("/indicators"),
    ]);
    State.taskDetail = detail;
    State.indicators = indicators;

    // 已核查的任务预拉 worksheet（用于 5 维度统计）
    State.worksheet = null;
    if (["ai_done", "reviewing", "finalized", "archived"].includes(detail.task.status)) {
      try {
        State.worksheet = await api(`/tasks/${taskId}/worksheet`);
      } catch { /* 底稿不存在则忽略 */ }
    }

    document.getElementById("tw-task-id").textContent = `任务 #${pad(detail.task.id)}`;
    document.getElementById("tw-title").textContent = detail.task.name;
    document.getElementById("tw-meta").innerHTML =
      `${esc(detail.unit.name)} · ${detail.task.eval_year} 年度 · ${statusBadge(detail.task.status)}`;

    document.getElementById("tw-count-materials").textContent = detail.materials.length;
    document.getElementById("tw-count-findings").textContent = detail.findings.length;

    renderTaskActions(detail.task);
    renderProgress(detail.task);
    renderSubtab();
    maybeStartProgressPolling(detail.task);
  } catch (e) { toast(e.message, "error"); }
}

function renderProgress(task) {
  const box = document.getElementById("tw-progress");
  if (!box) return;
  if (task.status !== "running") { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  const cur = task.progress_current || 0;
  const total = task.progress_total || 0;
  const pct = total > 0 ? Math.min(100, Math.round((cur / total) * 100)) : 0;
  document.getElementById("tw-progress-cur").textContent = cur;
  document.getElementById("tw-progress-total").textContent = total || "?";
  document.getElementById("tw-progress-fill").style.width = pct + "%";
  document.getElementById("tw-progress-now").textContent = task.progress_text || "准备中…";
  const modeEl = document.getElementById("tw-progress-mode");
  modeEl.textContent = task.fast_mode ? "快速模式" : "";
  modeEl.style.display = task.fast_mode ? "" : "none";
}

let _progressTimer = null;
function stopProgressPolling() {
  if (_progressTimer) { clearInterval(_progressTimer); _progressTimer = null; }
}
function maybeStartProgressPolling(task) {
  stopProgressPolling();
  if (task.status !== "running") return;
  const taskId = task.id;
  _progressTimer = setInterval(async () => {
    if (State.taskId !== taskId) { stopProgressPolling(); return; }
    try {
      const detail = await api(`/tasks/${taskId}`);
      State.taskDetail = detail;
      renderProgress(detail.task);
      document.getElementById("tw-meta").innerHTML =
        `${esc(detail.unit.name)} · ${detail.task.eval_year} 年度 · ${statusBadge(detail.task.status)}`;
      if (detail.task.status !== "running") {
        stopProgressPolling();
        // 状态变了 → 重渲整个工作台拿底稿、findings 等
        loadTaskWorkspace(taskId);
      }
    } catch (e) {
      console.warn("progress poll failed:", e.message);
    }
  }, 3000);
}
// 离开任务页时停轮询
window.addEventListener("hashchange", () => {
  if (!location.hash.startsWith("#/tasks/")) stopProgressPolling();
});

function renderTaskActions(task) {
  const box = document.getElementById("tw-actions");
  const acts = [];
  if (task.status === "ai_done" || task.status === "reviewing") {
    acts.push(`<button class="btn btn-success" onclick="finalizeTask()">${icon("check")} <span>完成复核，定稿</span></button>`);
  }
  // V3.1：暂时隐藏「导出 Word 报告」入口（用户当前主要走 Excel 底稿流程）
  // 接口仍保留，恢复时打开下面这段即可：
  // if (["ai_done", "reviewing", "finalized", "archived"].includes(task.status)) {
  //   acts.push(`<button class="btn btn-secondary" onclick="downloadTaskReport()">${icon("download")} <span>导出 Word 报告</span></button>`);
  // }
  acts.push(`<button class="btn btn-danger-ghost" onclick="deleteCurrentTask()" title="删除任务">${icon("delete")} <span>删除任务</span></button>`);
  box.innerHTML = acts.join("");
}

window.downloadTaskReport = async function() {
  if (!State.taskId) return;
  toast("正在生成 Word 报告…");
  try {
    const tok = getToken();
    const r = await fetch(`${API}/tasks/${State.taskId}/report`, {
      headers: { "Authorization": "Bearer " + tok },
    });
    if (!r.ok) {
      const text = await r.text();
      throw new Error(text || `HTTP ${r.status}`);
    }
    const blob = await r.blob();
    // 触发浏览器下载
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    // 从 Content-Disposition 解析文件名（含 RFC 5987 中文）
    const cd = r.headers.get("Content-Disposition") || "";
    let fname = `report_${State.taskId}.docx`;
    const m = cd.match(/filename\*=UTF-8''([^;]+)/);
    if (m) fname = decodeURIComponent(m[1]);
    a.download = fname;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast("✓ 报告已下载", "success");
  } catch (e) {
    toast(e.message || "报告下载失败", "error");
  }
};

window.finalizeTask = async function() {
  if (!confirm("将任务定稿，之后只读？")) return;
  try {
    await api(`/tasks/${State.taskId}/finalize`, { method: "POST" });
    toast("✓ 已定稿", "success");
    loadTaskWorkspace(State.taskId);
  } catch (e) { toast(e.message, "error"); }
};

window.deleteTaskFromList = async function(taskId, ev) {
  if (ev) { ev.stopPropagation(); ev.preventDefault(); }
  if (!confirm(`确定删除任务 #${pad(taskId)}？\n\n会一并清理：\n· 任务下的所有材料文件\n· 所有 AI 核查发现（Finding）\n\n此操作不可恢复。`)) return;
  try {
    await api(`/tasks/${taskId}`, { method: "DELETE" });
    toast(`✓ 任务 #${pad(taskId)} 已删除`, "success");
    loadTasks();
  } catch (e) { toast(e.message, "error"); }
};

window.deleteCurrentTask = async function() {
  if (!State.taskId) return;
  if (!confirm(`确定删除当前任务？\n\n会一并清理：\n· 任务下的所有材料文件\n· 所有 AI 核查发现\n\n此操作不可恢复。`)) return;
  try {
    await api(`/tasks/${State.taskId}`, { method: "DELETE" });
    toast(`✓ 任务已删除`, "success");
    navigate("#/tasks");
  } catch (e) { toast(e.message, "error"); }
};

document.getElementById("back-to-tasks").addEventListener("click", () => navigate("#/tasks"));

document.querySelectorAll('.subnav-item').forEach(b => {
  b.addEventListener("click", () => {
    State.subtab = b.dataset.subtab;
    document.querySelectorAll('.subnav-item').forEach(x => x.classList.toggle("active", x === b));
    renderSubtab();
  });
});

function renderSubtab() {
  document.querySelectorAll('.subtab-panel').forEach(p => p.classList.add("hidden"));
  document.getElementById("tw-" + State.subtab).classList.remove("hidden");
  if (State.subtab === "overview") renderOverview();
  if (State.subtab === "materials") renderMaterials();
  if (State.subtab === "findings") renderFindings();
  if (State.subtab === "review") loadMaterialReview();
  if (State.subtab === "worksheet") loadWorksheet();
}

// 7 对复选框标签
// 新底稿模板 5 对 10 项（与后端 FLAG_PAIRS 同步）
const WS_FLAG_PAIRS = [
  ["real",       "材料真实可靠",     "fake",          "材料涉嫌造假"],
  ["complete",   "材料完整",         "incomplete",    "材料不完整"],
  ["compliant",  "材料合法合规",     "non_compliant", "可能违法违规"],
  ["unique",     "未跨单位重复",     "duplicate",     "跨单位重复"],
  ["match_high", "材料匹配度高",     "match_low",     "材料匹配度低"],
];

function renderFlagBadges(flagsObj) {
  return WS_FLAG_PAIRS.map(([pk, pl, nk, nl]) => {
    const pos = !!flagsObj[pk], neg = !!flagsObj[nk];
    // 正向通过用绿、负向命中用红，未判定用灰
    let cls = "ws-flag-na", label = pl;
    if (pos && !neg) { cls = "ws-flag-ok"; label = pl; }
    else if (!pos && neg) { cls = "ws-flag-bad"; label = nl; }
    return `<span class="ws-flag ${cls}">${label}</span>`;
  }).join("");
}

// ============================================================
// 材料审核（V4）
// ============================================================
async function loadMaterialReview() {
  const summary = document.getElementById("mr-summary");
  summary.innerHTML = `<span class="text-muted">加载中…</span>`;
  let data;
  try {
    data = await api(`/tasks/${State.taskId}/material-review`);
  } catch (e) {
    summary.innerHTML = `<div class="callout callout-error">加载失败：${esc(e.message)}</div>`;
    return;
  }
  State.materialReview = data;
  document.getElementById("tw-count-review").textContent =
    (data.duplicates.same_task_groups.length + data.duplicates.cross_task_pairs.length) || "";

  renderMrSummary(data);
  renderMrDuplicates(data.duplicates);
  renderMrContent(data.content_review);
  renderMrMatching(data.matching, data.bind_sources);
  renderMrTimeline(data.timeline);
}

function renderMrSummary(data) {
  const summary = document.getElementById("mr-summary");
  const dup = data.duplicates.same_task_groups.length + data.duplicates.cross_task_pairs.length;
  const m = data.matching;
  const lowMatch = m.low_match_materials.length;
  summary.innerHTML = `
    <span><strong>${m.total_materials}</strong> 份材料</span>
    <span>已绑定 <strong>${m.bound}</strong> / 未绑定 <strong style="color:${m.unbound > 0 ? 'var(--brand-red)' : 'inherit'}">${m.unbound}</strong></span>
    <span>指标覆盖 <strong>${m.covered_indicators}/${m.target_indicators}</strong>（缺 <strong>${m.uncovered_indicators}</strong> 项）</span>
    <span>重复 <strong style="color:${dup > 0 ? 'var(--brand-red)' : '#1f7a3e'}">${dup}</strong> 组</span>
    <span>匹配度低 <strong style="color:${lowMatch > 0 ? '#d97706' : 'inherit'}">${lowMatch}</strong> 份</span>
  `;
}

function renderMrDuplicates(dup) {
  const box = document.getElementById("mr-dup-content");
  const cntEl = document.getElementById("mr-dup-count");
  const sameGroups = dup.same_task_groups || [];
  const crossPairs = dup.cross_task_pairs || [];
  cntEl.textContent = `同任务 ${sameGroups.length} 组 · 跨任务 ${crossPairs.length} 对`;

  if (sameGroups.length === 0 && crossPairs.length === 0) {
    box.innerHTML = `<div class="callout callout-success">✓ 未检出重复材料</div>`;
    return;
  }

  let html = "";
  if (sameGroups.length > 0) {
    html += `<div class="text-sm" style="font-weight:600;margin-bottom:8px">同任务内重复（${sameGroups.length} 组）：</div>`;
    html += sameGroups.map((g, idx) => `
      <div style="border:1px solid #f2c0c2;background:#fdecec;border-radius:8px;padding:12px;margin-bottom:10px">
        <div class="text-sm mb-2"><strong>组 ${idx + 1}</strong> · ${g.count} 份完全相同 · hash <code style="font-size:10px;color:#888">${g.content_hash.slice(0, 12)}…</code></div>
        ${g.materials.map((m, i) => `
          <div class="flex justify-between items-center" style="padding:6px 0;${i > 0 ? 'border-top:1px dashed #f2c0c2' : ''}">
            <div class="text-sm">
              <span class="code-id">#${pad(m.id)}</span>
              ${esc(m.file_name)}
              <span class="text-xs text-muted">${m.uploaded_at ? fmtTime(m.uploaded_at) : ''}</span>
            </div>
            <button class="btn btn-secondary btn-sm" onclick="mergeDupKeep('${g.content_hash}', ${m.id})">
              保留此份 + 合并其它
            </button>
          </div>
        `).join("")}
      </div>
    `).join("");
  }
  if (crossPairs.length > 0) {
    html += `<div class="text-sm" style="font-weight:600;margin-top:16px;margin-bottom:8px">跨任务材料重复（${crossPairs.length} 对）：</div>`;
    html += crossPairs.map(p => `
      <div style="border:1px solid #fde4a6;background:#fff8e1;border-radius:8px;padding:10px;margin-bottom:8px">
        <div class="text-sm">
          <span class="code-id">#${pad(p.my_material.id)}</span> ${esc(p.my_material.file_name)}
          <span class="text-muted">↔</span>
          <a href="#/tasks/${p.other_task_id}" class="text-blue">任务 #${p.other_task_id} ${esc(p.other_task_name)}</a>
        </div>
        <div class="text-xs text-muted" style="margin-top:4px">疑似跨单位共享材料或抄送</div>
      </div>
    `).join("");
  }
  box.innerHTML = html;
}

window.mergeDupKeep = async function(contentHash, keepId) {
  if (!confirm(`确定保留 #${pad(keepId)}，删除该组其它重复材料？`)) return;
  try {
    const res = await api(`/tasks/${State.taskId}/materials/merge-duplicates`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content_hash: contentHash, keep_material_id: keepId }),
    });
    toast(`✓ 已合并：保留 #${pad(res.kept)}，删除 ${res.removed} 份`, "success");
    await loadMaterialReview();
    // 也刷新材料列表
    await loadTaskWorkspace(State.taskId);
    State.subtab = "review";
    document.querySelectorAll('.subnav-item').forEach(x =>
      x.classList.toggle("active", x.dataset.subtab === "review"));
    renderSubtab();
  } catch (e) { toast(e.message, "error"); }
};

function renderMrContent(rows) {
  const tbody = document.getElementById("mr-content-tbody");
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty-state">尚无材料</td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map(r => {
    const ke = r.key_elements || {};
    const flags = r.flags || {};
    const seal = ke.has_official_seal ? `<span style="color:#1f7a3e">✓</span>` : `<span style="color:#b8262b">✗</span>`;
    const sig = ke.has_signature ? `<span style="color:#1f7a3e">✓</span>` : `<span style="color:#b8262b">✗</span>`;
    const year = ke.issue_year ? `<span class="tag" style="font-size:11px">${ke.issue_year}</span>` : `<span class="text-muted">—</span>`;
    const docno = ke.document_number ? `<span class="text-xs" style="font-family:monospace">${esc(ke.document_number)}</span>` : `<span class="text-muted">—</span>`;
    // 5 维度 chip
    const chips = [];
    if (flags.real) chips.push(`<span class="ws-flag ws-flag-ok">真实</span>`);
    if (flags.fake) chips.push(`<span class="ws-flag ws-flag-bad">涉嫌造假</span>`);
    if (flags.incomplete) chips.push(`<span class="ws-flag ws-flag-bad">不完整</span>`);
    if (flags.non_compliant) chips.push(`<span class="ws-flag ws-flag-bad">违法违规</span>`);
    if (flags.duplicate) chips.push(`<span class="ws-flag ws-flag-bad">重复</span>`);
    if (flags.match_low) chips.push(`<span class="ws-flag ws-flag-bad">匹配度低</span>`);
    if (chips.length === 0) chips.push(`<span class="text-muted">—</span>`);
    const ind = r.indicator_code ? `<span class="code-id">${esc(r.indicator_code)}</span> ${esc((r.indicator_name || "").slice(0, 8))}` : `<span class="text-muted">未绑定</span>`;
    return `
      <tr>
        <td><span class="code-id">#${pad(r.material_id)}</span></td>
        <td class="text-sm">${esc(r.file_name)}</td>
        <td class="text-xs">${ind}</td>
        <td class="text-center">${seal}</td>
        <td class="text-center">${sig}</td>
        <td class="text-center">${year}</td>
        <td>${docno}</td>
        <td>${chips.join(" ")}</td>
      </tr>
    `;
  }).join("");
}

function renderMrMatching(matching, bindSources) {
  const box = document.getElementById("mr-matching");
  const m = matching;
  const bs = bindSources || {};
  const total = (bs.by_keyword || 0) + (bs.by_ai || 0) + (bs.by_manual || 0) + (bs.unbound || 0);
  const pct = v => total ? Math.round((v / total) * 100) : 0;
  const bar = (color, value) => `<div style="background:${color};height:8px;width:${pct(value)}%;display:inline-block;vertical-align:middle"></div>`;

  let uncoveredHtml = "";
  if (m.uncovered_list.length) {
    uncoveredHtml = `
      <div style="margin-top:12px">
        <div class="text-sm" style="font-weight:600;margin-bottom:6px">缺材料指标（共 ${m.uncovered_indicators} 项，显示前 ${m.uncovered_list.length}）：</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          ${m.uncovered_list.map(i => `<span class="ws-flag ws-flag-na">${esc(i.indicator_code)} ${esc((i.name || "").slice(0, 10))}</span>`).join("")}
        </div>
      </div>
    `;
  }

  let lowMatchHtml = "";
  if (m.low_match_materials.length) {
    lowMatchHtml = `
      <div style="margin-top:12px">
        <div class="text-sm" style="font-weight:600;margin-bottom:6px;color:#d97706">匹配度低的材料（${m.low_match_materials.length}）：</div>
        ${m.low_match_materials.map(x => `
          <div class="text-sm" style="padding:4px 0">
            <span class="code-id">#${pad(x.material_id)}</span> ${esc(x.file_name)}
            → 当前绑定 <span class="code-id">${esc(x.indicator_code || "")}</span> ${esc((x.indicator_name || "").slice(0, 10))}
          </div>
        `).join("")}
      </div>
    `;
  }

  box.innerHTML = `
    <div class="text-sm" style="font-weight:600;margin-bottom:6px">绑定来源分布：</div>
    <div style="font-size:12px;line-height:1.8">
      <div>关键词匹配 ${bs.by_keyword || 0} 份 (${pct(bs.by_keyword || 0)}%) <span style="display:inline-block;background:#dde6f4;width:100%;max-width:300px;height:8px;border-radius:2px;vertical-align:middle"><span style="display:block;background:#0071e3;width:${pct(bs.by_keyword || 0)}%;height:100%"></span></span></div>
      <div>AI 阅读匹配 ${bs.by_ai || 0} 份 (${pct(bs.by_ai || 0)}%)</div>
      <div>手动指定 ${bs.by_manual || 0} 份 (${pct(bs.by_manual || 0)}%)</div>
      ${(bs.unbound || 0) > 0 ? `<div style="color:#d97706">未绑定 ${bs.unbound} 份 (${pct(bs.unbound)}%)</div>` : ""}
    </div>
    <div style="margin-top:10px;font-size:12px">
      指标覆盖度：<strong>${m.covered_indicators}</strong> / ${m.target_indicators} 项（覆盖率 ${m.target_indicators ? Math.round(m.covered_indicators / m.target_indicators * 100) : 0}%）
    </div>
    ${uncoveredHtml}
    ${lowMatchHtml}
  `;
}

function renderMrTimeline(events) {
  const box = document.getElementById("mr-timeline");
  if (!events.length) {
    box.innerHTML = `<div class="empty-state">暂无操作记录</div>`;
    return;
  }
  box.innerHTML = events.map(e => `
    <div class="flex items-start" style="padding:8px 0;border-bottom:1px solid var(--divider);font-size:13px">
      <div style="flex:0 0 130px;color:var(--text-secondary)">${e.at ? fmtTime(e.at) : ''}</div>
      <div style="flex:0 0 140px">${esc(e.label)}</div>
      <div style="flex:1;color:var(--text-secondary)">${esc(e.detail || '')}</div>
      <div style="flex:0 0 80px;text-align:right;color:var(--text-tertiary);font-size:11px">${esc(e.user || '')}</div>
    </div>
  `).join("");
}

// V3.1：从该指标下绑定材料的 key_elements 汇总「签章年度文号」
// 每份材料一行：公章✓ 签字✗ 2025 · 川师校〔2025〕86 号
function formatSignatureYearDocno(indicatorId) {
  if (!indicatorId || !State.taskDetail?.materials) return "";
  const mats = State.taskDetail.materials.filter(m => m.indicator_id === indicatorId);
  if (!mats.length) return `<span class="text-muted">未绑定材料</span>`;
  const lines = mats.map(m => {
    let ke = {};
    try { ke = JSON.parse(m.key_elements || "{}"); } catch {}
    const seal = ke.has_official_seal
      ? `<span style="color:#1f7a3e">公章✓</span>`
      : `<span style="color:#b8262b">公章✗</span>`;
    const sig = ke.has_signature
      ? `<span style="color:#1f7a3e">签字✓</span>`
      : `<span style="color:#b8262b">签字✗</span>`;
    const year = ke.issue_year ? String(ke.issue_year) : `<span style="color:#888">未识别</span>`;
    const docno = (ke.document_number || "").trim();
    const docPart = docno ? escapeHtml(docno) : `<span style="color:#888">无文号</span>`;
    return `${seal} ${sig} ${year} · ${docPart}`;
  });
  return lines.join("<br/>");
}

async function loadWorksheet() {
  const body = document.getElementById("ws-tbody");
  body.innerHTML = `<tr><td colspan="8" class="text-center text-muted" style="padding:24px">加载底稿中…</td></tr>`;
  document.getElementById("ws-summary").innerHTML = "";
  document.getElementById("tw-count-worksheet").textContent = "";

  let ws;
  try {
    ws = await api(`/tasks/${State.taskId}/worksheet`);
  } catch (e) {
    body.innerHTML = `<tr><td colspan="8" class="text-center text-muted" style="padding:24px">底稿尚未生成。请先在"材料"标签页触发 AI 核查。</td></tr>`;
    return;
  }
  State.worksheet = ws;
  document.getElementById("tw-count-worksheet").textContent = ws.rows.length;

  // 用指标库 id→name/category 映射
  const inds = await api(`/indicators`);
  const indMap = new Map(inds.map(i => [i.id, i]));

  const isLocked = ws.status === "finalized";

  let totMax = 0, totBefore = 0, totAfter = 0;
  body.innerHTML = ws.rows.map(r => {
    const ind = indMap.get(r.indicator_id) || {};
    totMax += +ind.max_score || 0;
    totBefore += r.original_score || 0;
    totAfter += r.audited_score || 0;
    const flags = (() => { try { return JSON.parse(r.material_flags || "{}"); } catch { return {}; } })();
    const cat = ind.subcategory ? `${ind.category}<br/><span class="text-xs text-muted">${ind.subcategory}</span>` : (ind.category || "");
    const max = +ind.max_score || 0;

    // 可编辑：得分 number input
    const scoreInput = isLocked
      ? `<strong>${(r.audited_score ?? 0).toFixed(2)}</strong>`
      : `<input type="number" min="0" max="${max}" step="0.25" value="${(r.audited_score ?? 0).toFixed(2)}"
            class="ws-cell-edit ws-score" data-row-id="${r.id}" data-max="${max}"
            style="width:56px;text-align:center;padding:4px;font-weight:600" />`;

    // 第 10 列「签章年度文号」：只读，从该指标绑定的材料 key_elements 汇总
    const signatureCell = formatSignatureYearDocno(r.indicator_id);

    // 核查要点 / 扣分规则 = 指标定义，只读
    const audit_points = ind.audit_points || "";
    const deduct_rules = ind.deduct_rules || "";

    return `
      <tr data-row-id="${r.id}">
        <td class="text-center text-muted">${r.serial}</td>
        <td class="text-sm">${cat}</td>
        <td>${escapeHtml(ind.name || "")}</td>
        <td class="text-xs ws-cell-readonly" style="color:#5f6e89">${escapeHtml(audit_points)}</td>
        <td class="text-xs ws-cell-readonly" style="color:#5f6e89">${escapeHtml(deduct_rules)}</td>
        <td>${renderEditableFlags(flags, r.id, isLocked)}</td>
        <td class="text-center">${ind.max_score ?? ""}</td>
        <td class="text-center">${(r.original_score ?? 0).toFixed(2)}</td>
        <td class="text-center">${scoreInput}</td>
        <td class="text-xs ws-cell-readonly" style="white-space:pre-wrap;line-height:1.5">${signatureCell}</td>
      </tr>
    `;
  }).join("");

  document.getElementById("ws-summary").innerHTML = `
    <span><span class="text-muted">单位：</span><strong>${escapeHtml(ws.unit_name || "—")}</strong></span>
    <span><span class="text-muted">底稿状态：</span>${renderWorksheetStatusBadge(ws.status)}</span>
    <span><span class="text-muted">标准分合计：</span><strong>${totMax.toFixed(0)}</strong></span>
    <span><span class="text-muted">核查前合计：</span><strong>${totBefore.toFixed(2)}</strong></span>
    <span><span class="text-muted">核查后合计：</span><strong style="color:var(--brand-red)" id="ws-total-after">${totAfter.toFixed(2)}</strong></span>
    <span class="ws-save-toast" id="ws-save-toast" style="margin-left:auto"></span>
  `;
  bindWorksheetCellEditors(isLocked);
  renderWorksheetActions(ws);
}

function renderWorksheetStatusBadge(status) {
  const map = {
    draft:      ['#fff3cd', '#856404', '草稿（AI 生成）'],
    reviewing:  ['#e3f2fd', '#1565c0', '复核中'],
    finalized:  ['#e8f5ee', '#1f7a3e', '已定稿'],
  };
  const [bg, fg, label] = map[status] || ['#eee', '#666', status];
  return `<span style="background:${bg};color:${fg};padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600">${label}</span>`;
}

function renderEditableFlags(flags, rowId, locked) {
  // 7 对 14 项，每对显示为「正向 / 负向」两个 chip 可点切换
  return WS_FLAG_PAIRS.map(([pk, pl, nk, nl]) => {
    const pos = !!flags[pk], neg = !!flags[nk];
    const posClass = pos ? "ws-flag ws-flag-ok" : "ws-flag ws-flag-na";
    const negClass = neg ? "ws-flag ws-flag-bad" : "ws-flag ws-flag-na";
    const click = locked ? "" : `onclick="toggleFlag(${rowId}, '${pk}', '${nk}', '${pk}')"`;
    const clickN = locked ? "" : `onclick="toggleFlag(${rowId}, '${pk}', '${nk}', '${nk}')"`;
    const cur = locked ? "" : ";cursor:pointer";
    return `<span class="${posClass}" style="user-select:none${cur}" ${click}>${pl}</span><span class="${negClass}" style="user-select:none${cur}" ${clickN}>${nl}</span>`;
  }).join("");
}

window.toggleFlag = async function(rowId, posKey, negKey, clicked) {
  const row = State.worksheet.rows.find(r => r.id === rowId);
  if (!row) return;
  let flags = {};
  try { flags = JSON.parse(row.material_flags || "{}"); } catch {}
  // 点正向：正向 = !正向；如果点开正向则关闭负向（互斥）
  if (clicked === posKey) {
    flags[posKey] = !flags[posKey];
    if (flags[posKey]) flags[negKey] = false;
  } else {
    flags[negKey] = !flags[negKey];
    if (flags[negKey]) flags[posKey] = false;
  }
  row.material_flags = JSON.stringify(flags);
  await saveWorksheetRow(rowId, { material_flags: flags });
  await loadWorksheet();
};

let _wsSaveTimer = null;
function bindWorksheetCellEditors(locked) {
  if (locked) return;
  document.querySelectorAll(".ws-cell-edit").forEach(el => {
    el.addEventListener("blur", async () => {
      const rowId = parseInt(el.dataset.rowId);
      if (el.classList.contains("ws-score")) {
        const v = parseFloat(el.value);
        const max = parseFloat(el.dataset.max);
        if (isNaN(v) || v < 0 || v > max) {
          showSaveToast(`✗ 得分必须在 0-${max}`, "error");
          await loadWorksheet();
          return;
        }
        await saveWorksheetRow(rowId, { audited_score: v });
      } else if (el.classList.contains("ws-note")) {
        await saveWorksheetRow(rowId, { audit_finding_text: el.value });
      }
      // ws-adjust 在 V3.1 已移除（该列改为只读"签章年度文号"自动展示）
    });
  });
}

async function saveWorksheetRow(rowId, payload) {
  try {
    showSaveToast("保存中…", "info");
    const res = await api(`/tasks/${State.taskId}/worksheet/rows/${rowId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    showSaveToast("✓ 已保存", "ok");
    // 状态可能从 draft → reviewing
    if (State.worksheet && State.worksheet.status !== res.worksheet_status) {
      State.worksheet.status = res.worksheet_status;
      const node = document.querySelector("#ws-summary");
      if (node) {
        // 局部刷新状态徽章
        const span = node.children[1];
        if (span) span.innerHTML = `<span class="text-muted">底稿状态：</span>${renderWorksheetStatusBadge(res.worksheet_status)}`;
      }
      renderWorksheetActions(State.worksheet);
    }
    // 更新本地缓存
    const row = State.worksheet?.rows?.find(r => r.id === rowId);
    if (row) {
      if (payload.audited_score !== undefined) row.audited_score = res.audited_score;
      if (payload.audit_finding_text !== undefined) row.audit_finding_text = res.audit_finding_text;
      if (payload.adjustment_note !== undefined) row.adjustment_note = res.adjustment_note;
      if (payload.material_flags !== undefined) row.material_flags = res.material_flags;
      // 重算合计
      const tot = State.worksheet.rows.reduce((a, r) => a + (r.audited_score || 0), 0);
      const totalEl = document.getElementById("ws-total-after");
      if (totalEl) totalEl.textContent = tot.toFixed(2);
    }
  } catch (e) {
    showSaveToast("✗ " + e.message, "error");
  }
}

function showSaveToast(text, kind) {
  const el = document.getElementById("ws-save-toast");
  if (!el) return;
  const colors = { info: "#666", ok: "#1f7a3e", error: "#b8262b" };
  el.style.color = colors[kind] || "#666";
  el.textContent = text;
  if (_wsSaveTimer) clearTimeout(_wsSaveTimer);
  _wsSaveTimer = setTimeout(() => { el.textContent = ""; }, 2500);
}

function renderWorksheetActions(ws) {
  const bar = document.getElementById("ws-action-bar");
  if (!bar) return;
  const acts = [];
  if (ws.status !== "finalized") {
    acts.push(`<button class="btn btn-secondary btn-sm" id="ws-rebuild-btn"><span data-icon="refresh"></span><span>重新生成</span></button>`);
    acts.push(`<button class="btn btn-primary btn-sm" id="ws-download-btn"><span data-icon="download"></span><span>下载 Excel</span></button>`);
    acts.push(`<button class="btn btn-success btn-sm" onclick="finalizeWorksheet()"><span data-icon="check"></span><span>完成复核，定稿</span></button>`);
  } else {
    acts.push(`<span style="color:#1f7a3e;font-size:13px;font-weight:600">已定稿（只读）</span>`);
    acts.push(`<button class="btn btn-primary btn-sm" id="ws-download-btn"><span data-icon="download"></span><span>下载 Excel</span></button>`);
    if (State.user && State.user.role === "super_admin") {
      acts.push(`<button class="btn btn-danger-ghost btn-sm" onclick="unlockWorksheet()">解锁底稿</button>`);
    }
  }
  bar.innerHTML = acts.join("");
}

window.finalizeWorksheet = async function() {
  if (!confirm("定稿后底稿将变为只读，不能再编辑单元格。\n\n确定定稿吗？")) return;
  try {
    const ws = await api(`/tasks/${State.taskId}/worksheet/finalize`, { method: "POST" });
    State.worksheet = ws;
    toast("✓ 底稿已定稿", "success");
    await loadWorksheet();
  } catch (e) { toast(e.message, "error"); }
};

window.unlockWorksheet = async function() {
  if (!confirm("解锁后底稿可继续编辑，且原定稿状态会丢失。\n\n确定解锁吗？")) return;
  try {
    const ws = await api(`/tasks/${State.taskId}/worksheet/unlock`, { method: "POST" });
    State.worksheet = ws;
    toast("✓ 底稿已解锁，可继续编辑", "success");
    await loadWorksheet();
  } catch (e) { toast(e.message, "error"); }
};

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

document.addEventListener("click", async (e) => {
  if (e.target.closest("#ws-download-btn")) {
    const token = localStorage.getItem("audit.token");
    const url = `/api/tasks/${State.taskId}/worksheet.xlsx`;
    // 用 fetch + blob 触发下载（带 token）
    const r = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    if (!r.ok) { alert("下载失败：" + await r.text()); return; }
    const blob = await r.blob();
    const cd = r.headers.get("Content-Disposition") || "";
    const m = cd.match(/filename\*=UTF-8''([^;]+)/);
    const name = m ? decodeURIComponent(m[1]) : `worksheet_${State.taskId}.xlsx`;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
  if (e.target.closest("#ws-rebuild-btn")) {
    if (!confirm("根据当前 Finding 状态重新生成底稿？现有底稿会被覆盖。")) return;
    try {
      await api(`/tasks/${State.taskId}/worksheet/rebuild`, { method: "POST" });
      await loadWorksheet();
    } catch (err) {
      alert("重建失败：" + err.message);
    }
  }
});

function renderOverview() {
  const d = State.taskDetail;
  const findings = d.findings;
  const severity = { 高: 0, 中: 0, 低: 0 };
  findings.forEach(f => severity[f.severity] = (severity[f.severity] || 0) + 1);
  document.getElementById("tw-stats").innerHTML = `
    ${statCard("材料数", d.materials.length, "已绑定指标", 1)}
    ${statCard("高风险", severity.高, "需重点关注", 2)}
    ${statCard("中风险", severity.中, "复核确认", 3)}
    ${statCard("低风险", severity.低, "提示性", 4)}
  `;
  document.getElementById("tw-summary").textContent = d.task.summary || "尚未开始 AI 核查。";

  // 评分卡（从 task.stats 解析）
  renderScoreCard(d.task);

  // 5 大维度统一聚合：真实性 / 完整性 / 合规性 / 重复性 / 匹配性
  const dims = aggregate5Dimensions(findings, State.worksheet);
  const breakdown = document.getElementById("tw-dimension-breakdown");
  const order = ["真实性问题", "完整性问题", "合规性问题", "重复性问题", "匹配性问题"];
  const subtitles = {
    "真实性问题": "公章/签字/年度/正式性",
    "完整性问题": "要素/章节/材料缺失",
    "合规性问题": "制度/流程/法规违规",
    "重复性问题": "跨单位材料重复",
    "匹配性问题": "材料与指标不匹配",
  };
  const totalCount = Object.values(dims).reduce((a, b) => a + b, 0);
  if (totalCount === 0) {
    breakdown.innerHTML = `<div class="empty-state" style="grid-column:1/-1">尚无核查发现</div>`;
  } else {
    breakdown.innerHTML = order.map(k => {
      const v = dims[k] || 0;
      const dim = v > 0 ? "" : "opacity:0.55";
      return `
        <div style="padding:16px;background:var(--bg);border-radius:10px;${dim}">
          <div class="text-xs text-faint">${k}</div>
          <div style="font-size:22px;font-weight:700;margin-top:4px;letter-spacing:-0.02em">${v}</div>
          <div class="text-xs text-faint" style="margin-top:2px">${subtitles[k]}</div>
        </div>`;
    }).join("");
  }
}

// V3：finding_type 已在后端规范化为 5 桶之一，直接按字段计数即可
function aggregate5Dimensions(findings, _worksheet /* legacy unused */) {
  const buckets = {
    "真实性问题": 0, "完整性问题": 0, "合规性问题": 0,
    "重复性问题": 0, "匹配性问题": 0,
  };
  for (const f of findings || []) {
    const t = f.finding_type || "";
    if (t in buckets) buckets[t]++;
    else buckets["合规性问题"]++;  // 兜底：未知类型归合规
  }
  return buckets;
}

function renderScoreCard(task) {
  let stats = {};
  try { stats = JSON.parse(task.stats || "{}"); } catch {}
  const scoring = stats.scoring;
  const container = document.getElementById("tw-score-card");
  if (!container) return;
  if (!scoring || !scoring.total_max) {
    container.innerHTML = "";
    container.classList.add("hidden");
    return;
  }
  const gradeBadge = {
    "优": "badge badge-green",
    "良": "badge badge-blue",
    "中": "badge badge-orange",
    "差": "badge badge-red",
  }[scoring.grade] || "badge badge-gray";

  container.classList.remove("hidden");
  container.innerHTML = `
    <div class="card" style="background:linear-gradient(135deg,#fafafa,#f0f0f2);border:1px solid var(--border)">
      <div class="flex items-center justify-between" style="flex-wrap:wrap;gap:16px">
        <div>
          <div class="text-xs text-faint" style="letter-spacing:0.04em;font-family:var(--font-mono)">SCORE</div>
          <div style="font-size:48px;font-weight:700;letter-spacing:-0.03em;line-height:1;margin-top:6px">
            ${scoring.total_score}
            <span style="font-size:20px;color:var(--text-tertiary);font-weight:500"> / ${scoring.total_max} 分</span>
          </div>
          <div class="mt-2" style="font-size:14px;color:var(--text-secondary)">
            得分率 <b>${scoring.score_pct}%</b>　·　等级 <span class="${gradeBadge}" style="font-size:13px">${scoring.grade}</span>
          </div>
        </div>
        <button class="btn btn-ghost" id="tw-score-toggle">展开明细 ▾</button>
      </div>
      <div id="tw-score-detail" class="hidden" style="margin-top:16px;border-top:1px solid var(--divider);padding-top:16px">
        <table class="table" style="font-size:12px">
          <thead><tr>
            <th>指标编号</th><th>名称</th><th>满分</th><th>扣分</th><th>得分</th><th>问题数</th>
          </tr></thead>
          <tbody>
            ${scoring.indicators.map(i => `<tr>
              <td><span class="code-id">${esc(i.indicator_code)}</span></td>
              <td>${esc(i.name)}</td>
              <td class="table-mono">${i.max_score}</td>
              <td class="table-mono ${i.deducted > 0 ? "" : "text-faint"}" style="${i.deducted > 0 ? "color:var(--red)" : ""}">${i.deducted}</td>
              <td class="table-mono" style="font-weight:600">${i.actual_score}</td>
              <td>${i.findings_total > 0
                ? `<span class="badge badge-orange">${i.findings_total}</span>`
                : '<span class="text-faint">0</span>'}</td>
            </tr>`).join("")}
          </tbody>
        </table>
        <div class="text-xs text-faint mt-3">
          扣分规则：高风险扣指标满分 50%，中风险扣 25%，低风险扣 10%；
          已忽略的发现不扣分，已调整的按 50% 计。等级阈值：优 ≥90 / 良 ≥80 / 中 ≥60 / 差 <60。
        </div>
      </div>
    </div>
  `;

  document.getElementById("tw-score-toggle").addEventListener("click", () => {
    const det = document.getElementById("tw-score-detail");
    const btn = document.getElementById("tw-score-toggle");
    if (det.classList.contains("hidden")) {
      det.classList.remove("hidden");
      btn.textContent = "收起明细 ▴";
    } else {
      det.classList.add("hidden");
      btn.textContent = "展开明细 ▾";
    }
  });
}

function renderMaterials() {
  const d = State.taskDetail;
  const indSel = document.getElementById("md-indicator");
  indSel.innerHTML = `<option value="">— 不绑定（归入共享池）—</option>` +
    State.indicators.map(i =>
      `<option value="${i.id}">[${esc(i.indicator_code)}] ${esc(i.name)}</option>`).join("");

  // 顶部条幅：绑定进度
  const bound = d.materials.filter(m => m.indicator_id).length;
  const total = d.materials.length;
  const banner = document.getElementById("tw-bind-banner");
  if (banner) {
    if (total === 0) {
      banner.innerHTML = "";
    } else if (bound === total) {
      banner.innerHTML = `<div class="callout callout-success" style="margin:8px 0">
        ✓ 全部 ${total} 份材料已绑定指标，可触发 AI 核查。</div>`;
    } else {
      banner.innerHTML = `<div class="callout callout-warn" style="margin:8px 0">
        <strong>${bound} / ${total}</strong> 已绑定指标，还有
        <strong>${total - bound}</strong> 份未绑定。可点
        <strong>「AI 自动绑定」</strong>批量识别，剩余的请用每行下拉手动指定。
      </div>`;
    }
  }

  const tbody = document.getElementById("tw-materials-tbody");
  if (!d.materials.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="empty-state">
      <div class="empty-state-glyph">⊕</div>尚未上传材料</td></tr>`;
    return;
  }
  // 下拉选项缓存（55 项）
  const indOptionsHtml = State.indicators.map(i =>
    `<option value="${i.id}">[${esc(i.indicator_code)}] ${esc(i.name)}</option>`).join("");

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

  // v1.5 重置 checkbox 状态 + 计数
  _updateBatchDelButton();

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

  // 触发核查按钮：按任务状态 + 绑定情况 动态切换
  const runBtn = document.getElementById("tw-run-btn");
  if (runBtn) {
    const allBound = total > 0 && bound === total;
    const status = d.task.status;
    if (status === "running") {
      runBtn.disabled = true;
      runBtn.innerHTML = `<span class="tw-progress-spinner" style="border-color:#cfdcf5;border-top-color:#fff;width:12px;height:12px"></span> <span>核查中…</span>`;
      runBtn.title = "任务正在核查中，请等待完成";
    } else if (["ai_done", "reviewing", "finalized", "archived"].includes(status)) {
      runBtn.disabled = !allBound;
      runBtn.innerHTML = `${icon("refresh")} <span>重新核查</span>`;
      runBtn.title = allBound ? "重新核查将清空已有疑点与底稿" : `仍有 ${total - bound} 份材料未绑定指标`;
    } else {
      runBtn.disabled = !allBound;
      runBtn.innerHTML = `${icon("play")} <span>触发 AI 核查</span>`;
      runBtn.title = allBound ? "" : `仍有 ${total - bound} 份材料未绑定指标`;
    }
    runBtn.style.opacity = runBtn.disabled ? "0.5" : "";
    runBtn.style.cursor = runBtn.disabled ? "not-allowed" : "";
  }
}

// AI 自动绑定（关键词 + LLM 阅读两阶段）
window.runAutoBind = async function() {
  if (!State.taskId) return;
  const btn = document.querySelector('[onclick="runAutoBind()"]');
  if (btn) {
    btn.disabled = true;
    btn.dataset.origHtml = btn.innerHTML;
    btn.innerHTML = `<span class="tw-progress-spinner" style="border-color:#ccc;border-top-color:#0071e3"></span> <span>AI 阅读材料中（约 1-2 分钟）…</span>`;
  }
  toast("AI 正在阅读材料内容，请稍候…（约 1-2 分钟）");
  try {
    const res = await api(`/tasks/${State.taskId}/materials/auto-bind`, { method: "POST" });
    const fb = res.fallback_bound || 0;
    const detail = res.ai_used
      ? `关键词命中 ${res.keyword_bound} + AI 命中 ${res.ai_bound} + 兜底 ${fb}`
      : `关键词命中 ${res.keyword_bound} + 兜底 ${fb}（未启用 LLM）`;
    toast(`✓ ${detail}，剩 ${res.still_unbound} 份未绑定`, "success");
    await loadTaskWorkspace(State.taskId);
  } catch (e) {
    toast(e.message, "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      if (btn.dataset.origHtml) btn.innerHTML = btn.dataset.origHtml;
    }
  }
};

document.getElementById("material-upload-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const indId = document.getElementById("md-indicator").value;
  const fileInput = document.getElementById("md-file");
  const status = document.getElementById("md-status");
  if (!fileInput.files.length) {
    status.innerHTML = `<div class="callout callout-warn">请选择文件</div>`;
    return;
  }
  const fd = new FormData();
  fd.append("file", fileInput.files[0]);
  if (indId) fd.append("indicator_id", indId);
  status.innerHTML = `<div class="callout callout-info">正在解析材料…</div>`;
  try {
    const tok = getToken();
    const r = await fetch(`${API}/tasks/${State.taskId}/materials`, {
      method: "POST", headers: { "Authorization": "Bearer " + tok }, body: fd,
    });
    if (!r.ok) throw new Error(await r.text());
    const body = await r.json();
    // v1.5 显示绑定置信度；v1.4 显示去重节省量
    const conf = body.binding_confidence || "none";
    const confLabel = {high: "高准确度", medium: "中等准确度", none: "未自动绑定"}[conf];
    const reusedTip = body.reused ? `（复用副本，省 ${body.reused_size_mb} MB）` : "";
    const tip = body.indicator_id
      ? `✓ 已上传 · 绑到指标（${confLabel}）${reusedTip}`
      : `✓ 已上传 · 未自动绑定（请手动指定指标）${reusedTip}`;
    status.innerHTML = `<div class="callout callout-success">${tip}</div>`;
    toast(tip, "success");
    fileInput.value = "";
    await loadTaskWorkspace(State.taskId);
  } catch (e) {
    status.innerHTML = `<div class="callout callout-error">✗ ${esc(e.message)}</div>`;
  }
});

// ============================================================
// 材料 · 文件夹批量上传
// ============================================================
const MD_FOLDER = { files: [], cancelled: false };
const MD_FOLDER_CONCURRENCY = 3;
const MD_FOLDER_MAX = 200;
const MD_FOLDER_EXTS = [".pdf", ".docx", ".xlsx", ".txt", ".md"];

document.getElementById("md-folder-btn").addEventListener("click", () => {
  document.getElementById("md-folder-picker").click();
});

document.getElementById("md-folder-picker").addEventListener("change", async ev => {
  const all = Array.from(ev.target.files || []);
  ev.target.value = "";
  if (!all.length) return;
  const valid = all.filter(f => {
    const n = (f.name || "").toLowerCase();
    return MD_FOLDER_EXTS.some(ext => n.endsWith(ext));
  });
  if (!valid.length) {
    toast("文件夹内无支持的文件", "error"); return;
  }
  if (valid.length > MD_FOLDER_MAX) {
    toast(`文件数 ${valid.length} 超过 ${MD_FOLDER_MAX} 上限`, "error"); return;
  }
  MD_FOLDER.files = valid;
  MD_FOLDER.cancelled = false;
  await runMaterialFolderUpload();
});

async function runMaterialFolderUpload() {
  const files = MD_FOLDER.files;
  const tbody = document.getElementById("mfp-tbody");
  document.getElementById("mfp-cancel").classList.remove("hidden");
  document.getElementById("mfp-cancel").disabled = false;
  document.getElementById("mfp-close").classList.add("hidden");
  document.getElementById("mfp-summary").textContent =
    `共 ${files.length} 份文件 · 归入任务共享池（核查时对所有指标交叉匹配）`;
  document.getElementById("mfp-bar").style.width = "0%";

  tbody.innerHTML = files.map((f, idx) => `
    <tr id="mfp-row-${idx}">
      <td><span id="mfp-icon-${idx}" class="text-muted">○</span></td>
      <td style="word-break:break-all">${esc(f.webkitRelativePath || f.name)}</td>
      <td class="text-faint">${(f.size / 1024).toFixed(1)} KB</td>
      <td id="mfp-msg-${idx}" class="text-sm text-muted">待上传</td>
    </tr>`).join("");

  document.getElementById("md-folder-progress-modal").classList.remove("hidden");

  let cursor = 0, done = 0, ok = 0, fail = 0;
  const updateBar = () => {
    document.getElementById("mfp-bar").style.width = `${(done / files.length) * 100}%`;
    document.getElementById("mfp-summary").textContent =
      `进度 ${done}/${files.length} · 成功 ${ok} · 失败 ${fail}`;
  };

  async function worker() {
    while (true) {
      if (MD_FOLDER.cancelled) break;
      const idx = cursor++;
      if (idx >= files.length) break;
      const file = files[idx];
      const icon = document.getElementById(`mfp-icon-${idx}`);
      const msg = document.getElementById(`mfp-msg-${idx}`);
      icon.innerHTML = '<span style="color:var(--orange)">⋯</span>';
      msg.textContent = "上传中…";
      try {
        const fd = new FormData();
        fd.append("file", file);
        if (file.webkitRelativePath) {
          fd.append("relative_path", file.webkitRelativePath);
        }
        // 不绑定 indicator_id → 归入共享池
        const tok = getToken();
        const r = await fetch(`${API}/tasks/${State.taskId}/materials`, {
          method: "POST", headers: { "Authorization": "Bearer " + tok }, body: fd,
        });
        if (!r.ok) throw new Error(await r.text());
        const body = await r.json();
        // v1.5 显示置信度；v1.4 显示复用情况
        const conf = body.binding_confidence || "none";
        const confLabel = {high: "高", medium: "中", none: "未绑"}[conf];
        icon.innerHTML = '<span style="color:var(--green)">✓</span>';
        if (body.reused) {
          msg.textContent = `✓ ${confLabel} · 复用（省 ${body.reused_size_mb} MB）`;
          MD_FOLDER.totalSavedMb = (MD_FOLDER.totalSavedMb || 0) + (body.reused_size_mb || 0);
        } else {
          msg.textContent = `✓ ${confLabel}`;
        }
        ok++;
      } catch (e) {
        icon.innerHTML = '<span style="color:var(--red)">✗</span>';
        msg.textContent = "✗ " + (e.message || "上传失败");
        msg.style.color = "var(--red)";
        fail++;
      }
      done++;
      updateBar();
    }
  }

  const workers = Array.from({ length: MD_FOLDER_CONCURRENCY }, () => worker());
  await Promise.all(workers);

  document.getElementById("mfp-cancel").classList.add("hidden");
  document.getElementById("mfp-close").classList.remove("hidden");
  if (MD_FOLDER.cancelled) {
    document.getElementById("mfp-summary").textContent =
      `已取消 · 完成 ${done}/${files.length} · 成功 ${ok} · 失败 ${fail}`;
  } else {
    const savedMb = (MD_FOLDER.totalSavedMb || 0).toFixed(2);
    const savedTip = savedMb > 0 ? `（去重共省 ${savedMb} MB）` : "";
    toast(`✓ 批量上传完成：${ok} 成功 / ${fail} 失败${savedTip}`, ok > 0 ? "success" : "error");
  }
  await loadTaskWorkspace(State.taskId);
}

document.getElementById("mfp-cancel").addEventListener("click", () => {
  MD_FOLDER.cancelled = true;
  document.getElementById("mfp-cancel").disabled = true;
});

document.getElementById("tw-run-btn").addEventListener("click", async () => {
  if (!State.taskDetail.materials.length) { toast("请先上传材料", "error"); return; }
  const status = State.taskDetail?.task?.status;
  if (status === "running") {
    toast("任务正在核查中，请等待完成", "warn");
    return;
  }
  let url = `/tasks/${State.taskId}/run`;
  if (["ai_done", "reviewing", "finalized", "archived"].includes(status)) {
    if (!confirm("重新核查将清空已有疑点和工作底稿。\n\n确定继续吗？")) return;
    url += "?force=true";
  }
  toast("AI 核查中…快速模式约 5 分钟、精确模式 10-15 分钟");
  try {
    await api(url, { method: "POST" });
    // 立即拉一下让进度条出现
    await loadTaskWorkspace(State.taskId);
  } catch (e) { toast(e.message, "error"); }
});

// ============================================================
// Findings 分栏审阅
// ============================================================
const _FIC_DIMS = ["真实性问题", "完整性问题", "合规性问题", "重复性问题", "匹配性问题", "形式性"];
const _FIC_DIM_SHORT = {
  "真实性问题": "真实",
  "完整性问题": "完整",
  "合规性问题": "合规",
  "重复性问题": "重复",
  "匹配性问题": "匹配",
  "形式性":     "形式",
};

function _groupFindingsByIndicator(findings, indicators) {
  const indMap = new Map();
  for (const ind of (indicators || [])) indMap.set(ind.id, ind);
  const groups = new Map();
  for (const f of findings) {
    const k = f.indicator_id == null ? "__unbound__" : f.indicator_id;
    if (!groups.has(k)) {
      const ind = (k === "__unbound__") ? null : indMap.get(f.indicator_id);
      groups.set(k, {
        key: k,
        indicator: ind,
        sort_code: ind ? ind.indicator_code : "ZZ",
        findings: [],
      });
    }
    groups.get(k).findings.push(f);
  }
  return Array.from(groups.values()).sort((a, b) => {
    if (a.key === "__unbound__") return 1;
    if (b.key === "__unbound__") return -1;
    return a.sort_code.localeCompare(b.sort_code);
  });
}

function renderFindings() {
  const d = State.taskDetail;
  const findings = d.findings;

  // 顶部维度横切按钮（保留）
  renderFindingBulkActions(findings);

  const filtered = findings.filter(f => {
    const v = State.findingFilter;
    if (v === "all") return true;
    if (["高","中","低"].includes(v)) return f.severity === v;
    if (v === "pending") return f.review_status === "pending";
    if (v === "confirmed") return f.review_status === "confirmed";
    return true;
  });

  const listBox = document.getElementById("finding-list");
  if (!filtered.length) {
    listBox.innerHTML = `<div class="empty-state">
      <div class="empty-state-glyph">▦</div>
      ${findings.length === 0 ? '尚无核查发现，请先触发 AI 核查' : '当前筛选下无结果'}
    </div>`;
    renderFindingDetail(null);
    return;
  }

  const groups = _groupFindingsByIndicator(filtered, State.indicators || []);
  listBox.innerHTML = groups.map(g => _renderIndicatorCard(g)).join("");

  // 卡 header 点击展开/折叠（按钮自身阻止冒泡）
  listBox.querySelectorAll(".finding-indicator-header").forEach(h => {
    h.addEventListener("click", e => {
      if (e.target.closest(".fic-actions")) return;
      h.parentElement.classList.toggle("is-open");
    });
  });

  // 卡内单条 finding 行点击 → 显示详情
  listBox.querySelectorAll(".fic-finding-row").forEach(row => {
    row.addEventListener("click", e => {
      if (e.target.closest(".fic-finding-row-actions")) return;
      const id = parseInt(row.dataset.id);
      State.activeFindingId = id;
      listBox.querySelectorAll(".fic-finding-row.is-active")
             .forEach(r => r.classList.remove("is-active"));
      row.classList.add("is-active");
      const f = findings.find(x => x.id === id);
      renderFindingDetail(f);
    });
  });

  if (!State.activeFindingId || !filtered.find(f => f.id === State.activeFindingId)) {
    State.activeFindingId = filtered[0].id;
  }
  // v1.6: 自动展开 active finding 所在卡，避免左侧看似空白
  const activeFinding = filtered.find(f => f.id === State.activeFindingId);
  if (activeFinding) {
    const activeKey = activeFinding.indicator_id == null
      ? "" : String(activeFinding.indicator_id);
    const activeCard = listBox.querySelector(
      `.finding-indicator-card[data-indicator-id="${activeKey}"]`
    );
    if (activeCard) activeCard.classList.add("is-open");
  }
  renderFindingDetail(activeFinding);
}

function _renderIndicatorCard(group) {
  const ind = group.indicator;
  const fs = group.findings;
  const title = ind
    ? `${esc(ind.indicator_code)} ${esc(ind.name)}`
    : `未绑指标`;
  const total = fs.length;
  const pending = fs.filter(f => (f.review_status || "pending") === "pending").length;
  const allReviewed = pending === 0;

  const dimCounts = {};
  for (const t of _FIC_DIMS) dimCounts[t] = 0;
  for (const f of fs) {
    if (dimCounts[f.finding_type] !== undefined) dimCounts[f.finding_type]++;
  }
  const badges = _FIC_DIMS.map(t => {
    const n = dimCounts[t];
    const short = _FIC_DIM_SHORT[t];
    return `<span class="fic-dim-badge dim-${t} ${n === 0 ? 'zero' : ''}">${short} ${n}</span>`;
  }).join("");

  const indId = ind ? ind.id : null;
  const actions = pending > 0 ? `
    <button class="btn btn-ghost"
            onclick="bulkReviewIndicator(${indId === null ? 'null' : indId}, 'confirmed')"
            title="把该指标下 ${pending} 条未复核全部确认">✓ 全部确认</button>
    <button class="btn btn-ghost"
            onclick="bulkReviewIndicator(${indId === null ? 'null' : indId}, 'ignored')"
            title="把该指标下 ${pending} 条未复核全部忽略">✗ 全部忽略</button>
  ` : `<span class="text-muted" style="font-size:12px">✓ 已全部复核</span>`;

  const body = _FIC_DIMS.map(dim => {
    const rows = fs.filter(f => f.finding_type === dim);
    if (!rows.length) return "";
    return `<div class="fic-dim-group">
      <div class="fic-dim-group-title">${dim}（${rows.length}）</div>
      ${rows.map(f => _renderFindingRow(f)).join("")}
    </div>`;
  }).join("");

  return `<div class="finding-indicator-card ${allReviewed ? 'all-reviewed' : ''}"
                data-indicator-id="${indId === null ? '' : indId}">
    <div class="finding-indicator-header">
      <span class="fic-caret"></span>
      <span class="fic-title">${title}</span>
      <span class="fic-count">共 ${total} 条 · 待复核 <span class="pending-num">${pending}</span></span>
      <span class="fic-dim-badges">${badges}</span>
      <span class="fic-actions">${actions}</span>
    </div>
    <div class="finding-indicator-body">${body}</div>
  </div>`;
}

function _renderFindingRow(f) {
  const isActive = f.id === State.activeFindingId;
  const desc = esc(f.description.slice(0, 100)) + (f.description.length > 100 ? '…' : '');
  const reviewed = (f.review_status || "pending") !== "pending";
  return `<div class="fic-finding-row ${isActive ? 'is-active' : ''}" data-id="${f.id}">
    <span class="chip-risk chip-risk-${f.severity}">${f.severity}</span>
    <span class="fic-finding-desc">${desc}</span>
    ${reviewBadge(f.review_status)}
    <span class="fic-finding-row-actions">
      ${reviewed ? '' : `
        <button class="btn-mini" onclick="event.stopPropagation(); reviewFindingInline(${f.id}, 'confirmed')" title="确认">✓</button>
        <button class="btn-mini" onclick="event.stopPropagation(); reviewFindingInline(${f.id}, 'ignored')" title="忽略">✗</button>
      `}
    </span>
  </div>`;
}

function reviewBadge(s) {
  const map = {
    pending:   ['badge badge-gray',  '待复核'],
    confirmed: ['badge badge-green', '已确认'],
    ignored:   ['badge badge-gray',  '已忽略'],
    adjusted:  ['badge badge-orange','已调整'],
  };
  const [cls, label] = map[s] || ['badge badge-gray', s];
  return `<span class="${cls}">${label}</span>`;
}
function rectifyBadge(s) {
  const map = {
    open:      ['badge badge-red',   '未整改'],
    submitted: ['badge badge-orange','已提交'],
    resolved:  ['badge badge-green', '已销号'],
  };
  const [cls, label] = map[s] || ['badge badge-gray', s];
  return `<span class="${cls}">${label}</span>`;
}

// V3：5 维度批量忽略 — 一键把同类未复核 finding 全部 ignored（复用 _FIC_DIMS）

function renderFindingBulkActions(findings) {
  const bar = document.getElementById("finding-bulk-actions");
  if (!bar) return;
  // 统计每个维度的"未复核"数量
  const pending = findings.filter(f => (f.review_status || "pending") === "pending");
  const counts = {};
  for (const t of _FIC_DIMS) counts[t] = 0;
  for (const f of pending) {
    if (counts[f.finding_type] !== undefined) counts[f.finding_type]++;
  }
  const totalPending = pending.length;
  if (totalPending === 0) {
    bar.innerHTML = `<span class="text-muted">✓ 所有疑点已复核</span>`;
    return;
  }
  const chips = _FIC_DIMS
    .filter(t => counts[t] > 0)
    .map(t => `<button class="btn btn-ghost btn-sm" style="font-size:12px"
                       onclick="bulkIgnoreFindings('${t}')"
                       title="把当前 ${counts[t]} 条未复核「${t}」一键标记为忽略">
                   忽略所有 ${t}（${counts[t]}）
               </button>`).join("");
  bar.innerHTML = `<span class="text-muted">共 ${totalPending} 条未复核：</span> ${chips}`;
}

window.bulkIgnoreFindings = async function(dim) {
  if (!confirm(`确定把所有「${dim}」未复核疑点一键标为"已忽略"？\n\n忽略后这类问题不再扣分。`)) return;
  const pendingCount = State.taskDetail.findings.filter(
    f => f.finding_type === dim && (f.review_status || "pending") === "pending"
  ).length;
  if (!pendingCount) { toast("没有未复核的此类条目"); return; }
  toast(`批量处理 ${pendingCount} 条…`);
  try {
    const resp = await api(`/tasks/${State.taskId}/findings/batch-review`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status: "ignored",
        note: `批量忽略：${dim}`,
        finding_type: dim,
        only_pending: true,
      }),
    });
    toast(`✓ 已忽略 ${resp.updated} 条「${dim}」`, "success");
  } catch (e) {
    console.error("批量忽略失败", e);
    toast(`批量忽略失败：${e.message}`, "error");
    return;
  }
  await loadTaskWorkspace(State.taskId);
};

// v1.6：指标级批量复核（卡 header 上的 [全部确认 / 全部忽略] 按钮）
window.bulkReviewIndicator = async function(indicatorId, status) {
  const verb = status === "confirmed" ? "确认" : "忽略";
  const findings = State.taskDetail.findings.filter(f => {
    const sameInd = indicatorId === null
      ? (f.indicator_id == null)
      : (f.indicator_id === indicatorId);
    return sameInd && (f.review_status || "pending") === "pending";
  });
  if (!findings.length) { toast("该指标已无未复核条目"); return; }
  const indLabel = indicatorId === null ? "未绑指标" : `指标 ${indicatorId}`;
  if (!confirm(`确定把「${indLabel}」下 ${findings.length} 条未复核疑点一键${verb}？`)) return;
  toast(`批量${verb} ${findings.length} 条…`);
  try {
    if (indicatorId === null) {
      // 后端 batch-review 必须传 indicator_id 或 finding_type 之一；
      // 未绑指标 → 退化为 N 次串行 PATCH（罕见场景）
      let ok = 0;
      for (const f of findings) {
        try {
          await api(`/findings/${f.id}/review`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status, note: `批量${verb}：未绑指标` }),
          });
          ok++;
        } catch (e) { console.warn("review fail", f.id, e.message); }
      }
      toast(`✓ 已${verb} ${ok} 条`, "success");
    } else {
      const resp = await api(`/tasks/${State.taskId}/findings/batch-review`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          status, note: `批量${verb}：指标级`,
          indicator_id: indicatorId, only_pending: true,
        }),
      });
      toast(`✓ 已${verb} ${resp.updated} 条`, "success");
    }
  } catch (e) {
    console.error("批量复核失败", e);
    toast(`批量复核失败：${e.message}`, "error");
    return;
  }
  await loadTaskWorkspace(State.taskId);
};

// v1.6：单条 finding 行内确认/忽略（卡片二级分组里的小按钮）
window.reviewFindingInline = async function(findingId, status) {
  const verb = status === "confirmed" ? "确认" : "忽略";
  try {
    await api(`/findings/${findingId}/review`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, note: `行内${verb}` }),
    });
    toast(`✓ 已${verb}`, "success");
  } catch (e) {
    console.error("review failed", e);
    toast(`${verb}失败：${e.message}`, "error");
    return;
  }
  await loadTaskWorkspace(State.taskId);
};

function renderFindingDetail(f) {
  const box = document.getElementById("finding-detail");
  if (!f) {
    box.innerHTML = `<div class="triage-empty">
      <div class="triage-empty-glyph">▦</div>
      <div>从左侧列表选择一条发现<br/>进行复核标注或整改跟踪</div>
    </div>`;
    return;
  }
  const indicator = State.indicators.find(i => i.id === f.indicator_id);
  const material = State.taskDetail.materials.find(m => m.id === f.material_id);

  box.innerHTML = `
    <div class="flex items-center gap-2 mb-4">
      <span class="chip-risk chip-risk-${f.severity}">${f.severity} 风险</span>
      <span class="tag">${esc(f.finding_type)}</span>
      <span class="text-xs text-faint">由 ${f.source === 'rule' ? '刚性规则' : 'LLM'} 检出</span>
    </div>

    <h2 class="detail-heading">${esc(f.description)}</h2>

    <dl class="detail-meta-grid">
      <dt>评价指标</dt>
      <dd>${indicator ? `<span class="code-id">${esc(indicator.indicator_code)}</span> ${esc(indicator.name)}` : '<span class="text-muted">—</span>'}</dd>
      <dt>材料出处</dt>
      <dd>${material
            ? `<a href="javascript:void(0)" class="material-link"
                  onclick="openMaterial(${material.id})"
                  title="点击查看原文件">${esc(material.file_name)}</a>`
            : '<span class="text-muted">—</span>'}</dd>
      <dt>具体位置</dt>
      <dd>${esc(f.evidence_location || '—')}${
            material && f.evidence_location && f.evidence_location !== '—' && f.evidence_location !== '全文'
              ? ` <span class="text-xs text-muted">（打开文件后按 Ctrl+F 搜索关键词定位）</span>`
              : ''}</dd>
      <dt>复核状态</dt>
      <dd>${reviewBadge(f.review_status)}${f.review_note ? ' · <span class="text-muted">' + esc(f.review_note) + '</span>' : ''}</dd>
      <dt>整改状态</dt>
      <dd>${rectifyBadge(f.rectification_status)}${f.rectification_note ? ' · <span class="text-muted">' + esc(f.rectification_note) + '</span>' : ''}</dd>
    </dl>

    ${f.legal_basis ? `
      <div class="detail-section">
        <div class="detail-section-title">法规依据</div>
        <div class="detail-quote">${esc(f.legal_basis)}</div>
      </div>` : ''}

    ${f.suggestion ? `
      <div class="detail-section">
        <div class="detail-section-title">整改建议</div>
        <div class="detail-quote">${esc(f.suggestion)}</div>
      </div>` : ''}

    <div class="detail-section">
      <div class="detail-section-title">审查员复核</div>
      <textarea id="review-note" class="form-textarea mb-3" placeholder="复核意见（可选）"></textarea>
      <div class="action-bar">
        <button class="btn btn-success" onclick="reviewFinding('confirmed')">✓ 确认问题</button>
        <button class="btn btn-secondary" onclick="reviewFinding('ignored')">忽略</button>
        <button class="btn btn-secondary" onclick="reviewFinding('adjusted')">调整</button>
      </div>
    </div>

    <div class="detail-section">
      <div class="detail-section-title">整改闭环</div>
      <textarea id="rectify-note" class="form-textarea mb-3" placeholder="整改说明">${esc(f.rectification_note || '')}</textarea>
      <div class="action-bar">
        <button class="btn btn-secondary" onclick="submitRectification()">提交整改</button>
        <button class="btn btn-brand" onclick="resolveRectification()">销号</button>
      </div>
    </div>
  `;
}

window.reviewFinding = async function(status) {
  const note = document.getElementById("review-note").value;
  try {
    await api(`/findings/${State.activeFindingId}/review`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, note }),
    });
    toast(`✓ 已标注为「${status}」`, "success");
    await loadTaskWorkspace(State.taskId);
    renderSubtab();
  } catch (e) { toast(e.message, "error"); }
};

window.submitRectification = async function() {
  const note = document.getElementById("rectify-note").value;
  if (!note.trim()) { toast("请填写整改说明", "error"); return; }
  try {
    await api(`/findings/${State.activeFindingId}/rectify`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note }),
    });
    toast("✓ 整改说明已提交", "success");
    await loadTaskWorkspace(State.taskId);
    renderSubtab();
  } catch (e) { toast(e.message, "error"); }
};

window.resolveRectification = async function() {
  const note = document.getElementById("rectify-note").value;
  if (!confirm("将此条标记为「已销号」？")) return;
  try {
    await api(`/findings/${State.activeFindingId}/resolve`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note }),
    });
    toast("✓ 已销号", "success");
    await loadTaskWorkspace(State.taskId);
    renderSubtab();
  } catch (e) { toast(e.message, "error"); }
};

document.getElementById("finding-filters").addEventListener("click", ev => {
  if (!ev.target.matches(".filter-chip")) return;
  document.querySelectorAll("#finding-filters .filter-chip").forEach(b => b.classList.remove("on"));
  ev.target.classList.add("on");
  State.findingFilter = ev.target.dataset.filter;
  State.activeFindingId = null;
  renderFindings();
});

// ============================================================
// 知识库 — 法规库
// ============================================================
let _regCache = { all: [], docTypes: [], regions: [] };

async function loadRegulations() {
  const params = new URLSearchParams();
  const search = document.getElementById("reg-search").value.trim();
  const docType = document.getElementById("reg-filter-type").value;
  const region = document.getElementById("reg-filter-region").value;
  if (search) params.set("search", search);
  if (docType) params.set("doc_type", docType);
  if (region) params.set("region", region);

  try {
    const resp = await api("/regulations?" + params.toString());
    _regCache = { all: resp.regulations, docTypes: resp.doc_types, regions: resp.regions };

    // 装填筛选下拉
    const ftype = document.getElementById("reg-filter-type");
    const fregion = document.getElementById("reg-filter-region");
    if (ftype.options.length <= 1) {
      ftype.innerHTML = `<option value="">全部类型</option>` +
        resp.doc_types.map(t => `<option value="${esc(t)}">${esc(t)}</option>`).join("");
    }
    if (fregion.options.length <= 1) {
      fregion.innerHTML = `<option value="">全部地区</option>` +
        resp.regions.map(r => `<option value="${esc(r)}">${esc(r)}</option>`).join("");
    }
    if (docType) ftype.value = docType;
    if (region) fregion.value = region;

    document.getElementById("reg-count").textContent = `共 ${resp.total} 条`;

    const tbody = document.getElementById("regulations-tbody");
    if (!resp.regulations.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="empty-state">
        <div class="empty-state-glyph">⊕</div>
        ${search || docType || region ? '当前筛选下无结果' : '暂无法规，请点击右上角「+ 上传法规」'}
      </td></tr>`;
      return;
    }
    tbody.innerHTML = resp.regulations.map(r => {
      const isAdmin = State.user && State.user.role === "super_admin";
      const sizeKB = (r.file_size / 1024).toFixed(1);
      return `<tr>
        <td>
          <div style="font-weight:500">${esc(r.title)}</div>
          ${r.description ? `<div class="text-sm text-muted mt-2">${esc(r.description)}</div>` : ''}
        </td>
        <td>${docTypeBadge(r.doc_type)}</td>
        <td><span class="badge badge-gray">${esc(r.region)}</span></td>
        <td class="text-sm">
          ${r.issuer ? esc(r.issuer) : '<span class="text-faint">—</span>'}
          ${r.doc_number ? '<div class="text-xs text-muted mt-2"><span class="code-id">' + esc(r.doc_number) + '</span></div>' : ''}
        </td>
        <td class="text-sm">
          <div>${esc(r.file_name)}</div>
          <div class="text-xs text-faint mt-2">${sizeKB} KB · ${esc(r.file_type)}</div>
        </td>
        <td>
          ${r.indexed
            ? `<span class="badge badge-green">${r.chunks_count} 块</span>`
            : '<span class="badge badge-orange">未索引</span>'}
        </td>
        <td class="text-sm text-muted">${fmtTime(r.created_at)}</td>
        <td>
          <div class="flex gap-2" style="justify-content:flex-end">
            <button class="btn btn-ghost btn-sm" onclick="previewRegulation(${r.id})" title="预览">${icon("view")}</button>
            <button class="btn btn-ghost btn-sm" onclick="downloadRegulation(${r.id})" title="下载">${icon("download")}</button>
            ${isAdmin ? `<button class="btn btn-danger-ghost btn-sm" onclick="deleteRegulation(${r.id}, '${esc(r.title)}')" title="删除">${icon("delete")}</button>` : ''}
          </div>
        </td>
      </tr>`;
    }).join("");
  } catch (e) {
    toast(e.message, "error");
  }
}

function docTypeBadge(t) {
  const map = {
    "上位法":   ['badge badge-brand'],
    "评价办法": ['badge badge-blue'],
    "编报指南": ['badge badge-green'],
    "地方法规": ['badge badge-orange'],
    "部门规章": ['badge badge-gray'],
    "高频问题": ['badge badge-red'],
  };
  const cls = (map[t] || ['badge badge-gray'])[0];
  return `<span class="${cls}">${esc(t)}</span>`;
}

// 打开核查发现/底稿/材料审核中提到的材料原文件
// PDF/图片/文本 → 新标签页内联预览；docx/xlsx → 下载到本地
window.openMaterial = async function(materialId) {
  const tok = getToken();
  if (!tok) { toast("请先登录", "error"); return; }
  try {
    toast("正在加载材料…");
    const r = await fetch(`${API}/materials/${materialId}/preview`, {
      headers: { Authorization: "Bearer " + tok },
    });
    if (!r.ok) {
      const text = await r.text();
      throw new Error(text || `HTTP ${r.status}`);
    }
    const blob = await r.blob();
    // 根据 Content-Disposition 判断该 inline 还是 attachment
    const cd = r.headers.get("Content-Disposition") || "";
    const isInline = cd.toLowerCase().startsWith("inline");
    const ctype = r.headers.get("Content-Type") || "";

    const url = URL.createObjectURL(blob);
    if (isInline) {
      // 新标签打开预览（PDF / 图片 / 文本）
      const w = window.open(url, "_blank");
      if (!w) toast("浏览器拦截了新标签，请允许弹窗", "warn");
      else toast("已在新标签打开");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } else {
      // 下载（Office 文件）
      let fname = `material_${materialId}`;
      const m = cd.match(/filename\*=UTF-8''([^;]+)/);
      if (m) fname = decodeURIComponent(m[1]);
      else {
        const m2 = cd.match(/filename="?([^";]+)"?/);
        if (m2) fname = m2[1];
      }
      const a = document.createElement("a");
      a.href = url;
      a.download = fname;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast("已下载，请用本地 Office 打开", "success");
    }
  } catch (e) {
    toast("打开失败：" + (e.message || e), "error");
  }
};

window.downloadRegulation = async function(id) {
  const tok = getToken();
  if (!tok) { toast("请先登录", "error"); return; }
  try {
    toast("正在下载…");
    const r = await fetch(`${API}/regulations/${id}/download`, {
      headers: { Authorization: "Bearer " + tok },
    });
    if (!r.ok) {
      const text = await r.text();
      throw new Error(text || `HTTP ${r.status}`);
    }
    const blob = await r.blob();
    // 从 Content-Disposition 解析文件名（含 RFC 5987 中文）
    const cd = r.headers.get("Content-Disposition") || "";
    let fname = `regulation_${id}`;
    const m = cd.match(/filename\*=UTF-8''([^;]+)/);
    if (m) fname = decodeURIComponent(m[1]);
    else {
      const m2 = cd.match(/filename="?([^";]+)"?/);
      if (m2) fname = m2[1];
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = fname;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast("✓ 下载完成", "success");
  } catch (e) {
    toast("下载失败：" + (e.message || e), "error");
  }
};

window.previewRegulation = async function(id) {
  toast("加载法规内容…");
  try {
    const data = await api(`/regulations/${id}/content`);
    const r = data.regulation;
    document.getElementById("rp-title").textContent = r.title;
    document.getElementById("rp-doctype").innerHTML = docTypeBadge(r.doc_type);
    document.getElementById("rp-region").innerHTML = `<span class="badge badge-gray">${esc(r.region)}</span>`;

    const metaParts = [];
    if (r.issuer) metaParts.push(esc(r.issuer));
    if (r.doc_number) metaParts.push(`<span class="code-id">${esc(r.doc_number)}</span>`);
    if (r.effective_date) metaParts.push(`生效 ${esc(r.effective_date)}`);
    metaParts.push(`文件 ${esc(r.file_name)} (${(r.file_size / 1024).toFixed(1)} KB)`);
    metaParts.push(`<span class="badge badge-green">${r.chunks_count} 条款块入向量库</span>`);
    document.getElementById("rp-meta").innerHTML = metaParts.join(" · ");

    document.getElementById("rp-text").textContent = data.text;
    const trunc = document.getElementById("rp-truncated");
    if (data.truncated) {
      trunc.textContent = `（已截取前 ${data.text.length} / 全文 ${data.text_total_chars} 字符）`;
      trunc.classList.remove("hidden");
    } else {
      trunc.classList.add("hidden");
    }

    document.getElementById("rp-chunks-count").textContent = data.chunks.length;
    document.getElementById("rp-chunks-list").innerHTML = data.chunks.length
      ? data.chunks.map((c, i) => `
        <div style="border-bottom:1px solid var(--divider);padding:12px 8px">
          <div class="flex items-center gap-2 mb-2">
            <span class="code-id">#${pad(i + 1)}</span>
            <span class="badge badge-blue">${esc(c.citation)}</span>
            ${c.article ? `<span class="text-xs text-faint">${esc(c.article)}</span>` : ''}
          </div>
          <div style="font-size:13px;line-height:1.6;color:var(--text-secondary);white-space:pre-wrap">${esc(c.text)}</div>
        </div>`).join("")
      : `<div class="empty-state">该法规未生成条款分块</div>`;

    const rpDl = document.getElementById("rp-download");
    rpDl.removeAttribute("href");
    rpDl.style.cursor = "pointer";
    rpDl.onclick = (ev) => { ev.preventDefault(); downloadRegulation(id); };

    // 默认显示全文 tab
    document.querySelectorAll("[data-rptab]").forEach(b => {
      b.classList.toggle("active", b.dataset.rptab === "text");
    });
    document.getElementById("rp-tab-text").classList.remove("hidden");
    document.getElementById("rp-tab-chunks").classList.add("hidden");

    document.getElementById("reg-preview-modal").classList.remove("hidden");
  } catch (e) {
    toast("预览失败：" + e.message, "error");
  }
};

// 预览模态的 tab 切换
document.addEventListener("click", ev => {
  if (!ev.target.matches("[data-rptab]")) return;
  const t = ev.target.dataset.rptab;
  document.querySelectorAll("[data-rptab]").forEach(b => b.classList.toggle("active", b === ev.target));
  document.getElementById("rp-tab-text").classList.toggle("hidden", t !== "text");
  document.getElementById("rp-tab-chunks").classList.toggle("hidden", t !== "chunks");
});

window.deleteRegulation = async function(id, title) {
  if (!confirm(`确定删除法规《${title}》？\n该法规的原始文件将被删除（向量库内的索引块保留）。`)) return;
  try {
    await api(`/regulations/${id}`, { method: "DELETE" });
    toast("✓ 已删除", "success");
    loadRegulations();
  } catch (e) { toast(e.message, "error"); }
};

// 搜索 / 筛选 实时触发
let _regSearchTimer;
function bindRegFilters() {
  const searchInput = document.getElementById("reg-search");
  if (searchInput && !searchInput._bound) {
    searchInput._bound = true;
    searchInput.addEventListener("input", () => {
      clearTimeout(_regSearchTimer);
      _regSearchTimer = setTimeout(loadRegulations, 280);
    });
    document.getElementById("reg-filter-type").addEventListener("change", loadRegulations);
    document.getElementById("reg-filter-region").addEventListener("change", loadRegulations);
  }
}
bindRegFilters();

// 上传弹窗
// ============================================================
// 文件夹批量上传（功能 4）
// ============================================================
const FOLDER_STATE = {
  files: [],
  strategy: "ai",
  cancelled: false,
};
const FOLDER_MAX_FILES = 200;
const FOLDER_MAX_SIZE_MB = 50;
const FOLDER_CONCURRENCY = 3;
const SUPPORTED_FOLDER_EXTS = [".pdf", ".docx", ".xlsx", ".txt", ".md"];
const PATH_FOLDER_DOC_TYPES = ["上位法", "评价办法", "编报指南", "地方法规",
                                "部门规章", "高频问题"];

document.getElementById("open-folder-upload").addEventListener("click", () => {
  document.getElementById("folder-picker").click();
});

document.getElementById("folder-picker").addEventListener("change", ev => {
  const all = Array.from(ev.target.files || []);
  ev.target.value = "";  // 允许再次选择同一文件夹
  if (!all.length) return;

  // 按扩展名过滤
  const valid = all.filter(f => {
    const name = (f.name || "").toLowerCase();
    return SUPPORTED_FOLDER_EXTS.some(ext => name.endsWith(ext));
  });

  if (!valid.length) {
    toast("文件夹内未找到任何支持的文件（PDF/Word/Excel/TXT/MD）", "error");
    return;
  }
  if (valid.length > FOLDER_MAX_FILES) {
    toast(`文件数 ${valid.length} 超过 ${FOLDER_MAX_FILES} 上限，请分批上传`, "error");
    return;
  }
  const tooBig = valid.filter(f => f.size > FOLDER_MAX_SIZE_MB * 1024 * 1024);
  if (tooBig.length) {
    toast(`${tooBig.length} 份文件超过 ${FOLDER_MAX_SIZE_MB}MB，请检查`, "error");
    return;
  }

  FOLDER_STATE.files = valid;
  FOLDER_STATE.cancelled = false;
  openFolderConfigModal();
});

function openFolderConfigModal() {
  document.getElementById("fc-count").textContent = FOLDER_STATE.files.length;
  document.getElementById("folder-config-modal").classList.remove("hidden");
  document.getElementById("fc-error").classList.add("hidden");
  document.getElementById("fc-strategy").value = "ai";
  updateFcStrategyUI("ai");
}

document.getElementById("fc-strategy").addEventListener("change", ev => {
  updateFcStrategyUI(ev.target.value);
});

function updateFcStrategyUI(s) {
  document.getElementById("fc-strategy-ai").classList.toggle("hidden", s !== "ai");
  document.getElementById("fc-strategy-uniform").classList.toggle("hidden", s !== "uniform");
  document.getElementById("fc-strategy-path").classList.toggle("hidden", s !== "path");
  if (s === "path") renderPathPreview();
}

function fileRelativePath(f) {
  // 浏览器把目录相对路径放在 webkitRelativePath（如 "上位法/财办63号.pdf"）
  return f.webkitRelativePath || f.name;
}

function renderPathPreview() {
  // 按一级目录分组预览
  const groups = {};
  FOLDER_STATE.files.forEach(f => {
    const rel = fileRelativePath(f);
    const parts = rel.split("/");
    // parts[0] 是用户选的根目录名；parts[1] 是真正的一级子目录（如 "上位法"）
    const subDir = parts.length >= 3 ? parts[1] : "(根目录)";
    groups[subDir] = (groups[subDir] || 0) + 1;
  });
  const box = document.getElementById("fc-path-preview");
  box.innerHTML = Object.entries(groups)
    .map(([dir, n]) => {
      const matched = PATH_FOLDER_DOC_TYPES.includes(dir);
      const cls = matched ? "color:var(--green)" : "color:var(--orange)";
      const label = matched ? `→ ${dir}` : `→ 其它（未匹配）`;
      return `<div style="${cls}">· <b>${esc(dir)}/</b> (${n} 份) <span style="opacity:0.7">${label}</span></div>`;
    }).join("");
}

document.getElementById("fc-start").addEventListener("click", async () => {
  const strategy = document.getElementById("fc-strategy").value;
  FOLDER_STATE.strategy = strategy;

  // AI 策略需要 API Key
  if (strategy === "ai") {
    try {
      const cfg = await api("/settings/llm");
      if (!cfg.has_api_key) {
        document.getElementById("fc-error").textContent =
          "AI 策略需要先在「后台管理 → 大语言模型」配置 API Key，请改选「统一应用」或「按路径」";
        document.getElementById("fc-error").classList.remove("hidden");
        return;
      }
    } catch (e) {
      document.getElementById("fc-error").textContent = "无法读取 LLM 配置：" + e.message;
      document.getElementById("fc-error").classList.remove("hidden");
      return;
    }
  }

  document.getElementById("folder-config-modal").classList.add("hidden");
  await runFolderUpload();
});

// ============================================================
// 主上传循环
// ============================================================
async function runFolderUpload() {
  const files = FOLDER_STATE.files;
  const strategy = FOLDER_STATE.strategy;
  FOLDER_STATE.cancelled = false;

  // 准备进度模态
  const tbody = document.getElementById("fp-tbody");
  document.getElementById("fp-close").classList.add("hidden");
  document.getElementById("fp-cancel").classList.remove("hidden");
  document.getElementById("fp-summary").textContent =
    `共 ${files.length} 份文件，使用「${strategyLabel(strategy)}」策略`;
  document.getElementById("fp-bar").style.width = "0%";

  tbody.innerHTML = files.map((f, idx) => `
    <tr id="fp-row-${idx}">
      <td><span id="fp-icon-${idx}" class="text-muted">○</span></td>
      <td style="word-break:break-all">${esc(fileRelativePath(f))}</td>
      <td id="fp-doctype-${idx}" class="text-faint">—</td>
      <td id="fp-region-${idx}" class="text-faint">—</td>
      <td id="fp-chunks-${idx}" class="text-faint">—</td>
      <td id="fp-msg-${idx}" class="text-sm text-muted">待上传</td>
    </tr>`).join("");

  document.getElementById("folder-progress-modal").classList.remove("hidden");

  // 并发控制
  let cursor = 0;
  let done = 0;
  let succeeded = 0;
  let failed = 0;

  const updateBar = () => {
    document.getElementById("fp-bar").style.width = `${(done / files.length) * 100}%`;
    document.getElementById("fp-summary").textContent =
      `进度 ${done}/${files.length} · 成功 ${succeeded} · 失败 ${failed}`;
  };

  async function worker() {
    while (true) {
      if (FOLDER_STATE.cancelled) break;
      const idx = cursor++;
      if (idx >= files.length) break;
      const file = files[idx];
      await processOne(file, idx, strategy)
        .then(() => { succeeded++; })
        .catch(() => { failed++; });
      done++;
      updateBar();
    }
  }

  const workers = Array.from({ length: FOLDER_CONCURRENCY }, () => worker());
  await Promise.all(workers);

  // 完成
  document.getElementById("fp-cancel").classList.add("hidden");
  document.getElementById("fp-close").classList.remove("hidden");
  if (FOLDER_STATE.cancelled) {
    document.getElementById("fp-summary").textContent =
      `已取消 · 完成 ${done}/${files.length} · 成功 ${succeeded} · 失败 ${failed}`;
    toast(`已取消上传（已完成 ${done}）`, "info");
  } else {
    toast(`✓ 完成：成功 ${succeeded}，失败 ${failed}`, succeeded > 0 ? "success" : "error");
  }
  // 刷新法规库列表
  loadRegulations();
}

function strategyLabel(s) {
  return { ai: "AI 智能识别", uniform: "统一应用", path: "按路径" }[s] || s;
}

document.getElementById("fp-cancel").addEventListener("click", () => {
  FOLDER_STATE.cancelled = true;
  document.getElementById("fp-cancel").disabled = true;
});

// ============================================================
// 单文件处理：决策分类 → POST 上传
// ============================================================
async function processOne(file, idx, strategy) {
  setRowState(idx, "wait", "正在处理…");
  let meta;
  try {
    meta = await decideClassification(file, strategy);
  } catch (e) {
    setRowState(idx, "fail", "分类失败：" + e.message);
    return Promise.reject(e);
  }

  setRowDoc(idx, meta);
  setRowState(idx, "wait", "上传中…");

  try {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("title", meta.title);
    fd.append("doc_type", meta.doc_type);
    fd.append("region", meta.region);
    fd.append("issuer", meta.issuer || "");
    fd.append("doc_number", meta.doc_number || "");
    fd.append("effective_date", meta.effective_date || "");
    fd.append("description", `批量上传 · 策略：${strategyLabel(strategy)}`);
    fd.append("tags", "[]");

    const tok = getToken();
    const r = await fetch(`${API}/regulations`, {
      method: "POST",
      headers: { "Authorization": "Bearer " + tok },
      body: fd,
    });
    if (!r.ok) {
      const text = await r.text();
      let msg = text;
      try { msg = JSON.parse(text).detail || text; } catch {}
      throw new Error(msg || `HTTP ${r.status}`);
    }
    const reg = await r.json();
    setRowChunks(idx, reg.chunks_count);
    setRowState(idx, "ok", `✓ 已上传`);
    return reg;
  } catch (e) {
    setRowState(idx, "fail", "✗ " + e.message);
    throw e;
  }
}

async function decideClassification(file, strategy) {
  if (strategy === "uniform") {
    return {
      title: stripExt(file.name),
      doc_type: document.getElementById("fc-default-doc-type").value,
      region: document.getElementById("fc-default-region").value,
    };
  }

  if (strategy === "path") {
    const parts = fileRelativePath(file).split("/");
    const subDir = parts.length >= 3 ? parts[1] : "";
    const doc_type = PATH_FOLDER_DOC_TYPES.includes(subDir) ? subDir : "其它";
    // 简单按文件夹名推断 region
    let region = "国家";
    if (doc_type === "地方法规") region = "省";
    if (doc_type === "部门规章") region = "部门";
    return {
      title: stripExt(file.name),
      doc_type,
      region,
    };
  }

  // ai 策略：调 /classify 端点
  const fd = new FormData();
  fd.append("file", file);
  const tok = getToken();
  const r = await fetch(`${API}/regulations/classify`, {
    method: "POST",
    headers: { "Authorization": "Bearer " + tok },
    body: fd,
  });
  if (!r.ok) {
    const text = await r.text();
    let msg = text;
    try { msg = JSON.parse(text).detail || text; } catch {}
    throw new Error(msg);
  }
  return await r.json();
}

function stripExt(name) {
  const i = name.lastIndexOf(".");
  return i > 0 ? name.slice(0, i) : name;
}

function setRowState(idx, state, msg) {
  const icon = document.getElementById(`fp-icon-${idx}`);
  const m = document.getElementById(`fp-msg-${idx}`);
  if (icon) {
    const iconMap = {
      wait: '<span style="color:var(--orange)">⋯</span>',
      ok:   '<span style="color:var(--green)">✓</span>',
      fail: '<span style="color:var(--red)">✗</span>',
    };
    icon.innerHTML = iconMap[state] || "○";
  }
  if (m) {
    m.textContent = msg;
    m.className = "text-sm " + (state === "fail" ? "" : "text-muted");
    if (state === "fail") m.style.color = "var(--red)";
  }
}

function setRowDoc(idx, meta) {
  const dt = document.getElementById(`fp-doctype-${idx}`);
  const rg = document.getElementById(`fp-region-${idx}`);
  if (dt) {
    dt.innerHTML = docTypeBadge(meta.doc_type);
  }
  if (rg) {
    rg.innerHTML = `<span class="badge badge-gray">${esc(meta.region)}</span>`;
  }
}

function setRowChunks(idx, n) {
  const c = document.getElementById(`fp-chunks-${idx}`);
  if (c) c.innerHTML = `<span class="badge badge-green">${n}</span>`;
}

// ============================================================
// 原有单文件上传按钮
// ============================================================
document.getElementById("open-reg-upload").addEventListener("click", () => {
  document.getElementById("reg-upload-modal").classList.remove("hidden");
  document.getElementById("reg-upload-error").classList.add("hidden");
  document.getElementById("reg-upload-status").innerHTML = "";
  document.getElementById("reg-upload-form").reset();
});

document.getElementById("reg-upload-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const status = document.getElementById("reg-upload-status");
  const errBox = document.getElementById("reg-upload-error");
  errBox.classList.add("hidden");

  // FormData 已包含 file + 所有 input；确保 tags 是合法 JSON
  fd.set("tags", "[]");

  status.innerHTML = `<div class="callout callout-info">正在解析并入向量库…可能耗时数秒</div>`;
  try {
    const tok = getToken();
    const r = await fetch(`${API}/regulations`, {
      method: "POST",
      headers: { "Authorization": "Bearer " + tok },
      body: fd,
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: "上传失败" }));
      throw new Error(err.detail || "上传失败");
    }
    const reg = await r.json();
    status.innerHTML = `<div class="callout callout-success">✓ 上传成功 · ${reg.chunks_count} 个条款块已入向量库</div>`;
    setTimeout(() => {
      document.getElementById("reg-upload-modal").classList.add("hidden");
      loadRegulations();
    }, 800);
  } catch (e) {
    errBox.textContent = e.message;
    errBox.classList.remove("hidden");
    status.innerHTML = "";
  }
});

// ============================================================
// 知识库 — 评价指标 / 问题清单（增强：搜索 + 删除）
// ============================================================
let _indCache = [];

async function loadIndicators() {
  const inds = await api("/indicators");
  State.indicators = inds;
  _indCache = inds;

  // 装填业务分类下拉
  const fcat = document.getElementById("ind-filter-category");
  if (fcat.options.length <= 1) {
    const cats = [...new Set(inds.map(i => i.category).filter(Boolean))].sort();
    fcat.innerHTML = `<option value="">全部业务分类</option>` +
      cats.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
  }
  renderIndicators();
}

function renderIndicators() {
  const search = document.getElementById("ind-search").value.trim().toLowerCase();
  const level = document.getElementById("ind-filter-level").value;
  const category = document.getElementById("ind-filter-category").value;

  let filtered = _indCache;
  if (level) filtered = filtered.filter(i => i.level === level);
  if (category) filtered = filtered.filter(i => i.category === category);
  if (search) {
    filtered = filtered.filter(i =>
      (i.indicator_code || "").toLowerCase().includes(search) ||
      (i.name || "").toLowerCase().includes(search) ||
      (i.category || "").toLowerCase().includes(search) ||
      (i.subcategory || "").toLowerCase().includes(search)
    );
  }

  document.getElementById("ind-count").textContent = `共 ${filtered.length} / ${_indCache.length} 条`;
  const tbody = document.getElementById("indicators-tbody");
  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty-state">
      <div class="empty-state-glyph">⊕</div>
      ${_indCache.length === 0 ? '暂无评价指标，使用右上角「批量导入 JSON」开始' : '当前筛选下无结果'}
    </td></tr>`;
    return;
  }
  const isAdmin = State.user && State.user.role === "super_admin";
  tbody.innerHTML = filtered.map(i => {
    let mats = []; try { mats = JSON.parse(i.required_materials || "[]"); } catch {}
    return `<tr>
      <td><span class="code-id">${esc(i.indicator_code)}</span></td>
      <td><span class="badge badge-gray">${esc(i.level)}</span></td>
      <td>${esc(i.category)}</td>
      <td style="font-weight:500">${esc(i.name)}</td>
      <td class="table-mono">${i.max_score}</td>
      <td class="text-sm text-muted">${esc(mats.join("、")) || '—'}</td>
      <td class="text-right" style="white-space:nowrap">
        <button class="btn btn-ghost btn-sm" onclick="viewIndicator(${i.id})" title="查看详情">${icon("view")}</button>
        ${isAdmin
          ? `<button class="btn btn-danger-ghost btn-sm" onclick="deleteIndicator(${i.id}, '${esc(i.indicator_code)}')" title="删除">${icon("delete")}</button>`
          : ''}
      </td>
    </tr>`;
  }).join("");
}

// 查看评价指标详情
window.viewIndicator = function(id) {
  const ind = _indCache.find(i => i.id === id);
  if (!ind) return;
  let mats = []; try { mats = JSON.parse(ind.required_materials || "[]"); } catch {}

  const rows = [
    ["指标编号", `<span class="code-id">${esc(ind.indicator_code)}</span>`],
    ["层级", `<span class="badge badge-gray">${esc(ind.level)}</span>`],
    ["业务分类", esc(ind.category) || "—"],
    ["子类", esc(ind.subcategory) || "—"],
    ["满分", `<span class="table-mono">${ind.max_score} 分</span>`],
    ["指标描述", esc(ind.description) || "—"],
    ["扣分细则", `<div class="detail-quote" style="margin:0">${esc(ind.deduct_rules) || "—"}</div>`],
    ["常见扣分情形", `<div class="detail-quote" style="margin:0">${esc(ind.common_deductions) || "—"}</div>`],
    ["必需材料", mats.length ? mats.map(m => `<span class="tag">${esc(m)}</span>`).join(" ") : "—"],
    ["入库时间", fmtTime(ind.created_at)],
  ];

  document.getElementById("kbd-title").textContent = ind.name;
  document.getElementById("kbd-code").textContent = ind.indicator_code;
  document.getElementById("kbd-grid").innerHTML = rows.map(([k, v]) =>
    `<dt>${esc(k)}</dt><dd>${v}</dd>`
  ).join("");

  // 单条下载
  const dl = document.getElementById("kbd-download");
  dl.onclick = () => downloadJsonBlob(
    `indicator_${ind.indicator_code}.json`,
    [{
      indicator_code: ind.indicator_code,
      level: ind.level,
      category: ind.category,
      subcategory: ind.subcategory,
      name: ind.name,
      description: ind.description,
      max_score: ind.max_score,
      deduct_rules: ind.deduct_rules,
      common_deductions: ind.common_deductions,
      required_materials: mats,
    }]
  );

  document.getElementById("kb-detail-modal").classList.remove("hidden");
};

window.deleteIndicator = async function(id, code) {
  if (!confirm(`确定删除评价指标「${code}」？`)) return;
  try {
    await api(`/indicators/${id}`, { method: "DELETE" });
    toast("✓ 已删除", "success");
    loadIndicators();
  } catch (e) { toast(e.message, "error"); }
};

let _indSearchTimer;
function bindIndFilters() {
  const s = document.getElementById("ind-search");
  if (s && !s._bound) {
    s._bound = true;
    s.addEventListener("input", () => {
      clearTimeout(_indSearchTimer);
      _indSearchTimer = setTimeout(renderIndicators, 200);
    });
    document.getElementById("ind-filter-level").addEventListener("change", renderIndicators);
    document.getElementById("ind-filter-category").addEventListener("change", renderIndicators);
  }
}
bindIndFilters();

let _ciCache = [];

async function loadCheckItems() {
  const items = await api("/check-items");
  _ciCache = items;
  renderCheckItems();
}

function renderCheckItems() {
  const search = document.getElementById("ci-search").value.trim().toLowerCase();
  const dim = document.getElementById("ci-filter-dim").value;
  const method = document.getElementById("ci-filter-method").value;

  let filtered = _ciCache;
  if (dim) filtered = filtered.filter(x => x.dimension === dim);
  if (method) filtered = filtered.filter(x => x.check_method === method);
  if (search) {
    filtered = filtered.filter(x =>
      (x.item_code || "").toLowerCase().includes(search) ||
      (x.description || "").toLowerCase().includes(search) ||
      (x.subcategory || "").toLowerCase().includes(search)
    );
  }

  document.getElementById("ci-count").textContent = `共 ${filtered.length} / ${_ciCache.length} 条`;
  const tbody = document.getElementById("items-tbody");
  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty-state">
      <div class="empty-state-glyph">⊕</div>
      ${_ciCache.length === 0 ? '暂无条目，请批量导入' : '当前筛选下无结果'}
    </td></tr>`;
    return;
  }
  const isAdmin = State.user && State.user.role === "super_admin";
  tbody.innerHTML = filtered.map(it => `<tr>
    <td><span class="code-id">${esc(it.item_code)}</span></td>
    <td><span class="badge badge-blue">${esc(it.dimension)}</span></td>
    <td>${esc(it.subcategory)}</td>
    <td class="text-sm">${esc(it.description)}</td>
    <td><span class="tag">${esc(checkMethodLabel(it.check_method))}</span></td>
    <td><span class="chip-risk chip-risk-${it.risk_level}">${it.risk_level}</span></td>
    <td class="text-right" style="white-space:nowrap">
      <button class="btn btn-ghost btn-sm" onclick="viewCheckItem(${it.id})" title="查看详情">${icon("view")}</button>
      ${isAdmin
        ? `<button class="btn btn-danger-ghost btn-sm" onclick="deleteCheckItem(${it.id}, '${esc(it.item_code)}')" title="删除">${icon("delete")}</button>`
        : ''}
    </td>
  </tr>`).join("");
}

// 查看问题清单详情
window.viewCheckItem = function(id) {
  const it = _ciCache.find(x => x.id === id);
  if (!it) return;

  let apps = []; try { apps = JSON.parse(it.applicable_indicators || "[]"); } catch {}
  let pats = []; try { pats = JSON.parse(it.common_patterns || "[]"); } catch {}
  let kws = []; try { kws = JSON.parse(it.keywords || "[]"); } catch {}

  const rows = [
    ["条目编号", `<span class="code-id">${esc(it.item_code)}</span>`],
    ["检查维度", `<span class="badge badge-blue">${esc(it.dimension)}</span>`],
    ["子类", esc(it.subcategory) || "—"],
    ["条目描述", `<div class="detail-quote" style="margin:0">${esc(it.description)}</div>`],
    ["检查方法", `<span class="tag">${esc(checkMethodLabel(it.check_method))}</span> ${it.check_method === 'rule' ? '（基于规则关键词匹配）' : '（AI 语义判断）'}`],
    ["风险等级", `<span class="chip-risk chip-risk-${it.risk_level}">${it.risk_level}</span>`],
    ["适用指标", apps.length ? apps.map(c => `<span class="code-id">${esc(c)}</span>`).join("、") : "全部指标"],
    ["常见问题", pats.length ? pats.map(p => `<div class="text-sm">· ${esc(p)}</div>`).join("") : "—"],
    ["关键词", kws.length ? kws.map(k => `<span class="tag">${esc(k)}</span>`).join(" ") : "—"],
    ["启用状态", it.is_active ? '<span class="badge badge-green">启用</span>' : '<span class="badge badge-gray">停用</span>'],
  ];

  document.getElementById("kbd-title").textContent = it.description;
  document.getElementById("kbd-code").textContent = it.item_code;
  document.getElementById("kbd-grid").innerHTML = rows.map(([k, v]) =>
    `<dt>${esc(k)}</dt><dd>${v}</dd>`
  ).join("");

  document.getElementById("kbd-download").onclick = () => downloadJsonBlob(
    `check_item_${it.item_code}.json`,
    [{
      item_code: it.item_code,
      dimension: it.dimension,
      subcategory: it.subcategory,
      description: it.description,
      applicable_indicators: apps,
      risk_level: it.risk_level,
      common_patterns: pats,
      check_method: it.check_method,
      keywords: kws,
    }]
  );

  document.getElementById("kb-detail-modal").classList.remove("hidden");
};

// 通用：导出 JSON 为浏览器下载
function downloadJsonBlob(filename, data) {
  const json = JSON.stringify(data, null, 2);
  const blob = new Blob([json], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// 批量导出当前筛选列表
document.getElementById("export-indicators").addEventListener("click", () => {
  // 用当前筛选后的列表
  const search = (document.getElementById("ind-search").value || "").trim().toLowerCase();
  const level = document.getElementById("ind-filter-level").value;
  const category = document.getElementById("ind-filter-category").value;
  let list = _indCache;
  if (level) list = list.filter(i => i.level === level);
  if (category) list = list.filter(i => i.category === category);
  if (search) {
    list = list.filter(i =>
      (i.indicator_code || "").toLowerCase().includes(search) ||
      (i.name || "").toLowerCase().includes(search) ||
      (i.category || "").toLowerCase().includes(search)
    );
  }
  if (!list.length) { toast("当前筛选下没有可导出条目", "error"); return; }
  const data = list.map(i => {
    let mats = []; try { mats = JSON.parse(i.required_materials || "[]"); } catch {}
    return {
      indicator_code: i.indicator_code,
      level: i.level,
      category: i.category,
      subcategory: i.subcategory,
      name: i.name,
      description: i.description,
      max_score: i.max_score,
      deduct_rules: i.deduct_rules,
      common_deductions: i.common_deductions,
      required_materials: mats,
    };
  });
  const ts = new Date().toISOString().slice(0, 10);
  downloadJsonBlob(`indicators_${ts}_${data.length}items.json`, data);
  toast(`✓ 已导出 ${data.length} 条评价指标`, "success");
});

document.getElementById("export-check-items").addEventListener("click", () => {
  const search = (document.getElementById("ci-search").value || "").trim().toLowerCase();
  const dim = document.getElementById("ci-filter-dim").value;
  const method = document.getElementById("ci-filter-method").value;
  let list = _ciCache;
  if (dim) list = list.filter(x => x.dimension === dim);
  if (method) list = list.filter(x => x.check_method === method);
  if (search) {
    list = list.filter(x =>
      (x.item_code || "").toLowerCase().includes(search) ||
      (x.description || "").toLowerCase().includes(search)
    );
  }
  if (!list.length) { toast("当前筛选下没有可导出条目", "error"); return; }
  const data = list.map(it => {
    let apps = []; try { apps = JSON.parse(it.applicable_indicators || "[]"); } catch {}
    let pats = []; try { pats = JSON.parse(it.common_patterns || "[]"); } catch {}
    let kws = []; try { kws = JSON.parse(it.keywords || "[]"); } catch {}
    return {
      item_code: it.item_code,
      dimension: it.dimension,
      subcategory: it.subcategory,
      description: it.description,
      applicable_indicators: apps,
      risk_level: it.risk_level,
      common_patterns: pats,
      check_method: it.check_method,
      keywords: kws,
    };
  });
  const ts = new Date().toISOString().slice(0, 10);
  downloadJsonBlob(`check_items_${ts}_${data.length}items.json`, data);
  toast(`✓ 已导出 ${data.length} 条问题清单`, "success");
});

window.deleteCheckItem = async function(id, code) {
  if (!confirm(`确定删除问题清单「${code}」？（软删，可在管理端恢复）`)) return;
  try {
    await api(`/check-items/${id}`, { method: "DELETE" });
    toast("✓ 已删除", "success");
    loadCheckItems();
  } catch (e) { toast(e.message, "error"); }
};

let _ciSearchTimer;
function bindCiFilters() {
  const s = document.getElementById("ci-search");
  if (s && !s._bound) {
    s._bound = true;
    s.addEventListener("input", () => {
      clearTimeout(_ciSearchTimer);
      _ciSearchTimer = setTimeout(renderCheckItems, 200);
    });
    document.getElementById("ci-filter-dim").addEventListener("change", renderCheckItems);
    document.getElementById("ci-filter-method").addEventListener("change", renderCheckItems);
  }
}
bindCiFilters();

async function uploadJson(endpoint, file) {
  const fd = new FormData(); fd.append("file", file);
  const tok = getToken();
  const r = await fetch(API + endpoint, {
    method: "POST", headers: { "Authorization": "Bearer " + tok }, body: fd,
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

// ============================================================
// 批量导入（PDF / Word / Excel / JSON）+ 预览确认流程
// ============================================================

let _importState = {
  kind: null,        // "indicators" | "check-items"
  file: null,
  preview: [],
  total: 0,
};

const IMPORT_COLUMNS = {
  "indicators": [
    { key: "indicator_code", label: "编号", w: 70 },
    { key: "category", label: "指标分类", w: 130 },
    { key: "name", label: "指标名称", w: 160 },
    { key: "max_score", label: "标准分", w: 60 },
    { key: "audit_points", label: "核查要点", w: 260, fmt: truncate160 },
    { key: "deduct_rules", label: "扣分规则", w: 260, fmt: truncate160 },
  ],
  "check-items": [
    { key: "item_code", label: "编号", w: 90 },
    { key: "dimension", label: "维度", w: 120 },
    { key: "subcategory", label: "子类", w: 100 },
    { key: "description", label: "描述" },
    { key: "check_method", label: "方法", w: 80, fmt: checkMethodLabel },
    { key: "risk_level", label: "风险", w: 60 },
  ],
};

function tryJsonList(v) {
  try {
    const arr = typeof v === "string" ? JSON.parse(v) : v;
    return Array.isArray(arr) ? arr.join("、") : String(v);
  } catch { return String(v); }
}

function truncate160(v) {
  const s = String(v ?? "");
  return s.length > 160 ? s.slice(0, 160) + "…" : s;
}

// 问题清单 check_method 字段中文化
const CHECK_METHOD_LABEL = {
  rule: "规则匹配",
  llm:  "AI 分析",
};
function checkMethodLabel(m) {
  return CHECK_METHOD_LABEL[m] || (m || "—");
}

async function importDryRun(kind, file) {
  const endpoint = kind === "indicators"
    ? "/indicators/import-from-file?dry_run=true"
    : "/check-items/import-from-file?dry_run=true";
  const fd = new FormData(); fd.append("file", file);
  const tok = getToken();
  const r = await fetch(API + endpoint, {
    method: "POST",
    headers: { "Authorization": "Bearer " + tok },
    body: fd,
  });
  if (!r.ok) {
    const text = await r.text();
    let msg = text;
    try { msg = JSON.parse(text).detail || text; } catch {}
    throw new Error(msg);
  }
  return r.json();
}

async function importConfirm(kind, file) {
  const endpoint = kind === "indicators"
    ? "/indicators/import-from-file?dry_run=false"
    : "/check-items/import-from-file?dry_run=false";
  const fd = new FormData(); fd.append("file", file);
  const tok = getToken();
  const r = await fetch(API + endpoint, {
    method: "POST",
    headers: { "Authorization": "Bearer " + tok },
    body: fd,
  });
  if (!r.ok) {
    const text = await r.text();
    let msg = text;
    try { msg = JSON.parse(text).detail || text; } catch {}
    throw new Error(msg);
  }
  return r.json();
}

function openImportPreview(kind, file, resp) {
  _importState = { kind, file, preview: resp.preview || [], total: resp.total || resp.preview.length };

  const labels = {
    "indicators":  { title: "评价指标 — 导入预览", page: "评价指标" },
    "check-items": { title: "问题清单 — 导入预览", page: "问题清单" },
  };
  document.getElementById("ipm-title").textContent = labels[kind].title;
  document.getElementById("ipm-sub").textContent =
    `文件：${file.name} · 抽取条目：${_importState.total}（预览前 ${_importState.preview.length} 条）`;

  // note 样式：Excel 表头识别 = 绿色（快/准），LLM 抽取 = 蓝色，正则 = 黄色
  const note = String(resp.note || "");
  let kind_color = "info";
  if (note.includes("Excel 表头自动识别")) kind_color = "success";
  else if (note.includes("LLM 抽取")) kind_color = "info";
  else if (note.includes("正则启发式")) kind_color = "warn";
  document.getElementById("ipm-note").innerHTML = note
    ? `<div class="callout callout-${kind_color}">${esc(note)}</div>`
    : "";

  const cols = IMPORT_COLUMNS[kind];
  const thead = document.getElementById("ipm-thead");
  thead.innerHTML = `<tr>${cols.map(c =>
    `<th${c.w ? ` style="width:${c.w}px"` : ''}>${esc(c.label)}</th>`).join("")}</tr>`;

  const tbody = document.getElementById("ipm-tbody");
  if (!_importState.preview.length) {
    tbody.innerHTML = `<tr><td colspan="${cols.length}" class="empty-state">
      <div class="empty-state-glyph">⊕</div>未抽到条目，请检查文件内容或配置 LLM API Key 后重试
    </td></tr>`;
    document.getElementById("ipm-confirm").disabled = true;
  } else {
    tbody.innerHTML = _importState.preview.map(row => `<tr>${cols.map(c => {
      let v = row[c.key];
      if (c.fmt) v = c.fmt(v);
      const txt = v == null ? '—' : String(v);
      return `<td class="text-sm" style="white-space:pre-wrap;line-height:1.5;vertical-align:top">${esc(txt)}</td>`;
    }).join("")}</tr>`).join("");
    document.getElementById("ipm-confirm").disabled = false;
  }
  document.getElementById("ipm-status").innerHTML = "";
  document.getElementById("import-preview-modal").classList.remove("hidden");
}

async function handleImportSelect(kind, ev) {
  const file = ev.target.files[0];
  if (!file) return;
  ev.target.value = "";  // 允许重选同文件
  toast(`正在解析 ${file.name}…`);
  try {
    const resp = await importDryRun(kind, file);
    openImportPreview(kind, file, resp);
  } catch (e) {
    toast(`✗ 解析失败：${e.message}`, "error");
  }
}

document.getElementById("import-indicators").addEventListener("change",
  ev => handleImportSelect("indicators", ev));
document.getElementById("import-items").addEventListener("change",
  ev => handleImportSelect("check-items", ev));

document.getElementById("ipm-confirm").addEventListener("click", async () => {
  const { kind, file } = _importState;
  if (!kind || !file) return;
  const btn = document.getElementById("ipm-confirm");
  const status = document.getElementById("ipm-status");
  btn.disabled = true;
  btn._t = btn.textContent;
  btn.textContent = "导入中…";
  status.innerHTML = `<div class="callout callout-info">正在写入数据库…</div>`;
  try {
    const result = await importConfirm(kind, file);
    const errCount = (result.errors || []).length;
    status.innerHTML = `<div class="callout callout-success">
      ✓ 完成：新建 ${result.created}，跳过 ${result.skipped}${errCount ? `，错误 ${errCount}` : ''}
    </div>`;
    toast(`✓ 已导入 ${result.created} 条${result.skipped ? `（跳过 ${result.skipped}）` : ''}`, "success");
    setTimeout(() => {
      document.getElementById("import-preview-modal").classList.add("hidden");
      if (kind === "indicators") loadIndicators();
      else loadCheckItems();
    }, 1000);
  } catch (e) {
    status.innerHTML = `<div class="callout callout-error">✗ ${esc(e.message)}</div>`;
    toast(`✗ 导入失败：${e.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = btn._t || "确认导入";
  }
});

// ============================================================
// 后台管理控制台
// ============================================================
function setConsoleTab(tab) {
  State.consoleTab = tab;
  document.querySelectorAll(".console-nav-item").forEach(b =>
    b.classList.toggle("active", b.dataset.cnav === tab));
  document.querySelectorAll(".console-panel").forEach(p => p.classList.add("hidden"));
  document.getElementById("console-" + tab).classList.remove("hidden");
  switch (tab) {
    case "llm": loadLLMConfig(); loadVisionConfig(); loadAutoFormReviewConfig(); break;
    case "system": loadSystemInfo(); break;
    case "users": loadUsers(); break;
    case "units": loadUnitsConsole(); break;
    case "audit": loadAuditLogs(); break;
  }
}

document.querySelectorAll(".console-nav-item").forEach(b => {
  b.addEventListener("click", () => setConsoleTab(b.dataset.cnav));
});

// LLM 配置
async function loadLLMConfig() {
  try {
    const cfg = await api("/settings/llm");
    const form = document.getElementById("llm-form");
    form.provider.value = cfg.provider;
    form.model.value = cfg.model;
    form.base_url.value = cfg.base_url;
    form.thinking_mode.value = cfg.thinking_mode;
    form.api_key.value = "";
    document.getElementById("llm-key-hint").textContent = cfg.has_api_key
      ? "✓ 已配置 API Key · 留空表示不修改"
      : "尚未配置 · 请填入 DeepSeek API Key（sk-...）";
    document.getElementById("llm-status").textContent = "";
  } catch (e) { console.error(e); }
}

document.getElementById("llm-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const form = ev.target;
  const submitBtn = form.querySelector('button[type="submit"]');
  const fd = new FormData(form);
  const status = document.getElementById("llm-status");
  const payload = {
    provider: fd.get("provider"), model: fd.get("model"),
    base_url: fd.get("base_url"), thinking_mode: fd.get("thinking_mode"),
  };
  const apiKey = fd.get("api_key");
  if (apiKey !== "") payload.api_key = apiKey.trim();

  // 立即反馈（toast + callout + 按钮 loading）
  status.innerHTML = `<div class="callout callout-info">正在保存配置…</div>`;
  if (submitBtn) {
    submitBtn._origText = submitBtn._origText || submitBtn.textContent;
    submitBtn.disabled = true;
    submitBtn.textContent = "保存中…";
  }
  toast("正在保存 LLM 配置…");

  try {
    const result = await api("/settings/llm", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const provider = result.provider || payload.provider;
    const hasKey = result.has_api_key ? "已配置 API Key" : "未配置 API Key";
    status.innerHTML = `<div class="callout callout-success">✓ 已保存 · ${esc(provider)} · ${esc(hasKey)}</div>`;
    toast(`✓ 已保存：${provider}（${hasKey}）`, "success");
    await loadLLMConfig();
  } catch (e) {
    status.innerHTML = `<div class="callout callout-error">✗ 保存失败：${esc(e.message)}</div>`;
    toast(`✗ 保存失败：${e.message}`, "error");
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = submitBtn._origText || "保存配置";
    }
  }
});

document.getElementById("llm-test").addEventListener("click", async () => {
  const btn = document.getElementById("llm-test");
  const status = document.getElementById("llm-status");
  btn._origText = btn._origText || btn.textContent;
  btn.disabled = true;
  btn.textContent = "测试中…";
  status.innerHTML = `<div class="callout callout-info">正在向 LLM 发送测试请求…</div>`;
  toast("正在测试 LLM 连接…");
  try {
    const r = await api("/settings/llm/test", { method: "POST" });
    if (r.success) {
      const preview = (r.preview || "").slice(0, 60);
      status.innerHTML = `<div class="callout callout-success">✓ ${esc(r.client)} 连接成功${preview ? ' · 响应：' + esc(preview) : ''}</div>`;
      toast(`✓ ${r.client} 连接成功`, "success");
    } else {
      status.innerHTML = `<div class="callout callout-error">✗ ${esc(r.client)}：${esc(r.error)}</div>`;
      toast(`✗ 测试失败：${r.error}`, "error");
    }
  } catch (e) {
    status.innerHTML = `<div class="callout callout-error">✗ ${esc(e.message)}</div>`;
    toast(`✗ ${e.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = btn._origText || "测试连接";
  }
});

// v1.3 Qwen-VL OCR 配置
async function loadVisionConfig() {
  try {
    const cfg = await api("/settings/vision");
    document.getElementById("vision-enabled").checked = !!cfg.enabled;
    document.getElementById("vision-api-key").value = "";  // 永不回显明文，留空表示不修改
    document.getElementById("vision-api-key").placeholder = cfg.api_key
      ? "✓ 已配置 · 留空表示不修改"
      : "尚未配置 · 填入 dashscope sk-...";
    document.getElementById("vision-model").value = cfg.model || "qwen-vl-plus";
    document.getElementById("vision-status").textContent = "";
  } catch (e) {
    console.warn("加载 Vision 配置失败：", e.message);
  }
}

document.getElementById("vision-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const status = document.getElementById("vision-status");
  const submitBtn = ev.target.querySelector('button[type="submit"]');
  const newKey = document.getElementById("vision-api-key").value.trim();
  // 留空表示不修改 api_key：先 GET 现有值，把它带回去（后端是 upsert，全字段必填）
  let existingKey = "";
  if (!newKey) {
    try {
      const cur = await api("/settings/vision");
      existingKey = cur.api_key || "";
    } catch {}
  }
  const payload = {
    enabled: document.getElementById("vision-enabled").checked,
    api_key: newKey || existingKey,
    model: document.getElementById("vision-model").value,
  };
  status.innerHTML = `<div class="callout callout-info">正在保存…</div>`;
  if (submitBtn) submitBtn.disabled = true;
  try {
    await api("/settings/vision", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const keyState = payload.api_key ? "已配置 API key" : "未配 key";
    const enState = payload.enabled ? "已启用" : "未启用";
    status.innerHTML = `<div class="callout callout-success">✓ Vision 配置已保存 · ${esc(enState)} · ${esc(keyState)}</div>`;
    toast(`✓ Qwen-VL 配置已保存（${enState}）`, "success");
    await loadVisionConfig();
  } catch (e) {
    status.innerHTML = `<div class="callout callout-error">✗ 保存失败：${esc(e.message)}</div>`;
    toast(`✗ Qwen-VL 保存失败：${e.message}`, "error");
  } finally {
    if (submitBtn) submitBtn.disabled = false;
  }
});

document.getElementById("vision-test").addEventListener("click", async () => {
  const status = document.getElementById("vision-status");
  const btn = document.getElementById("vision-test");
  const newKey = document.getElementById("vision-api-key").value.trim();
  const model = document.getElementById("vision-model").value;
  // 新 key 优先；为空时后端会从 DB 取
  const payload = { api_key: newKey, model };
  status.innerHTML = `<div class="callout callout-info">正在调 Qwen-VL 测试（5-15 秒）…</div>`;
  toast("正在测试 Qwen-VL 连接…");
  btn.disabled = true;
  btn._origText = btn._origText || btn.textContent;
  btn.textContent = "测试中…";
  try {
    const r = await api("/settings/vision/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (r.success) {
      const preview = r.preview ? ` · 模型回答："${esc(r.preview)}"` : "";
      status.innerHTML = `<div class="callout callout-success">✓ Qwen-VL 连接成功 · ${esc(r.model || model)}${preview}</div>`;
      toast(`✓ Qwen-VL 连接成功`, "success");
    } else {
      status.innerHTML = `<div class="callout callout-error">✗ 连接失败：${esc(r.error || "未知错误")}</div>`;
      toast(`✗ Qwen-VL 测试失败：${r.error}`, "error");
    }
  } catch (e) {
    status.innerHTML = `<div class="callout callout-error">✗ ${esc(e.message)}</div>`;
    toast(`✗ ${e.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = btn._origText || "测试连接";
  }
});

// v1.5 自动形式审查配置
async function loadAutoFormReviewConfig() {
  try {
    const cfg = await api("/settings/auto-form-review");
    document.getElementById("auto-form-review-enabled").checked = !!cfg.enabled;
    document.getElementById("auto-form-review-status").textContent = "";
  } catch (e) {
    console.warn("加载自动审查配置失败：", e.message);
  }
}

document.getElementById("auto-form-review-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const status = document.getElementById("auto-form-review-status");
  const enabled = document.getElementById("auto-form-review-enabled").checked;
  try {
    await api("/settings/auto-form-review", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({enabled}),
    });
    const label = enabled ? "已启用" : "已关闭";
    status.innerHTML = `<div class="callout callout-success">✓ ${label}</div>`;
    toast(`✓ 自动形式审查 ${label}`, "success");
  } catch (e) {
    status.innerHTML = `<div class="callout callout-error">✗ ${esc(e.message)}</div>`;
  }
});

// 系统信息
async function loadSystemInfo() {
  try {
    const h = await api("/health");
    document.getElementById("system-info").innerHTML = `
      <div class="kv-row">
        <div class="kv-key">系统名称</div>
        <div class="kv-value">${esc(h.app)}</div>
      </div>
      <div class="kv-row">
        <div class="kv-key">服务状态</div>
        <div class="kv-value"><span class="badge badge-green">● 正常运行</span></div>
      </div>
      <div class="kv-row">
        <div class="kv-key">LLM 默认服务商</div>
        <div class="kv-value"><span class="tag">${esc(h.llm_default_provider)}</span></div>
      </div>
      <div class="kv-row">
        <div class="kv-key">Embedding 引擎</div>
        <div class="kv-value"><span class="tag">${esc(h.embedder)}</span></div>
      </div>
      <div class="kv-row">
        <div class="kv-key">向量库</div>
        <div class="kv-value"><span class="tag">${esc(h.vector_store)}</span></div>
      </div>
      <div class="kv-row">
        <div class="kv-key">前端版本</div>
        <div class="kv-value text-muted">v3.0 · 苹果系统级 UI</div>
      </div>`;
  } catch (e) { console.error(e); }
}

// 用户
async function loadUsers() {
  const users = await api("/users");
  const meId = State.user && State.user.id;
  document.getElementById("users-tbody").innerHTML = users.map(u => {
    const isSelf = u.id === meId;
    const isDeleted = u.username.startsWith("deleted_");
    const activeBadge = u.is_active
      ? '<span class="badge badge-green">启用</span>'
      : (isDeleted ? '<span class="badge badge-red">已删除</span>' : '<span class="badge badge-gray">停用</span>');
    const actions = [];
    actions.push(`<button class="btn btn-ghost btn-sm" onclick="openChangePwd(${u.id}, '${esc(u.username)}')" title="改密码">${icon("key")}</button>`);
    if (!isSelf && !isDeleted) {
      if (u.is_active) {
        actions.push(`<button class="btn btn-ghost btn-sm" onclick="toggleUserActive(${u.id}, false)" title="停用">${icon("pause")}</button>`);
      } else {
        actions.push(`<button class="btn btn-ghost btn-sm" onclick="toggleUserActive(${u.id}, true)" title="启用">${icon("play")}</button>`);
      }
      actions.push(`<button class="btn btn-danger-ghost btn-sm" onclick="deleteUser(${u.id}, '${esc(u.username)}')" title="软删">${icon("delete")}</button>`);
    }
    return `<tr>
      <td><span class="code-id">#${pad(u.id)}</span></td>
      <td style="font-weight:500">${esc(u.username)}${isSelf ? ' <span class="text-xs text-faint">(你)</span>' : ''}</td>
      <td>${roleBadge(u.role)}</td>
      <td>${esc(u.full_name || "—")}</td>
      <td>${activeBadge}</td>
      <td class="text-right" style="white-space:nowrap">${actions.join(" ")}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="6" class="empty-state">暂无用户</td></tr>`;
}

// 改密码 / 启停 / 删除 — 全局处理器
window.openChangePwd = function(userId, username) {
  const isSelf = State.user && State.user.id === userId;
  const isAdmin = State.user && State.user.role === "super_admin";
  const needOld = !isAdmin && isSelf;
  const modal = document.getElementById("pwd-modal");
  document.getElementById("pwd-title").textContent =
    isSelf ? "修改我的密码" : `重置 ${username} 的密码`;
  document.getElementById("pwd-target-id").value = userId;
  document.getElementById("pwd-form").reset();
  document.getElementById("pwd-old-row").style.display = needOld ? "" : "none";
  document.getElementById("pwd-status").innerHTML = "";
  document.getElementById("pwd-old-input").required = needOld;
  modal.classList.remove("hidden");
};

window.toggleUserActive = async function(userId, active) {
  const verb = active ? "启用" : "停用";
  if (!confirm(`确定${verb}此用户？\n${active ? "" : "停用后该用户当前登录态将立即失效。"}`)) return;
  try {
    await api(`/users/${userId}/activate`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active }),
    });
    toast(`✓ 已${verb}`, "success");
    loadUsers();
  } catch (e) { toast(e.message, "error"); }
};

window.deleteUser = async function(userId, username) {
  if (!confirm(`确定删除用户 ${username}？\n\n· 软删（操作日志中保留）\n· 该用户立即无法登录\n· 用户名会加 deleted_ 前缀\n\n此操作不可恢复。`)) return;
  try {
    await api(`/users/${userId}`, { method: "DELETE" });
    toast("✓ 用户已删除", "success");
    loadUsers();
  } catch (e) { toast(e.message, "error"); }
};

// 改密码表单提交
document.getElementById("pwd-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const userId = parseInt(document.getElementById("pwd-target-id").value);
  const newPwd = fd.get("new_password");
  const confirmPwd = fd.get("new_password_confirm");
  const oldPwd = fd.get("old_password");
  const status = document.getElementById("pwd-status");

  if (newPwd !== confirmPwd) {
    status.innerHTML = `<div class="callout callout-warn">两次输入的新密码不一致</div>`;
    return;
  }
  if (newPwd.length < 6) {
    status.innerHTML = `<div class="callout callout-warn">密码至少 6 位</div>`;
    return;
  }

  try {
    const payload = { new_password: newPwd };
    if (oldPwd) payload.old_password = oldPwd;
    await api(`/users/${userId}/password`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    document.getElementById("pwd-modal").classList.add("hidden");
    const isSelf = State.user && State.user.id === userId;
    toast(`✓ 密码已修改${isSelf ? "，请重新登录" : ""}`, "success");
    if (isSelf) {
      // 改自己密码 → token 已被吊销 → 退出
      setToken(""); State.user = null;
      setTimeout(() => showLogin("密码已修改，请用新密码登录"), 500);
    } else {
      // 改别人的密码（管理员场景）→ 刷新用户列表
      if (typeof loadUsers === "function") loadUsers();
    }
  } catch (e) {
    status.innerHTML = `<div class="callout callout-error">✗ ${esc(e.message)}</div>`;
  }
});

function roleBadge(r) {
  const map = {
    super_admin: ['badge badge-brand', '超级管理员'],
    auditor:     ['badge badge-blue',  '审查员'],
    unit:        ['badge badge-orange','被检查单位'],
    readonly:    ['badge badge-gray',  '只读'],
  };
  const [cls, label] = map[r] || ['badge badge-gray', r];
  return `<span class="${cls}">${label}</span>`;
}

document.getElementById("user-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const status = document.getElementById("user-form-status");
  try {
    await api("/users", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: fd.get("username"), password: fd.get("password"),
        role: fd.get("role"), full_name: fd.get("full_name") || "",
      }),
    });
    status.innerHTML = `<div class="callout callout-success">✓ 用户已创建</div>`;
    ev.target.reset();
    loadUsers();
  } catch (e) {
    status.innerHTML = `<div class="callout callout-error">✗ ${esc(e.message)}</div>`;
  }
});

// 单位
async function loadUnitsConsole() {
  const units = await api("/units");
  document.getElementById("units-tbody").innerHTML = units.map(u => `
    <tr>
      <td><span class="code-id">#${pad(u.id)}</span></td>
      <td style="font-weight:500">${esc(u.name)}</td>
      <td class="text-muted">${esc(u.code || "—")}</td>
      <td><span class="badge badge-gray">${esc(u.level)}</span></td>
      <td class="text-sm text-muted">${fmtTime(u.created_at)}</td>
      <td class="text-right">
        <button class="btn btn-danger-ghost btn-sm" onclick="deleteUnit(${u.id}, '${esc(u.name).replace(/'/g, "\\'")}')" title="删除单位">${icon("delete")}</button>
      </td>
    </tr>`).join("") || `<tr><td colspan="6" class="empty-state">暂无单位</td></tr>`;
}

window.deleteUnit = async function(unitId, name) {
  if (!confirm(`确定删除单位「${name}」？\n\n如有关联任务必须先删除任务。`)) return;
  try {
    await api(`/units/${unitId}`, { method: "DELETE" });
    toast(`✓ 已删除单位「${name}」`, "success");
    await loadUnitsConsole();
  } catch (e) {
    toast(`✗ ${e.message}`, "error");
  }
};

// 单位批量导入（v1.1）：Excel/CSV → POST /units/import-from-file
document.getElementById("import-units").addEventListener("change", async ev => {
  const f = ev.target.files && ev.target.files[0];
  if (!f) return;
  const fd = new FormData(); fd.append("file", f);
  try {
    const r = await fetch(API + "/units/import-from-file", {
      method: "POST",
      headers: { "Authorization": "Bearer " + getToken() },
      body: fd,
    });
    const body = await r.json();
    if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
    const errs = (body.errors || []).length;
    toast(
      `✓ 单位批量导入：总 ${body.total} · 入库 ${body.inserted} · 跳过 ${body.skipped}` +
      (errs ? ` · 错误 ${errs}` : ""),
      "success",
    );
    await loadUnitsConsole();
  } catch (e) {
    toast(`✗ ${e.message}`, "error");
  } finally {
    ev.target.value = "";  // 允许相同文件再次选择
  }
});

document.getElementById("unit-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const status = document.getElementById("unit-form-status");
  try {
    await api("/units", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: fd.get("name"), code: fd.get("code"), level: fd.get("level"),
      }),
    });
    status.innerHTML = `<div class="callout callout-success">✓ 单位已创建</div>`;
    ev.target.reset();
    loadUnitsConsole();
  } catch (e) {
    status.innerHTML = `<div class="callout callout-error">✗ ${esc(e.message)}</div>`;
  }
});

// 审计日志
async function loadAuditLogs() {
  const logs = await api("/audit-logs?limit=100");
  document.getElementById("audit-tbody").innerHTML = logs.map(l => `
    <tr>
      <td class="text-sm text-muted">${fmtTime(l.created_at)}</td>
      <td style="font-weight:500">${esc(l.username || "—")}</td>
      <td><span class="tag">${esc(l.action)}</span></td>
      <td class="text-sm">${esc(l.target_type)}${l.target_id ? ' #' + l.target_id : ''}</td>
      <td class="text-sm text-muted">${esc(l.detail || "—")}</td>
    </tr>`).join("") || `<tr><td colspan="5" class="empty-state">暂无日志</td></tr>`;
}
document.getElementById("refresh-audit").addEventListener("click", loadAuditLogs);

// ============================================================
// 认证 & 启动
// ============================================================
function showLogin(msg) {
  document.getElementById("app").classList.add("hidden");
  document.getElementById("login-shell").classList.remove("hidden");
  const err = document.getElementById("login-error");
  if (msg) { err.textContent = msg; err.classList.remove("hidden"); }
  else { err.classList.add("hidden"); }
}
function hideLogin() {
  document.getElementById("login-shell").classList.add("hidden");
  document.getElementById("app").classList.remove("hidden");
}

function renderUserCard() {
  const box = document.getElementById("user-card");
  if (!State.user) { box.innerHTML = ""; return; }
  const name = State.user.full_name || State.user.username;
  box.innerHTML = `
    <div class="user-card">
      <div class="user-avatar">${initial(name)}</div>
      <div class="user-meta">
        <div class="user-name">${esc(name)}</div>
        <div class="user-role">${esc(State.roleLabel)}</div>
      </div>
      <button class="btn-logout-icon" id="btn-changepwd" title="改密码">${icon("key")}</button>
      <button class="btn-logout-icon" id="btn-logout" title="登出">
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
          <path d="M6 3H3v10h3 M11 11l3-3-3-3 M14 8H6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
    </div>`;
  document.getElementById("btn-changepwd").addEventListener("click", () => {
    openChangePwd(State.user.id, State.user.username);
  });
  document.getElementById("btn-logout").addEventListener("click", async () => {
    try { await api("/auth/logout", { method: "POST" }); } catch {}
    setToken(""); State.user = null;
    showLogin();
  });

  // 按角色显隐侧栏每一条导航项
  document.querySelectorAll(".nav-link").forEach(btn => {
    const route = btn.dataset.route;
    const visible = isRouteAllowed(route, State.user);
    btn.style.display = visible ? "" : "none";
  });
  // 管理分组：里面所有项都不可见时整段隐藏
  const adminSection = document.getElementById("nav-admin-section");
  const adminVisible = isRouteAllowed("console", State.user);
  adminSection.style.display = adminVisible ? "" : "none";
  // 知识库分组：里面所有项都不可见时整段隐藏
  const kbSection = document.querySelector('[data-nav-group="knowledge"]');
  if (kbSection) {
    const kbVisible = isRouteAllowed("indicators", State.user) ||
                      isRouteAllowed("check-items", State.user);
    kbSection.style.display = kbVisible ? "" : "none";
  }
}

document.getElementById("login-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  try {
    const r = await fetch(API + "/auth/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: fd.get("username"), password: fd.get("password") }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: "登录失败" }));
      throw new Error(err.detail || "登录失败");
    }
    const data = await r.json();
    setToken(data.token);
    State.user = data.user;
    State.roleLabel = data.role_label;
    hideLogin();
    renderUserCard();
    if (!location.hash) location.hash = "#/dashboard";
    handleRoute();
  } catch (e) { showLogin(e.message); }
});

async function bootstrap() {
  if (getToken()) {
    try {
      const data = await api("/auth/me");
      State.user = data.user;
      State.roleLabel = data.role_label;
      hideLogin();
      renderUserCard();
      if (!location.hash) location.hash = "#/dashboard";
      handleRoute();
      return;
    } catch {}
  }
  showLogin();
}
bootstrap();

// ============================================================
// v1.5 材料批量删除（checkbox + 顶部按钮）
// ============================================================
function _updateBatchDelButton() {
  const checked = document.querySelectorAll('input.material-select:checked').length;
  const btn = document.getElementById("batch-delete-materials");
  const cnt = document.getElementById("batch-del-count");
  if (cnt) cnt.textContent = checked;
  if (btn) btn.disabled = checked === 0;
}

document.addEventListener("change", (ev) => {
  if (ev.target && ev.target.matches && ev.target.matches("input.material-select")) {
    _updateBatchDelButton();
  }
  if (ev.target && ev.target.id === "material-select-all") {
    document.querySelectorAll('input.material-select').forEach(cb => {
      cb.checked = ev.target.checked;
    });
    _updateBatchDelButton();
  }
});

document.addEventListener("click", async (ev) => {
  if (!ev.target || !ev.target.closest) return;
  const btn = ev.target.closest("#batch-delete-materials");
  if (!btn) return;
  ev.preventDefault();
  const ids = Array.from(
    document.querySelectorAll('input.material-select:checked')
  ).map(cb => parseInt(cb.dataset.materialId, 10));
  if (!ids.length) return;
  if (!confirm(`确定删除选中的 ${ids.length} 份材料？\n（被其它任务引用的物理文件会保留）`)) return;
  try {
    const r = await api("/materials/batch-delete", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({material_ids: ids}),
    });
    toast(`✓ 已删除 ${r.deleted} 份（物理删 ${r.deleted_physical} 留 ${r.kept_physical}）`,
          "success");
    if (typeof loadTaskWorkspace === "function" && State.taskId) {
      await loadTaskWorkspace(State.taskId);
    }
  } catch (e) {
    toast(`✗ ${e.message}`, "error");
  }
});
