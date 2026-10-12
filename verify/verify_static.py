"""DB(챔피언스) vs Showdown 챔피언스 모드 정적 데이터 비교.
사용: python -I verify_static.py [--db pokemon] [--json out/sd_champions.json] [--show 8]
출력은 항목별 요약 + 처음 N개 차이만 (토큰 절약)."""
import argparse, ast, json, os, re, sys
import pymysql

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("POKEMON_DB", "pokemon"))
ap.add_argument("--json", default=os.path.join(HERE, "out", "sd_champions.json"))
ap.add_argument("--show", type=int, default=8)
args = ap.parse_args()
norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower().replace("’", ""))

sd = json.load(open(args.json, encoding="utf-8"))
# PokeAPI 폼 이름 -> Showdown id 별칭 (etl/load_champions_legal.py 의 ALIAS)
src = open(os.path.join(HERE, "..", "etl", "load_champions_legal.py"), encoding="utf-8").read()
alias_node = next(n for n in ast.parse(src).body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "ALIAS")
ALIAS = ast.literal_eval(alias_node.value)            # showdown id -> PokeAPI name
REV = {norm(v): k for k, v in ALIAS.items()}           # PokeAPI(norm) -> showdown id

db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"], database=args.db, charset="utf8mb4")
cur = db.cursor()
cur.execute("select game_id from game where code='CHAMPIONS'")
CG = cur.fetchone()[0]
results = []
# 비교 도구의 한계로 생기는 오탐 (사유 명시)
KNOWN_FALSE = {
    "direclaw": "확률 상태이상이 데이터가 아니라 코드(onHit)로 구현됨(무작위 독/마비/잠듦 30%)",
    "curse": "챔피언스는 volatileStatus 대신 onHit 코드로 구현했지만 효과는 같음",
}
IGNORE_DB_ONLY_SPECIES = {"aegislashblade", "castformrainy", "castformsnowy", "castformsunny"}      # 전투 중 폼(선택 불가)
IGNORE_SD_ONLY_SPECIES = {"mausholdfour", "polteageistantique", "sinistchamasterpiece", "vivillonfancy", "vivillonpokeball"}  # 외형만 다른 폼
IGNORE_ABILITIES = {"battlebond"}   # 개구리의 폼 전용(선택 불가 폼)


def report(title, diffs, total):
    results.append((title, len(diffs), total))
    print(f"\n[{'OK' if not diffs else '차이'}] {title}: {len(diffs)}/{total}")
    for d in diffs[: args.show]:
        print("   ", d)
    if len(diffs) > args.show:
        print(f"    ... 외 {len(diffs) - args.show}건")


# ───── DB 로딩 ─────
sys.path.insert(0, os.path.join(HERE, "..", "etl"))
cache = os.path.join(HERE, "..", "etl", "cache")
from fetch import get as _get   # etl/fetch.py (PokeAPI 캐시; 없으면 받아옴)
def api_name(pid):
    return _get(f"pokemon/{pid}")["name"]

cur.execute("""select p.pokemon_id, p.base_hp,p.base_atk,p.base_def,p.base_spa,p.base_spd,p.base_spe, t1.name_en, t2.name_en, gp.tier
               from game_pokemon gp join pokemon p using(pokemon_id) join type t1 on t1.type_id=p.type1_id
               left join type t2 on t2.type_id=p.type2_id where gp.game_id=%s""", (CG,))
dbp = {}
for pid, hp, at, df, sa, sd_, sp, t1, t2, tier in cur.fetchall():
    n = norm(api_name(pid))
    sid = REV.get(n, n)
    dbp[sid] = dict(pid=pid, stats=dict(hp=hp, atk=at, def_=df, spa=sa, spd=sd_, spe=sp), types=[t1] + ([t2] if t2 else []), tier=tier)

