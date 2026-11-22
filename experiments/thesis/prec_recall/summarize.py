"""Aggregate shard JSONs into a summary JSON: per (topology, scenario, scheme, metric) the mean and
90% CI half-width (normal approximation, 1.645 * sample std / sqrt(n)).

Rows of the same (topology, scenario, trial) from several shard directories are merged, so schemes run
in separate sweeps (e.g. FIVES/Operator in shards/, Operator-PA in shards_pa/) share one summary.
The faults are identical across sweeps because they are seeded by (topology, scenario, trial).

Usage: summarize.py --shard_dirs shards [shards_pa ...] --out pr_summary.json
"""
import argparse
import glob
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
METRICS = ["precision", "recall", "localized", "steps", "final", "eq0", "cost", "wall_s"]
SCHEMES = ("FIVES", "Operator", "Operator-PA")
Z90 = 1.6448536269514722


def load_rows(shard_dirs):
    merged = {}
    for d in shard_dirs:
        files = sorted(glob.glob(os.path.join(HERE, d, "shard_*.json")))
        assert len(files) > 0, f"no shards in {d}"
        for f in files:
            # shard_<topo>_<scenario>_<k>.json; topo has no '_', scenario may.
            topo, rest = os.path.basename(f)[len("shard_"):-len(".json")].split("_", 1)
            scen = rest.rsplit("_", 1)[0]
            for r in json.load(open(f)):
                key = (topo, scen, r["trial"])
                if key not in merged:
                    merged[key] = dict(r)
                    continue
                prev = merged[key]
                assert prev["culprit"] == r["culprit"] and prev["pair"] == r["pair"], f"fault mismatch {key}"
                for s in SCHEMES:
                    if s in r:
                        assert s not in prev, f"scheme {s} duplicated for {key}"
                        prev[s] = r[s]
    groups = {}
    for (topo, scen, _), r in merged.items():
        groups.setdefault((topo, scen), []).append(r)
    return groups


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard_dirs", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = {}
    for (topo, scen), rows in sorted(load_rows(args.shard_dirs).items()):
        schemes = [s for s in SCHEMES if s in rows[0]]
        assert all(s in r for r in rows for s in schemes), f"incomplete scheme coverage in {topo} {scen}"
        entry = {"n": len(rows)}
        for scheme in schemes:
            entry[scheme] = {}
            for m in METRICS:
                x = np.array([r[scheme][m] for r in rows], dtype=float)
                se = x.std(ddof=1) / np.sqrt(len(x))
                entry[scheme][m] = {"mean": float(x.mean()), "ci90": float(Z90 * se)}
        out.setdefault(topo, {})[scen] = entry
    json.dump(out, open(os.path.join(HERE, args.out), "w"), indent=1)
    for topo, d in out.items():
        for scen, e in d.items():
            schemes = [s for s in SCHEMES if s in e]
            print(f"{topo:10s} {scen:12s} n={e['n']:3d} | " + " | ".join(
                f"{s}: P={e[s]['precision']['mean']:.3f}±{e[s]['precision']['ci90']:.3f} "
                f"R={e[s]['recall']['mean']:.3f}±{e[s]['recall']['ci90']:.3f} "
                f"loc={e[s]['localized']['mean']:.3f} steps={e[s]['steps']['mean']:.2f}±{e[s]['steps']['ci90']:.2f}"
                for s in schemes))


if __name__ == "__main__":
    main()
