"""move_rules_data.py -> move_rule 테이블"""
import os, re, json, pymysql
from move_rules_data import RULES

norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"],
                     database=os.environ.get("POKEMON_DB", "pokemon"), charset="utf8mb4")
cur = db.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS move_rule (
  rule_id   INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  move_id   SMALLINT UNSIGNED NOT NULL,
  game_id   TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '0=공통',
  rule_type VARCHAR(24) NOT NULL,   -- power_mult_if / power_formula / damage_formula / on_hit_effect ...
  params    JSON NOT NULL,          -- 공식 이름, 배율, 조건 등
  note      VARCHAR(300) NULL,
  KEY idx_move (move_id), KEY idx_type (rule_type),
  FOREIGN KEY (move_id) REFERENCES move(move_id))""")
cur.execute("delete from move_rule")
cur.execute("select move_id, name_en from move")
ids = {norm(n): i for i, n in cur.fetchall()}
rows, unknown = [], []
for r in RULES:
    mid = ids.get(norm(r["move"]))
    if mid is None:
        unknown.append(r["move"])
        continue
    rows.append((mid, r["rule_type"], json.dumps(r["params"], ensure_ascii=False), r["note"]))
cur.executemany("insert into move_rule (move_id,rule_type,params,note) values (%s,%s,%s,%s)", rows)
db.commit()
cur.execute("""select count(distinct g.move_id) from game_move g join move_rule r using(move_id) where g.game_id=4""")
print("rules", len(rows), "| 기술 수(챔피언스)", cur.fetchone()[0], "| 이름 없음:", unknown)
