"""Comprehensive verification suite for the FIVES simulation & evaluation engine."""

import os
import subprocess
import numpy as np

from fives import (
    ActiveProbe,
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
    TelemetryRecord,
    TelemetryWindow,
    TwoPhaseImpactEstimator,
    load_campus_prod_system,
    load_edgelist_network,
    run_episode,
)

REPO_ROOT = "/usr/local/google/home/rahulbothra/faultference"
TOPO_DIR = os.path.join(REPO_ROOT, "faultference", "topologies")


def _pick_inter_pod_pair_and_core(net, rng: np.random.Generator):
    racks = net.rack_nodes
    for _ in range(200):
        s = int(racks[int(rng.integers(0, len(racks)))])
        d = int(racks[int(rng.integers(0, len(racks)))])
        if s == d:
            continue
        paths = net.shortest_paths(s, d)
        if len(paths) >= 4 and len(paths[0]) >= 3:
            interior = sorted({n for p in paths for n in p[1:-1]})
            if len(interior) >= 4:
                culprit = int(interior[int(rng.integers(0, len(interior)))])
                return (s, d), culprit
    raise AssertionError(f"Could not find multi-path pair in {net.name}")


def test_clos_silent_drop_and_baselines():
    net = load_edgelist_network(
        os.path.join(TOPO_DIR, "ft_deg10_sw125_svr250_os3_bidir_false.edgelist"),
        name="Clos-k10",
    )
    rng = np.random.default_rng(7)
    pair, culprit = _pick_inter_pod_pair_and_core(net, rng)
    spec = FailureSpec(
        mode=FailureMode.SILENT_DROP,
        faulty_node=culprit,
        affected_pairs=(pair,),
        drop_prob=0.03,
        bg_noise_prob=1.0e-4,
    )

    safety = SafetyFilter(net)
    impact = TwoPhaseImpactEstimator(net)
    eff = MultiOutcomeEfficacyEstimator(net)

    fives_res = run_episode(
        net,
        spec,
        FivesPlanner(net, safety, impact, eff, tradeoff_lambda=0.5, lookahead_k=1),
        MultiRoundBayesianPGM(net),
        impact,
        np.random.default_rng(101),
    )
    op_res = run_episode(
        net,
        spec,
        CheapestFirstOperatorPlanner(net, safety, impact, eff, np.random.default_rng(102)),
        SetIntersectionInference(net, path_aware=False),
        impact,
        np.random.default_rng(101),
    )
    np_mitig = run_episode(
        net,
        spec,
        NetPilotPlanner(net, safety, impact),
        SetIntersectionInference(net, path_aware=False),
        impact,
        np.random.default_rng(101),
        stop_on_symptom_mitigation=True,
    )
    np_loc = run_episode(
        net,
        spec,
        NetPilotPlanner(net, safety, impact),
        SetIntersectionInference(net, path_aware=False),
        impact,
        np.random.default_rng(101),
        stop_on_symptom_mitigation=False,
    )
    rnd_res = run_episode(
        net,
        spec,
        RandomSafePlanner(net, safety, np.random.default_rng(103)),
        SetIntersectionInference(net, path_aware=False),
        impact,
        np.random.default_rng(101),
    )

    print(
        f"[Clos-k10 SilentDrop] culprit={culprit} eq0={fives_res.initial_eq_size} | "
        f"FIVES: steps={fives_res.num_perturbations}, TTL={fives_res.total_ttl_sec:.1f}s, "
        f"disrupt={fives_res.total_disruption:.2f}, P/R={fives_res.precision:.2f}/{fives_res.recall:.2f} | "
        f"Operator: steps={op_res.num_perturbations}, TTL={op_res.total_ttl_sec:.1f}s, "
        f"disrupt={op_res.total_disruption:.2f} | "
        f"NetPilot(mitig): eq_end={len(np_mitig.final_eq_set)}, P={np_mitig.precision:.2f} | "
        f"NetPilot(loc): steps={np_loc.num_perturbations}, disrupt={np_loc.total_disruption:.2f} | "
        f"Random: steps={rnd_res.num_perturbations}"
    )
    assert fives_res.recall == 1.0 and fives_res.precision == 1.0
    assert fives_res.num_perturbations < op_res.num_perturbations


