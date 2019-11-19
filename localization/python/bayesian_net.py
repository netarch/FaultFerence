import sys
from heapq import heappush, heappop
import multiprocessing
from multiprocessing import Process, Queue
import math
import copy
import time
import random
import numpy as np
from scipy.optimize import minimize
import utils
import queue
from decimal import Decimal
from utils import *
from plot_utils import *

USE_CONDITIONAL = False

def fn(naffected, npaths, naffected_r, npaths_r, p1, p2):
    #end_to_end: e2e
    e2e_paths = npaths * npaths_r
    e2e_correct_paths = (npaths - naffected) * (npaths_r - naffected_r)
    e2e_failed_paths = e2e_paths - e2e_correct_paths
    return (e2e_failed_paths * (1.0 - p1)/e2e_paths + e2e_correct_paths * p2/e2e_paths)

#math.log((1.0 - 1.0/k) + (1.0-p1)/(p2*k))
def bnf_bad(naffected, npaths, naffected_r, npaths_r, p1, p2):
    return math.log(fn(naffected, npaths, naffected_r, npaths_r, p1, p2)/fn(0, npaths, 0, npaths_r, p1, p2))

# math.log((1.0 - 1.0/k) + p1/((1.0-p2)*k))
def bnf_good(naffected, npaths, naffected_r, npaths_r, p1, p2):
    return math.log((1 - fn(naffected, npaths, naffected_r, npaths_r, p1, p2))/(1 - fn(0, npaths, 0, npaths_r, p1, p2)))

def bnf_weighted(naffected, npaths, naffected_r, npaths_r, p1, p2, weight_good, weight_bad):
    #end_to_end: e2e
    e2e_paths = npaths * npaths_r
    e2e_correct_paths = (npaths - naffected) * (npaths_r - naffected_r)
    e2e_failed_paths = e2e_paths - e2e_correct_paths
    a = float(e2e_failed_paths)/e2e_paths
    val = (1.0 - a) + a * (((1.0 - p1)/p2) ** weight_bad) * ((p1/(1.0-p2)) ** weight_good)
    #d = Decimal(val)
    #return float(d.ln())
    return math.log(val)

def bnf_weighted_conditional(naffected, npaths, naffected_r, npaths_r, p1, p2, weight_good, weight_bad):
    #end_to_end: e2e
    e2e_paths = npaths * npaths_r
    e2e_correct_paths = (npaths - naffected) * (npaths_r - naffected_r)
    e2e_failed_paths = e2e_paths - e2e_correct_paths
    assert(e2e_paths == 1 and e2e_failed_paths)
    a = float(e2e_failed_paths)/e2e_paths
    val1 = (1.0 - a) + a * (((1.0 - p1)/p2) ** weight_bad) * ((p1/(1.0-p2)) ** weight_good)
    total_weight = weight_good + weight_bad
    val2 = (1.0 - a) + a * (1 - (p1**total_weight))/(1.0 - ((1.0 - p2)**total_weight))
    d = Decimal(val1/val2)
    return float(d.ln())
    #return math.log(max(1.0e-900, val1)) - math.log(max(1.0e-900, val2))

def bnf_weighted_path_individual(p_arr, correct_p_arr, weight_good, weight_bad):
    likelihood_numerator = 0.0
    likelihood_denominator = 0.0
    #if correct_p_arr[0] > 1.5e-3:
    #    print(p_arr, correct_p_arr)
    for i in range(len(p_arr)):
        p = p_arr[i]
        p0 = correct_p_arr[i]
        likelihood_numerator += (p ** weight_bad) * ((1.0 - p) ** weight_good)
        likelihood_denominator += (p0 ** weight_bad) * ((1.0 - p0) ** weight_good)
    return math.log(likelihood_numerator/likelihood_denominator)

