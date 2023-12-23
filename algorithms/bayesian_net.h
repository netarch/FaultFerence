#ifndef __FAULT_LOCALIZE_BAYESIAN_NET__
#define __FAULT_LOCALIZE_BAYESIAN_NET__
#include "estimator.h"

class BayesianNet : public Estimator {
  public:
    BayesianNet();
    void LocalizeFailures(double min_start_time_ms, double max_finish_time_ms,
                          Hypothesis &localized_links, int nopenmp_threads);
    void LocalizeDeviceFailures(double min_start_time_ms,
                                double max_finish_time_ms,
                                Hypothesis &localized_devices,
                                int nopenmp_threads);
    const bool PRINT_SCORES = true;
    // TODO: Rework
    const int MAX_FAILS = 1;
    const int NUM_CANDIDATES = max(15, 5 * MAX_FAILS);
    const int NUM_TOP_HYPOTHESIS_AT_EACH_STAGE = 500; //!TODO: 4
    // For printing purposes
    const int N_MAX_K_LIKELIHOODS = 50; //!TODO: 20
    double PRIOR = -1000.0;
    const int GIBBS_SAMPLING_ITERATIONS = 1000000;
    bool REDUCED_ANALYSIS = false;
    void SetReducedAnalysis(bool val) { REDUCED_ANALYSIS = val; }
    void
    SetNumReducedLinksMap(unordered_map<int, int> *num_reduced_links_map_) {
        num_reduced_links_map = num_reduced_links_map_;
    }
    void SetFlowsByLinkId(vector<vector<int>> *flows_by_link_id_) {
        assert(flows_by_link_id_ != NULL);
        flows_by_link_id = flows_by_link_id_;
    }
    BayesianNet *CreateObject();
    void SetLogData(LogData *data, double max_finish_time_ms,
                    int nopenmp_threads);
    void SetParams(vector<double> &param);
    void SetParamsFromInput(double max_finish_time_ms);
    bool params_from_input = false;

  protected:
    void LocalizeFailuresHelper(double min_start_time_ms,
                                double max_finish_time_ms,
                                Hypothesis &localized_links, bool device_level,
                                int nopenmp_threads);
    void HypothesesUnion(set<Hypothesis *> &hypotheses_set, Hypothesis &result);
    void HypothesesIntersection(set<Hypothesis *> &hypotheses_set,
                                Hypothesis &result);

    void UnionTopHypothesis(
        vector<pair<double, Hypothesis *>> &likelihood_hypotheses, int K,
        Hypothesis &result);

    void SearchHypotheses(double min_start_time_ms, double max_finish_time_ms,
                          unordered_map<Hypothesis *, double> &all_hypotheses,
                          int nopenmp_threads);
    void
    SearchHypothesesJle(double min_start_time_ms, double max_finish_time_ms,
                        unordered_map<Hypothesis *, double> &all_hypotheses,
                        bool device_level, int nopenmp_threads);
    void SearchHypothesesMisconfiguredACL(
        double min_start_time_ms, double max_finish_time_ms,
        unordered_map<Hypothesis *, double> &all_hypotheses, bool device_level,
        int nopenmp_threads);

    void SearchHypothesesGibbsSampling(
        double min_start_time_ms, double max_finish_time_ms,
        unordered_map<Hypothesis *, double> &all_hypothesis,
        int nopenmp_threads);
    void SearchHypothesesGibbsSamplingJLE(
        double min_start_time_ms, double max_finish_time_ms,
        unordered_map<Hypothesis *, double> &all_hypothesis,
        int nopenmp_threads);
    void FlipLinkId(Hypothesis *hypothesis, int link_id);

    void PrintScores(double min_start_time_ms, double max_finish_time_ms,
                     bool device_level, int nopenmp_threads);

    void PrintCorrectHypothesisLikelihood(double min_start_time_ms,
                                          double max_finish_time_ms,
                                          Hypothesis &localized_components,
                                          bool device_level,
                                          int nopenmp_threads);

    void ComputeInitialLikelihoods(vector<double> &initial_likelihoods,
                                   double min_start_time_ms,
                                   double max_finish_time_ms,
                                   int nopenmp_threads);
    void ComputeInitialLikelihoodsHelper(vector<double> &initial_likelihoods,
                                         double min_start_time_ms,
                                         double max_finish_time_ms,
                                         bool device_level,
                                         int nopenmp_threads);
    void ComputeSingleLinkLogLikelihood(
        vector<pair<double, Hypothesis *>> &result, double min_start_time_ms,
        double max_finish_time_ms, int nopenmp_threads);
    void GetRelevantFlows(Hypothesis *hypothesis, Hypothesis *base_hypothesis,
                          double min_start_time_ms, double max_finish_time_ms,
                          vector<int> &relevant_flows);
    void GetRelevantFlowsHelper(Hypothesis *hypothesis,
                                Hypothesis *base_hypothesis,
                                double min_start_time_ms,
                                double max_finish_time_ms,
                                vector<int> &relevant_flows, bool device_level);

    inline bool DiscardFlow(Flow *flow, double min_start_time_ms,
                            double max_finish_time_ms);

    array<int, 6> ComputeFlowPathCountersUnreduced(Flow *flow,
                                                   Hypothesis *hypothesis,
                                                   Hypothesis *base_hypothesis,
                                                   double max_finish_time_ms);
    array<int, 6>
    ComputeFlowPathCountersUnreducedDevice(Flow *flow, Hypothesis *hypothesis,
                                           Hypothesis *base_hypothesis,
                                           double max_finish_time_ms);
    array<int, 6> ComputeFlowPathCountersReduced(Flow *flow,
                                                 Hypothesis *hypothesis,
                                                 Hypothesis *base_hypothesis,
                                                 double max_finish_time_ms);

