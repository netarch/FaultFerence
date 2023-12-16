#include "faultference_utils.h"
#include "bayesian_net.h"
#include "bayesian_net_continuous.h"
#include "bayesian_net_sherlock.h"
#include "doubleO7.h"
#include "net_bouncer.h"
#include "utils.h"
#include <assert.h>
#include <bits/stdc++.h>
#include <chrono>
#include <iostream>

using namespace std;

void GetDroppedFlows(LogData &data, vector<Flow *> &dropped_flows) {
    for (Flow *flow : data.flows) {
        if (flow->GetLatestPacketsLost())
            dropped_flows.push_back(flow);
    }
}

// Check if removing a link does not eliminate all shortest paths
void CheckShortestPathExists(LogData &data, double max_finish_time_ms,
                             vector<Flow *> &dropped_flows,
                             int link_to_remove) {
    Hypothesis removed_links;
    removed_links.insert(link_to_remove);
    int rlink_id = data.GetReverseLinkId(link_to_remove);
    removed_links.insert(rlink_id);
    for (Flow *flow : dropped_flows) {
        vector<Path *> *flow_paths = flow->GetPaths(max_finish_time_ms);
        int npaths = 0;
        for (Path *link_path : *flow_paths) {
            if (!HypothesisIntersectsPath(&removed_links, link_path)) {
                npaths++;
            }
        }
        //! TODO
        // assert(npaths > 0);
    }
}

// ... in the modified network
void BinFlowsByDevice(LogData &data, double max_finish_time_ms,
                      vector<Flow *> &dropped_flows, Hypothesis &removed_links,
                      map<int, set<Flow *>> &flows_by_device) {
    for (Flow *flow : dropped_flows) {
        vector<Path *> *flow_paths = flow->GetPaths(max_finish_time_ms);
        for (Path *link_path : *flow_paths) {
            if (!HypothesisIntersectsPath(&removed_links, link_path)) {
                Path device_path;
                data.GetDeviceLevelPath(flow, *link_path, device_path);
                for (int device : device_path)
                    flows_by_device[device].insert(flow);
            }
        }
        cout << "Dropped flow: " << flow->src << "("
             << data.hosts_to_racks[flow->src] << ")->" << flow->dest << "("
             << data.hosts_to_racks[flow->dest] << ") " << endl;
    }
}

int GetExplanationEdgesFromMap(map<int, set<Flow *>> &flows_by_device) {
    vector<pair<int, set<Flow *>>> sorted_map(flows_by_device.begin(),
                                              flows_by_device.end());
    sort(sorted_map.begin(), sorted_map.end(), SortByValueSize);
    int ntotal = 0;
    for (auto &[device, flows] : sorted_map) {
        cout << "Device " << device << " explains " << flows.size() << " drops"
             << endl;
        ntotal += flows.size();
    }
    cout << "Total explanation edges " << ntotal << endl;
    return ntotal;
}

set<int> GetEquivalentDevices(map<int, set<Flow *>> &flows_by_device) {
    set<int> ret;
    vector<pair<int, set<Flow *>>> sorted_map(flows_by_device.begin(),
                                              flows_by_device.end());
    sort(sorted_map.begin(), sorted_map.end(), SortByValueSize);
    int maxedges = sorted_map[0].second.size();
    for (auto &[device, flows] : sorted_map) {
        if (flows.size() < maxedges)
            break;
        cout << "Eq device " << device << " explains " << flows.size()
             << " drops" << endl;
        ret.insert(device);
    }
    return ret;
}

void AggLogData(LogData *data, int ntraces, LogData &result,
                int nopenmp_threads) {
    result.memoized_paths.clear();
    result.inverse_links = data[0].inverse_links;
    result.links_to_ids = data[0].links_to_ids;
    for (int ii = 0; ii < ntraces; ii++) {
        typedef vector<Path *> PathVec;
        unordered_map<Path *, Path *> path_mapping;
        unordered_map<PathVec *, PathVec *> pathvec_mapping;
        for (auto &[src_dst, mpaths] : data[ii].memoized_paths) {
            vector<Path *> *new_paths = new vector<Path *>();
            for (Path *path : mpaths->paths) {
                Path *new_path = new Path();
                // cout << "Pathh " << *path << " " << ii << " "
                // << src_dst << " " << (int)path->size() << endl;
                for (int link_id : *path) {
                    Link link = data[ii].inverse_links[link_id];
                    new_path->push_back(data[0].links_to_ids[link]);
                }
                path_mapping[path] = new_path;
                new_paths->push_back(new_path);
            }
            pathvec_mapping[&mpaths->paths] = new_paths;
        }
        cout << "Done mapping paths " << ii << endl;
        for (Flow *f : data[ii].flows) {
            Flow *fnew = new Flow(f->src, f->srcport, f->dest, f->destport,
                                  f->nbytes, f->start_time_ms);
            for (FlowSnapshot *fs : f->snapshots)
                fnew->snapshots.push_back(new FlowSnapshot(*fs));

            // !TODO: add paths
            if (f->paths != NULL) {
                // assert(f->paths->size() > 1);
                fnew->paths = pathvec_mapping[f->paths];
            }
            if (f->reverse_paths != NULL) {
                // assert(f->reverse_paths->size() > 1);
                fnew->reverse_paths = pathvec_mapping[f->reverse_paths];
            }

            fnew->first_link_id =
                data[0].links_to_ids[data[ii].inverse_links[f->first_link_id]];
            fnew->last_link_id =
                data[0].links_to_ids[data[ii].inverse_links[f->last_link_id]];

            assert(f->path_taken_vector.size() == 1);
            fnew->path_taken_vector.push_back(
                path_mapping[f->path_taken_vector[0]]);

            if (f->reverse_path_taken_vector.size() != 1) {
                // cout << f->paths->size() << " "
                //      << f->path_taken_vector.size() << " "
                //      << f->reverse_path_taken_vector.size() << endl;
                // assert (f->reverse_path_taken_vector.size() == 1);
            } else {
                fnew->reverse_path_taken_vector.push_back(
                    path_mapping[f->reverse_path_taken_vector[0]]);
            }

            result.flows.push_back(fnew);
        }
    }
}

