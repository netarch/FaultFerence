#include <iostream>
#include <stdio.h>
#include <thread>
#include <algorithm>
#include <stdlib.h>
#include <jsoncpp/json/json.h>
#include <sys/socket.h>
#include <chrono>
#include <netinet/in.h>
#include <string.h>
#include <mutex>
#include <arpa/inet.h>
#include <fstream>
#include <fcntl.h> // for open
#include <unistd.h> // for close
#include <pthread.h>
#include <vector>
#include <queue>
#include "thread_pool.h"
#include "flow_parser.h"
/* Flock headers */
#include <flow.h>
#include <logdata.h>
#include <bayesian_net.h>

using namespace std;

void HandleIncomingConnection(int socket, FlowParser *flow_parser){
    flow_parser->HandleIncomingConnection(socket);
}

struct SocketThreadArgs{
    int socket;
    FlowParser *flow_parser;
};

void* SocketThread(void *arg){
    SocketThreadArgs* args = (SocketThreadArgs*)arg;
    HandleIncomingConnection(args->socket, args->flow_parser);
    close(args->socket);
    delete args;
    pthread_exit(NULL);
}

void* RunAnalysisPeriodically(void* arg){
    FlowParser* flow_parser = (FlowParser*) arg;
    LogData* log_data = flow_parser->log_data;
    FlowQueue* flow_queue = flow_parser->GetFlowQueue();
    //!TODO: vipul
    BayesianNet estimator;
    vector<double> params = {1.0-5.0e-3, 2.0e-4, -25.0};
    estimator.SetParams(params);
    int nopenmp_threads = 1;
    while(true){
        auto start_time = chrono::high_resolution_clock::now();
        log_data->flows.clear();
        int nflows = flow_queue->size();
        for(int ii=0; ii<nflows; ii++){
            log_data->flows.push_back(flow_queue->pop());
        }
        double max_finish_time_ms = 1000.0;
        estimator.SetLogData(log_data, max_finish_time_ms, nopenmp_threads);
        Hypothesis estimator_hypothesis;
        estimator.LocalizeFailures(0.0, max_finish_time_ms,
                                  estimator_hypothesis, nopenmp_threads);
        double elapsed_time_ms = chrono::duration_cast<chrono::milliseconds>(
                chrono::high_resolution_clock::now() - start_time).count();
        cout << "Output Hypothesis "  << log_data->IdsToLinks(estimator_hypothesis)
             << " analysis time taken for "<< nflows <<" flows (ms) " <<  elapsed_time_ms;
        log_data->ResetForAnalysis();
        if (elapsed_time_ms < 1000.0){
            cout << " sleeping for time " << int(3000.0 - elapsed_time_ms)  << " ms" << endl;
            chrono::milliseconds timespan(int(3000.0 - elapsed_time_ms));
            std::this_thread::sleep_for(timespan);
        }
    else cout << endl;
    }
    return NULL;
}

int main(int argc, char *argv[]){
    ios_base::sync_with_stdio(false);

    if (argc != 5){
        cout << "Not enough arguments specified " << endl
             << "Usage: ./collector <topology_file> <path_file> <collector_ip> <collector_port>" << endl;
        exit(1);
    }
    char* topology_file = argv[1];
    char* path_file = argv[2];
    char* collector_ip = argv[3];
    int collector_port = atoi(argv[4]);

    int collector_socket, sock_opt=1;
    // Create socket file descriptor 
    if ((collector_socket = socket(AF_INET, SOCK_STREAM, 0)) == 0) {
        perror("Error while creating socket");
        exit(1); 
    } 

    // Set some options on the socket
    if (setsockopt(collector_socket, SOL_SOCKET, SO_REUSEADDR | SO_REUSEPORT, &sock_opt, sizeof(sock_opt)) != 0){
        perror("Error while setting socket options");
        exit(1);
    } 

    sockaddr_in collector_address;
    bzero((char*)&collector_address, sizeof(collector_address));
    collector_address.sin_family = AF_INET;
    //!TODO: see if " = htonl () " works
    collector_address.sin_addr.s_addr = inet_addr(collector_ip);
    collector_address.sin_port = htons(collector_port);

    if (bind(collector_socket, (struct sockaddr *)&collector_address, sizeof(collector_address)) != 0){
        perror("Error while binding");
        exit(1);
    }

    FlowParser* flow_parser = new FlowParser();
    flow_parser->PreProcessTopology(topology_file);
    flow_parser->PreProcessPaths(path_file);

    /* Launch daemon thread that will periodically invoke the analysis */
    pthread_t tid;
    if(pthread_create(&tid, NULL, RunAnalysisPeriodically, flow_parser) != 0 ){
        perror("Failed to create analysis thread");
        exit(1);
    }
#define USE_THREAD_POOL
#ifdef USE_THREAD_POOL
    int num_threads = 20;
    ThreadPool thread_pool(num_threads);
    thread_pool.SetFlowParser(flow_parser);
#endif
    while(true){
        int MAX_PENDING_CONNECTIONS = 4096; 
        if (listen(collector_socket, MAX_PENDING_CONNECTIONS) != 0){
            perror("Error while listening on socket");
            continue;
        }

        int new_socket, addrlen = sizeof(collector_address);
        if ((new_socket = accept(collector_socket, (struct sockaddr *)&collector_address,
                        (socklen_t*)&addrlen))<0){
            perror("Error while accepting connection");
            continue;
        }
        else{
#ifdef USE_THREAD_POOL
            thread_pool.AddConnection(new_socket);
#else
            SocketThreadArgs *args = new SocketThreadArgs();
            args->socket = new_socket;
            args->flow_parser = flow_parser;
            if(pthread_create(&tid, NULL, SocketThread, args) != 0)
                cout << "Failed to create thread" << endl;
#endif
        }
    }
    return 0;
}
