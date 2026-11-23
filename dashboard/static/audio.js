// Inspector Switch · Procedural Web Audio Synthesizer (`window.GameAudio`)
// Sherlock-style chamber mystery background theme + tactile SFX on every action.
// 100% static client-side Web Audio API — zero external audio files required.
"use strict";

(function () {
  const AudioCtor = window.AudioContext || window.webkitAudioContext;

  // MIDI -> Hz
  function mtof(midi) {
    return 440.0 * Math.pow(2.0, (midi - 69.0) / 12.0);
  }

  // 8-bar (32-beat, 64 eighth-note) Sherlock-inspired D harmonic minor chamber theme
  // Tempo: 104 BPM -> 1 eighth note = 0.288s (~18.4s seamless loop)
  // Chords: Dm | Dm/C | Gm/Bb | A7 | Dm | BbMaj7 | Edim7 A7 | Dm A7
  const BASS_EIGHTHS = [
    // Bar 1: Dm
    38, null, 45, null, 50, null, 45, null,
    // Bar 2: Dm/C
    36, null, 45, null, 50, null, 45, null,
    // Bar 3: Gm/Bb
    34, null, 43, null, 46, null, 43, null,
    // Bar 4: A7 (leading tone C# = 37/49)
    33, null, 40, null, 45, null, 37, null,
    // Bar 5: Dm
    38, null, 45, null, 53, null, 50, null,
    // Bar 6: BbMaj7
    34, null, 41, null, 46, null, 45, null,
    // Bar 7: Edim7 -> A7
    40, null, 43, null, 33, null, 37, null,
    // Bar 8: Dm -> A7 turnaround
    38, null, 45, null, 38, null, 33, 37,
  ];

  // Off-beat staccato chamber accompaniment (harpsichord/pizzicato strings)
  const CHORD_STABS = [
    // Bar 1 (Dm: F4 A4 D5)
    null, [65, 69], null, [62, 65, 69], null, [65, 69], null, [62, 69],
    // Bar 2 (Dm/C)
    null, [65, 69], null, [62, 65, 69], null, [65, 69], null, [64, 69],
    // Bar 3 (Gm)
    null, [62, 67], null, [58, 62, 67], null, [62, 67], null, [58, 67],
    // Bar 4 (A7b9: E4 G4 Bb4 C#5)
    null, [61, 67], null, [61, 64, 70], null, [61, 67], null, [61, 64],
    // Bar 5 (Dm)
    null, [65, 69], null, [62, 65, 69], null, [65, 69], null, [62, 69],
    // Bar 6 (BbMaj7: D4 F4 A4)
    null, [62, 65, 69], null, [62, 65], null, [62, 65, 69], null, [62, 65],
    // Bar 7 (Edim7 -> A7)
    null, [64, 67, 70], null, [64, 70], null, [61, 67, 69], null, [61, 67],
    // Bar 8 (Dm -> A7)
    null, [62, 65, 69], null, [62, 65], null, [61, 64, 67], null, null,
  ];

  // Inquisitive Baker-Street celesta/clavichord melody [midi, lengthInEighths]
  const MELODY = [
    // Bar 1
    [74, 2], null, [76, 1], [77, 2], null, [74, 1], [69, 2],
    // Bar 2
    null, [74, 1], [76, 1], [77, 2], [81, 2], [79, 1], [77, 1],
    // Bar 3
    [79, 3], null, null, [77, 1], [74, 1], [70, 2],
    // Bar 4 (harmonic minor C#5 = 73)
    null, [69, 2], null, [73, 2], null, [76, 1], [73, 1],
    // Bar 5
    [74, 2], null, [77, 1], [81, 2], null, [77, 1], [74, 2],
    // Bar 6
    null, [82, 2], null, [81, 2], [79, 1], [77, 1], [76, 2],
    // Bar 7
    null, [79, 2], null, [77, 1], [76, 1], [73, 2], [76, 2],
    // Bar 8
    null, [74, 4], null, null, null, null, [69, 1], [73, 1],
  ];

  // Flatten MELODY to fixed 64-step lookup cleanly:
  // Build exact step-indexed melody map (8 bars * 8 eighths = 64 steps)
  const MELODY_STEPS = new Array(64).fill(null);
  (function buildMelodyGrid() {
    const raw = [
      // Bar 1 (0..7)
      [0, 74, 1.8], [2, 76, 0.9], [3, 77, 1.8], [5, 74, 0.9], [6, 69, 1.8],
      // Bar 2 (8..15)
      [9, 74, 0.9], [10, 76, 0.9], [11, 77, 1.8], [13, 81, 1.6], [15, 77, 0.9],
      // Bar 3 (16..23)
      [16, 79, 2.6], [19, 77, 0.9], [20, 74, 1.4], [22, 70, 1.8],
      // Bar 4 (24..31)
      [24, 69, 1.8], [26, 73, 1.8], [28, 76, 1.4], [30, 73, 1.6],
      // Bar 5 (32..39)
      [32, 74, 1.8], [34, 77, 0.9], [35, 81, 1.8], [37, 77, 0.9], [38, 74, 1.8],
      // Bar 6 (40..47)
      [40, 82, 1.8], [42, 81, 1.8], [44, 79, 0.9], [45, 77, 0.9], [46, 76, 1.8],
      // Bar 7 (48..55)
      [48, 79, 1.8], [50, 77, 0.9], [51, 76, 0.9], [52, 73, 1.8], [54, 76, 1.6],
      // Bar 8 (56..63)
      [56, 74, 3.5], [62, 69, 0.9], [63, 73, 0.9],
    ];
    for (const [idx, note, durSteps] of raw) {
      MELODY_STEPS[idx] = { note, durSteps };
    }
  })();

  const state = {
    ctx: null,
    masterGain: null,
    musicGain: null,
    sfxGain: null,
    delayNode: null,
    noiseBuf: null,
    muted: false,
    musicStarted: false,
    stepIdx: 0,
    nextNoteTime: 0,
    timerId: null,
    lastStepSfxAt: 0,
  };

  const STEP_SEC = 60.0 / 104.0 / 2.0; // eighth note at 104 BPM (~0.2885s)

  function ensureContext() {
    if (!AudioCtor) return null;
    if (!state.ctx) {
      const ctx = new AudioCtor();
      state.ctx = ctx;

      const master = ctx.createGain();
      master.gain.value = state.muted ? 0.0 : 0.85;
      master.connect(ctx.destination);
      state.masterGain = master;

      // Subtle room slapback echo for the Sherlock chamber instruments
      const musicBus = ctx.createGain();
      musicBus.gain.value = 0.22;
      musicBus.connect(master);

      const delay = ctx.createDelay(0.5);
      delay.delayTime.value = 0.21;
      const fb = ctx.createGain();
      fb.gain.value = 0.22;
      const wetLp = ctx.createBiquadFilter();
      wetLp.type = "lowpass";
      wetLp.frequency.value = 1800;
      const wetGain = ctx.createGain();
      wetGain.gain.value = 0.18;

      musicBus.connect(delay);
      delay.connect(wetLp);
      wetLp.connect(fb);
      fb.connect(delay);
      wetLp.connect(wetGain);
      wetGain.connect(master);
      state.musicGain = musicBus;

      const sfxBus = ctx.createGain();
      sfxBus.gain.value = 0.55;
      sfxBus.connect(master);
      state.sfxGain = sfxBus;

      // Pre-build short white-noise buffer for tactile clicks / whooshes
      const len = Math.floor(ctx.sampleRate * 0.4);
      const buf = ctx.createBuffer(1, len, ctx.sampleRate);
      const ch = buf.getChannelData(0);
      for (let i = 0; i < len; i++) {
        ch[i] = Math.random() * 2.0 - 1.0;
      }
      state.noiseBuf = buf;
    }
    if (state.ctx.state === "suspended") {
      state.ctx.resume();
    }
    return state.ctx;
  }

  // ---------------------------------------------------------------------------
  // Chamber Theme Instrument Voices
  // ---------------------------------------------------------------------------
  function schedulePizzBass(ctx, t, midi) {
    const freq = mtof(midi);
    const osc = ctx.createOscillator();
    const sub = ctx.createOscillator();
    osc.type = "triangle";
    sub.type = "sine";
    osc.frequency.setValueAtTime(freq, t);
    sub.frequency.setValueAtTime(freq, t);

    const lp = ctx.createBiquadFilter();
    lp.type = "lowpass";
    lp.frequency.setValueAtTime(520, t);
    lp.frequency.exponentialRampToValueAtTime(150, t + 0.24);

    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.linearRampToValueAtTime(0.52, t + 0.012);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.34);

    osc.connect(lp);
    sub.connect(lp);
    lp.connect(g);
    g.connect(state.musicGain);

    osc.start(t);
    sub.start(t);
    osc.stop(t + 0.36);
    sub.stop(t + 0.36);
  }

  function scheduleChordStab(ctx, t, notes) {
    for (const midi of notes) {
      const freq = mtof(midi);
      const osc = ctx.createOscillator();
      osc.type = "triangle";
      osc.frequency.setValueAtTime(freq, t);

      const lp = ctx.createBiquadFilter();
      lp.type = "lowpass";
      lp.frequency.setValueAtTime(1500, t);
      lp.frequency.exponentialRampToValueAtTime(650, t + 0.14);

      const g = ctx.createGain();
      g.gain.setValueAtTime(0.0001, t);
      g.gain.linearRampToValueAtTime(0.11, t + 0.008);
      g.gain.exponentialRampToValueAtTime(0.001, t + 0.15);

      osc.connect(lp);
      lp.connect(g);
      g.connect(state.musicGain);
      osc.start(t);
      osc.stop(t + 0.17);
    }
  }

  function scheduleClavichordLead(ctx, t, midi, durSec) {
    const freq = mtof(midi);
    const osc1 = ctx.createOscillator();
    const osc2 = ctx.createOscillator();
    osc1.type = "triangle";
    osc2.type = "sawtooth";
    osc1.frequency.setValueAtTime(freq, t);
    osc2.frequency.setValueAtTime(freq * 2.0, t); // quiet harpsichord octave shimmer

    const lp = ctx.createBiquadFilter();
    lp.type = "lowpass";
    lp.frequency.setValueAtTime(2600, t);
    lp.frequency.exponentialRampToValueAtTime(900, t + durSec);

    const g1 = ctx.createGain();
    g1.gain.setValueAtTime(0.0001, t);
    g1.gain.linearRampToValueAtTime(0.24, t + 0.008);
    g1.gain.exponentialRampToValueAtTime(0.0015, t + durSec);

    const g2 = ctx.createGain();
    g2.gain.setValueAtTime(0.0001, t);
    g2.gain.linearRampToValueAtTime(0.038, t + 0.006);
    g2.gain.exponentialRampToValueAtTime(0.0008, t + Math.min(0.18, durSec));

    osc1.connect(g1);
    osc2.connect(g2);
    g1.connect(lp);
    g2.connect(lp);
    lp.connect(state.musicGain);

    osc1.start(t);
    osc2.start(t);
    osc1.stop(t + durSec + 0.03);
    osc2.stop(t + durSec + 0.03);
  }

  function schedulerTick() {
    if (!state.ctx || state.muted || state.ctx.state !== "running") return;
    const lookahead = 0.28;
    while (state.nextNoteTime < state.ctx.currentTime + lookahead) {
      const s = state.stepIdx % 64;
      const t = state.nextNoteTime;

      const b = BASS_EIGHTHS[s];
      if (b !== null) schedulePizzBass(state.ctx, t, b);

      const ch = CHORD_STABS[s];
      if (ch !== null) scheduleChordStab(state.ctx, t, ch);

      const mel = MELODY_STEPS[s];
      if (mel !== null) {
        scheduleClavichordLead(state.ctx, t, mel.note, mel.durSteps * STEP_SEC * 0.92);
      }

      state.nextNoteTime += STEP_SEC;
      state.stepIdx = (state.stepIdx + 1) % 64;
    }
  }

  function startMusic() {
    const ctx = ensureContext();
    if (!ctx) return;
    if (!state.musicStarted) {
      state.musicStarted = true;
      state.stepIdx = 0;
      state.nextNoteTime = ctx.currentTime + 0.06;
      state.timerId = setInterval(schedulerTick, 100);
    } else if (state.nextNoteTime < ctx.currentTime) {
      state.nextNoteTime = ctx.currentTime + 0.06;
    }
  }

  // ---------------------------------------------------------------------------
  // Procedural Sound Effects Primitives
  // ---------------------------------------------------------------------------
  function playTone(ctx, freqStart, freqEnd, startT, dur, type, peakGain) {
    const osc = ctx.createOscillator();
    osc.type = type;
    osc.frequency.setValueAtTime(freqStart, startT);
    if (freqEnd !== freqStart) {
      osc.frequency.exponentialRampToValueAtTime(Math.max(20, freqEnd), startT + dur);
    }
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, startT);
    g.gain.linearRampToValueAtTime(peakGain, startT + 0.008);
    g.gain.exponentialRampToValueAtTime(0.0008, startT + dur);
    osc.connect(g);
    g.connect(state.sfxGain);
    osc.start(startT);
    osc.stop(startT + dur + 0.02);
  }

  function playNoiseBurst(ctx, startT, dur, filterFreq, filterType, peakGain) {
    const src = ctx.createBufferSource();
    src.buffer = state.noiseBuf;
    const flt = ctx.createBiquadFilter();
    flt.type = filterType;
    flt.frequency.setValueAtTime(filterFreq, startT);
    flt.Q.value = 2.2;
    const g = ctx.createGain();
    g.gain.setValueAtTime(peakGain, startT);
    g.gain.exponentialRampToValueAtTime(0.001, startT + dur);
    src.connect(flt);
    flt.connect(g);
    g.connect(state.sfxGain);
    src.start(startT);
    src.stop(startT + dur + 0.01);
  }

  function sfx(kind, clean = true) {
    if (state.muted) return;
    const ctx = ensureContext();
    if (!ctx) return;
    startMusic();
    const now = ctx.currentTime;

    if (kind === "ui") {
      playNoiseBurst(ctx, now, 0.032, 1800, "bandpass", 0.16);
      playTone(ctx, 540, 420, now, 0.045, "triangle", 0.14);
      return;
    }

    if (kind === "step") {
      if (now - state.lastStepSfxAt < 0.19) return;
      state.lastStepSfxAt = now;
      playNoiseBurst(ctx, now, 0.025, 650, "lowpass", 0.09);
      playTone(ctx, 145, 95, now, 0.035, "sine", 0.07);
      return;
    }

    if (kind === "active_probe") {
      // Sonar radar ping + clean/drop reply
      playTone(ctx, 880, 1320, now, 0.11, "sine", 0.24);
      if (clean) {
        playTone(ctx, 1046.5, 1318.5, now + 0.16, 0.16, "triangle", 0.22);
      } else {
        playTone(ctx, 440, 261.6, now + 0.16, 0.22, "sawtooth", 0.16);
      }
      return;
    }

    if (kind === "packet_mirror") {
      // Optical lens clink
      playTone(ctx, 1568, 2093, now, 0.07, "sine", 0.20);
      playTone(ctx, clean ? 1318.5 : 370, clean ? 1568 : 277, now + 0.08, 0.16, "triangle", 0.18);
      return;
    }

    if (kind === "subtle_weight_shift") {
      // Precision brass dial ticks + smooth glide
      for (let i = 0; i < 3; i++) {
        playTone(ctx, 700 + i * 140, 650 + i * 140, now + i * 0.045, 0.03, "triangle", 0.16);
      }
      playTone(ctx, 523.25, 783.99, now + 0.14, 0.18, "sine", 0.18);
      return;
    }

    if (kind === "flow_link_drain" || kind === "flow_group_split") {
      // Mechanical patch-panel throw + reroute whoosh
      playNoiseBurst(ctx, now, 0.05, 1200, "bandpass", 0.22);
      playTone(ctx, 280, 520, now + 0.03, 0.16, "triangle", 0.22);
      playNoiseBurst(ctx, now + 0.05, 0.16, 900, "bandpass", 0.12);
      return;
    }

    if (kind === "full_link_drain") {
      // Heavy breaker snap
      playNoiseBurst(ctx, now, 0.06, 700, "lowpass", 0.30);
      playTone(ctx, 220, 95, now, 0.18, "sawtooth", 0.22);
      return;
    }

    if (kind === "component_reset") {
      // Power-down whine -> reboot chime
      playTone(ctx, 480, 85, now, 0.28, "sawtooth", 0.18);
      playTone(ctx, 261.6, 523.25, now + 0.30, 0.22, "triangle", 0.20);
      return;
    }

    if (kind === "accuse") {
      playTone(ctx, 196, 110, now, 0.12, "triangle", 0.28);
      playNoiseBurst(ctx, now, 0.04, 900, "lowpass", 0.22);
      return;
    }

    if (kind === "blocked") {
      // Metallic shield clang + double buzz
      playTone(ctx, 185, 130, now, 0.11, "sawtooth", 0.22);
      playTone(ctx, 155, 110, now + 0.12, 0.15, "sawtooth", 0.22);
      return;
    }

    if (kind === "cleared") {
      playTone(ctx, 659.25, 880, now, 0.09, "triangle", 0.16);
      return;
    }

    if (kind === "unlock" || kind === "hint") {
      // Sherlock monocle sparkle arpeggio (A4 - C#5 - E5 - A5)
      const notes = [69, 73, 76, 81];
      notes.forEach((m, i) => {
        playTone(ctx, mtof(m), mtof(m), now + i * 0.055, 0.18, "triangle", 0.18);
      });
      return;
    }

    if (kind === "win") {
      // Triumphant Picardy D-major detective cadence (D4 - F#4 - A4 - D5)
      const fanfare = [62, 66, 69, 74];
      fanfare.forEach((m, i) => {
        playTone(ctx, mtof(m), mtof(m), now + i * 0.085, 0.36, "triangle", 0.24);
      });
      return;
    }

    if (kind === "fired") {
      // Dramatic detective failure sting ("dun-dun-duuun!")
      playTone(ctx, mtof(58), mtof(58), now, 0.16, "sawtooth", 0.22);
      playTone(ctx, mtof(57), mtof(57), now + 0.18, 0.16, "sawtooth", 0.22);
      playTone(ctx, mtof(50), mtof(38), now + 0.36, 0.65, "sawtooth", 0.28);
    }
  }

  function toggleMute() {
    state.muted = !state.muted;
    const ctx = ensureContext();
    if (ctx && state.masterGain) {
      state.masterGain.gain.setValueAtTime(state.muted ? 0.0 : 0.85, ctx.currentTime);
    }
    if (!state.muted) {
      startMusic();
      sfx("ui");
    }
    return state.muted;
  }

  window.GameAudio = {
    startMusic,
    sfx,
    toggleMute,
    isMuted: () => state.muted,
  };
})();
