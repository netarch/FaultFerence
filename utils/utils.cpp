#include "utils.h"
#include "logdata.h"
#include <algorithm>
#include <assert.h>
#include <atomic>
#include <chrono>
#include <cstring>
#include <fstream>
#include <mutex>
#include <omp.h>
#include <queue>
#include <sparsehash/dense_hash_map>
#include <string>
using google::dense_hash_map;

const bool LEAFSPINE_NET_BOUNCER = false; //! HACK

bool VERBOSE = false;
bool CONSIDER_DEVICE_LINK = true;
bool TRACEROUTE_BAD_FLOWS = true;
bool PATH_KNOWN = true;
bool ACTIVE_PROBES_PATH_KNOWN = true;

pthread_mutex_t mutex_getline = PTHREAD_MUTEX_INITIALIZER;
InputFlowType INPUT_FLOW_TYPE = ALL_FLOWS;

bool MISCONFIGURED_ACL = false;

//! HACK HACK HACK FIX FIX FIX
bool FLOW_DELAY = false;
const int FLOW_DELAY_THRESHOLD_US = 10000;

inline bool StringEqualTo(const char *a, const char *b) {
    while ((*b == *a) and (*a != '\0')) {
        a++;
        b++;
    }
    return (*b == '\0' and *a == '\0');
}

void GetDataFromLogFileDistributed(string dirname, int nchunks, LogData *result,
                                   int nopenmp_threads) {
    auto start_time = chrono::high_resolution_clock::now();
#pragma omp parallel for num_threads(nopenmp_threads)
    for (int i = 0; i < nchunks; i++) {
        GetDataFromLogFile(dirname + "/" + to_string(i), result);
    }
    if (VERBOSE) {
        cout << "Read log file chunks in " << GetTimeSinceSeconds(start_time)
             << " seconds" << endl;
    }
}

void ComputeAllPairShortestPaths(unordered_set<int> &nodes,
                                 unordered_set<Link> &links, LogData *result) {
    assert(!CONSIDER_DEVICE_LINK);
    int MAX_NODE_ID = *max_element(nodes.begin(), nodes.end());
    vector<vector<int>> shortest_path_len(MAX_NODE_ID + 1);
    for (int i = 0; i < MAX_NODE_ID + 1; i++) {
        shortest_path_len[i].resize(MAX_NODE_ID + 1, 100000000);
        shortest_path_len[i][i] = 0;
    }
    for (auto [i, j] : links) {
        shortest_path_len[i][j] = 1;
    }
    // floyd warshall
    for (int k : nodes) {
        for (int i : nodes) {
            for (int j : nodes) {
                if (shortest_path_len[i][j] >
                    shortest_path_len[i][k] + shortest_path_len[k][j])
                    shortest_path_len[i][j] =
                        shortest_path_len[i][k] + shortest_path_len[k][j];
            }
        }
    }
    for (int src_sw : nodes) {
        for (int dest_sw : nodes) {
            MemoizedPaths *memoized_paths =
                result->GetMemoizedPaths(src_sw, dest_sw);
            if (src_sw != dest_sw) {
                vector<int> path_till_now;
                path_till_now.push_back(src_sw);
                queue<vector<int>> shortest_paths_till_now;
                shortest_paths_till_now.push(path_till_now);
                while (!shortest_paths_till_now.empty()) {
                    vector<int> path_till_now = shortest_paths_till_now.front();
                    shortest_paths_till_now.pop();
                    int last_vertex = path_till_now.back();
                    for (int next_hop : nodes) {
                        if (links.find(Link(last_vertex, next_hop)) !=
                            links.end()) {
                            if (next_hop == dest_sw) {
                                // found a shortest path!
                                path_till_now.push_back(next_hop);
                                Path *path_link_ids =
                                    new Path(path_till_now.size() - 1);
                                for (int nn = 1; nn < path_till_now.size();
                                     nn++) {
                                    path_link_ids->push_back(
                                        result->GetLinkIdUnsafe(
                                            Link(path_till_now[nn - 1],
                                                 path_till_now[nn])));
                                }
                                if (VERBOSE)
                                    cout << "Found a shortest path "
                                         << path_till_now << " link_id_paths "
                                         << *path_link_ids << endl;
                                memoized_paths->AddPath(path_link_ids);
                            } else if (shortest_path_len[last_vertex]
                                                        [dest_sw] ==
                                       1 + shortest_path_len[next_hop]
                                                            [dest_sw]) {
                                vector<int> shortest_path_till_now(
                                    path_till_now);
                                shortest_path_till_now.push_back(next_hop);
                                shortest_paths_till_now.push(
                                    shortest_path_till_now);
                            }
                        }
                    }
                }
            } else {
                memoized_paths->AddPath(new Path(0));
            }
        }
    }
}

