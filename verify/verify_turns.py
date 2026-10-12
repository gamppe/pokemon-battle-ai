"""턴 엔진(ai/battle.py) vs Showdown 분포 대조.
같은 팀/같은 행동으로 각 시나리오를 R번씩 양쪽에서 돌려 (HP, 상태이상, 능력 단계, 도구, 교체 위치, 날씨/필드, 해저드/벽, 승패)의 분포가
통계적으로 같은지 검정한다. 난수 시퀀스는 일치시킬 수 없으므로 분포(카이제곱/KS)로 비교한다.
사용: python verify/verify_turns.py [--n 300] [--runs 200] [--turns 1] [--seed 1] [--snap 33] [--only 기술이름] [--show]"""
import argparse
import collections
import json
import os
import random
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np
from scipy import stats
from ai.gamedata import GameData, connect, norm
from ai.meta import Meta
from ai.battle import Engine

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)
SD_WEATHER = {"sun": "sunnyday", "rain": "raindance", "sand": "sandstorm", "snow": "snowscape", None: ""}
SD_TERRAIN = {"electric": "electricterrain", "grassy": "grassyterrain", "misty": "mistyterrain", "psychic": "psychicterrain", None: ""}
SD_SIDE = {"reflect": "reflect", "light_screen": "lightscreen", "aurora_veil": "auroraveil", "tailwind": "tailwind", "safeguard": "safeguard"}


def make_scenarios(meta, data, n, turns, seed, only=None):
    rng = random.Random(seed)
    pairs = []
    for sid in meta.top_species(60):
        for mk, p in meta.moves.get(sid, []):
            if p >= 0.1 and mk in data.moves and (not only or norm(only) == mk):
                pairs.append((sid, mk))
    sc = []
    for k in range(n):
        sid, mk = rng.choice(pairs)
        t0 = meta.random_team(rng)
        t1 = meta.random_team(rng)
        lead = meta.build_set(sid, rng)
        lead["moves"] = [mk] + [m for m in lead["moves"] if m != mk][:3]
        t0[0] = lead
        if rng.random() < 0.1:
            first = [("s", 1), ("m", rng.randrange(len(t1[0]["moves"])))]
        else:
            first = [("m", 0), ("m", rng.randrange(len(t1[0]["moves"])))]
        tl = [first]
        for _ in range(turns - 1):
            tl.append([("m", rng.randrange(len(t0[0]["moves"]))), ("m", rng.randrange(len(t1[0]["moves"])))])
        sc.append(dict(id=f"s{k}", teams=[t0, t1], turns=tl, key=mk))
    return sc


def summarize_ours(st):
    mons = []
    for side in st.sides:
        mons.append([dict(hp=m.hp, st=m.status or "", b={k: v for k, v in m.boosts.items() if v}, it=norm(m.item), fnt=int(not m.alive))
                     for m in side.team])
    sc = []
    for side in st.sides:
        o = dict(side.hazards)
        for k, v in side.screens.items():
            if v > 0:
                o[SD_SIDE.get(k, k)] = 1
        sc.append(o)
    return dict(mons=mons, act=[s.active for s in st.sides], sc=sc, w=SD_WEATHER[st.weather], t=SD_TERRAIN[st.terrain], win=st.winner)


def run_ours(eng, sc, runs, seed):
    outs = []
    for r in range(runs):
        rng = random.Random(seed * 100003 + r)
        st = eng.new_state(sc["teams"][0], sc["teams"][1], rng=rng)
        for turn in sc["turns"]:
            if st.winner is not None:
                break
            acts = []
            for i in (0, 1):
                a = tuple(turn[i])
                legal = eng.legal_actions(st, i)
                acts.append(a if a in legal else legal[0])
            eng.step(st, acts, rng, None)
        outs.append(summarize_ours(st))
    return outs


def flatten(s):
    d = {}
    for side in (0, 1):
        for i, m in enumerate(s["mons"][side]):
            d[f"hp:{side}:{i}"] = m["hp"]
            d[f"st:{side}:{i}"] = m["st"]
            d[f"it:{side}:{i}"] = m["it"]
            for k, v in m["b"].items():
                d[f"b:{side}:{i}:{k}"] = v
        d[f"act:{side}"] = s["act"][side]
        for k, v in s["sc"][side].items():
            d[f"sc:{side}:{k}"] = v
    d["w"], d["t"] = s["w"], s["t"]
    d["win"] = -9 if s["win"] is None else s["win"]
    return d


