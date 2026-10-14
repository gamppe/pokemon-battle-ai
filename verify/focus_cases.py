"""특정 상호작용만 집중해서 Showdown 과 분포 대조하는 도구 (날씨/필드/벽/탁쳐서떨구기+수확/잠자기-잠꼬대 등).
사용: python verify/focus_cases.py <카테고리> [n] [runs] [turns] [seed] [switch]
카테고리: weather terrain screens knockoff sleeptalk  (all 이면 전부)
출력은 verify/out/focus_*.json 에 분리 저장한다 (sweep 의 출력 파일과 겹치지 않는다)."""
import json
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import verify_turns as vt
from ai.gamedata import GameData, connect, norm
from ai.meta import Meta
from ai.battle import Engine

CAT = sys.argv[1] if len(sys.argv) > 1 else "all"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 200
RUNS = int(sys.argv[3]) if len(sys.argv) > 3 else 100
TURNS = int(sys.argv[4]) if len(sys.argv) > 4 else 4
SEED = int(sys.argv[5]) if len(sys.argv) > 5 else 1
SWITCH = float(sys.argv[6]) if len(sys.argv) > 6 else 0.25
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)
vt.MIN_TV, vt.MIN_KS = 0.15, 0.3

conn = connect()
data = GameData(conn)
meta = Meta(conn, data, 32)

WEATHER_MOVES = ["raindance", "sunnyday", "sandstorm", "snowscape", "weatherball"]
ROCKS = ["Damp Rock", "Heat Rock", "Smooth Rock", "Icy Rock"]
TERRAIN_MOVES = ["electricterrain", "grassyterrain", "mistyterrain", "psychicterrain"]
SEEDS = ["Electric Seed", "Grassy Seed", "Misty Seed", "Psychic Seed"]
FILLER = ["protect", "uturn", "roost", "recover", "swordsdance", "calmmind", "earthquake", "surf", "flamethrower", "icebeam", "thunderbolt", "shadowball", "knockoff"]


def mk(sid, rng, ability=None, item=None, moves=None, must=()):
    """meta 세트를 바탕으로 특성/도구/기술을 덮어쓴 세트"""
    try:
        s = meta.build_set(sid, rng)
    except Exception:
        s = dict(sid=sid, ability="", item="", nature="Serious", sp={"hp": 32, "atk": 16, "def": 8, "spa": 16, "spd": 8, "spe": 16}, moves=[])
    s = dict(s)
    if ability:
        s["ability"] = ability
    if item:
        s["item"] = item
    ms = list(must)
    pool = [m for m in (moves or []) if m in data.moves and m not in ms] + [m for m in s.get("moves", []) if m not in ms]
    for m in pool:
        if len(ms) >= 4:
            break
        if m not in ms and m in data.moves:
            ms.append(m)
    for m in FILLER:
        if len(ms) >= 4:
            break
        if m not in ms and m in data.moves:
            ms.append(m)
    s["moves"] = ms[:4]
    return s


MEGA_POOL = set(Engine(data).mega_map)


def with_mega(rng, team, a):
    if a[0] == "m" and any(norm(m.get("item", "")) in MEGA_POOL for m in team) and rng.random() < 0.35:
        return ("M", a[1])
    return a


def pick_move(rng, spec, names):
    """spec 의 기술 중 names 에 있는 것을 우선 고른다"""
    idx = [k for k, m in enumerate(spec["moves"]) if m in names]
    return rng.choice(idx) if idx and rng.random() < 0.6 else rng.randrange(len(spec["moves"]))