bool RunFlock(LogData &data, string fail_file, double min_start_time_ms,
              double max_finish_time_ms, vector<double> &params,
              int nopenmp_threads) {
    BayesianNet estimator;
    estimator.SetParams(params);
    PATH_KNOWN = false;
    TRACEROUTE_BAD_FLOWS = false;
    INPUT_FLOW_TYPE = APPLICATION_FLOWS;

    estimator.SetLogData(&data, max_finish_time_ms, nopenmp_threads);

    // map[(src, dst)] = (failed_component(link/device), failparam)
    map<PII, pair<int, double>> failed_comps = ReadFailuresBlackHole(fail_file);

    Hypothesis localized_links;
    auto start_localization_time = chrono::high_resolution_clock::now();
    estimator.LocalizeFailures(min_start_time_ms, max_finish_time_ms,
                               localized_links, nopenmp_threads);

    vector<int> failed_device_links;
    for (auto &[k, v] : failed_comps) {
        int d = v.first;
        int d_id = data.links_to_ids[PII(d, d)];
        failed_device_links.push_back(d_id);
    }

    bool all_present = true;
    for (int d : failed_device_links) {
        all_present =
            all_present & (localized_links.find(d) != localized_links.end());
    }
    return all_present;
}

void OperatorScheme(vector<pair<string, string>> in_topo_traces,
                    double min_start_time_ms, double max_finish_time_ms,
                    int nopenmp_threads) {
    int ntraces = in_topo_traces.size();
    LogData data[ntraces];
    for (int ii = 0; ii < ntraces; ii++) {
        string topo_f = in_topo_traces[ii].first;
        string trace_f = in_topo_traces[ii].second;
        cout << "calling GetDataFromLogFileParallel on " << topo_f << ", "
             << trace_f << endl;
        GetDataFromLogFileParallel(trace_f, topo_f, &data[ii], nopenmp_threads);
    }
    cout << "Done reading " << endl;

    set<Link> failed_links;
    for (auto [l, failparam] : data[0].failed_links)
        failed_links.insert(l);

    set<Link> used_links_orig =
        GetUsedLinks(data, ntraces, min_start_time_ms, max_finish_time_ms);

    set<Link> used_links;

    int total_iter = 0, max_iter = 20;
    for (int ii = 0; ii < max_iter; ii++) {
        used_links = used_links_orig;
        int niter = 0;
        int unchanged = 0;
        while (niter < 200 and unchanged < 3) {
            niter++;
            // pick a random link
            vector<Link> used_links_vec(used_links.begin(), used_links.end());
            Link l = used_links_vec[rand() % used_links_vec.size()];

            // remove l and other links that pariticipate in paths that all have
            // l
            set<Link> remove_links = used_links;
            for (int ii = 0; ii < ntraces; ii++) {
                for (Flow *flow : data[ii].flows) {
                    vector<Path *> *flow_paths =
                        flow->GetPaths(max_finish_time_ms);
                    for (Path *path : *flow_paths) {
                        int l_id = data[0].links_to_ids[l];
                        if (path->find(l_id) == path->end() and
                            flow->first_link_id != l_id and
                            flow->last_link_id != l_id) {
                            for (int link_id : *path) {
                                Link link = data[ii].inverse_links[link_id];
                                if (remove_links.find(link) !=
                                    remove_links.end()) {
                                    remove_links.erase(link);
                                }
                            }
                        }
                    }
                }
            }

            bool covered = true;
            for (Link fl : failed_links) {
                covered =
                    covered and (remove_links.find(fl) != remove_links.end());
            }

            // cout << l << " remove_links " << remove_links << " " << covered
            // << " " << used_links.size() << endl;

            if (covered) {
                if (used_links == remove_links)
                    unchanged++;
                else
                    unchanged = 0;
                used_links = remove_links;
            } else {
                for (Link rl : remove_links)
                    used_links.erase(rl);
                unchanged = 0;
            }
        }
        cout << "iterations for localization " << niter << endl;
        total_iter += niter;
    }
    cout << "Operator avg. iterations " << double(total_iter) / max_iter
         << endl;
}

