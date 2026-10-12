"""상대 세트 추론기 평가: 메타에서 뽑은 '진짜 세트'를 상대로 휴리스틱 정책끼리 몇 턴 싸우게 하고,
그 사이 관측만으로 추론기가 진짜 세트에 부여하는 확률이 사전확률 대비 얼마나 올라가는지 본다.
사용: python -m ai.infer_eval [--games 60] [--turns 3] [--snap 33] [--seed 0]"""
import argparse
import math
import random
import re
import time

from .battle import Engine
from .observe import ObsEngine
from .gamedata import GameData, connect, norm
from .inference import OppModel, feed_events, feed_turn, snapshot
from .meta import Meta
from .teams import MetaTeams, ReplayTeams
from .policy import greedy_action, make_switch_policy

DMG = re.compile(r"^  (.+) -(\d+) \((\d+)/(\d+)\)$")
MOVE = re.compile(r"^\[(\d)\] (.+): (.+)$")


def parse_turn(lines):
    """한 턴의 로그에서 [(행동자, 기술명, [(대상HP후, 최대HP, 데미지)...])] 를 행동 순서대로 뽑는다"""
    ev = []
    for ln in lines:
        m = MOVE.match(ln)
        if m and "등장" not in ln:
            ev.append([int(m.group(1)), m.group(3), []])
            continue
        d = DMG.match(ln)
        if d and ev:
            ev[-1][2].append((int(d.group(3)), int(d.group(4)), int(d.group(2))))
    return ev


def true_probs(model, truth):
    ab = model.marginal("ability").get(truth["ability"], 0.0)
    it = model.marginal("item").get(truth["item"], 0.0)
    sp = model.marginal("spread").get((truth["nature"], tuple(sorted(truth["sp"].items()))), 0.0)
    mp = model._move_probs()
    mv = [mp.get(norm(m), 0.0) for m in truth["moves"]]
    return ab, it, sp, sum(mv) / max(1, len(mv))


def run(args):
    conn = connect()
    data = GameData(conn)
    meta = Meta(conn, data, args.snap)
    src = ReplayTeams(conn, data, meta) if args.teams == "replay" else MetaTeams(meta)
    eng = (ObsEngine if args.events else Engine)(data)
    rng = random.Random(args.seed)
    pol = make_switch_policy(eng, rng)
    # 단계별(0=사전, 1..T=관측 후) 누적: -log p(진짜), 진짜가 1순위인 비율
    stats = {t: dict(ab=0.0, it=0.0, sp=0.0, mv=0.0, n=0, top_ab=0, top_it=0, top_sp=0) for t in range(args.turns + 1)}
    t0 = time.time()
    for g in range(args.games):
        ours, theirs = src.random_team(rng), src.random_team(rng)
        st = eng.new_state(ours, theirs, log=True, rng=rng)
        truth = theirs[0]
        model = OppModel(meta, data, truth["sid"])
        if args.events:                      # 시작 직후 공개된 등장 효과(위협, 날씨 특성 등)
            feed_events(model, data, getattr(st, "events", []), 1, True, None, None)
        ev_n = len(getattr(st, "events", []) or [])
        for t in range(args.turns + 1):
            if t > 0:
                if st.winner is not None or st.sides[1].active != 0:
                    break
                snap = snapshot(eng, st)
                acts = [greedy_action(eng, st, k, rng) for k in (0, 1)]
                n0 = len(st.log)
                w0, t0_ = st.weather, st.terrain
                item0, vol0 = st.sides[1].mon.item, set(st.sides[1].mon.vol)
                eng.step(st, acts, rng, pol)
                feed_turn(model, data, snap, st.log[n0:], w0, t0_)
                if args.events:
                    evs = getattr(st, "events", [])[ev_n:]
                    ev_n = len(getattr(st, "events", []))
                    feed_events(model, data, evs, 1, st.sides[1].active == 0, w0, t0_)
                    D1 = st.sides[1].mon
                    if st.sides[1].active == 0 and item0 and not D1.item:         # 도구를 잃음(소모/탈취/풍선 터짐): 무슨 도구였는지 공개됨
                        model.observe_item(item0)
                    if "busted" in D1.vol and "busted" not in vol0:
                        model.observe_ability("Disguise")
                    if "protean" in D1.vol and "protean" not in vol0:
                        model.observe_ability(D1.ability)
            ab, it, sp, mv = true_probs(model, truth)
            s = stats[t]
            s["n"] += 1
            s["ab"] += -math.log(max(ab, 1e-6))
            s["it"] += -math.log(max(it, 1e-6))
            s["sp"] += -math.log(max(sp, 1e-6))
            s["mv"] += mv
            top = lambda what: next(iter(model.marginal(what)))
            s["top_ab"] += top("ability") == truth["ability"]
            s["top_it"] += top("item") == truth["item"]
            s["top_sp"] += top("spread") == (truth["nature"], tuple(sorted(truth["sp"].items())))
        if (g + 1) % 10 == 0:
            print(f"  ... {g + 1}/{args.games} ({time.time() - t0:.0f}s)")
    print(f"\n상대 세트 추론 평가: {args.games}판, 관측 {args.turns}턴 (낮을수록 좋은 값: -log p, 높을수록 좋은 값: 1순위 적중률)")
    print(f"{'단계':8s} {'n':>4s} | 특성 -logp  1순위 | 도구 -logp  1순위 | 성격+SP -logp  1순위 | 기술(미공개 포함) 진짜 기술 평균 확률")
    for t, s in stats.items():
        if not s["n"]:
            continue
        n = s["n"]
        print(f"{'사전' if t == 0 else f'{t}턴 후':8s} {n:4d} | {s['ab'] / n:9.2f} {s['top_ab'] / n:7.0%} | {s['it'] / n:9.2f} {s['top_it'] / n:7.0%} | "
              f"{s['sp'] / n:11.2f} {s['top_sp'] / n:7.0%} | {s['mv'] / n:.2f}")


def Field_(st):
    from .damage_calc import Field
    return Field(st.weather, st.terrain)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=60)
    ap.add_argument("--turns", type=int, default=3)
    ap.add_argument("--snap", type=int, default=33)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--teams", default="meta", choices=["meta", "replay"])
    ap.add_argument("--no-events", dest="events", action="store_false", help="특성/도구 발동 같은 공개 사건 증거를 쓰지 않는다")
    run(ap.parse_args())
