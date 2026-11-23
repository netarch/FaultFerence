// Inspector Switch
// Pure vanilla JS + HTML5 2D Canvas + custom Sprites (`sprites.js`).
"use strict";

const $ = (id) => document.getElementById(id);
const Sprites = window.Sprites;
const Sound = window.GameAudio;
const Engine = window.LocalEngine;

const MODE_LABELS = {
  silent_drop: "Silent Drop",
  blackhole: "Blackhole",
  intermittent: "Intermittent",
  high_latency: "High Latency",
};

const LENS_CARDS = [
  {
    code: "flock",
    icon: "flock",
    name: "Flock",
    desc: "Weighs evidence across rounds using probabilities",
  },
  {
    code: "set",
    icon: "set_lens",
    name: "Set ∩",
    desc: "Rules switches in or out strictly by pass / fail",
  },
];

const IMPACT_WORDS = {
  active_probe: "Minimal",
  packet_mirror: "Low",
  subtle_weight_shift: "Very Low",
  flow_link_drain: "Low",
  flow_group_split: "Moderate",
  full_link_drain: "High",
  component_reset: "Heavy Outage",
};

const TAG_LABELS = {
  "no-drain": "Protected Link (No Detours)",
  "no-reset": "Critical Switch (No Reboot)",
  "no-probe": "No Ping Origination",
  blackbox: "External Peer (Read-Only)",
};

const G = {
  cfg: null,
  state: null,
  actions: [],
  visibleWeapons: [],
  fives: null,
  fivesHint: false,
  fivesUnlocked: false,
  deckOpen: false,
  peekFault: false,
  infBase: "flock",       // Flock active by default at start
  pathAware: false,
  armedWeapon: null,
  selected: null,
  popActions: [],
  hovered: null,
  nearest: null,
  busy: false,
  autoPlay: false,
  startScreenOpen: true,
  sloBudgetSec: 150,
  wallElapsedSec: 0,
  sloViolated: false,

  canvas: null,
  ctx: null,
  heroCanvas: null,
  heroCtx: null,
  vw: 800,
  vh: 520,
  dpr: 1,
  keys: new Set(),
  det: {
    x: 120,
    y: 260,
    tx: null,
    ty: null,
    onArrive: null,
    facing: 1,
    walkPhase: 0,
    jumpT: 0,
    mood: "idle",
    moodUntil: 0,
    say: "",
    sayKind: "info",
    sayUntil: 0,
  },
  shake: 0,
  fx: [],
  lastTs: performance.now(),
};

// ---------------------------------------------------------------------------
// Formatting Helpers
// ---------------------------------------------------------------------------
function currentInfCode() {
  return G.pathAware ? `${G.infBase}_tr` : G.infBase;
}

function fmtTime(sec) {
  return sec >= 120 ? `${(sec / 60).toFixed(1)}m` : `${Math.round(sec)}s`;
}

