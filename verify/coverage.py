"""챔피언스에서 쓸 수 있는 모든 특성 / 도구 / 기술을 하나씩 골라 Showdown 과 분포 대조 (메타 비중과 무관하게 빠짐없이).
사용: python verify/coverage.py <ability|item|move> [항목당 시나리오 수] [runs] [turns] [seed] [이름 일부(필터)]
시나리오: 대상 항목을 가진 포켓몬(특성은 그 특성을 쓰는 종, 기술은 그 기술을 배우는 종)을 선두에 세우고, 상대는 메타 무작위 팀.
결과: 항목별 불일치 수를 표로 출력하고 verify/out/coverage_<종류>.json 에 상세를 남긴다."""
import json
import os
import random
import subprocess
import sys
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import verify_turns as vt
from ai.gamedata import GameData, connect, norm
from ai.meta import Meta
from ai.battle import Engine

KIND = sys.argv[1] if len(sys.argv) > 1 else "ability"
PER = int(sys.argv[2]) if len(sys.argv) > 2 else 6
RUNS = int(sys.argv[3]) if len(sys.argv) > 3 else 100
TURNS = int(sys.argv[4]) if len(sys.argv) > 4 else 3
SEED = int(sys.argv[5]) if len(sys.argv) > 5 else 1
FILT = norm(sys.argv[6]) if len(sys.argv) > 6 else ""
OUT = os.path.join(HERE, "out")
vt.MIN_TV, vt.MIN_KS = 0.15, 0.3

conn = connect()
data = GameData(conn)
meta = Meta(conn, data, 32)
eng = Engine(data)
sd = json.load(open(os.path.join(OUT, "sd_champions.json")))
SP = {k: v for k, v in sd["species"].items() if k in data.pokemon}
MEGA_POOL = set(eng.mega_map)
rng = random.Random(SEED)
ITEMS_OK = [k for k, v in sd["items"].items() if not v.get("isNonstandard")]
FILLER = ["protect", "swordsdance", "calmmind", "roost", "uturn", "earthquake", "surf", "flamethrower", "icebeam", "thunderbolt", "shadowball", "crunch", "closecombat"]


def generic_set(sid, ability=None, item=None, must=()):
    p = SP[sid]
    bs = p["baseStats"]
    phys = bs["atk"] >= bs["spa"]
    sp = {"hp": 2, "atk": 32 if phys else 0, "def": 0, "spa": 0 if phys else 32, "spd": 0, "spe": 32}
    if ability is None:
        ab = [a for k, a in p["abilities"].items()]
        ability = rng.choice(ab)
    legal = [m for m in p["learnset"] if m in data.moves]
    ms = [m for m in must if m in data.moves]
    pool = [m for m in legal if m not in ms]
    rng.shuffle(pool)
    for m in pool:
        if len(ms) >= 4:
            break
        ms.append(m)
    for m in FILLER:
        if len(ms) >= 4:
            break
        if m in data.moves and m not in ms:
            ms.append(m)
    return dict(sid=sid, ability=ability, item=item or "", nature="Adamant" if phys else "Modest", sp=sp, moves=ms[:4])


def display_item(ik):
    return sd["items"][ik]["name"]


def pick_action(team_lead, rng_, first_prefer):
    k = rng_.randrange(4)
    if first_prefer is not None and rng_.random() < 0.55:
        k = first_prefer
    a = ("m", k)
    if norm(team_lead.get("item", "")) in MEGA_POOL and rng_.random() < 0.4:
        a = ("M", k)
    return a


entries = []
if KIND == "ability":
    by = collections.defaultdict(list)
    for sid, v in SP.items():
        if v["name"].endswith("-Mega") or "Mega" in (v.get("forme") or ""):
            continue
        for a in set(v["abilities"].values()):
            by[a].append(sid)
    for a, sids in sorted(by.items()):
        if FILT and FILT not in norm(a):
            continue
        entries.append((a, sids))
elif KIND == "item":
    for ik in sorted(ITEMS_OK):
        if FILT and FILT not in ik:
            continue
        if sd["items"][ik].get("megaStone"):
            continue
        entries.append((display_item(ik), None))
else:
    seen = set()
    for sid, v in SP.items():
        for m in v["learnset"]:
            if m in data.moves:
                seen.add(m)
    for m in sorted(seen):
        if FILT and FILT not in m:
            continue
        entries.append((m, [sid for sid, v in SP.items() if m in v["learnset"] and not ("Mega" in (v.get("forme") or ""))]))

scs, owner = [], {}
for name, sids in entries:
    for r in range(PER):
        k = len(scs)
        if KIND == "ability":
            sid = rng.choice(sids)
            lead = generic_set(sid, ability=name, item=rng.choice(["Leftovers", "Sitrus Berry", "Life Orb", "Focus Sash", "", "Lum Berry"]))
            pref = None
        elif KIND == "item":
            sid = rng.choice(list(SP))
            while "Mega" in (SP[sid].get("forme") or "") or SP[sid]["tier"] == "Illegal":
                sid = rng.choice(list(SP))
            lead = generic_set(sid, item=name)
            pref = None
        else:
            sid = rng.choice(sids)
            lead = generic_set(sid, item=rng.choice(["Leftovers", "Sitrus Berry", "Life Orb", "", "Lum Berry"]), must=[name])
            pref = lead["moves"].index(name) if name in lead["moves"] else None
        t0, t1 = meta.random_team(rng), meta.random_team(rng)
        t0 = [lead] + t0[1:]
        turns = [[pick_action(t0[0], rng, pref), pick_action(t1[0], rng, None)] for _ in range(TURNS)]
        scs.append(dict(id=f"s{k}", teams=[t0, t1], turns=turns, key=name))
        owner[f"s{k}"] = name

W = 2
procs = []
for w in range(W):
    ch = scs[w::W]
    fin, fout = os.path.join(OUT, f"cov_in_{w}.json"), os.path.join(OUT, f"cov_sd_{w}.json")
    json.dump([dict(id=s["id"], teams=s["teams"], turns=s["turns"], runs=RUNS, seed=SEED) for s in ch], open(fin, "w"))
    procs.append((subprocess.Popen(["node", os.path.join(HERE, "sd_turns.js"), os.path.join(HERE, "..", "showdown"), fin, fout],
                                   stderr=subprocess.PIPE, text=True), fout))
sdr = {}
for p, fout in procs:
    _, err = p.communicate()
    if p.returncode:
        print(err[-1500:])
        sys.exit(1)
    sdr.update(json.load(open(fout)))

bad_by = collections.Counter()
tot_by = collections.Counter()
flagged, errors = [], collections.Counter()
for s in scs:
    r = sdr[s["id"]]
    nm = owner[s["id"]]
    tot_by[nm] += 1
    if "error" in r:
        errors[nm] += 1
        continue
    bad = vt.compare(vt.run_ours(eng, s, RUNS, SEED), r["results"], 1e-5)
    if bad:
        bad_by[nm] += 1
        flagged.append(dict(id=s["id"], key=nm, teams=s["teams"], turns=s["turns"], bad=bad))
print(f"[{KIND}] 항목 {len(entries)}개 x {PER} 시나리오, {TURNS}턴 x {RUNS}회: 불일치 시나리오 {len(flagged)}개, SD 오류 {sum(errors.values())}")
for nm, c in bad_by.most_common():
    print(f"  {nm}: {c}/{tot_by[nm]}")
if errors:
    print("  SD 오류 항목:", dict(errors))
json.dump(flagged, open(os.path.join(OUT, f"coverage_{KIND}.json"), "w"), default=str)