// Compute and store (Link <-> Link-id) mappings
void GetLinkMappings(string topology_file, LogData *result,
                     bool compute_paths) {
    assert((compute_paths and CONSIDER_DEVICE_LINK) == false);
    ifstream tfile(topology_file);
    string line;
    if (VERBOSE) {
        cout << "Asuuming trace file has hosts numbered as host_id + "
             << OFFSET_HOST << " (OFFSET)" << endl;
    }
    unordered_set<int> nodes;
    unordered_set<Link> links;
    while (getline(tfile, line)) {
        char *linec = const_cast<char *>(line.c_str());
        int index = line.find("->");
        if (index == string::npos) {
            int sw1, sw2;
            GetFirstInt(linec, sw1);
            GetFirstInt(linec, sw2);
            result->GetLinkId(Link(sw1, sw2));
            result->GetLinkId(Link(sw2, sw1));
            // if (CONSIDER_DEVICE_LINK){
            result->GetLinkId(Link(sw1, sw1));
            result->GetLinkId(Link(sw2, sw2));
            //}
            if (compute_paths) {
                nodes.insert(sw1);
                nodes.insert(sw2);
                links.insert(Link(sw1, sw2));
                links.insert(Link(sw2, sw1));
            }
        } else {
            line.replace(index, 2, " ");
            int svr, sw;
            GetFirstInt(linec, svr);
            // svr += OFFSET_HOST;
            GetFirstInt(linec, sw);
            result->GetLinkId(Link(sw, svr));
            result->GetLinkId(Link(svr, sw));
            result->hosts_to_racks[svr] = sw;
            result->GetLinkId(Link(sw, sw));
            // cout << svr << "-->" << sw << endl;
        }
    }
    if (compute_paths) {
        ComputeAllPairShortestPaths(nodes, links, result);
    }
}

