#include <iostream>
#include <assert.h>
#include "utils.h"
#include "bayesian_net.h"
#include "bayesian_net_continuous.h"
#include <chrono>

using namespace std;

int main(int argc, char *argv[]){
    assert (argc == 6);
    string filename (argv[1]); 
    cout << "Running analysis on file "<<filename << endl;
    string topology_filename (argv[2]);
    cout << "Reading topology from file " << topology_filename << endl;
    double min_start_time_ms = atof(argv[3]) * 1000.0, max_finish_time_ms = atof(argv[4]) * 1000.0;
    int nopenmp_threads = atoi(argv[5]);
    cout << "Using " << nopenmp_threads << " openmp threads"<<endl;
    //int nchunks = 32;
    LogData data;
    //GetDataFromLogFile(filename, &data);
    GetDataFromLogFileParallel(filename, topology_filename, &data, nopenmp_threads);
    string a="";
    //GetDataFromLogFileDistributed(filename, nchunks, &data, nchunks);
    Hypothesis failed_links_set;
    data.GetFailedLinkIds(failed_links_set);
    BayesianNet estimator;
    vector<double> params = {1.0-5.0e-3, 2.0e-4};
    estimator.SetParams(params);
    estimator.SetLogData(&data, max_finish_time_ms, nopenmp_threads);
    Hypothesis estimator_hypothesis;
    estimator.LocalizeFailures(min_start_time_ms, max_finish_time_ms,
                               estimator_hypothesis, nopenmp_threads);
    PDD precision_recall = GetPrecisionRecall(failed_links_set, estimator_hypothesis);
    cout << "Output Hypothesis: " << data.IdsToLinks(estimator_hypothesis) << " precsion_recall "
         <<precision_recall.first << " " << precision_recall.second<<endl;
    return 0;
}
