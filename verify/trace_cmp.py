"""사건 순서 비교: 1턴 동안 일어난 사건(피해/회복/상태이상/능력변화/도구소모/교체)의 '순서열' 분포를 Showdown 과 우리 엔진에서 비교한다.
최종 상태 분포 비교(verify_turns.py)가 놓치는 '처리 순서' 불일치(누가 먼저 맞았는가, 부가효과/특성 발동 순서 등)를 잡는다.
사용: python -m verify.trace_cmp --n 300 --runs 200 [--turns 1] [--seed 1] [--show 10]
Showdown 쪽은 SD_LOG=1 로 프로토콜 로그를 받아 '|turn|1' ~ '|turn|2' 사이만 토큰화한다."""
import argparse
import collections
import json
import os
import random
import subprocess
import sys

import numpy as np
from scipy.stats import chi2_contingency

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from ai.battle import Engine
from ai.gamedata import GameData, connect, norm
from ai.meta import Meta
from verify.verify_turns import make_scenarios

OUT = os.path.join(HERE, "out")
SIDE = {"p1": 0, "p2": 1}


def sd_tokens(log, turn=1):
    toks, on, skip = [], False, False
    for ln in log.split("\n"):
        if skip:             # |split| 다음 줄은 비공개(실제 HP) 판 — 공개 판 한 줄만 쓴다
            skip = False
            continue
        p = ln.split("|")
        if len(p) < 2:
            continue
        k = p[1]
        if k == "split":
            skip = True
            continue
        if k == "turn":
            if int(p[2]) == turn:
                on = True
                continue
            if on:
                break
        if not on:
            continue
        side = SIDE.get(p[2][:2]) if len(p) > 2 else None
        if k == "-damage" and side is not None:
            toks.append(("dmg", side, ""))
        elif k == "-heal" and side is not None:
            toks.append(("heal", side, ""))
        elif k == "-status":
            toks.append(("status", side, p[3]))
        elif k in ("-boost", "-unboost"):
            toks.append((k[1:], side, p[3]))
        elif k in ("switch", "drag"):
            toks.append(("switch", side, ""))
        elif k == "-enditem":
            toks.append(("item", side, ""))
    return norm_seq(toks)


def norm_seq(toks):
    """토큰화 세밀도 차이를 없앤다: 같은 사건이 연속되면 하나로(연속기/디스가이즈 추가 피해 등), 같은 쪽의 '도구소모→회복'은 '회복→도구소모' 로(열매)"""
    out = []
    for t in toks:
        if t[0] == "item":           # 도구 소모는 엔진 여러 곳에서 직접 비워서 추적이 불완전하다 -> 비교에서 제외
            continue
        if out and out[-1] == t:
            continue
        out.append(t)
    i = 0
    while i < len(out):               # 연속된 능력치 변화는 순서가 달라도 같은 것으로 본다 (서로 독립)
        j = i
        while j < len(out) and out[j][0] in ("boost", "unboost"):
            j += 1
        if j - i > 1:
            out[i:j] = sorted(out[i:j], key=str)
        i = max(j, i + 1)
    i = 0
    while i + 1 < len(out):
        if out[i][0] == "item" and out[i + 1][0] == "heal" and out[i][1] == out[i + 1][1]:
            out[i], out[i + 1] = out[i + 1], out[i]
            i += 2
        else:
            i += 1
    return tuple(out)


def our_tokens(eng, sc, r, seed, turn_idx=0):
    rng = random.Random(seed * 100003 + r)
    st = eng.new_state(sc["teams"][0], sc["teams"][1], rng=rng)
    for k, turn in enumerate(sc["turns"]):
        if st.winner is not None:
            break
        acts = []
        for i in (0, 1):
            a = tuple(turn[i])
            legal = eng.legal_actions(st, i)
            acts.append(a if a in legal else legal[0])
        st.trace = [] if k == turn_idx else None
        eng.step(st, acts, rng, None)
        if k == turn_idx:
            return norm_seq(st.trace)
    return ()


