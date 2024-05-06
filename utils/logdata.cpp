#include "logdata.h"
#include <algorithm>
#include <assert.h>
#include <atomic>
#include <chrono>
#include <fstream>
#include <mutex>
#include <omp.h>
#include <shared_mutex>
#include <sparsehash/dense_hash_map>
#include <sstream>
#include <string>
using google::dense_hash_map;

MemoizedPaths *LogData::GetMemoizedPaths(int src_rack, int dest_rack) {
    PII st(src_rack, dest_rack);
    MemoizedPaths *ret;
    if constexpr (PARALLEL_IO)
        memoized_paths_lock.lock_shared();
    auto it = memoized_paths.find(st);
    if constexpr (PARALLEL_IO)
        memoized_paths_lock.unlock_shared();
    if (it == memoized_paths.end()) {
        if constexpr (PARALLEL_IO) {
            memoized_paths_lock.lock();
            // need to check a second time for correctness
            it = memoized_paths.find(st);
            if (it == memoized_paths.end()) {
                ret = new MemoizedPaths();
                memoized_paths.insert(make_pair(st, ret));
            } else {
                ret = it->second;
            }
            memoized_paths_lock.unlock();
        } else {
            ret = new MemoizedPaths();
            memoized_paths.insert(make_pair(st, ret));
        }
    } else {
        ret = it->second;
    }
    return ret;
}

LogData::LogData(LogData &data) : LogData() {
    failed_links = data.failed_links;
    flows = data.flows;
    hosts_to_racks = data.hosts_to_racks;
    links_to_ids = data.links_to_ids;
    inverse_links = data.inverse_links;
    memoized_paths = data.memoized_paths;
}

void LogData::GetReducedData(unordered_map<Link, Link> &reduced_graph_map,
                             LogData &reduced_data, int nopenmp_threads) {
    for (auto &it : failed_links) {
        Link l = it.first;
        Link rl = (reduced_graph_map.find(l) == reduced_graph_map.end()
                       ? l
                       : reduced_graph_map[l]);
        if (reduced_data.failed_links.find(rl) ==
            reduced_data.failed_links.end()) {
            //! HACK: set dummy failparam
            reduced_data.failed_links.insert(make_pair(rl, 0.0));
        }
    }
    if (VERBOSE) {
        for (auto &it : reduced_data.failed_links) {
            cout << "Failed reduced link " << it.first << endl;
        }
    }

    for (auto &it : links_to_ids) {
        Link l = it.first;
        Link rl = (reduced_graph_map.find(l) == reduced_graph_map.end()
                       ? l
                       : reduced_graph_map[l]);
        if (reduced_data.links_to_ids.find(rl) ==
            reduced_data.links_to_ids.end()) {
            reduced_data.links_to_ids[rl] = reduced_data.inverse_links.size();
            reduced_data.inverse_links.push_back(rl);
        }
    }
    if (VERBOSE) {
        cout << "Finished assigning ids to reduced links, nlinks(reduced) "
             << reduced_data.inverse_links.size() << endl;
    }

    reduced_data.flows.resize(flows.size());
    atomic<int> flow_ctr = 0;
#pragma omp parallel for num_threads(nopenmp_threads)
    for (int ff = 0; ff < flows.size(); ff++) {
        Flow *rf = new Flow(*flows[ff], reduced_graph_map, *this, reduced_data);
        reduced_data.flows[flow_ctr++] = rf;
    }
}

void LogData::FilterFlowsBeforeTime(double finish_time_ms,
                                    int nopenmp_threads) {
    auto start_filter_time = chrono::high_resolution_clock::now();
    vector<Flow *> filtered_flows[nopenmp_threads];
#pragma omp parallel for num_threads(nopenmp_threads)
    for (int ff = 0; ff < flows.size(); ff++) {
        int thread_num = omp_get_thread_num();
        Flow *f = flows[ff];
        if (f->AnySnapshotBefore(finish_time_ms)) {
            filtered_flows[thread_num].push_back(f);
        } else {
            //! TODO: improve memory management for flows
            // delete(f);
        }
    }
    flows.clear();
    for (int t = 0; t < nopenmp_threads; t++) {
        flows.insert(flows.end(), filtered_flows[t].begin(),
                     filtered_flows[t].end());
    }
    if (VERBOSE) {
        cout << "Filtered flows for analysis before " << finish_time_ms
             << " (ms) simtime in " << GetTimeSinceSeconds(start_filter_time)
             << " seconds" << endl;
    }
}

