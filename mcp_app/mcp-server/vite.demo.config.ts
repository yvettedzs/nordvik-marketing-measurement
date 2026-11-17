/**
 * Static demo build: `npm run build:demo` writes docs/demo/index.html (GitHub Pages).
 *
 * Same input as the MCP app build (mcp-app.html and src/mcp-app.js, unchanged). Two differences only:
 * - the import "@modelcontextprotocol/ext-apps" resolves to ../demo/shim.js, which answers the tool calls from
 *   docs/demo/recordings.json (made by ../demo/record_responses.py) instead of an MCP host;
 * - a permanent banner is added at the top of the page.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.resolve(HERE, "../../docs/demo");
const BANNER_TEXT = "Interactive demo: recorded responses from simulated data. Roles are switched in the browser; " +
  "this is not access control.";

const BANNER = `<div class="demo-banner" role="note" style="position:sticky;top:0;z-index:10;margin:0;` +
  `padding:8px 16px;background:#0b0b0b;color:#fcfcfb;font:600 13px/1.4 system-ui,-apple-system,'Segoe UI',` +
  `sans-serif;text-align:center">${BANNER_TEXT}</div>`;

function demoPage(): Plugin {
  return {
    name: "nordvik-demo-page",
    transformIndexHtml: {
      order: "pre",
      handler: (html) => html
        .replace("<title>Nordvik steering hub</title>", "<title>Nordvik steering hub: interactive demo</title>")
        .replace("<body>", `<body>\n  ${BANNER}`),
    },
    closeBundle() {
      // the page is built from mcp-app.html; GitHub Pages serves index.html for /demo/
      const built = path.join(OUT_DIR, "mcp-app.html");
      if (fs.existsSync(built)) fs.renameSync(built, path.join(OUT_DIR, "index.html"));
    },
  };
}

export default defineConfig({
  plugins: [demoPage(), viteSingleFile()],
  resolve: {
    alias: { "@modelcontextprotocol/ext-apps": path.resolve(HERE, "../demo/shim.js") },
  },
  build: {
    outDir: OUT_DIR,
    emptyOutDir: false,          // keeps recordings.json in docs/demo/
    rollupOptions: { input: path.resolve(HERE, "mcp-app.html") },
  },
});
