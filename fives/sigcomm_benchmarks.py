"""Full SIGCOMM parallelized evaluation suite & vector PDF plot generator for FIVES."""

import json
import multiprocessing as mp
import os
from typing import Dict, List, Tuple
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from fives import (
    CheapestFirstOperatorPlanner,
    ExactOptimalPlanner,
    FailureMode,
    FailureSpec,
    FivesPlanner,
    MicroserviceSystem,
    MultiOutcomeEfficacyEstimator,
    MultiRoundBayesianPGM,
    NetPilotPlanner,
    RandomSafePlanner,
    SafetyConfig,
    SafetyFilter,
    SetIntersectionInference,
    TwoPhaseImpactEstimator,
    load_campus_prod_system,
    load_edgelist_network,
    run_episode,
)
from fives.experiments import REPO_ROOT, TOPO_DIR, sample_valid_fault, summarize_runs


def _eval_topology_shard(args: Tuple[str, str, int, int, float]) -> Tuple[str, int, int, Dict[str, List[Dict]]]:
    fname, label, t_start, t_end, drop_prob = args
    net = (
        load_campus_prod_system(os.path.join(TOPO_DIR, fname))
        if label == "PROD"
        else load_edgelist_network(os.path.join(TOPO_DIR, fname), name=label)
    )
    safety = SafetyFilter(net)
    impact = TwoPhaseImpactEstimator(net)
    eff = MultiOutcomeEfficacyEstimator(net)

    buckets: Dict[str, List[Dict]] = {
        "FIVES": [],
        "Operator": [],
        "NetPilot-Loc": [],
        "NetPilot-Mitig": [],
        "Random": [],
    }
    base_seed = 31415 + sum(ord(c) * (idx + 1) for idx, c in enumerate(label))
    for t in range(t_start, t_end):
        rng_fault = np.random.default_rng(base_seed + t * 97)
        pairs, culprit = sample_valid_fault(net, rng_fault, num_pairs=1)
        spec = FailureSpec(FailureMode.SILENT_DROP, culprit, pairs, drop_prob=drop_prob)
        seed_ep = 5000 + t

        configs = [
            ("FIVES", FivesPlanner(net, safety, impact, eff, tradeoff_lambda=0.5), MultiRoundBayesianPGM(net), False),
            ("Operator", CheapestFirstOperatorPlanner(net, safety, impact, eff, np.random.default_rng(seed_ep + 1)), SetIntersectionInference(net), False),
            ("NetPilot-Loc", NetPilotPlanner(net, safety, impact), SetIntersectionInference(net), False),
            ("NetPilot-Mitig", NetPilotPlanner(net, safety, impact), SetIntersectionInference(net), True),
            ("Random", RandomSafePlanner(net, safety, np.random.default_rng(seed_ep + 2)), SetIntersectionInference(net), False),
        ]
        for scheme, planner, inf, mitig_stop in configs:
            res = run_episode(
                net, spec, planner, inf, impact, np.random.default_rng(seed_ep),
                stop_on_symptom_mitigation=mitig_stop,
            )
            buckets[scheme].append({
                "steps": res.num_perturbations,
                "ttl": res.total_ttl_sec,
                "disruption": res.total_disruption,
                "peak_disruption": res.peak_step_disruption,
                "precision": res.precision,
                "recall": res.recall,
                "compute_ms": res.total_compute_ms,
                "eq0": res.initial_eq_size,
            })

    n_hosts = max(net.G.number_of_nodes() - len(net.switch_nodes), len(net.rack_nodes))
    return label, n_hosts, len(net.switch_nodes), buckets


