#!/bin/bash
cd "$(dirname "$0")/.."
LOG=verify/out/overnight2.log
echo "시작 $(date)" > $LOG
run() { echo "=== $* ===" >> $LOG; python -X utf8 -m ai.bench_match "$@" --worlds 3 --rollouts 4 --workers 4 2>&1 | grep -v -i warn | tail -2 >> $LOG; }
run --a flat --b greedy --games 80
run --a nashv --b flat --games 80 --pick max
run --a nash --b flat --games 80 --pick max
echo "끝 $(date)" >> $LOG
echo ALL_DONE >> $LOG
