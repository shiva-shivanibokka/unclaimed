// The simulated Echo Show. Hands-free after the first tap (browsers allow the mic and sound
// only after one): the mic opens by itself each time Alexa finishes speaking (Alexa's
// follow-up mode), and between conversations it waits for the wake word ("Alexa" or "Hey
// Alexa", alone or before a request), until you tap it to mute. Alexa
// speaks with Amazon Polly (the server sends the audio with each reply), falling back to the
// browser's voice. The add-on's screen is hosted below (MCP Apps). The conversation lives
// only in this page and goes to the server with each turn; reloading forgets it.

const $ = (id) => document.getElementById(id);
const screenEl = $("screen"), say = $("say"), heard = $("heard"), app = $("app"), caption = $("caption");
const mic = $("mic"), mode = $("mode"), text = $("text"), form = $("form"), status = $("status"), log = $("log");

const OPEN = "Alexa, open Unclaimed";
const WAKE = /\b(?:hey\s+)?alexa\b[,.!?]?\s*/i;
// Said to the device, not to the add-on: handled here, like on an Echo Show.
const DEVICE = [
  { words: /^(go )?back( to (the )?(results|previous screen|last screen))?[.!]?$|^previous screen[.!]?$/i, run: () => back() },
  { words: /^(stop|cancel|be quiet)[.!]?$/i, run: () => { quiet(); wake(); } },
];
const MAX_SILENT_LISTENS = 4; // ~8 s each: about half a minute of silence, then it waits for "Alexa"

let messages = [];
let busy = false;
let conversation = 0; // bumped by "New conversation", so a reply still on its way is dropped
let handsFree = false;
let silent = 0;

// ---- States: idle | listening | thinking | speaking (the glow and the mic follow) ----
const LABELS = { idle: "Tap to talk", listening: "Listening…", thinking: "Thinking…", speaking: "Speaking…" };
function setState(s) {
  screenEl.dataset.state = s;
  mode.textContent = s === "idle" && handsFree ? "Say “Alexa” anytime" : LABELS[s];
  mic.classList.toggle("on", s === "listening");
}
function setHandsFree(on) {
  handsFree = on;
  silent = 0;
  if (!on) stopListening();
  setState(screenEl.dataset.state === "listening" && !on ? "idle" : screenEl.dataset.state);
}
function view(v) { screenEl.dataset.view = v; }

function addLog(who, words) {
  const li = document.createElement("li");
  if (who === "you") li.className = "you";
  li.textContent = words;
  log.appendChild(li);
  log.scrollTop = log.scrollHeight;
}

setInterval(function tick() {
  $("clock").textContent = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return tick;
}(), 15000);

// ---- Voice out: Polly audio, else the browser's voice; the glow follows the loudness ----
let audioCtx = null, analyser = null, player = null;
const synth = window.speechSynthesis;

function unlockAudio() { // browsers allow sound only after a tap: called from the first one
  if (audioCtx) return;
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return;
  audioCtx = new Ctx();
  analyser = audioCtx.createAnalyser();
  analyser.fftSize = 256;
  analyser.connect(audioCtx.destination);
}

function followLoudness() {
  if (!analyser || screenEl.dataset.state !== "speaking") return screenEl.style.setProperty("--level", 0);
  const data = new Uint8Array(analyser.frequencyBinCount);
  analyser.getByteTimeDomainData(data);
  let peak = 0;
  for (const v of data) peak = Math.max(peak, Math.abs(v - 128));
  screenEl.style.setProperty("--level", Math.min(1, peak / 64).toFixed(2));
  requestAnimationFrame(followLoudness);
}

function quiet() {
  if (player) { player.onended = player.onerror = null; player.pause(); player = null; }
  synth?.cancel();
  if (screenEl.dataset.state === "speaking") setState("idle");
}

function spoken() { // Alexa finished: listen again if hands-free
  player = null;
  setState("idle");
  if (handsFree) listen();
}

// `clips`: the reply's sentences as MP3 (base64), played one after another.
function speak(words, clips) {
  quiet();
  setState("speaking");
  if (!clips?.length) return speakInBrowser(words);
  const [clip, ...rest] = clips;
  player = new Audio(`data:audio/mpeg;base64,${clip}`);
  if (audioCtx) {
    audioCtx.resume();
    audioCtx.createMediaElementSource(player).connect(analyser);
  }
  player.onplay = followLoudness;
  player.onended = rest.length ? () => speak(words, rest) : spoken;
  player.onerror = spoken;
  player.play().catch(() => speakInBrowser(words));
}

