// ============================================================
// 内控评价智能审核系统 · 前端应用
// 设计：左侧固定导航 + Hash 路由 + 任务工作台子视图 + Finding 分栏审阅
// ============================================================

const API = "/api";
const TOKEN_KEY = "audit.token";

const State = {
  user: null,
  roleLabel: "",
  units: [],
  indicators: [],
  tasks: [],
  // 任务工作台
  taskId: null,
  taskDetail: null,
  subtab: "overview",
  // Finding 审阅
  findingFilter: "all",
  activeFindingId: null,
};

// ============================================================
// 工具
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
    throw new Error(`${msg || r.statusText}`);
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
    const d = new Date(s);
    return d.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  } catch { return s; }
}
function pad(n) { return String(n).padStart(2, "0"); }

function toast(msg, kind = "info") {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "toast" + (kind === "success" ? " toast-success" : kind === "error" ? " toast-error" : "");
  setTimeout(() => t.classList.add("hidden"), 3000);
  t.classList.remove("hidden");
}

// ============================================================
// 路由（hash-based）
// ============================================================
const ROUTES = ["dashboard", "tasks", "indicators", "check-items",
                "users", "audit-logs", "settings"];

function parseHash() {
  const h = (location.hash || "#/dashboard").replace(/^#\/?/, "");
  const [path, query = ""] = h.split("?");
  const qp = new URLSearchParams(query);
  // task workspace: tasks/:id?sub=findings
  const m = path.match(/^tasks\/(\d+)$/);
  if (m) return {
    route: "task-workspace",
    params: { id: parseInt(m[1]), sub: qp.get("sub") || "overview" }
  };
  const route = ROUTES.includes(path) ? path : "dashboard";
  return { route, params: {} };
}

function navigate(hash) {
  if (location.hash !== hash) location.hash = hash;
}

async function handleRoute() {
  const { route, params } = parseHash();
  // 隐藏所有 page-section
  document.querySelectorAll(".page-section").forEach(s => s.classList.add("hidden"));

  // 高亮侧栏
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
    case "indicators": await loadIndicators(); break;
    case "check-items": await loadCheckItems(); break;
    case "users": await loadUsers(); break;
    case "audit-logs": await loadAuditLogs(); break;
    case "settings": await loadSettings(); break;
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

    // 统计卡
    const findings_pending = tasks
      .filter(t => t.status === "ai_done")
      .reduce((acc, t) => acc + parseStats(t.stats).findings_total, 0);
    const statsBox = document.getElementById("dash-stats");
    statsBox.innerHTML = `
      ${statCard("被检查单位", units.length, "已纳入复核", 1)}
      ${statCard("核查任务", tasks.length, `进行中 ${tasks.filter(t => t.status !== 'finalized').length}`, 2)}
      ${statCard("评价指标", indicators.length, "已入库", 3)}
      ${statCard("问题清单", items.length, "AI 考题", 4)}
    `;

    // 待我处理 — 那些 ai_done 的任务，意味着等审查员复核
    const pending = tasks.filter(t => t.status === "ai_done");
    const pendingBox = document.getElementById("dash-pending");
    if (!pending.length) {
      pendingBox.innerHTML = `<div class="empty-state"><div class="empty-state-glyph">⌬</div>暂无待复核任务</div>`;
    } else {
      pendingBox.innerHTML = pending.slice(0, 6).map((t, i) => {
        const unit = units.find(u => u.id === t.unit_id);
        const stats = parseStats(t.stats);
        return `
          <div class="marginalia-item" onclick="navigate('#/tasks/${t.id}')">
            <div class="marginalia-num">${pad(i + 1)}</div>
            <div>
              <div class="serif" style="font-size:14px;font-weight:600">${esc(t.name)}</div>
              <div class="text-xs muted mt-1">${esc(unit ? unit.name : "—")} · ${t.eval_year} 年度</div>
              <div class="text-xs mt-2" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
                <span class="stamp stamp-seal">AI 初核完成</span>
                <span class="text-xs muted">共 ${stats.findings_total || 0} 条疑点</span>
              </div>
            </div>
          </div>`;
      }).join("");
    }

    // 最近任务表
    document.getElementById("dash-tasks-tbody").innerHTML = tasks.slice(0, 6).map(t => {
      const unit = units.find(u => u.id === t.unit_id);
      return `
        <tr onclick="navigate('#/tasks/${t.id}')" class="is-row-button">
          <td class="table-mono-id">#${pad(t.id)}</td>
          <td class="serif">${esc(unit ? unit.name : "—")}</td>
          <td>${statusStamp(t.status)}</td>
          <td class="text-xs muted">${esc(t.summary || "—")}</td>
        </tr>`;
    }).join("") || `<tr><td colspan="4" class="empty-state">暂无任务</td></tr>`;

    document.getElementById("dash-system-status").textContent =
      `${health.app} · LLM ${health.llm_default_provider} · 向量 ${health.vector_store}`;
  } catch (e) {
    console.error(e);
  }
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

function statusStamp(status) {
  const map = {
    pending:    ['stamp stamp-ink',  '待开始'],
    running:    ['stamp stamp-ochre','核查中'],
    ai_done:    ['stamp stamp-seal', 'AI 初核'],
    reviewing:  ['stamp stamp-ochre','复核中'],
    finalized:  ['stamp stamp-sage', '已定稿'],
    archived:   ['stamp stamp-ink',  '已归档'],
    failed:     ['stamp stamp-seal', '失败'],
  };
  const [cls, label] = map[status] || ['stamp stamp-ink', status];
  return `<span class="${cls}">${label}</span>`;
}

// 工作台快捷创建
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
        <div class="empty-state-glyph">◈</div>暂无任务，点击右上角「＋ 新建任务」开始。
      </td></tr>`;
      return;
    }
    tbody.innerHTML = tasks.map(t => {
      const unit = units.find(u => u.id === t.unit_id);
      return `
        <tr onclick="navigate('#/tasks/${t.id}')" class="is-row-button">
          <td class="table-mono-id">#${pad(t.id)}</td>
          <td class="serif">${esc(unit ? unit.name : "—")}</td>
          <td>${esc(t.name)}</td>
          <td class="code">${t.eval_year}</td>
          <td>${statusStamp(t.status)}</td>
          <td class="text-xs muted">${esc(t.summary || "—")}</td>
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
    const units = await api("/units");
    State.units = units;
    const sel = document.getElementById("ct-unit-select");
    sel.innerHTML = `<option value="">— 选择单位 —</option>` +
      units.map(u => `<option value="${u.id}">${esc(u.name)}</option>`).join("");
    document.getElementById("create-task-modal").classList.remove("hidden");
    document.getElementById("ct-new-unit-form").classList.add("hidden");
    document.getElementById("ct-error").classList.add("hidden");
    document.getElementById("task-create-form").reset();
    document.getElementById("ct-unit-select").value = "";
  } catch (e) { toast(e.message, "error"); }
}

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
    }, 1500);
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
  try {
    const task = await api("/tasks", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        unit_id: parseInt(fd.get("unit_id")),
        name: fd.get("name"),
        eval_year: parseInt(fd.get("eval_year")),
      }),
    });
    document.getElementById("create-task-modal").classList.add("hidden");
    toast(`✓ 任务 #${pad(task.id)} 已创建`, "success");
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
      api(`/tasks/${taskId}`),
      api("/indicators"),
    ]);
    State.taskDetail = detail;
    State.indicators = indicators;

    document.getElementById("tw-task-id").textContent = `任务 #${pad(detail.task.id)}`;
    document.getElementById("tw-title").textContent = detail.task.name;
    document.getElementById("tw-meta").innerHTML =
      `${esc(detail.unit.name)} <span class="muted">·</span> ${detail.task.eval_year} 年度 <span class="muted">·</span> ${statusStamp(detail.task.status)}`;

    document.getElementById("tw-count-materials").textContent = detail.materials.length;
    document.getElementById("tw-count-findings").textContent = detail.findings.length;

    // 操作区按钮（按状态显示）
    renderTaskActions(detail.task);

    // 默认展示当前子 tab
    renderSubtab();
  } catch (e) {
    toast(e.message, "error");
  }
}