void GetDataFromLogFile(string trace_file, LogData *result) {
    auto start_time = chrono::high_resolution_clock::now();
    vector<Flow *> chunk_flows;
    dense_hash_map<Link, int, hash<Link>> links_to_ids_cache;
    links_to_ids_cache.set_empty_key(Link(-1, -1));
    auto GetLinkId = [&links_to_ids_cache, result](Link link) {
        int link_id;
        auto it = links_to_ids_cache.find(link);
        if (it == links_to_ids_cache.end()) {
            link_id = result->GetLinkId(link);
            links_to_ids_cache[link] = link_id;
        } else {
            link_id = it->second;
        }
        return link_id;
    };
    vector<int> temp_path(10);
    vector<int> path_nodes(10);
    ifstream infile(trace_file);
    string line, op;
    Flow *flow = NULL;
    int nlines = 0;
    while (getline(infile, line)) {
        char *linec = const_cast<char *>(line.c_str());
        GetString(linec, op);
        // cout << op <<endl;
        // istringstream line_stream (line);
        // sscanf(linum, "%s *", op);
        // line_stream >> op;
        // cout << "op " << op << " : " << line << endl;
        nlines += 1;
        if (StringStartsWith(op, "FPRT")) {
            assert(flow != NULL);
            temp_path.clear();
            path_nodes.clear();
            int node;
            // This is only the portion from dest_rack to src_rack
            while (GetFirstInt(linec, node)) {
                if (path_nodes.size() > 0) {
                    temp_path.push_back(
                        GetLinkId(Link(path_nodes.back(), node)));
                }
                path_nodes.push_back(node);
            }
            flow->SetReversePathTaken(
                result->GetPointerToPathTaken(path_nodes, temp_path, flow));
        } else if (StringStartsWith(op, "FPT")) {
            assert(flow != NULL);
            temp_path.clear();
            path_nodes.clear();
            int node;
            // This is only the portion from src_rack to dest_rack
            while (GetFirstInt(linec, node)) {
                if (path_nodes.size() > 0) {
                    temp_path.push_back(
                        GetLinkId(Link(path_nodes.back(), node)));
                }
                path_nodes.push_back(node);
            }
            flow->SetPathTaken(
                result->GetPointerToPathTaken(path_nodes, temp_path, flow));
        } else if (StringStartsWith(op, "FP")) {
            assert(flow == NULL);
            temp_path.clear();
            path_nodes.clear();
            int node;
            // This is only the portion from src_rack to dest_rack
            while (GetFirstInt(linec, node)) {
                if (path_nodes.size() > 0) {
                    temp_path.push_back(
                        GetLinkId(Link(path_nodes.back(), node)));
                }
                path_nodes.push_back(node);
            }
            assert(path_nodes.size() >
                   0); // No direct link for src_host to dest_host or vice_versa
            MemoizedPaths *memoized_paths =
                result->GetMemoizedPaths(path_nodes[0], *path_nodes.rbegin());
            memoized_paths->AddPath(temp_path);
            // memoized_paths->GetPath(temp_path);
            // cout << temp_path << endl;
        } else if (op == "SS") {
            double snapshot_time_ms;
            int packets_sent, packets_lost, packets_randomly_lost;
            GetFirstDouble(linec, snapshot_time_ms);
            GetFirstInt(linec, packets_sent);
            GetFirstInt(linec, packets_lost);
            GetFirstInt(linec, packets_randomly_lost);
            assert(flow != NULL);
            //! HACK- change! change! change!
            // flow->AddSnapshot(snapshot_time_ms, 1, (packets_lost>0),
            // (packets_randomly_lost>0));
            if (FLOW_DELAY) {
                //! HACK: interpret packets randomly lost as delay
                int max_delay_us = packets_randomly_lost;
                flow->AddSnapshot(snapshot_time_ms, 1,
                                  (max_delay_us > FLOW_DELAY_THRESHOLD_US),
                                  max_delay_us);
            } else
                flow->AddSnapshot(snapshot_time_ms, packets_sent, packets_lost,
                                  packets_randomly_lost);
        } else if (op == "FID") {
            // Log the previous flow
            if (flow != NULL)
                flow->DoneAddingPaths();
            if (flow != NULL and flow->paths != NULL and
                flow->paths->size() > 0 and
                flow->path_taken_vector.size() == 1) {
                assert(flow->GetPathTaken());
                if constexpr (CONSIDER_REVERSE_PATH) {
                    assert(flow->GetReversePathTaken());
                }
                if (flow->GetLatestPacketsSent() > 0 and
                    !flow->DiscardFlow() and flow->paths->size() > 0) {
                    chunk_flows.push_back(flow);
                }
            }
            int src, dest, srcrack, destrack, nbytes, srcport, dstport;
            double start_time_ms;
            GetFirstInt(linec, src);
            GetFirstInt(linec, dest);
            GetFirstInt(linec, srcrack);
            GetFirstInt(linec, destrack);
            GetFirstInt(linec, srcport);
            GetFirstInt(linec, dstport);
            GetFirstInt(linec, nbytes);
            GetFirstDouble(linec, start_time_ms);
            flow = new Flow(src, srcport, dest, dstport, nbytes, start_time_ms);
            // Set flow paths
            MemoizedPaths *memoized_paths =
                result->GetMemoizedPaths(srcrack, destrack);
            memoized_paths->GetAllPaths(&flow->paths);
            flow->SetFirstLinkId(GetLinkId(Link(flow->src, srcrack)));
            flow->SetLastLinkId(GetLinkId(Link(destrack, flow->dest)));
        } else if (op == "Failing_link") {
            int src, dest;
            double failparam;
            GetFirstInt(linec, src);
            GetFirstInt(linec, dest);
            GetFirstDouble(linec, failparam);
            // sscanf (linum + op.size(),"%d %*d %f", &src, &dest, &failparam);
            result->AddFailedLink(Link(src, dest), failparam);
            if (VERBOSE) {
                cout << "Failed link " << src << " " << dest << " " << failparam
                     << endl;
            }
        } else if (op == "link_statistics") {
            assert(false);
        }
    }
    // Log the last flow
    if (flow != NULL)
        flow->DoneAddingPaths();
    if (flow != NULL and flow->paths != NULL and flow->paths->size() > 0 and
        flow->path_taken_vector.size() == 1) {
        assert(flow->GetPathTaken());
        if constexpr (CONSIDER_REVERSE_PATH) {
            assert(flow->GetReversePathTaken());
        }
        if (flow->GetLatestPacketsSent() > 0 and !flow->DiscardFlow() and
            flow->paths != NULL and flow->paths->size() > 0) {
            // flow->PrintInfo();
            chunk_flows.push_back(flow);
        }
    }
    result->AddChunkFlows(chunk_flows);
    cout << "Num flows " << chunk_flows.size() << endl;
    if (VERBOSE) {
        cout << "Read log file in " << GetTimeSinceSeconds(start_time)
             << " seconds, numlines " << nlines << endl;
    }
}

