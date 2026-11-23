// Inspector Switch · Procedural Web Audio Synthesizer (`window.GameAudio`)
// Unmistakable Sherlock Holmes chamber score:
//   - Hammered Cimbalom / Victorian Harpsichord broken-chord ostinato
//   - Bowed Solo Violin lead with vibrato (Sherlock's violin!)
//   - Stealthy Pizzicato Cello/Bass ("oom-pah" chromatic detective walk)
//   - Subtle Baker-Street Pocket-Watch tick
//   - Crisp alternating leather-shoe footsteps ("tap-tok") & per-action SFX
// 100% static Web Audio API — zero external audio files required.
"use strict";

(function () {
  const AudioCtor = window.AudioContext || window.webkitAudioContext;

  function mtof(midi) {
    return 440.0 * Math.pow(2.0, (midi - 69.0) / 12.0);
  }

  // 8-bar (64 sixteenth/eighth-grid steps at 112 BPM -> 1 step = 0.2678s, ~17.1s loop)
  // Key: C Harmonic Minor (C D Eb F G Ab B) with chromatic F# sleuth turns!
  // Chords:
  //   Bar 1: Cm          Bar 2: G7/B -> Cm
  //   Bar 3: Fm          Bar 4: Cm -> G7
  //   Bar 5: Cm          Bar 6: AbMaj7 -> F#dim7
  //   Bar 7: G7sus4->G7  Bar 8: Cm -> G7 turnaround

  // Pizzicato Cello/Contrabass ("oom ... oom ..." on beats, with sneaky chromatic walkups)
  const BASS_STEPS = [
    // Bar 1 (Cm)
    36, null, 43, null, 48, null, 43, null,
    // Bar 2 (G7/B -> Cm)
    35, null, 43, null, 36, null, 43, null,
    // Bar 3 (Fm)
    41, null, 48, null, 44, null, 41, null,
    // Bar 4 (Cm -> F# -> G7)
    36, null, 43, null, 42, null, 43, null,
    // Bar 5 (Cm)
    36, null, 43, null, 48, null, 47, null,
    // Bar 6 (Ab -> F#dim7)
    44, null, 48, null, 42, null, 45, null,
    // Bar 7 (G7 pedal suspense)
    43, null, 31, null, 43, null, 47, null,
    // Bar 8 (Cm -> G7 turnaround)
    36, null, 43, null, 36, null, 42, 43,
  ];

  // Hammered Cimbalom / Harpsichord broken-chord ostinato (classic Zimmer/Sherlock pulse!)
  const CIMBALOM_STEPS = [
    // Bar 1: Cm (C4 Eb4 G4 C5)
    60, 63, 67, 63, 72, 67, 63, 67,
    // Bar 2: G7/B -> Cm (B3 D4 G4 F4 -> C4 Eb4 G4)
    59, 62, 67, 65, 60, 63, 67, 63,
    // Bar 3: Fm (F4 Ab4 C5 Ab4)
    65, 68, 72, 68, 77, 72, 68, 65,
    // Bar 4: Cm -> G7 (Eb4 G4 C5 -> D4 F#4 G4 B4)
    63, 67, 72, 67, 62, 66, 67, 71,
    // Bar 5: Cm
    60, 63, 67, 72, 67, 63, 67, 63,
    // Bar 6: AbMaj7 -> F#dim7 (Ab3 C4 Eb4 G4 -> F#4 A4 C5 Eb5)
    56, 60, 63, 67, 66, 69, 72, 69,
    // Bar 7: G7(b9) suspense (G4 Ab4 B4 D5 F5)
    67, 68, 71, 74, 77, 74, 71, 68,
    // Bar 8: Cm -> G7 pickup
    60, 63, 67, 72, 60, null, 59, 62,
  ];

  // Off-beat staccato chamber strings ("oom-PAH, oom-PAH" Victorian parlor feel)
  const STAB_STEPS = [
    null, [60, 63, 67], null, [60, 63, 67], null, [60, 63, 67], null, [60, 67],
    null, [59, 62, 67], null, [59, 65, 67], null, [60, 63, 67], null, [60, 63],
    null, [60, 65, 68], null, [60, 65, 68], null, [60, 65, 68], null, [60, 65],
    null, [60, 63, 67], null, [60, 63], null, [59, 62, 67], null, [59, 65, 67],
    null, [60, 63, 67], null, [60, 63, 67], null, [60, 63, 67], null, [59, 67],
    null, [60, 63, 68], null, [60, 63, 68], null, [60, 66, 69], null, [60, 66, 69],
    null, [59, 62, 68], null, [59, 65, 68], null, [59, 62, 67], null, [59, 65, 67],
    null, [60, 63, 67], null, [60, 63], null, null, null, [59, 65, 67],
  ];

  // Sherlock's Bowed Solo Violin Melody [stepIndex, midiNote, durationInSteps]
  // Features dramatic minor-6th leaps, chromatic F#->G sleuth turns, and harmonic-minor B natural!
  const VIOLIN_NOTES = [
    // Bar 1: C5 -> G4 -> Eb5 -> D5 -> C5
    [0, 72, 1.8], [2, 67, 0.9], [3, 75, 2.2], [6, 74, 0.9], [7, 72, 0.9],
    // Bar 2: B4 -> D5 -> G4 -> C5
    [8, 71, 1.8], [10, 74, 0.9], [11, 67, 0.9], [12, 72, 3.2],
    // Bar 3: F5 -> G5 -> Ab5 -> F5 -> D5
    [16, 77, 1.8], [18, 79, 0.9], [19, 80, 2.2], [22, 77, 0.9], [23, 74, 0.9],
    // Bar 4: Eb5 -> C5 -> F#4 -> G4 (classic chromatic Sherlock turn!)
    [24, 75, 1.8], [26, 72, 1.6], [28, 66, 0.9], [29, 67, 2.5],
    // Bar 5: G4 -> C5 -> D5 -> Eb5 -> G5
    [32, 67, 0.9], [33, 72, 0.9], [34, 74, 0.9], [35, 75, 1.8], [37, 79, 2.5],
    // Bar 6: Ab5 -> G5 -> F#5 -> Eb5 -> C5
    [40, 80, 1.8], [42, 79, 0.9], [43, 78, 1.8], [45, 75, 1.4], [47, 72, 0.9],
    // Bar 7: D5 -> Eb5 -> D5 -> C5 -> B4 -> D5 -> G5
    [48, 74, 1.4], [50, 75, 0.9], [51, 74, 0.9], [52, 72, 0.9], [53, 71, 0.9], [54, 74, 1.8],
    // Bar 8: C5 dramatic hold + cheeky pickup B4 -> D5
    [56, 72, 4.2], [62, 71, 0.85], [63, 74, 0.85],
  ];

  const VIOLIN_BY_STEP = new Array(64).fill(null);
  for (const [idx, note, durSteps] of VIOLIN_NOTES) {
    VIOLIN_BY_STEP[idx] = { note, durSteps };
  }

  const STEP_SEC = 60.0 / 114.0 / 2.0; // eighth-note pulse at 114 BPM (~0.263s)

  const state = {
    ctx: null,
    masterGain: null,
    musicGain: null,
    sfxGain: null,
    noiseBuf: null,
    muted: false,
    musicStarted: false,
    musicPausedForEnd: false,
    stepIdx: 0,
    nextNoteTime: 0,
    timerId: null,
    lastStepSfxAt: 0,
    footParity: 0,
  };

  const MASTER_VOL = 0.38;
  const MUSIC_VOL = 0.14;

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

      // Victorian chamber slapback ambience
      const delay = ctx.createDelay(0.5);
      delay.delayTime.value = 0.195;
      const fb = ctx.createGain();
      fb.gain.value = 0.22;
      const wetLp = ctx.createBiquadFilter();
      wetLp.type = "lowpass";
      wetLp.frequency.value = 2100;
      const wetGain = ctx.createGain();
      wetGain.gain.value = 0.09;

      musicBus.connect(delay);
      delay.connect(wetLp);
      wetLp.connect(fb);
      fb.connect(delay);
      wetLp.connect(wetGain);
      wetGain.connect(master);
      state.musicGain = musicBus;

      const sfxBus = ctx.createGain();
      sfxBus.gain.value = 0.48;
      sfxBus.connect(master);
      state.sfxGain = sfxBus;

      // White-noise buffer for hammers, footsteps, relays
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
  // Sherlock Chamber Voices
  // ---------------------------------------------------------------------------
  function schedulePizzBass(ctx, t, midi) {
    const freq = mtof(midi);
    const osc = ctx.createOscillator();
    const body = ctx.createOscillator();
    osc.type = "sawtooth";
    body.type = "triangle";
    osc.frequency.setValueAtTime(freq, t);
    body.frequency.setValueAtTime(freq, t);

    const lp = ctx.createBiquadFilter();
    lp.type = "lowpass";
    lp.Q.value = 2.4;
    lp.frequency.setValueAtTime(680, t);
    lp.frequency.exponentialRampToValueAtTime(140, t + 0.22);

    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.linearRampToValueAtTime(0.46, t + 0.010);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.28);

    osc.connect(lp);
    body.connect(lp);
    lp.connect(g);
    g.connect(state.musicGain);

    osc.start(t);
    body.start(t);
    osc.stop(t + 0.30);
    body.stop(t + 0.30);
  }

  function scheduleCimbalom(ctx, t, midi) {
    // Slightly detuned pair of struck strings + crisp wooden hammer transient!
    const freq = mtof(midi);
    const osc1 = ctx.createOscillator();
    const osc2 = ctx.createOscillator();
    osc1.type = "sawtooth";
    osc2.type = "triangle";
    osc1.frequency.setValueAtTime(freq * 1.0032, t);
    osc2.frequency.setValueAtTime(freq * 0.9968, t);

    const bp = ctx.createBiquadFilter();
    bp.type = "lowpass";
    bp.Q.value = 1.8;
    bp.frequency.setValueAtTime(3400, t);
    bp.frequency.exponentialRampToValueAtTime(820, t + 0.22);

    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.linearRampToValueAtTime(0.16, t + 0.004);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.24);

    osc1.connect(bp);
    osc2.connect(bp);
    bp.connect(g);
    g.connect(state.musicGain);

    osc1.start(t);
    osc2.start(t);
    osc1.stop(t + 0.26);
    osc2.stop(t + 0.26);
  }

  function scheduleChamberStab(ctx, t, notes) {
    for (const midi of notes) {
      const osc = ctx.createOscillator();
      osc.type = "triangle";
      osc.frequency.setValueAtTime(mtof(midi), t);

      const lp = ctx.createBiquadFilter();
      lp.type = "lowpass";
      lp.frequency.setValueAtTime(1600, t);
      lp.frequency.exponentialRampToValueAtTime(600, t + 0.11);

      const g = ctx.createGain();
      g.gain.setValueAtTime(0.0001, t);
      g.gain.linearRampToValueAtTime(0.085, t + 0.007);
      g.gain.exponentialRampToValueAtTime(0.001, t + 0.12);

      osc.connect(lp);
      lp.connect(g);
      g.connect(state.musicGain);
      osc.start(t);
      osc.stop(t + 0.14);
    }
  }

  function scheduleSoloViolin(ctx, t, midi, durSec) {
    // Bowed solo detective violin: sawtooth + wooden body resonance + expressive vibrato!
    const freq = mtof(midi);
    const osc = ctx.createOscillator();
    osc.type = "sawtooth";
    osc.frequency.setValueAtTime(freq, t);

    // Vibrato LFO (5.8 Hz) kicking in gently as the bow sustains
    const lfo = ctx.createOscillator();
    const lfoGain = ctx.createGain();
    lfo.type = "sine";
    lfo.frequency.setValueAtTime(5.8, t);
    lfoGain.gain.setValueAtTime(0.2, t);
    lfoGain.gain.linearRampToValueAtTime(freq * 0.011, t + Math.min(0.18, durSec * 0.5));
    lfo.connect(lfoGain);
    lfoGain.connect(osc.frequency);

    // Violin wooden body resonance (warm formant around 950 Hz + smooth top roll-off)
    const body = ctx.createBiquadFilter();
    body.type = "peaking";
    body.frequency.value = 980;
    body.Q.value = 1.6;
    body.gain.value = 4.5;

    const lp = ctx.createBiquadFilter();
    lp.type = "lowpass";
    lp.frequency.setValueAtTime(2750, t);

    const g = ctx.createGain();
    const attack = Math.min(0.045, durSec * 0.25);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.linearRampToValueAtTime(0.22, t + attack);
    g.gain.setValueAtTime(0.19, t + Math.max(attack, durSec * 0.72));
    g.gain.exponentialRampToValueAtTime(0.0012, t + durSec);

    osc.connect(body);
    body.connect(lp);
    lp.connect(g);
    g.connect(state.musicGain);

    osc.start(t);
    lfo.start(t);
    osc.stop(t + durSec + 0.03);
    lfo.stop(t + durSec + 0.03);
  }

  function schedulePocketWatchTick(ctx, t, accent) {
    const src = ctx.createBufferSource();
    src.buffer = state.noiseBuf;
    const bp = ctx.createBiquadFilter();
    bp.type = "bandpass";
    bp.frequency.setValueAtTime(accent ? 3600 : 2900, t);
    bp.Q.value = 6.0;
    const g = ctx.createGain();
    g.gain.setValueAtTime(accent ? 0.045 : 0.028, t);
    g.gain.exponentialRampToValueAtTime(0.0008, t + 0.022);
    src.connect(bp);
    bp.connect(g);
    g.connect(state.musicGain);
    src.start(t);
    src.stop(t + 0.026);
  }

  function schedulerTick() {
    if (!state.ctx || state.muted || state.musicPausedForEnd || state.ctx.state !== "running") return;
    const lookahead = 0.28;
    while (state.nextNoteTime < state.ctx.currentTime + lookahead) {
      const s = state.stepIdx % 64;
      const t = state.nextNoteTime;

      const b = BASS_STEPS[s];
      if (b !== null) schedulePizzBass(state.ctx, t, b);

      const cimb = CIMBALOM_STEPS[s];
      if (cimb !== null) scheduleCimbalom(state.ctx, t, cimb);

      const stab = STAB_STEPS[s];
      if (stab !== null) scheduleChamberStab(state.ctx, t, stab);

      const vln = VIOLIN_BY_STEP[s];
      if (vln !== null) {
        scheduleSoloViolin(state.ctx, t, vln.note, vln.durSteps * STEP_SEC * 0.94);
      }

      // Subtle Baker-Street pocket-watch tick-tock on every beat
      if (s % 2 === 0) {
        schedulePocketWatchTick(state.ctx, t, s % 4 === 0);
      }

      state.nextNoteTime += STEP_SEC;
      state.stepIdx = (state.stepIdx + 1) % 64;
    }
  }

  function startMusic() {
    const ctx = ensureContext();
    if (!ctx) return;
    state.musicPausedForEnd = false;
    if (state.musicGain) {
      state.musicGain.gain.cancelScheduledValues(ctx.currentTime);
      state.musicGain.gain.setValueAtTime(MUSIC_VOL, ctx.currentTime);
    }
    if (!state.musicStarted) {
      state.musicStarted = true;
      state.stepIdx = 0;
      state.nextNoteTime = ctx.currentTime + 0.05;
      state.timerId = setInterval(schedulerTick, 90);
    } else if (state.nextNoteTime < ctx.currentTime) {
      state.nextNoteTime = ctx.currentTime + 0.05;
    }
  }

  function stopMusic() {
    state.musicPausedForEnd = true;
    if (state.timerId !== null) {
      clearInterval(state.timerId);
      state.timerId = null;
    }
    state.musicStarted = false;
    if (state.ctx && state.musicGain) {
      const now = state.ctx.currentTime;
      state.musicGain.gain.cancelScheduledValues(now);
      state.musicGain.gain.setValueAtTime(state.musicGain.gain.value, now);
      state.musicGain.gain.linearRampToValueAtTime(0.0001, now + 0.06);
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
    g.gain.linearRampToValueAtTime(peakGain, startT + 0.007);
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
    } else if (!state.musicPausedForEnd) {
      startMusic();
    }
    const now = ctx.currentTime;

    if (kind === "ui") {
      playNoiseBurst(ctx, now, 0.032, 1850, "bandpass", 0.18);
      playTone(ctx, 560, 420, now, 0.045, "triangle", 0.16);
      return;
    }

    if (kind === "step") {
      // Crisp, clearly audible alternating detective leather-shoe footsteps ("tap - tok")
      if (now - state.lastStepSfxAt < 0.165) return;
      state.lastStepSfxAt = now;
      const leftFoot = state.footParity === 0;
      state.footParity = 1 - state.footParity;

      // 1. Leather heel click transient (audibly cuts through laptop speakers!)
      playNoiseBurst(
        ctx,
        now,
        0.036,
        leftFoot ? 1280 : 1060,
        "bandpass",
        0.30,
        3.2
      );
      // 2. Wooden floorboard knock resonance
      playTone(
        ctx,
        leftFoot ? 330 : 285,
        leftFoot ? 155 : 135,
        now,
        0.058,
        "triangle",
        0.28
      );
      return;
    }

    if (kind === "active_probe") {
      playTone(ctx, 880, 1320, now, 0.11, "sine", 0.24);
      if (clean) {
        playTone(ctx, 1046.5, 1318.5, now + 0.16, 0.16, "triangle", 0.22);
      } else {
        playTone(ctx, 440, 261.6, now + 0.16, 0.22, "sawtooth", 0.18);
      }
      return;
    }

    if (kind === "packet_mirror") {
      playTone(ctx, 1568, 2093, now, 0.07, "sine", 0.22);
      playTone(ctx, clean ? 1318.5 : 370, clean ? 1568 : 277, now + 0.08, 0.16, "triangle", 0.20);
      return;
    }

    if (kind === "subtle_weight_shift") {
      for (let i = 0; i < 3; i++) {
        playTone(ctx, 720 + i * 140, 660 + i * 140, now + i * 0.045, 0.03, "triangle", 0.18);
      }
      playTone(ctx, 523.25, 783.99, now + 0.14, 0.18, "sine", 0.20);
      return;
    }

    if (kind === "flow_link_drain" || kind === "flow_group_split") {
      playNoiseBurst(ctx, now, 0.05, 1250, "bandpass", 0.24);
      playTone(ctx, 290, 540, now + 0.03, 0.16, "triangle", 0.24);
      playNoiseBurst(ctx, now + 0.05, 0.16, 920, "bandpass", 0.14);
      return;
    }

    if (kind === "full_link_drain") {
      playNoiseBurst(ctx, now, 0.06, 750, "lowpass", 0.32);
      playTone(ctx, 230, 95, now, 0.18, "sawtooth", 0.24);
      return;
    }

    if (kind === "component_reset") {
      playTone(ctx, 480, 85, now, 0.28, "sawtooth", 0.20);
      playTone(ctx, 261.6, 523.25, now + 0.30, 0.22, "triangle", 0.22);
      return;
    }

    if (kind === "accuse") {
      playTone(ctx, 196, 110, now, 0.12, "triangle", 0.30);
      playNoiseBurst(ctx, now, 0.04, 900, "lowpass", 0.24);
      return;
    }

    if (kind === "blocked") {
      playTone(ctx, 185, 130, now, 0.11, "sawtooth", 0.24);
      playTone(ctx, 155, 110, now + 0.12, 0.15, "sawtooth", 0.24);
      return;
    }

    if (kind === "cleared") {
      playTone(ctx, 659.25, 987.77, now, 0.09, "triangle", 0.18);
      return;
    }

    if (kind === "unlock" || kind === "hint") {
      // Sherlock C-minor -> G7 -> C6 sleuth flourish
      const notes = [72, 75, 79, 84];
      notes.forEach((m, i) => {
        playTone(ctx, mtof(m), mtof(m), now + i * 0.055, 0.18, "triangle", 0.20);
      });
      return;
    }

    if (kind === "win") {
      // Case Solved! Bright ascending Sherlock flourish + warm resolved C-major chord & chime
      const arpeggio = [67, 72, 76, 79];
      arpeggio.forEach((m, i) => {
        playTone(ctx, mtof(m), mtof(m), now + i * 0.085, 0.22, "triangle", 0.24);
      });
      const chordT = now + 0.34;
      for (const m of [60, 64, 67, 72, 76]) {
        playTone(ctx, mtof(m), mtof(m), chordT, 0.95, "triangle", 0.16);
      }
      playTone(ctx, mtof(84), mtof(84), chordT, 0.75, "sine", 0.18);
      return;
    }

    if (kind === "wrong") {
      // Wrong Suspect! Classic chromatic descending detective blunder ("wah - wah - waaah")
      playTone(ctx, mtof(67), mtof(66.5), now, 0.18, "sawtooth", 0.22);
      playTone(ctx, mtof(66), mtof(65.5), now + 0.20, 0.18, "sawtooth", 0.22);
      playTone(ctx, mtof(65), mtof(58), now + 0.40, 0.62, "sawtooth", 0.26);
      playTone(ctx, mtof(48), mtof(42), now + 0.40, 0.62, "triangle", 0.24);
      return;
    }

    if (kind === "fired") {
      // SLO Violated! Urgent pager double-alarm + dramatic low minor drop
      playTone(ctx, 880, 622.25, now, 0.12, "square", 0.16);
      playTone(ctx, 880, 622.25, now + 0.15, 0.12, "square", 0.16);
      playTone(ctx, mtof(54), mtof(36), now + 0.32, 0.72, "sawtooth", 0.30);
      playTone(ctx, mtof(48), mtof(36), now + 0.32, 0.72, "triangle", 0.26);
    }
  }

  function toggleMute() {
    state.muted = !state.muted;
    const ctx = ensureContext();
    if (ctx && state.masterGain) {
      state.masterGain.gain.setValueAtTime(state.muted ? 0.0 : MASTER_VOL, ctx.currentTime);
    }
    if (!state.muted && !state.musicPausedForEnd) {
      startMusic();
      sfx("ui");
    }
    return state.muted;
  }

  window.GameAudio = {
    startMusic,
    stopMusic,
    sfx,
    toggleMute,
    isMuted: () => state.muted,
  };
})();