function renderTaskActions(task) {
  const box = document.getElementById("tw-actions");
  const acts = [];
  if (task.status === "pending" || task.status === "running") {
    // 引导上传材料
  }
  if (task.status === "ai_done" || task.status === "reviewing") {
    acts.push(`<button class="btn btn-sage" onclick="finalizeTask()">✓ 完成复核，定稿</button>`);
  }
  if (task.status === "finalized" || task.status === "ai_done") {
    acts.push(`<button class="btn btn-ghost" disabled>报告导出（v3 后续）</button>`);
  }
  box.innerHTML = acts.join("");
}

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

  // 维度分布
  const byType = {};
  findings.forEach(f => byType[f.finding_type] = (byType[f.finding_type] || 0) + 1);
  const breakdown = document.getElementById("tw-dimension-breakdown");
  if (Object.keys(byType).length === 0) {
    breakdown.innerHTML = `<div class="empty-state" style="grid-column:1/-1">尚无核查发现</div>`;
  } else {
    breakdown.innerHTML = Object.entries(byType).map(([k, v]) => `
      <div style="padding:var(--space-3);border:1px solid var(--rule)">
        <div class="text-xs code muted">${esc(k)}</div>
        <div class="serif" style="font-size:24px;font-weight:700;margin-top:4px">${v}</div>
      </div>`).join("");
  }
}

