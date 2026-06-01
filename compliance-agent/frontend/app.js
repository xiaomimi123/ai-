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
    if (btn.dataset.tab === "batches") loadBatches();
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

// 通用轮询：直到 task.status ∈ {done, failed} 或超时
async function pollTask(getPath, statusEl, max = 60) {
  for (let i = 0; i < max; i++) {
    const task = await api(getPath);
    if (task.status === "done" || task.status === "failed") return task;
    statusEl.textContent = `任务排队中（${task.status === "pending" ? "等待 worker" : "执行中"}）…`;
    await new Promise(r => setTimeout(r, 1000));
  }
  throw new Error("任务执行超时（60s 未完成）");
}

document.getElementById("check-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const status = document.getElementById("check-status");
  const resultBox = document.getElementById("check-result");
  status.textContent = "提交任务到队列…";
  status.className = "text-sm text-indigo-600 mt-3";
  resultBox.classList.add("hidden");
  try {
    const initial = await api("/checks/async", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_id: parseInt(fd.get("document_id")),
        template_key: fd.get("template_key"),
      }),
    });
    // 轮询直到完成
    const task = await pollTask(`/checks/${initial.id}`, status);
    if (task.status === "failed") throw new Error(task.summary || "任务失败");
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

const STATUS_LABEL = {
  open: "新建", assigned: "已下发", fixing: "整改中",
  reviewing: "待复核", resolved: "已销号", rejected: "已打回",
};

function renderCheckResult(task) {
  const box = document.getElementById("check-result");
  box.classList.remove("hidden");
  document.getElementById("check-result-title").textContent = `检查结果 · 任务 #${task.id}`;
  document.getElementById("check-result-summary").textContent = task.summary;
  document.getElementById("report-link").href = `${API}/checks/${task.id}/report`;

  const tbody = document.getElementById("issues-tbody");
  tbody.innerHTML = "";
  if (!task.issues.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-center text-emerald-600 py-6">✓ 未发现疑点。</td></tr>`;
    return;
  }
  task.issues.forEach((i, idx) => {
    const row = el(`
      <tr>
        <td class="font-mono text-xs">${idx + 1}</td>
        <td>${esc(i.description)}<div class="text-xs text-slate-400 mt-1">规则：${esc(i.rule_id)} · ${i.source === "rigid" ? "刚性" : i.source === "soft" ? "柔性(LLM)" : i.source}</div></td>
        <td class="text-xs text-slate-600">${esc(i.location || "—")}</td>
        <td><span class="badge badge-${i.risk_level}">${esc(i.risk_level)}</span></td>
        <td class="text-xs"><span class="cat-tag">${esc(STATUS_LABEL[i.handle_status] || i.handle_status)}</span></td>
        <td class="text-xs">${esc(i.suggestion || "—")}</td>
        <td><button class="btn-secondary text-xs" data-issue="${i.id}">协同复核</button></td>
      </tr>
    `);
    row.querySelector("button").addEventListener("click", () => openIssueModal(i.id));
    tbody.appendChild(row);
  });
}

// ─── 协同复核模态 ─────────────────────────────────────
let _modalIssueId = null;

async function openIssueModal(issueId) {
  _modalIssueId = issueId;
  document.getElementById("issue-modal").classList.remove("hidden");
  await refreshIssueModal();
}

document.getElementById("modal-close").addEventListener("click", () => {
  document.getElementById("issue-modal").classList.add("hidden");
  _modalIssueId = null;
});

async function refreshIssueModal() {
  if (!_modalIssueId) return;
  const issue = await api(`/issues/${_modalIssueId}`);
  document.getElementById("modal-issue-title").textContent = issue.description;
  document.getElementById("m-rule").textContent = issue.rule_id;
  document.getElementById("m-risk").innerHTML = `<span class="badge badge-${issue.risk_level}">${esc(issue.risk_level)}</span>`;
  document.getElementById("m-loc").textContent = issue.location || "—";
  document.getElementById("m-status").textContent = STATUS_LABEL[issue.handle_status] || issue.handle_status;
  document.getElementById("m-sugg").textContent = issue.suggestion || "—";

  const fixBox = document.getElementById("m-fix-note-box");
  fixBox.style.display = issue.fix_note ? "" : "none";
  document.getElementById("m-fix-note").textContent = issue.fix_note || "";

  const reviewBox = document.getElementById("m-review-note-box");
  reviewBox.style.display = issue.review_note ? "" : "none";
  document.getElementById("m-review-note").textContent = issue.review_note || "";

  // 渲染按钮组（根据状态 + 当前用户角色）
  renderActionButtons(issue);
  await loadComments();
}