function speakInBrowser(words) {
  if (!synth) return spoken();
  const u = new SpeechSynthesisUtterance(words);
  u.lang = "en-US";
  const voice = synth.getVoices().find((v) => v.lang === "en-US" && /natural|aria|jenny|samantha|female/i.test(v.name));
  if (voice) u.voice = voice;
  u.onend = spoken;
  synth.speak(u);
}

// ---- Voice in: browser speech recognition, reopened after every reply when hands-free ----
const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null, listening = false, waking = false, final = "";

if (Recognition) {
  rec = new Recognition();
  rec.lang = "en-US";
  rec.interimResults = true;
  rec.onresult = (e) => {
    let interim = "";
    final = "";
    for (const r of e.results) (r.isFinal ? (final += r[0].transcript) : (interim += r[0].transcript));
    if (waking) return; // waiting for the wake word: nothing else shows
    heard.textContent = interim || final;
    if (screenEl.dataset.view === "app") caption.textContent = interim || final;
  };
  rec.onend = () => {
    listening = false;
    const words = final.trim();
    final = "";
    if (waking) {
      waking = false;
      const m = words.match(WAKE);
      if (m) { silent = 0; return send(words.slice(m.index)); } // "Alexa" alone listens; with a request, it's sent
      return wake(); // anything else is ignored: keep waiting
    }
    if (words) { silent = 0; return send(words); }
    // Silence: keep listening for a while, then wait for the wake word.
    if (handsFree && !busy && screenEl.dataset.state === "listening" && ++silent < MAX_SILENT_LISTENS) return listen();
    if (screenEl.dataset.state === "listening") { setState("idle"); wake(); }
  };
  rec.onerror = (e) => {
    if (e.error === "not-allowed" || e.error === "service-not-allowed") {
      setHandsFree(false);
      mode.textContent = "Microphone blocked: type instead";
    }
  };
} else {
  mic.disabled = true;
  mic.title = "Voice input needs Chrome or Edge; type instead.";
  mode.textContent = "Type below (voice needs Chrome or Edge)";
}

function listen() {
  if (!rec || busy || listening) return;
  quiet();
  setState("listening");
  try { rec.start(); listening = true; } catch { /* already starting */ }
}
// Wait for "Alexa" (hands-free only). Recognition ends after each phrase or a few seconds
// of silence and is restarted, until a turn starts or the mic is muted.
function wake() {
  if (!rec || !handsFree || busy || listening) return;
  setState("idle");
  waking = true;
  try { rec.start(); listening = true; } catch { waking = false; }
}
function stopListening() {
  final = ""; // words caught just before muting aren't sent
  waking = false;
  if (rec && listening) rec.abort();
  listening = false;
}

// ---- MCP Apps host (spec 2026-01-26) --------------------------------------------------
// The MCP server declares which tools show a screen (tool _meta.ui.resourceUri) and serves
// the screen's HTML; this page shows it in a sandboxed frame (an opaque origin: it can't
// reach this page or its storage, and its content-security policy allows only the domains
// the server declared) and hands it the tool's input and result. One simplification: the
// spec's separate-origin proxy frame is replaced by that sandbox.
const PROTOCOL = "2026-01-26";
let screens = null; // {tools: {name: uri}, screens: {uri: {html, meta}}}
let shown = null; // the tool call on screen
let frame = null;
let lastId = null; // the newest screen call shown, so going back doesn't bring it again
const history = []; // screens shown, for "go back" (like the device's back)

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
  // Only well-formed https origins go into the policy: anything else could rewrite it.
  const origin = /^https:\/\/[a-z0-9.-]+(:\d{1,5})?$/i;
  const list = (domains) => (Array.isArray(domains) ? domains : []).filter((d) => origin.test(d)).join(" ");
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
        toolInfo: { id: shown.id, tool: { name: shown.name } },
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

