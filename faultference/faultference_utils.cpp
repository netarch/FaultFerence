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

bool USE_ACTIVE_PROBE_MC = true;
const int SCORE_THRESHOLD = 1.0e-3;
vector<int> ACTIVE_PROBE_FORBIDDEN_LIST;
vector<int> LINK_REMOVAL_FORBIDDEN_LIST;

bool ActiveProbeForbidden(int elem){
    if (ACTIVE_PROBE_FORBIDDEN_LIST.size() == 0){
        ifstream inputFile("./forbidden/active-probe");
        if (inputFile) {        
            int value;
            cout << "Reading forbidden probes: ";
            while ( inputFile >> value ) {
                cout << value << " ";
                ACTIVE_PROBE_FORBIDDEN_LIST.push_back(value);
            }
            cout << endl;
        }
        else{
            cout << "*** FILE READING ERROR ***";
        }
    }
    if (find(ACTIVE_PROBE_FORBIDDEN_LIST.begin(), ACTIVE_PROBE_FORBIDDEN_LIST.end(), elem) == ACTIVE_PROBE_FORBIDDEN_LIST.end()){
        return false;
    }
    return true;
}

bool LinkRemovalForbidden(int elem){
    if (LINK_REMOVAL_FORBIDDEN_LIST.size() == 0){
        ifstream inputFile("./forbidden/link-removal");
        if (inputFile) {        
            int value;
            cout << "Reading forbidden link removals: ";
            while ( inputFile >> value ) {
                cout << value << " ";
                LINK_REMOVAL_FORBIDDEN_LIST.push_back(value);
            }
            cout << endl;
        }
        else{
            cout << "*** FILE READING ERROR ***";
        }
    }
    if (find(LINK_REMOVAL_FORBIDDEN_LIST.begin(), LINK_REMOVAL_FORBIDDEN_LIST.end(), elem) == LINK_REMOVAL_FORBIDDEN_LIST.end()){
        return false;
    }
    return true;
}


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
        /*
        cout << "Dropped flow: " << flow->src << "("
             << data.hosts_to_racks[flow->src] << ")->" << flow->dest << "("
             << data.hosts_to_racks[flow->dest] << ") " << endl;
        */
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
                          int nopenmp_threads, string topo_name) {
    BayesianNet estimator;

    map<string, vector<double>> params;
    params["ft_deg10"] = {1.0 - 0.49, 5.0e-3, -10.0};
    params["ft_deg12"] = {1.0 - 0.49, 6.0e-4, -20.0};
    params["ft_deg14"] = {1.0 - 0.41, 1.5e-4, -20.0};
    params["ft_deg16"] = {1.0 - 0.49, 1.0e-6, -10.0};
    params["ft_deg18"] = {1.0 - 0.41, 1.0e-6, -10.0};
    params["ft_deg20"] = {1.0 - 0.41, 1.0e-6, -20.0};

    params["rg_deg10"] = {1.0 - 0.73, 1.0e-6, -10.0};
    params["rg_deg12"] = {1.0 - 0.73, 1.0e-6, -10.0};
    params["rg_deg14"] = {1.0 - 0.73, 1.0e-6, -10.0};
    params["rg_deg16"] = {1.0 - 0.73, 1.0e-6, -10.0};
    params["rg_deg18"] = {1.0 - 0.73, 3.0e-4, -10.0};
    params["rg_deg20"] = {1.0 - 0.73, 1.0e-6, -10.0};

    params["ASN2k"] = {1.0 - 0.81, 1.0e-6, -10.0};
    params["B4"] = {1.0 - 0.73, 1.0e-6, -10.0};
    params["Kdl"] = {1.0 - 0.89, 1.0e-6, -10.0};
    params["UsC"] = {1.0 - 0.81, 1.0e-6, -10.0};


    estimator.SetParams(params[topo_name]);
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
                           int nopenmp_threads, string topo_name, set<int> prev_eq_devices, string micro_change) {

    set<int> localized_devices, new_localized_devices;
    cout << "New change offered: " << micro_change << ", Prev devices: " << prev_eq_devices << endl;

    map<Flow *, map<int, int>> path_per_link_per_flow;
    int min_path_per_link = 1000;

    if (prev_eq_devices.find(-1) != prev_eq_devices.end()){
        for (Flow *flow : data[0].flows) {
            vector<Path *> *flow_paths = flow->GetPaths(max_finish_time_ms);
            for (Path *path : *flow_paths) {
                for (int link_id : *path) {
                    Link link = data[0].inverse_links[link_id];
                    if (link.first == link.second) {
                        localized_devices.insert(link.first);
                    }
                }
            }
        }
        return localized_devices;
    }
    else{
        localized_devices = prev_eq_devices;
    }

    if (micro_change == "REMOVE_LINK"){
        // calculate the min_path_per_link
        for (Flow *flow : data[0].flows) {
            vector<Path *> *flow_paths = flow->GetPaths(max_finish_time_ms);
            for (Path *path : *flow_paths) {
                for (int link_id : *path) {
                    path_per_link_per_flow[flow].emplace(link_id, 0);
                    path_per_link_per_flow[flow][link_id] += 1;
                }
            }
            for (auto it = path_per_link_per_flow[flow].begin();
                it != path_per_link_per_flow[flow].end(); ++it) {
                if (it->second <= min_path_per_link) {
                    min_path_per_link = it->second;
                }
            }
        }

        set<int> temp_devices;
        for (Flow *flow : data[ntraces - 1].flows) {
            vector<Path *> *flow_paths = flow->GetPaths(max_finish_time_ms);
            for (Path *path : *flow_paths) {
                for (int link_id : *path) {
                    Link link = data[ntraces - 1].inverse_links[link_id];
                    if (link.first == link.second) {
                        new_localized_devices.insert(link.first);
                    }
                }
            }
        }

        cout << "Localized paths in iter " << ntraces - 1 << ": " << localized_devices
                << endl;
        cout << "Count " << localized_devices.size() << endl;

        cout << "New localized paths in iter " << ntraces - 1 << ": "
                << new_localized_devices << endl;
        cout << "Count " << new_localized_devices.size() << endl;

        if (IsProblemSolved(&(data[ntraces - 1]), max_finish_time_ms,
                            min_path_per_link) == 1) {
            cout << "Problem was solved" << endl;
            set_difference(localized_devices.begin(), localized_devices.end(),
                            new_localized_devices.begin(),
                            new_localized_devices.end(),
                            std::inserter(temp_devices, temp_devices.begin()));
        } else {
            cout << "Problem was not solved" << endl;
            set_intersection(localized_devices.begin(), localized_devices.end(),
                                new_localized_devices.begin(),
                                new_localized_devices.end(),
                                std::inserter(temp_devices, temp_devices.begin()));
        }

        localized_devices = temp_devices;
    }
    else if (micro_change == "ACTIVE_PROBE"){
        set<int> temp_devices;
        int probes_sent = 0, probes_lost = 0;
        for (Flow *flow : data[ntraces - 1].flows) {
            if (flow->IsFlowActive()) {
                vector<Path *> *flow_paths = flow->GetPaths(max_finish_time_ms);
                for (Path *path : *flow_paths) {
                    for (int link_id : *path) {
                        Link link = data[ntraces - 1].inverse_links[link_id];
                        if (link.first == link.second) {
                            new_localized_devices.insert(link.first);
                        }
                    }
                }
                probes_sent += flow->snapshots[0]->packets_sent;
                probes_lost += flow->snapshots[0]->packets_lost;
            }
        }
        if (probes_lost == probes_sent){
            set_intersection(localized_devices.begin(), localized_devices.end(),
                        new_localized_devices.begin(),
                        new_localized_devices.end(),
                        std::inserter(temp_devices, temp_devices.begin()));
        }
        else{
            set_difference(localized_devices.begin(), localized_devices.end(),
                    new_localized_devices.begin(),
                    new_localized_devices.end(),
                    std::inserter(temp_devices, temp_devices.begin()));
        }
        localized_devices = temp_devices;
    }

    return localized_devices;
}

