/* Recertia console — Pilot / Tower / Ops (C0–C5) */

const $ = (sel) => document.querySelector(sel);
const state = { session: localStorage.getItem("recertia_session") || "" };

function apiKey() { return $("#apiKey").value.trim(); }
function tenantHeader() { return $("#tenantHeader").value.trim(); }

async function api(path, opts = {}) {
  const headers = Object.assign({ "content-type": "application/json" }, opts.headers || {});
  if (apiKey()) headers["X-API-Key"] = apiKey();
  if (state.session) headers["X-Recertia-Session"] = state.session;
  if (tenantHeader()) headers["X-Recertia-Tenant"] = tenantHeader();
  const res = await fetch(path, { ...opts, headers });
  const text = await res.text();
  let body;
  try { body = text ? JSON.parse(text) : null; } catch { body = { raw: text }; }
  if (!res.ok) throw new Error(body?.detail || body?.error?.message || res.statusText);
  return body;
}

function showView(name) {
  document.querySelectorAll(".view").forEach((el) => el.classList.remove("active"));
  document.querySelectorAll(".nav button[data-view]").forEach((el) => el.classList.remove("active"));
  $(`#view-${name}`).classList.add("active");
  document.querySelector(`.nav button[data-view="${name}"]`).classList.add("active");
}

document.querySelectorAll(".nav button[data-view]").forEach((btn) => {
  btn.addEventListener("click", () => showView(btn.dataset.view));
});

function addDesiredRow(prefill = {}) {
  const row = document.createElement("div");
  row.className = "desired-row";
  row.innerHTML = `
    <input placeholder="id" value="${prefill.id || ""}" data-f="id" />
    <select data-f="kind">
      <option value="file_exists">file_exists</option>
      <option value="file_contains">file_contains</option>
      <option value="command">command</option>
    </select>
    <input placeholder="path / pattern / command" value="${prefill.path || prefill.pattern || prefill.run || ""}" data-f="value" />
    <button type="button" class="danger">×</button>`;
  if (prefill.kind) row.querySelector('[data-f="kind"]').value = prefill.kind;
  row.querySelector("button").onclick = () => row.remove();
  $("#desiredList").appendChild(row);
}

$("#addDesired").onclick = () => addDesiredRow({ id: `d${$("#desiredList").children.length + 1}`, kind: "file_exists" });
addDesiredRow({ id: "d1", kind: "file_exists", path: ".gitignore" });

function buildGoal() {
  const desired = [...$("#desiredList").children].map((row, i) => {
    const id = row.querySelector('[data-f="id"]').value || `d${i + 1}`;
    const kind = row.querySelector('[data-f="kind"]').value;
    const value = row.querySelector('[data-f="value"]').value;
    const base = { id, kind, weight: 1.0 };
    if (kind === "file_exists") return { ...base, path: value };
    if (kind === "file_contains") return { ...base, path: value.split("|")[0], pattern: value.split("|")[1] || value };
    return { ...base, run: value };
  });
  return {
    goal_id: `console-${Date.now()}`,
    desired,
    constraints: [],
    context: $("#goalContext").value || null,
    task_class: $("#taskClass").value || "repo-chore",
  };
}

$("#previewGoal").onclick = async () => {
  try {
    const out = await api("/v1/goals/preview", { method: "POST", body: JSON.stringify({ goal: buildGoal() }) });
    $("#previewOut").textContent = JSON.stringify(out, null, 2);
  } catch (e) { $("#previewOut").textContent = String(e); }
};

$("#submitRun").onclick = async () => {
  try {
    const goal = buildGoal();
    const mode = $("#runMode").value;
    const body = { goal, task_class: goal.task_class, mode, budget: { max_attempts: 2 } };
    const res = await fetch("/v1/runs", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...(apiKey() ? { "X-API-Key": apiKey() } : {}),
        ...(state.session ? { "X-Recertia-Session": state.session } : {}),
      },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    $("#previewOut").textContent = JSON.stringify({ status: res.status, ...data }, null, 2);
    if (mode === "async" && data.run_id) streamEvents(data.run_id);
  } catch (e) { $("#previewOut").textContent = String(e); }
};

