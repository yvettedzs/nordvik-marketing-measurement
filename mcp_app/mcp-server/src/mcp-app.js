/**
 * Nordvik steering hub dashboard (MCP App). ALL DATA IS SIMULATED (fictional brand "Nordvik Outdoor").
 *
 * Renders what the MCP tools return; computes no metric. The only arithmetic here is presentation:
 * each channel's share of the spend_eur values in the response (axis labels), axis ranges and the
 * lengths of error bars drawn around values the response already contains.
 * Views: roas_lenses, business_health, attribution_sensitivity, conversion_lag, data_quality; plus the audit log.
 */
import { App } from "@modelcontextprotocol/ext-apps";

// ---------------------------------------------------------------- constants
const ROLES = [
  { id: "country_manager_de", label: "Country Manager, Germany" },
  { id: "performance_marketing", label: "Performance Marketing" },
  { id: "leadership", label: "Marketing Leadership" },
];
const CHART_VIEWS = new Set(["roas_lenses", "business_health", "attribution_sensitivity", "conversion_lag"]);
const SEPARATE_PANEL = new Set(["Email"]);     // own linear axis, beside the main panel
const MAIN_DOMAIN = [0, 0.76];
const SIDE_DOMAIN = [0.84, 1];
const MAX_BAR_PX = 24;
const GAP_PX = 2;

const COLOR = {
  surface: "#fcfcfb", ink: "#0b0b0b", ink2: "#52514e", muted: "#898781", grid: "#e1e0d9", axis: "#c3c2b7",
  platform: "#2a78d6", lnd: "#eb6834", tested: "#1baf7a",
};
const STATUS = {   // reserved status colours: always with an icon and a text label
  OK: { color: "#0ca30c", icon: "✓", cls: "st-good", label: "OK" },
  WARN: { color: "#fab219", icon: "!", cls: "st-warning", label: "WARN" },
  FLAG: { color: "#ec835a", icon: "⚑", cls: "st-serious", label: "FLAG" },
  FAIL: { color: "#d03b3b", icon: "✕", cls: "st-critical", label: "FAIL" },
};
const FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif';
const VALIDATION_ONLY = "validation only: not observable in real data";

const SERIES = {
  platform: { name: "Platform ROAS", color: COLOR.platform, pattern: undefined },
  lnd: { name: "Last non-direct ROAS (90 days)", color: COLOR.lnd, pattern: "/" },
  tested: { name: "Tested iROAS (geo holdout, 95% interval)", color: COLOR.tested, pattern: "\\" },
};

// conversion-lag paths: colour + dash + marker, so no path relies on colour alone
const LAG_STYLE = {
  all: { name: "All paths", color: COLOR.ink, dash: "solid", symbol: "circle", width: 2.5 },
  self_serve: { name: "Self-serve", color: COLOR.platform, dash: "dash", symbol: "square", width: 2 },
  lead: { name: "Lead (sales-assisted)", color: COLOR.lnd, dash: "dot", symbol: "diamond", width: 2 },
};

// same labels as analysis/03_attribution_models.py (LABELS)
const MODEL_LABEL = {
  last_click: "Last click", last_non_direct: "Last non-direct", first_click: "First click", linear: "Linear",
  time_decay_7d: "Time decay (7d half-life)", time_decay_30d: "Time decay (30d half-life)",
  u_shaped: "U-shaped 40/20/40", w_shaped: "W-shaped 30/30/30+10",
};
const VIEW_LABEL = {          // used only when the role's own view list does not contain the view (after a refusal)
  roas_lenses: "ROAS lenses", business_health: "Business health", attribution_sensitivity: "Attribution sensitivity",
  conversion_lag: "Conversion lag", data_quality: "Data quality",
};
const CHECK_01_TRUTH_COLUMNS = new Set(["channel_roas", "claim_ratio"]);   // shown only with the leadership overlay
const OPTION_LABEL = { metric: "Metric", group_by: "Group by", market: "Market", channel: "Channel" };
const VALUE_LABEL = {
  mer: "MER", cac: "Blended CAC", cm_after_marketing: "Contribution margin after marketing",
  market: "Market", week: "Week", all: "All markets",
};