    // for a single hypothesis
    double
    ComputeLogLikelihood(Hypothesis *hypothesis, Hypothesis *base_hypothesis,
                         double base_likelihood, double min_start_time_ms,
                         double max_finish_time_ms, vector<int> &relevant_flows,
                         int nopenmp_threads = 1);

    // for a single hypothesis (device level)
    double ComputeLogLikelihoodDevice(Hypothesis *hypothesis,
                                      Hypothesis *base_hypothesis,
                                      double base_likelihood,
                                      double min_start_time_ms,
                                      double max_finish_time_ms,
                                      vector<int> &relevant_flows,
                                      int nopenmp_threads = 1);

    // for a single hypothesis (abstracts out link/device level)
    double ComputeLogLikelihoodHelper(
        Hypothesis *hypothesis, Hypothesis *base_hypothesis,
        double base_likelihood, double min_start_time_ms,
        double max_finish_time_ms, vector<int> &relevant_flows,
        bool device_level, int nopenmp_threads = 1);

    // differentiate between multiple link failures on a path
    double
    ComputeLogLikelihood2(Hypothesis *hypothesis, Hypothesis *base_hypothesis,
                          double base_likelihood, double min_start_time_ms,
                          double max_finish_time_ms,
                          vector<int> &relevant_flows, int nopenmp_threads = 1);

    // computes relevant_flows and calls the other version
    double
    ComputeLogLikelihood(Hypothesis *hypothesis, Hypothesis *base_hypothesis,
                         double base_likelihood, double min_start_time_ms,
                         double max_finish_time_ms, int nopenmp_threads = 1);

    // computes relevant_flows and calls the other version
    double ComputeLogLikelihoodHelper(
        Hypothesis *hypothesis, Hypothesis *base_hypothesis,
        double base_likelihood, double min_start_time_ms,
        double max_finish_time_ms, bool device_level, int nopenmp_threads = 1);

    // for a set of hypothesis
    void ComputeLogLikelihood(
        vector<Hypothesis *> &hypothesis_space,
        vector<pair<Hypothesis *, double>> &base_hypothesis_likelihood,
        vector<pair<double, Hypothesis *>> &result, double min_start_time_ms,
        double max_finish_time_ms, int nopenmp_threads);

    inline long double
    GetBnfWeightedUnconditionalIntermediateValue(Flow *flow,
                                                 double max_finish_time_ms);

    inline double BnfWeighted(int naffected, int npaths, int naffected_r,
                              int npaths_r, double weight_good,
                              double weight_bad);

    inline double BnfWeighted(int naffected, int npaths, int naffected_r,
                              int npaths_r, double weight_good,
                              double weight_bad, long double intermediate_val);

    inline double BnfWeightedConditional(int naffected, int npaths,
                                         int naffected_r, int npaths_r,
                                         double weight_good, double weight_bad);

    inline double BnfWeightedUnconditional(int naffected, int npaths,
                                           int naffected_r, int npaths_r,
                                           double weight_good,
                                           double weight_bad);

    inline double
    BnfWeightedUnconditionalIntermediate(int naffected, int npaths,
                                         int naffected_r, int npaths_r,
                                         long double intermediate_val);

    double ComputeLogPrior(Hypothesis *hypothesis);
    double ComputeLogPrior(int link_id);
    void SortCandidatesWrtNumRelevantFlows(vector<int> &candidates);
    void CleanUpAfterLocalization(
        unordered_map<Hypothesis *, double> &all_hypothesis);

    // Cache intermediate results of time consuming arithmetic operations
    void ComputeAndStoreIntermediateValues(int nopenmp_threads,
                                           double max_finish_time_ms);

    int UpdateScores(vector<double> &likelihood_scores, Hypothesis *hypothesis,
                     Hypothesis *base_hypothesis, double min_start_time_ms,
                     double max_finish_time_ms, int nopenmp_threads);
    int UpdateScoresPopulateCounters(
        vector<Path *> *flow_paths, Hypothesis *hypothesis,
        int end_failed_links, vector<int> &end_links,
        vector<int> &npaths_failed_exclude_end_link,
        vector<short int> &link_ctrs_threads, bool *hypothesis_link_bitmap);

    int UpdateScoresDevice(vector<double> &likelihood_scores,
                           Hypothesis *hypothesis, Hypothesis *base_hypothesis,
                           double min_start_time_ms, double max_finish_time_ms,
                           int nopenmp_threads);
    int UpdateScoresDevicePopulateCounters(
        Flow *flow, vector<Path *> *flow_paths, Hypothesis *hypothesis,
        vector<short int> &device_ctrs_threads, bool *hypothesis_link_bitmap);
    void GetIndicesOfTopK(vector<double> &scores, int k, vector<int> &result,
                          Hypothesis *exclude, bool device_only=false);

    // Verify likelihood computation optimizations with the vanilla version
    bool VerifyLikelihoodComputation(
        unordered_map<Hypothesis *, double> &all_hypothesis,
        double min_start_time_ms, double max_finish_time_ms,
        int nopenmp_threads);

    void AddContributionsFromThreads(vector<double> *contributions,
                                     vector<double> &result,
                                     int nopenmp_threads);

    int GetNumComponents(bool device_level);

    Path *PathPointerSelect(Flow *flow, Path &link_path,
                            Path &device_path_unfilled, bool device_level);

    // Noise parameters
    double p1 = 1.0 - 5.0e-3, p2 = 2.0e-4;
    // double p1 = 1.0-4.0e-3, p2 = 1.5e-4;

    // For reduced analysis
    unordered_map<int, int> *num_reduced_links_map;

    // For printing scores
    vector<double> drops_per_component, flows_per_component;

    chrono::time_point<chrono::high_resolution_clock> timer_checkpoint;
};

#endif
