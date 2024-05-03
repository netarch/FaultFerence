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

def GetTimeValue(file_path):
    lines = open(file_path).readlines()
    for line in lines:
        if "Time taken:" in line:
            return int(line.lstrip("Time taken: "))/100
    assert(False)

log_path = sys.argv[1]
START_INDEX = 1
ITERATIONS = 2
MAX_NUM_STEPS = 250 # This is useful while calculating the average equivalent device size per step
TOPOLOGY_PREFIX = "ft"
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

PLOT_MAPPING = {
    "Intelligent": {
        "Flock": {
            "name": "FaultFerence",
            "color": "#f1a200",
            "marker": "o",
            "markersize": 11
        },
        "Naive": {
            "name": "FaultFerence w/o Flock",
            "color": "#995ec3",
            "marker": "s",
            "markersize": 11
        }
        
    },
    "Random": {
        "Flock": {
            "name": "Operator w/ Flock",
            "color": "#7fbf7b",
            "marker": "^",
            "markersize": 14
        },
        "Naive": {
            "name": "Operator",
            "color": "#cf4c32",
            "marker": "v",
            "markersize": 14
        }
    }
}

ALL_TIMES = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
AVG_TIMES_DEGREE = defaultdict(lambda: defaultdict(int))
ALL_TIMES_STEP = defaultdict(lambda: defaultdict(list))
AVG_TIMES_STEP = defaultdict(lambda: defaultdict(int))
CONFIDENCE_DEGREE = defaultdict(lambda: defaultdict(int))
CONFIDENCE_STEP = defaultdict(lambda: defaultdict(int))

# Schema of the log path should be <logdir>/<topology>/<iteration>/<sequence_scheme>/<inference_scheme>/
for topology in os.listdir(log_path):
    if not topology.startswith(TOPOLOGY_PREFIX):
        continue
    topo_degree = int(topology.lstrip(TOPOLOGY_PREFIX + "_deg")[:2])
    topology_path = os.path.join(log_path, topology)
    for iter_index in range(START_INDEX, ITERATIONS + START_INDEX):
        iter_string = str(iter_index)
        iter_path = os.path.join(topology_path, iter_string)

        # If some iterations are missing or still going on - this raises a warning
        if not iter_string in os.listdir(topology_path):
            print("WARNING:", topo_degree, "- does not have iteration", iter_string)
            continue
        for sequence_scheme in os.listdir(iter_path):
            sequence_path = os.path.join(iter_path, sequence_scheme)

            # There are some configuration fails which are unique to each run kept in this directory
            if not os.path.isdir(sequence_path):
                continue

            for inference_scheme in os.listdir(sequence_path):
                inference_path = os.path.join(sequence_path, inference_scheme, "Steps")
                # If the run is still ongoing / failed due to some error - this raises a warning
                if not "num_steps" in os.listdir(inference_path):
                    print("WARNING:", topo_degree, iter_string, inference_scheme, sequence_scheme, "- run does not have an output yet.")
                    continue

                # We noticed that processes got killed sometimes due to memory constraints - here's a check for that.
                logs = open(os.path.join(inference_path, "logs")).read()
                if "Killed" in logs:
                    print("WARNING:", topo_degree, iter_string, inference_scheme, sequence_scheme, "- some iterations were killed in this run")
                    continue
                num_steps = int(open(os.path.join(inference_path, "num_steps")).read())
                all_times = [GetTimeValue(os.path.join(inference_path, "localization", "iter_" + str(stepy))) for stepy in range(1, num_steps + 1)]
                ALL_TIMES[topo_degree][inference_scheme][iter_index] = all_times

                for stepy in range(num_steps):
                    if topo_degree == 10:
                        ALL_TIMES_STEP[inference_scheme][stepy].append(all_times[stepy])

for topo_degree in ALL_TIMES:
    for inference_scheme in ALL_TIMES[topo_degree]:
        TEMPEST = [x for xs in list(ALL_TIMES[topo_degree][inference_scheme].values()) for x in xs]
        AVG_TIMES_DEGREE[inference_scheme][topo_degree] = np.mean(TEMPEST)
        CONFIDENCE_DEGREE[inference_scheme][topo_degree] = st.norm.interval(confidence=0.90, loc=np.mean(TEMPEST), scale=st.sem(TEMPEST))
        
for inference_scheme in ALL_TIMES_STEP:
    for steps in ALL_TIMES_STEP[inference_scheme]:
        TEMPEST = ALL_TIMES_STEP[inference_scheme][steps]
        AVG_TIMES_STEP[inference_scheme][steps] = np.mean(TEMPEST)
        CONFIDENCE_STEP[inference_scheme][steps] = st.norm.interval(confidence=0.90, loc=np.mean(TEMPEST), scale=st.sem(TEMPEST))

