// Inspector Switch · Procedural Web Audio Synthesizer (`window.GameAudio`)
// Mild, soft BBC-Sherlock-style chamber theme (celesta/plucked harp + soft pizzicato bass)
// + gentle tactile footsteps & per-action SFX.
// Strictly stops background music when a case ends and never restarts until a new case starts.
"use strict";

(function () {
  const AudioCtor = window.AudioContext || window.webkitAudioContext;

  function mtof(midi) {
    return 440.0 * Math.pow(2.0, (midi - 69.0) / 12.0);
  }

  // 8-bar (64 eighth-note steps at 106 BPM -> 1 step = 0.283s, ~18.1s loop)
  // Melody: Iconic C-minor Sherlock theme motif:
  //   Phrase 1: G4 | C5 . C5 C5 D5 Eb5 | D5 C5 B4 . G4 |
  //   Phrase 2: G4 | C5 . C5 C5 D5 Eb5 | F5 . D5 . .   |
  //   Phrase 3: G4 | Eb5 . D5 C5 Ab4 F5 | Eb5 D5 C5 B4  | C5 (rest & breathe)

  // Sparse, sneaky upright pizzicato bass (pure warm sine/triangle, plenty of air)
  const BASS_STEPS = [
    // Bar 1 (Cm)
    36, null, null, null, 43, null, null, null,
    // Bar 2 (G/B -> Cm)
    35, null, null, null, 43, null, 36, null,
    // Bar 3 (Cm/Bb -> Ab)
    34, null, null, null, 44, null, null, null,
    // Bar 4 (G7)
    43, null, null, null, 31, null, null, null,
    // Bar 5 (Cm -> Fm)
    36, null, null, null, 41, null, null, null,
    // Bar 6 (G7 -> Cm)
    43, null, 35, null, 36, null, null, null,
    // Bar 7 (Ab -> G7)
    44, null, null, null, 43, null, null, null,
    // Bar 8 (Cm -> sneaky G2 pickup)
    36, null, null, null, null, null, 43, null,
  ];

  // Soft off-beat plucked accompaniment (gentle 2-note chamber intervals, never crowded)
  const COMP_STEPS = [
    null, null, [60, 63], null, null, null, [60, 63], null,
    null, null, [59, 62], null, null, null, [60, 63], null,
    null, null, [58, 63], null, null, null, [56, 60], null,
    null, null, [59, 62], null, null, null, null, null,
    null, null, [60, 63], null, null, null, [60, 65], null,
    null, null, [59, 62], null, null, null, [60, 63], null,
    null, null, [56, 60], null, null, null, [59, 62], null,
    null, null, [60, 63], null, null, null, null, null,
  ];

  // Sherlock Theme Melody [stepIdx, midi, durSteps]
  // C5=72, D5=74, Eb5=75, F5=77, G5=79, Ab4=68, B4=71, G4=67
  const THEME_NOTES = [
    // Bar 1: C5 — C5 C5 D5 Eb5
    [0, 72, 1.9], [2, 72, 0.9], [3, 72, 0.9], [4, 74, 1.8], [6, 75, 1.8],
    // Bar 2: D5 C5 B4 — (pickup G4)
    [8, 74, 1.4], [10, 72, 1.4], [12, 71, 2.6], [15, 67, 0.9],
    // Bar 3: C5 — C5 C5 D5 Eb5
    [16, 72, 1.9], [18, 72, 0.9], [19, 72, 0.9], [20, 74, 1.8], [22, 75, 1.8],
    // Bar 4: F5 — D5 — (pickup G4)
    [24, 77, 2.6], [27, 74, 3.2], [31, 67, 0.9],
    // Bar 5: Eb5 — D5 C5 Ab4 F5
    [32, 75, 1.9], [34, 74, 0.9], [35, 72, 0.9], [36, 68, 1.8], [38, 77, 1.8],
    // Bar 6: Eb5 D5 C5 B4 -> C5
    [40, 75, 0.9], [41, 74, 0.9], [42, 72, 0.9], [43, 71, 0.9], [44, 72, 3.2],
    // Bar 7: sneaky echo G4 -> Ab4 -> G4 -> F#4 -> G4
    [48, 67, 1.6], [50, 68, 1.6], [52, 67, 1.4], [54, 66, 0.9], [55, 67, 0.9],
    // Bar 8: C4/C5 rest & pickup G4 into Bar 1
    [56, 60, 2.8], [63, 67, 0.9],
  ];

  const MELODY_BY_STEP = new Array(64).fill(null);
  for (const [idx, note, durSteps] of THEME_NOTES) {
    MELODY_BY_STEP[idx] = { note, durSteps };
  }

  const STEP_SEC = 60.0 / 106.0 / 2.0;
  const MASTER_VOL = 0.30;
  const MUSIC_VOL = 0.065; // Whisper-mild ambient background bed
  const SFX_VOL = 0.44;

  const state = {
    ctx: null,
    masterGain: null,
    musicGain: null,
    sfxGain: null,
    noiseBuf: null,
    muted: false,
    musicActive: false,
    stepIdx: 63, // start right on the iconic G4 pickup into C5!
    nextNoteTime: 0,
    timerId: null,
    lastStepSfxAt: 0,
    footParity: 0,
  };

  function ensureContext() {
    if (!AudioCtor) return null;
    if (!state.ctx) {
      const ctx = new AudioCtor();
      state.ctx = ctx;

      const master = ctx.createGain();
      master.gain.value = state.muted ? 0.0 : MASTER_VOL;
      master.connect(ctx.destination);
      state.masterGain = master;

      const musicBus = ctx.createGain();
      musicBus.gain.value = MUSIC_VOL;
      musicBus.connect(master);

      // Gentle warm room reverb/delay
      const delay = ctx.createDelay(0.5);
      delay.delayTime.value = 0.22;
      const fb = ctx.createGain();
      fb.gain.value = 0.18;
      const wetLp = ctx.createBiquadFilter();
      wetLp.type = "lowpass";
      wetLp.frequency.value = 1100;
      const wetGain = ctx.createGain();
      wetGain.gain.value = 0.08;

      musicBus.connect(delay);
      delay.connect(wetLp);
      wetLp.connect(fb);
      fb.connect(delay);
      wetLp.connect(wetGain);
      wetGain.connect(master);
      state.musicGain = musicBus;

      const sfxBus = ctx.createGain();
      sfxBus.gain.value = SFX_VOL;
      sfxBus.connect(master);
      state.sfxGain = sfxBus;

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
  // Mild, Warm Chamber Voices (Pure Sine + Low-Passed Triangle — Zero Harshness)
  // ---------------------------------------------------------------------------
  function scheduleSoftPizzBass(ctx, t, midi) {
    const freq = mtof(midi);
    const osc = ctx.createOscillator();
    osc.type = "sine";
    osc.frequency.setValueAtTime(freq, t);

    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.linearRampToValueAtTime(0.42, t + 0.015);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.36);

    osc.connect(g);
    g.connect(state.musicGain);
    osc.start(t);
    osc.stop(t + 0.38);
  }

  function scheduleSoftPluckComp(ctx, t, notes) {
    for (const midi of notes) {
      const osc = ctx.createOscillator();
      osc.type = "sine";
      osc.frequency.setValueAtTime(mtof(midi), t);

      const g = ctx.createGain();
      g.gain.setValueAtTime(0.0001, t);
      g.gain.linearRampToValueAtTime(0.12, t + 0.010);
      g.gain.exponentialRampToValueAtTime(0.001, t + 0.16);

      osc.connect(g);
      g.connect(state.musicGain);
      osc.start(t);
      osc.stop(t + 0.18);
    }
  }

  function scheduleSherlockLead(ctx, t, midi, durSec) {
    // Mellow celesta / plucked chamber harp (warm triangle + sine through 1.2 kHz lowpass)
    const freq = mtof(midi);
    const osc1 = ctx.createOscillator();
    const osc2 = ctx.createOscillator();
    osc1.type = "triangle";
    osc2.type = "sine";
    osc1.frequency.setValueAtTime(freq, t);
    osc2.frequency.setValueAtTime(freq, t);

    const lp = ctx.createBiquadFilter();
    lp.type = "lowpass";
    lp.frequency.setValueAtTime(1250, t);
    lp.frequency.exponentialRampToValueAtTime(520, t + durSec);

    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.linearRampToValueAtTime(0.30, t + 0.014);
    g.gain.exponentialRampToValueAtTime(0.0012, t + durSec);

    osc1.connect(lp);
    osc2.connect(lp);
    lp.connect(g);
    g.connect(state.musicGain);

    osc1.start(t);
    osc2.start(t);
    osc1.stop(t + durSec + 0.03);
    osc2.stop(t + durSec + 0.03);
  }

  function schedulerTick() {
    if (!state.ctx || state.muted || !state.musicActive || state.ctx.state !== "running") return;
    const lookahead = 0.28;
    while (state.nextNoteTime < state.ctx.currentTime + lookahead) {
      const s = state.stepIdx % 64;
      const t = state.nextNoteTime;

      const b = BASS_STEPS[s];
      if (b !== null) scheduleSoftPizzBass(state.ctx, t, b);

      const comp = COMP_STEPS[s];
      if (comp !== null) scheduleSoftPluckComp(state.ctx, t, comp);

      const mel = MELODY_BY_STEP[s];
      if (mel !== null) {
        scheduleSherlockLead(state.ctx, t, mel.note, mel.durSteps * STEP_SEC * 0.94);
      }

      state.nextNoteTime += STEP_SEC;
      state.stepIdx = (state.stepIdx + 1) % 64;
    }
  }

  function unlockContext() {
    ensureContext();
  }

  function startMusic() {
    const ctx = ensureContext();
    if (!ctx) return;
    if (state.musicGain) {
      state.musicGain.gain.cancelScheduledValues(ctx.currentTime);
      state.musicGain.gain.setValueAtTime(MUSIC_VOL, ctx.currentTime);
    }
    if (!state.musicActive) {
      state.musicActive = true;
      state.stepIdx = 63; // G4 pickup -> C5!
      state.nextNoteTime = ctx.currentTime + 0.06;
      if (state.timerId !== null) clearInterval(state.timerId);
      state.timerId = setInterval(schedulerTick, 90);
    } else if (state.nextNoteTime < ctx.currentTime) {
      state.nextNoteTime = ctx.currentTime + 0.06;
    }
  }

  function stopMusic() {
    state.musicActive = false;
    if (state.timerId !== null) {
      clearInterval(state.timerId);
      state.timerId = null;
    }
    if (state.ctx && state.musicGain) {
      const now = state.ctx.currentTime;
      state.musicGain.gain.cancelScheduledValues(now);
      state.musicGain.gain.setValueAtTime(state.musicGain.gain.value, now);
      state.musicGain.gain.linearRampToValueAtTime(0.0001, now + 0.05);
    }
  }

  // ---------------------------------------------------------------------------
  // Gentle Procedural Sound Effects (Never Restarts Background Music!)
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

  function playNoiseBurst(ctx, startT, dur, filterFreq, filterType, peakGain, qVal = 2.2) {
    const src = ctx.createBufferSource();
    src.buffer = state.noiseBuf;
    const flt = ctx.createBiquadFilter();
    flt.type = filterType;
    flt.frequency.setValueAtTime(filterFreq, startT);
    flt.Q.value = qVal;
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
    if (kind === "win" || kind === "wrong" || kind === "fired") {
      stopMusic();
    }
    const now = ctx.currentTime;

    if (kind === "ui") {
      playNoiseBurst(ctx, now, 0.028, 1750, "bandpass", 0.14);
      playTone(ctx, 520, 400, now, 0.04, "triangle", 0.13);
      return;
    }

    if (kind === "step") {
      if (now - state.lastStepSfxAt < 0.17) return;
      state.lastStepSfxAt = now;
      const leftFoot = state.footParity === 0;
      state.footParity = 1 - state.footParity;

      playNoiseBurst(ctx, now, 0.032, leftFoot ? 1220 : 1020, "bandpass", 0.24, 3.0);
      playTone(ctx, leftFoot ? 310 : 270, leftFoot ? 150 : 132, now, 0.052, "triangle", 0.22);
      return;
    }

    if (kind === "active_probe") {
      playTone(ctx, 880, 1320, now, 0.11, "sine", 0.20);
      if (clean) {
        playTone(ctx, 1046.5, 1318.5, now + 0.15, 0.15, "triangle", 0.18);
      } else {
        playTone(ctx, 440, 261.6, now + 0.15, 0.20, "triangle", 0.18);
      }
      return;
    }

    if (kind === "packet_mirror") {
      playTone(ctx, 1568, 2093, now, 0.07, "sine", 0.18);
      playTone(ctx, clean ? 1318.5 : 370, clean ? 1568 : 277, now + 0.08, 0.15, "triangle", 0.17);
      return;
    }

    if (kind === "subtle_weight_shift") {
      for (let i = 0; i < 3; i++) {
        playTone(ctx, 720 + i * 140, 660 + i * 140, now + i * 0.045, 0.03, "triangle", 0.15);
      }
      playTone(ctx, 523.25, 783.99, now + 0.14, 0.17, "sine", 0.16);
      return;
    }

    if (kind === "flow_link_drain" || kind === "flow_group_split") {
      playNoiseBurst(ctx, now, 0.045, 1200, "bandpass", 0.18);
      playTone(ctx, 290, 520, now + 0.03, 0.15, "triangle", 0.19);
      return;
    }

    if (kind === "full_link_drain") {
      playNoiseBurst(ctx, now, 0.055, 750, "lowpass", 0.24);
      playTone(ctx, 220, 95, now, 0.17, "triangle", 0.20);
      return;
    }

    if (kind === "component_reset") {
      playTone(ctx, 460, 90, now, 0.26, "triangle", 0.18);
      playTone(ctx, 261.6, 523.25, now + 0.28, 0.20, "triangle", 0.18);
      return;
    }

    if (kind === "accuse") {
      playTone(ctx, 196, 110, now, 0.11, "triangle", 0.24);
      playNoiseBurst(ctx, now, 0.035, 900, "lowpass", 0.18);
      return;
    }

    if (kind === "blocked") {
      playTone(ctx, 185, 130, now, 0.10, "triangle", 0.20);
      playTone(ctx, 155, 110, now + 0.11, 0.14, "triangle", 0.20);
      return;
    }

    if (kind === "cleared") {
      playTone(ctx, 659.25, 987.77, now, 0.085, "triangle", 0.15);
      return;
    }

    if (kind === "unlock" || kind === "hint") {
      const notes = [72, 75, 79, 84];
      notes.forEach((m, i) => {
        playTone(ctx, mtof(m), mtof(m), now + i * 0.055, 0.17, "triangle", 0.16);
      });
      return;
    }

    if (kind === "win") {
      const arpeggio = [67, 72, 76, 79];
      arpeggio.forEach((m, i) => {
        playTone(ctx, mtof(m), mtof(m), now + i * 0.085, 0.22, "triangle", 0.20);
      });
      const chordT = now + 0.34;
      for (const m of [60, 64, 67, 72, 76]) {
        playTone(ctx, mtof(m), mtof(m), chordT, 0.85, "triangle", 0.12);
      }
      playTone(ctx, mtof(84), mtof(84), chordT, 0.65, "sine", 0.14);
      return;
    }

    if (kind === "wrong") {
      playTone(ctx, mtof(67), mtof(66.5), now, 0.18, "triangle", 0.20);
      playTone(ctx, mtof(66), mtof(65.5), now + 0.20, 0.18, "triangle", 0.20);
      playTone(ctx, mtof(65), mtof(58), now + 0.40, 0.58, "triangle", 0.24);
      playTone(ctx, mtof(48), mtof(42), now + 0.40, 0.58, "sine", 0.20);
      return;
    }

    if (kind === "fired") {
      playTone(ctx, 784, 554.37, now, 0.11, "triangle", 0.18);
      playTone(ctx, 784, 554.37, now + 0.14, 0.11, "triangle", 0.18);
      playTone(ctx, mtof(54), mtof(36), now + 0.30, 0.65, "triangle", 0.24);
    }
  }

  function toggleMute() {
    state.muted = !state.muted;
    const ctx = ensureContext();
    if (ctx && state.masterGain) {
      state.masterGain.gain.setValueAtTime(state.muted ? 0.0 : MASTER_VOL, ctx.currentTime);
    }
    if (!state.muted) {
      sfx("ui");
    }
    return state.muted;
  }

  window.GameAudio = {
    unlockContext,
    startMusic,
    stopMusic,
    sfx,
    toggleMute,
    isMuted: () => state.muted,
  };
})();
