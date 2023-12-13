#ifndef __FAULTFERENCE_UTILS__
#define __FAULTFERENCE_UTILS__

#include "utils.h"
#include <bits/stdc++.h>
#include <chrono>
#include <iostream>

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

set<int> GetEquivalentDevices(map<int, set<Flow *>> &flows_by_device);

void LocalizeScoreAgg(vector<pair<string, string>> &in_topo_traces,
                      double max_finish_time_ms, int nopenmp_threads);

pair<Link, int>
GetBestLinkToRemoveAgg(LogData *data, vector<Flow *> *dropped_flows,
                       int ntraces, set<int> &equivalent_devices,
                       set<Link> &prev_removed_links, double max_finish_time_ms,
                       int nopenmp_threads);

void BinFlowsByDeviceAgg(LogData *data, vector<Flow *> *dropped_flows,
                         int ntraces, set<Link> &removed_links,
                         map<int, set<Flow *>> &flows_by_device,
                         double max_finish_time_ms);

int GetExplanationEdgesAgg(LogData *data, vector<Flow *> *dropped_flows,
                           int ntraces, set<int> &equivalent_devices,
                           set<Link> &removed_links, double max_finish_time_ms);

int GetExplanationEdgesAgg2(LogData *data, vector<Flow *> *dropped_flows,
                            int ntraces, set<int> &equivalent_devices,
                            set<Link> &removed_links,
                            double max_finish_time_ms);

Link GetMostUsedLink(LogData *data, vector<Flow *> *dropped_flows, int ntraces,
                     int device, double max_finish_time_ms,
                     int nopenmp_threads);

set<int> LocalizeViaFlock(LogData *data, int ntraces, string fail_file,
                          double min_start_time_ms, double max_finish_time_ms,
                          int nopenmp_threads);

int IsProblemSolved(LogData *data, double max_finish_time_ms);

set<int> LocalizeViaNobody(LogData *data, int ntraces, string fail_file,
                          double min_start_time_ms, double max_finish_time_ms,
                          int nopenmp_threads);

void GetDeviceColors(set<int> &equivalent_devices, map<int, int> &device_colors,
                     set<set<int>> &eq_device_sets);

void GetColorCounts(map<int, int> &device_colors, map<int, int> &col_cnts);

/*
  Coloring based scheme
  Uses information theoretic measure of sets to identify best link removal
  sequence
*/
void LocalizeScoreITA(vector<pair<string, string>> &in_topo_traces,
                      double min_start_time_ms, double max_finish_time_ms,
                      int nopenmp_threads, string sequence_mode, string inference_mode);

void GetEqDeviceSetsITA(LogData *data, vector<Flow *> *dropped_flows,
                        int ntraces, set<int> &equivalent_devices,
                        Link removed_link, double max_finish_time_ms,
                        set<set<int>> &result);

double GetEqDeviceSetsMeasureITA(LogData *data, vector<Flow *> *dropped_flows,
                                 int ntraces, set<int> &equivalent_devices,
                                 Link removed_link, double max_finish_time_ms,
                                 set<set<int>> &eq_device_sets);

set<Link> GetUsedLinks(LogData *data, int ntraces, double min_start_time_ms,
                       double max_finish_time_ms);

pair<Link, double>
GetBestLinkToRemoveITA(LogData *data, vector<Flow *> *dropped_flows,
                       int ntraces, set<int> &equivalent_devices,
                       set<set<int>> &eq_device_sets, set<Link> &used_links,
                       double max_finish_time_ms, int nopenmp_threads);

/*
  Pick micro-change sequence to maximize number of pairs that can be distinguished
*/
int GetEqDeviceSetsMeasurePairs(LogData *data, vector<Flow *> *dropped_flows,
                                int ntraces, set<int> &equivalent_devices,
                                Link removed_link, double max_finish_time_ms,
                                set<set<int>> &eq_device_sets);

pair<Link, double>
GetBestLinkToRemovePairs(LogData *data, vector<Flow *> *dropped_flows,
                       int ntraces, set<int> &equivalent_devices,
                       set<set<int>> &eq_device_sets, set<Link> &used_links,
                       double max_finish_time_ms, int nopenmp_threads);

pair<Link, double>
GetRandomLinkToRemoveITA(LogData *data, vector<Flow *> *dropped_flows,
                       int ntraces, set<int> &equivalent_devices,
                       set<set<int>> &eq_device_sets, set<Link> &used_links,
                       double max_finish_time_ms, int nopenmp_threads);

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
