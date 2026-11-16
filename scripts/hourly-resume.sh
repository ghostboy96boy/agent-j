#!/usr/bin/env bash
# Hourly resume of the phase 0 rounds still open (owner decision, 2026-11-12), until 2026-11-17 23:00 BRT.
#
#   scripts/hourly-resume.sh
#
# - Never touches the lab: if alice has no active channel it stops, notifies and exits 3.
# - Starts a chain only if it is not already running, and only with models whose daily quota
#   should be back (python3 -m bench.quota), so a spent quota does not add an invalid run per hour.
#     Groq:  scripts/round.sh phase0-r1 3 <ready Groq models>
#     Flash: scripts/ordered-round.sh phase0-pilot-gemini gemini/gemini-3.6-flash
# - Waits for the chains it started. If at least one run was recorded (valid, invalid or
#   model error), it updates results/STATUS.md (counts only), commits and pushes that file
#   alone, and shows a Windows notification with the counts and the next attempt. A pass
#   that ran nothing (quota not back) notifies nothing.
# - When every repetition of both Groq models is executed (valid, or closed after 3
#   model-error attempts) it also shows the completion notification and
#   prints GROQ COMPLETE (once; marker in results/private/).
set -uo pipefail
cd "$(dirname "$0")/.."

DEADLINE="2026-11-17 23:00 -0300"
MARKER=results/private/groq-complete
mkdir -p results/private

if [ "$(date +%s)" -gt "$(date -d "$DEADLINE" +%s)" ]; then
  echo "past $DEADLINE: no new runs (cutoff job closes the rounds)"; exit 0
fi

status=$(make -s status 2>&1)
if ! grep -q "active=True" <<<"$status" || grep -q "active=False" <<<"$status"; then
  echo "LAB PROBLEM: alice has an inactive or missing channel; nothing started, lab untouched"
  scripts/notify.sh "Agent J" "Problema no lab: canal inativo. Nada foi iniciado." || true
  exit 3
fi

total_runs() { python3 -c "from bench.status import counts; print(sum(counts().values()))"; }

push_status() {
  python3 -m bench.status --write > /dev/null
  git add results/STATUS.md
  if [ "$(git diff --cached --name-only)" = "results/STATUS.md" ]; then
    git commit -q -m "results/STATUS.md: $1 (run counts only)" && git push -q origin phase0-first-round
  elif [ -n "$(git diff --cached --name-only)" ]; then
    echo "not committing STATUS.md: other files are staged"; git reset -q results/STATUS.md
  fi
}

before=$(total_runs)

running() { ps -eo args | grep -qE "^bash scripts/$1"; }
pids=()

if running "round\.sh phase0-r1 "; then
  echo "groq: round already running, not starting another"
else
  ready=()
  for m in groq/openai/gpt-oss-120b groq/qwen/qwen3.8-27b; do
    python3 -m bench.quota "$m" && ready+=("$m")
  done
  if [ ${#ready[@]} -gt 0 ]; then
    bash scripts/round.sh phase0-r1 3 "${ready[@]}" > /dev/null 2>&1 &
    pids+=($!); echo "groq: started for ${ready[*]}"
  fi
fi

if running "ordered-round\.sh phase0-pilot-gemini "; then
  echo "flash pilot: already running, not starting another"
elif python3 -m bench.quota gemini/gemini-3.6-flash; then
  bash scripts/ordered-round.sh phase0-pilot-gemini gemini/gemini-3.6-flash > /dev/null 2>&1 &
  pids+=($!); echo "flash pilot: started"
fi

for p in "${pids[@]}"; do wait "$p"; done
python3 -m bench.status

after=$(total_runs)
if [ "$after" -gt "$before" ]; then
  push_status "update after an hourly pass"
  text=$(python3 - <<'EOF'
from bench.status import counts, valid_total
c = counts()
print(f"Groq: gpt-oss {valid_total(c, 'groq/openai/gpt-oss-120b')}/78, "
      f"qwen {valid_total(c, 'groq/qwen/qwen3.8-27b')}/78 · "
      f"Flash {valid_total(c, 'gemini/gemini-3.6-flash', 'phase0-pilot-gemini')}/26")
EOF
)
  scripts/notify.sh "Agent J" "$text · próxima tentativa $(date -d '+1 hour' +%H):23" || true
  echo "NOTIFIED: $text ($((after - before)) new run(s))"
fi

if [ ! -f "$MARKER" ] && python3 -m bench.status --groq-done > /dev/null; then
  push_status "Groq phase0-r1 complete"
  text=$(python3 -m bench.status --groq-done-text | tail -1)
  scripts/notify.sh "Agent J" "$text" || true
  touch "$MARKER"
  echo "GROQ COMPLETE: $text"
fi
