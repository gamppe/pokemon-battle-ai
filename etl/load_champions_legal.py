"""챔피언스(Reg M-C) 허용 포켓몬/특성/습득기술/메가진화를 Showdown mods/champions 기준으로 재구성.
출처: formats-data.ts(허용+티어), learnsets.ts(습득기술), play.pokemonshowdown.com/data/pokedex.json(종족값/특성/메가아이템)"""
import os, re, json, pymysql
from fetch import get, names

HERE = os.path.dirname(os.path.abspath(__file__))
norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
rd = lambda f: open(os.path.join(HERE, f), encoding="utf-8").read()
PD = json.loads(rd("cache_sd_pokedex.json"))
STAT = {"hp": "hp", "attack": "atk", "defense": "def", "special-attack": "spa", "special-defense": "spd", "speed": "spe"}
ALIAS = {  # Showdown id -> PokeAPI pokemon 이름 (폼 이름 표기 차이)
    "taurospaldeacombat": "tauros-paldea-combat-breed", "taurospaldeablaze": "tauros-paldea-blaze-breed",
    "taurospaldeaaqua": "tauros-paldea-aqua-breed", "basculegion": "basculegion-male", "basculegionf": "basculegion-female",
    "pyroar": "pyroar-male", "meowstic": "meowstic-male", "meowsticf": "meowstic-female", "meowsticmmega": "meowstic-male-mega",
    "meowsticfmega": "meowstic-female-mega", "aegislash": "aegislash-shield", "gourgeist": "gourgeist-average",
    "lycanroc": "lycanroc-midday", "mimikyu": "mimikyu-disguised", "toxtricity": "toxtricity-amped",
    "toxtricitylowkey": "toxtricity-low-key", "indeedee": "indeedee-male", "indeedeef": "indeedee-female",
    "morpeko": "morpeko-full-belly", "palafin": "palafin-zero", "maushold": "maushold-family-of-four",
    "squawkabilly": "squawkabilly-green-plumage", "squawkabillyblue": "squawkabilly-blue-plumage",
    "squawkabillyyellow": "squawkabilly-yellow-plumage", "squawkabillywhite": "squawkabilly-white-plumage",
}
API = {norm(n): n for n in names("pokemon")}

# 1) 허용 목록 + 티어
legal = {}
for m in re.finditer(r"^\t(\w+): \{\n(.*?)^\t\},", rd("cache_sd_champ_formats-data.ts"), re.S | re.M):
    b = m.group(2)
    if "isNonstandard" in b or "Illegal" in b:
        continue
    t = re.search(r'tier: "([^"]+)"', b)
    legal[m.group(1)] = t.group(1) if t else None

# Showdown 덤프(정답)가 있으면 허용 목록에 포함 (외형 폼은 덤프 단계에서 이미 제외됨)
SD_DUMP = os.path.join(HERE, "..", "verify", "out", "sd_champions.json")
SKIP_FORMES = {"mausholdfour", "polteageistantique", "sinistchamasterpiece", "vivillonfancy", "vivillonpokeball",
               "aegislashblade", "castformrainy", "castformsnowy", "castformsunny"}
if os.path.exists(SD_DUMP):
    for sid, sp in json.load(open(SD_DUMP, encoding="utf-8"))["species"].items():
        if sid not in legal and sid not in SKIP_FORMES and sid in PD:
            legal[sid] = sp.get("tier")

db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"],
                     database=os.environ.get("POKEMON_DB", "pokemon"), charset="utf8mb4")
cur = db.cursor()


def alter(sql):
    try:
        cur.execute(sql)
    except pymysql.err.OperationalError as e:
        if e.args[0] not in (1060, 1050):
            raise


