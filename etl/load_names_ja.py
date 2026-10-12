"""일본어 이름 추가: pokemon / move / ability / item / type / nature 의 name_ja (PokeAPI names 의 'ja').
- pokemon.name_ja       : 종 이름 (예: リザードン)
- pokemon.form_name_ja  : 폼 이름 (PokeAPI pokemon-form 의 form_name; 메가는 'メガリザードンＸ' 처럼 전체 이름, 리전폼은 'アローラのすがた')
PokeAPI 에 없는 신규 챔피언스 요소(신규 특성/아이템 등)는 NULL 로 남는다."""
import glob, json, os, pymysql
from fetch import get

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")


def scan(prefix, key="id"):
    """cache/{prefix}_*.json 을 읽어 {id: json} (목록 파일은 제외)"""
    out = {}
    for f in glob.glob(os.path.join(CACHE, prefix + "_*.json")):
        d = json.load(open(f, encoding="utf-8"))
        if isinstance(d, dict) and key in d and "names" in d:
            out[d[key]] = d
    return out


def ja(names):
    return next((n["name"] for n in names or [] if n["language"]["name"] == "ja"), None)


db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"],
                     database=os.environ.get("POKEMON_DB", "pokemon"), charset="utf8mb4")
cur = db.cursor()
for tbl, col, ddl in (("pokemon", "name_ja", "VARCHAR(60) NULL"), ("pokemon", "form_name_ja", "VARCHAR(60) NULL"),
                      ("move", "name_ja", "VARCHAR(60) NULL"), ("ability", "name_ja", "VARCHAR(60) NULL"),
                      ("item", "name_ja", "VARCHAR(60) NULL"), ("type", "name_ja", "VARCHAR(30) NULL"),
                      ("nature", "name_ja", "VARCHAR(30) NULL")):
    try:
        cur.execute(f"ALTER TABLE `{tbl}` ADD COLUMN {col} {ddl}")
    except pymysql.err.OperationalError as e:
        if e.args[0] != 1060:
            raise
report = {}

# ── 포켓몬 종 이름 ──
species = scan("pokemon-species")
cur.execute("select pokemon_id, dex_no from pokemon")
n = 0
for pid, dex in cur.fetchall():
    nm = ja(species.get(dex, {}).get("names"))
    if nm:
        cur.execute("update pokemon set name_ja=%s where pokemon_id=%s", (nm, pid)); n += 1
report["pokemon(종)"] = n

# ── 폼 이름 (PokeAPI pokemon-form) ──
pokes = scan("pokemon", "id") if False else {}
for f in glob.glob(os.path.join(CACHE, "pokemon_*.json")):
    d = json.load(open(f, encoding="utf-8"))
    if isinstance(d, dict) and "forms" in d and "species" in d:
        pokes[d["id"]] = d
cur.execute("select pokemon_id from pokemon where form_name is not null")
n = miss = 0
for (pid,) in cur.fetchall():
    p = pokes.get(pid)
    if not p or not p["forms"]:
        miss += 1; continue
    form_id = p["forms"][0]["url"].rstrip("/").split("/")[-1]
    try:
        fm = get(f"pokemon-form/{form_id}")
    except Exception:
        miss += 1; continue
    name = next((x["name"] for x in fm.get("form_names", []) if x["language"]["name"] == "ja"), None)
    if name:
        cur.execute("update pokemon set form_name_ja=%s where pokemon_id=%s", (name, pid)); n += 1
    else:
        miss += 1
report["pokemon(폼)"] = f"{n} (없음 {miss})"

# ── 기술 / 특성 / 아이템 / 성격 (id 가 PokeAPI id 와 같음) ──
for tbl, idcol, prefix in (("move", "move_id", "move"), ("ability", "ability_id", "ability"), ("item", "item_id", "item"),
                           ("nature", "nature_id", "nature")):
    src = scan(prefix)
    cur.execute(f"select {idcol} from `{tbl}`")
    n = miss = 0
    for (i,) in cur.fetchall():
        d = src.get(i)
        nm = ja(d.get("names")) if d else None
        if nm:
            cur.execute(f"update `{tbl}` set name_ja=%s where {idcol}=%s", (nm, i)); n += 1
        else:
            miss += 1
    report[tbl] = f"{n} (없음 {miss})"

# ── 타입 (영문 이름으로 매칭) ──
cur.execute("select type_id, name_en from type")
n = 0
for tid, en in cur.fetchall():
    d = get(f"type/{en.lower()}")
    nm = ja(d.get("names"))
    if nm:
        cur.execute("update type set name_ja=%s where type_id=%s", (nm, tid)); n += 1
report["type"] = n
db.commit()
print("일본어 이름 반영:", report)