async function loadTemplates() {
  try {
    const data = await api("/v1/templates");
    const sel = $("#templateSelect");
    for (const t of data.templates || []) {
      const opt = document.createElement("option");
      opt.value = t.id; opt.textContent = t.title;
      sel.appendChild(opt);
    }
  } catch { /* key may be empty on first paint */ }
}

$("#templateSelect").onchange = async () => {
  const id = $("#templateSelect").value;
  if (!id) return;
  const data = await api(`/v1/templates/${id}`);
  const g = data.goal;
  $("#goalContext").value = g.context || "";
  $("#taskClass").value = g.task_class || "repo-chore";
  $("#desiredList").innerHTML = "";
  for (const d of g.desired || []) {
    addDesiredRow({
      id: d.id,
      kind: d.kind,
      path: d.path,
      pattern: d.pattern,
      run: d.run,
    });
  }
};

async function refreshRuns() {
  const data = await api("/v1/runs");
  const tb = $("#runsTable tbody");
  tb.innerHTML = "";
  for (const r of data.items || []) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${r.run_id}</td><td>${r.task_class}</td><td>${r.terminal || r.status}</td><td>${r.cost_usd ?? "—"}</td><td><button class="secondary">Open</button></td>`;
    tr.querySelector("button").onclick = () => openRun(r.run_id);
    tb.appendChild(tr);
  }
}

async function openRun(runId) {
  const rec = await api(`/v1/runs/${runId}`);
  $("#runDetail").classList.remove("hidden");
  $("#runDetail").textContent = JSON.stringify(rec, null, 2);
  try {
    const tr = await api(`/v1/runs/${runId}/transcript`);
    $("#runDetail").textContent += "\n\n--- transcript ---\n" + JSON.stringify(tr, null, 2);
  } catch { /* optional */ }
  streamEvents(runId);
}

function streamEvents(runId) {
  const el = $("#eventStream");
  el.classList.remove("hidden");
  el.textContent = `SSE ${runId}…\n`;
  const headers = {};
  if (apiKey()) headers["X-API-Key"] = apiKey();
  // EventSource cannot set headers; use fetch stream for keyed auth
  fetch(`/v1/runs/${runId}/events`, { headers }).then(async (res) => {
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      el.textContent += dec.decode(value);
      el.scrollTop = el.scrollHeight;
    }
  }).catch((e) => { el.textContent += String(e); });
}

$("#refreshRuns").onclick = () => refreshRuns().catch((e) => alert(e));

async function refreshSkills() {
  const data = await api("/v1/skills");
  const tb = $("#skillsTable tbody");
  tb.innerHTML = "";
  for (const s of data.items || []) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${s.skill_id}</td><td>${s.version}</td><td>${s.lifecycle}</td><td>${s.active}</td><td><button class="secondary">View</button> <button class="primary">Promote</button></td>`;
    tr.querySelectorAll("button")[0].onclick = async () => {
      const d = await api(`/v1/skills/${s.skill_id}/versions/${s.version}`);
      $("#skillDetail").classList.remove("hidden");
      $("#skillDetail").textContent = JSON.stringify(d, null, 2);
    };
    tr.querySelectorAll("button")[1].onclick = async () => {
      if (!confirm(`Promote ${s.skill_id}@v${s.version}? Golden gate required.`)) return;
      const d = await api(`/v1/skills/${s.skill_id}/versions/${s.version}/promote`, { method: "POST", body: "{}" });
      $("#skillDetail").classList.remove("hidden");
      $("#skillDetail").textContent = JSON.stringify(d, null, 2);
    };
    tb.appendChild(tr);
  }
}
$("#refreshSkills").onclick = () => refreshSkills().catch((e) => alert(e));

