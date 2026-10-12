"""동시 수 탐색: 수익 행렬 + 내시 균형.
싱글 배틀은 양쪽이 같은 턴에 동시에 행동을 정한다. 그래서
  1) '내 행동 x 상대 행동' 모든 칸의 승률을 몬테카를로 롤아웃으로 추정해 수익 행렬을 만들고,
  2) 이 영합 게임을 선형계획으로 풀어 최적 혼합 전략(내시 균형)을 구한다.
상대를 '항상 최대 데미지'로 단정하는 평면 몬테카를로(policy.evaluate_actions)와 달리 상대의 모든 응답에 대비한다.
숨은 정보는 세계(상대 세트 샘플)마다 행렬을 풀고 전략을 평균해서 처리한다."""
import random

import numpy as np
from scipy.optimize import linprog

from .decide import resample_opponent
from .gamedata import norm
from .policy import greedy_action, play_out, switch_value


def candidate_actions(eng, st, side, max_switches=2):
    """합법 행동 중 기술은 모두, 교체는 가치가 높은 상위 몇 개만 후보로 둔다"""
    acts = eng.legal_actions(st, side)
    moves = [a for a in acts if a[0] != "s"]
    sw = sorted([a for a in acts if a[0] == "s"], key=lambda a: -switch_value(eng, st, side, a[1]))[:max_switches]
    return moves + sw


def payoff_matrix(eng, st, me, my_acts, opp_acts, rollouts, rng, opp_eps=0.08):
    """M[i][j] = 내가 my_acts[i], 상대가 opp_acts[j] 를 고르고 이후 휴리스틱 정책으로 끝까지 갔을 때 내 승률"""
    opp = 1 - me
    M = np.zeros((len(my_acts), len(opp_acts)))
    for i, a in enumerate(my_acts):
        for j, b in enumerate(opp_acts):
            w = 0.0
            for _ in range(rollouts):
                s = eng.clone(st)
                acts = [None, None]
                acts[me], acts[opp] = a, b
                win = play_out(eng, s, rng, first_acts=acts, opp_eps=opp_eps)
                w += 1.0 if win == me else (0.5 if win == -1 else 0.0)
            M[i, j] = w / rollouts
    return M


def solve_zero_sum(M):
    """행 플레이어가 승률을 최대화하는 혼합 전략 x 와 게임 가치 v (선형계획)"""
    m, n = M.shape
    # 변수: x_0..x_{m-1}, v. 최소화 -v. 제약: v - sum_i x_i M[i,j] <= 0, sum x = 1
    c = np.zeros(m + 1)
    c[-1] = -1.0
    A_ub = np.hstack([-M.T, np.ones((n, 1))])
    b_ub = np.zeros(n)
    A_eq = np.zeros((1, m + 1))
    A_eq[0, :m] = 1.0
    res = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=[1.0], bounds=[(0, 1)] * m + [(None, None)], method="highs")
    if not res.success:
        x = np.zeros(m)
        x[int(np.argmax(M.min(axis=1)))] = 1.0
        return x, float(M.min(axis=1).max())
    x = np.clip(res.x[:m], 0, None)
    return x / x.sum(), float(res.x[-1])


def nash_strategy(eng, st, me, rollouts=6, rng=None, my_max_sw=2, opp_max_sw=1):
    """완전 정보(현재 상태 그대로) 상태에서 내 혼합 전략. 반환: (행동 리스트, 확률, 가치, 행렬)"""
    rng = rng or random.Random(0)
    my_acts = candidate_actions(eng, st, me, my_max_sw)
    opp_acts = candidate_actions(eng, st, 1 - me, opp_max_sw)
    M = payoff_matrix(eng, st, me, my_acts, opp_acts, rollouts, rng)
    x, v = solve_zero_sum(M)
    return my_acts, x, v, M


def nash_hidden(eng, st, me, models, worlds=4, rollouts=4, seed=0, my_max_sw=2, opp_max_sw=1):
    """숨은 정보: 상대 세트를 세계마다 샘플링해 행렬을 풀고 전략을 평균한다. 반환: {행동: 확률}"""
    rng = random.Random(seed)
    opp = 1 - me
    my_acts = candidate_actions(eng, st, me, my_max_sw)
    total = np.zeros(len(my_acts))
    for _ in range(worlds):
        sets = {idx: m.sample_set(rng) for idx, m in models.items()}
        for idx, spec in sets.items():                      # 기술이 모자라거나 진행 중 상태가 가리키는 기술은 유지
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
        opp_acts = candidate_actions(eng, world, opp, opp_max_sw)
        M = payoff_matrix(eng, world, me, my_acts, opp_acts, rollouts, rng)
        x, _ = solve_zero_sum(M)
        total += x
    total /= worlds
    return dict(zip(my_acts, total))


def pick(strategy, rng, how="sample"):
    """혼합 전략에서 행동 하나를 고른다: sample=확률대로, max=가장 높은 것"""
    acts = list(strategy)
    p = np.array([strategy[a] for a in acts])
    if how == "max":
        return acts[int(np.argmax(p))]
    p = p / p.sum()
    return acts[int(rng.choices(range(len(acts)), weights=p)[0])]