def compare(a_runs, b_runs, alpha):
    A = [flatten(x) for x in a_runs]
    B = [flatten(x) for x in b_runs]
    keys = set().union(*[d.keys() for d in A + B])
    bad = []
    for k in sorted(keys):
        default = "" if k.split(":")[0] in ("st", "it", "w", "t") else 0
        va = [d.get(k, default) for d in A]
        vb = [d.get(k, default) for d in B]
        if k.startswith("hp:"):
            if len(set(va)) == 1 and len(set(vb)) == 1:
                p = 1.0 if va[0] == vb[0] else 0.0
            else:
                p = stats.ks_2samp(va, vb).pvalue
        else:
            cats = sorted(set(va) | set(vb), key=str)
            if len(cats) == 1:
                continue
            ca, cb = collections.Counter(va), collections.Counter(vb)
            tab = np.array([[ca[c] for c in cats], [cb[c] for c in cats]], dtype=float)
            tab = tab[:, tab.sum(0) > 0]
            if tab.shape[1] < 2:
                continue
            p = stats.chi2_contingency(tab)[1]
        if p < alpha:
            bad.append((k, p, collections.Counter(va).most_common(4), collections.Counter(vb).most_common(4)))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--runs", type=int, default=200)
    ap.add_argument("--turns", type=int, default=1)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--snap", type=int, default=33)
    ap.add_argument("--only")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--alpha", type=float, default=1e-5)
    a = ap.parse_args()
    conn = connect()
    data = GameData(conn)
    meta = Meta(conn, data, a.snap)
    eng = Engine(data)
    scs = make_scenarios(meta, data, a.n, a.turns, a.seed, a.only)
    fin, fout = os.path.join(OUT, "turns_in.json"), os.path.join(OUT, "turns_sd.json")
    json.dump([dict(id=s["id"], teams=s["teams"], turns=s["turns"], runs=a.runs, seed=a.seed) for s in scs], open(fin, "w"))
    t0 = time.time()
    r = subprocess.run(["node", os.path.join(HERE, "sd_turns.js"), os.path.join(HERE, "..", "showdown"), fin, fout], capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-2000:])
        sys.exit(1)
    sd = json.load(open(fout))
    t1 = time.time()
    flagged, errors = [], 0
    by_move, by_ab, by_it = (collections.defaultdict(lambda: [0, 0]) for _ in range(3))
    for s in scs:
        res = sd[s["id"]]
        if "error" in res:
            errors += 1
            print("SD error:", s["id"], res["error"][:200])
            continue
        bad = compare(run_ours(eng, s, a.runs, a.seed), res["results"], a.alpha)
        lead = s["teams"][0][0]
        for tbl, key in ((by_ab, norm(lead["ability"])), (by_it, norm(lead["item"])), (by_move, s["key"])):
            tbl[key][0] += 1
            tbl[key][1] += bool(bad)
        if bad:
            flagged.append((s, bad))
    print(f"시나리오 {len(scs)}개 x {a.runs}회, 턴 {a.turns}: Showdown {t1 - t0:.0f}s, 비교 {time.time() - t1:.0f}s, "
          f"불일치 시나리오 {len(flagged)}개, SD 오류 {errors}")

    def table(name, d):
        rows = sorted(((v[1] / v[0], v[1], v[0], k) for k, v in d.items() if v[1]), reverse=True)[:15]
        print(f"\n[{name}] 불일치 상위")
        for _, b, n, k in rows:
            print(f"  {k:24s} {b}/{n}")
    table("공격 측 첫 기술", by_move)
    table("공격 측 특성", by_ab)
    table("공격 측 도구", by_it)
    json.dump([dict(id=s["id"], teams=s["teams"], turns=s["turns"], bad=b) for s, b in flagged],
              open(os.path.join(OUT, "turns_mismatch.json"), "w"), default=str)
    if a.show:
        for s, bad in flagged[:25]:
            t0_, t1_ = s["teams"][0][0], s["teams"][1][0]
            print(f"\n== {s['id']}: {t0_['sid']}({t0_['ability']},{t0_['item']}) {s['turns'][0][0]} {t0_['moves']} "
                  f"vs {t1_['sid']}({t1_['ability']},{t1_['item']}) {s['turns'][0][1]} {t1_['moves']}")
            for k, p, x, y in bad[:6]:
                print(f"   {k}: p={p:.1e}\n     ours={x}\n     SD  ={y}")
    print(f"\n상세: {OUT}/turns_mismatch.json")


main()