void ReadPath(char *path_c, vector<int> &path_nodes, vector<int> &temp_path,
              LogData *result) {
    temp_path.clear();
    path_nodes.clear();
    int node;
    // This is only the portion from src_rack to dst_rack
    while (GetFirstInt(path_c, node)) {
        if (path_nodes.size() > 0) {
            temp_path.push_back(
                result->GetLinkIdUnsafe(Link(path_nodes.back(), node)));
        }
        // TODO CONSIDER_DEVICE_LINK Read path
        path_nodes.push_back(node);
        if (CONSIDER_DEVICE_LINK) {
            path_nodes.push_back(node); // push twice
            temp_path.push_back(result->GetLinkIdUnsafe(Link(node, node)));
        }
    }
}

void GetCompletePaths(Flow *flow, FlowLines &flow_lines, LogData *data,
                      vector<int> &temp_path, vector<int> &path_nodes,
                      vector<int> &path_nodes_reverse, int srcrack,
                      int destrack) {
    /*
    if (LEAFSPINE_NET_BOUNCER and (srcrack == src or destrack == dest)){
        //!TODO: implement device link
        assert (flow->IsFlowActive() and !CONSIDER_DEVICE_LINK);
        if (src == srcrack){
            assert (destrack != dest);
            flow->SetFirstLinkId(result->GetLinkIdUnsafe(Link(srcrack,
                                 destrack)));
            flow->SetLastLinkId(result->GetLinkIdUnsafe(Link(destrack,
                                dest)));
        }
        else{
            assert (srcrack != dest);
            flow->SetFirstLinkId(result->GetLinkIdUnsafe(Link(flow->src,
                                 srcrack)));
            flow->SetLastLinkId(result->GetLinkIdUnsafe(Link(srcrack,
                                flow->dest)));
        }
        temp_path[thread_num].clear();
        path_nodes[thread_num].clear();
        flow->AddPath(result->GetPointerToPathTaken(
                      path_nodes[thread_num], temp_path[thread_num], flow), true);
        flow->AddReversePath(result->GetPointerToPathTaken(
                      path_nodes[thread_num], temp_path[thread_num], flow), true);
        //flow->PrintInfo();
    }
    else
    */
    {
        char *restore_c;
        /* Reverse flow path taken */
        if (flow_lines.fprt_c != NULL) {
            restore_c = flow_lines.fprt_c;
            ReadPath(flow_lines.fprt_c, path_nodes_reverse, temp_path, data);
            path_nodes_reverse.insert(path_nodes_reverse.begin(), flow->dest);
            path_nodes_reverse.push_back(flow->src);
            flow_lines.fprt_c = restore_c;
            if (CONSIDER_DEVICE_LINK) {
                if (data->IsNodeSwitch(flow->src))
                    path_nodes_reverse.push_back(flow->src);
                if (data->IsNodeSwitch(flow->dest))
                    path_nodes_reverse.insert(path_nodes_reverse.begin(),
                                              flow->dest);
            }
        }

        /* Flow path taken */
        if (flow_lines.fpt_c != NULL) {
            restore_c = flow_lines.fpt_c;
            ReadPath(flow_lines.fpt_c, path_nodes, temp_path, data);
            if (path_nodes.size() == 0)
                path_nodes.push_back(srcrack);
            path_nodes.insert(path_nodes.begin(), flow->src);
            path_nodes.push_back(flow->dest);
            // cout << "path_nodes " << path_nodes << " path-link " << temp_path
            // << endl;
            flow_lines.fpt_c = restore_c;
            if (CONSIDER_DEVICE_LINK) {
                if (data->IsNodeSwitch(flow->src))
                    path_nodes.insert(path_nodes.begin(), flow->src);
                if (data->IsNodeSwitch(flow->dest))
                    path_nodes.push_back(flow->dest);
            }
        }
    }
}