def fmt(seq):
    return " ".join(f"{k}{s if s is not None else ''}{':' + x if x else ''}" for k, s, x in seq) or "(없음)"


def compare(a, b, min_tv):
    """두 순서열 분포(Counter) 비교 -> (p값, 총변동거리) 또는 None"""
    keys = sorted(set(a) | set(b), key=lambda k: -(a[k] + b[k]))
    na, nb = sum(a.values()), sum(b.values())
    tv = 0.5 * sum(abs(a[k] / na - b[k] / nb) for k in keys)
    if tv < min_tv:
        return None
    big = [k for k in keys if a[k] + b[k] >= 10]
    rest = [k for k in keys if k not in big]
    rows = [[a[k] for k in big] + [sum(a[k] for k in rest)], [b[k] for k in big] + [sum(b[k] for k in rest)]]
    rows = np.array(rows)
    rows = rows[:, rows.sum(axis=0) > 0]
    if rows.shape[1] < 2:
        return None
    p = chi2_contingency(rows)[1]
    return p, tv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--runs", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--snap", type=int, default=33)
    ap.add_argument("--min-tv", type=float, default=0.12)
    ap.add_argument("--alpha", type=float, default=1e-5)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--show", type=int, default=10)
    a = ap.parse_args()
    conn = connect()
    data = GameData(conn)
    meta = Meta(conn, data, a.snap)
    scs = make_scenarios(meta, data, a.n, 1, a.seed)
    os.makedirs(OUT, exist_ok=True)
    procs = []
    for w in range(a.workers):
        ch = scs[w::a.workers]
        fin, fout = os.path.join(OUT, f"trace_in_{w}.json"), os.path.join(OUT, f"trace_sd_{w}.json")
        json.dump([dict(id=s["id"], teams=s["teams"], turns=s["turns"], runs=a.runs, seed=a.seed) for s in ch], open(fin, "w"))
        procs.append((subprocess.Popen(["node", os.path.join(HERE, "sd_turns.js"), os.path.join(HERE, "..", "showdown"), fin, fout],
                                       stderr=subprocess.PIPE, text=True, env=dict(os.environ, SD_LOG="2")), fout))
    sd = {}
    for pr, fout in procs:
        _, err = pr.communicate()
        if pr.returncode:
            print(err[-1500:])
            sys.exit(1)
        sd.update(json.load(open(fout)))
    eng = Engine(data)
    flagged = []
    for s in scs:
        r = sd[s["id"]]
        if "error" in r:
            continue
        A = collections.Counter(sd_tokens(x["log"]) for x in r["results"])
        B = collections.Counter(our_tokens(eng, s, k, a.seed) for k in range(a.runs))
        c = compare(A, B, a.min_tv)
        if c and c[0] < a.alpha:
            flagged.append((s, A, B, c))
    print(f"[trace] 시나리오 {len(scs)}개 x {a.runs}회: 순서열 분포 불일치 {len(flagged)}개")
    for s, A, B, c in flagged[:a.show]:
        t0, t1 = s["teams"][0][0], s["teams"][1][0]
        print(f"== {s['id']} {t0['sid']}/{t0['ability']}/{t0['item']} {t0['moves']} vs {t1['sid']}/{t1['ability']}/{t1['item']} {t1['moves']} acts={s['turns'][0]} p={c[0]:.1e} tv={c[1]:.2f}")
        keys = sorted(set(A) | set(B), key=lambda k: -abs(A[k] - B[k]))[:4]
        for k in keys:
            print(f"   SD {A[k]:4d} / ours {B[k]:4d}  {fmt(k)}")
    json.dump([dict(id=s["id"], teams=s["teams"], turns=s["turns"], p=c[0], tv=c[1]) for s, _, _, c in flagged],
              open(os.path.join(OUT, "trace_mismatch.json"), "w"), default=str)


if __name__ == "__main__":
    main()