alter("ALTER TABLE game_pokemon ADD COLUMN tier VARCHAR(10) NULL COMMENT 'Showdown tier (usage based)'")
cur.execute("""CREATE TABLE IF NOT EXISTS mega_evolution (
  mega_pokemon_id SMALLINT UNSIGNED PRIMARY KEY, base_pokemon_id SMALLINT UNSIGNED NOT NULL, item_id SMALLINT UNSIGNED NULL,
  FOREIGN KEY (mega_pokemon_id) REFERENCES pokemon(pokemon_id), FOREIGN KEY (base_pokemon_id) REFERENCES pokemon(pokemon_id),
  FOREIGN KEY (item_id) REFERENCES item(item_id))""")
cur.execute("select game_id from game where code='CHAMPIONS'")
cg = cur.fetchone()[0]
cur.execute("select type_id, name_en from type")
tid = {n.lower(): i for i, n in cur.fetchall()}
cur.execute("select ability_id, name_en from ability")
abil = {norm(n): i for i, n in cur.fetchall()}
cur.execute("select move_id, name_en from move")
mv = {norm(n): i for i, n in cur.fetchall()}
cur.execute("select item_id, name_en from item")
itm = {norm(n): i for i, n in cur.fetchall()}
cur.execute("select pokemon_id from pokemon")
have = {r[0] for r in cur.fetchall()}

