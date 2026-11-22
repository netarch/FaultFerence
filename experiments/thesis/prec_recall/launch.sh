#!/bin/bash
# Launch all shards: 10 topologies x 3 scenarios x 10 shards x 20 trials = 200 trials/config.
# Usage: launch.sh <schemes> <outdir> <logdir>
#   original sweep:   launch.sh FIVES,Operator shards logs
#   path-aware rerun: launch.sh Operator-PA shards_pa logs_pa
set -euo pipefail
SCHEMES=$1
OUTDIR=$2
LOGDIR=$3
D=$(cd "$(dirname "$0")" && pwd)
PY=${PY:?set PY to a python with numpy/scipy/networkx}
SHARDS=10
TPS=20
mkdir -p "$D/$OUTDIR" "$D/$LOGDIR"
cd "$D"
date +%s > "$D/$LOGDIR/start_epoch"
for t in Clos-K20 Kdl Clos-K14 ASN2k UsCarrier Clos-K10 RRG-K10 RRG-K14 RRG-K20 B4; do
  for s in blackhole silent_drop high_latency; do
    for k in $(seq 0 $((SHARDS - 1))); do
      echo "$t $s $k"
    done
  done
done | xargs -P 120 -L 1 bash -c "$PY $D/run_pr.py \$0 \$1 \$2 $TPS $D/$OUTDIR/shard_\$0_\$1_\$2.json $SCHEMES > $D/$LOGDIR/log_\$0_\$1_\$2.txt 2>&1"
date +%s > "$D/$LOGDIR/end_epoch"
