"use strict";
const $ = (id) => document.getElementById(id);
const labels = {queued:"准备",running:"运行中",completed:"完成",paused:"暂停"};
const toolLabels = {search_experiences:"检索经历",get_experience:"读取完整经历",get_evidence_stats:"检查证据覆盖"};
const toolIcons = {search_experiences:"search",get_experience:"file",get_evidence_stats:"link"};
let mode = "demo", records = [], runId = null, currentRun = null, config = null;
let busy = false, pollTimer = null, requestVersion = 0;
let historyRuns = [], historyOpen = false, currentRecordId = null;
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const icon = (name, className = "icon") => `<svg class="${className}" aria-hidden="true"><use href="#icon-${name}"></use></svg>`;
async function api(path, data, method) {
  const verb = method || (data === undefined ? "GET" : "POST");
  const response = await fetch(path, {method:verb,headers:{"X-ExperienceOS":"workbench",...(data === undefined ? {} : {"Content-Type":"application/json"})},body:data === undefined ? undefined : JSON.stringify(data)});
  if (verb === "DELETE") return null;
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "请求未完成，请重试。");
  return result;
}
function showError(error) { $("error").textContent = error.message || String(error); $("error").hidden = false; }
function clearError() { $("error").hidden = true; }
function setBusy(value) {
  busy = value;
  $("start").disabled = value || !config || (mode === "live" && (!config.live_ready || !records.length));
  $("mode-demo").disabled = value; $("mode-live").disabled = value;
  $("simulate-failure").disabled = value; $("history-toggle").disabled = value;
  $("question").readOnly = value || mode === "demo";
  $("start").innerHTML = value ? `${icon("terminal")}运行中` : `运行${icon("play")}`;
}
async function loadRecords() {
  records = await api(`/api/experiences?mode=${mode}`);
  $("record-count").textContent = records.length;
  $("records").innerHTML = records.length ? records.map(r => `<button class="record-row" data-record="${esc(r.id)}">${icon("file","record-icon")}<span class="record-title">${esc(r.title)}</span><span class="evidence-count ${r.evidence.length ? "" : "missing"}" aria-label="${r.evidence.length ? `${r.evidence.length} 条引用` : "缺少证据"}">${icon(r.evidence.length ? "link" : "alert")}${r.evidence.length || ""}</span></button>`).join("") : `<div class="empty-library">${icon("file")}暂无经历</div>`;
  setBusy(busy);
}
function evidenceHTML(e) {
  let location = esc(e.location);
  try { const url = new URL(e.location); if (["http:","https:"].includes(url.protocol)) location = `<a href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">${location} ↗</a>`; } catch (_) { /* Local paths remain text. */ }
  return `<div class="evidence-item">${icon("link")}<span>${esc(e.description || "证据")}</span><small>${location}</small></div>`;
}
function showRecord(id) {
  const r = records.find(item => item.id === id);
  if (!r) { showError(new Error("引用的经历已不在当前经历库中。")); return; }
  currentRecordId = id;
  const list = (title, glyph, values) => values.length ? `<section class="detail-section"><h3>${icon(glyph)}${title}</h3><ul>${values.map(v=>`<li>${esc(v)}</li>`).join("")}</ul></section>` : "";
  const statusLabel = {active:"正式",draft:"草稿",archived:"归档"}[r.status?.value || r.status] || "";
  $("record-detail").innerHTML = `<h2 id="detail-title">${esc(r.title)}</h2><p class="detail-meta">${statusLabel ? `<span class="status-pill">${statusLabel}</span> · ` : ""}${esc(r.role || "未记录角色")} · ${esc(r.period.start || "时间未知")}${r.period.start ? " — " + esc(r.period.end || "至今") : ""}</p><p>${esc(r.description)}</p>${list("贡献","check",r.contribution)}${list("成果","arrow",r.result)}<section class="detail-section"><h3>${icon("link")}证据</h3>${r.evidence.length ? r.evidence.map(evidenceHTML).join("") : `<p class="missing">${icon("alert")}未关联证据</p>`}</section><p class="source-line">${esc(r.source.origin)} · ${esc(r.source.created_by)}${mode === "demo" ? " · 示例" : ""}</p>`;
  $("detail-actions").hidden = mode !== "live";
  document.querySelectorAll(".record-row").forEach(button => button.setAttribute("aria-current", String(button.dataset.record === id)));
  $("record-dialog").showModal();
}
async function changeMode(next, preserveRun = false) {
  mode = next;
  $("mode-demo").setAttribute("aria-pressed", String(mode === "demo"));
  $("mode-live").setAttribute("aria-pressed", String(mode === "live"));
  $("failure-option").hidden = mode !== "demo"; $("model-label").hidden = mode !== "live";
  $("library-tools").hidden = mode !== "live";
  $("question").value = mode === "demo" ? config.demo_question : "哪些项目最能体现我的后端能力？请列出成果、引用来源和证据缺口。";
  $("mode-note").textContent = mode === "demo" ? "示例数据" : config.live_ready ? config.model : `缺少 ${config.api_key_env}`;
  $("model-label").textContent = config.model;
  if (!preserveRun) {
    clearTimeout(pollTimer); requestVersion++; runId = null; currentRun = null;
    $("result").innerHTML = `<div class="empty-result">${icon("search","empty-icon")}<p>输入问题，开始分析</p></div>`;
    $("activity").hidden = true;
    $("result-status").textContent = "就绪"; $("events").innerHTML = `<li class="pending-event">${icon("terminal")}等待</li>`;
    $("run-status").textContent = "未运行"; $("run-status").dataset.status = "";
    $("metrics").hidden = true; $("recovery").hidden = true; $("run-id").textContent = ""; setHistorySelection(null);
  }
  await loadRecords(); clearError();
}
function renderRun(run) {
  const previousRun = currentRun;
  $("activity").hidden = false;
  if ((run.active && previousRun?.id !== run.id) || (run.status === "paused" && previousRun?.status !== "paused")) $("activity").open = true;
  currentRun = run;
  setHistorySelection(runId);
  $("run-status").textContent = labels[run.status]; $("run-status").dataset.status = run.status;
  $("result-status").textContent = `${run.mode === "demo" ? "离线演示" : "真实模型"} · ${labels[run.status]}`;
  $("run-id").textContent = run.workflow_id || run.id;
  $("events").innerHTML = `<li class="done">${icon("check")}已开始</li>` + run.events.map(event => {
    const r = records.find(r => r.id === event.arguments.id_or_prefix);
    return `<li class="done">${icon(toolIcons[event.name] || "terminal")}${esc(toolLabels[event.name] || event.name)}${r ? `<small>${esc(r.title)}</small>` : ""}</li>`;
  }).join("") + (run.status === "completed" ? `<li class="done">${icon("check")}校验通过</li>` : `<li class="pending-event">${icon(run.status === "paused" ? "alert" : "terminal")}${run.status === "paused" ? "已暂停" : "处理中"}</li>`);
  $("recovery").hidden = run.status !== "paused";
  $("recovery-message").textContent = run.error || "本次运行暂停，可从保存的进度继续。";
  $("resume").hidden = !run.can_resume; $("resume").disabled = run.active;
  if (run.output) {
    const out = run.output;
    const list = values => `<ul>${values.map(v => `<li>${esc(v)}</li>`).join("")}</ul>`;
    const section = (glyph,title,content,className="") => content ? `<section class="brief-section ${className}"><h3>${icon(glyph)}${title}</h3>${content}</section>` : "";
    const citations = out.citations.map(c=>`<button class="citation" data-record="${esc(c.experience_id)}"><span>${esc(c.claim)}</span><small>${icon("link")}${c.evidence_locations.length}</small></button>`).join("");
    $("result").innerHTML = `<div class="brief-intro"><p>${esc(out.answer)}</p></div>${section("check","亮点",out.highlights.length ? list(out.highlights) : "")}${section("link",`来源 ${out.citations.length}`,citations)}${section("alert","缺口",out.evidence_gaps.length ? list(out.evidence_gaps) : "","gap-section")}${section("arrow","建议",list(out.next_actions))}`;
  } else {
    $("result").innerHTML = `<div class="empty-result">${icon(run.status === "paused" ? "alert" : "terminal","empty-icon")}<p>${run.status === "paused" ? "已暂停" : "分析中"}</p></div>`;
  }
  const report = run.report;
  $("metrics").hidden = !report;
  if (report) {
    const metric = (v,label) => `<div class="metric"><strong>${esc(v)}</strong><span>${label}</span></div>`;
    $("metrics").innerHTML = metric(report.latency_ms == null ? "—" : (report.latency_ms / 1000).toFixed(1) + "s","耗时") + metric(report.tool_call_count,"工具") + metric(report.citation_count,"引用") + metric(report.total_tokens ?? "—","Tokens");
  }
  setBusy(run.active);
}
const timeAgo = (iso) => {
  const time = new Date(iso).getTime();
  if (Number.isNaN(time)) return "";
  const seconds = Math.max(0, (Date.now() - time) / 1000);
  if (seconds < 60) return "刚刚";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  if (seconds < 172800) return "昨天";
  return new Date(iso).toLocaleDateString("zh-CN");
};
const runMeta = (r) => `${r.mode === "demo" ? "演示" : "在线"} · ${labels[r.status] || r.status} · ${timeAgo(r.created_at)}`;
function setHistorySelection(id) {
  const selected = historyRuns.find(r => r.id === id);
  const label = $("history-toggle-label");
  label.textContent = selected ? selected.question : "选择运行记录";
  label.classList.toggle("placeholder", !selected);
  document.querySelectorAll(".history-item").forEach(item => item.setAttribute("aria-selected", String(item.dataset.run === id)));
}
function renderHistory(runs) {
  historyRuns = runs;
  $("history-count").textContent = runs.length;
  $("history-list").innerHTML = runs.length ? runs.map(r => `<button type="button" class="history-item" role="option" data-run="${esc(r.id)}" aria-selected="false"><span class="run-dot" data-status="${esc(r.status)}"></span><span class="run-info"><span class="run-question">${esc(r.question)}</span><span class="run-meta">${esc(runMeta(r))}</span></span></button>`).join("") : `<div class="history-empty">还没有运行记录</div>`;
  setHistorySelection(runId);
}
function positionHistoryList() {
  const list = $("history-list"), rect = $("history-toggle").getBoundingClientRect();
  const width = Math.max(rect.width, 250);
  list.style.left = `${Math.max(10, Math.min(rect.left, window.innerWidth - width - 10))}px`;
  list.style.minWidth = `${rect.width}px`;
  list.style.maxWidth = `${width}px`;
  list.style.top = ""; list.style.bottom = "";
  const above = rect.top - 10, below = window.innerHeight - rect.bottom - 10;
  list.style.maxHeight = `${Math.max(200, Math.min(340, Math.max(above, below)))}px`;
  if (above >= below) list.style.bottom = `${window.innerHeight - rect.top + 6}px`;
  else list.style.top = `${rect.bottom + 6}px`;
}
function openHistory(open) {
  if (open === historyOpen) return;
  historyOpen = open;
  $("history-list").hidden = !open;
  $("history-toggle").setAttribute("aria-expanded", String(open));
  if (open) {
    positionHistoryList();
    (document.querySelector('.history-item[aria-selected="true"]') || document.querySelector(".history-item"))?.focus();
  }
}
async function loadHistory() {
  const runs = await api("/api/runs");
  renderHistory(runs);
  return runs;
}
async function poll(version) {
  if (version !== requestVersion || !runId) return;
  try {
    const run = await api(`/api/runs/${runId}`);
    if (version !== requestVersion) return;
    clearError();
    renderRun(run);
    if (run.active) pollTimer = setTimeout(()=>poll(version),650);
    else await loadHistory();
  } catch (error) {
    if (version !== requestVersion) return;
    showError(error);
    pollTimer = setTimeout(()=>poll(version),2000);
  }
}
async function startRun() {
  clearError(); setBusy(true);
  try {
    const result = await api("/api/runs",{mode,question:$("question").value,simulate_failure:mode === "demo" && $("simulate-failure").checked});
    runId = result.id; await poll(++requestVersion);
  } catch (error) { showError(error); setBusy(false); }
}
$("task-form").addEventListener("submit",event=>{event.preventDefault();startRun();});
async function selectMode(next) {
  setBusy(true);
  try { await changeMode(next); } catch(error) { showError(error); }
  finally { setBusy(false); }
}
$("mode-demo").addEventListener("click",()=>selectMode("demo"));
$("mode-live").addEventListener("click",()=>selectMode("live"));
document.addEventListener("click",event=>{const button=event.target.closest("[data-record]");if(button)showRecord(button.dataset.record);});
$("close-detail").addEventListener("click",()=>$("record-dialog").close());
$("resume").addEventListener("click",async()=>{
  clearError(); setBusy(true); $("resume").disabled = true;
  try { await api(`/api/runs/${runId}/resume`,{}); await poll(++requestVersion); }
  catch(error) {showError(error);setBusy(false);$("resume").disabled=false;}
});
$("history-toggle").addEventListener("click", () => openHistory(!historyOpen));
$("history-toggle").addEventListener("keydown", event => {
  if (event.key !== "ArrowDown") return;
  event.preventDefault();
  if (historyOpen) document.querySelector('.history-item[aria-selected="true"]')?.focus();
  else openHistory(true);
});
$("history-list").addEventListener("click", async event => {
  const item = event.target.closest("[data-run]");
  if (!item) return;
  openHistory(false);
  if (item.dataset.run === runId) return;
  try {
    clearTimeout(pollTimer);
    const version = ++requestVersion;
    runId = item.dataset.run;
    setHistorySelection(runId);
    const run = await api(`/api/runs/${runId}`);
    await changeMode(run.mode, true);
    $("question").value = run.question;
    await poll(version);
  } catch (error) { showError(error); }
});
$("history-list").addEventListener("keydown", event => {
  if (!["ArrowDown", "ArrowUp"].includes(event.key)) return;
  const items = [...document.querySelectorAll(".history-item")];
  if (!items.length) return;
  event.preventDefault();
  const index = items.indexOf(document.activeElement);
  const next = index === -1 ? 0 : event.key === "ArrowDown" ? Math.min(items.length - 1, index + 1) : Math.max(0, index - 1);
  items[next].focus();
});
document.addEventListener("click", event => { if (historyOpen && !event.target.closest(".history-select")) openHistory(false); });
document.addEventListener("keydown", event => { if (event.key === "Escape" && historyOpen) { openHistory(false); $("history-toggle").focus(); } });
window.addEventListener("resize", () => { if (historyOpen) openHistory(false); });
window.addEventListener("scroll", event => { if (historyOpen && !event.target.closest?.(".history-list")) openHistory(false); }, true);
// ---- record management: create / edit / delete / export (live mode only) ----
const evidenceKindOptions = ["repo","commit","pull_request","issue","url","doc","file","image","other"];
function evidenceRow(ev = {}) {
  const row = document.createElement("div");
  row.className = "evidence-row";
  row.innerHTML = `<select class="ev-kind">${evidenceKindOptions.map(k=>`<option value="${k}"${k===(ev.kind||"repo")?" selected":""}>${k}</option>`).join("")}</select><input class="ev-location" placeholder="github.com/you/project 或链接" value="${esc(ev.location||"")}" maxlength="2000"><input class="ev-desc" placeholder="说明（可选）" value="${esc(ev.description||"")}" maxlength="2000"><button type="button" class="icon-button ev-remove" aria-label="移除该证据">✕</button>`;
  row.querySelector(".ev-remove").addEventListener("click",()=>row.remove());
  return row;
}
function openForm(record) {
  clearError();
  const editing = Boolean(record);
  $("form-title").textContent = editing ? "编辑经历" : "新增经历";
  $("f-title").value = record?.title || "";
  $("f-type").value = record?.type?.value || record?.type || "personal";
  $("f-status").value = record?.status?.value || record?.status || "active";
  $("f-start").value = record?.period?.start || "";
  $("f-end").value = record?.period?.end || "";
  $("f-role").value = record?.role || "";
  $("f-context").value = record?.context || "";
  $("f-description").value = record?.description || "";
  $("f-technology").value = (record?.technology || []).join(", ");
  $("f-tags").value = (record?.tags || []).join(", ");
  const lines = field => (record?.[field] || []).join("\n");
  $("f-contribution").value = lines("contribution");
  $("f-challenge").value = lines("challenge");
  $("f-solution").value = lines("solution");
  $("f-result").value = lines("result");
  $("f-reflection").value = record?.reflection || "";
  $("evidence-rows").innerHTML = "";
  (record?.evidence && record.evidence.length ? record.evidence : [{}]).forEach(ev => $("evidence-rows").appendChild(evidenceRow(ev)));
  $("form-dialog").dataset.recordId = editing ? record.id : "";
  $("record-dialog").close();
  $("form-dialog").showModal();
}
function collectForm() {
  const perLine = id => $("" + id).value.split("\n").map(s=>s.trim()).filter(Boolean);
  const csv = id => $("" + id).value.split(/[,，]/).map(s=>s.trim()).filter(Boolean);
  const evidence = [...document.querySelectorAll("#evidence-rows .evidence-row")].map(row => ({
    kind: row.querySelector(".ev-kind").value,
    location: row.querySelector(".ev-location").value.trim(),
    description: row.querySelector(".ev-desc").value.trim(),
  })).filter(ev => ev.location);
  return {
    title: $("f-title").value.trim(),
    type: $("f-type").value,
    status: $("f-status").value,
    period: {start: $("f-start").value || null, end: $("f-end").value || null},
    role: $("f-role").value.trim(),
    context: $("f-context").value.trim(),
    description: $("f-description").value.trim(),
    technology: csv("f-technology"),
    tags: csv("f-tags"),
    contribution: perLine("f-contribution"),
    challenge: perLine("f-challenge"),
    solution: perLine("f-solution"),
    result: perLine("f-result"),
    reflection: $("f-reflection").value.trim(),
    evidence,
  };
}
async function saveForm(event) {
  event.preventDefault();
  clearError();
  const payload = collectForm();
  if (!payload.title) { showError(new Error("标题必填。")); return; }
  const id = $("form-dialog").dataset.recordId;
  $("save-record").disabled = true;
  try {
    if (id) await api(`/api/experiences/${encodeURIComponent(id)}?mode=live`, payload, "PUT");
    else await api("/api/experiences?mode=live", payload);
    $("form-dialog").close();
    await loadRecords();
    if (id) showRecord(id);
  } catch (error) { showError(error); }
  finally { $("save-record").disabled = false; }
}
async function exportAs(name) {
  clearError();
  try {
    const response = await fetch(`/api/export?name=${name}&mode=live`, {headers:{"X-ExperienceOS":"workbench"}});
    if (!response.ok) { const err = await response.json().catch(()=>({})); throw new Error(err.error || "导出失败。"); }
    const blob = await response.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `experienceos-export-${name === "markdown" ? "markdown.md" : "html.html"}`;
    link.click();
    URL.revokeObjectURL(link.href);
  } catch (error) { showError(error); }
}
$("new-record").addEventListener("click",()=>openForm(null));
$("add-evidence").addEventListener("click",()=>$("evidence-rows").appendChild(evidenceRow()));
$("record-form").addEventListener("submit",saveForm);
$("cancel-form").addEventListener("click",()=>$("form-dialog").close());
$("close-form").addEventListener("click",()=>$("form-dialog").close());
$("edit-record").addEventListener("click",()=>{
  const r = records.find(item => item.id === currentRecordId);
  if (r) openForm(r);
});
$("delete-record").addEventListener("click",async()=>{
  if (!currentRecordId) return;
  if (!confirm("删除后不可恢复，确定删除这条经历？")) return;
  clearError();
  try {
    await api(`/api/experiences/${encodeURIComponent(currentRecordId)}?mode=live`, undefined, "DELETE");
    $("record-dialog").close();
    currentRecordId = null;
    await loadRecords();
  } catch (error) { showError(error); }
});
$("export-md").addEventListener("click",()=>exportAs("markdown"));
$("export-html").addEventListener("click",()=>exportAs("html"));