# ───── 1. 종 목록 ─────
sd_ids = set(sd["species"])
only_db = sorted(set(dbp) - sd_ids - IGNORE_DB_ONLY_SPECIES)
only_sd = sorted(sd_ids - set(dbp) - IGNORE_SD_ONLY_SPECIES)
report("사용 가능 포켓몬 목록 일치 (DB에만)", [f"DB에만: {x}" for x in only_db], len(dbp))
report("사용 가능 포켓몬 목록 일치 (Showdown에만)", [f"Showdown에만: {x} ({sd['species'][x]['name']}, tier={sd['species'][x]['tier']})" for x in only_sd], len(sd_ids))

# ───── 2. 종족값 / 타입 / 특성 ─────
cur.execute("""select pa.pokemon_id, pa.slot, a.name_en from pokemon_ability pa join ability a using(ability_id) where pa.game_id=%s""", (CG,))
ab = {}
for pid, slot, name in cur.fetchall():
    ab.setdefault(pid, {})[slot] = name
diffs_s, diffs_t, diffs_a = [], [], []
common = sorted(set(dbp) & sd_ids)
for sid in common:
    d, s = dbp[sid], sd["species"][sid]
    b = s["baseStats"]
    ssd = dict(hp=b["hp"], atk=b["atk"], def_=b["def"], spa=b["spa"], spd=b["spd"], spe=b["spe"])
    if d["stats"] != ssd:
        diffs_s.append((sid, d["stats"], ssd))
    if sorted(d["types"]) != sorted(s["types"]):
        diffs_t.append((sid, d["types"], s["types"]))
    sa = {{"0": "1", "1": "2", "H": "hidden"}[k]: v for k, v in s["abilities"].items() if k in ("0", "1", "H")}
    da = ab.get(d["pid"], {})
    if {k: norm(v) for k, v in da.items()} != {k: norm(v) for k, v in sa.items()}:
        diffs_a.append((sid, da, sa))
report("종족값", diffs_s, len(common)); report("타입", diffs_t, len(common)); report("특성 슬롯", diffs_a, len(common))

# ───── 3. 습득 기술 ─────
cur.execute("select pm.pokemon_id, m.name_en from pokemon_move pm join move m using(move_id) where pm.game_id=%s", (CG,))
dbl = {}
for pid, n in cur.fetchall():
    dbl.setdefault(pid, set()).add(norm(n))
diffs_l = []
for sid in common:
    dset = dbl.get(dbp[sid]["pid"], set())
    sset = set(sd["species"][sid]["learnset"])
    if dset != sset:
        diffs_l.append((sid, f"DB만 {len(dset - sset)}: {sorted(dset - sset)[:4]}", f"SD만 {len(sset - dset)}: {sorted(sset - dset)[:4]}"))
report("습득 기술 목록(종별)", diffs_l, len(common))

# ───── 4. 기술 수치 ─────
cur.execute("""select m.move_id, m.name_en, t.name_en, m.category, m.power, m.accuracy, m.pp, m.priority, m.target,
       g.power_override, g.accuracy_override, g.pp_override, ot.name_en, m.crit_stage, m.min_hits, m.max_hits,
       m.drain_pct, m.recoil_pct, m.heal_pct, g.target_override
       from game_move g join move m using(move_id) join type t on t.type_id=m.type_id left join type ot on ot.type_id=g.type_override
       where g.game_id=%s""", (CG,))
dbm = {}
for r in cur.fetchall():
    mid, name, typ, cat, pw, acc, pp, pr, tg, po, ao, ppo, ot, crit, mn, mx, dr, rc, hl, tgo = r
    dbm[norm(name)] = dict(mid=mid, type=ot or typ, category=cat.capitalize(), bp=po if po is not None else (pw or 0),
                           acc=(None if ao == 255 else ao) if ao is not None else acc, pp=ppo if ppo is not None else pp, priority=pr, target=tgo or tg,
                           crit=crit, hits=(mn, mx), drain=dr, recoil=rc, heal=hl)
