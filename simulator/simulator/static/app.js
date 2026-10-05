// The simulated Echo Show, talking with Alexa live: the microphone streams to Amazon Nova 2
// Sonic (through the server, /api/live) and Alexa's voice streams back, so she answers as
// soon as you finish and you can cut in while she talks. Hands-free after the first tap
// (browsers allow the mic and sound only after one). After some quiet the conversation rests
// (the server closes it: a live conversation costs by the minute) and the device waits for
// the wake word ("Alexa" or "Hey Alexa", alone or before a request), then carries on where
// it left off. The add-on's screen is hosted below (MCP Apps). The conversation lives only
// in this page; reloading forgets it.

const $ = (id) => document.getElementById(id);
const screenEl = $("screen"), say = $("say"), heard = $("heard"), app = $("app"), caption = $("caption");
const mic = $("mic"), mode = $("mode"), text = $("text"), form = $("form"), status = $("status"), log = $("log");

const OPEN = "Alexa, open Unclaimed";
const WAKE = /\b(?:hey\s+)?alexa\b[,.!?]?\s*/i;
const IN_RATE = 16000, OUT_RATE = 24000; // the server's audio formats (16-bit PCM, mono)
const FRAME = 512; // microphone samples per message: 32 ms
const MAX_SAID = 40; // lines of conversation carried into the next one after a rest

let ws = null; // the live conversation, when one is open
let handsFree = false;
let household = null; // the latest household draft (from the server), to carry on after a rest
const said = []; // the conversation so far, [{role, text}], ditto
let asked = 0; // when the person finished speaking, to time Alexa's answer

// ---- States: idle | listening | thinking | speaking (the glow and the mic follow) ----
const LABELS = { idle: "Tap to talk", listening: "Listening…", thinking: "Thinking…", speaking: "Speaking…" };
function setState(s) {
  screenEl.dataset.state = s;
  mode.textContent = s === "idle" && handsFree && rec ? "Say “Alexa” anytime" : LABELS[s];
  mic.classList.toggle("on", Boolean(ws));
}
function view(v) { screenEl.dataset.view = v; }

function addLog(who, words) {
  said.push({ role: who === "you" ? "user" : "assistant", text: words });
  if (said.length > MAX_SAID) said.shift();
  const li = document.createElement("li");
  if (who === "you") li.className = "you";
  li.textContent = words;
  log.appendChild(li);
  log.scrollTop = log.scrollHeight;
}

function tick() {
  $("clock").textContent = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}
tick();
setInterval(tick, 15000);

// ---- Audio: the microphone in (resampled to 16 kHz in a worklet), Alexa's voice out ----
// The worklet averages each run of input samples into one output sample (a simple
// low-pass), and with no microphone it sends silence, so typed words still work.
const WORKLET = `
registerProcessor("mic", class extends AudioWorkletProcessor {
  constructor({ processorOptions: o }) {
    super();
    this.step = sampleRate / o.rate;
    this.size = o.frame;
    this.frame = new Int16Array(this.size);
    this.n = this.sum = this.count = this.pos = 0;
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    const len = ch ? ch.length : 128;
    for (let i = 0; i < len; i++) {
      this.sum += ch ? ch[i] : 0;
      this.count++;
      if (++this.pos >= this.step) {
        this.pos -= this.step;
        this.frame[this.n++] = Math.max(-1, Math.min(1, this.sum / this.count)) * 0x7fff;
        this.sum = this.count = 0;
        if (this.n === this.size) {
          this.port.postMessage(this.frame.buffer, [this.frame.buffer]);
          this.frame = new Int16Array(this.size);
          this.n = 0;
        }
      }
    }
    return true;
  }
});`;

let ctx = null, analyser = null, hasMic = false;
const playing = new Set(); // Alexa's voice: chunks scheduled one after another
let playAt = 0;

// Called from the first tap: sound, the microphone (if allowed) and the worklet.
async function setupAudio() {
  if (ctx) return ctx.resume();
  const Ctx = window.AudioContext || window.webkitAudioContext;
  ctx = new Ctx();
  analyser = ctx.createAnalyser();
  analyser.fftSize = 256;
  analyser.connect(ctx.destination);
  let stream = null;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
  } catch { /* no microphone, or not allowed: typing still works */ }
  const send = (frame) => { if (ws?.readyState === WebSocket.OPEN) ws.send(frame); };
  try {
    await ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], { type: "text/javascript" })));
    const node = new AudioWorkletNode(ctx, "mic", { processorOptions: { rate: IN_RATE, frame: FRAME } });
    if (stream) ctx.createMediaStreamSource(stream).connect(node);
    const mute = ctx.createGain(); // keeps the worklet running; nothing is heard
    mute.gain.value = 0;
    node.connect(mute).connect(ctx.destination);
    node.port.onmessage = (e) => send(e.data);
    hasMic = Boolean(stream);
  } catch { // no AudioWorklet: no voice in, but typed words still need an audio stream
    setInterval(() => send(new Int16Array(FRAME).buffer), (FRAME / IN_RATE) * 1000);
  }
  if (!hasMic) mode.textContent = "Microphone off: type below";
}

