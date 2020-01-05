#ifndef __FAULT_LOCALIZE_NET_BOUNCER__
#define __FAULT_LOCALIZE_NET_BOUNCER__
#include "estimator.h"

class NetBouncer: public Estimator{
 public:
    NetBouncer(): Estimator() {}
    void LocalizeFailures(double min_start_time_ms, double max_finish_time_ms,
                          Hypothesis &localized_links, int nopenmp_threads);

    void SetLogData(LogData* data_, double max_finish_time_ms, int nopenmp_threads);
    NetBouncer* CreateObject();
    void SetParams(vector<double>& params);

private:

    inline double EstimatedPathSuccessRate(Flow *flow, vector<double>& success_prob);

    double ComputeError(vector<Flow*>& active_flows, vector<double>& success_prob,
                        double min_start_time_ms, double max_finish_time_ms);

    double ArgMinError(vector<Flow*>& active_flows, vector<double>& success_prob,
            int var_link_id, double min_start_time_ms, double max_finish_time_ms);

    double regularize_const = 0.01;
    double fail_threshold = 0.001;
    const int MAX_ITERATIONS = 100;
};
#endif
