#!/usr/bin/env bash
# Full evaluation, one script after the other (total concurrency stays at --concurrency).
#   bash scripts/eval/run_all.sh baseline 3 400     # label, concurrency, budget USD
set -u
cd "$(dirname "$0")/../.."
LABEL=${1:-baseline}; CONC=${2:-3}; BUDGET=${3:-400}
PY=.venv/bin/python
ARGS="--label $LABEL --concurrency $CONC --budget-usd $BUDGET"
echo "=== $(date -u +%FT%TZ) benchmark"; $PY scripts/eval/benchmark.py --n 600 $ARGS
echo "=== $(date -u +%FT%TZ) judge benchmark"; $PY scripts/eval/judge.py --source benchmark $ARGS
echo "=== $(date -u +%FT%TZ) red team"; $PY scripts/eval/redteam.py --n 200 $ARGS
echo "=== $(date -u +%FT%TZ) compare presenters"; $PY scripts/eval/compare_presenters.py --n 100 $ARGS
echo "=== $(date -u +%FT%TZ) secret scan"
$PY -c "
import sys; sys.path.insert(0, 'scripts/eval'); import common as c
bad = c.scan([c.EVAL_ROOT, c.DOCS])
print('secret scan:', 'clean' if not bad else bad)"
echo "=== $(date -u +%FT%TZ) done"
