import os
import sys
import numpy as np
from collections import defaultdict
from pprint import pprint
import json
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

log_path = sys.argv[1]
ITERATIONS = 10

ALL_STEPS = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
LAST_DEVICES = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
AVG_STEPS = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

# Schema of the log path should be <logdir>/<topology>/<iteration>/<sequence_scheme>/<inference_scheme>/
for topology in os.listdir(log_path):
    topo_degree = int(topology.lstrip("ft_deg")[:2])
    topology_path = os.path.join(log_path, topology)
    for iter_index in range(1, ITERATIONS + 1):
        iter_string = str(iter_index)
        iter_path = os.path.join(topology_path, iter_string)
        for sequence_scheme in os.listdir(iter_path):
            sequence_path = os.path.join(iter_path, sequence_scheme)
            if not os.path.isdir(sequence_path):
                continue
            for inference_scheme in os.listdir(sequence_path):
                inference_path = os.path.join(sequence_path, inference_scheme)
                num_steps = int(open(os.path.join(inference_path, "num_steps")).read())
                last_devices = int(open(os.path.join(inference_path, "equivalent_devices")).readlines()[-2].split(", Devices:")[0].split("Size: ")[1])
                ALL_STEPS[sequence_scheme][inference_scheme][topo_degree].append(num_steps)
                LAST_DEVICES[sequence_scheme][inference_scheme][topo_degree].append(last_devices)

for sequence_scheme in ALL_STEPS:
    for inference_scheme in ALL_STEPS[sequence_scheme]:
        for topo_degree in ALL_STEPS[sequence_scheme][inference_scheme]:
            AVG_STEPS[sequence_scheme][inference_scheme][topo_degree] = np.mean(ALL_STEPS[sequence_scheme][inference_scheme][topo_degree])


fm.fontManager.addfont("./gillsans.ttf")
matplotlib.rcParams.update({'font.size': 28, 'font.family': "GillSans"})

colors = ['#cc6600', '#330066', '#af0505', '#db850d', '#a5669f', '#028413', '#000000', '#0e326d']
markers = ['o', 's', '^', 'v', 'p', '*', 'p', 'h']
linestyles = ["-", ":", "-.", "dotted"]

fig = plt.figure(figsize=(8, 6.5))
ax = plt.subplot(1, 1, 1)

i = 0
for sequence_scheme in AVG_STEPS:
    for inference_scheme in AVG_STEPS[sequence_scheme]:
        dicty = AVG_STEPS[sequence_scheme][inference_scheme]
        ax.plot(dicty.keys(), dicty.values(), color=colors[i], marker=markers[i], linestyle=linestyles[i], label = "-".join([sequence_scheme, inference_scheme]))
        i +=1

ax.set_xlabel('Degree')
ax.set_ylabel('# steps')

# ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1])
# ax.set_xticks(topo_degrees)

# ax.set_ylim([0, 1])
# ax.set_xlim([0, 600])
ax.grid()

plt.tight_layout()
plt.legend()
plt.savefig("hello.png")

pprint(json.loads(json.dumps(ALL_STEPS)), indent = 4)
pprint(json.loads(json.dumps(LAST_DEVICES)), indent = 4)
pprint(json.loads(json.dumps(AVG_STEPS)), indent = 4)