void LogData::FilterFlowsForConditional(double max_finish_time_ms,
                                        int nopenmp_threads) {
    auto start_filter_time = chrono::high_resolution_clock::now();
    vector<Flow *> filtered_flows[nopenmp_threads];
#pragma omp parallel for num_threads(nopenmp_threads)
    for (int ff = 0; ff < flows.size(); ff++) {
        int thread_num = omp_get_thread_num();
        Flow *f = flows[ff];
        if (f->TracerouteFlow(max_finish_time_ms) and !f->DiscardFlow()) {
            filtered_flows[thread_num].push_back(f);
            f->ResetSnapshotCounter();
        } else {
            //! TODO: improve memory management for flows
            // delete(f);
        }
    }
    flows.clear();
    for (int t = 0; t < nopenmp_threads; t++) {
        flows.insert(flows.end(), filtered_flows[t].begin(),
                     filtered_flows[t].end());
    }
    if (VERBOSE) {
        cout << "Filtered flows for conditional analysis in "
             << GetTimeSinceSeconds(start_filter_time) << " seconds" << endl;
    }
}

vector<vector<int>> *LogData::GetForwardFlowsByLinkId(double max_finish_time_ms,
                                                      int nopenmp_threads) {
    int nlinks = inverse_links.size();
    vector<int> sizes[nopenmp_threads];
    for (int thread_num = 0; thread_num < nopenmp_threads; thread_num++) {
        sizes[thread_num] = vector<int>(nlinks, 0);
    }
    auto start_time = chrono::high_resolution_clock::now();
    int chunk_size =
        (flows.size() + nopenmp_threads) / nopenmp_threads; // ceiling
#pragma omp parallel num_threads(nopenmp_threads)
    {
        int thread_num = omp_get_thread_num();
        assert(thread_num < nopenmp_threads);
        int start = min((int)flows.size(), thread_num * chunk_size);
        int end = min((int)flows.size(), (thread_num + 1) * chunk_size);
        assert(start <= end);
        for (int ff = start; ff < end; ff++) {
            Flow *flow = flows[ff];
            if (flow->AnySnapshotBefore(max_finish_time_ms)) {
                auto flow_paths = flow->GetPaths(max_finish_time_ms);
                sizes[thread_num][flow->first_link_id]++;
                sizes[thread_num][flow->last_link_id]++;
                for (Path *path : *flow_paths) {
                    for (int link_id : *path) {
                        sizes[thread_num][link_id]++;
                    }
                }
            }
        }
    }
    vector<int> final_sizes;
    final_sizes.resize(nlinks);
#pragma omp parallel for num_threads(nopenmp_threads)
    for (int link_id = 0; link_id < nlinks; link_id++) {
        // use sizes as offsets
        assert(omp_get_thread_num() < nopenmp_threads);
        int curr_bin_size = sizes[0][link_id], last_bin_size;
        sizes[0][link_id] = 0;
        for (int thread_num = 1; thread_num < nopenmp_threads; thread_num++) {
            last_bin_size = curr_bin_size;
            curr_bin_size = sizes[thread_num][link_id];
            sizes[thread_num][link_id] =
                sizes[thread_num - 1][link_id] + last_bin_size;
        }
        final_sizes[link_id] =
            sizes[nopenmp_threads - 1][link_id] + curr_bin_size;
    }
    if (VERBOSE) {
        cout << "Binning flows part 1 done in "
             << GetTimeSinceSeconds(start_time) << " seconds" << endl;
    }
    start_time = chrono::high_resolution_clock::now();
    forward_flows_by_link_id = new vector<vector<int>>(nlinks);
    int nthreads = min(12, nopenmp_threads);
#pragma omp parallel for num_threads(nthreads)
    for (int link_id = 0; link_id < nlinks; link_id++) {
        assert(omp_get_thread_num() < nthreads);
        //(*forward_flows_by_link_id)[link_id].resize(final_sizes[link_id]);
        (*forward_flows_by_link_id)[link_id] =
            vector<int>(final_sizes[link_id]);
    }
    if (VERBOSE) {
        cout << "Binning flows part 2 done in "
             << GetTimeSinceSeconds(start_time) << " seconds" << endl;
    }
    start_time = chrono::high_resolution_clock::now();
#pragma omp parallel num_threads(nopenmp_threads)
    {
        int thread_num = omp_get_thread_num();
        assert(thread_num < nopenmp_threads);
        int start = min((int)flows.size(), thread_num * chunk_size);
        int end = min((int)flows.size(), (thread_num + 1) * chunk_size);
        auto &offsets = sizes[thread_num];
        assert(start <= end);
        for (int ff = start; ff < end; ff++) {
            Flow *flow = flows[ff];
            if (flow->AnySnapshotBefore(max_finish_time_ms)) {
                auto flow_paths = flow->GetPaths(max_finish_time_ms);
                (*forward_flows_by_link_id)[flow->first_link_id]
                                           [offsets[flow->first_link_id]++] =
                                               ff;
                (*forward_flows_by_link_id)[flow->last_link_id]
                                           [offsets[flow->last_link_id]++] = ff;
                for (Path *path : *flow_paths) {
                    for (int link_id : *path) {
                        (*forward_flows_by_link_id)[link_id]
                                                   [offsets[link_id]++] = ff;
                    }
                }
            }
        }
    }
    if (VERBOSE) {
        cout << "Binning flows part 3 done in "
             << GetTimeSinceSeconds(start_time) << " seconds" << endl;
    }
    start_time = chrono::high_resolution_clock::now();
    return forward_flows_by_link_id;
}

