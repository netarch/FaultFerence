import os
import networkx as nx

NODE_MAPPING = {}
UNMAPPED_LINKS = []

sw_index = 0
host_offset = 0
TOPO_DIR = ".."
TOPO_NAME = "campus-str"

HAVE_HOST_PREFIX = ["sw-"]
NOT_HAVE_HOST_PREFIX = ["bd-", "core", "dist"]
HOST_INDEX = 10000
HOSTS_PER_NODE = 20

with open(os.path.join(TOPO_DIR, TOPO_NAME + ".edgelist")) as f:
    lines = f.readlines()
    for line in lines:
        if len(line.strip()) == 0:
            continue
        line_split = line.split(" ")

        src = line_split[0].strip()
        dst = line_split[1].strip()

        if src not in NODE_MAPPING:
            NODE_MAPPING[src] = sw_index
            sw_index +=1

        if dst not in NODE_MAPPING:
            NODE_MAPPING[dst] = sw_index
            sw_index +=1
        
        link = [src, dst]
        link.sort()

        if link in UNMAPPED_LINKS:
            continue
            if link[0].startswith("bd-") and link[1].startswith("dist"):
                continue
            else:
                if not (input("Accept duplicate link: " + line) == "y"):
                    print("Rejecting the line")
                    continue
        
        # if len(line_split) > 2:
        if False:
            if not (input("Accept this line: " + line) == "y"):
                print("Rejecting the line")
                continue
        UNMAPPED_LINKS.append([src, dst])

# print(UNMAPPED_LINKS)
# print(NODE_MAPPING)

with open(os.path.join(TOPO_DIR, TOPO_NAME + "-processed.edgelist"), "w") as f:
    for link in UNMAPPED_LINKS:
        src, dst = link
        src_index = NODE_MAPPING[src]
        dst_index = NODE_MAPPING[dst]
        f.write(str(src_index) + " " + str(dst_index) + "\n")

    for node in NODE_MAPPING:
        for elem in NOT_HAVE_HOST_PREFIX:
            if node.startswith(elem):
                continue
        # if node not in HAVE_HOST_PREFIX:
        #     if not(input("Should I add host to this: " + node) == "y"):
        #         print("Not adding host to", node)
        #         continue
        for i in range(HOSTS_PER_NODE):
            host_id = HOST_INDEX + host_offset
            f.write(str(host_id) + "->" + str(NODE_MAPPING[node]) + "\n")
            host_offset+=1

print("Number of switches:", sw_index - 1)
print("Number of hosts:", host_offset - 1)

# To check if the entire graph is connected or not
print("Connected components:",)
for elem in list(nx.connected_components(nx.from_edgelist(UNMAPPED_LINKS))):
    print("***", elem)
