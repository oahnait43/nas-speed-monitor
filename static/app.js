const state = {
  hours: 24,
  history: [],
  summary: null,
  focusTimeMs: null,
  heartbeatTargets: [],
  heartbeat: {
    hours: 6,
    bucket: "5m",
    target: document.getElementById("heartbeatTargetSelect")?.value || "223.5.5.5",
    dashboard: null,
  },
};

const statusText = document.getElementById("statusText");
const historyTableBody = document.getElementById("historyTableBody");
const heartbeatTargetTableBody = document.getElementById("heartbeatTargetTableBody");
const heartbeatEventTableBody = document.getElementById("heartbeatEventTableBody");
const serverBadge = document.getElementById("serverBadge");
const runNowBtn = document.getElementById("runNowBtn");
const cleanupBtn = document.getElementById("cleanupBtn");
const heartbeatLattice = document.getElementById("heartbeatLattice");
const heartbeatSparkline = document.getElementById("heartbeatSparkline");
const heartbeatTargetSelect = document.getElementById("heartbeatTargetSelect");
const targetCompareChart = document.getElementById("targetCompareChart");
const internetChart = document.getElementById("internetChart");
const chartTooltip = document.getElementById("chartTooltip");

function speedtestScheduleSummary() {
  return "正式测速固定时刻 01:30 / 07:30 / 13:30 / 19:30";
}

function isMobileViewport() {
  return window.innerWidth <= 760;
}

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

function showTooltip(event, html) {
  if (!chartTooltip) {
    return;
  }
  chartTooltip.innerHTML = html;
  chartTooltip.hidden = false;
  const offset = 14;
  chartTooltip.style.left = `${event.clientX + offset}px`;
  chartTooltip.style.top = `${event.clientY + offset}px`;
}

function hideTooltip() {
  if (!chartTooltip) {
    return;
  }
  chartTooltip.hidden = true;
}

function nearestPoint(points, targetMs) {
  if (!points.length || targetMs === null || targetMs === undefined) {
    return null;
  }
  return points.reduce((best, point) => {
    if (!best) {
      return point;
    }
    return Math.abs(point.x - targetMs) < Math.abs(best.x - targetMs) ? point : best;
  }, null);
}

