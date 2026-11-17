/**
 * Nordvik steering hub: MCP server (TypeScript, Streamable HTTP on port 3001).
 * ALL DATA IS SIMULATED (fictional brand "Nordvik Outdoor").
 *
 * Four tools (list_views, run_view, get_drilldown, get_audit_log) forward to the Python API on port 5001,
 * which checks access, calls the existing metric code and writes the audit log. This server computes nothing.
 * run_view opens the dashboard resource ui://nordvik/steering-hub (dist/mcp-app.html, built by `npm run build`).
 *
 * Start:  npm run build && npm start     (the Python API must be running: .venv\Scripts\python.exe mcp_app/api.py)
 */
import fs from "node:fs/promises";
import path from "node:path";

import cors from "cors";
import type { Request, Response } from "express";
import { z } from "zod";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { createMcpExpressApp } from "@modelcontextprotocol/sdk/server/express.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import { RESOURCE_MIME_TYPE, registerAppResource, registerAppTool } from "@modelcontextprotocol/ext-apps/server";

const HOST = "127.0.0.1";
const PORT = Number(process.env.PORT ?? 3001);
const API_URL = process.env.NORDVIK_API_URL ?? "http://127.0.0.1:5001";
const RESOURCE_URI = "ui://nordvik/steering-hub";
const PLOTLY_ORIGIN = "https://cdn.plot.ly";
const HTML_PATH = path.join(import.meta.dirname, "dist", "mcp-app.html");
const START_API = String.raw`.venv\Scripts\python.exe mcp_app/api.py`;

const READ_ONLY = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false };
const ROLE_HELP = "Role id: country_manager_de, performance_marketing or leadership. Roles are chosen by the caller " +
  "(no login); the API refuses views and markets the role may not see.";
const VIEW_HELP = "View id: roas_lenses, business_health, attribution_sensitivity, conversion_lag or data_quality.";
const SIMULATED = "All data is simulated (fictional brand Nordvik Outdoor).";

// ---------------------------------------------------------------- Python API bridge
async function callApi(method: "GET" | "POST", route: string, body?: unknown): Promise<CallToolResult> {
  let res: globalThis.Response;
  try {
    res = await fetch(API_URL + route, {
      method,
      headers: body === undefined ? undefined : { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    const err = { error: `Python API not reachable at ${API_URL}. Start it from the repo root: ${START_API}`,
                  access_denied: false };
    return { content: [{ type: "text", text: JSON.stringify(err) }], structuredContent: err, isError: true };
  }
  let json: Record<string, unknown>;
  try {
    json = (await res.json()) as Record<string, unknown>;
  } catch {
    json = { error: `Python API returned a non-JSON reply (HTTP ${res.status}).`, access_denied: false };
  }
  return { content: [{ type: "text", text: JSON.stringify(json) }], structuredContent: json, isError: !res.ok };
}

// ---------------------------------------------------------------- MCP server (a fresh one per request)
export function createServer(): McpServer {
  const server = new McpServer({ name: "nordvik-steering-hub", version: "0.1.0" });

  server.registerTool(
    "list_views",
    {
      title: "List steering-hub views",
      description: `Views a role may open, with their options and drilldowns. ${ROLE_HELP} ${SIMULATED}`,
      inputSchema: { role: z.string().describe(ROLE_HELP) },
      annotations: READ_ONLY,
    },
    async ({ role }) => callApi("GET", `/api/views?role=${encodeURIComponent(role)}`),
  );

  registerAppTool(
    server,
    "run_view",
    {
      title: "Open a steering-hub view",
      description:
        `Run one view for a role and show it in the Nordvik steering hub dashboard. ${VIEW_HELP} ` +
        "Options per view: roas_lenses {overlay: boolean, leadership only}. Every number comes from the repo's " +
        `agreed metric code; the response states the definitions, sources and caveats. ${SIMULATED}`,
      inputSchema: {
        role: z.string().describe(ROLE_HELP),
        view: z.string().describe(VIEW_HELP),
        options: z.record(z.string(), z.unknown()).optional().describe("View options, e.g. {\"overlay\": true}"),
      },
      annotations: READ_ONLY,
      _meta: { ui: { resourceUri: RESOURCE_URI } },
    },
    async ({ role, view, options }) => callApi("POST", "/api/run", { role, view, options: options ?? {} }),
  );

  server.registerTool(
    "get_drilldown",
    {
      title: "Drill into a view",
      description:
        `Detail behind one segment of a view. ${VIEW_HELP} Segment per view: roas_lenses {channel}. ${SIMULATED}`,
      inputSchema: {
        role: z.string().describe(ROLE_HELP),
        view: z.string().describe(VIEW_HELP),
        segment: z.record(z.string(), z.unknown()).describe("The clicked segment, e.g. {\"channel\": \"Meta\"}"),
        options: z.record(z.string(), z.unknown()).optional().describe("The view's options"),
      },
      annotations: READ_ONLY,
    },
    async ({ role, view, segment, options }) =>
      callApi("POST", "/api/drilldown", { role, view, segment, options: options ?? {} }),
  );

  server.registerTool(
    "get_audit_log",
    {
      title: "Read the audit log",
      description: "Most recent audit entries (runs, drilldowns and refusals), newest first. " +
        "Keys: timestamp, role, action, inputs, success, message.",
      inputSchema: { limit: z.number().int().min(1).max(1000).optional().describe("1 to 1000, default 50") },
      annotations: READ_ONLY,
    },
    async ({ limit }) => callApi("GET", `/api/audit?limit=${limit ?? 50}`),
  );

  registerAppResource(
    server,
    "Nordvik steering hub",
    RESOURCE_URI,
    { description: "Role-based dashboard over the Nordvik metrics (simulated data)." },
    async () => {
      let html: string;
      try {
        html = await fs.readFile(HTML_PATH, "utf-8");
      } catch {
        throw new Error(`Dashboard not built: ${HTML_PATH} is missing. Run \`npm run build\` in mcp_app/mcp-server.`);
      }
      return {
        contents: [{
          uri: RESOURCE_URI,
          mimeType: RESOURCE_MIME_TYPE,
          text: html,
          _meta: { ui: { csp: { resourceDomains: [PLOTLY_ORIGIN] } } },
        }],
      };
    },
  );

  return server;
}

// ---------------------------------------------------------------- HTTP (stateless: new server + transport per request)
const app = createMcpExpressApp({ host: HOST });
app.use(cors({ exposedHeaders: ["Mcp-Session-Id"] }));

app.post("/mcp", async (req: Request, res: Response) => {
  const server = createServer();
  const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
  res.on("close", () => {
    void transport.close();
    void server.close();
  });
  try {
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
  } catch (e) {
    console.error("MCP request failed:", e);
    if (!res.headersSent) {
      res.status(500).json({ jsonrpc: "2.0", error: { code: -32603, message: "Internal server error" }, id: null });
    }
  }
});

const methodNotAllowed = (_req: Request, res: Response) => {
  res.status(405).json({ jsonrpc: "2.0", error: { code: -32000, message: "Method not allowed (stateless server)." },
                         id: null });
};
app.get("/mcp", methodNotAllowed);
app.delete("/mcp", methodNotAllowed);

app.listen(PORT, HOST, (err?: Error) => {
  if (err) {
    console.error(`Could not listen on ${HOST}:${PORT}:`, err.message);
    process.exit(1);
  }
  console.log(`Nordvik steering hub MCP server: http://${HOST}:${PORT}/mcp  (Python API: ${API_URL})`);
});
