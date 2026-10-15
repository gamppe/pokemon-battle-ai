"""부트스트랩 라벨 데이터 생성: 휴리스틱 대전의 상태마다 '현재 가치망으로 한 턴 뒤를 평가한 내시 균형 값'을 라벨로 저장한다.
기존 라벨(휴리스틱 롤아웃 평균)은 휴리스틱 수준을 못 넘는다. 이 라벨은 가치망이 한 턴 탐색으로 개선된 값이라, 이걸로 다시 학습하면
가치망이 한 단계 더 앞을 내다보게 된다 (정책 평가 반복). 완전 정보(실제 상대 세트)로 푼다.
- 상태 하나에서 내시 값 v 를 한 번 풀면 양쪽 시점 라벨(v, 1-v) 두 개를 얻는다
- 최종 y = mix * 내시값 + (1-mix) * 실제 결과 (결과는 잡음이 크지만 편향이 없다)
사용: python -m ai.gen_bootstrap --ckpt data/value_v2/value_net.pt --games 24000 --workers 4 --out data/value_v3b"""
import argparse
import concurrent.futures as cf
import os
import random
import shutil

import numpy as np

from .features import Vocab, encode
from .gamedata import GameData, connect
from .meta import Meta
from .observe import ObsEngine
from .policy import greedy_action, make_switch_policy
from .search import candidate_actions, solve_zero_sum
from .search_value import ValueEvaluator, payoff_matrix_value
from .teams import MetaTeams, ReplayTeams

_G = {}


def _init(snap, ckpt):
    conn = connect()
    data = GameData(conn)
    meta = Meta(conn, data, snap)
    try:
        replay = ReplayTeams(conn, data, meta)
    except Exception:
        replay = None
    eng = ObsEngine(data)
    vocab_path = os.path.join(os.path.dirname(ckpt), "vocab.json")
    _G.update(data=data, eng=eng, meta_src=MetaTeams(meta), replay_src=replay, vocab=Vocab.load(vocab_path),
              ev=ValueEvaluator(eng, ckpt, vocab_path, device="cpu"))


def nash_value(eng, ev, st, rng, pol, samples):
    my_acts = candidate_actions(eng, st, 0, 2)
    opp_acts = candidate_actions(eng, st, 1, 2)
    M = payoff_matrix_value(eng, ev, st, 0, my_acts, opp_acts, samples, rng, pol)
    return solve_zero_sum(M)[1]


def play(args):
    gseed, samples, every, mix = args
    eng, vocab, ev = _G["eng"], _G["vocab"], _G["ev"]
    rng = random.Random(gseed)
    src = _G["replay_src"] if (_G["replay_src"] is not None and rng.random() < 0.5) else _G["meta_src"]
    st = eng.new_state(src.random_team(rng), src.random_team(rng), rng=rng)
    pol = make_switch_policy(eng, rng)
    eps = [rng.choice([0.05, 0.15, 0.3]), rng.choice([0.05, 0.15, 0.3])]
    states = []
    while st.winner is None and st.turn < 60:
        if st.turn % every == 0:
            v0 = nash_value(eng, ev, st, rng, pol, samples)
            for me in (0, 1):
                c, n, g = encode(eng, vocab, st, me)
                states.append((me, c, n, g, st.turn, v0 if me == 0 else 1.0 - v0))
        acts = [greedy_action(eng, st, i, rng, eps=eps[i]) for i in (0, 1)]
        eng.step(st, acts, rng, pol)
    w = st.winner
    out = ([], [], [], [], [], [])
    for me, c, n, g, t, vb in states:
        yo = 0.5 if w in (-1, None) else (1.0 if w == me else 0.0)
        for lst, val in zip(out, (c, n, g, mix * vb + (1 - mix) * yo, t, vb)):
            lst.append(val)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default="data/value_v2/value_net.pt")
    ap.add_argument("--games", type=int, default=24000)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--chunk", type=int, default=1000)
    ap.add_argument("--out", default="data/value_v3b")
    ap.add_argument("--snap", type=int, default=33)
    ap.add_argument("--seed0", type=int, default=900000)
    ap.add_argument("--samples", type=int, default=2, help="행동 쌍마다 한 턴을 진행하는 횟수 (우연 요소 평균)")
    ap.add_argument("--every", type=int, default=2)
    ap.add_argument("--mix", type=float, default=0.7, help="내시값 비중 (나머지는 실제 결과)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    vp = os.path.join(a.out, "vocab.json")
    if not os.path.exists(vp):
        shutil.copy(os.path.join(os.path.dirname(a.ckpt), "vocab.json"), vp)
    for start in range(0, a.games, a.chunk):
        path = os.path.join(a.out, f"chunk_{a.seed0 + start}.npz")
        if os.path.exists(path):
            continue
        seeds = [a.seed0 + start + k for k in range(min(a.chunk, a.games - start))]
        C, N, G, Y, T, B = [], [], [], [], [], []
        with cf.ProcessPoolExecutor(max_workers=a.workers, initializer=_init, initargs=(a.snap, a.ckpt)) as ex:
            for c, n, g, y, t, b in ex.map(play, [(sd, a.samples, a.every, a.mix) for sd in seeds], chunksize=4):
                C += c; N += n; G += g; Y += y; T += t; B += b
        np.savez_compressed(path, cat=np.array(C), num=np.array(N), glob=np.array(G), y=np.array(Y, dtype=np.float32),
                            turn=np.array(T, dtype=np.int16), boot=np.array(B, dtype=np.float32))
        print(f"저장 {path}: 상태 {len(Y)}개 (평균 y {np.mean(Y):.3f}, 평균 내시값 {np.mean(B):.3f})", flush=True)


if __name__ == "__main__":
    main()
