"use strict";
/* Parley UI. Talks to Python through window.pywebview.api; falls back to a
   small mock so the page can be previewed in a normal browser. */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

const HUES = [215, 340, 150, 28, 268, 190, 5, 95, 300, 50];
const DEFAULT_VOICES = ["en-US-AvaNeural", "en-US-AndrewNeural", "en-GB-SoniaNeural", "en-GB-RyanNeural",
  "en-US-EmmaNeural", "en-US-BrianNeural", "en-AU-NatashaNeural", "en-AU-WilliamMultilingualNeural"];
const FEMALE = /^(woman|girl|mother|mom|mum|mrs|ms|miss|lady|she|female|grandma|aunt|sister|daughter|queen|waitress)\b/i;
const MALE = /^(man|boy|father|dad|mr|sir|he|male|grandpa|uncle|brother|son|king|waiter)\b/i;
const EXAMPLE = [
  ["Barista", "Good morning! What can I get for you today?"],
  ["Customer", "Hi! Could I have a medium latte, please?"],
  ["Barista", "Of course. Would you like it hot or iced?"],
  ["Customer", "Hot, please. And one of those blueberry muffins."],
  ["Barista", "Great choice. That comes to six fifty. [pause 1s] Here you go. Enjoy!"],
];

const S = {
  mode: "dialogue", narration: "", lines: [], cast: {}, order: [], gap: 400,
  voices: [], profiles: [], allLanguages: false, accent: "en", ocr: false,
  path: null, name: "", dirty: false, busy: false,
  audio: null, stale: false, lastSaved: null, update: null, info: {},
};
let uid = 0;
const audio = $("#audio");
const previewAudio = new Audio();

/* ---------- bridge ---------- */
const mock = {
  init: async () => ({ version: "dev", platform: "browser", ocr: true, engine: "preview", engineCustom: false, settings: {} }),
  voices: async () => ({ ok: true, voices: DEFAULT_VOICES.map((v, i) => ({ ShortName: v, Locale: v.slice(0, 5), Gender: i % 2 ? "Male" : "Female" })) }),
  generate: async () => ({ ok: false, error: "Audio can only be created in the Parley app." }),
  preview: async () => ({ ok: false, error: "Previews work in the Parley app." }),
  parse_text: async (t) => ({ ok: true, mode: /^\s*\w[^:\n]{0,59}:/m.test(t) ? "dialogue" : "narration", text: t,
    lines: t.split(/\n/).filter(Boolean).map((l) => { const m = l.match(/^([^:]{1,60}):\s*(.*)$/); return { speaker: m ? m[1].trim() : "Narrator", text: m ? m[2] : l }; }) }),
  parse_dialogue: async (t) => mock.parse_text(t),
  set_settings: async () => true, set_dirty: async () => {}, cache_size: async () => 0,
  get_profiles: async () => [
    { name: "Narrator", voice: "en-US-AvaNeural", alt: null, rate: 0, pitch: 0, aliases: [], group: "General" },
    { name: "Teacher", voice: "en-GB-SoniaNeural", alt: "en-US-AndrewNeural", rate: 0, pitch: 0, aliases: ["Tutor"], group: "Campus" },
    { name: "Student", voice: "en-US-AndrewNeural", alt: "en-US-EmmaNeural", rate: 0, pitch: 0, aliases: [], group: "Campus" },
    { name: "Waiter", voice: "en-US-BrianNeural", alt: null, rate: 0, pitch: 0, aliases: ["Server"], group: "Food & shopping" }],
  save_profiles: async (p) => ({ ok: true, profiles: p }),
};
const api = new Proxy({}, { get: (_, k) => (...a) => (window.pywebview?.api?.[k] ?? mock[k] ?? (async () => ({ ok: false })))(...a) });