def test_exact_optimal_vs_greedy_and_lookahead():
    net = load_edgelist_network(
        os.path.join(TOPO_DIR, "B4.edgelist"),
        name="B4",
        safety=SafetyConfig(enable_subtle_weight_shifts=False),
    )
    safety = SafetyFilter(net)
    impact = TwoPhaseImpactEstimator(net)
    eff = MultiOutcomeEfficacyEstimator(net)

    pair = (0, 11)
    paths = net.shortest_paths(*pair)
    suspects = frozenset(n for p in paths for n in p)
    post = {n: 1.0 / len(suspects) for n in suspects}

    opt_planner = ExactOptimalPlanner(net, safety, impact, eff, tradeoff_lambda=0.5)
    _, opt_cost = opt_planner.compute_optimal_tree_cost(suspects, post, (pair,), expected_drop_prob=1.0)

    # Evaluate empirical average cost over all culprits in `suspects` for Optimal, FIVES(k=1), FIVES(k=2)
    costs = {"OPT": [], "k=1": [], "k=2": []}
    for c in sorted(suspects):
        spec = FailureSpec(FailureMode.BLACKHOLE, c, (pair,), drop_prob=1.0, bg_noise_prob=1.0e-6)
        for tag, pl in [
            ("OPT", opt_planner),
            ("k=1", FivesPlanner(net, safety, impact, eff, tradeoff_lambda=0.5, lookahead_k=1)),
            ("k=2", FivesPlanner(net, safety, impact, eff, tradeoff_lambda=0.5, lookahead_k=2)),
        ]:
            res = run_episode(net, spec, pl, MultiRoundBayesianPGM(net, bg_noise_prob=1.0e-6), impact, np.random.default_rng(42 + c))
            step_c = sum(t.impact.scalar_cost(0.5) for t in res.trajectory[1:])
            costs[tag].append(step_c)
            assert res.recall == 1.0

    m_opt = float(np.mean(costs["OPT"]))
    m_k1 = float(np.mean(costs["k=1"]))
    m_k2 = float(np.mean(costs["k=2"]))
    print(f"[Exact OPT vs Greedy on B4 (|E0|={len(suspects)})] tree_opt={opt_cost:.3f}, emp_OPT={m_opt:.3f}, k=1={m_k1:.3f}, k=2={m_k2:.3f}")
    assert m_opt <= opt_cost + 1.0e-6
    assert m_k1 <= 1.25 * m_opt


def test_subtle_perturbations_and_dlb():
    # Under DLB (per-packet adaptive routing) on switches without active-probe injection support,
    # Subtle WCMP weight shifts + Bayesian PGM localize with dramatically lower peak disruption than hard drains.
    all_sw = frozenset(range(125))
    net_subtle = load_edgelist_network(
        os.path.join(TOPO_DIR, "ft_deg10_sw125_svr250_os3_bidir_false.edgelist"),
        name="Clos-DLB-Subtle",
        safety=SafetyConfig(
            probe_banned_nodes=all_sw,
            enable_subtle_weight_shifts=True,
            enable_component_reset=False,
        ),
        dlb_routing=True,
    )
    net_hard = load_edgelist_network(
        os.path.join(TOPO_DIR, "ft_deg10_sw125_svr250_os3_bidir_false.edgelist"),
        name="Clos-DLB-Hard",
        safety=SafetyConfig(
            probe_banned_nodes=all_sw,
            enable_subtle_weight_shifts=False,
            enable_component_reset=False,
        ),
        dlb_routing=True,
    )
    rng = np.random.default_rng(19)
    pair, _ = _pick_inter_pod_pair_and_core(net_subtle, rng)
    cores_on_path = sorted({n for p in net_subtle.shortest_paths(*pair) for n in p if n >= 100})
    culprit = cores_on_path[0]
    spec = FailureSpec(FailureMode.SILENT_DROP, culprit, (pair,), drop_prob=0.10, bg_noise_prob=1.0e-4)

    imp_s = TwoPhaseImpactEstimator(net_subtle)
    res_s = run_episode(
        net_subtle,
        spec,
        FivesPlanner(net_subtle, SafetyFilter(net_subtle), imp_s, MultiOutcomeEfficacyEstimator(net_subtle), tradeoff_lambda=0.85),
        MultiRoundBayesianPGM(net_subtle),
        imp_s,
        np.random.default_rng(55),
    )

    imp_h = TwoPhaseImpactEstimator(net_hard)
    res_h = run_episode(
        net_hard,
        spec,
        FivesPlanner(net_hard, SafetyFilter(net_hard), imp_h, MultiOutcomeEfficacyEstimator(net_hard), tradeoff_lambda=0.85),
        MultiRoundBayesianPGM(net_hard),
        imp_h,
        np.random.default_rng(55),
    )
    print(
        f"[Subtle vs Hard under DLB] Subtle peak_disrupt={res_s.peak_step_disruption:.2f}, total_disrupt={res_s.total_disruption:.2f}, R={res_s.recall:.2f} | "
        f"Hard peak_disrupt={res_h.peak_step_disruption:.2f}, total_disrupt={res_h.total_disruption:.2f}, R={res_h.recall:.2f}"
    )
    assert res_s.recall == 1.0
    assert res_s.peak_step_disruption < res_h.peak_step_disruption