set<int> LocalizeViaFlock(LogData *data, int ntraces, string fail_file,
                          double min_start_time_ms, double max_finish_time_ms,
                          int nopenmp_threads) {
    BayesianNet estimator;
    // vector<double> params = {1.0 - 0.49, 5.0e-3, -10.0}; // ft_k10
    // vector<double> params = {1.0 - 0.41, 1.0e-3, -10.0}; // ft_k12
    vector<double> params = {1.0 - 0.49, 0.75e-3, -10.0}; // ft_k14'

    estimator.SetParams(params);
    PATH_KNOWN = false;
    TRACEROUTE_BAD_FLOWS = false;
    INPUT_FLOW_TYPE = APPLICATION_FLOWS;

    LogData agg;
    AggLogData(data, ntraces, agg, nopenmp_threads);
    estimator.SetLogData(&agg, max_finish_time_ms, nopenmp_threads);

    //! TODO: set failed components

    Hypothesis localized_links;
    auto start_localization_time = chrono::high_resolution_clock::now();
    estimator.LocalizeFailures(min_start_time_ms, max_finish_time_ms,
                               localized_links, nopenmp_threads);

    Hypothesis failed_links_set;
    data[0].GetFailedLinkIds(failed_links_set);
    PDD precision_recall =
        GetPrecisionRecall(failed_links_set, localized_links, &data[0]);

    set<int> equivalent_devices;
    for (int link_id : localized_links) {
        equivalent_devices.insert(data[0].inverse_links[link_id].first);
    }

    cout << "Output Hypothesis: " << equivalent_devices << " precision_recall "
         << precision_recall.first << " " << precision_recall.second << endl;
    cout << "Finished localization in "
         << GetTimeSinceSeconds(start_localization_time) << " seconds" << endl;
    cout << "****************************" << endl << endl << endl;
    return equivalent_devices;
}

set<vector<Link>> GetSetOfActualPath(LogData data, double max_finish_time_ms) {
    set<vector<Link>> localized_paths;
    for (Flow *flow : data.flows) {
        vector<Path *> *flow_paths = flow->GetPaths(max_finish_time_ms);
        for (Path *path : *flow_paths) {
            vector<Link> path_link;
            for (int link_id : *path) {
                Link link = data.inverse_links[link_id];
                path_link.push_back(link);
            }
            localized_paths.insert(path_link);
        }
    }
    return localized_paths;
}

set<int> LocalizeViaNobody(LogData *data, int ntraces, string fail_file,
                           double min_start_time_ms, double max_finish_time_ms,
                           int nopenmp_threads) {

    set<vector<Link>> localized_paths;
    for (Flow *flow : data[0].flows) {
        vector<Path *> *flow_paths = flow->GetPaths(max_finish_time_ms);
        for (Path *path : *flow_paths) {
            vector<Link> path_link;
            for (int link_id : *path) {
                Link link = data[0].inverse_links[link_id];
                path_link.push_back(link);
            }
            localized_paths.insert(path_link);
        }
    }

    set<int> healthy_devices;

    for (int ii = 1; ii < ntraces; ii++) {
        set<vector<Link>> new_localized_paths;
        set<vector<Link>> temp;
        for (Flow *flow : data[ii].flows) {
            vector<Path *> *flow_paths = flow->GetPaths(max_finish_time_ms);
            for (Path *path : *flow_paths) {
                vector<Link> path_link;
                for (int link_id : *path) {
                    Link link = data[ii].inverse_links[link_id];
                    path_link.push_back(link);
                }
                new_localized_paths.insert(path_link);
            }
        }

        cout << "Localized paths in iter " << ii << ": " << localized_paths
             << endl;
        cout << "Count " << localized_paths.size() << endl;

        cout << "New localized paths in iter " << ii << ": "
             << new_localized_paths << endl;
        cout << "Count " << new_localized_paths.size() << endl;

        if (IsProblemSolved(&(data[ii]), max_finish_time_ms) == 1) {
            cout << "Problem was solved" << endl;
            set_difference(localized_paths.begin(), localized_paths.end(),
                           new_localized_paths.begin(),
                           new_localized_paths.end(),
                           std::inserter(temp, temp.begin()));
            for (vector<Link> path : new_localized_paths) {
                for (Link link : path) {
                    if (link.first == link.second) {
                        healthy_devices.insert(link.first);
                    }
                }
            }
        } else {
            cout << "Problem was not solved" << endl;
            set_intersection(localized_paths.begin(), localized_paths.end(),
                             new_localized_paths.begin(),
                             new_localized_paths.end(),
                             std::inserter(temp, temp.begin()));
        }

        localized_paths = temp;
    }

    set<int> equivalent_devices;
    set<int> temp2;
    for (vector<Link> path : localized_paths) {
        for (Link link : path) {
            if (link.first == link.second) {
                equivalent_devices.insert(link.first);
            }
        }
    }
    set_difference(equivalent_devices.begin(), equivalent_devices.end(),
                   healthy_devices.begin(), healthy_devices.end(),
                   std::inserter(temp2, temp2.begin()));
    equivalent_devices = temp2;
    cout << "Size of equivalent devices " << equivalent_devices.size() << endl;

    return equivalent_devices;
}