function setFocusedTime(timeMs, { scrollToSpeed = false } = {}) {
  state.focusTimeMs = timeMs;
  if (state.heartbeat.dashboard) {
    renderHeartbeatLattice();
    drawHeartbeatChart();
  }
  if (state.summary) {
    drawInternetChart();
  }
  if (scrollToSpeed) {
    internetChart?.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

function bindTooltipPoints(container, selector = "[data-tooltip]") {
  if (!container) {
    return;
  }
  container.querySelectorAll(selector).forEach((node) => {
    node.addEventListener("mouseenter", (event) => {
      showTooltip(event, node.dataset.tooltip || "");
    });
    node.addEventListener("mousemove", (event) => {
      showTooltip(event, node.dataset.tooltip || "");
    });
    node.addEventListener("mouseleave", hideTooltip);
  });
}

function buildSeries(rows, key) {
  return rows
    .filter((row) => row.success && row[key] !== null && row[key] !== undefined)
    .map((row) => ({
      x: new Date(row.measured_at).getTime(),
      y: Number(row[key]),
      row,
    }));
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
    heartbeatLattice.innerHTML = `<p class="empty-state">暂无连通性数据</p>`;
    return;
  }
  const groups = [];
  let currentDay = null;
  let currentItems = [];
  series.forEach((point) => {
    const day = point.bucket_start.slice(0, 10);
    if (day !== currentDay) {
      if (currentDay) {
        groups.push({ day: currentDay, items: currentItems });
      }
      currentDay = day;
      currentItems = [];
    }
    currentItems.push(point);
  });
  if (currentDay) {
    groups.push({ day: currentDay, items: currentItems });
  }
  heartbeatLattice.innerHTML = groups.map((group) => `
    <section class="lattice-day">
      <div class="lattice-day-label">${group.day}</div>
      <div class="lattice-day-grid">
        ${group.items.map((point) => {
          const pointMs = new Date(point.bucket_start).getTime();
          const selected = state.focusTimeMs !== null && Math.abs(pointMs - state.focusTimeMs) <= point.bucket_minutes * 60 * 1000;
          return `
            <button
              class="heartbeat-cell ${heartbeatCellTone(point)} ${selected ? "selected" : ""}"
              type="button"
              data-tooltip="${formatTime(point.bucket_start)}<br>在线率 ${pct(point.uptime_ratio)}<br>平均 ${fmt(point.avg_latency_ms, " ms")}<br>p95 ${fmt(point.p95_latency_ms, " ms")}"
              title="${formatTime(point.bucket_start)} | 在线率 ${pct(point.uptime_ratio)} | p95 ${fmt(point.p95_latency_ms, " ms")}"
              data-focus-time="${pointMs}"
              aria-label="${formatTime(point.bucket_start)}"></button>
          `;
        }).join("")}
      </div>
    </section>
  `).join("");
  heartbeatLattice.querySelectorAll("[data-focus-time]").forEach((node) => {
    node.addEventListener("click", () => {
      setFocusedTime(Number(node.dataset.focusTime), { scrollToSpeed: true });
    });
  });
  bindTooltipPoints(heartbeatLattice);
}

function drawTargetCompareChart() {
  const rows = [...state.heartbeatTargets];
  if (!rows.length) {
    targetCompareChart.innerHTML = `<p class="empty-state">暂无目标对比数据</p>`;
    return;
  }
  rows.sort((a, b) => {
    const groupScore = a.group.localeCompare(b.group);
    if (groupScore !== 0) {
      return groupScore;
    }
    return (a.avg_latency_ms ?? Number.MAX_SAFE_INTEGER) - (b.avg_latency_ms ?? Number.MAX_SAFE_INTEGER);
  });
  const width = 700;
  const rowHeight = 82;
  const pad = { top: 88, right: 184, bottom: 24, left: 180 };
  const maxLatency = Math.max(...rows.flatMap((row) => [Number(row.avg_latency_ms || 0), Number(row.p95_latency_ms || 0), Number(row.p99_latency_ms || 0)]), 120);
  const height = pad.top + rows.length * rowHeight + pad.bottom;
  const scaleX = (value) => pad.left + (Number(value || 0) / maxLatency) * (width - pad.left - pad.right);
  const primary = rows.find((row) => row.target === state.heartbeat.target) || rows.find((row) => row.delta_vs_primary_ms === 0) || rows[0];
  const domestic = rows.filter((row) => row.group === "domestic");
  const international = rows.filter((row) => row.group === "international");
  const degradedRows = rows.filter((row) => row.health === "degraded");
  const groupState = (items) => {
    if (!items.length) {
      return "unknown";
    }
    const totalFailures = items.reduce((sum, row) => sum + (row.failure_count || 0), 0);
    const avgSuccess = items.reduce((sum, row) => sum + Number(row.success_rate || 0), 0) / items.length;
    if (avgSuccess < 95 || totalFailures > 0) {
      return "degraded";
    }
    if (items.some((row) => row.health === "slow")) {
      return "slow";
    }
    return "healthy";
  };
  const domesticState = groupState(domestic);
  const internationalState = groupState(international);
  let diagnosis = "多目标状态接近，当前更像整体稳定。";
  if (domesticState === "healthy" && internationalState !== "healthy") {
    diagnosis = "国内目标稳定，异常更像国际出口或国际目标侧问题。";
  } else if (domesticState !== "healthy" && internationalState === "healthy") {
    diagnosis = "国际目标稳定，异常更像本地到国内出口链路问题。";
  } else if (domesticState !== "healthy" && internationalState !== "healthy") {
    diagnosis = "国内和国际目标同时偏弱，更像整体外网波动或出口拥塞。";
  } else if (degradedRows.length === 1) {
    diagnosis = `${degradedRows[0].target} 单点异常更明显，其余目标可作为对照基线。`;
  }

  const thresholdBands = [
    { limit: Math.min(20, maxLatency), cls: "diag-band-good" },
    { limit: Math.min(60, maxLatency), cls: "diag-band-warn" },
    { limit: maxLatency, cls: "diag-band-bad" },
  ].map((band, index, list) => {
    const previous = index === 0 ? 0 : list[index - 1].limit;
    const x = scaleX(previous);
    const widthValue = scaleX(band.limit) - x;
    return `<rect class="diagnostic-band ${band.cls}" x="${x}" y="${pad.top - 18}" width="${Math.max(widthValue, 0)}" height="${height - pad.top - pad.bottom + 24}"></rect>`;
  }).join("");

  const axisTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
    const value = maxLatency * ratio;
    const x = pad.left + ratio * (width - pad.left - pad.right);
    return `
      <line class="grid-line" x1="${x}" y1="${pad.top - 18}" x2="${x}" y2="${height - pad.bottom}"></line>
      <text class="axis-label" x="${x - 10}" y="${pad.top - 28}">${value.toFixed(0)} ms</text>
    `;
  }).join("");

  const rowsSvg = rows.map((row, index) => {
    const y = pad.top + index * rowHeight;
    const laneY = y - 8;
    const avgX = scaleX(row.avg_latency_ms);
    const p95X = scaleX(row.p95_latency_ms);
    const p99X = scaleX(row.p99_latency_ms);
    const groupLabel = row.group === "domestic" ? "国内" : "国际";
    const deltaText = row.delta_vs_primary_ms === null ? "--" : `${row.delta_vs_primary_ms > 0 ? "+" : ""}${row.delta_vs_primary_ms.toFixed(1)} ms`;
    const healthClass = row.health === "healthy" ? "healthy" : (row.health === "slow" ? "slow" : "degraded");
    const latestClass = row.latest_success ? "healthy" : "degraded";
    const failureLabel = row.failure_count ? `${row.failure_count} 失败` : "0 失败";
    return `
      <rect class="diagnostic-lane" x="${pad.left}" y="${laneY}" width="${width - pad.left - pad.right}" height="42" rx="12"></rect>
      <text class="axis-label target-label" x="10" y="${y + 6}">${row.target}</text>
      <text class="small-tag" x="10" y="${y + 24}">${groupLabel} · ${row.label || row.provider || row.target}</text>
      <text class="small-tag" x="10" y="${y + 40}">${row.role || "--"} · ${row.samples} 样本</text>
      <text class="small-tag ${healthClass}" x="10" y="${y + 56}">${row.health === "healthy" ? "稳定" : row.health === "slow" ? "偏慢" : "异常"} · ${failureLabel}</text>
      <line class="target-range" x1="${avgX}" y1="${y + 8}" x2="${p95X}" y2="${y + 8}"></line>
      <circle class="diagnostic-dot ${healthClass}" data-tooltip="${row.target}<br>${row.label || "--"} / ${row.provider || "--"}<br>${row.role || "--"}<br>平均 ${fmt(row.avg_latency_ms, " ms")}<br>p95 ${fmt(row.p95_latency_ms, " ms")}<br>p99 ${fmt(row.p99_latency_ms, " ms")}<br>成功率 ${pct(row.success_rate)}<br>失败 ${row.failure_count}<br>相对主目标 ${deltaText}" cx="${avgX}" cy="${y + 8}" r="6"></circle>
      <circle class="diagnostic-ring" cx="${p95X}" cy="${y + 8}" r="6"></circle>
      <circle class="diagnostic-p99" cx="${p99X}" cy="${y + 8}" r="4"></circle>
      <circle class="latest-health ${latestClass}" cx="${width - pad.right + 14}" cy="${y + 2}" r="5"></circle>
      <text class="annotation-label" x="${width - pad.right + 28}" y="${y + 6}">成功率 ${pct(row.success_rate)}</text>
      <text class="annotation-label" x="${width - pad.right + 28}" y="${y + 24}">avg ${fmt(row.avg_latency_ms, " ms")} / p95 ${fmt(row.p95_latency_ms, " ms")}</text>
      <text class="annotation-label" x="${width - pad.right + 28}" y="${y + 42}">p99 ${fmt(row.p99_latency_ms, " ms")} / 相对主目标 ${deltaText}</text>
    `;
  }).join("");

  targetCompareChart.innerHTML = `
    <svg class="chart-svg diagnostic-svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet">
      <text class="annotation-label top-note" x="${pad.left}" y="16">基线目标 ${primary?.target || "--"}；实心点表示平均延迟，横线表示到 p95，紫点表示 p99。</text>
      <text class="annotation-label top-note" x="${pad.left}" y="34">右侧展示成功率、延迟分位和相对基线偏移，可结合国内/国际分组判断异常范围。</text>
      <text class="diagnosis-banner" x="${pad.left}" y="58">${diagnosis}</text>
      ${thresholdBands}
      ${axisTicks}
      ${rowsSvg}
    </svg>
  `;
  bindTooltipPoints(targetCompareChart);
}

