#include "bayesian_net.h"
#include "utils.h"
#include <algorithm>
#include <assert.h>
#include <chrono>
#include <cmath>
#include <iostream>
#include <limits>
#include <numeric>
#include <omp.h>
#include <queue>
#include <sparsehash/dense_hash_set>
#include <tuple>
using google::dense_hash_set;
using namespace std;

//! TODO: Change to smart pointers for easier GC
//! TODO: Add code for REVERSE_PATH

BayesianNet::BayesianNet() : Estimator() {
    CONSIDER_DEVICE_LINK = true;
    // CONSIDER_DEVICE_LINK = false;
}

// Optimization to ensure that extra links in the hypothesis are the optimal
// ones
void BayesianNet::SortCandidatesWrtNumRelevantFlows(vector<int> &candidates) {
    sort(candidates.begin(), candidates.end(),
         [&](int &link_id1, int link_id2) -> bool {
             return flows_by_link_id[link_id1].size() <
                    flows_by_link_id[link_id2].size();
         });
}

// Free memory allocated to hypotheses
void BayesianNet::CleanUpAfterLocalization(
    unordered_map<Hypothesis *, double> &all_hypothesis) {
    for (auto &it : all_hypothesis) {
        delete (it.first);
    }
}

// Optimization legitimate for regular unconditional computation
void BayesianNet::ComputeAndStoreIntermediateValues(int nopenmp_threads,
                                                    double max_finish_time_ms) {
#pragma omp parallel for num_threads(nopenmp_threads)
    for (int ii = 0; ii < data->flows.size(); ii++) {
        Flow *flow = data->flows[ii];
        if (flow->AnySnapshotBefore(max_finish_time_ms)) {
            flow->SetCachedIntermediateValue(
                GetBnfWeightedUnconditionalIntermediateValue(
                    flow, max_finish_time_ms));
        }
    }
}

BayesianNet *BayesianNet::CreateObject() {
    BayesianNet *ret = new BayesianNet();
    vector<double> param{p1, p2, PRIOR};
    ret->SetParams(param);
    return ret;
}

void BayesianNet::SetParams(vector<double> &param) {
    assert(param.size() == 3);
    if (params_from_input) {
        PRIOR = param[2];
    } else
        tie(p1, p2, PRIOR) = {param[0], param[1], param[2]};
}

void BayesianNet::SetParamsFromInput(double max_finish_time_ms) {
    assert(false);
    long int nsent = 0, ndropped = 0;
    vector<float> drop_rates;
    for (int ii = 0; ii < data->flows.size(); ii++) {
        Flow *flow = data->flows[ii];
        nsent += flow->GetPacketsSent(max_finish_time_ms);
        ndropped += flow->GetPacketsLost(max_finish_time_ms);
        drop_rates.push_back(flow->GetDropRate(max_finish_time_ms));
    }
    p2 = min((float)1.0e-3, ((float)ndropped / nsent));
    // p2 = min((float)1.0e-3, ((float)ndropped)/nsent);
    p1 = 1.0 - 20 * p2;
    sort(drop_rates.begin(), drop_rates.end());
    float dr = drop_rates[(int)(0.98 * drop_rates.size()) - 1];
    // p1 = 1.0 - dr/2;
    // p1 = 1.0 - min(d99, (float)(10.0 * p2));
    // p1 = 1 - 0.008; p2 = 0.0002; PRIOR = -200;

    cout << "Setting parameters automatically " << 1 - p1 << " " << p2 << " "
         << PRIOR << endl;
    params_from_input = true;
}

void BayesianNet::SetLogData(LogData *data_, double max_finish_time_ms,
                             int nopenmp_threads) {
    Estimator::SetLogData(data_, max_finish_time_ms, nopenmp_threads);
    if (INPUT_FLOW_TYPE == PROBLEMATIC_FLOWS) {
        data->FilterFlowsForConditional(max_finish_time_ms, nopenmp_threads);
    }
    // if ((p1==0) or (p2==0)){
    // assert (INPUT_FLOW_TYPE != PROBLEMATIC_FLOWS);
    // SetParamsFromInput(max_finish_time_ms);
    //}
}

void BayesianNet::SearchHypotheses(
    double min_start_time_ms, double max_finish_time_ms,
    unordered_map<Hypothesis *, double> &all_hypothesis, int nopenmp_threads) {
    Hypothesis *no_failure_hypothesis = new Hypothesis();
    all_hypothesis[no_failure_hypothesis] = 0.0;
    vector<Hypothesis *> prev_hypothesis_space;
    // Initial list of candidates is all links
    vector<int> candidates;
    for (int link_id = 0; link_id < data->inverse_links.size(); link_id++) {
        candidates.push_back(link_id);
    }
    prev_hypothesis_space.push_back(no_failure_hypothesis);
    int nfails = 1;
    double max_likelihood_this_stage = 0; // empty hypothesis
    double max_likelihood_previous_stage = -1.0e10;
    while (max_likelihood_this_stage >
           max_likelihood_previous_stage) { // nfails <= MAX_FAILS){
        auto start_stage_time = chrono::high_resolution_clock::now();
        max_likelihood_previous_stage = max_likelihood_this_stage;
        max_likelihood_this_stage = -1.0e10; //-inf
        vector<pair<double, Hypothesis *>> result;
        if (nfails == 1) {
            ComputeSingleLinkLogLikelihood(result, min_start_time_ms,
                                           max_finish_time_ms, nopenmp_threads);
        } else {
            // Inefficient if |hypothesis_space| is large, say > 1000
            vector<Hypothesis *> hypothesis_space;
            vector<pair<Hypothesis *, double>> base_hypothesis_likelihood;
            for (int link_id : candidates) {
                for (Hypothesis *h : prev_hypothesis_space) {
                    assert(h != NULL);
                    if (h->find(link_id) == h->end()) {
                        h->insert(link_id);
                        if (true or find_if(hypothesis_space.begin(),
                                            hypothesis_space.end(),
                                            HypothesisPointerCompare(h)) ==
                                        hypothesis_space.end()) {
                            Hypothesis *hnew = new Hypothesis(*h);
                            hypothesis_space.push_back(hnew);
                            base_hypothesis_likelihood.push_back(
                                make_pair(h, all_hypothesis[h]));
                            // base_hypothesis_likelihood.push_back(make_pair(no_failure_hypothesis,
                            // 0.0));
                        }
                        h->erase(link_id);
                    }
                }
            }
            if (VERBOSE)
                cout << "Starting to compute LL after "
                     << GetTimeSinceSeconds(start_stage_time) << " "
                     << hypothesis_space.size() << endl;
            ComputeLogLikelihood(hypothesis_space, base_hypothesis_likelihood,
                                 result, min_start_time_ms, max_finish_time_ms,
                                 nopenmp_threads);
        }
        // cout << "Calling sort after " <<
        // GetTimeSinceSeconds(start_stage_time) << " seconds " << endl;
        sort(result.begin(), result.end(),
             greater<pair<double, Hypothesis *>>());
        max_likelihood_this_stage =
            max(max_likelihood_this_stage, result[0].first);
        if (nfails == 1) {
            // update candidates
            candidates.clear();
            int num_candidates = result.size(); // NUM_CANDIDATES
            for (int i = 0; i < min((int)result.size(), num_candidates); i++) {
                Hypothesis *h = result[i].second;
                assert(h->size() == 1);
                int link_id = *(h->begin());
                candidates.push_back(link_id);
                // if (VERBOSE){
                //    cout << "Candidate " << data->IdsToLinks(*h) << " " <<
                //    result[i].first << endl;
                //}
            }
            if (VERBOSE) {
                for (auto [link, failparam] : data->failed_links) {
                    int link_id = data->links_to_ids[link];
                    if (find(candidates.begin(), candidates.end(), link_id) ==
                        candidates.end()) {
                        cout << "Link " << link
                             << " absent from initial candidates" << endl;
                    }
                }
            }
            // SortCandidatesWrtNumRelevantFlows(candidates);
        }
        if (VERBOSE) {
            cout << "Finished hypothesis search across " << result.size()
                 << " Hypothesis for " << nfails << " failures in "
                 << GetTimeSinceSeconds(start_stage_time) << " seconds" << endl;
        }
        nfails++;
        prev_hypothesis_space.clear();
        for (int i = 0;
             (i < result.size() and
              prev_hypothesis_space.size() < NUM_TOP_HYPOTHESIS_AT_EACH_STAGE);
             i++) {
            if (find_if(prev_hypothesis_space.begin(),
                        prev_hypothesis_space.end(),
                        HypothesisPointerCompare(result[i].second)) ==
                prev_hypothesis_space.end())
                prev_hypothesis_space.push_back(result[i].second);
        }
        for (auto &it : result) {
            all_hypothesis[it.second] = it.first;
        }
    }
}

int BayesianNet::GetNumComponents(bool device_level) {
    return (device_level ? data->GetMaxDevicePlus1()
                         : data->inverse_links.size());
}

