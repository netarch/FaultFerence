#include "flow.h"
#include "utils.h"
#include <assert.h>

Path *GetReducedPath(Path *path, unordered_map<Link, Link> &reduced_graph_map,
                     LogData &data, LogData &reduced_data);

int GetReducedLinkId(int link_id, unordered_map<Link, Link> &reduced_graph_map,
                     LogData &data, LogData &reduced_data);

Flow::Flow(int src_, int srcport_, int dest_, int destport_, int nbytes_,
           double start_time_ms_)
    : src(src_), srcport(srcport_), dest(dest_), destport(destport_),
      nbytes(nbytes_), start_time_ms(start_time_ms_), curr_snapshot_ptr(-1),
      paths(NULL), reverse_paths(NULL), npaths_unreduced(1),
      npaths_reverse_unreduced(1) {}

Flow::Flow(Flow &flow, unordered_map<Link, Link> &reduced_graph_map,
           LogData &data, LogData &reduced_data)
    : src(flow.src), srcport(flow.srcport), dest(flow.dest),
      destport(flow.destport), nbytes(flow.nbytes),
      start_time_ms(flow.start_time_ms), curr_snapshot_ptr(-1),
      snapshots(flow.snapshots), npaths_unreduced(1),
      npaths_reverse_unreduced(1) {

    first_link_id = GetReducedLinkId(flow.first_link_id, reduced_graph_map,
                                     data, reduced_data);
    last_link_id = GetReducedLinkId(flow.last_link_id, reduced_graph_map, data,
                                    reduced_data);
    if constexpr (CONSIDER_REVERSE_PATH) {
        reverse_first_link_id = GetReducedLinkId(
            flow.reverse_first_link_id, reduced_graph_map, data, reduced_data);
        reverse_last_link_id = GetReducedLinkId(
            flow.reverse_last_link_id, reduced_graph_map, data, reduced_data);
    }

    if (flow.paths != NULL) {
        paths = new vector<Path *>();
        // populate forward paths
        for (Path *path : *flow.paths) {
            Path *reduced_path =
                GetReducedPath(path, reduced_graph_map, data, reduced_data);
            bool new_path = true;
            for (Path *path : *paths) {
                if (*path == *reduced_path) {
                    new_path = false;
                    break;
                }
            }
            if (new_path)
                paths->push_back(reduced_path);
            else
                delete (reduced_path);
            npaths_unreduced = flow.paths->size();
        }
    }

    if (flow.reverse_paths != NULL) {
        reverse_paths = new vector<Path *>();
        // populate reverse paths
        for (Path *reverse_path : *flow.reverse_paths) {
            Path *reduced_reverse_path = GetReducedPath(
                reverse_path, reduced_graph_map, data, reduced_data);
            bool new_path = true;
            for (Path *reverse_path : *reverse_paths) {
                if (*reverse_path == *reduced_reverse_path) {
                    new_path = false;
                    break;
                }
            }
            if (new_path)
                reverse_paths->push_back(reduced_reverse_path);
            else
                delete (reduced_reverse_path);
            npaths_reverse_unreduced = flow.reverse_paths->size();
        }
    }

    if (flow.path_taken_vector.size() > 0) {
        Path *reduced_path_taken = GetReducedPath(
            flow.path_taken_vector[0], reduced_graph_map, data, reduced_data);
        SetPathTaken(reduced_path_taken);
    }
    if (flow.reverse_path_taken_vector.size() > 0) {
        Path *reduced_reverse_path_taken =
            GetReducedPath(flow.reverse_path_taken_vector[0], reduced_graph_map,
                           data, reduced_data);
        SetReversePathTaken(reduced_reverse_path_taken);
    }
}

void Flow::DoneAddingPaths() {
    /* Since paths and reverse paths are shared, it's not safe to call
     * shrink_to_fit on them */
    // if (paths != NULL) paths->shrink_to_fit();
    // if (reverse_paths != NULL) reverse_paths->shrink_to_fit();
    path_taken_vector.shrink_to_fit();
    reverse_path_taken_vector.shrink_to_fit();
    snapshots.shrink_to_fit();
}