vector<vector<int>> *
LogData::GetForwardFlowsByLinkId2(double max_finish_time_ms,
                                  int nopenmp_threads) {
    int nlinks = inverse_links.size();
    forward_flows_by_link_id = new vector<vector<int>>(nlinks);
    mutex link_locks[nlinks];
#pragma omp parallel for num_threads(nopenmp_threads) schedule(auto)
    for (int ff = 0; ff < flows.size(); ff++) {
        Flow *flow = flows[ff];
        if (flow->AnySnapshotBefore(max_finish_time_ms)) {
            // src --> src_tor
            link_locks[flow->first_link_id].lock();
            (*forward_flows_by_link_id)[flow->first_link_id].push_back(ff);
            link_locks[flow->first_link_id].unlock();

            // dest_tor --> dest
            link_locks[flow->last_link_id].lock();
            (*forward_flows_by_link_id)[flow->last_link_id].push_back(ff);
            link_locks[flow->last_link_id].unlock();

            auto flow_paths = flow->GetPaths(max_finish_time_ms);
            for (Path *path : *flow_paths) {
                for (int link_id : *path) {
                    link_locks[link_id].lock();
                    (*forward_flows_by_link_id)[link_id].push_back(ff);
                    link_locks[link_id].unlock();
                }
            }
        }
    }
    return forward_flows_by_link_id;
}

