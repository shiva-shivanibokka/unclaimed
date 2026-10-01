// The simulated Echo Show: push-to-talk (browser speech recognition), spoken replies
// (browser speech synthesis), and result cards. The conversation lives only in this page
// and goes to the server with each turn; reloading forgets it.

const $ = (id) => document.getElementById(id);
const say = $("say"), heard = $("heard"), cards = $("cards"), bar = $("bar");
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

// The latest get_results tool result in the conversation, if any.
function latestResults() {
  const ids = new Set();
  for (const m of messages) for (const b of m.content) if (b.toolUse?.name === "get_results") ids.add(b.toolUse.toolUseId);
  for (let i = messages.length - 1; i >= 0; i--) {
    for (const b of messages[i].content) {
      const r = b.toolResult;
      if (!r || !ids.has(r.toolUseId) || r.status === "error") continue;
      for (const c of r.content) {
        if (c.json) return c.json;
        try { return JSON.parse(c.text); } catch { /* not JSON */ }
      }
    }
  }
  return null;
}

const money = (x) => `$${Math.round(x).toLocaleString("en-US")}`;

function renderCards(results) {
  cards.replaceChildren();
  if (!results) return;
  const yes = results.programs.filter((p) => p.eligible);
  for (const p of yes) {
    const card = document.createElement("div");
    card.className = `card${p.conditional_on ? " if" : ""}`;
    const h = document.createElement("h3");
    h.textContent = p.name;
    const amt = document.createElement("div");
    amt.className = "amt";
    amt.textContent = p.amount === undefined ? "Covered" : p.amount > 0 ? `${money(p.amount)} / ${p.per}` : "Qualifies";
    card.append(h, amt);
    const notes = [];
    if (p.amount === 0) notes.push("amount depends on your bill");
    if (p.conditional_on) notes.push("depends on an answer you skipped");
    if (p.eligible_people) notes.push(`for ${p.eligible_people.length} ${p.eligible_people.length === 1 ? "person" : "people"}`);
    if (notes.length) {
      const n = document.createElement("div");
      n.className = "note";
      n.textContent = notes.join(" · ");
      card.appendChild(n);
    }
    cards.appendChild(card);
  }
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
    renderCards(latestResults());
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
  cards.replaceChildren();
  log.replaceChildren();
  heard.textContent = "";
  status.textContent = "";
  say.innerHTML = "Tap the mic and say <em>“Alexa, open Unclaimed”</em>, or type below.";
});
