const state = {
  hours: 24,
  history: [],
  summary: null,
  heartbeat: {
    hours: 6,
    bucket: "5m",
    target: document.getElementById("heartbeatTargetSelect")?.value || "223.5.5.5",
    dashboard: null,
  },
};

const internetSummary = document.getElementById("internetSummary");
const internetChart = document.getElementById("internetChart");
const statusText = document.getElementById("statusText");
const statsGrid = document.getElementById("statsGrid");
const historyTableBody = document.getElementById("historyTableBody");
const latestProfile = document.getElementById("latestProfile");
const failureList = document.getElementById("failureList");
const serverBadge = document.getElementById("serverBadge");
const runNowBtn = document.getElementById("runNowBtn");
const cleanupBtn = document.getElementById("cleanupBtn");
const strategyPanel = document.getElementById("strategyPanel");
const anomalyHoursPanel = document.getElementById("anomalyHoursPanel");
const streakPanel = document.getElementById("streakPanel");
const overviewGrid = document.getElementById("overviewGrid");
const alertStrip = document.getElementById("alertStrip");
const heartbeatLattice = document.getElementById("heartbeatLattice");
const heartbeatStats = document.getElementById("heartbeatStats");
const heartbeatSparkline = document.getElementById("heartbeatSparkline");
const heartbeatEvents = document.getElementById("heartbeatEvents");
const heartbeatTargetSelect = document.getElementById("heartbeatTargetSelect");

function fmt(value, suffix = "", digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "--";
  }
  return `${Number(value).toFixed(digits)}${suffix}`;
}

function pct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "--";
  }
  return `${Number(value).toFixed(2)}%`;
}

function formatTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value || "--";
  }
  return `${date.toLocaleDateString()} ${date.toLocaleTimeString()}`;
}

function chipsHtml(anomalies = []) {
  if (!anomalies.length) {
    return `<span class="chip chip-ok">正常</span>`;
  }
  const labels = {
    download_low: "下载偏低",
    upload_low: "上传偏低",
    latency_high: "延迟偏高",
    duration_high: "耗时过长",
  };
  return anomalies.map((item) => `<span class="chip chip-alert">${labels[item] || item}</span>`).join("");
}

function overviewCard(title, value, meta, tone = "") {
  return `
    <article class="overview-card ${tone}">
      <p class="overview-title">${title}</p>
      <p class="overview-value">${value}</p>
      <p class="overview-meta">${meta}</p>
    </article>
  `;
}

function statCard(title, value, meta) {
  return `
    <article class="stat-card">
      <p class="stat-title">${title}</p>
      <p class="stat-value">${value}</p>
      <p class="stat-meta">${meta}</p>
    </article>
  `;
}

function buildSeries(rows, key) {
  return rows
    .filter((row) => row.success && row[key] !== null && row[key] !== undefined)
    .map((row) => ({
      x: new Date(row.measured_at).getTime(),
      y: Number(row[key]),
    }));
}

function renderOverview() {
  const overview = state.summary?.overview;
  const summary = state.summary;
  if (!overview || !summary) {
    overviewGrid.innerHTML = "";
    return;
  }
  overviewGrid.innerHTML = [
    overviewCard("当前下载", fmt(overview.current_download_mbps, " Mbps"), "本次样本", overview.current_download_mbps < summary.thresholds.download_alert_mbps ? "danger" : "good"),
    overviewCard("当前延迟", fmt(overview.current_latency_ms, " ms"), "越低越稳", overview.current_latency_ms > summary.thresholds.latency_alert_ms ? "danger" : "good"),
    overviewCard("测速成功率", pct(summary.success_rate), `${summary.success_count}/${summary.total_count} 次`, summary.success_rate < 95 ? "danger" : "good"),
    overviewCard("峰值下载", fmt(summary.max_download_mbps, " Mbps"), `均值 ${fmt(summary.avg_download_mbps, " Mbps")}`),
  ].join("");
}

