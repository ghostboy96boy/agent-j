#!/usr/bin/env bash
# Daily unattended benchmark round (called by Windows Task Scheduler through wsl.exe).
#
# Tops every cell up to REPEAT valid runs for each model, in parallel (each model
# has its own free-tier quota), stops a model when its daily quota is spent, and
# writes a summary to results/daily-<date>.md. Safe to run when the round is
# already complete: it then does nothing but write the summary.
#
# Usage: scripts/daily-bench.sh            (defaults below)
#        REPEAT=10 MODELS="groq/qwen/qwen3.8-27b" scripts/daily-bench.sh
set -uo pipefail

cd "$(dirname "$0")/.."
REPEAT="${REPEAT:-5}"
MODELS="${MODELS:-groq/openai/gpt-oss-120b groq/qwen/qwen3.8-27b gemini/gemini-3.8-flash}"
DAY="$(date +%Y%m%d)"
LOG="results/daily-$DAY.log"
mkdir -p results
exec >>"$LOG" 2>&1
echo "=== $(date -Is) daily bench start (repeat=$REPEAT)"

if pgrep -f "bench.run" >/dev/null; then
  echo "another bench is already running; exiting"
  exit 0
fi

git pull --ff-only -q || echo "warning: git pull failed, using local code"

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: docker is not reachable from WSL; start Docker and rerun"
  exit 1
fi
docker compose --env-file .env up -d >/dev/null 2>&1
sleep 20  # let LND reconnect to peers after a cold start
if ! docker compose exec -T alice lncli --network=regtest listchannels 2>/dev/null | grep -q '"active": true'; then
  echo "ERROR: alice has no active channel; run 'make status' and check the lab"
  exit 1
fi

python3 -m unittest discover -s tests >/dev/null 2>&1 || { echo "ERROR: offline tests fail; not running"; exit 1; }

for m in $MODELS; do
  python3 -u -m bench.run --resume --repeat "$REPEAT" --models "$m" \
    >"results/bench-$(basename "$m")-$DAY.log" 2>&1 &
  echo "started $m (pid $!)"
done
wait
echo "=== $(date -Is) all models finished"
for m in $MODELS; do tail -3 "results/bench-$(basename "$m")-$DAY.log"; done

python3 -m bench.report > "results/daily-$DAY.md" 2>&1
echo "summary: results/daily-$DAY.md"
