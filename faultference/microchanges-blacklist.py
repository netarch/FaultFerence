# Usage: python3 microchanges-blacklist.py <num_nodes> <fraction_requested>
# num_nodes: Total number of switches in the topology
# fraction_requested: Fraction of nodes that cannot support each micro-action

import os
import random
import sys

FORBIDDEN_DIR = "forbidden"
MICRO_ACTIONS = ["active-probe", "link-removal"]

num_nodes = int(sys.argv[1])
fraction_requested = int(sys.argv[2])

for action in MICRO_ACTIONS:
    with open(os.path.join(FORBIDDEN_DIR, action), "w") as f:
        listy = random.sample(range(num_nodes), (num_nodes * fraction_requested) // 100)
        listy = [str(x) for x in listy]
        f.write(" ".join(listy))