void Flow::AddPath(Path *path, bool is_path_taken) {
    if (paths == NULL)
        paths = new vector<Path *>();
    paths->push_back(path);
    if (is_path_taken) {
        SetPathTaken(path);
    }
}

void Flow::AddReversePath(Path *path, bool is_reverse_path_taken) {
    if (reverse_paths == NULL)
        reverse_paths = new vector<Path *>();
    reverse_paths->push_back(path);
    if (is_reverse_path_taken) {
        SetReversePathTaken(path);
    }
}

void Flow::SetPathTaken(Path *path) {
    assert(path_taken_vector.size() == 0);
    path_taken_vector.push_back(path);
}

void Flow::SetReversePathTaken(Path *path) {
    assert(reverse_path_taken_vector.size() == 0);
    reverse_path_taken_vector.push_back(path);
}

int Flow::GetLatestPacketsSent() {
    if (snapshots.empty())
        return 0;
    return snapshots.back()->packets_sent;
}

int Flow::GetLatestPacketsLost() {
    if (snapshots.empty())
        return 0;
    return snapshots.back()->packets_lost;
}

bool Flow::AnySnapshotBefore(double finish_time_ms) {
    return (snapshots.size() > 0 &&
            snapshots[0]->snapshot_time_ms <= finish_time_ms);
}

void Flow::AddSnapshot(double snapshot_time_ms, int packets_sent,
                       int packets_lost, int packets_randomly_lost) {
    FlowSnapshot *snapshot = new FlowSnapshot(
        snapshot_time_ms, packets_sent, packets_lost, packets_randomly_lost);
    snapshots.push_back(snapshot);
}

void Flow::PrintFlowSnapshots(ostream &out) {
    for (FlowSnapshot *snapshot : snapshots) {
        out << "Snapshot " << snapshot->snapshot_time_ms << " "
            << snapshot->packets_sent << " " << snapshot->packets_lost << " "
            << snapshot->packets_randomly_lost << endl;
    }
}

void Flow::PrintFlowMetrics(ostream &out) {
    out << "Flowid= " << src << " " << dest << " " << nbytes / 1500 << " "
        << start_time_ms << endl;
}

void Flow::PrintInfo(ostream &out) {
    PrintFlowMetrics(out);
    PrintFlowSnapshots(out);
    for (Path *path : *paths) {
        out << "flowpath";
        if (path == path_taken_vector[0]) {
            out << "_taken";
        }
        for (int n : *path) {
            out << " " << n;
        }
        out << endl;
    }
    for (Path *path : *reverse_paths) {
        out << "flowpath_reverse";
        if (path == reverse_path_taken_vector[0]) {
            out << "_taken";
        }
        for (int n : *path) {
            out << " " << n;
        }
        out << endl;
    }
}

vector<Path *> *Flow::GetPaths(double max_finish_time_ms) {
    if (PATH_KNOWN or TracerouteFlow(max_finish_time_ms)) {
        assert(path_taken_vector.size() == 1);
        return &path_taken_vector;
    }
    return paths;
}

vector<Path *> *Flow::GetReversePaths(double max_finish_time_ms) {
    if (PATH_KNOWN or TracerouteFlow(max_finish_time_ms)) {
        assert(reverse_path_taken_vector.size() == 1);
        return &reverse_path_taken_vector;
    }
    return reverse_paths;
}

Path *Flow::GetPathTaken() {
    assert(path_taken_vector.size() == 1);
    return path_taken_vector[0];
}

Path *Flow::GetReversePathTaken() {
    assert(reverse_path_taken_vector.size() == 1);
    return reverse_path_taken_vector[0];
}

void Flow::UpdateSnapshotPtr(double max_finish_time_ms) {
    // cout<<"UpdateSnapshotPtr "<<curr_snapshot_ptr<<"
    // "<<max_finish_time_ms<<endl;
    //! TODO(Bug): There is a race condition here!
    assert(curr_snapshot_ptr == -1 ||
           snapshots[curr_snapshot_ptr]->snapshot_time_ms < max_finish_time_ms);
    while (curr_snapshot_ptr + 1 < snapshots.size() &&
           snapshots[curr_snapshot_ptr + 1]->snapshot_time_ms <
               max_finish_time_ms) {
        curr_snapshot_ptr += 1;
    }
}

