// v3 内控评价智能审核系统 前端逻辑

const API = "/api";
const TOKEN_KEY = "audit.token";

const State = {
  user: null,
  roleLabel: "",
  units: [],
  indicators: [],
  checkItems: [],
  tasks: [],
  activeTaskId: null,
  activeFindingId: null,
};

// ─── 工具 ─────────────────────────────────────────────
function getToken() { return localStorage.getItem(TOKEN_KEY) || ""; }
function setToken(t) {
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
}

async function api(path, opts = {}) {
  const headers = new Headers(opts.headers || {});
  const tok = getToken();
  if (tok) headers.set("Authorization", "Bearer " + tok);
  const r = await fetch(API + path, { ...opts, headers });
  if (r.status === 401) {
    setToken("");
    State.user = null;
    showLogin("登录已失效，请重新登录");
    throw new Error("未登录");
  }
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    let msg = text;
    try { msg = JSON.parse(text).detail || text; } catch {}
    throw new Error(`${msg || r.statusText} (HTTP ${r.status})`);
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
  try { return new Date(s).toLocaleString("zh-CN"); } catch { return s; }
}

// ─── 标签切换 ─────────────────────────────────────────
document.querySelectorAll(".nav-tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-tab").forEach(b => b.classList.remove("tab-active"));
    btn.classList.add("tab-active");
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.add("hidden"));
    document.getElementById("tab-" + btn.dataset.tab).classList.remove("hidden");
    const tab = btn.dataset.tab;
    if (tab === "dashboard") loadDashboard();
    if (tab === "tasks") loadTasksTab();
    if (tab === "knowledge") loadKnowledgeTab();
    if (tab === "admin") loadAdmin();
    if (tab === "settings") loadSettings();
  });
});

// 知识库子 tab
document.querySelectorAll(".kb-tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".kb-tab").forEach(b => b.classList.remove("kb-active"));
    btn.classList.add("kb-active");
    document.querySelectorAll(".kb-panel").forEach(p => p.classList.add("hidden"));
    document.getElementById("kb-" + btn.dataset.kb).classList.remove("hidden");
    loadKnowledgeTab();
  });
});

// ─── 仪表板 ───────────────────────────────────────────
async function loadDashboard() {
  try {
    const health = await api("/health");
    document.getElementById("health-info").innerHTML = `
      <div class="flex justify-between"><span class="text-slate-500">服务</span><span class="text-emerald-600 font-medium">● 正常</span></div>
      <div class="flex justify-between"><span class="text-slate-500">应用</span><span>${esc(health.app)}</span></div>
      <div class="flex justify-between"><span class="text-slate-500">LLM</span><span>${esc(health.llm_default_provider)}</span></div>
      <div class="flex justify-between"><span class="text-slate-500">向量库</span><span>${esc(health.vector_store)}</span></div>
    `;

    const [units, tasks, indicators, items] = await Promise.all([
      api("/units").catch(() => []),
      api("/tasks").catch(() => []),
      api("/indicators").catch(() => []),
      api("/check-items").catch(() => []),
    ]);
    State.units = units;
    State.indicators = indicators;
    State.checkItems = items;
    State.tasks = tasks;

    document.getElementById("stat-units").textContent = units.length;
    document.getElementById("stat-tasks").textContent = tasks.length;
    document.getElementById("stat-indicators").textContent = indicators.length;
    document.getElementById("stat-check-items").textContent = items.length;

    const tbody = document.getElementById("dash-tasks-tbody");
    if (!tasks.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="text-center text-slate-400 py-6">暂无任务</td></tr>`;
    } else {
      tbody.innerHTML = tasks.slice(0, 8).map(t => {
        const unit = units.find(u => u.id === t.unit_id);
        return `<tr>
          <td class="font-mono text-xs">${t.id}</td>
          <td>${esc(unit ? unit.name : "—")}</td>
          <td>${esc(t.name)}</td>
          <td>${esc(t.eval_year)}</td>
          <td><span class="cat-tag">${esc(t.status)}</span></td>
          <td class="text-xs">${esc(t.summary || "—")}</td>
        </tr>`;
      }).join("");
    }
  } catch (e) {
    console.error(e);
  }
}

// ─── 核查任务 ─────────────────────────────────────────
async function loadTasksTab() {
  try {
    const [units, tasks, indicators] = await Promise.all([
      api("/units"), api("/tasks"), api("/indicators"),
    ]);
    State.units = units;
    State.tasks = tasks;
    State.indicators = indicators;

    const unitSel = document.getElementById("task-unit-select");
    unitSel.innerHTML = `<option value="">— 选择单位 —</option>` +
      units.map(u => `<option value="${u.id}">${esc(u.name)}</option>`).join("");

    const tbody = document.getElementById("tasks-tbody");
    if (!tasks.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-center text-slate-400 py-6">暂无任务</td></tr>`;
      return;
    }
    tbody.innerHTML = "";
    tasks.forEach(t => {
      const unit = units.find(u => u.id === t.unit_id);
      const row = el(`<tr>
        <td class="font-mono text-xs">${t.id}</td>
        <td>${esc(unit ? unit.name : "—")}</td>
        <td>${esc(t.name)}</td>
        <td>${esc(t.eval_year)}</td>
        <td><span class="cat-tag">${esc(t.status)}</span></td>
        <td class="text-xs">${esc(t.summary || "—")}</td>
        <td><button class="btn-secondary text-xs" data-id="${t.id}">查看</button></td>
      </tr>`);
      row.querySelector("button").addEventListener("click", () => openTaskDetail(t.id));
      tbody.appendChild(row);
    });
  } catch (e) {
    console.error(e);
  }
}

