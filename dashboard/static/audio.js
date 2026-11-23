// Inspector Switch · Procedural Web Audio Synthesizer (`window.GameAudio`)
// Sherlock's Solo Bowed Violin Theme (16-bar BBC Sherlock motif + 221B Baker Street violin variation)
// with wooden violin body formants, bow swell, finger vibrato, portamento slides,
// and soft pizzicato cello accompaniment.
"use strict";

(function () {
  const AudioCtor = window.AudioContext || window.webkitAudioContext;

  function mtof(midi) {
    return 440.0 * Math.pow(2.0, (midi - 69.0) / 12.0);
  }

  // 16-bar (128 eighth-note steps at 104 BPM -> 1 step = 0.2885s, ~36.9s full piece)
  // Key: C Minor / C Harmonic Minor (C D Eb F G Ab B)
  //
  // Section A (Steps 0..63): Iconic BBC Sherlock Violin Theme
  // Section B (Steps 64..127): Sherlock's 221B Baker Street Lyrical Violin Solo

  const TOTAL_STEPS = 128;
  const STEP_SEC = 60.0 / 104.0 / 2.0;

  // Restored balanced volume (fixing the accidental double reduction)
  const MASTER_VOL = 0.58;
  const MUSIC_VOL = 0.22;
  const SFX_VOL = 0.58;

  // Sparse, warm Pizzicato Cello bassline
  const BASS_STEPS = [
    // --- Section A (Bars 1..8) ---
    // Bar 1: Cm
    36, null, null, null, 43, null, null, null,
    // Bar 2: G7/B -> Cm
    35, null, null, null, 43, null, 36, null,
    // Bar 3: Cm/Bb -> Ab
    36, null, null, null, 34, null, null, null,
    // Bar 4: Fm -> G7
    41, null, null, null, 43, null, null, null,
    // Bar 5: Cm -> Fm
    36, null, null, null, 41, null, null, null,
    // Bar 6: G7 -> Cm
    43, null, 35, null, 36, null, null, null,
    // Bar 7: Ab -> G7
    44, null, null, null, 43, null, null, null,
    // Bar 8: Cm
    36, null, null, null, 43, null, null, null,

    // --- Section B: Baker Street Solo Violin (Bars 9..16) ---
    // Bar 9: Cm -> Cm/Bb
    36, null, 43, null, 34, null, 43, null,
    // Bar 10: AbMaj7 -> G7
    32, null, 39, null, 31, null, 43, null,
    // Bar 11: Fm -> Ddim/F
    41, null, 48, null, 38, null, 44, null,
    // Bar 12: G7sus4 -> G7 (F# -> G)
    43, null, 42, null, 43, null, 35, null,
    // Bar 13: Cm -> Eb/Bb
    36, null, 43, null, 39, null, 46, null,
    // Bar 14: Ab -> F#dim7
    44, null, 48, null, 42, null, 45, null,
    // Bar 15: Cm/G -> G7
    43, null, 48, null, 43, null, 35, null,
    // Bar 16: Cm -> pickup
    36, null, 43, null, 36, null, null, null,
  ];

  // Gentle off-beat plucked chamber chords (soft triangle/sine harp)
  const COMP_STEPS = [
    // Section A
    null, null, [60, 63, 67], null, null, null, [60, 63, 67], null,
    null, null, [59, 62, 67], null, null, null, [60, 63, 67], null,
    null, null, [60, 63, 67], null, null, null, [58, 63, 67], null,
    null, null, [60, 65, 68], null, null, null, [59, 62, 67], null,
    null, null, [60, 63, 67], null, null, null, [60, 65, 68], null,
    null, null, [59, 62, 67], null, null, null, [60, 63, 67], null,
    null, null, [60, 63, 68], null, null, null, [59, 62, 67], null,
    null, null, [60, 63, 67], null, null, null, null, null,

    // Section B
    null, [60, 63], null, [63, 67], null, [58, 63], null, [63, 67],
    null, [60, 63], null, [63, 68], null, [59, 62], null, [62, 67],
    null, [60, 65], null, [65, 68], null, [62, 65], null, [65, 68],
    null, [60, 67], null, [60, 66], null, [59, 67], null, null,
    null, [60, 63], null, [63, 67], null, [63, 67], null, [67, 70],
    null, [60, 68], null, [63, 68], null, [60, 66], null, [63, 69],
    null, [60, 63, 67], null, [60, 67], null, [59, 62, 67], null, [59, 65],
    null, [60, 63, 67], null, null, null, null, null, null,
  ];

  // Sherlock's Bowed Solo Violin Score: [stepIdx, midi, durSteps, slideFromMidiOrNull]
  // Uses expressive portamento slides on key leaps (e.g. G4->C5, G4->Eb5, F#5->G5)!
  const VIOLIN_SCORE = [
    // --- Section A: Iconic BBC Sherlock Violin Theme ---
    // Bar 1: (from G4 pickup) -> C5 — C5 C5 D5 Eb5
    [0, 72, 1.95, 67], [2, 72, 0.88, null], [3, 72, 0.88, null], [4, 74, 1.9, null], [6, 75, 1.9, null],
    // Bar 2: D5 C5 B4 — (pickup G4)
    [8, 74, 1.45, null], [10, 72, 1.45, null], [12, 71, 2.7, null], [15, 67, 0.95, null],
    // Bar 3: C5 — C5 C5 D5 Eb5
    [16, 72, 1.95, 67], [18, 72, 0.88, null], [19, 72, 0.88, null], [20, 74, 1.9, null], [22, 75, 1.9, null],
    // Bar 4: F5 — D5 — (pickup G4)
    [24, 77, 2.7, 75], [27, 74, 3.1, null], [31, 67, 0.95, null],
    // Bar 5: Eb5 — D5 C5 Ab4 F5
    [32, 75, 1.95, 67], [34, 74, 0.92, null], [35, 72, 0.92, null], [36, 68, 1.85, null], [38, 77, 1.9, 72],
    // Bar 6: Eb5 D5 C5 B4 -> C5 (warm vibrato hold)
    [40, 75, 0.92, null], [41, 74, 0.92, null], [42, 72, 0.92, null], [43, 71, 0.92, null], [44, 72, 3.4, null],
    // Bar 7: Mysterious low-string turn G4 -> Ab4 -> G4 -> F#4 -> G4
    [48, 67, 1.8, null], [50, 68, 1.8, null], [52, 67, 1.4, null], [54, 66, 0.92, null], [55, 67, 0.95, null],
    // Bar 8: C5 hold -> high pickup D5 Eb5 into Baker Street Solo
    [56, 72, 4.2, 67], [62, 74, 0.92, null], [63, 75, 0.95, null],

    // --- Section B: 221B Baker Street Lyrical Violin Solo ---
    // Bar 9: Singing high G5 — F5 Eb5 D5 C5
    [64, 79, 2.8, 75], [67, 77, 0.92, null], [68, 75, 1.8, null], [70, 74, 0.92, null], [71, 72, 0.92, null],
    // Bar 10: Eb5 — D5 C5 B4 -> G4
    [72, 75, 2.7, null], [75, 74, 0.92, null], [76, 72, 1.8, null], [78, 71, 1.8, null],
    // Bar 11: Rising apasionato F4 -> Ab4 -> C5 -> F5 -> Ab5!
    [80, 65, 0.95, null], [81, 68, 0.95, null], [82, 72, 1.8, null], [84, 77, 1.8, 72], [86, 80, 1.9, 77],
    // Bar 12: Dramatic Sherlockian F#5 -> G5 trill/turn!
    [88, 79, 1.8, null], [90, 78, 1.8, null], [92, 79, 3.2, 78],
    // Bar 13: G5 -> Eb5 -> C5 -> D5 -> Eb5
    [96, 79, 1.8, null], [98, 75, 1.8, null], [100, 72, 1.8, null], [102, 74, 0.92, null], [103, 75, 0.92, null],
    // Bar 14: F5 -> Eb5 -> D5 -> C5 -> A4 -> C5 (diminished mystery)
    [104, 77, 1.8, null], [106, 75, 0.92, null], [107, 74, 0.92, null], [108, 72, 1.8, null], [110, 69, 0.92, null], [111, 72, 0.95, null],
    // Bar 15: D5 — Eb5 D5 C5 B4
    [112, 74, 2.8, null], [115, 75, 0.92, null], [116, 74, 1.8, null], [118, 71, 1.8, null],
    // Bar 16: Final C5 resolution + iconic G4 pickup back to Bar 1!
    [120, 72, 5.2, 71], [127, 67, 0.95, null],
  ];

  const VIOLIN_BY_STEP = new Array(TOTAL_STEPS).fill(null);
  for (const [idx, note, durSteps, slideFrom] of VIOLIN_SCORE) {
    VIOLIN_BY_STEP[idx] = { note, durSteps, slideFrom };
  }

  const state = {
    ctx: null,
    masterGain: null,
    musicGain: null,
    violinBodyIn: null,
    sfxGain: null,
    noiseBuf: null,
    muted: false,
    musicActive: false,
    stepIdx: 127, // Start right on the iconic G4 pickup sliding into C5!
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

      // Warm concert-parlor hall echo for Sherlock's solo violin
      const delay = ctx.createDelay(0.6);
      delay.delayTime.value = 0.24;
      const fb = ctx.createGain();
      fb.gain.value = 0.25;
      const wetLp = ctx.createBiquadFilter();
      wetLp.type = "lowpass";
      wetLp.frequency.value = 1750;
      const wetGain = ctx.createGain();
      wetGain.gain.value = 0.16;

      musicBus.connect(delay);
      delay.connect(wetLp);
      wetLp.connect(fb);
      fb.connect(delay);
      wetLp.connect(wetGain);
      wetGain.connect(master);
      state.musicGain = musicBus;

      // Dedicated acoustic Violin Body Resonator chain (shared across violin notes):
      //   1. Highpass 190 Hz (violin G3 body floor)
      //   2. Warm wood cavity resonance at 440 Hz (+3.5 dB)
      //   3. Singing bridge formant at 1020 Hz (+3.0 dB)
      //   4. Smooth silk lowpass at 2450 Hz (eliminates digital sawtooth buzz!)
      const vHp = ctx.createBiquadFilter();
      vHp.type = "highpass";
      vHp.frequency.value = 190;

      const vWood = ctx.createBiquadFilter();
      vWood.type = "peaking";
      vWood.frequency.value = 440;
      vWood.Q.value = 1.4;
      vWood.gain.value = 3.5;

      const vBridge = ctx.createBiquadFilter();
      vBridge.type = "peaking";
      vBridge.frequency.value = 1020;
      vBridge.Q.value = 1.8;
      vBridge.gain.value = 3.0;

      const vSilkLp = ctx.createBiquadFilter();
      vSilkLp.type = "lowpass";
      vSilkLp.frequency.value = 2450;
      vSilkLp.Q.value = 0.7;

      vHp.connect(vWood);
      vWood.connect(vBridge);
      vBridge.connect(vSilkLp);
      vSilkLp.connect(musicBus);
      state.violinBodyIn = vHp;

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
  // Sherlock Solo Violin + Chamber Accompaniment Voices
  // ---------------------------------------------------------------------------
  function scheduleSherlockViolin(ctx, t, midi, durSec, slideFromMidi) {
    const targetFreq = mtof(midi);
    const startFreq = slideFromMidi !== null ? mtof(slideFromMidi) : targetFreq;

    // Dual subtly detuned bowed-string oscillators for rich acoustic string warmth
    const osc1 = ctx.createOscillator();
    const osc2 = ctx.createOscillator();
    osc1.type = "sawtooth";
    osc2.type = "sawtooth";

    osc1.frequency.setValueAtTime(startFreq * 1.0018, t);
    osc2.frequency.setValueAtTime(startFreq * 0.9982, t);
    if (slideFromMidi !== null) {
      // Expressive finger portamento slide over 55ms
      osc1.frequency.exponentialRampToValueAtTime(targetFreq * 1.0018, t + 0.055);
      osc2.frequency.exponentialRampToValueAtTime(targetFreq * 0.9982, t + 0.055);
    }

    // Expressive finger vibrato (5.6 Hz) blooming smoothly on sustained notes
    const lfo = ctx.createOscillator();
    const lfoGain = ctx.createGain();
    lfo.type = "sine";
    lfo.frequency.setValueAtTime(5.6, t);
    lfoGain.gain.setValueAtTime(0.0, t);
    if (durSec > 0.30) {
      lfoGain.gain.setValueAtTime(0.0, t + 0.09);
      lfoGain.gain.linearRampToValueAtTime(targetFreq * 0.0125, t + Math.min(0.28, durSec * 0.55));
    }
    lfo.connect(lfoGain);
    lfoGain.connect(osc1.frequency);
    lfoGain.connect(osc2.frequency);

    // Subtle rosin bow-hair breath on initial stroke
    const bowNoise = ctx.createBufferSource();
    bowNoise.buffer = state.noiseBuf;
    const bowBp = ctx.createBiquadFilter();
    bowBp.type = "bandpass";
    bowBp.frequency.value = 1900;
    bowBp.Q.value = 2.5;
    const bowGain = ctx.createGain();
    bowGain.gain.setValueAtTime(0.032, t);
    bowGain.exponentialRampToValueAtTime(0.0005, t + 0.045);
    bowNoise.connect(bowBp);
    bowBp.connect(bowGain);
    bowGain.connect(state.violinBodyIn);

    // Smooth bowed envelope: swells gently, sustains singing tone, tapers cleanly
    const g = ctx.createGain();
    const attack = Math.min(0.068, durSec * 0.28);
    const sustainEnd = Math.max(attack + 0.02, durSec * 0.78);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.linearRampToValueAtTime(0.23, t + attack);
    g.gain.linearRampToValueAtTime(0.26, t + sustainEnd * 0.6);
    g.gain.setValueAtTime(0.22, t + sustainEnd);
    g.gain.exponentialRampToValueAtTime(0.0012, t + durSec + 0.025);

    osc1.connect(g);
    osc2.connect(g);
    g.connect(state.violinBodyIn);

    osc1.start(t);
    osc2.start(t);
    lfo.start(t);
    bowNoise.start(t);

    const stopAt = t + durSec + 0.04;
    osc1.stop(stopAt);
    osc2.stop(stopAt);
    lfo.stop(stopAt);
    bowNoise.stop(t + 0.055);
  }

  function schedulePizzCello(ctx, t, midi) {
    const freq = mtof(midi);
    const osc = ctx.createOscillator();
    osc.type = "triangle";
    osc.frequency.setValueAtTime(freq, t);

    const lp = ctx.createBiquadFilter();
    lp.type = "lowpass";
    lp.frequency.setValueAtTime(420, t);
    lp.frequency.exponentialRampToValueAtTime(140, t + 0.30);

    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.linearRampToValueAtTime(0.38, t + 0.012);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.36);

    osc.connect(lp);
    lp.connect(g);
    g.connect(state.musicGain);
    osc.start(t);
    osc.stop(t + 0.38);
  }

  function schedulePluckHarp(ctx, t, notes) {
    for (const midi of notes) {
      const osc = ctx.createOscillator();
      osc.type = "triangle";
      osc.frequency.setValueAtTime(mtof(midi), t);

      const lp = ctx.createBiquadFilter();
      lp.type = "lowpass";
      lp.frequency.setValueAtTime(1200, t);
      lp.frequency.exponentialRampToValueAtTime(500, t + 0.16);

      const g = ctx.createGain();
      g.gain.setValueAtTime(0.0001, t);
      g.gain.linearRampToValueAtTime(0.085, t + 0.009);
      g.gain.exponentialRampToValueAtTime(0.001, t + 0.17);

      osc.connect(lp);
      lp.connect(g);
      g.connect(state.musicGain);
      osc.start(t);
      osc.stop(t + 0.19);
    }
  }

  function schedulerTick() {
    if (!state.ctx || state.muted || !state.musicActive || state.ctx.state !== "running") return;
    const lookahead = 0.28;
    while (state.nextNoteTime < state.ctx.currentTime + lookahead) {
      const s = state.stepIdx % TOTAL_STEPS;
      const t = state.nextNoteTime;

      const b = BASS_STEPS[s];
      if (b !== null) schedulePizzCello(state.ctx, t, b);

      const comp = COMP_STEPS[s];
      if (comp !== null) schedulePluckHarp(state.ctx, t, comp);

      const vln = VIOLIN_BY_STEP[s];
      if (vln !== null) {
        scheduleSherlockViolin(state.ctx, t, vln.note, vln.durSteps * STEP_SEC * 0.96, vln.slideFrom);
      }

      state.nextNoteTime += STEP_SEC;
      state.stepIdx = (state.stepIdx + 1) % TOTAL_STEPS;
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
      state.stepIdx = 127; // Iconic G4 violin pickup sliding into C5!
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
  // Procedural Sound Effects (Never Restarts Background Music!)
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
      playNoiseBurst(ctx, now, 0.028, 1750, "bandpass", 0.16);
      playTone(ctx, 520, 400, now, 0.04, "triangle", 0.15);
      return;
    }

    if (kind === "step") {
      if (now - state.lastStepSfxAt < 0.17) return;
      state.lastStepSfxAt = now;
      const leftFoot = state.footParity === 0;
      state.footParity = 1 - state.footParity;

      playNoiseBurst(ctx, now, 0.034, leftFoot ? 1240 : 1040, "bandpass", 0.26, 3.0);
      playTone(ctx, leftFoot ? 320 : 275, leftFoot ? 150 : 132, now, 0.055, "triangle", 0.25);
      return;
    }

    if (kind === "active_probe") {
      playTone(ctx, 880, 1320, now, 0.11, "sine", 0.22);
      if (clean) {
        playTone(ctx, 1046.5, 1318.5, now + 0.15, 0.15, "triangle", 0.20);
      } else {
        playTone(ctx, 440, 261.6, now + 0.15, 0.20, "triangle", 0.20);
      }
      return;
    }

    if (kind === "packet_mirror") {
      playTone(ctx, 1568, 2093, now, 0.07, "sine", 0.20);
      playTone(ctx, clean ? 1318.5 : 370, clean ? 1568 : 277, now + 0.08, 0.15, "triangle", 0.19);
      return;
    }

    if (kind === "subtle_weight_shift") {
      for (let i = 0; i < 3; i++) {
        playTone(ctx, 720 + i * 140, 660 + i * 140, now + i * 0.045, 0.03, "triangle", 0.17);
      }
      playTone(ctx, 523.25, 783.99, now + 0.14, 0.17, "sine", 0.18);
      return;
    }

    if (kind === "flow_link_drain" || kind === "flow_group_split") {
      playNoiseBurst(ctx, now, 0.045, 1200, "bandpass", 0.20);
      playTone(ctx, 290, 520, now + 0.03, 0.15, "triangle", 0.21);
      return;
    }

    if (kind === "full_link_drain") {
      playNoiseBurst(ctx, now, 0.055, 750, "lowpass", 0.26);
      playTone(ctx, 220, 95, now, 0.17, "triangle", 0.22);
      return;
    }

    if (kind === "component_reset") {
      playTone(ctx, 460, 90, now, 0.26, "triangle", 0.20);
      playTone(ctx, 261.6, 523.25, now + 0.28, 0.20, "triangle", 0.20);
      return;
    }

    if (kind === "accuse") {
      playTone(ctx, 196, 110, now, 0.11, "triangle", 0.26);
      playNoiseBurst(ctx, now, 0.035, 900, "lowpass", 0.20);
      return;
    }

    if (kind === "blocked") {
      playTone(ctx, 185, 130, now, 0.10, "triangle", 0.22);
      playTone(ctx, 155, 110, now + 0.11, 0.14, "triangle", 0.22);
      return;
    }

    if (kind === "cleared") {
      playTone(ctx, 659.25, 987.77, now, 0.085, "triangle", 0.17);
      return;
    }

    if (kind === "unlock" || kind === "hint") {
      const notes = [72, 75, 79, 84];
      notes.forEach((m, i) => {
        playTone(ctx, mtof(m), mtof(m), now + i * 0.055, 0.17, "triangle", 0.18);
      });
      return;
    }

    if (kind === "win") {
      const arpeggio = [67, 72, 76, 79];
      arpeggio.forEach((m, i) => {
        playTone(ctx, mtof(m), mtof(m), now + i * 0.085, 0.22, "triangle", 0.22);
      });
      const chordT = now + 0.34;
      for (const m of [60, 64, 67, 72, 76]) {
        playTone(ctx, mtof(m), mtof(m), chordT, 0.85, "triangle", 0.14);
      }
      playTone(ctx, mtof(84), mtof(84), chordT, 0.65, "sine", 0.16);
      return;
    }

    if (kind === "wrong") {
      playTone(ctx, mtof(67), mtof(66.5), now, 0.18, "sawtooth", 0.18);
      playTone(ctx, mtof(66), mtof(65.5), now + 0.20, 0.18, "sawtooth", 0.18);
      playTone(ctx, mtof(65), mtof(58), now + 0.40, 0.58, "sawtooth", 0.22);
      playTone(ctx, mtof(48), mtof(42), now + 0.40, 0.58, "triangle", 0.22);
      return;
    }

    if (kind === "fired") {
      playTone(ctx, 784, 554.37, now, 0.11, "square", 0.14);
      playTone(ctx, 784, 554.37, now + 0.14, 0.11, "square", 0.14);
      playTone(ctx, mtof(54), mtof(36), now + 0.30, 0.65, "sawtooth", 0.24);
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
