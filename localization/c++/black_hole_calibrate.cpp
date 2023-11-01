#include "bayesian_net.h"
#include "bayesian_net_continuous.h"
#include "bayesian_net_sherlock.h"
#include "black_hole_utils.h"
#include "common_testing_system.h"
#include "doubleO7.h"
#include "net_bouncer.h"
#include "utils.h"
#include <assert.h>
#include <bits/stdc++.h>
#include <chrono>
#include <iostream>

using namespace std;

bool USE_DIFFERENT_TOPOLOGIES = false;
vector<string> __trace_files__;

vector<string> GetFilesHelper() { return __trace_files__; }
pair<vector<string>, vector<string>> GetFilesTopologiesHelper() {
    assert(false);
    return pair<vector<string>, vector<string>>();
}

vector<string> (*GetFiles)() = GetFilesHelper;
pair<vector<string>, vector<string>> (*GetFilesTopologies)() =
    GetFilesTopologiesHelper;

vector<vector<double>> GetFlockParams() {
    vector<vector<double>> params;
    double eps = 1.0e-10;
    for (double p1c = 1.0e-2; p1c <= 75.0e-2 + eps; p1c += 8.0e-2) {
        for (double p2 = 0.01e-3; p2 <= 1.5e-3 + eps; p2 += 0.25e-3) {
            if (p2 >= p1c - 0.5e-3)
                continue;
            for (double nprior : {10, 20})
                params.push_back(vector<double>{1.0 - p1c, p2, -nprior});
        }
    }
    /*
    for (double p1c = 1.0e-2; p1c <= 3.0e-2 + eps; p1c += 4.0e-2) {
        for (double p2 = 1.0e-3; p2 <= 3.0e-3 + eps; p2 += 4.0e-3) {
            if (p2 >= p1c - 0.5e-3)
                continue;
            for (double nprior : {2})
                params.push_back(vector<double>{1.0 - p1c, p2, -nprior});
        }
    }
    */
    return params;
}

void CalibrateFlock(vector<pair<string, string>> topo_traces,
                    double min_start_time_ms, double max_finish_time_ms,
                    int nopenmp_threads) {
    vector<vector<double>> params = GetFlockParams();
    cout << "Num params " << params.size() << endl;

    vector<PDD> results;
    BayesianNet estimator;
    PATH_KNOWN = false;
    TRACEROUTE_BAD_FLOWS = false;
    INPUT_FLOW_TYPE = APPLICATION_FLOWS;
    VERBOSE = false;

    for (auto &pss : topo_traces)
        __trace_files__.push_back(pss.second);
    GetPrecisionRecallParamsFiles(topo_traces[0].first, min_start_time_ms,
                                  max_finish_time_ms, params, results,
                                  &estimator, nopenmp_threads);
    for (int i = 0; i < params.size(); i++) {
        cout << "Calibrate " << params[i] << " " << results[i] << endl;
    }
}

void CalibrateFlock1(vector<pair<string, string>> topo_traces,
                     double min_start_time_ms, double max_finish_time_ms,
                     int nopenmp_threads) {
    vector<vector<double>> params = GetFlockParams();
    cout << "Num params" << params.size() << endl;

    vector<vector<PDD>> results;

    for (auto [topo_f, trace_f] : topo_traces) {
        cout << "calling GetDataFromLogFileParallel on " << topo_f << ", "
             << trace_f << endl;

        BayesianNet estimator;
        PATH_KNOWN = false;
        TRACEROUTE_BAD_FLOWS = false;
        INPUT_FLOW_TYPE = APPLICATION_FLOWS;
        VERBOSE = false;

        vector<PDD> result;
        GetPrecisionRecallParamsFile(topo_f, trace_f, min_start_time_ms,
                                     max_finish_time_ms, params, &estimator,
                                     result, nopenmp_threads);
        results.push_back(result);
        cout << "Done" << endl;
    }
    for (int i = 0; i < params.size(); i++) {
        int npresent = 0;
        for (int k = 0; k < topo_traces.size(); k++)
            npresent += (results[k][i].second > 0.999);
        cout << "Calibrate " << params[i] << " " << npresent << " "
             << topo_traces.size() << endl;
    }
}

int main(int argc, char *argv[]) {
    assert(argc >= 6 && argc % 2 == 0);
    double min_start_time_ms = atof(argv[1]) * 1000.0,
           max_finish_time_ms = atof(argv[2]) * 1000.0;
    int nopenmp_threads = atoi(argv[3]);
    cout << "Using " << nopenmp_threads << " openmp threads" << endl;

    vector<pair<string, string>> in_topo_traces;
    for (int ii = 4; ii < argc; ii += 2) {
        string topo_file(argv[ii]);
        cout << "Adding topology file " << topo_file << endl;
        string trace_file(argv[ii + 1]);
        cout << "Adding trace file " << trace_file << endl;
        in_topo_traces.push_back(pair<string, string>(topo_file, trace_file));
    }

    CalibrateFlock(in_topo_traces, min_start_time_ms, max_finish_time_ms,
                   nopenmp_threads);

    return 0;
}