/* ---------- utilities ---------- */
const fmt = (s) => { s = Math.max(0, Math.floor(s || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const regionName = (() => {
  let dn; try { dn = new Intl.DisplayNames(["en"], { type: "region" }); } catch { dn = null; }
  return (r) => (dn ? dn.of(r) : r);
})();
const langName = (() => {
  let dn; try { dn = new Intl.DisplayNames(["en"], { type: "language" }); } catch { dn = null; }
  return (l) => (dn ? dn.of(l) : l);
})();
const voiceLabel = (v) => {
  const short = v.ShortName.split("-").slice(2).join("-").replace(/Neural$/, "").replace(/Multilingual/, " (multilingual)");
  return `${short} · ${v.Gender === "Female" ? "female" : "male"}`;
};
function setRangeFill(r) { const p = ((r.value - r.min) / (r.max - r.min)) * 100; r.style.setProperty("--p", p + "%"); }

let toastTimer;
function toast(message, { error = false, actions = [], sticky = false } = {}) {
  const t = $("#toast");
  t.className = "toast" + (error ? " error" : "");
  t.innerHTML = `<div>${esc(message)}</div>`;
  if (actions.length) {
    const row = document.createElement("div"); row.className = "toast-actions";
    for (const [label, fn] of actions) {
      const b = document.createElement("button"); b.className = "link"; b.textContent = label;
      b.onclick = () => { t.hidden = true; fn(); }; row.append(b);
    }
    const close = document.createElement("button"); close.className = "link muted"; close.textContent = "Dismiss";
    close.onclick = () => (t.hidden = true); row.append(close); t.append(row);
  }
  t.hidden = false;
  clearTimeout(toastTimer);
  if (!sticky && !actions.length) toastTimer = setTimeout(() => (t.hidden = true), error ? 7000 : 3500);
}
function status(text, error = false) { const s = $("#status"); s.textContent = text; s.classList.toggle("error", error); }
function busyOverlay(text) { $("#busyOverlay").hidden = !text; if (text) $("#busyText").textContent = text; }

/* ---------- state helpers ---------- */
/* Voice profiles: a character named like a profile (or one of its aliases) gets
   its voice. "Student A"/"Student B" or "Student 1"/"Student 2" use the
   profile's first and second voice. */
const norm = (s) => s.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
function findProfile(key) {
  return S.profiles.find((p) => norm(p.name) === key || (p.aliases || []).some((a) => norm(a) === key));
}
function profileMatch(name) {
  const n = norm(name);
  const exact = findProfile(n);
  if (exact) return { p: exact, variant: 0 };
  const m = n.match(/^(.+?) ([a-z]|\d{1,2})$/);
  if (!m) return null;
  const p = findProfile(m[1]);
  if (!p) return null;
  return { p, variant: /\d/.test(m[2]) ? Math.max(0, Number(m[2]) - 1) : m[2].charCodeAt(0) - 97 };
}
function characterFor(name) {
  if (!S.cast[name]) {
    const i = Object.keys(S.cast).length;
    let voice = DEFAULT_VOICES[i % DEFAULT_VOICES.length], rate = 0, pitch = 0;
    const match = profileMatch(name);
    if (match) {
      const { p, variant } = match;
      voice = variant === 0 ? p.voice : variant === 1 && p.alt ? p.alt : DEFAULT_VOICES[(i + variant) % DEFAULT_VOICES.length];
      rate = p.rate || 0; pitch = p.pitch || 0;
    } else if (FEMALE.test(name)) voice = "en-US-AvaNeural";
    else if (MALE.test(name)) voice = "en-US-AndrewNeural";
    S.cast[name] = { name, voice, rate, pitch, hue: HUES[i % HUES.length], tune: false };
  }
  return S.cast[name];
}
const ownProfile = (c) => S.profiles.find((p) => p.name.toLowerCase() === c.name.toLowerCase());
const inSync = (c, p) => p && p.voice === c.voice && (p.rate || 0) === c.rate && (p.pitch || 0) === c.pitch;
let profileSaveTimer;
async function persistProfiles(now = false) {
  clearTimeout(profileSaveTimer);
  const run = async () => {
    const r = await api.save_profiles(S.profiles);
    if (!r.ok) return toast(r.error || "Could not save the voice profiles.", { error: true });
    S.profiles = r.profiles; fillProfileNames();
  };
  if (now) return run();
  profileSaveTimer = setTimeout(run, 400);
}
async function saveAsProfile(c) {
  const existing = ownProfile(c);
  if (existing) Object.assign(existing, { voice: c.voice, rate: c.rate, pitch: c.pitch });
  else S.profiles.unshift({ name: c.name, voice: c.voice, alt: null, rate: c.rate, pitch: c.pitch, aliases: [], group: "My profiles" });
  await persistProfiles(true);
  toast(existing ? `Updated the “${c.name}” profile.` : `Saved “${c.name}” as a voice profile. New characters with this name will sound the same.`);
  renderCast();
}
function fillProfileNames() {
  $("#profileNames").innerHTML = S.profiles.map((p) => `<option value="${esc(p.name)}">`).join("");
}
function speakers() {
  if (S.mode === "narration") return ["Narrator"];
  const seen = []; for (const l of S.lines) if (!seen.includes(l.speaker)) seen.push(l.speaker);
  return seen;
}
function nextSpeaker(after) {
  const names = speakers();
  if (names.length < 2) return names[0] ? (names[0] === "A" ? "B" : null) : "A";
  const i = names.indexOf(after);
  return names[(i + 1) % names.length];
}
function markDirty() {
  if (!S.dirty) { S.dirty = true; api.set_dirty(true); }
  if (S.audio && !S.stale) { S.stale = true; refreshCreate(); $$(".line .from").forEach((b) => (b.hidden = true)); status("The script changed. Update the audio to hear the latest version."); }
  updateCount();
}
function projectState() {
  return {
    format: "parley", version: 1, mode: S.mode, narration: S.narration,
    lines: S.lines.map(({ speaker, text }) => ({ speaker, text })),
    characters: [...new Set([...speakers(), ...Object.keys(S.cast)])].filter((n) => S.cast[n])
      .map((n) => ({ name: n, voice: S.cast[n].voice, rate: S.cast[n].rate, pitch: S.cast[n].pitch })),
    gap_ms: S.gap,
  };
}
function loadState(p, { path = null, name = "" } = {}) {
  S.mode = p.mode; S.narration = p.narration || ""; S.gap = p.gap_ms ?? 400; S.cast = {};
  for (const c of p.characters || []) Object.assign(characterFor(c.name), { voice: c.voice, rate: c.rate || 0, pitch: c.pitch || 0 });
  S.lines = (p.lines || []).map((l) => ({ id: ++uid, speaker: l.speaker, text: l.text }));
  S.lines.forEach((l) => characterFor(l.speaker));
  S.path = path; S.name = name; S.dirty = false; api.set_dirty(false);
  clearAudio(); renderAll();
}

/* ---------- rendering ---------- */
function renderAll() {
  $$(".segmented button").forEach((b) => b.setAttribute("aria-selected", b.dataset.mode === S.mode));
  const dialogue = S.mode === "dialogue";
  $("#narrationView").hidden = dialogue;
  $("#dialogueView").hidden = !dialogue || S.textEdit;
  $("#dialogueTextView").hidden = !dialogue || !S.textEdit;
  $("#toggleTextBtn").hidden = !dialogue;
  $("#toggleTextBtn").textContent = S.textEdit ? "Done" : "Edit as text";
  $("#gapRow").hidden = !dialogue;
  $("#narration").value = S.narration;
  $("#docName").textContent = S.name;
  renderLines(); renderCast(); updateCount(); refreshCreate();
  $("#gapOut").textContent = (S.gap / 1000).toFixed(1) + " s";
}

function speakerOptions(current) {
  const names = speakers(); if (!names.includes(current)) names.push(current);
  return names.map((n) => `<option ${n === current ? "selected" : ""}>${esc(n)}</option>`).join("") +
    `<option disabled>──────────</option><option value="__new">New character…</option>`;
}

function renderLines() {
  const ol = $("#lines");
  ol.innerHTML = "";
  for (const line of S.lines) ol.append(lineEl(line));
  $("#emptyDialogue").hidden = S.lines.length > 0;
  $$(".line textarea", ol).forEach(autoGrow);
}

function lineEl(line) {
  const c = characterFor(line.speaker);
  const li = document.createElement("li");
  li.className = "line"; li.dataset.id = line.id; li.style.setProperty("--h", c.hue);
  li.innerHTML = `<span class="grip" title="Drag to reorder"><svg><use href="#i-grip"/></svg></span>
    <select class="speaker" aria-label="Character">${speakerOptions(line.speaker)}</select>
    <textarea rows="1" spellcheck="true" placeholder="What does ${esc(line.speaker)} say?"></textarea>
    <span class="row-btns"><button class="del" title="Delete line"><svg><use href="#i-x"/></svg></button>
      <button class="from" title="Play from this line" ${S.audio && !S.stale ? "" : "hidden"}><svg><use href="#i-play"/></svg></button></span>`;
  const ta = $("textarea", li); ta.value = line.text;
  const sel = $(".speaker", li);

  sel.onchange = () => {
    if (sel.value === "__new") { sel.value = line.speaker; askName(sel, (name) => { line.speaker = name; characterFor(name); markDirty(); renderLines(); renderCast(); focusLine(line.id); }); return; }
    line.speaker = sel.value; markDirty(); li.style.setProperty("--h", characterFor(line.speaker).hue); renderCast();
  };
  ta.oninput = () => { line.text = ta.value.replace(/\n/g, " "); if (ta.value.includes("\n")) ta.value = line.text; autoGrow(ta); markDirty(); };
  ta.onkeydown = (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
      e.preventDefault(); addLine(line.id);
    } else if (e.key === "Backspace" && !ta.value && S.lines.length > 1) {
      e.preventDefault(); const i = S.lines.indexOf(line); removeLine(line.id); const prev = S.lines[Math.max(0, i - 1)]; focusLine(prev.id, true);
    }
  };
  ta.onpaste = async (e) => {
    const text = e.clipboardData.getData("text");
    if (!/\n/.test(text.trim()) || !/^[^:\n]{1,60}:/m.test(text)) return;
    const r = await api.parse_dialogue(text);
    if (!r.ok) return;
    e.preventDefault();
    const at = S.lines.indexOf(line);
    const fresh = r.lines.map((l) => ({ id: ++uid, speaker: l.speaker, text: l.text }));
    fresh.forEach((l) => characterFor(l.speaker));
    S.lines.splice(at + (line.text.trim() ? 1 : 0), line.text.trim() ? 0 : 1, ...fresh);
    markDirty(); renderLines(); renderCast(); toast(`Added ${fresh.length} lines.`);
  };
  $(".del", li).onclick = () => removeLine(line.id);
  $(".from", li).onclick = () => seekToLine(line.id);

  // drag to reorder
  const grip = $(".grip", li);
  grip.onmousedown = () => (li.draggable = true);
  li.ondragstart = (e) => { li.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/parley-line", String(line.id)); };
  li.ondragend = () => { li.draggable = false; li.classList.remove("dragging"); $$(".drop-before,.drop-after").forEach((x) => x.classList.remove("drop-before", "drop-after")); };
  li.ondragover = (e) => {
    if (!e.dataTransfer.types.includes("text/parley-line")) return;
    e.preventDefault(); const after = e.offsetY > li.offsetHeight / 2;
    li.classList.toggle("drop-after", after); li.classList.toggle("drop-before", !after);
  };
  li.ondragleave = () => li.classList.remove("drop-before", "drop-after");
  li.ondrop = (e) => {
    const id = Number(e.dataTransfer.getData("text/parley-line")); if (!id || id === line.id) return;
    e.preventDefault(); e.stopPropagation();
    const moving = S.lines.find((l) => l.id === id); S.lines.splice(S.lines.indexOf(moving), 1);
    const after = li.classList.contains("drop-after");
    S.lines.splice(S.lines.indexOf(line) + (after ? 1 : 0), 0, moving);
    markDirty(); renderLines();
  };
  return li;
}

function askName(anchor, done) {
  const input = document.createElement("input");
  input.className = "speaker"; input.placeholder = "Name"; input.style.setProperty("--h", 215); input.maxLength = 60;
  input.setAttribute("list", "profileNames");
  input.style.background = "var(--field)"; input.style.color = "var(--ink)"; input.style.width = "132px";
  anchor.replaceWith(input); input.focus();
  let finished = false;
  const finish = (ok) => {
    if (finished) return; finished = true;
    const name = input.value.trim().replace(/:/g, "");
    input.replaceWith(anchor);
    if (ok && name) done(name);
  };
  input.onkeydown = (e) => { if (e.key === "Enter") finish(true); if (e.key === "Escape") finish(false); };
  input.onblur = () => finish(true);
}

function autoGrow(ta) { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + "px"; }
function focusLine(id, atEnd = false) {
  const ta = $(`.line[data-id="${id}"] textarea`); if (!ta) return;
  ta.focus(); if (atEnd) ta.setSelectionRange(ta.value.length, ta.value.length);
}
function addLine(afterId = null) {
  const at = afterId == null ? S.lines.length - 1 : S.lines.findIndex((l) => l.id === afterId);
  const prev = S.lines[at];
  const speaker = prev ? nextSpeaker(prev.speaker) || "B" : speakers()[0] || "A";
  const line = { id: ++uid, speaker, text: "" };
  characterFor(speaker);
  S.lines.splice(at + 1, 0, line);
  markDirty(); renderLines(); renderCast(); focusLine(line.id);
}
function removeLine(id) {
  S.lines = S.lines.filter((l) => l.id !== id); markDirty(); renderLines(); renderCast();
}

/* ---------- voices panel ---------- */
function accentOptions() {
  const sel = $("#accent");
  const locales = [...new Set(S.voices.map((v) => v.Locale))];
  let html = "";
  if (S.allLanguages) {
    const langs = [...new Set(locales.map((l) => l.split("-")[0]))].sort((a, b) => langName(a).localeCompare(langName(b)));
    html = langs.map((l) => `<option value="${l}">${esc(langName(l))}</option>`).join("");
  } else {
    html = `<option value="en">All English accents</option>` + locales.filter((l) => l.startsWith("en-"))
      .sort((a, b) => regionName(a.slice(3)).localeCompare(regionName(b.slice(3))))
      .map((l) => `<option value="${l}">${esc(regionName(l.slice(3)))}</option>`).join("");
  }
  sel.innerHTML = html;
  if (![...sel.options].some((o) => o.value === S.accent)) S.accent = "en";
  sel.value = S.accent;
}
function visibleVoices(current) {
  const list = S.voices.filter((v) => (S.accent.length === 2 ? v.Locale.startsWith(S.accent + "-") : v.Locale === S.accent));
  if (current && !list.some((v) => v.ShortName === current)) {
    const cur = S.voices.find((v) => v.ShortName === current) || { ShortName: current, Locale: current.slice(0, 5), Gender: "" };
    list.unshift(cur);
  }
  return list;
}
function voiceOptions(current) {
  const groups = {};
  for (const v of visibleVoices(current)) (groups[v.Locale] ||= []).push(v);
  return Object.keys(groups).sort().map((loc) => {
    const [l, r] = loc.split("-");
    const label = l === "en" ? `English (${regionName(r)})` : `${langName(l)} (${regionName(r)})`;
    return `<optgroup label="${esc(label)}">` + groups[loc].map((v) =>
      `<option value="${v.ShortName}" ${v.ShortName === current ? "selected" : ""}>${esc(voiceLabel(v))}</option>`).join("") + "</optgroup>";
  }).join("");
}
function renderCast() {
  const box = $("#cast"); box.innerHTML = "";
  for (const name of speakers()) {
    const c = characterFor(name);
    const own = ownProfile(c), synced = inSync(c, own), match = !own && profileMatch(name);
    const note = synced ? "Voice profile" : own ? "Changed from its voice profile" : match ? `From the “${esc(match.p.name)}” profile` : "";
    const el = document.createElement("div"); el.className = "character"; el.style.setProperty("--h", c.hue);
    el.innerHTML = `<div class="char-top"><span class="dot"></span>
        <input class="char-name" value="${esc(name)}" maxlength="60" aria-label="Character name" ${S.mode === "narration" ? "readonly" : ""}>
        <button class="mini ${c.tune ? "active" : ""} tune" title="Speed and pitch"><svg><use href="#i-sliders"/></svg></button>
        <button class="mini listen" title="Listen to this voice"><svg><use href="#i-speaker"/></svg></button>
        <button class="mini save-profile ${synced ? "active" : ""}" title="${synced ? `Saved as the “${esc(own.name)}” profile` : own ? `Update the “${esc(own.name)}” profile` : "Save as a voice profile"}"><svg><use href="${synced ? "#i-bookmark-fill" : "#i-bookmark"}"/></svg></button></div>
      ${note ? `<div class="char-sub">${note}</div>` : ""}
      <select class="voice-select" aria-label="Voice for ${esc(name)}">${voiceOptions(c.voice)}</select>
      <div class="tuning" ${c.tune ? "" : "hidden"}>
        <span>Speed</span><input type="range" class="rate" min="-50" max="100" step="5" value="${c.rate}"><output>${c.rate ? (c.rate > 0 ? "+" : "") + c.rate + "%" : "Normal"}</output>
        <span>Pitch</span><input type="range" class="pitch" min="-50" max="50" step="5" value="${c.pitch}"><output>${c.pitch ? (c.pitch > 0 ? "+" : "") + c.pitch : "Normal"}</output>
      </div>`;
    $(".voice-select", el).onchange = (e) => { c.voice = e.target.value; markDirty(); renderCast(); };
    $(".tune", el).onclick = () => { c.tune = !c.tune; renderCast(); };
    $(".listen", el).onclick = (e) => preview(c, e.currentTarget);
    $(".save-profile", el).onclick = () => { if (!synced) saveAsProfile(c); else toast(`“${c.name}” already matches its voice profile. Change it under Settings → Voice profiles.`); };
    for (const [cls, key, unit] of [["rate", "rate", "%"], ["pitch", "pitch", ""]]) {
      const r = $("." + cls, el); setRangeFill(r);
      r.oninput = () => { c[key] = Number(r.value); setRangeFill(r); r.nextElementSibling.textContent = c[key] ? (c[key] > 0 ? "+" : "") + c[key] + unit : "Normal"; markDirty(); };
      r.onchange = () => renderCast();
    }
    const nameInput = $(".char-name", el);
    nameInput.onkeydown = (e) => { if (e.key === "Enter") nameInput.blur(); };
    nameInput.onchange = () => renameCharacter(name, nameInput.value.trim().replace(/:/g, ""), nameInput);
    box.append(el);
  }
  if (!speakers().length) box.innerHTML = `<p class="hint" style="padding:8px">Characters appear here as you add lines.</p>`;
}
function renameCharacter(from, to, input) {
  if (!to || to === from) { input.value = from; return; }
  if (speakers().includes(to)) { toast(`There is already a character called “${to}”.`, { error: true }); input.value = from; return; }
  S.cast[to] = { ...S.cast[from], name: to }; delete S.cast[from];
  S.lines.forEach((l) => { if (l.speaker === from) l.speaker = to; });
  markDirty(); renderLines(); renderCast();
}
async function preview(c, btn) {
  btn.classList.add("active");
  const r = await api.preview(c.voice, c.rate, c.pitch);
  btn.classList.remove("active");
  if (!r.ok) return handleSpeechError(r, () => preview(c, btn));
  audio.pause(); previewAudio.src = "data:audio/mpeg;base64," + r.audio; previewAudio.play();
}

/* ---------- create & play ---------- */
function updateCount() {
  const n = S.mode === "narration" ? S.narration.length : S.lines.reduce((a, l) => a + l.text.length, 0);
  $("#count").textContent = `${n.toLocaleString("en-US")} characters`;
}
function refreshCreate() {
  const b = $("#createBtn");
  b.classList.toggle("cancel", S.busy);
  b.textContent = S.busy ? "Cancel" : S.audio && S.stale ? "Update audio" : S.audio ? "Create again" : "Create audio";
  $("#exportWrap").hidden = !S.audio || S.busy;
  $("#playBtn").disabled = !S.audio || S.busy;
  $("#scrub").disabled = !S.audio;
  $$(".segmented button, #openBtn, #saveProjectBtn").forEach((x) => (x.disabled = S.busy));
}
function clearAudio() {
  audio.pause(); if (S.audio?.url) URL.revokeObjectURL(S.audio.url);
  S.audio = null; S.stale = false; audio.removeAttribute("src");
  $("#timeNow").textContent = "0:00"; $("#timeTotal").textContent = "0:00"; $("#scrub").value = 0; setRangeFill($("#scrub"));
  refreshCreate();
}
function progress(fraction) { $("#progress div").style.width = fraction == null ? "0" : Math.round(fraction * 100) + "%"; }

async function create() {
  if (S.busy) { api.cancel_job(); status("Cancelling…"); return; }
  if (S.mode === "dialogue" && S.textEdit && !(await applyTextEdit())) return;
  const p = projectState();
  if (S.mode === "narration") p.characters = [{ name: "Narrator", ...pick(characterFor("Narrator")) }];
  S.busy = true; refreshCreate(); progress(0.02); status("Connecting to the speech service…");
  const r = await api.generate(p);
  S.busy = false; progress(null);
  if (!r.ok) {
    refreshCreate();
    if (r.cancelled) return status("Cancelled. Nothing was changed.");
    return handleSpeechError(r, create);
  }
  clearAudio();
  const blob = await (await fetch("data:audio/mpeg;base64," + r.audio)).blob();
  S.audio = { url: URL.createObjectURL(blob), seconds: r.seconds, segments: r.segments };
  audio.src = S.audio.url;
  $("#timeTotal").textContent = fmt(r.seconds);
  refreshCreate(); renderLines();
  status(`Ready · ${fmt(r.seconds)} of audio. Press play to listen, then save it as MP3.`);
  audio.play().catch(() => {});
}
const pick = (c) => ({ voice: c.voice, rate: c.rate, pitch: c.pitch });

async function handleSpeechError(r, retry) {
  if (!r.blocked) { status("Could not create audio.", true); return toast(r.error || "Something went wrong.", { error: true }); }
  status("The speech service changed. Repairing…", true);
  busyOverlay("Updating the speech engine…");
  const fix = await api.repair_engine();
  busyOverlay(null);
  if (fix.ok) {
    toast(`Speech engine updated (${fix.previous} → ${fix.version}).`);
    S.info.engine = fix.version; S.info.engineCustom = true;
    return retry();
  }
  status("The speech service is not available right now.", true);
  if (fix.update) showUpdate(fix.update, true);
  else toast(fix.error || "Repair failed.", { error: true });
}

function lineIdAt(t) {
  if (!S.audio || S.mode !== "dialogue") return null;
  const lines = S.lines.filter((l) => l.text.trim());
  const seg = S.audio.segments.find((s) => t >= s.start && t < s.end + (S.gap / 1000));
  return seg ? lines[seg.line]?.id ?? null : null;
}
function seekToLine(id, play = true) {
  const lines = S.lines.filter((l) => l.text.trim());
  const i = lines.findIndex((l) => l.id === id);
  const seg = S.audio?.segments.find((s) => s.line === i);
  if (!seg) return;
  audio.currentTime = seg.start;
  if (play) audio.play();
}
let lastPlaying = null;
audio.ontimeupdate = () => {
  const t = audio.currentTime, d = S.audio?.seconds || audio.duration || 1;
  $("#timeNow").textContent = fmt(t);
  const scrub = $("#scrub"); if (!scrub.matches(":active")) { scrub.value = Math.round((t / d) * 1000); setRangeFill(scrub); }
  const id = S.stale ? null : lineIdAt(t);
  if (id !== lastPlaying) {
    $$(".line.playing").forEach((x) => x.classList.remove("playing"));
    const el = id && $(`.line[data-id="${id}"]`);
    if (el) { el.classList.add("playing"); if (!audio.paused) el.scrollIntoView({ block: "nearest", behavior: "smooth" }); }
    lastPlaying = id;
  }
};
audio.onplay = audio.onpause = () => { $("#playBtn use").setAttribute("href", audio.paused ? "#i-play" : "#i-pause"); };
audio.onended = () => { $$(".line.playing").forEach((x) => x.classList.remove("playing")); lastPlaying = null; };
$("#playBtn").onclick = () => (audio.paused ? audio.play() : audio.pause());
$("#scrub").oninput = (e) => { setRangeFill(e.target); if (S.audio) audio.currentTime = (e.target.value / 1000) * S.audio.seconds; };
$("#createBtn").onclick = create;

$("#saveAudioBtn").onclick = async () => {
  const r = await api.save_audio(S.name || "Parley audio");
  if (r.ok) toast("Saved " + r.path.split(/[\\/]/).pop(), { actions: [["Show in folder", () => api.reveal(r.path)]] });
  else if (r.error) toast(r.error, { error: true });
};
$("#exportMore").onclick = (e) => { e.stopPropagation(); toggleMenu("#exportMenu"); };

/* ---------- mode, text editing ---------- */
$$(".segmented button").forEach((b) => (b.onclick = () => switchMode(b.dataset.mode)));
function switchMode(mode) {
  if (mode === S.mode) return;
  if (mode === "narration" && !S.narration.trim() && S.lines.length) S.narration = S.lines.map((l) => l.text).join("\n\n");
  S.mode = mode; S.textEdit = false; clearAudio(); markDirty(); renderAll();
}
$("#narration").oninput = (e) => { S.narration = e.target.value; markDirty(); };
$("#addLine").onclick = () => addLine();
$("#emptyAdd").onclick = () => addLine();
$("#emptyExample").onclick = () => loadExample();
$("#toggleTextBtn").onclick = async () => {
  if (S.textEdit) { if (await applyTextEdit()) { S.textEdit = false; renderAll(); } return; }
  $("#dialogueText").value = S.lines.map((l) => `${l.speaker}: ${l.text}`).join("\n");
  S.textEdit = true; renderAll(); $("#dialogueText").focus();
};
async function applyTextEdit() {
  const text = $("#dialogueText").value;
  if (!text.trim()) { S.lines = []; return true; }
  const r = await api.parse_dialogue(text);
  if (!r.ok) { toast(r.error, { error: true }); return false; }
  S.lines = r.lines.map((l) => ({ id: ++uid, speaker: l.speaker, text: l.text }));
  S.lines.forEach((l) => characterFor(l.speaker));
  return true;
}
$("#dialogueText").oninput = () => markDirty();

$$(".stepper button").forEach((b) => (b.onclick = () => {
  S.gap = Math.max(0, Math.min(3000, S.gap + Number(b.dataset.step)));
  $("#gapOut").textContent = (S.gap / 1000).toFixed(1) + " s"; markDirty();
}));
$("#accent").onchange = (e) => { S.accent = e.target.value; renderCast(); };

/* ---------- menus & files ---------- */
function toggleMenu(sel) {
  const m = $(sel), open = m.hidden;
  $$(".menu").forEach((x) => (x.hidden = true));
  m.hidden = !open;
}
document.addEventListener("click", () => $$(".menu").forEach((x) => (x.hidden = true)));
$("#openBtn").onclick = (e) => { e.stopPropagation(); toggleMenu("#openMenu"); };
$$(".menu button").forEach((b) => (b.onclick = () => { $$(".menu").forEach((x) => (x.hidden = true)); actions[b.dataset.action](); }));

async function okToReplace() {
  if (!S.dirty || !hasContent()) return true;
  return window.pywebview ? await api.confirm_discard() : confirm("Discard unsaved changes?");
}
const hasContent = () => S.narration.trim() || S.lines.some((l) => l.text.trim());

function applyParsed(r, name = "") {
  if (!r.ok) { if (r.error) toast(r.error, { error: true }); return; }
  S.cast = {}; S.path = null; S.name = name.replace(/\.[^.]+$/, "");
  if (r.mode === "dialogue") {
    S.mode = "dialogue"; S.lines = r.lines.map((l) => ({ id: ++uid, ...l })); S.lines.forEach((l) => characterFor(l.speaker));
  } else {
    S.mode = "narration"; S.narration = r.text; S.lines = [];
  }
  S.textEdit = false; clearAudio(); S.dirty = true; api.set_dirty(true); renderAll();
  toast(r.mode === "dialogue" ? `Found ${speakers().length} characters and ${S.lines.length} lines.` : "Text loaded. Choose a voice and create the audio.");
}

const actions = {
  async openText() { if (!(await okToReplace())) return; const r = await api.open_text(); if (r.ok || r.error) applyParsed(r, r.name || ""); },
  async openImage() {
    if (!(await okToReplace())) return;
    busyOverlay("Reading text from the image…"); const r = await api.open_image(); busyOverlay(null);
    if (r.ok || r.error) { applyParsed(r); if (r.ok) status("Check the text carefully. Image reading can make small mistakes."); }
  },
  async openProject() {
    if (!(await okToReplace())) return;
    const r = await api.open_project(); if (!r.ok) { if (r.error) toast(r.error, { error: true }); return; }
    loadState(r.project, { path: r.path, name: r.name }); toast("Opened " + r.name);
  },
  async newProject() { if (!(await okToReplace())) return; loadState({ mode: "dialogue", lines: [], characters: [], narration: "" }); },
  async example() { if (!(await okToReplace())) return; loadExample(); },
  saveSrt: async () => { const r = await api.save_subtitles(S.name || "Parley audio"); if (r.ok) toast("Subtitles saved."); else if (r.error) toast(r.error, { error: true }); },
};
function loadExample() {
  loadState({ mode: "dialogue", narration: "", gap_ms: 400, characters: [],
    lines: EXAMPLE.map(([speaker, text]) => ({ speaker, text })) }, { name: "Example" });
}
async function saveProject() {
  if (S.mode === "dialogue" && S.textEdit && !(await applyTextEdit())) return;
  const r = await api.save_project(projectState(), S.path);
  if (!r.ok) { if (r.error) toast(r.error, { error: true }); return; }
  S.path = r.path; S.name = r.name; S.dirty = false; api.set_dirty(false); $("#docName").textContent = S.name; toast("Project saved.");
}
$("#saveProjectBtn").onclick = saveProject;

// Drag and drop files onto the window
document.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("Files")) e.preventDefault(); });
document.addEventListener("drop", async (e) => {
  const file = e.dataTransfer.files?.[0]; if (!file) return;
  e.preventDefault();
  if (!(await okToReplace())) return;
  if (/\.parley$/i.test(file.name)) {
    try { const p = JSON.parse(await file.text()); loadState(p, { name: file.name.replace(/\.parley$/i, "") }); } catch { toast("That project file could not be opened.", { error: true }); }
  } else if (file.type.startsWith("image/")) {
    if (!S.ocr) return toast("Reading text from images needs Windows 10 or 11.", { error: true });
    const b64 = await new Promise((res) => { const fr = new FileReader(); fr.onload = () => res(fr.result.split(",")[1]); fr.readAsDataURL(file); });
    busyOverlay("Reading text from the image…"); const r = await api.read_image_data(b64); busyOverlay(null); applyParsed(r);
  } else if (/\.txt$/i.test(file.name) || file.type.startsWith("text/")) {
    applyParsed(await api.parse_text(await file.text()), file.name);
  } else toast("Drop a .txt file, an image or a .parley project.", { error: true });
});

