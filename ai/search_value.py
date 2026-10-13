"""가치망을 쓴 1턴 탐색 (롤아웃 대체).
수익 행렬의 각 칸 = 그 행동 쌍으로 한 턴을 몇 번 진행한 뒤 가치망이 평가한 승률 평균.
끝까지 굴리는 롤아웃이 없어서 훨씬 빠르고, 평가함수가 좋아질수록 정확해진다.
(상태 평가는 한 번에 모아서 배치로 처리한다)"""
import random

import numpy as np
import torch

from .decide import resample_opponent
from .features import Vocab, encode
from .gamedata import norm
from .search import candidate_actions, pick, solve_zero_sum
from .value_net import ValueNet


class ValueEvaluator:
    def __init__(self, eng, ckpt_path, vocab_path, device=None):
        self.eng = eng
        self.dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
        ck = torch.load(ckpt_path, map_location=self.dev)
        self.vocab = Vocab.load(vocab_path)
        self.net = ValueNet(ck["vocab_sizes"], ck["n_num"], ck["n_glob"]).to(self.dev)
        self.net.load_state_dict(ck["state"])
        self.net.eval()

    def values(self, states, me):
        """상태 리스트 -> 내(me) 승률 배열. 이미 끝난 판은 1/0.5/0 으로 처리"""
        out = np.zeros(len(states))
        pending, ids = [], []
        for k, s in enumerate(states):
            if s.winner is not None:
                out[k] = 1.0 if s.winner == me else (0.5 if s.winner == -1 else 0.0)
            else:
                pending.append(encode(self.eng, self.vocab, s, me))
                ids.append(k)
        if pending:
            C = torch.tensor(np.stack([p[0] for p in pending]), device=self.dev)
            N = torch.tensor(np.stack([p[1] for p in pending]), device=self.dev)
            G = torch.tensor(np.stack([p[2] for p in pending]), device=self.dev)
            with torch.no_grad():
                p = torch.sigmoid(self.net(C, N, G)).cpu().numpy()
            out[ids] = p
        return out


def payoff_matrix_value(eng, ev, st, me, my_acts, opp_acts, samples, rng, pol):
    opp = 1 - me
    M = np.zeros((len(my_acts), len(opp_acts)))
    for i, a in enumerate(my_acts):
        for j, b in enumerate(opp_acts):
            nxt = []
            for _ in range(samples):
                s = eng.clone(st)
                acts = [None, None]
                acts[me], acts[opp] = a, b
                eng.step(s, acts, rng, pol)
                nxt.append(s)
            M[i, j] = ev.values(nxt, me).mean()
    return M


def _sample_world(eng, st, opp, models, rng):
    sets = {idx: m.sample_set(rng) for idx, m in models.items()}
    for idx, spec in sets.items():
        bm = st.sides[opp].team[idx]
        for mv in bm.spec["moves"]:
            if len(spec["moves"]) >= 4:
                break
            if mv not in spec["moves"]:
                spec["moves"].append(mv)
        for key in [norm(x) for x in (bm.charge, bm.locked, bm.last_move if (bm.rampage or bm.encore) else None) if x]:
            if key not in [norm(m) for m in spec["moves"]]:
                if len(spec["moves"]) >= 4:
                    spec["moves"][-1] = key
                else:
                    spec["moves"].append(key)
    world = resample_opponent(eng, st, opp, sets)
    return world


def nash_value_hidden(eng, ev, st, me, models, worlds=4, samples=4, seed=0, pol=None, my_max_sw=2, opp_max_sw=1):
    """숨은 정보 + 가치망 1턴 탐색. 반환 {행동: 확률}"""
    from .policy import make_switch_policy
    rng = random.Random(seed)
    pol = pol or make_switch_policy(eng, rng)
    opp = 1 - me
    my_acts = candidate_actions(eng, st, me, my_max_sw)
    total = np.zeros(len(my_acts))
    for _ in range(worlds):
        world = _sample_world(eng, st, opp, models, rng)
        opp_acts = candidate_actions(eng, world, opp, opp_max_sw)
        M = payoff_matrix_value(eng, ev, world, me, my_acts, opp_acts, samples, rng, pol)
        x, _ = solve_zero_sum(M)
        total += x
    total /= worlds
    return dict(zip(my_acts, total))