function renderMaterials() {
  const d = State.taskDetail;
  const indSel = document.getElementById("md-indicator");
  indSel.innerHTML = `<option value="">— 选择指标 —</option>` +
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
      ke.has_official_seal ? `<span class="stamp stamp-sage">公章</span>` : `<span class="stamp stamp-seal">无公章</span>`,
      ke.has_signature ? `<span class="stamp stamp-sage">签字</span>` : `<span class="stamp stamp-ochre">无签字</span>`,
      ke.issue_year ? `<span class="tag">${ke.issue_year} 年</span>` : `<span class="stamp stamp-seal">无日期</span>`,
      ke.is_draft ? `<span class="stamp stamp-seal">草稿</span>` : '',
      ke.document_number ? `<span class="tag code">${esc(ke.document_number)}</span>` : '',
    ].filter(Boolean).join(" ");
    return `<tr>
      <td class="table-mono-id">#${pad(m.id)}</td>
      <td class="serif">${esc(m.file_name)}</td>
      <td>${ind ? `<span class="code">${esc(ind.indicator_code)}</span> ${esc(ind.name)}` : '<span class="muted">未绑定</span>'}</td>
      <td>${badges}</td>
    </tr>`;
  }).join("");
}

document.getElementById("material-upload-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const indId = document.getElementById("md-indicator").value;
  const fileInput = document.getElementById("md-file");
  const status = document.getElementById("md-status");
  if (!indId || !fileInput.files.length) {
    status.innerHTML = `<span class="callout callout-warn">请选择指标并上传文件</span>`;
    return;
  }
  const fd = new FormData();
  fd.append("file", fileInput.files[0]);
  fd.append("indicator_id", indId);
  status.innerHTML = `<span class="callout callout-info">正在解析材料…</span>`;
  try {
    const tok = getToken();
    const r = await fetch(`${API}/tasks/${State.taskId}/materials`, {
      method: "POST", headers: { "Authorization": "Bearer " + tok }, body: fd,
    });
    if (!r.ok) throw new Error(await r.text());
    status.innerHTML = `<span class="callout callout-success">✓ 已上传并自动抽取 key_elements</span>`;
    fileInput.value = "";
    await loadTaskWorkspace(State.taskId);
  } catch (e) {
    status.innerHTML = `<span class="callout callout-warn">✗ ${esc(e.message)}</span>`;
  }
});

