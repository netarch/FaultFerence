import sys
import os
import networkx as nx

if not len(sys.argv) == 4: 
	print("Required number of arguments: 3.", len(sys.argv)-1, "provided")
	print("Arguments: <degree> <oversubscription> <bi-directional:true/false>")
	sys.exit()

k = int(sys.argv[1])
switches = int((5 * k * k)/4)
servers = int((k * k * k)/4)
tors = int((k * k)/2)
oversubscription = int(sys.argv[2])
bi_dir = sys.argv[3]
outputFile = "ft_deg%d_sw%d_svr%d_os%d_bidir_%s.edgelist" % (k, switches, servers, oversubscription, bi_dir)

G = nx.Graph()

for pod in range(0, k):
    for agg in range(0, int(k/2)):
        for edge in range(0, int(k/2)):
            aggind = pod * int(k/2) + agg + tors
            edgeind = pod * int(k/2) + edge
            G.add_edge(aggind, edgeind)

    for agg in range(0, int(k/2)):
        for out in range(0, int(k/2)):
            aggind = pod * int(k/2) + agg + tors
            coreind =  agg * int(k/2) + out + 2 * tors
            G.add_edge(aggind, coreind)


with open(os.path.join("..",outputFile), 'w') as f:
    edges =  G.edges()
    for (u,v) in edges:
        f.write(str(u) + " " + str(v) + "\n")
        if(bi_dir == "true"):
            f.write(str(v) + " " + str(u) + "\n")

    currsvr = 10000
    for i in range(tors):
        deg = int(k/2) * oversubscription
        for kk in range(0, deg):
            f.write(str(currsvr) + "->" + str(i) + "\n")
            currsvr = currsvr + 1

print("File %s created" % outputFile)
