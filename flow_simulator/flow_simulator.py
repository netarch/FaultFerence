import sys
import multiprocessing
from multiprocessing import Process, Queue
import copy
import time
import random
import math
import numpy as np
import networkx as nx
import argparse
from utils import *

parser = argparse.ArgumentParser()

parser.add_argument("--network_file", type=str, required=True)
parser.add_argument("--nfailures", type=int, default=0)
parser.add_argument("--flows_file", type=str, required=True)
parser.add_argument("--outfile", type=str, required=True)
parser.add_argument("--fail_file", type=str)
parser.add_argument("--fails_from_file", action="store_true", default=False)
parser.add_argument("--active_probes_file", type=str, required=False, default=None)
parser.add_argument("--failed_flows_only", action="store_true", default=False)
parser.add_argument(
    "--duplicate_link", nargs=2, metavar=("l1", "l2"), type=int, default=(-1, -1)
)

args = parser.parse_args()


HOST_OFFSET = 10000
BLACK_HOLE = True

# random.seed(42)
# np.random.seed(42)

print("Random witness", random.randint(1, 100000))

# tuple1 = (1573, 1031, 10390, 10650)
# tuple2 = (1573, 1029, 10390, 10650)
# print(TupleHash(tuple1), TupleHash(tuple1)%25, TupleHash(tuple2), TupleHash(tuple2)%25)

if args.fail_file is None:
    args.fail_file = args.outfile + ".fails"

topo = Topology()
topo.ReadGraphFromFile(args.network_file)

outfile = open(args.outfile, "w+")
topo.SetOutFile(outfile)
nflows = None
sumflowsize = None
if BLACK_HOLE:
    nflows, sumflowsize = topo.PrintLogsBlackHole(args)
else:
    # nflows, sumflowsize = topo.PrintLogsMisconfiguredACL(args.nfailures, args.fail_file, args.flows_file)
    nflows, sumflowsize = topo.PrintLogsSilentDrop(args.nfailures, args.flows_file)

print("Sum flow size: ", sumflowsize, "Numflows", nflows)
