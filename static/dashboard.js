"use strict";

/* LLM Gateway 仪表盘：拉取 /api/stats 并用本地 Chart.js 渲染（零构建、零 CDN）。 */

const state = { days: 7, tag: "" };
const charts = {};
const C = {
  blue: "#4da3ff", green: "#3fbf7f", orange: "#e0a13e",
  purple: "#b07ce8", red: "#e05c5c", gray: "#7d8b99",
};

const fmtInt = (n) => Number(n == null ? 0 : n).toLocaleString("zh-CN");
const fmtMs = (v) => (v == null ? "—" : Number(v).toFixed(1) + " ms");
const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString("zh-CN", { hour12: false }) : "—");
const esc = (s) =>
  String(s == null ? "" : s).replace(/[&<>"']/g, (ch) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));

function fmtShort(iso) {
  const d = new Date(iso);
  const p = (x) => String(x).padStart(2, "0");
  if (state.days <= 1) return p(d.getHours()) + ":" + p(d.getMinutes());
  return p(d.getMonth() + 1) + "-" + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes());
}

function axisCfg(right, title) {
  return {
    position: right ? "right" : "left",
    beginAtZero: true,
    grid: { color: "rgba(125,139,153,.12)", drawOnChartArea: !right },
    ticks: { color: "#7d8b99", font: { size: 11 }, maxTicksLimit: 7 },
    title: { display: !!title, text: title || "", color: "#7d8b99", font: { size: 11 } },
  };
}

function chartOptions(yTitle, y1Title) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { labels: { color: "#d8dee6", boxWidth: 12, font: { size: 11 } } },
      tooltip: { backgroundColor: "#1c242d", borderColor: "#242c35", borderWidth: 1 },
    },
    scales: {
      x: { grid: { color: "rgba(125,139,153,.08)" }, ticks: { color: "#7d8b99", font: { size: 11 }, maxTicksLimit: 9 } },
      y: axisCfg(false, yTitle),
      y1: axisCfg(true, y1Title),
    },
  };
}

function line(label, data, color, axis, fill) {
  return {
    type: "line", label: label, data: data, yAxisID: axis || "y",
    borderColor: color, backgroundColor: fill ? color + "22" : color,
    borderWidth: 1.6, tension: 0.25, spanGaps: true, fill: !!fill,
    pointRadius: 2, pointHoverRadius: 4, pointBackgroundColor: color,
  };
}

function upsertChart(id, config) {
  const existing = charts[id];
  if (existing) {
    existing.data.labels = config.data.labels;
    existing.data.datasets = config.data.datasets;
    existing.options = config.options;
    existing.update("none");
    return;
  }
  charts[id] = new Chart(document.getElementById("chart-" + id), config);
}

function renderCards(t) {
  const cards = [
    { label: "请求数", value: fmtInt(t.requests) },
    { label: "Tokens", value: fmtInt(t.tokens) },
    { label: "错误数", value: fmtInt(t.errors) },
    { label: "平均延迟", value: fmtMs(t.avg_latency_ms) },
    { label: "p95 延迟", value: fmtMs(t.p95_latency_ms) },
    { label: "平均 TTFT", value: fmtMs(t.avg_ttft_ms) },
  ];
  document.getElementById("cards").innerHTML = cards
    .map((c) => '<div class="card"><div class="label">' + c.label + '</div><div class="value">' + c.value + "</div></div>")
    .join("");
}

function renderTagOptions(byTag) {
  const select = document.getElementById("tag");
  const names = byTag.map((e) => e.tag).filter((t) => t);
  const options = ['<option value="">全部 tag</option>'].concat(
    names.map((t) => '<option value="' + esc(t) + '">' + esc(t) + "</option>")
  );
  if (state.tag && names.indexOf(state.tag) === -1) {
    options.push('<option value="' + esc(state.tag) + '">' + esc(state.tag) + "</option>");
  }
  select.innerHTML = options.join("");
  select.value = state.tag || "";
}