void BayesianNet::SearchHypothesesJle(
    double min_start_time_ms, double max_finish_time_ms,
    unordered_map<Hypothesis *, double> &all_hypothesis, bool device_level,
    int nopenmp_threads) {
    Hypothesis *no_failure_hypothesis = new Hypothesis();
    all_hypothesis[no_failure_hypothesis] = 0.0;

    vector<double> likelihood_scores1[NUM_TOP_HYPOTHESIS_AT_EACH_STAGE];
    vector<double> likelihood_scores2[NUM_TOP_HYPOTHESIS_AT_EACH_STAGE];
    vector<double> *likelihood_scores = likelihood_scores1;
    vector<double> *other_likelihood_scores = likelihood_scores2;

    vector<Hypothesis *> top_candidate_hypothesis;
    top_candidate_hypothesis.reserve(NUM_TOP_HYPOTHESIS_AT_EACH_STAGE);
    top_candidate_hypothesis.push_back(no_failure_hypothesis);

    auto start_init_time = chrono::high_resolution_clock::now();

    ComputeInitialLikelihoodsHelper(likelihood_scores[0], min_start_time_ms,
                                    max_finish_time_ms, device_level,
                                    nopenmp_threads);

    /*
    for(int link_id=0; link_id<data->inverse_links.size(); link_id++){
        Link l1 = Link(1, 7), l2 = Link(7, 1);
        //if (data->inverse_links[link_id]==l1 or
    data->inverse_links[link_id]==l2) cout << "Initial likelihoods " <<
    data->inverse_links[link_id] << " " << likelihood_scores[0][link_id] <<
    endl;
    }
    */
    if (VERBOSE) {
        cout << "Finished hypothesis search for 1 failure in "
             << GetTimeSinceSeconds(start_init_time) << " seconds" << endl;
        cout << "Finished linear stage in "
             << GetTimeSinceSeconds(timer_checkpoint) << " seconds" << endl;
        timer_checkpoint = chrono::high_resolution_clock::now();
    }
    int ncomponents = GetNumComponents(device_level);
    int nfails = 1; // single device failure scores already computed
    double max_likelihood_this_stage = 0; // empty hypothesis
    double max_likelihood_previous_stage = -1.0e10;
    while (max_likelihood_this_stage > max_likelihood_previous_stage) {
        if (nfails > MAX_FAILS) break;
        max_likelihood_previous_stage = max_likelihood_this_stage;
        max_likelihood_this_stage = -1.0e10; //-inf
        auto start_stage_time = chrono::high_resolution_clock::now();
        assert(top_candidate_hypothesis.size() <=
               NUM_TOP_HYPOTHESIS_AT_EACH_STAGE);
        // nl_nh_bh_s (new_likelihood, new_hypothesis, base_hypothesis, scores)
        vector<tuple<double, Hypothesis *, Hypothesis *, vector<double> *>>
            nl_nh_bh_s;
        vector<Hypothesis *> unique_hypotheses;
        for (int ii = 0; ii < top_candidate_hypothesis.size(); ii++) {
            Hypothesis *base_hypothesis = top_candidate_hypothesis[ii];
            double base_likelihood = all_hypothesis[base_hypothesis];
            vector<int> top_components;
            assert(likelihood_scores[ii].size() == ncomponents);
            GetIndicesOfTopK(likelihood_scores[ii],
                             NUM_TOP_HYPOTHESIS_AT_EACH_STAGE, top_components,
                             base_hypothesis, true); //!TODO: remove true
            for (int cmp : top_components) {
                assert(base_hypothesis->find(cmp) == base_hypothesis->end());
                base_hypothesis->insert(cmp);
                if (find_if(unique_hypotheses.begin(), unique_hypotheses.end(),
                            HypothesisPointerCompare(base_hypothesis)) ==
                    unique_hypotheses.end()) {
                    Hypothesis *new_hypothesis =
                        new Hypothesis(*base_hypothesis);
                    base_hypothesis->erase(cmp);
                    unique_hypotheses.push_back(new_hypothesis);
                    double new_likelihood =
                        base_likelihood + likelihood_scores[ii][cmp];
                    //+ ComputeLogPrior(new_hypothesis)
                    //- ComputeLogPrior(base_hypothesis);
                    // cout << " base_likelihood " << base_likelihood << "
                    // new_likelihood "
                    //     << " base_h " << data->IdsToLinks(*base_hypothesis)
                    //     << " new_h " << data->IdsToLinks(*new_hypothesis) <<
                    //     endl;
                    max_likelihood_this_stage =
                        max(new_likelihood, max_likelihood_this_stage);
                    nl_nh_bh_s.push_back({new_likelihood, new_hypothesis,
                                          base_hypothesis,
                                          &likelihood_scores[ii]});
                } else
                    base_hypothesis->erase(cmp);
            }
        }
        sort(
            nl_nh_bh_s.begin(), nl_nh_bh_s.end(),
            greater<
                tuple<double, Hypothesis *, Hypothesis *, vector<double> *>>());
        top_candidate_hypothesis.clear();
        int num_flows_analyzed = 0;
        for (int ii = 0;
             ii < min((int)nl_nh_bh_s.size(), NUM_TOP_HYPOTHESIS_AT_EACH_STAGE);
             ii++) {
            auto &[likelihood, hypothesis, base_hypothesis, scores] =
                nl_nh_bh_s[ii];
            all_hypothesis[hypothesis] = likelihood;
            top_candidate_hypothesis.push_back(hypothesis);
            // Update scores for other_likelihood_scores
            // cout << "After update scores " << data->IdsToLinks(*hypothesis)
            // << " " << data->IdsToLinks(*base_hypothesis) << " : " <<
            // likelihood << endl;
            assert(scores->size() == ncomponents);
            other_likelihood_scores[ii].clear();
            other_likelihood_scores[ii].insert(
                other_likelihood_scores[ii].begin(), scores->begin(),
                scores->end());
            if (device_level)
                num_flows_analyzed += UpdateScoresDevice(
                    other_likelihood_scores[ii], hypothesis, base_hypothesis,
                    min_start_time_ms, max_finish_time_ms, nopenmp_threads);
            else
                num_flows_analyzed += UpdateScores(
                    other_likelihood_scores[ii], hypothesis, base_hypothesis,
                    min_start_time_ms, max_finish_time_ms, nopenmp_threads);
        }
        swap(likelihood_scores, other_likelihood_scores);
        if (VERBOSE) {
            cout << "Total flows analyzed " << num_flows_analyzed
                 << " Finished hypothesis search for " << nfails
                 << " failures in " << GetTimeSinceSeconds(start_stage_time)
                 << " seconds" << endl;
            cout << "max_likelihood_this_stage: " << max_likelihood_this_stage
                 << ", max_likelihood_previous_stage: "
                 << max_likelihood_previous_stage << ",  params: " << 1 - p1
                 << " " << p2 << " " << PRIOR << endl;
        }
        nfails++;
    }
}

void BayesianNet::HypothesesUnion(set<Hypothesis *> &hypotheses_set,
                                  Hypothesis &result) {
    for (auto &ch : hypotheses_set) {
        for (int e : *ch)
            result.insert(e);
    }
}

void BayesianNet::HypothesesIntersection(set<Hypothesis *> &hypotheses_set,
                                         Hypothesis &result) {
    set<int> all_elements;
    for (auto &ch : hypotheses_set) {
        for (int e : *ch)
            all_elements.insert(e);
    }
    set<int> erase_elements;
    for (int e : all_elements) {
        for (auto &ch : hypotheses_set) {
            if (ch->find(e) == ch->end()) {
                erase_elements.insert(e);
                break;
            }
        }
    }
    for (int e : erase_elements)
        all_elements.erase(e);
    result.insert(all_elements.begin(), all_elements.end());
}

void BayesianNet::LocalizeDeviceFailures(double min_start_time_ms,
                                         double max_finish_time_ms,
                                         Hypothesis &localized_devices,
                                         int nopenmp_threads) {
    assert(!CONSIDER_DEVICE_LINK);
    LocalizeFailuresHelper(min_start_time_ms, max_finish_time_ms,
                           localized_devices, true, nopenmp_threads);
}

void BayesianNet::LocalizeFailures(double min_start_time_ms,
                                   double max_finish_time_ms,
                                   Hypothesis &localized_links,
                                   int nopenmp_threads) {
    // assert (CONSIDER_DEVICE_LINK);
    LocalizeFailuresHelper(min_start_time_ms, max_finish_time_ms,
                           localized_links, false, nopenmp_threads);
}

void BayesianNet::SearchHypothesesMisconfiguredACL(
    double min_start_time_ms, double max_finish_time_ms,
    unordered_map<Hypothesis *, double> &all_hypotheses, bool device_level,
    int nopenmp_threads) {
    Hypothesis *no_failure_hypothesis = new Hypothesis();
    all_hypotheses[no_failure_hypothesis] = 0.0;

    auto start_init_time = chrono::high_resolution_clock::now();
    vector<double> likelihood_scores;
    ComputeInitialLikelihoodsHelper(likelihood_scores, min_start_time_ms,
                                    max_finish_time_ms, device_level,
                                    nopenmp_threads);
    vector<int> top_link_ids;
    GetIndicesOfTopK(likelihood_scores, 2 * NUM_HYPOTHESIS_FOR_UNION,
                     top_link_ids, no_failure_hypothesis);
    for (int link_id : top_link_ids) {
        Hypothesis *h = new Hypothesis();
        h->insert(link_id);
        all_hypotheses[h] = likelihood_scores[link_id];
    }
}

