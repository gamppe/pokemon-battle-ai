"""DB 데미지 계산기(ai/damage_calc.py) vs Showdown(챔피언스 모드) 데미지 비교.
사용: python -X utf8 verify_damage.py [--n 3000] [--seed 1] [--db pokemon] [--show 25]
무작위 시나리오(포켓몬·특성·도구·SP·날씨·필드·상태·벽·급소)를 만들어 양쪽에서 16단계 난수 데미지를 계산하고,
일치율과 불일치가 많은 규칙(특성/도구/기술 규칙)을 집계한다."""
import argparse, collections, json, os, random, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from ai.damage_calc import Field, calc
from ai.gamedata import GameData, connect, norm

ap = argparse.ArgumentParser()
ap.add_argument("--n", type=int, default=3000)
ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--db", default=os.environ.get("POKEMON_DB", "pokemon"))
ap.add_argument("--show", type=int, default=25)
ap.add_argument("--only", default="", help="이 문자열이 효과 이름에 포함된 시나리오만 강조 생성(예: ability:Technician)")
args = ap.parse_args()
rnd = random.Random(args.seed)
data_conn = connect(args.db)
data = GameData(data_conn)

DMG_HOOKS = {"modify_bp", "modify_atk", "modify_def", "modify_dmg_dealt", "modify_dmg_taken", "modify_stab", "modify_move_type",
             "modify_atk_foe", "modify_bp_foe"}
atk_abilities = sorted(n for n, rows in data.ability_fx.items() if any(r["hook"] in DMG_HOOKS - {"modify_def"} for r in rows))
def_abilities = sorted(n for n, rows in data.ability_fx.items() if any(r["hook"] in {"modify_def", "modify_dmg_taken", "modify_atk_foe", "modify_bp_foe"} for r in rows)
                       or any(r["code"] and "type:Ground" in r["code"] for r in rows))
atk_items = sorted(n for n, rows in data.item_fx.items() if any(r["hook"] in DMG_HOOKS - {"modify_def"} for r in rows))
def_items = sorted(n for n, rows in data.item_fx.items() if any(r["hook"] in {"modify_def", "modify_dmg_taken"} for r in rows) or n == "airballoon")
# 표시용 원래 이름
ab_name, it_name = {}, {}
for n, rows in data.ability_fx.items():
    ab_name[n] = rows[0]["label"].split(":", 1)[1]
for n, rows in data.item_fx.items():
    it_name[n] = rows[0]["label"].split(":", 1)[1]
sids = sorted(x for x in data.pokemon if x not in {"aegislashblade", "castformrainy", "castformsnowy", "castformsunny"})
NATURES = sorted(data.natures)
SD_WEATHER = {"rain": "raindance", "sun": "sunnyday", "sand": "sandstorm", "snow": "snowscape"}
SD_TERRAIN = {"electric": "electricterrain", "grassy": "grassyterrain", "misty": "mistyterrain", "psychic": "psychicterrain"}
SD_SCREEN = {"reflect": "reflect", "light_screen": "lightscreen", "aurora_veil": "auroraveil"}
damaging = {k: m for k, m in data.moves.items() if m["category"] != "status" and (m["bp"] > 0 or any(r["type"] == "power_formula" for r in m["rules"]))}
rule_moves = [k for k, m in damaging.items() if any(r["type"] in ("power_mult_if", "power_formula", "type_by_condition") for r in m["rules"])]


def rand_sp():
    left, sp = 66, {}
    for k in rnd.sample(["hp", "atk", "def", "spa", "spd", "spe"], rnd.randint(1, 4)):
        v = rnd.randint(0, min(32, left)); sp[k] = v; left -= v
    return sp


def rand_side(is_attacker):
    sid = rnd.choice(sids)
    p = data.pokemon[sid]
    if is_attacker:
        pool = sorted(m for m in p["learn"] if m in damaging)
    own = list(p["abilities"].values())
    ab_pool, it_pool = (atk_abilities, atk_items) if is_attacker else (def_abilities, def_items)
    ability = ab_name[rnd.choice(ab_pool)] if rnd.random() < 0.65 else rnd.choice(own)
    item = it_name[rnd.choice(it_pool)] if rnd.random() < 0.55 else ""
    side = dict(sid=sid, ability=ability, item=item, nature=rnd.choice(NATURES), sp=rand_sp(), boosts={}, status=None, hp_frac=None,
                gender=rnd.choice(["N", "M", "F"]))
    if rnd.random() < 0.2:
        side["boosts"]["spe"] = rnd.choice([-1, 1, 2])
    if rnd.random() < 0.25:
        for k in rnd.sample(["atk", "def", "spa", "spd"], rnd.randint(1, 2)):
            side["boosts"][k] = rnd.choice([-2, -1, 1, 2, 3])
    if rnd.random() < 0.2:
        side["status"] = rnd.choice(["brn", "par", "psn", "slp"] if is_attacker else ["brn", "par", "psn", "slp", "frz"])
    if rnd.random() < 0.3:
        side["hp_frac"] = rnd.choice([0.1, 0.2, 0.3, 0.33, 0.34, 0.5, 0.75])
    return side, (pool if is_attacker else None)