def team_weather(rng):
    # (종, 특성, 도구 후보, 기술 후보)
    pool = [("pelipper", "Drizzle", ROCKS + ["Leftovers"], ["raindance", "weatherball", "hurricane", "surf", "uturn"]),
            ("politoed", "Drizzle", ROCKS + ["Leftovers"], ["raindance", "weatherball", "surf", "icebeam"]),
            ("torkoal", "Drought", ROCKS + ["Charcoal"], ["sunnyday", "weatherball", "eruption", "overheat", "yawn"]),
            ("ninetales", "Drought", ROCKS, ["sunnyday", "weatherball", "fireblast", "nastyplot"]),
            ("charizardmegay", "Drought", ["Charizardite Y"], ["weatherball", "sunnyday", "flamethrower", "roost", "solarbeam"]),
            ("charizard", "Blaze", ["Charizardite Y"], ["weatherball", "sunnyday", "flamethrower", "roost", "raindance"]),
            ("tyranitar", "Sand Stream", ROCKS, ["sandstorm", "weatherball", "crunch", "stoneedge", "rockslide"]),
            ("hippowdon", "Sand Stream", ROCKS, ["sandstorm", "weatherball", "earthquake", "stealthrock", "slackoff"]),
            ("ninetalesalola", "Snow Warning", ROCKS, ["snowscape", "weatherball", "auroraveil", "blizzard", "freezedry"]),
            ("abomasnow", "Snow Warning", ROCKS, ["snowscape", "blizzard", "woodhammer", "auroraveil"]),
            ("vanilluxe", "Snow Warning", ROCKS, ["snowscape", "blizzard", "weatherball", "flashcannon"]),
            ("castform", "Forecast", ROCKS, ["raindance", "sunnyday", "weatherball", "snowscape"]),
            ("excadrill", "Sand Rush", ["Life Orb"], ["earthquake", "ironhead", "rockslide", "swordsdance"]),
            ("qwilfish", "Swift Swim", [None], ["raindance", "waterfall", "crunch"]),
            ("vileplume", "Chlorophyll", [None], ["sunnyday", "sludgebomb", "gigadrain"]),
            ("altaria", "Cloud Nine", [None], ["dragondance", "weatherball", "roost", "earthquake"]),
            ("drampa", "Cloud Nine", [None], ["hypervoice", "weatherball", "roost", "dracometeor"]),
            ("blastoise", "Rain Dish", [None], ["raindance", "weatherball", "surf", "icebeam"]),
            ("glaceon", "Ice Body", [None], ["snowscape", "weatherball", "blizzard", "freezedry"])]
    team = []
    for sid, ab, items, mvs in rng.sample(pool, 3):
        if sid not in data.pokemon:
            continue
        item = rng.choice(items)
        mv = [m for m in mvs if m in data.moves]
        team.append(mk(sid, rng, ab, item, rng.sample(mv, min(len(mv), 4)), must=[]))
    while len(team) < 3:
        team.append(meta.build_set(rng.choice(["garchomp", "dragonite", "gengar"]), rng))
    return team


def team_terrain(rng):
    pool = [("rillaboom", "Grassy Surge", ["grassyterrain", "grassyglide", "woodhammer", "fakeout", "uturn"]),
            ("indeedee", "Psychic Surge", ["psychicterrain", "expandingforce", "trickroom", "dazzlinggleam", "healingwish"]),
            ("pincurchin", "Electric Surge", ["electricterrain", "risingvoltage", "thunderbolt", "recover"]),
            ("raichumegax", "Electric Surge", ["electricterrain", "wildcharge", "thunderpunch", "fakeout"]),
            ("vileplume", "Chlorophyll", ["grassyterrain", "mistyterrain", "sludgebomb", "gigadrain"]),
            ("garchomp", "Rough Skin", TERRAIN_MOVES + ["earthquake", "dragonclaw"]),
            ("pelipper", "Drizzle", TERRAIN_MOVES + ["surf", "hurricane"]),
            ("grimmsnarl", "Prankster", ["mistyterrain", "electricterrain", "reflect", "lightscreen", "thunderwave"]),
            ("clefable", "Magic Guard", TERRAIN_MOVES + ["moonblast", "softboiled"])]
    team = []
    for sid, ab, mvs in rng.sample(pool, 3):
        if sid not in data.pokemon:
            continue
        mv = [m for m in mvs if m in data.moves]
        item = rng.choice(["Terrain Extender", "Terrain Extender"] + SEEDS + ["Leftovers", None])
        team.append(mk(sid, rng, ab, item, rng.sample(mv, min(len(mv), 4))))
    while len(team) < 3:
        team.append(meta.build_set(rng.choice(["dragonite", "gengar", "metagross"]), rng))
    return team


def team_screens(rng):
    pool = [("grimmsnarl", "Prankster", ["lightscreen", "reflect", "auroraveil", "partingshot", "thunderwave"]),
            ("ninetalesalola", "Snow Warning", ["auroraveil", "snowscape", "blizzard", "freezedry", "encore"]),
            ("abomasnow", "Snow Warning", ["auroraveil", "snowscape", "blizzard", "woodhammer"]),
            ("vanilluxe", "Snow Warning", ["auroraveil", "blizzard", "snowscape", "flashcannon"]),
            ("slowking", "Regenerator", ["lightscreen", "reflect", "auroraveil", "snowscape", "psychic", "slackoff"]),
            ("clefable", "Magic Guard", ["lightscreen", "reflect", "moonblast", "softboiled", "wish"]),
            ("pelipper", "Drizzle", ["raindance", "auroraveil", "surf", "uturn", "defog"]),
            ("tyranitar", "Sand Stream", ["brickbreak", "psychicfangs", "rockslide", "crunch", "knockoff"]),
            ("aerodactyl", "Pressure", ["defog", "taunt", "stoneedge", "roost"]),
            ("metagross", "Clear Body", ["psychicfangs", "brickbreak", "ragingbull", "meteormash"]),
            ("kommoo", "Soundproof", ["brickbreak", "clangingscales", "closecombat", "auroraveil"]),
            ("hydreigon", "Levitate", ["brickbreak", "dracometeor", "darkpulse", "uturn"])]
    team = []
    for sid, ab, mvs in rng.sample(pool, 3):
        if sid not in data.pokemon:
            continue
        mv = [m for m in mvs if m in data.moves]
        item = rng.choice(["Light Clay", "Light Clay", "Leftovers", None, "Icy Rock", "Damp Rock"])
        team.append(mk(sid, rng, ab, item, rng.sample(mv, min(len(mv), 4))))
    while len(team) < 3:
        team.append(meta.build_set(rng.choice(["garchomp", "dragonite", "gengar"]), rng))
    return team