void BayesianNet::LocalizeFailuresHelper(double min_start_time_ms,
                                         double max_finish_time_ms,
                                         Hypothesis &localized_components,
                                         bool device_level,
                                         int nopenmp_threads) {
    if (VERBOSE)
        cout << "Params: p1 " << 1.0 - p1 << " p2 " << p2 << " Prior " << PRIOR
             << " openmp threads " << nopenmp_threads << endl;
    assert(data != NULL);

    if (device_level)
        BinFlowsByDevice(max_finish_time_ms, nopenmp_threads);
    else
        BinFlowsByLinkId(max_finish_time_ms, nopenmp_threads);

    auto start_time = timer_checkpoint = chrono::high_resolution_clock::now();
    if (INPUT_FLOW_TYPE != PROBLEMATIC_FLOWS) {
        ComputeAndStoreIntermediateValues(nopenmp_threads, max_finish_time_ms);
    }
    if (VERBOSE) {
        cout << "Finished computing intermediate values in "
             << GetTimeSinceSeconds(start_time) << " seconds" << endl;
    }
    if (VERBOSE and PRINT_SCORES) {
        auto start_print_time = chrono::high_resolution_clock::now();
        // TODO DEVICE
        PrintScores(min_start_time_ms, max_finish_time_ms, device_level,
                    nopenmp_threads);
        cout << "Finished printing scores in "
             << GetTimeSinceSeconds(start_print_time) << " seconds" << endl;
    }

    unordered_map<Hypothesis *, double> all_hypotheses;
    auto start_search_time = chrono::high_resolution_clock::now();
    // assert(!device_level); SearchHypotheses(min_start_time_ms,
    // max_finish_time_ms, all_hypotheses, nopenmp_threads);
    if (MISCONFIGURED_ACL and MACL_UNION_HYPOTHESES)
        SearchHypothesesMisconfiguredACL(min_start_time_ms, max_finish_time_ms,
                                         all_hypotheses, device_level,
                                         nopenmp_threads);
    else
        SearchHypothesesJle(min_start_time_ms, max_finish_time_ms,
                            all_hypotheses, device_level, nopenmp_threads);
    // else SearchHypotheses(min_start_time_ms, max_finish_time_ms,
    // all_hypotheses, nopenmp_threads);
    vector<pair<double, Hypothesis *>> likelihood_hypotheses;
    for (auto &it : all_hypotheses) {
        likelihood_hypotheses.push_back(make_pair(it.second, it.first));
    }
    sort(likelihood_hypotheses.begin(), likelihood_hypotheses.end(),
         greater<pair<double, Hypothesis *>>());
    localized_components.clear();
    double highest_likelihood = likelihood_hypotheses[0].first;
    set<Hypothesis *> candidate_hypothesis;
    for (int i =
             min((int)likelihood_hypotheses.size(), N_MAX_K_LIKELIHOODS) - 1;
         i >= 0; i--) {
        double likelihood = likelihood_hypotheses[i].first;
        Hypothesis *hypothesis = likelihood_hypotheses[i].second;
        if (VERBOSE) {
            if (device_level)
                cout << "Likely candidate " << *hypothesis << " " << likelihood
                     << endl;
            else
                cout << "Likely candidate " << data->IdsToLinks(*hypothesis)
                     << " " << likelihood << endl;
        }
        if (highest_likelihood - likelihood <=
            1.0e-3) { // and candidate_hypothesis.size() == 0){
            candidate_hypothesis.insert(hypothesis);
            // break;
        }
    }

    localized_components.clear();
    /*
    // If multiple hypothesis have highest likelihoods, then return common
    elements in all hypothesis HypothesesIntersection(candidate_hypothesis,
    localized_components);
    */
    // If multiple hypothesis have highest likelihoods, then return union of
    // elements in all hypothesis
    HypothesesUnion(candidate_hypothesis, localized_components);

    if (MISCONFIGURED_ACL and MACL_UNION_HYPOTHESES)
        UnionTopHypothesis(likelihood_hypotheses, NUM_HYPOTHESIS_FOR_UNION,
                           localized_components);

    if (VERBOSE) {
        cout << endl
             << "Searched hypothesis space in "
             << GetTimeSinceSeconds(start_search_time) << " seconds" << endl;
        PrintCorrectHypothesisLikelihood(min_start_time_ms, max_finish_time_ms,
                                         localized_components, device_level,
                                         nopenmp_threads);
        if (!device_level) {
            // Only for link level localization
            // VerifyLikelihoodComputation(all_hypotheses, min_start_time_ms,
            //                            max_finish_time_ms, nopenmp_threads);
        }
    }
    CleanUpAfterLocalization(all_hypotheses);
    if (VERBOSE) {
        cout << "Finished further search in "
             << GetTimeSinceSeconds(timer_checkpoint) << " seconds" << endl;
    }
}

void BayesianNet::UnionTopHypothesis(
    vector<pair<double, Hypothesis *>> &likelihood_hypotheses, int K,
    Hypothesis &result) {
    result.clear();
    // assuming likelihood hypotheses is sorted in decreasing order
    for (int i = 0; i < likelihood_hypotheses.size(); i++) {
        double likelihood = likelihood_hypotheses[i].first;
        Hypothesis *hypothesis = likelihood_hypotheses[i].second;
        for (int link_id : *hypothesis) {
            if (result.size() < K)
                result.insert(link_id);
        }
    }
}

void BayesianNet::PrintCorrectHypothesisLikelihood(
    double min_start_time_ms, double max_finish_time_ms,
    Hypothesis &localized_components, bool device_level, int nopenmp_threads) {
    Hypothesis correct_hypothesis;
    if (device_level)
        data->GetFailedDevices(correct_hypothesis);
    else
        data->GetFailedLinkIds(correct_hypothesis);
    Hypothesis *no_failure_hypothesis = new Hypothesis();
    double likelihood_correct_hypothesis = ComputeLogLikelihoodHelper(
        &correct_hypothesis, no_failure_hypothesis, 0.0, min_start_time_ms,
        max_finish_time_ms, device_level, nopenmp_threads);
    if (PRINT_SCORES) {
        for (int cmp : localized_components) {
            Hypothesis single_component_hypothesis = {cmp};
            double l = ComputeLogLikelihoodHelper(
                &single_component_hypothesis, no_failure_hypothesis, 0.0,
                min_start_time_ms, max_finish_time_ms, device_level,
                nopenmp_threads);
            // TODO DEVICE
            // cout << "Score of predicted failed component " <<
            // data->inverse_links[link_id]
            //     << " score " << drops_per_component[link_id] << " E[nflows] "
            //     << flows_per_component[link_id] << " likelihood " << l <<
            //     endl;
        }
    }
    if (device_level)
        cout << "Correct Hypothesis " << correct_hypothesis << " likelihood "
             << likelihood_correct_hypothesis << endl;
    else
        cout << "Correct Hypothesis " << data->IdsToLinks(correct_hypothesis)
             << " likelihood " << likelihood_correct_hypothesis << endl;
    delete (no_failure_hypothesis);
}

bool BayesianNet::VerifyLikelihoodComputation(
    unordered_map<Hypothesis *, double> &all_hypothesis,
    double min_start_time_ms, double max_finish_time_ms, int nopenmp_threads) {
    int ctr = 0;
    Hypothesis *no_failure_hypothesis = new Hypothesis();
    bool result = true;
    int ctr_network = 0;
    for (auto &[hypothesis_ptr, likelihood] : all_hypothesis) {
        if (ctr++ % 10000 == 0)
            cout << "Finished verifying " << (ctr - 1) << " hypotheses" << endl;
        for (int link_id : *hypothesis_ptr) {
            if (data->inverse_links[link_id].first < 10000 and
                data->inverse_links[link_id].second < 10000) {
                ctr_network++;
                break;
            }
        }
        double vanilla = ComputeLogLikelihood(
            hypothesis_ptr, no_failure_hypothesis, 0.0, min_start_time_ms,
            max_finish_time_ms, nopenmp_threads);
        if (abs((vanilla - likelihood) / vanilla) > 1.0e-3 or
            abs(vanilla - likelihood) > 0.001) {
            cout << "Violating hypothesis " << data->IdsToLinks(*hypothesis_ptr)
                 << " " << likelihood << " != " << vanilla << endl;
            result = false;
        }
    }
    cout << "Finished verifying " << ctr << " hypotheses" << endl;
    cout << "Finished verifying " << ctr_network << " network hypotheses"
         << endl;
    delete (no_failure_hypothesis);
    return result;
}

void BayesianNet::GetIndicesOfTopK(vector<double> &scores, int k,
                                   vector<int> &result, Hypothesis *exclude, bool device_only) {
    typedef pair<double, int> PDI;
    priority_queue<PDI, vector<PDI>, greater<PDI>> min_q;
    for (int i = 0; i < scores.size(); ++i) {
        if (exclude->find(i) == exclude->end() and (!device_only or data->IsLinkDevice(i))) {
            min_q.push(PDI(scores[i], i));
        }
        if (min_q.size() > k) {
            min_q.pop();
        }
    }
    assert(result.size() == 0);
    result.reserve(min_q.size());
    while (!min_q.empty()) {
        auto [score, ind] = min_q.top();
        result.push_back(ind);
        min_q.pop();
    }
}

void BayesianNet::AddContributionsFromThreads(vector<double> *contributions,
                                              vector<double> &result,
                                              int nopenmp_threads) {
    int ncomponents = contributions[0].size();
    for (int t = 0; t < nopenmp_threads; t++)
        assert(contributions[t].size() == ncomponents);
#pragma omp parallel for num_threads(nopenmp_threads)
    for (int cmp = 0; cmp < ncomponents; cmp++) {
        //! TODO: Try changing 2d array from (threads X components) to
        //! (components X threads)
        for (int t = 0; t < nopenmp_threads; t++) {
            result[cmp] += contributions[t][cmp];
        }
    }
}