async function initialize() {
  setBusy(true);
  config = await api("/api/config"); await changeMode("demo");
  const runs = await loadHistory();
  const latest = runs.find(r=>r.active) || runs[0];
  if (latest) {runId=latest.id;const run=await api(`/api/runs/${runId}`);await changeMode(run.mode,true);$("question").value=run.question;await poll(++requestVersion);}
  else setBusy(false);
}
initialize().catch(error=>{showError(error);setBusy(false);});

// Optional page-scoped tool. Unsupported browsers use the same visible UI.
const modelContext = document.modelContext;
if (modelContext?.registerTool) {
  const lifecycle = new AbortController();
  try {
    Promise.resolve(modelContext.registerTool({
      name: "get_experience_run_status",
      description: "Read the currently displayed ExperienceOS analysis status without starting a run.",
      inputSchema: {type:"object", properties:{}, additionalProperties:false},
      annotations: {readOnlyHint:true, untrustedContentHint:true},
      execute(input) {
        if (!input || typeof input !== "object" || Array.isArray(input) || Object.keys(input).length) {
          throw new Error("Expected an empty object.");
        }
        return currentRun ? {id:currentRun.id,mode:currentRun.mode,status:currentRun.status,
          toolCalls:currentRun.events.length,canResume:currentRun.can_resume} : {status:"idle"};
      }
    }, {signal:lifecycle.signal})).catch(()=>{});
  } catch (_) { /* Registration is optional. */ }
  window.addEventListener("pagehide",()=>lifecycle.abort(),{once:true});
}