double Flow::GetDropRate(double max_finish_time_ms) {
    UpdateSnapshotPtr(max_finish_time_ms);
    if (curr_snapshot_ptr >= 0) {
        return ((float)snapshots[curr_snapshot_ptr]->packets_lost) /
               max(1.0e-30, (double)snapshots[curr_snapshot_ptr]->packets_sent);
    }
    return 0.0;
}

int Flow::GetPacketsLost(double max_finish_time_ms) {
    UpdateSnapshotPtr(max_finish_time_ms);
    if (curr_snapshot_ptr >= 0) {
        return snapshots[curr_snapshot_ptr]->packets_lost;
    }
    return 0;
}

int Flow::GetPacketsSent(double max_finish_time_ms) {
    UpdateSnapshotPtr(max_finish_time_ms);
    if (curr_snapshot_ptr >= 0) {
        return snapshots[curr_snapshot_ptr]->packets_sent;
    }
    return 0;
}

void Flow::SetFirstLinkId(int link_id) { first_link_id = link_id; }

void Flow::SetLastLinkId(int link_id) { last_link_id = link_id; }

void Flow::SetReverseFirstLinkId(int link_id) {
    reverse_first_link_id = link_id;
}

void Flow::SetReverseLastLinkId(int link_id) { reverse_last_link_id = link_id; }

bool Flow::IsFlowActive() {
    // return false;
    //! MAJOR MAJOR HACK FOR A SPECIFIC TOPOLOGY
    return (src < OFFSET_HOST or dest < OFFSET_HOST);
    // return (paths.size() == 1);
}

bool Flow::TracerouteFlow(double max_finish_time_ms) {
    return (
        PATH_KNOWN ||
        (TRACEROUTE_BAD_FLOWS && (GetPacketsLost(max_finish_time_ms) > 0)) ||
        (ACTIVE_PROBES_PATH_KNOWN && IsFlowActive()));
}

bool Flow::IsFlowBad(double max_finish_time_ms) {
    return (GetPacketsLost(max_finish_time_ms) > 0);
}

PII Flow::LabelWeightsFunc(double max_finish_time_ms) {
    UpdateSnapshotPtr(max_finish_time_ms);
    int gw = 0, bw = 0;
    if (curr_snapshot_ptr >= 0) {
        gw = snapshots[curr_snapshot_ptr]->packets_sent -
             snapshots[curr_snapshot_ptr]->packets_lost;
        bw = snapshots[curr_snapshot_ptr]->packets_lost;
    }
    return PII(gw, bw);
}

void Flow::ResetSnapshotCounter() { curr_snapshot_ptr = -1; }

void Flow::SetCachedIntermediateValue(long double value) {
    cached_intermediate_value = value;
}

long double Flow::GetCachedIntermediateValue() {
    return cached_intermediate_value;
}

bool Flow::DiscardFlow() {
    double drop_rate =
        ((double)GetLatestPacketsLost()) / max(1, GetLatestPacketsSent());
    /*
    if(drop_rate > 0.1){
        //cout << " ******* Discarding flow ***** " << GetLatestPacketsLost() <<
    " " << GetLatestPacketsSent() << endl; return true;
    }
    */
    switch (INPUT_FLOW_TYPE) {
    case ALL_FLOWS:
        return false;
        break;
    case ACTIVE_FLOWS:
        return !IsFlowActive();
        break;
    case PROBLEMATIC_FLOWS:
        return IsFlowActive();
        break;
    case APPLICATION_FLOWS:
        return IsFlowActive();
        break;
    default:
        return false;
    }
    // return (GetLatestPacketsSent() < 100);
    // return (src < OFFSET_HOST  or  dest < OFFSET_HOST or
    // GetLatestPacketsSent() < 0);
}

double Flow::GetEndTime() { return snapshots.back()->snapshot_time_ms; }

Flow::~Flow() {
    // for (FlowSnapshot* s: snapshots) delete(s);
}