int IsProblemSolved(LogData *data, double max_finish_time_ms,
                    const int min_path_per_link) {
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
    cout << "Minimum paths per link " << min_path_per_link << endl;
    cout << "Total flows " << total_flows << endl;
    cout << "Failed flows " << failed_flows << endl;

    double p_inverse = double(shortest_paths) / min_path_per_link;
    double mean = double(total_flows) / p_inverse;
    double std_dev =
        sqrt(double(total_flows * (p_inverse - 1)) / (p_inverse * p_inverse));
    cout << "Standard Deviation " << std_dev << endl;
    cout << "Old equation: " << float(failed_flows) / total_flows
         << " <= " << failure_threshold / shortest_paths << endl;
    cout << "New equation: " << float(failed_flows)
         << " <= " << mean - 3 * std_dev << endl;

    // if (float(failed_flows) / total_flows <= failure_threshold /
    // shortest_paths) {
    if (failed_flows <= mean - 3 * std_dev) {
        return 1;
    }
    return 0;
}

bool CheckNoBranch(LogData *data, vector<Path *> *flow_paths, int src,
                   int dst) {
    // cout << "CheckNoBranch " << src << " " << dst << " " << data << endl;
    MemoizedPaths *mpaths = data->GetMemoizedPaths(src, dst);
    unordered_set<int> devices;
    for (Path *path : mpaths->paths) {
        // cout << "path for " << src << " " << dst << " " << *path << endl;
        for (int link_id : *path) {
            Link link = data->inverse_links[link_id];
            devices.insert(link.first);
            devices.insert(link.second);
        }
    }
    // cout << "devices: " << devices << endl;
    bool branch = true;
    for (Path *path : *flow_paths) {
        for (int link_id : *path) {
            Link link = data->inverse_links[link_id];
            // cout << "Link in path " << link << endl;
            if (link.second != src and
                devices.find(link.second) != devices.end() and
                devices.find(link.first) == devices.end()) {
                // incoming branch
                // check if there's a path from src->dst that does not go
                // through link.second if yes, then it is a branch and we can't
                // eliminate this sub-graph
                bool path_exists = false;
                for (Path *path : mpaths->paths) {
                    bool intersect = true;
                    for (int mid : *path) {
                        Link mlink = data->inverse_links[mid];
                        intersect = intersect or (mlink.first == link.second) or
                                    (mlink.second == link.second);
                    }
                    path_exists = path_exists or (!intersect);
                }
                if (path_exists)
                    return false;
            }
            if (link.first != dst and
                devices.find(link.first) != devices.end() and
                devices.find(link.second) == devices.end()) {
                // outgoing branch
                assert(link.first != src);
                return false;
            }
        }
    }
    // cout << "******* passed " << endl;
    return true;
}