/* ---------- settings & updates ---------- */
function openSettings() {
  $("#settings").hidden = false;
  $("#allLanguages").checked = S.allLanguages;
  $("#engineInfo").textContent = `edge-tts ${S.info.engine}${S.info.engineCustom ? " (downloaded)" : ""} · repairs itself when the service changes`;
  $("#resetEngineRow").hidden = !S.info.engineCustom;
  $("#versionInfo").textContent = `Parley ${S.info.version}`;
  $("#profilesInfo").textContent = `${S.profiles.length} profiles · characters with these names get their voice automatically`;
  api.cache_size().then((b) => ($("#cacheInfo").textContent = `${(b / 1048576).toFixed(1)} MB · speeds up re-creating unchanged lines.`));
}
$("#settingsBtn").onclick = openSettings;
$$("[data-close]").forEach((b) => (b.onclick = () => ($("#settings").hidden = true)));
$("#settings").onclick = (e) => { if (e.target.id === "settings") $("#settings").hidden = true; };
$("#allLanguages").onchange = (e) => { S.allLanguages = e.target.checked; S.accent = "en"; api.set_settings({ allLanguages: S.allLanguages }); accentOptions(); renderCast(); };
$("#repairBtn").onclick = async () => {
  busyOverlay("Checking for a newer speech engine…"); const r = await api.repair_engine(); busyOverlay(null);
  if (r.ok) { S.info.engine = r.version; S.info.engineCustom = true; openSettings(); toast(`Speech engine updated to ${r.version}.`); }
  else { toast(r.error, { error: !/newest/.test(r.error) }); if (r.update) showUpdate(r.update); }
};
$("#resetEngineBtn").onclick = async () => { const r = await api.reset_engine(); S.info.engine = r.version; S.info.engineCustom = false; openSettings(); toast("Restored the built-in speech engine."); };
$("#checkUpdateBtn").onclick = async () => {
  const r = await api.check_update();
  if (!r.ok) return toast(r.error, { error: true });
  if (r.update) { $("#settings").hidden = true; showUpdate(r.update); } else toast("Parley is up to date.");
};
$("#clearCacheBtn").onclick = async () => { await api.clear_cache(); openSettings(); toast("Audio cache cleared."); };
$("#licensesBtn").onclick = async () => { const p = $("#licenses"); if (p.hidden) p.textContent = await api.licenses(); p.hidden = !p.hidden; };
$("#githubBtn").onclick = () => api.open_url(`https://github.com/${S.info.repo || "arkayaga/parley"}`);

