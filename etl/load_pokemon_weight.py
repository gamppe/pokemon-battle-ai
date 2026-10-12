"""포켓몬 몸무게(kg): PokeAPI 캐시(weight는 hg 단위) -> pokemon.weight_kg. 챔피언스 포켓몬은 apply_sd_champion_overrides.py 가 Showdown 값으로 덮어씀."""
import glob, json, os, pymysql

HERE = os.path.dirname(os.path.abspath(__file__))
w = {}
for f in glob.glob(os.path.join(HERE, "cache", "pokemon_*.json")):
    d = json.load(open(f, encoding="utf-8"))
    if isinstance(d, dict) and "weight" in d and "id" in d and "species" in d:
        w[d["id"]] = d["weight"]
db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"],
                     database=os.environ.get("POKEMON_DB", "pokemon"), charset="utf8mb4")
cur = db.cursor()
try:
    cur.execute("ALTER TABLE pokemon ADD COLUMN weight_kg DECIMAL(6,1) NULL")
except pymysql.err.OperationalError as e:
    if e.args[0] != 1060:
        raise
cur.execute("select pokemon_id from pokemon")
n = miss = 0
for (pid,) in cur.fetchall():
    if pid in w:
        cur.execute("update pokemon set weight_kg=%s where pokemon_id=%s", (w[pid] / 10, pid)); n += 1
    else:
        miss += 1
db.commit()
print("몸무게 반영", n, "| 캐시에 없음", miss)
