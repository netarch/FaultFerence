import sys
import networkx as nx
import os

if not len(sys.argv) == 5: 
	print("Required number of arguments: 4.", len(sys.argv), "provided")
	print("Arguments: <degree> <switches> <servers> <oversubscription>")
	sys.exit()

totDegree = int(sys.argv[1])
switches = int(sys.argv[2])
servers = int(sys.argv[3])
oversubscription = int(sys.argv[4])
outputFile = "rg_deg%d_sw%d_svr%d_os%d.edgelist" % (totDegree, switches, servers, oversubscription)

HOST_OFFSET = 10000

degseq=[]
sdeg = int(servers/switches)
rem = servers%switches
for i in range(switches):
    deg = sdeg
    if (i >= switches-rem):
        deg = deg+1
    degseq.append(totDegree-deg)

G = nx.random_degree_sequence_graph(degseq)
while (not nx.is_connected(G)):
	G = nx.random_degree_sequence_graph(degseq)

with open(os.path.join("..", outputFile), 'w') as f:
    edges =  G.edges()
    for (u,v) in edges:
        f.write(str(u) + " " + str(v) + "\n")

    currsvr = 0
    for i in range(switches):
        deg = sdeg
        if (i >= switches-rem):
            deg = deg+1
        deg = deg * oversubscription
        for kk in range(0, deg):
            f.write(str(currsvr + HOST_OFFSET) + "->" + str(i) + "\n")
            currsvr = currsvr + 1

print("File %s created" % outputFile)
