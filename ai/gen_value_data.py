"""평가함수 학습 데이터 생성: 휴리스틱 정책끼리(탐색 노이즈 포함) 싸우게 하고, 매 턴 시작 상태와 최종 승패를 기록한다.
- 같은 상태를 양쪽 시점으로 모두 저장 (라벨은 시점에 맞춰 뒤집음)
- 팀은 메타/리플레이 출처를 섞고, 정책의 무작위성(eps)을 판마다 다르게 해 다양한 국면을 만든다
- CPU 온도를 위해 워커 수를 줄여 쓴다 (기본 6). 청크마다 npz 로 저장해 중간에 멈춰도 이어진다.
사용: python -m ai.gen_value_data --games 20000 --workers 6 --out data/value"""
import argparse
import concurrent.futures as cf
import os
import random

import numpy as np

from .features import Vocab, encode
from .gamedata import GameData, connect
from .meta import Meta
from .observe import ObsEngine
from .policy import greedy_action, make_switch_policy
from .teams import MetaTeams, ReplayTeams

_G = {}


def _init(snap, vocab_path):
    conn = connect()
    data = GameData(conn)
    meta = Meta(conn, data, snap)
    try:
        replay = ReplayTeams(conn, data, meta)
    except Exception:
        replay = None
    _G.update(data=data, eng=ObsEngine(data), meta_src=MetaTeams(meta), replay_src=replay, vocab=Vocab.load(vocab_path))


def play(args):
    gseed = args
    eng, vocab = _G["eng"], _G["vocab"]
    rng = random.Random(gseed)
    src = _G["replay_src"] if (_G["replay_src"] is not None and rng.random() < 0.5) else _G["meta_src"]
    st = eng.new_state(src.random_team(rng), src.random_team(rng), rng=rng)
    pol = make_switch_policy(eng, rng)
    eps = [rng.choice([0.05, 0.15, 0.3]), rng.choice([0.05, 0.15, 0.3])]
    states = []
    while st.winner is None and st.turn < 60:
        for me in (0, 1):
            c, n, g = encode(eng, vocab, st, me)
            states.append((me, c, n, g, st.turn))
        acts = [greedy_action(eng, st, i, rng, eps=eps[i]) for i in (0, 1)]
        eng.step(st, acts, rng, pol)
    w = st.winner
    out_c, out_n, out_g, out_y, out_t = [], [], [], [], []
    for me, c, n, g, t in states:
        y = 0.5 if w in (-1, None) else (1.0 if w == me else 0.0)
        out_c.append(c); out_n.append(n); out_g.append(g); out_y.append(y); out_t.append(t)
    return out_c, out_n, out_g, out_y, out_t, gseed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=20000)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--chunk", type=int, default=2000, help="이만큼의 판마다 파일로 저장")
    ap.add_argument("--out", default="data/value")
    ap.add_argument("--snap", type=int, default=33)
    ap.add_argument("--seed0", type=int, default=100000)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    vocab_path = os.path.join(a.out, "vocab.json")
    if not os.path.exists(vocab_path):
        conn = connect()
        Vocab.build(GameData(conn), conn).save(vocab_path)
    for start in range(0, a.games, a.chunk):
        path = os.path.join(a.out, f"chunk_{a.seed0 + start}.npz")
        if os.path.exists(path):
            continue
        seeds = [a.seed0 + start + k for k in range(min(a.chunk, a.games - start))]
        C, N, G, Y, T = [], [], [], [], []
        with cf.ProcessPoolExecutor(max_workers=a.workers, initializer=_init, initargs=(a.snap, vocab_path)) as ex:
            for c, n, g, y, t, _ in ex.map(play, seeds, chunksize=8):
                C += c; N += n; G += g; Y += y; T += t
        np.savez_compressed(path, cat=np.array(C), num=np.array(N), glob=np.array(G), y=np.array(Y, dtype=np.float32), turn=np.array(T, dtype=np.int16))
        print(f"저장 {path}: 상태 {len(Y)}개 (평균 승률 {np.mean(Y):.3f})", flush=True)


if __name__ == "__main__":
    main()
