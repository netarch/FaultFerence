#include "bayesian_net.h"
#include "utils.h"
#include <algorithm>
#include <assert.h>
#include <chrono>
#include <fstream>
#include <iostream>
#include <sstream>

using namespace std;

// Take reduced graph mapping as an input file
void ReducedGraphMappingFromFile(
    string reduced_map_file, unordered_map<Link, Link> &to_reduced_graph,
    unordered_map<Link, vector<Link>> &from_reduced_graph);
//! TODO: Deprecated
void ReducedGraphMappingLeafSpine(
    string topology_file, unordered_map<Link, Link> &to_reduced_graph,
    unordered_map<Link, vector<Link>> &from_reduced_graph);

void SetInputForReduced(BayesianNet &estimator, LogData *data,
                        LogData *reduced_data, string reduced_map_file,
                        double max_finish_time_ms, int nopenmp_threads);

LogData* RemoveLinksPassiveOnly(BayesianNet &estimator, LogData *data,
                                double start_time_ms, double end_time_ms,
                                double max_finish_time_ms, int remove_link_id,
                                int nopenmp_threads);