"""시뮬레이션 기반 선출: 내 6마리 중 3마리 조합(20가지)을 상대의 가능한 선출 3마리 조합(20가지)에 대해 모의 전투로 평가한다.
- 상대 선출 분포는 종별 '선출률'(리플레이 통계)을 가중치로 쓴다 (조합 가중치 = 세 마리 선출률의 곱, 정규화)
- 한 쌍의 승률은 휴리스틱 정책 롤아웃의 평균 (속도를 위해 가볍게)
- 결과: 내 조합별 기대 승률 -> 가장 높은 조합을 선출
사용: python -m ai.select_sim --games 20   (무작위로 뽑은 6마리 팀 쌍에 대해 추천 선출의 실제 승률을 확인)"""
import argparse
import itertools
import random

import numpy as np

from .battle import Engine
from .gamedata import GameData, connect, norm
from .meta import Meta
from .policy import play_out
from .teams import MetaTeams, ReplayTeams


def pair_winrate(eng, my3, op3, rng, rollouts):
    """my3/op3: 세트 리스트(3마리). 리드는 리스트 첫 번째. 내 쪽 승률"""
    w = 0.0
    for _ in range(rollouts):
        st = eng.new_state(my3, op3, rng=rng)
        res = play_out(eng, st, rng)
        w += 1.0 if res == 0 else (0.5 if res == -1 else 0.0)
    return w / rollouts


def evaluate_selections(eng, my6, op6, bring_rate, rng, rollouts=3, max_opp=10):
    """my6/op6: 세트 6개씩. 반환: [(내 조합 인덱스 튜플, 기대 승률)]"""
    my_combos = list(itertools.combinations(range(6), 3))
    op_combos = list(itertools.combinations(range(6), 3))
    wts = np.array([np.prod([bring_rate.get(op6[i]["sid"], 0.4) for i in c]) for c in op_combos])
    wts = wts / wts.sum()
    # 상대 조합은 가중치 상위 max_opp 개로 줄여 비용을 낮춘다
    top = np.argsort(-wts)[:max_opp]
    wsel = wts[top] / wts[top].sum()
    out = []
    for mc in my_combos:
        tot = 0.0
        for wt, k in zip(wsel, top):
            oc = op_combos[k]
            tot += wt * pair_winrate(eng, [my6[i] for i in mc], [op6[i] for i in oc], rng, rollouts)
        out.append((mc, tot))
    return sorted(out, key=lambda x: -x[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=10)
    ap.add_argument("--rollouts", type=int, default=3)
    ap.add_argument("--snap", type=int, default=33)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    conn = connect()
    data = GameData(conn)
    meta = Meta(conn, data, a.snap)
    eng = Engine(data)
    rng = random.Random(a.seed)
    # 종별 선출률 (리플레이)
    cur = conn.cursor()
    cur.execute("select species, avg(brought) r from replay_mon group by species")
    bring = {norm(r["species"]): float(r["r"]) for r in cur.fetchall()}
    gains, base_wins, best_wins, worst_wins = [], [], [], []
    for g in range(a.games):
        my6 = [meta.build_set(sid, rng) for sid in rng.sample(meta.top_species(40), 6)]
        op6 = [meta.build_set(sid, rng) for sid in rng.sample(meta.top_species(40), 6)]
        ranked = evaluate_selections(eng, my6, op6, bring, rng, rollouts=a.rollouts)
        best, worst = ranked[0], ranked[-1]
        # 실제 검증: 추천 조합 vs 최악 조합 vs 무작위 조합이 '실제 상대 선출(선출률 가중 무작위)'을 만났을 때의 승률
        oc = tuple(sorted(rng.sample(range(6), 3)))
        def real(mc):
            return pair_winrate(eng, [my6[i] for i in mc], [op6[i] for i in oc], rng, 30)
        rb, rw, rr = real(best[0]), real(worst[0]), real(rng.choice(ranked)[0])
        best_wins.append(rb); worst_wins.append(rw); base_wins.append(rr)
        print(f"  게임 {g + 1}: 추천 {best[0]} 예측 {best[1]:.2f} -> 실제 {rb:.2f} | 무작위 조합 {rr:.2f} | 최악 {rw:.2f}", flush=True)
    print(f"\n평균 실제 승률 — 추천 조합 {np.mean(best_wins):.3f}, 무작위 조합 {np.mean(base_wins):.3f}, 최악 조합 {np.mean(worst_wins):.3f}")


if __name__ == "__main__":
    main()
