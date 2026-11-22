# Thesis experiment scripts

Copies of the scripts that produced the thesis numbers; each writes its outputs next to itself.

* `prec_recall/`: absolute precision/recall sweep, FIVES vs Operator (legacy and path-aware), 10
  topologies x 3 failure scenarios x 200 trials. `PY=<python> bash launch.sh FIVES,Operator shards logs`,
  then `python summarize.py --shard_dirs shards --out pr_summary.json`.
* `testbed_replay/`: the Arista testbed (pruned k=8 fat tree, 26 VRFs, 40 links, 16 ECMP paths)
  replayed in the simulator, FIVES vs path-aware Operator vs drain sweep, with a traffic-loss model.
  Run everything end-to-end (topology/config generation + replay + summary + plots) with
  `./testbed/run_all.sh` (or `./testbed/run_all.sh --mode hardware [--dry-run]` for live/dry-run
  switch execution); individual scenario wrappers `python run_testbed.py <scenario> tb_<scenario>.json`
  and `python summarize_testbed.py` also remain here.