document.getElementById("tw-run-btn").addEventListener("click", async () => {
  if (!State.taskDetail.materials.length) {
    toast("请先上传材料", "error"); return;
  }
  toast("AI 核查中…可能耗时数十秒");
  try {
    await api(`/tasks/${State.taskId}/run`, { method: "POST" });
    // 轮询
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
// Finding 分栏审阅
// ============================================================
function renderFindings() {
  const d = State.taskDetail;
  const findings = d.findings;

  // 过滤
  const filtered = findings.filter(f => {
    const v = State.findingFilter;
    if (v === "all") return true;
    if (v === "高" || v === "中" || v === "低") return f.severity === v;
    if (v === "pending") return f.review_status === "pending";
    if (v === "confirmed") return f.review_status === "confirmed";
    return true;
  });

  // 列表
  const listBox = document.getElementById("finding-list");
  if (!filtered.length) {
    listBox.innerHTML = `<div class="empty-state">
      <div class="empty-state-glyph">⌬</div>
      ${findings.length === 0 ? '尚无核查发现，请先触发 AI 核查。' : '当前筛选下无结果。'}
    </div>`;
    renderFindingDetail(null);
    return;
  }

  listBox.innerHTML = filtered.map(f => {
    const isActive = f.id === State.activeFindingId;
    return `
      <div class="finding-row ${isActive ? 'is-active' : ''}" data-id="${f.id}">
        <div class="finding-row-strip finding-row-strip-${f.severity}"></div>
        <div>
          <div class="finding-row-desc">${esc(f.description.slice(0, 100))}${f.description.length > 100 ? '…' : ''}</div>
          <div class="finding-row-meta">
            <span class="chip-risk chip-risk-${f.severity}">${f.severity}</span>
            <span class="tag">${esc(f.finding_type)}</span>
            <span class="muted">${esc(f.review_status)}</span>
          </div>
        </div>
        <div class="row-arrow">→</div>
      </div>`;
  }).join("");

  listBox.querySelectorAll(".finding-row").forEach(row => {
    row.addEventListener("click", () => {
      const id = parseInt(row.dataset.id);
      State.activeFindingId = id;
      renderFindings();
    });
  });

  // 详情：默认选第一条
  if (!State.activeFindingId || !filtered.find(f => f.id === State.activeFindingId)) {
    State.activeFindingId = filtered[0].id;
  }
  renderFindingDetail(filtered.find(f => f.id === State.activeFindingId));
}

function renderFindingDetail(f) {
  const box = document.getElementById("finding-detail");
  if (!f) {
    box.innerHTML = `<div class="triage-empty">
      <div class="triage-empty-glyph">⌬</div>
      <div>从左侧列表选择一条发现<br/>进行复核标注或整改跟踪</div>
    </div>`;
    return;
  }
  const indicator = State.indicators.find(i => i.id === f.indicator_id);
  const material = State.taskDetail.materials.find(m => m.id === f.material_id);

  box.innerHTML = `
    <div class="flex items-baseline gap-3 mb-3">
      <span class="chip-risk chip-risk-${f.severity}">${f.severity} 风险</span>
      <span class="tag">${esc(f.finding_type)}</span>
      <span class="text-xs muted code">由 ${f.source === 'rule' ? '刚性规则' : 'LLM'} 检出</span>
    </div>

    <h2 class="detail-heading">${esc(f.description)}</h2>

    <dl class="detail-meta-grid">
      <dt>评价指标</dt>
      <dd>${indicator ? `<span class="code">${esc(indicator.indicator_code)}</span> ${esc(indicator.name)}` : '<span class="muted">—</span>'}</dd>
      <dt>材料出处</dt>
      <dd>${material ? esc(material.file_name) : '<span class="muted">—</span>'}</dd>
      <dt>具体位置</dt>
      <dd>${esc(f.evidence_location || '—')}</dd>
      <dt>复核状态</dt>
      <dd>${reviewStamp(f.review_status)}${f.review_note ? ' · <span class="muted">' + esc(f.review_note) + '</span>' : ''}</dd>
      <dt>整改状态</dt>
      <dd>${rectifyStamp(f.rectification_status)}${f.rectification_note ? ' · <span class="muted">' + esc(f.rectification_note) + '</span>' : ''}</dd>
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
        <button class="btn btn-sage" onclick="reviewFinding('confirmed')">✓ 确认问题</button>
        <button class="btn btn-ghost" onclick="reviewFinding('ignored')">○ 忽略</button>
        <button class="btn btn-ghost" onclick="reviewFinding('adjusted')">∆ 调整</button>
      </div>
    </div>

    <div class="detail-section">
      <div class="detail-section-title">整改闭环</div>
      <textarea id="rectify-note" class="form-textarea mb-3" placeholder="整改说明">${esc(f.rectification_note || '')}</textarea>
      <div class="action-bar">
        <button class="btn btn-ghost" onclick="submitRectification()">提交整改</button>
        <button class="btn btn-seal" onclick="resolveRectification()">销 号</button>
      </div>
    </div>
  `;
}

function reviewStamp(s) {
  const map = {
    pending: ['stamp stamp-ink', '待复核'],
    confirmed: ['stamp stamp-sage', '已确认'],
    ignored: ['stamp stamp-ink', '已忽略'],
    adjusted: ['stamp stamp-ochre', '已调整'],
  };
  const [cls, label] = map[s] || ['stamp stamp-ink', s];
  return `<span class="${cls}">${label}</span>`;
}
function rectifyStamp(s) {
  const map = {
    open: ['stamp stamp-seal', '未整改'],
    submitted: ['stamp stamp-ochre', '已提交'],
    resolved: ['stamp stamp-sage', '已销号'],
  };
  const [cls, label] = map[s] || ['stamp stamp-ink', s];
  return `<span class="${cls}">${label}</span>`;
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

// 筛选
document.getElementById("finding-filters").addEventListener("click", ev => {
  if (!ev.target.matches(".filter-chip")) return;
  document.querySelectorAll("#finding-filters .filter-chip").forEach(b => b.classList.remove("on"));
  ev.target.classList.add("on");
  State.findingFilter = ev.target.dataset.filter;
  State.activeFindingId = null;
  renderFindings();
});

// ============================================================
// 知识库
// ============================================================
async function loadIndicators() {
  const inds = await api("/indicators");
  State.indicators = inds;
  const tbody = document.getElementById("indicators-tbody");
  if (!inds.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-state">
      <div class="empty-state-glyph">◇</div>
      暂无评价指标，使用右上角「批量导入 JSON」开始。
    </td></tr>`;
    return;
  }
  tbody.innerHTML = inds.map(i => {
    let mats = []; try { mats = JSON.parse(i.required_materials || "[]"); } catch {}
    return `<tr>
      <td class="table-mono-id">${esc(i.indicator_code)}</td>
      <td><span class="tag">${esc(i.level)}</span></td>
      <td class="serif">${esc(i.category)}</td>
      <td class="serif">${esc(i.name)}</td>
      <td class="code">${i.max_score}</td>
      <td class="text-xs muted">${esc(mats.join("、")) || '—'}</td>
    </tr>`;
  }).join("");
}

async function loadCheckItems() {
  const items = await api("/check-items");
  const tbody = document.getElementById("items-tbody");
  if (!items.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-state">
      <div class="empty-state-glyph">◇</div>暂无条目，请批量导入。
    </td></tr>`;
    return;
  }
  tbody.innerHTML = items.map(it => `<tr>
    <td class="table-mono-id">${esc(it.item_code)}</td>
    <td><span class="tag">${esc(it.dimension)}</span></td>
    <td class="serif">${esc(it.subcategory)}</td>
    <td class="text-xs">${esc(it.description)}</td>
    <td><span class="tag">${esc(it.check_method)}</span></td>
    <td>${chipRisk(it.risk_level)}</td>
  </tr>`).join("");
}

function chipRisk(r) { return `<span class="chip-risk chip-risk-${r}">${r}</span>`; }

async function uploadJson(endpoint, file) {
  const fd = new FormData(); fd.append("file", file);
  const tok = getToken();
  const r = await fetch(API + endpoint, {
    method: "POST", headers: { "Authorization": "Bearer " + tok }, body: fd,
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

document.getElementById("import-indicators").addEventListener("change", async ev => {
  const file = ev.target.files[0]; if (!file) return;
  try {
    const r = await uploadJson("/indicators/import", file);
    toast(`✓ 创建 ${r.created}，跳过 ${r.skipped}`, "success");
    loadIndicators();
  } catch (e) { toast(e.message, "error"); }
});
document.getElementById("import-items").addEventListener("change", async ev => {
  const file = ev.target.files[0]; if (!file) return;
  try {
    const r = await uploadJson("/check-items/import", file);
    toast(`✓ 创建 ${r.created}，跳过 ${r.skipped}`, "success");
    loadCheckItems();
  } catch (e) { toast(e.message, "error"); }
});

// ============================================================
// 用户 / 审计日志 / 设置
// ============================================================
async function loadUsers() {
  const users = await api("/users");
  document.getElementById("users-tbody").innerHTML = users.map(u => `
    <tr>
      <td class="table-mono-id">#${pad(u.id)}</td>
      <td class="serif">${esc(u.username)}</td>
      <td><span class="tag">${esc(u.role)}</span></td>
      <td>${esc(u.full_name || "—")}</td>
      <td>${u.is_active ? '<span class="stamp stamp-sage">启用</span>' : '<span class="stamp stamp-ink">停用</span>'}</td>
    </tr>`).join("") || `<tr><td colspan="5" class="empty-state">暂无用户</td></tr>`;
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
    status.innerHTML = `<span class="callout callout-success">✓ 用户已创建</span>`;
    ev.target.reset();
    loadUsers();
  } catch (e) {
    status.innerHTML = `<span class="callout callout-warn">✗ ${esc(e.message)}</span>`;
  }
});

async function loadAuditLogs() {
  const logs = await api("/audit-logs?limit=100");
  document.getElementById("audit-tbody").innerHTML = logs.map(l => `
    <tr>
      <td class="text-xs code muted">${fmtTime(l.created_at)}</td>
      <td class="serif">${esc(l.username || "—")}</td>
      <td><span class="tag">${esc(l.action)}</span></td>
      <td class="text-xs">${esc(l.target_type)}${l.target_id ? ' #' + l.target_id : ''}</td>
      <td class="text-xs">${esc(l.detail || "—")}</td>
    </tr>`).join("") || `<tr><td colspan="5" class="empty-state">暂无日志</td></tr>`;
}
document.getElementById("refresh-audit").addEventListener("click", loadAuditLogs);

async function loadSettings() {
  try {
    const cfg = await api("/settings/llm");
    const form = document.getElementById("llm-form");
    form.provider.value = cfg.provider;
    form.model.value = cfg.model;
    form.base_url.value = cfg.base_url;
    form.thinking_mode.value = cfg.thinking_mode;
    form.api_key.value = "";
    document.getElementById("llm-key-hint").textContent = cfg.has_api_key
      ? "✓ 当前已配置 API Key（留空则不修改）"
      : "尚未配置，请填入 DeepSeek API Key（sk-...）";
    document.getElementById("llm-status").textContent = "";
  } catch (e) { console.error(e); }
}

document.getElementById("llm-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const payload = {
    provider: fd.get("provider"), model: fd.get("model"),
    base_url: fd.get("base_url"), thinking_mode: fd.get("thinking_mode"),
  };
  const apiKey = fd.get("api_key");
  if (apiKey !== "") payload.api_key = apiKey.trim();
  try {
    await api("/settings/llm", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    document.getElementById("llm-status").innerHTML = `<span class="callout callout-success">✓ 已保存</span>`;
    loadSettings();
  } catch (e) {
    document.getElementById("llm-status").innerHTML = `<span class="callout callout-warn">✗ ${esc(e.message)}</span>`;
  }
});

document.getElementById("llm-test").addEventListener("click", async () => {
  const status = document.getElementById("llm-status");
  status.innerHTML = `<span class="callout callout-info">测试中…</span>`;
  try {
    const r = await api("/settings/llm/test", { method: "POST" });
    if (r.success) {
      status.innerHTML = `<span class="callout callout-success">✓ ${esc(r.client)} 连接成功</span>`;
    } else {
      status.innerHTML = `<span class="callout callout-warn">✗ ${esc(r.client)}: ${esc(r.error)}</span>`;
    }
  } catch (e) {
    status.innerHTML = `<span class="callout callout-warn">✗ ${esc(e.message)}</span>`;
  }
});

// ============================================================
// 认证 & 启动
// ============================================================
function showLogin(msg) {
  document.getElementById("app").classList.add("hidden");
  document.getElementById("login-modal").classList.remove("hidden");
  const err = document.getElementById("login-error");
  if (msg) { err.textContent = msg; err.classList.remove("hidden"); }
  else { err.classList.add("hidden"); }
}
function hideLogin() {
  document.getElementById("login-modal").classList.add("hidden");
  document.getElementById("app").classList.remove("hidden");
}

function renderUserBar() {
  const box = document.getElementById("user-info");
  if (!State.user) { box.innerHTML = ""; return; }
  box.innerHTML = `
    <div class="user-line">
      <span class="user-name">${esc(State.user.full_name || State.user.username)}</span>
    </div>
    <div class="user-role">${esc(State.roleLabel)}</div>
    <button class="btn-logout" id="btn-logout">登 出</button>
  `;
  document.getElementById("btn-logout").addEventListener("click", async () => {
    try { await api("/auth/logout", { method: "POST" }); } catch {}
    setToken(""); State.user = null;
    showLogin();
  });

  document.getElementById("nav-admin-section").style.display =
    State.user.role === "super_admin" ? "" : "none";
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
    renderUserBar();
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
      renderUserBar();
      if (!location.hash) location.hash = "#/dashboard";
      handleRoute();
      return;
    } catch {}
  }
  showLogin();
}
bootstrap();
