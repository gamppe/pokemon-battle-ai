"""battle_state_data.py -> battle_state / battle_state_effect"""
import os, json, pymysql
from battle_state_data import STATES

db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"],
                     database=os.environ.get("POKEMON_DB", "pokemon"), charset="utf8mb4")
cur = db.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS battle_state (
  state_id   SMALLINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  code       VARCHAR(30) NOT NULL UNIQUE,
  name_ko    VARCHAR(40) NOT NULL,
  scope      ENUM('field','side','pokemon','slot') NOT NULL,
  category   VARCHAR(20) NOT NULL,
  set_by     VARCHAR(120) NULL,
  duration_turns TINYINT UNSIGNED NULL,
  duration_ext   JSON NULL,
  note       VARCHAR(300) NULL)""")
cur.execute("""CREATE TABLE IF NOT EXISTS battle_state_effect (
  effect_id  INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  state_id   SMALLINT UNSIGNED NOT NULL,
  hook       VARCHAR(24) NOT NULL,
  kind       VARCHAR(24) NOT NULL,
  target     VARCHAR(16) NULL,
  code       VARCHAR(60) NULL,
  value      DECIMAL(7,4) NULL,
  chance_pct TINYINT UNSIGNED NOT NULL DEFAULT 100,
  order_no   SMALLINT UNSIGNED NULL COMMENT '턴 종료 처리 순서(작을수록 먼저)',
  cond       JSON NULL,
  note       VARCHAR(300) NULL,
  phase_no   TINYINT UNSIGNED NULL,
  KEY idx_state (state_id), KEY idx_hook (hook, kind),
  FOREIGN KEY (state_id) REFERENCES battle_state(state_id))""")
cur.execute("delete from battle_state_effect"); cur.execute("delete from battle_state")
cur.execute("ALTER TABLE battle_state AUTO_INCREMENT = 1"); cur.execute("ALTER TABLE battle_state_effect AUTO_INCREMENT = 1")
n = 0
for s in STATES:
    cur.execute("""insert into battle_state (code,name_ko,scope,category,set_by,duration_turns,duration_ext,note)
        values (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (s["code"], s["name_ko"], s["scope"], s["category"], s["set_by"], s["duration"],
                 json.dumps(s["ext"], ensure_ascii=False) if s["ext"] else None, s["note"]))
    sid = cur.lastrowid
    for e in s["effects"]:
        cur.execute("""insert into battle_state_effect (state_id,hook,kind,target,code,value,chance_pct,order_no,cond,note)
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (sid, e["hook"], e["kind"], e["target"], e["code"], e["value"], e["chance"], e["order_no"],
                     json.dumps(e["cond"], ensure_ascii=False) if e["cond"] else None, e["note"]))
        n += 1
db.commit()
print("states", len(STATES), "effects", n)