def compute_log_likelihood(hypothesis, flows_by_link, flows, min_start_time_ms, max_finish_time_ms, p1, p2, base_hypothesis_likelihood=([], 0.0), active_flows_only=False):
    log_likelihood = 0.0
    base_hypothesis, base_likelihood = base_hypothesis_likelihood
    relevant_flows = set()
    for h in hypothesis:
        if h not in base_hypothesis:
            link_flows = flows_by_link[h]
            for f in link_flows:
                flow = flows[f]
                if flow.start_time_ms >= min_start_time_ms and (not active_flows_only or flow.is_active_flow()):
                    relevant_flows.add(f)

    #an optimization if we know path for every flow
    if PATH_KNOWN:
        weights = [flows[ff].label_weights_func(max_finish_time_ms) for ff in relevant_flows]
        weight_good = sum(w[0] for w in weights)
        weight_bad = sum(w[1] for w in weights)
        #log_likelihood += bnf_bad(1, 1, 1, 1, p1, p2) * weight_bad
        #log_likelihood += bnf_good(1, 1, 1, 1, p1, p2) * weight_good
        #because expression in bnf_weighted runs into numerical issues
        log_likelihood += weight_bad * math.log((1.0 - p1)/p2)
        log_likelihood += weight_good * math.log(p1/(1.0-p2))
        return log_likelihood

    for ff in relevant_flows:
        flow = flows[ff]
        flow_paths = flow.get_paths(max_finish_time_ms)
        weight = flow.label_weights_func(max_finish_time_ms)
        if weight[0] == 0 and weight[1] == 0:
            continue
        npaths = len(flow_paths)
        naffected = 0.0
        naffected_base = 0.0
        for path in flow_paths:
            for v in range(1, len(path)):
                l = (path[v-1], path[v])
                if l in hypothesis:
                    naffected += 1.0
                    break
            for v in range(1, len(path)):
                l = (path[v-1], path[v])
                if l in base_hypothesis:
                    naffected_base += 1.0
                    break
        flow_reverse_paths = flow.get_reverse_paths(max_finish_time_ms)
        npaths_r = len(flow_reverse_paths)
        naffected_r = 0.0
        naffected_base_r = 0.0
        if CONSIDER_REVERSE_PATH:
            for path in flow_reverse_paths:
                for v in range(1, len(path)):
                    l = (path[v-1], path[v])
                    if l in hypothesis:
                        naffected_r += 1.0
                        break
                for v in range(1, len(path)):
                    l = (path[v-1], path[v])
                    if l in base_hypothesis:
                        naffected_base_r += 1.0
                        break
        #print("Num paths: ", naffected, npaths, naffected_r, npaths_r)
        #log_likelihood += bnf_good(naffected, npaths, naffected_r, npaths_r, p1, p2) * weight[0]
        #log_likelihood += bnf_bad(naffected, npaths, naffected_r, npaths_r, p1, p2) * weight[1]
        log_likelihood += bnf_weighted(naffected, npaths, naffected_r, npaths_r, p1, p2, weight[0], weight[1])
        if naffected_base > 0 or naffected_base_r > 0:
            log_likelihood -= bnf_weighted(naffected_base, npaths, naffected_base_r, npaths_r, p1, p2, weight[0], weight[1])
    prior = 5
    return base_likelihood + log_likelihood + (len(base_hypothesis) -  len(hypothesis)) * prior