void ProcessFlowLines(vector<FlowLines> &all_flow_lines, LogData *result,
                      int nopenmp_threads) {
    auto start_time = chrono::high_resolution_clock::now();
    // vector<Flow*> flows_threads[nopenmp_threads];
    Flow *flows_threads = new Flow[all_flow_lines.size()];
    result->flow_pointers_to_delete.push_back(flows_threads);
    vector<int> temp_path[nopenmp_threads];
    vector<int> path_nodes[nopenmp_threads];
    vector<int> path_nodes_reverse[nopenmp_threads];
    for (int t = 0; t < nopenmp_threads; t++) {
        temp_path[t].reserve(MAX_PATH_LENGTH + 2);
        path_nodes[t].reserve(MAX_PATH_LENGTH + 2);
        path_nodes_reverse[t].reserve(MAX_PATH_LENGTH + 2);
    }
    int previous_nflows = result->flows.size();
#pragma omp parallel for num_threads(nopenmp_threads)
    for (int ii = 0; ii < all_flow_lines.size(); ii++) {
        int thread_num = omp_get_thread_num();
        FlowLines &flow_lines = all_flow_lines[ii];

        // cout << flow_lines.fid_c << flow_lines.fpt_c << flow_lines.ss_c[0] <<
        // endl;
        /* FID line */
        int src, dest, srcrack, destrack, nbytes, srcport, dstport;
        double start_time_ms;
        char *restore_c = flow_lines.fid_c;
        GetFirstInt(flow_lines.fid_c, src);
        GetFirstInt(flow_lines.fid_c, dest);
        GetFirstInt(flow_lines.fid_c, srcrack);
        GetFirstInt(flow_lines.fid_c, destrack);
        GetFirstInt(flow_lines.fid_c, srcport);
        GetFirstInt(flow_lines.fid_c, dstport);
        GetFirstInt(flow_lines.fid_c, nbytes);
        GetFirstDouble(flow_lines.fid_c, start_time_ms);
        assert (srcport != 0 and dstport != 0);
        flow_lines.fid_c = restore_c;
        Flow *flow = &(flows_threads[ii]);
        *flow = Flow(src, srcport, dest, dstport, nbytes, start_time_ms);

        // Set flow paths: If flow active and ACTIVE_PROBES_PATH_KNOWN is set
        // then there is only one path
        result->GetAllPaths(&flow->paths, srcrack, destrack);
        assert (flow->paths->size() >= 1);

        // Set paths taken by flow
        GetCompletePaths(flow, flow_lines, result, temp_path[thread_num],
                         path_nodes[thread_num], path_nodes_reverse[thread_num],
                         srcrack, destrack);

        // Set forward path
        if (path_nodes[thread_num].size() > 0) {
            // cout << "FPT " << path_nodes[thread_num] << " " <<
            // flow->first_link_id << " " << flow->last_link_id << " " << " " <<
            // srcrack << " " << destrack << endl;
            result->GetLinkIdPath(path_nodes[thread_num], flow->first_link_id,
                                  flow->last_link_id, temp_path[thread_num]);
            flow->SetPathTaken(result->GetPointerToPathTaken(
                srcrack, destrack, temp_path[thread_num], flow));
        }
        // Set reverse path
        if (path_nodes_reverse[thread_num].size() > 0) {
            // cout << "FPRT " << path_nodes_reverse[thread_num] << " " <<
            // flow->first_link_id << " " << flow->last_link_id << " " << endl;
            result->GetLinkIdPath(
                path_nodes_reverse[thread_num], flow->reverse_first_link_id,
                flow->reverse_last_link_id, temp_path[thread_num]);
            flow->SetReversePathTaken(result->GetPointerToPathTaken(
                destrack, srcrack, temp_path[thread_num], flow));
        }

        /* Snapshots */
        for (int ss = 0; ss < flow_lines.ss_c.size(); ss++) {
            char *ss_c = flow_lines.ss_c[ss];
            double snapshot_time_ms;
            int packets_sent, packets_lost, packets_randomly_lost;
            GetFirstDouble(ss_c, snapshot_time_ms);
            GetFirstInt(ss_c, packets_sent);
            GetFirstInt(ss_c, packets_lost);
            GetFirstInt(ss_c, packets_randomly_lost);
            assert(flow != NULL);
            //! HACK- change! change! change!
            // flow->AddSnapshot(snapshot_time_ms, 1, (packets_lost>0),
            // (packets_randomly_lost>0));
            if (FLOW_DELAY) {
                //! HACK: interpret packets randomly lost as delay
                int max_delay_us = packets_randomly_lost;
                flow->AddSnapshot(snapshot_time_ms, 1,
                                  (max_delay_us > FLOW_DELAY_THRESHOLD_US),
                                  max_delay_us);
            } else
                flow->AddSnapshot(snapshot_time_ms, packets_sent, packets_lost,
                                  packets_randomly_lost);
        }
        flow->DoneAddingPaths();
    }
    int nactive_flows = 0;
    for (int ii = 0; ii < all_flow_lines.size(); ii++) {
        Flow *flow = &(flows_threads[ii]);
        nactive_flows += (int)(flow->IsFlowActive());
        // For 007 verification, make the if condition always true
        if ((flow->IsFlowActive() or
             (flow->paths != NULL and flow->paths->size() > 0)) and
            flow->path_taken_vector.size() == 1) {
            assert(flow->GetPathTaken());
            if constexpr (CONSIDER_REVERSE_PATH) {
                assert(flow->GetReversePathTaken());
            }
            if (flow->GetLatestPacketsSent() > 0 and !flow->DiscardFlow()) {
                // flow->PrintInfo();
                result->flows.push_back(flow);
            }
        }
    }
    if (VERBOSE) {
        cout << "Active flows " << nactive_flows << endl;
        // cout<< "Processed flow lines in "<<GetTimeSinceSeconds(start_time)
        //    << " seconds, numflows " << all_flow_lines.size() << endl;
    }
}