BERRY_ITEMS = ["Sitrus Berry", "Sitrus Berry", "Sitrus Berry", "Lum Berry", "Leppa Berry", "Chesto Berry", "Oran Berry", "Leftovers", "Choice Scarf",
               "Focus Sash", "Life Orb", "Rocky Helmet", "Air Balloon", "Lum Berry"]


def team_knockoff(rng):
    team = []
    harvesters = [("trevenant", "Harvest"), ("arboliva", "Harvest")]
    for sid, ab in rng.sample(harvesters, 2):
        mv = [m for m in ["knockoff", "woodhammer", "poltergeist", "willowisp", "synthesis", "leechseed", "substitute", "protect", "earthpower", "gigadrain", "seedbomb", "hypervoice", "sunnyday"] if m in data.moves]
        team.append(mk(sid, rng, ab, rng.choice(BERRY_ITEMS), rng.sample(mv, 4), must=[]))
    atk = rng.choice(["garchomp", "kingambit", "hydreigon", "tyranitar", "weavile", "meowscarada", "bisharp"])
    atk = atk if atk in data.pokemon else "garchomp"
    mv = [m for m in ["knockoff", "thief", "covet", "bugbite", "pluck", "fling", "earthquake", "uturn", "closecombat", "suckerpunch", "protect", "trick", "switcheroo"] if m in data.moves]
    team.append(mk(atk, rng, None, rng.choice(BERRY_ITEMS + ["Black Glasses", "Choice Scarf"]), rng.sample(mv, 4), must=["knockoff"] if rng.random() < 0.7 else []))
    rng.shuffle(team)
    return team


def team_sleeptalk(rng):
    team = []
    sets = [("aerodactyl", ["rest", "sleeptalk", "whirlwind", "roar"], "Pressure"),
            ("aerodactyl", ["rest", "sleeptalk", "whirlwind", "stoneedge"], "Unnerve"),
            ("aerodactylmega", ["rest", "sleeptalk", "roar", "rockslide"], None),
            ("snorlax", ["rest", "sleeptalk", "bodyslam", "whirlwind"], None),
            ("slowking", ["rest", "sleeptalk", "roar", "psychic"], None),
            ("garchomp", ["rest", "sleeptalk", "earthquake", "outrage"], None)]
    for sid, mv, ab in rng.sample(sets, 3):
        if sid not in data.pokemon:
            continue
        mv = [m for m in mv if m in data.moves]
        item = rng.choice(["Chesto Berry", "Leftovers", "Lum Berry", None, "Focus Sash"])
        team.append(mk(sid, rng, ab, item, mv, must=mv[:4]))
    while len(team) < 3:
        team.append(meta.build_set(rng.choice(["garchomp", "dragonite", "gengar"]), rng))
    return team


ABIL_USERS = [("Thermal Exchange", "baxcalibur"), ("Scrappy", "kangaskhan"), ("Scrappy", "lopunny"), ("Fairy Aura", "gardevoir"), ("Defiant", "bisharp"),
              ("Defiant", "kingambit"), ("Competitive", "milotic"), ("Competitive", "gardevoir"), ("Thick Fat", "snorlax"), ("Thick Fat", "azumarill"),
              ("Oblivious", "slowbro"), ("Oblivious", "lickilicky"), ("Innards Out", "pyukumuku"), ("Water Bubble", "araquanid"),
              ("Purifying Salt", "garganacl"), ("Limber", "persian"), ("Ice Body", "glaceon"), ("Flower Veil", "florges"), ("Damp", "politoed"),
              ("Anger Point", "primeape"), ("Solar Power", "charizard"), ("Rain Dish", "blastoise"), ("Unnerve", "tyranitar"), ("Inner Focus", "lucario")]
