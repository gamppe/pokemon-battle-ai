"""Showdown moves.json -> move 컬럼 / move_flag / move_effect (AI용 수치화).
챔피언스 모드(mods/champions/moves.ts)의 수치 변경은 game_move 덮어쓰기로 반영."""
import os, re, json, pymysql
norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
SD = json.load(open(os.path.join(os.path.dirname(__file__), "cache_sd_moves.json"), encoding="utf-8"))
db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"], database=os.environ.get("POKEMON_DB", "pokemon"), charset="utf8mb4")
cur = db.cursor()

cols = [  # (name, ddl)
 ("target", "VARCHAR(20) NULL"), ("crit_stage", "TINYINT NOT NULL DEFAULT 0"), ("always_crit", "BOOL NOT NULL DEFAULT 0"),
 ("min_hits", "TINYINT UNSIGNED NOT NULL DEFAULT 1"), ("max_hits", "TINYINT UNSIGNED NOT NULL DEFAULT 1"),
 ("drain_pct", "TINYINT UNSIGNED NOT NULL DEFAULT 0"), ("recoil_pct", "TINYINT UNSIGNED NOT NULL DEFAULT 0"),
 ("heal_pct", "TINYINT UNSIGNED NOT NULL DEFAULT 0"), ("self_switch", "BOOL NOT NULL DEFAULT 0"),
 ("force_switch", "BOOL NOT NULL DEFAULT 0"), ("self_destruct", "BOOL NOT NULL DEFAULT 0"), ("ohko", "BOOL NOT NULL DEFAULT 0"),
 ("fixed_damage", "SMALLINT NULL"), ("extra", "JSON NULL"),
]
for n, ddl in cols:
    try: cur.execute(f"ALTER TABLE move ADD COLUMN {n} {ddl}")
    except pymysql.err.OperationalError as e:
        if e.args[0] != 1060: raise
cur.execute("""CREATE TABLE IF NOT EXISTS move_flag (
  move_id SMALLINT UNSIGNED NOT NULL, flag VARCHAR(20) NOT NULL, PRIMARY KEY (move_id, flag), KEY idx_flag (flag),
  FOREIGN KEY (move_id) REFERENCES move(move_id))""")
cur.execute("""CREATE TABLE IF NOT EXISTS move_effect (
  effect_id INT UNSIGNED PRIMARY KEY AUTO_INCREMENT, move_id SMALLINT UNSIGNED NOT NULL,
  trigger_type ENUM('primary','secondary') NOT NULL,   -- primary=항상 적용(변화기 등), secondary=확률 부가효과
  applies_to ENUM('target','self','field','side') NOT NULL,
  kind ENUM('status','volatile','stat_stage','weather','terrain','pseudo_weather','side_condition','slot_condition','special') NOT NULL,
  code VARCHAR(30) NOT NULL,       -- status:brn/par/slp/psn/tox/frz, stat_stage:atk/def/spa/spd/spe/accuracy/evasion, 그 외 효과 이름
  stages TINYINT NULL,             -- stat_stage 변화량(-6~6)
  chance_pct TINYINT UNSIGNED NOT NULL DEFAULT 100,
  KEY idx_move (move_id), KEY idx_kind (kind, code), FOREIGN KEY (move_id) REFERENCES move(move_id))""")
cur.execute("delete from move_effect"); cur.execute("delete from move_flag")

cur.execute("select move_id, name_en from move"); mv = {norm(n): i for i, n in cur.fetchall()}
EXTRA = ["stallingMove","ignoreAbility","ignoreImmunity","breaksProtect","thawsTarget","hasCrashDamage","ignoreDefensive",
         "ignoreEvasion","overrideDefensiveStat","overrideOffensiveStat","overrideOffensivePokemon","sleepUsable","stealsBoosts",
         "mindBlownRecoil","struggleRecoil","chloroblastRecoil","multiaccuracy","tracksTarget","callsMove","noPPBoosts","smartTarget"]
unmatched, nflag, neff = [], 0, 0
def eff(mid, trig, who, chance, src):
    global neff
    rows = []
    for st in [src.get("status")]:
        if st: rows.append((who, "status", st, None))
    if src.get("volatileStatus"): rows.append((who, "volatile", src["volatileStatus"], None))
    for s, v in (src.get("boosts") or {}).items(): rows.append((who, "stat_stage", s, v))
    for w, v in (src.get("self") or {}).get("boosts", {}).items(): rows.append(("self", "stat_stage", w, v))
    if (src.get("self") or {}).get("volatileStatus"): rows.append(("self", "volatile", src["self"]["volatileStatus"], None))
    for a, kind, code, stg in rows:
        cur.execute("insert into move_effect (move_id,trigger_type,applies_to,kind,code,stages,chance_pct) values (%s,%s,%s,%s,%s,%s,%s)",
                    (mid, trig, a, kind, code, stg, chance)); neff += 1

