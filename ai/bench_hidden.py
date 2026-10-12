"""숨은 정보 대결 벤치마크: 내 AI(0번 편)가 상대 세트를 모른 채 싸울 때, 정보를 얼마나 잘 쓰는가.
같은 팀/같은 시드로 네 가지 방식을 비교한다 (상대 1번 편은 항상 실제 세트로 휴리스틱 정책).
  oracle : 상대의 진짜 세트를 안다고 가정 (상한선)
  prior  : 메타 사전분포에서 세트를 뽑아 세계를 만듦 (증거 사용 안 함)
  post   : 관측 증거로 갱신한 사후분포에서 뽑음 (추론기)
  modal  : 메타에서 가장 흔한 세트 하나로 단정
사용: python -m ai.bench_hidden [--games 60] [--worlds 4] [--rollouts 6] [--workers 14]"""
import argparse
import concurrent.futures as cf
import os
import random

from .observe import ObsEngine
from .decide import evaluate_hidden
from .gamedata import GameData, connect
from .inference import OppModel, feed_events, feed_turn, snapshot
from .meta import Meta
from .teams import MetaTeams, ReplayTeams
from .policy import evaluate_actions, greedy_action, make_switch_policy

_G = {}


def _init(snap, teams="meta"):
    conn = connect()
    data = GameData(conn)
    meta = Meta(conn, data, snap)
    src = ReplayTeams(conn, data, meta) if teams == "replay" else MetaTeams(meta)
    _G.update(data=data, meta=meta, eng=ObsEngine(data), src=src)


def _modal_model_set(model):
    s = model.sample_set(random.Random(0))
    h = max(model.hyps, key=lambda x: x.w)
    s.update(ability=h.ability, item=h.item, nature=h.nature, sp=dict(h.sp))
    return s


def play(job):
    try:
        return _play(job)
    except Exception:
        import traceback
        return job[0], job[1], "ERR:" + traceback.format_exc()


def _play(job):
    mode, gseed, worlds, rollouts = job
    data, meta, eng = _G["data"], _G["meta"], _G["eng"]
    rng = random.Random(gseed)
    ours, theirs = _G["src"].random_team(rng), _G["src"].random_team(rng)
    st = eng.new_state(ours, theirs, log=True, rng=rng)
    pol = make_switch_policy(eng, rng)
    models = {i: OppModel(meta, data, theirs[i]["sid"]) for i in range(3)}
    arng = random.Random(gseed * 7 + 1)
    if mode == "post":
        feed_events(models[0], data, getattr(st, "events", []) or [], 1, True, None, None)
    ev_n = len(getattr(st, "events", []) or [])
    while st.winner is None and st.turn < 60:
        me, opp = 0, 1
        snap = snapshot(eng, st)
        if mode == "oracle":
            ev = evaluate_actions(eng, st, me, n=worlds * rollouts, seed=arng.randrange(10 ** 9))
        elif mode in ("prior", "post"):
            ms = {i: m for i, m in models.items() if st.sides[opp].team[i].alive}
            ev = evaluate_hidden(eng, st, me, ms, n_worlds=worlds, rollouts=rollouts, seed=arng.randrange(10 ** 9))
        else:       # modal
            sets = {i: _modal_model_set(m) for i, m in models.items() if st.sides[opp].team[i].alive}
            from .decide import resample_opponent
            w = resample_opponent(eng, st, opp, sets)
            ev = evaluate_actions(eng, w, me, n=worlds * rollouts, seed=arng.randrange(10 ** 9))
        a0 = max(ev, key=ev.get)
        a1 = greedy_action(eng, st, opp, rng)
        n0 = len(st.log)
        w0, t0 = st.weather, st.terrain
        opp_idx_before = st.sides[opp].active
        item0, vol0 = st.sides[opp].mon.item, set(st.sides[opp].mon.vol)
        eng.step(st, [a0, a1], rng, pol)
        evs = (getattr(st, "events", []) or [])[ev_n:]
        ev_n = len(getattr(st, "events", []) or [])
        if mode == "post":
            m = models[opp_idx_before]
            if st.sides[opp].active == opp_idx_before and snap["opp_active"] == opp_idx_before:
                feed_turn(m, data, snap, st.log[n0:], w0, t0)
                feed_events(m, data, evs, opp, True, w0, t0)
                D1 = st.sides[opp].mon
                if item0 and not D1.item:
                    m.observe_item(item0)
                if "busted" in D1.vol and "busted" not in vol0:
                    m.observe_ability("Disguise")
            else:
                m.left_field()
                # 새로 나온 상대의 등장 효과는 그 포켓몬 모델에 반영
                newm = models[st.sides[opp].active]
                feed_events(newm, data, evs, opp, True, w0, t0)
    win = 1.0 if st.winner == 0 else (0.5 if st.winner in (-1, None) else 0.0)
    return mode, gseed, win


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=60)
    ap.add_argument("--worlds", type=int, default=4)
    ap.add_argument("--rollouts", type=int, default=6)
    ap.add_argument("--snap", type=int, default=33)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) // 2))
    ap.add_argument("--modes", default="oracle,post,prior,modal")
    ap.add_argument("--teams", default="meta", choices=["meta", "replay"], help="팀 출처: 메타 사용률 / 리플레이의 실제 선출 3마리 조합")
    a = ap.parse_args()
    modes = a.modes.split(",")
    jobs = [(m, 1000 + g, a.worlds, a.rollouts) for g in range(a.games) for m in modes]
    res = {m: {} for m in modes}
    with cf.ProcessPoolExecutor(max_workers=a.workers, initializer=_init, initargs=(a.snap, a.teams)) as ex:
        for k, (mode, g, win) in enumerate(ex.map(play, jobs, chunksize=1)):
            if isinstance(win, str):
                print(f"오류 {mode} 게임 {g}:", win, flush=True)
                continue
            res[mode][g] = win
            if (k + 1) % 20 == 0:
                print(f"  ... {k + 1}/{len(jobs)}", flush=True)
    print(f"\n숨은 정보 대결 ({a.games}판, 세계 {a.worlds} x 롤아웃 {a.rollouts}) — 내 AI 승률 (같은 팀·시드 쌍)")
    for m in modes:
        v = list(res[m].values())
        print(f"  {m:7s} {sum(v) / max(1, len(v)):6.1%}  ({len(v)}판)")
    base = res.get("oracle")
    if base:
        for m in modes:
            if m != "oracle":
                common = [g for g in base if g in res[m]]
                d = [res[m][g] - base[g] for g in common]
                print(f"  oracle 대비 {m:7s} 평균 차이 {sum(d) / max(1, len(d)):+.3f}")


if __name__ == "__main__":
    main()
