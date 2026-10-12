"""숨은 정보가 있는 상태에서의 의사결정.
상대 세트를 추론기(OppModel)의 사후분포에서 여러 번 뽑아 '세계'를 만들고, 세계마다 몬테카를로 롤아웃으로
내 각 행동의 승률을 구한 뒤 평균한다 (determinization). 상대 정보가 부족할수록 세계 사이 승률이 갈려 평균이 흐려진다."""
import random

from .damage_calc import make_mon
from .gamedata import norm
from .policy import evaluate_actions


def resample_opponent(eng, st, opp_side, sets_by_idx):
    """st 를 복제해 상대 팀의 세트(특성/도구/성격/SP/기술)를 sets_by_idx{팀내번호: spec} 로 교체한다.
    HP는 '비율'을 유지하고, 능력치 단계/상태이상/현재 대상은 그대로 둔다. 이미 소모된 도구는 되살리지 않는다."""
    s = eng.clone(st)
    for idx, spec in sets_by_idx.items():
        bm = s.sides[opp_side].team[idx]
        frac = bm.hp / bm.maxhp if bm.maxhp else 0
        consumed = (bm.item == "" and bool(bm.spec.get("item")))
        m = make_mon(eng.data, dict(spec, boosts={}, status=None, hp_frac=None))
        bm.spec = dict(spec)
        bm.maxhp = m.maxhp
        bm.hp = max(1, round(m.maxhp * frac)) if frac > 0 else 0
        bm.ability = spec.get("ability", bm.ability)
        bm.item = "" if consumed else spec.get("item", "")
        if "ability" in spec and norm(spec["ability"]) == norm(bm.ability):
            pass
    return s


def evaluate_hidden(eng, st, me, models, n_worlds=6, rollouts=8, seed=0, bench_prior=None):
    """models: {상대 팀내번호: OppModel} (증거가 쌓인 것은 사후, 없는 것은 사전분포).
    반환: {행동: 평균 승률}"""
    rng = random.Random(seed)
    opp = 1 - me
    totals = {}
    for w in range(n_worlds):
        sets = {idx: model.sample_set(rng) for idx, model in models.items()}
        # 기술이 4개 미만이면 (메타 데이터 부족) 기존 기술을 유지해 채운다
        for idx, spec in sets.items():
            old = st.sides[opp].team[idx].spec["moves"]
            for mv in old:
                if len(spec["moves"]) >= 4:
                    break
                if mv not in spec["moves"]:
                    spec["moves"].append(mv)
        for idx, spec in sets.items():                  # 진행 중인 상태(충전/고정/앙코르)가 가리키는 기술은 반드시 유지
            bm = st.sides[opp].team[idx]
            need = [norm(x) for x in (bm.charge, bm.locked, bm.last_move if (bm.rampage or bm.encore) else None) if x]
            for key in need:
                if key not in [norm(m) for m in spec["moves"]]:
                    if len(spec["moves"]) >= 4:
                        spec["moves"][-1] = key
                    else:
                        spec["moves"].append(key)
        world = resample_opponent(eng, st, opp, sets)
        ev = evaluate_actions(eng, world, me, n=rollouts, seed=rng.randrange(10 ** 9))
        for a, v in ev.items():
            totals[a] = totals.get(a, 0.0) + v
    return {a: v / n_worlds for a, v in totals.items()}