document.getElementById("unit-create-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  try {
    await api("/units", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: fd.get("name"), code: fd.get("code"), level: fd.get("level"),
      }),
    });
    ev.target.reset();
    loadTasksTab();
  } catch (e) { alert(e.message); }
});

document.getElementById("task-create-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  try {
    const t = await api("/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        unit_id: parseInt(fd.get("unit_id")),
        name: fd.get("name"),
        eval_year: parseInt(fd.get("eval_year")),
      }),
    });
    ev.target.reset();
    await loadTasksTab();
    openTaskDetail(t.id);
  } catch (e) { alert(e.message); }
});

async function openTaskDetail(taskId) {
  State.activeTaskId = taskId;
  document.getElementById("task-detail").classList.remove("hidden");
  await refreshTaskDetail();
}

document.getElementById("td-close").addEventListener("click", () => {
  document.getElementById("task-detail").classList.add("hidden");
  State.activeTaskId = null;
});

async function refreshTaskDetail() {
  if (!State.activeTaskId) return;
  const detail = await api(`/tasks/${State.activeTaskId}`);
  document.getElementById("td-title").textContent =
    `任务 #${detail.task.id} · ${detail.task.name}`;
  document.getElementById("td-meta").textContent =
    `${detail.unit.name} · ${detail.task.eval_year} 年度 · 状态: ${detail.task.status}`;

  // 指标下拉
  const indSel = document.getElementById("md-indicator-select");
  indSel.innerHTML = `<option value="">— 选择指标 —</option>` +
    State.indicators.map(i =>
      `<option value="${i.id}">[${esc(i.indicator_code)}] ${esc(i.name)}</option>`
    ).join("");

  // 材料列表
  const mbody = document.getElementById("td-materials-tbody");
  if (!detail.materials.length) {
    mbody.innerHTML = `<tr><td colspan="4" class="text-center text-slate-400 py-4">尚未上传材料</td></tr>`;
  } else {
    mbody.innerHTML = detail.materials.map(m => {
      const ind = State.indicators.find(i => i.id === m.indicator_id);
      let ke = {};
      try { ke = JSON.parse(m.key_elements || "{}"); } catch {}
      const kebadges = [
        ke.has_official_seal ? '<span class="badge badge-low">公章</span>' : '<span class="badge badge-high">无公章</span>',
        ke.has_signature ? '<span class="badge badge-low">签字</span>' : '<span class="badge badge-mid">无签字</span>',
        ke.issue_year ? `<span class="badge badge-low">${ke.issue_year}年</span>` : '<span class="badge badge-high">无日期</span>',
        ke.is_draft ? '<span class="badge badge-high">草稿</span>' : '',
      ].filter(Boolean).join(" ");
      return `<tr>
        <td class="font-mono text-xs">${m.id}</td>
        <td>${esc(m.file_name)}</td>
        <td>${ind ? esc(ind.indicator_code) + " " + esc(ind.name) : "—"}</td>
        <td>${kebadges}</td>
      </tr>`;
    }).join("");
  }

  // Findings 汇总
  const findings = detail.findings;
  const sevCount = { 高: 0, 中: 0, 低: 0 };
  findings.forEach(f => { sevCount[f.severity] = (sevCount[f.severity] || 0) + 1; });
  document.getElementById("td-summary").innerHTML = `
    <div class="bg-slate-50 rounded p-3 border border-slate-200">
      <div class="text-xs text-slate-500">材料数</div><div class="text-xl font-semibold mt-1">${detail.materials.length}</div>
    </div>
    <div class="bg-rose-50 rounded p-3 border border-rose-200">
      <div class="text-xs text-rose-600">高风险</div><div class="text-xl font-semibold mt-1 text-rose-700">${sevCount.高}</div>
    </div>
    <div class="bg-amber-50 rounded p-3 border border-amber-200">
      <div class="text-xs text-amber-700">中风险</div><div class="text-xl font-semibold mt-1 text-amber-800">${sevCount.中}</div>
    </div>
    <div class="bg-slate-50 rounded p-3 border border-slate-200">
      <div class="text-xs text-slate-500">低风险</div><div class="text-xl font-semibold mt-1">${sevCount.低}</div>
    </div>
  `;

  const fbody = document.getElementById("td-findings-tbody");
  if (!findings.length) {
    fbody.innerHTML = `<tr><td colspan="7" class="text-center text-emerald-600 py-4">✓ 暂无 Finding</td></tr>`;
  } else {
    fbody.innerHTML = "";
    findings.forEach((f, idx) => {
      const row = el(`<tr>
        <td class="font-mono text-xs">${idx + 1}</td>
        <td><span class="cat-tag">${esc(f.finding_type)}</span></td>
        <td><span class="badge badge-${f.severity}">${esc(f.severity)}</span></td>
        <td class="text-xs">${esc(f.description)}<div class="text-xs text-slate-400 mt-1">${esc(f.evidence_location || "")}</div></td>
        <td class="text-xs">${esc(f.suggestion || "—")}</td>
        <td><span class="cat-tag">${esc(f.review_status)}</span></td>
        <td>
          <span class="cat-tag">${esc(f.rectification_status)}</span>
          <button class="btn-secondary text-xs ml-1" data-fid="${f.id}">详情</button>
        </td>
      </tr>`);
      row.querySelector("button").addEventListener("click", () => openFindingModal(f));
      fbody.appendChild(row);
    });
  }
}