function play(bytes) {
  const pcm = new Int16Array(bytes);
  if (!pcm.length || !ctx) return;
  const buffer = ctx.createBuffer(1, pcm.length, OUT_RATE);
  const out = buffer.getChannelData(0);
  for (let i = 0; i < pcm.length; i++) out[i] = pcm[i] / 0x8000;
  const source = ctx.createBufferSource();
  source.buffer = buffer;
  source.connect(analyser);
  playAt = Math.max(playAt, ctx.currentTime + 0.05);
  source.start(playAt);
  playAt += buffer.duration;
  playing.add(source);
  source.onended = () => {
    playing.delete(source);
    if (!playing.size) setState(ws ? "listening" : "idle");
  };
  if (screenEl.dataset.state !== "speaking") {
    if (asked) status.textContent = `Live · Alexa answered in ${((performance.now() - asked) / 1000).toFixed(1)} s`;
    asked = 0;
    setState("speaking");
    followLoudness();
  }
}

function hush() { // stop Alexa mid-sentence (the person cut in, or the conversation ended)
  for (const s of playing) { s.onended = null; s.stop(); }
  playing.clear();
  playAt = 0;
}

let loudness = null; // reused every frame
function followLoudness() {
  if (!analyser || screenEl.dataset.state !== "speaking") return screenEl.style.setProperty("--level", 0);
  if (loudness?.length !== analyser.frequencyBinCount) loudness = new Uint8Array(analyser.frequencyBinCount);
  const data = loudness;
  analyser.getByteTimeDomainData(data);
  let peak = 0;
  for (const v of data) peak = Math.max(peak, Math.abs(v - 128));
  screenEl.style.setProperty("--level", Math.min(1, peak / 64).toFixed(2));
  requestAnimationFrame(followLoudness);
}

function chime() { // the device heard its wake word
  if (!ctx) return;
  [660, 880].forEach((f, i) => {
    const o = ctx.createOscillator(), g = ctx.createGain(), t = ctx.currentTime + i * 0.09;
    o.frequency.value = f;
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.15, t + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.12);
    o.connect(g).connect(ctx.destination);
    o.start(t);
    o.stop(t + 0.13);
  });
}

// ---- The live conversation ----
let line = { you: "", alexa: "" }; // the words arriving now
const pending = []; // typed words waiting for the connection to open

function connect(words) {
  if (words) pending.push(words);
  if (ws) return flush();
  stopWaking();
  const sock = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/live`);
  ws = sock;
  sock.binaryType = "arraybuffer";
  setState("thinking");
  sock.onopen = () => {
    if (ws !== sock) return;
    sock.send(JSON.stringify({ start: { household, said, screens: history.length } }));
    setState("listening");
    status.textContent = "Live";
    flush();
  };
  sock.onmessage = (e) => { // only the current conversation's (a muted one's last words are dropped)
    if (ws !== sock) return;
    if (typeof e.data === "string") onEvent(JSON.parse(e.data));
    else play(e.data);
  };
  sock.onclose = () => {
    if (ws !== sock) return;
    ws = null;
    if (!playing.size) setState("idle");
    if (handsFree) wake();
  };
}

function hangUp() {
  const old = ws;
  ws = null;
  old?.close();
}

function flush() {
  if (ws?.readyState !== WebSocket.OPEN) return;
  for (const words of pending.splice(0)) {
    addLog("you", words);
    heard.textContent = words;
    if (screenEl.dataset.view !== "app") view("talk");
    asked = performance.now();
    ws.send(JSON.stringify({ text: words }));
  }
}

function onEvent(e) {
  if (e.type === "heard") { // the person's words, as Alexa heard them
    line.you = e.final ? e.text : line.you + e.text;
    heard.textContent = line.you;
    if (screenEl.dataset.view === "app") caption.textContent = line.you;
    if (screenEl.dataset.view !== "app") view("talk");
    if (e.final) {
      if (e.text.trim()) addLog("you", e.text.trim());
      line.you = "";
      asked = performance.now();
      if (!playing.size) setState("thinking");
    }
  } else if (e.type === "said") { // Alexa's words, shown as she says them (any markdown dropped)
    const words = e.text.replace(/[*_#`]+/g, "");
    line.alexa = e.final ? words : line.alexa + words;
    say.textContent = caption.textContent = line.alexa;
    if (e.final) {
      if (words.trim()) addLog("alexa", words.trim());
      line.alexa = "";
    }
  } else if (e.type === "interrupted") {
    hush();
    setState("listening");
  } else if (e.type === "household") {
    household = e.household;
  } else if (e.type === "screen") {
    showScreen(e.call);
  } else if (e.type === "back") {
    back();
  } else if (e.type === "end") {
    if (e.reason === "quiet") status.textContent = rec ? "Resting · say “Alexa” to carry on" : "Resting · tap the mic to carry on";
    if (e.reason === "long") status.textContent = "That conversation ran long · say “Alexa” to carry on";
    if (e.message) {
      handsFree = false;
      say.textContent = caption.textContent = e.message;
      status.textContent = "";
    }
  }
}

