#ifndef __COMMON_TESTING_SYSTEM__
#define __COMMON_TESTING_SYSTEM__
#include "estimator.h"
#include "logdata.h"
#include "utils.h"
#include <assert.h>
#include <chrono>
#include <iostream>

using namespace std;

double GetPrecisionRecallTrendFile(string topology_file, string trace_file,
                                   double min_start_time_ms,
                                   double max_finish_time_ms, double step_ms,
                                   Estimator *base_estimator,
                                   vector<PDD> &result, int nopenmp_threads);

void GetPrecisionRecallTrendFiles(string topology_file,
                                  double min_start_time_ms,
                                  double max_finish_time_ms, double step_ms,
                                  vector<PDD> &result, Estimator *estimator,
                                  int nopenmp_threads);

void GetPrecisionRecallParamsFile(string topology_file, string trace_file,
                                  double min_start_time_ms,
                                  double max_finish_time_ms,
                                  vector<vector<double>> &params,
                                  Estimator *estimator, vector<PDD> &result,
                                  int nopenmp_threads);

void GetPrecisionRecallParamsFiles(
    string topology_file, double min_start_time_ms, double max_finish_time_ms,
    vector<vector<double>> &params, vector<PDD> &result,
    Estimator *base_estimator, int nopenmp_threads);
#endif