document.getElementById("material-upload-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  if (!State.activeTaskId) return;
  const indId = document.getElementById("md-indicator-select").value;
  const fileInput = document.getElementById("md-file");
  if (!fileInput.files.length || !indId) {
    alert("请选择指标并选择文件"); return;
  }
  const fd = new FormData();
  fd.append("file", fileInput.files[0]);
  fd.append("indicator_id", indId);
  const status = document.getElementById("md-upload-status");
  status.textContent = "上传解析中…";
  status.className = "text-sm mt-2 text-indigo-600";
  try {
    const tok = getToken();
    const r = await fetch(`${API}/tasks/${State.activeTaskId}/materials`, {
      method: "POST",
      headers: { "Authorization": "Bearer " + tok },
      body: fd,
    });
    if (!r.ok) throw new Error(await r.text());
    status.textContent = "✓ 上传成功";
    status.className = "text-sm mt-2 text-emerald-600";
    fileInput.value = "";
    await refreshTaskDetail();
  } catch (e) {
    status.textContent = "✗ " + e.message;
    status.className = "text-sm mt-2 text-rose-600";
  }
});

document.getElementById("td-run").addEventListener("click", async () => {
  if (!State.activeTaskId) return;
  const status = document.getElementById("td-run-status");
  status.textContent = "AI 核查中…（可能耗时数十秒）";
  status.className = "text-sm text-indigo-600";
  try {
    await api(`/tasks/${State.activeTaskId}/run`, { method: "POST" });
    // eager 模式下立即完成；生产模式轮询
    let task = await api(`/tasks/${State.activeTaskId}`);
    for (let i = 0; i < 60 && task.task.status === "running"; i++) {
      await new Promise(r => setTimeout(r, 1000));
      task = await api(`/tasks/${State.activeTaskId}`);
    }
    status.textContent = `✓ 完成：${task.task.summary || ""}`;
    status.className = "text-sm text-emerald-600";
    await refreshTaskDetail();
  } catch (e) {
    status.textContent = "✗ " + e.message;
    status.className = "text-sm text-rose-600";
  }
});

