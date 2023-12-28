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
START_INDEX = 1
ITERATIONS = 100
TOPOLOGY_PREFIX = "rg"
DEGREE_SWITCH_MAPPING = {
    10: 125,
    12: 180,
    14: 245,
    16: 320,
    18: 405,
    20: 500
}

DEGREE_HOST_MAPPING = {
    10: 750,
    12: 1296,
    14: 2058,
    16: 3072,
    18: 4374,
    20: 6000
}

SEQUENCE_SCHEME_MAPPING = {
    "Intelligent": "FF.",
    "Random": "Op."
}

INFERENCE_SCHEME_MAPPING = {
    "Flock": " w/ Flock",
    "Naive": " w/o Flock"
}

ALL_STEPS = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
AVG_STEPS = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
CONFIDENCE_INTERVAL = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
LAST_DEVICES = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
AVG_LAST_DEVICES = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

PRECISION = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
AVG_PRECISION = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

# Schema of the log path should be <logdir>/<topology>/<iteration>/<sequence_scheme>/<inference_scheme>/
for topology in os.listdir(log_path):
    if not topology.startswith(TOPOLOGY_PREFIX):
        continue
    topo_degree = int(topology.lstrip(TOPOLOGY_PREFIX + "_deg")[:2])
    topology_path = os.path.join(log_path, topology)
    if topo_degree > 20:
        continue
    for iter_index in range(START_INDEX, ITERATIONS + START_INDEX):
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
                last_devices_list = open(os.path.join(inference_path, "equivalent_devices")).readlines()[-2].split(", Devices: [")[1].split("]")[0].split(", ")
                failed_device = int(open(os.path.join(iter_path, "initial.fails")).read().split(" ")[3])
                if not last_devices_list == ['']:
                    print(failed_device, last_devices_list)
                    last_devices_list = [int(x) for x in last_devices_list]
                    if failed_device in last_devices_list:
                        PRECISION[sequence_scheme][inference_scheme][topo_degree].append(1/len(last_devices_list))
                    else:
                        PRECISION[sequence_scheme][inference_scheme][topo_degree].append(0)
                if inference_scheme == "Naive" and last_devices == 0: # HACK
                    last_devices = 2
                    PRECISION[sequence_scheme][inference_scheme][topo_degree].append(0.5)
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
            CONFIDENCE_INTERVAL[sequence_scheme][inference_scheme][topo_degree] = st.norm.interval(confidence=0.90, loc=np.mean(all_steps), scale=st.sem(all_steps))

            AVG_PRECISION[sequence_scheme][inference_scheme][topo_degree] = np.mean(PRECISION[sequence_scheme][inference_scheme][topo_degree])


fm.fontManager.addfont("./gillsans.ttf")
matplotlib.rcParams.update({'font.size': 24, 'font.family': "GillSans"})

# colors = ['#cc6600', '#330066', '#af0505', '#db850d', '#a5669f', '#028413', '#000000', '#0e326d']
# colors = ['seagreen', 'brown', 'skyblue', 'black']
colors = ["#f1a200", "#995ec3", "#7fbf7b", "#cf4c32"]
markers = ['o', 's', '^', 'v', 'p', '*', 'p', 'h']
# linestyles = ["-", ":", "-.", "dotted"]

fig = plt.figure(figsize=(8, 6.5))
ax = plt.subplot(1, 1, 1)

i = 0
for sequence_scheme in AVG_STEPS:
    for inference_scheme in AVG_STEPS[sequence_scheme]:
        dicty = AVG_STEPS[sequence_scheme][inference_scheme]
        dicty = OrderedDict(sorted(dicty.items()))
        confidence_dicty = CONFIDENCE_INTERVAL[sequence_scheme][inference_scheme]
        confidence_dicty = OrderedDict(sorted(confidence_dicty.items()))

        # ax.plot([DEGREE_HOST_MAPPING[x] for x in dicty.keys()], dicty.values(), linewidth=3, color=colors[i], marker=markers[i], label = "-".join([sequence_scheme[:1], inference_scheme[:1]]))
        # ax.fill_between([DEGREE_HOST_MAPPING[x] for x in confidence_dicty.keys()], [x[0] for x in confidence_dicty.values()], [x[1] for x in confidence_dicty.values()], color=colors[i], alpha=0.2)
        
        confidence_dicty = np.array([x[1] for x in confidence_dicty.values()]) - np.array(list(dicty.values()))
        if i > 1:
            markersize = 14
        else:
            markersize = 11
        ax.errorbar([DEGREE_HOST_MAPPING[x] for x in dicty.keys()], dicty.values(), confidence_dicty.transpose(), color=colors[i], marker=markers[i], markersize=markersize, label = SEQUENCE_SCHEME_MAPPING[sequence_scheme] + INFERENCE_SCHEME_MAPPING[inference_scheme], capsize = 3, linewidth=3, elinewidth=0.9)
        i +=1

# ax.set_xlabel('Degree')
ax.set_xlabel("Topology size (# hosts)", alpha=0.5)
ax.set_ylabel('# Manual micro-changes', alpha = 0.5)

# ax.set_xticks([10, 12, 14, 16, 18, 20]) # Topology degree
# ax.set_xticks([100, 200, 300, 400, 500]) # Number of switches
ax.set_xticks([0, 1500, 3000, 4500, 6000]) # Number of hosts

# ax.set_yticklabels(["", 10, 20, 30, 40]) # For ft
# ax.set_yticks([0, 10, 20, 30, 40]) # For ft

ax.tick_params(axis="both", direction="in", labelcolor="grey", width=3, length=6)

plt.ylim(bottom=0)
# ax.set_xlim([100, 500]) # Number of switches
ax.grid(color="gray", alpha=0.3)

# Changing the color of the axis
ax.spines["bottom"].set(color="grey", alpha=0.3)
ax.spines["top"].set(color="grey", alpha=0.3)
ax.spines["left"].set(color="grey", alpha=0.3)
ax.spines["right"].set(color="grey", alpha=0.3)

plt.tight_layout()
legend = plt.legend(fontsize="22", markerscale=0.7, handlelength=0.7, handletextpad=0.4, framealpha=0.3)

plt.savefig("steps-" + TOPOLOGY_PREFIX + ".png")

print("ALL STEPS")
PRINTY = []
THING_TO_PRINT = AVG_PRECISION
for sequence_scheme in THING_TO_PRINT:
    for inference_scheme in THING_TO_PRINT[sequence_scheme]:
        for topo_degree in THING_TO_PRINT[sequence_scheme][inference_scheme]:
            all_steps = THING_TO_PRINT[sequence_scheme][inference_scheme][topo_degree]
            stringy = str(topo_degree) + " " + sequence_scheme + " " + inference_scheme + " " + str(all_steps)
            PRINTY.append(stringy)

PRINTY.sort()
for line in PRINTY:
    print(line)

# print("******\n NUM DEVICES IN LAST STEP")
# pprint(json.loads(json.dumps(LAST_DEVICES)))
# print("******\n AVG STEPS:")
# pprint(json.loads(json.dumps(AVG_STEPS)))
# print("******\n AVG LAST DEVICES:")
# pprint(json.loads(json.dumps(AVG_LAST_DEVICES)))