int IsProblemSolved(LogData *data, double max_finish_time_ms) {
    float failure_threshold = 0.5;
    int shortest_paths = 0;
    int failed_flows = 0, total_flows = 0;

    for (Flow *flow : data->flows) {
        if (flow->snapshots[0]->packets_lost ==
            flow->snapshots[0]->packets_sent) {
            failed_flows++;
        }
        total_flows++;
        shortest_paths = (flow->GetPaths(max_finish_time_ms))->size();
    }
    cout << "Shortest paths " << shortest_paths << endl;
    cout << "Total flows " << total_flows << endl;
    cout << "Failed flows " << failed_flows << endl;
    if (((float)failed_flows) / total_flows <=
        failure_threshold / shortest_paths) {
        return 1;
    }
    return 0;
}

set<Link> GetUsedLinks(LogData *data, int ntraces, double min_start_time_ms,
                       double max_finish_time_ms) {
    set<Link> used_links;
    for (int ii = 0; ii < ntraces; ii++) {
        for (Flow *flow : data[ii].flows) {
            vector<Path *> *flow_paths = flow->GetPaths(max_finish_time_ms);
            for (Path *path : *flow_paths) {
                for (int link_id : *path) {
                    Link link = data[ii].inverse_links[link_id];
                    used_links.insert(link);
                }
                // Path device_path;
                // data[ii].GetDeviceLevelPath(flow, *path, device_path);
                // cout << "path " << device_path << endl;
            }
            // assert (ii == 0);
            used_links.insert(data[ii].inverse_links[flow->first_link_id]);
            used_links.insert(data[ii].inverse_links[flow->last_link_id]);
        }
        cout << "GetUsedLinks: finished iteration " << ii << endl;
    }
    return used_links;
}

void LocalizeFailure(vector<pair<string, string>> &in_topo_traces,
                     double min_start_time_ms, double max_finish_time_ms,
                      int nopenmp_threads, string sequence_mode,
                      string inference_mode) {
    int ntraces = in_topo_traces.size();
    vector<Flow *> dropped_flows[ntraces];
    LogData data[ntraces];
    for (int ii = 0; ii < ntraces; ii++) {
        string topo_f = in_topo_traces[ii].first;
        string trace_f = in_topo_traces[ii].second;
        cout << "calling GetDataFromLogFileParallel on " << topo_f << ", "
             << trace_f << endl;
        GetDataFromLogFileParallel(trace_f, topo_f, &data[ii], nopenmp_threads);
        GetDroppedFlows(data[ii], dropped_flows[ii]);
    }
    cout << "Done reading " << endl;
    string fail_file = in_topo_traces[0].second + ".fails";
    set<Link> removed_links;
    map<int, set<Flow *>> flows_by_device_agg;
    BinFlowsByDeviceAgg(data, dropped_flows, ntraces, removed_links,
                        flows_by_device_agg, max_finish_time_ms);

    set<int> eq_devices;
    /* Use a fault localization algorithm to obtain equivalent set of localized
     * devices
     */
    // equivalent_devices = GetEquivalentDevices(flows_by_device_agg);
    if (inference_mode == "Flock") {
        eq_devices =
            LocalizeViaFlock(data, ntraces, fail_file, min_start_time_ms,
                             max_finish_time_ms, nopenmp_threads);
    } else if (inference_mode == "Naive") {
        eq_devices =
            LocalizeViaNobody(data, ntraces, fail_file, min_start_time_ms,
                              max_finish_time_ms, nopenmp_threads);
    }

    cout << "equivalent devices " << eq_devices << " size " << eq_devices.size()
         << endl;

    GetExplanationEdgesFromMap(flows_by_device_agg);
    cout << "Explaining drops" << endl;

    int max_iter = 1;
    set<set<int>> eq_device_sets({eq_devices});
    set<Link> used_links =
        GetUsedLinks(data, ntraces, min_start_time_ms, max_finish_time_ms);
    cout << "Used links " << used_links.size() << " : " << used_links << endl;
    double last_score = 0.0;
    double curr_score;
    while (1) {
        MicroChange* mc;
        tie(mc, curr_score) =  GetBestMicroChange(data, dropped_flows, ntraces,
                                  eq_devices, eq_device_sets, used_links,
                                  max_finish_time_ms, sequence_mode, nopenmp_threads);

        if (curr_score - last_score < 1.0e-3 or max_iter == 0 or
            curr_score < 1.0e-8)
            break;

        cout << "Best MicroChange: " << mc << " score " << curr_score << endl;
        last_score = curr_score;
        max_iter--;
    }
}

