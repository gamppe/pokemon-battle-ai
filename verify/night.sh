#!/bin/sh
# 야간 작업: 부트스트랩 가치망 개선 -> 평가 -> (2차) -> 정보 가치 실험.  로그: verify/out/night_*.log
export PYTHONIOENCODING=utf-8
cd "$(dirname "$0")/.."
L=verify/out
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a $L/night_main.log; }
winrate() { grep -o "승률 [0-9.]*%" "$1" | tail -1 | grep -o "[0-9.]*"; }
EV="--worlds 3 --rollouts 4 --pick max --workers 4"

log "== 1) v3b 부트스트랩 데이터 생성 (v2 가치망, 24000판)"
python -m ai.gen_bootstrap --ckpt data/value_v2/value_net.pt --games 24000 --workers 4 --chunk 1000 --out data/value_v3b --seed0 900000 > $L/night_gen_v3b.log 2>&1
log "== 2) v3b 학습"
python -m ai.train_value --data data/value_v3b --epochs 14 --out data/value_v3b/value_net.pt > $L/night_train_v3b.log 2>&1
tail -3 $L/night_train_v3b.log | tee -a $L/night_main.log

log "== 3) 평가: nashv(v3b) vs flat (200판x2)"
python -m ai.bench_match --a nashv --b flat --games 200 $EV --ckpt data/value_v3b/value_net.pt > $L/night_eval_v3b_flat.log 2>&1
tail -1 $L/night_eval_v3b_flat.log | tee -a $L/night_main.log
log "== 4) 평가: nashv(v3b) vs nashv(v2) (200판x2)"
python -m ai.bench_match --a nashv --b nashv2 --games 200 $EV --ckpt data/value_v3b/value_net.pt --ckpt2 data/value_v2/value_net.pt > $L/night_eval_v3b_v2.log 2>&1
tail -1 $L/night_eval_v3b_v2.log | tee -a $L/night_main.log

W=$(winrate $L/night_eval_v3b_v2.log)
BEST=data/value_v2/value_net.pt
if [ -n "$W" ] && [ "$(python -c "print(1 if float('$W')>=50.0 else 0)")" = "1" ]; then BEST=data/value_v3b/value_net.pt; fi
log "== 최고 모델(1차): $BEST (v3b vs v2 승률 ${W:-?}%)"

if [ "$BEST" = "data/value_v3b/value_net.pt" ]; then
  log "== 5) v3c 부트스트랩 (v3b 가치망)"
  python -m ai.gen_bootstrap --ckpt data/value_v3b/value_net.pt --games 24000 --workers 4 --chunk 1000 --out data/value_v3c --seed0 950000 > $L/night_gen_v3c.log 2>&1
  python -m ai.train_value --data data/value_v3c --epochs 14 --out data/value_v3c/value_net.pt > $L/night_train_v3c.log 2>&1
  tail -3 $L/night_train_v3c.log | tee -a $L/night_main.log
  log "== 6) 평가: nashv(v3c) vs nashv(v3b)"
  python -m ai.bench_match --a nashv --b nashv2 --games 200 $EV --ckpt data/value_v3c/value_net.pt --ckpt2 data/value_v3b/value_net.pt > $L/night_eval_v3c_v3b.log 2>&1
  tail -1 $L/night_eval_v3c_v3b.log | tee -a $L/night_main.log
  W2=$(winrate $L/night_eval_v3c_v3b.log)
  if [ -n "$W2" ] && [ "$(python -c "print(1 if float('$W2')>=50.0 else 0)")" = "1" ]; then BEST=data/value_v3c/value_net.pt; fi
  log "== 최고 모델(2차): $BEST (v3c vs v3b ${W2:-?}%)"
fi

log "== 7) 정보 가치 실험 (최고 모델: $BEST)"
for I in post prior oracle know_item know_moves know_spread know_ability; do
  python -m ai.bench_match --a nashv --b nashv2 --games 80 $EV --ckpt $BEST --ckpt2 $BEST --info $I > $L/night_info_$I.log 2>&1
  log "info=$I: $(tail -1 $L/night_info_$I.log)"
done
echo "$BEST" > $L/night_best.txt
log "== 완료 ALL_DONE"
