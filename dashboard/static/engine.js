// Inspector Switch · Pure Client-Side FaultFerence / FIVES / Flock / Set Engine
// Zero external dependencies, zero backend required (100% static GitHub Pages compatible).
"use strict";

(function () {
  const FLOWS_PER_PAIR = 400;
  const PACKETS_PER_FLOW = 25;
  const BG_NOISE_PROB = 1.0e-4;

  const FAILURE_MODES = ["silent_drop", "blackhole", "intermittent", "high_latency"];
  const INFERENCE_MODES = ["flock", "flock_tr", "bayesian", "bayesian_tr", "set", "set_tr"];

  const WEAPONS = [
    { kind: "active_probe", short: "Ping", hint: "Test hops to DST", target: "node" },
    { kind: "packet_mirror", short: "Tap", hint: "Mirror switch", target: "node" },
    { kind: "subtle_weight_shift", short: "Dial 20%", hint: "Gentle traffic shift", target: "edge" },
    { kind: "flow_link_drain", short: "Detour", hint: "Reroute this flow", target: "edge" },
    { kind: "flow_group_split", short: "Split", hint: "Drain half branches", target: "node" },
    { kind: "full_link_drain", short: "Shut Link", hint: "Cut whole link", target: "edge" },
    { kind: "component_reset", short: "Reboot", hint: "Restart switch", target: "node" },
  ];

  // ---------------------------------------------------------------------------
  // 1. Seeded PRNG & Exact Statistical Special Functions
  // ---------------------------------------------------------------------------
  class Rng {
    constructor(seed) {
      this._state = (Number(seed) >>> 0) || 0x9e3779b9;
    }

    random() {
      this._state = (this._state + 0x6d2b79f5) >>> 0;
      let t = this._state;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296.0;
    }

    integers(low, high) {
      return low + Math.floor(this.random() * (high - low));
    }

    choiceCounts(probs, totalDraws) {
      const k = probs.length;
      const counts = new Int32Array(k);
      if (k === 1) {
        counts[0] = totalDraws;
        return counts;
      }
      const cdf = new Float64Array(k);
      let acc = 0.0;
      for (let i = 0; i < k; i++) {
        acc += probs[i];
        cdf[i] = acc;
      }
      cdf[k - 1] = 1.0;
      for (let d = 0; d < totalDraws; d++) {
        const u = this.random();
        let idx = 0;
        while (idx < k - 1 && u >= cdf[idx]) idx++;
        counts[idx]++;
      }
      return counts;
    }

    binomial(n, p) {
      if (n <= 0 || p <= 0.0) return 0;
      if (p >= 1.0) return n;
      // Fast exact waiting-time skip when expected successes n*p < 20
      if (n * p < 20.0 && p < 0.5) {
        const log1mp = Math.log(1.0 - p);
        let x = 0;
        let pos = 0;
        while (true) {
          const u = Math.max(1.0e-15, this.random());
          const skip = Math.floor(Math.log(u) / log1mp);
          pos += skip + 1;
          if (pos > n) break;
          x++;
        }
        return x;
      }
      let hits = 0;
      for (let i = 0; i < n; i++) {
        if (this.random() < p) hits++;
      }
      return hits;
    }
  }

  const LANCZOS_COEFFS = [
    0.99999999999980993,
    676.5203681218851,
    -1259.1392167224028,
    771.32342877765313,
    -176.61502916214059,
    12.507343278686905,
    -0.13857109526572012,
    9.9843695780195716e-6,
    1.5056327351493116e-7,
  ];

  const LGAMMA_CACHE = new Float64Array(20005);
  let lgammaReady = false;

  function lgammaRaw(z) {
    if (z < 0.5) {
      return Math.log(Math.PI / Math.sin(Math.PI * z)) - lgammaRaw(1.0 - z);
    }
    const zm = z - 1.0;
    let x = LANCZOS_COEFFS[0];
    for (let i = 1; i < LANCZOS_COEFFS.length; i++) {
      x += LANCZOS_COEFFS[i] / (zm + i);
    }
    const t = zm + 7.5;
    return 0.5 * Math.log(2.0 * Math.PI) + (zm + 0.5) * Math.log(t) - t + Math.log(x);
  }

  function lgammaInt(nPlus1) {
    if (!lgammaReady) {
      LGAMMA_CACHE[0] = 0.0;
      LGAMMA_CACHE[1] = 0.0;
      let acc = 0.0;
      for (let i = 2; i < LGAMMA_CACHE.length; i++) {
        acc += Math.log(i - 1);
        LGAMMA_CACHE[i] = acc;
      }
      lgammaReady = true;
    }
    if (nPlus1 >= 0 && nPlus1 < LGAMMA_CACHE.length) {
      return LGAMMA_CACHE[nPlus1];
    }
    return lgammaRaw(nPlus1);
  }

  function binomLogPmf(k, n, p) {
    const pc = Math.min(1.0 - 1.0e-12, Math.max(1.0e-12, p));
    const lc = lgammaInt(n + 1) - lgammaInt(k + 1) - lgammaInt(n - k + 1);
    return lc + k * Math.log(pc) + (n - k) * Math.log(1.0 - pc);
  }

  function binomSf(kMinus1, n, p) {
    const startK = kMinus1 + 1;
    if (startK <= 0) return 1.0;
    if (startK > n) return 0.0;
    let sum = 0.0;
    const cap = Math.min(n, startK + 80);
    for (let j = startK; j <= cap; j++) {
      const term = Math.exp(binomLogPmf(j, n, p));
      sum += term;
      if (j > startK + 4 && term < sum * 1.0e-12) break;
    }
    return sum;
  }

  function logSumExp(arr) {
    let m = -Infinity;
    for (let i = 0; i < arr.length; i++) {
      if (arr[i] > m) m = arr[i];
    }
    if (!Number.isFinite(m)) return m;
    let s = 0.0;
    for (let i = 0; i < arr.length; i++) {
      s += Math.exp(arr[i] - m);
    }
    return m + Math.log(s);
  }

  function erf(x) {
    const sign = x < 0 ? -1.0 : 1.0;
    const ax = Math.abs(x);
    const t = 1.0 / (1.0 + 0.3275911 * ax);
    const y =
      1.0 -
      (((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t +
        0.254829592) *
        t) *
        Math.exp(-ax * ax);
    return sign * y;
  }

  function normSf(z) {
    return 0.5 * (1.0 - erf(z / Math.SQRT2));
  }

  function dailySeed() {
    const iso = new Date().toISOString().slice(0, 10).replace(/-/g, "");
    return Number(iso);
  }

  // ---------------------------------------------------------------------------
  // 2. FailureSpec & Perturbation Representations
  // ---------------------------------------------------------------------------
  class FailureSpec {
    constructor(mode, faultyNode, affectedPairs, dropProb) {
      this.mode = mode;
      this.faultyNode = faultyNode;
      this.affectedPairs = affectedPairs;
      this.dropProb = mode === "high_latency" ? Math.max(dropProb, 0.08) : dropProb;
      this.bgNoiseProb = BG_NOISE_PROB;
      this.dutyCycle = mode === "intermittent" ? 0.65 : 1.0;
      this.latencyInflationUs = mode === "high_latency" ? 1000.0 : 0.0;
      this.latencyJitterUs = mode === "high_latency" ? 10.0 : 0.0;
      this.latencyThresholdUs = mode === "high_latency" ? 37.19 : 0.0;
    }

    unitBadProb(hitsFault) {
      if (this.mode === "high_latency") {
        const pJitter = normSf(this.latencyThresholdUs / this.latencyJitterUs);
        if (!hitsFault) return pJitter;
        const pInf = normSf(
          (this.latencyThresholdUs - this.latencyInflationUs) / this.latencyJitterUs
        );
        return this.dropProb * pInf + (1.0 - this.dropProb) * pJitter;
      }
      return hitsFault ? this.dropProb : this.bgNoiseProb;
    }
  }

  function makeProbe(srcNode, dstNode, flowPair, numProbes = 500) {
    return {
      kind: "active_probe",
      plane: "telemetry",
      srcNode,
      dstNode,
      flowPair,
      numProbes,
      key: `probe:${srcNode}:${dstNode}:${flowPair[0]}:${flowPair[1]}:${numProbes}`,
    };
  }

  function makeMirror(node, filtered, flowPair) {
    return {
      kind: "packet_mirror",
      plane: "telemetry",
      node,
      filtered,
      flowPair,
      key: `mirror:${node}:${filtered ? 1 : 0}:${flowPair[0]}:${flowPair[1]}`,
    };
  }

  function makeFlowDrain(u, v, flowPair) {
    return {
      kind: "flow_link_drain",
      plane: "control",
      u,
      v,
      flowPair,
      key: `fdrain:${u}:${v}:${flowPair[0]}:${flowPair[1]}`,
    };
  }

  function makeGroupSplit(u, drainedNexthops, flowPair) {
    return {
      kind: "flow_group_split",
      plane: "control",
      u,
      drainedNexthops: drainedNexthops.slice(),
      flowPair,
      key: `gsplit:${u}:${drainedNexthops.join(",")}:${flowPair[0]}:${flowPair[1]}`,
    };
  }

  function makeWeightShift(u, v, weightFactor, flowPair) {
    return {
      kind: "subtle_weight_shift",
      plane: "control",
      u,
      v,
      weightFactor,
      flowPair,
      key: `wshift:${u}:${v}:${weightFactor.toFixed(2)}:${flowPair[0]}:${flowPair[1]}`,
    };
  }

  function makeFullDrain(u, v) {
    const a = Math.min(u, v);
    const b = Math.max(u, v);
    return {
      kind: "full_link_drain",
      plane: "control",
      u,
      v,
      key: `ldrain:${a}:${b}`,
    };
  }

  function makeReset(node) {
    return {
      kind: "component_reset",
      plane: "physical",
      node,
      key: `reset:${node}`,
    };
  }

  // ---------------------------------------------------------------------------
  // 3. NetworkSystem (Shortest-Path DAG, Perturbed Routing, Simulation)
  // ---------------------------------------------------------------------------
  function edgeKey(u, v) {
    return u < v ? `${u}:${v}` : `${v}:${u}`;
  }

  function pairEq(a, b) {
    return a[0] === b[0] && a[1] === b[1];
  }

  class JSNetwork {
    constructor(spec) {
      this.name = spec.name;
      this.switchNodes = spec.switches.slice();
      this.rackNodes = spec.racks.slice();
      this.names = spec.names;
      this.dlbRouting = spec.dlb;
      this.articulationPoints = new Set(spec.articulation);

      const s = spec.safety;
      this.safety = {
        minBandwidthRatio: s.min_bw,
        drainBanned: new Set(s.drain_ban),
        resetBanned: new Set(s.reset_ban),
        probeBanned: new Set(s.probe_ban),
        mirrorFiltered: new Set(s.mirror_filt),
        mirrorUnfilteredOnly: new Set(s.mirror_raw),
        mirrorBanned: new Set(s.mirror_ban),
        externalBlackbox: new Set(s.blackbox),
        maxUnfilteredMirrorLoad: s.max_raw_load,
        enableSubtleWeightShifts: s.en_weight,
        enableGroupSplits: s.en_split,
        enableFlowLinkDrains: s.en_drain,
        enablePacketMirror: s.en_mirror,
        enableComponentReset: s.en_reset,
      };

      this.adj = new Map();
      for (const sw of this.switchNodes) {
        this.adj.set(sw, []);
      }
      this.edgeCapacities = new Map();
      this.edgeLoads = new Map();
      for (const [u, v, cap, load] of spec.edges) {
        this.adj.get(u).push(v);
        this.adj.get(v).push(u);
        const ek = edgeKey(u, v);
        this.edgeCapacities.set(ek, cap);
        this.edgeLoads.set(ek, load);
      }
      for (const arr of this.adj.values()) {
        arr.sort((a, b) => a - b);
      }

      this._spCache = new Map();
      this._noBranchCache = new Map();
    }

    nodeName(n) {
      return this.names[String(n)];
    }

    edgeCap(u, v) {
      return this.edgeCapacities.get(edgeKey(u, v));
    }

    edgeLoad(u, v) {
      return this.edgeLoads.get(edgeKey(u, v));
    }

    neighbors(u) {
      return this.adj.get(u);
    }

    hasPathWithoutNode(src, dst, bannedNode) {
      if (src === bannedNode || dst === bannedNode) return false;
      if (src === dst) return true;
      const seen = new Set([src, bannedNode]);
      const q = [src];
      let head = 0;
      while (head < q.length) {
        const u = q[head++];
        const nbs = this.adj.get(u);
        for (let i = 0; i < nbs.length; i++) {
          const v = nbs[i];
          if (v === dst) return true;
          if (!seen.has(v)) {
            seen.add(v);
            q.push(v);
          }
        }
      }
      return false;
    }

    _computeAllShortestPaths(src, dst, cutU, cutV, maxPaths) {
      if (src === dst) return [[src]];
      const distSrc = new Map([[src, 0]]);
      const q = [src];
      let head = 0;
      let targetDist = -1;

      while (head < q.length) {
        const u = q[head++];
        const du = distSrc.get(u);
        if (targetDist !== -1 && du >= targetDist) continue;
        const nbs = this.adj.get(u);
        for (let i = 0; i < nbs.length; i++) {
          const v = nbs[i];
          if (
            cutU !== -1 &&
            ((u === cutU && v === cutV) || (u === cutV && v === cutU))
          ) {
            continue;
          }
          if (!distSrc.has(v)) {
            distSrc.set(v, du + 1);
            if (v === dst) targetDist = du + 1;
            q.push(v);
          }
        }
      }

      if (targetDist === -1) return [];

      // Reverse BFS from dst restricted to nodes within targetDist so DAG traversal has zero dead-ends
      const distDst = new Map([[dst, 0]]);
      const rq = [dst];
      let rhead = 0;
      while (rhead < rq.length) {
        const u = rq[rhead++];
        const rdu = distDst.get(u);
        if (rdu >= targetDist) continue;
        const nbs = this.adj.get(u);
        for (let i = 0; i < nbs.length; i++) {
          const prev = nbs[i];
          if (
            cutU !== -1 &&
            ((u === cutU && prev === cutV) || (u === cutV && prev === cutU))
          ) {
            continue;
          }
          if (distSrc.get(prev) === targetDist - (rdu + 1) && !distDst.has(prev)) {
            distDst.set(prev, rdu + 1);
            rq.push(prev);
          }
        }
      }

      const results = [];
      const stack = [src];

      const dfs = (u, d) => {
        if (results.length >= maxPaths) return;
        if (u === dst) {
          results.push(stack.slice());
          return;
        }
        const nbs = this.adj.get(u);
        const wantSrcD = d + 1;
        const wantDstD = targetDist - wantSrcD;
        for (let i = 0; i < nbs.length; i++) {
          const v = nbs[i];
          if (
            cutU !== -1 &&
            ((u === cutU && v === cutV) || (u === cutV && v === cutU))
          ) {
            continue;
          }
          if (distSrc.get(v) === wantSrcD && distDst.get(v) === wantDstD) {
            stack.push(v);
            dfs(v, wantSrcD);
            stack.pop();
            if (results.length >= maxPaths) return;
          }
        }
      };

      dfs(src, 0);
      return results;
    }

    shortestPaths(src, dst, maxPaths = 256) {
      const ck = `${src}:${dst}:${maxPaths}`;
      if (!this._spCache.has(ck)) {
        this._spCache.set(ck, this._computeAllShortestPaths(src, dst, -1, -1, maxPaths));
      }
      return this._spCache.get(ck);
    }

    pathsUnderPerturbation(pair, pert) {
      const basePaths = this.shortestPaths(pair[0], pair[1]);

      if (pert && pert.kind === "flow_link_drain" && pairEq(pert.flowPair, pair)) {
        const kept = basePaths.filter((p) => {
          for (let i = 0; i < p.length - 1; i++) {
            if (p[i] === pert.u && p[i + 1] === pert.v) return false;
          }
          return true;
        });
        if (kept.length === 0) return [];
        const w = 1.0 / kept.length;
        return kept.map((path) => ({ path, weight: w }));
      }

      if (pert && pert.kind === "flow_group_split" && pairEq(pert.flowPair, pair)) {
        const drained = new Set(pert.drainedNexthops);
        const kept = basePaths.filter((p) => {
          for (let i = 0; i < p.length - 1; i++) {
            if (p[i] === pert.u && drained.has(p[i + 1])) return false;
          }
          return true;
        });
        if (kept.length === 0) return [];
        const w = 1.0 / kept.length;
        return kept.map((path) => ({ path, weight: w }));
      }

      if (pert && pert.kind === "full_link_drain") {
        const kept = basePaths.filter((p) => {
          for (let i = 0; i < p.length - 1; i++) {
            if (
              (p[i] === pert.u && p[i + 1] === pert.v) ||
              (p[i] === pert.v && p[i + 1] === pert.u)
            ) {
              return false;
            }
          }
          return true;
        });
        if (kept.length > 0) {
          const w = 1.0 / kept.length;
          return kept.map((path) => ({ path, weight: w }));
        }
        const rerouted = this._computeAllShortestPaths(pair[0], pair[1], pert.u, pert.v, 256);
        if (rerouted.length === 0) return [];
        const w = 1.0 / rerouted.length;
        return rerouted.map((path) => ({ path, weight: w }));
      }

      if (pert && pert.kind === "subtle_weight_shift" && pairEq(pert.flowPair, pair)) {
        const rawW = [];
        let total = 0.0;
        for (const p of basePaths) {
          let uses = false;
          for (let i = 0; i < p.length - 1; i++) {
            if (p[i] === pert.u && p[i + 1] === pert.v) {
              uses = true;
              break;
            }
          }
          const rw = uses ? pert.weightFactor : 1.0;
          rawW.push(rw);
          total += rw;
        }
        return basePaths.map((path, idx) => ({ path, weight: rawW[idx] / total }));
      }

      const w = 1.0 / basePaths.length;
      return basePaths.map((path) => ({ path, weight: w }));
    }

    checkNoBranch(flowPair, probeSrc, probeDst) {
      if (this.dlbRouting) {
        return this.shortestPaths(probeSrc, probeDst).length === 1;
      }
      const ck = `${flowPair[0]}:${flowPair[1]}:${probeSrc}:${probeDst}`;
      if (this._noBranchCache.has(ck)) return this._noBranchCache.get(ck);

      const subPaths = this.shortestPaths(probeSrc, probeDst);
      if (subPaths.length === 0) {
        this._noBranchCache.set(ck, false);
        return false;
      }

      const subNodes = new Set();
      for (const sp of subPaths) {
        for (const n of sp) subNodes.add(n);
      }

      const flowPaths = this.shortestPaths(flowPair[0], flowPair[1]);
      let ok = true;
      for (const fp of flowPaths) {
        for (let i = 0; i < fp.length - 1; i++) {
          const a = fp[i];
          const b = fp[i + 1];
          if (b !== probeSrc && subNodes.has(b) && !subNodes.has(a)) {
            if (subPaths.some((sp) => !sp.includes(b))) {
              ok = false;
              break;
            }
          }
          if (a !== probeDst && subNodes.has(a) && !subNodes.has(b)) {
            ok = false;
            break;
          }
        }
        if (!ok) break;
      }

      this._noBranchCache.set(ck, ok);
      return ok;
    }

    candidatePerturbations(activePairs, suspectsSet) {
      const cands = [];
      const seen = new Set();
      const add = (p) => {
        if (!seen.has(p.key)) {
          seen.add(p.key);
          cands.push(p);
        }
      };

      const relevantEdges = new Map();
      for (const pair of activePairs) {
        const paths = this.shortestPaths(pair[0], pair[1]);
        for (const path of paths) {
          if (!path.some((n) => suspectsSet.has(n))) continue;
          const dstSw = path[path.length - 1];
          for (let idx = 0; idx < path.length - 1; idx++) {
            const u = path[idx];
            const v = path[idx + 1];
            relevantEdges.set(`${u}:${v}`, [u, v]);
            if (u !== dstSw && this.checkNoBranch(pair, u, dstSw)) {
              add(makeProbe(u, dstSw, pair));
            }
          }

          if (this.safety.enablePacketMirror) {
            for (const sw of path) {
              if (suspectsSet.has(sw)) {
                if (this.safety.mirrorFiltered.has(sw)) {
                  add(makeMirror(sw, true, pair));
                } else if (this.safety.mirrorUnfilteredOnly.has(sw)) {
                  add(makeMirror(sw, false, pair));
                }
              }
            }
          }

          if (paths.length > 1) {
            for (let idx = 0; idx < path.length - 1; idx++) {
              const u = path[idx];
              const v = path[idx + 1];
              if (this.safety.enableFlowLinkDrains) {
                add(makeFlowDrain(u, v, pair));
              }
              if (this.safety.enableSubtleWeightShifts) {
                add(makeWeightShift(u, v, 0.2, pair));
              }
            }
          }
        }

        if (paths.length > 2 && this.safety.enableGroupSplits) {
          const uToNhs = new Map();
          const uNhHits = new Map();
          for (const path of paths) {
            for (let idx = 0; idx < path.length - 1; idx++) {
              const u = path[idx];
              const v = path[idx + 1];
              if (!uToNhs.has(u)) uToNhs.set(u, new Set());
              uToNhs.get(u).add(v);
              let hits = 0;
              for (let k = idx + 1; k < path.length; k++) {
                if (suspectsSet.has(path[k])) hits++;
              }
              const hk = `${u}:${v}`;
              uNhHits.set(hk, (uNhHits.has(hk) ? uNhHits.get(hk) : 0) + hits);
            }
          }

          const sortedUs = Array.from(uToNhs.keys()).sort((a, b) => a - b);
          for (const u of sortedUs) {
            const nhArr = Array.from(uToNhs.get(u)).sort((a, b) => a - b);
            const maxDrain = Math.floor(nhArr.length / 2);
            if (maxDrain < 2) continue;
            let minH = Infinity;
            for (const v of nhArr) {
              const h = uNhHits.get(`${u}:${v}`);
              if (h < minH) minH = h;
            }
            let activeNhs = nhArr.filter((v) => uNhHits.get(`${u}:${v}`) > minH);
            if (activeNhs.length === 0) {
              activeNhs = nhArr.filter((v) => uNhHits.get(`${u}:${v}`) > 0);
            }
            if (activeNhs.length >= 3) {
              const half = Math.min(maxDrain, Math.max(2, Math.floor(activeNhs.length / 2)));
              add(makeGroupSplit(u, activeNhs.slice(0, half), pair));
            }
          }
        }
      }

      const sortedEdges = Array.from(relevantEdges.values()).sort(
        (a, b) => a[0] - b[0] || a[1] - b[1]
      );
      for (const [u, v] of sortedEdges) {
        add(makeFullDrain(u, v));
      }

      if (this.safety.enableComponentReset) {
        const sortedSus = Array.from(suspectsSet).sort((a, b) => a - b);
        for (const sw of sortedSus) {
          add(makeReset(sw));
        }
      }

      return cands;
    }

    simulateWindow(failure, pert, rng, flowsPerPair, packetsPerFlow) {
      let faultActive = true;
      if (failure.mode === "intermittent") {
        faultActive = rng.random() < failure.dutyCycle;
      }
      const faultSuppressed =
        Boolean(pert) && pert.kind === "component_reset" && pert.node === failure.faultyNode;

      const records = [];
      for (const pair of failure.affectedPairs) {
        const pw = this.pathsUnderPerturbation(pair, pert);
        const probs = pw.map((item) => item.weight);
        const totalPkts = flowsPerPair * packetsPerFlow;

        if (this.dlbRouting) {
          const counts = rng.choiceCounts(probs, totalPkts);
          let badPkts = 0;
          for (let i = 0; i < pw.length; i++) {
            if (counts[i] === 0) continue;
            const hits = faultActive && !faultSuppressed && pw[i].path.includes(failure.faultyNode);
            badPkts += rng.binomial(counts[i], failure.unitBadProb(hits));
          }
          records.push({
            pair,
            isProbe: false,
            isMirror: false,
            mirrorNode: -1,
            packetsSent: totalPkts,
            packetsBad: badPkts,
            pathWeights: pw,
            tracedPath: [],
          });
        } else {
          const flowCounts = rng.choiceCounts(probs, flowsPerPair);
          if (failure.mode === "blackhole" || failure.mode === "high_latency") {
            let badFlows = 0;
            for (let i = 0; i < pw.length; i++) {
              if (flowCounts[i] === 0) continue;
              const hits =
                faultActive && !faultSuppressed && pw[i].path.includes(failure.faultyNode);
              badFlows += rng.binomial(flowCounts[i], failure.unitBadProb(hits));
            }
            records.push({
              pair,
              isProbe: false,
              isMirror: false,
              mirrorNode: -1,
              packetsSent: flowsPerPair,
              packetsBad: badFlows,
              pathWeights: pw,
              tracedPath: [],
            });
          } else {
            let badPkts = 0;
            for (let i = 0; i < pw.length; i++) {
              const cntPkts = flowCounts[i] * packetsPerFlow;
              if (cntPkts === 0) continue;
              const hits =
                faultActive && !faultSuppressed && pw[i].path.includes(failure.faultyNode);
              badPkts += rng.binomial(cntPkts, failure.unitBadProb(hits));
            }
            records.push({
              pair,
              isProbe: false,
              isMirror: false,
              mirrorNode: -1,
              packetsSent: totalPkts,
              packetsBad: badPkts,
              pathWeights: pw,
              tracedPath: [],
            });
          }
        }
      }

      if (pert && pert.kind === "active_probe") {
        const subPaths = this.shortestPaths(pert.srcNode, pert.dstNode);
        const w = 1.0 / subPaths.length;
        const pwProbe = subPaths.map((sp) => ({ path: sp, weight: w }));
        const chosenSp = subPaths[rng.integers(0, subPaths.length)];
        const hits = faultActive && chosenSp.includes(failure.faultyNode);
        const badProbes = rng.binomial(pert.numProbes, failure.unitBadProb(hits));
        records.push({
          pair: pert.flowPair,
          isProbe: true,
          isMirror: false,
          mirrorNode: -1,
          packetsSent: pert.numProbes,
          packetsBad: badProbes,
          pathWeights: pwProbe,
          tracedPath: chosenSp,
        });
      } else if (pert && pert.kind === "packet_mirror") {
        const basePaths = this.shortestPaths(pert.flowPair[0], pert.flowPair[1]);
        const throughM = basePaths.filter((p) => p.includes(pert.node));
        if (throughM.length > 0) {
          const upPrefixes = throughM.map((p) => p.slice(0, p.indexOf(pert.node) + 1));
          const w = 1.0 / upPrefixes.length;
          const pwMir = upPrefixes.map((up) => ({ path: up, weight: w }));
          const nMir = 200;
          const uniformP = upPrefixes.map(() => w);
          const counts = rng.choiceCounts(uniformP, nMir);
          let badMir = 0;
          for (let i = 0; i < upPrefixes.length; i++) {
            if (counts[i] === 0) continue;
            const hits = faultActive && upPrefixes[i].includes(failure.faultyNode);
            badMir += rng.binomial(counts[i], failure.unitBadProb(hits));
          }
          records.push({
            pair: pert.flowPair,
            isProbe: false,
            isMirror: true,
            mirrorNode: pert.node,
            packetsSent: nMir,
            packetsBad: badMir,
            pathWeights: pwMir,
            tracedPath: [],
          });
        }
      }

      return { perturbation: pert, records, faultWasActive: faultActive };
    }
  }

  const NET_CACHE = new Map();
  function getNetwork(name) {
    if (!NET_CACHE.has(name)) {
      const spec = window.TOPOLOGY_DATA[name];
      if (!spec) throw new Error(`Unknown topology: ${name}`);
      NET_CACHE.set(name, new JSNetwork(spec));
    }
    return NET_CACHE.get(name);
  }

  // ---------------------------------------------------------------------------
  // 4. Safety, Impact & Multi-Outcome Efficacy Evaluators
  // ---------------------------------------------------------------------------
  function pathHasEdgeDir(path, u, v) {
    for (let i = 0; i < path.length - 1; i++) {
      if (path[i] === u && path[i + 1] === v) return true;
    }
    return false;
  }

  function samePath(a, b) {
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) {
      if (a[i] !== b[i]) return false;
    }
    return true;
  }

  function violationReason(net, p, pairs) {
    const cfg = net.safety;
    if (p.kind === "active_probe") {
      for (const n of [p.srcNode, p.dstNode]) {
        if (cfg.probeBanned.has(n)) return `No probe support on ${net.nodeName(n)}`;
        if (cfg.externalBlackbox.has(n)) return `External peer (${net.nodeName(n)})`;
      }
      if (!net.checkNoBranch(p.flowPair, p.srcNode, p.dstNode)) {
        return "Ping paths branch off flow";
      }
      return null;
    }

    if (p.kind === "packet_mirror") {
      if (cfg.mirrorBanned.has(p.node) || cfg.externalBlackbox.has(p.node)) {
        return `No tap hardware on ${net.nodeName(p.node)}`;
      }
      if (p.filtered) {
        return cfg.mirrorFiltered.has(p.node)
          ? null
          : `No filtered tap on ${net.nodeName(p.node)}`;
      }
      if (!cfg.mirrorUnfilteredOnly.has(p.node)) {
        return `No raw tap on ${net.nodeName(p.node)}`;
      }
      const nbrs = net.neighbors(p.node);
      if (nbrs.length === 0) return "Isolated switch";
      let sumLoad = 0.0;
      for (const nb of nbrs) sumLoad += net.edgeLoad(p.node, nb);
      const meanLoad = sumLoad / nbrs.length;
      if (meanLoad > cfg.maxUnfilteredMirrorLoad) {
        return `Too busy for raw tap (${Math.round(meanLoad * 100)}% > ${Math.round(
          cfg.maxUnfilteredMirrorLoad * 100
        )}%)`;
      }
      return null;
    }

    if (p.kind === "flow_link_drain" || p.kind === "flow_group_split") {
      const touched =
        p.kind === "flow_link_drain" ? [p.u, p.v] : [p.u, ...p.drainedNexthops];
      for (const n of touched) {
        if (cfg.drainBanned.has(n)) return `Protected switch (${net.nodeName(n)})`;
        if (cfg.externalBlackbox.has(n)) return `External peer (${net.nodeName(n)})`;
      }
      const base = net.shortestPaths(p.flowPair[0], p.flowPair[1]);
      const post = net.pathsUnderPerturbation(p.flowPair, p);
      if (post.length === 0) return "Would cut all paths";
      if (post.length / base.length < cfg.minBandwidthRatio) {
        return `Drops capacity below ${Math.round(cfg.minBandwidthRatio * 100)}%`;
      }
      return null;
    }

    if (p.kind === "subtle_weight_shift") {
      for (const n of [p.u, p.v]) {
        if (cfg.externalBlackbox.has(n)) return `External peer (${net.nodeName(n)})`;
      }
      const base = net.shortestPaths(p.flowPair[0], p.flowPair[1]);
      if (base.length <= 1) return "Single path — can't shift";
      let uses = 0;
      for (const path of base) {
        if (pathHasEdgeDir(path, p.u, p.v)) uses++;
      }
      if (uses === 0 || uses === base.length) return "Shared bottleneck — shift is no-op";
      const eff = (uses * p.weightFactor + (base.length - uses)) / base.length;
      if (eff < cfg.minBandwidthRatio) {
        return `Drops capacity below ${Math.round(cfg.minBandwidthRatio * 100)}%`;
      }
      return null;
    }

    if (p.kind === "full_link_drain") {
      for (const n of [p.u, p.v]) {
        if (cfg.drainBanned.has(n)) return `Protected switch (${net.nodeName(n)})`;
        if (cfg.externalBlackbox.has(n)) return `External peer (${net.nodeName(n)})`;
      }
      const cap = net.edgeCap(p.u, p.v);
      if (cap <= cfg.minBandwidthRatio * 100.0) return "Link bundle already degraded";
      for (const pair of pairs) {
        const base = net.shortestPaths(pair[0], pair[1]);
        const post = net.pathsUnderPerturbation(pair, p);
        if (post.length === 0) return "Would cut active traffic";
        const firstInBase = base.some((bp) => samePath(bp, post[0].path));
        if (firstInBase && post.length / base.length < cfg.minBandwidthRatio) {
          return `Drops capacity below ${Math.round(cfg.minBandwidthRatio * 100)}%`;
        }
      }
      return null;
    }

    if (p.kind === "component_reset") {
      if (cfg.resetBanned.has(p.node)) return `Protected spine (${net.nodeName(p.node)})`;
      if (cfg.externalBlackbox.has(p.node)) return `External peer (${net.nodeName(p.node)})`;
      for (const pair of pairs) {
        if (p.node === pair[0] || p.node === pair[1]) {
          return `Flow endpoint (${net.nodeName(p.node)})`;
        }
      }
      if (net.articulationPoints.has(p.node)) {
        for (const pair of pairs) {
          if (!net.hasPathWithoutNode(pair[0], pair[1], p.node)) {
            return "Single point of failure";
          }
        }
      }
      return null;
    }

    throw new Error(`Unknown perturbation kind: ${p.kind}`);
  }

  function congestionPenalty(util) {
    const u = Math.min(0.96, Math.max(0.01, util));
    return u / (1.0 - u);
  }

  function estimateImpact(net, p, expectedDropProb = 0.02) {
    let applyT, applyD, obsT, obsD;

    if (p.kind === "active_probe") {
      applyT = 1.0;
      applyD = 0.05;
      obsT = Math.max(2.0, Math.min(15.0, 2.5 / Math.max(0.01, expectedDropProb)));
      obsD = 0.15;
    } else if (p.kind === "packet_mirror") {
      applyT = 2.0;
      applyD = p.filtered ? 0.1 : 0.6;
      obsT = Math.max(4.0, Math.min(20.0, 3.0 / Math.max(0.01, expectedDropProb)));
      obsD = p.filtered ? 0.25 : 1.8;
    } else if (p.kind === "subtle_weight_shift") {
      const basePaths = net.shortestPaths(p.flowPair[0], p.flowPair[1]);
      let nUv = 0;
      for (const path of basePaths) {
        if (pathHasEdgeDir(path, p.u, p.v)) nUv++;
      }
      const shiftedFrac = (1.0 - p.weightFactor) * (nUv / basePaths.length);
      const baseU = net.edgeLoad(p.u, p.v);
      const congDelta =
        congestionPenalty(baseU + 0.06 * shiftedFrac) - congestionPenalty(baseU);
      applyT = 1.5;
      applyD = 0.12 * shiftedFrac;
      obsT = Math.max(
        6.0,
        Math.min(30.0, 4.5 / Math.max(0.01, expectedDropProb * shiftedFrac))
      );
      obsD = 0.35 * shiftedFrac + 1.5 * congDelta;
    } else if (p.kind === "flow_link_drain") {
      const basePaths = net.shortestPaths(p.flowPair[0], p.flowPair[1]);
      let nUv = 0;
      for (const path of basePaths) {
        if (pathHasEdgeDir(path, p.u, p.v)) nUv++;
      }
      const reroutedFrac = nUv / Math.max(1, basePaths.length);
      const remFrac = Math.max(0.1, 1.0 - reroutedFrac);
      const baseU = net.edgeLoad(p.u, p.v);
      const congDelta =
        congestionPenalty(baseU + 0.18 * (reroutedFrac / remFrac)) -
        congestionPenalty(baseU);
      applyT = 4.0;
      applyD = 0.8 * reroutedFrac;
      obsT = Math.max(5.0, Math.min(25.0, 3.0 / Math.max(0.01, expectedDropProb)));
      obsD = 1.2 * reroutedFrac + 3.5 * congDelta;
    } else if (p.kind === "flow_group_split") {
      const basePaths = net.shortestPaths(p.flowPair[0], p.flowPair[1]);
      const postPaths = net.pathsUnderPerturbation(p.flowPair, p);
      const reroutedFrac = (basePaths.length - postPaths.length) / Math.max(1, basePaths.length);
      const remFrac = Math.max(0.1, 1.0 - reroutedFrac);
      let baseU = 0.0;
      for (const v of p.drainedNexthops) {
        baseU = Math.max(baseU, net.edgeLoad(p.u, v));
      }
      const congDelta =
        congestionPenalty(baseU + 0.18 * (reroutedFrac / remFrac)) -
        congestionPenalty(baseU);
      applyT = 4.0;
      applyD = 0.8 * reroutedFrac;
      obsT = Math.max(5.0, Math.min(25.0, 3.0 / Math.max(0.01, expectedDropProb)));
      obsD = 1.2 * reroutedFrac + 3.5 * congDelta;
    } else if (p.kind === "full_link_drain") {
      const baseU = net.edgeLoad(p.u, p.v);
      const deg = Math.max(1, net.neighbors(p.u).length - 1);
      const congDelta = congestionPenalty(baseU + baseU / deg) - congestionPenalty(baseU);
      applyT = 18.0;
      applyD = 4.5 * baseU;
      obsT = Math.max(8.0, Math.min(30.0, 3.0 / Math.max(0.01, expectedDropProb)));
      obsD = 6.0 * baseU + 8.0 * congDelta;
    } else if (p.kind === "component_reset") {
      const nbrs = net.neighbors(p.node);
      let totalLoad = 0.0;
      for (const nb of nbrs) totalLoad += net.edgeLoad(p.node, nb);
      applyT = 120.0;
      applyD = 15.0 + 6.0 * totalLoad;
      obsT = 15.0;
      obsD = 8.0 + 3.0 * totalLoad;
    } else {
      throw new Error(`Unhandled perturbation kind: ${p.kind}`);
    }

    const totalTimeSec = applyT + obsT;
    const totalDisruption = applyD + obsD;
    return {
      totalTimeSec,
      totalDisruption,
      scalarCost(lam) {
        const normD = totalDisruption;
        const normT = totalTimeSec / 10.0;
        return Math.max(
          1.0e-4,
          lam * normD + (1.0 - lam) * normT + 1.0e-3 * (normD + normT)
        );
      },
    };
  }

  function round2(x) {
    return Math.round(x * 100) / 100;
  }

  function partitionSuspects(net, p, suspects, activePairs) {
    const buckets = new Map();
    const susSet = new Set(suspects);
    const pushBucket = (sigKey, sigNums, s) => {
      if (!buckets.has(sigKey)) buckets.set(sigKey, { nums: sigNums, group: [] });
      buckets.get(sigKey).group.push(s);
    };

    if (p.kind === "component_reset") {
      for (const s of suspects) {
        const v = s === p.node ? 1 : 0;
        pushBucket(`reset:${v}`, [v], s);
      }
      return buckets;
    }

    if (p.kind === "active_probe") {
      const subPaths = net.shortestPaths(p.srcNode, p.dstNode);
      const invN = 1.0 / subPaths.length;
      const hitMap = new Map();
      for (const s of suspects) hitMap.set(s, 0.0);
      for (const sp of subPaths) {
        for (const n of sp) {
          if (susSet.has(n)) hitMap.set(n, hitMap.get(n) + invN);
        }
      }
      for (const s of suspects) {
        const v = round2(hitMap.get(s));
        pushBucket(`probe:${v.toFixed(2)}`, [v], s);
      }
      return buckets;
    }

    if (p.kind === "packet_mirror") {
      const basePaths = net.shortestPaths(p.flowPair[0], p.flowPair[1]);
      const throughM = basePaths.filter((path) => path.includes(p.node));
      const hitMap = new Map();
      for (const s of suspects) hitMap.set(s, 0.0);
      if (throughM.length > 0) {
        const invM = 1.0 / throughM.length;
        for (const path of throughM) {
          const idxM = path.indexOf(p.node);
          for (let k = 0; k <= idxM; k++) {
            const n = path[k];
            if (susSet.has(n)) hitMap.set(n, hitMap.get(n) + invM);
          }
        }
      }
      for (const s of suspects) {
        const v = round2(hitMap.get(s));
        pushBucket(`mirror:${v.toFixed(2)}`, [v], s);
      }
      return buckets;
    }

    const pairRatios = [];
    for (const pair of activePairs) {
      const baseMap = new Map();
      const postMap = new Map();
      for (const s of suspects) {
        baseMap.set(s, 0.0);
        postMap.set(s, 0.0);
      }
      for (const item of net.pathsUnderPerturbation(pair, null)) {
        for (const n of item.path) {
          if (susSet.has(n)) baseMap.set(n, baseMap.get(n) + item.weight);
        }
      }
      for (const item of net.pathsUnderPerturbation(pair, p)) {
        for (const n of item.path) {
          if (susSet.has(n)) postMap.set(n, postMap.get(n) + item.weight);
        }
      }
      const rmap = new Map();
      for (const s of suspects) {
        const b = baseMap.get(s);
        rmap.set(s, b > 1.0e-9 ? round2(postMap.get(s) / b) : 0.0);
      }
      pairRatios.push(rmap);
    }

    for (const s of suspects) {
      const nums = pairRatios.map((rm) => rm.get(s));
      const sigKey = `control:${nums.map((v) => v.toFixed(2)).join(",")}`;
      pushBucket(sigKey, nums, s);
    }
    return buckets;
  }

  function binEntropy(q) {
    if (q <= 1.0e-12 || q >= 1.0 - 1.0e-12) return 0.0;
    return -(q * Math.log2(q) + (1.0 - q) * Math.log2(1.0 - q));
  }

  function mutualInformationAndPairs(
    net,
    p,
    posteriors,
    activePairs,
    expectedDropProb,
    pNodeMap,
    flowsPerPair,
    packetsPerFlow
  ) {
    const suspects = [];
    for (const [c, pr] of posteriors.entries()) {
      if (pr > 1.0e-6) suspects.push(c);
    }
    if (suspects.length <= 1) return [0.0, 0.0];

    let totalMass = 0.0;
    for (const c of suspects) totalMass += posteriors.get(c);
    const probs = new Map();
    for (const c of suspects) probs.set(c, posteriors.get(c) / totalMass);

    if (p.kind === "active_probe") {
      const subPaths = net.shortestPaths(p.srcNode, p.dstNode);
      const qFail = new Map();
      let qBar = 0.0;
      const bgDet = 1.0 - Math.pow(1.0 - 1.0e-4, p.numProbes);
      for (const c of suspects) {
        const pC = pNodeMap && pNodeMap.has(c) ? pNodeMap.get(c) : expectedDropProb;
        const detC = 1.0 - Math.pow(1.0 - pC, p.numProbes);
        let hits = 0;
        for (const sp of subPaths) {
          if (sp.includes(c)) hits++;
        }
        const hC = hits / subPaths.length;
        const qf = hC * detC + (1.0 - hC) * bgDet;
        qFail.set(c, qf);
        qBar += probs.get(c) * qf;
      }
      let condH = 0.0;
      for (const c of suspects) condH += probs.get(c) * binEntropy(qFail.get(c));
      const mi = binEntropy(qBar) - condH;
      if (mi <= 1.0e-9) return [0.0, 0.0];
      const pairsW = qBar * (1.0 - qBar) * (suspects.length * suspects.length);
      return [Math.max(0.0, mi), pairsW];
    }

    if (p.kind === "packet_mirror") {
      const basePaths = net.shortestPaths(p.flowPair[0], p.flowPair[1]);
      const throughM = basePaths.filter((path) => path.includes(p.node));
      if (throughM.length === 0) return [0.0, 0.0];
      const nMir = 200;
      const qFail = new Map();
      let qBar = 0.0;
      for (const c of suspects) {
        const pC = pNodeMap && pNodeMap.has(c) ? pNodeMap.get(c) : expectedDropProb;
        let upHits = 0;
        for (const path of throughM) {
          const idxM = path.indexOf(p.node);
          for (let k = 0; k <= idxM; k++) {
            if (path[k] === c) {
              upHits++;
              break;
            }
          }
        }
        const upFrac = upHits / throughM.length;
        const qf = 1.0 - Math.pow(1.0 - Math.max(1.0e-4, upFrac * pC), nMir);
        qFail.set(c, qf);
        qBar += probs.get(c) * qf;
      }
      let condH = 0.0;
      for (const c of suspects) condH += probs.get(c) * binEntropy(qFail.get(c));
      const mi = binEntropy(qBar) - condH;
      const pairsW = qBar * (1.0 - qBar) * (suspects.length * suspects.length);
      return [Math.max(0.0, mi), pairsW];
    }

    const buckets = partitionSuspects(net, p, suspects, activePairs);
    if (buckets.size <= 1) return [0.0, 0.0];

    const entries = Array.from(buckets.values());
    const groupProbs = entries.map((b) => {
      let s = 0.0;
      for (const c of b.group) s += probs.get(c);
      return s;
    });

    let hPart = 0.0;
    for (const gp of groupProbs) {
      if (gp > 1.0e-12) hPart -= gp * Math.log2(gp);
    }

    let pairMass = 0.0;
    for (let i = 0; i < groupProbs.length; i++) {
      for (let j = i + 1; j < groupProbs.length; j++) {
        pairMass += groupProbs[i] * groupProbs[j];
      }
    }
    const weightedPairs = pairMass * (suspects.length * suspects.length);

    if (p.kind === "component_reset") {
      return [hPart, weightedPairs];
    }

    const c0 = suspects[0];
    const pC0 = pNodeMap && pNodeMap.has(c0) ? pNodeMap.get(c0) : expectedDropProb;
    const pw0 = net.pathsUnderPerturbation(activePairs[0], null);
    let h0Raw = 0.0;
    for (const item of pw0) {
      if (item.path.includes(c0)) h0Raw += item.weight;
    }
    const h0 = Math.max(0.01, h0Raw);
    const baseObsRate = h0 * pC0;
    const effFlows = Math.max(flowsPerPair, 25 * pw0.length);
    const nSamples = effFlows * packetsPerFlow;
    const stdNoise = Math.sqrt(Math.max(1.0, nSamples * baseObsRate));

    let sepPairMass = 0.0;
    for (let i = 0; i < entries.length; i++) {
      for (let j = i + 1; j < entries.length; j++) {
        let gap = 0.0;
        for (let k = 0; k < entries[i].nums.length; k++) {
          gap += Math.abs(entries[i].nums[k] - entries[j].nums[k]);
        }
        const z = (nSamples * baseObsRate * gap) / stdNoise;
        const alpha = erf(z / Math.SQRT2);
        sepPairMass += groupProbs[i] * groupProbs[j] * alpha;
      }
    }

    const sepFactor = pairMass > 1.0e-12 ? sepPairMass / pairMass : 0.0;
    return [hPart * sepFactor, weightedPairs * sepFactor];
  }

  // ---------------------------------------------------------------------------
  // 5. Inference Engines: Flock (MultiRoundBayesianPGM) & Set ∩ (GameSetInference)
  // ---------------------------------------------------------------------------
  class MultiRoundBayesianPGM {
    constructor(net, pathAware, dutyCyclePrior) {
      this.net = net;
      this.pathAware = pathAware;
      this.bgNoiseProb = BG_NOISE_PROB;
      this.dutyCyclePrior = dutyCyclePrior;
      this.candidates = [];
      this.logPost = new Float64Array(0);
      this.nodeDropProb = new Map();
      this._nodeExcessBad = new Map();
      this._nodeExposure = new Map();
      this._history = [];
      this.estimatedDropProb = 0.02;
    }

    reset(candidateNodes) {
      this.candidates = candidateNodes.slice().sort((a, b) => a - b);
      const n = this.candidates.length;
      this.logPost = new Float64Array(n).fill(-Math.log(n));
      this.nodeDropProb.clear();
      this._nodeExcessBad.clear();
      this._nodeExposure.clear();
      for (const c of this.candidates) {
        this.nodeDropProb.set(c, 0.02);
        this._nodeExcessBad.set(c, 0.0);
        this._nodeExposure.set(c, 0.0);
      }
      this._history = [];
      this.estimatedDropProb = 0.02;
    }

    _updateRunningMle(window) {
      const pert = window.perturbation;
      const activeRecs = window.records.filter(
        (r) => !r.isProbe && !r.isMirror && r.packetsSent > 0
      );
      if (activeRecs.length === 0) return;

      for (const c of this.candidates) {
        if (pert && pert.kind === "component_reset" && pert.node === c) continue;
        for (const r of activeRecs) {
          const bgExp = r.packetsSent * this.bgNoiseProb;
          if (r.packetsBad <= bgExp + 3.0 * Math.sqrt(Math.max(1.0, bgExp))) continue;
          let hitW = 0.0;
          for (const item of r.pathWeights) {
            if (item.path.includes(c)) hitW += item.weight;
          }
          if (hitW > 1.0e-9) {
            const excess = Math.max(0.0, r.packetsBad - bgExp);
            this._nodeExcessBad.set(c, this._nodeExcessBad.get(c) + excess);
            this._nodeExposure.set(c, this._nodeExposure.get(c) + r.packetsSent * hitW);
          }
        }
        const expC = this._nodeExposure.get(c);
        if (expC > 0.0) {
          this.nodeDropProb.set(
            c,
            Math.min(0.9999, Math.max(0.0005, this._nodeExcessBad.get(c) / expC))
          );
        }
      }
    }

    _recordLogLikelihood(rec, node, pDrop, suppressed) {
      if (suppressed) {
        return binomLogPmf(rec.packetsBad, rec.packetsSent, this.bgNoiseProb);
      }
      let hitW = 0.0;
      for (const item of rec.pathWeights) {
        if (item.path.includes(node)) hitW += item.weight;
      }
      if (hitW <= 0.0) {
        return binomLogPmf(rec.packetsBad, rec.packetsSent, this.bgNoiseProb);
      }
      if (rec.isProbe && this.pathAware) {
        const pUnit = rec.tracedPath.includes(node) ? pDrop : this.bgNoiseProb;
        return binomLogPmf(rec.packetsBad, rec.packetsSent, pUnit);
      }
      if (rec.isProbe) {
        const lpHit = binomLogPmf(rec.packetsBad, rec.packetsSent, pDrop);
        if (hitW >= 1.0 - 1.0e-9) return lpHit;
        const lpMiss = binomLogPmf(rec.packetsBad, rec.packetsSent, this.bgNoiseProb);
        return logSumExp([Math.log(hitW) + lpHit, Math.log(1.0 - hitW) + lpMiss]);
      }
      const q = hitW * pDrop + (1.0 - hitW) * this.bgNoiseProb;
      return binomLogPmf(rec.packetsBad, rec.packetsSent, q);
    }

    update(window) {
      this._history.push(window);
      this._updateRunningMle(window);
      const alpha = this.dutyCyclePrior;
      const n = this.candidates.length;
      const totalLp = new Float64Array(n).fill(-Math.log(n));

      for (const win of this._history) {
        let llInactive = 0.0;
        for (const r of win.records) {
          llInactive += binomLogPmf(r.packetsBad, r.packetsSent, this.bgNoiseProb);
        }
        const pert = win.perturbation;
        for (let idx = 0; idx < n; idx++) {
          const node = this.candidates[idx];
          const pNode = this.nodeDropProb.get(node);
          const suppressed =
            Boolean(pert) && pert.kind === "component_reset" && pert.node === node;
          let llActive = 0.0;
          for (const r of win.records) {
            llActive += this._recordLogLikelihood(r, node, pNode, suppressed);
          }
          if (alpha >= 1.0 - 1.0e-9) {
            totalLp[idx] += llActive;
          } else {
            totalLp[idx] += logSumExp([
              Math.log(alpha) + llActive,
              Math.log(1.0 - alpha) + llInactive,
            ]);
          }
        }
      }

      const norm = logSumExp(totalLp);
      let estDrop = 0.0;
      for (let i = 0; i < n; i++) {
        this.logPost[i] = totalLp[i] - norm;
        estDrop += Math.exp(this.logPost[i]) * this.nodeDropProb.get(this.candidates[i]);
      }
      if (n > 0) this.estimatedDropProb = estDrop;
    }

    posteriors() {
      const m = new Map();
      for (let i = 0; i < this.candidates.length; i++) {
        m.set(this.candidates[i], Math.exp(this.logPost[i]));
      }
      return m;
    }

    equivalenceSet(credMass = 0.95) {
      const indices = this.candidates.map((_, i) => i);
      indices.sort((a, b) => this.logPost[b] - this.logPost[a]);
      const chosen = new Set();
      let acc = 0.0;
      let lastLp = null;
      for (const idx of indices) {
        const lpVal = this.logPost[idx];
        const pVal = Math.exp(lpVal);
        if (acc >= credMass && (lastLp === null || lastLp - lpVal > 0.05)) break;
        if (pVal < 1.0e-6 && chosen.size > 0) break;
        chosen.add(this.candidates[idx]);
        acc += pVal;
        lastLp = lpVal;
      }
      return chosen;
    }
  }

  class GameSetInference {
    constructor(net, pathAware) {
      this.net = net;
      this.pathAware = pathAware;
      this.bgNoiseProb = BG_NOISE_PROB;
      this.suspects = new Set();
      this.baselineBadRate = new Map();
    }

    reset(candidateNodes) {
      this.suspects = new Set(candidateNodes);
      this.baselineBadRate.clear();
    }

    _isAnomalous(rec) {
      if (this.pathAware) {
        return binomSf(rec.packetsBad - 1, rec.packetsSent, this.bgNoiseProb) < 1.0e-3;
      }
      const rate = rec.packetsBad / Math.max(1, rec.packetsSent);
      return rec.packetsBad >= 1 && rate > 10.0 * this.bgNoiseProb;
    }

    update(window) {
      const pert = window.perturbation;
      if (!pert) {
        const probeRecs = window.records.filter((r) => r.isProbe);
        if (probeRecs.length > 1) {
          let cur = new Set(this.suspects);
          for (const pr of probeRecs) {
            const useTrace = this.pathAware || pr.tracedPath.length > 0;
            const subNodes = new Set();
            if (useTrace && pr.tracedPath.length > 0) {
              for (const n of pr.tracedPath) subNodes.add(n);
            } else {
              for (const item of pr.pathWeights) {
                for (const n of item.path) subNodes.add(n);
              }
            }
            const failed = this._isAnomalous(pr);
            const nxt = new Set();
            for (const s of cur) {
              if (failed ? subNodes.has(s) : !subNodes.has(s)) nxt.add(s);
            }
            if (nxt.size > 0) cur = nxt;
          }
          this.suspects = cur;
          return;
        }

        const pathNodes = new Set();
        for (const rec of window.records) {
          const pk = `${rec.pair[0]}:${rec.pair[1]}`;
          const rate = rec.packetsBad / Math.max(1, rec.packetsSent);
          this.baselineBadRate.set(pk, rate);
          if (rate > 5.0 * this.bgNoiseProb && rec.packetsBad > 0) {
            for (const item of rec.pathWeights) {
              for (const n of item.path) pathNodes.add(n);
            }
          }
        }
        if (pathNodes.size > 0) {
          const nxt = new Set();
          for (const s of this.suspects) {
            if (pathNodes.has(s)) nxt.add(s);
          }
          if (nxt.size > 0) this.suspects = nxt;
        }
        return;
      }

      if (pert.kind === "component_reset") {
        let stillBad = false;
        for (const r of window.records) {
          if (r.isProbe || r.isMirror) continue;
          const pk = `${r.pair[0]}:${r.pair[1]}`;
          const baseR = this.baselineBadRate.get(pk);
          const rate = r.packetsBad / Math.max(1, r.packetsSent);
          if (rate > Math.max(5.0 * this.bgNoiseProb, 0.35 * baseR)) {
            stillBad = true;
            break;
          }
        }
        const nxt = new Set();
        if (stillBad) {
          for (const s of this.suspects) {
            if (s !== pert.node) nxt.add(s);
          }
        } else if (this.suspects.has(pert.node)) {
          nxt.add(pert.node);
        }
        if (nxt.size > 0) this.suspects = nxt;
        return;
      }

      if (pert.kind === "active_probe") {
        const pr = window.records.find((r) => r.isProbe);
        const subNodes = new Set();
        if (this.pathAware) {
          for (const n of pr.tracedPath) subNodes.add(n);
        } else {
          for (const item of pr.pathWeights) {
            for (const n of item.path) subNodes.add(n);
          }
        }
        const failed = this._isAnomalous(pr);
        const nxt = new Set();
        for (const s of this.suspects) {
          if (failed ? subNodes.has(s) : !subNodes.has(s)) nxt.add(s);
        }
        if (nxt.size > 0) this.suspects = nxt;
        return;
      }

      if (pert.kind === "packet_mirror") {
        const mr = window.records.find((r) => r.isMirror);
        if (!mr) return;
        const upNodes = new Set();
        for (const item of mr.pathWeights) {
          for (const n of item.path) upNodes.add(n);
        }
        const seenUp = this._isAnomalous(mr);
        const nxt = new Set();
        for (const s of this.suspects) {
          if (seenUp ? upNodes.has(s) : !upNodes.has(s)) nxt.add(s);
        }
        if (nxt.size > 0) this.suspects = nxt;
        return;
      }

      if (
        pert.kind === "flow_link_drain" ||
        pert.kind === "full_link_drain" ||
        pert.kind === "flow_group_split"
      ) {
        for (const rec of window.records) {
          if (rec.isProbe || rec.isMirror) continue;
          const pk = `${rec.pair[0]}:${rec.pair[1]}`;
          const baseR = this.baselineBadRate.get(pk);
          if (baseR <= 5.0 * this.bgNoiseProb) continue;
          const currR = rec.packetsBad / Math.max(1, rec.packetsSent);
          const activeNodes = new Set();
          for (const item of rec.pathWeights) {
            for (const n of item.path) activeNodes.add(n);
          }
          const eliminated = currR <= Math.max(3.0 * this.bgNoiseProb, 0.2 * baseR);
          const nxt = new Set();
          for (const s of this.suspects) {
            if (eliminated ? !activeNodes.has(s) : activeNodes.has(s)) nxt.add(s);
          }
          if (nxt.size > 0) this.suspects = nxt;
        }
      }
    }

    posteriors() {
      const m = new Map();
      const w = 1.0 / this.suspects.size;
      for (const c of this.suspects) m.set(c, w);
      return m;
    }

    equivalenceSet() {
      return new Set(this.suspects);
    }
  }

  function makeInferenceEngine(net, mode, dutyCycle) {
    const prior = dutyCycle < 1.0 ? 0.7 : 1.0;
    if (mode === "flock" || mode === "bayesian") {
      return new MultiRoundBayesianPGM(net, false, prior);
    }
    if (mode === "flock_tr" || mode === "bayesian_tr") {
      return new MultiRoundBayesianPGM(net, true, prior);
    }
    if (mode === "set") {
      return new GameSetInference(net, false);
    }
    if (mode === "set_tr") {
      return new GameSetInference(net, true);
    }
    throw new Error(`Unknown inference mode: ${mode}`);
  }

  // ---------------------------------------------------------------------------
  // 6. Scenario Sampling & Collision-Free 2D Room Layout
  // ---------------------------------------------------------------------------
  function sampleFault(net, rng, numPairs) {
    const racks = net.rackNodes.filter((r) => !net.safety.externalBlackbox.has(r));
    for (const [maxPool, maxHops] of [
      [17, 9],
      [60, 30],
    ]) {
      for (let attempt = 0; attempt < 1000; attempt++) {
        const s = racks[rng.integers(0, racks.length)];
        const d = racks[rng.integers(0, racks.length)];
        if (s === d) continue;
        const paths = net.shortestPaths(s, d);
        if (paths.length < 2 || paths[0].length < 3 || paths[0].length > maxHops) continue;
        const interiorSet = new Set();
        for (const p of paths) {
          for (let i = 1; i < p.length - 1; i++) interiorSet.add(p[i]);
        }
        const interior = Array.from(interiorSet).sort((a, b) => a - b);
        if (interior.length < (maxPool === 17 ? 3 : 2)) continue;
        const culprit = interior[rng.integers(0, interior.length)];
        const pairs = [[s, d]];
        for (let a2 = 0; a2 < 300 && pairs.length < numPairs; a2++) {
          const s2 = racks[rng.integers(0, racks.length)];
          const d2 = racks[rng.integers(0, racks.length)];
          if (
            s2 !== d2 &&
            !pairs.some((pr) => pr[0] === s2 && pr[1] === d2) &&
            net.shortestPaths(s2, d2).some((p) => p.includes(culprit))
          ) {
            pairs.push([s2, d2]);
          }
        }
        if (pairs.length < numPairs) continue;
        const pool = new Set();
        for (const pair of pairs) {
          for (const p of net.shortestPaths(pair[0], pair[1])) {
            for (const n of p) pool.add(n);
          }
        }
        if (pool.size <= maxPool) return { pairs, culprit };
      }
    }
    throw new Error(`Failed to sample multi-path fault in ${net.name}`);
  }

  function computeRoomLayout(net, roomNodes, pairs) {
    const nodes = roomNodes.slice().sort((a, b) => a - b);
    const nodeSet = new Set(nodes);
    const dagEdgeMap = new Map();
    const subAdj = new Map();
    for (const n of nodes) subAdj.set(n, new Set());

    for (const pair of pairs) {
      for (const path of net.shortestPaths(pair[0], pair[1])) {
        for (let i = 0; i < path.length - 1; i++) {
          const x = path[i];
          const y = path[i + 1];
          if (nodeSet.has(x) && nodeSet.has(y)) {
            const a = Math.min(x, y);
            const b = Math.max(x, y);
            dagEdgeMap.set(`${a}:${b}`, [a, b]);
            subAdj.get(a).add(b);
            subAdj.get(b).add(a);
          }
        }
      }
    }

    const src = pairs[0][0];
    const dist = new Map([[src, 0]]);
    const q = [src];
    let head = 0;
    let maxD = 1;
    while (head < q.length) {
      const u = q[head++];
      const du = dist.get(u);
      if (du > maxD) maxD = du;
      for (const v of subAdj.get(u)) {
        if (!dist.has(v)) {
          dist.set(v, du + 1);
          q.push(v);
        }
      }
    }

    const layers = new Map();
    for (const n of nodes) {
      const d = dist.has(n) ? dist.get(n) : Math.floor(maxD / 2);
      if (!layers.has(d)) layers.set(d, []);
      layers.get(d).push(n);
    }

    const pos = new Map();
    const sortedCols = Array.from(layers.keys()).sort((a, b) => a - b);
    const totalCols = sortedCols.length;
    const wrap = totalCols > 8;
    const topCount = wrap ? Math.floor((totalCols + 1) / 2) : totalCols;

    sortedCols.forEach((d, colIdx) => {
      const members = layers.get(d);
      if (colIdx > 0) {
        const bary = (n) => {
          let sum = 0.0;
          let cnt = 0;
          for (const nb of subAdj.get(n)) {
            if (pos.has(nb)) {
              sum += pos.get(nb)[1];
              cnt++;
            }
          }
          return cnt > 0 ? sum / cnt : 0.5;
        };
        members.sort((a, b) => bary(a) - bary(b) || a - b);
      } else {
        members.sort((a, b) => a - b);
      }

      if (!wrap) {
        const xRaw = totalCols > 1 ? colIdx / Math.max(1, totalCols - 1) : 0.5;
        const xBase = 0.12 + 0.76 * xRaw;
        if (members.length <= 8) {
          members.forEach((n, rowIdx) => {
            const yRaw = (rowIdx + 1) / (members.length + 1);
            pos.set(n, [xBase, 0.2 + 0.6 * yRaw]);
          });
        } else {
          const subCols = Math.ceil(members.length / 7.0);
          members.forEach((n, mIdx) => {
            const sc = mIdx % subCols;
            const sr = Math.floor(mIdx / subCols);
            const rowsInSc = Math.ceil((members.length - sc) / subCols);
            const dx = (sc - (subCols - 1) / 2.0) * 0.065;
            const yRaw = (sr + 1) / (rowsInSc + 1);
            pos.set(n, [Math.min(0.9, Math.max(0.1, xBase + dx)), 0.18 + 0.64 * yRaw]);
          });
        }
      } else if (colIdx < topCount) {
        const x = 0.12 + 0.76 * (colIdx / Math.max(1, topCount - 1));
        members.forEach((n, rowIdx) => {
          const y = 0.16 + 0.26 * ((rowIdx + 1) / (members.length + 1));
          pos.set(n, [x, y]);
        });
      } else {
        const botIdx = colIdx - topCount;
        const botTotal = totalCols - topCount;
        const xRaw = botTotal > 1 ? 1.0 - botIdx / Math.max(1, botTotal - 1) : 0.5;
        const x = 0.12 + 0.76 * xRaw;
        members.forEach((n, rowIdx) => {
          const y = 0.56 + 0.26 * ((rowIdx + 1) / (members.length + 1));
          pos.set(n, [x, y]);
        });
      }
    });

    const edges = Array.from(dagEdgeMap.values()).sort(
      (a, b) => a[0] - b[0] || a[1] - b[1]
    );
    const socketT = new Map();
    const placedPts = nodes.map((n) => pos.get(n));
    const candidatesT = [0.5, 0.35, 0.65, 0.27, 0.73, 0.42, 0.58];

    for (const [u, v] of edges) {
      const [ax, ay] = pos.get(u);
      const [bx, by] = pos.get(v);
      let bestT = 0.5;
      let bestClear = -1.0;
      for (const ct of candidatesT) {
        const px = ax + (bx - ax) * ct;
        const py = ay + (by - ay) * ct;
        let minD = Infinity;
        for (const [qx, qy] of placedPts) {
          const d = Math.hypot(px - qx, py - qy);
          if (d < minD) minD = d;
        }
        if (minD > bestClear + 1.0e-6) {
          bestClear = minD;
          bestT = ct;
        }
        if (minD >= 0.045) {
          bestT = ct;
          break;
        }
      }
      const rt = Math.round(bestT * 1000) / 1000;
      socketT.set(`${u}:${v}`, rt);
      placedPts.push([ax + (bx - ax) * bestT, ay + (by - ay) * bestT]);
    }

    return { nodes, edges, pos, socketT };
  }

  function buildBackgroundContext(net, activeNodes, activePos, pairs) {
    const activeSet = new Set(activeNodes);
    const bgNodes = [];
    const bgEdges = [];
    const coordByKey = new Map();
    for (const n of activeNodes) coordByKey.set(`sw:${n}`, activePos.get(n));

    const src0 = pairs[0][0];
    const dst0 = pairs[0][1];
    const [, sy] = activePos.get(src0);
    const [dx, dy] = activePos.get(dst0);

    bgNodes.push({ key: "host:a", name: "host-a", kind: "host", active: true, x: 0.01, y: sy });
    coordByKey.set("host:a", [0.01, sy]);
    bgEdges.push({ a: "host:a", b: `sw:${src0}`, active: true });

    const dstX = dx > 0.5 ? 0.99 : 0.01;
    bgNodes.push({ key: "host:b", name: "host-b", kind: "host", active: true, x: dstX, y: dy });
    coordByKey.set("host:b", [dstX, dy]);
    bgEdges.push({ a: `sw:${dst0}`, b: "host:b", active: true });

    const ring1Set = new Set();
    for (const n of activeNodes) {
      for (const nb of net.neighbors(n)) {
        if (!activeSet.has(nb)) ring1Set.add(nb);
      }
    }
    const ring1 = Array.from(ring1Set).sort((a, b) => a - b);

    const ring2Set = new Set();
    for (const nb of ring1) {
      for (const nb2 of net.neighbors(nb)) {
        if (!activeSet.has(nb2) && !ring1Set.has(nb2)) ring2Set.add(nb2);
      }
    }
    const ring2 = Array.from(ring2Set).sort((a, b) => a - b);
    const candSw = ring1.concat(ring2).slice(0, 8);

    const anchorX = (sw) => {
      const actX = [];
      for (const nb of net.neighbors(sw)) {
        if (activeSet.has(nb)) actX.push(activePos.get(nb)[0]);
      }
      if (actX.length > 0) {
        return actX.reduce((a, b) => a + b, 0.0) / actX.length;
      }
      const ringX = [];
      for (const nb of net.neighbors(sw)) {
        for (const nb2 of net.neighbors(nb)) {
          if (activeSet.has(nb2)) ringX.push(activePos.get(nb2)[0]);
        }
      }
      return ringX.length > 0 ? ringX.reduce((a, b) => a + b, 0.0) / ringX.length : 0.5;
    };

    candSw.sort(
      (a, b) => Math.round(anchorX(a) * 1000) - Math.round(anchorX(b) * 1000) || a - b
    );
    const topSw = candSw.filter((_, i) => i % 2 === 0);
    const botSw = candSw.filter((_, i) => i % 2 === 1);

    topSw.forEach((sw, idx) => {
      const bx = 0.16 + 0.68 * ((idx + 0.5) / Math.max(1, topSw.length));
      const by = 0.065;
      const k = `sw:${sw}`;
      bgNodes.push({
        key: k,
        name: net.nodeName(sw),
        kind: "switch",
        active: false,
        x: Math.round(bx * 10000) / 10000,
        y: by,
      });
      coordByKey.set(k, [bx, by]);
    });

    botSw.forEach((sw, idx) => {
      const bx = 0.24 + 0.64 * ((idx + 0.5) / Math.max(1, botSw.length));
      const by = 0.925;
      const k = `sw:${sw}`;
      bgNodes.push({
        key: k,
        name: net.nodeName(sw),
        kind: "switch",
        active: false,
        x: Math.round(bx * 10000) / 10000,
        y: by,
      });
      coordByKey.set(k, [bx, by]);
    });

    const chosenBgSet = new Set(candSw);
    const seenE = new Set();
    for (const sw of candSw) {
      const swX = coordByKey.get(`sw:${sw}`)[0];
      const nbs = net
        .neighbors(sw)
        .filter((nb) => activeSet.has(nb) || chosenBgSet.has(nb))
        .sort(
          (a, b) =>
            Math.abs(swX - coordByKey.get(`sw:${a}`)[0]) -
            Math.abs(swX - coordByKey.get(`sw:${b}`)[0])
        );
      for (const nb of nbs.slice(0, 2)) {
        const ka = `sw:${sw}`;
        const kb = `sw:${nb}`;
        const pk = ka < kb ? `${ka}|${kb}` : `${kb}|${ka}`;
        if (!seenE.has(pk)) {
          seenE.add(pk);
          bgEdges.push({ a: ka, b: kb, active: false });
        }
      }
    }

    const rackSet = new Set(net.rackNodes);
    let hostAttach = candSw.filter((sw) => rackSet.has(sw)).slice(0, 3);
    if (hostAttach.length < 2) hostAttach = candSw.slice(0, 2);
    hostAttach.forEach((sw, hIdx) => {
      const [sxB, syB] = coordByKey.get(`sw:${sw}`);
      const hx = sxB < 0.5 ? Math.max(0.02, sxB - 0.09) : Math.min(0.98, sxB + 0.09);
      const hy = syB;
      const hk = `host:bg${hIdx + 1}`;
      bgNodes.push({
        key: hk,
        name: `host-${hIdx + 1}`,
        kind: "host",
        active: false,
        x: Math.round(hx * 10000) / 10000,
        y: Math.round(hy * 10000) / 10000,
      });
      coordByKey.set(hk, [hx, hy]);
      bgEdges.push({ a: hk, b: `sw:${sw}`, active: false });
    });

    const resolvedEdges = bgEdges.map((e) => {
      const [x1, y1] = coordByKey.get(e.a);
      const [x2, y2] = coordByKey.get(e.b);
      return {
        x1: Math.round(x1 * 10000) / 10000,
        y1: Math.round(y1 * 10000) / 10000,
        x2: Math.round(x2 * 10000) / 10000,
        y2: Math.round(y2 * 10000) / 10000,
        active: e.active,
      };
    });

    return { bgNodes, bgEdges: resolvedEdges };
  }

  // ---------------------------------------------------------------------------
  // 7. Action JSON <-> Internal Perturbation & LocalGameSession
  // ---------------------------------------------------------------------------
  function actionToJson(net, p, multiPair = false) {
    const d = { kind: p.kind, plane: p.plane, key: p.key };
    if (p.kind === "active_probe") {
      const sNm = net.nodeName(p.srcNode);
      const dNm = net.nodeName(p.dstNode);
      const pairS = multiPair
        ? ` (${net.nodeName(p.flowPair[0])}→${net.nodeName(p.flowPair[1])})`
        : "";
      d.icon = "active_probe";
      d.title = `Ping ${sNm} → ${dNm}`;
      d.subtitle = `Test hops to receiver${pairS}`;
      d.params = {
        src: p.srcNode,
        dst: p.dstNode,
        pair: [p.flowPair[0], p.flowPair[1]],
        num_probes: p.numProbes,
      };
      d.anchor = { type: "node", id: p.srcNode };
      d.nodes = [p.srcNode, p.dstNode];
      d.edges = [];
    } else if (p.kind === "packet_mirror") {
      const nNm = net.nodeName(p.node);
      const modeS = p.filtered ? "filtered" : "raw";
      const pairS = multiPair
        ? ` · ${net.nodeName(p.flowPair[0])}→${net.nodeName(p.flowPair[1])}`
        : "";
      d.icon = "packet_mirror";
      d.title = `Tap @ ${nNm}`;
      d.subtitle = `Check ${modeS} packets here${pairS}`;
      d.params = {
        node: p.node,
        filtered: p.filtered,
        pair: [p.flowPair[0], p.flowPair[1]],
      };
      d.anchor = { type: "node", id: p.node };
      d.nodes = [p.node];
      d.edges = [];
    } else if (p.kind === "subtle_weight_shift") {
      const uNm = net.nodeName(p.u);
      const vNm = net.nodeName(p.v);
      const a = Math.min(p.u, p.v);
      const b = Math.max(p.u, p.v);
      d.icon = "subtle_weight_shift";
      d.title = `Dial 20% ${uNm} → ${vNm}`;
      d.subtitle = "Gently nudge 80% of flow elsewhere";
      d.params = { u: p.u, v: p.v, w: p.weightFactor, pair: [p.flowPair[0], p.flowPair[1]] };
      d.anchor = { type: "edge", u: a, v: b };
      d.nodes = [];
      d.edges = [[p.u, p.v]];
    } else if (p.kind === "flow_link_drain") {
      const uNm = net.nodeName(p.u);
      const vNm = net.nodeName(p.v);
      const a = Math.min(p.u, p.v);
      const b = Math.max(p.u, p.v);
      d.icon = "flow_link_drain";
      d.title = `Detour ${uNm} → ${vNm}`;
      d.subtitle = "Move broken flow off this link";
      d.params = { u: p.u, v: p.v, pair: [p.flowPair[0], p.flowPair[1]] };
      d.anchor = { type: "edge", u: a, v: b };
      d.nodes = [];
      d.edges = [[p.u, p.v]];
    } else if (p.kind === "flow_group_split") {
      const uNm = net.nodeName(p.u);
      const nhNames = p.drainedNexthops.map((v) => net.nodeName(v)).join(", ");
      d.icon = "flow_group_split";
      d.title = `Split @ ${uNm}`;
      d.subtitle = `Drain half of branches (${nhNames})`;
      d.params = {
        u: p.u,
        nexthops: p.drainedNexthops.slice(),
        pair: [p.flowPair[0], p.flowPair[1]],
      };
      d.anchor = { type: "node", id: p.u };
      d.nodes = [p.u];
      d.edges = p.drainedNexthops.map((v) => [p.u, v]);
    } else if (p.kind === "full_link_drain") {
      const uNm = net.nodeName(p.u);
      const vNm = net.nodeName(p.v);
      const a = Math.min(p.u, p.v);
      const b = Math.max(p.u, p.v);
      d.icon = "full_link_drain";
      d.title = `Shut Link ${uNm} ↔ ${vNm}`;
      d.subtitle = "Cut link for ALL traffic";
      d.params = { u: p.u, v: p.v };
      d.anchor = { type: "edge", u: a, v: b };
      d.nodes = [];
      d.edges = [[p.u, p.v]];
    } else if (p.kind === "component_reset") {
      const nNm = net.nodeName(p.node);
      d.icon = "component_reset";
      d.title = `Reboot ${nNm}`;
      d.subtitle = "Restart switch (heavy outage!)";
      d.params = { node: p.node };
      d.anchor = { type: "node", id: p.node };
      d.nodes = [p.node];
      d.edges = [];
    } else {
      throw new Error(`Unknown perturbation: ${p.kind}`);
    }
    return d;
  }

  function actionFromJson(d) {
    const k = d.kind;
    const a = d.params;
    if (k === "active_probe") {
      return makeProbe(Number(a.src), Number(a.dst), [Number(a.pair[0]), Number(a.pair[1])], Number(a.num_probes));
    }
    if (k === "packet_mirror") {
      return makeMirror(Number(a.node), Boolean(a.filtered), [Number(a.pair[0]), Number(a.pair[1])]);
    }
    if (k === "flow_link_drain") {
      return makeFlowDrain(Number(a.u), Number(a.v), [Number(a.pair[0]), Number(a.pair[1])]);
    }
    if (k === "flow_group_split") {
      return makeGroupSplit(
        Number(a.u),
        a.nexthops.map((x) => Number(x)),
        [Number(a.pair[0]), Number(a.pair[1])]
      );
    }
    if (k === "subtle_weight_shift") {
      return makeWeightShift(Number(a.u), Number(a.v), Number(a.w), [Number(a.pair[0]), Number(a.pair[1])]);
    }
    if (k === "full_link_drain") {
      return makeFullDrain(Number(a.u), Number(a.v));
    }
    if (k === "component_reset") {
      return makeReset(Number(a.node));
    }
    throw new Error(`Unknown action kind: ${k}`);
  }

  function entropyBits(postMap) {
    let h = 0.0;
    for (const p of postMap.values()) {
      if (p > 1.0e-12) h -= p * Math.log2(p);
    }
    return h;
  }

  let sessionCounter = 1;

  class LocalGameSession {
    constructor({ topology, failureMode, inference, seed, numPairs, dropProb, credMass }) {
      if (!FAILURE_MODES.includes(failureMode)) {
        throw new Error(`Invalid failure mode: ${failureMode}`);
      }
      if (!INFERENCE_MODES.includes(inference)) {
        throw new Error(`Invalid inference mode: ${inference}`);
      }
      this.id = `local-${sessionCounter++}-${seed}`;
      this.topology = topology;
      this.inferenceMode = inference;
      this.seed = seed;
      this.credMass = credMass;
      this.net = getNetwork(topology);

      const sampleRng = new Rng(seed);
      const { pairs, culprit } = sampleFault(this.net, sampleRng, numPairs);
      this.failure = new FailureSpec(failureMode, culprit, pairs, dropProb);

      const rawRoomSet = new Set();
      for (const pair of pairs) {
        for (const path of this.net.shortestPaths(pair[0], pair[1])) {
          for (const n of path) rawRoomSet.add(n);
        }
      }
      const rawRoom = Array.from(rawRoomSet).sort((a, b) => a - b);
      const layout = computeRoomLayout(this.net, rawRoom, pairs);
      this.edges = layout.edges;
      this.pos = layout.pos;
      this.socketT = layout.socketT;

      const bg = buildBackgroundContext(this.net, rawRoom, this.pos, pairs);
      this.bgNodes = bg.bgNodes;
      this.bgEdges = bg.bgEdges;

      this.nodes = rawRoom.slice().sort((a, b) => {
        const [ax, ay] = this.pos.get(a);
        const [bx, by] = this.pos.get(b);
        return (
          Math.round(ax * 10000) - Math.round(bx * 10000) ||
          Math.round(ay * 10000) - Math.round(by * 10000) ||
          a - b
        );
      });

      const endpoints = new Set();
      for (const pair of pairs) {
        endpoints.add(pair[0]);
        endpoints.add(pair[1]);
      }
      this.pool = this.nodes.filter((n) => !endpoints.has(n));

      let maxPaths = 1;
      for (const pair of pairs) {
        maxPaths = Math.max(maxPaths, this.net.shortestPaths(pair[0], pair[1]).length);
      }
      this.flowsPerPair = Math.max(FLOWS_PER_PAIR, 25 * maxPaths);

      this.rng = new Rng(seed + 1000);
      const win0 = this.net.simulateWindow(
        this.failure,
        null,
        this.rng,
        this.flowsPerPair,
        PACKETS_PER_FLOW
      );
      this.windows = [win0];
      this.rawEvents = [
        {
          step: 0,
          move_num: 0,
          status: "observe",
          action: null,
          windowIdx: 0,
          time: 0.0,
          disruption: 0.0,
          fives_rank: null,
          reason: null,
          note: null,
        },
      ];

      this.tried = new Set();
      this.lastControlPert = null;
      this.nActions = 0;
      this.nRejected = 0;
      this.totalTime = 0.0;
      this.totalDisruption = 0.0;
      this.lastLambda = 0.5;
      this.lastK = 1;
      this.accusedNode = null;

      this.engine = makeInferenceEngine(this.net, inference, this.failure.dutyCycle);
      this.eqSet = new Set();
      this.history = [];
      this._rebuildInference();
    }

    _effectivePacketsPerFlow() {
      return this.failure.mode === "blackhole" || this.failure.mode === "high_latency"
        ? 1
        : PACKETS_PER_FLOW;
    }

    _telemetryJson(win) {
      return win.records.map((r) => ({
        kind: r.isProbe ? "probe" : r.isMirror ? "mirror" : "flow",
        pair: [r.pair[0], r.pair[1]],
        sent: r.packetsSent,
        bad: r.packetsBad,
        rate: r.packetsBad / Math.max(1, r.packetsSent),
        traced_path: r.tracedPath.slice(),
      }));
    }

    _rebuildInference() {
      this.engine = makeInferenceEngine(this.net, this.inferenceMode, this.failure.dutyCycle);
      this.engine.reset(this.pool);
      const built = [];
      let currEq = new Set(this.pool);

      for (const ev of this.rawEvents) {
        const before = new Set(currEq);
        let tel = [];
        let faultAct = true;

        if (ev.status === "accuse") {
          currEq = new Set([ev.accusedNode]);
        } else if (ev.windowIdx !== null) {
          const win = this.windows[ev.windowIdx];
          this.engine.update(win);
          currEq = this.engine.equivalenceSet(this.credMass);
          tel = this._telemetryJson(win);
          faultAct = win.faultWasActive;
        }

        const postSnap = this.engine.posteriors();
        const postObj = {};
        for (const n of this.pool) {
          if (ev.status === "accuse") {
            postObj[String(n)] = n === ev.accusedNode ? 1.0 : 0.0;
          } else {
            postObj[String(n)] = postSnap.has(n)
              ? Math.round(postSnap.get(n) * 10000) / 10000
              : 0.0;
          }
        }

        const removed = [];
        for (const b of before) {
          if (!currEq.has(b)) removed.push(b);
        }
        removed.sort((a, b) => a - b);

        built.push({
          step: ev.step,
          move_num: ev.move_num,
          status: ev.status,
          action: ev.action,
          reason: ev.reason,
          note: ev.note,
          telemetry: tel,
          fault_active: faultAct,
          eq_before: before.size,
          eq_after: currEq.size,
          eq_nodes: Array.from(currEq).sort((a, b) => a - b),
          removed,
          posteriors: postObj,
          time: ev.time,
          disruption: ev.disruption,
          fives_rank: ev.fives_rank,
        });
      }

      this.eqSet = currEq;
      this.history = built;
    }

    _estDrop() {
      if (this.engine instanceof MultiRoundBayesianPGM) {
        return this.engine.estimatedDropProb;
      }
      return this.failure.unitBadProb(true);
    }

    _status() {
      if (this.eqSet.size === 1) {
        return this.eqSet.has(this.failure.faultyNode) ? "localized" : "mislocalized";
      }
      if (!this.eqSet.has(this.failure.faultyNode)) {
        return "culprit_eliminated";
      }
      return "playing";
    }

    _edgeFlowWeights() {
      const weights = new Map();
      for (const [u, v] of this.edges) weights.set(`${u}:${v}`, 0.0);
      const pairs = this.failure.affectedPairs;
      for (const pair of pairs) {
        for (const item of this.net.pathsUnderPerturbation(pair, this.lastControlPert)) {
          for (let i = 0; i < item.path.length - 1; i++) {
            const a = Math.min(item.path[i], item.path[i + 1]);
            const b = Math.max(item.path[i], item.path[i + 1]);
            const ek = `${a}:${b}`;
            if (weights.has(ek)) {
              weights.set(ek, weights.get(ek) + item.weight / pairs.length);
            }
          }
        }
      }
      return weights;
    }

    stats() {
      const post = this.engine.posteriors();
      let topPost = 0.0;
      for (const v of post.values()) {
        if (v > topPost) topPost = v;
      }
      return {
        actions: this.nActions,
        rejected: this.nRejected,
        time_sec: this.totalTime,
        disruption: this.totalDisruption,
        eq_size: this.eqSet.size,
        initial_eq_size: this.history[0].eq_after,
        pool_size: this.pool.length,
        entropy_bits: entropyBits(post),
        top_posterior: topPost,
        status: this._status(),
      };
    }

    stateJson() {
      const net = this.net;
      const cfg = net.safety;
      const post = this.engine.posteriors();
      const endpoints = new Set();
      const srcs = new Set();
      const dsts = new Set();
      for (const pair of this.failure.affectedPairs) {
        endpoints.add(pair[0]);
        endpoints.add(pair[1]);
        srcs.add(pair[0]);
        dsts.add(pair[1]);
      }
      const poolSet = new Set(this.pool);

      const nodes = this.nodes.map((n) => {
        const tags = [];
        if (cfg.drainBanned.has(n)) tags.push("no-drain");
        if (cfg.resetBanned.has(n)) tags.push("no-reset");
        if (cfg.probeBanned.has(n)) tags.push("no-probe");
        if (cfg.externalBlackbox.has(n)) tags.push("blackbox");
        const role = srcs.has(n) ? "src" : dsts.has(n) ? "dst" : "switch";
        const [x, y] = this.pos.get(n);
        return {
          id: n,
          name: net.nodeName(n),
          role,
          is_endpoint: endpoints.has(n),
          in_pool: poolSet.has(n),
          x,
          y,
          suspect: this.eqSet.has(n),
          posterior: post.has(n) ? post.get(n) : 0.0,
          tags,
        };
      });

      const ew = this._edgeFlowWeights();
      const edges = this.edges.map(([u, v]) => {
        const ek = `${u}:${v}`;
        return {
          u,
          v,
          socket_t: this.socketT.get(ek),
          flow_weight: Math.round(ew.get(ek) * 10000) / 10000,
          load: Math.round(net.edgeLoad(u, v) * 1000) / 1000,
          cap: Math.round(net.edgeCap(u, v) * 10) / 10,
        };
      });

      const flow0 = this.history[0].telemetry.filter((r) => r.kind === "flow");
      const baseRate =
        flow0.reduce((acc, r) => acc + r.rate, 0.0) / Math.max(1, flow0.length);

      return {
        id: this.id,
        topology: this.topology,
        seed: this.seed,
        inference: this.inferenceMode,
        baseline_loss_rate: Math.round(baseRate * 100000) / 100000,
        total_switches: net.switchNodes.length,
        ruled_out_off_path: Math.max(0, net.switchNodes.length - this.pool.length),
        failure: {
          mode: this.failure.mode,
          culprit: this.failure.faultyNode,
          culprit_name: net.nodeName(this.failure.faultyNode),
          pairs: this.failure.affectedPairs.map((p) => [p[0], p[1]]),
          pair_names: this.failure.affectedPairs.map((p) => [
            net.nodeName(p[0]),
            net.nodeName(p[1]),
          ]),
          drop_prob: this.failure.dropProb,
        },
        nodes,
        bg_nodes: this.bgNodes,
        bg_edges: this.bgEdges,
        suspect_ids: this.pool.slice(),
        edges,
        eq_set: Array.from(this.eqSet).sort((a, b) => a - b),
        stats: this.stats(),
        history: this.history,
      };
    }

    candidateActions() {
      const pairs = this.failure.affectedPairs;
      const multi = pairs.length > 1;
      const cands = this.net.candidatePerturbations(pairs, new Set(this.pool));
      const seen = new Set(cands.map((p) => p.key));
      const add = (p) => {
        if (!seen.has(p.key)) {
          seen.add(p.key);
          cands.push(p);
        }
      };

      for (const pair of pairs) {
        const dst = pair[1];
        for (const n of this.nodes) {
          if (n !== dst) add(makeProbe(n, dst, pair));
          if (this.net.safety.enablePacketMirror && n !== pair[0] && n !== pair[1]) {
            const filt = !this.net.safety.mirrorUnfilteredOnly.has(n);
            add(makeMirror(n, filt, pair));
          }
        }
      }
      if (this.net.safety.enableComponentReset) {
        for (const n of this.pool) add(makeReset(n));
      }

      const planeOrder = { telemetry: 0, control: 1, physical: 2 };
      const est = this._estDrop();
      const out = cands.map((p) => {
        const d = actionToJson(this.net, p, multi);
        d.violation = violationReason(this.net, p, pairs);
        const imp = estimateImpact(this.net, p, est);
        d.est_time = Math.round(imp.totalTimeSec * 100) / 100;
        d.est_disruption = Math.round(imp.totalDisruption * 1000) / 1000;
        d.tried = this.tried.has(p.key);
        return d;
      });

      out.sort((a, b) => {
        const va = a.violation !== null ? 1 : 0;
        const vb = b.violation !== null ? 1 : 0;
        if (va !== vb) return va - vb;
        if (planeOrder[a.plane] !== planeOrder[b.plane]) {
          return planeOrder[a.plane] - planeOrder[b.plane];
        }
        if (a.est_disruption !== b.est_disruption) {
          return a.est_disruption - b.est_disruption;
        }
        return a.title.localeCompare(b.title);
      });
      return out;
    }

    _ranking(lam, k) {
      const post = this.engine.posteriors();
      const suspects = new Set();
      for (const [c, pr] of post.entries()) {
        if (pr > 1.0e-6) suspects.add(c);
      }
      if (suspects.size <= 1) return [];

      const est = this._estDrop();
      const pairs = this.failure.affectedPairs;
      const isSetMode = this.inferenceMode === "set" || this.inferenceMode === "set_tr";
      const ppf = this._effectivePacketsPerFlow();
      const pNodeMap =
        this.engine instanceof MultiRoundBayesianPGM ? this.engine.nodeDropProb : null;

      const rawCands = this.net.candidatePerturbations(pairs, suspects);
      const out = [];
      for (const p of rawCands) {
        if (this.tried.has(p.key)) continue;
        if (violationReason(this.net, p, pairs) !== null) continue;
        if (isSetMode && p.kind === "subtle_weight_shift") continue;
        const [ig, pairsW] = mutualInformationAndPairs(
          this.net,
          p,
          post,
          pairs,
          est,
          pNodeMap,
          this.flowsPerPair,
          ppf
        );
        let sc = 0.0;
        if (ig > 1.0e-9 || pairsW > 1.0e-9) {
          const cost = estimateImpact(this.net, p, est).scalarCost(lam);
          sc = (ig + 1.0e-3 * pairsW) / cost;
        }
        out.push({ score: sc, ig, pert: p });
      }

      out.sort((a, b) => b.score - a.score);
      return out;
    }

    _fivesRankOf(p) {
      const useful = this._ranking(this.lastLambda, this.lastK).filter((t) => t.score > 0.0);
      const idx = useful.findIndex((t) => t.pert.key === p.key);
      return { rank: idx >= 0 ? idx + 1 : null, of: useful.length };
    }

    apply(actionObj) {
      if (this._status() !== "playing") {
        return {
          result: this.history[this.history.length - 1],
          state: this.stateJson(),
          actions: this.candidateActions(),
        };
      }

      const p = actionFromJson(actionObj);
      const pairs = this.failure.affectedPairs;
      const multi = pairs.length > 1;
      const rankInfo = this._fivesRankOf(p);
      const reason = violationReason(this.net, p, pairs);
      const step = this.rawEvents.length;

      if (reason !== null) {
        this.nRejected += 1;
        this.rawEvents.push({
          step,
          move_num: this.nActions,
          status: "rejected",
          action: actionToJson(this.net, p, multi),
          windowIdx: null,
          time: 0.0,
          disruption: 0.0,
          fives_rank: rankInfo,
          reason,
          note: null,
        });
        this._rebuildInference();
        return {
          result: this.history[this.history.length - 1],
          state: this.stateJson(),
          actions: this.candidateActions(),
        };
      }

      const imp = estimateImpact(this.net, p, this.failure.dropProb);
      const win = this.net.simulateWindow(
        this.failure,
        p,
        this.rng,
        this.flowsPerPair,
        PACKETS_PER_FLOW
      );
      const winIdx = this.windows.length;
      this.windows.push(win);
      this.tried.add(p.key);
      this.lastControlPert = p.plane === "control" ? p : null;
      this.nActions += 1;
      this.totalTime += imp.totalTimeSec;
      this.totalDisruption += imp.totalDisruption;

      this.rawEvents.push({
        step,
        move_num: this.nActions,
        status: "applied",
        action: actionToJson(this.net, p, multi),
        windowIdx: winIdx,
        time: Math.round(imp.totalTimeSec * 100) / 100,
        disruption: Math.round(imp.totalDisruption * 1000) / 1000,
        fives_rank: rankInfo,
        reason: null,
        note: null,
      });
      this._rebuildInference();
      return {
        result: this.history[this.history.length - 1],
        state: this.stateJson(),
        actions: this.candidateActions(),
      };
    }

    setInference(mode) {
      if (!INFERENCE_MODES.includes(mode)) {
        throw new Error(`Invalid inference mode: ${mode}`);
      }
      this.inferenceMode = mode;
      this._rebuildInference();
      return { state: this.stateJson() };
    }

    accuse(nodeId) {
      if (this._status() !== "playing") {
        return {
          result: this.history[this.history.length - 1],
          state: this.stateJson(),
          actions: this.candidateActions(),
        };
      }
      const nid = Number(nodeId);
      if (!this.pool.includes(nid)) {
        throw new Error(`Switch ${nid} is not an interior suspect`);
      }
      this.accusedNode = nid;
      this.nActions += 1;
      const nm = this.net.nodeName(nid);
      const correct = nid === this.failure.faultyNode;
      this.rawEvents.push({
        step: this.rawEvents.length,
        move_num: this.nActions,
        status: "accuse",
        accusedNode: nid,
        action: {
          kind: "accuse",
          plane: "telemetry",
          icon: "accuse",
          title: `Accuse ${nm}`,
          subtitle: "final culprit arrest",
          anchor: { type: "node", id: nid },
          nodes: [nid],
          edges: [],
        },
        windowIdx: null,
        time: 0.0,
        disruption: 0.0,
        fives_rank: null,
        reason: null,
        note: `Arrested ${nm} — ${correct ? "guilty!" : "innocent!"}`,
      });
      this._rebuildInference();
      return {
        result: this.history[this.history.length - 1],
        state: this.stateJson(),
        actions: this.candidateActions(),
      };
    }

    fives(lam, k, top) {
      this.lastLambda = lam;
      this.lastK = k;
      const ranking = this._ranking(lam, k).filter((t) => t.score > 0.0);
      const est = this._estDrop();
      const multi = this.failure.affectedPairs.length > 1;
      const eqSorted = Array.from(this.eqSet).sort((a, b) => a - b);

      const rows = ranking.slice(0, top).map(({ score, ig, pert }) => {
        const imp = estimateImpact(this.net, pert, est);
        const d = actionToJson(this.net, pert, multi);
        const buckets = Array.from(
          partitionSuspects(this.net, pert, eqSorted, this.failure.affectedPairs).values()
        );
        buckets.sort((a, b) => b.group.length - a.group.length);
        d.score = Math.round(score * 1000) / 1000;
        d.info_gain_bits = Math.round(ig * 1000) / 1000;
        d.est_time = Math.round(imp.totalTimeSec * 100) / 100;
        d.est_disruption = Math.round(imp.totalDisruption * 1000) / 1000;
        d.cost = Math.round(imp.scalarCost(lam) * 1000) / 1000;
        d.partition = buckets.map((b) => b.group.length);
        d.partition_groups = buckets.map((b) => b.group.map((s) => this.net.nodeName(s)));
        return d;
      });

      return {
        lambda: lam,
        k,
        est_drop_prob: est,
        n_safe: ranking.length,
        ranking: rows,
        best: rows.length > 0 ? rows[0] : null,
      };
    }
  }

  // ---------------------------------------------------------------------------
  // 8. Public In-Browser API (`window.LocalEngine`)
  // ---------------------------------------------------------------------------
  const SESSIONS = new Map();

  window.LocalEngine = {
    getConfig() {
      return {
        topologies: Object.keys(window.TOPOLOGY_DATA),
        failure_modes: FAILURE_MODES.slice(),
        inference_modes: INFERENCE_MODES.slice(),
        weapons: WEAPONS.map((w) => ({ ...w })),
        daily_seed: dailySeed(),
      };
    },

    newSession(body) {
      const rawSeed = String(body.seed).trim();
      let seed;
      if (rawSeed === "daily") {
        seed = dailySeed();
      } else if (rawSeed === "") {
        seed = Math.floor(Date.now() % 1000000);
      } else {
        seed = Number(rawSeed);
      }
      const s = new LocalGameSession({
        topology: body.topology,
        failureMode: body.failure_mode,
        inference: body.inference,
        seed,
        numPairs: Number(body.num_pairs),
        dropProb: Number(body.drop_prob),
        credMass: Number(body.cred_mass),
      });
      SESSIONS.clear();
      SESSIONS.set(s.id, s);
      return { state: s.stateJson(), actions: s.candidateActions() };
    },

    getActions(sid) {
      const s = SESSIONS.get(sid);
      if (!s) throw new Error(`Session not found: ${sid}`);
      return { actions: s.candidateActions() };
    },

    apply(sid, action) {
      const s = SESSIONS.get(sid);
      if (!s) throw new Error(`Session not found: ${sid}`);
      return s.apply(action);
    },

    setInference(sid, inference) {
      const s = SESSIONS.get(sid);
      if (!s) throw new Error(`Session not found: ${sid}`);
      return s.setInference(inference);
    },

    accuse(sid, node) {
      const s = SESSIONS.get(sid);
      if (!s) throw new Error(`Session not found: ${sid}`);
      return s.accuse(node);
    },

    fives(sid, lam, k, top) {
      const s = SESSIONS.get(sid);
      if (!s) throw new Error(`Session not found: ${sid}`);
      return s.fives(Number(lam), Number(k), Number(top));
    },
  };
})();
