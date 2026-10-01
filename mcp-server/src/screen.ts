// The Echo Show screen (MCP Apps): one self-contained HTML view for get_results and get_plan.
// The QR library is inlined here so the view loads nothing from outside (Alexa blocks it).
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

export const SCREEN_URI = "ui://unclaimed/screen";
export const SCREEN_MIME = "text/html;profile=mcp-app"; // MCP Apps spec 2026-01-26

const require = createRequire(import.meta.url);
export const screenHtml = readFileSync(new URL("../ui/screen.html", import.meta.url), "utf8")
  .replace("/*QRCODE*/", () => readFileSync(require.resolve("qrcode-generator"), "utf8"));