/* ---------- voice profile manager ---------- */
function allVoiceOptions(current) {
  const list = S.voices.filter((v) => S.allLanguages || v.Locale.startsWith("en-"));
  if (current && !list.some((v) => v.ShortName === current)) list.unshift({ ShortName: current, Locale: current.slice(0, 5), Gender: "" });
  const groups = {};
  for (const v of list) (groups[v.Locale] ||= []).push(v);
  return Object.keys(groups).sort().map((loc) => {
    const [l, r] = loc.split("-");
    const label = l === "en" ? `English (${regionName(r)})` : `${langName(l)} (${regionName(r)})`;
    return `<optgroup label="${esc(label)}">` + groups[loc].map((v) =>
      `<option value="${v.ShortName}" ${v.ShortName === current ? "selected" : ""}>${esc(voiceLabel(v))}</option>`).join("") + "</optgroup>";
  }).join("");
}
const shortVoice = (id) => (id || "").split("-").slice(2).join("-").replace(/(Multilingual)?Neural$/, "");

function renderProfiles() {
  const q = norm($("#profileSearch").value || "");
  const box = $("#profileList"); box.innerHTML = "";
  const shown = S.profiles.filter((p) => !q || norm(p.name).includes(q) || (p.aliases || []).some((a) => norm(a).includes(q)));
  const groups = [];
  for (const p of shown) { let g = groups.find((x) => x.name === (p.group || "My profiles")); if (!g) groups.push(g = { name: p.group || "My profiles", items: [] }); g.items.push(p); }
  groups.sort((a, b) => (a.name === "My profiles" ? -1 : b.name === "My profiles" ? 1 : 0));
  for (const g of groups) {
    const h = document.createElement("div"); h.className = "profile-group"; h.textContent = g.name; box.append(h);
    for (const p of g.items) {
      const row = document.createElement("div"); row.className = "profile-row";
      const extra = [p.aliases?.length ? "Also matches: " + p.aliases.join(", ") : "", p.alt ? `Second voice: ${shortVoice(p.alt)}` : "",
        p.rate ? `Speed ${p.rate > 0 ? "+" : ""}${p.rate}%` : "", p.pitch ? `Pitch ${p.pitch > 0 ? "+" : ""}${p.pitch}` : ""].filter(Boolean).join(" · ");
      row.innerHTML = `<input value="${esc(p.name)}" maxlength="60" aria-label="Profile name">
        <select class="voice-select" aria-label="Voice">${allVoiceOptions(p.voice)}</select>
        <button class="mini" title="Listen"><svg><use href="#i-speaker"/></svg></button>
        <button class="mini" title="Delete profile"><svg><use href="#i-x"/></svg></button>
        ${extra ? `<div class="aka">${esc(extra)}</div>` : ""}`;
      const [nameIn, voiceSel] = [$("input", row), $("select", row)];
      const [listen, del] = $$(".mini", row);
      nameIn.onchange = () => {
        const v = nameIn.value.replace(/:/g, "").trim();
        if (!v || S.profiles.some((x) => x !== p && norm(x.name) === norm(v))) {
          toast(v ? `There is already a profile called “${v}”.` : "A profile needs a name.", { error: true }); nameIn.value = p.name; return;
        }
        p.name = v; persistProfiles(); renderCast();
      };
      voiceSel.onchange = () => { p.voice = voiceSel.value; persistProfiles(); renderCast(); };
      listen.onclick = (e) => preview({ voice: p.voice, rate: p.rate || 0, pitch: p.pitch || 0 }, e.currentTarget);
      del.onclick = () => {
        const i = S.profiles.indexOf(p); S.profiles.splice(i, 1); persistProfiles(true); renderProfiles(); renderCast();
        toast(`Deleted “${p.name}”.`, { actions: [["Undo", () => { S.profiles.splice(i, 0, p); persistProfiles(true); renderProfiles(); renderCast(); }]] });
      };
      box.append(row);
    }
  }
  if (!shown.length) box.innerHTML = `<p class="hint" style="padding:12px 4px">${q ? "No profile matches your search." : "No voice profiles yet."}</p>`;
}
function openProfiles() { $("#settings").hidden = true; $("#profilesSheet").hidden = false; $("#profileSearch").value = ""; renderProfiles(); }
function closeProfiles() { $("#profilesSheet").hidden = true; persistProfiles(true); }
$("#manageProfilesBtn").onclick = openProfiles;
$("[data-close-profiles]").onclick = closeProfiles;
$("#profilesSheet").onclick = (e) => { if (e.target.id === "profilesSheet") closeProfiles(); };
$("#profileSearch").oninput = renderProfiles;
$("#addProfileBtn").onclick = () => {
  let name = "New profile", n = 2;
  while (S.profiles.some((p) => norm(p.name) === norm(name))) name = `New profile ${n++}`;
  S.profiles.unshift({ name, voice: "en-US-AvaNeural", alt: null, rate: 0, pitch: 0, aliases: [], group: "My profiles" });
  persistProfiles(true); $("#profileSearch").value = ""; renderProfiles();
  const input = $("#profileList .profile-row input"); input?.focus(); input?.select();
};
$("#resetProfilesBtn").onclick = async () => {
  const sure = window.pywebview ? await api.ask("Restore default profiles?", "Your own profiles and changes will be replaced by the built-in profiles.")
    : confirm("Restore the built-in profiles? Your own profiles will be removed.");
  if (!sure) return;
  const r = await api.reset_profiles(); if (r.ok) { S.profiles = r.profiles; fillProfileNames(); renderProfiles(); renderCast(); toast("Default profiles restored."); }
};
$("#exportProfilesBtn").onclick = async () => {
  const r = await api.export_profiles(S.profiles);
  if (r.ok) toast("Profiles exported. Share the file with colleagues; they can import it in Parley.");
  else if (r.error) toast(r.error, { error: true });
};
$("#importProfilesBtn").onclick = async () => {
  const r = await api.import_profiles(S.profiles);
  if (!r.ok) { if (r.error) toast(r.error, { error: true }); return; }
  S.profiles = r.profiles; fillProfileNames(); renderProfiles(); renderCast(); toast(`Imported ${r.count} profiles.`);
};