function renderAlertStrip() {
  const summary = state.summary;
  const heartbeat = state.heartbeat.dashboard;
  if (!summary || !heartbeat) {
    alertStrip.innerHTML = "";
    return;
  }
  const latest = summary.latest_success;
  const stats = heartbeat.stats;
  const parts = [
    `目标：${heartbeat.target}`,
    `心跳成功率：${pct(stats.uptime_ratio)}`,
    `心跳 p95：${fmt(stats.p95_latency_ms, " ms")}`,
    `心跳 p99：${fmt(stats.p99_latency_ms, " ms")}`,
    `测速节点：${latest?.server_name || latest?.server_sponsor || "--"}`,
  ];
  alertStrip.innerHTML = `<div class="alert-banner">${parts.join(" · ")}</div>`;
}

function renderSummary() {
  const latest = state.summary?.latest_success;
  const newest = state.history[state.history.length - 1];
  const previous = [...state.history].filter((row) => row.success).slice(-2)[0];
  if (!newest) {
    internetSummary.innerHTML = `<p class="empty-state">还没有外网测速数据。</p>`;
    return;
  }

  const downloadDelta = latest && previous?.download_mbps !== null && previous?.download_mbps !== undefined
    ? latest.download_mbps - previous.download_mbps
    : null;
  const latencyDelta = latest && previous?.latency_ms !== null && previous?.latency_ms !== undefined
    ? latest.latency_ms - previous.latency_ms
    : null;
  const deltaText = (value, suffix) => {
    if (value === null || Number.isNaN(Number(value))) {
      return "--";
    }
    const sign = value > 0 ? "+" : "";
    return `${sign}${Number(value).toFixed(2)}${suffix}`;
  };

  internetSummary.innerHTML = `
    <div class="metric-line compact-line"><span>状态</span><div><div class="metric-value">${newest.success ? "成功" : "失败"}</div><div class="card-meta">${newest.success ? chipsHtml(latest?.anomalies || []) : (newest.error_message || "最近一次测速失败")}</div></div></div>
    <div class="metric-line compact-line"><span>节点</span><div><div class="metric-value metric-small">${latest?.server_sponsor || latest?.server_name || "--"}</div><div class="card-meta">${latest?.server_location || "--"}</div></div></div>
    <div class="metric-line compact-line"><span>相对上次</span><div><div class="metric-value metric-small">下行 ${deltaText(downloadDelta, " Mbps")}</div><div class="card-meta">延迟 ${deltaText(latencyDelta, " ms")}</div></div></div>
    <div class="metric-line compact-line"><span>注释</span><div><div class="metric-value metric-small">${fmt((latest?.test_duration_ms || 0) / 1000, " s")}</div><div class="card-meta">${latest?.isp_name || "--"} / ${formatTime(latest?.measured_at)}</div></div></div>
  `;
}

function renderStats() {
  const summary = state.summary;
  const heartbeat = state.heartbeat.dashboard;
  if (!summary || !heartbeat) {
    statsGrid.innerHTML = "";
    return;
  }
  statsGrid.innerHTML = [
    statCard("心跳 p95", fmt(heartbeat.stats.p95_latency_ms, " ms"), `目标 ${heartbeat.target}`),
    statCard("心跳 p99", fmt(heartbeat.stats.p99_latency_ms, " ms"), `样本 ${heartbeat.stats.samples}`),
    statCard("异常事件", `${heartbeat.events.length} 条`, `${heartbeat.bucket} / ${heartbeat.hours}h`),
    statCard("平均测速耗时", fmt((summary.avg_test_duration_ms || 0) / 1000, " s"), `阈值 ${summary.thresholds.test_duration_alert_seconds} s`),
  ].join("");
}