for key, m in SD.items():
    mid = mv.get(norm(m["name"]))
    if mid is None:
        if not m.get("isMax") and not m.get("isZ") and m.get("isNonstandard") not in ("CAP", "Unobtainable"): unmatched.append(m["name"])
        continue
    for f in m.get("flags", {}): cur.execute("insert ignore into move_flag (move_id,flag) values (%s,%s)", (mid, f)); nflag += 1
    mh = m.get("multihit"); lo, hi = (mh, mh) if isinstance(mh, int) else (mh or (1, 1))
    pct = lambda x: round(100 * x[0] / x[1]) if x else 0
    extra = {k: m[k] for k in EXTRA if k in m}
    cur.execute("""update move set target=%s, crit_stage=%s, always_crit=%s, min_hits=%s, max_hits=%s, drain_pct=%s, recoil_pct=%s,
        heal_pct=%s, self_switch=%s, force_switch=%s, self_destruct=%s, ohko=%s, fixed_damage=%s, extra=%s where move_id=%s""",
        (m["target"], max(0, m.get("critRatio", 1) - 1), bool(m.get("willCrit")), lo, hi, pct(m.get("drain")), pct(m.get("recoil")),
         pct(m.get("heal")), bool(m.get("selfSwitch")), bool(m.get("forceSwitch")), bool(m.get("selfdestruct")), bool(m.get("ohko")),
         m["damage"] if isinstance(m.get("damage"), int) else None, json.dumps(extra) if extra else None, mid))
    who = "self" if m["target"] == "self" else "target"
    eff(mid, "primary", who, 100, m)
    sec = ([m["secondary"]] if m.get("secondary") else []) + (m.get("secondaries") or [])
    for s in sec: eff(mid, "secondary", who, s.get("chance", 100), s)
    for kind, key2, ap in (("weather","weather","field"),("terrain","terrain","field"),("pseudo_weather","pseudoWeather","field"),
                           ("side_condition","sideCondition","side"),("slot_condition","slotCondition","side")):
        if m.get(key2):
            cur.execute("insert into move_effect (move_id,trigger_type,applies_to,kind,code,chance_pct) values (%s,'primary',%s,%s,%s,100)",
                        (mid, ap, kind, m[key2])); neff += 1

# ── 코드(onHit)로 구현돼 데이터에 안 보이는 확률 부가효과 (Showdown moves.ts 소스 기준, 수작업) ──
# (applies_to, kind, code, chance, 조건 설명)
FUNCTION_SECONDARIES = {
    "triattack": [("target", "status", "random(brn|par|frz)", 20)],
    "spiritshackle": [("target", "volatile", "trapped", 100)],
    "throatchop": [("target", "volatile", "throatchop", 100)],
    "eeriespell": [("target", "special", "reduce_last_move_pp:3", 100)],
    "burningjealousy": [("target", "status", "brn", 100)],     # 상대가 이번 턴 능력이 올랐을 때만 (조건은 move_rule 참고)
    "alluringvoice": [("target", "volatile", "confusion", 100)],  # 상대가 이번 턴 능력이 올랐을 때만
    "stoneaxe": [("side", "special", "sheer_force_marker", 100)],   # 실제 효과는 move_rule(스텔스록 설치), 천부적 폭력 판정용 표시
    "ceaselessedge": [("side", "special", "sheer_force_marker", 100)],
}
for mname, effs in FUNCTION_SECONDARIES.items():
    mid = mv.get(mname)
    if mid is None:
        continue
    for who, kind, code, chance in effs:
        cur.execute("insert into move_effect (move_id,trigger_type,applies_to,kind,code,chance_pct) values (%s,'secondary',%s,%s,%s,%s)",
                    (mid, who, kind, code, chance))

# ── 챔피언스 수치 변경 -> game_move 덮어쓰기 / 사용불가(Past) 표시
src = open(os.path.join(os.path.dirname(__file__), "cache_sd_champ_moves.ts"), encoding="utf-8").read()
cur.execute("select game_id from game where code='CHAMPIONS'"); cg = cur.fetchone()[0]
over, past, other = 0, [], {}
for em in re.finditer(r"^\t(\w+): \{\n(.*?)^\t\},", src, re.S | re.M):
    name, body = em.group(1), em.group(2)
    mid = mv.get(norm(name))
    if mid is None: continue
    if re.search(r'isNonstandard: "Past"', body): past.append(mid)
    ov = {k: int(v) for k, v in re.findall(r"^\t\t(basePower|accuracy|pp): (\d+),", body, re.M)}
    rest = [k for k in re.findall(r"^\t\t(\w+):", body, re.M) if k not in ("inherit", "basePower", "accuracy", "pp", "isNonstandard")]
    if rest: other[name] = rest
    if ov:
        cur.execute("""update game_move set power_override=%s, accuracy_override=%s, pp_override=%s where game_id=%s and move_id=%s""",
                    (ov.get("basePower"), ov.get("accuracy"), ov.get("pp"), cg, mid)); over += cur.rowcount
db.commit()
print("flags", nflag, "effects", neff, "챔피언스 덮어쓰기", over, "Past 표시 기술", len(past))
print("Showdown 미매칭:", unmatched[:30], len(unmatched))
print("챔피언스 모드의 기타 변경(수동 확인 필요):", other)
json.dump(past, open(os.path.join(os.path.dirname(__file__), "champ_past_moves.json"), "w"))