cases = []
tries = 0
while len(cases) < args.n and tries < args.n * 20:
    tries += 1
    a, pool = rand_side(True)
    if not pool:
        continue
    if rnd.random() < 0.35 and any(m in rule_moves for m in pool):
        move = rnd.choice([m for m in pool if m in rule_moves])
    else:
        move = rnd.choice(pool)
    d, _ = rand_side(False)
    c = dict(id=f"c{len(cases)}", atk=a, **{"def": d}, move=move, crit=rnd.random() < 0.2,
             weather=rnd.choice(list(SD_WEATHER)) if rnd.random() < 0.3 else None,
             terrain=rnd.choice(list(SD_TERRAIN)) if rnd.random() < 0.25 else None,
             screens=[rnd.choice(list(SD_SCREEN))] if rnd.random() < 0.2 else [],
             hit=rnd.randint(1, 3) if move == "tripleaxel" else None, proc=(rnd.random() < 0.5) if move == "ficklebeam" else None)
    if args.only and args.only.lower() not in (norm(a["ability"]) + norm(a["item"]) + norm(d["ability"]) + norm(d["item"]) + move):
        continue
    cases.append(c)

# Showdown 입력으로 변환
sd_cases = []
for c in cases:
    def side(s):
        return dict(species=s["sid"], ability=s["ability"], item=s["item"], nature=s["nature"], sp=s["sp"], boosts=s["boosts"],
                    status=s["status"], hp_frac=s["hp_frac"], gender=s["gender"])
    sd_cases.append(dict(id=c["id"], atk=side(c["atk"]), **{"def": side(c["def"])}, move=c["move"], crit=c["crit"],
                         weather=SD_WEATHER.get(c["weather"]), terrain=SD_TERRAIN.get(c["terrain"]),
                         screens=[SD_SCREEN[s] for s in c["screens"]],
                         **({"hit": c["hit"]} if c["hit"] else {}), **({"proc": c["proc"]} if c["proc"] is not None else {})))
out_dir = os.path.join(HERE, "out"); os.makedirs(out_dir, exist_ok=True)
cp, rp = os.path.join(out_dir, "dmg_cases.json"), os.path.join(out_dir, "dmg_sd.json")
json.dump(sd_cases, open(cp, "w", encoding="utf-8"))
subprocess.run(["node", os.path.join(HERE, "sd_damage.js"), os.path.join(HERE, "..", "showdown"), cp, rp], check=True, capture_output=True)
sd = json.load(open(rp, encoding="utf-8"))

stat = collections.Counter()
by_label = collections.defaultdict(lambda: [0, 0])   # label -> [사용 횟수, 불일치 횟수]
examples = {}
mismatches = []
stage_by_label = collections.defaultdict(collections.Counter)
for c in cases:
    s = sd[c["id"]]
    if "error" in s:
        stat["showdown_error"] += 1; examples.setdefault("showdown_error", (c, s["error"])); continue
    F = Field(weather=c["weather"], terrain=c["terrain"], screens=tuple(c["screens"]))
    try:
        r = calc(data, c["atk"], c["def"], c["move"], F, c["crit"], hit=c["hit"] or 1, proc=c["proc"])
    except Exception as e:  # 계산기 버그
        stat["calc_exception"] += 1; examples.setdefault("calc_exception", (c, repr(e))); continue
    if r["unsupported"]:
        stat["unsupported"] += 1
        for u in r["unsupported"]:
            stat["u:" + u.split(":")[0] + ":" + u.split(":", 1)[-1][:40]] += 1
        continue
    if s.get("immune"):
        ok = r["rolls"] is None and r["reason"] == ("fail" if s.get("failed") else "immune")
        stat["immune_ok" if ok else "immune_mismatch"] += 1
        if not ok:
            mismatches.append((c, r, s));
        continue
    if r["rolls"] is None:
        stat["calc_none_sd_damage"] += 1; mismatches.append((c, r, s)); continue
    ok = r["rolls"] == s["rolls"]
    if not ok:
        mid, smid = r["mid"], s["mid"]
        stage = ("moveType" if mid["moveType"] != smid["moveType"] else "bp" if mid["bp"] != smid["bp"] else
                 "typeMod" if mid["typeMod"] != smid["typeMod"] else "later(스탯/최종 보정)")
        stat["stage:" + stage] += 1
        for lab in (r["used"] or ["(기본)"]):
            stage_by_label[lab][stage] += 1
    stat["match" if ok else "mismatch"] += 1
    for lab in (r["used"] or ["(효과 없음: 기본 공식)"]):
        by_label[lab][0] += 1
        if not ok:
            by_label[lab][1] += 1
    if not ok:
        mismatches.append((c, r, s))
        for lab in (r["used"] or ["(효과 없음: 기본 공식)"]):
            examples.setdefault(lab, (c, r["rolls"][0], r["rolls"][-1], s["rolls"][0], s["rolls"][-1]))