void LogData::GetSizesForForwardFlowsByLinkId(double max_finish_time_ms,
                                              int nopenmp_threads,
                                              vector<int> &result) {
    int nlinks = inverse_links.size();
    vector<int> sizes[nopenmp_threads];
    for (int thread_num = 0; thread_num < nopenmp_threads; thread_num++) {
        sizes[thread_num] = vector<int>(nlinks, 0);
    }
#pragma omp parallel for num_threads(nopenmp_threads)
    for (int ff = 0; ff < flows.size(); ff++) {
        Flow *flow = flows[ff];
        if (flow->AnySnapshotBefore(max_finish_time_ms)) {
            auto flow_paths = flow->GetPaths(max_finish_time_ms);
            int thread_num = omp_get_thread_num();
            sizes[thread_num][flow->first_link_id]++;
            sizes[thread_num][flow->last_link_id]++;
            for (Path *path : *flow_paths) {
                for (int link_id : *path) {
                    sizes[thread_num][link_id]++;
                }
            }
        }
    }
    result.reserve(nlinks);
    for (int link_id = 0; link_id < nlinks; link_id++) {
        result.push_back(0);
        for (int thread_num = 0; thread_num < nopenmp_threads; thread_num++) {
            result[link_id] += sizes[thread_num][link_id];
        }
    }
}

// Lockless version
vector<vector<int>> *
LogData::GetForwardFlowsByLinkId1(double max_finish_time_ms,
                                  int nopenmp_threads) {
    int nlinks = inverse_links.size();
    forward_flows_by_link_id = new vector<vector<int>>(nlinks);
    auto start_time = chrono::high_resolution_clock::now();
    vector<int> sizes;
    GetSizesForForwardFlowsByLinkId(max_finish_time_ms, nopenmp_threads, sizes);
    if (VERBOSE) {
        cout << "Binning flows part 1 done in "
             << GetTimeSinceSeconds(start_time) << " seconds" << endl;
    }
    start_time = chrono::high_resolution_clock::now();
    int nthreads = min(3, nopenmp_threads);
#pragma omp parallel for num_threads(nthreads)
    for (int link_id = 0; link_id < nlinks; link_id++) {
        (*forward_flows_by_link_id)[link_id].reserve(sizes[link_id]);
    }
    if (VERBOSE) {
        cout << "Binning flows part 2 done in "
             << GetTimeSinceSeconds(start_time) << " seconds" << endl;
    }
    start_time = chrono::high_resolution_clock::now();
    // mutex link_locks[nlinks];
    atomic_flag link_locks[nlinks](ATOMIC_FLAG_INIT);
#pragma omp parallel for num_threads(nopenmp_threads) schedule(auto)
    for (int ff = 0; ff < flows.size(); ff++) {
        Flow *flow = flows[ff];
        if (flow->AnySnapshotBefore(max_finish_time_ms)) {
            auto flow_paths = flow->GetPaths(max_finish_time_ms);

            // link_locks[flow->first_link_id].lock();
            while (link_locks[flow->first_link_id].test_and_set(
                std::memory_order_acquire))
                ;
            (*forward_flows_by_link_id)[flow->first_link_id].push_back(ff);
            link_locks[flow->first_link_id].clear(std::memory_order_release);
            // link_locks[flow->first_link_id].unlock();

            // link_locks[flow->last_link_id].lock();
            while (link_locks[flow->last_link_id].test_and_set(
                std::memory_order_acquire))
                ;
            (*forward_flows_by_link_id)[flow->last_link_id].push_back(ff);
            link_locks[flow->last_link_id].clear(std::memory_order_release);
            // link_locks[flow->last_link_id].unlock();

            for (Path *path : *flow_paths) {
                for (int link_id : *path) {
                    // link_locks[link_id].lock();
                    while (link_locks[link_id].test_and_set(
                        std::memory_order_acquire))
                        ;
                    (*forward_flows_by_link_id)[link_id].push_back(ff);
                    link_locks[link_id].clear(std::memory_order_release);
                    // link_locks[link_id].unlock();
                }
            }
        }
    }
    if (VERBOSE) {
        cout << "Binning flows part 3 done in "
             << GetTimeSinceSeconds(start_time) << " seconds" << endl;
    }
    start_time = chrono::high_resolution_clock::now();
    return forward_flows_by_link_id;
}