// ---------------------------------------------------------------- state
const state = {
  role: "performance_marketing", view: "roas_lenses", views: [], overlay: false,
  opts: {},            // per view: the non-overlay options last used (metric, group_by, market, channel)
  data: null, drill: null, auditOpen: false,
  refusedView: null,   // set while a refusal for this view is on screen: the View menu stays on it
};
const $ = (id) => document.getElementById(id);

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "style") node.style.cssText = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of children.flat()) {
    if (c === undefined || c === null || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

const fmtRatio = (v) => (v === null || v === undefined ? "–" : Number(v).toFixed(2));
const fmtEur = (v, digits = 2) => (v === null || v === undefined ? "–"
  : Number(v).toLocaleString("en-GB", { minimumFractionDigits: digits, maximumFractionDigits: digits }));
const fmtInt = (v) => (v === null || v === undefined ? "–" : Number(v).toLocaleString("en-GB"));
const fmtPct = (v) => (v === null || v === undefined ? "–" : `${(Number(v) * 100).toFixed(1)}%`);
const fmtMetric = (unit, v) => (v === null || v === undefined ? "–"
  : unit === "EUR" ? `EUR ${fmtEur(v, 0)}` : fmtRatio(v));
const label = (v) => VALUE_LABEL[v] ?? v;
const rowsFlagged = (flagged, total) => `${flagged} of ${total} ${total === 1 ? "row" : "rows"} flagged`;

// ---------------------------------------------------------------- MCP app
const app = new App({ name: "Nordvik steering hub", version: "0.2.0" });

function payload(result) {
  if (result && result.structuredContent) return result.structuredContent;
  const text = result?.content?.find((c) => c.type === "text")?.text;
  if (!text) return { error: "Empty tool result.", access_denied: false };
  try { return JSON.parse(text); } catch { return { error: text, access_denied: false }; }
}

async function callTool(name, args) {
  try {
    const result = await app.callServerTool({ name, arguments: args });
    return { result, data: payload(result), isError: Boolean(result.isError) };
  } catch (e) {
    return { result: null, data: { error: `Tool call ${name} failed: ${e?.message ?? e}`, access_denied: false }, isError: true };
  }
}

app.ontoolinput = (params) => {
  const args = params?.arguments ?? {};
  if (typeof args.role === "string") state.role = args.role;
  if (typeof args.view === "string") state.view = args.view;
  const o = args.options && typeof args.options === "object" ? args.options : {};
  state.overlay = o.overlay === true;
  const { overlay: _ignored, ...rest } = o;
  state.opts[state.view] = { ...(state.opts[state.view] ?? {}), ...rest };
  syncControls();
};

app.ontoolresult = (result) => {
  handleViewResult(payload(result), Boolean(result?.isError));
  void refreshViews(false);
};

// ---------------------------------------------------------------- controls
function initControls() {
  const roleSel = $("role-select");
  for (const r of ROLES) roleSel.append(el("option", { value: r.id }, r.label));
  roleSel.addEventListener("change", async () => {
    state.role = roleSel.value;
    state.overlay = false;
    state.opts = {};
    state.refusedView = null;
    closeDrilldown();
    await refreshViews(true);
  });
  $("view-select").addEventListener("change", () => {
    state.view = $("view-select").value;
    state.refusedView = null;
    closeDrilldown();
    syncControls();
    void runView();
  });
  $("overlay-toggle").addEventListener("change", () => {
    state.overlay = $("overlay-toggle").checked;
    closeDrilldown();
    void runView();
  });
  $("table-toggle").addEventListener("click", () => {
    const tv = $("table-view");
    tv.hidden = !tv.hidden;
    $("table-toggle").textContent = tv.hidden ? "Show as table" : "Hide table";
    $("table-toggle").setAttribute("aria-expanded", String(!tv.hidden));
  });
  $("drill-close").addEventListener("click", closeDrilldown);
  $("drill-market").addEventListener("change", renderRoasDrillTable);
  $("audit-toggle").addEventListener("click", () => {
    state.auditOpen = !state.auditOpen;
    $("audit-body").hidden = !state.auditOpen;
    $("audit-controls").hidden = !state.auditOpen;
    $("audit-toggle").textContent = state.auditOpen ? "Hide audit log" : "Show audit log";
    $("audit-toggle").setAttribute("aria-expanded", String(state.auditOpen));
    if (state.auditOpen) void refreshAudit();
  });
  $("audit-refresh").addEventListener("click", () => void refreshAudit());
  $("audit-limit").addEventListener("change", () => void refreshAudit());
  syncControls();
}

function currentSpec() {
  return state.views.find((v) => v.id === state.view) ?? null;
}

function syncControls() {
  const roleSel = $("role-select");
  if (![...roleSel.options].some((o) => o.value === state.role)) roleSel.append(el("option", { value: state.role }, state.role));
  roleSel.value = state.role;
  const viewSel = $("view-select");
  viewSel.replaceChildren();
  const views = state.views.length ? state.views : [{ id: state.view, label: VIEW_LABEL[state.view] ?? state.view }];
  for (const v of views) viewSel.append(el("option", { value: v.id }, v.label));
  if (!views.some((v) => v.id === state.view)) {
    // a refused view stays selected (greyed out) while its refusal is on screen
    const refused = state.refusedView === state.view;
    viewSel.append(el("option", { value: state.view, disabled: true },
      (VIEW_LABEL[state.view] ?? state.view) + (refused ? " (refused for this role)" : "")));
  }
  viewSel.value = state.view;
  const spec = currentSpec();
  const overlayAllowed = Boolean(spec && spec.options && spec.options.overlay);
  $("overlay-control").hidden = !overlayAllowed;
  $("overlay-toggle").checked = overlayAllowed && state.overlay;
  renderOptionControls(spec);
}

/** One select per enum option the server lists for this view and role (overlay is the header checkbox). */
function renderOptionControls(spec) {
  const row = $("view-options");
  row.replaceChildren();
  if (!spec) return;
  const opts = (state.opts[spec.id] = state.opts[spec.id] ?? {});
  for (const [name, o] of Object.entries(spec.options ?? {})) {
    if (o.type !== "enum") continue;
    if (!o.values.includes(opts[name])) opts[name] = o.default;
    const locked = o.values.length === 1;
    const sel = el("select", { "aria-label": OPTION_LABEL[name] ?? name, disabled: locked },
      ...o.values.map((v) => el("option", { value: v }, label(v) + (locked ? " (locked for this role)" : ""))));
    sel.value = opts[name];
    sel.addEventListener("change", () => {
      opts[name] = sel.value;
      closeDrilldown();
      void runView();
    });
    row.append(el("label", {}, OPTION_LABEL[name] ?? name, sel));
  }
}

async function refreshViews(runAfter) {
  const { data, isError } = await callTool("list_views", { role: state.role });
  if (isError) {
    state.views = [];
    syncControls();
    showError(data);
    return;
  }
  state.views = data.result.views;
  const keepRefused = !runAfter && state.refusedView === state.view;
  if (!keepRefused && !state.views.some((v) => v.id === state.view) && state.views.length) state.view = state.views[0].id;
  syncControls();
  if (runAfter) await runView();
}

function viewOptions() {
  const spec = currentSpec();
  const options = {};
  for (const [name, o] of Object.entries(spec?.options ?? {})) {
    if (name === "overlay") options.overlay = state.overlay;
    else if (o.type === "enum") options[name] = state.opts[state.view]?.[name] ?? o.default;
  }
  return options;
}

async function runView() {
  const options = viewOptions();
  showStatus(state.view === "business_health" && options.group_by === "week"
    ? "Loading the weekly series… (in the first minutes after the API starts, a market can take up to a minute)"
    : "Loading…");
  const { data, isError } = await callTool("run_view", { role: state.role, view: state.view, options });
  handleViewResult(data, isError);
}

// ---------------------------------------------------------------- status / errors
function showStatus(text) {
  const s = $("status");
  s.replaceChildren(text);
  s.hidden = false;
}

function errorBox(data) {
  const lbl = data && data.access_denied ? "Access refused" : "Error";
  return el("div", { class: "error" }, el("span", { class: "label" }, lbl + ":"), data?.error ?? "Unknown error");
}

function showError(data) {
  const s = $("status");
  s.replaceChildren(errorBox(data));
  s.hidden = false;
}

function hideView() {
  $("view").hidden = true;
  $("footer").hidden = true;
  closeDrilldown();
}

function handleViewResult(data, isError) {
  if (isError || !data || data.error) {
    state.refusedView = data && data.access_denied ? state.view : null;
    hideView();
    syncControls();
    showError(data);
    if (state.auditOpen) void refreshAudit();
    return;
  }
  state.refusedView = null;
  state.data = data;
  if (data.role) state.role = data.role;
  if (data.view) state.view = data.view;
  if (data.options) {
    const { overlay, ...rest } = data.options;
    if (typeof overlay === "boolean") state.overlay = overlay;
    state.opts[state.view] = { ...(state.opts[state.view] ?? {}), ...rest };
  }
  syncControls();
  $("status").hidden = true;
  renderFooter(data);
  renderView(data);
  if (state.auditOpen) void refreshAudit();
}

function renderView(data) {
  $("view").hidden = false;
  $("panel-note").textContent = "";
  $("overlay-banner").hidden = true;
  $("chart-legend").hidden = true;
  $("table-toggle").hidden = false;
  renderList($("caveats"), data.caveats);
  const renderers = {
    roas_lenses: renderRoasLenses,
    business_health: renderBusinessHealth,
    attribution_sensitivity: renderAttribution,
    conversion_lag: renderConversionLag,
    data_quality: renderDataQuality,
  };
  const fn = renderers[data.view];
  if (fn) fn(data);
  else showStatus(`Unknown view "${data.view}".`);
}

/** Show the Plotly area (or the tiles area). Returns false when Plotly is missing (table shown instead). */
function useChart(on, ariaLabel) {
  const chart = $("chart");
  if (!on) {
    if (window.Plotly) window.Plotly.purge(chart);
    chart.replaceChildren();
    chart.hidden = true;
    $("tiles").hidden = false;
    return true;
  }
  $("tiles").hidden = true;
  $("tiles").replaceChildren();
  chart.hidden = false;
  chart.setAttribute("aria-label", ariaLabel);
  if (!window.Plotly) {
    chart.replaceChildren(el("div", { class: "error" }, el("span", { class: "label" }, "Chart unavailable:"),
      "Plotly could not be loaded from cdn.plot.ly. The table below shows every value."));
    $("table-view").hidden = false;
    return false;
  }
  return true;
}

function setTable(head, rows) {
  $("table-view").replaceChildren(el("div", { class: "scroll" },
    el("table", {}, el("thead", {}, el("tr", {}, ...head)), el("tbody", {}, rows))));
}

function baseLayout(extra) {
  return {
    paper_bgcolor: COLOR.surface, plot_bgcolor: COLOR.surface,
    font: { family: FONT, size: 12, color: COLOR.ink2 },
    hovermode: "closest", dragmode: false, showlegend: false,
    hoverlabel: { bgcolor: COLOR.surface, bordercolor: COLOR.axis, font: { family: FONT, color: COLOR.ink, size: 12 } },
    ...extra,
  };
}

function plot(traces, layout, onClick) {
  const chartEl = $("chart");
  chartEl.style.height = `${layout.height}px`;        // the box follows each chart's own height
  window.Plotly.react(chartEl, traces, layout, { displayModeBar: false, responsive: true });
  chartEl.removeAllListeners?.("plotly_click");
  chartEl.on("plotly_click", (ev) => {
    const cd = ev?.points?.[0]?.customdata;
    if (cd === undefined || cd === null) return;
    // one click can arrive twice (seen in the audit log 0.2 s apart): ignore a repeat on the same point within 0.5 s
    const key = JSON.stringify(cd);
    const now = Date.now();
    if (key === lastClick.key && now - lastClick.at < 500) return;
    lastClick.key = key;
    lastClick.at = now;
    onClick(cd);
  });
}
const lastClick = { key: "", at: 0 };

function plotWidth(margin) {
  return Math.max(200, ($("chart").clientWidth || 900) - margin.l - margin.r);
}

// ---------------------------------------------------------------- footer and caveats
function renderFooter(data) {
  const f = $("footer");
  const defs = Object.entries(data.definitions_used ?? {});
  f.replaceChildren(
    el("div", {}, el("span", { class: "badge" }, "Simulated data"), " ", data.notice ?? ""),
    el("dl", {},
      el("dt", {}, "Definitions used"),
      ...defs.map(([k, v]) => el("dd", {}, el("strong", {}, k + ": "), v)),
      el("dt", {}, "Sources"),
      el("dd", {}, ...(data.sources ?? []).flatMap((s, i) => [i ? ", " : "", el("code", {}, s)])),
      data.conventions ? el("dt", {}, "Conventions") : null,
      data.conventions ? el("dd", {}, data.conventions) : null,
    ),
  );
  f.hidden = false;
}

function renderList(ul, items) {
  ul.replaceChildren(...(items ?? []).map((c) => el("li", {}, c)));
}

// ---------------------------------------------------------------- roas_lenses
function spendShares(channels) {
  const total = channels.reduce((a, c) => a + (c.spend_eur ?? 0), 0);
  const out = {};
  for (const c of channels) {
    const pct = total > 0 ? (100 * c.spend_eur) / total : 0;
    out[c.channel] = pct > 0 && pct < 1 ? "<1%" : `${Math.round(pct)}%`;
  }
  return out;
}

function niceCeil(v) {
  if (!(v > 0)) return 1;
  const step = v <= 10 ? 1 : v <= 50 ? 5 : 10 ** Math.floor(Math.log10(v));
  return Math.ceil(v / step) * step;
}

function panelMax(rows, truthByChannel) {
  let m = 0;
  for (const r of rows) {
    for (const v of [r.platform_roas, r.last_non_direct_roas_90d, r.tested_iroas?.value, r.tested_iroas?.ci_95?.[1]]) {
      if (typeof v === "number") m = Math.max(m, v);
    }
    const t = truthByChannel[r.channel];
    if (t) for (const v of [t.simulated_true_iroas, t.journey_true_iroas]) if (typeof v === "number") m = Math.max(m, v);
  }
  return m;
}

const MAIN_TICK_STEP = 3;
const NARROW_CHART_PX = 600;     // below this chart width the tested label shows only its value

/** Axis top per panel: the main panel rounds up to a multiple of its tick step (SEO's 8.0 -> 9). */
function roasTop(rows, truth, isMain) {
  const raw = panelMax(rows, truth) * 1.08;
  return isMain ? Math.max(MAIN_TICK_STEP, Math.ceil(raw / MAIN_TICK_STEP) * MAIN_TICK_STEP) : niceCeil(raw);
}

function sideStep(top) {
  return top <= 10 ? 2 : top <= 40 ? 5 : 10;
}

function renderRoasLenses(data) {
  const res = data.result;
  const overlay = res.overlay ?? null;
  const truth = Object.fromEntries((overlay?.channels ?? []).map((t) => [t.channel, t]));
  const shares = spendShares(res.channels);
  const main = res.channels.filter((c) => !SEPARATE_PANEL.has(c.channel));
  const side = res.channels.filter((c) => SEPARATE_PANEL.has(c.channel));

  $("view-title").textContent = "ROAS lenses: what platforms claim, what attribution credits, what a test measured";
  const scope = res.scope ? res.scope[0].toUpperCase() + res.scope.slice(1) : "";
  $("view-subtitle").textContent = `${scope}. Break-even ROAS ${fmtRatio(res.break_even_roas)} ` +
    `(${res.break_even_formula}). Click a bar for weekly rows by market.`;
  $("overlay-banner").hidden = !overlay;
  $("overlay-banner-text").textContent = "Black ticks mark the simulation's true iROAS on the bar from the same dataset.";
  renderRoasTable(res, shares, truth);
  renderRoasLegend(overlay, res.break_even_roas);
  if (!useChart(true, "ROAS lenses chart")) return;
  drawRoasChart(res, main, side, shares, truth, overlay);
}

/** HTML legend above the chart (wraps on narrow widths). Swatches repeat each mark's encoding, not only its colour. */
function renderRoasLegend(overlay, be) {
  const item = (cls, text) => el("span", { class: "legend-item" }, el("span", { class: `sw ${cls}`, "aria-hidden": "true" }), text);
  const lg = $("chart-legend");
  lg.replaceChildren(...[
    item("sw-platform", SERIES.platform.name),
    item("sw-lnd", SERIES.lnd.name),
    item("sw-tested", SERIES.tested.name),
    overlay ? item("sw-truth", `Simulated truth (${VALIDATION_ONLY})`) : null,
    item("sw-breakeven", `Break-even ROAS ${fmtRatio(be)} (both panels; marked on both axes)`),
  ].filter(Boolean));
  lg.hidden = false;
}

/** Regular ticks from 0 to top, plus the break-even value as an extra labelled tick. The main panel uses steps of 3
 *  (0, 3, 6, 9) so the bold 1.82 tick never sits on a "2"; other panels step by 5 or 10. */
function roasTicks(top, be, step) {
  const vals = [];
  for (let v = 0; v <= top + 1e-9; v += step) vals.push(v);
  return { tickvals: [...vals, be], ticktext: [...vals.map((v) => String(v)), `<b>${fmtRatio(be)}</b>`] };
}

function drawRoasChart(res, main, side, shares, truth, overlay) {
  const margin = { l: 52, r: 16, t: 44, b: 60 };    // legend is HTML above the chart; top room is for the side note
  const plotW = plotWidth(margin);
  const narrow = ($("chart").clientWidth || 900) < NARROW_CHART_PX;
  const traces = [];
  const annotations = [];
  const shapes = [];
  const be = res.break_even_roas;
  // the note under the chart: everything that would otherwise need text inside the plot area
  const notes = ["The percentage under each channel name is its share of total spend."];
  const noPlatform = res.channels.filter((r) => r.platform_roas === null || r.platform_roas === undefined);
  if (noPlatform.length) {
    notes.push(`${noPlatform.map((r) => r.channel).join(", ")} has no ad platform, so there is no platform ROAS bar.`);
  }
  if (narrow) {
    for (const r of res.channels.filter((c) => c.tested_iroas)) {
      const t = r.tested_iroas;
      notes.push(`${r.channel} tested iROAS ${fmtRatio(t.value)}, 95% interval ${fmtRatio(t.ci_95[0])}–` +
        `${fmtRatio(t.ci_95[1])} (the whisker on the green bar).`);
    }
  }

  const panels = [
    { rows: main, x: "x", y: "y", domain: MAIN_DOMAIN, legend: true },
    { rows: side, x: "x2", y: "y2", domain: SIDE_DOMAIN, legend: false },
  ].filter((p) => p.rows.length);

  const layout = baseLayout({
    height: 460, margin,
    barmode: "overlay", barcornerradius: 4, showlegend: false,
    annotations, shapes,
  });

  for (const [pi, p] of panels.entries()) {
    const n = p.rows.length;
    // the side panel gets extra room on the right so its break-even label clears the bars
    const range = pi === 0 ? [-0.6, n - 0.4] : [-0.6, n + 0.1];
    const pxPerCat = (plotW * (p.domain[1] - p.domain[0])) / (range[1] - range[0]);
    const w = Math.min(0.24, MAX_BAR_PX / pxPerCat);
    const off = w + GAP_PX / pxPerCat;
    const xs = p.rows.map((_, i) => i);
    const names = p.rows.map((r) => r.channel);
    const top = roasTop(p.rows, truth, pi === 0);
    const sfx = pi === 0 ? "" : "2";

    layout[`xaxis${sfx}`] = {
      domain: p.domain, anchor: `y${sfx}`, range, fixedrange: true, showgrid: false, zeroline: false,
      tickmode: "array", tickvals: xs, ticktext: p.rows.map((r) => `${r.channel}<br>${shares[r.channel]}`),
      tickangle: 0, tickfont: { color: COLOR.ink, size: 12 }, ticks: "", showline: true, linecolor: COLOR.axis,
    };
    layout[`yaxis${sfx}`] = {
      domain: [0, 1], anchor: `x${sfx}`, range: [0, top], fixedrange: true, rangemode: "tozero",
      gridcolor: COLOR.grid, gridwidth: 1, zeroline: false, showline: false, ticks: "",
      tickfont: { color: COLOR.muted, size: 11 }, tickmode: "array",
      ...roasTicks(top, be, pi === 0 ? MAIN_TICK_STEP : sideStep(top)),
      title: pi === 0 ? { text: "ROAS (revenue / spend)", font: { color: COLOR.ink2, size: 12 } } : undefined,
    };

    const bar = (key, dx, ys, extra = {}) => {
      const s = SERIES[key];
      traces.push({
        type: "bar", name: s.name, legendgroup: key, showlegend: p.legend,
        xaxis: p.x, yaxis: p.y, x: xs.map((i) => i + dx), y: ys, width: w,
        marker: {
          color: s.color, line: { width: 0 },
          pattern: s.pattern ? { shape: s.pattern, fillmode: "overlay", fgcolor: COLOR.surface, fgopacity: 0.9,
                                 size: 6, solidity: 0.3 } : undefined,
        },
        customdata: names.map((c) => [c, s.name]),
        hovertemplate: "<b>%{customdata[0]}</b><br>%{customdata[1]}: %{y:.2f}<extra></extra>",
        ...extra,
      });
    };

    bar("platform", -off, p.rows.map((r) => r.platform_roas));
    bar("lnd", 0, p.rows.map((r) => r.last_non_direct_roas_90d));
    const tested = p.rows.map((r) => r.tested_iroas);
    if (tested.some(Boolean) || p.legend) {
      bar("tested", off, tested.map((t) => (t ? t.value : null)), {
        error_y: {
          type: "data", symmetric: false, visible: true, color: COLOR.ink, thickness: 1.5, width: 5,
          array: tested.map((t) => (t ? t.ci_95[1] - t.value : null)),
          arrayminus: tested.map((t) => (t ? t.value - t.ci_95[0] : null)),
        },
        customdata: p.rows.map((r) => [r.channel, SERIES.tested.name,
          r.tested_iroas ? `${fmtRatio(r.tested_iroas.ci_95[0])} to ${fmtRatio(r.tested_iroas.ci_95[1])}` : "",
          r.tested_iroas ? `${r.tested_iroas.market}; ${r.tested_iroas.verdict}` : ""]),
        hovertemplate: "<b>%{customdata[0]}</b><br>Tested iROAS: %{y:.2f} (95% interval %{customdata[2]})" +
          "<br>%{customdata[3]}<extra></extra>",
      });
    }

    p.rows.forEach((r, i) => {
      if (r.tested_iroas) {
        const t = r.tested_iroas;
        // two lines centred on the tested bar; on narrow charts only the value (the interval goes to the note)
        annotations.push({ xref: p.x, yref: p.y, x: i + off, y: t.ci_95[1], yanchor: "bottom", yshift: 4,
          text: narrow ? fmtRatio(t.value)
            : `tested ${fmtRatio(t.value)}<br>(${fmtRatio(t.ci_95[0])}–${fmtRatio(t.ci_95[1])})`, align: "center",
          showarrow: false, font: { color: COLOR.ink, size: 11 } });
      }
      // a missing platform figure is explained in the note under the chart, never inside the plot area
    });

    if (overlay) {
      const tx = [], ty = [], cd = [];
      p.rows.forEach((r, i) => {
        const t = truth[r.channel];
        if (!t) return;
        if (typeof t.simulated_true_iroas === "number") {
          tx.push(i - off); ty.push(t.simulated_true_iroas);
          cd.push([r.channel, "Simulated true iROAS (weekly dataset; compare with platform ROAS)"]);
        }
        if (typeof t.journey_true_iroas === "number") {
          tx.push(i); ty.push(t.journey_true_iroas);
          cd.push([r.channel, "Journey true iROAS (journey simulation; compare with last non-direct ROAS)"]);
        }
      });
      traces.push({
        type: "scatter", mode: "markers", name: `Simulated truth (${VALIDATION_ONLY})`, legendgroup: "truth",
        showlegend: p.legend, xaxis: p.x, yaxis: p.y, x: tx, y: ty, customdata: cd,
        // tick as long as its bar, minus 2px, so ticks on neighbouring bars never join into one line
        marker: { symbol: "line-ew", size: Math.max(10, Math.round(w * pxPerCat) - 2),
                  line: { width: 3, color: COLOR.ink }, color: COLOR.ink },
        hovertemplate: `<b>%{customdata[0]}</b><br>%{customdata[1]}: %{y:.2f}<br>${VALIDATION_ONLY}<extra></extra>`,
      });
    }

    // break-even: the line in each panel, labelled by the bold tick on its y axis and in the HTML legend
    shapes.push({ type: "line", xref: `${p.x} domain`, yref: p.y, x0: 0, x1: 1, y0: be, y1: be,
                  line: { color: COLOR.ink2, width: 1.5 }, layer: "above" });
    if (pi === 1) {
      annotations.push({ xref: `${p.x} domain`, yref: "paper", x: 0.5, y: 1, yanchor: "bottom", yshift: 6,
        text: `<b>Different scale</b><br>axis runs to ${top}`, showarrow: false, align: "center",
        font: { color: COLOR.ink, size: 11 } });
      notes.splice(1, 0, `${p.rows.map((r) => r.channel).join(", ")} is shown on its own linear scale ` +
        `(axis 0 to ${top}), so its bars are not comparable by height with the main panel (axis 0 to ` +
        `${roasTop(main, truth, true)}).`);
    }
  }
  $("panel-note").textContent = notes.join(" ");

  plot(traces, layout, (cd) => void openRoasDrilldown(cd[0]));
}

function renderRoasTable(res, shares, truth) {
  const hasTruth = Object.keys(truth).length > 0;
  const head = [
    el("th", {}, "Channel"), el("th", { class: "num" }, "Share of spend"), el("th", { class: "num" }, "Spend (EUR)"),
    el("th", { class: "num" }, el("span", { class: "swatch", style: `background:${COLOR.platform}` }), "Platform ROAS"),
    el("th", { class: "num" }, el("span", { class: "swatch", style: `background:${COLOR.lnd}` }), "Last non-direct (90d)"),
    el("th", { class: "num" }, el("span", { class: "swatch", style: `background:${COLOR.tested}` }), "Tested iROAS (95% interval)"),
    hasTruth ? el("th", { class: "num" }, "Simulated true iROAS (validation only)") : null,
    hasTruth ? el("th", { class: "num" }, "Journey true iROAS (validation only)") : null,
    el("th", {}, "Drilldown"),
  ];
  const rows = res.channels.map((r) => {
    const t = r.tested_iroas;
    return el("tr", {},
      el("td", {}, r.channel), el("td", { class: "num" }, shares[r.channel]), el("td", { class: "num" }, fmtEur(r.spend_eur, 0)),
      el("td", { class: "num" }, fmtRatio(r.platform_roas)), el("td", { class: "num" }, fmtRatio(r.last_non_direct_roas_90d)),
      el("td", { class: "num" }, t ? `${fmtRatio(t.value)} (${fmtRatio(t.ci_95[0])}–${fmtRatio(t.ci_95[1])})` : "–"),
      hasTruth ? el("td", { class: "num" }, fmtRatio(truth[r.channel]?.simulated_true_iroas)) : null,
      hasTruth ? el("td", { class: "num" }, fmtRatio(truth[r.channel]?.journey_true_iroas)) : null,
      el("td", {}, el("button", { type: "button", onclick: () => openRoasDrilldown(r.channel) }, "Weekly rows")),
    );
  });
  setTable(head, rows);
}

// ---------------------------------------------------------------- business_health
function renderBusinessHealth(data) {
  const res = data.result;
  const mk = res.market === "all" ? "All markets" : res.market;
  $("view-title").textContent = `Business health: ${res.metric_label}`;
  const single = res.group_by === "market" && res.points.length === 1;
  const clickHint = res.group_by === "market" ? (single ? "Click Details for the totals."
    : "Click a bar for that market's totals.") : "Click a point for that week's totals.";
  $("view-subtitle").textContent = `${mk}, ${res.period}. ${clickHint}`;

  const segName = res.group_by === "market" ? "Market" : "Week starting";
  setTable([el("th", {}, segName), el("th", { class: "num" }, res.metric_label), el("th", {}, "Drilldown")],
    res.points.map((p) => el("tr", {}, el("td", {}, p.segment), el("td", { class: "num" }, fmtMetric(res.unit, p.value)),
      el("td", {}, el("button", { type: "button", onclick: () => openBusinessDrill(res.group_by, p.segment) }, "Totals")))));

  if (single) {               // one value: a stat tile, not a one-bar chart
    $("table-toggle").hidden = true;
    $("table-view").hidden = true;
    useChart(false);
    const p = res.points[0];
    $("tiles").replaceChildren(el("div", { class: "card stat-tile" },
      el("div", { class: "tile-kicker" }, `${p.segment}, ${res.period.replace(/ \(.*\)$/, "")}`),
      el("div", { class: "tile-name" }, res.metric_label),
      el("div", { class: "hero" }, fmtMetric(res.unit, p.value)),
      el("button", { type: "button", onclick: () => openBusinessDrill("market", p.segment) }, "Details")));
    return;
  }
  if (!useChart(true, `Business health: ${res.metric_label} by ${res.group_by}`)) return;

  const margin = { l: 84, r: 16, t: 16, b: 48 };
  const yaxis = {
    rangemode: "tozero", fixedrange: true, gridcolor: COLOR.grid, zeroline: true, zerolinecolor: COLOR.axis,
    showline: false, ticks: "", tickfont: { color: COLOR.muted, size: 11 },
    tickformat: res.unit === "EUR" ? "~s" : ".1f", tickprefix: res.unit === "EUR" ? "EUR " : "",
    title: { text: res.unit === "EUR" ? "EUR" : res.metric.toUpperCase(), font: { color: COLOR.ink2, size: 12 } },
  };
  const hover = `<b>%{customdata}</b><br>${res.metric_label}: ` +
    (res.unit === "EUR" ? "EUR %{y:,.0f}" : "%{y:.2f}") + "<extra></extra>";

  if (res.group_by === "market") {
    const n = res.points.length;
    const pxPerCat = plotWidth(margin) / n;
    plot([{
      type: "bar", x: res.points.map((p) => p.segment), y: res.points.map((p) => p.value),
      width: Math.min(0.6, MAX_BAR_PX * 1.5 / pxPerCat), marker: { color: COLOR.platform, line: { width: 0 } },
      customdata: res.points.map((p) => p.segment), hovertemplate: hover,
    }], baseLayout({
      height: 380, margin, barcornerradius: 4,
      xaxis: { fixedrange: true, showgrid: false, ticks: "", showline: true, linecolor: COLOR.axis,
               tickfont: { color: COLOR.ink, size: 12 }, type: "category" },
      yaxis,
    }), (seg) => void openBusinessDrill("market", seg));
  } else {
    plot([{
      // 104 points: a plain 2px line; hover snaps to the nearest week and a click opens it
      type: "scatter", mode: "lines", x: res.points.map((p) => p.segment), y: res.points.map((p) => p.value),
      line: { color: COLOR.platform, width: 2 },
      customdata: res.points.map((p) => p.segment),
      hovertemplate: `<b>Week starting %{customdata}</b><br>${res.metric_label}: ` +
        (res.unit === "EUR" ? "EUR %{y:,.0f}" : "%{y:.2f}") + "<extra></extra>",
    }], baseLayout({
      height: 380, margin, hovermode: "x",
      xaxis: { type: "date", fixedrange: true, showgrid: false, ticks: "outside", ticklen: 4, tickcolor: COLOR.axis,
               showline: true, linecolor: COLOR.axis, tickfont: { color: COLOR.ink2, size: 11 },
               showspikes: true, spikemode: "across", spikethickness: 1, spikecolor: COLOR.muted, spikedash: "solid" },
      yaxis,
    }), (seg) => void openBusinessDrill("week", seg));
  }
}

// ---------------------------------------------------------------- attribution_sensitivity
function renderAttribution(data) {
  const res = data.result;
  $("view-title").textContent = `Attribution sensitivity: ${res.channel}, model-credited ROAS under 8 models (90-day lookback)`;
  $("view-subtitle").textContent = `${res.label}. ${res.scope ? res.scope[0].toUpperCase() + res.scope.slice(1) + ". " : ""}` +
    `Journey spend EUR ${fmtEur(res.journey_spend_eur, 0)}. Break-even ROAS ${fmtRatio(res.break_even_roas)}. ` +
    "Click a bar for that model at other lookbacks.";

  setTable([el("th", {}, "Model"),
    el("th", { class: "num" }, el("span", { class: "swatch", style: `background:${COLOR.lnd}` }), "Model-credited ROAS (90d)"),
    el("th", {}, "Drilldown")],
  res.models.map((m) => el("tr", {}, el("td", {}, MODEL_LABEL[m.model] ?? m.model),
    el("td", { class: "num" }, fmtRatio(m.model_roas)),
    el("td", {}, el("button", { type: "button", onclick: () => openAttributionDrill(m.model) }, "Lookbacks")))));
  if (!useChart(true, `Attribution sensitivity for ${res.channel}`)) return;

  const be = res.break_even_roas;
  const n = res.models.length;
  const rowPx = 36;
  const margin = { l: 200, r: 24, t: 28, b: 48 };
  const top = niceCeil(Math.max(be, ...res.models.map((m) => m.model_roas ?? 0)) * 1.08);
  plot([{
    type: "bar", orientation: "h", y: res.models.map((m) => MODEL_LABEL[m.model] ?? m.model),
    x: res.models.map((m) => m.model_roas), width: Math.min(0.8, MAX_BAR_PX / rowPx),
    marker: { color: COLOR.lnd, line: { width: 0 },
              pattern: { shape: "/", fillmode: "overlay", fgcolor: COLOR.surface, fgopacity: 0.9, size: 6, solidity: 0.3 } },
    customdata: res.models.map((m) => m.model),
    hovertemplate: "<b>%{y}</b><br>Model-credited ROAS (90d): %{x:.2f}<extra></extra>",
  }], baseLayout({
    height: n * rowPx + margin.t + margin.b, margin, barcornerradius: 4,
    yaxis: { autorange: "reversed", fixedrange: true, ticks: "", showgrid: false, tickfont: { color: COLOR.ink, size: 12 },
             type: "category", showline: true, linecolor: COLOR.axis },
    xaxis: { range: [0, top], fixedrange: true, gridcolor: COLOR.grid, zeroline: false, ticks: "",
             tickfont: { color: COLOR.muted, size: 11 }, tickformat: top > 10 ? ".0f" : ".1f",
             // short title so it fits at 480 px; the subtitle carries the full definition
             title: { text: "Model-credited ROAS", font: { color: COLOR.ink2, size: 12 } } },
    shapes: [{ type: "line", xref: "x", yref: "paper", x0: be, x1: be, y0: 0, y1: 1,
               line: { color: COLOR.ink2, width: 1.5 }, layer: "above" }],
    annotations: [{ xref: "x", yref: "paper", x: be, y: 1, yanchor: "bottom", xanchor: "left", xshift: 4, yshift: 2,
                    text: `Break-even ${fmtRatio(be)}`, showarrow: false, font: { color: COLOR.ink2, size: 11 } }],
  }), (model) => void openAttributionDrill(model));
}

// ---------------------------------------------------------------- conversion_lag
function renderConversionLag(data) {
  const res = data.result;
  const days = res.checkpoints_days;
  const r30 = res.day30_weekly_range;
  $("view-title").textContent = "Conversion lag: how much of a cohort's 365-day orders is visible after d days";
  $("view-subtitle").textContent = `${res.scope[0].toUpperCase() + res.scope.slice(1)}. ` +
    "Click a point for blended CAC and payback at 30, 90 and 365 days.";
  $("panel-note").textContent = `Bar on the all-paths day-30 point: range across weekly cohorts, ${fmtPct(r30.min)} to ` +
    `${fmtPct(r30.max)} (median ${fmtPct(r30.median)}). All markets pooled: the results file is not split by market.`;

  setTable([el("th", {}, "Path"), ...days.map((d) => el("th", { class: "num" }, `${d} d`))],
    res.series.map((s) => el("tr", {}, el("td", {}, LAG_STYLE[s.path]?.name ?? s.path),
      ...s.share_visible.map((v, i) => el("td", { class: "num" },
        el("button", { type: "button", class: "link-button", onclick: () => openLagDrill(s.path, days[i]) }, fmtPct(v)))))));
  if (!useChart(true, "Conversion lag chart")) return;

  const i30 = days.indexOf(30);
  const traces = res.series.map((s) => {
    const st = LAG_STYLE[s.path] ?? { name: s.path, color: COLOR.ink2, dash: "solid", symbol: "circle", width: 2 };
    const t = {
      type: "scatter", mode: "lines+markers", name: st.name, x: days, y: s.share_visible,
      line: { color: st.color, width: st.width, dash: st.dash },
      marker: { symbol: st.symbol, size: 9, color: st.color, line: { width: 2, color: COLOR.surface } },
      customdata: days.map((d) => [s.path, d, st.name]),
      hovertemplate: "<b>%{customdata[2]}</b><br>Day %{x}: %{y:.1%} of 365-day orders visible<extra></extra>",
    };
    if (s.path === "all" && i30 >= 0) {
      const v = s.share_visible[i30];
      t.error_y = { type: "data", symmetric: false, visible: true, color: COLOR.ink, thickness: 1.5, width: 6,
        array: days.map((_, i) => (i === i30 ? r30.max - v : null)),
        arrayminus: days.map((_, i) => (i === i30 ? v - r30.min : null)) };
    }
    return t;
  });
  // direct labels where each path has free space: self-serve above-left of its day-90 point (the steepest line),
  // all paths below-right of its day-90 point, lead below-right of its day-180 point
  const LABEL_AT = {
    self_serve: { day: 90, xanchor: "right", yanchor: "bottom", xshift: -8, yshift: 6 },
    all: { day: 90, xanchor: "left", yanchor: "top", xshift: 8, yshift: -6 },
    lead: { day: 180, xanchor: "left", yanchor: "top", xshift: 8, yshift: -6 },
  };
  const annotations = res.series.flatMap((s) => {
    const pos = LABEL_AT[s.path];
    const i = pos ? days.indexOf(pos.day) : -1;
    if (i < 0) return [];
    const { day: _d, ...anchor } = pos;
    return [{ x: days[i], y: s.share_visible[i], ...anchor, showarrow: false,
              text: LAG_STYLE[s.path]?.name ?? s.path, font: { color: COLOR.ink, size: 11 } }];
  });
  plot(traces, baseLayout({
    height: 420, margin: { l: 64, r: 24, t: 48, b: 56 }, showlegend: true,
    legend: { orientation: "h", x: 0, xanchor: "left", y: 1.02, yanchor: "bottom", font: { color: COLOR.ink, size: 12 },
              itemclick: false, itemdoubleclick: false },
    // the axis starts left of 0 so the day-7 points sit clear of the axis corner and are easy to click
    xaxis: { range: [-12, 380], fixedrange: true, tickmode: "array", tickvals: days, ticktext: days.map((d) => `${d}`),
             showgrid: false, ticks: "outside", ticklen: 4, tickcolor: COLOR.axis, showline: true, linecolor: COLOR.axis,
             tickfont: { color: COLOR.ink2, size: 11 },
             title: { text: "Days since first click", font: { color: COLOR.ink2, size: 12 } } },
    yaxis: { range: [0, 1.04], fixedrange: true, tickformat: ".0%", gridcolor: COLOR.grid, zeroline: false, ticks: "",
             tickfont: { color: COLOR.muted, size: 11 },
             title: { text: "Share of 365-day orders visible", font: { color: COLOR.ink2, size: 12 } } },
    annotations,
  }), (cd) => void openLagDrill(cd[0], cd[1]));
}

// ---------------------------------------------------------------- data_quality
function statusChip(status) {
  const st = STATUS[status] ?? { color: COLOR.muted, icon: "?", cls: "", label: status ?? "unknown" };
  return el("span", { class: "status-chip" },
    el("span", { class: `status-icon ${st.cls}`, style: `background:${st.color}`, "aria-hidden": "true" }, st.icon),
    st.label);
}

function renderDataQuality(data) {
  const res = data.result;
  const overlay = data.options?.overlay === true;
  $("view-title").textContent = "Data quality: four checks on the simulated data";
  $("view-subtitle").textContent = `Status levels, mildest first: ${res.status_levels.join(", ")}. ` +
    "Click a tile for the rule, the action and the flagged rows.";
  $("overlay-banner").hidden = !overlay;
  $("overlay-banner-text").textContent = "Check 01's drilldown shows channel_roas and claim_ratio.";
  $("table-toggle").hidden = true;
  $("table-view").hidden = true;
  useChart(false);
  $("tiles").replaceChildren(el("div", { class: "tiles" }, ...res.tiles.map((t) => el("button", {
    type: "button", class: "tile", onclick: () => openQualityDrill(t.number),
    "aria-label": `Check ${t.number}, status ${t.status}, ${rowsFlagged(t.flagged_count, t.row_count)}. Open details.`,
  },
  el("div", { class: "tile-kicker" }, `Check ${t.number}`),
  el("div", { class: "tile-name" }, t.description),
  statusChip(t.status),
  el("div", { class: "tile-detail" }, rowsFlagged(t.flagged_count, t.row_count)),
  t.status_detail && t.status_detail !== t.status ? el("div", { class: "tile-detail" }, t.status_detail) : null,
  t.validation_note ? el("div", { class: "tile-detail" }, t.validation_note) : null,
  el("div", { class: "tile-link" }, "Rule, action and flagged rows")))));
}

// ---------------------------------------------------------------- drilldown (shared)
async function openDrill(segment, title) {
  const view = state.view;
  const section = $("drilldown");
  section.hidden = false;
  $("drill-market-wrap").hidden = view !== "roas_lenses";
  $("drill-title").textContent = title;
  $("drill-subtitle").textContent = "Loading…";
  $("drill-note").hidden = true;
  $("drill-note").replaceChildren();
  $("drill-kv").replaceChildren();
  $("drill-table").replaceChildren();
  $("drill-table").hidden = false;
  renderList($("drill-caveats"), []);
  const options = state.data?.options ?? {};
  const { data, isError } = await callTool("get_drilldown", { role: state.role, view, segment, options });
  if (state.auditOpen) void refreshAudit();
  if (isError || data.error) {
    state.drill = null;
    $("drill-subtitle").replaceChildren(errorBox(data));
    $("drill-table").hidden = true;
    return null;
  }
  state.drill = data;
  renderList($("drill-caveats"), data.caveats);
  section.scrollIntoView({ behavior: "smooth", block: "nearest" });
  return data;
}

function kvTable(pairs) {
  return el("table", { class: "kv" }, el("tbody", {}, ...pairs.filter(([, v]) => v !== undefined && v !== null)
    .map(([k, v]) => el("tr", {}, el("th", {}, k), el("td", {}, v)))));
}

function dataTable(cols, rows, fmt = {}, rowClass = () => undefined) {
  const isNum = (c) => rows.some((r) => typeof r[c] === "number");
  const numCols = new Set(cols.filter(isNum));
  return el("table", {},
    el("thead", {}, el("tr", {}, ...cols.map((c) => el("th", { class: numCols.has(c) ? "num" : undefined }, fmt[c]?.label ?? c)))),
    el("tbody", {}, ...rows.map((r) => el("tr", { class: rowClass(r) }, ...cols.map((c) => el("td",
      { class: numCols.has(c) ? "num" : undefined },
      fmt[c]?.f ? fmt[c].f(r[c]) : r[c] === null || r[c] === undefined ? "–" : String(r[c])))))));
}

// roas_lenses: weekly rows by market, with a market filter
async function openRoasDrilldown(channel) {
  const data = await openDrill({ channel }, `${channel}: weekly rows by market`);
  if (!data) return;
  const markets = [...new Set(data.result.rows.map((r) => r.market))];
  $("drill-market").replaceChildren(el("option", { value: "all" }, "All markets"), ...markets.map((m) => el("option", { value: m }, m)));
  renderRoasDrillTable();
}

function renderRoasDrillTable() {
  const data = state.drill;
  if (!data || data.view !== "roas_lenses") return;
  const market = $("drill-market").value || "all";
  const rows = data.result.rows.filter((r) => market === "all" || r.market === market);
  $("drill-subtitle").textContent = `${rows.length} of ${data.result.row_count} rows. Observable columns only: ` +
    `${data.definitions_used?.Columns ?? data.result.columns.join(", ")}.`;
  const cols = data.result.columns;
  const numeric = new Set(["spend_eur", "sessions", "platform_reported_revenue_eur"]);
  const fmt = (c, v) => (c === "sessions" ? fmtInt(v) : numeric.has(c) ? fmtEur(v) : v ?? "–");
  $("drill-table").replaceChildren(el("table", {},
    el("thead", {}, el("tr", {}, ...cols.map((c) => el("th", { class: numeric.has(c) ? "num" : undefined }, c)))),
    el("tbody", {}, ...rows.map((r) => el("tr", {}, ...cols.map((c) =>
      el("td", { class: numeric.has(c) ? "num" : undefined }, fmt(c, r[c])))))),
  ));
}

// business_health: totals for one market or one week
async function openBusinessDrill(kind, value) {
  const title = kind === "market" ? `${value}: totals for the full period` : `Week starting ${value}: totals`;
  const data = await openDrill({ [kind]: value }, title);
  if (!data) return;
  const r = data.result;
  $("drill-subtitle").textContent = `${r.market === "all" ? "All markets" : r.market}, all channels.`;
  $("drill-kv").replaceChildren(kvTable([
    ["Market", r.market === "all" ? "All markets" : r.market],
    ["Period", `${r.first_week} to ${r.last_week} (${r.weeks} week${r.weeks === 1 ? "" : "s"})`],
    ["Marketing spend (EUR, ex VAT)", fmtEur(r.spend_eur)],
    ["Orders", fmtInt(r.orders)],
    [`Net revenue (EUR, ${r.net_revenue_label})`, fmtEur(r.net_revenue_eur)],
    ["MER", fmtRatio(r.mer)],
  ]));
  $("drill-table").hidden = true;
}

// attribution_sensitivity: one model at 7, 30, 90 and 365 days
async function openAttributionDrill(model) {
  const ch = state.data?.result?.channel ?? "";
  const data = await openDrill({ model }, `${ch}, ${MODEL_LABEL[model] ?? model}: by lookback window`);
  if (!data) return;
  const r = data.result;
  $("drill-subtitle").textContent = `${r.label}. Break-even ROAS ${fmtRatio(r.break_even_roas)}.`;
  $("drill-table").replaceChildren(dataTable(["lookback_days", "model_roas", "ga4_lookback_supported"], r.by_lookback, {
    lookback_days: { label: "Lookback (days)" },
    model_roas: { label: "Model-credited ROAS", f: fmtRatio },
    ga4_lookback_supported: { label: "Lookback available in GA4", f: (v) => (v ? "Yes" : "No") },
  }));
}

// conversion_lag: blended payback at 30, 90 and 365 days
async function openLagDrill(path, day) {
  const name = LAG_STYLE[path]?.name ?? path;
  const data = await openDrill({ path, day }, `${name}, day ${day}: blended CAC and payback`);
  if (!data) return;
  const r = data.result;
  const hl = r.highlight_horizon_days;
  $("drill-subtitle").textContent = `${name} at day ${r.clicked.day}: ${fmtPct(r.clicked.share_visible)} of 365-day ` +
    `orders visible. ${r.note}` + (hl === null ? "" : ` Row for day ${hl} highlighted.`);
  if (hl === null) {
    $("drill-note").replaceChildren(el("strong", {}, `No payback figure at day ${r.clicked.day}`),
      `: the results file has payback at ${r.horizons.map((h) => h.horizon_days).join(", ")} days only. ` +
      "The table shows those three horizons; none is highlighted.");
    $("drill-note").hidden = false;
  }
  $("drill-kv").replaceChildren(kvTable([
    ["Spend on these cohorts' touches", `EUR ${fmtEur(r.payback_spend_eur, 0)}`],
    ["Payback ratio", r.payback_ratio_formula],
  ]));
  $("drill-table").replaceChildren(dataTable(["horizon_days", "orders", "blended_cac_eur", "cm_per_order_eur", "payback_ratio"],
    r.horizons, {
      horizon_days: { label: "Horizon (days)" },
      orders: { label: "Orders", f: fmtInt },
      blended_cac_eur: { label: "Blended CAC (EUR)", f: (v) => fmtEur(v, 0) },
      cm_per_order_eur: { label: "Contribution margin per order (EUR)", f: (v) => fmtEur(v, 0) },
      payback_ratio: { label: "Payback ratio", f: fmtRatio },
    }, (row) => (row.horizon_days === hl ? "hl" : undefined)));
}

// data_quality: the check's rule, action and flagged rows
async function openQualityDrill(number) {
  const data = await openDrill({ check: number }, `Check ${number}: rule, action and flagged rows`);
  if (!data) return;
  const r = data.result;
  $("drill-subtitle").replaceChildren(statusChip(r.overall_status.split(":")[0].trim()), " ",
    `${rowsFlagged(r.flagged_count, r.row_count_total)}.`);
  $("drill-kv").replaceChildren(kvTable([
    ["Check", r.check], ["File", el("code", {}, r.file)], ["What it checks", r.description],
    ["Method", r.method], ["Rule", r.rule], ["Action", r.action ?? r.action_note ?? "–"],
    ["Note", r.note], ["Overall status", r.overall_status],
    ["Validation", r.validation_note], ["Hidden columns", r.hidden_columns_note],
    ...Object.entries(r.column_notes ?? {}).map(([k, v]) => [`Column ${k}`, v]),
  ]));
  // check 01 with the leadership overlay: mark the two truth columns in the header
  const truthLabels = Object.fromEntries(r.columns.filter((c) => r.number === "01" && CHECK_01_TRUTH_COLUMNS.has(c))
    .map((c) => [c, { label: `${c} (validation only)` }]));
  $("drill-table").replaceChildren(dataTable(r.columns, r.flagged_rows, truthLabels));
}

function closeDrilldown() {
  state.drill = null;
  $("drilldown").hidden = true;
}

// ---------------------------------------------------------------- audit log
async function refreshAudit() {
  const limit = Number($("audit-limit").value) || 50;
  $("audit-subtitle").textContent = "Loading…";
  const { data, isError } = await callTool("get_audit_log", { limit });
  if (isError || data.error) {
    $("audit-subtitle").replaceChildren(errorBox(data));
    $("audit-table").replaceChildren();
    return;
  }
  const entries = data.result.entries;
  $("audit-subtitle").textContent = `${entries.length} most recent entries, newest first (timestamps in UTC). ` +
    "Every run, drilldown and refusal is logged; reading the log is not itself logged, so changing Rows or " +
    "clicking Refresh adds no entry. The log is readable without a role.";
  $("audit-table").replaceChildren(el("table", {},
    el("thead", {}, el("tr", {}, ...["Time (UTC)", "Role", "Action", "View", "Other inputs", "Result", "Message"]
      .map((h) => el("th", {}, h)))),
    el("tbody", {}, ...entries.map((e) => {
      const { view, ...rest } = e.inputs ?? {};
      const other = Object.fromEntries(Object.entries(rest).filter(([, v]) => v !== null && v !== undefined &&
        !(typeof v === "object" && Object.keys(v).length === 0)));
      return el("tr", {},
        el("td", { class: "mono nowrap" }, String(e.timestamp ?? "").replace("T", " ").replace(/\.\d+\+00:00$/, "")),
        el("td", {}, e.role ?? "–"), el("td", {}, e.action), el("td", {}, view ?? "–"),
        el("td", { class: "mono" }, Object.keys(other).length ? JSON.stringify(other) : "–"),
        el("td", {}, e.success ? "OK" : "Not OK"), el("td", {}, e.message));
    }))));
}

// ---------------------------------------------------------------- resize
// redraw only when the width changes (bar widths are set in pixels); height changes never trigger it
let resizeTimer = null;
let lastWidth = 0;
new ResizeObserver((entries) => {
  const w = Math.round(entries[0]?.contentRect?.width ?? 0);
  if (w === lastWidth) return;
  lastWidth = w;
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (state.data && CHART_VIEWS.has(state.data.view) && !$("view").hidden && !$("chart").hidden && window.Plotly) {
      renderView(state.data);
    }
  }, 150);
}).observe(document.body);

// ---------------------------------------------------------------- start
initControls();
app.connect().catch((e) => showError({ error: `Could not connect to the host: ${e?.message ?? e}`, access_denied: false }));