def _run_ablation_task(task_name: str, trials: int = 30) -> Tuple[str, Dict]:
    clos_path = os.path.join(TOPO_DIR, "ft_deg10_sw125_svr250_os3_bidir_false.edgelist")

    if task_name == "optimal_vs_lookahead":
        b4 = load_edgelist_network(
            os.path.join(TOPO_DIR, "B4.edgelist"),
            name="B4",
            safety=SafetyConfig(enable_subtle_weight_shifts=False, enable_group_splits=False),
        )
        s_b4, i_b4, e_b4 = SafetyFilter(b4), TwoPhaseImpactEstimator(b4), MultiOutcomeEfficacyEstimator(b4)
        opt_pl = ExactOptimalPlanner(b4, s_b4, i_b4, e_b4, tradeoff_lambda=0.5)
        lookahead_stats: Dict[str, List[float]] = {"OPT": [], "k=1": [], "k=2": [], "k=3": []}
        rng_b4 = np.random.default_rng(77)
        for t in range(trials):
            pairs, culprit = sample_valid_fault(b4, rng_b4, 1)
            spec = FailureSpec(FailureMode.BLACKHOLE, culprit, pairs, drop_prob=1.0, bg_noise_prob=1.0e-6)
            for tag, pl in [
                ("OPT", opt_pl),
                ("k=1", FivesPlanner(b4, s_b4, i_b4, e_b4, tradeoff_lambda=0.5, lookahead_k=1)),
                ("k=2", FivesPlanner(b4, s_b4, i_b4, e_b4, tradeoff_lambda=0.5, lookahead_k=2)),
                ("k=3", FivesPlanner(b4, s_b4, i_b4, e_b4, tradeoff_lambda=0.5, lookahead_k=3)),
            ]:
                res = run_episode(b4, spec, pl, MultiRoundBayesianPGM(b4, bg_noise_prob=1.0e-6), i_b4, np.random.default_rng(900 + t))
                sc = sum(st.impact.scalar_cost(0.5) for st in res.trajectory[1:])
                lookahead_stats[tag].append(sc)
        return task_name, {k: float(np.mean(v)) for k, v in lookahead_stats.items()}

    if task_name == "subtle_dlb":
        all_sw = frozenset(range(125))
        net_sub = load_edgelist_network(
            clos_path, "Clos-DLB-Subtle",
            safety=SafetyConfig(probe_banned_nodes=all_sw, enable_subtle_weight_shifts=True, enable_group_splits=False, enable_component_reset=False),
            dlb_routing=True,
        )
        net_hrd = load_edgelist_network(
            clos_path, "Clos-DLB-Hard",
            safety=SafetyConfig(probe_banned_nodes=all_sw, enable_subtle_weight_shifts=False, enable_group_splits=False, enable_component_reset=False),
            dlb_routing=True,
        )
        sub_runs, hrd_runs = [], []
        rng_dlb = np.random.default_rng(88)
        for t in range(trials):
            pairs, _ = sample_valid_fault(net_sub, rng_dlb, 1)
            cores = sorted({n for p in net_sub.shortest_paths(*pairs[0]) for n in p if n >= 100})
            if len(cores) == 0:
                continue
            culprit = int(cores[int(rng_dlb.integers(0, len(cores)))])
            spec = FailureSpec(FailureMode.SILENT_DROP, culprit, pairs, drop_prob=0.08)
            for net_x, bucket in [(net_sub, sub_runs), (net_hrd, hrd_runs)]:
                imp_x = TwoPhaseImpactEstimator(net_x)
                res = run_episode(
                    net_x, spec,
                    FivesPlanner(net_x, SafetyFilter(net_x), imp_x, MultiOutcomeEfficacyEstimator(net_x), tradeoff_lambda=0.85),
                    MultiRoundBayesianPGM(net_x), imp_x, np.random.default_rng(1200 + t),
                )
                bucket.append({
                    "steps": res.num_perturbations, "ttl": res.total_ttl_sec,
                    "disruption": res.total_disruption, "peak_disruption": res.peak_step_disruption,
                    "precision": res.precision, "recall": res.recall, "compute_ms": res.total_compute_ms,
                })
        return task_name, {"Subtle+Hard": summarize_runs(sub_runs), "HardOnly": summarize_runs(hrd_runs)}

    if task_name == "cost_noise_sensitivity":
        net_c = load_edgelist_network(clos_path, "Clos-k10")
        true_imp = TwoPhaseImpactEstimator(net_c)
        s_c, e_c = SafetyFilter(net_c), MultiOutcomeEfficacyEstimator(net_c)
        noise_res: Dict[str, Dict] = {}
        for sigma in (0.0, 0.25, 0.50, 1.00):
            runs_sig = []
            rng_n = np.random.default_rng(404)
            for t in range(trials):
                pairs, culprit = sample_valid_fault(net_c, rng_n, 1)
                spec = FailureSpec(FailureMode.SILENT_DROP, culprit, pairs, drop_prob=0.03)
                noisy_imp = TwoPhaseImpactEstimator(net_c, noise_sigma=sigma, noise_rng=np.random.default_rng(7000 + t))
                res = run_episode(
                    net_c, spec,
                    FivesPlanner(net_c, s_c, noisy_imp, e_c, tradeoff_lambda=0.5),
                    MultiRoundBayesianPGM(net_c), true_imp, np.random.default_rng(3000 + t),
                )
                runs_sig.append({
                    "steps": res.num_perturbations, "ttl": res.total_ttl_sec,
                    "disruption": res.total_disruption, "peak_disruption": res.peak_step_disruption,
                    "precision": res.precision, "recall": res.recall, "compute_ms": res.total_compute_ms,
                })
            noise_res[f"sigma={sigma:.2f}"] = summarize_runs(runs_sig)
        return task_name, noise_res

    if task_name == "pareto_lambda":
        net_c = load_edgelist_network(clos_path, "Clos-k10")
        true_imp = TwoPhaseImpactEstimator(net_c)
        s_c, e_c = SafetyFilter(net_c), MultiOutcomeEfficacyEstimator(net_c)
        pareto_res: Dict[str, Dict] = {}
        for lam in (0.0, 0.25, 0.50, 0.75, 1.0):
            runs_l = []
            rng_p = np.random.default_rng(505)
            for t in range(trials):
                pairs, culprit = sample_valid_fault(net_c, rng_p, 1)
                spec = FailureSpec(FailureMode.SILENT_DROP, culprit, pairs, drop_prob=0.04)
                res = run_episode(
                    net_c, spec,
                    FivesPlanner(net_c, s_c, true_imp, e_c, tradeoff_lambda=lam),
                    MultiRoundBayesianPGM(net_c), true_imp, np.random.default_rng(4000 + t),
                )
                runs_l.append({
                    "steps": res.num_perturbations, "ttl": res.total_ttl_sec,
                    "disruption": res.total_disruption, "peak_disruption": res.peak_step_disruption,
                    "precision": res.precision, "recall": res.recall, "compute_ms": res.total_compute_ms,
                })
            pareto_res[f"lambda={lam:.2f}"] = summarize_runs(runs_l)
        return task_name, pareto_res

    if task_name == "multi_flow":
        net_c = load_edgelist_network(clos_path, "Clos-k10")
        true_imp = TwoPhaseImpactEstimator(net_c)
        s_c, e_c = SafetyFilter(net_c), MultiOutcomeEfficacyEstimator(net_c)
        mf_res: Dict[str, Dict] = {}
        for npairs in (1, 2, 4):
            runs_mf = []
            rng_mf = np.random.default_rng(606)
            for t in range(trials):
                pairs, culprit = sample_valid_fault(net_c, rng_mf, num_pairs=npairs)
                spec = FailureSpec(FailureMode.SILENT_DROP, culprit, pairs, drop_prob=0.03)
                res = run_episode(
                    net_c, spec, FivesPlanner(net_c, s_c, true_imp, e_c),
                    MultiRoundBayesianPGM(net_c), true_imp, np.random.default_rng(6000 + t),
                )
                runs_mf.append({
                    "steps": res.num_perturbations, "ttl": res.total_ttl_sec,
                    "disruption": res.total_disruption, "peak_disruption": res.peak_step_disruption,
                    "precision": res.precision, "recall": res.recall, "compute_ms": res.total_compute_ms,
                })
            mf_res[f"pairs={npairs}"] = summarize_runs(runs_mf)
        return task_name, mf_res

    if task_name == "intermittent":
        net_c = load_edgelist_network(clos_path, "Clos-k10")
        true_imp = TwoPhaseImpactEstimator(net_c)
        s_c, e_c = SafetyFilter(net_c), MultiOutcomeEfficacyEstimator(net_c)
        int_res: Dict[str, Dict] = {}
        for duty in (0.40, 0.70, 1.00):
            fives_i, op_i = [], []
            rng_i = np.random.default_rng(707)
            for t in range(trials):
                pairs, culprit = sample_valid_fault(net_c, rng_i, 1)
                mode = FailureMode.INTERMITTENT if duty < 1.0 else FailureMode.SILENT_DROP
                spec = FailureSpec(mode, culprit, pairs, drop_prob=0.06, duty_cycle=duty)
                r_f = run_episode(
                    net_c, spec, FivesPlanner(net_c, s_c, true_imp, e_c, allow_repeat_noisy=(duty < 1.0)),
                    MultiRoundBayesianPGM(net_c, duty_cycle_prior=duty), true_imp,
                    np.random.default_rng(8000 + t), max_steps=25, stall_patience=6,
                )
                r_o = run_episode(
                    net_c, spec, CheapestFirstOperatorPlanner(net_c, s_c, true_imp, e_c, np.random.default_rng(8100 + t)),
                    SetIntersectionInference(net_c), true_imp,
                    np.random.default_rng(8000 + t), max_steps=25, stall_patience=6,
                )
                for bkt, rx in [(fives_i, r_f), (op_i, r_o)]:
                    bkt.append({
                        "steps": rx.num_perturbations, "ttl": rx.total_ttl_sec,
                        "disruption": rx.total_disruption, "peak_disruption": rx.peak_step_disruption,
                        "precision": rx.precision, "recall": rx.recall, "compute_ms": rx.total_compute_ms,
                    })
            int_res[f"duty={duty:.2f}"] = {"FIVES": summarize_runs(fives_i), "Operator": summarize_runs(op_i)}
        return task_name, int_res

    if task_name == "microservices":
        ms = MicroserviceSystem()
        s_m, i_m, e_m = SafetyFilter(ms), TwoPhaseImpactEstimator(ms), MultiOutcomeEfficacyEstimator(ms)
        ms_buckets: Dict[str, List[Dict]] = {"FIVES": [], "Operator": [], "NetPilot-Loc": [], "Random": []}
        for comp in range(1, 10):
            for rep in range(4):
                spec = FailureSpec(
                    FailureMode.HIGH_LATENCY, comp, ((0, 10),), drop_prob=0.12,
                    latency_inflation_us=1000.0, latency_jitter_us=10.0, latency_threshold_us=37.19,
                )
                seed_m = 9500 + comp * 10 + rep
                for lbl, pl, inf in [
                    ("FIVES", FivesPlanner(ms, s_m, i_m, e_m, tradeoff_lambda=0.7), MultiRoundBayesianPGM(ms, excluded_endpoints={0, 10})),
                    ("Operator", CheapestFirstOperatorPlanner(ms, s_m, i_m, e_m, np.random.default_rng(seed_m + 1)), SetIntersectionInference(ms)),
                    ("NetPilot-Loc", NetPilotPlanner(ms, s_m, i_m), SetIntersectionInference(ms)),
                    ("Random", RandomSafePlanner(ms, s_m, np.random.default_rng(seed_m + 2)), SetIntersectionInference(ms)),
                ]:
                    rx = run_episode(ms, spec, pl, inf, i_m, np.random.default_rng(seed_m), candidate_pool=list(range(1, 10)))
                    ms_buckets[lbl].append({
                        "steps": rx.num_perturbations, "ttl": rx.total_ttl_sec,
                        "disruption": rx.total_disruption, "peak_disruption": rx.peak_step_disruption,
                        "precision": rx.precision, "recall": rx.recall, "compute_ms": rx.total_compute_ms,
                    })
        return task_name, {k: summarize_runs(v) for k, v in ms_buckets.items()}

    raise ValueError(f"Unknown ablation task: {task_name}")


