#!/usr/bin/env bash
# Run (or continue) a round in a fixed order read from bench/rounds/ROUND.order.
#
#   scripts/ordered-round.sh ROUND MODEL [ORDER_FILE]   (default bench/rounds/ROUND.order)
#   scripts/ordered-round.sh phase0-pilot-gemini gemini/gemini-3.6-flash
#   scripts/ordered-round.sh phase0-r1 gemini/gemma-4-31b-it bench/rounds/phase0-r1-gemma.order
#
# Each line of the order file is "DEFENSE SCENARIO"; '#' lines are comments. The k-th
# appearance of a line asks for k runs of that cell (--repeat k). Runs already
# recorded for ROUND are skipped (--resume), so rerunning the same command after a daily
# quota stop continues at the first missing line. Stops at the first daily-quota message.
set -uo pipefail
cd "$(dirname "$0")/.."

[ $# -eq 2 ] || [ $# -eq 3 ] || { sed -n "2,11p" "$0"; exit 2; }
ROUND=$1 MODEL=$2
ORDER=${3:-"bench/rounds/${ROUND}.order"}
[ -f "$ORDER" ] || { echo "no order file: $ORDER" >&2; exit 2; }
LOG="results/round-${ROUND}-${MODEL//\//_}-$(date +%Y%m%d-%H%M%S).log"
echo "round $ROUND (order $ORDER), model $MODEL  (log: $LOG)"

declare -A seen
while read -r defense scenario; do
  [ -n "$defense" ] || continue
  key="$defense $scenario"
  seen[$key]=$(( ${seen[$key]:-0} + 1 ))
  out=$(mktemp)
  python3 -m bench.run --round "$ROUND" --resume --repeat "${seen[$key]}" --defense "$defense" \
    --models "$MODEL" --scenarios "$scenario" </dev/null 2>&1 | tee -a "$LOG" "$out"
  if grep -q "daily quota reached for" "$out"; then
    rm -f "$out"
    echo ">>> $MODEL: daily quota spent at $defense $scenario #${seen[$key]}; continue tomorrow with the same command" | tee -a "$LOG"
    exit 0
  fi
  rm -f "$out"
done < <(grep -v '^\s*#' "$ORDER")
echo ">>> $MODEL: ordered round $ROUND finished (missing lines, if any, were invalid runs)" | tee -a "$LOG"
