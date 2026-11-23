// FaultFerence · 2D Indie Paper-and-Ink Icon & Canvas Sprite Toolkit
// Zero external dependencies. Exposes global `window.Sprites`.
"use strict";

(function () {
  const INK = "#23201b";
  const PAPER = "#fcfaf5";
  const AMBER = "#e2a432";
  const GOLD = "#d99316";
  const GREEN = "#538d4e";
  const TEAL = "#1e9e8e";
  const INDIGO = "#6355d8";
  const BLUE = "#3568d4";
  const CORAL = "#dd6b34";
  const RED = "#d94848";

  // ---------------------------------------------------------------------------
  // 1. Inline SVG Icon Definitions (viewBox="0 0 24 24", 2px #23201b ink strokes)
  // ---------------------------------------------------------------------------
  const ICON_DEFS = {
    // --- Perturbation Kinds ---
    probe: (
      '<path d="M4 20.5h7.5M7.8 16.8v3.7"/>' +
      '<path d="M5.2 10.4a6.4 6.4 0 0 0 8.4 8.4L5.2 10.4Z" fill="#9eeadf"/>' +
      '<line x1="9.4" y1="14.6" x2="12.8" y2="11.2"/>' +
      '<circle cx="13.5" cy="10.5" r="1.6" fill="#e2a432"/>' +
      '<path d="M15.8 5.4a4.6 4.6 0 0 1 2.8 2.8" stroke="#1e9e8e"/>' +
      '<path d="M16.8 2.4a8.2 8.2 0 0 1 4.8 4.8" stroke="#1e9e8e"/>'
    ),

    mirror: (
      '<polygon points="4.5,16.5 16.5,10.5 19.5,15.5 7.5,21.5" fill="#9eeadf"/>' +
      '<line x1="8.8" y1="16.8" x2="14.4" y2="14" stroke="#ffffff" stroke-width="1.6"/>' +
      '<line x1="3" y1="5.8" x2="10.5" y2="13.3" stroke="#e2a432" stroke-width="2.2"/>' +
      '<line x1="10.5" y1="13.3" x2="19.5" y2="4.5" stroke="#1e9e8e" stroke-width="2.2"/>' +
      '<polyline points="15.8,4.5 19.5,4.5 19.5,8.2" stroke="#1e9e8e"/>' +
      '<circle cx="10.5" cy="13.3" r="1.5" fill="#fff3bf"/>'
    ),

    weight: (
      '<path d="M8 21h8M12 6v15"/>' +
      '<line x1="4.5" y1="8.5" x2="19.5" y2="11.5"/>' +
      '<circle cx="12" cy="5.5" r="2" fill="#e2a432"/>' +
      '<path d="M4.5 8.5L2.4 13.5h4.2L4.5 8.5Z" fill="#fde6a8"/>' +
      '<path d="M2.1 13.5a2.4 2 0 0 0 4.8 0H2.1Z" fill="#e2a432"/>' +
      '<path d="M19.5 11.5l-2.3 5h4.6l-2.3-5Z" fill="#cbc5ff"/>' +
      '<path d="M16.8 16.5a2.7 2.2 0 0 0 5.4 0h-5.4Z" fill="#6355d8"/>'
    ),

    drain: (
      '<rect x="2.5" y="18.5" width="12" height="2.5" rx="1" fill="#dd6b34"/>' +
      '<polygon points="4.8,18.5 7.2,6.5 9.8,6.5 12.2,18.5" fill="#dd6b34"/>' +
      '<polygon points="6,12.8 6.5,10 10.5,10 11,12.8" fill="#fcfaf5"/>' +
      '<path d="M15 18.2c4-1 5.6-4.4 5-8-.5-3-2.7-4.7-6-4.9" stroke="#6355d8" stroke-width="2.2"/>' +
      '<polyline points="16.4,2.8 13.6,5.3 16.2,7.9" stroke="#6355d8"/>'
    ),

    split: (
      '<line x1="2.5" y1="12" x2="7.5" y2="12"/>' +
      '<rect x="7" y="9" width="5.5" height="6" rx="1.6" fill="#cbc5ff"/>' +
      '<path d="M12.5 10.5c2.6 0 3.4-4 8-4" stroke="#6355d8" stroke-width="2.2"/>' +
      '<polyline points="18,4 20.8,6.5 18,9" stroke="#6355d8"/>' +
      '<path d="M12.5 13.5c2.6 0 3.4 4 8 4" stroke="#e2a432" stroke-width="2.2"/>' +
      '<polyline points="18,15 20.8,17.5 18,20" stroke="#e2a432"/>'
    ),

    cut: (
      '<line x1="2" y1="12" x2="7.2" y2="12" stroke="#697382" stroke-width="2.6"/>' +
      '<line x1="16.8" y1="12" x2="22" y2="12" stroke="#697382" stroke-width="2.6"/>' +
      '<line x1="8.2" y1="7.2" x2="17.8" y2="16.4"/>' +
      '<line x1="8.2" y1="16.8" x2="17.8" y2="7.6"/>' +
      '<circle cx="6" cy="5.8" r="2.6" fill="#f9b4b4"/>' +
      '<circle cx="6" cy="18.2" r="2.6" fill="#f9b4b4"/>' +
      '<circle cx="12.5" cy="12" r="1.5" fill="#e2a432"/>' +
      '<path d="M12.5 6.4V4.2M12.5 19.8v-2.2" stroke="#d94848" stroke-width="1.8"/>'
    ),

    reboot: (
      '<rect x="3" y="3" width="18" height="18" rx="5" fill="#ffd0b5"/>' +
      '<path d="M16.2 9.6a5 5 0 1 0 .9 4.2"/>' +
      '<polyline points="16.8,6.2 16.5,9.8 13,9.4"/>' +
      '<line x1="12" y1="7.6" x2="12" y2="12" stroke="#dd6b34" stroke-width="2.4"/>' +
      '<circle cx="12" cy="12.2" r="1.4" fill="#e2a432"/>'
    ),

    // --- UI & HUD Icons ---
    detective: (
      '<path d="M5.2 21.5c1.1-2.6 3.5-4 6.8-4s5.7 1.4 6.8 4" fill="#d59b58"/>' +
      '<circle cx="12" cy="14" r="5.5" fill="#ffe3c4"/>' +
      '<circle cx="9.7" cy="14.2" r="1.05" fill="#23201b" stroke="none"/>' +
      '<circle cx="14.3" cy="14.1" r="2.3" fill="#fff3bf" stroke="#d99316" stroke-width="1.8"/>' +
      '<circle cx="14.3" cy="14.1" r="0.85" fill="#23201b" stroke="none"/>' +
      '<path d="M16.2 15.4c.5 1.3.2 2.5-.6 3.4" stroke="#d99316" stroke-width="1.4"/>' +
      '<path d="M6.8 9.2c.3-3.6 1.8-5.7 5.2-5.5 3.4-.2 4.9 1.9 5.2 5.5H6.8Z" fill="#433224"/>' +
      '<rect x="6.9" y="7.2" width="10.2" height="2" fill="#e8b339"/>' +
      '<ellipse cx="12" cy="9.5" rx="8.8" ry="2.1" fill="#433224"/>'
    ),

    bug: (
      '<path d="M6.5 11.5L3.5 10M6 14.5H3M6.8 17.5L4 19.2M17.5 11.5L20.5 10M18 14.5h3M17.2 17.5L20 19.2"/>' +
      '<path d="M9.5 7.6L7.2 4.2M14.5 7.6l2.3-3.4"/>' +
      '<circle cx="7" cy="4" r="1.1" fill="#d94848" stroke="none"/>' +
      '<circle cx="17" cy="4" r="1.1" fill="#d94848" stroke="none"/>' +
      '<path d="M6.2 13.4a5.8 5.8 0 0 1 11.6 0v3.3a3.5 3.5 0 0 1-3.5 3.5H9.7a3.5 3.5 0 0 1-3.5-3.5v-3.3Z" fill="#d94848"/>' +
      '<line x1="12" y1="14.6" x2="12" y2="20.2"/>' +
      '<circle cx="9.6" cy="11.8" r="1.9" fill="#ffffff" stroke-width="1.4"/>' +
      '<circle cx="14.4" cy="11.8" r="1.9" fill="#ffffff" stroke-width="1.4"/>' +
      '<circle cx="9.8" cy="11.9" r="0.85" fill="#23201b" stroke="none"/>' +
      '<circle cx="14.2" cy="11.9" r="0.85" fill="#23201b" stroke="none"/>'
    ),

    monocle: (
      '<circle cx="11.5" cy="11.5" r="6.8" fill="#e8b339"/>' +
      '<circle cx="11.5" cy="11.5" r="4.6" fill="#fff3bf" stroke-width="1.5"/>' +
      '<path d="M9.2 9.8a2.8 2.8 0 0 1 3.2-1" stroke="#ffffff" stroke-width="1.6"/>' +
      '<circle cx="5.1" cy="14" r="1.3" fill="#e8b339" stroke-width="1.5"/>' +
      '<path d="M5.1 15.4c-.3 2.5.8 4.4 3.2 5.2" stroke="#b77708" stroke-width="1.8" stroke-dasharray="1.5 2.2"/>' +
      '<path d="M19 2.2l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8.8-2Z" fill="#f5c84c" stroke-width="1.4"/>'
    ),

    calendar: (
      '<rect x="3" y="4.5" width="18" height="16.5" rx="3" fill="#fcfaf5"/>' +
      '<path d="M3 7.5a3 3 0 0 1 3-3h12a3 3 0 0 1 3 3v2H3v-2Z" fill="#d94848"/>' +
      '<line x1="8" y1="2.5" x2="8" y2="6"/>' +
      '<line x1="16" y1="2.5" x2="16" y2="6"/>' +
      '<rect x="6.5" y="12" width="4.3" height="4.3" rx="1" fill="#e2a432" stroke-width="1.5"/>' +
      '<rect x="13.2" y="12" width="4.3" height="4.3" rx="1" fill="#538d4e" stroke-width="1.5"/>'
    ),

    dice: (
      '<rect x="3.5" y="3.5" width="17" height="17" rx="3.8" fill="#fcfaf5"/>' +
      '<path d="M5.5 18.2h11a1.7 1.7 0 0 0 1.7-1.7V5.5" stroke="#ded7c6" stroke-width="1.6"/>' +
      '<circle cx="8" cy="8" r="1.45" fill="#23201b" stroke="none"/>' +
      '<circle cx="16" cy="8" r="1.45" fill="#23201b" stroke="none"/>' +
      '<circle cx="12" cy="12" r="1.6" fill="#e2a432" stroke="#23201b" stroke-width="1.1"/>' +
      '<circle cx="8" cy="16" r="1.45" fill="#23201b" stroke="none"/>' +
      '<circle cx="16" cy="16" r="1.45" fill="#23201b" stroke="none"/>'
    ),

    copy: (
      '<rect x="3" y="3" width="13" height="14" rx="2.5" fill="#ebe4d4"/>' +
      '<rect x="8" y="7" width="13" height="14" rx="2.5" fill="#fcfaf5"/>' +
      '<rect x="10.6" y="10" width="3.2" height="3.2" rx="0.7" fill="#e2a432" stroke="none"/>' +
      '<rect x="15.2" y="10" width="3.2" height="3.2" rx="0.7" fill="#c8ccd2" stroke="none"/>' +
      '<rect x="10.6" y="14.6" width="3.2" height="3.2" rx="0.7" fill="#c8ccd2" stroke="none"/>' +
      '<rect x="15.2" y="14.6" width="3.2" height="3.2" rx="0.7" fill="#538d4e" stroke="none"/>'
    ),

    shield: (
      '<polygon points="12,2.5 20.2,7.2 20.2,16.8 12,21.5 3.8,16.8 3.8,7.2" fill="#d94848"/>' +
      '<polyline points="6.2,8.5 12,5.2 17.8,8.5" stroke="#f9b4b4" stroke-width="1.5"/>' +
      '<path d="M9.2 9.2l5.6 5.6M14.8 9.2l-5.6 5.6" stroke="#ffffff" stroke-width="2.3"/>'
    ),

    eye: (
      '<path d="M2.2 12C4.5 7.2 8 5 12 5s7.5 2.2 9.8 7c-2.3 4.8-5.8 7-9.8 7s-7.5-2.2-9.8-7Z" fill="#fcfaf5"/>' +
      '<circle cx="12" cy="12" r="3.8" fill="#1e9e8e"/>' +
      '<circle cx="12" cy="12" r="1.5" fill="#23201b" stroke="none"/>' +
      '<circle cx="13.2" cy="10.8" r="0.9" fill="#ffffff" stroke="none"/>'
    ),

    rack: (
      '<rect x="4.5" y="2.5" width="15" height="19" rx="3" fill="#dfe4ea"/>' +
      '<rect x="7" y="5.2" width="10" height="3.6" rx="1.2" fill="#fcfaf5" stroke-width="1.4"/>' +
      '<circle cx="9.2" cy="7" r="1.15" fill="#e2a432" stroke="none"/>' +
      '<circle cx="12" cy="7" r="1.15" fill="#538d4e" stroke="none"/>' +
      '<line x1="7.5" y1="12.5" x2="16.5" y2="12.5"/>' +
      '<line x1="7.5" y1="16" x2="16.5" y2="16"/>'
    ),

    cable: (
      '<path d="M3.2 20.8c2.4-2.4 4.2-3.6 6.4-5.8" stroke-width="2.4"/>' +
      '<polygon points="7.8,12.6 12.6,7.8 16.2,11.4 11.4,16.2" fill="#6355d8"/>' +
      '<polygon points="12.6,7.8 16.6,3.8 20.2,7.4 16.2,11.4" fill="#e2a432"/>' +
      '<line x1="18.4" y1="5.6" x2="21" y2="3"/>'
    ),

    path: (
      '<circle cx="4.5" cy="19" r="2.1" fill="#9eeadf"/>' +
      '<path d="M6.8 19c4.4 0 3.6-3.2 8.2-3.2" stroke="#3568d4" stroke-dasharray="2.2 2.4"/>' +
      '<path d="M15.5 3.2a5.2 5.2 0 0 0-5.2 5.2c0 3.6 5.2 8.4 5.2 8.4s5.2-4.8 5.2-8.4a5.2 5.2 0 0 0-5.2-5.2Z" fill="#3568d4"/>' +
      '<circle cx="15.5" cy="8.4" r="2" fill="#fcfaf5" stroke-width="1.5"/>'
    ),

    play: (
      '<polygon points="6.5,4.5 19.5,12 6.5,19.5" fill="#538d4e"/>'
    ),

    fast_forward: (
      '<polygon points="3.5,5.5 12,12 3.5,18.5" fill="#e2a432"/>' +
      '<polygon points="12,5.5 20.5,12 12,18.5" fill="#f5c84c"/>'
    ),

    pause: (
      '<rect x="5.5" y="4.5" width="4.5" height="15" rx="1.5" fill="#dd6b34"/>' +
      '<rect x="14" y="4.5" width="4.5" height="15" rx="1.5" fill="#dd6b34"/>'
    ),

    trophy: (
      '<path d="M6 6H3.8a2.3 2.3 0 0 0 0 4.6H6M18 6h2.2a2.3 2.3 0 0 1 0 4.6H18"/>' +
      '<path d="M6 4h12v6a6 6 0 0 1-12 0V4Z" fill="#f5c84c"/>' +
      '<line x1="9" y1="6.5" x2="9" y2="10.2" stroke="#ffffff" stroke-width="1.5"/>' +
      '<line x1="12" y1="16" x2="12" y2="19.5"/>' +
      '<rect x="7.5" y="19.5" width="9" height="2.2" rx="1" fill="#e2a432"/>'
    ),

    // --- Helpful Extra UI Accents ---
    bolt: (
      '<polygon points="13.5,2.5 5.5,13.2 11.5,13.2 10.5,21.5 18.5,10.8 12.5,10.8" fill="#f5c84c"/>'
    ),

    clock: (
      '<circle cx="12" cy="13" r="8" fill="#fcfaf5"/>' +
      '<line x1="10" y1="2.5" x2="14" y2="2.5"/>' +
      '<line x1="12" y1="2.5" x2="12" y2="5"/>' +
      '<polyline points="12,8.5 12,13 15.2,14.8" stroke="#d99316"/>'
    ),

    feather: (
      '<path d="M19.2 4.8a5.5 5.5 0 0 0-7.8 0L5 11.2V19h7.8l6.4-6.4a5.5 5.5 0 0 0 0-7.8Z" fill="#9eeadf"/>' +
      '<line x1="3.5" y1="20.5" x2="14.5" y2="9.5"/>'
    ),

    star: (
      '<polygon points="12,2.8 14.8,8.6 21.2,9.5 16.6,14 17.7,20.4 12,17.4 6.3,20.4 7.4,14 2.8,9.5 9.2,8.6" fill="#f5c84c"/>'
    ),

    warning: (
      '<polygon points="12,3.2 21.5,19.8 2.5,19.8" fill="#fde6a8"/>' +
      '<line x1="12" y1="9.2" x2="12" y2="14"/>' +
      '<circle cx="12" cy="17" r="1.1" fill="#d94848" stroke="none"/>'
    ),

    flock: (
      '<path d="M3.5 14.5c2.2-4.6 6.2-7 11.2-6.5l3.8-2.8-1.1 4.2 3.1 1.4-3.3 1.4c-1.2 4.3-5.2 6.8-10.2 6.3-1.4-.1-2.6-.6-3.5-1.3l2.6-1.8-2.6-.9Z" fill="#fde6a8"/>' +
      '<path d="M8.5 12.2c1.8-1.4 4-1.8 6.2-1.1" stroke="#d99316" stroke-width="1.7"/>' +
      '<circle cx="14.8" cy="10.2" r="1.1" fill="#23201b" stroke="none"/>'
    ),

    gadget_007: (
      '<circle cx="12" cy="12" r="8" fill="#dce8ff"/>' +
      '<circle cx="12" cy="12" r="4" fill="#fcfaf5" stroke="#3568d4" stroke-width="1.7"/>' +
      '<line x1="12" y1="2.2" x2="12" y2="6.2"/>' +
      '<line x1="12" y1="17.8" x2="12" y2="21.8"/>' +
      '<line x1="2.2" y1="12" x2="6.2" y2="12"/>' +
      '<line x1="17.8" y1="12" x2="21.8" y2="12"/>' +
      '<circle cx="12" cy="12" r="1.4" fill="#d94848" stroke="none"/>'
    ),

    netbouncer: (
      '<rect x="6.5" y="3" width="11" height="5.5" rx="1.8" fill="#cbc5ff"/>' +
      '<polyline points="4,19.5 11.5,9 19.5,19.5" stroke="#1e9e8e" stroke-width="2.3"/>' +
      '<polyline points="15.5,19.5 19.5,19.5 19.5,15.5" stroke="#1e9e8e"/>' +
      '<circle cx="11.5" cy="9" r="1.8" fill="#f5c84c"/>'
    ),

    accuse: (
      '<circle cx="12" cy="12" r="8.5" fill="#eaf5e9"/>' +
      '<circle cx="12" cy="12" r="4.8" fill="#538d4e"/>' +
      '<polyline points="9.6,12.2 11.3,13.9 14.6,10.3" stroke="#ffffff" stroke-width="2.2"/>'
    ),

    chevron: (
      '<polyline points="6,9 12,15 18,9" stroke="currentColor" stroke-width="2.6"/>'
    ),

    cards: (
      '<rect x="3" y="4.5" width="11.5" height="15" rx="2.3" transform="rotate(-8 8.5 12)" fill="#ebe4d4"/>' +
      '<rect x="9" y="4" width="12" height="16" rx="2.4" transform="rotate(6 15 12)" fill="#fde6a8"/>' +
      '<circle cx="15" cy="12" r="2.4" fill="#e2a432"/>'
    ),

    set_lens: (
      '<circle cx="9.2" cy="12" r="5.8" fill="#dce8ff"/>' +
      '<circle cx="14.8" cy="12" r="5.8" fill="#fde6a8" fill-opacity="0.82"/>' +
      '<path d="M12 7.2a5.8 5.8 0 0 1 0 9.6 5.8 5.8 0 0 1 0-9.6Z" fill="#538d4e"/>' +
      '<circle cx="9.2" cy="12" r="5.8" fill="none"/>'
    ),

    wand: (
      '<line x1="4" y1="20" x2="15.5" y2="8.5" stroke-width="2.5"/>' +
      '<polygon points="17.5,2.8 18.8,6.2 22.2,7.5 18.8,8.8 17.5,12.2 16.2,8.8 12.8,7.5 16.2,6.2" fill="#f5c84c"/>' +
      '<circle cx="8" cy="6.5" r="1.2" fill="#e2a432" stroke="none"/>'
    ),
  };

  const ICON_ALIASES = {
    active_probe: "probe",
    packet_mirror: "mirror",
    subtle_weight_shift: "weight",
    flow_link_drain: "drain",
    flow_group_split: "split",
    full_link_drain: "cut",
    component_reset: "reboot",
    blocked: "shield",
  };

  function icon(name, size = 16) {
    const key = ICON_ALIASES[name] !== undefined ? ICON_ALIASES[name] : name;
    const body = ICON_DEFS[key];
    if (body === undefined) {
      throw new Error("Sprites.icon: unknown icon '" + name + "'");
    }
    return (
      '<svg class="sp-icon sp-icon-' + key + '" xmlns="http://www.w3.org/2000/svg" ' +
      'width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" ' +
      'stroke="#23201b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ' +
      'aria-hidden="true" style="display:inline-block;vertical-align:-0.16em;flex-shrink:0">' +
      body +
      "</svg>"
    );
  }

  // ---------------------------------------------------------------------------
  // 2. Canvas 2D Geometry Helpers
  // ---------------------------------------------------------------------------
  function rrect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, r);
  }

  function drawSparkle(ctx, x, y, r, fill) {
    ctx.save();
    ctx.fillStyle = fill;
    ctx.strokeStyle = INK;
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(x, y - r);
    ctx.lineTo(x + r * 0.34, y - r * 0.34);
    ctx.lineTo(x + r, y);
    ctx.lineTo(x + r * 0.34, y + r * 0.34);
    ctx.lineTo(x, y + r);
    ctx.lineTo(x - r * 0.34, y + r * 0.34);
    ctx.lineTo(x - r, y);
    ctx.lineTo(x - r * 0.34, y - r * 0.34);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.restore();
  }

  // ---------------------------------------------------------------------------
  // 3. Chibi Detective Sprite (`Sprites.drawDetective(ctx, state, now)`)
  //    state: { x, y, facing, walkPhase, walking, jumpT, fivesOpen, mood }
  //    mood: "idle" | "walk" | "happy" | "shocked" | "thinking"
  // ---------------------------------------------------------------------------
  function drawDetective(ctx, state, now) {
    const walking = Boolean(state.walking);
    const mood = state.mood === "idle" && walking ? "walk" : state.mood;
    const facing = state.facing >= 0 ? 1 : -1;
    const fivesOpen = Boolean(state.fivesOpen);

    let bob = Math.sin(now * 0.0042) * 1.25;
    if (walking || mood === "walk") {
      bob = Math.abs(Math.sin(state.walkPhase)) * 3.8;
    } else if (mood === "happy") {
      bob = Math.abs(Math.sin(now * 0.009)) * 3.1;
    } else if (mood === "shocked") {
      bob = Math.sin(now * 0.055) * 1.1;
    }

    const jumpY = state.jumpT > 0 ? Math.sin(Math.min(1, state.jumpT / 0.6) * Math.PI) * 16 : 0;
    const x = state.x;
    const y = state.y - bob - jumpY;

    ctx.save();

    // Soft elliptical floor shadow
    ctx.fillStyle = "rgba(35, 32, 27, 0.18)";
    ctx.beginPath();
    ctx.ellipse(x, state.y + 3, Math.max(6.5, 12.5 - jumpY * 0.25), 4.5, 0, 0, Math.PI * 2);
    ctx.fill();

    ctx.translate(x, y);
    ctx.scale(facing, 1);

    // Subtle stride lean when walking
    if (walking || mood === "walk") {
      ctx.rotate(0.045);
    } else if (mood === "shocked") {
      ctx.rotate(-0.06);
    }

    // Fluttering detective scarf / coat-tail behind body
    const flutter = (walking || mood === "walk")
      ? Math.sin(state.walkPhase - 0.9) * 3.4
      : Math.sin(now * 0.005) * 1.1;
    const tailLift = (walking || mood === "walk") ? 2.8 : (mood === "happy" ? 2.2 : 0);

    // Coat-tail flare
    ctx.fillStyle = "#b97f3d";
    ctx.strokeStyle = INK;
    ctx.lineWidth = 1.7;
    ctx.beginPath();
    ctx.moveTo(-7, -11);
    ctx.quadraticCurveTo(-13.5, -9.5 - tailLift + flutter * 0.4, -14.8, -4.5 - tailLift + flutter * 0.55);
    ctx.lineTo(-8.5, -4.2);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();

    // Warm crimson scarf tail fluttering from collar
    ctx.fillStyle = RED;
    ctx.strokeStyle = INK;
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    ctx.moveTo(-5.5, -18.2);
    ctx.quadraticCurveTo(-12.5, -18.8 - tailLift + flutter * 0.5, -15.6, -14.2 - tailLift + flutter);
    ctx.quadraticCurveTo(-11.8, -12.6 - tailLift + flutter * 0.7, -6.5, -15.4);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();

    // Little espresso leather boots
    const legSwing = (walking || mood === "walk")
      ? Math.sin(state.walkPhase) * 4.8
      : (mood === "happy" ? Math.sin(now * 0.012) * 2.2 : 0);
    ctx.fillStyle = "#3a2c20";
    ctx.strokeStyle = INK;
    ctx.lineWidth = 1.6;
    rrect(ctx, -7.2 + legSwing, -5.2, 6.2, 6, 2.5);
    ctx.fill();
    ctx.stroke();
    rrect(ctx, 1.2 - legSwing, -5.2, 6.2, 6, 2.5);
    ctx.fill();
    ctx.stroke();

    // Camel trenchcoat body
    ctx.fillStyle = "#d59b58";
    ctx.strokeStyle = INK;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(-8.8, -18.2);
    ctx.lineTo(8.8, -18.2);
    ctx.lineTo(11.2, -4.2);
    ctx.lineTo(-10.8, -4.2);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();

    // Warm highlight panel on front of coat
    ctx.fillStyle = "rgba(255, 245, 224, 0.28)";
    ctx.beginPath();
    ctx.moveTo(1, -17.4);
    ctx.lineTo(7.8, -17.4);
    ctx.lineTo(9.6, -5);
    ctx.lineTo(1.5, -5);
    ctx.closePath();
    ctx.fill();

    // Trenchcoat belt + brass buckle
    ctx.fillStyle = "#9c682d";
    ctx.fillRect(-9.6, -9.8, 19.4, 2.4);
    ctx.fillStyle = "#f5c84c";
    ctx.strokeStyle = INK;
    ctx.lineWidth = 1.1;
    rrect(ctx, 0.2, -10.3, 3.6, 3.4, 0.8);
    ctx.fill();
    ctx.stroke();

    // Scarf neck wrap + coat lapels
    ctx.fillStyle = RED;
    ctx.strokeStyle = INK;
    ctx.lineWidth = 1.5;
    rrect(ctx, -6.5, -19.2, 13, 3.2, 1.5);
    ctx.fill();
    ctx.stroke();

    ctx.strokeStyle = "#7d5122";
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.moveTo(-3.2, -16.2);
    ctx.lineTo(0.8, -11.2);
    ctx.lineTo(4.2, -16.2);
    ctx.stroke();

    // Cute chibi round head + little back ear
    ctx.fillStyle = "#ffd4ab";
    ctx.strokeStyle = INK;
    ctx.lineWidth = 1.7;
    ctx.beginPath();
    ctx.arc(-8.4, -24.8, 2.4, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = "#ffe3c4";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(0, -25.2, 9, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();

    // Rosy cheeks
    ctx.fillStyle = mood === "happy" ? "rgba(235, 95, 95, 0.58)" : "rgba(235, 115, 115, 0.44)";
    ctx.beginPath();
    ctx.arc(-3.6, -22.8, 2.1, 0, Math.PI * 2);
    ctx.arc(5.8, -22.8, 2.1, 0, Math.PI * 2);
    ctx.fill();

    // --- Expressive Eyes, Brows & Mouth by Mood ---
    const blinking = (now % 3400) < 120;
    if (mood === "happy") {
      // Joyful ^_^ curved eyes
      ctx.strokeStyle = INK;
      ctx.lineWidth = 1.9;
      ctx.beginPath();
      ctx.arc(-0.8, -24.8, 2, Math.PI * 1.12, Math.PI * 1.88);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(4.6, -24.8, 2, Math.PI * 1.12, Math.PI * 1.88);
      ctx.stroke();
      // Happy grin
      ctx.fillStyle = RED;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(2, -22.7, 1.8, 0, Math.PI);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    } else if (mood === "shocked") {
      // Wide O_O shocked sclera + pinpoint pupils
      ctx.fillStyle = "#ffffff";
      ctx.strokeStyle = INK;
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      ctx.arc(-0.8, -25.6, 2.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(4.7, -25.6, 2.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = INK;
      ctx.beginPath();
      ctx.arc(-0.6, -25.6, 0.9, 0, Math.PI * 2);
      ctx.arc(4.9, -25.6, 0.9, 0, Math.PI * 2);
      ctx.fill();

      // Raised worried brows
      ctx.beginPath();
      ctx.moveTo(-3.2, -28.6);
      ctx.lineTo(-0.2, -29.6);
      ctx.moveTo(3.6, -29.6);
      ctx.lineTo(6.8, -28.6);
      ctx.stroke();

      // Tiny gasped 'o' mouth
      ctx.fillStyle = "#a92828";
      ctx.beginPath();
      ctx.ellipse(2, -21.4, 1.5, 1.9, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      // Cute anime sweat drop by temple
      const dropBob = (now * 0.012) % 3;
      ctx.fillStyle = "#7dd3fc";
      ctx.strokeStyle = INK;
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.moveTo(-11.8, -30.5 + dropBob);
      ctx.quadraticCurveTo(-9.5, -27 + dropBob, -11.8, -25.6 + dropBob);
      ctx.quadraticCurveTo(-14.1, -27 + dropBob, -11.8, -30.5 + dropBob);
      ctx.fill();
      ctx.stroke();
    } else if (mood === "thinking") {
      // Glancing upward-right inquisitive eyes + raised brow
      ctx.fillStyle = INK;
      ctx.beginPath();
      ctx.arc(-0.3, -26.2, 1.45, 0, Math.PI * 2);
      ctx.arc(4.9, -26.2, 1.45, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#ffffff";
      ctx.beginPath();
      ctx.arc(0.1, -26.7, 0.55, 0, Math.PI * 2);
      ctx.arc(5.3, -26.7, 0.55, 0, Math.PI * 2);
      ctx.fill();

      // One arched brow
      ctx.strokeStyle = INK;
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      ctx.moveTo(-2.4, -28.2);
      ctx.lineTo(0.8, -28.2);
      ctx.moveTo(3.2, -29.4);
      ctx.quadraticCurveTo(5, -30.5, 6.8, -28.9);
      ctx.stroke();

      // Cute 'hmm' mouth
      ctx.beginPath();
      ctx.moveTo(0.6, -21.8);
      ctx.quadraticCurveTo(2.2, -22.5, 3.6, -21.6);
      ctx.stroke();
    } else {
      // Idle or Walk: bright dark eyes with crisp white catchlights + periodic blink
      if (blinking) {
        ctx.strokeStyle = INK;
        ctx.lineWidth = 1.8;
        ctx.beginPath();
        ctx.moveTo(-2.2, -25.4);
        ctx.lineTo(0.8, -25.4);
        ctx.moveTo(3.2, -25.4);
        ctx.lineTo(6.2, -25.4);
        ctx.stroke();
      } else {
        ctx.fillStyle = INK;
        ctx.beginPath();
        ctx.arc(-0.6, -25.5, 1.55, 0, Math.PI * 2);
        ctx.arc(4.7, -25.5, 1.55, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "#ffffff";
        ctx.beginPath();
        ctx.arc(-1, -26.1, 0.58, 0, Math.PI * 2);
        ctx.arc(4.3, -26.1, 0.58, 0, Math.PI * 2);
        ctx.fill();
      }
      // Determined brows when walking, cozy smile otherwise
      ctx.strokeStyle = INK;
      ctx.lineWidth = 1.5;
      if (mood === "walk") {
        ctx.beginPath();
        ctx.moveTo(-2.2, -28.4);
        ctx.lineTo(0.6, -27.8);
        ctx.moveTo(3.4, -27.8);
        ctx.lineTo(6.2, -28.4);
        ctx.stroke();
      }
      ctx.beginPath();
      ctx.arc(2, -22.4, 1.5, 0.15 * Math.PI, 0.85 * Math.PI);
      ctx.stroke();
    }

    // --- Golden Glowing FIVES Monocle when `fivesOpen` ---
    if (fivesOpen) {
      const glowR = 5.4 + Math.sin(now * 0.008) * 0.8;
      ctx.fillStyle = "rgba(245, 200, 76, 0.34)";
      ctx.beginPath();
      ctx.arc(4.7, -25.5, glowR, 0, Math.PI * 2);
      ctx.fill();

      // Delicate hanging brass chain
      ctx.strokeStyle = "#c78509";
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.moveTo(7.8, -24.2);
      ctx.quadraticCurveTo(9.2, -20.2, 6.2, -17.5);
      ctx.stroke();

      // Monocle lens & rim
      ctx.fillStyle = "rgba(255, 243, 176, 0.55)";
      ctx.strokeStyle = "#e8a317";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(4.7, -25.5, 3.7, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      drawSparkle(ctx, 8.2, -28.6, 2.3, "#fff3bf");
    }

    // --- Espresso Fedora Hat (pops up slightly when shocked!) ---
    const hatLift = mood === "shocked" ? -2.6 : 0;
    ctx.save();
    ctx.translate(0, hatLift);
    ctx.fillStyle = "#433224";
    ctx.strokeStyle = INK;
    ctx.lineWidth = 1.9;
    // Brim
    ctx.beginPath();
    ctx.ellipse(0.5, -31.8, 12.8, 3.2, -0.05, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    // Crown with pinched detective indent
    ctx.beginPath();
    ctx.moveTo(-7.6, -32);
    ctx.quadraticCurveTo(-7.4, -40.2, -2.2, -39.8);
    ctx.quadraticCurveTo(0.4, -38.6, 3.2, -39.9);
    ctx.quadraticCurveTo(7.8, -40.2, 7.8, -32);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    // Gold hatband + brass buckle pip
    ctx.fillStyle = "#e8b339";
    ctx.fillRect(-7.2, -34.2, 14.6, 2.3);
    ctx.strokeRect(-7.2, -34.2, 14.6, 2.3);
    ctx.fillStyle = "#fff3bf";
    ctx.fillRect(2.2, -34.2, 2.4, 2.3);
    ctx.restore();

    // --- Chibi Hand & Brass Magnifying Glass ---
    let handX = 8.4, handY = -11.2;
    let lensX = 16.4, lensY = -18;
    if (mood === "happy") {
      handX = 8.5;
      handY = -17.5;
      lensX = 15.8;
      lensY = -27.5;
    } else if (mood === "shocked") {
      handX = 9.2;
      handY = -14.2;
      lensX = 18.2;
      lensY = -13.5;
    } else if (mood === "thinking") {
      // Chin-tapping paw!
      ctx.fillStyle = "#ffe3c4";
      ctx.strokeStyle = INK;
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      ctx.arc(3.2, -19.6, 2.3, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      handX = 7.8;
      handY = -11.8;
      lensX = 15.2;
      lensY = -16.8;
    } else if (walking || mood === "walk") {
      const armSwing = Math.cos(state.walkPhase) * 1.8;
      lensX += armSwing;
      lensY += armSwing * 0.5;
    }

    // Walnut handle
    ctx.strokeStyle = INK;
    ctx.lineWidth = 3.8;
    ctx.beginPath();
    ctx.moveTo(handX, handY);
    ctx.lineTo(lensX, lensY);
    ctx.stroke();
    ctx.strokeStyle = "#5c4028";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(handX, handY);
    ctx.lineTo(lensX, lensY);
    ctx.stroke();

    // Cute round chibi hand gripping handle
    ctx.fillStyle = "#ffe3c4";
    ctx.strokeStyle = INK;
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    ctx.arc(handX + 0.8, handY - 0.6, 2.3, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();

    // Brass outer rim + glass lens
    ctx.fillStyle = fivesOpen ? "#f5c84c" : "#e2a432";
    ctx.strokeStyle = INK;
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    ctx.arc(lensX, lensY, 5.4, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = fivesOpen ? "rgba(255, 240, 150, 0.88)" : "rgba(186, 230, 253, 0.85)";
    ctx.lineWidth = 1.3;
    ctx.beginPath();
    ctx.arc(lensX, lensY, 3.6, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();

    // Specular glint on magnifying glass
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.arc(lensX, lensY, 2.2, Math.PI * 1.1, Math.PI * 1.65);
    ctx.stroke();

    // Mood floating emotes (unflipped '?' for thinking, victory stars for happy)
    if (mood === "happy") {
      const pulse = 2.6 + Math.sin(now * 0.012) * 0.6;
      drawSparkle(ctx, -13, -34, pulse, "#f5c84c");
      drawSparkle(ctx, 13.5, -38, pulse * 0.85, "#fde6a8");
    } else if (mood === "thinking") {
      ctx.scale(facing, 1); // keep '?' upright regardless of facing!
      const qx = facing * 13.5;
      const qy = -36 + Math.sin(now * 0.006) * 1.8;
      ctx.font = "800 12px Inter, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.strokeStyle = PAPER;
      ctx.lineWidth = 3;
      ctx.strokeText("?", qx, qy);
      ctx.fillStyle = GOLD;
      ctx.fillText("?", qx, qy);
    }

    ctx.restore();
  }

  // ---------------------------------------------------------------------------
  // 4. Glitch-Bug Sprite (`Sprites.drawBug(ctx, x, y, now)`)
  // ---------------------------------------------------------------------------
  function drawBug(ctx, x, y, now) {
    const bob = Math.sin(now * 0.0085) * 1.9;
    const tilt = Math.sin(now * 0.005) * 0.06;
    const by = y + bob;

    ctx.save();
    ctx.translate(x, by);
    ctx.rotate(tilt);

    // 6 cute scurrying legs (3 per side)
    ctx.strokeStyle = INK;
    ctx.lineWidth = 1.6;
    ctx.lineCap = "round";
    for (let i = 0; i < 3; i++) {
      const ly = -2.5 + i * 2.6;
      const wigL = Math.sin(now * 0.02 + i * 1.7) * 1.4;
      const wigR = Math.cos(now * 0.02 + i * 1.7) * 1.4;
      ctx.beginPath();
      ctx.moveTo(-7.5, ly);
      ctx.lineTo(-11.5, ly - 0.8 + wigL);
      ctx.moveTo(7.5, ly);
      ctx.lineTo(11.5, ly - 0.8 + wigR);
      ctx.stroke();
    }

    // Wiggling antennae with glowing coral tips
    const antWig = Math.sin(now * 0.015) * 1.8;
    const antX1 = -8.2 + antWig;
    const antY1 = -12.4;
    const antX2 = 8.2 + antWig;
    const antY2 = -12.4;
    ctx.strokeStyle = INK;
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    ctx.moveTo(-3.8, -6.5);
    ctx.quadraticCurveTo(-6.5, -10.2, antX1, antY1);
    ctx.moveTo(3.8, -6.5);
    ctx.quadraticCurveTo(6.5, -10.2, antX2, antY2);
    ctx.stroke();

    ctx.fillStyle = "#ff6b6b";
    ctx.beginPath();
    ctx.arc(antX1, antY1, 1.5, 0, Math.PI * 2);
    ctx.arc(antX2, antY2, 1.5, 0, Math.PI * 2);
    ctx.fill();

    // Domed crimson beetle carapace
    ctx.fillStyle = "#e5484d";
    ctx.strokeStyle = INK;
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    ctx.arc(0, -0.5, 8.8, Math.PI, 0);
    ctx.lineTo(8.8, 3.2);
    ctx.quadraticCurveTo(0, 4.4, -8.8, 3.2);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();

    // Glossy carapace highlight + center seam
    ctx.strokeStyle = "rgba(255, 255, 255, 0.48)";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(0, -0.5, 6.4, Math.PI * 1.14, Math.PI * 1.48);
    ctx.stroke();

    ctx.strokeStyle = "rgba(35, 32, 27, 0.35)";
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(0, 0.5);
    ctx.lineTo(0, 3.6);
    ctx.stroke();

    // Blinking & darting eyes
    const blinking = (now % 2700) < 110;
    const lookX = Math.sin(now * 0.0028) * 0.7;
    if (blinking) {
      ctx.strokeStyle = INK;
      ctx.lineWidth = 1.8;
      ctx.beginPath();
      ctx.moveTo(-5.2, -2);
      ctx.lineTo(-1.4, -2);
      ctx.moveTo(1.4, -2);
      ctx.lineTo(5.2, -2);
      ctx.stroke();
    } else {
      ctx.fillStyle = "#ffffff";
      ctx.strokeStyle = INK;
      ctx.lineWidth = 1.3;
      ctx.beginPath();
      ctx.arc(-3.3, -2.1, 2.35, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(3.3, -2.1, 2.35, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = INK;
      ctx.beginPath();
      ctx.arc(-3.1 + lookX, -1.9, 1.1, 0, Math.PI * 2);
      ctx.arc(3.1 + lookX, -1.9, 1.1, 0, Math.PI * 2);
      ctx.fill();
    }

    // Deterministic pixel glitch sparks orbiting carapace
    const tick = Math.floor(now / 150);
    const sparkCols = [RED, TEAL, AMBER];
    for (let s = 0; s < 2; s++) {
      const h = (tick * 7 + s * 13) % 11;
      const sx = (s === 0 ? -1 : 1) * (9.5 + (h % 4) * 1.4);
      const sy = -8 + ((h * 3) % 9);
      ctx.fillStyle = sparkCols[(tick + s) % 3];
      ctx.fillRect(sx - 1.3, sy - 1.3, 2.6, 2.6);
    }

    ctx.restore();
  }

  // ---------------------------------------------------------------------------
  // 5. Isometric-Front Server Rack (`Sprites.drawRackProp(ctx, x, y, w, h, opts, now)`)
  //    (x, y) is rack center; opts: { suspect, solved, isEndpoint, posterior,
  //                                   selected, hovered, compact, showLock, id }
  // ---------------------------------------------------------------------------
  function drawRackProp(ctx, x, y, w, h, opts, now) {
    const selected = Boolean(opts.selected);
    const hovered = Boolean(opts.hovered);
    const solved = Boolean(opts.solved);
    const suspect = Boolean(opts.suspect);
    const isEndpoint = Boolean(opts.isEndpoint);
    const compact = Boolean(opts.compact);
    const showLock = Boolean(opts.showLock);
    const phaseId = opts.id !== undefined ? opts.id : 0;

    ctx.save();

    // Selection / proximity halo on floor
    if (selected || hovered) {
      ctx.strokeStyle = selected ? INK : GOLD;
      ctx.lineWidth = 2.2;
      ctx.setLineDash(selected ? [] : [4, 3]);
      rrect(ctx, x - w / 2 - 5, y - h / 2 - 5, w + 10, h + 10, 11);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Ground drop shadow + cute rubber rack feet
    ctx.fillStyle = "rgba(35, 32, 27, 0.14)";
    rrect(ctx, x - w / 2 + 1.5, y - h / 2 + 4.5, w, h, 8);
    ctx.fill();

    ctx.fillStyle = INK;
    rrect(ctx, x - w / 2 + 4, y + h / 2 - 2, 5, 4, 1.5);
    ctx.fill();
    rrect(ctx, x + w / 2 - 9, y + h / 2 - 2, 5, 4, 1.5);
    ctx.fill();

    // Cabinet palette
    let faceFill = "#dfe4ea";
    let topLidFill = "#eef2f6";
    let trimCol = "#697382";
    let led1 = "#38a169";
    let led2 = "#9eeadf";

    if (solved) {
      faceFill = GREEN;
      topLidFill = "#6fae69";
      trimCol = "#264a23";
      led1 = "#c6f7c0";
      led2 = "#ffffff";
    } else if (suspect) {
      faceFill = "#f3b643";
      topLidFill = "#fbd079";
      trimCol = "#7d4f06";
      const blink = Math.floor(now / 360 + phaseId) % 2 === 0;
      led1 = blink ? "#fff6cc" : "#dd6b34";
      led2 = blink ? "#dd6b34" : "#fff6cc";
    } else if (isEndpoint) {
      faceFill = "#4c7ce3";
      topLidFill = "#79a1f5";
      trimCol = "#1e3d82";
      led1 = "#bae6fd";
      led2 = "#ffffff";
    }

    const rx = x - w / 2;
    const ry = y - h / 2;

    // Main cabinet body
    ctx.fillStyle = faceFill;
    ctx.strokeStyle = INK;
    ctx.lineWidth = 2;
    rrect(ctx, rx, ry, w, h, 8);
    ctx.fill();

    // Isometric-front top lid bevel
    ctx.fillStyle = topLidFill;
    rrect(ctx, rx + 1, ry + 1, w - 2, 7.5, [7, 7, 2, 2]);
    ctx.fill();

    // Subtle bottom chassis shade
    ctx.fillStyle = "rgba(35, 32, 27, 0.10)";
    rrect(ctx, rx + 1, ry + h - 5, w - 2, 4, [1, 1, 7, 7]);
    ctx.fill();

    // Crisp outer ink stroke + lid seam
    rrect(ctx, rx, ry, w, h, 8);
    ctx.stroke();
    ctx.strokeStyle = "rgba(35, 32, 27, 0.22)";
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(rx + 2, ry + 7.5);
    ctx.lineTo(rx + w - 2, ry + 7.5);
    ctx.stroke();

    // Recessed status faceplate visor + dual LEDs
    const visorY = ry + 9.5;
    ctx.fillStyle = "rgba(35, 32, 27, 0.18)";
    rrect(ctx, rx + 4, visorY, w - 8, 7, 3.2);
    ctx.fill();

    ctx.fillStyle = led1;
    ctx.beginPath();
    ctx.arc(rx + 8.5, visorY + 3.5, 2.1, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = led2;
    ctx.beginPath();
    ctx.arc(rx + 14.5, visorY + 3.5, 1.9, 0, Math.PI * 2);
    ctx.fill();

    if (!compact) {
      // Mini management port square on right of visor
      ctx.fillStyle = "rgba(255, 255, 255, 0.45)";
      rrect(ctx, rx + w - 11, visorY + 1.8, 4.5, 3.4, 0.8);
      ctx.fill();
    }

    // Recessed vent grilles
    ctx.strokeStyle = trimCol;
    ctx.lineWidth = 1.5;
    ctx.lineCap = "round";
    const ventStart = compact ? y - 1 : y - 2.5;
    const ventCount = compact ? 2 : 3;
    for (let i = 0; i < ventCount; i++) {
      const vy = ventStart + i * 4.5;
      ctx.beginPath();
      ctx.moveTo(rx + 6.5, vy);
      ctx.lineTo(rx + w - 6.5, vy);
      ctx.stroke();
    }

    // Smooth posterior confidence bar along bottom of suspect racks
    if (suspect && !compact) {
      const bw = w - 10;
      const barY = ry + h - 8.5;
      ctx.fillStyle = "rgba(35, 32, 27, 0.25)";
      rrect(ctx, x - bw / 2, barY, bw, 4.2, 2.1);
      ctx.fill();
      const fillW = Math.max(3.5, bw * Math.min(1, Math.max(0, opts.posterior)));
      ctx.fillStyle = "#ffffff";
      rrect(ctx, x - bw / 2, barY, fillW, 4.2, 2.1);
      ctx.fill();
    }

    // Optional corner safety-constraint padlock badge
    if (showLock) {
      const lx = rx + w - 2.5;
      const ly = ry + 2.5;
      ctx.fillStyle = PAPER;
      ctx.strokeStyle = INK;
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.arc(lx, ly, 5.6, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      // Padlock shackle
      ctx.beginPath();
      ctx.arc(lx, ly - 1.1, 2, Math.PI, 0);
      ctx.stroke();

      // Padlock body
      ctx.fillStyle = RED;
      rrect(ctx, lx - 2.8, ly - 1, 5.6, 4.2, 1);
      ctx.fill();
      ctx.stroke();
    }

    ctx.restore();
  }

  // ---------------------------------------------------------------------------
  // 6. Miniature In-World Action Props (`Sprites.drawActionProp(ctx, kind, x, y, k)`)
  //    k in [0, 1] normalized FX progress (elastic pop-in -> hold -> smooth fade)
  // ---------------------------------------------------------------------------
  const PROP_ALIASES = {
    active_probe: "probe",
    packet_mirror: "mirror",
    subtle_weight_shift: "weight",
    control: "weight",
    flow_link_drain: "drain",
    flow_group_split: "split",
    full_link_drain: "cut",
    component_reset: "reboot",
    blocked: "shield",
  };

  function drawActionProp(ctx, kind, x, y, k) {
    const key = PROP_ALIASES[kind] !== undefined ? PROP_ALIASES[kind] : kind;
    const t = Math.max(0, Math.min(1, k));

    // Pop-in [0..0.16], crisp hold [0.16..0.72], smooth float-fade [0.72..1.0]
    let scale = 1;
    if (t < 0.16) {
      const u = t / 0.16;
      scale = 0.45 + 0.65 * Math.sin(u * Math.PI * 0.65);
    }
    const alpha = t > 0.72 ? Math.max(0, 1 - (t - 0.72) / 0.28) : 1;
    const floatY = t > 0.72 ? -((t - 0.72) / 0.28) * 7 : 0;

    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.translate(x, y + floatY);
    ctx.scale(scale, scale);
    ctx.lineCap = "round";
    ctx.lineJoin = "round";

    if (key === "probe") {
      // Miniature sonar dish + expanding ping waves
      ctx.strokeStyle = INK;
      ctx.lineWidth = 1.8;
      ctx.beginPath();
      ctx.moveTo(-6, 7);
      ctx.lineTo(1, 7);
      ctx.moveTo(-2.5, 4);
      ctx.lineTo(-2.5, 7);
      ctx.stroke();

      ctx.fillStyle = "#9eeadf";
      ctx.beginPath();
      ctx.arc(-2, 0.5, 5.5, Math.PI * 0.3, Math.PI * 1.2);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = AMBER;
      ctx.beginPath();
      ctx.arc(1.2, -1.8, 1.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      const wave = (t * 2.4) % 1;
      ctx.strokeStyle = TEAL;
      ctx.lineWidth = 1.8;
      ctx.beginPath();
      ctx.arc(2, -2.5, 3.5 + wave * 5.5, -Math.PI * 0.42, Math.PI * 0.05);
      ctx.stroke();
    } else if (key === "mirror") {
      // Gleaming optical prism reflecting a teal beam
      ctx.fillStyle = "#9eeadf";
      ctx.strokeStyle = INK;
      ctx.lineWidth = 1.8;
      ctx.beginPath();
      ctx.moveTo(0, -7.5);
      ctx.lineTo(7.5, 6);
      ctx.lineTo(-7.5, 6);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();

      ctx.strokeStyle = AMBER;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(-9.5, -3);
      ctx.lineTo(-2.5, 0);
      ctx.stroke();

      ctx.strokeStyle = TEAL;
      ctx.beginPath();
      ctx.moveTo(2.5, 0);
      ctx.lineTo(9.8, -4.5);
      ctx.stroke();
      drawSparkle(ctx, 0, -1, 2.4, "#ffffff");
    } else if (key === "weight") {
      // Tilting brass-and-indigo balance scale
      const tilt = Math.sin(t * Math.PI * 2.5) * 0.22 + 0.14;
      ctx.strokeStyle = INK;
      ctx.lineWidth = 1.8;
      ctx.beginPath();
      ctx.moveTo(-4.5, 7.5);
      ctx.lineTo(4.5, 7.5);
      ctx.moveTo(0, -5.5);
      ctx.lineTo(0, 7.5);
      ctx.stroke();

      ctx.save();
      ctx.translate(0, -4.5);
      ctx.rotate(tilt);
      ctx.beginPath();
      ctx.moveTo(-7.5, 0);
      ctx.lineTo(7.5, 0);
      ctx.stroke();

      ctx.fillStyle = AMBER;
      rrect(ctx, -9.5, 1.5, 4.2, 3.2, 1);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = INDIGO;
      rrect(ctx, 5.3, 1.5, 4.6, 4.2, 1);
      ctx.fill();
      ctx.stroke();
      ctx.restore();

      ctx.fillStyle = AMBER;
      ctx.beginPath();
      ctx.arc(0, -5.2, 2, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    } else if (key === "drain") {
      // Cute striped orange traffic cone + curved indigo reroute arrow
      ctx.fillStyle = CORAL;
      ctx.strokeStyle = INK;
      ctx.lineWidth = 1.8;
      rrect(ctx, -7.5, 5, 11.5, 2.8, 1);
      ctx.fill();
      ctx.stroke();

      ctx.beginPath();
      ctx.moveTo(-5.5, 5);
      ctx.lineTo(-3, -6.5);
      ctx.lineTo(-0.5, -6.5);
      ctx.lineTo(2, 5);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = PAPER;
      ctx.beginPath();
      ctx.moveTo(-4.3, 0.2);
      ctx.lineTo(-3.8, -2.5);
      ctx.lineTo(0.3, -2.5);
      ctx.lineTo(0.8, 0.2);
      ctx.closePath();
      ctx.fill();

      ctx.strokeStyle = INDIGO;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(3.2, 0, 5.4, Math.PI * 0.35, -Math.PI * 0.48, true);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(5.2, -7.2);
      ctx.lineTo(3, -5.3);
      ctx.lineTo(5.4, -3.5);
      ctx.stroke();
    } else if (key === "split") {
      // Indigo/Amber Y-fork splitter gate badge
      ctx.fillStyle = "#cbc5ff";
      ctx.strokeStyle = INK;
      ctx.lineWidth = 1.8;
      rrect(ctx, -7.5, -7.5, 15, 15, 4);
      ctx.fill();
      ctx.stroke();

      ctx.strokeStyle = INDIGO;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(-4.5, 0);
      ctx.lineTo(-0.5, 0);
      ctx.lineTo(4.2, -3.8);
      ctx.stroke();

      ctx.strokeStyle = AMBER;
      ctx.beginPath();
      ctx.moveTo(-0.5, 0);
      ctx.lineTo(4.2, 3.8);
      ctx.stroke();
    } else if (key === "cut") {
      // Snapping red-handled cable shears
      const open = 0.24 + Math.abs(Math.cos(t * Math.PI * 3)) * 0.34;
      ctx.strokeStyle = INK;
      ctx.lineWidth = 2;

      for (const sgn of [-1, 1]) {
        ctx.save();
        ctx.rotate(sgn * open);
        ctx.beginPath();
        ctx.moveTo(-4.5, 0);
        ctx.lineTo(8, 0);
        ctx.stroke();

        ctx.fillStyle = "#f9b4b4";
        ctx.beginPath();
        ctx.arc(-6.4, 0, 2.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.restore();
      }
      ctx.fillStyle = AMBER;
      ctx.beginPath();
      ctx.arc(0.8, 0, 1.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    } else if (key === "reboot") {
      // Spinning wrench + golden bolt spark
      ctx.save();
      ctx.rotate(t * Math.PI * 2.4);
      ctx.fillStyle = CORAL;
      ctx.strokeStyle = INK;
      ctx.lineWidth = 1.7;
      rrect(ctx, -2, -1.5, 9.5, 3.2, 1.4);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = "#dfe4ea";
      ctx.beginPath();
      ctx.arc(-3.8, 0, 4.2, Math.PI * 0.28, Math.PI * 1.72);
      ctx.lineTo(-2.2, -1.4);
      ctx.lineTo(-2.2, 1.4);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      ctx.restore();

      drawSparkle(ctx, 6.5, -6.5, 2.6, "#f5c84c");
    } else if (key === "shield") {
      // Crimson hexagonal safety badge with X
      const r = 8.8;
      ctx.fillStyle = RED;
      ctx.strokeStyle = INK;
      ctx.lineWidth = 1.8;
      ctx.beginPath();
      for (let i = 0; i < 6; i++) {
        const a = (Math.PI / 3) * i - Math.PI / 6;
        const px = Math.cos(a) * r;
        const py = Math.sin(a) * r;
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.closePath();
      ctx.fill();
      ctx.stroke();

      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 2.2;
      ctx.beginPath();
      ctx.moveTo(-3.2, -3.2);
      ctx.lineTo(3.2, 3.2);
      ctx.moveTo(3.2, -3.2);
      ctx.lineTo(-3.2, 3.2);
      ctx.stroke();
    } else {
      throw new Error("Sprites.drawActionProp: unknown kind '" + kind + "'");
    }

    ctx.restore();
  }

  function drawForensicsDesk(ctx, x, y, hovered, now) {
    ctx.save();
    ctx.translate(x, y);
    if (hovered) {
      ctx.strokeStyle = GOLD;
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 3]);
      rrect(ctx, -31, -24, 62, 42, 9);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    // Shadow
    ctx.fillStyle = "rgba(35,32,27,0.12)";
    rrect(ctx, -26, -6, 52, 20, 5);
    ctx.fill();
    // Desk legs
    ctx.fillStyle = "#5c4028";
    ctx.strokeStyle = INK;
    ctx.lineWidth = 1.8;
    rrect(ctx, -23, 2, 6, 11, 2);
    ctx.fill();
    ctx.stroke();
    rrect(ctx, 17, 2, 6, 11, 2);
    ctx.fill();
    ctx.stroke();
    // Wooden desk top
    ctx.fillStyle = "#c98b4b";
    rrect(ctx, -27, -7, 54, 11, 3.5);
    ctx.fill();
    ctx.stroke();
    // CRT Log Terminal on left of desk
    ctx.fillStyle = "#dfe4ea";
    rrect(ctx, -20, -22, 24, 16, 3.5);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "#1f2e2b";
    rrect(ctx, -17.5, -19.5, 19, 11, 2);
    ctx.fill();
    // Animated green log scan lines on screen
    ctx.strokeStyle = "#4ade80";
    ctx.lineWidth = 1.4;
    const scan = Math.floor(now / 280) % 3;
    for (let i = 0; i < 3; i++) {
      const ly = -16.8 + i * 3.1;
      const lw = i === scan ? 13 : 8 + (i * 3) % 6;
      ctx.beginPath();
      ctx.moveTo(-15, ly);
      ctx.lineTo(-15 + lw, ly);
      ctx.stroke();
    }
    // Cute coffee mug on right of desk + steam wisp
    ctx.fillStyle = "#fcfaf5";
    ctx.strokeStyle = INK;
    ctx.lineWidth = 1.6;
    rrect(ctx, 11, -15, 8.5, 9, 2);
    ctx.fill();
    ctx.stroke();
    ctx.strokeStyle = "rgba(117,110,98,0.6)";
    ctx.lineWidth = 1.2;
    const sw = Math.sin(now * 0.006) * 1.5;
    ctx.beginPath();
    ctx.moveTo(15, -17);
    ctx.quadraticCurveTo(15 + sw, -20, 15, -23);
    ctx.stroke();
    ctx.restore();
  }

  function drawHostProp(ctx, x, y, active, name) {
    ctx.save();
    ctx.translate(x, y);
    if (!active) ctx.globalAlpha = 0.42;
    // Little monitor stand + screen
    ctx.fillStyle = active ? "#3568d4" : "#cbd2dc";
    ctx.strokeStyle = active ? INK : "#828a96";
    ctx.lineWidth = 1.8;
    rrect(ctx, -13, -12, 26, 18, 4);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = active ? "#dbeafe" : "#eef1f5";
    rrect(ctx, -10, -9.5, 20, 11.5, 2);
    ctx.fill();

    // Base stand
    ctx.strokeStyle = active ? INK : "#828a96";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(0, 6);
    ctx.lineTo(0, 10);
    ctx.moveTo(-6, 10);
    ctx.lineTo(6, 10);
    ctx.stroke();

    ctx.font = active ? "800 11px Inter, sans-serif" : "600 10px Inter, sans-serif";
    ctx.fillStyle = active ? "#1e3a8a" : "#7c838f";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillText(name, 0, 13);
    ctx.restore();
  }

  function drawBgSwitchProp(ctx, x, y, name) {
    ctx.save();
    ctx.translate(x, y);
    ctx.globalAlpha = 0.38;
    ctx.fillStyle = "#dad5c8";
    ctx.strokeStyle = "#857e70";
    ctx.lineWidth = 1.6;
    rrect(ctx, -15, -14, 30, 28, 6);
    ctx.fill();
    ctx.stroke();
    ctx.strokeStyle = "#968f80";
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(-9, -2);
    ctx.lineTo(9, -2);
    ctx.moveTo(-9, 4);
    ctx.lineTo(9, 4);
    ctx.stroke();
    ctx.font = "600 9.5px Inter, sans-serif";
    ctx.fillStyle = "#6c6558";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    const lbl = name.length > 9 ? name.slice(0, 8) + "…" : name;
    ctx.fillText(lbl, 0, 16);
    ctx.restore();
  }

  const Sprites = {
    icon: icon,
    drawDetective: drawDetective,
    drawBug: drawBug,
    drawRackProp: drawRackProp,
    drawActionProp: drawActionProp,
    drawForensicsDesk: drawForensicsDesk,
    drawHostProp: drawHostProp,
    drawBgSwitchProp: drawBgSwitchProp,
    ICON_NAMES: Object.freeze(Object.keys(ICON_DEFS).concat(Object.keys(ICON_ALIASES))),
  };

  window.Sprites = Sprites;
})();