document.getElementById("td-finalize").addEventListener("click", async () => {
  if (!State.activeTaskId) return;
  try {
    await api(`/tasks/${State.activeTaskId}/finalize`, { method: "POST" });
    await refreshTaskDetail();
  } catch (e) { alert(e.message); }
});

// ─── Finding 模态 ─────────────────────────────────────
function openFindingModal(f) {
  State.activeFindingId = f.id;
  document.getElementById("finding-modal").classList.remove("hidden");
  document.getElementById("fm-title").textContent = `[${f.finding_type}] 风险 ${f.severity}`;
  document.getElementById("fm-body").innerHTML = `
    <div><span class="text-slate-500">问题描述：</span>${esc(f.description)}</div>
    <div><span class="text-slate-500">位置：</span>${esc(f.evidence_location || "—")}</div>
    <div><span class="text-slate-500">法规依据：</span>${esc(f.legal_basis || "—")}</div>
    <div><span class="text-slate-500">建议：</span>${esc(f.suggestion || "—")}</div>
    <div><span class="text-slate-500">来源：</span>${esc(f.source)}</div>
    <div><span class="text-slate-500">复核状态：</span>${esc(f.review_status)} ${f.review_note ? '— ' + esc(f.review_note) : ''}</div>
    <div><span class="text-slate-500">整改状态：</span>${esc(f.rectification_status)} ${f.rectification_note ? '— ' + esc(f.rectification_note) : ''}</div>
  `;
  document.getElementById("fm-review-note").value = f.review_note || "";
  document.getElementById("fm-rectify-note").value = f.rectification_note || "";
}

document.getElementById("fm-close").addEventListener("click", () => {
  document.getElementById("finding-modal").classList.add("hidden");
  State.activeFindingId = null;
});

document.querySelectorAll(".fm-review-btn").forEach(btn => {
  btn.addEventListener("click", async () => {
    if (!State.activeFindingId) return;
    const note = document.getElementById("fm-review-note").value;
    try {
      await api(`/findings/${State.activeFindingId}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: btn.dataset.status, note }),
      });
      document.getElementById("finding-modal").classList.add("hidden");
      await refreshTaskDetail();
    } catch (e) { alert(e.message); }
  });
});

document.getElementById("fm-rectify-btn").addEventListener("click", async () => {
  if (!State.activeFindingId) return;
  const note = document.getElementById("fm-rectify-note").value;
  if (!note.trim()) { alert("请填写整改说明"); return; }
  try {
    await api(`/findings/${State.activeFindingId}/rectify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note }),
    });
    document.getElementById("finding-modal").classList.add("hidden");
    await refreshTaskDetail();
  } catch (e) { alert(e.message); }
});