def test_intermittent_and_multiflow():
    net = load_edgelist_network(
        os.path.join(TOPO_DIR, "ft_deg10_sw125_svr250_os3_bidir_false.edgelist"),
        name="Clos-k10",
    )
    rng = np.random.default_rng(31)
    pair1, culprit = _pick_inter_pod_pair_and_core(net, rng)
    # Find a second rack pair whose shortest paths also traverse `culprit`
    pair2 = None
    for s in net.rack_nodes[:15]:
        for d in net.rack_nodes[15:35]:
            if (s, d) != pair1 and any(culprit in p for p in net.shortest_paths(s, d)):
                pair2 = (s, d)
                break
        if pair2 is not None:
            break
    assert pair2 is not None

    safety = SafetyFilter(net)
    impact = TwoPhaseImpactEstimator(net)
    eff = MultiOutcomeEfficacyEstimator(net)

    # 1. Multi-flow correlation shrinks initial equivalence / total steps
    spec_1 = FailureSpec(FailureMode.SILENT_DROP, culprit, (pair1,), drop_prob=0.04)
    spec_2 = FailureSpec(FailureMode.SILENT_DROP, culprit, (pair1, pair2), drop_prob=0.04)
    r1 = run_episode(net, spec_1, FivesPlanner(net, safety, impact, eff), MultiRoundBayesianPGM(net), impact, np.random.default_rng(77))
    r2 = run_episode(net, spec_2, FivesPlanner(net, safety, impact, eff), MultiRoundBayesianPGM(net), impact, np.random.default_rng(77))
    print(f"[Multi-Flow] 1-pair steps={r1.num_perturbations} (eq0={r1.initial_eq_size}) -> 2-pair steps={r2.num_perturbations} (eq0={r2.initial_eq_size})")
    assert r1.recall == 1.0 and r2.recall == 1.0
    assert r2.num_perturbations <= r1.num_perturbations

    # 2. Intermittent gray failure (duty_cycle = 0.55)
    spec_int = FailureSpec(FailureMode.INTERMITTENT, culprit, (pair1,), drop_prob=0.08, duty_cycle=0.55)
    r_pgm = run_episode(
        net,
        spec_int,
        FivesPlanner(net, safety, impact, eff, allow_repeat_noisy=True),
        MultiRoundBayesianPGM(net, duty_cycle_prior=0.55),
        impact,
        np.random.default_rng(88),
        max_steps=25,
        stall_patience=8,
    )
    print(f"[Intermittent 55% duty] BayesianPGM: final_eq={r_pgm.final_eq_set}, P={r_pgm.precision:.2f}, R={r_pgm.recall:.2f}")
    assert r_pgm.recall == 1.0