int BayesianNet::UpdateScores(vector<double> &likelihood_scores,
                              Hypothesis *hypothesis,
                              Hypothesis *base_hypothesis,
                              double min_start_time_ms,
                              double max_finish_time_ms, int nopenmp_threads) {
    int nlinks = data->inverse_links.size();
    vector<double> likelihood_scores_thread[nopenmp_threads];
    vector<short int> link_ctrs_threads[nopenmp_threads];
    vector<short int> link_ctrs_threads_base[nopenmp_threads];
#pragma omp parallel for num_threads(nopenmp_threads)
    for (int t = 0; t < nopenmp_threads; t++) {
        likelihood_scores_thread[t].resize(nlinks, 0.0);
        link_ctrs_threads[t].resize(nlinks, 0);
        link_ctrs_threads_base[t].resize(nlinks, 0);
    }
    auto start_init_time = chrono::high_resolution_clock::now();
    vector<int> relevant_flows;

    bool hypothesis_link_bitmap[nlinks] = {false};
    for (int cmp : *hypothesis)
        hypothesis_link_bitmap[cmp] = true;
    bool base_hypothesis_link_bitmap[nlinks] = {false};
    for (int cmp : *base_hypothesis)
        base_hypothesis_link_bitmap[cmp] = true;

    GetRelevantFlows(hypothesis, base_hypothesis, min_start_time_ms,
                     max_finish_time_ms, relevant_flows);
#pragma omp parallel for num_threads(nopenmp_threads) if (nopenmp_threads > 1)
    for (int ii = 0; ii < relevant_flows.size(); ii++) {
        int thread_num = omp_get_thread_num();
        Flow *flow = data->flows[relevant_flows[ii]];
        if (DiscardFlow(flow, min_start_time_ms, max_finish_time_ms))
            continue;
        vector<Path *> *flow_paths = flow->GetPaths(max_finish_time_ms);
        int npaths = flow_paths->size();
        if (REDUCED_ANALYSIS) {
            assert(npaths == 1);
            npaths = flow->npaths_unreduced;
        }
        //! TODO: implement REVERSE_PATH case
        int npaths_r = 1, naffected_r = 0, naffected_r_base = 0;
        if constexpr (CONSIDER_REVERSE_PATH) {
            assert(false);
        }
        PII weight = flow->LabelWeightsFunc(max_finish_time_ms);
        if (weight.first == 0 and weight.second == 0)
            continue;

        int end_failed_links = (hypothesis->count(flow->first_link_id) > 0) +
                               (hypothesis->count(flow->last_link_id) > 0);
        int end_failed_links_base =
            (base_hypothesis->count(flow->first_link_id) > 0) +
            (base_hypothesis->count(flow->last_link_id) > 0);

        int npaths_failed = 0, npaths_failed_base = 0;
        vector<int> npaths_failed_exclude_end_link = {0, 0};
        vector<int> npaths_failed_exclude_end_link_base = {0, 0};
        vector<int> end_links = {flow->first_link_id, flow->last_link_id};

        npaths_failed += UpdateScoresPopulateCounters(
            flow_paths, hypothesis, end_failed_links, end_links,
            npaths_failed_exclude_end_link, link_ctrs_threads[thread_num],
            hypothesis_link_bitmap);
        npaths_failed_base += UpdateScoresPopulateCounters(
            flow_paths, base_hypothesis, end_failed_links_base, end_links,
            npaths_failed_exclude_end_link_base,
            link_ctrs_threads_base[thread_num], base_hypothesis_link_bitmap);

        //! TODO: reduced analysis can be made cleaner and more robust
        if (REDUCED_ANALYSIS and end_failed_links > 0)
            npaths_failed = npaths;
        long double intermediate_val = flow->GetCachedIntermediateValue();
        double no_failure_score =
            BnfWeighted(npaths_failed, npaths, naffected_r, npaths_r,
                        weight.first, weight.second, intermediate_val);
        double no_failure_score_base =
            BnfWeighted(npaths_failed_base, npaths, naffected_r_base, npaths_r,
                        weight.first, weight.second, intermediate_val);
        for (Path *path : *flow_paths) {
            for (int link_id : *path) {
                int naffected = link_ctrs_threads[thread_num][link_id];
                int naffected_base =
                    link_ctrs_threads_base[thread_num][link_id];
                if (naffected != 0 or naffected_base != 0) {
                    double diff =
                        BnfWeighted(naffected + npaths_failed, npaths,
                                    naffected_r, npaths_r, weight.first,
                                    weight.second, intermediate_val);
                    diff -=
                        BnfWeighted(naffected_base + npaths_failed_base, npaths,
                                    naffected_r_base, npaths_r, weight.first,
                                    weight.second, intermediate_val);
                    diff -= (no_failure_score - no_failure_score_base);
                    likelihood_scores_thread[thread_num][link_id] += diff;
                    // Reset counter so that likelihood for link_id isn't
                    // counted again
                    link_ctrs_threads[thread_num][link_id] = 0;
                    link_ctrs_threads_base[thread_num][link_id] = 0;
                }
            }
        }

        // For the first and last links that are common to all paths
        int naffected = npaths;
        double log_likelihood =
            BnfWeighted(naffected, npaths, naffected_r, npaths_r, weight.first,
                        weight.second, intermediate_val);

        // For the first and last links that are common to all paths
        for (int ee = 0; ee < end_links.size(); ee++) {
            double diff = -(no_failure_score - no_failure_score_base);
            if (hypothesis_link_bitmap[end_links[ee]])
                diff += BnfWeighted(npaths_failed_exclude_end_link[ee], npaths,
                                    naffected_r, npaths_r, weight.first,
                                    weight.second, intermediate_val);
            else
                diff += log_likelihood;
            if (base_hypothesis_link_bitmap[end_links[ee]])
                diff -=
                    BnfWeighted(npaths_failed_exclude_end_link_base[ee], npaths,
                                naffected_r_base, npaths_r, weight.first,
                                weight.second, intermediate_val);
            else
                diff -= log_likelihood;
            likelihood_scores_thread[thread_num][end_links[ee]] += diff;
        }
    }
    AddContributionsFromThreads(likelihood_scores_thread, likelihood_scores,
                                nopenmp_threads);
    return relevant_flows.size();
}

// Return value for logging purposes
int BayesianNet::UpdateScoresDevice(vector<double> &likelihood_scores,
                                    Hypothesis *hypothesis,
                                    Hypothesis *base_hypothesis,
                                    double min_start_time_ms,
                                    double max_finish_time_ms,
                                    int nopenmp_threads) {
    int ndevices = GetNumComponents(true);
    vector<double> likelihood_scores_thread[nopenmp_threads];
    vector<short int> device_ctrs_threads[nopenmp_threads];
    vector<short int> device_ctrs_threads_base[nopenmp_threads];
#pragma omp parallel for num_threads(nopenmp_threads)
    for (int t = 0; t < nopenmp_threads; t++) {
        likelihood_scores_thread[t].resize(ndevices, 0.0);
        device_ctrs_threads[t].resize(ndevices, 0);
        device_ctrs_threads_base[t].resize(ndevices, 0);
    }
    auto start_init_time = chrono::high_resolution_clock::now();
    vector<int> relevant_flows;

    bool hypothesis_component_bitmap[ndevices] = {false};
    for (int cmp : *hypothesis)
        hypothesis_component_bitmap[cmp] = true;
    bool base_hypothesis_component_bitmap[ndevices] = {false};
    for (int cmp : *base_hypothesis)
        base_hypothesis_component_bitmap[cmp] = true;

    GetRelevantFlowsHelper(hypothesis, base_hypothesis, min_start_time_ms,
                           max_finish_time_ms, relevant_flows, true);
#pragma omp parallel for num_threads(nopenmp_threads) if (nopenmp_threads > 1)
    for (int ii = 0; ii < relevant_flows.size(); ii++) {
        int thread_num = omp_get_thread_num();
        Flow *flow = data->flows[relevant_flows[ii]];
        if (DiscardFlow(flow, min_start_time_ms, max_finish_time_ms))
            continue;
        vector<Path *> *flow_paths = flow->GetPaths(max_finish_time_ms);
        int npaths = flow_paths->size();
        if (REDUCED_ANALYSIS) {
            assert(npaths == 1);
            npaths = flow->npaths_unreduced;
        }
        //! TODO: implement REVERSE_PATH case
        int npaths_r = 1, naffected_r = 0, naffected_r_base = 0;
        if constexpr (CONSIDER_REVERSE_PATH) {
            assert(false);
        }
        PII weight = flow->LabelWeightsFunc(max_finish_time_ms);
        if (weight.first == 0 and weight.second == 0)
            continue;

        int npaths_failed = 0, npaths_failed_base = 0;
        npaths_failed += UpdateScoresDevicePopulateCounters(
            flow, flow_paths, hypothesis, device_ctrs_threads[thread_num],
            hypothesis_component_bitmap);
        npaths_failed_base += UpdateScoresDevicePopulateCounters(
            flow, flow_paths, base_hypothesis,
            device_ctrs_threads_base[thread_num],
            base_hypothesis_component_bitmap);

        long double intermediate_val = flow->GetCachedIntermediateValue();
        double no_failure_score =
            BnfWeighted(npaths_failed, npaths, naffected_r, npaths_r,
                        weight.first, weight.second, intermediate_val);
        double no_failure_score_base =
            BnfWeighted(npaths_failed_base, npaths, naffected_r_base, npaths_r,
                        weight.first, weight.second, intermediate_val);
        Path device_path;
        for (Path *link_path : *flow_paths) {
            data->GetDeviceLevelPath(flow, *link_path, device_path);
            for (int device : device_path) {
                int naffected = device_ctrs_threads[thread_num][device];
                int naffected_base =
                    device_ctrs_threads_base[thread_num][device];
                if (naffected != 0 or naffected_base != 0) {
                    double diff =
                        BnfWeighted(naffected + npaths_failed, npaths,
                                    naffected_r, npaths_r, weight.first,
                                    weight.second, intermediate_val);
                    diff -=
                        BnfWeighted(naffected_base + npaths_failed_base, npaths,
                                    naffected_r_base, npaths_r, weight.first,
                                    weight.second, intermediate_val);
                    diff -= (no_failure_score - no_failure_score_base);
                    likelihood_scores_thread[thread_num][device] += diff;
                    // Reset counter so that likelihood for device isn't counted
                    // again
                    device_ctrs_threads[thread_num][device] = 0;
                    device_ctrs_threads_base[thread_num][device] = 0;
                }
            }
        }
    }
    AddContributionsFromThreads(likelihood_scores_thread, likelihood_scores,
                                nopenmp_threads);
    return relevant_flows.size();
}

int BayesianNet::UpdateScoresPopulateCounters(
    vector<Path *> *flow_paths, Hypothesis *hypothesis, int end_failed_links,
    vector<int> &end_links, vector<int> &npaths_failed_exclude_end_link,
    vector<short int> &link_ctrs_threads, bool *hypothesis_link_bitmap) {
    int npaths_failed = 0;
    for (Path *path : *flow_paths) {
        int failed_links_in_path =
            NumIntersectionsHypothesisPath(hypothesis, path) + end_failed_links;
        for (int ee = 0; ee < end_links.size(); ee++) {
            npaths_failed_exclude_end_link[ee] +=
                (int)(failed_links_in_path -
                          hypothesis_link_bitmap[end_links[ee]] >
                      0);
        }
        npaths_failed += (int)(failed_links_in_path > 0);
        for (int link_id : *path) {
            if (hypothesis_link_bitmap[link_id]) // path will become unfailed if
                                                 // only this link causes it to
                                                 // fail
                link_ctrs_threads[link_id] -= (int)(failed_links_in_path == 1);
            else
                link_ctrs_threads[link_id] += (int)(failed_links_in_path == 0);
        }
    }
    return npaths_failed;
}

