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
    return new Date(s).toLocaleString("zh-CN", {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
    });
  } catch { return s; }
}
function pad(n) { return String(n).padStart(2, "0"); }
function initial(s) { return (s || "?").slice(0, 1).toUpperCase(); }

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
        <tr onclick="navigate('#/tasks/${t.id}')" class="is-row-button">
          <td><span class="code-id">#${pad(t.id)}</span></td>
          <td style="font-weight:500">${esc(unit ? unit.name : "—")}</td>
          <td>${esc(t.name)}</td>
          <td class="table-mono">${t.eval_year}</td>
          <td>${statusBadge(t.status)}</td>
          <td class="text-sm text-muted">${esc(t.summary || "—")}</td>
          <td class="row-arrow text-right">→</td>
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
    const sel = document.getElementById("ct-unit-select");
    sel.innerHTML = `<option value="">— 选择单位 —</option>` +
      units.map(u => `<option value="${u.id}">${esc(u.name)}</option>`).join("");

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
    document.getElementById("ct-unit-select").value = "";
    document.getElementById("ct-indicator-picker").classList.add("hidden");
  } catch (e) { toast(e.message, "error"); }
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
    const sel = document.getElementById("ct-unit-select");
    const opt = document.createElement("option");
    opt.value = unit.id; opt.textContent = unit.name; opt.selected = true;
    sel.appendChild(opt);
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

  try {
    const task = await api("/tasks", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        unit_id: parseInt(fd.get("unit_id")),
        name: fd.get("name"),
        eval_year: parseInt(fd.get("eval_year")),
        scope,
        selected_indicator_ids: selectedIds,
      }),
    });
    document.getElementById("create-task-modal").classList.add("hidden");
    const scopeLbl = scope === "all" ? "全部指标" : `${selectedIds.length} 个指标`;
    toast(`✓ 任务 #${pad(task.id)} 已创建（${scopeLbl}）`, "success");
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

    document.getElementById("tw-task-id").textContent = `任务 #${pad(detail.task.id)}`;
    document.getElementById("tw-title").textContent = detail.task.name;
    document.getElementById("tw-meta").innerHTML =
      `${esc(detail.unit.name)} · ${detail.task.eval_year} 年度 · ${statusBadge(detail.task.status)}`;

    document.getElementById("tw-count-materials").textContent = detail.materials.length;
    document.getElementById("tw-count-findings").textContent = detail.findings.length;

    renderTaskActions(detail.task);
    renderSubtab();
  } catch (e) { toast(e.message, "error"); }
}

function renderTaskActions(task) {
  const box = document.getElementById("tw-actions");
  const acts = [];
  if (task.status === "ai_done" || task.status === "reviewing") {
    acts.push(`<button class="btn btn-success" onclick="finalizeTask()">✓ 完成复核，定稿</button>`);
  }
  if (["ai_done", "reviewing", "finalized", "archived"].includes(task.status)) {
    acts.push(`<button class="btn btn-secondary" onclick="downloadTaskReport()">导出 Word 报告</button>`);
  }
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
}

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

  const byType = {};
  findings.forEach(f => byType[f.finding_type] = (byType[f.finding_type] || 0) + 1);
  const breakdown = document.getElementById("tw-dimension-breakdown");
  if (Object.keys(byType).length === 0) {
    breakdown.innerHTML = `<div class="empty-state" style="grid-column:1/-1">尚无核查发现</div>`;
  } else {
    breakdown.innerHTML = Object.entries(byType).map(([k, v]) => `
      <div style="padding:16px;background:var(--bg);border-radius:10px">
        <div class="text-xs text-faint">${esc(k)}</div>
        <div style="font-size:22px;font-weight:700;margin-top:4px;letter-spacing:-0.02em">${v}</div>
      </div>`).join("");
  }
}