pair<MicroChange*, double>
GetBestMicroChange(LogData *data, vector<Flow *> *dropped_flows,
                   int ntraces, set<int> &eq_devices,
                   set<set<int>> &eq_device_sets, set<Link> &used_links,
                   double max_finish_time_ms, string sequence_mode,
                   int nopenmp_threads) {
    Link best_link_to_remove;
    double score;
    if (sequence_mode == "Random") {
        tie(best_link_to_remove, score) = GetRandomLinkToRemoveITA(
            data, dropped_flows, ntraces, eq_devices, eq_device_sets,
            used_links, max_finish_time_ms, nopenmp_threads);
    } else if (sequence_mode == "Intelligent") {
        // tie(best_link_to_remove, score) = GetBestLinkToRemoveITA(
        tie(best_link_to_remove, score) = GetBestLinkToRemovePairs(
            data, dropped_flows, ntraces, eq_devices, eq_device_sets,
            used_links, max_finish_time_ms, nopenmp_threads);
    }
    RemoveLinkMc* mc = new RemoveLinkMc(best_link_to_remove);
    cout << mc << endl;
    return pair<MicroChange*, double>(mc, score);
}

void LocalizeScoreAgg(vector<pair<string, string>> &in_topo_traces,
                      double max_finish_time_ms, int nopenmp_threads) {
    int ntraces = in_topo_traces.size();
    vector<Flow *> dropped_flows[ntraces];
    LogData data[ntraces];
    for (int ii = 0; ii < ntraces; ii++) {
        string topo_f = in_topo_traces[ii].first;
        string trace_f = in_topo_traces[ii].second;
        cout << "calling GetDataFromLogFileParallel on " << topo_f << ", "
             << trace_f << endl;
        GetDataFromLogFileParallel(trace_f, topo_f, &data[ii], nopenmp_threads);
        GetDroppedFlows(data[ii], dropped_flows[ii]);
    }

    set<Link> removed_links;
    map<int, set<Flow *>> flows_by_device_agg;
    BinFlowsByDeviceAgg(data, dropped_flows, ntraces, removed_links,
                        flows_by_device_agg, max_finish_time_ms);
    set<int> equivalent_devices = GetEquivalentDevices(flows_by_device_agg);
    cout << "equivalent devices " << equivalent_devices << " size "
         << equivalent_devices.size() << endl;

    GetExplanationEdgesFromMap(flows_by_device_agg);
    cout << "Explaining drops" << endl;

    int old_expl_edges = int(1.0e9), curr_expl_edges = int(1.0e9);
    int max_iter = 10;
    while (1) {
        auto [best_link_to_remove, expl_edges] = GetBestLinkToRemoveAgg(
            data, dropped_flows, ntraces, equivalent_devices, removed_links,
            max_finish_time_ms, nopenmp_threads);
        old_expl_edges = curr_expl_edges;
        curr_expl_edges = expl_edges;
        cout << "Best link to remove " << best_link_to_remove
             << " nexplanation edges " << expl_edges << " removed_links "
             << removed_links << endl;
        // if (old_expl_edges - curr_expl_edges < 10 or max_iter == 0) break;
        if (old_expl_edges - curr_expl_edges < 1 or max_iter == 0)
            break;
        max_iter--;
        removed_links.insert(best_link_to_remove);
        Link rlink(best_link_to_remove.second, best_link_to_remove.first);
        removed_links.insert(rlink);
    }
}

Link GetMostUsedLink(LogData *data, vector<Flow *> *dropped_flows, int ntraces,
                     int device, double max_finish_time_ms,
                     int nopenmp_threads) {
    map<Link, int> link_ctrs;
    for (int tt = 0; tt < ntraces; tt++) {
        // cout << "Done with trace " << tt << endl;
        for (Flow *flow : dropped_flows[tt]) {
            // cout << "Done with flow " << flow << endl;
            vector<Path *> *flow_paths = flow->GetPaths(max_finish_time_ms);
            for (Path *link_path : *flow_paths) {
                Path device_path;
                data[tt].GetDeviceLevelPath(flow, *link_path, device_path);
                for (int ii = 1; ii < device_path.size(); ii++) {
                    if ((device_path[ii - 1] == device or
                         device_path[ii] == device) and
                        (device_path[ii - 1] != device_path[ii])) {
                        Link l(device_path[ii - 1], device_path[ii]);
                        link_ctrs[l]++;
                    }
                }
            }
        }
    }
    map<Link, int>::iterator most_used =
        max_element(link_ctrs.begin(), link_ctrs.end(),
                    [](const std::pair<Link, int> &a,
                       const std::pair<Link, int> &b) -> bool {
                        return a.second < b.second;
                    });
    return most_used->first;
}