int BayesianNet::UpdateScoresDevicePopulateCounters(
    Flow *flow, vector<Path *> *flow_paths, Hypothesis *hypothesis,
    vector<short int> &device_ctrs_threads, bool *hypothesis_link_bitmap) {
    int npaths_failed = 0;
    Path device_path;
    for (Path *link_path : *flow_paths) {
        data->GetDeviceLevelPath(flow, *link_path, device_path);
        int failed_links_in_path =
            NumIntersectionsHypothesisPath(hypothesis, &device_path);
        npaths_failed += (int)(failed_links_in_path > 0);
        for (int device : device_path) {
            if (hypothesis_link_bitmap[device]) // path will become unfailed if
                                                // only this device causes it to
                                                // fail
                device_ctrs_threads[device] -= (int)(failed_links_in_path == 1);
            else
                device_ctrs_threads[device] += (int)(failed_links_in_path == 0);
        }
    }
    return npaths_failed;
}

void BayesianNet::FlipLinkId(Hypothesis *hypothesis, int link_id) {
    if (hypothesis->find(link_id) == hypothesis->end())
        hypothesis->insert(link_id);
    else
        hypothesis->erase(link_id);
}

void BayesianNet::SearchHypothesesGibbsSampling(
    double min_start_time_ms, double max_finish_time_ms,
    unordered_map<Hypothesis *, double> &all_hypothesis, int nopenmp_threads) {
    // start with no_failure hypothesis
    Hypothesis *current_hypothesis = new Hypothesis();
    double current_likelihood = 0.0;
    all_hypothesis[current_hypothesis] = current_likelihood;

    vector<double> likelihood_scores, other_likelihood_scores;

    auto start_init_time = chrono::high_resolution_clock::now();
    ComputeInitialLikelihoods(likelihood_scores, min_start_time_ms,
                              max_finish_time_ms, nopenmp_threads);
    int niter = 0, num_flows_analyzed = 0;
    srand(time(NULL));
    while (niter++ < GIBBS_SAMPLING_ITERATIONS) {
        int link_id = rand() % data->inverse_links.size();
        // int link_id = niter%data->inverse_links.size();
        Hypothesis *new_hypothesis = new Hypothesis(*current_hypothesis);
        FlipLinkId(new_hypothesis, link_id);
        double new_likelihood = ComputeLogLikelihood(
            new_hypothesis, current_hypothesis, current_likelihood,
            min_start_time_ms, max_finish_time_ms, nopenmp_threads);
        double prob_x = exp(current_likelihood -
                            new_likelihood); // more resilient to overflow
        double prob_not_x = 1;
        // normalize
        double sum_prob = prob_x + prob_not_x;
        prob_x /= sum_prob;
        prob_not_x /= sum_prob;
        // cout << " prob. " << prob_x << " " << prob_not_x << endl;
        if (niter % 100 == 0)
            cout << "niter " << niter << " " << prob_x << " " << prob_not_x
                 << " " << current_likelihood << " " << new_likelihood << endl;
        if (float(rand()) / RAND_MAX < prob_not_x) {
            if (VERBOSE) {
                cout << "Updating link " << link_id << " current likelihood "
                     << current_likelihood << " new likelihood "
                     << new_likelihood << " new diff "
                     << likelihood_scores[link_id] << " current-hypothesis "
                     << *current_hypothesis << " iterations " << niter << endl;
            }
            all_hypothesis[new_hypothesis] = new_likelihood;
            current_hypothesis = new_hypothesis;
            current_likelihood = new_likelihood;
        } else {
            delete (new_hypothesis);
        }
    }
}

void BayesianNet::SearchHypothesesGibbsSamplingJLE(
    double min_start_time_ms, double max_finish_time_ms,
    unordered_map<Hypothesis *, double> &all_hypothesis, int nopenmp_threads) {
    // start with no_failure hypothesis
    Hypothesis *current_hypothesis = new Hypothesis();
    double current_likelihood = 0.0;
    all_hypothesis[current_hypothesis] = current_likelihood;

    vector<double> likelihood_scores, other_likelihood_scores;

    auto start_init_time = chrono::high_resolution_clock::now();
    ComputeInitialLikelihoods(likelihood_scores, min_start_time_ms,
                              max_finish_time_ms, nopenmp_threads);
    int niter = 0, num_flows_analyzed = 0;
    srand(time(NULL));
    while (niter++ < GIBBS_SAMPLING_ITERATIONS) {
        int link_id = rand() % data->inverse_links.size();
        // int link_id = niter%data->inverse_links.size();
        double old_log_prior = ComputeLogPrior(current_hypothesis);
        FlipLinkId(current_hypothesis, link_id);
        double new_log_prior = ComputeLogPrior(current_hypothesis);
        double new_likelihood = current_likelihood +
                                likelihood_scores[link_id] + new_log_prior -
                                old_log_prior;
        double prob_x = exp(current_likelihood -
                            new_likelihood); // more resilient to overflow
        double prob_not_x = 1;
        // normalize
        double sum_prob = prob_x + prob_not_x;
        prob_x /= sum_prob;
        prob_not_x /= sum_prob;
        // cout << " prob. " << prob_x << " " << prob_not_x << endl;
        if (link_id % 10000 == 0)
            cout << "niter " << niter << " " << prob_x << " " << prob_not_x
                 << " " << current_likelihood << " " << new_likelihood << endl;
        if (float(rand()) / RAND_MAX < prob_not_x) {
            Hypothesis *new_hypothesis = new Hypothesis(*current_hypothesis);
            FlipLinkId(current_hypothesis, link_id);
            if (VERBOSE) {
                cout << "Updating link " << link_id << " current likelihood "
                     << current_likelihood << " new likelihood "
                     << new_likelihood << " new diff "
                     << likelihood_scores[link_id] << " current-hypothesis "
                     << *current_hypothesis << " iterations " << niter << endl;
            }
            num_flows_analyzed += UpdateScores(
                likelihood_scores, new_hypothesis, current_hypothesis,
                min_start_time_ms, max_finish_time_ms, nopenmp_threads);
            /*
            if (VERBOSE){
                cout << "Updating link " << link_id << " current likelihood " <<
            current_likelihood
                     << " new likelihood " << new_likelihood << " new diff " <<
            likelihood_scores[link_id]
                     << " current-hypothesis " << *current_hypothesis << "
            iterations " << niter << endl;
            }
            */
            all_hypothesis[new_hypothesis] = new_likelihood;
            current_hypothesis = new_hypothesis;
            current_likelihood = new_likelihood;
        } else {
            FlipLinkId(current_hypothesis, link_id);
        }
    }
}

void BayesianNet::PrintScores(double min_start_time_ms,
                              double max_finish_time_ms, bool device_level,
                              int nopenmp_threads) {
    int ncomponents = GetNumComponents(device_level);
    vector<double> scores1[nopenmp_threads];
    vector<double> scores2[nopenmp_threads];
    vector<double> nflows_threads[nopenmp_threads];
    vector<short int> component_ctrs_threads[nopenmp_threads];
#pragma omp parallel for num_threads(nopenmp_threads)
    for (int t = 0; t < nopenmp_threads; t++) {
        scores1[t].resize(ncomponents, 0.0);
        scores2[t].resize(ncomponents, 0.0);
        nflows_threads[t].resize(ncomponents, 0.0);
        component_ctrs_threads[t].resize(ncomponents, 0);
    }
#pragma omp parallel for num_threads(nopenmp_threads)
    for (int ii = 0; ii < data->flows.size(); ii++) {
        Flow *flow = data->flows[ii];
        if (DiscardFlow(flow, min_start_time_ms, max_finish_time_ms))
            continue;
        int thread_num = omp_get_thread_num();
        vector<Path *> *flow_paths = flow->GetPaths(max_finish_time_ms);
        int npaths = flow_paths->size();
        if (REDUCED_ANALYSIS)
            npaths = flow->npaths_unreduced;
        //! TODO: implement REVERSE_PATH case
        int npaths_r = 1, naffected_r = 0;
        if constexpr (CONSIDER_REVERSE_PATH) {
            assert(false);
        }
        PII weight = flow->LabelWeightsFunc(max_finish_time_ms);
        if (weight.first == 0 and weight.second == 0)
            continue;

        if (!device_level) {
            nflows_threads[thread_num][flow->first_link_id] += 1;
            nflows_threads[thread_num][flow->last_link_id] += 1;
            scores1[thread_num][flow->first_link_id] += weight.first;
            scores2[thread_num][flow->first_link_id] += weight.second;
            scores1[thread_num][flow->last_link_id] += weight.first;
            scores2[thread_num][flow->last_link_id] += weight.second;
        }
        /*
        if (flow->dest == 10278){
            flow->PrintFlowMetrics();
            cout << "weights " << weight.first << " " << weight.second << endl;
        }
        */
        // cout << "npaths " << npaths << endl;
        Path device_path, *path_ptr;
        for (Path *link_path : *flow_paths) {
            path_ptr =
                PathPointerSelect(flow, *link_path, device_path, device_level);
            for (int cmp : *path_ptr) {
                component_ctrs_threads[thread_num][cmp]++;
            }
        }
        for (Path *link_path : *flow_paths) {
            path_ptr =
                PathPointerSelect(flow, *link_path, device_path, device_level);
            for (int cmp : *path_ptr) {
                int naffected = component_ctrs_threads[thread_num][cmp];
                if (naffected > 0) {
                    nflows_threads[thread_num][cmp] +=
                        ((double)naffected) / npaths;
                    scores1[thread_num][cmp] +=
                        (double)((weight.first + weight.second) * naffected) / npaths;
                    scores2[thread_num][cmp] += weight.second;
                }
                // Reset counter so that likelihood for cmp isn't counted again
                component_ctrs_threads[thread_num][cmp] = 0;
            }
        }
    }
    drops_per_component.resize(ncomponents, 0.0);
    flows_per_component.resize(ncomponents, 0.0);

    auto GetScore = [&scores1, &scores2, nopenmp_threads](int cmp) {
        double score1 = 0, score2 = 0;
        for (int t = 0; t < nopenmp_threads; t++) {
            score1 += scores1[t][cmp];
            score2 += scores2[t][cmp];
        }
        return tuple(score2, score1);
    };
#pragma omp parallel for num_threads(nopenmp_threads)
    for (int cmp = 0; cmp < ncomponents; cmp++) {
        //! TODO: Try changing likelihoods 2d array from (threads X links) to
        //! (links X threads)
        auto [score2, score1] = GetScore(cmp);
        drops_per_component[cmp] = score2 / max(1.0e-30, score1);
        double f = 0.0;
        for (int t = 0; t < nopenmp_threads; t++) {
            f += nflows_threads[t][cmp];
        }
        flows_per_component[cmp] = f;
    }
    vector<int> idx(drops_per_component.size());
    iota(idx.begin(), idx.end(), 0);
    sort(idx.begin(), idx.end(), [this](int i1, int i2) {
        return (abs(drops_per_component[i1] - drops_per_component[i2]) < 1.0e-6
                    ? false
                    : (drops_per_component[i1] < drops_per_component[i2]));
    });
    for (int ii = max(0, (int)idx.size() - 1000); ii < idx.size(); ii++) {
        int cmp = idx[ii];
        auto [score2, score1] = GetScore(cmp);
        if (flows_per_component[cmp] > 0) {
            if (device_level)
                cout << "Device " << cmp;
            else
                cout << "Link " << data->inverse_links[cmp];
            cout << " " << score2 << " " << score1 << " "
                 << drops_per_component[cmp] << " E[nflows] "
                 << flows_per_component[cmp] << endl;
        }
    }
    if (device_level) {
        for (auto [device, failparam] : data->failed_devices) {
            auto [score2, score1] = GetScore(device);
            cout << "Failed Device " << device << " " << score2 << " " << score1
                 << " " << drops_per_component[device] << " E[nflows] "
                 << flows_per_component[device] << endl;
        }
    } else {
        for (auto [link, failparam] : data->failed_links) {
            int link_id = data->links_to_ids[link];
            auto [score2, score1] = GetScore(link_id);
            cout << "Failed Link " << link << " " << score2 << " " << score1
                 << " " << drops_per_component[link_id] << " E[nflows] "
                 << flows_per_component[link_id] << endl;
        }
    }
}

