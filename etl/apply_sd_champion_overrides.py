"""Showdown 챔피언스 모드(정답) 덤프를 읽어 챔피언스 전용 값을 DB에 자동 반영.
선행: node verify/sd_dump.js showdown verify/out/sd_champions.json
 1) 기술 기본값 오류 보정: DB 기본 수치가 Showdown 기본(gen9)과 다르면 move 컬럼을 고침 (PokeAPI 값 오류)
 2) 챔피언스 변경: 챔피언스 값이 gen9 기본과 다르면 game_move 덮어쓰기(위력/명중/PP/타입) 또는 대상 변경으로 기록
    - 전역 규칙: 챔피언스는 모든 기술의 PP가 20을 넘지 않음 (mods/champions/scripts.ts)
 3) 플래그 변경: 챔피언스 플래그가 기본과 다르면 move_flag(game_id=챔피언스)에 전체 플래그 기록 (+ 공통 부가효과 복사)
 4) 습득 기술: Showdown 검증기가 판정한 챔피언스 학습표로 pokemon_move 재구성 (폼별 학습표 반영)
accuracy_override=255 는 '필중'(accuracy NULL)을 뜻한다."""
import ast, json, os, re, sys, pymysql

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from fetch import get

norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower().replace("’", ""))
JSON = os.path.join(HERE, "..", "verify", "out", "sd_champions.json")
if not os.path.exists(JSON):
    sys.exit("verify/out/sd_champions.json 이 없습니다. 먼저 `node verify/sd_dump.js showdown verify/out/sd_champions.json` 를 실행하세요.")
sd = json.load(open(JSON, encoding="utf-8"))
src = open(os.path.join(HERE, "load_champions_legal.py"), encoding="utf-8").read()
ALIAS = ast.literal_eval(next(n for n in ast.parse(src).body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "ALIAS").value)
REV = {norm(v): k for k, v in ALIAS.items()}

db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"],
                     database=os.environ.get("POKEMON_DB", "pokemon"), charset="utf8mb4")
cur = db.cursor()
try:
    cur.execute("ALTER TABLE game_move ADD COLUMN target_override VARCHAR(20) NULL")
except pymysql.err.OperationalError as e:
    if e.args[0] != 1060:
        raise
cur.execute("select game_id from game where code='CHAMPIONS'")
CG = cur.fetchone()[0]
cur.execute("select type_id, name_en from type")
tid = {n: i for i, n in cur.fetchall()}
log = dict(base_fix=0, pp=0, acc=0, power=0, type=0, target=0, flags=0, learn=0)

# ── 1)(2) 기술 기본값 보정 + 챔피언스 덮어쓰기 ──
cur.execute("""select m.move_id, m.name_en, m.power, m.accuracy, m.pp, t.name_en, m.category, m.priority, m.target
               from game_move g join move m using(move_id) join type t on t.type_id=m.type_id where g.game_id=%s""", (CG,))
