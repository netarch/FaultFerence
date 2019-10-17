#ifndef __FAULT_LOCALIZE_007__
#define __FAULT_LOCALIZE_007__
#include "estimator.h"

class DoubleO7: public Estimator{
 public:
    DoubleO7(): Estimator() {}
    void LocalizeFailures(double min_start_time_ms, double max_finish_time_ms,
                          Hypothesis &localized_links, int nopenmp_threads);

    void SetLogData(LogData* data_, double max_finish_time_ms, int nopenmp_threads);
    DoubleO7* CreateObject();
    void SetParams(vector<double>& params);

private:

    PDD ComputeVotes(vector<Flow*>& bad_flows, vector<double>& votes,
                     Hypothesis &problematic_link_ids, double min_start_time_ms,
                     double max_finish_time_ms);

    // Noise parameters
    double fail_threshold = 0.0025;
    const bool ADJUST_VOTES = false;
};

#endif