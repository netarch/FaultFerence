"""Summarize testbed trials: mean and 90% CI half-width (1.645 * std / sqrt(n)) per metric.

loss_frac is pooled over trials (sum lost / sum offered pair-seconds; trials that localize with zero
perturbations contribute nothing), with a 90% percentile-bootstrap CI over trials (2000 resamples).

Usage:
  python3 summarize_testbed.py [--indir out] [--outdir out]
"""
import argparse
import json
import os

import numpy as np

SCHEMES = ("FIVES", "Operator-PA", "Drain-Sweep")
SCENARIOS = ("blackhole", "silent_drop", "high_latency")
METRICS = ("eq0", "steps", "precision", "recall", "localized", "time_s", "lost_gb",
           "n_probe", "n_mirror", "n_drain")
Z90 = 1.6448536269514722


def summarize_dir(indir: str, outdir: str) -> str:
    os.makedirs(outdir, exist_ok=True)
    out = {}
    for scen in SCENARIOS:
        rows = json.load(open(os.path.join(indir, f"tb_{scen}.json")))
        out[scen] = {"n": len(rows)}
        for s in SCHEMES:
            out[scen][s] = {}
            for m in METRICS:
                x = np.array([r[s][m] for r in rows], dtype=float)
                out[scen][s][m] = {"mean": float(x.mean()), "ci90": float(Z90 * x.std(ddof=1) / np.sqrt(len(x)))}
            lost = np.array([r[s]["lost_pair_s"] for r in rows], dtype=float)
            offered = np.array([r[s]["offered_pair_s"] for r in rows], dtype=float)
            rng = np.random.default_rng(0)
            boot = [lost[i].sum() / offered[i].sum() for i in rng.integers(0, len(rows), size=(2000, len(rows)))]
            lo, hi = np.percentile(boot, [5, 95])
            out[scen][s]["loss_frac"] = {
                "pooled": float(lost.sum() / offered.sum()),
                "ci90_lo": float(lo),
                "ci90_hi": float(hi),
            }
    with open(os.path.join(outdir, "tb_summary.json"), "w") as fp:
        json.dump(out, fp, indent=1)
        fp.write("\n")

    lines = [
        "| Scenario | Scheme | n | Initial eq. (|E_0|) | Steps | Precision | Recall | Loc. rate | Time (s) | Loss frac (pooled, 90% CI) | Lost (GB) | probe/mirror/drain |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for scen, e in out.items():
        for s in SCHEMES:
            v = e[s]
            fmt = lambda m, d=2: f"{v[m]['mean']:.{d}f}±{v[m]['ci90']:.{d}f}"
            lines.append(
                f"| {scen} | {s} | {e['n']} | {fmt('eq0')} | {fmt('steps')} | {fmt('precision', 3)} | "
                f"{fmt('recall', 3)} | {fmt('localized', 3)} | {fmt('time_s', 1)} | "
                f"{v['loss_frac']['pooled']:.4f} [{v['loss_frac']['ci90_lo']:.4f}, {v['loss_frac']['ci90_hi']:.4f}] | "
                f"{fmt('lost_gb', 2)} | {fmt('n_probe')}/{fmt('n_mirror')}/{fmt('n_drain')} |"
            )
    table_md = "\n".join(lines) + "\n"
    with open(os.path.join(outdir, "tb_table.md"), "w") as fp:
        fp.write(table_md)
    return table_md


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--indir", default=".", help="directory containing tb_<scenario>.json (default: .)")
    ap.add_argument("--outdir", help="directory for tb_summary.json and tb_table.md (default: --indir)")
    args = ap.parse_args()
    outdir = args.outdir if args.outdir is not None else args.indir
    print(summarize_dir(args.indir, outdir), end="")


if __name__ == "__main__":
    main()