total_cmp = stat["match"] + stat["mismatch"]
bad_total = stat["mismatch"] + stat["immune_mismatch"] + stat["calc_none_sd_damage"]
print(f"시나리오 {len(cases)}개 | 비교 가능 {total_cmp + stat['immune_ok'] + stat['immune_mismatch']} | 완전 일치 {stat['match']} / 불일치 {bad_total}"
      f" ({100 * stat['match'] / max(1, total_cmp):.1f}% 일치)")
for k in ("stage:moveType", "stage:bp", "stage:typeMod", "stage:later(스탯/최종 보정)", "immune_ok", "immune_mismatch", "calc_none_sd_damage", "unsupported", "showdown_error", "calc_exception"):
    print(f"  {k}: {stat[k]}")
print("\n[규칙별 불일치] (사용 횟수 / 불일치) - 불일치 많은 순")
rows = sorted(((l, v) for l, v in by_label.items() if v[1] > 0), key=lambda x: (-x[1][1], x[0]))
for l, (n, m) in rows[: args.show]:
    ex = examples[l]
    st = ",".join(f"{k.split('(')[0]}{v}" for k, v in stage_by_label[l].most_common(2))
    print(f"  {l:40s} {n:5d} / {m:4d} [{st}]  예) DB {ex[1]}~{ex[2]} vs SD {ex[3]}~{ex[4]}")
print(f"\n불일치 없는 규칙 수: {sum(1 for v in by_label.values() if v[1] == 0)} / {len(by_label)}")
# 한 번도 활성화되지 않아 검증하지 못한 효과 (시나리오를 늘리거나 --only 로 집중 생성)
all_labels = set()
for src, pre in ((data.ability_fx, "ability:"), (data.item_fx, "item:")):
    for rows in src.values():
        for r in rows:
            if r["hook"] in DMG_HOOKS and r["kind"] == "mult":
                all_labels.add(r["label"])
for st in ("rain", "sun", "sand", "snow", "reflect", "light_screen", "aurora_veil", "electric_terrain", "grassy_terrain", "misty_terrain", "psychic_terrain"):
    for r in data.state_fx.get(st, []):
        if r["hook"] in DMG_HOOKS and r["kind"] == "mult":
            all_labels.add(r["label"])
for m in data.moves.values():
    if any(x["type"] in ("power_mult_if", "power_formula") for x in m["rules"]):
        all_labels.add("move_rule:" + m["name"])
untested = sorted(all_labels - set(by_label))
# 미지원 사유가 붙은 효과 이름 모으기 (왜 검증을 못 했는지 구분)
unsup_labels = set()
for k in stat:
    if k.startswith("u:"):
        unsup_labels.add(k[2:].split(":")[1] if k.count(":") >= 2 else k[2:])
_cur = data_conn.cursor()
def KO_NAME(label):
    kind, _, name = label.partition(":")
    q = {"ability": "select name_ko from ability where name_en=%s", "item": "select name_ko from item where name_en=%s",
         "move_rule": "select name_ko from move where name_en=%s", "state": "select name_ko from battle_state where code=%s"}[kind]
    _cur.execute(q, (name,))
    r = _cur.fetchone()
    return (r["name_ko"] if r else name)
untested_ko = [(l, KO_NAME(l)) for l in untested]
json.dump(untested_ko, open(os.path.join(out_dir, "untested.json"), "w", encoding="utf-8"), ensure_ascii=False)
print(f"\n[검증되지 않은 효과] {len(untested)}/{len(all_labels)}: " + ", ".join(untested))
top_u = [(k[2:], v) for k, v in stat.items() if k.startswith("u:")]
top_u.sort(key=lambda x: -x[1])
print("미지원(건너뜀) 상위:", "; ".join(f"{k}×{v}" for k, v in top_u[:8]))
json.dump([dict(case=c, db=r, sd=s) for c, r, s in mismatches], open(os.path.join(out_dir, "dmg_mismatch.json"), "w", encoding="utf-8"), ensure_ascii=False)
