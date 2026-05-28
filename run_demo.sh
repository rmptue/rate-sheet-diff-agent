#!/usr/bin/env bash
# Single-take demo: runs the full agent end-to-end in dry-run mode so the
# rendered email prints to stdout. No network email is sent.

set -euo pipefail
cd "$(dirname "$0")"

echo "==> Running rate-sheet diff agent (dry-run)"
python -m agent.orchestrator \
    --old data/Example_1.xlsx \
    --new data/Example_2.xlsx \
    --to "${RECIPIENT_EMAIL:-ops@example.com}" \
    --sender gmail-api
