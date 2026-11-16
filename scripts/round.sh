#!/usr/bin/env bash
# Run (or continue) a benchmark round for the models of one provider, in sequence.
#
#   scripts/round.sh ROUND REPEAT MODEL [MODEL ...]
#   scripts/round.sh phase0-r1 3 groq/openai/gpt-oss-120b groq/qwen/qwen3.8-27b
#
# Every scenario runs under both prompt defenses (none, prompt). The round advances in
# passes (repeat 1 of both defenses, then repeat 2, ...) so a daily quota that ends the
# day midway leaves the two defenses with about the same number of runs. A model whose
# daily quota is spent is skipped until the next call; rerunning the same command the
# next day continues where it stopped (--resume counts only runs tagged with ROUND).
set -uo pipefail
cd "$(dirname "$0")/.."

[ $# -ge 3 ] || { sed -n '2,10p' "$0"; exit 2; }
ROUND=$1 REPEAT=$2
shift 2
LOG="results/round-${ROUND}-$(date +%Y%m%d-%H%M%S).log"
echo "round $ROUND, repeat $REPEAT, models: $*  (log: $LOG)"

for model in "$@"; do
  for pass in $(seq 1 "$REPEAT"); do
    for defense in none prompt; do
      out=$(mktemp)
      python3 -m bench.run --round "$ROUND" --resume --repeat "$pass" --defense "$defense" \
        --models "$model" 2>&1 | tee -a "$LOG" "$out"
      if grep -q "daily quota reached for" "$out"; then
        rm -f "$out"
        echo ">>> $model: daily quota spent; continue tomorrow with the same command" | tee -a "$LOG"
        continue 3
      fi
      rm -f "$out"
    done
  done
  echo ">>> $model: round $ROUND complete at repeat $REPEAT" | tee -a "$LOG"
done