function renderCharts(data) {
  const trafficLabels = data.timeseries.map((p) => fmtShort(p.ts));
  upsertChart("traffic", {
    type: "bar",
    data: {
      labels: trafficLabels,
      datasets: [
        { type: "bar", label: "请求数", data: data.timeseries.map((p) => p.requests), yAxisID: "y", backgroundColor: "rgba(77,163,255,.55)", borderRadius: 3, maxBarThickness: 46 },
        line("Tokens", data.timeseries.map((p) => p.tokens), C.green, "y1", false),
      ],
    },
    options: chartOptions("请求数", "Tokens"),
  });

  upsertChart("latency", {
    type: "line",
    data: {
      labels: trafficLabels,
      datasets: [
        line("平均延迟 ms", data.timeseries.map((p) => p.avg_latency_ms), C.blue, "y", false),
        line("TTFT ms", data.timeseries.map((p) => p.avg_ttft_ms), C.orange, "y", false),
      ],
    },
    options: chartOptions("毫秒", null),
  });

  upsertChart("gpu", {
    type: "line",
    data: {
      labels: data.gpu.map((p) => fmtShort(p.ts)),
      datasets: [
        line("GPU 利用率 %", data.gpu.map((p) => p.avg_util), C.orange, "y", true),
        line("显存 used (MB)", data.gpu.map((p) => p.avg_mem_used_mb), C.purple, "y1", false),
      ],
    },
    options: chartOptions("利用率 %", "显存 MB"),
  });

  upsertChart("engine", {
    type: "line",
    data: {
      labels: data.engine.map((p) => fmtShort(p.ts)),
      datasets: [
        line("运行中", data.engine.map((p) => p.max_running), C.green, "y", false),
        line("排队中", data.engine.map((p) => p.max_waiting), C.orange, "y", false),
        line("KV cache %", data.engine.map((p) => (p.avg_kv_cache_perc == null ? null : p.avg_kv_cache_perc * 100)), C.blue, "y1", false),
      ],
    },
    options: chartOptions("请求数", "KV cache %"),
  });
}

function renderRecent(rows) {
  const body = document.getElementById("recent-body");
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="8" class="muted">窗口内暂无请求</td></tr>';
    return;
  }
  const known = ["ok", "upstream_error", "client_abort", "timeout"];
  body.innerHTML = rows
    .map((r) => {
      const cls = known.indexOf(r.status) !== -1 ? r.status : "timeout";
      const tagCell = r.tag ? esc(r.tag) : '<span class="muted">—</span>';
      const modelCell = esc(r.resolved_model) + (r.fallback_used ? ' <span class="muted">fallback</span>' : "");
      const tokenCell = fmtInt(r.total_tokens) + ' <span class="muted">(' + fmtInt(r.prompt_tokens) + "+" + fmtInt(r.completion_tokens) + ")</span>";
      return (
        "<tr><td>" + fmtTime(r.ts) + "</td><td>" + tagCell + "</td><td>" + modelCell +
        "</td><td>" + tokenCell + "</td><td>" + fmtMs(r.latency_ms) + "</td><td>" + fmtMs(r.ttft_ms) +
        '</td><td><span class="status ' + cls + '">' + esc(r.status) + "</span></td><td>" + r.attempts + "</td></tr>"
      );
    })
    .join("");
}

/* ---- 模型目录 / Provider 接入（/api/models，含连通性探测） ---- */

function kindBadge(kind) {
  return kind === "local"
    ? '<span class="badge local">本地</span>'
    : '<span class="badge cloud">API</span>';
}

function fallbackCell(entries) {
  if (!entries || !entries.length) return '<span class="muted">—</span>';
  return entries
    .map((e) => (e.tag ? '<span class="muted">@' + esc(e.tag) + "</span> " : "") +
      "→ " + e.chain.map(esc).join(" → "))
    .join("<br>");
}