async function refreshTower() {
  const summary = await api("/v1/console/tower-summary");
  $("#towerSummary").innerHTML = `
    <div class="card"><div class="k">active_cap_pressure</div><div class="v">${summary.active_cap_pressure ?? "—"}</div></div>
    <div class="card"><div class="k">composition depth</div><div class="v">${summary.mean_composition_depth ?? "—"}</div></div>
    <div class="card"><div class="k">practice_conversion</div><div class="v">${summary.practice_conversion ?? summary.practice_conversion_unavailable ?? "—"}</div></div>
    <div class="card"><div class="k">pending proposals</div><div class="v">${summary.pending_proposals}</div></div>`;
  const props = await api("/v1/proposals");
  const tb = $("#proposalsTable tbody");
  tb.innerHTML = "";
  for (const p of props.items || []) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${p.proposal_id}</td><td>${p.kind}</td><td>${p.skill_id}</td><td>${p.status}</td>
      <td><button class="secondary">Open</button>
      <button class="primary" ${p.status !== "pending" ? "disabled" : ""}>Approve</button>
      <button class="danger" ${p.status !== "pending" ? "disabled" : ""}>Reject</button></td>`;
    const [openBtn, okBtn, noBtn] = tr.querySelectorAll("button");
    openBtn.onclick = () => {
      $("#proposalDetail").classList.remove("hidden");
      $("#proposalDetail").textContent = JSON.stringify(p, null, 2);
      if (p.payload?.replay_pack) {
        $("#proposalDetail").textContent += "\n\n--- replay_pack ---\n" + JSON.stringify(p.payload.replay_pack, null, 2);
      }
    };
    okBtn.onclick = async () => {
      const d = await api(`/v1/proposals/${p.proposal_id}/decision`, {
        method: "POST", body: JSON.stringify({ decision: "approve", note: "console" }),
      });
      $("#proposalDetail").classList.remove("hidden");
      $("#proposalDetail").textContent = JSON.stringify(d, null, 2);
      refreshTower();
    };
    noBtn.onclick = async () => {
      await api(`/v1/proposals/${p.proposal_id}/decision`, {
        method: "POST", body: JSON.stringify({ decision: "reject", note: "console" }),
      });
      refreshTower();
    };
    tb.appendChild(tr);
  }
}
$("#refreshProposals").onclick = () => refreshTower().catch((e) => alert(e));
$("#runCurator").onclick = async () => {
  const d = await api("/v1/jobs/curator/run", { method: "POST", body: JSON.stringify({ dry_run: true }) });
  $("#proposalDetail").classList.remove("hidden");
  $("#proposalDetail").textContent = JSON.stringify(d, null, 2);
  refreshTower();
};
$("#runPractice").onclick = async () => {
  const d = await api("/v1/jobs/practice/run", { method: "POST", body: JSON.stringify({ dry_run: true }) });
  $("#proposalDetail").classList.remove("hidden");
  $("#proposalDetail").textContent = JSON.stringify(d, null, 2);
};

$("#refreshMetrics").onclick = async () => {
  try {
    const report = await api("/v1/metrics/report");
    const canary = await api("/v1/metrics/canary");
    const dash = await api("/v1/metrics/dashboard");
    $("#metricsOut").textContent = JSON.stringify({ report, canary, dashboard: dash }, null, 2);
  } catch (e) { $("#metricsOut").textContent = String(e); }
};

$("#devLogin").onclick = async () => {
  const d = await api("/v1/auth/dev-login", {
    method: "POST",
    body: JSON.stringify({
      user_id: "dev-operator",
      roles: ["operator", "reviewer", "admin"],
      tenants: ["default", "tenant-b"],
    }),
  });
  state.session = d.session;
  localStorage.setItem("recertia_session", d.session);
  $("#authOut").textContent = JSON.stringify(d, null, 2);
};
$("#loadMe").onclick = async () => {
  try { $("#authOut").textContent = JSON.stringify(await api("/v1/me"), null, 2); }
  catch (e) { $("#authOut").textContent = String(e); }
};
$("#logout").onclick = async () => {
  await api("/v1/auth/logout", { method: "POST", body: "{}" });
  state.session = "";
  localStorage.removeItem("recertia_session");
  $("#authOut").textContent = "logged out";
};
$("#doSwitch").onclick = async () => {
  const d = await api("/v1/auth/switch-tenant", {
    method: "POST",
    body: JSON.stringify({ tenant_id: $("#switchTenant").value }),
  });
  state.session = d.session;
  localStorage.setItem("recertia_session", d.session);
  $("#tenantHeader").value = d.active_tenant;
  $("#authOut").textContent = JSON.stringify(d, null, 2);
};

loadTemplates();
