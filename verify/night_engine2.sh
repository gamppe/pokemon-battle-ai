#!/bin/sh
# 야간 엔진 스윕: 시드를 바꿔 가며 반복. 불일치가 나오면 verify/out/night_eng2_mismatch_<시각>.json 으로 보관.
export PYTHONIOENCODING=utf-8
cd "$(dirname "$0")/.."
L=verify/out/night_engine2.log
for N in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18; do
  S=$((600 + N * 7))
  echo "[$(date +%H:%M:%S)] cycle $N seed $S" >> $L
  python -m verify.verify_turns --n 1500 --runs 120 --turns 1 --seed $S --workers 3 2>&1 | head -1 >> $L
  [ -f verify/out/turns_mismatch.json ] && cp verify/out/turns_mismatch.json verify/out/night_eng2_mismatch_${N}_a.json
  python -m verify.verify_turns --n 1000 --runs 120 --turns 4 --seed $S --switch 0.3 --workers 3 2>&1 | head -1 >> $L
  cp verify/out/turns_mismatch.json verify/out/night_eng2_mismatch_${N}_b.json 2>/dev/null
  python verify/focus_cases.py all 600 100 4 $S 2>&1 | grep "^\[" >> $L
  cp verify/out/focus_mismatch_all.json verify/out/night_eng2_mismatch_${N}_c.json 2>/dev/null
  python -m verify.trace_cmp --n 400 --runs 100 --turns 2 --switch 0.25 --seed $S --show 0 --workers 3 2>&1 | head -1 >> $L
done
echo "[$(date +%H:%M:%S)] ENGINE_DONE" >> $L