function drawHeartbeatChart() {
  const dashboard = state.heartbeat.dashboard;
  const series = dashboard?.series || [];
  if (!series.length) {
    heartbeatSparkline.innerHTML = `<p class="empty-state">暂无心跳聚合数据</p>`;
    return;
  }
  const points = series
    .filter((item) => item.avg_latency_ms !== null && item.avg_latency_ms !== undefined)
    .map((item) => ({
      x: new Date(item.bucket_start).getTime(),
      y: Number(item.avg_latency_ms),
      p95: item.p95_latency_ms !== null ? Number(item.p95_latency_ms) : null,
      p99: item.p99_latency_ms !== null ? Number(item.p99_latency_ms) : null,
      bucketStart: item.bucket_start,
    }));
  if (!points.length) {
    heartbeatSparkline.innerHTML = `<p class="empty-state">当前范围没有有效延迟样本</p>`;
    return;
  }
  const mobile = isMobileViewport();
  const width = mobile ? 420 : 1220;
  const height = mobile ? 250 : 310;
  const pad = mobile
    ? { top: 24, right: 12, bottom: 28, left: 36 }
    : { top: 28, right: 20, bottom: 34, left: 50 };
  const yValues = points.flatMap((point) => [point.y, point.p95, point.p99]).filter((value) => value !== null && value !== undefined);
  const rawMinY = Math.min(...yValues);
  const rawMaxY = Math.max(...yValues);
  const span = Math.max(rawMaxY - rawMinY, 0.8);
  const padding = Math.max(span * 0.24, 0.45);
  const minY = Math.max(0, rawMinY - padding);
  const maxY = rawMaxY + padding;
  const minX = Math.min(...points.map((point) => point.x));
  const maxX = Math.max(...points.map((point) => point.x));
  const toX = (x) => (minX === maxX ? width / 2 : pad.left + ((x - minX) / (maxX - minX)) * (width - pad.left - pad.right));
  const toY = (y) => {
    if (maxY === minY) {
      return (pad.top + height - pad.bottom) / 2;
    }
    return height - pad.bottom - ((y - minY) / (maxY - minY)) * (height - pad.top - pad.bottom);
  };
  const line = (pts, cls) => `<polyline class="${cls}" points="${pts.map((point) => `${toX(point.x).toFixed(2)},${toY(point.y).toFixed(2)}`).join(" ")}"></polyline>`;
  const avgLine = line(points, "series-line series-latency");
  const p95Line = line(points.filter((point) => point.p95 !== null).map((point) => ({ x: point.x, y: point.p95 })), "series-line p-line p95-line");
  const p99Line = line(points.filter((point) => point.p99 !== null).map((point) => ({ x: point.x, y: point.p99 })), "series-line p-line p99-line");
  const dots = points.map((point) => `<circle class="series-dot dot-latency" data-tooltip="${dashboard.target}<br>${formatTime(point.bucketStart)}<br>平均 ${fmt(point.y, " ms")}<br>p95 ${fmt(point.p95, " ms")}<br>p99 ${fmt(point.p99, " ms")}" cx="${toX(point.x).toFixed(2)}" cy="${toY(point.y).toFixed(2)}" r="2.4"></circle>`).join("");
  const events = (dashboard.events || []).slice(-10).map((event, index) => {
    const x = toX(new Date(event.start).getTime()).toFixed(2);
    const labelY = pad.top + 14 + (index % 3) * 14;
    return `<line class="event-line ${event.type}" x1="${x}" y1="${pad.top}" x2="${x}" y2="${height - pad.bottom}"></line><text class="event-label" x="${Number(x) + 4}" y="${labelY}">${event.type === "outage" ? "断流" : "毛刺"}</text>`;
  }).join("");
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
    const value = maxY - (maxY - minY) * ratio;
    const y = pad.top + ratio * (height - pad.top - pad.bottom);
    return `<line class="grid-line" x1="${pad.left}" y1="${y}" x2="${width - pad.right}" y2="${y}"></line><text class="axis-label" x="4" y="${y + 4}">${value.toFixed(1)}</text>`;
  });
  const xTickRatios = mobile ? [0, 1] : [0, 0.5, 1];
  const xTicks = xTickRatios.map((ratio) => {
    const x = pad.left + ratio * (width - pad.left - pad.right);
    const time = new Date(minX + (maxX - minX) * ratio);
    const label = mobile
      ? time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      : `${time.toLocaleDateString()} ${time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
    return `<text class="axis-label" x="${mobile ? x - 18 : x - 30}" y="${height - 8}">${label}</text>`;
  });
  const latestPoint = points[points.length - 1];
  const focused = state.focusTimeMs !== null ? nearestPoint(points, state.focusTimeMs) : null;
  const topNote = mobile
    ? `${dashboard.target} · ${dashboard.bucket} · p95 ${fmt(dashboard.stats.p95_latency_ms, " ms")} · p99 ${fmt(dashboard.stats.p99_latency_ms, " ms")}`
    : `${dashboard.target} · ${dashboard.bucket} · uptime ${pct(dashboard.stats.uptime_ratio)} · p95 ${fmt(dashboard.stats.p95_latency_ms, " ms")} · p99 ${fmt(dashboard.stats.p99_latency_ms, " ms")}`;

  heartbeatSparkline.innerHTML = `
    <svg class="chart-svg heartbeat-svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet">
      ${yTicks.join("")}
      ${xTicks.join("")}
      ${events}
      ${p99Line}
      ${p95Line}
      ${avgLine}
      ${dots}
      ${focused ? `<line class="focus-line" x1="${toX(focused.x)}" y1="${pad.top}" x2="${toX(focused.x)}" y2="${height - pad.bottom}"></line>` : ""}
      ${focused ? `<text class="focus-label" x="${toX(focused.x) + 6}" y="${height - pad.bottom - 10}">${formatTime(focused.bucketStart)}</text>` : ""}
      <text class="annotation-label latest-label" x="${toX(latestPoint.x) - 22}" y="${toY(latestPoint.y) - 12}">最新 ${latestPoint.y.toFixed(1)} ms</text>
      <text class="annotation-label top-note" x="${pad.left}" y="${pad.top - 6}">${topNote}</text>
    </svg>
    <div class="legend compact-legend">
      <span class="legend-item"><span class="legend-swatch legend-latency"></span>平均延迟</span>
      <span class="legend-item"><span class="legend-swatch legend-p95"></span>p95</span>
      <span class="legend-item"><span class="legend-swatch legend-p99"></span>p99</span>
      <span class="legend-item"><span class="legend-swatch legend-event"></span>事件线</span>
    </div>
  `;
  bindTooltipPoints(heartbeatSparkline);
}

function drawInternetChart() {
  const summary = state.summary;
  const rows = state.history;
  const download = buildSeries(rows, "download_mbps");
  const upload = buildSeries(rows, "upload_mbps");
  const latency = buildSeries(rows, "latency_ms");
  const allPoints = [...download, ...upload, ...latency];
  if (!allPoints.length) {
    internetChart.innerHTML = `<p class="empty-state">暂无测速数据</p>`;
    return;
  }
  const mobile = isMobileViewport();
  const width = mobile ? 420 : 1220;
  const panelHeight = mobile ? 96 : 150;
  const height = panelHeight * 3 + (mobile ? 52 : 70);
  const pad = mobile
    ? { top: 20, right: 12, bottom: 18, left: 36 }
    : { top: 22, right: 20, bottom: 18, left: 44 };
  const minX = Math.min(...allPoints.map((point) => point.x));
  const maxX = Math.max(...allPoints.map((point) => point.x));
  const toX = (x) => (minX === maxX ? width / 2 : pad.left + ((x - minX) / (maxX - minX)) * (width - pad.left - pad.right));
  const buildPanel = (points, colorClass, label, unit, metricKey, thresholdValue, panelIndex) => {
    if (!points.length) {
      return "";
    }
    const panelTop = panelIndex * panelHeight + (mobile ? 24 : 20);
    const panelBottom = panelTop + panelHeight - (mobile ? 18 : 28);
    const maxY = Math.max(...points.map((point) => point.y), thresholdValue || 0, 1);
    const toY = (y) => panelBottom - (y / maxY) * (panelBottom - panelTop);
    const polyline = points.map((point) => `${toX(point.x).toFixed(2)},${toY(point.y).toFixed(2)}`).join(" ");
    const dots = points.map((point) => {
      const row = point.row || {};
      return `<circle class="series-dot ${colorClass}" data-tooltip="${formatTime(row.measured_at)}<br>下载 ${fmt(row.download_mbps, " Mbps")}<br>上传 ${fmt(row.upload_mbps, " Mbps")}<br>延迟 ${fmt(row.latency_ms, " ms")}<br>节点 ${row.server_sponsor || row.server_name || "--"}" cx="${toX(point.x).toFixed(2)}" cy="${toY(point.y).toFixed(2)}" r="3"></circle>`;
    }).join("");
    const yTicks = [0, 0.5, 1].map((ratio) => {
      const value = (maxY * (1 - ratio)).toFixed(0);
      const y = panelTop + ratio * (panelBottom - panelTop);
      return `<line class="grid-line" x1="${pad.left}" y1="${y}" x2="${width - pad.right}" y2="${y}"></line><text class="axis-label" x="4" y="${y + 4}">${value}</text>`;
    }).join("");
    const threshold = thresholdValue ? `<line class="threshold-line" x1="${pad.left}" y1="${toY(thresholdValue)}" x2="${width - pad.right}" y2="${toY(thresholdValue)}"></line>` : "";
    const latestPoint = points[points.length - 1];
    return `
      <text class="panel-label" x="${pad.left}" y="${panelTop - 8}">${label}</text>
      ${yTicks}
      ${threshold}
      <polyline class="series-line ${metricKey}" points="${polyline}"></polyline>
      ${dots}
      <text class="annotation-label latest-label" x="${toX(latestPoint.x) - 24}" y="${toY(latestPoint.y) - 10}">最新 ${latestPoint.y.toFixed(1)}${unit}</text>
    `;
  };
  const xTickRatios = mobile ? [0, 1] : [0, 0.5, 1];
  const xTicks = xTickRatios.map((ratio) => {
    const x = pad.left + ratio * (width - pad.left - pad.right);
    const time = new Date(minX + (maxX - minX) * ratio);
    const label = mobile
      ? `${time.getMonth() + 1}/${time.getDate()}`
      : time.toLocaleDateString();
    return `<text class="axis-label" x="${mobile ? x - 12 : x - 30}" y="${height - 8}">${label}</text>`;
  }).join("");
  const latest = summary?.latest_success;
  const failureMarkers = rows.filter((row) => !row.success).slice(-6).map((row) => {
    const x = toX(new Date(row.measured_at).getTime()).toFixed(2);
    return `<line class="event-line outage" x1="${x}" y1="18" x2="${x}" y2="${height - 28}"></line>`;
  }).join("");
  const focusSource = download.length ? download : (upload.length ? upload : latency);
  const focused = state.focusTimeMs !== null ? nearestPoint(focusSource, state.focusTimeMs) : null;
  const hoverBands = focusSource.map((point, index) => {
    const prevX = index === 0 ? toX(point.x) : (toX(focusSource[index - 1].x) + toX(point.x)) / 2;
    const nextX = index === focusSource.length - 1 ? toX(point.x) : (toX(point.x) + toX(focusSource[index + 1].x)) / 2;
    const widthBand = Math.max(nextX - prevX, 10);
    return `<rect class="hover-band" data-focus-time="${point.x}" data-tooltip="${formatTime(point.row.measured_at)}<br>下载 ${fmt(point.row.download_mbps, " Mbps")}<br>上传 ${fmt(point.row.upload_mbps, " Mbps")}<br>延迟 ${fmt(point.row.latency_ms, " ms")}<br>节点 ${point.row.server_sponsor || point.row.server_name || "--"}" x="${prevX}" y="18" width="${widthBand}" height="${height - 40}" fill="transparent"></rect>`;
  }).join("");
  const topNote = mobile
    ? `下载 ${fmt(latest?.download_mbps, " Mbps")} · 上传 ${fmt(latest?.upload_mbps, " Mbps")} · 延迟 ${fmt(latest?.latency_ms, " ms")}`
    : `成功率 ${pct(summary?.success_rate)} · 当前下载 ${fmt(latest?.download_mbps, " Mbps")} · 当前上传 ${fmt(latest?.upload_mbps, " Mbps")} · 当前延迟 ${fmt(latest?.latency_ms, " ms")} · 节点 ${latest?.server_sponsor || latest?.server_name || "--"}`;

  internetChart.innerHTML = `
    <svg class="chart-svg internet-svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet">
      ${xTicks}
      ${failureMarkers}
      ${hoverBands}
      <text class="annotation-label top-note" x="${pad.left}" y="14">${topNote}</text>
      ${buildPanel(download, "dot-download", "下载 Mbps", " Mbps", "series-download", summary?.thresholds?.download_alert_mbps || null, 0)}
      ${buildPanel(upload, "dot-upload", "上传 Mbps", " Mbps", "series-upload", summary?.thresholds?.upload_alert_mbps || null, 1)}
      ${buildPanel(latency, "dot-latency", "延迟 ms", " ms", "series-latency", summary?.thresholds?.latency_alert_ms || null, 2)}
      ${focused ? `<line class="focus-line" x1="${toX(focused.x)}" y1="18" x2="${toX(focused.x)}" y2="${height - 28}"></line>` : ""}
      ${focused ? `<text class="focus-label" x="${toX(focused.x) + 6}" y="${height - 12}">${formatTime(focused.row.measured_at)}</text>` : ""}
    </svg>
    <div class="legend compact-legend">
      <span class="legend-item"><span class="legend-swatch legend-download"></span>下载</span>
      <span class="legend-item"><span class="legend-swatch legend-upload"></span>上传</span>
      <span class="legend-item"><span class="legend-swatch legend-latency"></span>延迟</span>
      <span class="legend-item"><span class="legend-swatch legend-event"></span>失败标线</span>
    </div>
  `;
  serverBadge.textContent = latest ? `${latest.server_sponsor || "--"} / ${latest.server_name || "--"} / ${latest.external_ip || "--"}` : "暂无最近测速信息";
  bindTooltipPoints(internetChart);
  internetChart.querySelectorAll("[data-focus-time]").forEach((node) => {
    node.addEventListener("mouseenter", () => {
      setFocusedTime(Number(node.dataset.focusTime));
    });
    node.addEventListener("click", () => {
      setFocusedTime(Number(node.dataset.focusTime));
    });
  });
}

function renderHeartbeatTargetTable() {
  const rows = state.heartbeatTargets;
  heartbeatTargetTableBody.innerHTML = rows.length
    ? rows.map((row) => `<tr><td>${row.target}<br><span class="table-subtle">${row.label || "--"} / ${row.role || "--"}</span></td><td>${row.samples}</td><td>${pct(row.success_rate)}</td><td>${fmt(row.avg_latency_ms, " ms")}</td><td>${formatTime(row.latest_measured_at)}</td></tr>`).join("")
    : `<tr><td colspan="5" class="empty-state">暂无数据</td></tr>`;
}

function renderHeartbeatEventTable() {
  const rows = state.heartbeat.dashboard?.events || [];
  heartbeatEventTableBody.innerHTML = rows.length
    ? rows.slice().reverse().map((row) => `<tr><td>${formatTime(row.start)}</td><td>${row.type === "outage" ? "断流" : "毛刺"}</td><td>${row.target || "--"}</td><td>${row.label}</td></tr>`).join("")
    : `<tr><td colspan="4" class="empty-state">当前时间范围内没有显著事件</td></tr>`;
}

function renderHistoryTable() {
  const rows = [...state.history].sort((a, b) => new Date(b.measured_at) - new Date(a.measured_at)).slice(0, 24);
  historyTableBody.innerHTML = rows.length
    ? rows.map((row) => `<tr><td>${formatTime(row.measured_at)}</td><td class="${row.success ? "ok" : "bad"}">${chipsHtml(row.anomalies || [])}</td><td>${fmt(row.download_mbps)}</td><td>${fmt(row.upload_mbps)}</td><td>${fmt(row.latency_ms)}</td><td>${row.server_name || row.server_sponsor || row.target || "--"}</td></tr>`).join("")
    : `<tr><td colspan="6" class="empty-state">暂无记录</td></tr>`;
}

async function loadData() {
  const heartbeatParams = new URLSearchParams({
    hours: String(state.heartbeat.hours),
    bucket: state.heartbeat.bucket,
    target: state.heartbeat.target,
  });
  const [historyResponse, summaryResponse, heartbeatDashboardResponse, heartbeatTargetsResponse] = await Promise.all([
    fetch(`/api/history?kind=internet&hours=${state.hours}`),
    fetch(`/api/internet/summary?hours=${state.hours}`),
    fetch(`/api/heartbeat/dashboard?${heartbeatParams.toString()}`),
    fetch(`/api/heartbeat/targets?hours=${state.heartbeat.hours}`),
  ]);
  if (!historyResponse.ok || !summaryResponse.ok || !heartbeatDashboardResponse.ok || !heartbeatTargetsResponse.ok) {
    throw new Error("数据读取失败");
  }
  state.history = await historyResponse.json();
  state.summary = await summaryResponse.json();
  state.heartbeat.dashboard = await heartbeatDashboardResponse.json();
  state.heartbeatTargets = await heartbeatTargetsResponse.json();
}

async function refresh() {
  statusText.textContent = "正在同步监控数据...";
  await loadData();
  renderHeartbeatLattice();
  drawTargetCompareChart();
  drawHeartbeatChart();
  drawInternetChart();
  renderHeartbeatTargetTable();
  renderHeartbeatEventTable();
  renderHistoryTable();
  statusText.textContent = `心跳 ${state.heartbeat.target} · ${state.heartbeat.bucket} · 最近 ${state.heartbeat.hours} 小时；${speedtestScheduleSummary()}；测速展示 ${state.hours === 0 ? "全部历史" : `最近 ${state.hours} 小时`}`;
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

window.addEventListener("resize", () => {
  if (!state.summary || !state.heartbeat.dashboard) {
    return;
  }
  drawHeartbeatChart();
  drawInternetChart();
  drawTargetCompareChart();
});
