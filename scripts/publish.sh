#!/usr/bin/env bash
# One-time: creates the public GitHub repo ghostboy96boy/agent-j and pushes this folder.
# Requires the GitHub CLI logged in (`gh auth login`).
set -euo pipefail
cd "$(dirname "$0")/.."

REPO="ghostboy96boy/agent-j"

if ! command -v gh >/dev/null; then
  echo "Install the GitHub CLI first: https://cli.github.com" >&2; exit 1
fi
gh auth status >/dev/null || { echo "Run: gh auth login" >&2; exit 1; }

if [[ ! -d .git ]]; then
  git init -b main
fi
git add .
git commit -m "Agent J: regtest lab, docs and project plan" || true

if gh repo view "$REPO" >/dev/null 2>&1; then
  git remote get-url origin >/dev/null 2>&1 || git remote add origin "https://github.com/$REPO.git"
  git push -u origin main
else
  gh repo create "$REPO" --public \
    --description "Open security benchmark and guardrails for AI agents that hold Lightning wallets" \
    --source . --remote origin --push
fi
gh repo edit "$REPO" --add-topic bitcoin,lightning,ai-agents,security,benchmark,prompt-injection
echo "Done: https://github.com/$REPO"