cur.execute("select move_id, flag from move_flag where game_id in (0,%s)", (CG,))
flags = {}
for mid, f in cur.fetchall():
    flags.setdefault(mid, set()).add(f)
# 챔피언스 전용 플래그 행이 있으면 그 행만 사용
cur.execute("select move_id, flag from move_flag where game_id=%s", (CG,))
over = {}
for mid, f in cur.fetchall():
    over.setdefault(mid, set()).add(f)
smoves = {norm(v["name"]): v for v in sd["moves"].values()}
d_num, d_flag, d_extra = [], [], []
miss = [n for n in dbm if n not in smoves]
for n, d in dbm.items():
    s = smoves.get(n)
    if not s:
        continue
    sacc = None if s["accuracy"] is True else s["accuracy"]
    chk = [("타입", d["type"], s["type"]), ("분류", d["category"], s["category"]), ("위력", d["bp"], s["basePower"]),
           ("명중", d["acc"], sacc), ("PP", d["pp"], s["pp"]), ("우선도", d["priority"], s["priority"]),
           ("대상", d["target"], s["target"])]
    bad = [f"{k}:DB={a}/SD={b}" for k, a, b in chk if a != b]
    if bad:
        d_num.append((n, bad))
    fl = over.get(d["mid"]) or (flags.get(d["mid"], set()) - {"nosketch"})
    sfl = set(s["flags"]) - {"nosketch"}
    if set(fl) - {"nosketch"} != sfl:
        d_flag.append((n, f"DB만 {sorted(set(fl) - sfl)}", f"SD만 {sorted(sfl - set(fl))}"))
    sc = max(0, (s["critRatio"] or 1) - 1)
    sh = s["multihit"]
    shits = (sh, sh) if isinstance(sh, int) else (tuple(sh) if sh else (1, 1))
    pct = lambda x: round(100 * x[0] / x[1]) if x else 0
    ex = [f"{k}:DB={a}/SD={b}" for k, a, b in
          [("급소", d["crit"], sc), ("연속", d["hits"], shits), ("흡수%", d["drain"], pct(s["drain"])),
           ("반동%", d["recoil"], pct(s["recoil"])), ("회복%", d["heal"], pct(s["heal"]))] if a != b]
    if ex:
        d_extra.append((n, ex))
report("기술 DB에는 있는데 Showdown에 없음", [f"{n}" for n in miss], len(dbm))
report("기술 기본 수치(타입/분류/위력/명중/PP/우선도/대상, 챔피언스 반영)", d_num, len(dbm))
report("기술 플래그(챔피언스 반영)", d_flag, len(dbm))
report("기술 급소/연속/흡수/반동/회복", d_extra, len(dbm))

# ───── 5. 기술 부가효과 (확률 부가효과 + 능력 변화) ─────
cur.execute("select game_id, move_id from game_move where game_id=%s and effects_overridden=1", (CG,))
ovr_moves = {r[1] for r in cur.fetchall()}
cur.execute("select move_id, game_id, trigger_type, applies_to, kind, code, stages, chance_pct from move_effect")
eff = {}
for mid, gid, trig, who, kind, code, stg, ch in cur.fetchall():
    if kind not in ("status", "volatile", "stat_stage"):
        continue
    use_game = CG if mid in ovr_moves else 0
    if gid != use_game:
        continue
    eff.setdefault(mid, set()).add((trig, who, kind, code, None if stg is None else int(stg), int(ch)))