vector<vector<int>> *
LogData::GetReverseFlowsByLinkId(double max_finish_time_ms) {
    if (reverse_flows_by_link_id != NULL)
        delete (reverse_flows_by_link_id);
    reverse_flows_by_link_id = new vector<vector<int>>(inverse_links.size());
    for (int ff = 0; ff < flows.size(); ff++) {
        Flow *flow = flows[ff];
        if (flow->AnySnapshotBefore(max_finish_time_ms)) {
            auto flow_reverse_paths = flow->GetReversePaths(max_finish_time_ms);
            (*reverse_flows_by_link_id)[flow->reverse_first_link_id].push_back(
                ff);
            (*reverse_flows_by_link_id)[flow->reverse_last_link_id].push_back(
                ff);
            for (Path *path : *flow_reverse_paths) {
                for (int link_id : *path) {
                    (*reverse_flows_by_link_id)[link_id].push_back(ff);
                }
            }
        }
    }
    return reverse_flows_by_link_id;
}

// TODO DEVICE OPTIMIZE
vector<vector<int>> *LogData::GetFlowsByDevice(double max_finish_time_ms,
                                               int nopenmp_threads) {
    int ndevices = GetMaxDevicePlus1();
    vector<int> sizes[nopenmp_threads];
    for (int thread_num = 0; thread_num < nopenmp_threads; thread_num++) {
        sizes[thread_num] = vector<int>(ndevices, 0);
    }
    auto start_time = chrono::high_resolution_clock::now();
    int chunk_size =
        (flows.size() + nopenmp_threads) / nopenmp_threads; // ceiling
#pragma omp parallel num_threads(nopenmp_threads)
    {
        int thread_num = omp_get_thread_num();
        assert(thread_num < nopenmp_threads);
        int start = min((int)flows.size(), thread_num * chunk_size);
        int end = min((int)flows.size(), (thread_num + 1) * chunk_size);
        assert(start <= end);
        Path device_path;
        for (int ff = start; ff < end; ff++) {
            Flow *flow = flows[ff];
            if (flow->AnySnapshotBefore(max_finish_time_ms)) {
                auto flow_paths = flow->GetPaths(max_finish_time_ms);
                for (Path *link_path : *flow_paths) {
                    GetDeviceLevelPath(flow, *link_path, device_path);
                    for (int device : device_path) {
                        if (device < 0 or device >= ndevices) {
                            cout << "Device " << device << " ndevices "
                                 << ndevices << " link_path " << *link_path
                                 << " device_path " << device_path
                                 << " link_path_size "
                                 << int((*link_path).size())
                                 << " device_path_size "
                                 << int(device_path.size()) << endl;
                            assert(false);
                        }
                        sizes[thread_num][device]++;
                    }
                }
            }
        }
    }
    vector<int> final_sizes;
    final_sizes.resize(ndevices);
#pragma omp parallel for num_threads(nopenmp_threads)
    for (int device = 0; device < ndevices; device++) {
        // use sizes as offsets
        assert(omp_get_thread_num() < nopenmp_threads);
        int curr_bin_size = sizes[0][device], last_bin_size;
        sizes[0][device] = 0;
        for (int thread_num = 1; thread_num < nopenmp_threads; thread_num++) {
            last_bin_size = curr_bin_size;
            curr_bin_size = sizes[thread_num][device];
            sizes[thread_num][device] =
                sizes[thread_num - 1][device] + last_bin_size;
        }
        final_sizes[device] =
            sizes[nopenmp_threads - 1][device] + curr_bin_size;
    }
    if (VERBOSE) {
        cout << "Binning flows part 1 done in "
             << GetTimeSinceSeconds(start_time) << " seconds" << endl;
    }
    start_time = chrono::high_resolution_clock::now();
    flows_by_device = new vector<vector<int>>(ndevices);
    int nthreads = min(12, nopenmp_threads);
#pragma omp parallel for num_threads(nthreads)
    for (int device = 0; device < ndevices; device++) {
        assert(omp_get_thread_num() < nthreads);
        (*flows_by_device)[device] = vector<int>(final_sizes[device]);
    }
    if (VERBOSE) {
        cout << "Binning flows part 2 done in "
             << GetTimeSinceSeconds(start_time) << " seconds" << endl;
    }
    start_time = chrono::high_resolution_clock::now();
#pragma omp parallel num_threads(nopenmp_threads)
    {
        int thread_num = omp_get_thread_num();
        assert(thread_num < nopenmp_threads);
        int start = min((int)flows.size(), thread_num * chunk_size);
        int end = min((int)flows.size(), (thread_num + 1) * chunk_size);
        auto &offsets = sizes[thread_num];
        assert(start <= end);
        Path device_path;
        for (int ff = start; ff < end; ff++) {
            Flow *flow = flows[ff];
            if (flow->AnySnapshotBefore(max_finish_time_ms)) {
                auto flow_paths = flow->GetPaths(max_finish_time_ms);
                for (Path *link_path : *flow_paths) {
                    GetDeviceLevelPath(flow, *link_path, device_path);
                    for (int device : device_path) {
                        (*flows_by_device)[device][offsets[device]++] = ff;
                    }
                }
            }
        }
    }
    if (VERBOSE) {
        cout << "Binning flows part 3 done in "
             << GetTimeSinceSeconds(start_time) << " seconds" << endl;
    }
    start_time = chrono::high_resolution_clock::now();
    return flows_by_device;
}

