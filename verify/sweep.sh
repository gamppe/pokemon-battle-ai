#!/bin/bash
# 여러 시드로 연속 실행하고 불일치 파일을 verify/out/sweep/ 에 보관 (사용: bash verify/sweep.sh "1턴 시드들" "2턴 시드들")
cd "$(dirname "$0")/.."
for sd in $1; do
  python -X utf8 verify/verify_turns.py --n 1500 --runs 100 --seed $sd --snap ${SNAP:-32} 2>&1 | head -1
  cp verify/out/turns_mismatch.json verify/out/sweep/t1_$sd.json; cp verify/out/turns_in.json verify/out/sweep/t1_${sd}_in.json
done
for sd in $2; do
  python -X utf8 verify/verify_turns.py --n 1000 --runs 100 --turns 2 --seed $sd --snap ${SNAP:-32} 2>&1 | head -1
  cp verify/out/turns_mismatch.json verify/out/sweep/t2_$sd.json; cp verify/out/turns_in.json verify/out/sweep/t2_${sd}_in.json
done
echo SWEEP_DONE