void BayesianNet::ComputeInitialLikelihoods(vector<double> &initial_likelihoods,
                                            double min_start_time_ms,
                                            double max_finish_time_ms,
                                            int nopenmp_threads) {
    ComputeInitialLikelihoodsHelper(initial_likelihoods, min_start_time_ms,
                                    max_finish_time_ms, false, nopenmp_threads);
}

Path *BayesianNet::PathPointerSelect(Flow *flow, Path &link_path,
                                     Path &device_path_unfilled,
                                     bool device_level) {
    if (device_level) {
        data->GetDeviceLevelPath(flow, link_path, device_path_unfilled);
        return &device_path_unfilled;
    } else
        return &link_path;
}

void BayesianNet::ComputeInitialLikelihoodsHelper(
    vector<double> &initial_likelihoods, double min_start_time_ms,
    double max_finish_time_ms, bool device_level, int nopenmp_threads) {
    int ncomponents = GetNumComponents(device_level);
    vector<double> likelihoods[nopenmp_threads];
    vector<short int> component_ctrs_threads[nopenmp_threads];
#pragma omp parallel for num_threads(nopenmp_threads)
    for (int t = 0; t < nopenmp_threads; t++) {
        likelihoods[t].resize(ncomponents, 0.0);
        component_ctrs_threads[t].resize(ncomponents, 0);
    }
#pragma omp parallel for num_threads(nopenmp_threads)
    for (int ii = 0; ii < data->flows.size(); ii++) {
        Flow *flow = data->flows[ii];
        if (DiscardFlow(flow, min_start_time_ms, max_finish_time_ms))
            continue;
        int thread_num = omp_get_thread_num();
        vector<Path *> *flow_paths = flow->GetPaths(max_finish_time_ms);
        int npaths = flow_paths->size();
        if (REDUCED_ANALYSIS)
            npaths = flow->npaths_unreduced;
        //! TODO: implement REVERSE_PATH case
        int npaths_r = 1, naffected_r = 0;
        if constexpr (CONSIDER_REVERSE_PATH) {
            assert(false);
        }
        PII weight = flow->LabelWeightsFunc(max_finish_time_ms);
        if (weight.first == 0 and weight.second == 0)
            continue;
        Path device_path, *path_ptr;
        for (Path *link_path : *flow_paths) {
            path_ptr =
                PathPointerSelect(flow, *link_path, device_path, device_level);
            for (int component : *path_ptr) {
                component_ctrs_threads[thread_num][component]++;
            }
        }
        long double intermediate_val = flow->GetCachedIntermediateValue();
        for (Path *link_path : *flow_paths) {
            path_ptr =
                PathPointerSelect(flow, *link_path, device_path, device_level);
            for (int cmp : *path_ptr) {
                int naffected = component_ctrs_threads[thread_num][cmp];
                if (naffected > 0) {
                    likelihoods[thread_num][cmp] += BnfWeighted(
                        naffected, npaths, naffected_r, npaths_r, weight.first,
                        weight.second, intermediate_val);
                }
                // Reset counter so that likelihood for component isn't counted
                // again
                component_ctrs_threads[thread_num][cmp] = 0;
            }
        }

        if (not device_level) {
            // For the first and last links that are common to all paths
            int naffected = npaths;
            // if (REDUCED_ANALYSIS) naffected = npaths;
            double log_likelihood =
                BnfWeighted(naffected, npaths, naffected_r, npaths_r,
                            weight.first, weight.second, intermediate_val);
            if (false and log_likelihood > 1.0e6) {
                cout << "Likelihood computation precision bug ";
                cout << naffected << " " << npaths << " " << naffected_r << " "
                     << npaths_r << " " << weight.first << " " << weight.second
                     << " " << intermediate_val << " " << p1 << " " << p2 << " "
                     << PRIOR << " " << log_likelihood << endl;
                //! TODO; TODO: TODO
                assert(false);
            }
            likelihoods[thread_num][flow->first_link_id] += log_likelihood;
            likelihoods[thread_num][flow->last_link_id] += log_likelihood;
        }
    }

    initial_likelihoods.resize(ncomponents, 0.0);
    AddContributionsFromThreads(likelihoods, initial_likelihoods,
                                nopenmp_threads);
#pragma omp parallel for num_threads(nopenmp_threads)
    for (int cmp = 0; cmp < ncomponents; cmp++) {
        initial_likelihoods[cmp] += ComputeLogPrior(cmp);
    }
}

void BayesianNet::ComputeSingleLinkLogLikelihood(
    vector<pair<double, Hypothesis *>> &result, double min_start_time_ms,
    double max_finish_time_ms, int nopenmp_threads) {
    int nlinks = data->inverse_links.size();
    vector<double> initial_likelihoods;
    ComputeInitialLikelihoods(initial_likelihoods, min_start_time_ms,
                              max_finish_time_ms, nopenmp_threads);
    result.resize(nlinks);
    for (int link_id = 0; link_id < nlinks; link_id++) {
        Hypothesis *h = new Hypothesis();
        h->insert(link_id);
        double likelihood = initial_likelihoods[link_id];
        // likelihood += ComputeLogPrior(h);
        result[link_id] = make_pair(likelihood, h);
    }
}

void BayesianNet::ComputeLogLikelihood(
    vector<Hypothesis *> &hypothesis_space,
    vector<pair<Hypothesis *, double>> &base_hypothesis_likelihood,
    vector<pair<double, Hypothesis *>> &result, double min_start_time_ms,
    double max_finish_time_ms, int nopenmp_threads) {
    auto start_time = chrono::high_resolution_clock::now();
    result.resize(hypothesis_space.size());
    vector<vector<int>> relevant_flows;
    relevant_flows.resize(hypothesis_space.size());
#pragma omp parallel for num_threads(nopenmp_threads)
    for (int i = 0; i < hypothesis_space.size(); i++) {
        // if (i%10000 == 0) cout << "Finished relevant flows population " << i
        // << endl;
        Hypothesis *h = hypothesis_space[i];
        auto &base = base_hypothesis_likelihood[i];
        GetRelevantFlows(h, base.first, min_start_time_ms, max_finish_time_ms,
                         relevant_flows[i]);
    }
    // cout << "Finished populating relevant flows in " <<
    // GetTimeSinceSeconds(start_time) << " seconds" << endl;
    int total_flows_analyzed = 0;
    for (int i = 0; i < hypothesis_space.size(); i++) {
        // if (i%10000 == 0) cout << "Finished hypothesis space " << i << "
        // after " << GetTimeSinceSeconds(start_time) << " sconds" << endl;
        Hypothesis *h = hypothesis_space[i];
        auto &base = base_hypothesis_likelihood[i];
        result[i] = pair<double, Hypothesis *>(
            ComputeLogLikelihood(h, base.first, base.second, min_start_time_ms,
                                 max_finish_time_ms, relevant_flows[i],
                                 nopenmp_threads),
            h);
        total_flows_analyzed += relevant_flows[i].size();
    }
    if (VERBOSE) {
        // cout << "Finished computing log likelihood in " <<
        // GetTimeSinceSeconds(start_time)
        //     << " numhypo " << hypothesis_space.size() << endl;
        // cout << "Total flows analyzed "<< total_flows_analyzed << " ";
    }
}

inline double BayesianNet::BnfWeighted(int naffected, int npaths,
                                       int naffected_r, int npaths_r,
                                       double weight_good, double weight_bad) {
    if (INPUT_FLOW_TYPE == PROBLEMATIC_FLOWS)
        return BnfWeightedConditional(naffected, npaths, naffected_r, npaths_r,
                                      weight_good, weight_bad);
    else
        return BnfWeightedUnconditional(naffected, npaths, naffected_r,
                                        npaths_r, weight_good, weight_bad);
}

inline double BayesianNet::BnfWeighted(int naffected, int npaths,
                                       int naffected_r, int npaths_r,
                                       double weight_good, double weight_bad,
                                       long double intermediate_val) {
    if (INPUT_FLOW_TYPE == PROBLEMATIC_FLOWS)
        return BnfWeightedConditional(naffected, npaths, naffected_r, npaths_r,
                                      weight_good, weight_bad);
    else
        return BnfWeightedUnconditionalIntermediate(
            naffected, npaths, naffected_r, npaths_r, intermediate_val);
}

