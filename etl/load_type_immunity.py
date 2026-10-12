"""Showdown data/typechart.ts 의 면역(damageTaken 값 3) -> type_immunity.
키가 타입 이름(대문자 시작)이면 그 타입 기술의 피해 면역, 소문자면 상태/조건 면역
(powder=분말, prankster=우선도 장난 변화기, par/brn/psn/tox/frz=상태이상, sandstorm/hail=날씨 피해, trapped=교체 불가)."""
import os, re, pymysql

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "cache_sd_typechart.ts"), encoding="utf-8").read()
db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"],
                     database=os.environ.get("POKEMON_DB", "pokemon"), charset="utf8mb4")
cur = db.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS type_immunity (
  type_id TINYINT UNSIGNED NOT NULL, immunity_key VARCHAR(20) NOT NULL,
  kind ENUM('damage','condition') NOT NULL, note VARCHAR(120) NULL,
  PRIMARY KEY (type_id, immunity_key), FOREIGN KEY (type_id) REFERENCES type(type_id))""")
cur.execute("delete from type_immunity")
cur.execute("select type_id, name_en from type")
tid = {n.lower(): i for i, n in cur.fetchall()}
NOTE = {"powder": "분말 기술 무효", "prankster": "Prankster로 우선도가 오른 변화 기술 무효", "par": "마비 면역", "brn": "화상 면역",
        "psn": "독 면역", "tox": "맹독 면역", "frz": "얼음 면역", "sandstorm": "모래바람 피해 면역", "hail": "우박 피해 면역(9세대는 눈이라 피해 없음)",
        "trapped": "교체 불가 면역"}
rows = []
for m in re.finditer(r"^\t(\w+): \{\n\t\tdamageTaken: \{\n(.*?)^\t\t\},", src, re.S | re.M):
    t = m.group(1)
    if t not in tid:
        continue
    for k, v in re.findall(r"^\t\t\t(\w+): (\d),", m.group(2), re.M):
        if v == "3":
            damage = k[0].isupper()
            rows.append((tid[t], k.lower() if damage else k, "damage" if damage else "condition", None if damage else NOTE.get(k)))
cur.executemany("insert into type_immunity values (%s,%s,%s,%s)", rows)
db.commit()
print("type_immunity", len(rows))