function fmtCountdown(sec) {
  const s = Math.max(0, Math.ceil(sec));
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${rem < 10 ? "0" : ""}${rem}`;
}

function effectiveStatus() {
  if (!G.state) return "playing";
  if (G.sloViolated && G.state.stats.status === "playing") return "slo_violated";
  return G.state.stats.status;
}

function totalElapsedSec() {
  if (!G.state) return 0;
  return G.wallElapsedSec + G.state.stats.time_sec;
}

function sloRemainingSec() {
  return Math.max(0, G.sloBudgetSec - totalElapsedSec());
}

function renderSloHud() {
  const rem = sloRemainingSec();
  $("h-time").textContent = fmtCountdown(rem);
  const card = $("hud-slo-card");
  card.classList.remove("warn", "danger", "violated");
  if (G.sloViolated) {
    card.classList.add("violated");
  } else if (effectiveStatus() === "playing") {
    if (rem <= 20) card.classList.add("danger");
    else if (rem <= 45) card.classList.add("warn");
  }
}

function triggerSloViolation() {
  if (G.sloViolated || !G.state || G.state.stats.status !== "playing") return;
  G.sloViolated = true;
  G.autoPlay = false;
  setSolveBtnLabel(false);
  setArmedWeapon(null);
  closeDeck();
  closePopover();
  G.det.tx = null;
  G.det.ty = null;
  G.det.onArrive = null;
  G.shake = 14;
  Sound.sfx("fired");
  detectiveSay("SLO violated. You are fired!", "bad", 9000, "shocked");
  $("fired-sub").textContent = `Faulty switch was ${G.state.failure.culprit_name}.`;
  $("slo-fired-overlay").classList.remove("hidden");
  renderHud();
  renderWordleGrid(false);
  refreshFivesHint();
}

function fmtImpactHud(d) {
  if (d < 0.01) return "None";
  if (d < 1.0) return "Low";
  if (d < 5.0) return "Medium";
  return "High";
}

function toast(msg, bad = false) {
  const el = $("toast");
  el.textContent = msg;
  el.className = bad ? "toast on bad" : "toast on";
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.className = "toast"; }, 2500);
}

function detectiveSay(text, kind = "info", ms = 4400, mood = null) {
  G.det.say = text;
  G.det.sayKind = kind;
  G.det.sayUntil = performance.now() + ms;
  if (mood) {
    G.det.mood = mood;
    G.det.moodUntil = performance.now() + Math.min(ms, 2800);
  }
}

function suspectNodes() {
  return G.state.nodes.filter((n) => n.in_pool);
}

function analyzeOutcome(res) {
  if (!res.telemetry || res.telemetry.length === 0) {
    return { badge: "", clean: true, say: "" };
  }
  if (res.fault_active === false) {
    return { badge: "Quiet Round", clean: true, say: "No drops seen right now" };
  }
  const probe = res.telemetry.find((r) => r.kind === "probe");
  if (probe) {
    return probe.bad === 0
      ? { badge: "✓ Ping Clean!", clean: true, say: "Pings arrived safely" }
      : { badge: "✕ Pings Dropped!", clean: false, say: "Test pings hit packet loss" };
  }
  const mir = res.telemetry.find((r) => r.kind === "mirror");
  if (mir) {
    return mir.bad === 0
      ? { badge: "✓ Clean Here!", clean: true, say: "Packets look healthy at this switch" }
      : { badge: "✕ Bad Already!", clean: false, say: "Packets are already failing here" };
  }
  const flows = res.telemetry.filter((r) => r.kind === "flow");
  if (flows.length > 0) {
    const curr = flows.reduce((s, r) => s + r.rate, 0) / flows.length;
    const base = G.state.baseline_loss_rate;
    const bypassed = curr <= Math.max(0.0004, base * 0.2);
    if (bypassed) {
      return { badge: "✓ Loss Stopped!", clean: true, say: "Detour avoided the faulty switch!" };
    }
    return { badge: "⚠ Still Dropping", clean: false, say: "Traffic still hits the fault" };
  }
  return { badge: "", clean: true, say: "" };
}

// ---------------------------------------------------------------------------
// Room Coordinates & Hit Testing
// ---------------------------------------------------------------------------
function roomPad() {
  return { left: 52, right: 56, top: 52, bottom: 72 };
}

function normToPx(nx, ny) {
  const p = roomPad();
  const w = Math.max(180, G.vw - p.left - p.right);
  const h = Math.max(150, G.vh - p.top - p.bottom);
  return { x: p.left + nx * w, y: p.top + ny * h };
}

function rackDims() {
  const compact = G.state && G.state.nodes.length > 18;
  return { rw: compact ? 30 : 40, rh: compact ? 34 : 44, compact };
}

function nodePos(n) {
  return normToPx(n.x, n.y);
}

function nodeById(id) {
  return G.state.nodes.find((n) => n.id === id);
}

function edgeByEnds(u, v) {
  const a = Math.min(u, v), b = Math.max(u, v);
  return G.state.edges.find((e) => e.u === a && e.v === b);
}

function edgeSocket(e) {
  const a = nodePos(nodeById(e.u));
  const b = nodePos(nodeById(e.v));
  const t = e.socket_t;
  return {
    x: a.x + (b.x - a.x) * t,
    y: a.y + (b.y - a.y) * t,
    ax: a.x,
    ay: a.y,
    bx: b.x,
    by: b.y,
  };
}

function ptSegDist(px, py, ax, ay, bx, by) {
  const dx = bx - ax, dy = by - ay;
  const len = Math.hypot(dx, dy);
  const margin = len < 80 ? 0.24 : 0.16;
  const len2 = dx * dx + dy * dy;
  const t = len2 > 1e-6 ? Math.max(margin, Math.min(1 - margin, ((px - ax) * dx + (py - ay) * dy) / len2)) : 0.5;
  const cx = ax + t * dx, cy = ay + t * dy;
  return Math.hypot(px - cx, py - cy);
}

function hitTestRoom(mx, my) {
  if (!G.state) return null;

  let bestSock = null, bestSD = 11;
  for (const e of G.state.edges) {
    const s = edgeSocket(e);
    const d = Math.hypot(mx - s.x, my - s.y);
    if (d < bestSD) {
      bestSD = d;
      bestSock = { type: "edge", u: e.u, v: e.v };
    }
  }
  if (bestSock) return bestSock;

  const { rw, rh } = rackDims();
  for (const n of G.state.nodes) {
    const p = nodePos(n);
    if (Math.abs(mx - p.x) <= rw / 2 + 2 && Math.abs(my - p.y) <= rh / 2 + 2) {
      return { type: "node", id: n.id };
    }
  }

  let bestEdge = null, bestED = 12;
  for (const e of G.state.edges) {
    const a = nodePos(nodeById(e.u));
    const b = nodePos(nodeById(e.v));
    const d = ptSegDist(mx, my, a.x, a.y, b.x, b.y);
    if (d < bestED) {
      bestED = d;
      bestEdge = { type: "edge", u: e.u, v: e.v };
    }
  }
  if (bestEdge) return bestEdge;

  for (const bn of G.state.bg_nodes) {
    const bp = normToPx(bn.x, bn.y);
    if (Math.abs(mx - bp.x) <= 18 && Math.abs(my - bp.y) <= 18) {
      return { type: "bg", name: bn.name, active: bn.active };
    }
  }
  return null;
}

function targetStandPos(target) {
  if (target.type === "node") {
    const p = nodePos(nodeById(target.id));
    const offsetY = p.y + 38 < G.vh - 64 ? 36 : -38;
    return { x: p.x, y: p.y + offsetY, anchorX: p.x, anchorY: p.y };
  }
  const e = edgeByEnds(target.u, target.v);
  const s = edgeSocket(e);
  return { x: s.x, y: Math.min(G.vh - 64, s.y + 22), anchorX: s.x, anchorY: s.y };
}

// ---------------------------------------------------------------------------
// Action Pack Card Deck (`Actions` Button)
// ---------------------------------------------------------------------------
function actionsForTarget(target) {
  return G.actions.filter((a) => {
    const anc = a.anchor;
    if (target.type === "node" && anc.type === "node") return anc.id === target.id;
    if (target.type === "edge" && anc.type === "edge") {
      const u = Math.min(target.u, target.v), v = Math.max(target.u, target.v);
      return anc.u === u && anc.v === v;
    }
    return false;
  });
}

function weaponMatchesTarget(kind, target) {
  return actionsForTarget(target).filter((a) => a.kind === kind);
}

function isFivesOnlyKind(kind) {
  return kind === "subtle_weight_shift";
}

async function unlockFives() {
  G.fivesUnlocked = true;
  G.fivesHint = true;
  Sound.sfx("unlock");
  if (G.infBase !== "flock") {
    G.infBase = "flock";
    await switchInferenceMode();
  } else {
    await refreshFivesHint();
  }
  toast("Unlocked with FIVES — Dial 20% enabled!");
  if (G.deckOpen) renderDeckCards();
  if (G.selected) openPopover(G.selected);
}

function openDeck() {
  if (!G.state || effectiveStatus() !== "playing") return;
  Sound.sfx("ui");
  closePopover();
  G.deckOpen = true;
  renderDeckCards();
  $("deck-overlay").classList.remove("hidden");
}

function closeDeck() {
  G.deckOpen = false;
  $("deck-overlay").classList.add("hidden");
}

function toggleDeck() {
  if (G.deckOpen) closeDeck();
  else openDeck();
}

function setArmedWeapon(kind) {
  if (!kind || G.armedWeapon === kind) {
    G.armedWeapon = null;
    $("armed-banner").classList.add("hidden");
    return;
  }
  if (isFivesOnlyKind(kind) && !G.fivesUnlocked) {
    unlockFives();
    return;
  }
  Sound.sfx("ui");
  closeDeck();
  closePopover();
  G.armedWeapon = kind;
  const wMeta = G.cfg.weapons.find((w) => w.kind === kind);
  const targetWord = wMeta.target === "node" ? "switch" : "link";
  $("armed-text").innerHTML = `${Sprites.icon(kind, 18)} <b>${wMeta.short}</b>: click a highlighted ${targetWord}`;
  $("armed-banner").classList.remove("hidden");
}

function renderDeckCards() {
  if (!G.cfg || !G.state) return;

  const lensEl = $("lens-cards");
  lensEl.innerHTML = "";
  for (const lc of LENS_CARDS) {
    const active = G.infBase === lc.code;
    const card = document.createElement("button");
    card.type = "button";
    card.className = "play-card lens-card" + (active ? " active-lens" : "");
    card.innerHTML = `
      <div class="card-art">${Sprites.icon(lc.icon, 26)}</div>
      <div style="min-width:0">
        <div class="card-name">${lc.name}</div>
        <div class="card-desc">${lc.desc}</div>
      </div>
      ${active ? '<span class="active-pill">ACTIVE</span>' : ""}
    `;
    card.addEventListener("click", async () => {
      Sound.sfx("ui");
      if (G.infBase !== lc.code) {
        G.infBase = lc.code;
        await switchInferenceMode();
        renderDeckCards();
      }
    });
    lensEl.appendChild(card);
  }

  const actEl = $("action-cards");
  actEl.innerHTML = "";
  G.visibleWeapons = G.cfg.weapons.filter((w) => G.actions.some((a) => a.kind === w.kind));

  G.visibleWeapons.forEach((w, idx) => {
    const allOfKind = G.actions.filter((a) => a.kind === w.kind);
    const sample = allOfKind.find((a) => a.violation === null) || allOfKind[0];
    const fivesLocked = isFivesOnlyKind(w.kind) && !G.fivesUnlocked;
    const card = document.createElement("button");
    card.type = "button";
    card.className = fivesLocked
      ? "play-card fives-locked-card"
      : `play-card plane-${sample.plane}`;
    const artHtml = fivesLocked
      ? `<div class="card-art">${Sprites.icon(w.kind, 26)}<span class="lock-badge-mini">${Sprites.icon("lock", 12)}</span></div>`
      : `<div class="card-art">${Sprites.icon(w.kind, 26)}</div>`;
    const footHtml = fivesLocked
      ? `<div class="card-foot"><span class="unlock-fives-pill">${Sprites.icon("lock", 11)} Unlock with FIVES</span></div>`
      : `<div class="card-foot">
           <span>Time: ~${fmtTime(sample.est_time)}</span>
           <span>${IMPACT_WORDS[w.kind]}</span>
         </div>`;
    card.innerHTML = `
      <div style="display:flex;justify-content:space-between;width:100%;align-items:center">
        ${artHtml}
        <kbd>${idx + 1}</kbd>
      </div>
      <div>
        <div class="card-name">${w.short}</div>
        <div class="card-desc">${fivesLocked ? "Subtle fractional shift (FIVES only)" : w.hint}</div>
      </div>
      ${footHtml}
    `;
    card.addEventListener("click", () => {
      if (fivesLocked) unlockFives();
      else setArmedWeapon(w.kind);
    });
    actEl.appendChild(card);
  });
}

// ---------------------------------------------------------------------------
// Story-Telling Visual Action Animations
// ---------------------------------------------------------------------------
function receiverHostPx() {
  const hb = G.state.bg_nodes.find((b) => b.key === "host:b");
  return hb ? normToPx(hb.x, hb.y) : { x: G.vw - 54, y: G.vh * 0.5 };
}

function triggerStoryFx(res) {
  const action = res.action;
  const stPos = targetStandPos(action.anchor);

  if (res.status === "rejected") {
    G.shake = 10;
    G.fx.push({ kind: "shield", propKind: "shield", x: stPos.anchorX, y: stPos.anchorY, t: 0, dur: 1.05 });
    G.det.x = Math.max(36, Math.min(G.vw - 36, G.det.x - G.det.facing * 20));
    G.det.jumpT = 0.34;
    return;
  }

  const out = analyzeOutcome(res);

  if (action.kind === "active_probe") {
    const srcP = nodePos(nodeById(action.params.src));
    const dstP = nodePos(nodeById(action.params.dst));
    G.fx.push({
      kind: "probe",
      propKind: "active_probe",
      x: srcP.x,
      y: srcP.y,
      x2: dstP.x,
      y2: dstP.y,
      clean: out.clean,
      badge: out.badge,
      t: 0,
      dur: 1.35,
    });
  } else {
    G.fx.push({
      kind: "prop",
      propKind: action.kind,
      x: stPos.anchorX,
      y: stPos.anchorY,
      t: 0,
      dur: 1.15,
    });
    // For control / reboot / tap actions, pop outcome badge right where the result is observed!
    const bx = action.kind === "packet_mirror" ? stPos.anchorX : receiverHostPx().x;
    const by = action.kind === "packet_mirror" ? stPos.anchorY - 34 : receiverHostPx().y - 30;
    if (out.badge) {
      G.fx.push({
        kind: "floatTag",
        x: bx,
        y: by,
        text: out.badge,
        clean: out.clean,
        t: 0,
        dur: 1.7,
      });
    }
  }

  // Pop green `✓ Out` badges over every switch newly cleared in this round!
  for (const remId of res.removed) {
    const rn = nodeById(remId);
    if (rn) {
      const rp = nodePos(rn);
      G.fx.push({
        kind: "clearedPop",
        x: rp.x,
        y: rp.y - 24,
        t: 0,
        dur: 1.3,
      });
    }
  }
}

function triggerConfetti() {
  const palette = ["#538d4e", "#e2a432", "#3568d4", "#e5484d", "#1e9e8e"];
  for (let i = 0; i < 40; i++) {
    const ang = Math.random() * Math.PI * 2;
    const spd = 60 + Math.random() * 150;
    G.fx.push({
      kind: "confetti",
      x: G.det.x,
      y: G.det.y - 24,
      vx: Math.cos(ang) * spd,
      vy: Math.sin(ang) * spd - 95,
      color: palette[i % palette.length],
      t: 0,
      dur: 1.35 + Math.random() * 0.5,
    });
  }
  G.det.jumpT = 0.6;
}

// ---------------------------------------------------------------------------
// Bigger, Context-Rich Switch / Link Action Card
// ---------------------------------------------------------------------------
function closePopover() {
  G.selected = null;
  G.popActions = [];
  $("action-popover").classList.add("hidden");
}

function actionExplain(a) {
  if (a.kind === "active_probe") return "Sends test pings from here to receiver to see if they drop.";
  if (a.kind === "packet_mirror") return "Checks packets passing here to see if loss started upstream.";
  if (a.kind === "subtle_weight_shift") return "Shifts most of the flow onto sibling links without cutting this link.";
  if (a.kind === "flow_link_drain") return "Reroutes the affected flow around this link.";
  if (a.kind === "flow_group_split") return "Drains half of the outgoing branches at once.";
  if (a.kind === "full_link_drain") return "Shuts this link down for all traffic in the network.";
  if (a.kind === "component_reset") return "Restarts this switch to see if the symptom disappears.";
  return a.subtitle;
}

function popoverActionTitle(a) {
  if (a.kind === "active_probe") return "Send Ping";
  if (a.kind === "packet_mirror") return "Tap Traffic";
  if (a.kind === "subtle_weight_shift") return "Dial 20%";
  if (a.kind === "flow_link_drain") return "Detour Flow";
  if (a.kind === "flow_group_split") return "Split Branches";
  if (a.kind === "full_link_drain") return "Shut Link";
  if (a.kind === "component_reset") return "Reboot Switch";
  return a.title;
}

function cleanViolationReason(v) {
  if (!v) return "";
  if (v.startsWith("Protected spine")) return "Protected spine — reboot disabled";
  if (v.startsWith("Protected switch")) return "Protected switch — detour disabled";
  if (v.startsWith("No filtered tap") || v.startsWith("No tap hardware") || v.startsWith("No raw tap")) {
    return "No packet-tap hardware here";
  }
  if (v.startsWith("No probe support")) return "Ping origination disabled here";
  if (v.startsWith("External peer")) return "External peer — read-only";
  if (v.startsWith("Flow endpoint")) return "Edge switch — reboot disabled";
  return v.replace(/\s*\([^)]*\)/g, "");
}

function openPopover(target, filterKind = null) {
  const wasHidden = $("action-popover").classList.contains("hidden");
  G.selected = target;
  const pop = $("action-popover");
  const list = $("pop-list");
  const pill = $("pop-status-pill");
  list.innerHTML = "";
  const gameDone = effectiveStatus() !== "playing";

  let acts = actionsForTarget(target);
  if (filterKind) acts = acts.filter((a) => a.kind === filterKind);
  G.popActions = acts;

  if (target.type === "node") {
    const n = nodeById(target.id);
    $("pop-title").innerHTML = `${Sprites.icon("rack", 18)} <span>${n.name}</span>`;
    if (n.is_endpoint) {
      pill.textContent = "Edge Switch";
      pill.className = "status-pill edge";
    } else if (n.suspect) {
      pill.textContent = "Suspect";
      pill.className = "status-pill suspect";
    } else {
      pill.textContent = "Ruled Out";
      pill.className = "status-pill out";
    }
  } else {
    const nu = nodeById(target.u), nv = nodeById(target.v);
    const edge = edgeByEnds(target.u, target.v);
    $("pop-title").innerHTML = `${Sprites.icon("cable", 18)} <span>${nu.name} ↔ ${nv.name}</span>`;
    const active = edge.flow_weight > 0.001;
    pill.textContent = active ? "Active Link" : "Detoured";
    pill.className = "status-pill " + (active ? "edge" : "out");
  }

  const bestKey = G.fivesHint && G.fives && G.fives.best ? G.fives.best.key : null;

  acts.forEach((a) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.disabled = gameDone;
    const label = popoverActionTitle(a);
    const isBest = bestKey === a.key;
    const fivesLocked = isFivesOnlyKind(a.kind) && !G.fivesUnlocked;
    const isPolicyLocked = a.violation !== null;

    if (fivesLocked) {
      btn.className = "act-btn fives-locked-act";
      btn.innerHTML = `
        <span class="act-ic">
          ${Sprites.icon(a.kind, 22)}
          <span class="lock-badge-mini">${Sprites.icon("lock", 12)}</span>
        </span>
        <div class="act-main">
          <div class="act-t">
            <span>${label}</span>
            <span class="unlock-fives-pill">${Sprites.icon("lock", 11)} Unlock with FIVES</span>
          </div>
          <div class="act-s">Subtle fractional shift — click to unlock FIVES.</div>
        </div>
      `;
      btn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        unlockFives();
      });
    } else if (isPolicyLocked) {
      btn.className = `act-btn plane-${a.plane} locked-act`;
      btn.innerHTML = `
        <span class="act-ic">
          ${Sprites.icon(a.kind, 22)}
          <span class="lock-badge-mini">${Sprites.icon("lock", 12)}</span>
        </span>
        <div class="act-main">
          <div class="act-t"><span>${label}</span></div>
          <div class="act-s lock-hint">${cleanViolationReason(a.violation)}</div>
        </div>
      `;
      btn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        walkAndApply(a);
      });
    } else {
      btn.className =
        `act-btn plane-${a.plane}` +
        (a.tried ? " tried" : "") +
        (isBest ? " fives-best" : "");
      const star = isBest ? Sprites.icon("star", 14) : "";
      btn.innerHTML = `
        <span class="act-ic">${Sprites.icon(a.kind, 22)}</span>
        <div class="act-main">
          <div class="act-t"><span>${label}</span>${star}</div>
          <div class="act-s">${actionExplain(a)}</div>
          <div class="act-pills">
            <span class="meta-chip">Time: ~${fmtTime(a.est_time)}</span>
            <span class="meta-chip">Impact: ${IMPACT_WORDS[a.kind]}</span>
          </div>
        </div>
      `;
      btn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        walkAndApply(a);
      });
    }
    list.appendChild(btn);
  });

  if (target.type === "node" && !filterKind) {
    const n = nodeById(target.id);
    if (n.in_pool) {
      const accBtn = document.createElement("button");
      accBtn.type = "button";
      accBtn.disabled = gameDone;
      accBtn.className = "act-btn accuse-btn";
      accBtn.innerHTML = `
        <span class="act-ic">${Sprites.icon("accuse", 22)}</span>
        <div class="act-main">
          <div class="act-t"><span>Accuse as Faulty</span></div>
          <div class="act-s">Declare this switch the culprit and close the case.</div>
        </div>
      `;
      accBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        accuseSwitch(n.id);
      });
      list.appendChild(accBtn);
    }
  }

  if (wasHidden) Sound.sfx("ui");
  pop.classList.remove("hidden");
  positionPopover(target);
}

function positionPopover(target) {
  const pop = $("action-popover");
  if (pop.classList.contains("hidden")) return;
  const st = targetStandPos(target);
  const popW = 348;
  const popH = pop.offsetHeight || 240;
  let left = st.anchorX + 34;
  if (left + popW > G.vw - 12) left = st.anchorX - popW - 34;
  left = Math.max(12, Math.min(G.vw - popW - 12, left));
  const top = Math.max(10, Math.min(G.vh - popH - 14, st.anchorY - popH * 0.45));
  pop.style.left = `${left}px`;
  pop.style.top = `${top}px`;
}

function walkDetectiveTo(target, cb) {
  const dest = targetStandPos(target);
  if (dest.x < G.det.x - 2) G.det.facing = -1;
  if (dest.x > G.det.x + 2) G.det.facing = 1;
  G.det.tx = dest.x;
  G.det.ty = dest.y;
  G.det.onArrive = cb;
}

function walkAndApply(action) {
  if (G.busy || !G.state || effectiveStatus() !== "playing") return;
  setArmedWeapon(null);
  closeDeck();
  closePopover();
  const dest = targetStandPos(action.anchor);
  const dist = Math.hypot(G.det.x - dest.x, G.det.y - dest.y);
  if (dist < 26) {
    applyAction(action);
  } else {
    walkDetectiveTo(action.anchor, () => applyAction(action));
  }
}

// ---------------------------------------------------------------------------
// HUD, Suspect Grid & FIVES Hint / Solve
// ---------------------------------------------------------------------------
function renderHud() {
  const s = G.state.stats;
  $("h-moves").textContent = String(s.actions);
  const rej = $("h-rej");
  if (s.rejected > 0) {
    rej.innerHTML = `${Sprites.icon("shield", 12)} ${s.rejected}`;
    rej.classList.remove("hidden");
  } else {
    rej.classList.add("hidden");
  }
  renderSloHud();
  $("h-impact").textContent = fmtImpactHud(s.disruption);
  $("h-eq").textContent = String(s.eq_size);
  $("h-pool").textContent = ` / ${s.pool_size}`;

  const done = effectiveStatus() !== "playing";
  $("btn-actions").disabled = done;
  $("btn-fives-hint").disabled = done;
  if (!G.autoPlay) $("btn-fives-solve").disabled = done;
}

function shortColName(name) {
  if (name.length <= 5) return name;
  let s = name
    .replace(/^sw-dcldc/i, "dc")
    .replace(/^sw-acbdc/i, "ac")
    .replace(/^bd-bd-/i, "b-")
    .replace(/^rtr-/i, "r-")
    .replace(/^dist/i, "d")
    .replace(/^core/i, "c")
    .replace(/^agg/i, "a")
    .replace(/^tor/i, "t")
    .replace(/^sw-/i, "s")
    .replace(/^bd-/i, "b-");
  if (s.length <= 5) return s;
  const tail = s.match(/\d+(?:-\d+)?$/);
  if (tail && tail[0].length < 5) {
    return s.slice(0, 5 - tail[0].length) + tail[0];
  }
  return s.slice(0, 5);
}

function renderWordleGrid(animateLastRow) {
  const st = G.state;
  const sNodes = suspectNodes();
  const cols = sNodes.length;
  const header = $("wordle-header");
  const rowsEl = $("wordle-rows");
  header.style.setProperty("--cols", cols);
  rowsEl.style.setProperty("--cols", cols);

  header.innerHTML = "";
  const corner = document.createElement("div");
  corner.className = "w-step-tag";
  corner.textContent = "ROUND";
  header.appendChild(corner);

  const showCulpritCol = G.peekFault || effectiveStatus() !== "playing";
  for (const n of sNodes) {
    const lbl = document.createElement("div");
    lbl.className = "w-col-lbl" + (showCulpritCol && n.id === st.failure.culprit ? " culprit-col" : "");
    lbl.textContent = shortColName(n.name);
    lbl.title = `${n.name} (${n.suspect ? "suspect" : "ruled out"}) — click to inspect`;
    lbl.addEventListener("click", () => {
      walkDetectiveTo({ type: "node", id: n.id }, () => openPopover({ type: "node", id: n.id }));
    });
    header.appendChild(lbl);
  }

  rowsEl.innerHTML = "";
  const lastIdx = st.history.length - 1;

  st.history.forEach((h, rIdx) => {
    const row = document.createElement("div");
    const isLast = animateLastRow && rIdx === lastIdx && rIdx > 0;
    row.className = "w-row" + (isLast && h.status === "rejected" ? " shake" : "");

    const tag = document.createElement("div");
    tag.className = "w-step-tag";
    if (h.status === "observe") {
      tag.innerHTML = `${Sprites.icon("eye", 15)}<span>Start</span>`;
      tag.title = "Initial passive check";
    } else if (h.status === "rejected") {
      tag.innerHTML = `${Sprites.icon("shield", 14)}<span>Blocked</span>`;
      tag.title = `${h.action.title} — ${h.reason}`;
    } else {
      const out = analyzeOutcome(h);
      tag.innerHTML = `${Sprites.icon(h.action.icon, 15)}<span>#${h.move_num}</span>`;
      tag.title = `${h.action.title} (~${fmtTime(h.time)})${out.say ? " — " + out.say : ""}`;
    }
    row.appendChild(tag);

    if (h.status === "rejected") {
      const ban = document.createElement("div");
      ban.className = "w-reject-banner";
      ban.innerHTML = `${Sprites.icon("shield", 14)}<span>${h.reason}</span>`;
      ban.title = `${h.action.title}: ${h.reason}`;
      row.appendChild(ban);
    } else {
      const eqSet = new Set(h.eq_nodes);
      const solvedHere =
        rIdx === lastIdx && st.stats.status === "localized" && h.eq_nodes.length === 1;

      sNodes.forEach((n, cIdx) => {
        const tile = document.createElement("div");
        const inEq = eqSet.has(n.id);
        const postP = h.posteriors[String(n.id)];
        let cls = "w-tile filled ";
        if (solvedHere && inEq && n.id === st.failure.culprit) {
          cls += "green";
        } else if (inEq) {
          cls += postP < 0.08 && cols > 4 ? "amber low-p" : "amber";
        } else {
          cls += "grey";
        }
        if (isLast) {
          cls += " flip";
          tile.style.animationDelay = `${cIdx * 36}ms`;
        }
        tile.className = cls;
        tile.title = `${n.name}: ${inEq ? "Suspect" : "Ruled out"}`;
        row.appendChild(tile);
      });
    }
    rowsEl.appendChild(row);
  });

  const appliedSoFar = st.stats.actions;
  for (let m = appliedSoFar + 1; m <= 5 && effectiveStatus() === "playing"; m++) {
    const row = document.createElement("div");
    row.className = "w-row";
    const tag = document.createElement("div");
    tag.className = "w-step-tag";
    tag.style.opacity = "0.35";
    tag.textContent = `· #${m}`;
    row.appendChild(tag);
    for (let c = 0; c < cols; c++) {
      const tile = document.createElement("div");
      tile.className = "w-tile";
      row.appendChild(tile);
    }
    rowsEl.appendChild(row);
  }

  const sc = $("wordle-scroll");
  sc.scrollTop = sc.scrollHeight;
  renderEndCard();
}