'''
!TODO: Implement optimized from k^3 --> k^2
!TODO: Use previous hypothesis before extend step to optimize the size of relevant_flows
!TODO: This will make the processing independent of the size of the hypothesis
'''
def compute_log_likelihood_conditional(hypothesis, flows_by_link, flows, min_start_time_ms, max_finish_time_ms, p1, p2, base_hypothesis_likelihood=([], 0.0), active_flows_only=False):
    log_likelihood = 0.0
    base_hypothesis, base_likelihood = base_hypothesis_likelihood
    relevant_flows = set()
    for h in hypothesis:
        if h not in base_hypothesis:
            link_flows = flows_by_link[h]
            for f in link_flows:
                flow = flows[f]
                if flow.start_time_ms >= min_start_time_ms and (flow.is_active_flow() or flow.is_flow_bad(max_finish_time_ms)):
                    relevant_flows.add(f)

    for ff in relevant_flows:
        flow = flows[ff]
        flow_paths = flow.get_paths(max_finish_time_ms)
        weight = flow.label_weights_func(max_finish_time_ms)
        if weight[0] == 0 and weight[1] == 0:
            continue
        npaths = len(flow_paths)
        naffected = 0.0
        naffected_base = 0.0
        for path in flow_paths:
            for v in range(1, len(path)):
                l = (path[v-1], path[v])
                if l in hypothesis:
                    naffected += 1.0
                    break
            for v in range(1, len(path)):
                l = (path[v-1], path[v])
                if l in base_hypothesis:
                    naffected_base += 1.0
                    break
        flow_reverse_paths = flow.get_reverse_paths(max_finish_time_ms)
        npaths_r = len(flow_reverse_paths)
        naffected_r = 0.0
        naffected_base_r = 0.0
        if CONSIDER_REVERSE_PATH:
            for path in flow_reverse_paths:
                for v in range(1, len(path)):
                    l = (path[v-1], path[v])
                    if l in hypothesis:
                        naffected_r += 1.0
                        break
                for v in range(1, len(path)):
                    l = (path[v-1], path[v])
                    if l in base_hypothesis:
                        naffected_base_r += 1.0
                        break
        #print("Num paths: ", naffected, npaths, naffected_r, npaths_r)
        #log_likelihood += bnf_good(naffected, npaths, naffected_r, npaths_r, p1, p2) * weight[0]
        #log_likelihood += bnf_bad(naffected, npaths, naffected_r, npaths_r, p1, p2) * weight[1]
        if flow.is_active_flow():
            assert (False)
            log_likelihood += bnf_weighted(naffected, npaths, naffected_r, npaths_r, p1, p2, weight[0], weight[1])
            if naffected_base > 0 or naffected_base_r > 0:
                log_likelihood -= bnf_weighted(naffected_base, npaths, naffected_base_r, npaths_r, p1, p2, weight[0], weight[1])
        elif flow.is_flow_bad(max_finish_time_ms):
            log_likelihood += bnf_weighted_conditional(naffected, npaths, naffected_r, npaths_r, p1, p2, weight[0], weight[1])
            if naffected_base > 0 or naffected_base_r > 0:
                log_likelihood -= bnf_weighted_conditional(naffected_base, npaths, naffected_base_r, npaths_r, p1, p2, weight[0], weight[1])
        else:
            assert(False)
    prior = 5.0
    return base_likelihood + log_likelihood + (len(base_hypothesis) -  len(hypothesis)) * prior

def compute_likelihoods_daemon(request_queue, flows_by_link, flows, min_start_time_ms_, max_finish_time_ms_, p1_, p2_, response_queue, final_request):
    min_start_time_ms = min_start_time_ms_
    max_finish_time_ms = max_finish_time_ms_
    p1 = p1_
    p2 = p2_
    start_time = time.time()
    while not final_request:
        hypothesis_space, final_request, active_flows_only = request_queue.get()
        likelihoods = []
        for hypothesis, base_hypothesis_likelihood in hypothesis_space:
            if USE_CONDITIONAL:
                log_likelihood = compute_log_likelihood_conditional(hypothesis, flows_by_link, flows, min_start_time_ms, max_finish_time_ms, p1, p2, base_hypothesis_likelihood, active_flows_only)
            else:
                log_likelihood = compute_log_likelihood(hypothesis, flows_by_link, flows, min_start_time_ms, max_finish_time_ms, p1, p2, base_hypothesis_likelihood, active_flows_only)
            #print(log_likelihood, hypothesis)
            likelihoods.append((log_likelihood, list(hypothesis)))
        #if utils.VERBOSE:
        #print("compute_likelihoods computed", len(hypothesis_space), "in", time.time() - start_time, "seconds") 
        response_queue.put(likelihoods)
        #request_queue.task_done()
        #response_queue.join()