function renderStrategy() {
  const strategy = state.summary?.server_strategy;
  const thresholds = state.summary?.thresholds;
  if (!strategy || !thresholds) {
    strategyPanel.innerHTML = `<p class="empty-state">暂无策略信息。</p>`;
    return;
  }
  strategyPanel.innerHTML = `
    <div class="strategy-item"><span class="profile-label">固定节点池</span><span class="profile-value">${(strategy.preferred_pool || []).join(", ") || "未配置"}</span></div>
    <div class="strategy-item"><span class="profile-label">自动兜底</span><span class="profile-value">${strategy.fallback_to_auto ? "开启" : "关闭"}</span></div>
    <div class="strategy-item"><span class="profile-label">异常阈值</span><span class="profile-value">下载 < ${thresholds.download_alert_mbps} / 上传 < ${thresholds.upload_alert_mbps} / 延迟 > ${thresholds.latency_alert_ms}</span></div>
  `;
}

function drawInternetChart() {
  const download = buildSeries(state.history, "download_mbps");
  const upload = buildSeries(state.history, "upload_mbps");
  const latency = buildSeries(state.history, "latency_ms");
  const allPoints = [...download, ...upload, ...latency];

  if (!allPoints.length) {
    internetChart.innerHTML = `<p class="empty-state">当前时间范围内没有可绘制的数据。</p>`;
    return;
  }

  const width = 940;
  const height = 300;
  const pad = { top: 18, right: 18, bottom: 42, left: 44 };
  const minX = Math.min(...allPoints.map((point) => point.x));
  const maxX = Math.max(...allPoints.map((point) => point.x));
  const maxY = Math.max(...allPoints.map((point) => point.y), 1);

  const toX = (x) => (minX === maxX ? width / 2 : pad.left + ((x - minX) / (maxX - minX)) * (width - pad.left - pad.right));
  const toY = (y) => height - pad.bottom - (y / maxY) * (height - pad.top - pad.bottom);
  const polyline = (points) => points.map((point) => `${toX(point.x).toFixed(2)},${toY(point.y).toFixed(2)}`).join(" ");
  const pointDots = (points, cls) => points.map((point) => `<circle class="series-dot ${cls}" cx="${toX(point.x).toFixed(2)}" cy="${toY(point.y).toFixed(2)}" r="3.3"></circle>`).join("");
  const spikeLines = (points, cls) => points.map((point) => `<line class="series-spike ${cls}" x1="${toX(point.x).toFixed(2)}" y1="${height - pad.bottom}" x2="${toX(point.x).toFixed(2)}" y2="${toY(point.y).toFixed(2)}"></line>`).join("");

  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
    const value = (maxY * (1 - ratio)).toFixed(0);
    const y = pad.top + ratio * (height - pad.top - pad.bottom);
    return `<line class="grid-line" x1="${pad.left}" y1="${y}" x2="${width - pad.right}" y2="${y}"></line><text class="axis-label" x="6" y="${y + 4}">${value}</text>`;
  });
  const xLabels = [0, 0.5, 1].map((ratio) => {
    const x = pad.left + ratio * (width - pad.left - pad.right);
    const time = new Date(minX + (maxX - minX) * ratio);
    return `<text class="axis-label" x="${x - 34}" y="${height - 12}">${time.toLocaleDateString()}</text>`;
  });
  const latestPoint = download[download.length - 1];
  const thresholdY = state.summary?.thresholds?.download_alert_mbps ? toY(state.summary.thresholds.download_alert_mbps) : null;

  internetChart.innerHTML = `
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-label="internet chart">
      ${yTicks.join("")}
      ${xLabels.join("")}
      ${thresholdY !== null ? `<line class="threshold-line" x1="${pad.left}" y1="${thresholdY}" x2="${width - pad.right}" y2="${thresholdY}"></line><text class="threshold-label" x="${width - pad.right - 120}" y="${thresholdY - 8}">下载异常阈值</text>` : ""}
      ${spikeLines(download, "spike-download")}
      <polyline class="series-line series-download" points="${polyline(download)}"></polyline>
      <polyline class="series-line series-upload" points="${polyline(upload)}"></polyline>
      <polyline class="series-line series-latency" points="${polyline(latency)}"></polyline>
      ${pointDots(download, "dot-download")}
      ${pointDots(upload, "dot-upload")}
      ${pointDots(latency, "dot-latency")}
      ${latestPoint ? `<text class="annotation-label latest-label" x="${toX(latestPoint.x) - 24}" y="${toY(latestPoint.y) - 14}">最新 ${latestPoint.y.toFixed(1)}</text>` : ""}
    </svg>
    <div class="legend">
      <span class="legend-item"><span class="legend-swatch legend-download"></span>下载曲线，带采样点和毛刺</span>
      <span class="legend-item"><span class="legend-swatch legend-upload"></span>上传曲线</span>
      <span class="legend-item"><span class="legend-swatch legend-latency"></span>延迟曲线</span>
    </div>
  `;
  const latestServer = state.summary?.latest_server;
  serverBadge.textContent = latestServer ? `${latestServer.server_sponsor || "--"} / ${latestServer.server_name || "--"} / ${latestServer.external_ip || "--"}` : "暂无最近测速信息";
}