function buildShareText() {
  const st = G.state;
  const s = st.stats;
  const status = effectiveStatus();
  const sNodes = suspectNodes();
  const statusLabel =
    status === "localized"
      ? "Solved"
      : status === "slo_violated"
      ? "SLO violated. You are fired!"
      : "Unsolved";
  const lines = [
    `Inspector Switch · ${st.topology}`,
    `${statusLabel} (${s.actions} actions · ${fmtImpactHud(s.disruption)} impact)`,
  ];
  const lastIdx = st.history.length - 1;
  st.history.forEach((h, rIdx) => {
    if (h.status === "gadget") return;
    if (h.status === "rejected") {
      lines.push("🟥".repeat(sNodes.length));
      return;
    }
    const eq = new Set(h.eq_nodes);
    const solved = rIdx === lastIdx && status === "localized";
    const rowStr = sNodes
      .map((n) => {
        if (solved && eq.has(n.id) && n.id === st.failure.culprit) return "🟩";
        return eq.has(n.id) ? "🟨" : "⬜";
      })
      .join("");
    lines.push(rowStr);
  });
  return lines.join("\n");
}

function renderEndCard() {
  const st = G.state;
  const s = st.stats;
  const status = effectiveStatus();
  const card = $("end-card");
  if (status === "playing") {
    card.classList.add("hidden");
    return;
  }
  card.classList.remove("hidden");
  if (status === "localized") {
    $("end-headline").innerHTML = `${Sprites.icon("trophy", 19)}<span>Solved! Faulty switch: ${st.failure.culprit_name}</span>`;
    $("end-compare").textContent =
      `${s.actions} actions · ${fmtCountdown(sloRemainingSec())} SLO left · ${fmtImpactHud(s.disruption)} impact`;
  } else if (status === "slo_violated") {
    $("end-headline").innerHTML = `${Sprites.icon("warning", 19)}<span>SLO violated. You are fired!</span>`;
    $("end-compare").textContent =
      `Fault was ${st.failure.culprit_name} · ${s.actions} actions · ${fmtImpactHud(s.disruption)} impact`;
  } else if (status === "mislocalized") {
    const wrong = nodeById(st.eq_set[0]).name;
    $("end-headline").innerHTML = `${Sprites.icon("shield", 19)}<span>Picked ${wrong} — fault was ${st.failure.culprit_name}</span>`;
    $("end-compare").textContent =
      `${s.actions} actions · ${fmtImpactHud(s.disruption)} impact`;
  } else {
    $("end-headline").innerHTML = `${Sprites.icon("warning", 19)}<span>${st.failure.culprit_name} slipped away!</span>`;
    $("end-compare").textContent =
      `${s.actions} actions · ${fmtImpactHud(s.disruption)} impact`;
  }
  $("end-emoji").textContent = buildShareText();
}

