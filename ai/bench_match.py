"""AI 대 AI 대결 (양쪽 모두 상대 세트를 모르고 추론한다).
같은 두 팀을 양쪽 자리에서 번갈아 잡고 두 번씩 싸워 공정하게 비교한다 (팀 강약이 상쇄됨).
종류: greedy(휴리스틱) / flat(평면 몬테카를로, 상대=휴리스틱 가정) / nash(수익 행렬+내시 균형, 숨은 정보는 세계 평균)
사용: python -m ai.bench_match --a nash --b flat --games 60"""
import argparse
import concurrent.futures as cf
import os
import random

from .decide import evaluate_hidden
from .gamedata import GameData, connect
from .inference import OppModel, feed_events, feed_turn, snapshot
from .meta import Meta
from .observe import ObsEngine
from .policy import greedy_action, make_switch_policy
from .search import nash_hidden, pick
from .search_value import ValueEvaluator, nash_value_hidden
from .search_deep import nash_deep_hidden
from .teams import MetaTeams, ReplayTeams

_G = {}


def _init(snap, teams, ckpt=None, ckpt2=None):
    conn = connect()
    data = GameData(conn)
    meta = Meta(conn, data, snap)
    src = ReplayTeams(conn, data, meta) if teams == "replay" else MetaTeams(meta)
    eng = ObsEngine(data)
    ev = ValueEvaluator(eng, ckpt, os.path.join(os.path.dirname(ckpt), "vocab.json"), device="cpu") if ckpt else None
    ev2 = ValueEvaluator(eng, ckpt2, os.path.join(os.path.dirname(ckpt2), "vocab.json"), device="cpu") if ckpt2 else None
    _G.update(data=data, meta=meta, eng=eng, src=src, ev=ev, ev2=ev2)


def _override(spec, true, what):
    """정보 실험: 상대 세트 표본의 일부(또는 전부)를 정답으로 바꾼다"""
    spec = dict(spec)
    if what in ("oracle", "know_item"):
        spec["item"] = true["item"]
    if what in ("oracle", "know_ability"):
        spec["ability"] = true["ability"]
    if what in ("oracle", "know_spread"):
        spec["nature"], spec["sp"] = true["nature"], dict(true["sp"])
    if what in ("oracle", "know_moves"):
        spec["moves"] = list(true["moves"])
    return spec


class Player:
    def __init__(self, side, kind, opp_species, params, seed, opp_team=None, info="post"):
        data, meta = _G["data"], _G["meta"]
        self.side, self.kind, self.params, self.info = side, kind, params, info
        self.rng = random.Random(seed)
        self.models = {i: OppModel(meta, data, sid) for i, sid in enumerate(opp_species)}
        self.ev_n = 0
        if info not in ("post", "prior") and opp_team:           # oracle / know_*: 상대의 진짜 세트(일부)를 안다고 가정
            for i, m in self.models.items():
                m.sample_set = (lambda rng, m=m, t=opp_team[i], w=info: _override(type(m).sample_set(m, rng), t, w))

    def start(self, st):
        if self.info == "prior":
            return
        feed_events(self.models[st.sides[1 - self.side].active], _G["data"], getattr(st, "events", []) or [], 1 - self.side, True, None, None)
        self.ev_n = len(getattr(st, "events", []) or [])

    def decide(self, st):
        eng, me, opp = _G["eng"], self.side, 1 - self.side
        if self.kind == "greedy":
            return greedy_action(eng, st, me, self.rng)
        alive = {i: m for i, m in self.models.items() if st.sides[opp].team[i].alive}
        w, r = self.params["worlds"], self.params["rollouts"]
        if self.kind == "flat":
            ev = evaluate_hidden(eng, st, me, alive, n_worlds=w, rollouts=r, seed=self.rng.randrange(10 ** 9))
            return max(ev, key=ev.get)
        if self.kind in ("nashv", "nashv2"):          # 가치망 1턴 탐색 + 내시 균형 (nashv2 = 두 번째 가치망, --ckpt2)
            strat = nash_value_hidden(eng, _G["ev2"] if self.kind == "nashv2" else _G["ev"], st, me, alive, worlds=w, samples=r, seed=self.rng.randrange(10 ** 9))
            return pick(strat, self.rng, self.params.get("pick", "sample"))
        if self.kind == "nashd":          # 가치망 다턴 탐색 (후회 기준 가지치기)
            strat = nash_deep_hidden(eng, _G["ev"], st, me, alive, depth=self.params["depth"], worlds=w, samples=r,
                                     kmax=self.params["kmax"], delta=self.params["delta"], seed=self.rng.randrange(10 ** 9))
            return pick(strat, self.rng, "max")
        if self.kind == "nash":
            strat = nash_hidden(eng, st, me, alive, worlds=w, rollouts=r, seed=self.rng.randrange(10 ** 9))
            return pick(strat, self.rng, self.params.get("pick", "sample"))
        raise ValueError(self.kind)

    def before(self, st):
        self.snap = snapshot(_G["eng"], st, self.side)
        o = st.sides[1 - self.side]
        self.opp_idx, self.item0, self.vol0 = o.active, o.mon.item, set(o.mon.vol)
        self.w0, self.t0, self.n0 = st.weather, st.terrain, len(st.log)

    def after(self, st):
        if self.info == "prior":
            return
        data = _G["data"]
        opp = 1 - self.side
        evs = (getattr(st, "events", []) or [])[self.ev_n:]
        self.ev_n = len(getattr(st, "events", []) or [])
        m = self.models[self.opp_idx]
        if st.sides[opp].active == self.opp_idx and self.snap["opp_active"] == self.opp_idx:
            feed_turn(m, data, self.snap, st.log[self.n0:], self.w0, self.t0)
            feed_events(m, data, evs, opp, True, self.w0, self.t0)
            D1 = st.sides[opp].mon
            if self.item0 and not D1.item:
                m.observe_item(self.item0)
            if "busted" in D1.vol and "busted" not in self.vol0:
                m.observe_ability("Disguise")
        else:
            m.left_field()
            feed_events(self.models[st.sides[opp].active], data, evs, opp, True, self.w0, self.t0)