void ProcessFlowPathLines(vector<char *> &lines, LogData *result,
                          int nopenmp_threads) {
    auto start_time = chrono::high_resolution_clock::now();
    vector<int> path_nodes_t[nopenmp_threads];
    vector<int> temp_path_t[nopenmp_threads];
    for (int t = 0; t < nopenmp_threads; t++) {
        path_nodes_t[t].reserve(MAX_PATH_LENGTH + 1);
    }
    Path *path_arr = new Path[lines.size()];
    vector<PII> src_dest_rack(lines.size());
#pragma omp parallel for num_threads(nopenmp_threads)
    for (int ii = 0; ii < lines.size(); ii++) {
        int thread_num = omp_get_thread_num();
        char *linec = lines[ii];
        ReadPath(linec, path_nodes_t[thread_num], temp_path_t[thread_num],
                 result);
        assert (temp_path_t[thread_num].size() >= 0);
        path_arr[ii] = Path(temp_path_t[thread_num]);
        assert (path_arr[ii].size() >= 0);
        // No direct link for src_host to dest_host or vice_versa
        assert (path_nodes_t[thread_num].size() > 0);
        src_dest_rack[ii] =
            PII(path_nodes_t[thread_num][0], path_nodes_t[thread_num].back());
    }
    if (VERBOSE) {
        cout << "Parsed flow path lines in " << GetTimeSinceSeconds(start_time)
             << " seconds, numlines " << lines.size() << endl;
    }
    //! TODO: Save repeated memory allocation for memoized paths
    for (int ii = 0; ii < lines.size(); ii++) {
        MemoizedPaths *memoized_paths = result->GetMemoizedPaths(
            src_dest_rack[ii].first, src_dest_rack[ii].second);
        memoized_paths->AddPath(&path_arr[ii]);
    }
    path_arr = new Path[result->GetMaxDevicePlus1()];
    Path *empty_path = new Path();
    for (int device = 0; device < result->GetMaxDevicePlus1(); device++) {
        MemoizedPaths *memoized_paths =
            result->GetMemoizedPaths(device, device);
        // memoized_paths->AddPath(empty_path);
        if (CONSIDER_DEVICE_LINK) {
            temp_path_t[0].clear();
            temp_path_t[0].push_back(
                result->GetLinkIdUnsafe(Link(device, device)));
            path_arr[device] = Path(temp_path_t[0]);
            memoized_paths->AddPath(&path_arr[device]);
        }
    }
}