function renderLatestProfile() {
  const latest = state.summary?.latest_success;
  if (!latest) {
    latestProfile.innerHTML = `<p class="empty-state">还没有成功测速画像。</p>`;
    return;
  }
  const items = [
    ["测速节点", `${latest.server_sponsor || "--"} / ${latest.server_name || "--"}`],
    ["位置", `${latest.server_location || "--"} / ${latest.server_country || "--"}`],
    ["运营商", latest.isp_name || "--"],
    ["外网 IP", latest.external_ip || "--"],
    ["结果链接", latest.result_url ? `<a href="${latest.result_url}" target="_blank" rel="noreferrer">打开</a>` : "--"],
  ];
  latestProfile.innerHTML = items.map(([label, value]) => `<div class="profile-item"><span class="profile-label">${label}</span><span class="profile-value">${value}</span></div>`).join("");
}

function renderFailures() {
  const failures = state.summary?.recent_failures || [];
  failureList.innerHTML = failures.length
    ? failures.map((item) => `<div class="failure-item"><p class="failure-time">${formatTime(item.measured_at)}</p><p class="failure-msg">${item.error_message || "未知错误"}</p></div>`).join("")
    : `<p class="empty-state">当前时间范围内没有失败记录。</p>`;
}

function renderAnomalyHours() {
  const rows = state.summary?.anomaly_hours || [];
  anomalyHoursPanel.innerHTML = rows.length
    ? rows.map((row) => `<div class="failure-item"><p class="failure-time">${row.hour}:00 - ${row.hour}:59</p><p class="failure-msg">异常率 ${pct(row.rate)}，异常 ${row.anomalies}/${row.samples}</p></div>`).join("")
    : `<p class="empty-state">当前时间范围内还没有明显异常时段。</p>`;
}

function renderStreak() {
  const streak = state.summary?.current_anomaly_streak;
  const heartbeat = state.heartbeat.dashboard;
  const outage = heartbeat?.events.find((event) => event.type === "outage");
  if ((streak && streak.count) || outage) {
    streakPanel.innerHTML = `
      <div class="failure-item">
        <p class="failure-time">测速连续异常 ${streak?.count || 0} 次</p>
        <p class="failure-msg">${streak?.count ? `开始于 ${formatTime(streak.start)}，最近一次 ${formatTime(streak.end)}` : "当前没有测速连续异常"}</p>
      </div>
      <div class="failure-item">
        <p class="failure-time">最近断流事件</p>
        <p class="failure-msg">${outage ? `${formatTime(outage.start)} 到 ${formatTime(outage.end)} / ${outage.label}` : "当前没有连续失败事件"}</p>
      </div>
    `;
    return;
  }
  streakPanel.innerHTML = `<p class="empty-state">当前没有连续异常告警。</p>`;
}