set<PII> ViableSrcDstForActiveProbe(LogData *data, int ntraces,
                                    double min_start_time_ms,
                                    double max_finish_time_ms) {
    set<PII> src_dst_pairs;
    for (int t = 0; t < ntraces; t++) {
        for (Flow *flow : data[t].flows) {
            vector<Path *> *flow_paths = flow->GetPaths(max_finish_time_ms);
            for (Path *path : *flow_paths) {
                Path dpath;
                data[t].GetDeviceLevelPath(flow, *path, dpath);
                int dst = dpath[dpath.size() - 1];
                // cout << "path " << dpath << endl;
                for (int i = 0; i < dpath.size() - 1; i++) {
                    if (data[t].IsNodeSwitch(dpath[i]) and
                        data[t].IsNodeSwitch(dst) and dpath[i] != dst and
                        CheckNoBranch(&data[t], flow_paths, dpath[i], dst)) {
                            if (!(ActiveProbeForbidden(dpath[i]) || ActiveProbeForbidden(dst))){
                                src_dst_pairs.insert(PII(dpath[i], dst));
                            }
                    }
                }
            }
            // assert (t == 0);
        }
        cout << "ViableSrcDstForActiveProbe: finished iteration " << t << endl;
    }
    return src_dst_pairs;
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
                     string inference_mode, string minimize_mode, string topo_name, set<int> prev_eq_devices, string micro_change) {
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
    if (inference_mode == "Flock") {
        eq_devices =
            LocalizeViaFlock(data, ntraces, fail_file, min_start_time_ms,
                             max_finish_time_ms, nopenmp_threads, topo_name);
    } else if (inference_mode == "Naive") {
        eq_devices =
            LocalizeViaNobody(data, ntraces, fail_file, min_start_time_ms,
                              max_finish_time_ms, nopenmp_threads, topo_name, prev_eq_devices, micro_change);
    } else {
        cout << "ERROR! ERROR! Somebody save me!" << endl;
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
        MicroChange *mc;
        tie(mc, curr_score) = GetMicroChange(
            data, dropped_flows, ntraces, eq_devices, eq_device_sets,
            used_links, min_start_time_ms, max_finish_time_ms, sequence_mode,
            minimize_mode, nopenmp_threads);

        if (curr_score - last_score < SCORE_THRESHOLD or curr_score < 1.0e-8)
            break;

        cout << "comes here" << endl;
        cout << "Best MicroChange: " << *mc << " score " << curr_score << endl;
        cout << "and also here" << endl;
        last_score = curr_score;

        max_iter--;
        if (max_iter == 0) {
            break;
        }
    }
}

