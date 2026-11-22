"""Summarize testbed-replay trials: mean and 90% CI half-width (1.645 * std / sqrt(n)) per metric.

loss_frac is pooled over trials (sum lost / sum offered pair-seconds; trials that localize with zero
perturbations contribute nothing), with a 90% percentile-bootstrap CI over trials (2000 resamples).
"""
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMES = ("FIVES", "Operator-PA", "Drain-Sweep")
METRICS = ("steps", "precision", "recall", "localized", "time_s", "lost_gb",
           "n_probe", "n_mirror", "n_drain")
Z90 = 1.6448536269514722


def main():
    out = {}
    for scen in ("blackhole", "silent_drop", "high_latency"):
        rows = json.load(open(os.path.join(HERE, f"tb_{scen}.json")))
        out[scen] = {"n": len(rows)}
        for s in SCHEMES:
            out[scen][s] = {}
            for m in METRICS:
                x = np.array([r[s][m] for r in rows], dtype=float)
                out[scen][s][m] = {"mean": float(x.mean()), "ci90": float(Z90 * x.std(ddof=1) / np.sqrt(len(x)))}
            lost = np.array([r[s]["lost_pair_s"] for r in rows])
            offered = np.array([r[s]["offered_pair_s"] for r in rows])
            rng = np.random.default_rng(0)
            boot = [lost[i].sum() / offered[i].sum() for i in rng.integers(0, len(rows), size=(2000, len(rows)))]
            lo, hi = np.percentile(boot, [5, 95])
            out[scen][s]["loss_frac"] = {"pooled": float(lost.sum() / offered.sum()), "ci90_lo": float(lo),
                                         "ci90_hi": float(hi)}
    json.dump(out, open(os.path.join(HERE, "tb_summary.json"), "w"), indent=1)
    print("| Scenario | Scheme | n | Steps | Precision | Recall | Loc. rate | Time (s) | Loss frac (pooled, 90% CI) | Lost (GB) | probe/mirror/drain |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for scen, e in out.items():
        for s in SCHEMES:
            v = e[s]
            f = lambda m, d=2: f"{v[m]['mean']:.{d}f}±{v[m]['ci90']:.{d}f}"
            print(f"| {scen} | {s} | {e['n']} | {f('steps')} | {f('precision', 3)} | {f('recall', 3)} | "
                  f"{v['localized']['mean']:.3f} | {f('time_s', 1)} | {v['loss_frac']['pooled']:.4f} "
                  f"[{v['loss_frac']['ci90_lo']:.4f}, {v['loss_frac']['ci90_hi']:.4f}] | {f('lost_gb', 2)} | "
                  f"{v['n_probe']['mean']:.2f}/{v['n_mirror']['mean']:.2f}/{v['n_drain']['mean']:.2f} |")


if __name__ == "__main__":
    main()