function renderHistoryTable() {
  const rows = [...state.history].sort((a, b) => new Date(b.measured_at) - new Date(a.measured_at)).slice(0, 12);
  historyTableBody.innerHTML = rows.length
    ? rows.map((row) => `<tr><td>${formatTime(row.measured_at)}</td><td class="${row.success ? "ok" : "bad"}">${chipsHtml(row.anomalies || [])}</td><td class="${row.anomalies?.includes("download_low") ? "cell-alert" : ""}">${fmt(row.download_mbps)}</td><td class="${row.anomalies?.includes("upload_low") ? "cell-alert" : ""}">${fmt(row.upload_mbps)}</td><td class="${row.anomalies?.includes("latency_high") ? "cell-alert" : ""}">${fmt(row.latency_ms)}</td><td>${row.server_name || row.server_sponsor || row.target || "--"}</td></tr>`).join("")
    : `<tr><td colspan="6" class="empty-state">暂无记录</td></tr>`;
}

function heartbeatCellTone(point) {
  if (!point) {
    return "empty";
  }
  if ((point.failure_count || 0) > 0) {
    return "down";
  }
  if (Number(point.p95_latency_ms || point.avg_latency_ms || 0) >= 30) {
    return "warn";
  }
  return "up";
}

function renderHeartbeatLattice() {
  const series = state.heartbeat.dashboard?.series || [];
  if (!series.length) {
    heartbeatLattice.innerHTML = `<p class="empty-state">还没有连通性聚合数据。</p>`;
    return;
  }
  heartbeatLattice.innerHTML = series.map((point) => `
    <button
      class="heartbeat-cell ${heartbeatCellTone(point)}"
      type="button"
      title="${formatTime(point.bucket_start)} | 在线率 ${pct(point.uptime_ratio)} | p95 ${fmt(point.p95_latency_ms, " ms")}"
      aria-label="${formatTime(point.bucket_start)}">
    </button>
  `).join("");
}

function drawHeartbeatChart() {
  const dashboard = state.heartbeat.dashboard;
  const series = dashboard?.series || [];
  if (!series.length) {
    heartbeatSparkline.innerHTML = `<p class="empty-state">暂时没有可用的延迟聚合曲线。</p>`;
    return;
  }

  const points = series
    .filter((row) => row.avg_latency_ms !== null && row.avg_latency_ms !== undefined)
    .map((row) => ({
      x: new Date(row.bucket_start).getTime(),
      y: Number(row.avg_latency_ms),
      p95: row.p95_latency_ms !== null ? Number(row.p95_latency_ms) : null,
      p99: row.p99_latency_ms !== null ? Number(row.p99_latency_ms) : null,
    }));

  if (!points.length) {
    heartbeatSparkline.innerHTML = `<p class="empty-state">当前时间范围没有有效延迟样本。</p>`;
    return;
  }

  const width = 620;
  const height = 210;
  const pad = { top: 18, right: 18, bottom: 28, left: 38 };
  const maxY = Math.max(
    ...points.flatMap((point) => [point.y, point.p95 || 0, point.p99 || 0]),
    1,
  );
  const minX = Math.min(...points.map((point) => point.x));
  const maxX = Math.max(...points.map((point) => point.x));
  const toX = (x) => (minX === maxX ? width / 2 : pad.left + ((x - minX) / (maxX - minX)) * (width - pad.left - pad.right));
  const toY = (y) => height - pad.bottom - (y / maxY) * (height - pad.top - pad.bottom);
  const line = (values, cls) => `
    <polyline class="${cls}" points="${values.map((point) => `${toX(point.x).toFixed(2)},${toY(point.y).toFixed(2)}`).join(" ")}"></polyline>
  `;

  const avgLine = line(points, "series-line series-latency");
  const p95Line = line(points.filter((point) => point.p95 !== null).map((point) => ({ x: point.x, y: point.p95 })), "series-line p-line p95-line");
  const p99Line = line(points.filter((point) => point.p99 !== null).map((point) => ({ x: point.x, y: point.p99 })), "series-line p-line p99-line");
  const dots = points.map((point) => `<circle class="series-dot dot-latency" cx="${toX(point.x).toFixed(2)}" cy="${toY(point.y).toFixed(2)}" r="2.6"></circle>`).join("");
  const eventLines = (dashboard.events || []).slice(-8).map((event) => {
    const x = toX(new Date(event.start).getTime()).toFixed(2);
    return `<line class="event-line ${event.type}" x1="${x}" y1="${pad.top}" x2="${x}" y2="${height - pad.bottom}"></line><text class="event-label" x="${Number(x) + 4}" y="${pad.top + 12}">${event.type === "outage" ? "断流" : "毛刺"}</text>`;
  }).join("");
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
    const value = (maxY * (1 - ratio)).toFixed(0);
    const y = pad.top + ratio * (height - pad.top - pad.bottom);
    return `<line class="grid-line" x1="${pad.left}" y1="${y}" x2="${width - pad.right}" y2="${y}"></line><text class="axis-label" x="4" y="${y + 4}">${value}</text>`;
  });
  const xTicks = [0, 0.5, 1].map((ratio) => {
    const x = pad.left + ratio * (width - pad.left - pad.right);
    const time = new Date(minX + (maxX - minX) * ratio);
    return `<text class="axis-label" x="${x - 22}" y="${height - 8}">${time.toLocaleDateString()} ${time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</text>`;
  });

  heartbeatSparkline.innerHTML = `
    <div class="sparkline-header">
      <span>${dashboard.target} / ${dashboard.bucket} / 最近 ${dashboard.hours} 小时</span>
      <span>avg ${fmt(dashboard.stats.avg_latency_ms, " ms")} · p95 ${fmt(dashboard.stats.p95_latency_ms, " ms")} · p99 ${fmt(dashboard.stats.p99_latency_ms, " ms")}</span>
    </div>
    <svg class="sparkline-svg large" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
      ${yTicks.join("")}
      ${xTicks.join("")}
      ${eventLines}
      ${p99Line}
      ${p95Line}
      ${avgLine}
      ${dots}
    </svg>
    <div class="legend compact-legend">
      <span class="legend-item"><span class="legend-swatch legend-latency"></span>平均延迟</span>
      <span class="legend-item"><span class="legend-swatch legend-p95"></span>p95</span>
      <span class="legend-item"><span class="legend-swatch legend-p99"></span>p99</span>
      <span class="legend-item"><span class="legend-swatch legend-event"></span>事件标注</span>
    </div>
  `;
}