# 2) 포켓몬 확보 (없으면 PokeAPI 캐시에서 추가) + 종족값/타입 Showdown 기준으로 정정
pid_of, added, stat_fix, unmatched = {}, 0, 0, []
for sid in legal:
    api = ALIAS.get(sid) or API.get(sid)
    if not api:
        unmatched.append(sid)
        continue
    d = get(f"pokemon/{api}")
    pid = d["id"]
    pid_of[sid] = pid
    if pid not in have:
        sp = d["species"]["name"]
        s = get(f"pokemon-species/{sp}")
        ko = next((n["name"] for n in s["names"] if n["language"]["name"] == "ko"), None)
        en = next((n["name"] for n in s["names"] if n["language"]["name"] == "en"), sp)
        ts = {t["slot"]: tid[t["type"]["name"]] for t in d["types"]}
        st = {STAT[x["stat"]["name"]]: x["base_stat"] for x in d["stats"]}
        form = None if d["is_default"] else (api[len(sp) + 1:] if api.startswith(sp + "-") else api)
        cur.execute("""insert into pokemon (pokemon_id,dex_no,form_name,name_ko,name_en,type1_id,type2_id,
            base_hp,base_atk,base_def,base_spa,base_spd,base_spe) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (pid, s["id"], form, ko or en, en, ts[1], ts.get(2),
                     st["hp"], st["atk"], st["def"], st["spa"], st["spd"], st["spe"]))
        have.add(pid)
        added += 1
    sd = PD.get(sid)
    if sd:
        b = sd["baseStats"]
        ty = [tid[t.lower()] for t in sd["types"]]
        t2 = ty[1] if len(ty) > 1 else None
        cur.execute("""update pokemon set base_hp=%s,base_atk=%s,base_def=%s,base_spa=%s,base_spd=%s,base_spe=%s,
            type1_id=%s,type2_id=%s where pokemon_id=%s and not (base_hp<=>%s and base_atk<=>%s and base_def<=>%s
            and base_spa<=>%s and base_spd<=>%s and base_spe<=>%s and type1_id<=>%s and type2_id<=>%s)""",
                    (b["hp"], b["atk"], b["def"], b["spa"], b["spd"], b["spe"], ty[0], t2, pid,
                     b["hp"], b["atk"], b["def"], b["spa"], b["spd"], b["spe"], ty[0], t2))
        stat_fix += cur.rowcount

# 3) 챔피언스 게임 데이터 재구성
for t in ("pokemon_move", "pokemon_ability", "game_pokemon"):
    cur.execute(f"delete from {t} where game_id=%s", (cg,))
cur.executemany("insert into game_pokemon (game_id,pokemon_id,tier) values (%s,%s,%s)",
                [(cg, pid_of[s], legal[s]) for s in pid_of])
SLOT = {"0": "1", "1": "2", "H": "hidden"}
miss_ab, rows = set(), []
for sid, pid in pid_of.items():
    for k, nm_ in (PD.get(sid, {}).get("abilities") or {}).items():
        if k not in SLOT:
            continue
        a = abil.get(norm(nm_))
        if a is None:
            miss_ab.add(nm_)
            continue
        rows.append((cg, pid, SLOT[k], a))
cur.executemany("insert ignore into pokemon_ability (game_id,pokemon_id,slot,ability_id) values (%s,%s,%s,%s)", rows)

# 4) 습득기술 (learnsets.ts; 폼은 changesFrom -> baseSpecies 순으로 상속)
LS = {}
for m in re.finditer(r"^\t(\w+): \{\n\t\tlearnset: \{\n(.*?)^\t\t\},", rd("cache_sd_champ_learnsets.ts"), re.S | re.M):
    LS[m.group(1)] = re.findall(r"^\t\t\t(\w+):", m.group(2), re.M)


def learnset(sid):
    seen = set()
    while sid and sid not in seen:
        if sid in LS:
            return LS[sid]
        seen.add(sid)
        p = PD.get(sid, {})
        sid = norm(p.get("changesFrom") or p.get("baseSpecies") or "") or None
    return []


# 챔피언스에서 사용 불가(isNonstandard: "Past")인 기술. load_move_effects.py 보다 먼저 돌므로 여기서 직접 계산한다
past = set()
for m in re.finditer(r"^\t(\w+): \{\n(.*?)^\t\},", rd("cache_sd_champ_moves.ts"), re.S | re.M):
    mid = mv.get(norm(m.group(1)))
    if mid is not None and re.search(r'isNonstandard: "Past"', m.group(2)):
        past.add(mid)
pm, miss_mv, nols = set(), set(), []
for sid, pid in pid_of.items():
    L = learnset(sid)
    if not L:
        nols.append(sid)
    for mname in L:
        m_ = mv.get(mname)
        if m_ is None:
            miss_mv.add(mname)
            continue
        if m_ in past:
            continue
        pm.add((cg, pid, m_, "machine", 0))
used = {m_ for _, _, m_, _, _ in pm}
cur.execute("select move_id from game_move where game_id=%s", (cg,))
gm = {r[0] for r in cur.fetchall()}
cur.executemany("insert ignore into game_move (game_id,move_id) values (%s,%s)", [(cg, m_) for m_ in sorted(used - gm)])
cur.executemany("insert into pokemon_move (game_id,pokemon_id,move_id,method,level) values (%s,%s,%s,%s,%s)", sorted(pm))
for m_ in gm - used:
    cur.execute("delete from game_move where game_id=%s and move_id=%s", (cg, m_))

# 5) 메가진화 (메가 -> 기본폼, 메가스톤)
cur.execute("delete from mega_evolution")
mega_miss = []
base_pid = {}
cur.execute("select pokemon_id, name_en from pokemon where form_name is null")
for i, n in cur.fetchall():
    base_pid[norm(n)] = i
for sid, pid in pid_of.items():
    p = PD.get(sid, {})
    if "Mega" not in p.get("forme", ""):
        continue
    base = base_pid.get(norm(p["baseSpecies"]))
    it = itm.get(norm(p.get("requiredItem", "")))
    if base is None or it is None:
        mega_miss.append((sid, base, p.get("requiredItem")))
    if base:
        cur.execute("insert ignore into mega_evolution values (%s,%s,%s)", (pid, base, it))
db.commit()
print(f"허용 {len(legal)} / 매핑 {len(pid_of)} / 신규 추가 {added} / 종족값·타입 정정 {stat_fix}")
print("매핑 실패:", unmatched, "| 특성 매칭 실패:", sorted(miss_ab), "| 학습표 없음:", nols[:20],
      "| 기술 매칭 실패:", sorted(miss_mv)[:20])
print("습득기술", len(pm), "챔피언스 기술 수", len(used), "| 메가 연결 실패:", mega_miss)
