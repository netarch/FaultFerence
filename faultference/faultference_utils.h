#ifndef __FAULTFERENCE_UTILS__
#define __FAULTFERENCE_UTILS__

#include "microchange.h"
#include "utils.h"
#include <bits/stdc++.h>
#include <chrono>
#include <iostream>

extern bool USE_ACTIVE_PROBE_MC;

inline bool SortByValueSize(const pair<int, set<Flow *>> &a,
                            const pair<int, set<Flow *>> &b) {
    return (a.second.size() > b.second.size());
}

// Check if removing a link does not eliminate all shortest paths
void CheckShortestPathExists(LogData &data, double max_finish_time_ms,
                             vector<Flow *> &dropped_flows, int link_to_remove);

// ... in the modified network
void BinFlowsByDevice(LogData &data, double max_finish_time_ms,
                      vector<Flow *> &dropped_flows, Hypothesis &removed_links,
                      map<int, set<Flow *>> &flows_by_device);

int GetExplanationEdgesFromMap(map<int, set<Flow *>> &flows_by_device);

map<PII, pair<int, double>> ReadFailuresBlackHole(string fail_file);
set<int> ReadEqDevices(string eq_devices_file);

set<int> GetEquivalentDevices(map<int, set<Flow *>> &flows_by_device);

void BinFlowsByDeviceAgg(LogData *data, vector<Flow *> *dropped_flows,
                         int ntraces, set<Link> &removed_links,
                         map<int, set<Flow *>> &flows_by_device,
                         double max_finish_time_ms);

Link GetMostUsedLink(LogData *data, vector<Flow *> *dropped_flows, int ntraces,
                     int device, double max_finish_time_ms,
                     int nopenmp_threads);

set<int> LocalizeViaFlock(LogData *data, int ntraces, string fail_file,
                          double min_start_time_ms, double max_finish_time_ms,
                          int nopenmp_threads, string topo_name);

int IsProblemSolved(LogData *data, double max_finish_time_ms, const int min_path_per_link);

set<int> LocalizeViaNobody(LogData *data, int ntraces, string fail_file,
                           double min_start_time_ms, double max_finish_time_ms,
                           int nopenmp_threads, string topo_name, set<int> prev_eq_devices, string micro_change);

void GetDeviceColors(set<int> &equivalent_devices, map<int, int> &device_colors,
                     set<set<int>> &eq_device_sets);

void GetColorCounts(map<int, int> &device_colors, map<int, int> &col_cnts);

void LocalizeFailure(vector<pair<string, string>> &in_topo_traces,
                     double min_start_time_ms, double max_finish_time_ms,
                     int nopenmp_threads, string sequence_mode,
                     string inference_mode, string minimize_mode, string topo_name, set<int> prev_eq_devices, string micro_change);

pair<MicroChange*, double>
GetMicroChange(LogData *data, vector<Flow *> *dropped_flows, int ntraces,
                   set<int> &equivalent_devices, set<set<int>> &eq_device_sets,
                   set<Link> &used_links, double min_start_time_ms,
                   double max_finish_time_ms, string sequence_mode,
                   string minimize_mode, int nopenmp_threads);

void GetEqDeviceSets(LogData *data, vector<Flow *> *dropped_flows, int ntraces,
                     set<int> &equivalent_devices, Link removed_link,
                     double max_finish_time_ms, set<set<int>> &result);

/*
  Coloring based scheme
  pick micro-change sequence to maximize number of pairs that can be
  distinguished
*/
int GetEqDeviceSetsMeasure(LogData *data, vector<Flow *> *dropped_flows,
                           int ntraces, set<int> &equivalent_devices,
                           Link removed_link, double max_finish_time_ms,
                           set<set<int>> &eq_device_sets);
set<Link> GetUsedLinks(LogData *data, int ntraces, double min_start_time_ms,
                       double max_finish_time_ms);

/* Utility functions for link removal microchange */
pair<RemoveLinkMc *, double>
GetBestLinkToRemove(LogData *data, vector<Flow *> *dropped_flows, int ntraces,
                    set<int> &equivalent_devices, set<set<int>> &eq_device_sets,
                    set<Link> &used_links, double min_start_time_ms,
                    double max_finish_time_ms, string minimize_mode, int nopenmp_threads);

pair<RemoveLinkMc *, double>
GetLowestCostLinkToRemove(LogData *data, vector<Flow *> *dropped_flows, int ntraces,
                    set<int> &equivalent_devices, set<set<int>> &eq_device_sets,
                    set<Link> &used_links, double min_start_time_ms,
                    double max_finish_time_ms, string minimize_mode, int nopenmp_threads);

pair<RemoveLinkMc *, double>
GetRandomLinkToRemove(LogData *data, vector<Flow *> *dropped_flows, int ntraces,
                      set<int> &equivalent_devices,
                      set<set<int>> &eq_device_sets, set<Link> &used_links,
                      double min_start_time_ms, double max_finish_time_ms,
                      string minimize_mode, int nopenmp_threads);

/** end of utility functions for link removal microchange **/

/* Utility functions for active probe microchange */
bool CheckNoBranch(LogData *data, vector<Path *> *flow_paths, int src, int dst);
set<PII> ViableSrcDstForActiveProbe(LogData *data, int ntraces,
                                    double min_start_time_ms,
                                    double max_finish_time_ms);

/* Get <src, dst, srcport, dstport> tuple that had the most number of packet drops */
tuple<int, int, int, int> SrcDstWithMaxDrops(LogData *data, vector<Flow *> *dropped_flows,
                               int ntraces, double min_start_time_ms,
                               double max_finish_time_ms, int nopenmp_threads);

pair<ActiveProbeMc*, double>
GetBestActiveProbeMc(LogData *data, vector<Flow *> *dropped_flows, int ntraces,
                     set<int> &equivalent_devices,
                     set<set<int>> &eq_device_sets, set<Link> &used_links,
                     double min_start_time_ms, double max_finish_time_ms,
                     string minimize_mode, int nopenmp_threads);


pair<ActiveProbeMc*, double>
GetLowestCostActiveProbeMc(LogData *data, vector<Flow *> *dropped_flows, int ntraces,
                     set<int> &equivalent_devices,
                     set<set<int>> &eq_device_sets, set<Link> &used_links,
                     double min_start_time_ms, double max_finish_time_ms,
                     string minimize_mode, int nopenmp_threads);

pair<ActiveProbeMc*, double>
GetRandomActiveProbeMc(LogData *data, vector<Flow *> *dropped_flows, int ntraces,
                     set<int> &equivalent_devices,
                     set<set<int>> &eq_device_sets, set<Link> &used_links,
                     double min_start_time_ms, double max_finish_time_ms,
                     string minimize_mode, int nopenmp_threads);


int EvaluateActiveProbeMc(LogData *data, vector<Flow *> *dropped_flows,
                          int ntraces, set<int> &equivalent_devices,
                          PII src_dst, double min_start_time_ms,
                          double max_finish_time_ms,
                          set<set<int>> &eq_device_sets);

/** end of utility functions for active probe microchange **/

void GetEqDevicesInFlowPaths(LogData &data, Flow *flow,
                             set<int> &equivalent_devices,
                             Hypothesis &removed_links,
                             double max_finish_time_ms, set<int> &result);

void OperatorScheme(vector<pair<string, string>> in_topo_traces,
                    double min_start_time_ms, double max_finish_time_ms,
                    int nopenmp_threads);

bool RunFlock(LogData &data, string fail_file, double min_start_time_ms,
              double max_finish_time_ms, vector<double> &params,
              int nopenmp_threads);
#endif
