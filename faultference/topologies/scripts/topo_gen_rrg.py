import sys
import networkx as nx

if not len(sys.argv) == 7: 
	print("Required number of arguments: 6.", len(sys.argv), "provided")
	print("Usage: python networkGenerator_ns3.py <degree> <switches> <servers> <oversubscription> <instance number> <prefixFile>")
	sys.exit()

totDegree = int(sys.argv[1])
switches = int(sys.argv[2])
servers = int(sys.argv[3])
oversubscription = int(sys.argv[4])
instance = int(sys.argv[5])
prefixFile = sys.argv[6]
outputFile = "%s_deg%d_sw%d_svr%d_os%d_i%d.edgelist" % (prefixFile, totDegree, switches, servers, oversubscription, instance)

HOST_OFFSET = 10000

degseq=[]
sdeg = int(servers/switches)
rem = servers%switches
for i in range(switches):
    deg = sdeg
    if (i >= switches-rem):
        deg = deg+1
    degseq.append(totDegree-deg)

print("Degree sequence : ", degseq)

G = nx.random_degree_sequence_graph(degseq)
while (not nx.is_connected(G)):
	G = nx.random_degree_sequence_graph(degseq)

with open(outputFile, 'w') as f:
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