fm.fontManager.addfont("./gillsans.ttf")
matplotlib.rcParams.update({'font.size': 24, 'font.family': "GillSans"})

# Plot 1 specific code starts
fig = plt.figure(figsize=(8, 6.5))
ax = plt.subplot(1, 1, 1)
i = 0
for inference_scheme in AVG_TIMES_DEGREE:
        dicty = AVG_TIMES_DEGREE[inference_scheme]
        dicty = OrderedDict(sorted(dicty.items()))
        confidence_dicty = CONFIDENCE_DEGREE[inference_scheme]
        confidence_dicty = OrderedDict(sorted(confidence_dicty.items()))

        # ax.plot([DEGREE_HOST_MAPPING[x] for x in dicty.keys()], dicty.values(), linewidth=3, color=colors[i], marker=markers[i], label = "-".join([sequence_scheme[:1], inference_scheme[:1]]))
        # ax.fill_between([DEGREE_HOST_MAPPING[x] for x in confidence_dicty.keys()], [x[0] for x in confidence_dicty.values()], [x[1] for x in confidence_dicty.values()], color=colors[i], alpha=0.2)
        
        confidence_dicty = np.array([x[1] for x in confidence_dicty.values()]) - np.array(list(dicty.values()))

        line_config = PLOT_MAPPING["Intelligent"][inference_scheme]
        ax.errorbar([DEGREE_HOST_MAPPING[x] for x in dicty.keys()], dicty.values(), confidence_dicty.transpose(), color=line_config["color"], marker=line_config["marker"], markersize=line_config["markersize"], label = line_config["name"], capsize = 3, linewidth=3, elinewidth=0.9)
        i +=1

# ax.set_xlabel('Degree')
ax.set_xlabel("Topology size (# hosts)", alpha=0.5)
ax.set_ylabel('Runtime (ms)', alpha = 0.5)

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

plt.savefig("figures/time-" + TOPOLOGY_PREFIX + ".png")

# Plot 1 specific code ends


# Plot 2 specific code starts
# DEVICES_PLOT_MAX_RANGE = 61 # for ft
DEVICES_PLOT_MAX_RANGE = 11 # for Random Graphs

fig = plt.figure(figsize=(8, 6.5))
ax = plt.subplot(1, 1, 1)
i = 0
for inference_scheme in AVG_TIMES_STEP:
    TEMPEST = list(OrderedDict(sorted(AVG_TIMES_STEP[inference_scheme].items())).values())
    print(TEMPEST)
    ax.plot(list(range(len(TEMPEST)))[:DEVICES_PLOT_MAX_RANGE], TEMPEST[:DEVICES_PLOT_MAX_RANGE], linewidth=3, color=PLOT_MAPPING[sequence_scheme][inference_scheme]["color"], label = PLOT_MAPPING[sequence_scheme][inference_scheme]["name"])
    i += 1

# ax.set_xlabel('Degree')
ax.set_xlabel("N-th iteration", alpha=0.5)
ax.set_ylabel('Runtime (ms)', alpha = 0.5)

# ax.set_xticks([0, 15, 30, 45, 60]) # For ft
ax.set_xticks([0, 2, 4, 6, 8, 10]) # For rg
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

plt.savefig("figures/step-time-" + TOPOLOGY_PREFIX + ".png")

# Plot 2 specific code ends

print("** Summary of results **")

THINGS_TO_PRINT = [AVG_TIMES_DEGREE, AVG_TIMES_STEP]
THINGS_TO_PRINT_TITLES = ["Avg times degree", "Avg times step"]
PRINTY = []

for index, THING_TO_PRINT in enumerate(THINGS_TO_PRINT):
    PRINTY = []
    for inference_scheme in THING_TO_PRINT:
        for topo_degree in THING_TO_PRINT[inference_scheme]:
            all_steps = THING_TO_PRINT[inference_scheme][topo_degree]
            stringy = str(topo_degree) + " " + inference_scheme + " " + str(all_steps)
            PRINTY.append(stringy)
    
    print("\n" + THINGS_TO_PRINT_TITLES[index])
    PRINTY.sort()
    for line in PRINTY:
        print(line)

# print("******\n NUM DEVICES IN LAST STEP")
# pprint(json.loads(json.dumps(LAST_DEVICES)))
# print("******\n AVG STEPS:")
# pprint(json.loads(json.dumps(AVG_STEPS)))
# print("******\n AVG LAST DEVICES:")
# pprint(json.loads(json.dumps(AVG_LAST_DEVICES)))


