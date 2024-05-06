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
ITERATIONS = 200
MAX_NUM_STEPS = 250 # This is useful while calculating the average equivalent device size per step
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

PLOT_MAPPING = {
    "Intelligent": {
        "Flock": {
            "name": "FaultFerence (Bayesian)",
            "color": "#f1a200",
            "marker": "o",
            "markersize": 11
        },
        "Naive": {
            "name": "FaultFerence (Basic)",
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

ALL_STEPS = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
AVG_STEPS = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
CONFIDENCE_INTERVAL = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
ALL_DEVICE_SIZES = defaultdict(lambda: defaultdict(list))
AVG_DEVICE_SIZES = defaultdict(lambda: defaultdict(int))
LAST_DEVICES = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
AVG_LAST_DEVICES = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

PRECISION = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
AVG_PRECISION = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

RECALL = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
AVG_RECALL = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))


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
                if inference_scheme == "Naive_old":
                    continue
                
                if inference_scheme == "Flock" and sequence_scheme == "Random":
                    continue
                inference_path = os.path.join(sequence_path, inference_scheme)

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
                all_devices_sizes = [int(stringy.split(", Devices:")[0].split("Size: ")[1]) for stringy in open(os.path.join(inference_path, "equivalent_devices")).readlines()[:-2]]
                last_devices = all_devices_sizes[-1]
                all_devices_sizes = all_devices_sizes + [last_devices for x in range(MAX_NUM_STEPS - len(all_devices_sizes))]

                last_devices_list = open(os.path.join(inference_path, "equivalent_devices")).readlines()[-2].split(", Devices: [")[1].split("]")[0].split(", ")
                failed_device = int(open(os.path.join(iter_path, "initial.fails")).read().split(" ")[3])
                
                if num_steps == 0 and not last_devices_list == [""] and last_devices == int(last_devices_list[0]):
                    continue

                if last_devices_list == [""]:
                    # HACK - Naive_Old had this bug where it reduced equivalent class to 0 because of an incorrect algorithm
                    if inference_scheme == "Naive_old":
                        last_devices = 2
                        PRECISION[sequence_scheme][inference_scheme][topo_degree].append(0.5)
                        RECALL[sequence_scheme][inference_scheme][topo_degree].append(1)
                    else:
                        print("WARNING:", topo_degree, iter_string, inference_scheme, sequence_scheme, "- number of equivalent devices reduced to 0. How?")
                        PRECISION[sequence_scheme][inference_scheme][topo_degree].append(0)
                        RECALL[sequence_scheme][inference_scheme][topo_degree].append(0)
                else:
                    last_devices_list = [int(x) for x in last_devices_list]
                    if failed_device in last_devices_list:
                        PRECISION[sequence_scheme][inference_scheme][topo_degree].append(1/len(last_devices_list))
                        RECALL[sequence_scheme][inference_scheme][topo_degree].append(1)
                    else:
                        PRECISION[sequence_scheme][inference_scheme][topo_degree].append(0)
                        RECALL[sequence_scheme][inference_scheme][topo_degree].append(0)

                ALL_STEPS[sequence_scheme][inference_scheme][topo_degree].append(num_steps + (last_devices//2))
                LAST_DEVICES[sequence_scheme][inference_scheme][topo_degree].append(last_devices)
                if topo_degree == 20:
                    ALL_DEVICE_SIZES[sequence_scheme][inference_scheme].append(all_devices_sizes)

for sequence_scheme in ALL_STEPS:
    for inference_scheme in ALL_STEPS[sequence_scheme]:
        ALL_DEVICES_TEMP = ALL_DEVICE_SIZES[sequence_scheme][inference_scheme]
        AVG_DEVICE_SIZES[sequence_scheme][inference_scheme] = [np.mean([ALL_DEVICES_TEMP[y][x] for y in range(len(ALL_DEVICES_TEMP))]) for x in range(MAX_NUM_STEPS)]

        for topo_degree in ALL_STEPS[sequence_scheme][inference_scheme]:
            all_steps = ALL_STEPS[sequence_scheme][inference_scheme][topo_degree]
            AVG_STEPS[sequence_scheme][inference_scheme][topo_degree] = np.mean(all_steps)
            CONFIDENCE_INTERVAL[sequence_scheme][inference_scheme][topo_degree] = st.norm.interval(confidence=0.90, loc=np.mean(all_steps), scale=st.sem(all_steps))
            
            AVG_LAST_DEVICES[sequence_scheme][inference_scheme][topo_degree] = np.mean(LAST_DEVICES[sequence_scheme][inference_scheme][topo_degree])
            AVG_PRECISION[sequence_scheme][inference_scheme][topo_degree] = np.mean(PRECISION[sequence_scheme][inference_scheme][topo_degree])
            AVG_RECALL[sequence_scheme][inference_scheme][topo_degree] = np.mean(RECALL[sequence_scheme][inference_scheme][topo_degree])


fm.fontManager.addfont("./gillsans.ttf")
matplotlib.rcParams.update({'font.size': 24, 'font.family': "GillSans"})

# Plot 1 specific code starts
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

        ################ If we only want to plot Operator and FaultFerence #############
        # if inference_scheme == "Flock" and sequence_scheme == "Random":
        #     continue
        # if inference_scheme == "Naive" and sequence_scheme == "Intelligent":
        #     continue
        line_config = PLOT_MAPPING[sequence_scheme][inference_scheme]
        ax.errorbar([DEGREE_HOST_MAPPING[x] for x in dicty.keys()], dicty.values(), confidence_dicty.transpose(), color=line_config["color"], marker=line_config["marker"], markersize=line_config["markersize"], label = line_config["name"], capsize = 3, linewidth=3, elinewidth=0.9)
        i +=1

# ax.set_xlabel('Degree')
ax.set_xlabel("Topology size (# hosts)")
ax.set_ylabel('# Manual micro-actions')

PLOT_RANGES = {
    "ft": {
        "xticks_sw": [100, 200, 300, 400, 500, 600],
        "xticks_deg": [10, 12, 14, 16, 18, 29],
        "xticks_hosts": [0, 1500, 3000, 4500, 6000],

        "yticks": [0, 10, 20, 30, 40]
    },
    "rg": {
        "xticks_sw": [100, 200, 300, 400, 500, 600],
        "xticks_deg": [10, 12, 14, 16, 18, 29],
        "xticks_hosts": [0, 1500, 3000, 4500, 6000],

        "yticks": [0, 1, 2, 3, 4]
    }
}

ax.set_xticks(PLOT_RANGES[TOPOLOGY_PREFIX]["xticks_hosts"])
# ax.set_xlim(PLOT_RANGES[TOPOLOGY_PREFIX]["xticks_hosts"][0], PLOT_RANGES[TOPOLOGY_PREFIX]["xticks_hosts"][-1])

ax.set_yticks(PLOT_RANGES[TOPOLOGY_PREFIX]["yticks"])
# ax.set_ylim(PLOT_RANGES[TOPOLOGY_PREFIX]["yticks"][0], PLOT_RANGES[TOPOLOGY_PREFIX]["yticks"][-1])


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

# get handles
handles, labels = ax.get_legend_handles_labels()
handles = [h[0] for h in handles]
legend = ax.legend(handles, labels, numpoints=1, fontsize="22", markerscale=0.7, handlelength=0.7, handletextpad=0.4, framealpha=0.3)

# legend = plt.legend(fontsize="22", markerscale=0.7, handlelength=0.7, handletextpad=0.4, framealpha=0.3)

plt.savefig("figures/steps-" + TOPOLOGY_PREFIX + ".pdf")
plt.savefig("figures/steps-" + TOPOLOGY_PREFIX + ".png")

# Plot 1 specific code ends


# Plot 2 specific code starts
# DEVICES_PLOT_MAX_RANGE = 61 # for ft
DEVICES_PLOT_MAX_RANGE = 11 # for Random Graphs

fig = plt.figure(figsize=(8, 6.5))
ax = plt.subplot(1, 1, 1)
i = 0
for sequence_scheme in AVG_DEVICE_SIZES:
    for inference_scheme in AVG_DEVICE_SIZES[sequence_scheme]:
        ax.plot(list(range(DEVICES_PLOT_MAX_RANGE)), AVG_DEVICE_SIZES[sequence_scheme][inference_scheme][:DEVICES_PLOT_MAX_RANGE], linewidth=3, color=PLOT_MAPPING[sequence_scheme][inference_scheme]["color"], label = PLOT_MAPPING[sequence_scheme][inference_scheme]["name"])
        i += 1

# ax.set_xlabel('Degree')
ax.set_xlabel("Iteration #")
ax.set_ylabel('# Equivalent devices')

PLOT_RANGES_2 = {
    "ft": {
        "xticks": [0, 2, 4, 6, 8, 10],
        "yticks": [0, 30, 60, 90, 120]
    },
    "rg": {
        "xticks": [0, 2, 4, 6, 8, 10],
        "yticks": [0, 2, 4, 6, 8, 10]
    }
}

ax.set_xticks(PLOT_RANGES_2[TOPOLOGY_PREFIX]["xticks"])
# ax.set_xlim(PLOT_RANGES_2[TOPOLOGY_PREFIX]["xticks"][0], PLOT_RANGES_2[TOPOLOGY_PREFIX]["xticks"][-1])

ax.set_yticks(PLOT_RANGES_2[TOPOLOGY_PREFIX]["yticks"]) # Number of hosts
# ax.set_ylim(PLOT_RANGES_2[TOPOLOGY_PREFIX]["yticks"][0], PLOT_RANGES_2[TOPOLOGY_PREFIX]["yticks"][-1])


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

plt.savefig("figures/devices-" + TOPOLOGY_PREFIX + ".pdf")
plt.savefig("figures/devices-" + TOPOLOGY_PREFIX + ".png")

# Plot 2 specific code ends

print("** Summary of results **")

THINGS_TO_PRINT = [AVG_PRECISION, AVG_RECALL]
THINGS_TO_PRINT_TITLES = ["Average precision", "Average recall"]
PRINTY = []

for index, THING_TO_PRINT in enumerate(THINGS_TO_PRINT):
    PRINTY = []
    for sequence_scheme in THING_TO_PRINT:
        for inference_scheme in THING_TO_PRINT[sequence_scheme]:
            for topo_degree in THING_TO_PRINT[sequence_scheme][inference_scheme]:
                all_steps = THING_TO_PRINT[sequence_scheme][inference_scheme][topo_degree]
                stringy = str(topo_degree) + " " + sequence_scheme + " " + inference_scheme + " " + str(all_steps)
                PRINTY.append(stringy)
    
    print(THINGS_TO_PRINT_TITLES[index])
    PRINTY.sort()
    for line in PRINTY:
        print(line)

# print("******\n NUM DEVICES IN LAST STEP")
# pprint(json.loads(json.dumps(LAST_DEVICES)))
# print("******\n AVG STEPS:")
# pprint(json.loads(json.dumps(AVG_STEPS)))
# print("******\n AVG LAST DEVICES:")
# pprint(json.loads(json.dumps(AVG_LAST_DEVICES)))


