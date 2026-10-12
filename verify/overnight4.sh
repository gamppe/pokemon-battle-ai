#!/bin/bash
# 가치망 확장: 데이터 추가 생성 -> 재학습 -> 대결 확인 (워커 4개)
cd "$(dirname "$0")/.."
LOG=verify/out/overnight4.log
echo "시작 $(date)" > $LOG
echo "== 데이터 추가 생성 (16000판, 롤아웃 라벨) ==" >> $LOG
python -X utf8 -m ai.gen_value_data --games 16000 --workers 4 --chunk 1000 --rollouts 6 --every 2 --seed0 500000 --out data/value_v2 2>&1 | tail -3 >> $LOG
echo "== 재학습 ==" >> $LOG
python -X utf8 -m ai.train_value --data data/value_v2 --epochs 14 --out data/value_v2/value_net_v3.pt 2>&1 | grep -v -i warn | tail -6 >> $LOG
echo "== 대결: nashv(v3) vs flat ==" >> $LOG
python -X utf8 -m ai.bench_match --a nashv --b flat --games 200 --pick max --worlds 3 --rollouts 4 --workers 4 --ckpt data/value_v2/value_net_v3.pt 2>&1 | grep -v -i warn | tail -2 >> $LOG
echo "끝 $(date)" >> $LOG
echo ALL_DONE >> $LOG
