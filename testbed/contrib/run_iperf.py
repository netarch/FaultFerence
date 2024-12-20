import sys
import os
import random
import json
import threading
import time
import numpy as np
import subprocess
from subprocess import Popen
import argparse
from collections import defaultdict
from pprint import pprint

parser = argparse.ArgumentParser(description='Run iperf3 traffic')
parser.add_argument("n", help="number of iperf servers/clients", type=int)
parser.add_argument("result_file", help="Specify the output result file.")
parser.add_argument("dest_ip", help="Specify dest ip")
parser.add_argument("host_ip", help="Specify host (self) ip")
parser.add_argument("iperf_role", help="Specify whether to launch servers or launch clients =[servers/clients/].")
args = parser.parse_args()

PRINT_ONLY = False

class IperfServer():
    def __init__(self, tcp_dst_port):
        self.tcp_dst_port = tcp_dst_port
        self.out = ""
        self.err = ""

    def LaunchServer(self):
        port = self.tcp_dst_port
        #cmd = "iperf -s  -p " + str(port) + " -V -l 128K -w 512KB "
        cmd = "iperf -s  -p " + str(port)
        print(cmd)
        if not PRINT_ONLY:
            svr_thread = Popen(cmd, shell=True, preexec_fn=os.setpgrp)
        #svr_thread = Popen(cmd, shell=True, start_new_session=True)
        #self.out, err = svr_thread.communicate()

class IperfClient(threading.Thread):
    def __init__(self, dest_ip, dest_port, flow_bytes, time=30, max_rate="1M"):
        self.dest_ip = dest_ip
        self.dest_port = dest_port
        self.time = time
        self.max_rate = max_rate
        self.flow_bytes = flow_bytes
        threading.Thread.__init__(self)
        self.out = ""

    def run(self):
        cmd = "iperf -c " +  self.dest_ip +  " -n " +  str(self.flow_bytes) + " -p " + str(self.dest_port)  + " -B " + str(self.max_rate)
        # cmd = "iperf -c " +  self.dest_ip +  " -t " +  str(self.time) + " -p " + str(self.dest_port)  + " -B " + str(self.max_rate)
        print(cmd)
        if not PRINT_ONLY:
            connection_thread = Popen(cmd, shell=True, stdout=subprocess.PIPE)
            self.out, err = connection_thread.communicate()
        '''
        while(True):
            try:
                connection_thread = Popen(cmd, shell=True, stdout=subprocess.PIPE)
                self.out, err = connection_thread.communicate()
                break
            except:
                print("Exception in connection_thread")
                break
        '''

UNIFORM_FLOW_DIST = False
mean_bytes = 200.0 * 1024
#median_bytes = 10.0 * 1500 #packets * 1500.0
shape = 1.05
#scale = median_bytes/(2.0 ** shape)
scale = mean_bytes * (shape - 1)/shape;

def get_flow_bytes():
    if UNIFORM_FLOW_DIST:
       return random.randint(50, 1250) * 1000
    else:
        flow_bytes = int((np.random.pareto(shape) + 1) * scale)
        # skip flows > 10 MB as testbed is unable to handle those flows
        while flow_bytes < 1 * 1024 or flow_bytes > 10 * 1024 * 1024:
            flow_bytes = int((np.random.pareto(shape) + 1) * scale)
        return flow_bytes


iperf_server_ports = [x for x in range(5301,5301+args.n)]
if(args.iperf_role == "servers"):
    for port in iperf_server_ports:
        svr_obj = IperfServer(port)
        svr_obj.LaunchServer()
    print("All servers launched")

elif(args.iperf_role == "clients"):
    remaining_flows = 10
    interflow_sec = 0.05 #0.15 #0.10 #0.075 #0.015
    connection_threads = []
    while(remaining_flows > 0):
        time.sleep(interflow_sec)
        remaining_flows -= 1
        dest_port = random.choice(iperf_server_ports)
        flow_bytes = get_flow_bytes()
        connection_thread = IperfClient(args.dest_ip, dest_port, flow_bytes)
        connection_thread.start()
        connection_threads.append(connection_thread)

    print("writing to ", args.result_file)
    resultsfile = open(args.result_file, 'w')
    for connection_thread in connection_threads:
        connection_thread.join()
        result = connection_thread.out
        resultsfile.write("%s\n" % result)
        print(result)
    resultsfile.close()

else:
    print("Incorrect IperfRole: allowed values: clients/servers")