def test_prod_campus_structured_constraints():
    prod = load_campus_prod_system(os.path.join(TOPO_DIR, "campus-str.edgelist"))
    print(
        f"[PROD Campus] switches={len(prod.switch_nodes)}, racks={len(prod.rack_nodes)}, "
        f"drain_banned={len(prod.safety.drain_banned_nodes)}, "
        f"mirror_filt={len(prod.safety.mirror_filtered_nodes)}, "
        f"ext_peers={len(prod.safety.external_blackbox_nodes)}"
    )
    rng = np.random.default_rng(12)
    # Pick two racks with multi-hop path through distribution/core
    racks = prod.rack_nodes
    chosen = None
    for _ in range(400):
        s = int(racks[int(rng.integers(0, len(racks)))])
        d = int(racks[int(rng.integers(0, len(racks)))])
        if s == d or s in prod.safety.external_blackbox_nodes or d in prod.safety.external_blackbox_nodes:
            continue
        paths = prod.shortest_paths(s, d)
        if len(paths) >= 2 and len(paths[0]) >= 4:
            interior = sorted({n for p in paths for n in p[1:-1]})
            if len(interior) >= 3:
                chosen = ((s, d), interior[len(interior) // 2])
                break
    assert chosen is not None
    pair, culprit = chosen
    spec = FailureSpec(FailureMode.SILENT_DROP, culprit, (pair,), drop_prob=0.05)
    safety = SafetyFilter(prod)
    impact = TwoPhaseImpactEstimator(prod)
    eff = MultiOutcomeEfficacyEstimator(prod)

    res = run_episode(
        prod,
        spec,
        FivesPlanner(prod, safety, impact, eff),
        MultiRoundBayesianPGM(prod),
        impact,
        np.random.default_rng(202),
    )
    print(
        f"[PROD Episode] culprit={prod.node_names[culprit]} ({culprit}) | "
        f"eq0={res.initial_eq_size} -> final={res.final_eq_set} in {res.num_perturbations} steps, "
        f"P={res.precision:.2f}, R={res.recall:.2f}"
    )
    assert res.recall == 1.0


def test_microservices_generality():
    ms = MicroserviceSystem()
    # Fault on `redis-replica` (node 7) causing 10% tail-latency / timeout spikes
    spec = FailureSpec(
        mode=FailureMode.HIGH_LATENCY,
        faulty_node=7,
        affected_pairs=((0, 10),),
        drop_prob=0.15,
        latency_inflation_us=1000.0,
        latency_jitter_us=10.0,
        latency_threshold_us=37.19,
    )
    safety = SafetyFilter(ms)
    impact = TwoPhaseImpactEstimator(ms)
    eff = MultiOutcomeEfficacyEstimator(ms)

    res_fives = run_episode(
        ms,
        spec,
        FivesPlanner(ms, safety, impact, eff, tradeoff_lambda=0.7),
        MultiRoundBayesianPGM(ms, excluded_endpoints={0, 10}),
        impact,
        np.random.default_rng(9),
        candidate_pool=list(range(1, 10)),
    )
    actions_taken = [t.perturbation.short_name() for t in res_fives.trajectory[1:]]
    print(
        f"[Microservices Case Study] culprit={ms.node_names[7]} -> localized={tuple(ms.node_names[x] for x in res_fives.final_eq_set)} "
        f"in {res_fives.num_perturbations} steps (disrupt={res_fives.total_disruption:.2f}): {actions_taken}"
    )
    assert res_fives.final_eq_set == (7,)
    # Verify zero high-cost ComponentReset pod restarts were needed!
    assert all(not a.startswith("Reset") for a in actions_taken)


def test_cpp_estimator_binary_smoke():
    est_bin = os.path.join(REPO_ROOT, "faultference", "estimator_agg")
    assert os.path.exists(est_bin), "C++ estimator_agg binary missing"


def test_parallel_and_multifault_extensions():
    from fives.extensions import run_parallel_episode, run_two_fault_episode

    net = load_edgelist_network(
        os.path.join(TOPO_DIR, "ft_deg10_sw125_svr250_os3_bidir_false.edgelist"),
        name="Clos-k10",
    )
    rng = np.random.default_rng(123)
    pair, culprit = _pick_inter_pod_pair_and_core(net, rng)
    spec = FailureSpec(FailureMode.SILENT_DROP, culprit, (pair,), drop_prob=0.04)

    r1 = run_parallel_episode(net, spec, batch_size=1, confirm_culprit=True, rng_seed=55)
    r4 = run_parallel_episode(net, spec, batch_size=4, confirm_culprit=True, rng_seed=55)
    r_sla = run_parallel_episode(net, spec, batch_size=1, max_step_disruption=0.25, confirm_culprit=True, rng_seed=55)
    print(
        f"[Parallel & SLA] B=1 rounds={r1['rounds']:.0f} TTL={r1['ttl']:.1f}s -> "
        f"B=4 rounds={r4['rounds']:.0f} TTL={r4['ttl']:.1f}s | SLA peak={r_sla['peak_disruption']:.2f}"
    )
    assert r1["recall"] == 1.0 and r4["recall"] == 1.0 and r_sla["recall"] == 1.0
    assert r4["rounds"] <= r1["rounds"]
    assert r_sla["peak_disruption"] <= 0.25 + 1.0e-9

    interior = sorted({n for p in net.shortest_paths(pair[0], pair[1]) for n in p[1:-1] if n != culprit})
    c2 = interior[0]
    rf2 = run_two_fault_episode(net, (culprit, c2), (pair,), drop_prob=0.05, mode="fives", rng_seed=88)
    print(f"[2-Faults] culprits={(culprit, c2)} -> recall={rf2['recall']:.2f}, prec={rf2['precision']:.2f}")
    assert rf2["recall"] == 1.0


if __name__ == "__main__":
    test_clos_silent_drop_and_baselines()
    test_exact_optimal_vs_greedy_and_lookahead()
    test_subtle_perturbations_and_dlb()
    test_intermittent_and_multiflow()
    test_prod_campus_structured_constraints()
    test_microservices_generality()
    test_cpp_estimator_binary_smoke()
    test_parallel_and_multifault_extensions()
    print("\nALL FIVES VERIFICATION TESTS PASSED!")


def test_high_latency_failure_model():
    spec = FailureSpec(
        mode=FailureMode.HIGH_LATENCY,
        faulty_node=1,
        affected_pairs=((0, 2),),
        drop_prob=0.25,
        latency_inflation_us=50.0,
        latency_jitter_us=10.0,
        latency_threshold_us=37.19,
    )
    assert abs(spec.unit_bad_prob(False) - 1.0e-4) < 1.0e-6
    assert abs(spec.unit_bad_prob(True) - 0.2251) < 1.0e-3
    for bad_kwargs in (dict(), dict(latency_inflation_us=50.0, latency_jitter_us=10.0)):
        try:
            FailureSpec(FailureMode.HIGH_LATENCY, 1, ((0, 2),), drop_prob=0.25, **bad_kwargs)
        except AssertionError:
            continue
        raise AssertionError(f"HIGH_LATENCY accepted incomplete latency params {bad_kwargs}")

    net = load_edgelist_network(
        os.path.join(TOPO_DIR, "ft_deg10_sw125_svr250_os3_bidir_false.edgelist"),
        name="Clos-k10",
    )
    rng = np.random.default_rng(11)
    pair, culprit = _pick_inter_pod_pair_and_core(net, rng)
    spec = FailureSpec(
        mode=FailureMode.HIGH_LATENCY,
        faulty_node=culprit,
        affected_pairs=(pair,),
        drop_prob=0.25,
        latency_inflation_us=50.0,
        latency_jitter_us=10.0,
        latency_threshold_us=37.19,
    )
    res = run_episode(
        net,
        spec,
        FivesPlanner(net, SafetyFilter(net), TwoPhaseImpactEstimator(net), MultiOutcomeEfficacyEstimator(net)),
        MultiRoundBayesianPGM(net, bg_noise_prob=spec.unit_bad_prob(False)),
        TwoPhaseImpactEstimator(net),
        np.random.default_rng(12),
    )
    print(f"[Clos-k10 HighLatency] culprit={culprit} eq0={res.initial_eq_size} -> {res.final_eq_set} "
          f"in {res.num_perturbations} steps")
    assert res.recall == 1.0


def test_path_aware_set_intersection_probe_verdicts():
    net = load_edgelist_network(
        os.path.join(TOPO_DIR, "ft_deg10_sw125_svr250_os3_bidir_false.edgelist"),
        name="Clos-k10",
    )
    pair, _ = _pick_inter_pod_pair_and_core(net, np.random.default_rng(7))
    sub_paths = net.shortest_paths(pair[0], pair[1])
    traced = sub_paths[0]
    pool = sorted({n for p in sub_paths for n in p})
    probe = ActiveProbe(pair[0], pair[1], pair)
    w = 1.0 / len(sub_paths)

    def window(bad: int) -> TelemetryWindow:
        rec = TelemetryRecord(
            pair=pair, is_probe=True, is_mirror=False, mirror_node=-1, packets_sent=200, packets_bad=bad,
            path_weights=tuple((sp, w) for sp in sub_paths), traced_path=traced,
        )
        return TelemetryWindow(perturbation=probe, records=(rec,), fault_was_active=True)

    # Passed probe: legacy exonerates every ECMP sub-path; path-aware only the traced one.
    legacy, aware = SetIntersectionInference(net, path_aware=False), SetIntersectionInference(net, path_aware=True)
    for inf in (legacy, aware):
        inf.reset(pool)
        inf.update(window(0))
    assert legacy.equivalence_set() == set(pool)  # nothing left to exonerate -> set unchanged
    assert aware.equivalence_set() == set(pool) - set(traced)

    # One bad probe at bg=1e-4: legacy calls it failed; the binomial test (p ~= 0.02) does not.
    legacy, aware = SetIntersectionInference(net, path_aware=False), SetIntersectionInference(net, path_aware=True)
    for inf in (legacy, aware):
        inf.reset(pool)
        inf.update(window(1))
    assert legacy.equivalence_set() == set(pool)  # intersect with all sub-path nodes = pool
    assert aware.equivalence_set() == set(pool) - set(traced)
    aware.reset(pool)
    aware.update(window(3))
    assert aware.equivalence_set() == set(traced)
