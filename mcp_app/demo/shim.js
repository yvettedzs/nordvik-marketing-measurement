/**
 * Static demo stand-in for `App` from @modelcontextprotocol/ext-apps. ALL DATA IS SIMULATED.
 *
 * The demo build (mcp-server/vite.demo.config.ts) maps that import to this file, so the dashboard code
 * (mcp-app.html, src/mcp-app.js) runs unchanged. Instead of an MCP host, this file answers the four tool calls
 * from recordings.json, which mcp_app/demo/record_responses.py records from the real API:
 * - list_views, run_view, get_drilldown: the recorded reply for exactly these arguments;
 * - access: checked here against the recorded roles table, in the API's order (view, market lock, overlay);
 *   a refusal returns the API's recorded refusal. This runs in the browser: it is not access control;
 * - get_audit_log: an in-memory log in the API's format, cleared on reload.
 * Nothing is computed: a call that was not recorded gets an error saying so.
 */

export const RECORDINGS_URL = "recordings.json";
const DEFAULT_OPEN = { role: "performance_marketing", view: "roas_lenses" };
const OVERLAY_VIEWS = new Set(["roas_lenses", "data_quality"]);

/** Same string as call_key() in record_responses.py: keys sorted at every level, no spaces. */
export function callKey(name, args) {
  return JSON.stringify(sortKeys({ name, arguments: args }));
}

function sortKeys(v) {
  if (Array.isArray(v)) return v.map(sortKeys);
  if (v && typeof v === "object") {
    return Object.fromEntries(Object.keys(v).sort().map((k) => [k, sortKeys(v[k])]));
  }
  return v;
}

export function unpack(rec, entry) {
  const [status, fields] = entry;
  return { status, body: Object.fromEntries(fields.map(([field, i]) => [field, rec.parts[i]])) };
}

const blank = (v) => v === undefined || v === null || String(v).trim() === "";

/** The refusal case for a run_view or get_drilldown call, or null when the role may make it. */
export function refusalCase(rec, args) {
  const role = rec.roles.find((r) => r.id === args.role);
  if (!role) return null;                                      // unknown role: not recorded
  const options = args.options ?? {};
  if (!role.views.includes(args.view)) return `view|${role.id}|${args.view}`;
  if (role.market_lock && args.view === "business_health" && !blank(options.market) &&
      String(options.market).trim().toUpperCase() !== role.market_lock) {
    return `market|${role.id}|${String(options.market).trim()}`;
  }
  if (!role.overlay_allowed && OVERLAY_VIEWS.has(args.view) && options.overlay === true) {
    return `overlay|${role.id}|${args.view}`;
  }
  return null;
}

export class Recordings {
  constructor(rec) {
    this.rec = rec;
    this.audit = [];
  }

  log(role, action, inputs, success, message) {
    this.audit.push({ timestamp: new Date().toISOString().replace("Z", "+00:00"), role, action, inputs, success, message });
  }

  /** The reply to one tool call: { status, body }. */
  answer(name, args) {
    if (name === "get_audit_log") {
      const limit = Number(args.limit ?? 50);
      const entries = this.audit.slice(-limit).reverse();
      return { status: 200, body: { data_origin: "simulated", sources: ["this browser tab (demo audit log)"],
        result: { entries, count: entries.length, order: "newest first" } } };
    }
    const action = name;
    const inputs = name === "run_view" ? { view: args.view, options: args.options }
      : name === "get_drilldown" ? { view: args.view, segment: args.segment, options: args.options } : {};
    const logged = name === "run_view" || name === "get_drilldown";
    if (logged) {
      const refusal = refusalCase(this.rec, args);
      if (refusal) {
        const entry = this.rec.refusals[refusal];
        const out = entry ? unpack(this.rec, entry) : notRecorded(name, args);
        this.log(args.role, action, inputs, false, out.body.error);
        return out;
      }
    }
    const entry = this.rec.calls[callKey(name, args)];
    const out = entry ? unpack(this.rec, entry) : notRecorded(name, args);
    if (logged) this.log(args.role, action, inputs, out.status === 200, out.status === 200 ? `ok: ${args.view}` : out.body.error);
    return out;
  }
}

function notRecorded(name, args) {
  return { status: 404, body: { error: `This demo has no recorded reply for ${name} ${JSON.stringify(args)}. ` +
    "It can only replay calls the dashboard makes from its own menus.", access_denied: false } };
}

function toolResult({ status, body }) {
  return { content: [{ type: "text", text: JSON.stringify(body) }], structuredContent: body, isError: status !== 200 };
}

/** The opening call, as Claude would send it: ?role=…&view=…&options={…} in the page URL, else the default. */
export function openingArgs(search) {
  const q = new URLSearchParams(search);
  const args = { role: q.get("role") || DEFAULT_OPEN.role, view: q.get("view") || DEFAULT_OPEN.view, options: {} };
  if (q.get("options")) {
    try {
      const o = JSON.parse(q.get("options"));
      if (o && typeof o === "object" && !Array.isArray(o)) args.options = o;
    } catch { /* ignore a malformed options parameter */ }
  }
  return args;
}

export class App {
  constructor(_info) {
    this.ontoolinput = null;
    this.ontoolresult = null;
    this.recordings = null;
  }

  async connect() {
    const res = await fetch(new URL(RECORDINGS_URL, document.baseURI));
    if (!res.ok) throw new Error(`could not load ${RECORDINGS_URL} (HTTP ${res.status})`);
    this.recordings = new Recordings(await res.json());
    const args = openingArgs(window.location.search);
    this.ontoolinput?.({ arguments: args });
    this.ontoolresult?.(toolResult(this.recordings.answer("run_view", args)));
  }

  async callServerTool({ name, arguments: args }) {
    if (!this.recordings) throw new Error("recordings not loaded");
    return toolResult(this.recordings.answer(name, args ?? {}));
  }
}
