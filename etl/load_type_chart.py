import os, pymysql
from fetch import get
db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"], database=os.environ.get("POKEMON_DB", "pokemon"))
cur = db.cursor()
cur.execute("select type_id, name_en from type"); tid = {n.lower(): i for i, n in cur.fetchall()}
rows = []
for n, a in tid.items():
    dr = get(f"type/{n}")["damage_relations"]
    for key, m in (("double_damage_to", 2), ("half_damage_to", 0.5), ("no_damage_to", 0)):
        rows += [(a, tid[t["name"]], m) for t in dr[key] if t["name"] in tid]
cur.execute("""CREATE TABLE IF NOT EXISTS type_efficacy (
  attack_type_id TINYINT UNSIGNED NOT NULL, defense_type_id TINYINT UNSIGNED NOT NULL,
  multiplier DECIMAL(3,1) NOT NULL, PRIMARY KEY (attack_type_id, defense_type_id),
  FOREIGN KEY (attack_type_id) REFERENCES type(type_id), FOREIGN KEY (defense_type_id) REFERENCES type(type_id))""")
cur.execute("delete from type_efficacy")
cur.executemany("insert into type_efficacy values (%s,%s,%s)", rows); db.commit(); print(len(rows))