pair<Link, int>
GetBestLinkToRemoveAgg(LogData *data, vector<Flow *> *dropped_flows,
                       int ntraces, set<int> &equivalent_devices,
                       set<Link> &prev_removed_links, double max_finish_time_ms,
                       int nopenmp_threads) {
    set<Link> removed_links;
    int total_expl_edges =
        GetExplanationEdgesAgg(data, dropped_flows, ntraces, equivalent_devices,
                               removed_links, max_finish_time_ms);
    int min_expl_edges = int(1e9);
    Link best_link_to_remove = Link(-1, -1);
    for (Link link : data[0].inverse_links) {
        int link_id = data[0].links_to_ids[link];
        Link rlink = Link(link.second, link.first);
        if (data[0].IsNodeSwitch(link.first) and
            data[0].IsNodeSwitch(link.second) and
            !data[0].IsLinkDevice(link_id)) {
            removed_links = prev_removed_links;
            removed_links.insert(link);
            removed_links.insert(rlink);
            cout << "Removing link " << link << endl;
            for (int ii = 0; ii < ntraces; ii++) {
                int link_id_ii = data[ii].links_to_ids[link];
                CheckShortestPathExists(data[ii], max_finish_time_ms,
                                        dropped_flows[ii], link_id_ii);
            }

            int expl_edges = GetExplanationEdgesAgg(
                data, dropped_flows, ntraces, equivalent_devices, removed_links,
                max_finish_time_ms);
            // expl_edges = max(expl_edges, total_expl_edges - expl_edges);
            if (expl_edges < min_expl_edges or
                (expl_edges == min_expl_edges and
                 (equivalent_devices.find(link.first) !=
                      equivalent_devices.end() or
                  equivalent_devices.find(link.second) !=
                      equivalent_devices.end()))) {
                min_expl_edges = expl_edges;
                best_link_to_remove = link;
            }
        }
    }
    return pair<Link, int>(best_link_to_remove, min_expl_edges);
}

void BinFlowsByDeviceAgg(LogData *data, vector<Flow *> *dropped_flows,
                         int ntraces, set<Link> &removed_links,
                         map<int, set<Flow *>> &flows_by_device,
                         double max_finish_time_ms) {
    for (int ii = 0; ii < ntraces; ii++) {
        Hypothesis removed_links_hyp;
        for (Link l : removed_links) {
            if (data[ii].links_to_ids.find(l) != data[ii].links_to_ids.end())
                removed_links_hyp.insert(data[ii].links_to_ids[l]);
        }
        BinFlowsByDevice(data[ii], max_finish_time_ms, dropped_flows[ii],
                         removed_links_hyp, flows_by_device);
    }
}

void GetEqDevicesInFlowPaths(LogData &data, Flow *flow,
                             set<int> &equivalent_devices,
                             Hypothesis &removed_links,
                             double max_finish_time_ms, set<int> &result) {
    vector<Path *> *flow_paths = flow->GetPaths(max_finish_time_ms);
    for (Path *link_path : *flow_paths) {
        if (!HypothesisIntersectsPath(&removed_links, link_path)) {
            Path device_path;
            data.GetDeviceLevelPath(flow, *link_path, device_path);
            for (int device : device_path) {
                if (equivalent_devices.find(device) !=
                    equivalent_devices.end()) {
                    result.insert(device);
                }
            }
        }
    }
}

// ITA: information theoretic algorithm
void GetEqDeviceSetsITA(LogData *data, vector<Flow *> *dropped_flows,
                        int ntraces, set<int> &equivalent_devices,
                        Link removed_link, double max_finish_time_ms,
                        set<set<int>> &result) {
    int link_id = data[0].links_to_ids[removed_link];
    int rlink_id = data[0].GetReverseLinkId(link_id);
    Hypothesis removed_links({link_id, rlink_id});

    // do it for flows from the first trace in the unchanged network
    for (Flow *flow : dropped_flows[0]) {
        set<int> flow_eq_devices;
        GetEqDevicesInFlowPaths(data[0], flow, equivalent_devices,
                                removed_links, max_finish_time_ms,
                                flow_eq_devices);
        if (result.find(flow_eq_devices) == result.end()) {
            result.insert(flow_eq_devices);
        }
    }
    if (VERBOSE) {
        cout << "Printing eq device sets" << endl;
        for (auto &s : result)
            cout << "Eq device set " << s << endl;
        cout << "Done printing eq device sets " << result.size() << endl;
    }
}

void GetDeviceColors(set<int> &equivalent_devices, map<int, int> &device_colors,
                     set<set<int>> &eq_device_sets) {
    /*
        Use a coloring algorithm to find all possible intersection sets
    */

    // initialize colors
    int curr_color = 0;
    for (int d : equivalent_devices)
        device_colors[d] = curr_color;

    for (auto &eq_device_set : eq_device_sets) {
        // update colors of all devices in eq_device_set
        // mapping from old color to new color
        map<int, int> col_newcol;
        for (int d : eq_device_set) {
            // d should be a device in equivalent_devices
            assert(device_colors.find(d) != device_colors.end());
            int c = device_colors[d];
            if (col_newcol.find(c) == col_newcol.end()) {
                col_newcol[c] = ++curr_color;
            }
            device_colors[d] = col_newcol[c];
        }
    }
}

void GetColorCounts(map<int, int> &device_colors, map<int, int> &col_cnts) {
    for (auto [d, c] : device_colors) {
        // cout << "Device color " << d << " " << c << endl;
        col_cnts[c]++;
    }
}

