#include "utils.h"
#include "logdata.h"
#include <cstring>
#include <assert.h>
#include <string>
#include <fstream>
#include <chrono>
#include <algorithm>
#include <omp.h>
#include <mutex>
#include <atomic>
#include <sparsehash/dense_hash_map>
using google::dense_hash_map;

inline bool StringStartsWith(const string &a, const string &b) {
    return (b.length() <= a.length() && equal(b.begin(), b.end(), a.begin()));
}

inline bool StringEqualTo(const char* a, const char* b) {
    while ((*b == *a) and (*a!='\0')){
        a++;
        b++;
    }
    return (*b=='\0' and *a=='\0');
}



void GetDataFromLogFileDistributed(string dirname, int nchunks, LogData *result, int nopenmp_threads){ 
    auto start_time = chrono::high_resolution_clock::now();
    #pragma omp parallel for num_threads(nopenmp_threads)
    for(int i=0; i<nchunks; i++){
        GetDataFromLogFile(dirname + "/" + to_string(i), result);
    }
    if constexpr (VERBOSE){
        cout<<"Read log file chunks in "<<GetTimeSinceMilliSeconds(start_time) << " seconds"<<endl;
    }
}

//Compute and store (Link <-> Link-id) mappings
void GetLinkMappings(string topology_file, LogData* result){
    ifstream tfile(topology_file);
    string line;
    // All trace files have hosts numbered as host + OFFSET_HOST
    const int OFFSET_HOST = 10000;
    if constexpr (VERBOSE){
        cout << "Asuuming trace file has hosts numbered as host_id + " << OFFSET_HOST << " (OFFSET)" << endl;
    }
    while (getline(tfile, line)){
        char *linec = const_cast<char*>(line.c_str());
        int index = line.find("->");
        if (index == string::npos){
            int sw1, sw2;
            GetFirstInt(linec, sw1);
            GetFirstInt(linec, sw2);
            result->GetLinkId(Link(sw1, sw2));
            result->GetLinkId(Link(sw2, sw1));
        }
        else{
            line.replace(index, 2, " ");
            int svr, sw;
            GetFirstInt(linec, svr);
            svr += OFFSET_HOST;
            GetFirstInt(linec, sw);
            result->GetLinkId(Link(sw, svr));
            result->GetLinkId(Link(svr, sw));
        }
    }
}