vector<vector<int>> *LogData::GetFlowsByLinkId(double max_finish_time_ms,
                                               int nopenmp_threads) {
    GetForwardFlowsByLinkId(max_finish_time_ms, nopenmp_threads);
    if constexpr (!CONSIDER_REVERSE_PATH)
        flows_by_link_id = forward_flows_by_link_id;
    else {
        assert(false);
        GetReverseFlowsByLinkId(max_finish_time_ms);
        flows_by_link_id = new vector<vector<int>>(inverse_links.size());
        for (int link_id = 0; link_id < inverse_links.size(); link_id++) {
            set_union(forward_flows_by_link_id->at(link_id).begin(),
                      forward_flows_by_link_id->at(link_id).end(),
                      reverse_flows_by_link_id->at(link_id).begin(),
                      reverse_flows_by_link_id->at(link_id).end(),
                      back_inserter(flows_by_link_id->at(link_id)));
            //! TODO: Check if flows_by_link actually gets populated
        }
        delete (forward_flows_by_link_id);
        delete (reverse_flows_by_link_id);
    }
    return flows_by_link_id;
}

void LogData::GetFailedLinkIds(Hypothesis &failed_links_set) {
    for (auto &it : failed_links) {
        assert(links_to_ids.find(it.first) != links_to_ids.end());
        failed_links_set.insert(links_to_ids[it.first]);
    }
}

void LogData::GetFailedDevices(Hypothesis &failed_devices_set) {
    for (auto &it : failed_devices) {
        failed_devices_set.insert(it.first);
    }
}

set<Link> LogData::IdsToLinks(Hypothesis &h) {
    set<Link> ret;
    for (int link_id : h) {
        ret.insert(inverse_links[link_id]);
    }
    return ret;
}

void LogData::AddChunkFlows(vector<Flow *> &chunk_flows) {
#pragma omp critical(AddChunkFlows)
    { flows.insert(flows.end(), chunk_flows.begin(), chunk_flows.end()); }
}

void LogData::AddFailedLink(Link link, double failparam) {
#pragma omp critical(AddFailedLink)
    { failed_links[link] = failparam; }
}

int LogData::GetLinkId(Link link) {
    int link_id;
#pragma omp critical(AddNewLink)
    {
        auto it = links_to_ids.find(link);
        if (it == links_to_ids.end()) {
            link_id = inverse_links.size();
            links_to_ids[link] = link_id;
            inverse_links.push_back(link);
        } else
            link_id = it->second;
    }
    return link_id;
}

int LogData::GetLinkIdUnsafe(Link link) {
    auto it = links_to_ids.find(link);
    if (it == links_to_ids.end()) cout << "Link " << link
        << " not found in topology" << endl;
    assert(it != links_to_ids.end());
    return it->second;
}