inline char *strdup(char *str) {
    int str_size = strlen(str);
    char *result = new char[str_size + 1];
    memcpy(result, str, str_size + 1);
    return result;
}

void GetDataFromLogFileParallel(string trace_file, string topology_file,
                                LogData *result, int nopenmp_threads) {
    auto start_time = chrono::high_resolution_clock::now();
    GetLinkMappings(topology_file, result);

    pthread_mutex_lock(&mutex_getline);
    const char *trace_file_c = trace_file.c_str();
    FILE *infile = fopen(trace_file.c_str(), "r");
    pthread_mutex_unlock(&mutex_getline);
    size_t linec_size = 500;
    char *linec = new char[linec_size];
    char *restore_c = linec;
    size_t max_line_size = linec_size;
    char *op = new char[30];
    int nlines = 0;


    // pthread_mutex_lock(&mutex_getline);
    auto getline_result = getline(&linec, &max_line_size, infile);
    // pthread_mutex_unlock(&mutex_getline);
    GetString(linec, op);
    while (getline_result > 0 and StringEqualTo(op, "Failing_link")) {
        nlines += 1;
        int src, dest;
        GetFirstInt(linec, src);
        GetFirstInt(linec, dest);
        double failparam;
        GetFirstDouble(linec, failparam);
        result->AddFailedLink(Link(src, dest), failparam);
        if (VERBOSE) {
            cout << "Failed link " << src << " " << dest << " " << failparam
                 << endl;
        }
        linec = restore_c;
        max_line_size = linec_size;
        // pthread_mutex_lock(&mutex_getline);
        getline_result = getline(&linec, &max_line_size, infile);
        // pthread_mutex_unlock(&mutex_getline);
        GetString(linec, op);
    }

    const int FLOWPATH_BUFFER_SIZE = 5000001;
    vector<char *> buffered_lines;
    buffered_lines.reserve(FLOWPATH_BUFFER_SIZE);
    const int FLOW_LINE_BUFFER_SIZE = 10100000;
    FlowLines *curr_flow_lines;
    vector<FlowLines> buffered_flows;
    buffered_flows.reserve(FLOW_LINE_BUFFER_SIZE);
    while (getline_result > 0 and StringEqualTo(op, "FP")) {
        buffered_lines.push_back(strdup(linec));
        nlines += 1;
        linec = restore_c;
        max_line_size = linec_size;
        getline_result = getline(&linec, &max_line_size, infile);
        GetString(linec, op);
    }
    if (VERBOSE) {
        cout << "Calling ProcessFlowPathLines with " << buffered_lines.size()
             << " lines after " << GetTimeSinceSeconds(start_time) << " seconds"
             << endl;
    }
    if (buffered_lines.size() > 0) {
        ProcessFlowPathLines(buffered_lines, result, nopenmp_threads);
        //! TODO check where delete[] needs to be called instead of delete/free
        for (char *c : buffered_lines)
            delete[] c;
        if (VERBOSE) {
            cout << "Processed flow paths after "
                 << GetTimeSinceSeconds(start_time) << " seconds, numlines "
                 << buffered_lines.size() << endl;
        }
    }

    while (getline_result > 0) {
        nlines += 1;
        char *dup_linec = strdup(linec);
        // cout << "op " << op << " : " << linec;
        if (StringEqualTo(op, "SS")) {
            assert(curr_flow_lines->fid_c != NULL);
            curr_flow_lines->ss_c.push_back(dup_linec);
        } else if (StringStartsWith(op, "FID")) {
            if (buffered_flows.size() > FLOW_LINE_BUFFER_SIZE) {
                ProcessFlowLines(buffered_flows, result, nopenmp_threads);
                for_each(buffered_flows.begin(), buffered_flows.end(),
                         [](FlowLines &fl) { fl.FreeMemory(); });
                buffered_flows.clear();
            }
            buffered_flows.push_back(FlowLines());
            curr_flow_lines = &(buffered_flows.back());
            curr_flow_lines->fid_c = dup_linec;
        } else if (StringEqualTo(op, "FPT")) {
            assert(curr_flow_lines->fpt_c == NULL);
            curr_flow_lines->fpt_c = dup_linec;
        } else if (StringEqualTo(op, "FPRT")) {
            assert(curr_flow_lines->fprt_c == NULL);
            curr_flow_lines->fprt_c = dup_linec;
        }
        linec = restore_c;
        max_line_size = linec_size;
        getline_result = getline(&linec, &max_line_size, infile);
        GetString(linec, op);
    }

    if (VERBOSE) {
        cout << "Calling ProcessFlowLines after "
             << GetTimeSinceSeconds(start_time) << " seconds, numflows "
             << buffered_flows.size() << endl;
    }
    ProcessFlowLines(buffered_flows, result, nopenmp_threads);
    for_each(buffered_flows.begin(), buffered_flows.end(),
             [](FlowLines &fl) { fl.FreeMemory(); });
    buffered_flows.clear();
    if (VERBOSE) {
        cout << "Read log file in " << GetTimeSinceSeconds(start_time)
             << " seconds, numlines " << nlines << ", numflows "
             << result->flows.size() << " numlinks "
             << result->links_to_ids.size() << endl;
    }
    fclose(infile);
}