document.getElementById("fm-resolve-btn").addEventListener("click", async () => {
  if (!State.activeFindingId) return;
  const note = document.getElementById("fm-rectify-note").value;
  try {
    await api(`/findings/${State.activeFindingId}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note }),
    });
    document.getElementById("finding-modal").classList.add("hidden");
    await refreshTaskDetail();
  } catch (e) { alert(e.message); }
});

// ─── 知识库 ───────────────────────────────────────────
async function loadKnowledgeTab() {
  try {
    const [inds, items] = await Promise.all([
      api("/indicators"), api("/check-items"),
    ]);
    State.indicators = inds;
    State.checkItems = items;
    const itbody = document.getElementById("indicators-tbody");
    if (!inds.length) {
      itbody.innerHTML = `<tr><td colspan="6" class="text-center text-slate-400 py-4">暂无指标。请使用「批量导入」上传 JSON。</td></tr>`;
    } else {
      itbody.innerHTML = inds.map(i => {
        let mats = [];
        try { mats = JSON.parse(i.required_materials || "[]"); } catch {}
        return `<tr>
          <td class="font-mono text-xs">${esc(i.indicator_code)}</td>
          <td>${esc(i.level)}</td>
          <td><span class="cat-tag">${esc(i.category)}</span></td>
          <td>${esc(i.name)}</td>
          <td>${i.max_score}</td>
          <td class="text-xs">${mats.length ? esc(mats.join("、")) : "—"}</td>
        </tr>`;
      }).join("");
    }
    const cbody = document.getElementById("items-tbody");
    if (!items.length) {
      cbody.innerHTML = `<tr><td colspan="6" class="text-center text-slate-400 py-4">暂无条目</td></tr>`;
    } else {
      cbody.innerHTML = items.map(it => `<tr>
        <td class="font-mono text-xs">${esc(it.item_code)}</td>
        <td><span class="cat-tag">${esc(it.dimension)}</span></td>
        <td>${esc(it.subcategory)}</td>
        <td class="text-xs">${esc(it.description)}</td>
        <td><span class="cat-tag">${esc(it.check_method)}</span></td>
        <td><span class="badge badge-${it.risk_level}">${esc(it.risk_level)}</span></td>
      </tr>`).join("");
    }
  } catch (e) {
    console.error(e);
  }
}

async function importJson(endpoint, file) {
  const fd = new FormData();
  fd.append("file", file);
  const tok = getToken();
  const r = await fetch(API + endpoint, {
    method: "POST",
    headers: { "Authorization": "Bearer " + tok },
    body: fd,
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

document.getElementById("import-indicators-file").addEventListener("change", async ev => {
  const file = ev.target.files[0];
  if (!file) return;
  try {
    const result = await importJson("/indicators/import", file);
    alert(`导入完成：创建 ${result.created}，跳过 ${result.skipped}`);
    loadKnowledgeTab();
  } catch (e) { alert("导入失败：" + e.message); }
});

document.getElementById("import-items-file").addEventListener("change", async ev => {
  const file = ev.target.files[0];
  if (!file) return;
  try {
    const result = await importJson("/check-items/import", file);
    alert(`导入完成：创建 ${result.created}，跳过 ${result.skipped}`);
    loadKnowledgeTab();
  } catch (e) { alert("导入失败：" + e.message); }
});

// ─── 系统管理 ─────────────────────────────────────────
async function loadAdmin() {
  if (!State.user || State.user.role !== "super_admin") return;
  try {
    const users = await api("/users");
    document.getElementById("users-tbody").innerHTML = users.map(u => `
      <tr>
        <td class="font-mono text-xs">${u.id}</td>
        <td>${esc(u.username)}</td>
        <td><span class="cat-tag">${esc(u.role)}</span></td>
        <td>${esc(u.full_name || "—")}</td>
        <td>${u.is_active ? "✓" : "✗"}</td>
      </tr>`).join("");

    const logs = await api("/audit-logs?limit=100");
    document.getElementById("audit-tbody").innerHTML = logs.map(l => `
      <tr>
        <td class="text-xs text-slate-500">${fmtTime(l.created_at)}</td>
        <td>${esc(l.username || "—")}</td>
        <td><span class="cat-tag">${esc(l.action)}</span></td>
        <td class="text-xs">${esc(l.target_type)}${l.target_id ? ' #' + l.target_id : ''}</td>
        <td class="text-xs text-slate-600">${esc(l.detail || "—")}</td>
      </tr>`).join("");
  } catch (e) { console.error(e); }
}

document.getElementById("user-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const status = document.getElementById("user-form-status");
  try {
    await api("/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: fd.get("username"),
        password: fd.get("password"),
        role: fd.get("role"),
        full_name: fd.get("full_name") || "",
      }),
    });
    status.textContent = "✓ 用户已创建";
    status.className = "text-sm mt-2 text-emerald-600";
    ev.target.reset();
    loadAdmin();
  } catch (e) {
    status.textContent = "✗ " + e.message;
    status.className = "text-sm mt-2 text-rose-600";
  }
});

document.getElementById("refresh-audit").addEventListener("click", loadAdmin);

// ─── 系统设置 - LLM Key ───────────────────────────────
async function loadSettings() {
  if (!State.user || State.user.role !== "super_admin") return;
  try {
    const cfg = await api("/settings/llm");
    const form = document.getElementById("llm-form");
    form.provider.value = cfg.provider;
    form.model.value = cfg.model;
    form.base_url.value = cfg.base_url;
    form.thinking_mode.value = cfg.thinking_mode;
    form.api_key.value = "";  // 永远不回显明文
    document.getElementById("llm-key-hint").textContent =
      cfg.has_api_key
        ? "✓ 当前已配置 API Key（保存时留空则不修改；输入空格再保存则清空）"
        : "尚未配置，请填入 DeepSeek API Key（sk-...）";
    document.getElementById("llm-status").textContent = "";
  } catch (e) { console.error(e); }
}

document.getElementById("llm-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const status = document.getElementById("llm-status");
  // api_key 为空表示不变；用户实际想清空可以输入一个空格
  const apiKey = fd.get("api_key");
  const payload = {
    provider: fd.get("provider"),
    model: fd.get("model"),
    base_url: fd.get("base_url"),
    thinking_mode: fd.get("thinking_mode"),
  };
  if (apiKey !== "") payload.api_key = apiKey.trim();
  try {
    await api("/settings/llm", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    status.textContent = "✓ 已保存";
    status.className = "text-sm text-emerald-600";
    loadSettings();
  } catch (e) {
    status.textContent = "✗ " + e.message;
    status.className = "text-sm text-rose-600";
  }
});

document.getElementById("llm-test-btn").addEventListener("click", async () => {
  const status = document.getElementById("llm-status");
  status.textContent = "测试中…";
  status.className = "text-sm text-indigo-600";
  try {
    const r = await api("/settings/llm/test", { method: "POST" });
    if (r.success) {
      status.textContent = `✓ ${r.client} 连接成功；预览：${(r.preview || "").slice(0, 50)}`;
      status.className = "text-sm text-emerald-600";
    } else {
      status.textContent = `✗ ${r.client} 连接失败：${r.error}`;
      status.className = "text-sm text-rose-600";
    }
  } catch (e) {
    status.textContent = "✗ " + e.message;
    status.className = "text-sm text-rose-600";
  }
});

// ─── 认证 ─────────────────────────────────────────────
function showLogin(msg = "") {
  document.getElementById("login-modal").classList.remove("hidden");
  const errBox = document.getElementById("login-error");
  if (msg) { errBox.textContent = msg; errBox.classList.remove("hidden"); }
  else { errBox.classList.add("hidden"); }
}
function hideLogin() {
  document.getElementById("login-modal").classList.add("hidden");
}

function renderUserBar() {
  const bar = document.getElementById("user-bar");
  if (!State.user) { bar.innerHTML = ""; return; }
  bar.innerHTML = `
    <span class="text-sm">
      <span class="font-medium">${esc(State.user.full_name || State.user.username)}</span>
      <span class="text-xs text-slate-400 ml-1">· ${esc(State.roleLabel)}</span>
    </span>
    <button id="logout-btn" class="btn-secondary text-xs">退出</button>
  `;
  document.getElementById("logout-btn").addEventListener("click", async () => {
    try { await api("/auth/logout", { method: "POST" }); } catch {}
    setToken(""); State.user = null;
    renderUserBar();
    document.getElementById("nav-admin").style.display = "none";
    document.getElementById("nav-settings").style.display = "none";
    showLogin();
  });
  const showAdminTabs = State.user.role === "super_admin";
  document.getElementById("nav-admin").style.display = showAdminTabs ? "" : "none";
  document.getElementById("nav-settings").style.display = showAdminTabs ? "" : "none";
}

document.getElementById("login-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  try {
    const r = await fetch(API + "/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
    loadDashboard();
  } catch (e) { showLogin(e.message); }
});

// ─── 启动 ─────────────────────────────────────────────
async function bootstrap() {
  if (getToken()) {
    try {
      const data = await api("/auth/me");
      State.user = data.user;
      State.roleLabel = data.role_label;
      hideLogin();
      renderUserBar();
      loadDashboard();
      return;
    } catch {}
  }
  showLogin();
}
bootstrap();