function showUpdate(u, needed = false) {
  S.update = u;
  $("#bannerText").textContent = needed
    ? `Parley ${u.version} fixes the speech service. Update now to keep creating audio.`
    : `Parley ${u.version} is available.`;
  $("#bannerAction").textContent = "Update";
  $("#banner").hidden = false;
}
$("#bannerClose").onclick = () => ($("#banner").hidden = true);
$("#bannerAction").onclick = async () => {
  busyOverlay("Downloading the update… Parley will restart."); const r = await api.install_update();
  if (!r.ok || r.browser) busyOverlay(null);
  if (!r.ok) toast(r.error || "The update could not be installed.", { error: true });
};

/* ---------- keyboard ---------- */
document.addEventListener("keydown", (e) => {
  const mod = e.ctrlKey || e.metaKey;
  const typing = /^(TEXTAREA|INPUT|SELECT)$/.test(document.activeElement?.tagName) && document.activeElement.type !== "range";
  if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); saveProject(); }
  else if (mod && e.key.toLowerCase() === "o") { e.preventDefault(); e.stopPropagation(); toggleMenu("#openMenu"); }
  else if (mod && e.key === "Enter") { e.preventDefault(); create(); }
  else if (e.key === "Escape") {
    $$(".menu").forEach((x) => (x.hidden = true)); $("#settings").hidden = true; $("#toast").hidden = true;
    if (!$("#profilesSheet").hidden) closeProfiles();
  }
  else if (e.key === " " && !typing && S.audio) { e.preventDefault(); $("#playBtn").click(); }
});

/* ---------- start ---------- */
async function start() {
  S.info = await api.init();
  S.ocr = S.info.ocr; $("#openImageItem").hidden = !S.ocr;
  S.allLanguages = !!S.info.settings?.allLanguages;
  S.profiles = (await api.get_profiles()) || [];
  fillProfileNames();
  loadState({ mode: "dialogue", lines: [], characters: [], narration: "" });
  const v = await api.voices();
  S.voices = v.voices;
  if (!v.ok) status("Could not load the voice list. Showing a few common voices.", true);
  accentOptions(); renderCast();
  setTimeout(async () => { const r = await api.check_update(); if (r.ok && r.update) showUpdate(r.update); }, 2500);
}
window.parley = {
  onEvent(name, data) {
    if (name === "progress") { progress(Math.max(0.02, data.fraction)); status(data.message); }
  },
};
if (window.pywebview?.api) start();
else {
  let started = false;
  const go = () => { if (!started) { started = true; start(); } };
  window.addEventListener("pywebviewready", go);
  setTimeout(() => { if (!window.pywebview) go(); }, 400);
}