function renderHeartbeatStats() {
  const dashboard = state.heartbeat.dashboard;
  if (!dashboard) {
    heartbeatStats.innerHTML = "";
    return;
  }
  const stats = dashboard.stats;
  const items = [
    ["当前目标", dashboard.target, "good"],
    ["在线率", pct(stats.uptime_ratio), stats.uptime_ratio < 99 ? "warn" : "good"],
    ["p95", fmt(stats.p95_latency_ms, " ms"), "good"],
    ["p99", fmt(stats.p99_latency_ms, " ms"), stats.p99_latency_ms > 50 ? "warn" : "good"],
  ];
  heartbeatStats.innerHTML = items.map(([label, value, tone]) => `
    <article class="heartbeat-stat ${tone}">
      <p class="overview-title">${label}</p>
      <p class="heartbeat-value">${value}</p>
    </article>
  `).join("");
}

function renderHeartbeatEvents() {
  const events = state.heartbeat.dashboard?.events || [];
  heartbeatEvents.innerHTML = events.length
    ? events.slice(-6).reverse().map((event) => `<div class="failure-item"><p class="failure-time">${formatTime(event.start)}</p><p class="failure-msg">${event.label} · ${event.target}</p></div>`).join("")
    : `<p class="empty-state">当前时间范围内没有显著心跳事件。</p>`;
}