ABIL_ITEMS = ["Sitrus Berry", "Sitrus Berry", "Chesto Berry", "Lum Berry", "Haban Berry", "Shuca Berry", "Chople Berry", "Colbur Berry", "Kasib Berry",
              "Wacan Berry", "Grassy Seed", "Psychic Seed", "Misty Seed", "Electric Seed", "Leftovers", None]
ABIL_TRIG = ["fakeout", "icywind", "willowisp", "thunderwave", "spore", "taunt", "closecombat", "flamethrower", "icebeam", "dragonclaw", "earthquake",
             "dazzlinggleam", "shadowball", "snarl", "leer", "intimidate", "psychicterrain", "grassyterrain", "mistyterrain", "electricterrain", "raindance",
             "sunnyday", "snowscape", "sandstorm", "uturn", "knockoff", "rest", "swordsdance", "crunch", "highhorsepower", "hurricane", "thunderbolt"]


def team_abil(rng):
    team = []
    for ab, sid in rng.sample(ABIL_USERS, 2):
        if sid not in data.pokemon:
            sid = "garchomp"
        team.append(mk(sid, rng, ab, rng.choice(ABIL_ITEMS), rng.sample([m for m in ABIL_TRIG if m in data.moves], 4)))
    other = rng.choice(["incineroar", "landorustherian", "gyarados", "salamence", "hydreigon", "ursaluna", "garchomp"])
    other = other if other in data.pokemon else "garchomp"
    team.append(mk(other, rng, None, rng.choice(ABIL_ITEMS), rng.sample([m for m in ABIL_TRIG if m in data.moves], 4)))
    rng.shuffle(team)
    return team


CATS = {"weather": (team_weather, WEATHER_MOVES), "terrain": (team_terrain, TERRAIN_MOVES), "screens": (team_screens, ["lightscreen", "reflect", "auroraveil", "brickbreak", "psychicfangs", "defog"]),
        "knockoff": (team_knockoff, ["knockoff", "thief", "covet", "bugbite", "pluck", "fling", "trick"]), "sleeptalk": (team_sleeptalk, ["rest", "sleeptalk", "whirlwind", "roar"]),
        "abil": (team_abil, ABIL_TRIG)}
names = list(CATS) if CAT == "all" else [CAT]

rng = random.Random(SEED)
scs = []
for k in range(N):
    cat = names[k % len(names)]
    fn, pref = CATS[cat]
    ta, tb = fn(rng), fn(rng)
    turns = []
    for t in range(TURNS):
        row = []
        for team in (ta, tb):
            if t > 0 and rng.random() < SWITCH:
                row.append(("s", rng.choice([1, 2])))
            else:
                row.append(with_mega(rng, team, ("m", pick_move(rng, team[0], pref))))
        turns.append(row)
    scs.append(dict(id=f"s{k}", teams=[ta, tb], turns=turns, key=cat))

W = 2
procs = []
for w in range(W):
    ch = scs[w::W]
    fin, fout = os.path.join(OUT, f"focus_in_{w}.json"), os.path.join(OUT, f"focus_sd_{w}.json")
    json.dump([dict(id=s["id"], teams=s["teams"], turns=s["turns"], runs=RUNS, seed=SEED) for s in ch], open(fin, "w"))
    procs.append((subprocess.Popen(["node", os.path.join(HERE, "sd_turns.js"), os.path.join(HERE, "..", "showdown"), fin, fout],
                                   stderr=subprocess.PIPE, text=True), fout))
sd = {}
for p, fout in procs:
    _, err = p.communicate()
    if p.returncode:
        print(err[-1500:])
        sys.exit(1)
    sd.update(json.load(open(fout)))

eng = Engine(data)
flagged, errors = [], 0
for s in scs:
    r = sd[s["id"]]
    if "error" in r:
        errors += 1
        print("SD error", s["id"], r["error"][:200])
        continue
    bad = vt.compare(vt.run_ours(eng, s, RUNS, SEED), r["results"], 1e-5)
    if bad:
        flagged.append((s, bad))
print(f"[{CAT}] {len(scs)}개 x {RUNS}회, {TURNS}턴: 불일치 시나리오 {len(flagged)}개, SD 오류 {errors}")
json.dump([dict(id=s["id"], teams=s["teams"], turns=s["turns"], key=s["key"], bad=b) for s, b in flagged],
          open(os.path.join(OUT, f"focus_mismatch_{CAT}.json"), "w"), default=str)
for s, bad in flagged[:12]:
    a, b = s["teams"][0][0], s["teams"][1][0]
    print(f"== {s['id']} [{s['key']}] {a['sid']}/{a['ability']}/{a['item']}{a['moves']} vs {b['sid']}/{b['ability']}/{b['item']}{b['moves']} turns={s['turns']}")
    for k, p, x, y, tv in bad[:4]:
        print(f"   {k}: p={p:.1e} ours={x} SD={y}")