def bayesian_network_cilia(flows, links, inverse_links, flows_by_link, forward_flows_by_link, reverse_flows_by_link, failed_links, link_statistics, min_start_time_ms, max_finish_time_ms, params, nprocesses):

    if USE_CONDITIONAL: 
        flows = [flow for flow in flows if flow.start_time_ms >= min_start_time_ms and flow.any_snapshot_before(max_finish_time_ms) and flow.traceroute_flow(max_finish_time_ms)]
        if utils.VERBOSE:
            print("Num conditional flows", len(flows))
        forward_flows_by_link = get_forward_flows_by_link(flows, inverse_links, max_finish_time_ms)
        reverse_flows_by_link = dict()
        flows_by_link = get_flows_by_link(forward_flows_by_link, reverse_flows_by_link, inverse_links)

    weights = [flow.label_weights_func(max_finish_time_ms) for flow in flows if flow.start_time_ms >= min_start_time_ms]
    weight_good = sum(w[0] for w in weights)
    weight_bad = sum(w[1] for w in weights)
    score_time = time.time()

    #knobs in the bayesian network
    # p1 = P[flow good|bad path], p2 = P[flow bad|good path]
    #p2 = max(1.0e-10, weight_bad/(weight_good + weight_bad))
    #p2 = 2.5e-4
    #p1 = max(0.001, (1.0 - max_alpha_score))
    #p1 = 1.0 - 2.5e-3
    p1 = params[0]
    p2 = params[1]
    if utils.VERBOSE:
        scores, expected_scores = get_link_scores(flows, inverse_links, forward_flows_by_link, reverse_flows_by_link, min_start_time_ms, max_finish_time_ms, active_flows_only=False)
        alpha_scores = [calc_alpha(scores[link], expected_scores[link]) for link in inverse_links]
        max_alpha_score = max(alpha_scores)
        min_expected_flows_on_link = min([expected_scores[link] for link in inverse_links])
        max_expected_flows_on_link = max([expected_scores[link] for link in inverse_links])
        print("Weight (bad):", weight_bad, " (good):", weight_good, "Num flows", len(flows))
        print("Parameters: P[sample bad|link bad] (1-p1)", 1-p1, "P[sample bad|link good] (p2)", p2)
        print("Min expected coverage on link", min_expected_flows_on_link, "Max", max_expected_flows_on_link)
        print("Calculated scores in", time.time() - score_time, " seconds")

    request_queues = [Queue() for x in range(nprocesses)]
    #response_queues = []
    response_queue = Queue()
    MAX_FAILS = 10
    if nprocesses > 1:
        for i in range(nprocesses):
            #request_queues.append(multiprocessing.JoinableQueue())
            #response_queues.append(multiprocessing.JoinableQueue())
            proc = Process(target=compute_likelihoods_daemon, args=(request_queues[i], dict(flows_by_link), list(flows), min_start_time_ms, max_finish_time_ms, p1, p2, response_queue, False))
            proc.start()

    n_max_k_likelihoods = 20
    max_k_likelihoods = []
    heappush(max_k_likelihoods, (0.0, []))
    prev_hypothesis_space = [[]]
    likelihoods = dict()
    likelihoods[frozenset()] = 0.0
    NUM_CANDIDATES = min(len(inverse_links), max(15, int(5 * MAX_FAILS)))
    candidates = inverse_links

    if utils.VERBOSE:
        print("Beginning search, num candidates", len(candidates), "branch_factor", len(prev_hypothesis_space))
    start_search_time = time.time()

    nfails = 1
    # might have to repeat nfails_1 if likelihoods computed using only active flows
    repeat_nfails_1 = True
    while nfails <= MAX_FAILS:
        start_time = time.time()
        hypothesis_space_no_base = []
        hypothesis_space = []
        #print(candidates, prev_hypothesis_space)
        for h in prev_hypothesis_space:
            for link in candidates:
                if link not in h:
                    hnew = sorted(h+[link])
                    if hnew not in hypothesis_space_no_base:
                        hypothesis_space_no_base.append(hnew)
                        hypothesis_space.append((hnew, (h, likelihoods[frozenset(h)])))
                        #hypothesis_space.append((hnew, ([], 0.0)))
        num_hypothesis = len(hypothesis_space)
        for i in range(nprocesses):
            start = int(i * num_hypothesis/nprocesses)
            end = int(min(num_hypothesis, (i+1) * num_hypothesis/nprocesses))
            #!TODO: Hack. The 3rd argument will restrict flows to active flows only for nfails==1
            active_flows_only = False #(nfails==1 and repeat_nfails_1)
            request_queues[i].put((list(hypothesis_space[start:end]), (nfails==MAX_FAILS or nprocesses==1), active_flows_only))

        if (nprocesses == 1):
            #Optimization for single process
            compute_likelihoods_daemon(request_queues[i], flows_by_link, flows, min_start_time_ms, max_finish_time_ms, p1, p2, response_queue, False)

        l_h = [] # each element is (likelihood, hypothesis)
        for i in range(nprocesses):
            #request_queues[i].join()
            l_h.extend(response_queue.get())
            #response_queues[i].task_done()
        top_hypotheses = np.argsort([x[0] for x in l_h])

        for likelihood, hypothesis in l_h:
            likelihoods[frozenset(hypothesis)] = likelihood

        if not (nfails == 1 and repeat_nfails_1):
            for i in range(min(n_max_k_likelihoods, len(top_hypotheses))):
                ind = top_hypotheses[-(i+1)]
                heappush(max_k_likelihoods, l_h[ind])
                if (len(max_k_likelihoods) > n_max_k_likelihoods):
                    heappop(max_k_likelihoods)
            if utils.VERBOSE:
                print("Finished hypothesis search across ", len(hypothesis_space), "Hypothesis for ", nfails, "failures in", time.time() - start_time, "seconds")

        if nfails == 1 and repeat_nfails_1:
            candidates_likelihoods = [l_h[i] for i in top_hypotheses[-NUM_CANDIDATES:]]
            if utils.VERBOSE:
                for l, h in candidates_likelihoods:
                    link = h[0]
                    print(link, l, calc_alpha(scores[link], expected_scores[link]), scores[link], expected_scores[link])
                for l,h in l_h:
                    link = h[0]
                    if link in failed_links:
                        print("Failed link: ", link, l, calc_alpha(scores[link], expected_scores[link]), " scores: ", scores[link], expected_scores[link])
                print("Time for preprocessing nfails=1", time.time() - start_time, "seconds")
            candidates = [l_h[1][0] for l_h in candidates_likelihoods if l_h[0] > -500.0] #update candidates for further search
            #candidates = [l_h[1][0] for l_h in candidates_likelihoods] #update candidates for further search
            repeat_nfails_1 = False
        else:
            prev_hypothesis_space = [l_h[i][1] for i in top_hypotheses[-NUM_CANDIDATES:]]
            nfails += 1
        #Aggressively limit candidates at further stages
        NUM_CANDIDATES = min(len(inverse_links), 5)

    failed_links_set = set(failed_links.keys())
    if utils.VERBOSE:
        if USE_CONDITIONAL:
            likelihood_correct_hypothesis = compute_log_likelihood_conditional(failed_links_set, flows_by_link, flows, min_start_time_ms, max_finish_time_ms, p1, p2)
        else:
            likelihood_correct_hypothesis = compute_log_likelihood(failed_links_set, flows_by_link, flows, min_start_time_ms, max_finish_time_ms, p1, p2)
        print ("Correct Hypothesis ", list(failed_links_set), " likelihood ", likelihood_correct_hypothesis)
    highest_likelihood = -1000000000000.0 
    for likelihood, hypothesis in max_k_likelihoods:
        highest_likelihood = max(likelihood, highest_likelihood)
    ret_hypothesis = set()
    while(len(max_k_likelihoods) > 0):
        likelihood, hypothesis = heappop(max_k_likelihoods)
        if(highest_likelihood > 1.0e-3 and highest_likelihood - likelihood <= 1.0e-3):
            for h in hypothesis:
                ret_hypothesis.add(h)
        if utils.VERBOSE:
            print ("Likely candidate", hypothesis, likelihood)
    precision, recall = get_precision_recall(failed_links, ret_hypothesis)
    if utils.VERBOSE:
        print("\nSearched hypothesis space in ", time.time() - start_search_time, " seconds")
    print ("Output Hypothesis: ", list(ret_hypothesis), "precsion_recall", precision, recall)
    return (precision, recall), None

