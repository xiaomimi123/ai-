// 前端应用：与 /api 通信、管理 5 个面板的状态与渲染。

const API = "/api";
const TOKEN_KEY = "compliance.token";

// ─── 通用工具 ─────────────────────────────────────────
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
    Auth.user = null;
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
    if (btn.dataset.tab === "documents") loadDocs();
    if (btn.dataset.tab === "checks") loadDocsForCheck();
    if (btn.dataset.tab === "chains") loadDocsForChain();
  });
});

// ─── 仪表板 ───────────────────────────────────────────
async function loadDashboard() {
  try {
    const [health, templates, docs] = await Promise.all([
      api("/health"), api("/templates"), api("/documents").catch(() => []),
    ]);

    // 系统状态
    document.getElementById("health-info").innerHTML = `
      <div class="flex justify-between"><span class="text-slate-500">服务</span><span class="text-emerald-600 font-medium">● 正常</span></div>
      <div class="flex justify-between"><span class="text-slate-500">LLM</span><span>${esc(health.llm)}</span></div>
      <div class="flex justify-between"><span class="text-slate-500">向量库</span><span>${esc(health.vector_store)}</span></div>
      <div class="flex justify-between"><span class="text-slate-500">Embedding</span><span>${esc(health.embedder)}</span></div>
    `;

    // 模板
    const tg = document.getElementById("templates-grid");
    tg.innerHTML = "";
    templates.forEach(t => {
      tg.appendChild(el(`
        <div class="tmpl-card">
          <div class="flex items-start justify-between">
            <div class="font-medium">${esc(t.name)}</div>
            <span class="badge ${t.ready ? "badge-低" : "badge-中"}" style="background:${t.ready ? '#dcfce7' : '#fef3c7'};color:${t.ready ? '#166534' : '#92400e'}">${t.ready ? "就绪" : "占位"}</span>
          </div>
          <div class="mt-1 text-xs text-slate-500">${esc(t.applies_to)} · 刚性 ${t.rigid_rules} / 柔性 ${t.soft_rules}</div>
        </div>
      `));
    });

    document.getElementById("stat-docs").textContent = docs.length;
    document.getElementById("stat-checks").textContent = State.checkCount;
    document.getElementById("stat-chains").textContent = State.chainCount;
    document.getElementById("stat-issues").textContent = State.issueCount;
  } catch (e) {
    document.getElementById("health-info").innerHTML =
      `<div class="text-rose-600 text-sm">无法连接后端：${esc(e.message)}</div>`;
  }
}

const State = { checkCount: 0, chainCount: 0, issueCount: 0, docs: [], templates: [] };

// 由于 /api/documents 没有 GET 列表端点，我们在前端维护已上传的文档列表
async function loadDocs() {
  const tbody = document.getElementById("docs-tbody");
  if (State.docs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-center text-slate-400 py-6">暂无上传文档。请在上方上传文档。</td></tr>`;
    return;
  }
  tbody.innerHTML = "";
  State.docs.forEach(d => {
    tbody.appendChild(el(`
      <tr>
        <td class="font-mono text-xs">${d.id}</td>
        <td>${esc(d.file_name)}</td>
        <td><span class="cat-tag">${esc(d.category || "—")}</span></td>
        <td>${esc(d.subcategory || "—")}</td>
        <td>${esc(d.year || "—")}</td>
        <td class="text-xs text-slate-500">${fmtTime(d.created_at)}</td>
      </tr>
    `));
  });
}

document.getElementById("refresh-docs").addEventListener("click", loadDocs);

document.getElementById("upload-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const form = ev.target;
  const fd = new FormData(form);
  const status = document.getElementById("upload-status");
  status.textContent = "上传中…";
  try {
    const doc = await api("/documents", { method: "POST", body: fd });
    State.docs.unshift(doc);
    status.textContent = `✓ 已上传：${doc.file_name} (id=${doc.id})`;
    status.className = "text-sm text-emerald-600";
    form.reset();
    loadDocs();
    document.getElementById("stat-docs").textContent = State.docs.length;
  } catch (e) {
    status.textContent = "✗ " + e.message;
    status.className = "text-sm text-rose-600";
  }
});