inline double BayesianNet::BnfWeightedConditional(int naffected, int npaths,
                                                  int naffected_r, int npaths_r,
                                                  double weight_good,
                                                  double weight_bad) {
    //! TODO: change temporary!
    return BnfWeightedUnconditional(naffected, npaths, naffected_r, npaths_r,
                                    weight_good, weight_bad);
    // e2e: end-to-end
    int e2e_paths = npaths * npaths_r;
    int e2e_failed_paths =
        e2e_paths - (npaths - naffected) * (npaths_r - naffected_r);
    assert(e2e_paths == 1);
    double a = ((double)(e2e_paths - e2e_failed_paths)) / e2e_paths;
    double b = ((double)e2e_failed_paths) / e2e_paths;
    //! TODO TODO TODO: precision goes out of long double range
    long double ival = pow((long double)((1.0 - p1) / p2), weight_bad) *
                       pow(p1 / (1.0 - p2), weight_good);
    // ival = min(ival,  std::numeric_limits<long double>::max());
    long double val1 = a + b * ival;
    double total_weight = weight_good + weight_bad;
    double val2 = a + b * (1 - pow(p1, total_weight)) /
                          (1.0 - pow((1.0 - p2), total_weight));
    if (val1 >= 1.0e10000 or val2 <= 1.0e-10000) {
        cout << "Something went wrong " << val1 << " " << val2 << " "
             << weight_bad << " " << weight_good << " " << a << " " << b
             << endl;
        cout << pow(((1.0 - p1) / p2), weight_bad) << " "
             << pow((p1 / (1.0 - p2)), weight_good) << endl;
        cout << ((1.0 - p1) / p2) << " " << (p1 / (1.0 - p2)) << endl;
        cout << pow(10.0, 513) << endl;
        assert(false);
    }
    return log(val1) - log(val2);
}

inline double BayesianNet::BnfWeightedUnconditional(int naffected, int npaths,
                                                    int naffected_r,
                                                    int npaths_r,
                                                    double weight_good,
                                                    double weight_bad) {
    // e2e: end-to-end
    int e2e_paths = npaths * npaths_r;
    int e2e_failed_paths =
        e2e_paths - (npaths - naffected) * (npaths_r - naffected_r);
    // Separate computation for "a" and "b" required because if "a = 0"
    // then using "(1.0 - b)" for "a" inside the log can be buggy
    // as it can get approximated by a small value, which messes with the log
    // computation
    double a = ((double)(e2e_paths - e2e_failed_paths)) / e2e_paths;
    double b = ((double)e2e_failed_paths) / e2e_paths;
    double ret = log(a + b * pow((long double)((1.0 - p1) / p2), weight_bad) *
                             pow(p1 / (1.0 - p2), weight_good));
    ret = min(ret, std::numeric_limits<double>::max());
    return ret;
}

inline long double BayesianNet::GetBnfWeightedUnconditionalIntermediateValue(
    Flow *flow, double max_finish_time_ms) {
    PII weight = flow->LabelWeightsFunc(max_finish_time_ms);
    assert(INPUT_FLOW_TYPE != PROBLEMATIC_FLOWS);
    // return log((1.0 - a) + a * pow((1.0 - p1)/p2,
    // weight_bad)*pow(p1/(1.0-p2), weight_good));
    //                            <------------------- intermediate_val
    //                            ---------------------->
    long double ret = pow((long double)((1.0 - p1) / p2), weight.second) *
                      pow(p1 / (1.0 - p2), weight.first);
    //! TODO TODO TODO: precision goes out of long double range
    ret = min(ret, std::numeric_limits<long double>::max());
    return ret;
}

inline double BayesianNet::BnfWeightedUnconditionalIntermediate(
    int naffected, int npaths, int naffected_r, int npaths_r,
    long double intermediate_val) {
    // e2e: end-to-end
    int e2e_paths = npaths * npaths_r;
    int e2e_failed_paths =
        e2e_paths - (npaths - naffected) * (npaths_r - naffected_r);
    double a = ((double)(e2e_paths - e2e_failed_paths)) / e2e_paths;
    double b = ((double)e2e_failed_paths) / e2e_paths;
    return log(a + b * intermediate_val);
}

bool BayesianNet::DiscardFlow(Flow *flow, double min_start_time_ms,
                              double max_finish_time_ms) {
    return (!flow->AnySnapshotBefore(max_finish_time_ms) or
            flow->start_time_ms < min_start_time_ms or
            (INPUT_FLOW_TYPE == PROBLEMATIC_FLOWS and
             !flow->TracerouteFlow(max_finish_time_ms)));
}

void BayesianNet::GetRelevantFlows(Hypothesis *hypothesis,
                                   Hypothesis *base_hypothesis,
                                   double min_start_time_ms,
                                   double max_finish_time_ms,
                                   vector<int> &relevant_flows) {
    GetRelevantFlowsHelper(hypothesis, base_hypothesis, min_start_time_ms,
                           max_finish_time_ms, relevant_flows, false);
}

void BayesianNet::GetRelevantFlowsHelper(Hypothesis *hypothesis,
                                         Hypothesis *base_hypothesis,
                                         double min_start_time_ms,
                                         double max_finish_time_ms,
                                         vector<int> &relevant_flows,
                                         bool device_level) {
    auto start_init_time = chrono::high_resolution_clock::now();
    dense_hash_set<int, hash<int>> relevant_flows_set;
    relevant_flows_set.set_empty_key(-1);
    vector<vector<int>> *flows_by_component;
    if (device_level)
        flows_by_component = flows_by_device;
    else
        flows_by_component = flows_by_link_id;
    // for components that are in hypothesis, but not in base_hypothesis
    for (int cmp : *hypothesis) {
        if (base_hypothesis->count(cmp) == 0) {
            vector<int> &cmp_flows = (*flows_by_component)[cmp];
            for (int f : cmp_flows) {
                //! TODO: Add option for active_flows_only
                if (!DiscardFlow(data->flows[f], min_start_time_ms,
                                 max_finish_time_ms))
                    relevant_flows_set.insert(f);
            }
        }
    }
    // for components that are in base_hypothesis, but not in hypothesis
    for (int cmp : *base_hypothesis) {
        if (hypothesis->count(cmp) == 0) {
            vector<int> &cmp_flows = (*flows_by_component)[cmp];
            for (int f : cmp_flows) {
                //! TODO: Add option for active_flows_only
                if (!DiscardFlow(data->flows[f], min_start_time_ms,
                                 max_finish_time_ms))
                    relevant_flows_set.insert(f);
            }
        }
    }
    relevant_flows.insert(relevant_flows.begin(), relevant_flows_set.begin(),
                          relevant_flows_set.end());
}

double BayesianNet::ComputeLogLikelihoodHelper(
    Hypothesis *hypothesis, Hypothesis *base_hypothesis, double base_likelihood,
    double min_start_time_ms, double max_finish_time_ms, bool device_level,
    int nopenmp_threads) {
    vector<int> relevant_flows;
    GetRelevantFlowsHelper(hypothesis, base_hypothesis, min_start_time_ms,
                           max_finish_time_ms, relevant_flows, device_level);
    // cout << " Relevant flows for ComputeLogLikelihood " <<
    // relevant_flows.size()
    //     << " Num flows "<< data->flows.size() << " relevant flows "<<
    //     (*flows_by_link_id)[*hypothesis->begin()].size() << endl;
    return ComputeLogLikelihoodHelper(
        hypothesis, base_hypothesis, base_likelihood, min_start_time_ms,
        max_finish_time_ms, relevant_flows, device_level, nopenmp_threads);
}

double BayesianNet::ComputeLogLikelihood(
    Hypothesis *hypothesis, Hypothesis *base_hypothesis, double base_likelihood,
    double min_start_time_ms, double max_finish_time_ms, int nopenmp_threads) {
    vector<int> relevant_flows;
    GetRelevantFlows(hypothesis, base_hypothesis, min_start_time_ms,
                     max_finish_time_ms, relevant_flows);
    // cout << " Relevant flows for ComputeLogLikelihood " <<
    // relevant_flows.size()
    //     << " Num flows "<< data->flows.size() << " relevant flows "<<
    //     (*flows_by_link_id)[*hypothesis->begin()].size() << endl;
    return ComputeLogLikelihood(hypothesis, base_hypothesis, base_likelihood,
                                min_start_time_ms, max_finish_time_ms,
                                relevant_flows, nopenmp_threads);
}

array<int, 6>
BayesianNet::ComputeFlowPathCountersReduced(Flow *flow, Hypothesis *hypothesis,
                                            Hypothesis *base_hypothesis,
                                            double max_finish_time_ms) {
    vector<Path *> *flow_paths = flow->GetPaths(max_finish_time_ms);
    assert(flow_paths != NULL and flow_paths->size() == 1);
    int npaths = flow->npaths_unreduced, naffected = 0, naffected_base = 0;
    // If common links of all paths are in hypothesis, then all paths are
    // affected
    if (hypothesis->count(flow->first_link_id) > 0 or
        hypothesis->count(flow->last_link_id) > 0) {
        naffected = npaths;
    } else {
        for (Path *path : *flow_paths) {
            naffected += HypothesisIntersectsPath(hypothesis, path);
        }
    }
    if (base_hypothesis->count(flow->first_link_id) > 0 or
        base_hypothesis->count(flow->last_link_id) > 0) {
        naffected_base = npaths;
    } else {
        for (Path *path : *flow_paths) {
            naffected_base += HypothesisIntersectsPath(base_hypothesis, path);
        }
    }
    int npaths_r = 1, naffected_r = 0, naffected_base_r = 0;
    //! TODO: implement REVERSE_PATH case
    if constexpr (CONSIDER_REVERSE_PATH) {
        assert(false);
    }
    return {npaths,   naffected,   naffected_base,
            npaths_r, naffected_r, naffected_base_r};
}