void GetDataFromLogFile(string filename, LogData *result){ 
    auto start_time = chrono::high_resolution_clock::now();
    vector<Flow*> chunk_flows;
    dense_hash_map<Link, int, hash<Link> > links_to_ids_cache;
    links_to_ids_cache.set_empty_key(Link(-1, -1));
    auto GetLinkId =
        [&links_to_ids_cache, result] (Link link){
            int link_id;
            auto it = links_to_ids_cache.find(link);
            if (it == links_to_ids_cache.end()){
                link_id = result->GetLinkId(link);
                links_to_ids_cache[link] = link_id;
            }
            else{
                link_id = it->second;
            }
            return link_id;
        };
    vector<int> temp_path (10);
    vector<int> path_nodes (10);
    ifstream infile(filename);
    string line, op;
    Flow *flow = NULL;
    int nlines = 0;
    while (getline(infile, line)){
        char* linec = const_cast<char*>(line.c_str());
        GetString(linec, op);
        //cout << op <<endl;
        //istringstream line_stream (line);
        //sscanf(linum, "%s *", op);
        //line_stream >> op;
        //cout << "op " << op << " : " << line << endl;
        nlines += 1;
        if (StringStartsWith(op, "FPRT")){
            assert (flow != NULL);
            temp_path.clear();
            path_nodes.clear();
            int node;
            // This is only the portion from dest_rack to src_rack
            while (GetFirstInt(linec, node)){
                if (path_nodes.size() > 0){
                    temp_path.push_back(GetLinkId(Link(path_nodes.back(), node)));
                }
                path_nodes.push_back(node);
            }
            assert(path_nodes.size()>0); // No direct link for src_host to dest_host or vice_versa
            MemoizedPaths *memoized_paths = result->GetMemoizedPaths(path_nodes[0], *path_nodes.rbegin());;
            Path* path = memoized_paths->GetPath(temp_path);
            flow->SetReversePathTaken(path);
        }
        else if (StringStartsWith(op, "FPT")){
            assert (flow != NULL);
            temp_path.clear();
            path_nodes.clear();
            int node;
            // This is only the portion from src_rack to dest_rack
            while (GetFirstInt(linec, node)){
                if (path_nodes.size() > 0){
                    temp_path.push_back(GetLinkId(Link(path_nodes.back(), node)));
                }
                path_nodes.push_back(node);
            }
            assert(path_nodes.size()>0); // No direct link for src_host to dest_host or vice_versa
            MemoizedPaths *memoized_paths = result->GetMemoizedPaths(path_nodes[0], *path_nodes.rbegin());
            Path *path = memoized_paths->GetPath(temp_path);
            flow->SetPathTaken(path);
        }
        else if (StringStartsWith(op, "FP")){
            assert (flow == NULL);
            temp_path.clear();
            path_nodes.clear();
            int node;
            // This is only the portion from src_rack to dest_rack
            while (GetFirstInt(linec, node)){
                if (path_nodes.size() > 0){
                    temp_path.push_back(GetLinkId(Link(path_nodes.back(), node)));
                }
                path_nodes.push_back(node);
            }
            assert(path_nodes.size()>0); // No direct link for src_host to dest_host or vice_versa
            MemoizedPaths *memoized_paths = result->GetMemoizedPaths(path_nodes[0], *path_nodes.rbegin());
            memoized_paths->AddPath(temp_path);
            //memoized_paths->GetPath(temp_path);
            //cout << temp_path << endl;
        }
        else if (op == "SS"){
            double snapshot_time_ms;
            int packets_sent, packets_lost, packets_randomly_lost;
            GetFirstDouble(linec, snapshot_time_ms);
            GetFirstInt(linec, packets_sent);
            GetFirstInt(linec, packets_lost);
            GetFirstInt(linec, packets_randomly_lost);
            assert (flow != NULL);
            flow->AddSnapshot(snapshot_time_ms, packets_sent, packets_lost, packets_randomly_lost);
        }
        else if (op == "FID"){
            // Log the previous flow
            if (flow != NULL) flow->DoneAddingPaths();
            if (flow != NULL and flow->paths!=NULL and flow->paths->size() > 0 and flow->path_taken_vector.size() == 1){
                assert (flow->GetPathTaken());
                if constexpr (CONSIDER_REVERSE_PATH){
                    assert (flow->GetReversePathTaken());
                }
                if (flow->GetLatestPacketsSent() > 0 and !flow->DiscardFlow()
                    and flow->paths->size() > 0){
                    chunk_flows.push_back(flow);
                }
            }
            int src, dest, srcrack, destrack, nbytes;
            double start_time_ms;
            GetFirstInt(linec, src);
            GetFirstInt(linec, dest);
            GetFirstInt(linec, srcrack);
            GetFirstInt(linec, destrack);
            GetFirstInt(linec, nbytes);
            GetFirstDouble(linec, start_time_ms);
            flow = new Flow(src, 0, dest, 0, nbytes, start_time_ms);
            // Set flow paths
            MemoizedPaths *memoized_paths = result->GetMemoizedPaths(srcrack, destrack);
            memoized_paths->GetAllPaths(&flow->paths);
            flow->SetFirstLinkId(GetLinkId(Link(flow->src, srcrack)));
            flow->SetLastLinkId(GetLinkId(Link(destrack, flow->dest)));
        }
        else if (op == "Failing_link"){
            int src, dest;
            double failparam;
            GetFirstInt(linec, src);
            GetFirstInt(linec, dest);
            GetFirstDouble(linec, failparam);
            //sscanf (linum + op.size(),"%d %*d %f", &src, &dest, &failparam);
            result->AddFailedLink(Link(src, dest), failparam);
            if constexpr (VERBOSE){
                cout<< "Failed link "<<src<<" "<<dest<<" "<<failparam<<endl; 
            }
        }
        else if (op == "link_statistics"){
            assert (false);
        }
    }
    // Log the last flow
    if (flow != NULL) flow->DoneAddingPaths();
    if (flow != NULL and flow->paths!=NULL and flow->paths->size() > 0 and flow->path_taken_vector.size() == 1){
        assert (flow->GetPathTaken());
        if constexpr (CONSIDER_REVERSE_PATH){
            assert (flow->GetReversePathTaken());
        }
        if (flow->GetLatestPacketsSent() > 0 and !flow->DiscardFlow() and flow->paths!=NULL and flow->paths->size() > 0){
            //flow->PrintInfo();
            chunk_flows.push_back(flow);
        }
    }
    result->AddChunkFlows(chunk_flows);
    cout << "Num flows " << chunk_flows.size() << endl;
    if constexpr (VERBOSE){
        cout<< "Read log file in "<<GetTimeSinceMilliSeconds(start_time)
            << " seconds, numlines " << nlines << endl;
    }
}

