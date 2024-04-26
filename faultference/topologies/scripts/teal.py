import json
import os

from networkx import *
DIR_NAME = "teal_data"
HOST_START_INDEX = 10000

for filey in os.listdir(DIR_NAME):
    data = json.load(open(os.path.join(DIR_NAME, filey), 'r'))
    G = readwrite.json_graph.node_link_graph(data).to_undirected()
    nodesy = list(G)
    nodesy.sort()
    write_edgelist(G, os.path.join("..", filey.rstrip(".json") + ".edgelist"), data = False)

    with open(os.path.join("..", filey.rstrip(".json") + ".edgelist"), "w") as f:
        for liney in generate_edgelist(G, data = False):
            f.write(liney + "\n")
        
        for index, node in enumerate(nodesy):
            f.write(str(HOST_START_INDEX + index) + "->" + str(node) + "\n")
            