const ACTION_BUTTONS = {
  // status -> [{ action, label, color, adminOnly, needsNote }, ...]
  open: [
    { action: "assign", label: "指派", adminOnly: true, needsAssignee: true },
  ],
  assigned: [
    { action: "start", label: "开始整改" },
    { action: "assign", label: "改派", adminOnly: true, needsAssignee: true },
  ],
  fixing: [
    { action: "submit", label: "提交整改", needsNote: true, noteLabel: "整改说明" },
  ],
  reviewing: [
    { action: "approve", label: "通过销号", adminOnly: true, needsNote: true,
      noteLabel: "复核意见（可空）", optionalNote: true, color: "emerald" },
    { action: "reject", label: "打回", adminOnly: true, needsNote: true,
      noteLabel: "打回原因（必填）", color: "rose" },
  ],
  rejected: [
    { action: "reopen", label: "重新整改" },
  ],
  resolved: [],
};

function renderActionButtons(issue) {
  const box = document.getElementById("m-action-buttons");
  const role = Auth.user?.role;
  const isAdmin = role === "admin";
  const actions = ACTION_BUTTONS[issue.handle_status] || [];
  if (actions.length === 0) {
    box.innerHTML = `<span class="text-sm text-slate-500">当前状态无可执行操作。</span>`;
    return;
  }
  box.innerHTML = "";
  actions.forEach(a => {
    if (a.adminOnly && !isAdmin) return;
    const btn = el(`<button class="btn-primary" style="${a.color === 'rose' ? 'background:#dc2626' : a.color === 'emerald' ? 'background:#059669' : ''}">${esc(a.label)}</button>`);
    btn.addEventListener("click", () => openActionModal(issue, a));
    box.appendChild(btn);
  });
}

async function openActionModal(issue, action) {
  document.getElementById("am-title").textContent = action.label;
  document.getElementById("am-error").classList.add("hidden");
  document.getElementById("am-note").value = "";

  const assigneeBox = document.getElementById("am-assignee-box");
  const noteBox = document.getElementById("am-note-box");
  const noteLabel = document.getElementById("am-note-label");

  if (action.needsAssignee) {
    assigneeBox.style.display = "";
    const users = await api("/users");
    const sel = document.getElementById("am-assignee");
    sel.innerHTML = users
      .filter(u => u.is_active && u.role !== "admin")
      .map(u => `<option value="${u.id}">${esc(u.username)}（${esc(u.role)}）${u.full_name ? ' - ' + esc(u.full_name) : ''}</option>`)
      .join("") || `<option value="">— 无可选用户 —</option>`;
  } else {
    assigneeBox.style.display = "none";
  }

  if (action.needsNote) {
    noteBox.style.display = "";
    noteLabel.textContent = action.noteLabel || "说明";
  } else {
    noteBox.style.display = "none";
  }

  document.getElementById("action-modal").classList.remove("hidden");

  document.getElementById("am-confirm").onclick = async () => {
    const payload = {};
    if (action.needsAssignee) {
      const id = parseInt(document.getElementById("am-assignee").value);
      if (!id) {
        showActionError("请选择被指派人"); return;
      }
      payload.assignee_id = id;
    }
    if (action.needsNote) {
      const note = document.getElementById("am-note").value.trim();
      if (!note && !action.optionalNote) {
        showActionError(`请填写${action.noteLabel || "说明"}`); return;
      }
      if (action.action === "submit") payload.fix_note = note;
      else payload.review_note = note;
    }
    try {
      await api(`/issues/${issue.id}/${action.action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      document.getElementById("action-modal").classList.add("hidden");
      await refreshIssueModal();
    } catch (e) {
      showActionError(e.message);
    }
  };
}

function showActionError(msg) {
  const e = document.getElementById("am-error");
  e.textContent = msg;
  e.classList.remove("hidden");
}

document.getElementById("am-cancel").addEventListener("click", () => {
  document.getElementById("action-modal").classList.add("hidden");
});

async function loadComments() {
  if (!_modalIssueId) return;
  const comments = await api(`/issues/${_modalIssueId}/comments`);
  const box = document.getElementById("m-comments");
  if (!comments.length) {
    box.innerHTML = `<div class="text-sm text-slate-400 text-center py-4">暂无批注</div>`;
    return;
  }
  box.innerHTML = comments.map(c => `
    <div class="bg-slate-50 rounded p-2 border border-slate-200">
      <div class="flex items-baseline justify-between">
        <span class="font-medium text-sm">${esc(c.author_name)}</span>
        <span class="text-xs text-slate-400">${fmtTime(c.created_at)}</span>
      </div>
      <div class="text-sm text-slate-700 mt-1 whitespace-pre-wrap">${esc(c.body)}</div>
    </div>`).join("");
  box.scrollTop = box.scrollHeight;
}

document.getElementById("m-comment-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const input = document.getElementById("m-comment-body");
  const body = input.value.trim();
  if (!body || !_modalIssueId) return;
  try {
    await api(`/issues/${_modalIssueId}/comments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body }),
    });
    input.value = "";
    await loadComments();
  } catch (e) {
    alert("发送失败：" + e.message);
  }
});