void LogData::ResetForAnalysis() {
    flows.clear();
    /*!TODO
    if(forward_flows_by_link_id!=NULL) delete forward_flows_by_link_id;
    if(reverse_flows_by_link_id!=NULL){
        delete reverse_flows_by_link_id;
        delete flows_by_link_id;
    }
    */
    forward_flows_by_link_id = reverse_flows_by_link_id = flows_by_link_id =
        NULL;
}

Path *LogData::GetPointerToPathTaken(vector<int> &path_nodes,
                                     vector<int> &temp_path, Flow *flow) {
    // For 007 verification, make this if condition always true
    if (flow->IsFlowActive()) {
        return new Path(temp_path);
    } else {
        assert(path_nodes.size() >
               0); // No direct link for src_host to dest_host or vice_versa
        int src_sw = inverse_links[temp_path[0]].first;
        int dst_sw = inverse_links[temp_path.back()].second;
        assert(path_nodes[0] == src_sw and path_nodes.back() == dst_sw);
        MemoizedPaths *memoized_paths =
            GetMemoizedPaths(path_nodes[0], *path_nodes.rbegin());
        return memoized_paths->GetPath(temp_path);
    }
}

Path *LogData::GetPointerToPathTaken(int src_sw, int dst_sw,
                                     vector<int> &temp_path, Flow *flow) {
    // For 007 verification, make this if condition always true
    if (flow->IsFlowActive()) {
        return new Path(temp_path);
    } else {
        MemoizedPaths *memoized_paths = GetMemoizedPaths(src_sw, dst_sw);
        return memoized_paths->GetPath(temp_path);
    }
}

void LogData::GetAllPaths(vector<Path *> **result, int src_rack,
                          int dest_rack) {
    MemoizedPaths *memoized_paths = GetMemoizedPaths(src_rack, dest_rack);
    memoized_paths->GetAllPaths(result);
}

void LogData::GetRacksList(vector<int> &result) {
    set<int> racks;
    for (auto &[k, v] : hosts_to_racks) {
        racks.insert(v);
    }
    result.insert(result.begin(), racks.begin(), racks.end());
}

void LogData::OutputToTrace(ostream &out) {
    for (auto &it : failed_links) {
        out << "Failing_link " << it.first.first << " " << it.first.second
            << " " << it.second << endl;
    }
    vector<Path *> *paths;
    for (auto &[src_dest, m_paths] : memoized_paths) {
        assert(m_paths != NULL);
        m_paths->GetAllPaths(&paths);
        for (Path *path : *paths) {
            out << "FP " << src_dest.first;
            for (int link_id : *path) {
                out << " " << inverse_links[link_id].second;
            }
            out << endl;
        }
    }
    for (Flow *flow : flows) {
        Link first_link = inverse_links[flow->first_link_id];
        Link last_link = inverse_links[flow->last_link_id];
        assert(first_link.first == flow->src);
        assert(last_link.second == flow->dest);
        out << "FID " << flow->src << " " << flow->dest << " "
            << first_link.second << " " << last_link.first << " "
            << flow->nbytes << " " << flow->start_time_ms << endl;
        for (FlowSnapshot *ss : flow->snapshots) {
            out << "SS " << ss->snapshot_time_ms << " " << ss->packets_sent
                << " " << ss->packets_lost << " " << ss->packets_randomly_lost
                << endl;
        }
        if (flow->path_taken_vector.size() > 0 and
            flow->path_taken_vector[0] != NULL) {
            Path *path_taken = flow->path_taken_vector[0];
            out << "FPT";
            if (path_taken->size() > 0) {
                Link first_link = inverse_links[(*path_taken)[0]];
                out << " " << first_link.first;
            }
            for (int link_id : *path_taken) {
                out << " " << inverse_links[link_id].second;
            }
            out << endl;
        }
        if (flow->reverse_path_taken_vector.size() > 0 and
            flow->reverse_path_taken_vector[0] != NULL) {
            Path *reverse_path_taken = flow->path_taken_vector[0];
            out << "FPRT";
            if (reverse_path_taken->size() > 0) {
                Link first_link = inverse_links[(*reverse_path_taken)[0]];
                out << " " << first_link.first;
            }
            for (int link_id : *reverse_path_taken) {
                out << " " << inverse_links[link_id].second;
            }
            out << endl;
        }
    }
}