async function refreshFivesHint() {
  if (!G.state) return;
  $("btn-fives-hint").classList.toggle("on", G.fivesHint);
  if (!G.fivesHint || effectiveStatus() !== "playing") {
    G.fives = null;
    $("fives-banner").classList.add("hidden");
    return;
  }
  const lam = $("lambda").value;
  const r = Engine.fives(G.state.id, lam, 1, 3);
  G.fives = r;
  $("fives-banner").classList.remove("hidden");
  if (!r.best) {
    $("fives-hint-text").innerHTML = `${Sprites.icon("monocle", 17)}<span>No safe move splits the remaining suspects</span>`;
    $("fives-hint-why").textContent = "";
    $("btn-fives-step").disabled = true;
    return;
  }
  const b = r.best;
  $("fives-hint-text").innerHTML = `${Sprites.icon("monocle", 18)}<span>Try: ${b.title}</span>`;
  $("fives-hint-why").textContent =
    `Splits ${G.state.stats.eq_size} suspects into ${b.partition.join(" vs ")} · ~${fmtTime(b.est_time)} · ${IMPACT_WORDS[b.kind]} impact`;
  $("btn-fives-step").disabled = false;
}

// ---------------------------------------------------------------------------
// Game Actions (100% Client-Side via `window.LocalEngine`)
// ---------------------------------------------------------------------------
async function startNewCase(seedOverride) {
  G.autoPlay = false;
  G.fivesHint = false;
  G.fivesUnlocked = false;
  setSolveBtnLabel(false);
  setArmedWeapon(null);
  closeDeck();
  closePopover();
  $("cfg-menu").classList.add("hidden");
  $("slo-fired-overlay").classList.add("hidden");
  G.busy = true;
  const payload = {
    topology: $("topology").value,
    failure_mode: $("failure_mode").value,
    inference: currentInfCode(),
    seed: seedOverride !== undefined ? String(seedOverride) : "",
    num_pairs: 1,
    drop_prob: 0.03,
    cred_mass: 0.95,
  };
  const data = Engine.newSession(payload);
  G.state = data.state;
  G.actions = data.actions;
  G.fx = [];
  G.wallElapsedSec = 0;
  G.sloViolated = false;
  G.sloBudgetSec = Math.max(150, Math.ceil((G.state.stats.pool_size * 22) / 10) * 10);
  G.visibleWeapons = G.cfg.weapons.filter((w) => G.actions.some((a) => a.kind === w.kind));

  const srcNode = nodeById(G.state.failure.pairs[0][0]);
  const sp = nodePos(srcNode);
  G.det.x = Math.min(G.vw - 50, sp.x + 34);
  G.det.y = Math.min(G.vh - 68, sp.y + 40);
  G.det.tx = null;
  G.det.ty = null;
  G.det.onArrive = null;
  G.det.facing = 1;
  G.det.mood = "idle";
  detectiveSay(
    `host-b is losing traffic! ${G.state.stats.eq_size} switches could be at fault.`,
    "info",
    4800,
    "thinking"
  );

  renderHud();
  renderWordleGrid(false);
  await refreshFivesHint();
  G.busy = false;
}