// ─── 联动校验 ─────────────────────────────────────────
const CHAIN_CONFIGS = {
  procurement: {
    title: "招采链联动校验",
    desc: "招标 → 投标 → 评标 → 合同 跨文件字段比对",
    endpoint: "/chain-checks/async",
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
    endpoint: "/chain-checks/finance/async",
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
    endpoint: "/chain-checks/report/async",
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
    const initial = await api(cfg.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const task = await pollTask(`/chain-checks/${initial.id}`, status);
    if (task.status === "failed") throw new Error(task.summary || "联动校验失败");
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

// ─── 批次管理 ─────────────────────────────────────────
let _activeBatchId = null;

async function loadBatches() {
  try {
    const batches = await api("/batches");
    const tbody = document.getElementById("batches-tbody");
    if (!batches.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-center text-slate-400 py-6">暂无批次。请在上方创建批次。</td></tr>`;
      return;
    }
    tbody.innerHTML = "";
    batches.forEach(b => {
      const row = el(`
        <tr>
          <td class="font-mono text-xs">${b.id}</td>
          <td class="font-medium">${esc(b.name)}</td>
          <td>${esc(b.project_id || "—")}</td>
          <td>${esc(b.year || "—")}</td>
          <td>${esc(b.department || "—")}</td>
          <td class="text-xs text-slate-500">${fmtTime(b.created_at)}</td>
          <td><button class="btn-secondary text-xs" data-id="${b.id}">查看</button></td>
        </tr>`);
      row.querySelector("button").addEventListener("click", () => openBatchDetail(b.id));
      tbody.appendChild(row);
    });
  } catch (e) {
    console.error(e);
  }
}

document.getElementById("batch-create-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const status = document.getElementById("batch-create-status");
  try {
    const b = await api("/batches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: fd.get("name"),
        project_id: fd.get("project_id") || "",
        year: fd.get("year") || "",
        department: fd.get("department") || "",
      }),
    });
    status.textContent = `✓ 批次 #${b.id} 已创建`;
    status.className = "text-sm mt-2 text-emerald-600";
    ev.target.reset();
    loadBatches();
    openBatchDetail(b.id);
  } catch (e) {
    status.textContent = "✗ " + e.message;
    status.className = "text-sm mt-2 text-rose-600";
  }
});

document.getElementById("bd-close").addEventListener("click", () => {
  document.getElementById("batch-detail").classList.add("hidden");
  _activeBatchId = null;
});

async function openBatchDetail(batchId) {
  _activeBatchId = batchId;
  document.getElementById("batch-detail").classList.remove("hidden");
  await refreshBatchDetail();
}

const CHAIN_LABELS = { procurement: "招采链", finance: "财务链", report: "报告链" };