// ITA: information theoretic algorithm
// Replacement of GetExplanationEdgesAgg
// eq_device_sets should at least have the entire equivalent_devices set
double GetEqDeviceSetsMeasureITA(LogData *data, vector<Flow *> *dropped_flows,
                                 int ntraces, set<int> &equivalent_devices,
                                 Link removed_link, double max_finish_time_ms,
                                 set<set<int>> &eq_device_sets) {
    GetEqDeviceSetsITA(data, dropped_flows, ntraces, equivalent_devices,
                       removed_link, max_finish_time_ms, eq_device_sets);
    map<int, int> device_colors, col_cnts;
    GetDeviceColors(equivalent_devices, device_colors, eq_device_sets);
    GetColorCounts(device_colors, col_cnts);

    double information = 0.0;
    for (auto [c, cnt] : col_cnts) {
        // cout << "Device color cnt " << c << " " << cnt << endl;
        double p = cnt / (double)equivalent_devices.size();
        information += -p * log(p);
    }
    return information;
}

// Pairs: count number of pairs that will be distinguished by the micro-change
// sequence. eq_device_sets should have the entire equivalent_devices set
int GetEqDeviceSetsMeasurePairs(LogData *data, vector<Flow *> *dropped_flows,
                                int ntraces, set<int> &equivalent_devices,
                                Link removed_link, double max_finish_time_ms,
                                set<set<int>> &eq_device_sets) {
    GetEqDeviceSetsITA(data, dropped_flows, ntraces, equivalent_devices,
                       removed_link, max_finish_time_ms, eq_device_sets);
    map<int, int> device_colors, col_cnts;
    GetDeviceColors(equivalent_devices, device_colors, eq_device_sets);
    GetColorCounts(device_colors, col_cnts);

    int pairs = 0;
    for (auto [c, cnt] : col_cnts) {
        pairs += cnt * (equivalent_devices.size() - cnt);
    }
    return pairs;
}

pair<Link, double>
GetBestLinkToRemovePairs(LogData *data, vector<Flow *> *dropped_flows,
                         int ntraces, set<int> &equivalent_devices,
                         set<set<int>> &eq_device_sets, set<Link> &used_links,
                         double max_finish_time_ms, int nopenmp_threads) {
    int max_pairs = 0;
    Link best_link_to_remove = Link(-1, -1);
    for (Link link : used_links) {
        int link_id = data[0].links_to_ids[link];
        Link rlink = Link(link.second, link.first);
        if (data[0].IsNodeSwitch(link.first) and
            data[0].IsNodeSwitch(link.second) and
            !data[0].IsLinkDevice(link_id)) {
            for (int ii = 0; ii < ntraces; ii++) {
                int link_id_ii = data[ii].links_to_ids[link];
                CheckShortestPathExists(data[ii], max_finish_time_ms,
                                        dropped_flows[ii], link_id_ii);
            }
            set<set<int>> eq_device_sets_copy = eq_device_sets;
            int pairs = GetEqDeviceSetsMeasurePairs(
                data, dropped_flows, ntraces, equivalent_devices, link,
                max_finish_time_ms, eq_device_sets_copy);
            cout << "Removing link " << link << " pairs " << pairs << endl;
            if (pairs > max_pairs) {
                best_link_to_remove = link;
                max_pairs = pairs;
            }
        }
    }
    // do again for the best link to populate eq_device_sets
    GetEqDeviceSetsMeasurePairs(data, dropped_flows, ntraces,
                                equivalent_devices, best_link_to_remove,
                                max_finish_time_ms, eq_device_sets);
    return pair<Link, double>(best_link_to_remove, (double)max_pairs);
}

// ITA: information theoretic algorithm
pair<Link, double>
GetBestLinkToRemoveITA(LogData *data, vector<Flow *> *dropped_flows,
                       int ntraces, set<int> &equivalent_devices,
                       set<set<int>> &eq_device_sets, set<Link> &used_links,
                       double max_finish_time_ms, int nopenmp_threads) {
    double max_information = 0.0;
    Link best_link_to_remove = Link(-1, -1);
    for (Link link : used_links) {
        int link_id = data[0].links_to_ids[link];
        Link rlink = Link(link.second, link.first);
        if (data[0].IsNodeSwitch(link.first) and
            data[0].IsNodeSwitch(link.second) and
            !data[0].IsLinkDevice(link_id)) {
            for (int ii = 0; ii < ntraces; ii++) {
                int link_id_ii = data[ii].links_to_ids[link];
                CheckShortestPathExists(data[ii], max_finish_time_ms,
                                        dropped_flows[ii], link_id_ii);
            }
            set<set<int>> eq_device_sets_copy = eq_device_sets;
            double information = GetEqDeviceSetsMeasureITA(
                data, dropped_flows, ntraces, equivalent_devices, link,
                max_finish_time_ms, eq_device_sets_copy);
            cout << "Removing link " << link << " information " << information
                 << endl;
            if (information > max_information) {
                best_link_to_remove = link;
                max_information = information;
            }
        }
    }
    // Do again for the best link to populate eq_device_sets
    GetEqDeviceSetsMeasureITA(data, dropped_flows, ntraces, equivalent_devices,
                              best_link_to_remove, max_finish_time_ms,
                              eq_device_sets);
    return pair<Link, double>(best_link_to_remove, max_information);
}