async function applyAction(action) {
  if (G.busy || !G.state || effectiveStatus() !== "playing") return;
  G.busy = true;
  closePopover();
  const data = Engine.apply(G.state.id, action);
  G.state = data.state;
  G.actions = data.actions;
  const res = data.result;

  triggerStoryFx(res);

  if (G.state.stats.status === "playing" && sloRemainingSec() <= 0) {
    G.busy = false;
    triggerSloViolation();
    return;
  }

  if (res.status === "rejected") {
    Sound.sfx("blocked");
    detectiveSay(`Blocked: ${res.reason}`, "bad", 4400, "shocked");
    toast(`Blocked: ${res.reason}`, true);
  } else {
    const cleared = res.eq_before - res.eq_after;
    const out = analyzeOutcome(res);
    Sound.sfx(res.action.kind, out.clean);
    if (G.state.stats.status === "localized") {
      setTimeout(() => Sound.sfx("win"), 220);
      detectiveSay(`Solved! Faulty switch is ${G.state.failure.culprit_name}!`, "win", 7000, "happy");
      triggerConfetti();
    } else if (G.state.stats.status !== "playing") {
      setTimeout(() => Sound.sfx("fired"), 220);
      detectiveSay(`Lost track of ${G.state.failure.culprit_name}!`, "bad", 5500, "shocked");
    } else if (cleared > 0) {
      setTimeout(() => Sound.sfx("cleared"), 200);
      detectiveSay(`${out.say} — ruled out ${cleared}!`, "good", 4400, "happy");
    } else if (G.infBase === "set" && res.action.kind === "subtle_weight_shift") {
      detectiveSay(`${out.say} — switch to Flock in Actions to read gentle shifts!`, "info", 5000, "thinking");
    } else {
      detectiveSay(`${out.say} — ${res.eq_after} suspects remain.`, "info", 4000, "thinking");
    }
  }

  renderHud();
  renderWordleGrid(true);
  await refreshFivesHint();
  G.busy = false;
}

async function accuseSwitch(nodeId) {
  if (G.busy || !G.state || effectiveStatus() !== "playing") return;
  setArmedWeapon(null);
  G.busy = true;
  closePopover();
  Sound.sfx("accuse");
  const data = Engine.accuse(G.state.id, nodeId);
  G.state = data.state;
  G.actions = data.actions;
  if (G.state.stats.status === "localized") {
    setTimeout(() => Sound.sfx("win"), 160);
    detectiveSay(`Solved! ${G.state.failure.culprit_name} was the culprit!`, "win", 7000, "happy");
    triggerConfetti();
  } else {
    setTimeout(() => Sound.sfx("fired"), 160);
    const nm = nodeById(nodeId).name;
    detectiveSay(`Wrong! ${nm} was healthy — fault: ${G.state.failure.culprit_name}.`, "bad", 6500, "shocked");
    G.shake = 10;
  }
  renderHud();
  renderWordleGrid(true);
  await refreshFivesHint();
  G.busy = false;
}

async function switchInferenceMode() {
  if (!G.state || G.busy) return;
  G.busy = true;
  const prevEq = G.state.stats.eq_size;
  const code = currentInfCode();
  const data = Engine.setInference(G.state.id, code);
  G.state = data.state;
  const nowEq = G.state.stats.eq_size;
  renderHud();
  renderWordleGrid(false);
  await refreshFivesHint();
  const nm = G.infBase === "flock" ? "Flock" : "Set ∩";
  detectiveSay(`${nm}: ${nowEq} suspect${nowEq === 1 ? "" : "s"} (was ${prevEq}).`, "info", 3200, "thinking");
  G.busy = false;
}

function setSolveBtnLabel(running) {
  $("btn-fives-solve").innerHTML = running
    ? `${Sprites.icon("pause", 15)}<span>Stop</span>`
    : `${Sprites.icon("wand", 16)}<span>Solve with FIVES</span>`;
}

async function solveWithFives() {
  if (G.autoPlay) {
    G.autoPlay = false;
    setSolveBtnLabel(false);
    return;
  }
  if (!G.state || effectiveStatus() !== "playing") return;
  G.fivesUnlocked = true;
  Sound.sfx("unlock");
  if (G.infBase !== "flock") {
    G.infBase = "flock";
    await switchInferenceMode();
  }
  closeDeck();
  closePopover();
  setArmedWeapon(null);
  G.autoPlay = true;
  setSolveBtnLabel(true);
  G.fivesHint = true;
  await refreshFivesHint();

  while (G.autoPlay && G.state && effectiveStatus() === "playing") {
    await refreshFivesHint();
    if (!G.fives || !G.fives.best) break;
    const pick = G.fives.best;
    await new Promise((resolve) => {
      walkDetectiveTo(pick.anchor, async () => {
        await applyAction(pick);
        resolve();
      });
    });
    await new Promise((r) => setTimeout(r, 700));
  }
  G.autoPlay = false;
  setSolveBtnLabel(false);
}

// ---------------------------------------------------------------------------
// 2D Canvas Rendering (Symptom Badges, Story FX, Switches & Inspector Switch)
// ---------------------------------------------------------------------------
function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
}

function drawFloor(ctx) {
  ctx.fillStyle = "#fcfaf5";
  ctx.fillRect(0, 0, G.vw, G.vh);

  ctx.strokeStyle = "#f1ece0";
  ctx.lineWidth = 1;
  const step = 32;
  ctx.beginPath();
  for (let x = step; x < G.vw; x += step) {
    ctx.moveTo(x, 0);
    ctx.lineTo(x, G.vh);
  }
  for (let y = step; y < G.vh; y += step) {
    ctx.moveTo(0, y);
    ctx.lineTo(G.vw, y);
  }
  ctx.stroke();
}

function drawBackgroundNetwork(ctx, now) {
  for (const be of G.state.bg_edges) {
    const a = normToPx(be.x1, be.y1);
    const b = normToPx(be.x2, be.y2);
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    if (be.active) {
      ctx.strokeStyle = "#6c93e0";
      ctx.lineWidth = 3.5;
      ctx.setLineDash([5, 4]);
      ctx.lineDashOffset = -(now * 0.025) % 18;
    } else {
      ctx.strokeStyle = "rgba(175, 168, 154, 0.34)";
      ctx.lineWidth = 2;
      ctx.setLineDash([]);
    }
    ctx.stroke();
    ctx.setLineDash([]);
  }

  for (const bn of G.state.bg_nodes) {
    const p = normToPx(bn.x, bn.y);
    if (bn.kind === "host") {
      Sprites.drawHostProp(ctx, p.x, p.y, bn.active, bn.name);
      // Visual symptom cue on `host-b` so it's immediately obvious what's happening!
      if (bn.key === "host:b") {
        const solved = G.state.stats.status === "localized";
        const bob = Math.sin(now * 0.006) * 2;
        const txt = solved ? "✓ Fixed" : "! Loss";
        ctx.save();
        ctx.font = "800 10.5px Inter, sans-serif";
        const tw = ctx.measureText(txt).width + 10;
        const bx = Math.min(G.vw - tw - 6, Math.max(6, p.x - tw / 2));
        const by = p.y - 31 + bob;
        ctx.fillStyle = solved ? "#538d4e" : "#d94848";
        roundRect(ctx, bx, by, tw, 17, 6);
        ctx.fill();
        ctx.fillStyle = "#fff";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(txt, bx + tw / 2, by + 9);
        ctx.restore();
      }
    } else {
      Sprites.drawBgSwitchProp(ctx, p.x, p.y, bn.name);
    }
  }
}

function sameTarget(a, b) {
  if (!a || !b || a.type !== b.type) return false;
  if (a.type === "node") return a.id === b.id;
  if (a.type === "edge") {
    const au = Math.min(a.u, a.v), av = Math.max(a.u, a.v);
    const bu = Math.min(b.u, b.v), bv = Math.max(b.u, b.v);
    return au === bu && av === bv;
  }
  return false;
}