async function refreshBatchDetail() {
  if (!_activeBatchId) return;
  const data = await api(`/batches/${_activeBatchId}`);
  const b = data.batch;
  document.getElementById("bd-title").textContent = `批次 #${b.id} · ${b.name}`;
  document.getElementById("bd-meta").textContent =
    `${b.project_id || ""} ${b.year || ""} ${b.department || ""}`.trim() || "无附加信息";

  const s = data.summary;
  const sumBox = document.getElementById("bd-summary");
  sumBox.innerHTML = `
    <div class="bg-slate-50 rounded p-3 border border-slate-200">
      <div class="text-xs text-slate-500">文档总数</div>
      <div class="text-2xl font-semibold mt-1">${s.documents_total}</div>
    </div>
    <div class="bg-slate-50 rounded p-3 border border-slate-200">
      <div class="text-xs text-slate-500">检查任务</div>
      <div class="text-2xl font-semibold mt-1">${s.check_tasks.length}</div>
    </div>
    <div class="bg-slate-50 rounded p-3 border border-slate-200">
      <div class="text-xs text-slate-500">联动校验</div>
      <div class="text-2xl font-semibold mt-1">${s.chain_tasks.length}</div>
    </div>
    <div class="bg-rose-50 rounded p-3 border border-rose-200">
      <div class="text-xs text-rose-600">疑点总数</div>
      <div class="text-2xl font-semibold text-rose-700 mt-1">${s.issues_total}</div>
      <div class="text-xs text-slate-500 mt-1">高 ${s.issues_by_risk["高"] || 0} · 中 ${s.issues_by_risk["中"] || 0} · 低 ${s.issues_by_risk["低"] || 0}</div>
    </div>
  `;

  const checkTbody = document.getElementById("bd-check-tbody");
  checkTbody.innerHTML = s.check_tasks.length === 0
    ? `<tr><td colspan="5" class="text-center text-slate-400 py-4">尚无检查任务</td></tr>`
    : s.check_tasks.map(t => `
        <tr>
          <td class="font-mono text-xs">#${t.id}</td>
          <td class="text-xs">文档 #${t.document_id}</td>
          <td><span class="cat-tag">${esc(t.template_key)}</span></td>
          <td><span class="cat-tag">${esc(t.status)}</span></td>
          <td class="text-xs">${esc(t.summary || "—")}</td>
        </tr>`).join("");

  const chainTbody = document.getElementById("bd-chain-tbody");
  chainTbody.innerHTML = s.chain_tasks.length === 0
    ? `<tr><td colspan="4" class="text-center text-slate-400 py-4">尚未触发联动校验（需批次内文档凑齐对应链路）</td></tr>`
    : s.chain_tasks.map(t => `
        <tr>
          <td class="font-mono text-xs">#${t.id}</td>
          <td>${esc(CHAIN_LABELS[t.chain_type] || t.chain_type)}</td>
          <td><span class="cat-tag">${esc(t.status)}</span></td>
          <td class="text-xs">${esc(t.summary || "—")}</td>
        </tr>`).join("");
}

document.getElementById("batch-upload-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  if (!_activeBatchId) return;
  const fd = new FormData();
  const fileInput = document.getElementById("bd-files");
  if (!fileInput.files.length) return;
  for (const f of fileInput.files) fd.append("files", f);

  const status = document.getElementById("bd-upload-status");
  status.textContent = `上传中（${fileInput.files.length} 个文件）…`;
  status.className = "text-sm mt-2 text-indigo-600";
  try {
    const tok = getToken();
    const r = await fetch(`${API}/batches/${_activeBatchId}/upload`, {
      method: "POST",
      headers: { "Authorization": "Bearer " + tok },
      body: fd,
    });
    if (!r.ok) throw new Error(await r.text());
    const result = await r.json();
    // 展示分类结果
    const resultsBox = document.getElementById("bd-upload-results");
    resultsBox.innerHTML = `
      <table class="table mt-2">
        <thead><tr><th>文件</th><th>识别分类</th><th>方式</th><th>检查任务</th><th>状态</th></tr></thead>
        <tbody>${result.items.map(i => `
          <tr>
            <td class="text-xs">${esc(i.file_name)}</td>
            <td><span class="cat-tag">${esc(i.category || "—")}</span>${i.subcategory ? ' / ' + esc(i.subcategory) : ''}</td>
            <td class="text-xs text-slate-500">${esc(i.method)} (${(i.confidence * 100).toFixed(0)}%)</td>
            <td class="text-xs">${i.check_task_id ? '#' + i.check_task_id : '—'}</td>
            <td class="text-xs ${i.error ? 'text-rose-600' : 'text-emerald-600'}">${i.error || '✓ 已入队'}</td>
          </tr>`).join("")}
        </tbody>
      </table>
      ${Object.keys(result.triggered_chains || {}).length > 0 ? `
        <div class="mt-3 p-3 bg-indigo-50 border border-indigo-200 rounded text-sm">
          <strong>自动触发联动校验：</strong>
          ${Object.entries(result.triggered_chains).map(([k, v]) =>
            `${CHAIN_LABELS[k] || k} (任务 #${v})`).join(" / ")}
        </div>` : ""}
    `;
    status.textContent = `✓ 上传完成`;
    status.className = "text-sm mt-2 text-emerald-600";
    fileInput.value = "";
    // 短暂等待 worker 完成后刷新
    setTimeout(refreshBatchDetail, 1500);
  } catch (e) {
    status.textContent = "✗ " + e.message;
    status.className = "text-sm mt-2 text-rose-600";
  }
});

document.getElementById("bd-retrigger").addEventListener("click", async () => {
  if (!_activeBatchId) return;
  try {
    const r = await api(`/batches/${_activeBatchId}/retrigger`, { method: "POST" });
    alert(`重新触发：${JSON.stringify(r.triggered)}`);
    setTimeout(refreshBatchDetail, 1500);
  } catch (e) {
    alert("失败：" + e.message);
  }
});

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