int LogData::GetMaxDevicePlus1() {
    if (max_device == -1) {
        for (Link l : inverse_links) {
            if (l.first < OFFSET_HOST)
                max_device = max(max_device, l.first);
            if (l.second < OFFSET_HOST)
                max_device = max(max_device, l.second);
        }
    }
    return max_device + 1;
}

void LogData::GetLinkIdPath(vector<int> &path_nodes, int &first_link_id,
                            int &last_link_id, vector<int> &link_id_path) {
    // cout << path_nodes << endl;
    assert(path_nodes.size() > 2);
    first_link_id = GetLinkIdUnsafe(Link(path_nodes[0], path_nodes[1]));
    link_id_path.clear();
    for (int ind = 2; ind < path_nodes.size() - 1; ind++) {
        link_id_path.push_back(
            GetLinkIdUnsafe(Link(path_nodes[ind - 1], path_nodes[ind])));
    }
    last_link_id =
        GetLinkIdUnsafe(Link(path_nodes.rbegin()[1], path_nodes.rbegin()[0]));
}

void LogData::GetDeviceLevelPath(Flow *flow, Path &path, Path &result) {
    result.clear();
    Link first_link = inverse_links[flow->first_link_id];
    if (IsNodeSwitch(first_link.first))
        result.push_back(first_link.first);
    if (path.size() > 0) {
        Link link = inverse_links[path[0]];
        result.push_back(link.first);
        for (int link_id : path) {
            Link link = inverse_links[link_id];
            result.push_back(link.second);
        }
    } else
        result.push_back(first_link.second);
    Link last_link = inverse_links[flow->last_link_id];
    if (IsNodeSwitch(last_link.second))
        result.push_back(last_link.second);
}

void LogData::CleanupFlows() {
    for (Flow *f : flow_pointers_to_delete)
        delete[] f;
    delete (forward_flows_by_link_id);
    delete (reverse_flows_by_link_id);
    forward_flows_by_link_id = NULL;
    reverse_flows_by_link_id = NULL;
}

LogData::~LogData() {
    for (Flow *f : flows) {
        for (auto s : f->snapshots)
            delete (s);
    }
    CleanupFlows();
}

int LogData::NumLinksOfDevice(int device) {
    int num_links = 0;
    for (Link link : inverse_links) {
        num_links += (int)(link.first == device or link.second == device);
    }
    return num_links;
}

int LogData::GetReverseLinkId(int link_id){
    Link link = inverse_links[link_id];
    Link rlink = Link(link.second, link.first);
    int rlink_id = links_to_ids[rlink];
    return rlink_id;
}

int GetReducedLinkId(int link_id, unordered_map<Link, Link> &reduced_graph_map,
                     LogData &data, LogData &reduced_data) {
    Link l = data.inverse_links[link_id];
    Link rl = (reduced_graph_map.find(l) == reduced_graph_map.end()
                   ? l
                   : reduced_graph_map[l]);
    int link_id_r = reduced_data.links_to_ids[rl];
    return link_id_r;
}

void GetNumReducedLinksMap(unordered_map<Link, Link> &reduced_graph_map,
                           LogData &data, LogData &reduced_data,
                           unordered_map<int, int> &result_map) {
    for (int link_id = 0; link_id < data.inverse_links.size(); link_id++) {
        result_map[GetReducedLinkId(link_id, reduced_graph_map, data,
                                    reduced_data)]++;
    }
}

Path *GetReducedPath(Path *path, unordered_map<Link, Link> &reduced_graph_map,
                     LogData &data, LogData &reduced_data) {
    Path *reduced_path = new Path(path->size());
    // convert link_ids in path to reduced link_ids
    for (int link_id : *path) {
        reduced_path->push_back(
            GetReducedLinkId(link_id, reduced_graph_map, data, reduced_data));
    }
    return reduced_path;
}
