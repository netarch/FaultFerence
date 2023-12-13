import os
import sys
import numpy as np
from collections import defaultdict
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

log_path = sys.argv[1]
topologies = os.listdir(log_path)

ALL_STEPS = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
AVG_STEPS = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

for topology in topologies:
    print(topology)
    topology_path = os.path.join(log_path, topology)
    for sequence_scheme in os.listdir(topology_path):
        print(sequence_scheme)
        sequence_path = os.path.join(topology_path, sequence_scheme)
        for inference_scheme in os.listdir(sequence_path):
            print(inference_scheme)
            inference_path = os.path.join(sequence_path, inference_scheme)
            if not inference_scheme == "Flock" or not sequence_scheme == "Intelligent":
                continue
            num_steps = [int(open(os.path.join(inference_path, iteration, "num_steps")).read()) for iteration in os.listdir(inference_path)]
            topo_degree = int(topology.lstrip("topo_ft_deg")[:2])
            print(topo_degree)
            print(num_steps)
            ALL_STEPS[sequence_scheme][inference_scheme][topo_degree] = num_steps
            AVG_STEPS[sequence_scheme][inference_scheme][topo_degree] = np.mean(num_steps)


fm.fontManager.addfont("./gillsans.ttf")
matplotlib.rcParams.update({'font.size': 28, 'font.family': "GillSans"})

colors = ['#cc6600', '#330066', '#af0505', '#db850d', '#a5669f', '#028413', '#000000', '#0e326d']
markers = ['o', 's', '^', 'v', 'p', '*', 'p', 'h']
linestyles = ["-", ":", "-."]

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
plt.savefig("hello.png")