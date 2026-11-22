"""Generate all publication-grade vector PDF figures for the FIVES SIGCOMM paper."""

import json
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np


REPO_ROOT = "/usr/local/google/home/rahulbothra/faultference"
RESULTS_JSON = os.path.join(REPO_ROOT, "results", "sigcomm_results.json")
ABL_JSON = os.path.join(REPO_ROOT, "results", "component_ablation.json")
EXT_JSON = os.path.join(REPO_ROOT, "results", "extensions_results.json")
FIG_DIR = os.path.join(REPO_ROOT, "paper", "figures")

COL_FIVES = "#1B7837"
COL_OP = "#2166AC"
COL_NP_LOC = "#D95F02"
COL_NP_MIT = "#7570B3"
COL_RND = "#B2182B"


def _setup_style() -> None:
    plt.rcParams.update({
        "font.family": "C059",
        "font.size": 9.5,
        "axes.labelsize": 9.5,
        "axes.titlesize": 10.0,
        "legend.fontsize": 8.0,
        "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })


def gen_fig2_equivalence() -> None:
    """Figure 2: Observational equivalence in (a) symmetric Clos pod vs (b) replicated Microservices."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.0, 2.05), dpi=300)

    # Panel (a): Symmetric Clos
    ax1.set_xlim(0, 10)
    ax1.set_ylim(0, 6)
    ax1.axis("off")
    ax1.set_title("(a) Symmetric Network Fabric (ECMP / DLB)", fontweight="bold", pad=4)

    src_pos = (1.1, 3.0)
    dst_pos = (8.9, 3.0)
    aggs_l = [(3.3, 4.7), (3.3, 3.0), (3.3, 1.3)]
    cores = [(5.0, 5.0), (5.0, 3.7), (5.0, 2.3), (5.0, 1.0)]
    aggs_r = [(6.7, 4.7), (6.7, 3.0), (6.7, 1.3)]

    for ax_p in aggs_l:
        ax1.plot([src_pos[0], ax_p[0]], [src_pos[1], ax_p[1]], color="#444444", lw=1.2, zorder=1)
        for cp in cores:
            ax1.plot([ax_p[0], cp[0]], [ax_p[1], cp[1]], color="#777777", lw=0.8, zorder=1)
    for cp in cores:
        for ar_p in aggs_r:
            ax1.plot([cp[0], ar_p[0]], [cp[1], ar_p[1]], color="#777777", lw=0.8, zorder=1)
    for ar_p in aggs_r:
        ax1.plot([ar_p[0], dst_pos[0]], [ar_p[1], dst_pos[1]], color="#444444", lw=1.2, zorder=1)

    # Shaded equivalence box
    eq_rect = mpatches.FancyBboxPatch(
        (2.65, 0.56), 4.7, 4.98, boxstyle="round,pad=0.10",
        facecolor="#DED1FF", edgecolor="#4A3580", lw=1.1, ls="--", alpha=0.55, zorder=0
    )
    ax1.add_patch(eq_rect)
    ax1.text(5.0, 0.02, "Observational Equivalence Set (34\u2013115 switches)",
             ha="center", va="bottom", fontsize=7.9, fontweight="bold", color="#2B1B54")

    for p, lbl in [(src_pos, "ToR\nsrc"), (dst_pos, "ToR\ndst")]:
        c = mpatches.Circle(p, 0.48, facecolor="#D9EAD3", edgecolor="black", lw=1.2, zorder=3)
        ax1.add_patch(c)
        ax1.text(p[0], p[1], lbl, ha="center", va="center", fontsize=7.2, fontweight="bold", zorder=4)

    for grp in (aggs_l, cores, aggs_r):
        for idx, p in enumerate(grp):
            is_fault = (grp is cores and idx == 1)
            fc = "#F4CCCC" if is_fault else "#FFF2CC"
            ec = "#A61C1C" if is_fault else "#333333"
            c = mpatches.Circle(p, 0.36, facecolor=fc, edgecolor=ec, lw=1.3 if is_fault else 1.0, zorder=3)
            ax1.add_patch(c)
            ax1.text(p[0], p[1], "?" if not is_fault else "?", ha="center", va="center",
                     fontsize=8.5, fontweight="bold", color=ec, zorder=4)

    # Panel (b): Replicated Microservices
    ax2.set_xlim(0, 10)
    ax2.set_ylim(0, 6)
    ax2.axis("off")
    ax2.set_title("(b) Replicated Microservice Stack", fontweight="bold", pad=4)

    cli_pos = (0.9, 3.0)
    tiers = [
        [(2.9, 4.2), (2.9, 1.8)],
        [(5.3, 4.7), (5.3, 3.0), (5.3, 1.3)],
        [(8.0, 4.9), (8.0, 3.7), (8.0, 2.2), (8.0, 1.0)],
    ]
    tier_lbls = [
        ["core-1", "core-2"],
        ["reg-1", "reg-2", "reg-3"],
        ["redis-P", "redis-R", "pg-P", "pg-R"],
    ]
    eq_rect2 = mpatches.FancyBboxPatch(
        (2.05, 0.56), 6.85, 4.98, boxstyle="round,pad=0.10",
        facecolor="#DED1FF", edgecolor="#4A3580", lw=1.1, ls="--", alpha=0.55, zorder=0
    )
    ax2.add_patch(eq_rect2)
    ax2.text(5.5, 0.02, "Observational Equivalence Set (9 replicas across 4 tiers)",
             ha="center", va="bottom", fontsize=7.9, fontweight="bold", color="#2B1B54")

    c_cli = mpatches.FancyBboxPatch(
        (0.3, 2.4), 1.15, 1.2, boxstyle="round,pad=0.06",
        facecolor="#D9EAD3", edgecolor="black", lw=1.2, zorder=3
    )
    ax2.add_patch(c_cli)
    ax2.text(0.88, 3.0, "Client\np99↑", ha="center", va="center", fontsize=7.4, fontweight="bold", zorder=4)

    for p in tiers[0]:
        ax2.plot([1.45, p[0] - 0.65], [3.0, p[1]], color="#444444", lw=1.1, zorder=1)
    for p1 in tiers[0]:
        for p2 in tiers[1]:
            ax2.plot([p1[0] + 0.65, p2[0] - 0.65], [p1[1], p2[1]], color="#777777", lw=0.85, zorder=1)
    for p2 in tiers[1]:
        for p3 in tiers[2]:
            ax2.plot([p2[0] + 0.65, p3[0] - 0.72], [p2[1], p3[1]], color="#777777", lw=0.85, zorder=1)

    for t_idx, (grp, lbls) in enumerate(zip(tiers, tier_lbls)):
        for idx, (p, nm) in enumerate(zip(grp, lbls)):
            is_fault = (nm == "redis-R")
            fc = "#F4CCCC" if is_fault else "#FFF2CC"
            ec = "#A61C1C" if is_fault else "#333333"
            box = mpatches.FancyBboxPatch(
                (p[0] - 0.78, p[1] - 0.36), 1.56, 0.72, boxstyle="round,pad=0.05",
                facecolor=fc, edgecolor=ec, lw=1.25 if is_fault else 0.95, zorder=3
            )
            ax2.add_patch(box)
            ax2.text(p[0], p[1], f"{nm} ?", ha="center", va="center", fontsize=6.9, fontweight="bold", color=ec, zorder=4)

    fig.tight_layout(pad=0.4)
    fig.savefig(os.path.join(FIG_DIR, "fig2-equivalence.pdf"))
    plt.close(fig)


def gen_fig3_clos_scaling(topo: dict) -> None:
    """Figure 3: Clos scaling (k=10..20, 250..2,000 servers) across Steps, TTL, Disruption, and F1."""
    ks = [10, 12, 14, 16, 18, 20]
    hosts = [k * k * k // 4 for k in ks]

    fig, axes = plt.subplots(1, 4, figsize=(7.2, 1.80), dpi=300)
    schemes = [
        ("FIVES", "FIVES", COL_FIVES, "o", "-"),
        ("Operator", "Operator", COL_OP, "s", "--"),
        ("NetPilot-Loc", "NetPilot", COL_NP_LOC, "^", "-."),
        ("NetPilot-Mitig", "NetPilot (mitigate)", COL_NP_MIT, "d", ":"),
    ]

    for key, label, col, mk, ls in schemes:
        steps = [topo[f"Clos-k{k}"][key]["mean_steps"] for k in ks]
        ttls = [topo[f"Clos-k{k}"][key]["mean_ttl_sec"] for k in ks]
        dis = [topo[f"Clos-k{k}"][key]["mean_disruption"] for k in ks]
        f1s = []
        for k in ks:
            p = topo[f"Clos-k{k}"][key]["mean_precision"]
            r = topo[f"Clos-k{k}"][key]["mean_recall"]
            f1s.append((2 * p * r / (p + r)) if (p + r) > 0 else 0.0)

        axes[0].plot(hosts, steps, label=label, color=col, marker=mk, ls=ls, lw=1.6, markersize=4.2)
        axes[1].plot(hosts, ttls, label=label, color=col, marker=mk, ls=ls, lw=1.6, markersize=4.2)
        axes[2].plot(hosts, dis, label=label, color=col, marker=mk, ls=ls, lw=1.6, markersize=4.2)
        axes[3].plot(hosts, f1s, label=label, color=col, marker=mk, ls=ls, lw=1.6, markersize=4.2)

    axes[0].set_title("(a) Perturbations")
    axes[0].set_ylabel("Mean Steps")
    axes[1].set_title("(b) Localization Time")
    axes[1].set_ylabel("TTL (s, log)")
    axes[1].set_yscale("log")
    axes[2].set_title("(c) Live Disruption")
    axes[2].set_ylabel("Disruption (log)")
    axes[2].set_yscale("log")
    axes[3].set_title("(d) Accuracy (F1)")
    axes[3].set_ylabel("F1 Score")
    axes[3].set_ylim(0.0, 1.08)

    for ax in axes:
        ax.set_xlabel("Servers (k=10..20)")
        ax.set_xticks([250, 1000, 2000])
        ax.grid(True, alpha=0.3)

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=4, frameon=True, bbox_to_anchor=(0.5, 1.05), fontsize=8.0)
    fig.tight_layout(rect=[0, 0, 1, 0.91], pad=0.35)
    fig.savefig(os.path.join(FIG_DIR, "fig3-clos-scaling.pdf"), bbox_inches="tight")
    plt.close(fig)


def gen_fig4_cross_domain(topo: dict) -> None:
    """Figure 4: Expanders, WANs (B4, USCarrier, Kdl), and PROD (1,715 nodes)."""
    names = ["Expander-k10", "Expander-k20", "B4", "USCarrier", "Kdl", "PROD"]
    disp = ["Exp-k10", "Exp-k20", "B4", "USCarrier", "Kdl", "Prod"]
    x = np.arange(len(names))
    w = 0.25

    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(7.2, 1.86), dpi=300)
    bars = [
        ("FIVES", "FIVES", COL_FIVES),
        ("Operator", "Operator", COL_OP),
        ("NetPilot-Loc", "NetPilot", COL_NP_LOC),
    ]
    for idx, (key, lbl, col) in enumerate(bars):
        dis = [topo[n][key]["mean_disruption"] for n in names]
        ttl = [topo[n][key]["mean_ttl_sec"] for n in names]
        f1 = []
        for n in names:
            p = topo[n][key]["mean_precision"]
            r = topo[n][key]["mean_recall"]
            f1.append((2 * p * r / (p + r)) if (p + r) > 0 else 0.0)
        ax1.bar(x + (idx - 1) * w, dis, width=w, label=lbl, color=col, edgecolor="black", lw=0.5)
        ax2.bar(x + (idx - 1) * w, ttl, width=w, label=lbl, color=col, edgecolor="black", lw=0.5)
        ax3.bar(x + (idx - 1) * w, f1, width=w, label=lbl, color=col, edgecolor="black", lw=0.5)

    ax1.set_title("(a) Live Disruption")
    ax1.set_ylabel("Disruption (log)")
    ax1.set_yscale("log")
    ax2.set_title("(b) Wall-Clock TTL")
    ax2.set_ylabel("TTL (s, log)")
    ax2.set_yscale("log")
    ax2.set_yticks([100, 1000])
    ax3.set_title("(c) Accuracy (F1)")
    ax3.set_ylabel("F1 Score")
    ax3.set_ylim(0, 1.08)

    for ax in (ax1, ax2, ax3):
        ax.set_xticks(x)
        ax.set_xticklabels(disp, rotation=22, ha="right")
        ax.grid(True, axis="y", alpha=0.3)

    handles, labels = ax1.get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3, frameon=True, bbox_to_anchor=(0.5, 1.05), fontsize=8.0)
    fig.tight_layout(rect=[0, 0, 1, 0.91], pad=0.35)
    fig.savefig(os.path.join(FIG_DIR, "fig4-cross-domain.pdf"), bbox_inches="tight")
    plt.close(fig)


def gen_fig5_multiflow_intermittent(abl: dict, ext: dict) -> None:
    """Figure 5: (a) Correlated flows, (b) Intermittent duty cycle, (c) Simultaneous 2-faults, (d) Parallel batches."""
    fig, axes = plt.subplots(1, 4, figsize=(7.2, 1.76), dpi=300)

    # (a) Multi-flow correlation
    pairs = [1, 2, 4]
    mf_ttl = [abl["multi_flow"][f"pairs={p}"]["mean_ttl_sec"] for p in pairs]
    axes[0].plot(pairs, mf_ttl, color=COL_FIVES, marker="o", lw=1.7)
    axes[0].set_xticks(pairs)
    axes[0].set_xlabel("Correlated Flow Pairs")
    axes[0].set_ylabel("FIVES TTL (s)")
    axes[0].set_title("(a) Correlated Flows")
    axes[0].grid(True, alpha=0.3)

    # (b) Intermittent duty cycle
    duties = [0.40, 0.70, 1.00]
    f_rec = [abl["intermittent"][f"duty={d:.2f}"]["FIVES"]["mean_recall"] for d in duties]
    o_rec = [abl["intermittent"][f"duty={d:.2f}"]["Operator"]["mean_recall"] for d in duties]
    f_prc = [abl["intermittent"][f"duty={d:.2f}"]["FIVES"]["mean_precision"] for d in duties]
    o_prc = [abl["intermittent"][f"duty={d:.2f}"]["Operator"]["mean_precision"] for d in duties]
    f_f1 = [(2 * p * r / (p + r)) if (p + r) > 0 else 0.0 for p, r in zip(f_prc, f_rec)]
    o_f1 = [(2 * p * r / (p + r)) if (p + r) > 0 else 0.0 for p, r in zip(o_prc, o_rec)]
    axes[1].plot([int(d * 100) for d in duties], f_f1, color=COL_FIVES, marker="o", lw=1.7, label="FIVES")
    axes[1].plot([int(d * 100) for d in duties], o_f1, color=COL_OP, marker="s", ls="--", lw=1.7, label="Operator")
    axes[1].set_xticks([40, 70, 100])
    axes[1].set_xlabel("Fault Duty Cycle (%)")
    axes[1].set_ylabel("F1 Score")
    axes[1].set_ylim(0.0, 1.08)
    axes[1].set_title("(b) Intermittent Drops")
    axes[1].legend(frameon=True, fontsize=6.8, loc="lower right")
    axes[1].grid(True, alpha=0.3)

    # (c) Simultaneous 2-faults (Recall & Exact Pair %)
    tf = ext["two_faults"]
    x2 = np.arange(2)
    f_vals = [tf["FIVES"]["recall"] * 100.0, tf["FIVES"]["exact_pair"] * 100.0]
    o_vals = [tf["Operator"]["recall"] * 100.0, tf["Operator"]["exact_pair"] * 100.0]
    axes[2].bar(x2 - 0.16, f_vals, width=0.32, color=COL_FIVES, edgecolor="black", lw=0.6, label="FIVES")
    axes[2].bar(x2 + 0.16, o_vals, width=0.32, color=COL_OP, edgecolor="black", lw=0.6, label="Operator")
    axes[2].set_xticks(x2)
    axes[2].set_xticklabels(["Recall", "Exact Pair"])
    axes[2].set_ylabel("Accuracy (%)")
    axes[2].set_ylim(0, 112)
    axes[2].set_title("(c) Simultaneous Faults")
    axes[2].legend(frameon=True, fontsize=6.8, loc="upper right")
    axes[2].grid(True, axis="y", alpha=0.3)

    # (d) Parallel non-conflating batching (B = 1, 2, 4)
    bszs = [1, 2, 4]
    par = ext["parallel"]
    c10_ttl = [par["Clos-k10"][f"B={b}"]["ttl"] / par["Clos-k10"]["B=1"]["ttl"] for b in bszs]
    exp_ttl = [par["Expander-k20"][f"B={b}"]["ttl"] / par["Expander-k20"]["B=1"]["ttl"] for b in bszs]
    usc_ttl = [par["USCarrier"][f"B={b}"]["ttl"] / par["USCarrier"]["B=1"]["ttl"] for b in bszs]
    axes[3].plot(bszs, c10_ttl, color=COL_FIVES, marker="o", lw=1.6, label="Clos k=10")
    axes[3].plot(bszs, exp_ttl, color="#4A3580", marker="^", ls="--", lw=1.6, label="Exp k=20")
    axes[3].plot(bszs, usc_ttl, color=COL_NP_LOC, marker="s", ls="-.", lw=1.6, label="USCarrier")
    axes[3].set_xticks(bszs)
    axes[3].set_xlabel("Batch Size (B)")
    axes[3].set_ylabel("Relative TTL")
    axes[3].set_ylim(0.35, 1.08)
    axes[3].set_title("(d) Parallel Batches")
    axes[3].legend(frameon=True, fontsize=6.5, loc="upper right")
    axes[3].grid(True, alpha=0.3)

    fig.tight_layout(pad=0.35)
    fig.savefig(os.path.join(FIG_DIR, "fig5-multiflow-intermittent.pdf"))
    plt.close(fig)


def gen_fig6_opt_subtle_pareto(abl: dict) -> None:
    """Figure 6: (a) OPT vs k-lookahead, (b) Subtle weight shifts under DLB, (c) Cost-noise, (d) Pareto lambda."""
    fig, axes = plt.subplots(1, 4, figsize=(7.2, 1.76), dpi=300)

    # (a) OPT vs k=1,2,3
    tags = ["OPT", "k=1", "k=2", "k=3"]
    vals = [abl["optimal_vs_lookahead"][t] for t in tags]
    cols = ["#4A3580", COL_FIVES, "#5AAE61", "#A6DBA0"]
    axes[0].bar(tags, vals, color=cols, edgecolor="black", lw=0.6, width=0.58)
    axes[0].set_title("(a) vs. Optimal (B4)")
    axes[0].set_ylabel("Expected Cost")
    axes[0].set_ylim(0, max(vals) * 1.25)
    axes[0].grid(True, axis="y", alpha=0.3)

    # (b) Subtle vs Hard under DLB
    s_pk = abl["subtle_dlb"]["Subtle+Hard"]["mean_peak_disruption"]
    h_pk = abl["subtle_dlb"]["HardOnly"]["mean_peak_disruption"]
    s_tot = abl["subtle_dlb"]["Subtle+Hard"]["mean_disruption"]
    h_tot = abl["subtle_dlb"]["HardOnly"]["mean_disruption"]
    xb = np.arange(2)
    axes[1].bar(xb - 0.16, [s_pk, s_tot], width=0.32, color=COL_FIVES, edgecolor="black", lw=0.6, label="With shifts")
    axes[1].bar(xb + 0.16, [h_pk, h_tot], width=0.32, color=COL_NP_LOC, edgecolor="black", lw=0.6, label="Drains only")
    axes[1].set_xticks(xb)
    axes[1].set_xticklabels(["Peak", "Total"])
    axes[1].set_title("(b) Weight Shifts (DLB)")
    axes[1].set_ylabel("Disruption")
    axes[1].legend(frameon=True, fontsize=6.8)
    axes[1].grid(True, axis="y", alpha=0.3)

    # (c) Cost estimation noise sigma
    sigmas = [0.0, 0.25, 0.50, 1.00]
    n_dis = [abl["cost_noise_sensitivity"][f"sigma={s:.2f}"]["mean_disruption"] for s in sigmas]
    axes[2].plot(sigmas, n_dis, color=COL_FIVES, marker="o", lw=1.7)
    axes[2].set_title("(c) Cost Noise")
    axes[2].set_xlabel("Cost Error ($\\sigma$)")
    axes[2].set_ylabel("Mean Disruption")
    axes[2].set_ylim(0, max(n_dis) * 1.35)
    axes[2].grid(True, alpha=0.3)

    # (d) Disruption vs TTL tradeoff lambda
    lams = [0.0, 0.25, 0.50, 0.75, 1.0]
    p_ttl = [abl["pareto_lambda"][f"lambda={l:.2f}"]["mean_ttl_sec"] for l in lams]
    p_dis = [abl["pareto_lambda"][f"lambda={l:.2f}"]["mean_disruption"] for l in lams]
    axes[3].plot(p_ttl, p_dis, color="#4A3580", marker="D", lw=1.6, markersize=4.5)
    axes[3].set_xlim(min(p_ttl) * 0.85, max(p_ttl) * 1.18)
    axes[3].set_ylim(0.0, max(p_dis) * 1.22)
    axes[3].annotate("$\\lambda$=0.0", (p_ttl[0], p_dis[0]), textcoords="offset points", xytext=(6, -2), fontsize=6.8)
    axes[3].annotate("$\\lambda$=0.5", (p_ttl[2], p_dis[2]), textcoords="offset points", xytext=(6, 2), fontsize=6.8)
    axes[3].annotate("$\\lambda$=1.0", (p_ttl[4], p_dis[4]), textcoords="offset points", xytext=(-28, 6), fontsize=6.8)
    axes[3].set_title("(d) Disruption\u2013Time")
    axes[3].set_xlabel("TTL (s)")
    axes[3].set_ylabel("Disruption")
    axes[3].grid(True, alpha=0.3)

    fig.tight_layout(pad=0.35)
    fig.savefig(os.path.join(FIG_DIR, "fig6-deep-dives.pdf"))
    plt.close(fig)


def gen_fig7_microservices_and_factorized(abl: dict, comp_abl: dict) -> None:
    """Figure 7: (a) Factorized Menu x Inference x Sequencer on Clos k=14, (b) Microservices Generality."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.0, 1.86), dpi=300)

    c14 = comp_abl["Clos-k14"]
    rows = [
        ("Operator (Trad + Pass/Fail)", "Operator", COL_OP),
        ("Operator + Bayesian (Trad)", "Operator + Bayes", "#67A9CF"),
        ("NetPilot-Loc + Bayesian", "NetPilot + Bayes", COL_NP_LOC),
        ("FIVES (Trad Menu Only)", "FIVES (coarse)", "#7FBC41"),
        ("FIVES (Full Menu)", "FIVES", COL_FIVES),
    ]
    y_pos = np.arange(len(rows))
    dis_v = [c14[k]["mean_disruption"] for k, _, _ in rows]
    rec_v = [c14[k]["mean_recall"] for k, _, _ in rows]
    cols_v = [c for _, _, c in rows]
    ax1.barh(y_pos, dis_v, color=cols_v, edgecolor="black", lw=0.55, height=0.6)
    for yp, dv, rv in zip(y_pos, dis_v, rec_v):
        ax1.text(dv * 1.08, yp, f"R={int(round(rv*100))}%", va="center", fontsize=6.8)
    ax1.set_xlim(1.0, max(dis_v) * 2.1)
    ax1.set_yticks(y_pos)
    ax1.set_yticklabels([lbl for _, lbl, _ in rows])
    ax1.set_xscale("log")
    ax1.set_xlabel("Live Disruption on Clos k=14 (log)")
    ax1.set_title("(a) Factorized Component Ablation")
    ax1.grid(True, axis="x", alpha=0.3)

    ms = abl["microservices"]
    ms_comp = comp_abl["Microservices"]
    m_entries = [
        ("FIVES", ms["FIVES"]["mean_disruption"], ms["FIVES"]["mean_steps"], ms["FIVES"]["mean_recall"], COL_FIVES),
        ("Op+Bayes", ms_comp["Operator + Bayesian (Trad)"]["mean_disruption"], ms_comp["Operator + Bayesian (Trad)"]["mean_steps"], ms_comp["Operator + Bayesian (Trad)"]["mean_recall"], "#67A9CF"),
        ("NetPilot", ms["NetPilot-Loc"]["mean_disruption"], ms["NetPilot-Loc"]["mean_steps"], ms["NetPilot-Loc"]["mean_recall"], COL_NP_LOC),
        ("Operator", ms["Operator"]["mean_disruption"], ms["Operator"]["mean_steps"], ms["Operator"]["mean_recall"], COL_OP),
    ]
    ym = np.arange(len(m_entries))[::-1]
    m_dis = [e[1] for e in m_entries]
    m_stp = [e[2] for e in m_entries]
    m_rec = [e[3] for e in m_entries]
    m_col = [e[4] for e in m_entries]
    ax2.barh(ym, m_dis, color=m_col, edgecolor="black", lw=0.55, height=0.6)
    for yp, dv, sv, rv in zip(ym, m_dis, m_stp, m_rec):
        ax2.text(dv * 1.15, yp, f"{sv:.1f} stp ({int(round(rv*100))}%)", va="center", fontsize=6.4)
    ax2.set_xlim(0.1, max(m_dis) * 18.0)
    ax2.set_yticks(ym)
    ax2.set_yticklabels([e[0] for e in m_entries])
    ax2.set_xscale("log")
    ax2.set_xticks([0.1, 1, 10, 100])
    ax2.set_xlabel("Live Disruption on Microservices (log)")
    ax2.set_title("(b) 9-Component Microservice Stack")
    ax2.grid(True, axis="x", alpha=0.3)

    fig.tight_layout(pad=0.4)
    fig.savefig(os.path.join(FIG_DIR, "fig7-ablation-microservices.pdf"))
    plt.close(fig)


def main() -> None:
    os.makedirs(FIG_DIR, exist_ok=True)
    _setup_style()
    data = json.load(open(RESULTS_JSON))
    comp = json.load(open(ABL_JSON))
    ext = json.load(open(EXT_JSON))
    gen_fig2_equivalence()
    gen_fig3_clos_scaling(data["topologies"])
    gen_fig4_cross_domain(data["topologies"])
    gen_fig5_multiflow_intermittent(data["ablations"], ext)
    gen_fig6_opt_subtle_pareto(data["ablations"])
    gen_fig7_microservices_and_factorized(data["ablations"], comp)
    print("Generated all vector PDF figures in:", FIG_DIR)


if __name__ == "__main__":
    main()
