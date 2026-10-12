import os, json, glob, pymysql
from fetch import get, names
db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"], database=os.environ.get("POKEMON_DB", "pokemon"))
cur = db.cursor()
cur.execute("select game_id from game where code='ZA'"); g = cur.fetchone()[0]
cur.execute("select move_id from move"); ok = {r[0] for r in cur.fetchall()}
mid = {n: get(f"move/{n}")["id"] for n in names("move")}
rows, miss, nodata = set(), set(), 0
for f in glob.glob("cache_za/*.json"):
    pid = int(os.path.basename(f)[:-5]); d = json.load(open(f, encoding="utf-8"))
    if not d["moves"]: nodata += 1; continue
    for meth, lst in d["moves"].items():
        for slug, lv in lst:
            m = mid.get(slug)
            if m in ok: rows.add((g, pid, m, meth, lv))
            else: miss.add(slug)
cur.executemany("insert ignore into game_move (game_id,move_id) values (%s,%s)", sorted({(a, c) for a, _, c, _, _ in rows}))
cur.executemany("insert ignore into pokemon_move (game_id,pokemon_id,move_id,method,level) values (%s,%s,%s,%s,%s)", sorted(rows))
db.commit()
print("rows", len(rows), "no-data pokemon", nodata, "unmatched moves", sorted(miss))
