import sys
import networkx as nx
import random
import numpy as np
import math
import os

## For hardware calibration ##
## random: seeds 1-4, seeds 9-12, seeds 17-20
## skewed: seeds 5-8, seeds 13-16, seeds 21-24

UNIFORM = True
NB_PROBES = True

if not len(sys.argv) == 4: 
	print("Required number of arguments: 3.", len(sys.argv)-1, "provided")
	print("Arguments: <x> <y> <bi-directional:true/false>")
	sys.exit()

x = int(sys.argv[1])
y = int(sys.argv[2])
switches = x + 2 * y
num_servers = x * (x + y)
bi_dir = sys.argv[3]
outputFile = "ls_x%d_y%d_bidir_%s.edgelist" % (prefixFile, x, y, instance, bi_dir)

G = nx.Graph()
for leaf in range(y, x+2*y):
    for spine in range(0, y):
        G.add_edge(leaf, spine)

num_servers = 0
HOST_OFFSET = 10000
with open(outputFile, 'w') as f:
    edges =  G.edges()
    for (u,v) in edges:
        f.write(str(u) + " " + str(v) + "\n")
        if(bi_dir == "true"):
            f.write(str(v) + " " + str(u) + "\n")

    currsvr = HOST_OFFSET
    for leaf in range(y, x+2*y):
        for kk in range(0, x):
            f.write(str(currsvr) + "->" + str(leaf) + "\n")
            currsvr = currsvr + 1
            num_servers += 1

ncore_switches = y
racks = x + y
servers_per_rack = int(int(num_servers)/int(racks))
print("Num racks", racks, "Servers per rack", servers_per_rack)
print("File %s created" % outputFile)

