#!/bin/bash
# 밤사이 실행: AI 대결 비교 (워커 4개로 제한)
cd "$(dirname "$0")/.."
LOG=verify/out/overnight1.log
echo "시작 $(date)" > $LOG
for cfg in "nashv greedy" "nashv flat" "nash flat"; do
  set -- $cfg
  echo "=== $1 vs $2 ===" >> $LOG
  python -X utf8 -m ai.bench_match --a $1 --b $2 --games 120 --worlds 3 --rollouts 4 --workers 4 2>&1 | grep -v -i warn | tail -3 >> $LOG
done
echo "끝 $(date)" >> $LOG
echo ALL_DONE >> $LOG
