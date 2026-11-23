// Inspector Switch · Background Music & Procedural SFX Engine (`window.GameAudio`)
//
// Primary Background Music:
//   Streams Taryn Harbridge's "Sherlock Medley on Violin" (`l6B-8V4LyaU`) via the
//   YouTube IFrame API at a gentle background level (`YT_VOL = 24`).
//
// Clean, Simple Fallback Rendition:
//   Whenever YouTube is blocked, offline, or still buffering past 1.5s, plays a clean,
//   intimate solo-violin + sparse pizzicato rendition of the exact melody from `l6B-8V4LyaU`
//   (David Arnold & Michael Price's BBC Sherlock Theme + Irene's Theme in C Minor).
"use strict";

(function () {
  const AudioCtor = window.AudioContext || window.webkitAudioContext;
  const YT_VIDEO_ID = "l6B-8V4LyaU";
  const YT_START_SEC = 10;
  const YT_VOL = 24;

  function mtof(midi) {
    return 440.0 * Math.pow(2.0, (midi - 69.0) / 12.0);
  }

  // 16-bar (128 eighth-note steps at 108 BPM -> 1 step = 0.2778s, ~35.5s cycle)
  const TOTAL_STEPS = 128;
  const STEP_SEC = 60.0 / 108.0 / 2.0;

  const MASTER_VOL = 0.58;
  const MUSIC_VOL = 0.17;
  const SFX_VOL = 0.58;

  // Sparse, warm Pizzicato Cello bass notes per 8-step bar: [beat1Midi, beat3Midi]
  const BAR_BASS = [
    // Bars 1..2: Cm -> Ab/Fm ("C — G G F# G — | Ab G F")
    [36, 43],
    [44, 41],
    // Bars 3..4: Fm/G7 -> Cm ("C' — F — C' C' | B C' D' C'")
    [41, 43],
    [36, 43],
    // Bars 5..6: Eb/Cm -> Fm/G7 ("Eb' — G' — C' C' | D' Eb' D' Eb' D' C' F'")
    [39, 36],
    [41, 43],
    // Bars 7..8: Cm/Ab -> Bb/Cm ("C' — C' D' Eb' Eb' | F' D' D' Eb' C'")
    [36, 44],
    [46, 36],
    // Bars 9..10: Ab/Fm -> G7 ("C' D' B Ab | G — — F# G")
    [44, 41],
    [43, 35],
    // Bars 11..12: Cm -> Fm/Cm ("C' — G' — C' D' | Eb' D' C' —")
    [36, 43],
    [41, 36],
    // Bars 13..16: Irene's Theme answer ("G' — C' Eb' | Ab' — G' — | F' Eb' D' B | C' —")
    [36, 39],
    [44, 43],
    [41, 43],
    [36, 43],
  ];

  // Exact Melody of BBC Sherlock ("The Game Is On") -> Irene's Theme:
  // [stepIdx, midi, durSteps, slideFromMidiOrNull]
  const VIOLIN_SCORE = [
    // Bars 1..2: C4 — G4 G4 F#4 G4 — Ab4 G4 F4
    [0, 60, 2.80, null], [3, 67, 0.90, 60], [4, 67, 0.88, null], [5, 66, 0.88, null], [6, 67, 3.80, null],
    [10, 68, 1.88, null], [12, 67, 1.88, null], [14, 65, 1.88, null],

    // Bars 3..4: C5 — F4 — C5 C5 B4 C5 D5 C5
    [16, 72, 2.80, 65], [19, 65, 2.80, null], [22, 72, 0.88, 67], [23, 72, 0.88, null],
    [24, 71, 0.90, null], [25, 72, 0.90, null], [26, 74, 1.88, null], [28, 72, 3.60, null],

    // Bars 5..6: Eb5 — G5 — C5 C5 D5 Eb5 D5 Eb5 D5 C5 F5
    [32, 75, 2.80, 72], [35, 79, 2.80, 75], [38, 72, 0.88, null], [39, 72, 0.88, null],
    [40, 74, 0.88, null], [41, 75, 0.88, null], [42, 74, 0.88, null], [43, 75, 0.88, null],
    [44, 74, 0.88, null], [45, 72, 0.88, null], [46, 77, 1.88, 72],

    // Bars 7..8: C5 — C5 D5 Eb5 Eb5 F5 D5 D5 Eb5 C5
    [48, 72, 2.80, null], [51, 72, 0.88, null], [52, 74, 0.88, null], [53, 75, 1.82, null], [55, 75, 0.88, null],
    [56, 77, 1.85, null], [58, 74, 1.85, null], [60, 74, 0.88, null], [61, 75, 0.88, null], [62, 72, 1.88, null],

    // Bars 9..10: C5 D5 B4 Ab4 G4 — — F#4 G4
    [64, 72, 1.85, null], [66, 74, 1.85, null], [68, 71, 1.85, null], [70, 68, 1.85, null],
    [72, 67, 5.50, null], [78, 66, 0.88, null], [79, 67, 0.90, null],

    // Bars 11..12: C5 — G5 — C5 D5 Eb5 D5 C5 —
    [80, 72, 2.80, 67], [83, 79, 2.80, 72], [86, 72, 0.88, null], [87, 74, 0.88, null],
    [88, 75, 1.85, null], [90, 74, 1.85, null], [92, 72, 3.60, null],

    // Bars 13..16: Irene's Theme lyrical phrase -> gentle cadence
    [96, 79, 3.70, 72], [100, 72, 1.85, null], [102, 75, 1.85, null],
    [104, 80, 3.70, 75], [108, 79, 3.70, null],
    [112, 77, 1.85, null], [114, 75, 1.85, null], [116, 74, 1.85, null], [118, 71, 1.85, null],
    [120, 72, 5.60, 71],
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

    // YouTube IFrame API primary stream (`l6B-8V4LyaU`)
    ytEnabled: Boolean(
      window.location &&
        (window.location.protocol === "http:" || window.location.protocol === "https:")
    ),
    ytBooted: false,
    ytPlayer: null,
    ytReady: false,
    ytPositionedInitial: false,
    ytPlaying: false,
    ytFailed: false,
    ytTimedOutOnce: false,
    ytFallbackTimer: null,

    // Simple solo-violin fallback scheduler
    synthRunning: false,
    stepIdx: 0,
    nextNoteTime: 0,
    timerId: null,

    lastStepSfxAt: 0,
    footParity: 0,
  };

  // ---------------------------------------------------------------------------
  // YouTube IFrame Player Integration (`https://www.youtube.com/watch?v=l6B-8V4LyaU`)
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
          autoplay: 1,
          start: YT_START_SEC,
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
            if (!state.ytPositionedInitial) {
              state.ytPositionedInitial = true;
              ev.target.seekTo(YT_START_SEC, true);
            }
            if (state.musicActive && !state.muted) {
              ev.target.playVideo();
            }
          },
          onStateChange: (ev) => {
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
              stopSynthScheduler();
            } else if (ev.data === 0) {
              state.ytPlaying = false;
              if (state.musicActive && !state.muted) {
                ev.target.seekTo(YT_START_SEC, true);
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

    const resumeOnGesture = () => {
      if (state.muted) return;
      if (state.ctx && state.ctx.state === "suspended") {
        state.ctx.resume().then(() => {
          if (state.musicActive && state.synthRunning && !state.ytPlaying) {
            schedulerTick();
          }
        });
      }
      if (state.musicActive && !state.ytPlaying && state.ytReady && state.ytPlayer && !state.ytFailed) {
        state.ytPlayer.unMute();
        state.ytPlayer.setVolume(YT_VOL);
        state.ytPlayer.playVideo();
      }
    };
    document.addEventListener("pointerdown", resumeOnGesture, { passive: true });
    document.addEventListener("keydown", resumeOnGesture, { passive: true });
  }

  // ---------------------------------------------------------------------------
  // Web Audio Context & Warm Acoustic Solo Violin Filter Chain
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

      // Soft warm chamber room reflection
      const delay = ctx.createDelay(0.6);
      delay.delayTime.value = 0.24;
      const fb = ctx.createGain();
      fb.gain.value = 0.24;
      const wetLp = ctx.createBiquadFilter();
      wetLp.type = "lowpass";
      wetLp.frequency.value = 1550;
      const wetGain = ctx.createGain();
      wetGain.gain.value = 0.17;

      musicBus.connect(delay);
      delay.connect(wetLp);
      wetLp.connect(fb);
      fb.connect(delay);
      wetLp.connect(wetGain);
      wetGain.connect(master);
      state.musicGain = musicBus;

      // Mellow, rounded acoustic string harmonic wave (smooth overtones, zero harsh buzz)
      const real = new Float32Array(9);
      const imag = new Float32Array([0.0, 1.00, 0.52, 0.28, 0.16, 0.09, 0.05, 0.025, 0.012]);
      state.violinWave = ctx.createPeriodicWave(real, imag);

      const vHp = ctx.createBiquadFilter();
      vHp.type = "highpass";
      vHp.frequency.value = 190;

      const vWood = ctx.createBiquadFilter();
      vWood.type = "peaking";
      vWood.frequency.value = 430;
      vWood.Q.value = 1.3;
      vWood.gain.value = 3.0;

      const vSilkLp = ctx.createBiquadFilter();
      vSilkLp.type = "lowpass";
      vSilkLp.frequency.value = 1850;
      vSilkLp.Q.value = 0.65;

      vHp.connect(vWood);
      vWood.connect(vSilkLp);
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
  // Simple, Warm Solo Violin + Sparse Pizzicato Bass Voices
  // ---------------------------------------------------------------------------
  function scheduleSherlockViolin(ctx, t, midi, durSec, slideFromMidi) {
    const targetFreq = mtof(midi);
    const startFreq = slideFromMidi !== null ? mtof(slideFromMidi) : targetFreq;

    const osc1 = ctx.createOscillator();
    const osc2 = ctx.createOscillator();
    osc1.setPeriodicWave(state.violinWave);
    osc2.setPeriodicWave(state.violinWave);

    osc1.frequency.setValueAtTime(startFreq * 1.0014, t);
    osc2.frequency.setValueAtTime(startFreq * 0.9986, t);
    if (slideFromMidi !== null) {
      osc1.frequency.exponentialRampToValueAtTime(targetFreq * 1.0014, t + 0.05);
      osc2.frequency.exponentialRampToValueAtTime(targetFreq * 0.9986, t + 0.05);
    }

    // Gentle singing vibrato on held notes
    const lfo = ctx.createOscillator();
    const lfoGain = ctx.createGain();
    lfo.type = "sine";
    lfo.frequency.setValueAtTime(5.4, t);
    lfoGain.gain.setValueAtTime(0.0, t);
    if (durSec > 0.32) {
      lfoGain.gain.setValueAtTime(0.0, t + 0.10);
      lfoGain.gain.linearRampToValueAtTime(targetFreq * 0.011, t + Math.min(0.28, durSec * 0.55));
    }
    lfo.connect(lfoGain);
    lfoGain.connect(osc1.frequency);
    lfoGain.connect(osc2.frequency);

    // Register balance so higher notes stay silky and gentle
    const regScale = midi > 74 ? Math.max(0.72, 1.0 - (midi - 74) * 0.038) : 1.0;
    const g = ctx.createGain();
    const attack = Math.min(0.062, durSec * 0.28);
    const sustainEnd = Math.max(attack + 0.02, durSec * 0.78);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.linearRampToValueAtTime(0.18 * regScale, t + attack);
    g.gain.linearRampToValueAtTime(0.20 * regScale, t + sustainEnd * 0.6);
    g.gain.setValueAtTime(0.165 * regScale, t + sustainEnd);
    g.gain.exponentialRampToValueAtTime(0.001, t + durSec + 0.03);

    osc1.connect(g);
    osc2.connect(g);
    g.connect(state.violinBodyIn);

    osc1.start(t);
    osc2.start(t);
    lfo.start(t);

    const stopAt = t + durSec + 0.045;
    osc1.stop(stopAt);
    osc2.stop(stopAt);
    lfo.stop(stopAt);
  }

  function scheduleWarmPizzicato(ctx, t, midi) {
    const osc = ctx.createOscillator();
    osc.type = "triangle";
    osc.frequency.setValueAtTime(mtof(midi), t);

    const lp = ctx.createBiquadFilter();
    lp.type = "lowpass";
    lp.frequency.setValueAtTime(360, t);
    lp.frequency.exponentialRampToValueAtTime(130, t + 0.32);

    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.linearRampToValueAtTime(0.26, t + 0.012);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.36);

    osc.connect(lp);
    lp.connect(g);
    g.connect(state.musicGain);
    osc.start(t);
    osc.stop(t + 0.38);
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
      const t = state.nextNoteTime;

      // Sparse, gentle pizzicato cello on beat 1 and beat 3 only
      if (beatInBar === 0) {
        scheduleWarmPizzicato(state.ctx, t, BAR_BASS[barIdx][0]);
      } else if (beatInBar === 4) {
        scheduleWarmPizzicato(state.ctx, t, BAR_BASS[barIdx][1]);
      }

      // Expressive solo violin carrying the exact Sherlock melody
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

  function unlockContext() {
    ensureContext();
  }

  function startMusic() {
    ensureContext();
    state.musicActive = true;
    if (state.muted) return;

    initYoutubeAudio();

    if (state.ytEnabled && !state.ytFailed) {
      if (state.ytPlaying) return;
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
      }, 1500);
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
