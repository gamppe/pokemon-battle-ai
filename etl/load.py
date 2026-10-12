"""etl/cache -> MySQL. 사용: DB_PASSWORD 환경변수, root 계정"""
import os, re, json, glob, pymysql
from fetch import get

GAMES = {  # code: (version_group, pokedexes)
    "SwSh":      ("sword-shield",  ["galar", "isle-of-armor", "crown-tundra"]),
    "SV":        ("scarlet-violet", ["paldea", "kitakami", "blueberry"]),
    "ZA":        ("legends-za",    ["lumiose-city", "hyperspace"]),
    "CHAMPIONS": ("champions",     ["champions"]),
}
GAME_GEN_ITEM = {"SwSh": "generation-viii", "SV": "generation-ix"}  # PokeAPI item.game_indices
METHOD = {"level-up": "level-up", "machine": "machine", "egg": "egg", "tutor": "tutor"}
STAT = {"hp": "hp", "attack": "atk", "defense": "def", "special-attack": "spa", "special-defense": "spd", "speed": "spe"}

def ld(kind, n): return get(f"{kind}/{n}")
def names(kind): return [x["name"] for x in get(f"{kind}?limit=5000")["results"]]
def nm(d, lang):
    for n in d.get("names", []):
        if n["language"]["name"] == lang: return n["name"]
def ko_text(d):
    t = [e for e in d.get("flavor_text_entries", []) if e["language"]["name"] == "ko"]
    return re.sub(r"\s+", " ", (t[-1].get("flavor_text") or t[-1].get("text"))) if t else None
def en_eff(d, chance=None):
    for e in d.get("effect_entries", []):
        if e["language"]["name"] == "en":
            s = e["short_effect"]
            return s.replace("$effect_chance", str(chance)) if chance is not None else s

db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"],
                     database=os.environ.get("POKEMON_DB", "pokemon"), charset="utf8mb4", autocommit=False)
cur = db.cursor()
def q(sql, rows):
    if rows: cur.executemany(sql, rows)

cur.execute("select game_id, code from game"); gid = {c: i for i, c in cur.fetchall()}
cur.execute("select type_id, name_en from type"); tid = {n.lower(): i for i, n in cur.fetchall()}

# ability
miss_ko = {"ability": 0, "move": 0, "item": 0, "pokemon": 0}
abil_id = {}
rows = []
for i, n in enumerate(names("ability"), 1):
    d = ld("ability", n); abil_id[n] = d["id"]
    ko = nm(d, "ko"); miss_ko["ability"] += ko is None
    rows.append((d["id"], ko or nm(d, "en") or n, nm(d, "en") or n, en_eff(d), ko_text(d)))
q("insert into ability (ability_id,name_ko,name_en,effect_text,notes) values (%s,%s,%s,%s,%s)", rows)

# move
rows = []
for n in names("move"):
    d = ld("move", n)
    if d["type"]["name"] not in tid: continue  # stellar/unknown 제외
    ko = nm(d, "ko"); miss_ko["move"] += ko is None
    rows.append((d["id"], ko or nm(d, "en") or n, nm(d, "en") or n, tid[d["type"]["name"]],
                 d["damage_class"]["name"], d["power"], d["accuracy"], d["pp"] or 0, d["priority"],
                 en_eff(d, d["effect_chance"]), ko_text(d)))
q("insert into move (move_id,name_ko,name_en,type_id,category,power,accuracy,pp,priority,effect_text,notes) "
  "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)
move_ids = {r[0] for r in rows}
move_by_name = {ld("move", n)["name"]: ld("move", n)["id"] for n in names("move")}

# item (배틀 지닌물건: holdable-active/passive)
battle = set()
for a in ("holdable-active", "holdable-passive"):
    battle |= {i["name"] for i in get(f"item-attribute/{a}")["items"]}
rows, item_gens = [], {}
for n in sorted(battle):
    d = ld("item", n)
    ko = nm(d, "ko"); miss_ko["item"] += ko is None
    rows.append((d["id"], ko or nm(d, "en") or n, nm(d, "en") or n, en_eff(d) or ko_text(d)))
    item_gens[d["id"]] = {g["generation"]["name"] for g in d["game_indices"]}
q("insert into item (item_id,name_ko,name_en,effect_text) values (%s,%s,%s,%s)", rows)
q("insert into game_item (game_id,item_id) values (%s,%s)",
  [(gid[c], i) for c, g in GAME_GEN_ITEM.items() for i, gs in item_gens.items() if g in gs])

# 게임별 도감(종 단위)
dex = {}
for c, (vg, dexes) in GAMES.items():
    s = set()
    for dn in dexes:
        s |= {e["pokemon_species"]["name"] for e in ld("pokedex", dn)["pokemon_entries"]}
    dex[c] = s

# pokemon
pokemon_rows, pgame, pmove, pabil = [], [], [], []
pid_n = 0
for n in names("pokemon"):
    d = ld("pokemon", n)
    sp = d["species"]["name"]
    vgs = {}
    for m in d["moves"]:
        mid = move_by_name.get(m["move"]["name"])
        for v in m["version_group_details"]:
            vgs.setdefault(v["version_group"]["name"], []).append((mid, v))
    games = []
    for c, (vg, _) in GAMES.items():
        if sp not in dex[c]: continue
        # ZA는 PokeAPI에 기술 데이터가 없어 기본폼만 등록
        if vg in vgs or (vg == "legends-za" and d["is_default"]): games.append(c)
    if not games: continue
    s = ld("pokemon-species", sp)
    ko = nm(s, "ko"); miss_ko["pokemon"] += ko is None
    form = None if d["is_default"] else (n[len(sp) + 1:] if n.startswith(sp + "-") else n)
    ts = {t["slot"]: tid[t["type"]["name"]] for t in d["types"]}
    st = {STAT[x["stat"]["name"]]: x["base_stat"] for x in d["stats"]}
    pokemon_rows.append((d["id"], s["id"], form, ko or nm(s, "en") or sp, nm(s, "en") or sp,
                         ts[1], ts.get(2), st["hp"], st["atk"], st["def"], st["spa"], st["spd"], st["spe"]))
    for c in games:
        g = gid[c]; vg = GAMES[c][0]
        pgame.append((g, d["id"]))
        for a in d["abilities"]:
            slot = "hidden" if a["is_hidden"] else str(a["slot"])
            pabil.append((g, d["id"], slot, abil_id[a["ability"]["name"]]))
        for mid, v in vgs.get(vg, []):
            if mid not in move_ids: continue
            meth = METHOD.get(v["move_learn_method"]["name"], "other")
            pmove.append((g, d["id"], mid, meth, v["level_learned_at"] if meth == "level-up" else 0))

q("insert into pokemon (pokemon_id,dex_no,form_name,name_ko,name_en,type1_id,type2_id,"
  "base_hp,base_atk,base_def,base_spa,base_spd,base_spe) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", pokemon_rows)
q("insert into game_pokemon (game_id,pokemon_id) values (%s,%s)", pgame)
q("insert ignore into pokemon_ability (game_id,pokemon_id,slot,ability_id) values (%s,%s,%s,%s)", pabil)
pmove = list(set(pmove))
q("insert ignore into game_move (game_id,move_id) values (%s,%s)", sorted({(g, m) for g, _, m, _, _ in pmove}))
q("insert into pokemon_move (game_id,pokemon_id,move_id,method,level) values (%s,%s,%s,%s,%s)", pmove)
db.commit()
print("한글명 없음(영문으로 대체):", miss_ko)
