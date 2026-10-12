"""휴리스틱 정책 + 몬테카를로 승률 평가.
- greedy_action: 기대 데미지 비율 위주의 간단한 정책 (롤아웃용 상대/나 자신의 기본 행동)
- evaluate_actions: 내 각 행동의 승률을 롤아웃으로 추정 (상대는 greedy 정책, 정보는 완전 공개 가정 = v1)"""
import math
import random

from .gamedata import norm


def _avg_rolls(r):
    return sum(r["rolls"]) / len(r["rolls"]) if r["rolls"] else 0


def move_value(eng, st, side, mi):
    """기술 mi 의 점수: 상대 현재 HP 대비 기대 피해 비율(KO 보너스) 또는 변화기 휴리스틱"""
    A, D = st.sides[side].mon, st.sides[1 - side].mon
    mv = eng.data.moves[norm(A.spec["moves"][mi])]
    acc = 1.0 if mv["accuracy"] is None else mv["accuracy"] / 100
    if mv["category"] != "status" or mv["bp"]:
        if mv["fixed_damage"]:
            d = mv["fixed_damage"]
        else:
            r = eng.rolls(st, side, 1 - side, norm(mv["name"]), False)
            if r["rolls"] is None:
                return 0.0
            d = _avg_rolls(r) * max(1, (mv["min_hits"] + mv["max_hits"]) / 2 if mv["max_hits"] > 1 else 1)
        frac = min(d, D.hp) / D.maxhp * acc
        if d >= D.hp:
            frac += 0.5 * acc + (0.3 if eng._priority(st, side, mv) > 0 else 0)
        if mv["recoil"] or "recharge" in mv["flags"]:
            frac *= 0.85
        if mv["name"].lower() in ("fake out", "first impression") and A.active_turns != 0:
            return 0.0
        return frac
    # 변화기
    v = 0.0
    for e in mv["effects"]:
        if e["trigger_type"] != "primary":
            continue
        if e["kind"] == "stat_stage" and e["applies_to"] == "self" and (e["stages"] or 0) > 0 and A.boosts.get(e["code"], 0) < 2 and A.frac() > 0.5:
            v = max(v, 0.18 * min(e["stages"], 2) * (1.2 if e["code"] in ("atk", "spa", "spe") else 0.8))
        elif e["kind"] == "status" and not D.status and e["applies_to"] == "target":
            v = max(v, 0.3 * acc if e["code"] in ("brn", "par", "slp", "tox") else 0.15)
        elif e["kind"] == "side_condition" and e["code"] in ("stealthrock", "spikes", "toxicspikes", "stickyweb"):
            if len(st.sides[1 - side].alive_idx()) > 1 and not st.sides[1 - side].hazards.get(e["code"]):
                v = max(v, 0.25)
        elif e["kind"] == "side_condition" and e["code"] in ("reflect", "lightscreen", "tailwind", "auroraveil"):
            v = max(v, 0.15)
        elif e["kind"] == "weather" and not st.weather:
            v = max(v, 0.15)
    if mv["heal"] and A.frac() < 0.55:
        v = max(v, 0.6 * (1 - A.frac()) + 0.2)
    return v


def greedy_action(eng, st, side, rng, eps=0.08, allow_switch=True):
    acts = eng.legal_actions(st, side)
    if len(acts) > 1 and rng.random() < eps:
        return rng.choice(acts)
    best, bv = None, -1
    for a in acts:
        if a[0] == "m":
            v = move_value(eng, st, side, a[1]) + rng.random() * 0.01
        elif a[0] in ("r", "t"):
            v = 0.0 if a[0] == "r" else 0.05      # 재충전 턴 / 발버둥(선택지가 없을 때)
        else:
            v = -9
        if v > bv:
            best, bv = a, v
    if allow_switch and bv < 0.12:
        sw = [a for a in acts if a[0] == "s"]
        if sw:
            cand = max(sw, key=lambda a: switch_value(eng, st, side, a[1]))
            if switch_value(eng, st, side, cand[1]) > bv + 0.1:
                return cand
    return best


def best_damage_of(eng, st, att_side, att_idx, def_side):
    """att_side 의 team[att_idx] 가 상대 현재 포켓몬에게 줄 수 있는 최대 기대 데미지 비율"""
    S = st.sides[att_side]
    old = S.active
    S.active = att_idx
    try:
        bm = S.mon
        D = st.sides[def_side].mon
        best = 0.0
        for mi, m in enumerate(bm.spec["moves"]):
            mv = eng.data.moves.get(norm(m))
            if not mv or (mv["category"] == "status" and not mv["bp"]):
                continue
            r = eng.rolls(st, att_side, def_side, norm(m), False)
            if r["rolls"]:
                best = max(best, min(_avg_rolls(r), D.hp) / D.maxhp)
        return best
    finally:
        S.active = old


def switch_value(eng, st, side, j):
    me = st.sides[side].team[j]
    # 내 j 번이 상대에게 주는 피해 vs 상대가 j 번에게 주는 피해
    dealt = best_damage_of(eng, st, side, j, 1 - side)
    S0 = st.sides[side]
    old = S0.active
    S0.active = j
    try:
        taken = best_damage_of(eng, st, 1 - side, st.sides[1 - side].active, side)
    finally:
        S0.active = old
    return (dealt - taken) * 0.6 * me.frac() - 0.05


def make_switch_policy(eng, rng):
    def pick(st, side):
        alive = st.sides[side].alive_idx()
        return max(alive, key=lambda j: switch_value(eng, st, side, j))
    return pick


def play_out(eng, st, rng, max_turns=80, first_acts=None, opp_eps=0.08, my_policy=None, side=None):
    """한 판을 끝까지 진행해 승자(0/1/-1)를 돌려준다. 양쪽 기본은 greedy."""
    pol = make_switch_policy(eng, rng)
    first = True
    while st.winner is None and st.turn < max_turns:
        if first and first_acts is not None:
            acts = list(first_acts)
        else:
            acts = [greedy_action(eng, st, i, rng, eps=opp_eps) for i in (0, 1)]
        first = False
        eng.step(st, acts, rng, pol)
    return st.winner if st.winner is not None else -1


def evaluate_actions(eng, st, side, n=40, seed=0, opp_eps=0.08):
    """side 의 각 합법 행동 → 승률(무승부 0.5). 상대의 첫 행동도 정책에서 샘플링한다."""
    rng = random.Random(seed)
    out = {}
    for a in eng.legal_actions(st, side):
        w = 0.0
        for _ in range(n):
            s = eng.clone(st)
            opp = greedy_action(eng, s, 1 - side, rng, eps=opp_eps)
            acts = [None, None]
            acts[side], acts[1 - side] = a, opp
            win = play_out(eng, s, rng, first_acts=acts, opp_eps=opp_eps)
            w += 1.0 if win == side else (0.5 if win == -1 else 0.0)
        out[a] = w / n
    return out
