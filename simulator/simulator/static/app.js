// The simulated Echo Show: push-to-talk (browser speech recognition), spoken replies
// (browser speech synthesis), and the add-on's screen (MCP Apps, below). The conversation lives only in this page
// and goes to the server with each turn; reloading forgets it.

const $ = (id) => document.getElementById(id);
const say = $("say"), heard = $("heard"), app = $("app"), bar = $("bar");
const mic = $("mic"), text = $("text"), form = $("form"), status = $("status"), log = $("log");

let messages = [];
let busy = false;

const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const synth = window.speechSynthesis;

function setBar(state) { bar.className = `bar ${state || ""}`; }

function addLog(who, words) {
  const li = document.createElement("li");
  li.className = who === "you" ? "you" : "";
  li.textContent = `${who === "you" ? "You" : "Alexa"}: ${words}`;
  log.appendChild(li);
}

// Spoken, not shown: drop any markdown symbols a model slips in.
const plain = (s) => s.replace(/[*_#`>]+/g, "").replace(/^\s*[-•]\s+/gm, "").replace(/\s+/g, " ").trim();

function speak(words) {
  if (!synth) return;
  synth.cancel();
  const u = new SpeechSynthesisUtterance(plain(words));
  u.lang = "en-US";
  const voice = synth.getVoices().find((v) => v.lang === "en-US" && /female|samantha|aria|jenny/i.test(v.name));
  if (voice) u.voice = voice;
  u.onstart = () => setBar("speaking");
  u.onend = () => setBar("");
  synth.speak(u);
}

// ---- MCP Apps host (spec 2026-01-26) --------------------------------------------------
// The MCP server declares which tools show a screen (tool _meta.ui.resourceUri) and serves
// the screen's HTML; this page shows it in a sandboxed frame (an opaque origin: it can't
// reach this page, its storage or the network) and hands it the tool's input and result.
// One simplification: the spec's separate-origin proxy frame is replaced by that sandbox.
const PROTOCOL = "2026-01-26";
let screens = null; // {tools: {name: uri}, screens: {uri: {html, meta}}}
let shown = null; // the tool call on screen
let frame = null;

async function loadScreens() {
  if (!screens) {
    const res = await fetch("/api/screens");
    if (res.ok) screens = await res.json();
  }
  return screens;
}

// The latest call to a tool that has a screen: its input and its MCP result.
function latestScreenCall() {
  const uses = new Map();
  for (const m of messages) for (const b of m.content) if (b.toolUse) uses.set(b.toolUse.toolUseId, b.toolUse);
  for (let i = messages.length - 1; i >= 0; i--) {
    for (const b of messages[i].content) {
      const r = b.toolResult;
      const use = r && uses.get(r.toolUseId);
      if (!use || r.status === "error" || !screens?.tools[use.name]) continue;
      const content = r.content.filter((c) => c.text !== undefined).map((c) => ({ type: "text", text: c.text }));
      let structuredContent = r.content.find((c) => c.json)?.json;
      if (!structuredContent) try { structuredContent = JSON.parse(content[0]?.text); } catch { /* text only */ }
      return { id: use.toolUseId, uri: screens.tools[use.name], name: use.name, input: use.input, result: { content, structuredContent } };
    }
  }
  return null;
}

// What the view may load: only what the server declared (here, nothing outside the page).
function cspFor(meta) {
  const csp = meta?.csp ?? {};
  const list = (domains) => (domains ?? []).join(" ");
  return [
    "default-src 'none'",
    `script-src 'unsafe-inline' ${list(csp.resourceDomains)}`,
    `style-src 'unsafe-inline' ${list(csp.resourceDomains)}`,
    `img-src data: ${list(csp.resourceDomains)}`,
    `font-src ${list(csp.resourceDomains) || "'none'"}`,
    `connect-src ${list(csp.connectDomains) || "'none'"}`,
    `frame-src ${list(csp.frameDomains) || "'none'"}`,
    "base-uri 'none'",
    "object-src 'none'",
  ].join("; ");
}

function post(msg) { frame?.contentWindow?.postMessage({ jsonrpc: "2.0", ...msg }, "*"); }

window.addEventListener("message", (e) => {
  if (!frame || e.source !== frame.contentWindow) return;
  const m = e.data;
  if (!m || m.jsonrpc !== "2.0" || !m.method) return;
  if (m.method === "ui/initialize") {
    const box = app.getBoundingClientRect();
    post({ id: m.id, result: {
      protocolVersion: PROTOCOL,
      hostInfo: { name: "unclaimed-alexa-simulator", version: "1" },
      hostCapabilities: { openLinks: {} },
      hostContext: {
        theme: "dark", displayMode: "inline", platform: "web", locale: "en-US",
        containerDimensions: { width: Math.round(box.width), height: Math.round(box.height) },
        deviceCapabilities: { touch: "ontouchstart" in window, hover: matchMedia("(hover: hover)").matches },
        toolInfo: { tool: { name: shown.name } },
      },
    } });
  } else if (m.method === "ui/notifications/initialized") {
    post({ method: "ui/notifications/tool-input", params: { arguments: shown.input } });
    post({ method: "ui/notifications/tool-result", params: shown.result });
  } else if (m.method === "ui/open-link" && m.id !== undefined) {
    const url = String(m.params?.url ?? "");
    if (url.startsWith("https://")) window.open(url, "_blank", "noopener");
    post({ id: m.id, result: {} });
  } else if (m.id !== undefined) {
    post({ id: m.id, error: { code: -32601, message: `${m.method} isn't supported by this host` } });
  }
});

async function showScreen() {
  await loadScreens().catch(() => null);
  const call = screens && latestScreenCall();
  if (!call || call.id === shown?.id) return;
  shown = call;
  const screen = screens.screens[call.uri];
  frame = document.createElement("iframe");
  frame.title = "Unclaimed";
  frame.setAttribute("sandbox", "allow-scripts");
  frame.srcdoc = screen.html.replace("<head>", `<head><meta http-equiv="Content-Security-Policy" content="${cspFor(screen.meta)}">`);
  app.replaceChildren(frame);
  $("screen").classList.add("has-app");
}

function clearScreen() {
  shown = frame = null;
  app.replaceChildren();
  $("screen").classList.remove("has-app");
}

async function send(words) {
  words = words.trim();
  if (!words || busy) return;
  busy = true;
  mic.disabled = true;
  heard.textContent = `“${words}”`;
  addLog("you", words);
  setBar("thinking");
  const started = performance.now();
  try {
    const res = await fetch("/api/turn", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text: words, messages }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Something went wrong.");
    messages = data.messages;
    say.textContent = data.reply;
    addLog("alexa", data.reply);
    showScreen();
    const t = data.timing;
    status.textContent = `Turn ${((performance.now() - started) / 1000).toFixed(1)} s · model ${(t.model_ms / 1000).toFixed(1)} s · tools ${(t.tools_ms / 1000).toFixed(1)} s`;
    speak(data.reply);
  } catch (e) {
    say.textContent = e.message;
    setBar("");
  } finally {
    busy = false;
    mic.disabled = false;
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const words = text.value;
  text.value = "";
  send(words);
});

if (Recognition) {
  const rec = new Recognition();
  rec.lang = "en-US";
  rec.interimResults = true;
  let final = "";
  rec.onresult = (e) => {
    let interim = "";
    for (const r of e.results) (r.isFinal ? (final = r[0].transcript) : (interim += r[0].transcript));
    heard.textContent = interim || final;
  };
  rec.onend = () => {
    mic.classList.remove("on");
    if (!busy) setBar("");
    if (final) send(final);
    final = "";
  };
  mic.addEventListener("click", () => {
    if (mic.classList.contains("on")) return rec.stop();
    synth?.cancel();
    mic.classList.add("on");
    setBar("listening");
    rec.start();
  });
} else {
  mic.disabled = true;
  mic.title = "Voice input needs Chrome or Edge; type instead.";
}

$("reset").addEventListener("click", () => {
  messages = [];
  synth?.cancel();
  clearScreen();
  log.replaceChildren();
  heard.textContent = "";
  status.textContent = "";
  say.innerHTML = "Tap the mic and say <em>“Alexa, open Unclaimed”</em>, or type below.";
});