function drawEdges(ctx, now) {
  const pulse = Math.sin(now * 0.008) * 2;
  for (const e of G.state.edges) {
    const s = edgeSocket(e);
    const tObj = { type: "edge", u: e.u, v: e.v };
    const isSel = sameTarget(G.selected, tObj);
    const isHov = sameTarget(G.hovered, tObj) || sameTarget(G.nearest, tObj);
    const active = e.flow_weight > 0.001;
    const boosted = e.flow_weight > 0.34 && G.state.history.length > 1;
    const armedMatches = G.armedWeapon ? weaponMatchesTarget(G.armedWeapon, tObj) : [];
    const isArmedTarget = armedMatches.length > 0;
    const armedSafe = armedMatches.some((a) => a.violation === null);

    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(s.ax, s.ay);
    ctx.lineTo(s.bx, s.by);
    ctx.strokeStyle = isSel
      ? "#23201b"
      : (isHov || isArmedTarget ? "#6355d8" : (active ? (boosted ? "#7c72c9" : "#aca391") : "#e3ddd0"));
    ctx.lineWidth = isSel || isHov ? 7.5 : (active ? 5.2 : 3.5);
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(s.ax, s.ay);
    ctx.lineTo(s.bx, s.by);
    if (!active) {
      ctx.setLineDash([5, 5]);
      ctx.strokeStyle = "#d3cdc0";
    } else {
      ctx.setLineDash([]);
      ctx.strokeStyle = isHov || isArmedTarget ? "#cbc5ff" : "#f2ede2";
    }
    ctx.lineWidth = 2.3;
    ctx.stroke();
    ctx.setLineDash([]);

    if (isArmedTarget) {
      ctx.strokeStyle = armedSafe ? "#6355d8" : "#d94848";
      ctx.lineWidth = 2.2;
      if (!armedSafe) ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.arc(s.x, s.y, 10 + pulse, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    ctx.fillStyle = isSel
      ? "#23201b"
      : (isHov || isArmedTarget ? (armedSafe || !isArmedTarget ? "#6355d8" : "#d94848") : "#cfc7b6");
    ctx.beginPath();
    ctx.arc(s.x, s.y, isSel || isHov || isArmedTarget ? 6.5 : 3.8, 0, Math.PI * 2);
    ctx.fill();
    if (isSel || isHov || isArmedTarget) {
      ctx.fillStyle = "#fff";
      ctx.beginPath();
      ctx.arc(s.x, s.y, 2.5, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

function drawNodes(ctx, now) {
  const st = G.state;
  const solved = effectiveStatus() === "localized";
  const showBug = G.peekFault || effectiveStatus() !== "playing";
  const { rw, rh, compact } = rackDims();
  const pulse = Math.sin(now * 0.008) * 2.5;

  for (const n of st.nodes) {
    const p = nodePos(n);
    const tObj = { type: "node", id: n.id };
    const isSel = sameTarget(G.selected, tObj);
    const isHov = sameTarget(G.hovered, tObj) || sameTarget(G.nearest, tObj);
    const armedMatches = G.armedWeapon ? weaponMatchesTarget(G.armedWeapon, tObj) : [];
    const isArmedTarget = armedMatches.length > 0;
    const armedSafe = armedMatches.some((a) => a.violation === null);

    if (isArmedTarget) {
      ctx.strokeStyle = armedSafe ? "#1e9e8e" : "#d94848";
      ctx.lineWidth = 2.4;
      if (!armedSafe) ctx.setLineDash([4, 3]);
      roundRect(ctx, p.x - rw / 2 - 6 - pulse * 0.5, p.y - rh / 2 - 6 - pulse * 0.5, rw + 12 + pulse, rh + 12 + pulse, 12);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    Sprites.drawRackProp(
      ctx,
      p.x,
      p.y,
      rw,
      rh,
      {
        suspect: n.suspect,
        solved: solved && n.suspect && n.id === st.failure.culprit,
        isEndpoint: n.is_endpoint,
        posterior: n.posterior,
        selected: isSel,
        hovered: isHov,
        compact,
        showLock: n.tags.length > 0,
        id: n.id,
      },
      now
    );

    if (showBug && n.id === st.failure.culprit) {
      Sprites.drawBug(ctx, p.x, p.y - rh / 2 - 5, now);
    }

    if (!compact || n.suspect || isHov || isSel) {
      ctx.font = "700 11.5px Inter, sans-serif";
      const label = n.name.length > 12 ? n.name.slice(0, 11) + "…" : n.name;
      const lw = ctx.measureText(label).width + 10;
      ctx.fillStyle = "rgba(252, 250, 245, 0.94)";
      roundRect(ctx, p.x - lw / 2, p.y + rh / 2 + 3, lw, 16, 4);
      ctx.fill();
      ctx.fillStyle = n.suspect || n.is_endpoint ? "#23201b" : "#7c838f";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(label, p.x, p.y + rh / 2 + 11);
    }
  }
}

function drawArmedHoverTag(ctx) {
  if (!G.armedWeapon || !G.hovered) return;
  if (G.hovered.type !== "node" && G.hovered.type !== "edge") return;
  const matches = weaponMatchesTarget(G.armedWeapon, G.hovered);
  if (matches.length === 0) return;
  const a = matches.find((m) => m.violation === null) || matches[0];
  const locked = a.violation !== null;
  const txt = locked ? `Blocked: ${a.violation}` : `${a.title} · ~${fmtTime(a.est_time)}`;
  const st = targetStandPos(G.hovered);
  ctx.save();
  ctx.font = "700 12px Inter, sans-serif";
  const tw = ctx.measureText(txt).width + 18;
  const bx = Math.max(10, Math.min(G.vw - tw - 10, st.anchorX - tw / 2));
  const by = Math.max(10, st.anchorY - 46);
  ctx.fillStyle = locked ? "#fdecec" : "#23201b";
  ctx.strokeStyle = locked ? "#d94848" : "#23201b";
  ctx.lineWidth = 1.6;
  roundRect(ctx, bx, by, tw, 24, 8);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = locked ? "#a92828" : "#fff";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(txt, bx + tw / 2, by + 12.5);
  ctx.restore();
}

function drawFivesOverlay(ctx, now) {
  if (!G.fivesHint || !G.fives || !G.fives.best) return;
  const best = G.fives.best;
  const pos = targetStandPos(best.anchor);
  const pulse = Math.sin(now * 0.007) * 3;

  ctx.save();
  ctx.strokeStyle = "rgba(217, 147, 22, 0.72)";
  ctx.lineWidth = 2.4;
  ctx.setLineDash([5, 6]);
  ctx.lineDashOffset = -(now * 0.03) % 22;
  ctx.beginPath();
  ctx.moveTo(G.det.x, G.det.y - 6);
  ctx.lineTo(pos.anchorX, pos.anchorY);
  ctx.stroke();
  ctx.restore();

  ctx.strokeStyle = "#d99316";
  ctx.lineWidth = 2.6;
  ctx.beginPath();
  ctx.arc(pos.anchorX, pos.anchorY, 27 + pulse, 0, Math.PI * 2);
  ctx.stroke();

  const badge = "FIVES Hint";
  ctx.font = "800 11px Inter, sans-serif";
  const bw = ctx.measureText(badge).width + 14;
  const bx = pos.anchorX - bw / 2;
  const by = pos.anchorY - 42;
  ctx.fillStyle = "#ffefc2";
  ctx.strokeStyle = "#b77708";
  ctx.lineWidth = 1.6;
  roundRect(ctx, bx, by, bw, 18, 9);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = "#6e4600";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(badge, pos.anchorX, by + 9.5);
}

function drawDetectiveAndBubble(ctx, now) {
  const d = G.det;
  const walking = d.tx !== null || G.keys.size > 0;
  let mood = now < d.moodUntil ? d.mood : "idle";
  if (G.state && G.state.stats.status === "localized") mood = "happy";
  else if (walking) mood = "walk";
  else if (G.fivesHint && mood === "idle") mood = "thinking";

  Sprites.drawDetective(
    ctx,
    {
      x: d.x,
      y: d.y,
      facing: d.facing,
      walkPhase: d.walkPhase,
      walking,
      jumpT: d.jumpT,
      fivesOpen: G.fivesHint,
      mood,
    },
    now
  );

  if (d.say && now < d.sayUntil) {
    ctx.save();
    ctx.font = "700 13.5px Inter, sans-serif";
    const padX = 14;
    const tw = Math.min(G.vw - 26, ctx.measureText(d.say).width + padX * 2);
    const bh = 30;
    const bx = Math.max(10, Math.min(G.vw - tw - 10, d.x - tw / 2));
    const by = Math.max(12, d.y - 76);
    const borderCol =
      d.sayKind === "bad" ? "#d94848" : (d.sayKind === "win" ? "#538d4e" : (d.sayKind === "good" ? "#2f855a" : "#23201b"));
    ctx.fillStyle = d.sayKind === "bad" ? "#fff5f5" : (d.sayKind === "win" ? "#effaf0" : "#fffdf8");
    ctx.strokeStyle = borderCol;
    ctx.lineWidth = 2;
    roundRect(ctx, bx, by, tw, bh, 10);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = d.sayKind === "bad" ? "#a92525" : "#23201b";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(d.say, bx + tw / 2, by + bh / 2 + 0.5, tw - 16);
    ctx.restore();
  }
}

function drawFloatingPill(ctx, x, y, text, clean, alpha) {
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.font = "800 12px Inter, sans-serif";
  const tw = ctx.measureText(text).width + 16;
  const bx = Math.max(8, Math.min(G.vw - tw - 8, x - tw / 2));
  const by = Math.max(8, y - 11);
  ctx.fillStyle = clean ? "#eaf6ea" : "#fdecec";
  ctx.strokeStyle = clean ? "#538d4e" : "#d94848";
  ctx.lineWidth = 1.8;
  roundRect(ctx, bx, by, tw, 22, 8);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = clean ? "#255722" : "#a52424";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, bx + tw / 2, by + 11.5);
  ctx.restore();
}

function drawFx(ctx) {
  for (const f of G.fx) {
    const k = Math.min(1, f.t / f.dur);
    ctx.save();
    if (f.kind === "shield") {
      const r = 18 + k * 24;
      ctx.strokeStyle = `rgba(217, 72, 72, ${1 - k})`;
      ctx.fillStyle = `rgba(217, 72, 72, ${(1 - k) * 0.22})`;
      ctx.lineWidth = 3;
      ctx.beginPath();
      for (let i = 0; i < 6; i++) {
        const a = (Math.PI / 3) * i - Math.PI / 6;
        const px = f.x + Math.cos(a) * r;
        const py = f.y + Math.sin(a) * r;
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      Sprites.drawActionProp(ctx, "shield", f.x, f.y - 16, k);
    } else if (f.kind === "probe") {
      // Phase 1 (k < 0.55): bright teal ping orb zips across the network to receiver
      // Phase 2 (k >= 0.55): pops outcome badge at destination (`✓ Ping Clean!` or `✕ Pings Dropped!`)
      const travelK = Math.min(1, k / 0.55);
      const px = f.x + (f.x2 - f.x) * travelK;
      const py = f.y + (f.y2 - f.y) * travelK;
      if (k < 0.6) {
        ctx.strokeStyle = `rgba(30, 158, 142, ${1 - k})`;
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        ctx.arc(f.x, f.y, 10 + travelK * 22, 0, Math.PI * 2);
        ctx.stroke();
        ctx.fillStyle = "#0ea5e9";
        ctx.strokeStyle = "#23201b";
        ctx.lineWidth = 1.6;
        ctx.beginPath();
        ctx.arc(px, py, 6.2, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      }
      Sprites.drawActionProp(ctx, "active_probe", f.x, f.y - 20, k);
      if (k >= 0.48 && f.badge) {
        const fade = k > 0.82 ? (1 - k) / 0.18 : 1;
        drawFloatingPill(ctx, f.x2, f.y2 - 30 - (k - 0.48) * 14, f.badge, f.clean, fade);
      }
    } else if (f.kind === "prop") {
      ctx.strokeStyle = `rgba(99, 85, 216, ${(1 - k) * 0.7})`;
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      ctx.arc(f.x, f.y, 10 + k * 26, 0, Math.PI * 2);
      ctx.stroke();
      Sprites.drawActionProp(ctx, f.propKind, f.x, f.y - 18, k);
    } else if (f.kind === "floatTag") {
      const fade = k > 0.78 ? (1 - k) / 0.22 : Math.min(1, k / 0.14);
      drawFloatingPill(ctx, f.x, f.y - k * 14, f.text, f.clean, fade);
    } else if (f.kind === "clearedPop") {
      const fade = k > 0.7 ? (1 - k) / 0.3 : 1;
      drawFloatingPill(ctx, f.x, f.y - k * 16, "✓ Out", true, fade * 0.92);
    } else if (f.kind === "confetti") {
      ctx.fillStyle = f.color;
      ctx.globalAlpha = 1 - k;
      ctx.fillRect(f.x - 3, f.y - 3, 6, 6);
    }
    ctx.restore();
  }
}

// ---------------------------------------------------------------------------
// 60fps Game Loop
// ---------------------------------------------------------------------------
function stepWorld(dt) {
  if (!G.state) return;

  if (!G.startScreenOpen && effectiveStatus() === "playing") {
    G.wallElapsedSec += dt;
    renderSloHud();
    if (sloRemainingSec() <= 0) {
      triggerSloViolation();
      return;
    }
  }

  let vx = 0, vy = 0;
  if (G.keys.has("ArrowLeft") || G.keys.has("KeyA")) vx -= 1;
  if (G.keys.has("ArrowRight") || G.keys.has("KeyD")) vx += 1;
  if (G.keys.has("ArrowUp") || G.keys.has("KeyW")) vy -= 1;
  if (G.keys.has("ArrowDown") || G.keys.has("KeyS")) vy += 1;

  if (vx !== 0 || vy !== 0) {
    G.det.tx = null;
    G.det.ty = null;
    G.det.onArrive = null;
    const norm = Math.hypot(vx, vy);
    const speed = 225;
    G.det.x = Math.max(30, Math.min(G.vw - 30, G.det.x + (vx / norm) * speed * dt));
    G.det.y = Math.max(40, Math.min(G.vh - 58, G.det.y + (vy / norm) * speed * dt));
    if (vx < 0) G.det.facing = -1;
    if (vx > 0) G.det.facing = 1;
    G.det.walkPhase += dt * 15;
    if (!G.startScreenOpen) Sound.sfx("step");

    let near = null, bestD = 52;
    for (const n of G.state.nodes) {
      const p = nodePos(n);
      const d = Math.hypot(G.det.x - p.x, G.det.y - p.y);
      if (d < bestD) { bestD = d; near = { type: "node", id: n.id }; }
    }
    for (const e of G.state.edges) {
      const s = edgeSocket(e);
      const d = Math.hypot(G.det.x - s.x, G.det.y - s.y);
      if (d < bestD) { bestD = d; near = { type: "edge", u: e.u, v: e.v }; }
    }
    G.nearest = near;
  } else if (G.det.tx !== null) {
    const dx = G.det.tx - G.det.x;
    const dy = G.det.ty - G.det.y;
    const dist = Math.hypot(dx, dy);
    const step = 340 * dt;
    if (dist <= step + 2) {
      G.det.x = G.det.tx;
      G.det.y = G.det.ty;
      G.det.tx = null;
      G.det.ty = null;
      const cb = G.det.onArrive;
      G.det.onArrive = null;
      if (cb) cb();
    } else {
      G.det.x += (dx / dist) * step;
      G.det.y += (dy / dist) * step;
      G.det.walkPhase += dt * 17;
      if (!G.startScreenOpen) Sound.sfx("step");
    }
  }

  if (G.det.jumpT > 0) G.det.jumpT = Math.max(0, G.det.jumpT - dt);
  if (G.shake > 0) G.shake = Math.max(0, G.shake - dt * 28);

  for (let i = G.fx.length - 1; i >= 0; i--) {
    const f = G.fx[i];
    f.t += dt;
    if (f.kind === "confetti") {
      f.x += f.vx * dt;
      f.y += f.vy * dt;
      f.vy += 280 * dt;
    }
    if (f.t >= f.dur) G.fx.splice(i, 1);
  }
}

function renderWorld(now) {
  const ctx = G.ctx;
  ctx.save();
  ctx.scale(G.dpr, G.dpr);
  if (G.shake > 0.2) {
    ctx.translate((Math.random() - 0.5) * G.shake, (Math.random() - 0.5) * G.shake);
  }
  drawFloor(ctx);
  if (G.state) {
    drawBackgroundNetwork(ctx, now);
    drawEdges(ctx, now);
    drawNodes(ctx, now);
    drawFivesOverlay(ctx, now);
    drawFx(ctx);
    drawDetectiveAndBubble(ctx, now);
    drawArmedHoverTag(ctx);
  }
  ctx.restore();
}

function renderStartHero(now) {
  if (!G.startScreenOpen || !G.heroCtx) return;
  const ctx = G.heroCtx;
  const w = 420;
  const h = 96;
  ctx.save();
  ctx.clearRect(0, 0, w, h);
  ctx.scale(G.dpr, G.dpr);

  // Paper grid backdrop
  ctx.fillStyle = "#f8f4e8";
  ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = "#ede7d6";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let x = 24; x < w; x += 24) {
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
  }
  for (let y = 24; y < h; y += 24) {
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
  }
  ctx.stroke();

  // Cables: host-a -> sw-1 -> sw-2 (faulty) -> host-b
  const pts = [
    [42, 54],
    [150, 50],
    [268, 50],
    [376, 54],
  ];
  ctx.strokeStyle = "#aca391";
  ctx.lineWidth = 4;
  ctx.beginPath();
  ctx.moveTo(pts[1][0], pts[1][1]);
  ctx.lineTo(pts[2][0], pts[2][1]);
  ctx.stroke();

  ctx.strokeStyle = "rgba(30, 158, 142, 0.55)";
  ctx.lineWidth = 2.4;
  ctx.setLineDash([5, 4]);
  ctx.lineDashOffset = -(now * 0.025) % 18;
  ctx.beginPath();
  ctx.moveTo(pts[0][0], pts[0][1]);
  ctx.lineTo(pts[1][0], pts[1][1]);
  ctx.moveTo(pts[2][0], pts[2][1]);
  ctx.lineTo(pts[3][0], pts[3][1]);
  ctx.stroke();
  ctx.setLineDash([]);

  // Endpoints + 2 switches + glitch bug + Inspector Switch patrolling
  Sprites.drawHostProp(ctx, pts[0][0], pts[0][1], true, "host-a");
  Sprites.drawRackProp(
    ctx,
    pts[1][0],
    pts[1][1],
    34,
    40,
    { suspect: false, solved: false, isEndpoint: false, posterior: 0, selected: false, hovered: false, compact: true, showLock: false, id: 1 },
    now
  );
  Sprites.drawRackProp(
    ctx,
    pts[2][0],
    pts[2][1],
    34,
    40,
    { suspect: true, solved: false, isEndpoint: false, posterior: 0.85, selected: false, hovered: true, compact: true, showLock: false, id: 2 },
    now
  );
  Sprites.drawBug(ctx, pts[2][0], pts[2][1] - 24, now);
  Sprites.drawHostProp(ctx, pts[3][0], pts[3][1], true, "host-b");

  // Bobbing `! Loss` pill above host-b
  const bob = Math.sin(now * 0.006) * 2;
  ctx.fillStyle = "#d94848";
  roundRect(ctx, pts[3][0] - 22, pts[3][1] - 32 + bob, 44, 16, 6);
  ctx.fill();
  ctx.fillStyle = "#fff";
  ctx.font = "800 10px Inter, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("! Loss", pts[3][0], pts[3][1] - 23.5 + bob);

  // Detective patrolling toward the suspect switch
  const sweep = (Math.sin(now * 0.0018) + 1) * 0.5;
  const dx = 98 + sweep * 118;
  const facing = Math.cos(now * 0.0018) >= 0 ? 1 : -1;
  Sprites.drawDetective(
    ctx,
    {
      x: dx,
      y: 74,
      facing,
      walkPhase: now * 0.012,
      walking: true,
      jumpT: 0,
      fivesOpen: true,
      mood: "walk",
    },
    now
  );
  ctx.restore();
}

function frame(now) {
  const dt = Math.min(0.05, (now - G.lastTs) / 1000);
  G.lastTs = now;
  stepWorld(dt);
  renderWorld(now);
  renderStartHero(now);
  requestAnimationFrame(frame);
}

// ---------------------------------------------------------------------------
// Init, Icons & Event Wiring
// ---------------------------------------------------------------------------
function resizeCanvas() {
  const wrap = $("room-wrap");
  const rect = wrap.getBoundingClientRect();
  G.vw = Math.max(320, rect.width);
  G.vh = Math.max(320, rect.height);
  G.dpr = window.devicePixelRatio || 1;
  G.canvas.width = Math.round(G.vw * G.dpr);
  G.canvas.height = Math.round(G.vh * G.dpr);
  if (G.heroCanvas) {
    G.heroCanvas.width = Math.round(420 * G.dpr);
    G.heroCanvas.height = Math.round(96 * G.dpr);
  }
  G.det.x = Math.max(34, Math.min(G.vw - 34, G.det.x));
  G.det.y = Math.max(40, Math.min(G.vh - 58, G.det.y));
  if (G.selected) positionPopover(G.selected);
}

function updateSoundBtn() {
  const muted = Sound.isMuted();
  $("btn-sound").innerHTML = `${Sprites.icon(muted ? "sound_off" : "sound_on", 15)}<span>${muted ? "Muted" : "Sound"}</span>`;
  $("btn-sound").classList.toggle("on", !muted);
}

function mountStaticIcons() {
  $("brand-icon").innerHTML = Sprites.icon("detective", 26);
  $("st-ico-1").innerHTML = Sprites.icon("probe", 15);
  $("st-ico-3").innerHTML = Sprites.icon("monocle", 15);
  $("btn-start-play").innerHTML = `${Sprites.icon("detective", 18)}<span>Start Game</span>`;
  $("fired-icon").innerHTML = Sprites.icon("warning", 24);
  $("btn-fired-retry").innerHTML = `${Sprites.icon("dice", 16)}<span>Try Another Case</span>`;
  updateSoundBtn();
  $("btn-peek").innerHTML = `${Sprites.icon("bug", 15)}<span>Peek</span>`;
  $("btn-new").innerHTML = `${Sprites.icon("dice", 15)}<span>New Case</span>`;
  $("btn-cfg-toggle").innerHTML = Sprites.icon("chevron", 14);
  $("btn-share").innerHTML = `${Sprites.icon("copy", 14)}<span>Copy</span>`;
  $("btn-again").innerHTML = `${Sprites.icon("dice", 14)}<span>Next Case</span>`;
  $("btn-actions").innerHTML = `${Sprites.icon("cards", 19)}<span>Actions</span><kbd>Space</kbd>`;
  $("btn-fives-hint").innerHTML = `${Sprites.icon("monocle", 16)}<span>FIVES Hint</span><kbd>F</kbd>`;
  setSolveBtnLabel(false);
}

function dismissStartScreen() {
  Sound.startMusic();
  Sound.sfx("ui");
  $("topology").value = $("start-topology").value;
  $("failure_mode").value = $("start-failure-mode").value;
  G.startScreenOpen = false;
  $("start-screen").classList.add("hidden");
  startNewCase();
}

function handleRoomTargetClick(hit) {
  if (hit.type === "bg") {
    detectiveSay(
      hit.active ? `${hit.name} is seeing packet loss.` : `${hit.name} is off-path (already cleared).`,
      "info",
      3000
    );
    return;
  }
  if (G.armedWeapon && (hit.type === "node" || hit.type === "edge")) {
    const matches = weaponMatchesTarget(G.armedWeapon, hit);
    if (matches.length === 0) {
      toast("Click a highlighted target.");
      return;
    }
    if (matches.length === 1) {
      walkAndApply(matches[0]);
      return;
    }
    const kind = G.armedWeapon;
    setArmedWeapon(null);
    walkDetectiveTo(hit, () => openPopover(hit, kind));
    return;
  }
  walkDetectiveTo(hit, () => openPopover(hit));
}

async function init() {
  mountStaticIcons();
  G.canvas = $("world");
  G.ctx = G.canvas.getContext("2d");
  G.heroCanvas = $("start-hero");
  G.heroCtx = G.heroCanvas.getContext("2d");
  resizeCanvas();
  new ResizeObserver(resizeCanvas).observe($("room-wrap"));

  G.cfg = Engine.getConfig();
  for (const t of G.cfg.topologies) {
    $("topology").add(new Option(t, t, t === "Clos-k4", t === "Clos-k4"));
    $("start-topology").add(new Option(t, t, t === "Clos-k4", t === "Clos-k4"));
  }
  for (const m of G.cfg.failure_modes) {
    $("failure_mode").add(new Option(MODE_LABELS[m], m));
    $("start-failure-mode").add(new Option(MODE_LABELS[m], m));
  }

  $("topology").addEventListener("change", () => {
    $("start-topology").value = $("topology").value;
  });
  $("failure_mode").addEventListener("change", () => {
    $("start-failure-mode").value = $("failure_mode").value;
  });
  $("btn-start-play").addEventListener("click", () => dismissStartScreen());
  $("btn-fired-retry").addEventListener("click", () => startNewCase());

  $("btn-new").addEventListener("click", () => startNewCase());
  $("btn-cfg-toggle").addEventListener("click", (ev) => {
    ev.stopPropagation();
    $("cfg-menu").classList.toggle("hidden");
  });
  $("btn-cfg-apply").addEventListener("click", () => startNewCase());
  $("btn-again").addEventListener("click", () => startNewCase());
  $("chk-traceroute").addEventListener("change", () => {
    G.pathAware = $("chk-traceroute").checked;
    switchInferenceMode();
  });
  document.addEventListener("click", (ev) => {
    if (!$("config-wrap").contains(ev.target)) {
      $("cfg-menu").classList.add("hidden");
    }
  });

  $("btn-actions").addEventListener("click", toggleDeck);
  $("deck-close").addEventListener("click", closeDeck);
  $("deck-overlay").addEventListener("click", (ev) => {
    if (ev.target === $("deck-overlay")) closeDeck();
  });
  $("armed-cancel").addEventListener("click", () => setArmedWeapon(null));

  $("btn-share").addEventListener("click", async () => {
    await navigator.clipboard.writeText(buildShareText());
    toast("Copied grid!");
  });

  $("btn-sound").addEventListener("click", () => {
    Sound.toggleMute();
    updateSoundBtn();
  });

  $("btn-peek").addEventListener("click", () => {
    Sound.sfx("ui");
    G.peekFault = !G.peekFault;
    $("btn-peek").classList.toggle("on", G.peekFault);
    renderWordleGrid(false);
    detectiveSay(
      G.peekFault ? `Culprit: ${G.state.failure.culprit_name}` : "Culprit hidden",
      "info",
      2400
    );
  });

  const toggleFivesHint = async () => {
    G.fivesHint = !G.fivesHint;
    if (G.fivesHint) {
      G.fivesUnlocked = true;
      Sound.sfx("hint");
    } else {
      Sound.sfx("ui");
    }
    await refreshFivesHint();
    if (G.deckOpen) renderDeckCards();
    if (G.selected) openPopover(G.selected);
  };
  $("btn-fives-hint").addEventListener("click", toggleFivesHint);
  $("lambda").addEventListener("input", () => refreshFivesHint());
  $("btn-fives-step").addEventListener("click", () => {
    if (G.fives && G.fives.best) walkAndApply(G.fives.best);
  });
  $("btn-fives-solve").addEventListener("click", solveWithFives);
  $("pop-close").addEventListener("click", closePopover);

  G.canvas.addEventListener("mousemove", (ev) => {
    const r = G.canvas.getBoundingClientRect();
    G.hovered = hitTestRoom(ev.clientX - r.left, ev.clientY - r.top);
  });
  G.canvas.addEventListener("mouseleave", () => { G.hovered = null; });
  G.canvas.addEventListener("click", (ev) => {
    const r = G.canvas.getBoundingClientRect();
    const mx = ev.clientX - r.left;
    const my = ev.clientY - r.top;
    const hit = hitTestRoom(mx, my);
    if (hit) {
      handleRoomTargetClick(hit);
    } else {
      closePopover();
      G.det.tx = Math.max(30, Math.min(G.vw - 30, mx));
      G.det.ty = Math.max(40, Math.min(G.vh - 58, my));
      if (mx < G.det.x - 2) G.det.facing = -1;
      if (mx > G.det.x + 2) G.det.facing = 1;
      G.det.onArrive = null;
    }
  });

  window.addEventListener("keydown", (ev) => {
    if (ev.target.tagName === "SELECT" || ev.target.tagName === "INPUT") return;
    if (G.startScreenOpen) {
      if (ev.code === "Enter" || ev.code === "Space") {
        ev.preventDefault();
        dismissStartScreen();
      }
      return;
    }
    if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "KeyW", "KeyA", "KeyS", "KeyD"].includes(ev.code)) {
      ev.preventDefault();
      G.keys.add(ev.code);
      return;
    }
    if (ev.code === "Escape") {
      setArmedWeapon(null);
      closeDeck();
      closePopover();
      $("cfg-menu").classList.add("hidden");
      return;
    }
    if (ev.code === "Space") {
      ev.preventDefault();
      toggleDeck();
      return;
    }
    if (ev.code === "Enter" && G.nearest) {
      ev.preventDefault();
      handleRoomTargetClick(G.nearest);
      return;
    }
    if (ev.code === "KeyM") {
      ev.preventDefault();
      Sound.toggleMute();
      updateSoundBtn();
      return;
    }
    if (ev.code === "KeyF") {
      ev.preventDefault();
      toggleFivesHint();
      return;
    }
    if (ev.code === "KeyN") {
      ev.preventDefault();
      startNewCase();
      return;
    }
    if (/^Digit[1-7]$/.test(ev.code)) {
      const idx = Number(ev.code.slice(-1)) - 1;
      if (G.popActions.length > 0 && idx < G.popActions.length) {
        ev.preventDefault();
        const chosen = G.popActions[idx];
        if (isFivesOnlyKind(chosen.kind) && !G.fivesUnlocked) unlockFives();
        else walkAndApply(chosen);
      } else if (idx < G.visibleWeapons.length) {
        ev.preventDefault();
        setArmedWeapon(G.visibleWeapons[idx].kind);
      }
    }
  });
  window.addEventListener("keyup", (ev) => {
    G.keys.delete(ev.code);
  });

  requestAnimationFrame(frame);
  await startNewCase();
}

init();
