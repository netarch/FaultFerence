// Inspector Switch · Background Music & Procedural SFX Engine (`window.GameAudio`)
//
// Primary Background Music:
//   Streams the exact YouTube audio of Taryn Harbridge's "Sherlock Medley on Violin"
//   (`https://www.youtube.com/watch?v=l6B-8V4LyaU`) via the official YouTube IFrame API
//   at a gentle background level (`YT_VOL = 24`), tightly synchronized with Start Game,
//   Mute/Unmute, and Case End (Win / Wrong Accusation / SLO Violation).
//
// Automatic Offline / Adblocker Fallback:
//   If YouTube's embed player is blocked or does not enter PLAYING within 1.6s, seamlessly
//   runs a 32-bar (256-step) 4-voice acoustic arrangement of the exact BBC Sherlock Medley:
//     - Movement I: "Opening Titles / The Game Is On" (David Arnold & Michael Price, C Minor)
//     - Movement II: "Irene's Theme (SHERlocked)"
//   with custom PeriodicWave violin harmonics, 2nd-violin double-stops, hammered cimbalom
//   ostinato, and cello accompaniment.
"use strict";

(function () {
  const AudioCtor = window.AudioContext || window.webkitAudioContext;
  const YT_VIDEO_ID = "l6B-8V4LyaU";
  const YT_VOL = 24;

  function mtof(midi) {
    return 440.0 * Math.pow(2.0, (midi - 69.0) / 12.0);
  }

  // 32-bar medley = 256 eighth-note steps at 122 BPM (~62.9s full cycle)
  const TOTAL_STEPS = 256;
  const STEP_SEC = 60.0 / 122.0 / 2.0;

  const MASTER_VOL = 0.58;
  const MUSIC_VOL = 0.18;
  const SFX_VOL = 0.58;

  // ---------------------------------------------------------------------------
  // 1. Exact 32-Bar BBC Sherlock Medley Score (C Minor)
  // ---------------------------------------------------------------------------
  // Chord progression per 8-step bar: [celloRootMidi, celloFifthMidi, cimbalomPattern4, harmonyDroneMidi]
  const BAR_CHORDS = [
    // --- Movement I: BBC Sherlock Main Theme ("The Game Is On") ---
    // Bars 1..2: Driving C-minor Cimbalom + Pizzicato Intro Ostinato
    [36, 43, [60, 67, 63, 67, 60, 68, 67, 65], 55],
    [36, 43, [60, 67, 63, 67, 60, 66, 67, 59], 55],
    // Bar 3: Cm ("C — G G F# G—")
    [36, 43, [60, 67, 63, 67, 60, 67, 63, 67], 60],
    // Bar 4: Ab -> Fm ("— Ab G F")
    [44, 41, [56, 63, 60, 63, 56, 65, 60, 65], 56],
    // Bar 5: Fm -> G7 ("C' — F — C' C'")
    [41, 43, [56, 65, 60, 65, 59, 67, 62, 67], 60],
    // Bar 6: Cm ("B C' D' C'")
    [36, 43, [60, 67, 63, 67, 60, 67, 63, 67], 63],
    // Bar 7: Eb -> Cm ("Eb' — G' — C' C'")
    [39, 43, [63, 70, 67, 70, 60, 67, 63, 67], 67],
    // Bar 8: Fm7 -> G7 ("D' Eb' D' Eb' D' C' F'")
    [41, 43, [60, 68, 65, 68, 59, 67, 62, 67], 65],
    // Bar 9: Cm -> Ab ("C' — C' D' Eb' Eb'")
    [36, 44, [60, 67, 63, 67, 56, 63, 60, 63], 63],
    // Bar 10: Bb -> Cm ("F' D' D' Eb' C'")
    [46, 36, [58, 65, 62, 65, 60, 67, 63, 67], 62],
    // Bar 11: Ab -> Fm6 ("C' D' B Ab")
    [44, 41, [56, 63, 60, 63, 56, 62, 59, 62], 60],
    // Bar 12: G7sus4 -> G7 ("G — — F# G")
    [43, 35, [55, 62, 60, 62, 55, 62, 59, 62], 59],
    // Bar 13: Cm ("C' — G' — C' C'")
    [36, 43, [60, 67, 63, 67, 60, 67, 63, 67], 63],
    // Bar 14: Ab -> Fm ("D' Eb' D' C' F' C'")
    [44, 41, [56, 63, 60, 63, 56, 65, 60, 65], 60],
    // Bar 15: Dm7b5 -> G7 ("D' — Eb' D' B")
    [38, 43, [56, 62, 65, 62, 55, 62, 59, 67], 62],
    // Bar 16: Cm ("C' — — —")
    [36, 43, [60, 67, 63, 67, 60, 63, 67, 72], 63],

    // --- Movement II: Irene Adler's Theme ("SHERlocked") ---
    // Bar 17: Cm ("G' — C' C' Eb'")
    [36, 43, [60, 63, 67, 63, 60, 63, 67, 63], 63],
    // Bar 18: AbMaj7 -> G7 ("Ab' — G' —")
    [44, 43, [56, 60, 63, 67, 55, 59, 62, 67], 68],
    // Bar 19: Cm -> G/B ("C' D' B C' D'")
    [36, 35, [60, 63, 67, 63, 59, 62, 67, 62], 63],
    // Bar 20: Ab -> G7 ("G Ab C' D'")
    [44, 43, [56, 60, 63, 60, 55, 59, 62, 59], 60],
    // Bar 21: Cm -> Cm/Bb ("C' Eb' C' —")
    [36, 46, [60, 63, 67, 63, 58, 63, 67, 63], 63],
    // Bar 22: Eb -> Ab ("Eb' Bb' Ab' —")
    [39, 44, [58, 63, 67, 70, 56, 60, 63, 68], 67],
    // Bar 23: Dm7b5 -> Ab ("D' D' Eb' Ab' —")
    [38, 44, [56, 62, 65, 62, 56, 60, 63, 68], 65],
    // Bar 24: G7 ("G' — — —")
    [43, 35, [55, 59, 62, 67, 55, 59, 62, 67], 62],
    // Bar 25: Cm -> G/B ("C' D' B C' D'")
    [36, 35, [60, 63, 67, 63, 59, 62, 67, 62], 63],
    // Bar 26: Ab -> F#dim7 ("G Ab G Ab")
    [44, 42, [56, 60, 63, 60, 54, 60, 63, 60], 60],
    // Bar 27: Cm/G -> Ab ("G Ab' G' Ab'")
    [43, 44, [55, 60, 63, 67, 56, 60, 63, 68], 67],
    // Bar 28: G7sus4 -> G7 ("G' — Ab' —")
    [43, 35, [55, 60, 62, 67, 55, 59, 62, 68], 67],
    // Bar 29: Cm -> Fm ("G' — Eb' — D'")
    [36, 41, [60, 63, 67, 63, 56, 60, 65, 60], 63],
    // Bar 30: Cm ("C' — — —")
    [36, 43, [60, 67, 63, 67, 60, 67, 63, 67], 60],
    // Bars 31..32: Virtuoso Spiccato Turnaround back to Movement I
    [44, 43, [56, 63, 60, 68, 55, 62, 59, 67], 60],
    [36, 43, [60, 67, 63, 67, 60, 66, 67, 59], 55],
  ];

  // Lead Solo Violin Score: [stepIdx, midi, durSteps, slideFromMidiOrNull]
  const VIOLIN_SCORE = [
    // --- Movement I: BBC Sherlock Main Theme (Note-for-Note) ---
    // Pickup & Bars 3..4: C4 — G4 G4 F#4 G4 — Ab4 G4 F4
    [16, 60, 2.85, null], [19, 67, 0.92, 60], [20, 67, 0.90, null], [21, 66, 0.92, null], [22, 67, 3.80, null],
    [26, 68, 1.90, null], [28, 67, 1.90, null], [30, 65, 1.90, null],

    // Bars 5..6: C5 — F4 — C5 C5 B4 C5 D5 C5
    [32, 72, 2.85, 65], [35, 65, 2.85, null], [38, 72, 0.90, 67], [39, 72, 0.90, null],
    [40, 71, 0.92, null], [41, 72, 0.92, null], [42, 74, 1.90, null], [44, 72, 3.70, null],

    // Bars 7..8: Eb5 — G5 — C5 C5 D5 Eb5 D5 Eb5 D5 C5 F5
    [48, 75, 2.85, 72], [51, 79, 2.85, 75], [54, 72, 0.90, null], [55, 72, 0.90, null],
    [56, 74, 0.90, null], [57, 75, 0.90, null], [58, 74, 0.90, null], [59, 75, 0.90, null],
    [60, 74, 0.90, null], [61, 72, 0.90, null], [62, 77, 1.90, 72],

    // Bars 9..10: C5 — C5 D5 Eb5 Eb5 F5 D5 D5 Eb5 C5
    [64, 72, 2.85, null], [67, 72, 0.90, null], [68, 74, 0.90, null], [69, 75, 1.85, null], [71, 75, 0.90, null],
    [72, 77, 1.85, null], [74, 74, 1.85, null], [76, 74, 0.90, null], [77, 75, 0.90, null], [78, 72, 1.90, null],

    // Bars 11..12: C5 D5 B4 Ab4 G4 — — F#4 G4
    [80, 72, 1.85, null], [82, 74, 1.85, null], [84, 71, 1.85, null], [86, 68, 1.85, null],
    [88, 67, 5.60, null], [94, 66, 0.90, null], [95, 67, 0.92, null],

    // Bars 13..16: C5 — G5 — C5 C5 D5 Eb5 D5 C5 F5 C5 | D5 — Eb5 D5 B4 | C5 —
    [96, 72, 2.85, 67], [99, 79, 2.85, 72], [102, 72, 0.90, null], [103, 72, 0.90, null],
    [104, 74, 0.90, null], [105, 75, 0.90, null], [106, 74, 0.90, null], [107, 72, 0.90, null],
    [108, 77, 1.90, 72], [110, 72, 1.90, null],
    [112, 74, 2.85, null], [115, 75, 0.92, null], [116, 74, 1.85, null], [118, 71, 1.85, null],
    [120, 72, 6.80, 71],

    // --- Movement II: Irene Adler's Theme ("SHERlocked") ---
    // Bars 17..20: G5 — C5 C5 Eb5 | Ab5 — G5 — | C5 D5 B4 C5 D5 | G4 Ab4 C5 D5
    [128, 79, 3.80, 72], [132, 72, 1.85, null], [134, 72, 0.92, null], [135, 75, 0.92, null],
    [136, 80, 3.80, 75], [140, 79, 3.80, null],
    [144, 72, 1.85, null], [146, 74, 1.85, null], [148, 71, 1.85, null], [150, 72, 0.92, null], [151, 74, 0.92, null],
    [152, 67, 1.85, null], [154, 68, 1.85, null], [156, 72, 1.85, null], [158, 74, 1.85, null],

    // Bars 21..24: C5 Eb5 C5 — | Eb5 Bb5 Ab5 | D5 D5 Eb5 Ab5 | G5 —
    [160, 72, 1.85, null], [162, 75, 1.85, 72], [164, 72, 3.80, null],
    [168, 75, 1.90, null], [170, 82, 2.85, 75], [173, 80, 2.85, null],
    [176, 74, 1.85, null], [178, 74, 0.92, null], [179, 75, 0.92, null], [180, 80, 3.80, 75],
    [184, 79, 6.80, null],

    // Bars 25..30: C5 D5 B4 C5 D5 | G4 Ab4 G4 Ab4 | G4 Ab5 G5 Ab5 | G5 — Ab5 — | G5 — Eb5 — D5 | C5 —
    [192, 72, 1.85, null], [194, 74, 1.85, null], [196, 71, 1.85, null], [198, 72, 0.92, null], [199, 74, 0.92, null],
    [200, 67, 1.85, null], [202, 68, 1.85, null], [204, 67, 1.85, null], [206, 68, 1.85, null],
    [208, 67, 1.90, null], [210, 80, 1.90, 72], [212, 79, 1.90, null], [214, 80, 1.90, null],
    [216, 79, 3.80, null], [220, 80, 3.80, null],
    [224, 79, 2.85, null], [227, 75, 2.85, null], [230, 74, 1.90, null],
    [232, 72, 6.80, 71],

    // Bars 31..32: Spiccato Bridge Arpeggio back into Bar 1
    [240, 68, 0.90, null], [241, 72, 0.90, null], [242, 75, 0.90, null], [243, 80, 0.90, null],
    [244, 79, 1.85, null], [246, 74, 1.85, null],
    [248, 72, 2.85, 71], [252, 67, 1.85, null], [254, 66, 0.90, null], [255, 67, 0.92, null],
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
    violinWave: null,
    sfxGain: null,
    noiseBuf: null,
    muted: false,
    musicActive: false,

    // YouTube IFrame API primary stream state (`l6B-8V4LyaU`)
    ytEnabled: Boolean(
      window.location &&
        (window.location.protocol === "http:" || window.location.protocol === "https:")
    ),
    ytBooted: false,
    ytPlayer: null,
    ytReady: false,
    ytPlaying: false,
    ytFailed: false,
    ytTimedOutOnce: false,
    ytFallbackTimer: null,

    // Web Audio synth fallback scheduler state
    synthRunning: false,
    stepIdx: 0,
    nextNoteTime: 0,
    timerId: null,

    lastStepSfxAt: 0,
    footParity: 0,
  };

  // ---------------------------------------------------------------------------
  // 2. YouTube IFrame Player Integration (`https://www.youtube.com/watch?v=l6B-8V4LyaU`)
  // ---------------------------------------------------------------------------
  function initYoutubeAudio() {
    if (!state.ytEnabled || state.ytBooted || typeof document === "undefined") return;
    const mount = document.getElementById("yt-bgm-player");
    if (!mount) return;
    state.ytBooted = true;

    const createPlayer = () => {
      if (state.ytPlayer || !window.YT || !window.YT.Player) return;
      state.ytPlayer = new window.YT.Player("yt-bgm-player", {
        width: "200",
        height: "113",
        videoId: YT_VIDEO_ID,
        playerVars: {
          autoplay: 0,
          controls: 0,
          disablekb: 1,
          fs: 0,
          iv_load_policy: 3,
          loop: 1,
          playlist: YT_VIDEO_ID,
          modestbranding: 1,
          playsinline: 1,
          rel: 0,
          origin: window.location.origin,
        },
        events: {
          onReady: (ev) => {
            state.ytReady = true;
            ev.target.setVolume(YT_VOL);
            if (state.muted) {
              ev.target.mute();
            } else {
              ev.target.unMute();
            }
            if (state.musicActive && !state.muted) {
              ev.target.playVideo();
            }
          },
          onStateChange: (ev) => {
            // YT.PlayerState: ENDED=0, PLAYING=1, PAUSED=2, BUFFERING=3
            if (ev.data === 1) {
              if (!state.musicActive || state.muted) {
                state.ytPlaying = false;
                ev.target.pauseVideo();
                return;
              }
              state.ytPlaying = true;
              if (state.ytFallbackTimer !== null) {
                clearTimeout(state.ytFallbackTimer);
                state.ytFallbackTimer = null;
              }
              // Fade out synth fallback immediately so only the real YouTube track plays!
              stopSynthScheduler();
            } else if (ev.data === 0) {
              state.ytPlaying = false;
              if (state.musicActive && !state.muted) {
                ev.target.seekTo(0, true);
                ev.target.playVideo();
              }
            } else if (ev.data === 2) {
              state.ytPlaying = false;
            }
          },
          onError: () => {
            state.ytFailed = true;
            state.ytPlaying = false;
            if (state.musicActive && !state.muted) {
              startSynthScheduler();
            }
          },
        },
      });
    };

    if (window.YT && window.YT.Player) {
      createPlayer();
      return;
    }

    const prevCb = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = function () {
      if (typeof prevCb === "function") prevCb();
      createPlayer();
    };

    const script = document.createElement("script");
    script.src = "https://www.youtube.com/iframe_api";
    script.async = true;
    script.onerror = () => {
      state.ytFailed = true;
      if (state.musicActive && !state.muted) {
        startSynthScheduler();
      }
    };
    document.head.appendChild(script);
  }

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", initYoutubeAudio);
    } else {
      initYoutubeAudio();
    }
  }

  // ---------------------------------------------------------------------------
  // 3. Web Audio Context & Acoustic Violin Body Resonator
  // ---------------------------------------------------------------------------
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

      // Concert-hall stereo/parlor reflection for chamber depth
      const delay = ctx.createDelay(0.6);
      delay.delayTime.value = 0.23;
      const fb = ctx.createGain();
      fb.gain.value = 0.26;
      const wetLp = ctx.createBiquadFilter();
      wetLp.type = "lowpass";
      wetLp.frequency.value = 1850;
      const wetGain = ctx.createGain();
      wetGain.gain.value = 0.18;

      musicBus.connect(delay);
      delay.connect(wetLp);
      wetLp.connect(fb);
      fb.connect(delay);
      wetLp.connect(wetGain);
      wetGain.connect(master);
      state.musicGain = musicBus;

      // Custom PeriodicWave modeled on measured acoustic Stradivarius violin partials
      const real = new Float32Array(12);
      const imag = new Float32Array([
        0.0, 1.00, 0.68, 0.46, 0.34, 0.24, 0.17, 0.12, 0.08, 0.055, 0.035, 0.02,
      ]);
      state.violinWave = ctx.createPeriodicWave(real, imag);

      // Acoustic Violin Body Formant Chain (Helmholtz air resonance + wood + bridge)
      const vHp = ctx.createBiquadFilter();
      vHp.type = "highpass";
      vHp.frequency.value = 190;

      const vAir = ctx.createBiquadFilter();
      vAir.type = "peaking";
      vAir.frequency.value = 285;
      vAir.Q.value = 1.6;
      vAir.gain.value = 2.8;

      const vWood = ctx.createBiquadFilter();
      vWood.type = "peaking";
      vWood.frequency.value = 460;
      vWood.Q.value = 1.5;
      vWood.gain.value = 3.2;

      const vBridge = ctx.createBiquadFilter();
      vBridge.type = "peaking";
      vBridge.frequency.value = 1080;
      vBridge.Q.value = 1.7;
      vBridge.gain.value = 2.6;

      const vSilkLp = ctx.createBiquadFilter();
      vSilkLp.type = "lowpass";
      vSilkLp.frequency.value = 2650;
      vSilkLp.Q.value = 0.7;

      vHp.connect(vAir);
      vAir.connect(vWood);
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
  // 4. Multi-Layered Ensemble Voices (Fallback When YouTube Is Unavailable)
  // ---------------------------------------------------------------------------
  function scheduleSherlockViolin(ctx, t, midi, durSec, slideFromMidi) {
    const targetFreq = mtof(midi);
    const startFreq = slideFromMidi !== null ? mtof(slideFromMidi) : targetFreq;

    const osc1 = ctx.createOscillator();
    const osc2 = ctx.createOscillator();
    osc1.setPeriodicWave(state.violinWave);
    osc2.setPeriodicWave(state.violinWave);

    osc1.frequency.setValueAtTime(startFreq * 1.0016, t);
    osc2.frequency.setValueAtTime(startFreq * 0.9984, t);
    if (slideFromMidi !== null) {
      osc1.frequency.exponentialRampToValueAtTime(targetFreq * 1.0016, t + 0.052);
      osc2.frequency.exponentialRampToValueAtTime(targetFreq * 0.9984, t + 0.052);
    }

    const lfo = ctx.createOscillator();
    const lfoGain = ctx.createGain();
    lfo.type = "sine";
    lfo.frequency.setValueAtTime(5.7, t);
    lfoGain.gain.setValueAtTime(0.0, t);
    if (durSec > 0.28) {
      lfoGain.gain.setValueAtTime(0.0, t + 0.08);
      lfoGain.gain.linearRampToValueAtTime(targetFreq * 0.012, t + Math.min(0.26, durSec * 0.55));
    }
    lfo.connect(lfoGain);
    lfoGain.connect(osc1.frequency);
    lfoGain.connect(osc2.frequency);

    const bowNoise = ctx.createBufferSource();
    bowNoise.buffer = state.noiseBuf;
    const bowBp = ctx.createBiquadFilter();
    bowBp.type = "bandpass";
    bowBp.frequency.value = 1950;
    bowBp.Q.value = 2.6;
    const bowGain = ctx.createGain();
    bowGain.gain.setValueAtTime(0.020, t);
    bowGain.gain.exponentialRampToValueAtTime(0.0005, t + 0.042);
    bowNoise.connect(bowBp);
    bowBp.connect(bowGain);
    bowGain.connect(state.violinBodyIn);

    const g = ctx.createGain();
    const attack = Math.min(0.055, durSec * 0.25);
    const sustainEnd = Math.max(attack + 0.02, durSec * 0.80);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.linearRampToValueAtTime(0.18, t + attack);
    g.gain.linearRampToValueAtTime(0.20, t + sustainEnd * 0.58);
    g.gain.setValueAtTime(0.165, t + sustainEnd);
    g.gain.exponentialRampToValueAtTime(0.001, t + durSec + 0.024);

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
    bowNoise.stop(t + 0.052);
  }

  function scheduleSecondViolinPad(ctx, t, midi, durSec) {
    const osc = ctx.createOscillator();
    osc.setPeriodicWave(state.violinWave);
    osc.frequency.setValueAtTime(mtof(midi), t);

    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.linearRampToValueAtTime(0.065, t + 0.14);
    g.gain.setValueAtTime(0.058, t + Math.max(0.18, durSec - 0.15));
    g.gain.exponentialRampToValueAtTime(0.0008, t + durSec);

    osc.connect(g);
    g.connect(state.violinBodyIn);
    osc.start(t);
    osc.stop(t + durSec + 0.03);
  }

  function scheduleCimbalom(ctx, t, midi, accent) {
    const freq = mtof(midi);
    const osc1 = ctx.createOscillator();
    const osc2 = ctx.createOscillator();
    osc1.type = "triangle";
    osc2.type = "sine";
    osc1.frequency.setValueAtTime(freq, t);
    osc2.frequency.setValueAtTime(freq * 2.0, t);

    const lp = ctx.createBiquadFilter();
    lp.type = "lowpass";
    lp.frequency.setValueAtTime(accent ? 2300 : 1650, t);
    lp.frequency.exponentialRampToValueAtTime(520, t + 0.20);

    const g = ctx.createGain();
    const pk = accent ? 0.105 : 0.072;
    g.gain.setValueAtTime(0.0001, t);
    g.gain.linearRampToValueAtTime(pk, t + 0.005);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.22);

    osc1.connect(lp);
    osc2.connect(lp);
    lp.connect(g);
    g.connect(state.musicGain);

    osc1.start(t);
    osc2.start(t);
    osc1.stop(t + 0.24);
    osc2.stop(t + 0.24);
  }

  function scheduleCello(ctx, t, midi, bowed) {
    const freq = mtof(midi);
    const osc = ctx.createOscillator();
    osc.setPeriodicWave(state.violinWave);
    osc.frequency.setValueAtTime(freq, t);

    const lp = ctx.createBiquadFilter();
    lp.type = "lowpass";
    lp.frequency.setValueAtTime(bowed ? 360 : 420, t);
    if (!bowed) {
      lp.frequency.exponentialRampToValueAtTime(140, t + 0.30);
    }

    const dur = bowed ? STEP_SEC * 3.8 : 0.34;
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.linearRampToValueAtTime(bowed ? 0.19 : 0.25, t + (bowed ? 0.06 : 0.01));
    g.gain.exponentialRampToValueAtTime(0.001, t + dur);

    osc.connect(lp);
    lp.connect(g);
    g.connect(state.musicGain);
    osc.start(t);
    osc.stop(t + dur + 0.03);
  }

  function schedulerTick() {
    if (!state.ctx || state.muted || !state.musicActive || !state.synthRunning || state.ytPlaying) {
      return;
    }
    if (state.ctx.state !== "running") return;
    if (state.nextNoteTime < state.ctx.currentTime) {
      state.nextNoteTime = state.ctx.currentTime + 0.03;
    }

    const lookahead = 0.28;
    while (state.nextNoteTime < state.ctx.currentTime + lookahead) {
      const s = state.stepIdx % TOTAL_STEPS;
      const barIdx = Math.floor(s / 8);
      const beatInBar = s % 8;
      const bar = BAR_CHORDS[barIdx];
      const t = state.nextNoteTime;
      const ireneSection = barIdx >= 16 && barIdx < 30;

      // 1. Cello foundation (pizzicato in Movement I, lyrical arco in Irene's Theme)
      if (beatInBar === 0) {
        scheduleCello(state.ctx, t, bar[0], ireneSection);
      } else if (beatInBar === 4) {
        scheduleCello(state.ctx, t, bar[1], ireneSection);
      }

      // 2. 2nd-Violin Harmony Drone / Double-Stop on bar downbeats
      if (beatInBar === 0 && barIdx >= 2) {
        scheduleSecondViolinPad(state.ctx, t, bar[3], STEP_SEC * 7.6);
      }

      // 3. Signature Victorian Cimbalom / Hammered Dulcimer 8th-note ostinato
      const cimbMidi = bar[2][beatInBar];
      scheduleCimbalom(state.ctx, t, cimbMidi, beatInBar === 0 || beatInBar === 4);

      // 4. Lead Solo Violin (exact BBC Sherlock + Irene Adler medley)
      const vln = VIOLIN_BY_STEP[s];
      if (vln !== null) {
        scheduleSherlockViolin(state.ctx, t, vln.note, vln.durSteps * STEP_SEC * 0.96, vln.slideFrom);
      }

      state.nextNoteTime += STEP_SEC;
      state.stepIdx = (state.stepIdx + 1) % TOTAL_STEPS;
    }
  }

  function startSynthScheduler() {
    if (!state.musicActive || state.muted || state.ytPlaying) return;
    const ctx = ensureContext();
    if (!ctx) return;
    if (state.musicGain) {
      state.musicGain.gain.cancelScheduledValues(ctx.currentTime);
      state.musicGain.gain.setValueAtTime(MUSIC_VOL, ctx.currentTime);
    }
    if (!state.synthRunning) {
      state.synthRunning = true;
      state.stepIdx = 0;
      state.nextNoteTime = ctx.currentTime + 0.05;
      if (state.timerId !== null) clearInterval(state.timerId);
      state.timerId = setInterval(schedulerTick, 85);
      if (ctx.state === "running") {
        schedulerTick();
      } else {
        ctx.resume().then(() => {
          if (state.musicActive && state.synthRunning && !state.ytPlaying) {
            schedulerTick();
          }
        });
      }
    }
  }

  function stopSynthScheduler() {
    state.synthRunning = false;
    if (state.timerId !== null) {
      clearInterval(state.timerId);
      state.timerId = null;
    }
    if (state.ctx && state.musicGain) {
      const now = state.ctx.currentTime;
      state.musicGain.gain.cancelScheduledValues(now);
      state.musicGain.gain.setValueAtTime(state.musicGain.gain.value, now);
      state.musicGain.gain.linearRampToValueAtTime(0.0001, now + 0.08);
    }
  }

  // ---------------------------------------------------------------------------
  // 5. Unified Music Lifecycle Controls
  // ---------------------------------------------------------------------------
  function unlockContext() {
    ensureContext();
  }

  function startMusic() {
    ensureContext();
    state.musicActive = true;
    if (state.muted) return;

    initYoutubeAudio();

    if (state.ytEnabled && !state.ytFailed) {
      if (state.ytReady && state.ytPlayer && typeof state.ytPlayer.playVideo === "function") {
        state.ytPlayer.unMute();
        state.ytPlayer.setVolume(YT_VOL);
        state.ytPlayer.playVideo();
      }
      if (state.ytTimedOutOnce && !state.ytPlaying) {
        startSynthScheduler();
        return;
      }
      if (state.ytFallbackTimer !== null) clearTimeout(state.ytFallbackTimer);
      state.ytFallbackTimer = setTimeout(() => {
        state.ytFallbackTimer = null;
        if (state.musicActive && !state.muted && !state.ytPlaying) {
          state.ytTimedOutOnce = true;
          startSynthScheduler();
        }
      }, 1600);
      return;
    }

    startSynthScheduler();
  }

  function stopMusic() {
    state.musicActive = false;
    state.ytPlaying = false;
    if (state.ytFallbackTimer !== null) {
      clearTimeout(state.ytFallbackTimer);
      state.ytFallbackTimer = null;
    }
    if (state.ytReady && state.ytPlayer && typeof state.ytPlayer.pauseVideo === "function") {
      state.ytPlayer.pauseVideo();
    }
    stopSynthScheduler();
  }

  // ---------------------------------------------------------------------------
  // 6. Procedural Sound Effects (Never Restarts Background Music!)
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
    if (state.muted) {
      if (state.ytFallbackTimer !== null) {
        clearTimeout(state.ytFallbackTimer);
        state.ytFallbackTimer = null;
      }
      if (state.ytReady && state.ytPlayer && typeof state.ytPlayer.mute === "function") {
        state.ytPlayer.mute();
      }
      stopSynthScheduler();
    } else {
      if (state.ytReady && state.ytPlayer && typeof state.ytPlayer.unMute === "function") {
        state.ytPlayer.unMute();
        state.ytPlayer.setVolume(YT_VOL);
      }
      sfx("ui");
      if (state.musicActive) {
        startMusic();
      }
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
