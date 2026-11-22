# Thesis experiment scripts

Copies of the scripts that produced the thesis numbers; each writes its outputs next to itself.

* `prec_recall/`: absolute precision/recall sweep, FIVES vs Operator (legacy and path-aware), 10
  topologies x 3 failure scenarios x 200 trials. `PY=<python> bash launch.sh FIVES,Operator shards logs`,
  then `python summarize.py --shard_dirs shards --out pr_summary.json`.
* `testbed_replay/`: the Arista testbed (k=4 fat tree) replayed in the simulator, FIVES vs path-aware
  Operator vs drain sweep, with a traffic-loss model. `python run_testbed.py <scenario> tb_<scenario>.json`
  for blackhole / silent_drop / high_latency, then `python summarize_testbed.py`.