// ---- The wake word: browser speech recognition, only while the conversation rests ----
const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null, waking = false, final = "", failed = false;

if (Recognition) {
  rec = new Recognition();
  rec.lang = "en-US";
  rec.onresult = (e) => {
    final = "";
    for (const r of e.results) if (r.isFinal) final += r[0].transcript;
  };
  rec.onend = () => {
    const words = final.trim();
    final = "";
    if (!waking) return;
    waking = false;
    if (failed) { failed = false; return setTimeout(wake, 3000); }
    const m = words.match(WAKE);
    if (!m) return wake(); // anything else is ignored: keep waiting
    chime();
    connect(words.slice(m.index + m[0].length).trim() || null); // "Alexa" alone: listen
  };
  rec.onerror = (e) => {
    if (e.error === "not-allowed" || e.error === "service-not-allowed") rec = null;
    else if (e.error !== "no-speech" && e.error !== "aborted") failed = true;
  };
}

// Recognition ends after each phrase or a few seconds of silence and is restarted, until
// the conversation starts again or the mic is muted.
function wake() {
  if (!rec || !handsFree || ws || waking) return setState(screenEl.dataset.state);
  waking = true;
  setState("idle");
  try { rec.start(); } catch { waking = false; }
}
function stopWaking() {
  if (!waking) return;
  waking = false;
  rec?.abort();
}

// ---- MCP Apps host (spec 2026-01-26) --------------------------------------------------
// The MCP server declares which tools show a screen (tool _meta.ui.resourceUri) and serves
// the screen's HTML; this page shows it in a sandboxed frame (an opaque origin: it can't
// reach this page or its storage, and its content-security policy allows only the domains
// the server declared) and hands it the tool's input and result, which the server forwards
// as each tool call finishes. One simplification: the spec's separate-origin proxy frame is
// replaced by that sandbox.
const PROTOCOL = "2026-01-26";
let screens = null; // {tools: {name: uri}, screens: {uri: {html, meta}}}
let shown = null; // the tool call on screen
let frame = null;
const history = []; // screens shown, for "go back" (like the device's back)

async function loadScreens() {
  if (!screens) {
    const res = await fetch("/api/screens");
    if (res.ok) screens = await res.json();
  }
  return screens;
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
      hostInfo: { name: "unclaimed-alexa-simulator", version: "2" },
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
  const screen = call && screens?.screens[call.uri];
  if (!screen) {
    frame = null;
    app.replaceChildren();
    view("talk");
  } else {
    frame = document.createElement("iframe");
    frame.title = "Unclaimed";
    frame.setAttribute("sandbox", "allow-scripts");
    view("app"); // visible first, so the view lays out at its real size
    frame.srcdoc = screen.html.replace("<head>", `<head><meta http-equiv="Content-Security-Policy" content="${cspFor(screen.meta)}">`);
    app.replaceChildren(frame);
  }
  $("back").hidden = !screen;
}

async function showScreen(call) {
  await loadScreens().catch(() => null);
  history.push(call);
  await render(call);
}

async function back() {
  if (!history.length) return;
  history.pop();
  await render(history.at(-1) ?? null);
}

// ---- Controls ----
// The first tap turns on sound and the mic (browsers require one); after that, hands-free.
async function begin(words) {
  await setupAudio();
  handsFree = true;
  connect(words);
}

$("start").addEventListener("click", () => begin(OPEN));

// The mic: a tap during a conversation ends it (mutes); otherwise it starts one.
mic.addEventListener("click", () => {
  if (ws) {
    handsFree = false;
    stopWaking();
    hush();
    hangUp();
    status.textContent = "";
    return setState("idle");
  }
  begin(null);
});

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const words = text.value.trim();
  text.value = "";
  if (words) begin(words);
});

for (const b of document.querySelectorAll(".try")) b.addEventListener("click", () => begin(b.textContent));
$("back").addEventListener("click", async () => {
  await back();
  if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ screens: history.length }));
});

$("reset").addEventListener("click", async () => {
  hush();
  hangUp();
  stopWaking();
  handsFree = false;
  household = null;
  said.length = pending.length = 0;
  history.length = 0;
  line = { you: "", alexa: "" };
  await render(null);
  delete screenEl.dataset.view;
  log.replaceChildren();
  heard.textContent = say.textContent = caption.textContent = status.textContent = "";
  setState("idle");
});

loadScreens().catch(() => null);
setState("idle");
