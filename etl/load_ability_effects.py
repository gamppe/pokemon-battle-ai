"""ability_effects_data.py -> ability_effect 테이블"""
import os, json, pymysql
from ability_effects_data import ABILITIES

db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"],
                     database=os.environ.get("POKEMON_DB", "pokemon"), charset="utf8mb4")
cur = db.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS ability_effect (
  effect_id  INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  ability_id SMALLINT UNSIGNED NOT NULL,
  hook       VARCHAR(24) NOT NULL,                 -- 효과가 끼어드는 시점
  kind       VARCHAR(24) NOT NULL,                 -- mult/stat_stage/heal_frac/status/immune/special ...
  target     VARCHAR(12) NULL,                     -- self/attacker/foe/ally/foe_side/all
  code       VARCHAR(60) NULL,                     -- 스탯, 상태이상, 타입, 특수효과 이름 등
  value      DECIMAL(7,4) NULL,                    -- 배율 / 단계 / HP 비율 / 턴 수
  chance_pct TINYINT UNSIGNED NOT NULL DEFAULT 100,
  cond       JSON NULL,                            -- 발동 조건
  note       VARCHAR(200) NULL,
  KEY idx_ability (ability_id), KEY idx_hook (hook, kind),
  FOREIGN KEY (ability_id) REFERENCES ability(ability_id))""")
cur.execute("delete from ability_effect")
cur.execute("select ability_id, name_en from ability")
ids = {n: i for i, n in cur.fetchall()}
cur.execute("select distinct a.name_en from pokemon_ability pa join ability a using(ability_id) where pa.game_id=4")
need = {r[0] for r in cur.fetchall()}
rows, unknown = [], []
for name, effs in ABILITIES.items():
    if name not in ids:
        unknown.append(name)
        continue
    for e in effs:
        v = e["value"]
        if e["kind"] == "damage_frac" and v is None:
            v = None
        rows.append((ids[name], e["hook"], e["kind"], e["target"], e["code"], v, e["chance"],
                     json.dumps(e["cond"], ensure_ascii=False) if e["cond"] else None, e["note"]))
cur.executemany("""insert into ability_effect (ability_id,hook,kind,target,code,value,chance_pct,cond,note)
    values (%s,%s,%s,%s,%s,%s,%s,%s,%s)""", rows)
db.commit()
print("rows", len(rows), "abilities", len(ABILITIES), "| 이름 없음:", unknown,
      "| 챔피언스 특성 중 미정리:", sorted(need - set(ABILITIES)))
