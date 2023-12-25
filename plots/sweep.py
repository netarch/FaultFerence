import os
import sys
import numpy as np
from collections import defaultdict, OrderedDict
import scipy.stats as st 
from pprint import pprint
import json
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

log_path = sys.argv[1]
ITERATIONS = 20
TOPOLOGY_PREFIX = "ft"

ALL_STEPS = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
AVG_STEPS = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
CONFIDENCE_INTERVAL = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
LAST_DEVICES = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
AVG_LAST_DEVICES = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

# Schema of the log path should be <logdir>/<topology>/<iteration>/<sequence_scheme>/<inference_scheme>/
for topology in os.listdir(log_path):
    if not topology.startswith(TOPOLOGY_PREFIX):
        continue
    topo_degree = int(topology.lstrip(TOPOLOGY_PREFIX + "_deg")[:2])
    topology_path = os.path.join(log_path, topology)
    if topo_degree > 20:
        continue
    for iter_index in range(1, ITERATIONS + 1):
        iter_string = str(iter_index)
        iter_path = os.path.join(topology_path, iter_string)
        if not iter_string in os.listdir(topology_path):
            print("WARNING:", topo_degree, "- does not have iteration", iter_string)
            continue
        for sequence_scheme in os.listdir(iter_path):
            sequence_path = os.path.join(iter_path, sequence_scheme)
            if not os.path.isdir(sequence_path):
                continue
            for inference_scheme in os.listdir(sequence_path):
                inference_path = os.path.join(sequence_path, inference_scheme)
                if not "num_steps" in os.listdir(inference_path):
                    print("WARNING:", topo_degree, iter_string, inference_scheme, sequence_scheme, "- run does not have an output yet.")
                    continue
                logs = open(os.path.join(inference_path, "logs")).read()
                if "Killed" in logs:
                    print("WARNING:", topo_degree, iter_string, inference_scheme, sequence_scheme, "- some iterations were killed in this run")
                    continue
                num_steps = int(open(os.path.join(inference_path, "num_steps")).read())
                last_devices = int(open(os.path.join(inference_path, "equivalent_devices")).readlines()[-2].split(", Devices:")[0].split("Size: ")[1])
                if inference_scheme == "Naive" and last_devices == 0: # HACK
                    last_devices = 2
                if last_devices == 0:
                    print("WARNING:", topo_degree, iter_string, inference_scheme, sequence_scheme, "- number of equivalent devices reduced to 0. How?")
                    continue
                ALL_STEPS[sequence_scheme][inference_scheme][topo_degree].append(num_steps)
                LAST_DEVICES[sequence_scheme][inference_scheme][topo_degree].append(last_devices)

for sequence_scheme in ALL_STEPS:
    for inference_scheme in ALL_STEPS[sequence_scheme]:
        for topo_degree in ALL_STEPS[sequence_scheme][inference_scheme]:
            all_steps = ALL_STEPS[sequence_scheme][inference_scheme][topo_degree]
            AVG_STEPS[sequence_scheme][inference_scheme][topo_degree] = np.mean(all_steps)
            AVG_LAST_DEVICES[sequence_scheme][inference_scheme][topo_degree] = np.mean(LAST_DEVICES[sequence_scheme][inference_scheme][topo_degree])
            CONFIDENCE_INTERVAL[sequence_scheme][inference_scheme][topo_degree] = st.norm.interval(alpha=0.75, loc=np.mean(all_steps), scale=st.sem(all_steps))


fm.fontManager.addfont("./gillsans.ttf")
matplotlib.rcParams.update({'font.size': 28, 'font.family': "GillSans"})

# colors = ['#cc6600', '#330066', '#af0505', '#db850d', '#a5669f', '#028413', '#000000', '#0e326d']
colors = ["red", "yellow", "green", "blue"]
markers = ['o', 's', '^', 'v', 'p', '*', 'p', 'h']
linestyles = ["-", ":", "-.", "dotted"]

fig = plt.figure(figsize=(8, 6.5))
ax = plt.subplot(1, 1, 1)

i = 0
for sequence_scheme in AVG_STEPS:
    for inference_scheme in AVG_STEPS[sequence_scheme]:
        dicty = AVG_STEPS[sequence_scheme][inference_scheme]
        dicty = OrderedDict(sorted(dicty.items()))
        confidence_dicty = CONFIDENCE_INTERVAL[sequence_scheme][inference_scheme]
        confidence_dicty = OrderedDict(sorted(confidence_dicty.items()))
        print(confidence_dicty)
        ax.plot(dicty.keys(), dicty.values(), color=colors[i], marker=markers[i], linestyle=linestyles[i], label = "-".join([sequence_scheme[:1], inference_scheme[:1]]))
        ax.fill_between(confidence_dicty.keys(), [x[0] for x in confidence_dicty.values()], [x[1] for x in confidence_dicty.values()], color=colors[i], alpha=0.5)
        i +=1

ax.set_xlabel('Degree')
ax.set_ylabel('# steps')

# ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1])
ax.set_xticks([10, 12, 14, 16, 18, 20])

# ax.set_ylim([0])
plt.ylim(ymin=0)
# ax.set_xlim([0, 600])
ax.grid()

plt.tight_layout()
plt.legend(fontsize="20")
plt.savefig("steps.png")

# print("ALL STEPS")
# pprint(json.loads(json.dumps(ALL_STEPS)))
# print("******\n NUM DEVICES IN LAST STEP")
# pprint(json.loads(json.dumps(LAST_DEVICES)))
# print("******\n AVG STEPS:")
# pprint(json.loads(json.dumps(AVG_STEPS)))
# print("******\n AVG LAST DEVICES:")
# pprint(json.loads(json.dumps(AVG_LAST_DEVICES)))