d_eff = []
for n, d in dbm.items():
    s = smoves.get(n)
    if not s:
        continue
    exp = set()
    sec = ([s["secondary"]] if s["secondary"] else []) + (s["secondaries"] or [])
    tgt_self = s["target"] == "self"
    for x in sec:
        ch = int(x.get("chance") or 100)
        if x.get("status"): exp.add(("secondary", "target", "status", x["status"], None, ch))
        if x.get("volatileStatus"): exp.add(("secondary", "target", "volatile", x["volatileStatus"], None, ch))
        for k, v in (x.get("boosts") or {}).items(): exp.add(("secondary", "target", "stat_stage", k, int(v), ch))
        if isinstance(x.get("self"), dict):
            for k, v in x["self"].items(): exp.add(("primary", "self", "stat_stage", k, int(v), ch)) if False else exp.add(("secondary", "self", "stat_stage", k, int(v), ch))
    who = "self" if tgt_self else "target"
    if s.get("selfVolatile"): exp.add(("primary", "self", "volatile", s["selfVolatile"], None, 100))
    if s["status"]: exp.add(("primary", who, "status", s["status"], None, 100))
    if s["volatileStatus"]: exp.add(("primary", who, "volatile", s["volatileStatus"], None, 100))
    for k, v in (s["boosts"] or {}).items(): exp.add(("primary", who, "stat_stage", k, int(v), 100))
    for k, v in (s["selfBoosts"] or {}).items(): exp.add(("primary", "self", "stat_stage", k, int(v), 100))
    got = eff.get(d["mid"], set())
    # 챔피언스 오버라이드 행은 loader가 수동으로 넣어서 형식이 다를 수 있음 -> 정규화 비교
    if got != exp and n not in KNOWN_FALSE:
        d_eff.append((n, f"DB만 {sorted(got - exp)[:3]}", f"SD만 {sorted(exp - got)[:3]}"))
report("기술 부가효과(상태/능력 변화/확률)", d_eff, len(dbm))
print("   (오탐으로 제외:", ", ".join(f"{k}={v}" for k, v in KNOWN_FALSE.items()), ")")

# ───── 6. 아이템 / 특성 / 상성 / 성격 ─────
cur.execute("select i.name_en from game_item gi join item i using(item_id) where gi.game_id=%s", (CG,))
dbi = {norm(r[0]) for r in cur.fetchall()}
sdi = {norm(v["name"]) for v in sd["items"].values() if not v["isNonstandard"]}
report("사용 가능 아이템 목록", [f"DB만 {sorted(dbi - sdi)}", f"SD만 {sorted(sdi - dbi)}"] if dbi != sdi else [], len(dbi))
cur.execute("select distinct a.name_en from pokemon_ability pa join ability a using(ability_id) where pa.game_id=%s", (CG,))
dba = {norm(r[0]) for r in cur.fetchall()}
sda = {norm(n) for s in sd["species"].values() for k, n in s["abilities"].items()} - IGNORE_ABILITIES
report("사용 가능 특성 목록", [f"DB만 {sorted(dba - sda)}", f"SD만 {sorted(sda - dba)}"] if dba != sda else [], len(dba))
cur.execute("select a.name_en, d.name_en, e.multiplier from type_efficacy e join type a on a.type_id=e.attack_type_id join type d on d.type_id=e.defense_type_id")
dbt = {(a.lower(), d.lower()): float(m) for a, d, m in cur.fetchall()}
cur.execute("select name_en from type")
types = [r[0].lower() for r in cur.fetchall()]
code2mul = {0: 1.0, 1: 2.0, 2: 0.5, 3: 0.0}
d_t = []
for dtype, info in sd["typechart"].items():
    for atype in types:
        a = atype.capitalize()
        sdm = code2mul[info.get(a, 0)]
        dm = dbt.get((atype, dtype), 1.0)
        if sdm != dm and dtype in types:
            d_t.append((atype, dtype, dm, sdm))
report("타입 상성표", d_t, len(types) ** 2)
cur.execute("select name_en, plus_stat, minus_stat from nature")
dn = {norm(n): (p, m) for n, p, m in cur.fetchall()}
d_n = [(k, dn.get(k), (v["plus"], v["minus"])) for k, v in sd["natures"].items() if dn.get(k) != (v["plus"], v["minus"])]
report("성격", d_n, len(sd["natures"]))

print("\n요약:", ", ".join(f"{t}={n}" for t, n, _ in results if n))
print("차이 0건" if not any(n for _, n, _ in results) else "차이 있는 항목 있음")