array<int, 6> BayesianNet::ComputeFlowPathCountersUnreducedDevice(
    Flow *flow, Hypothesis *hypothesis, Hypothesis *base_hypothesis,
    double max_finish_time_ms) {
    vector<Path *> *flow_paths = flow->GetPaths(max_finish_time_ms);
    assert(flow_paths != NULL);
    int npaths = flow_paths->size(), naffected = 0, naffected_base = 0;
    Path device_path;
    for (Path *link_path : *flow_paths) {
        data->GetDeviceLevelPath(flow, *link_path, device_path);
        naffected += (int)HypothesisIntersectsPath(hypothesis, &device_path);
        naffected_base +=
            (int)HypothesisIntersectsPath(base_hypothesis, &device_path);
    }
    int npaths_r = 1, naffected_r = 0, naffected_base_r = 0;
    //! TODO: implement REVERSE_PATH case
    if constexpr (CONSIDER_REVERSE_PATH) {
        assert(false);
    }
    return {npaths,   naffected,   naffected_base,
            npaths_r, naffected_r, naffected_base_r};
}

array<int, 6> BayesianNet::ComputeFlowPathCountersUnreduced(
    Flow *flow, Hypothesis *hypothesis, Hypothesis *base_hypothesis,
    double max_finish_time_ms) {
    vector<Path *> *flow_paths = flow->GetPaths(max_finish_time_ms);
    assert(flow_paths != NULL);
    int npaths = flow_paths->size(), naffected = 0, naffected_base = 0;
    // If common end links are in hypothesis, then all paths are affected
    if (hypothesis->count(flow->first_link_id) > 0 or
        hypothesis->count(flow->last_link_id) > 0) {
        naffected = npaths;
    } else {
        for (Path *path : *flow_paths) {
            naffected += (int)HypothesisIntersectsPath(hypothesis, path);
        }
    }
    if (base_hypothesis->count(flow->first_link_id) > 0 or
        base_hypothesis->count(flow->last_link_id) > 0) {
        naffected_base = npaths;
    } else {
        for (Path *path : *flow_paths) {
            naffected_base +=
                (int)HypothesisIntersectsPath(base_hypothesis, path);
        }
    }
    int npaths_r = 1, naffected_r = 0, naffected_base_r = 0;
    //! TODO: implement REVERSE_PATH case
    if constexpr (CONSIDER_REVERSE_PATH) {
        assert(false);
    }
    return {npaths,   naffected,   naffected_base,
            npaths_r, naffected_r, naffected_base_r};
}

double BayesianNet::ComputeLogLikelihood2(
    Hypothesis *hypothesis, Hypothesis *base_hypothesis, double base_likelihood,
    double min_start_time_ms, double max_finish_time_ms,
    vector<int> &relevant_flows, int nopenmp_threads) {
    vector<double> log_likelihoods_threads(nopenmp_threads, 0.0);
#pragma omp parallel for num_threads(nopenmp_threads) if (nopenmp_threads > 1)
    for (int ii = 0; ii < relevant_flows.size(); ii++) {
        Flow *flow = data->flows[relevant_flows[ii]];
        double log_likelihood = 0.0;
        PII weight = flow->LabelWeightsFunc(max_finish_time_ms);
        if (weight.first == 0 and weight.second == 0)
            continue;
        //! TODO Reduced Analaysis
        assert(!REDUCED_ANALYSIS);
        //! TODO: implement REVERSE_PATH case
        if constexpr (CONSIDER_REVERSE_PATH) {
            assert(false);
        }
        vector<Path *> *flow_paths = flow->GetPaths(max_finish_time_ms);
        assert(flow_paths != NULL);
        int npaths = flow_paths->size();
        long double ll = 0.0, ll_base = 0.0;
        long double flow_dir = pow((long double)1.0 - p1, weight.second) *
                               pow((long double)p1, weight.first);
        flow_dir /= pow((long double)p2, weight.second) *
                    pow((long double)1.0 - p2, weight.first);
        for (Path *path : *flow_paths) {
            int nfailed = (hypothesis->count(flow->first_link_id) > 0);
            nfailed += (hypothesis->count(flow->last_link_id) > 0);
            int nfailed_base =
                (base_hypothesis->count(flow->first_link_id) > 0);
            nfailed_base += (base_hypothesis->count(flow->last_link_id) > 0);
            for (int link_id : *path) {
                nfailed += (hypothesis->count(link_id) > 0);
                nfailed_base += (base_hypothesis->count(link_id) > 0);
            }
            /*
            if (flow_dir >= 1.0){
                double p_bad = (nfailed > 0 ? 1.0 - p1 : p2);
                double p_bad_base = (nfailed_base > 0 ? 1.0 - p1 : p2);
                ll += (pow((long double)p_bad, weight.second) * pow((long
            double)(1.0 - p_bad), weight.first))/npaths; ll_base += (pow((long
            double)p_bad_base, weight.second) * pow((long double)(1.0 -
            p_bad_base), weight.first))/npaths;
            }
            else{
                long double no_failure_score = pow((long double)p2,
            weight.second) * pow ((long double)1.0 - p2, weight.first); long
            double one_failure_score = flow_dir * no_failure_score; ll +=
            no_failure_score * pow((long double) flow_dir, nfailed)/npaths;
                ll_base += no_failure_score * pow((long double) flow_dir,
            nfailed_base)/npaths;
                //ll += (nfailed * (one_failure_score  - no_failure_score) +
            no_failure_score)/npaths;
                //ll_base += (nfailed_base * (one_failure_score  -
            no_failure_score) + no_failure_score)/npaths;
            }
            */
            double p_bad = 1.0 - (pow(p1, nfailed) *
                                  pow(1.0 - p2, (path->size() + 2 - nfailed)));
            double p_bad_base =
                1.0 - (pow(p1, nfailed_base) *
                       pow(1.0 - p2, (path->size() + 2 - nfailed_base)));
            ll += (pow((long double)p_bad, weight.second) *
                   pow((long double)(1.0 - p_bad), weight.first)) /
                  npaths;
            ll_base += (pow((long double)p_bad_base, weight.second) *
                        pow((long double)(1.0 - p_bad_base), weight.first)) /
                       npaths;
        }
        log_likelihoods_threads[omp_get_thread_num()] +=
            (log(ll) - log(ll_base));
    }
    double log_likelihood = max(
        -1.0e9, accumulate(log_likelihoods_threads.begin(),
                           log_likelihoods_threads.end(), 0.0, plus<double>()));
    // cout << *hypothesis << " " << log_likelihood + hypothesis->size() * PRIOR
    // << endl;
    return base_likelihood + log_likelihood + ComputeLogPrior(hypothesis) -
           ComputeLogPrior(base_hypothesis);
}

double BayesianNet::ComputeLogLikelihoodHelper(
    Hypothesis *hypothesis, Hypothesis *base_hypothesis, double base_likelihood,
    double min_start_time_ms, double max_finish_time_ms,
    vector<int> &relevant_flows, bool device_level, int nopenmp_threads) {
    vector<double> log_likelihoods_threads(nopenmp_threads, 0.0);
#pragma omp parallel for num_threads(nopenmp_threads) if (nopenmp_threads > 1)
    for (int ii = 0; ii < relevant_flows.size(); ii++) {
        Flow *flow = data->flows[relevant_flows[ii]];
        double log_likelihood = 0.0;
        PII weight = flow->LabelWeightsFunc(max_finish_time_ms);
        if (weight.first == 0 and weight.second == 0)
            continue;
        array<int, 6> path_ctrs;
        if (device_level) {
            path_ctrs = ComputeFlowPathCountersUnreducedDevice(
                flow, hypothesis, base_hypothesis, max_finish_time_ms);
        } else {
            if (REDUCED_ANALYSIS)
                path_ctrs = ComputeFlowPathCountersReduced(
                    flow, hypothesis, base_hypothesis, max_finish_time_ms);
            else
                path_ctrs = ComputeFlowPathCountersUnreduced(
                    flow, hypothesis, base_hypothesis, max_finish_time_ms);
        }
        auto [npaths, naffected, naffected_base, npaths_r, naffected_r,
              naffected_base_r] = path_ctrs;
        int thread_num = omp_get_thread_num();
        log_likelihoods_threads[thread_num] +=
            BnfWeighted(naffected, npaths, naffected_r, npaths_r, weight.first,
                        weight.second);
        if (naffected_base > 0 or naffected_base_r > 0) {
            log_likelihoods_threads[thread_num] -=
                BnfWeighted(naffected_base, npaths, naffected_base_r, npaths_r,
                            weight.first, weight.second);
        }
    }
    double log_likelihood = max(
        -1.0e9, accumulate(log_likelihoods_threads.begin(),
                           log_likelihoods_threads.end(), 0.0, plus<double>()));
    // cout << *hypothesis << " " << log_likelihood + hypothesis->size() * PRIOR
    // << endl;
    return base_likelihood + log_likelihood + ComputeLogPrior(hypothesis) -
           ComputeLogPrior(base_hypothesis);
}

double BayesianNet::ComputeLogLikelihood(
    Hypothesis *hypothesis, Hypothesis *base_hypothesis, double base_likelihood,
    double min_start_time_ms, double max_finish_time_ms,
    vector<int> &relevant_flows, int nopenmp_threads) {
    return ComputeLogLikelihoodHelper(
        hypothesis, base_hypothesis, base_likelihood, min_start_time_ms,
        max_finish_time_ms, relevant_flows, false, nopenmp_threads);
}

double BayesianNet::ComputeLogLikelihoodDevice(
    Hypothesis *hypothesis, Hypothesis *base_hypothesis, double base_likelihood,
    double min_start_time_ms, double max_finish_time_ms,
    vector<int> &relevant_flows, int nopenmp_threads) {
    return ComputeLogLikelihoodHelper(
        hypothesis, base_hypothesis, base_likelihood, min_start_time_ms,
        max_finish_time_ms, relevant_flows, true, nopenmp_threads);
}

double BayesianNet::ComputeLogPrior(int link_id) {
    if (REDUCED_ANALYSIS)
        return log(num_reduced_links_map->at(link_id)) + PRIOR;
    else {
        int multiplier = (data->IsLinkDevice(link_id) ? 5 : 1);
        return multiplier * PRIOR;
    }
}

double BayesianNet::ComputeLogPrior(Hypothesis *hypothesis) {
    double log_prior = 0.0;
    for (int link_id : *hypothesis) {
        log_prior += ComputeLogPrior(link_id);
    }
    return log_prior;
}