void ProcessFlowLines(vector<FlowLines>& all_flow_lines, LogData* result, int nopenmp_threads){
    auto start_time = chrono::high_resolution_clock::now();
    //vector<Flow*> flows_threads[nopenmp_threads];
    Flow* flows_threads = new Flow[all_flow_lines.size()];
    vector<int> temp_path[nopenmp_threads];
    vector<int> path_nodes[nopenmp_threads];
    for (int t=0; t<nopenmp_threads; t++){
        temp_path[t].reserve(MAX_PATH_LENGTH + 2);
        path_nodes[t].reserve(MAX_PATH_LENGTH + 2);
    }
    int previous_nflows = result->flows.size();
    #pragma omp parallel for num_threads(nopenmp_threads)
    for(int ii=0; ii<all_flow_lines.size(); ii++){
        int thread_num = omp_get_thread_num();
        FlowLines& flow_lines = all_flow_lines[ii];
        /* FID line */
        int src, dest, srcrack, destrack, nbytes;
        double start_time_ms;
        char* restore_c = flow_lines.fid_c;
        GetFirstInt(flow_lines.fid_c, src);
        GetFirstInt(flow_lines.fid_c, dest);
        GetFirstInt(flow_lines.fid_c, srcrack);
        GetFirstInt(flow_lines.fid_c, destrack);
        GetFirstInt(flow_lines.fid_c, nbytes);
        GetFirstDouble(flow_lines.fid_c, start_time_ms);
        flow_lines.fid_c = restore_c;
        Flow *flow = &(flows_threads[ii]);
        *flow = Flow(src, 0, dest, 0, nbytes, start_time_ms);
        //Flow *flow = new Flow(src, 0, dest, 0, nbytes, start_time_ms);
        // Set flow paths
        flow->SetFirstLinkId(result->GetLinkIdUnsafe(Link(flow->src, srcrack)));
        flow->SetLastLinkId(result->GetLinkIdUnsafe(Link(destrack, flow->dest)));
        MemoizedPaths *memoized_paths = result->GetMemoizedPaths(srcrack, destrack);
        memoized_paths->GetAllPaths(&flow->paths);

        /* Reverse flow path taken */
        if (flow_lines.fprt_c != NULL){
            temp_path[thread_num].clear();
            path_nodes[thread_num].clear();
            restore_c = flow_lines.fprt_c;
            int node;
            // This is only the portion from dest_rack to src_rack
            while (GetFirstInt(flow_lines.fprt_c, node)){
                if (path_nodes[thread_num].size() > 0){
                    temp_path[thread_num].push_back(result->GetLinkIdUnsafe(Link(path_nodes[thread_num].back(), node)));
                }
                path_nodes[thread_num].push_back(node);
            }
            assert(path_nodes[thread_num].size()>0); // No direct link for src_host to dest_host or vice_versa
            MemoizedPaths *memoized_paths = result->GetMemoizedPaths(path_nodes[thread_num][0], *path_nodes[thread_num].rbegin());;
            Path* path = memoized_paths->GetPath(temp_path[thread_num]);
            flow->SetReversePathTaken(path);
            flow_lines.fprt_c = restore_c;
        }
        /* Flow path taken */
        if(flow_lines.fpt_c != NULL){
            temp_path[thread_num].clear();
            path_nodes[thread_num].clear();
            restore_c = flow_lines.fpt_c;
            int node;
            // This is only the portion from src_rack to dest_rack
            while (GetFirstInt(flow_lines.fpt_c, node)){
                if (path_nodes[thread_num].size() > 0){
                    temp_path[thread_num].push_back(result->GetLinkIdUnsafe(Link(path_nodes[thread_num].back(), node)));
                }
                path_nodes[thread_num].push_back(node);
            }
            assert(path_nodes[thread_num].size()>0); // No direct link for src_host to dest_host or vice_versa
            MemoizedPaths *memoized_paths = result->GetMemoizedPaths(path_nodes[thread_num][0], *path_nodes[thread_num].rbegin());
            Path *path = memoized_paths->GetPath(temp_path[thread_num]);
            flow->SetPathTaken(path);
            flow_lines.fpt_c = restore_c;
        }
        /* Snapshots */
        for(int ss=0; ss<flow_lines.ss_c.size(); ss++){
            char *ss_c = flow_lines.ss_c[ss];
            double snapshot_time_ms;
            int packets_sent, packets_lost, packets_randomly_lost;
            GetFirstDouble(ss_c, snapshot_time_ms);
            GetFirstInt(ss_c, packets_sent);
            GetFirstInt(ss_c, packets_lost);
            GetFirstInt(ss_c, packets_randomly_lost);
            assert (flow != NULL);
            flow->AddSnapshot(snapshot_time_ms, packets_sent, packets_lost, packets_randomly_lost);
        }
        flow->DoneAddingPaths();
    }
    for(int ii=0; ii<all_flow_lines.size(); ii++){
        Flow *flow = &(flows_threads[ii]);
        if (flow->paths!=NULL and flow->paths->size() > 0 and flow->path_taken_vector.size() == 1){
            assert (flow->GetPathTaken());
            if constexpr (CONSIDER_REVERSE_PATH){
                assert (flow->GetReversePathTaken());
            }
            if (flow->GetLatestPacketsSent() > 0 and !flow->DiscardFlow() and flow->paths->size() > 0){
                //flow->PrintInfo();
                result->flows.push_back(flow);
            }
        }
    }
    if constexpr (VERBOSE){
        //cout<< "Processed flow lines in "<<GetTimeSinceMilliSeconds(start_time)
        //    << " seconds, numflows " << all_flow_lines.size() << endl;
    }
}

