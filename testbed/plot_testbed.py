"""Generate publication-ready FIVES Arista testbed plots (PDF + PNG) from `tb_summary.json`.

Matches the thesis figure style (`fives_style.py`: Century Schoolbook / C059 serif, Type 42 vector PDF,
#E69F00 / #C8442E / #4E79A7 palette, 90% normal CI error bars, >= 9pt labels, cap-free top legend) with
zero machine-local paths.

Outputs in `<outdir>`:
  - `testbed-steps.{pdf,png}`: # Perturbations across Black hole / Silent drop / High latency
  - `testbed-time.{pdf,png}`:  Localization time (s) across the 3 scenarios
  - `testbed-loss.{pdf,png}`:  Traffic lost during localization (GB) across the 3 scenarios

Usage:
  python3 plot_testbed.py [--summary out/tb_summary.json] [--outdir out]
"""
import argparse
import json
import os

import matplotlib

matplotlib.use("Agg")
from matplotlib.patches import Patch  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

FIGSIZE = (3.6, 2.4)

SCENARIOS = [
    ("blackhole", "Black hole"),
    ("silent_drop", "Silent drop"),
    ("high_latency", "High latency"),
]

SERIES = [
    ("FIVES", "FIVES", "#E69F00", None),
    ("Operator-PA", "Operator", "#C8442E", None),
    ("Drain-Sweep", "Drain-Sweep", "#4E79A7", "////"),
]

BAR_ERR_KW = dict(elinewidth=0.75, capsize=2.2, capthick=0.75, ecolor="#222222")


def configure_style() -> None:
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Liberation Serif", "DejaVu Serif"],
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "font.size": 10.0,
        "axes.labelsize": 10.0,
        "xtick.labelsize": 9.5,
        "ytick.labelsize": 9.5,
        "legend.fontsize": 9.0,
        "axes.linewidth": 0.6,
        "axes.edgecolor": "#333333",
        "axes.labelcolor": "#111111",
        "xtick.color": "#222222",
        "ytick.color": "#222222",
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "xtick.major.size": 3.0,
        "ytick.major.size": 3.0,
        "xtick.direction": "out",
        "ytick.direction": "out",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "grid.color": "#d9d9d9",
        "grid.linewidth": 0.5,
        "axes.axisbelow": True,
        "legend.frameon": False,
        "figure.constrained_layout.use": True,
        "figure.constrained_layout.h_pad": 0.03,
        "figure.constrained_layout.w_pad": 0.03,
    })


def add_top_legend(fig) -> None:
    handles = [
        Patch(facecolor=color, edgecolor="#333333", linewidth=0.45, hatch=hatch, label=label)
        for _, label, color, hatch in SERIES
    ]
    fig.legend(
        handles=handles,
        labels=[label for _, label, _, _ in SERIES],
        loc="outside upper center",
        ncol=len(SERIES),
        handlelength=1.15,
        handletextpad=0.35,
        columnspacing=0.75,
        borderaxespad=0.15,
    )


def save_fig(fig, out_prefix: str) -> None:
    fig.savefig(out_prefix + ".pdf")
    fig.savefig(out_prefix + ".png", dpi=200)
    plt.close(fig)


def plot_grouped_bars(summary: dict, metric: str, ylabel: str, out_prefix: str, symlog: bool = False) -> None:
    fig, ax = plt.subplots(figsize=FIGSIZE)
    x = np.arange(len(SCENARIOS))
    width = 0.25
    n_s = len(SERIES)

    max_top = 0.0
    for idx, (key, label, color, hatch) in enumerate(SERIES):
        means = [float(summary[scen][key][metric]["mean"]) for scen, _ in SCENARIOS]
        cis = [float(summary[scen][key][metric]["ci90"]) for scen, _ in SCENARIOS]
        offsets = x + (idx - (n_s - 1) / 2.0) * width
        ax.bar(
            offsets,
            means,
            width * 0.92,
            yerr=cis,
            color=color,
            edgecolor="#333333",
            linewidth=0.45,
            hatch=hatch,
            label=label,
            error_kw=BAR_ERR_KW,
            zorder=2,
        )
        for xi, m_val, ci_val in zip(offsets, means, cis):
            max_top = max(max_top, m_val + ci_val)
            if symlog and m_val <= 1.0e-6:
                ax.text(xi, 0.06, "0", ha="center", va="bottom", fontsize=9.0, color="#222222", zorder=3)

    ax.set_xticks(x)
    ax.set_xticklabels([disp for _, disp in SCENARIOS])
    ax.tick_params(axis="x", length=0, pad=4)
    ax.set_ylabel(ylabel)

    if symlog:
        ax.set_yscale("symlog", linthresh=1.0)
        ax.set_ylim(0.0, max(160.0, max_top * 1.30))
        ax.set_yticks([0, 1, 3, 10, 30, 100])
        ax.set_yticklabels(["0", "1", "3", "10", "30", "100"])
        ax.minorticks_off()
    else:
        ax.set_ylim(0.0, max_top * 1.12)

    add_top_legend(fig)
    save_fig(fig, out_prefix)


def plot_all(summary_path: str, outdir: str) -> None:
    configure_style()
    os.makedirs(outdir, exist_ok=True)
    with open(summary_path) as f:
        summary = json.load(f)

    plot_grouped_bars(summary, "steps", "# Perturbations", os.path.join(outdir, "testbed-steps"))
    plot_grouped_bars(summary, "time_s", "Localization time (s)", os.path.join(outdir, "testbed-time"))
    plot_grouped_bars(summary, "lost_gb", "Traffic lost (GB)", os.path.join(outdir, "testbed-loss"), symlog=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--summary", default="tb_summary.json", help="path to tb_summary.json")
    ap.add_argument("--outdir", help="output directory for PDF/PNG plots (default: dirname(--summary))")
    args = ap.parse_args()
    outdir = args.outdir if args.outdir is not None else (os.path.dirname(os.path.abspath(args.summary)) or ".")
    plot_all(args.summary, outdir)
    print(f"wrote {outdir}/testbed-{{steps,time,loss}}.{{pdf,png}}")


if __name__ == "__main__":
    main()
