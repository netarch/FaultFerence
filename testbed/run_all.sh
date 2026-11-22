#!/usr/bin/env bash
# End-to-end FIVES Arista testbed pipeline:
#   1) Generate pruned k-ary FatTree topology JSON + alice/bob EOS configs + wiring.txt
#   2) Run all three fault scenarios (blackhole, silent_drop, high_latency) in replay or hardware mode
#   3) Summarize trials into tb_summary.json + tb_table.md (90% CIs)
#   4) Render publication vector PDFs + PNGs (testbed-steps, testbed-time, testbed-loss)
#
# Usage (from repo root or inside testbed/):
#   ./testbed/run_all.sh
#   ./testbed/run_all.sh --mode hardware --dry-run --reps 1
#   ./testbed/run_all.sh --mode hardware --reps 3 --outdir testbed/out_hw
set -euo pipefail

CALLER_PWD="$(pwd)"
TESTBED_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$TESTBED_DIR/.." && pwd)"

MODE="${MODE:-replay}"
DRY_RUN="${DRY_RUN:-0}"
K="${K:-8}"
PORTS_PER_SWITCH="${PORTS_PER_SWITCH:-48}"
REPS="${REPS:-3}"
FLOWS="${FLOWS:-400}"
WINDOW_S="${WINDOW_S:-10}"
OUTDIR="${OUTDIR:-$TESTBED_DIR/out}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --k) K="$2"; shift 2 ;;
    --ports-per-switch) PORTS_PER_SWITCH="$2"; shift 2 ;;
    --reps) REPS="$2"; shift 2 ;;
    --flows) FLOWS="$2"; shift 2 ;;
    --window-s) WINDOW_S="$2"; shift 2 ;;
    --outdir)
      if [[ "$2" = /* ]]; then
        OUTDIR="$2"
      else
        OUTDIR="$CALLER_PWD/$2"
      fi
      shift 2
      ;;
    -h|--help)
      sed -n '2,11p' "${BASH_SOURCE[0]}"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "${PYTHON:-}" ]]; then
  if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    PYTHON="$REPO_ROOT/.venv/bin/python"
  elif [[ -x "$HOME/miniconda3/bin/python" ]]; then
    PYTHON="$HOME/miniconda3/bin/python"
  else
    PYTHON="python3"
  fi
fi

TOPO_NAME="fattree_k${K}_pruned"
TOPO_JSON="$TESTBED_DIR/topologies/${TOPO_NAME}.json"
CFG_DIR="$TESTBED_DIR/configs/${TOPO_NAME}"
mkdir -p "$OUTDIR"

echo "[1/4] Generating ${TOPO_NAME} topology and EOS configs..."
"$PYTHON" "$TESTBED_DIR/make_pruned_clos.py" \
  --k "$K" \
  --ports-per-switch "$PORTS_PER_SWITCH" \
  --out "$TOPO_JSON" \
  --genconfig \
  --config-outdir "$CFG_DIR"

echo "[2/4] Running scenarios (mode=${MODE}, dry_run=${DRY_RUN}, k=${K}, reps=${REPS}, flows=${FLOWS})..."
if [[ "$MODE" == "replay" ]]; then
  pids=()
  for scen in blackhole silent_drop high_latency; do
    "$PYTHON" "$TESTBED_DIR/run_sweep.py" \
      --topology "$TOPO_JSON" \
      --mode replay \
      --scenario "$scen" \
      --reps "$REPS" \
      --flows "$FLOWS" \
      --outdir "$OUTDIR" \
      2>"$OUTDIR/log_${scen}.txt" &
    pids+=("$!")
  done
  for pid in "${pids[@]}"; do
    wait "$pid"
  done
elif [[ "$MODE" == "hardware" ]]; then
  hw_flags=()
  if [[ "$DRY_RUN" == "1" ]]; then
    hw_flags+=(--dry-run)
  fi
  "$PYTHON" "$TESTBED_DIR/run_sweep.py" \
    --topology "$TOPO_JSON" \
    --configs "$CFG_DIR" \
    --mode hardware \
    "${hw_flags[@]}" \
    --scenario all \
    --reps "$REPS" \
    --flows "$FLOWS" \
    --window-s "$WINDOW_S" \
    --outdir "$OUTDIR" \
    >"$OUTDIR/hardware_commands.log" 2>"$OUTDIR/log_hardware.txt"
else
  echo "Invalid --mode '$MODE' (expected replay or hardware)" >&2
  exit 2
fi

echo "[3/4] Summarizing trials -> $OUTDIR/{tb_summary.json,tb_table.md}"
"$PYTHON" "$TESTBED_DIR/summarize_testbed.py" --indir "$OUTDIR" --outdir "$OUTDIR"

echo "[4/4] Generating plots -> $OUTDIR/testbed-{steps,time,loss}.{pdf,png}"
"$PYTHON" "$TESTBED_DIR/plot_testbed.py" --summary "$OUTDIR/tb_summary.json" --outdir "$OUTDIR"
