"""다턴 깊이 탐색 (가치망 + 내시 균형).
각 노드에서
  1) 모든 행동 쌍을 한 턴 진행해 가치망으로 얕은 수익 행렬 M0 을 만들고 내시 균형(내 x, 상대 y)을 푼다.
  2) '가지치기'는 확률이 아니라 후회(regret) 기준: 균형 가치 v 에 대해 내 행동은 (M·y)[i] >= v - delta,
     상대 행동은 (x·M)[j] <= v + delta 이면 남긴다 (균형 지지 집합은 항상 포함). 확률이 낮아도 거의 최선이면 살아남는다.
  3) 남은 행동 쌍만 다음 턴으로 재귀해서 칸 값을 깊은 추정치로 바꾸고 다시 푼다.
확률적 사건(급소/명중/난수)은 가지치기하지 않고 표본으로 평균한다 (같은 행동 쌍을 여러 번 진행).
숨은 정보는 세계(상대 세트 샘플)마다 풀어 전략을 평균한다."""
import random

import numpy as np

from .search import candidate_actions, solve_zero_sum
from .search_value import _sample_world


def _shallow(eng, ev, st, me, my_acts, opp_acts, samples, rng, pol):
    opp = 1 - me
    nxt = {}
    flat = []
    for i, a in enumerate(my_acts):
        for j, b in enumerate(opp_acts):
            lst = []
            for _ in range(samples):
                s = eng.clone(st)
                acts = [None, None]
                acts[me], acts[opp] = a, b
                eng.step(s, acts, rng, pol)
                lst.append(s)
            nxt[i, j] = lst
            flat += lst
    vals = ev.values(flat, me)
    M = np.zeros((len(my_acts), len(opp_acts)))
    k = 0
    for (i, j), lst in nxt.items():
        M[i, j] = vals[k:k + len(lst)].mean()
        k += len(lst)
    return M, nxt


def _keep(M, x, y, v, delta, kmax):
    rows = M @ y
    cols = x @ M
    ri = [i for i in np.argsort(-rows) if rows[i] >= v - delta or x[i] > 1e-3][:kmax]
    cj = [j for j in np.argsort(cols) if cols[j] <= v + delta or y[j] > 1e-3][:kmax]
    return ri, cj


def solve_node(eng, ev, st, me, depth, rng, pol, samples, rec_n, kmax, delta, my_sw=2, opp_sw=1, stats=None):
    """-> (내 행동 리스트, x, 가치, M). depth 는 앞으로 더 볼 턴 수"""
    opp = 1 - me
    my_acts = candidate_actions(eng, st, me, my_sw)
    opp_acts = candidate_actions(eng, st, opp, opp_sw)
    M, nxt = _shallow(eng, ev, st, me, my_acts, opp_acts, samples, rng, pol)
    x, v = solve_zero_sum(M)
    if depth > 1:
        y, _ = solve_zero_sum(1.0 - M.T)
        ri, cj = _keep(M, x, y, v, delta, kmax)
        M2 = M.copy()
        for i in ri:
            for j in cj:
                vals = []
                for s in nxt[i, j][:rec_n]:
                    if s.winner is not None:
                        vals.append(1.0 if s.winner == me else 0.5 if s.winner == -1 else 0.0)
                    else:
                        vals.append(solve_node(eng, ev, s, me, depth - 1, rng, pol, 1, 1, kmax, delta, my_sw, opp_sw, stats)[2])
                M2[i, j] = float(np.mean(vals))
        M = M2
        x, v = solve_zero_sum(M)
    return my_acts, x, v, M


def nash_deep_hidden(eng, ev, st, me, models, depth=3, worlds=3, samples=3, rec_n=2, kmax=3, delta=0.08, seed=0, pol=None):
    from .policy import make_switch_policy
    rng = random.Random(seed)
    pol = pol or make_switch_policy(eng, rng)
    opp = 1 - me
    total = None
    for _ in range(worlds):
        world = _sample_world(eng, st, opp, models, rng)
        acts, x, _, _ = solve_node(eng, ev, world, me, depth, rng, pol, samples, rec_n, kmax, delta)
        total = x if total is None else total + x
    total /= worlds
    return dict(zip(acts, total))