// ─── 单文件检查 ───────────────────────────────────────
async function loadDocsForCheck() {
  const sel = document.getElementById("check-doc");
  sel.innerHTML = State.docs.length === 0
    ? `<option value="">请先在「文档管理」上传文档</option>`
    : State.docs.map(d => `<option value="${d.id}">[${d.id}] ${esc(d.file_name)} (${esc(d.category || "未分类")})</option>`).join("");

  if (State.templates.length === 0) {
    State.templates = await api("/templates");
  }
  const tsel = document.getElementById("check-template");
  tsel.innerHTML = State.templates
    .filter(t => t.ready)
    .map(t => `<option value="${t.key}">${esc(t.name)} (${esc(t.applies_to)})</option>`).join("");
}

document.getElementById("check-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const status = document.getElementById("check-status");
  const resultBox = document.getElementById("check-result");
  status.textContent = "检查中（包含 RAG+LLM 调用，可能耗时）…";
  status.className = "text-sm text-indigo-600 mt-3";
  resultBox.classList.add("hidden");
  try {
    const task = await api("/checks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_id: parseInt(fd.get("document_id")),
        template_key: fd.get("template_key"),
      }),
    });
    State.checkCount += 1;
    State.issueCount += task.issues.length;
    document.getElementById("stat-checks").textContent = State.checkCount;
    document.getElementById("stat-issues").textContent = State.issueCount;
    renderCheckResult(task);
    status.textContent = `✓ 检查完成（任务 #${task.id}）`;
    status.className = "text-sm text-emerald-600 mt-3";
  } catch (e) {
    status.textContent = "✗ " + e.message;
    status.className = "text-sm text-rose-600 mt-3";
  }
});

function renderCheckResult(task) {
  const box = document.getElementById("check-result");
  box.classList.remove("hidden");
  document.getElementById("check-result-title").textContent = `检查结果 · 任务 #${task.id}`;
  document.getElementById("check-result-summary").textContent = task.summary;
  document.getElementById("report-link").href = `${API}/checks/${task.id}/report`;

  const tbody = document.getElementById("issues-tbody");
  tbody.innerHTML = "";
  if (!task.issues.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-center text-emerald-600 py-6">✓ 未发现疑点。</td></tr>`;
    return;
  }
  task.issues.forEach((i, idx) => {
    tbody.appendChild(el(`
      <tr>
        <td class="font-mono text-xs">${idx + 1}</td>
        <td>${esc(i.description)}<div class="text-xs text-slate-400 mt-1">规则：${esc(i.rule_id)} · ${i.source === "rigid" ? "刚性" : i.source === "soft" ? "柔性(LLM)" : i.source}</div></td>
        <td class="text-xs text-slate-600">${esc(i.location || "—")}</td>
        <td><span class="cat-tag">${esc(i.category)}</span></td>
        <td><span class="badge badge-${i.risk_level}">${esc(i.risk_level)}</span></td>
        <td class="text-xs">${esc(i.suggestion || "—")}</td>
      </tr>
    `));
  });
}

// ─── 联动校验 ─────────────────────────────────────────
const CHAIN_CONFIGS = {
  procurement: {
    title: "招采链联动校验",
    desc: "招标 → 投标 → 评标 → 合同 跨文件字段比对",
    endpoint: "/chain-checks",
    fields: [
      { key: "tender_doc_id", label: "招标文件" },
      { key: "bid_doc_id", label: "投标文件" },
      { key: "eval_doc_id", label: "评标报告" },
      { key: "contract_doc_id", label: "合同" },
    ],
  },
  finance: {
    title: "财务链联动校验",
    desc: "财务报告 → 决算报告 → 资产报告 → 合同 数据交叉互验",
    endpoint: "/chain-checks/finance",
    fields: [
      { key: "finance_doc_id", label: "财务报告" },
      { key: "final_account_doc_id", label: "决算报告" },
      { key: "asset_doc_id", label: "资产报告" },
      { key: "contract_doc_ids", label: "合同（多选）", multi: true },
    ],
  },
  report: {
    title: "报告链联动校验",
    desc: "内控报告 → 绩效报告 → 项目资料 内容交叉印证",
    endpoint: "/chain-checks/report",
    fields: [
      { key: "ic_doc_id", label: "内控报告" },
      { key: "perf_doc_id", label: "绩效评价报告" },
      { key: "project_doc_id", label: "项目资料" },
    ],
  },
};