rows = cur.fetchall()
smoves = {norm(v["name"]): v for v in sd["moves"].values()}
for mid, name, pw, acc, pp, typ, cat, prio, tgt in rows:
    s = smoves.get(norm(name))
    if not s or not s.get("base"):
        continue
    b = s["base"]
    bacc = None if b["accuracy"] is True else b["accuracy"]
    # 1) 기본값 오류 보정 (PokeAPI vs Showdown gen9)
    fix = {}
    if (pw or 0) != b["basePower"]: fix["power"] = b["basePower"] if b["basePower"] else None
    if acc != bacc: fix["accuracy"] = bacc
    if pp != b["pp"]: fix["pp"] = b["pp"]
    if prio != b["priority"]: fix["priority"] = b["priority"]
    if tgt != b["target"]: fix["target"] = b["target"]
    if fix:
        cur.execute("update move set " + ",".join(f"{k}=%s" for k in fix) + " where move_id=%s", (*fix.values(), mid))
        log["base_fix"] += 1
    base_pw, base_acc, base_pp = b["basePower"], bacc, b["pp"]
    # 2) 챔피언스 덮어쓰기 (gen9 기본과 다를 때만)
    sacc = None if s["accuracy"] is True else s["accuracy"]
    po = s["basePower"] if s["basePower"] != base_pw else None
    ao = (255 if sacc is None else sacc) if sacc != base_acc else None
    ppo = s["pp"] if s["pp"] != base_pp else None
    to = tid[s["type"]] if s["type"] != b["type"] else None
    tgo = s["target"] if s["target"] != b["target"] else None
    cur.execute("""update game_move set power_override=%s, accuracy_override=%s, pp_override=%s, type_override=%s, target_override=%s
                   where game_id=%s and move_id=%s""", (po, ao, ppo, to, tgo, CG, mid))
    log["power"] += po is not None; log["acc"] += ao is not None; log["pp"] += ppo is not None
    log["type"] += to is not None; log["target"] += tgo is not None

    # 3) 플래그 변경
    sfl, bfl = set(s["flags"]), set(b["flags"])
    cur.execute("select count(*) from move_flag where move_id=%s and game_id=%s", (mid, CG))
    has_row = cur.fetchone()[0] > 0
    if sfl != bfl:
        cur.execute("delete from move_flag where move_id=%s and game_id=%s", (mid, CG))
        cur.executemany("insert into move_flag (move_id,flag,game_id) values (%s,%s,%s)", [(mid, f, CG) for f in sorted(sfl)])
        # 공통 부가효과를 챔피언스 행으로 복사 (플래그만 바뀐 기술의 효과가 사라지지 않도록)
        cur.execute("select count(*) from move_effect where move_id=%s and game_id=%s", (mid, CG))
        if cur.fetchone()[0] == 0:
            cur.execute("""insert into move_effect (move_id,trigger_type,applies_to,kind,code,stages,chance_pct,game_id)
                select move_id,trigger_type,applies_to,kind,code,stages,chance_pct,%s from move_effect where move_id=%s and game_id=0""",
                        (CG, mid))
        log["flags"] += 1
    elif has_row:
        cur.execute("delete from move_flag where move_id=%s and game_id=%s", (mid, CG))
# effects_overridden 은 챔피언스 효과 행이 실제로 있는 기술만 1
cur.execute("update game_move set effects_overridden=0 where game_id=%s", (CG,))
cur.execute("""update game_move g set effects_overridden=1 where g.game_id=%s and exists
               (select 1 from move_effect e where e.game_id=g.game_id and e.move_id=g.move_id)""", (CG,))
# Freeze-Dry 처럼 챔피언스에서 부가효과가 사라진 기술은 행이 없어도 override 표시가 필요
cur.execute("""update game_move g join move m using(move_id) set g.effects_overridden=1 where g.game_id=%s and m.name_en='Freeze-Dry'""", (CG,))

# ── 4) 습득 기술: Showdown 학습표로 재구성 ──
cur.execute("select p.pokemon_id from game_pokemon p where p.game_id=%s", (CG,))
ids = [r[0] for r in cur.fetchall()]
pid_of = {}
for pid in ids:
    n = norm(get(f"pokemon/{pid}")["name"])
    pid_of[REV.get(n, n)] = pid
cur.execute("select move_id, name_en from move")
mv = {norm(n): i for i, n in cur.fetchall()}
pm, missing = set(), set()
for sid, pid in pid_of.items():
    sp = sd["species"].get(sid)
    if not sp:
        continue
    for m in sp["learnset"]:
        mid = mv.get(m)
        if mid is None:
            missing.add(m)
        else:
            pm.add((CG, pid, mid, "machine", 0))
cur.execute("delete from pokemon_move where game_id=%s", (CG,))
used = {m for _, _, m, _, _ in pm}
cur.execute("select move_id from game_move where game_id=%s", (CG,))
have = {r[0] for r in cur.fetchall()}
cur.executemany("insert ignore into game_move (game_id,move_id) values (%s,%s)", [(CG, m) for m in sorted(used - have)])
cur.executemany("insert into pokemon_move (game_id,pokemon_id,move_id,method,level) values (%s,%s,%s,%s,%s)", sorted(pm))
for m in have - used:
    cur.execute("delete from game_move where game_id=%s and move_id=%s", (CG, m))
log["learn"] = len(pm)
db.commit()
print("적용:", log, "| DB에 없는 기술(무시):", sorted(missing)[:5])