function renderMaterials() {
  const d = State.taskDetail;
  const indSel = document.getElementById("md-indicator");
  indSel.innerHTML = `<option value="">— 不绑定（归入共享池）—</option>` +
    State.indicators.map(i =>
      `<option value="${i.id}">[${esc(i.indicator_code)}] ${esc(i.name)}</option>`).join("");

  const tbody = document.getElementById("tw-materials-tbody");
  if (!d.materials.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="empty-state">
      <div class="empty-state-glyph">⊕</div>尚未上传材料</td></tr>`;
    return;
  }
  tbody.innerHTML = d.materials.map(m => {
    const ind = State.indicators.find(i => i.id === m.indicator_id);
    let ke = {};
    try { ke = JSON.parse(m.key_elements || "{}"); } catch {}
    const badges = [
      ke.has_official_seal ? `<span class="badge badge-green">公章</span>` : `<span class="badge badge-red">无公章</span>`,
      ke.has_signature ? `<span class="badge badge-green">签字</span>` : `<span class="badge badge-orange">无签字</span>`,
      ke.issue_year ? `<span class="tag">${ke.issue_year}</span>` : `<span class="badge badge-red">无日期</span>`,
      ke.is_draft ? `<span class="badge badge-red">草稿</span>` : '',
      ke.document_number ? `<span class="tag">${esc(ke.document_number)}</span>` : '',
    ].filter(Boolean).join(" ");
    return `<tr>
      <td><span class="code-id">#${pad(m.id)}</span></td>
      <td style="font-weight:500">${esc(m.file_name)}</td>
      <td>${ind ? `<span class="code-id">${esc(ind.indicator_code)}</span> ${esc(ind.name)}` : '<span class="text-muted">未绑定</span>'}</td>
      <td><div class="flex gap-1" style="flex-wrap:wrap">${badges}</div></td>
    </tr>`;
  }).join("");
}

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
    status.innerHTML = `<div class="callout callout-success">✓ 已上传并自动抽取 key_elements</div>`;
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
        // 不绑定 indicator_id → 归入共享池
        const tok = getToken();
        const r = await fetch(`${API}/tasks/${State.taskId}/materials`, {
          method: "POST", headers: { "Authorization": "Bearer " + tok }, body: fd,
        });
        if (!r.ok) throw new Error(await r.text());
        icon.innerHTML = '<span style="color:var(--green)">✓</span>';
        msg.textContent = "✓ 已上传";
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
    toast(`✓ 批量上传完成：${ok} 成功 / ${fail} 失败`, ok > 0 ? "success" : "error");
  }
  await loadTaskWorkspace(State.taskId);
}

document.getElementById("mfp-cancel").addEventListener("click", () => {
  MD_FOLDER.cancelled = true;
  document.getElementById("mfp-cancel").disabled = true;
});

document.getElementById("tw-run-btn").addEventListener("click", async () => {
  if (!State.taskDetail.materials.length) { toast("请先上传材料", "error"); return; }
  toast("AI 核查中…可能耗时数十秒");
  try {
    await api(`/tasks/${State.taskId}/run`, { method: "POST" });
    for (let i = 0; i < 60; i++) {
      const d = await api(`/tasks/${State.taskId}`);
      if (d.task.status !== "running") {
        State.taskDetail = d;
        toast(d.task.summary, "success");
        await loadTaskWorkspace(State.taskId);
        State.subtab = "findings";
        document.querySelectorAll('.subnav-item').forEach(x =>
          x.classList.toggle("active", x.dataset.subtab === "findings"));
        renderSubtab();
        return;
      }
      await new Promise(r => setTimeout(r, 1000));
    }
  } catch (e) { toast(e.message, "error"); }
});

// ============================================================
// Findings 分栏审阅
// ============================================================
function renderFindings() {
  const d = State.taskDetail;
  const findings = d.findings;

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

  listBox.innerHTML = filtered.map(f => {
    const isActive = f.id === State.activeFindingId;
    return `
      <div class="finding-row finding-row-${f.severity} ${isActive ? 'is-active' : ''}" data-id="${f.id}">
        <div class="finding-row-desc">${esc(f.description.slice(0, 100))}${f.description.length > 100 ? '…' : ''}</div>
        <div class="finding-row-meta">
          <span class="chip-risk chip-risk-${f.severity}">${f.severity}</span>
          <span class="tag">${esc(f.finding_type)}</span>
          ${reviewBadge(f.review_status)}
        </div>
      </div>`;
  }).join("");

  listBox.querySelectorAll(".finding-row").forEach(row => {
    row.addEventListener("click", () => {
      const id = parseInt(row.dataset.id);
      State.activeFindingId = id;
      renderFindings();
    });
  });

  if (!State.activeFindingId || !filtered.find(f => f.id === State.activeFindingId)) {
    State.activeFindingId = filtered[0].id;
  }
  renderFindingDetail(filtered.find(f => f.id === State.activeFindingId));
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
      <dd>${material ? esc(material.file_name) : '<span class="text-muted">—</span>'}</dd>
      <dt>具体位置</dt>
      <dd>${esc(f.evidence_location || '—')}</dd>
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
            <a href="${API}/regulations/${r.id}/download" target="_blank" class="btn btn-ghost btn-sm" title="下载">↓</a>
            ${isAdmin ? `<button class="btn btn-danger-ghost btn-sm" onclick="deleteRegulation(${r.id}, '${esc(r.title)}')" title="删除">✕</button>` : ''}
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
      <td class="text-right">
        ${isAdmin
          ? `<button class="btn btn-danger-ghost btn-sm" onclick="deleteIndicator(${i.id}, '${esc(i.indicator_code)}')">✕</button>`
          : ''}
      </td>
    </tr>`;
  }).join("");
}

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
    <td><span class="tag">${esc(it.check_method)}</span></td>
    <td><span class="chip-risk chip-risk-${it.risk_level}">${it.risk_level}</span></td>
    <td class="text-right">
      ${isAdmin
        ? `<button class="btn btn-danger-ghost btn-sm" onclick="deleteCheckItem(${it.id}, '${esc(it.item_code)}')">✕</button>`
        : ''}
    </td>
  </tr>`).join("");
}

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
    { key: "indicator_code", label: "指标编号", w: 90 },
    { key: "level", label: "层级", w: 60 },
    { key: "category", label: "分类", w: 110 },
    { key: "name", label: "名称" },
    { key: "max_score", label: "满分", w: 60 },
    { key: "required_materials", label: "必需材料", w: 180, fmt: tryJsonList },
  ],
  "check-items": [
    { key: "item_code", label: "编号", w: 90 },
    { key: "dimension", label: "维度", w: 120 },
    { key: "subcategory", label: "子类", w: 100 },
    { key: "description", label: "描述" },
    { key: "check_method", label: "方法", w: 70 },
    { key: "risk_level", label: "风险", w: 60 },
  ],
};

function tryJsonList(v) {
  try {
    const arr = typeof v === "string" ? JSON.parse(v) : v;
    return Array.isArray(arr) ? arr.join("、") : String(v);
  } catch { return String(v); }
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

  document.getElementById("ipm-note").innerHTML = `<div>${esc(resp.note || "")}</div>`;

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
      return `<td class="text-sm">${esc(v == null ? '—' : String(v))}</td>`;
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
    case "llm": loadLLMConfig(); break;
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
  document.getElementById("users-tbody").innerHTML = users.map(u => `
    <tr>
      <td><span class="code-id">#${pad(u.id)}</span></td>
      <td style="font-weight:500">${esc(u.username)}</td>
      <td>${roleBadge(u.role)}</td>
      <td>${esc(u.full_name || "—")}</td>
      <td>${u.is_active ? '<span class="badge badge-green">启用</span>' : '<span class="badge badge-gray">停用</span>'}</td>
    </tr>`).join("") || `<tr><td colspan="5" class="empty-state">暂无用户</td></tr>`;
}

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
    </tr>`).join("") || `<tr><td colspan="5" class="empty-state">暂无单位</td></tr>`;
}

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
      <button class="btn-logout-icon" id="btn-logout" title="登出">
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
          <path d="M6 3H3v10h3 M11 11l3-3-3-3 M14 8H6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
    </div>`;
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