Hypothesis UnidirectionalHypothesis(Hypothesis &h, LogData *data) {
    set<Link> hlinks = data->IdsToLinks(h);
    set<Link> unidirectional_links;
    for (Link l : hlinks) {
        int n1 = min(l.first, l.second);
        int n2 = max(l.first, l.second);
        Link ul(n1, n2);
        unidirectional_links.insert(ul);
    }
    Hypothesis ret;
    for (Link l : unidirectional_links)
        ret.insert(data->GetLinkId(l));
    return ret;
}

PDD GetPrecisionRecallUnidirectional(Hypothesis &failed_links,
                                     Hypothesis &predicted_hypothesis,
                                     LogData *data) {
    Hypothesis failed_links_u = UnidirectionalHypothesis(failed_links, data);
    Hypothesis predicted_hypothesis_u =
        UnidirectionalHypothesis(predicted_hypothesis, data);
    return GetPrecisionRecall(failed_links_u, predicted_hypothesis_u, data);
}

PDD GetPrecisionRecall(Hypothesis &failed_links,
                       Hypothesis &predicted_hypothesis, LogData *data) {
    unordered_set<int> failed_devices, failed_predicted_devices;
    for (int link_id : failed_links) {
        if (data->IsLinkDevice(link_id))
            failed_devices.insert(data->inverse_links[link_id].first);
    }
    for (int link_id : predicted_hypothesis) {
        if (data->IsLinkDevice(link_id))
            failed_predicted_devices.insert(data->inverse_links[link_id].first);
    }

    double precision = 1.0;
    if (predicted_hypothesis.size() > 0) {
        int correctly_predicted = 0;
        for (int link_id : predicted_hypothesis) {
            Link link = data->inverse_links[link_id];
            if ((failed_links.find(link_id) != failed_links.end()) or
                (failed_devices.find(link.first) != failed_devices.end()) or
                (failed_devices.find(link.second) != failed_devices.end())) {
                correctly_predicted++;
            }
        }
        precision = ((double)correctly_predicted) / predicted_hypothesis.size();
    }

    double recall = 1.0;
    if (failed_links.size() > 0) {
        double correctly_recalled = 0.0;
        for (int link_id : predicted_hypothesis) {
            Link link = data->inverse_links[link_id];
            if (failed_links.find(link_id) != failed_links.end()) {
                correctly_recalled++;
            } else if (failed_devices.find(link.first) !=
                           failed_devices.end() and
                       failed_predicted_devices.find(link.first) ==
                           failed_predicted_devices.end()) {
                double multiplier = 1.0;
                if (MISCONFIGURED_ACL)
                    multiplier = 2.0;
                correctly_recalled +=
                    multiplier / data->NumLinksOfDevice(link.first);
            } else if (failed_devices.find(link.second) !=
                           failed_devices.end() and
                       failed_predicted_devices.find(link.second) ==
                           failed_predicted_devices.end()) {
                double multiplier = 1.0;
                if (MISCONFIGURED_ACL)
                    multiplier = 2.0;
                correctly_recalled +=
                    multiplier / data->NumLinksOfDevice(link.second);
            }
        }
        recall = ((double)correctly_recalled) / failed_links.size();
    }
    assert(recall <= 1.0);
    return PDD(precision, recall);
}