async function loadData() {
  const params = new URLSearchParams({
    hours: String(state.heartbeat.hours),
    bucket: state.heartbeat.bucket,
    target: state.heartbeat.target,
  });
  const [historyResponse, summaryResponse, heartbeatDashboardResponse] = await Promise.all([
    fetch(`/api/history?kind=internet&hours=${state.hours}`),
    fetch(`/api/internet/summary?hours=${state.hours}`),
    fetch(`/api/heartbeat/dashboard?${params.toString()}`),
  ]);
  if (!historyResponse.ok || !summaryResponse.ok || !heartbeatDashboardResponse.ok) {
    throw new Error("数据读取失败");
  }
  state.history = await historyResponse.json();
  state.summary = await summaryResponse.json();
  state.heartbeat.dashboard = await heartbeatDashboardResponse.json();
}

async function refresh() {
  statusText.textContent = "正在同步监控数据...";
  await loadData();
  renderHeartbeatLattice();
  renderHeartbeatStats();
  drawHeartbeatChart();
  renderHeartbeatEvents();
  renderOverview();
  renderAlertStrip();
  renderSummary();
  renderStats();
  renderStrategy();
  drawInternetChart();
  renderLatestProfile();
  renderFailures();
  renderAnomalyHours();
  renderStreak();
  renderHistoryTable();
  statusText.textContent = `心跳 ${state.heartbeat.target} · ${state.heartbeat.bucket} · 最近 ${state.heartbeat.hours} 小时`;
}

document.querySelectorAll(".range-btn[data-hours]").forEach((button) => {
  button.addEventListener("click", async () => {
    document.querySelectorAll(".range-btn[data-hours]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    state.hours = Number(button.dataset.hours);
    try {
      await refresh();
    } catch (error) {
      statusText.textContent = error.message;
    }
  });
});

document.querySelectorAll(".range-btn[data-heartbeat-hours]").forEach((button) => {
  button.addEventListener("click", async () => {
    document.querySelectorAll(".range-btn[data-heartbeat-hours]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    state.heartbeat.hours = Number(button.dataset.heartbeatHours);
    if (state.heartbeat.hours >= 168 && state.heartbeat.bucket === "1m") {
      state.heartbeat.bucket = "1h";
      document.querySelectorAll(".range-btn[data-heartbeat-bucket]").forEach((item) => {
        item.classList.toggle("active", item.dataset.heartbeatBucket === "1h");
      });
    }
    try {
      await refresh();
    } catch (error) {
      statusText.textContent = error.message;
    }
  });
});

document.querySelectorAll(".range-btn[data-heartbeat-bucket]").forEach((button) => {
  button.addEventListener("click", async () => {
    document.querySelectorAll(".range-btn[data-heartbeat-bucket]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    state.heartbeat.bucket = button.dataset.heartbeatBucket;
    try {
      await refresh();
    } catch (error) {
      statusText.textContent = error.message;
    }
  });
});

heartbeatTargetSelect?.addEventListener("change", async () => {
  state.heartbeat.target = heartbeatTargetSelect.value;
  try {
    await refresh();
  } catch (error) {
    statusText.textContent = error.message;
  }
});

runNowBtn.addEventListener("click", async () => {
  runNowBtn.disabled = true;
  runNowBtn.textContent = "测速中...";
  try {
    const response = await fetch("/api/run", { method: "POST" });
    if (!response.ok) {
      throw new Error("手动测速触发失败");
    }
    statusText.textContent = "已触发正式测速，稍后自动刷新";
    setTimeout(refresh, 6000);
  } catch (error) {
    statusText.textContent = error.message;
  } finally {
    setTimeout(() => {
      runNowBtn.disabled = false;
      runNowBtn.textContent = "立即测速";
    }, 5000);
  }
});

cleanupBtn.addEventListener("click", async () => {
  cleanupBtn.disabled = true;
  cleanupBtn.textContent = "清理中...";
  try {
    const response = await fetch("/api/admin/cleanup-legacy", { method: "POST" });
    const data = await response.json();
    statusText.textContent = `已清理 ${data.deleted || 0} 条旧样本`;
    await refresh();
  } catch (error) {
    statusText.textContent = "旧样本清理失败";
  } finally {
    cleanupBtn.disabled = false;
    cleanupBtn.textContent = "清理旧样本";
  }
});

refresh().catch((error) => {
  statusText.textContent = error.message;
});