def play(job):
    kinds, gseed, params = job            # kinds = (side0 종류, side1 종류)
    try:
        eng, src = _G["eng"], _G["src"]
        rng = random.Random(gseed)
        t0, t1 = src.random_team(rng), src.random_team(rng)
        st = eng.new_state(t0, t1, log=True, rng=rng)
        pol = make_switch_policy(eng, rng)
        info = [params.get("info", "post") if kinds[k] == params.get("info_kind") else "post" for k in (0, 1)]
        players = [Player(0, kinds[0], [s["sid"] for s in t1], params, gseed * 3 + 1, t1, info[0]),
                   Player(1, kinds[1], [s["sid"] for s in t0], params, gseed * 3 + 2, t0, info[1])]
        for p in players:
            p.start(st)
        while st.winner is None and st.turn < 60:
            for p in players:
                p.before(st)
            acts = [p.decide(st) for p in players]
            eng.step(st, acts, rng, pol)
            for p in players:
                p.after(st)
        return kinds, gseed, (1.0 if st.winner == 0 else 0.5 if st.winner in (-1, None) else 0.0)
    except Exception:
        import traceback
        return kinds, gseed, "ERR:" + traceback.format_exc()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="nash")
    ap.add_argument("--b", default="flat")
    ap.add_argument("--games", type=int, default=40)
    ap.add_argument("--worlds", type=int, default=3)
    ap.add_argument("--rollouts", type=int, default=4)
    ap.add_argument("--pick", default="sample", choices=["sample", "max"])
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--kmax", type=int, default=3)
    ap.add_argument("--delta", type=float, default=0.08)
    ap.add_argument("--info", default="post", choices=["post", "prior", "oracle", "know_item", "know_moves", "know_spread", "know_ability"],
                    help="--a 에이전트가 가진 상대 정보 수준 (정보 가치 실험)")
    ap.add_argument("--snap", type=int, default=33)
    ap.add_argument("--teams", default="meta", choices=["meta", "replay"])
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--ckpt", default="data/value_v2/value_net.pt", help="nashv 에이전트가 쓸 가치망")
    ap.add_argument("--ckpt2", default=None, help="nashv2 에이전트가 쓸 가치망")
    a = ap.parse_args()
    params = dict(worlds=a.worlds, rollouts=a.rollouts, pick=a.pick, depth=a.depth, kmax=a.kmax, delta=a.delta, info=a.info, info_kind=a.a)
    jobs = []
    for g in range(a.games):
        jobs.append(((a.a, a.b), 2000 + g, params))      # A 가 0번 자리
        jobs.append(((a.b, a.a), 2000 + g, params))      # A 가 1번 자리 (팀은 그대로)
    wins, n, errs = 0.0, 0, 0
    with cf.ProcessPoolExecutor(max_workers=a.workers, initializer=_init, initargs=(a.snap, a.teams, a.ckpt, a.ckpt2)) as ex:
        for k, (kinds, g, res) in enumerate(ex.map(play, jobs, chunksize=1)):
            if isinstance(res, str):
                errs += 1
                if errs == 1:
                    print(res)
                continue
            a_is_side0 = kinds[0] == a.a and kinds != (a.b, a.a)
            wins += res if a_is_side0 else 1 - res
            n += 1
            if (k + 1) % 20 == 0:
                print(f"  ... {k + 1}/{len(jobs)}  지금까지 {a.a} 승률 {wins / n:.1%}", flush=True)
    se = (0.25 / max(1, n)) ** 0.5
    print(f"\n{a.a} vs {a.b}: {a.a} 승률 {wins / max(1, n):.1%} (±{1.96 * se:.1%}, {n}판, 오류 {errs}) — 세계 {a.worlds} x 롤아웃 {a.rollouts}")


if __name__ == "__main__":
    main()