def save_plots(topo_res: Dict, abl_res: Dict, plot_dir: str) -> None:
    os.makedirs(plot_dir, exist_ok=True)
    plt.rcParams["font.family"] = "C059"
    plt.rcParams["font.size"] = 10

    ks = [10, 12, 14, 16, 18, 20]
    hosts = [topo_res[f"Clos-k{k}"]["num_endpoints"] for k in ks]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8.2, 3.1), dpi=300)
    styles = [
        ("FIVES", "#15803D", "o", "-"),
        ("Operator", "#1D4ED8", "s", "--"),
        ("NetPilot-Loc", "#B45309", "^", "-."),
        ("Random", "#A31515", "x", ":"),
    ]
    for sch, col, mk, ls in styles:
        ys_ttl = [topo_res[f"Clos-k{k}"][sch]["mean_ttl_sec"] for k in ks]
        ys_dis = [topo_res[f"Clos-k{k}"][sch]["mean_disruption"] for k in ks]
        ax1.plot(hosts, ys_ttl, label=sch, color=col, marker=mk, ls=ls, lw=1.8, markersize=5)
        ax2.plot(hosts, ys_dis, label=sch, color=col, marker=mk, ls=ls, lw=1.8, markersize=5)
    ax1.set_xlabel("Number of Servers (Clos)")
    ax1.set_ylabel("Time-to-Localize (s)")
    ax1.set_yscale("log")
    ax1.grid(True, alpha=0.3)
    ax1.legend(frameon=True, fontsize=8)
    ax2.set_xlabel("Number of Servers (Clos)")
    ax2.set_ylabel("Cumulative Disruption")
    ax2.set_yscale("log")
    ax2.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(plot_dir, "clos_scaling.pdf"))
    plt.close(fig)

    domains = ["B4", "USCarrier", "Kdl", "PROD", "Microservices"]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8.6, 3.2), dpi=300)
    x = np.arange(len(domains))
    w = 0.24
    for idx, (sch, col) in enumerate([("FIVES", "#15803D"), ("Operator", "#1D4ED8"), ("NetPilot-Loc", "#B45309")]):
        dis_vals = [
            (abl_res["microservices"][sch]["mean_disruption"] if d == "Microservices" else topo_res[d][sch]["mean_disruption"])
            for d in domains
        ]
        prec_vals = [
            (abl_res["microservices"][sch]["mean_precision"] if d == "Microservices" else topo_res[d][sch]["mean_precision"])
            for d in domains
        ]
        ax1.bar(x + (idx - 1) * w, dis_vals, width=w, label=sch, color=col, edgecolor="black", lw=0.6)
        ax2.bar(x + (idx - 1) * w, prec_vals, width=w, label=sch, color=col, edgecolor="black", lw=0.6)
    ax1.set_xticks(x)
    ax1.set_xticklabels(domains, rotation=15)
    ax1.set_ylabel("Live Disruption (log)")
    ax1.set_yscale("log")
    ax1.grid(True, axis="y", alpha=0.3)
    ax1.legend(frameon=True, fontsize=8)
    ax2.set_xticks(x)
    ax2.set_xticklabels(domains, rotation=15)
    ax2.set_ylabel("Localization Precision")
    ax2.set_ylim(0, 1.08)
    ax2.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(plot_dir, "cross_domain_summary.pdf"))
    plt.close(fig)


