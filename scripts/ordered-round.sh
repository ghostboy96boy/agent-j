#!/usr/bin/env bash
# Run (or continue) a one-pass round in a fixed order read from bench/rounds/ROUND.order.
#
#   scripts/ordered-round.sh ROUND MODEL
#   scripts/ordered-round.sh phase0-pilot-gemini gemini/gemini-3.6-flash
#
# Each line of the order file is "DEFENSE SCENARIO"; '#' lines are comments. Runs already
# recorded for ROUND are skipped (--resume), so rerunning the same command after a daily
# quota stop continues at the first missing line. Stops at the first daily-quota message.
set -uo pipefail
cd "$(dirname "$0")/.."

[ $# -eq 2 ] || { sed -n '2,9p' "$0"; exit 2; }
ROUND=$1 MODEL=$2
ORDER="bench/rounds/${ROUND}.order"
[ -f "$ORDER" ] || { echo "no order file: $ORDER" >&2; exit 2; }
LOG="results/round-${ROUND}-$(date +%Y%m%d-%H%M%S).log"
echo "round $ROUND (order $ORDER), model $MODEL  (log: $LOG)"

while read -r defense scenario; do
  [ -n "$defense" ] || continue
  out=$(mktemp)
  python3 -m bench.run --round "$ROUND" --resume --repeat 1 --defense "$defense" \
    --models "$MODEL" --scenarios "$scenario" </dev/null 2>&1 | tee -a "$LOG" "$out"
  if grep -q "daily quota reached for" "$out"; then
    rm -f "$out"
    echo ">>> $MODEL: daily quota spent at $defense $scenario; continue tomorrow with the same command" | tee -a "$LOG"
    exit 0
  fi
  rm -f "$out"
done < <(grep -v '^\s*#' "$ORDER")
echo ">>> $MODEL: ordered round $ROUND finished (missing lines, if any, were invalid runs)" | tee -a "$LOG"