pair<MicroChange *, double>
GetMicroChange(LogData *data, vector<Flow *> *dropped_flows, int ntraces,
                   set<int> &eq_devices, set<set<int>> &eq_device_sets,
                   set<Link> &used_links, double min_start_time_ms,
                   double max_finish_time_ms, string sequence_mode,
                   string minimize_mode, int nopenmp_threads) {
    pair<MicroChange *, double> result;
    pair<MicroChange *, double> result_ap, result_lr;
    set<set<int>> eq_device_sets_ap = eq_device_sets;
    set<set<int>> eq_device_sets_lr = eq_device_sets;
    int TOTAL_OPTIONS = 2;
    if (sequence_mode == "Intelligent"){
        result_ap = GetBestActiveProbeMc(
            data, dropped_flows, ntraces, eq_devices, eq_device_sets_ap,
            used_links, min_start_time_ms, max_finish_time_ms, minimize_mode, nopenmp_threads);
        
        result_lr = GetBestLinkToRemove(
            data, dropped_flows, ntraces, eq_devices, eq_device_sets_lr,
            used_links, min_start_time_ms, max_finish_time_ms, minimize_mode,
            nopenmp_threads);
        
        cout << "AP score: " << result_ap.second << ",LR score: " << result_lr.second;
        if (result_ap.second > result_lr.second){
            result = result_ap;
            eq_device_sets = eq_device_sets_ap;
        }
        else{
            result = result_lr;
            eq_device_sets = eq_device_sets_lr;
        }

    }
    else if (sequence_mode == "Random"){
        result_ap = GetRandomActiveProbeMc(
            data, dropped_flows, ntraces, eq_devices, eq_device_sets_ap,
            used_links, min_start_time_ms, max_finish_time_ms, minimize_mode, nopenmp_threads);
        
        result_lr = GetRandomLinkToRemove(
            data, dropped_flows, ntraces, eq_devices, eq_device_sets_lr,
            used_links, min_start_time_ms, max_finish_time_ms, minimize_mode,
            nopenmp_threads);
        
        cout << "AP score: " << result_ap.second << ",LR score: " << result_lr.second;
        if ((rand() % 2 && result_ap.second > 0) || result_lr.second == 0){
            cout << "AP was chosen" << endl;
            result = result_ap;
            eq_device_sets = eq_device_sets_ap;
        }
        else{
            cout << "LR was chosen" << endl;
            result = result_lr;
            eq_device_sets = eq_device_sets_lr;
        }
    }
    return result;
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

double get_normalized_score(MicroChange *m, double score, string minimize_mode){
    cout << "Minimize mode is " << minimize_mode << " score is " << score << endl;
    if (minimize_mode == "Cost"){
        score /= m->GetCost();
    }
    else if (minimize_mode == "Time"){
        score /= m->GetTimeToDiagnose();
    }
    cout << "Normalized score is " << score << endl;
    return score;
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

void GetEqDeviceSets(LogData *data, vector<Flow *> *dropped_flows, int ntraces,
                     set<int> &equivalent_devices, Link removed_link,
                     double max_finish_time_ms, set<set<int>> &result) {
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

// Count number of pairs that will be distinguished by the micro-change
// sequence. eq_device_sets should have the entire equivalent_devices set
int GetEqDeviceSetsMeasure(LogData *data, vector<Flow *> *dropped_flows,
                           int ntraces, set<int> &equivalent_devices,
                           Link removed_link, double max_finish_time_ms,
                           set<set<int>> &eq_device_sets) {
    GetEqDeviceSets(data, dropped_flows, ntraces, equivalent_devices,
                    removed_link, max_finish_time_ms, eq_device_sets);
    map<int, int> device_colors, col_cnts;
    GetDeviceColors(equivalent_devices, device_colors, eq_device_sets);
    GetColorCounts(device_colors, col_cnts);

    int pairs = 0;
    for (auto [c, cnt] : col_cnts) {
        pairs += cnt * (equivalent_devices.size() - cnt);
    }
    //! TODO: check if this assert holds, it should!
    assert(pairs % 2 == 0);
    pairs /= 2;
    return pairs;
}

int EvaluateActiveProbeMc(LogData *data, vector<Flow *> *dropped_flows,
                          int ntraces, set<int> &equivalent_devices,
                          PII src_dst, double min_start_time_ms,
                          double max_finish_time_ms,
                          set<set<int>> &eq_device_sets) {
    vector<Path *> *ap_paths;
    // paths in the original network
    data[0].GetAllPaths(&ap_paths, src_dst.first, src_dst.second);
    set<int> devices_in_path;
    for (Path *path : *ap_paths) {
        for (int link_id : *path) {
            Link link = data[0].inverse_links[link_id];
            devices_in_path.insert(link.first);
            devices_in_path.insert(link.second);
        }
    }
    set<int> devices_filtered;
    set_intersection(equivalent_devices.begin(), equivalent_devices.end(),
                     devices_in_path.begin(), devices_in_path.end(),
                     std::inserter(devices_filtered, devices_filtered.begin()));

    int pairs = devices_filtered.size() *
                (equivalent_devices.size() - devices_filtered.size());
    eq_device_sets.insert(devices_filtered);
    return pairs;
}

typedef tuple<int, int, int, int> TupIIII;
TupIIII SrcDstWithMaxDrops(LogData *data, vector<Flow *> *dropped_flows,
                           int ntraces, double min_start_time_ms,
                           double max_finish_time_ms, int nopenmp_threads) {
    map<TupIIII, int> tup_cnts;
    TupIIII ret_tup;
    int max_cnt = 0;
    for (int ii = 0; ii < ntraces; ii++) {
        for (Flow *flow : dropped_flows[ii]) {
            if (!flow->IsFlowActive()) {
                TupIIII tup(flow->src, flow->dest, flow->srcport,
                            flow->destport);
                if (tup_cnts.find(tup) == tup_cnts.end())
                    tup_cnts[tup] = 0;
                if (++tup_cnts[tup] > max_cnt) {
                    max_cnt = tup_cnts[tup];
                    ret_tup = tup;
                }
            }
        }
    }
    return ret_tup;
}

pair<ActiveProbeMc *, double>
GetBestActiveProbeMc(LogData *data, vector<Flow *> *dropped_flows, int ntraces,
                     set<int> &equivalent_devices,
                     set<set<int>> &eq_device_sets, set<Link> &used_links,
                     double min_start_time_ms, double max_finish_time_ms,
                     string minimize_mode, int nopenmp_threads) {

    set<PII> src_dst_pairs = ViableSrcDstForActiveProbe(
        data, ntraces, min_start_time_ms, max_finish_time_ms);
    int max_pairs = 0;
    PII best_src_dst = PII(-1, -1);
    cout << "Viable src dst pairs " << src_dst_pairs << endl;
    // mutex lock;
    // #pragma omp parallel for num_threads(nopenmp_threads)
    for (PII src_dst : src_dst_pairs) {
        //! TODO: make naming consistent
        //! TODO: implement EvaluateActiveProbeMc
        set<set<int>> eq_device_sets_copy = eq_device_sets;
        int pairs = EvaluateActiveProbeMc(
            data, dropped_flows, ntraces, equivalent_devices, src_dst,
            min_start_time_ms, max_finish_time_ms, eq_device_sets_copy);
        cout << "Active Probe Mc " << src_dst << " pairs " << pairs << endl;
        // lock.lock();
        if (pairs > max_pairs) {
            best_src_dst = src_dst;
            max_pairs = pairs;
        }
        // lock.unlock();
    }
    // do again for the best mc to populate eq_device_sets
    EvaluateActiveProbeMc(data, dropped_flows, ntraces, equivalent_devices,
                          best_src_dst, min_start_time_ms, max_finish_time_ms,
                          eq_device_sets);
    int nprobes = 10;
    auto [hsrc, hdst, srcport, dstport] =
        SrcDstWithMaxDrops(data, dropped_flows, ntraces, min_start_time_ms,
                           max_finish_time_ms, nopenmp_threads);
    // if dst is dst_rack, might as well make it the dst host
    if (!data[0].IsNodeSwitch(hdst) and
        data[0].hosts_to_racks[hdst] == best_src_dst.second) {
        best_src_dst.second = hdst;
    }
    cout << "best tuple " << best_src_dst << " " << hsrc << " " << hdst << " "
         << srcport << " " << dstport << endl;
    ActiveProbeMc *amc =
        new ActiveProbeMc(best_src_dst.first, best_src_dst.second, srcport,
                          dstport, nprobes, hsrc, hdst);
    
    return pair<ActiveProbeMc *, double>(amc, get_normalized_score(amc, (double)max_pairs, minimize_mode));
}

pair<ActiveProbeMc *, double>
GetRandomActiveProbeMc(LogData *data, vector<Flow *> *dropped_flows, int ntraces,
                     set<int> &equivalent_devices,
                     set<set<int>> &eq_device_sets, set<Link> &used_links,
                     double min_start_time_ms, double max_finish_time_ms,
                     string minimize_mode, int nopenmp_threads) {

    set<PII> src_dst_pairs = ViableSrcDstForActiveProbe(
        data, ntraces, min_start_time_ms, max_finish_time_ms);
    set<PII> src_dst_pairs_non_zero;
    int pairs = 0;
    PII best_src_dst = PII(-1, -1);

    for (PII src_dst : src_dst_pairs) {
        set<set<int>> eq_device_sets_copy = eq_device_sets;
        int pairs = EvaluateActiveProbeMc(
            data, dropped_flows, ntraces, equivalent_devices, src_dst,
            min_start_time_ms, max_finish_time_ms, eq_device_sets_copy);
        cout << "src dst pairs: (" << src_dst.first << ", " << src_dst.second << ") score: " << pairs << endl;
        if (pairs > 0) {
            src_dst_pairs_non_zero.insert(src_dst);
        }
    }

    cout << "Viable src dst pairs: " << src_dst_pairs.size() << " " << src_dst_pairs_non_zero.size() << " Non-zero scores: " << src_dst_pairs_non_zero.size() << endl;
    cout << "non zero pairs " << src_dst_pairs_non_zero << endl;

    if (src_dst_pairs_non_zero.size() > 0) {
        int random_idx = rand() % src_dst_pairs_non_zero.size();
        auto it = src_dst_pairs_non_zero.begin();
        cout << "random idx " << random_idx << endl;
        for (int i = 0; i < random_idx; i++){
            it++;
        }
        best_src_dst = *it;
        cout << "Best src dst loop 1 " << best_src_dst << endl;
        set<set<int>> eq_device_sets_copy = eq_device_sets;
        pairs = EvaluateActiveProbeMc(
            data, dropped_flows, ntraces, equivalent_devices, best_src_dst,
            min_start_time_ms, max_finish_time_ms, eq_device_sets_copy);
    }

    // do again for the best mc to populate eq_device_sets
    EvaluateActiveProbeMc(data, dropped_flows, ntraces, equivalent_devices,
                          best_src_dst, min_start_time_ms, max_finish_time_ms,
                          eq_device_sets);
    int nprobes = 10;
    auto [hsrc, hdst, srcport, dstport] =
        SrcDstWithMaxDrops(data, dropped_flows, ntraces, min_start_time_ms,
                           max_finish_time_ms, nopenmp_threads);
    // if dst is dst_rack, might as well make it the dst host
    if (!data[0].IsNodeSwitch(hdst) and
        data[0].hosts_to_racks[hdst] == best_src_dst.second) {
        best_src_dst.second = hdst;
    }
    cout << "GetRandomActiveProbeMc: best tuple " << best_src_dst << " " << hsrc << " " << hdst << " "
         << srcport << " " << dstport << endl;
    ActiveProbeMc *amc =
        new ActiveProbeMc(best_src_dst.first, best_src_dst.second, srcport,
                          dstport, nprobes, hsrc, hdst);
    return pair<ActiveProbeMc *, double>(amc, get_normalized_score(amc, (double)pairs, minimize_mode));
}

pair<RemoveLinkMc *, double>
GetBestLinkToRemove(LogData *data, vector<Flow *> *dropped_flows, int ntraces,
                    set<int> &equivalent_devices, set<set<int>> &eq_device_sets,
                    set<Link> &used_links, double min_start_time_ms,
                    double max_finish_time_ms, string minimize_mode, int nopenmp_threads) {
    int max_pairs = 0;
    // mutex lock;
    Link best_link_to_remove = Link(-1, -1);
    // #pragma omp parallel for num_threads(nopenmp_threads)
    for (Link link : used_links) {
        if (LinkRemovalForbidden(link.first) || LinkRemovalForbidden(link.second)){
            continue;
        }
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
            int pairs = GetEqDeviceSetsMeasure(
                data, dropped_flows, ntraces, equivalent_devices, link,
                max_finish_time_ms, eq_device_sets_copy);
            cout << "Removing link " << link << " pairs " << pairs << endl;
            // lock.lock();
            if (pairs > max_pairs) {
                best_link_to_remove = link;
                max_pairs = pairs;
            }
            // lock.unlock();
        }
    }
    // do again for the best link to populate eq_device_sets
    GetEqDeviceSetsMeasure(data, dropped_flows, ntraces, equivalent_devices,
                           best_link_to_remove, max_finish_time_ms,
                           eq_device_sets);
    RemoveLinkMc *mc = new RemoveLinkMc(best_link_to_remove);
    return pair<RemoveLinkMc *, double>(mc, get_normalized_score(mc, (double)max_pairs, minimize_mode));
}

pair<RemoveLinkMc *, double>
GetRandomLinkToRemove(LogData *data, vector<Flow *> *dropped_flows, int ntraces,
                      set<int> &equivalent_devices,
                      set<set<int>> &eq_device_sets, set<Link> &used_links,
                      double min_start_time_ms, double max_finish_time_ms,
                      string minimize_mode, int nopenmp_threads) {
    
    vector<pair<Link, int>> used_links_with_pairs;
    Link random_link_to_remove = Link(-1, -1);
    double pairs = 0;
    
    for (Link link : used_links) {
        if (LinkRemovalForbidden(link.first) || LinkRemovalForbidden(link.second)){
            continue;
        }
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
            int pairs = GetEqDeviceSetsMeasure(
                data, dropped_flows, ntraces, equivalent_devices, link,
                max_finish_time_ms, eq_device_sets_copy);
            cout << "Removing link " << link << " pairs " << pairs << endl;
            if (pairs > 0) {
                used_links_with_pairs.push_back(pair<Link, int>(link, pairs));
            }
        }
    }
    if (used_links_with_pairs.size() > 0) {
        tie(random_link_to_remove, pairs) =
        used_links_with_pairs[rand() % used_links_with_pairs.size()];
    }

    // Do again for the random link to populate eq_device_sets
    GetEqDeviceSetsMeasure(data, dropped_flows, ntraces, equivalent_devices,
                           random_link_to_remove, max_finish_time_ms,
                           eq_device_sets);
    
    RemoveLinkMc *mc = new RemoveLinkMc(random_link_to_remove);
    return pair<RemoveLinkMc *, double>(mc, get_normalized_score(mc, (double)pairs, minimize_mode));

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


set<int> ReadEqDevices(string eq_devices_file){
    ifstream eq_file(eq_devices_file);
    string line, lastline;
    set<int> devices;

    if (!eq_file.is_open()){
        // File is possible empty - likely that we don't have info on eq devices yet.
        devices.insert(-1);
        return devices;
    }

    while(getline(eq_file, line)) {
        lastline = line;
    }
    eq_file.close();

    if (lastline.empty()){
        // File is possible empty - likely that we don't have info on eq devices yet.
        devices.insert(-1);
        return devices;
    }
    else{
        // 
        stringstream ss(lastline);
        string temp;
        int num;

        getline(ss, temp, '[');

        while(ss >> num) {
            devices.insert(num);
            if (ss.peek() == ','){
                ss.ignore();
            }
        }
        return devices;
    }
}