void ProcessFlowPathLines(vector<char*>& lines, vector<array<int, MAX_PATH_LENGTH+2> >& path_nodes_list, int nopenmp_threads){
    auto start_time = chrono::high_resolution_clock::now();
    vector<int> path_nodes[nopenmp_threads];
    for(int t=0; t<nopenmp_threads; t++){
        path_nodes[t].reserve(MAX_PATH_LENGTH+2);
    }
    path_nodes_list.resize(lines.size());
    #pragma omp parallel for num_threads(nopenmp_threads)
    for(int ii=0; ii<lines.size(); ii++){
        int thread_num = omp_get_thread_num();
        char *linec = lines[ii];
        //cout << "line " << linec << endl;
        path_nodes[thread_num].clear();
        int node;
        // This is only the portion from src_rack to dest_rack
        while (GetFirstInt(linec, node)){
            path_nodes[thread_num].push_back(node);
        }
        assert(path_nodes[thread_num].size()>0); // No direct link for src_host to dest_host or vice_versa
        path_nodes_list[ii][0] = path_nodes[thread_num].size();
        copy_n(path_nodes[thread_num].begin(), path_nodes[thread_num].size(), path_nodes_list[ii].begin()+1);
    }
    if constexpr (VERBOSE){
        cout<< "Parsed flow path lines in "<<GetTimeSinceMilliSeconds(start_time)
            << " seconds, numlines " << lines.size() << endl;
    }
}

inline char* strdup (char *str){
    int str_size = strlen(str);
    char* result = new char[str_size+1];
    memcpy(result, str, str_size+1);
    return result;
}