pair<Link, double>
GetRandomLinkToRemoveITA(LogData *data, vector<Flow *> *dropped_flows,
                         int ntraces, set<int> &equivalent_devices,
                         set<set<int>> &eq_device_sets, set<Link> &used_links,
                         double max_finish_time_ms, int nopenmp_threads) {
    vector<pair<Link, double>> used_links_with_information;

    for (Link link : used_links) {
        int link_id = data[0].links_to_ids[link];
        Link rlink = Link(link.second, link.first);
        if (data[0].IsNodeSwitch(link.first) and
            data[0].IsNodeSwitch(link.second) and
            !data[0].IsLinkDevice(link_id)) {
            for (int ii = 0; ii < ntraces; ii++) {
                int link_id_ii = data[ii].links_to_ids[link];
                CheckShortestPathExists(data[ii], max_finish_time_ms,
                                        dropped_flows[ii], link_id_ii);
            }
            set<set<int>> eq_device_sets_copy = eq_device_sets;
            double information = GetEqDeviceSetsMeasureITA(
                data, dropped_flows, ntraces, equivalent_devices, link,
                max_finish_time_ms, eq_device_sets_copy);
            cout << "Removing link " << link << " information " << information
                 << endl;
            if (information > 0) {
                used_links_with_information.push_back(
                    pair<Link, double>(link, information));
            }
        }
    }
    if (used_links_with_information.size() == 0) {
        return pair<Link, double>(Link(-1, -1), 0);
    }

    auto [best_link_to_remove, max_information] =
        used_links_with_information[rand() %
                                    used_links_with_information.size()];

    // Do again for the best link to populate eq_device_sets
    GetEqDeviceSetsMeasureITA(data, dropped_flows, ntraces, equivalent_devices,
                              best_link_to_remove, max_finish_time_ms,
                              eq_device_sets);
    return pair<Link, double>(best_link_to_remove, max_information);
}

int GetExplanationEdgesAgg2(LogData *data, vector<Flow *> *dropped_flows,
                            int ntraces, set<int> &equivalent_devices,
                            set<Link> &removed_links,
                            double max_finish_time_ms) {
    map<int, set<Flow *>> flows_by_device;
    BinFlowsByDeviceAgg(data, dropped_flows, ntraces, removed_links,
                        flows_by_device, max_finish_time_ms);
    set<int> new_eq_devices = GetEquivalentDevices(flows_by_device);
    int ret =
        new_eq_devices.size(); // * 10000000 + 100 - (maxedges - nextedges);
    cout << "Total explanation edges " << ret << endl;
    return ret;
}

int GetExplanationEdgesAgg(LogData *data, vector<Flow *> *dropped_flows,
                           int ntraces, set<int> &equivalent_devices,
                           set<Link> &removed_links,
                           double max_finish_time_ms) {
    map<int, set<Flow *>> flows_by_device;
    BinFlowsByDeviceAgg(data, dropped_flows, ntraces, removed_links,
                        flows_by_device, max_finish_time_ms);
    int ntotal = 0;
    for (int device : equivalent_devices) {
        cout << "Flows for device " << device << " "
             << flows_by_device[device].size() << endl;
        ntotal += flows_by_device[device].size();
    }
    cout << "Total explanation edges " << ntotal << endl;
    return ntotal;
}

map<PII, pair<int, double>> ReadFailuresBlackHole(string fail_file) {
    auto start_time = chrono::high_resolution_clock::now();
    ifstream infile(fail_file);
    string line;
    char op[30];
    // map[(src, dst)] = (failed_component(link/device), failparam)
    map<PII, pair<int, double>> fails;
    while (getline(infile, line)) {
        char *linec = const_cast<char *>(line.c_str());
        GetString(linec, op);
        if (StringStartsWith(op, "Failing_component")) {
            int src, dest, device; // node1, node2;
            double failparam;
            GetFirstInt(linec, src);
            GetFirstInt(linec, dest);
            // GetFirstInt(linec, node1);
            // GetFirstInt(linec, node2);
            GetFirstInt(linec, device);
            GetFirstDouble(linec, failparam);
            // fails[PII(src, dest)] = pair<Link, double>(Link(node1, node2),
            // failparam);
            fails[PII(src, dest)] = pair<int, double>(device, failparam);
            if (VERBOSE) {
                // cout<< "Failed component "<<src<<" "<<dest<<"
                // ("<<node1<<","<<node2<<") "<<failparam<<endl;
                cout << "Failed component " << src << " " << dest << " "
                     << device << " " << failparam << endl;
            }
        }
    }
    if (VERBOSE) {
        cout << "Read fail file in " << GetTimeSinceSeconds(start_time)
             << " seconds, numfails " << fails.size() << endl;
    }
    return fails;
}
