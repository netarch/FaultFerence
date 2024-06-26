#include "bayesian_net.h"
#include "bayesian_net_continuous.h"
#include "bayesian_net_sherlock.h"
#include "doubleO7.h"
#include "faultference_utils.h"
#include "net_bouncer.h"
#include "utils.h"
#include <assert.h>
#include <bits/stdc++.h>
#include <chrono>
#include <iostream>

using namespace std;

int main(int argc, char *argv[]) {
    // assert(argc >= 7 && argc%2==1);
    double min_start_time_ms = atof(argv[1]) * 1000.0,
           max_finish_time_ms = atof(argv[2]) * 1000.0;
    int nopenmp_threads = atoi(argv[3]);
    cout << "Using " << nopenmp_threads << " openmp threads" << endl;
    cout << "Number of arguments passed are " << argc << endl;

    string sequence_mode(argv[4]);
    string inference_mode(argv[5]);
    string minimize_mode(argv[6]);
    string topo_name(argv[7]);
    string eq_devices_file(argv[8]);
    string fail_file(argv[9]);
    string micro_change;
    cout << "Sequence mode is " << sequence_mode << endl;
    cout << "Inference mode is " << inference_mode << endl;
    cout << "Reading failures from " << fail_file << endl;
    set<int> previous_eq_devices = ReadEqDevices(eq_devices_file);
    auto failed_components = ReadFailuresBlackHole(fail_file);

    vector<pair<string, string>> in_topo_traces;
    for (int ii = 10; ii < argc; ii += 3) {
        string topo_file(argv[ii]);
        cout << "Adding topology file " << topo_file << endl;
        string trace_file(argv[ii + 1]);
        cout << "Adding trace file " << trace_file << endl;
        string new_micro_change(argv[ii + 2]);
        in_topo_traces.push_back(pair<string, string>(topo_file, trace_file));
        micro_change = new_micro_change;
    }

    BayesianNet estimator;
    PATH_KNOWN = false;
    TRACEROUTE_BAD_FLOWS = false;
    INPUT_FLOW_TYPE = ALL_FLOWS;
    VERBOSE = true;
    ACTIVE_PROBES_PATH_KNOWN = false;
    // GetExplanationEdges(in_topo_traces, max_finish_time_ms, nopenmp_threads);
    // OperatorScheme(in_topo_traces, min_start_time_ms, max_finish_time_ms,
    // nopenmp_threads);
    auto start = chrono::high_resolution_clock::now();
    LocalizeFailure(in_topo_traces, min_start_time_ms, max_finish_time_ms,
                    nopenmp_threads, sequence_mode, inference_mode, minimize_mode, topo_name, previous_eq_devices, micro_change);
    auto stop = chrono::high_resolution_clock::now();
    auto duration = chrono::duration_cast<chrono::microseconds>(stop - start);
    cout << endl << "Time taken: " << duration.count() << endl;

    return 0;
}