void GetDataFromLogFileParallel(string filename, string topology_filename, LogData *result, int nopenmp_threads){ 
    auto start_time = chrono::high_resolution_clock::now();
    GetLinkMappings(topology_filename, result); 

    FILE *infile = fopen(filename.c_str(), "r");
    char *linec = new char[512];
    char *restore_c = linec;
    size_t linesz = 0;
    char *op = new char[100];
    int nlines = 0;

    auto getline_result = getline(&linec, &linesz, infile);
    GetString(linec, op);
    while(getline_result > 0 and StringEqualTo(op, "Failing_link")){
        nlines += 1;
        int src, dest;
        GetFirstInt(linec, src);
        GetFirstInt(linec, dest);
        double failparam;
        GetFirstDouble(linec, failparam);
        result->AddFailedLink(Link(src, dest), failparam);
        if constexpr (VERBOSE){
            cout<< "Failed link "<<src<<" "<<dest<<" "<<failparam<<endl; 
        }
        linec = restore_c;
        getline_result = getline(&linec, &linesz, infile);
        GetString(linec, op);
    }

    const int FLOWPATH_BUFFER_SIZE = 5000001;
    vector<char* > buffered_lines;
    buffered_lines.reserve(FLOWPATH_BUFFER_SIZE);
    const int FLOWLINE_BUFFER_SIZE = 11000000;
    FlowLines *curr_flow_lines;
    vector<FlowLines> buffered_flows;
    buffered_flows.reserve(FLOWLINE_BUFFER_SIZE);
    while(getline_result > 0 and StringEqualTo(op, "FP")){
        nlines += 1;
        buffered_lines.push_back(strdup(linec));
        linec = restore_c;
        getline_result = getline(&linec, &linesz, infile);
        GetString(linec, op);
    }
    if constexpr (VERBOSE){
        cout<< "Calling ProcessFlowPathLines after "<<GetTimeSinceMilliSeconds(start_time)
            << " seconds" << endl;
    }
    if (buffered_lines.size() > 0){
        vector<array<int, MAX_PATH_LENGTH+2> > path_nodes_list;
        ProcessFlowPathLines(buffered_lines, path_nodes_list, nopenmp_threads);
        vector<int> temp_path(MAX_PATH_LENGTH+2);
        for(array<int, MAX_PATH_LENGTH+2>& path_nodes: path_nodes_list){
            temp_path.clear();
            int nnodes = path_nodes[0];
            for (int i=2; i<nnodes+1; i++){
                temp_path.push_back(result->GetLinkIdUnsafe(Link(path_nodes[i-1], path_nodes[i])));
            }
            MemoizedPaths *memoized_paths = result->GetMemoizedPaths(path_nodes[1], path_nodes[nnodes]);
            memoized_paths->AddPath(temp_path);
        }
        //!TODO check where delete[] needs to be called instead of delete/free
        for (char* c: buffered_lines) delete[] c;
        if constexpr (VERBOSE){
            cout<< "Processed flow paths after "<<GetTimeSinceMilliSeconds(start_time)
                << " seconds, numlines " << buffered_lines.size() << endl;
        }
    }

    cout << "sizeof(Flow) " << sizeof(Flow) << endl;
    while(getline_result > 0){
        nlines += 1;
        char *dup_linec = strdup(linec);
        //cout << "op " << op << " : " << line << endl;
        if (StringEqualTo(op, "SS")){
            //assert(curr_flow_lines->fid_c != NULL);
            curr_flow_lines->ss_c.push_back(dup_linec);
        }
        else if (StringStartsWith(op, "FID")){
            if(buffered_flows.size() > FLOWLINE_BUFFER_SIZE){
                ProcessFlowLines(buffered_flows, result, nopenmp_threads);
                for_each(buffered_flows.begin(), buffered_flows.end(), [](FlowLines& fl){fl.FreeMemory();});
                buffered_flows.clear();
            }
            buffered_flows.push_back(FlowLines());
            curr_flow_lines = &(buffered_flows.back());
            curr_flow_lines->fid_c = dup_linec;
        }
        else if (StringEqualTo(op, "FPT")){
            //assert(curr_flow_lines->fpt_c == NULL);
            curr_flow_lines->fpt_c = dup_linec;
        }
        else if (StringEqualTo(op, "FPRT")){
            //assert(curr_flow_lines->fprt_c == NULL);
            curr_flow_lines->fprt_c = dup_linec;
        }
        linec = restore_c;
        getline_result = getline(&linec, &linesz, infile);
        GetString(linec, op);
    }

    if constexpr (VERBOSE){
        cout<< "Calling ProcessFlowLines after "<<GetTimeSinceMilliSeconds(start_time)
            << " seconds, numflows " << buffered_flows.size() << endl;
    }
    ProcessFlowLines(buffered_flows, result, nopenmp_threads);
    for_each(buffered_flows.begin(), buffered_flows.end(), [](FlowLines& fl){fl.FreeMemory();});
    buffered_flows.clear();
    cout << "Num flows " << result->flows.size() << endl;
    if constexpr (VERBOSE){
        cout<< "Read log file in "<<GetTimeSinceMilliSeconds(start_time)
            << " seconds, numlines " << nlines << endl;
    }
}


PDD GetPrecisionRecall(Hypothesis& failed_links, Hypothesis& predicted_hypothesis){
    vector<int> correctly_predicted;
    for (int link_id: predicted_hypothesis){
        if (failed_links.find(link_id) != failed_links.end()){
            correctly_predicted.push_back(link_id);
        }
    }
    double precision = 1.0, recall = 1.0;
    if (predicted_hypothesis.size() > 0) {
        precision = ((double) correctly_predicted.size())/predicted_hypothesis.size();
    }
    if (failed_links.size() > 0){
        recall = ((double) correctly_predicted.size())/failed_links.size();
    }
    return PDD(precision, recall);
}