function renderCatalog(data) {
  const def = data.aliases && data.aliases["default"];
  document.getElementById("catalog-hint").textContent =
    def ? "· 默认 default → " + def : "";

  const models = document.getElementById("models-body");
  const modelRows = (data.models || []).map((m) => {
    const aliases = (m.aliases || []).length
      ? m.aliases.map((a) => '<span class="badge">' + esc(a) + "</span>").join(" ")
      : '<span class="muted">—</span>';
    return "<tr><td>" + esc(m.id) + "</td><td>" + kindBadge(m.kind) + "</td><td>" +
      esc(m.provider) + '</td><td class="muted">' + esc(m.upstream) + "</td><td>" +
      aliases + "</td><td>" + fallbackCell(m.fallbacks) + "</td></tr>";
  });
  models.innerHTML = modelRows.join("") ||
    '<tr><td colspan="6" class="muted">无模型</td></tr>';

  const providers = document.getElementById("providers-body");
  const providerRows = (data.providers || []).map((p) => {
    const key = p.key || {};
    let keyCell;
    if (key.source === "literal") keyCell = '<span class="muted">字面量</span>';
    else if (key.source === "env") {
      keyCell = esc(key.name) + " " +
        (key.configured ? '<span class="status ok">已配置</span>'
                        : '<span class="status upstream_error">未配置</span>');
    } else keyCell = '<span class="status upstream_error">未配置</span>';
    const conn = p.reachable
      ? '<span class="status ok">可达</span> <span class="muted">' + fmtMs(p.latency_ms) + "</span>"
      : '<span class="status upstream_error">不可达</span> <span class="muted cellwrap">' + esc(p.detail) + "</span>";
    const served = (p.models || []).length
      ? p.models.map(esc).join("、")
      : '<span class="muted">—</span>';
    return "<tr><td>" + esc(p.name) + "</td><td>" + kindBadge(p.kind) +
      '</td><td class="muted cellwrap">' + esc(p.base_url) + '</td><td class="cellwrap">' + keyCell +
      "</td><td>" + conn + "</td><td>" + served + "</td></tr>";
  });
  providers.innerHTML = providerRows.join("") ||
    '<tr><td colspan="6" class="muted">无 provider</td></tr>';
}

async function loadCatalog() {
  const resp = await fetch("/api/models");
  if (!resp.ok) throw new Error("HTTP " + resp.status);
  renderCatalog(await resp.json());
}

function showError(err) {
  document.getElementById("updated").textContent = "加载失败：" + err.message;
}

async function load() {
  const params = new URLSearchParams({ days: String(state.days) });
  if (state.tag) params.set("tag", state.tag);
  const resp = await fetch("/api/stats?" + params.toString());
  if (!resp.ok) throw new Error("HTTP " + resp.status);
  const data = await resp.json();
  renderCards(data.totals);
  renderTagOptions(data.by_tag);
  renderCharts(data);
  renderRecent(data.recent);
  const bucket = data.bucket_seconds >= 3600 ? "1 小时" : "5 分钟";
  document.getElementById("updated").textContent =
    "更新于 " + new Date().toLocaleTimeString("zh-CN", { hour12: false }) + " · 桶粒度 " + bucket;
}

// 支持 ?days=N&tag=xx 初始化（便于书签/分享/自动化截图）
const urlParams = new URLSearchParams(location.search);
if (urlParams.get("days")) {
  const d = Number(urlParams.get("days"));
  if (Number.isFinite(d) && d >= 1 && d <= 90) state.days = Math.floor(d);
}
if (urlParams.get("tag")) state.tag = urlParams.get("tag");
document.getElementById("days").value = String(state.days);
document.getElementById("tag").value = state.tag;

document.getElementById("days").addEventListener("change", (event) => {
  state.days = Number(event.target.value);
  load().catch(showError);
});
document.getElementById("tag").addEventListener("change", (event) => {
  state.tag = event.target.value;
  load().catch(showError);
});
document.getElementById("refresh").addEventListener("click", () => {
  load().catch(showError);
  loadCatalog().catch(showError);
});

load().catch(showError);
// 目录含 provider 连通性探测：仅页面加载/手动刷新时拉取，不随 30s 轮询
loadCatalog().catch(showError);
setInterval(() => load().catch(() => {}), 30000);