// Before a screen goes away the view gets ui/resource-teardown (spec: SHOULD), briefly.
async function teardown() {
  if (!frame) return;
  const old = frame;
  const done = new Promise((resolve) => {
    const onReply = (e) => { if (e.source === old.contentWindow && e.data?.id === "teardown") resolve(); };
    window.addEventListener("message", onReply);
    setTimeout(resolve, 300);
  });
  post({ id: "teardown", method: "ui/resource-teardown", params: {} });
  await done;
}

async function render(call) {
  await teardown();
  shown = call;
  if (!call) {
    frame = null;
    app.replaceChildren();
    view("talk");
  } else {
    const screen = screens.screens[call.uri];
    frame = document.createElement("iframe");
    frame.title = "Unclaimed";
    frame.setAttribute("sandbox", "allow-scripts");
    view("app"); // visible first, so the view lays out at its real size
    frame.srcdoc = screen.html.replace("<head>", `<head><meta http-equiv="Content-Security-Policy" content="${cspFor(screen.meta)}">`);
    app.replaceChildren(frame);
  }
  $("back").hidden = !call;
}

async function showScreen() {
  await loadScreens().catch(() => null);
  const call = screens && latestScreenCall();
  if (!call || call.id === lastId) return;
  lastId = call.id;
  history.push(call);
  await render(call);
}

async function back() {
  if (!history.length) return;
  history.pop();
  await render(history.at(-1) ?? null);
  if (handsFree) listen();
}

// ---- A turn ----
async function send(words) {
  // "Alexa, ..." / "Hey Alexa, ...": the wake word isn't part of the request ("Alexa" alone: listen).
  const request = words.trim().replace(new RegExp(`^${WAKE.source}`, "i"), "").trim();
  if (busy) return;
  if (!request) return words.trim() ? listen() : undefined;
  words = request;
  const command = DEVICE.find((c) => c.words.test(words));
  if (command) { heard.textContent = ""; caption.textContent = ""; return command.run(); }
  stopListening();
  quiet();
  busy = true;
  if (screenEl.dataset.view !== "app") view("talk");
  heard.textContent = words;
  say.textContent = "";
  addLog("you", words);
  setState("thinking");
  const started = performance.now();
  const mine = conversation;
  try {
    const res = await fetch("/api/turn", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text: words, messages }),
    });
    const data = await res.json();
    if (mine !== conversation) return; // the conversation was reset meanwhile
    if (!res.ok) throw new Error(data.detail || "Something went wrong.");
    messages = data.messages;
    say.textContent = caption.textContent = data.reply;
    addLog("alexa", data.reply);
    await showScreen();
    const t = data.timing;
    status.textContent = `Turn ${((performance.now() - started) / 1000).toFixed(1)} s · model ${(t.model_ms / 1000).toFixed(1)} s · tools ${(t.tools_ms / 1000).toFixed(1)} s`;
    busy = false;
    speak(data.reply, data.audio);
  } catch (e) {
    if (mine !== conversation) return;
    busy = false;
    say.textContent = caption.textContent = e.message;
    setState("idle");
  }
}

// The first tap turns on sound and the mic (browsers require one); after that, hands-free.
function begin() {
  unlockAudio();
  setHandsFree(Boolean(rec));
}

$("start").addEventListener("click", () => { begin(); send(OPEN); });

// The mic: a tap while listening mutes; any other tap listens right away (cutting Alexa
// off) and turns hands-free on.
mic.addEventListener("click", () => {
  unlockAudio();
  if (screenEl.dataset.state === "listening") return setHandsFree(false);
  stopListening(); // e.g. waiting for the wake word
  setHandsFree(true);
  listen();
});

form.addEventListener("submit", (e) => {
  e.preventDefault();
  unlockAudio();
  const words = text.value;
  text.value = "";
  send(words);
});

for (const b of document.querySelectorAll(".try")) b.addEventListener("click", () => { unlockAudio(); send(b.textContent); });
$("back").addEventListener("click", back);

$("reset").addEventListener("click", async () => {
  conversation++;
  busy = false;
  messages = [];
  history.length = 0;
  lastId = null;
  quiet();
  setHandsFree(false);
  await render(null);
  delete screenEl.dataset.view;
  $("back").hidden = true;
  log.replaceChildren();
  heard.textContent = say.textContent = caption.textContent = status.textContent = "";
  setState("idle");
});

setState("idle");