let activeChain = "procurement";

document.querySelectorAll(".chain-tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".chain-tab").forEach(b => b.classList.remove("chain-active"));
    btn.classList.add("chain-active");
    activeChain = btn.dataset.chain;
    renderChainForm();
  });
});

function loadDocsForChain() {
  renderChainForm();
}

function renderChainForm() {
  const cfg = CHAIN_CONFIGS[activeChain];
  document.getElementById("chain-title").textContent = cfg.title;
  document.getElementById("chain-desc").textContent = cfg.desc;
  document.getElementById("chain-result").classList.add("hidden");

  const form = document.getElementById("chain-form");
  form.innerHTML = "";
  cfg.fields.forEach(f => {
    const opts = `<option value="">— 不选 —</option>` +
      State.docs.map(d => `<option value="${d.id}">[${d.id}] ${esc(d.file_name)}</option>`).join("");
    form.appendChild(el(`
      <div>
        <label class="form-label">${esc(f.label)}</label>
        <select name="${f.key}" class="form-input" ${f.multi ? "multiple size=4" : ""}>${opts}</select>
        ${f.multi ? '<p class="text-xs text-slate-500 mt-1">按住 Ctrl/⌘ 多选</p>' : ""}
      </div>
    `));
  });
}

document.getElementById("chain-submit").addEventListener("click", async () => {
  const cfg = CHAIN_CONFIGS[activeChain];
  const form = document.getElementById("chain-form");
  const fd = new FormData(form);

  // 构造 payload
  const payload = {};
  cfg.fields.forEach(f => {
    if (f.multi) {
      const sel = form.elements[f.key];
      payload[f.key] = Array.from(sel.selectedOptions).map(o => parseInt(o.value)).filter(v => v);
    } else {
      const v = fd.get(f.key);
      payload[f.key] = v ? parseInt(v) : null;
    }
  });

  const status = document.getElementById("chain-status");
  status.textContent = "联动校验中…";
  status.className = "text-sm text-indigo-600";

  try {
    const task = await api(cfg.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    State.chainCount += 1;
    State.issueCount += task.issues.length;
    document.getElementById("stat-chains").textContent = State.chainCount;
    document.getElementById("stat-issues").textContent = State.issueCount;
    renderChainResult(task);
    status.textContent = `✓ 联动校验完成（任务 #${task.id}）`;
    status.className = "text-sm text-emerald-600";
  } catch (e) {
    status.textContent = "✗ " + e.message;
    status.className = "text-sm text-rose-600";
  }
});

function renderChainResult(task) {
  document.getElementById("chain-result").classList.remove("hidden");
  document.getElementById("chain-result-summary").textContent = task.summary;
  try {
    const fields = JSON.parse(task.extracted_fields || "{}");
    document.getElementById("extracted-fields").textContent = JSON.stringify(fields, null, 2);
  } catch {
    document.getElementById("extracted-fields").textContent = task.extracted_fields || "（无）";
  }
  const tbody = document.getElementById("chain-issues-tbody");
  tbody.innerHTML = "";
  if (!task.issues.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="text-center text-emerald-600 py-6">✓ 跨文件比对未发现不一致。</td></tr>`;
    return;
  }
  task.issues.forEach((i, idx) => {
    tbody.appendChild(el(`
      <tr>
        <td class="font-mono text-xs">${idx + 1}</td>
        <td>${esc(i.description)}<div class="text-xs text-slate-400 mt-1">规则：${esc(i.rule_id)}</div></td>
        <td class="text-xs text-slate-600">${esc(i.location || "—")}</td>
        <td><span class="badge badge-${i.risk_level}">${esc(i.risk_level)}</span></td>
        <td class="text-xs">${esc(i.suggestion || "—")}</td>
      </tr>
    `));
  });
}

// ─── 认证 ─────────────────────────────────────────────
const Auth = { user: null, roleLabel: "", allowedCategories: [] };

function showLogin(msg = "") {
  document.getElementById("login-modal").classList.remove("hidden");
  const errBox = document.getElementById("login-error");
  if (msg) {
    errBox.textContent = msg;
    errBox.classList.remove("hidden");
  } else {
    errBox.classList.add("hidden");
  }
}

function hideLogin() {
  document.getElementById("login-modal").classList.add("hidden");
}

function renderUserBar() {
  const bar = document.getElementById("user-bar");
  if (!Auth.user) {
    bar.innerHTML = "";
    return;
  }
  bar.innerHTML = `
    <span class="text-sm">
      <span class="font-medium">${esc(Auth.user.full_name || Auth.user.username)}</span>
      <span class="text-xs text-slate-400 ml-1">· ${esc(Auth.roleLabel)}</span>
    </span>
    <button id="logout-btn" class="btn-secondary text-xs">退出</button>
  `;
  document.getElementById("logout-btn").addEventListener("click", async () => {
    try { await api("/auth/logout", { method: "POST" }); } catch {}
    setToken("");
    Auth.user = null;
    renderUserBar();
    document.getElementById("nav-admin").style.display = "none";
    showLogin();
  });
  document.getElementById("nav-admin").style.display =
    Auth.user.role === "admin" ? "" : "none";
}

document.getElementById("login-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  try {
    const r = await fetch(API + "/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: fd.get("username"),
        password: fd.get("password"),
      }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: "登录失败" }));
      throw new Error(err.detail || "登录失败");
    }
    const data = await r.json();
    setToken(data.token);
    Auth.user = data.user;
    Auth.roleLabel = data.role_label;
    Auth.allowedCategories = data.allowed_categories;
    hideLogin();
    renderUserBar();
    loadDashboard();
  } catch (e) {
    showLogin(e.message);
  }
});

// ─── 系统管理（仅管理员）─────────────────────────────
async function loadAdmin() {
  if (!Auth.user || Auth.user.role !== "admin") return;
  try {
    const users = await api("/users");
    const utbody = document.getElementById("users-tbody");
    utbody.innerHTML = users.map(u => `
      <tr>
        <td class="font-mono text-xs">${u.id}</td>
        <td>${esc(u.username)}</td>
        <td><span class="cat-tag">${esc(u.role)}</span></td>
        <td>${esc(u.full_name || "—")}</td>
        <td>${u.is_active ? "✓" : "✗"}</td>
      </tr>`).join("");

    const logs = await api("/audit-logs?limit=100");
    const atbody = document.getElementById("audit-tbody");
    atbody.innerHTML = logs.map(l => `
      <tr>
        <td class="text-xs text-slate-500">${fmtTime(l.created_at)}</td>
        <td>${esc(l.username || "—")}</td>
        <td><span class="cat-tag">${esc(l.action)}</span></td>
        <td class="text-xs">${esc(l.target_type)}${l.target_id ? ' #' + l.target_id : ''}</td>
        <td class="text-xs text-slate-600">${esc(l.detail || "—")}</td>
      </tr>`).join("") || `<tr><td colspan="5" class="text-center text-slate-400 py-4">无日志</td></tr>`;
  } catch (e) {
    console.error(e);
  }
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

// 给「系统管理」tab 注册 loadAdmin 钩子（覆盖原 nav-tab 行为）
document.querySelector('[data-tab="admin"]').addEventListener("click", loadAdmin);

// ─── 启动 ─────────────────────────────────────────────
async function bootstrap() {
  if (getToken()) {
    try {
      const data = await api("/auth/me");
      Auth.user = data.user;
      Auth.roleLabel = data.role_label;
      Auth.allowedCategories = data.allowed_categories;
      hideLogin();
      renderUserBar();
      loadDashboard();
      return;
    } catch {
      // token 失效 → 落到登录界面
    }
  }
  showLogin();
}
bootstrap();