def _dispatch_job(job: Tuple) -> Tuple[str, object]:
    kind = job[0]
    if kind == "topo":
        return ("topo", _eval_topology_shard(job[1]))
    if kind == "abl":
        return ("abl", _run_ablation_task(job[1], job[2]))
    raise ValueError(f"Unknown job kind: {kind}")


def main():
    out_dir = os.path.join(REPO_ROOT, "results")
    os.makedirs(out_dir, exist_ok=True)

    topo_specs = [
        ("ft_deg10_sw125_svr250_os3_bidir_false.edgelist", "Clos-k10", 30, 0.03),
        ("ft_deg12_sw180_svr432_os3_bidir_false.edgelist", "Clos-k12", 30, 0.03),
        ("ft_deg14_sw245_svr686_os3_bidir_false.edgelist", "Clos-k14", 30, 0.03),
        ("ft_deg16_sw320_svr1024_os3_bidir_false.edgelist", "Clos-k16", 25, 0.03),
        ("ft_deg18_sw405_svr1458_os3_bidir_false.edgelist", "Clos-k18", 20, 0.03),
        ("ft_deg20_sw500_svr2000_os3_bidir_false.edgelist", "Clos-k20", 20, 0.03),
        ("rg_deg10_sw125_svr250_os3.edgelist", "Expander-k10", 30, 0.03),
        ("rg_deg16_sw320_svr1024_os3.edgelist", "Expander-k16", 25, 0.03),
        ("rg_deg20_sw500_svr2000_os3.edgelist", "Expander-k20", 20, 0.03),
        ("B4.edgelist", "B4", 30, 0.03),
        ("UsC.edgelist", "USCarrier", 30, 0.03),
        ("Kdl.edgelist", "Kdl", 25, 0.03),
        ("campus-str.edgelist", "PROD", 30, 0.03),
    ]

    shard_size = 5
    all_jobs: List[Tuple] = []
    for fname, lbl, total_t, dp in topo_specs:
        for s in range(0, total_t, shard_size):
            all_jobs.append(("topo", (fname, lbl, s, min(s + shard_size, total_t), dp)))

    ablation_names = [
        "optimal_vs_lookahead",
        "subtle_dlb",
        "cost_noise_sensitivity",
        "pareto_lambda",
        "multi_flow",
        "intermittent",
        "microservices",
    ]
    for nm in ablation_names:
        all_jobs.append(("abl", nm, 30))

    n_workers = min(85, os.cpu_count() or 16)
    print(f"Running {len(all_jobs)} parallel benchmark jobs across {n_workers} workers...", flush=True)

    with mp.Pool(processes=n_workers) as pool:
        raw_outputs = pool.map(_dispatch_job, all_jobs, chunksize=1)

    shard_outputs = [payload for kind, payload in raw_outputs if kind == "topo"]
    abl_outputs = [payload for kind, payload in raw_outputs if kind == "abl"]

    merged_buckets: Dict[str, Dict[str, List[Dict]]] = {}
    meta_counts: Dict[str, Tuple[int, int]] = {}
    for lbl, n_endp, n_comp, bkts in shard_outputs:
        meta_counts[lbl] = (n_endp, n_comp)
        if lbl not in merged_buckets:
            merged_buckets[lbl] = {k: [] for k in bkts}
        for k, lst in bkts.items():
            merged_buckets[lbl][k].extend(lst)

    topo_results: Dict[str, Dict] = {}
    for _, lbl, _, _ in topo_specs:
        bkts = merged_buckets[lbl]
        entry = {k: summarize_runs(v) for k, v in bkts.items()}
        entry["mean_eq0"] = float(np.mean([r["eq0"] for r in bkts["FIVES"]]))
        entry["num_endpoints"] = meta_counts[lbl][0]
        entry["num_components"] = meta_counts[lbl][1]
        topo_results[lbl] = entry
        f = entry["FIVES"]
        np_l = entry["NetPilot-Loc"]
        op = entry["Operator"]
        print(
            f"[{lbl:12s}] eq0={entry['mean_eq0']:5.1f} | "
            f"FIVES: steps={f['mean_steps']:.2f}, TTL={f['mean_ttl_sec']:.1f}s, disrupt={f['mean_disruption']:.2f}, P/R={f['mean_precision']:.2f}/{f['mean_recall']:.2f} | "
            f"Op: steps={op['mean_steps']:.2f}, P/R={op['mean_precision']:.2f}/{op['mean_recall']:.2f} | "
            f"NP-Loc: TTL={np_l['mean_ttl_sec']:.1f}s, disrupt={np_l['mean_disruption']:.2f}",
            flush=True,
        )

    abl_results = {nm: res for nm, res in abl_outputs}
    print("Optimal vs Lookahead:", abl_results["optimal_vs_lookahead"], flush=True)
    print("Subtle DLB:", {k: (v["mean_peak_disruption"], v["mean_disruption"], v["mean_recall"]) for k, v in abl_results["subtle_dlb"].items()}, flush=True)
    print("Microservices:", {k: (v["mean_steps"], v["mean_disruption"], v["mean_precision"], v["mean_recall"]) for k, v in abl_results["microservices"].items()}, flush=True)

    full = {"topologies": topo_results, "ablations": abl_results}
    json_path = os.path.join(out_dir, "sigcomm_results.json")
    with open(json_path, "w") as fp:
        json.dump(full, fp, indent=2)
    save_plots(topo_results, abl_results, os.path.join(out_dir, "plots"))
    print(f"\nSaved complete SIGCOMM results to {json_path} and plots to {out_dir}/plots/", flush=True)


if __name__ == "__main__":
    main()
