"""item_effects_data.py + mega_evolution -> item_effect 테이블"""
import os, re, json, pymysql
from item_effects_data import ITEMS

norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower().replace("’", ""))
db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"],
                     database=os.environ.get("POKEMON_DB", "pokemon"), charset="utf8mb4")
cur = db.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS item_effect (
  effect_id  INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  item_id    SMALLINT UNSIGNED NOT NULL,
  hook       VARCHAR(24) NOT NULL,
  kind       VARCHAR(24) NOT NULL,
  target     VARCHAR(12) NULL,
  code       VARCHAR(60) NULL,
  value      DECIMAL(7,4) NULL,
  chance_pct TINYINT UNSIGNED NOT NULL DEFAULT 100,
  single_use BOOL NOT NULL DEFAULT 0,
  cond       JSON NULL,
  note       VARCHAR(200) NULL,
  KEY idx_item (item_id), KEY idx_hook (hook, kind),
  FOREIGN KEY (item_id) REFERENCES item(item_id))""")
cur.execute("delete from item_effect")
cur.execute("select item_id, name_en from item")
ids = {norm(n): i for i, n in cur.fetchall()}
cur.execute("select i.item_id, i.name_en from game_item gi join item i using(item_id) where gi.game_id=4")
champ = {i: n for i, n in cur.fetchall()}

rows, unknown = [], []
for name, effs in ITEMS.items():
    iid = ids.get(norm(name))
    if iid is None:
        unknown.append(name)
        continue
    for e in effs:
        rows.append((iid, e["hook"], e["kind"], e["target"], e["code"], e["value"], e["chance"], int(e["single_use"]),
                     json.dumps(e["cond"], ensure_ascii=False) if e["cond"] else None, e["note"]))
done = {r[0] for r in rows}

# 메가스톤: mega_evolution 표에서 자동 생성
cur.execute("""select me.item_id, m.name_en, b.name_en, m.form_name from mega_evolution me
               join pokemon m on m.pokemon_id=me.mega_pokemon_id join pokemon b on b.pokemon_id=me.base_pokemon_id
               where me.item_id is not null""")
mega = 0
for iid, mname, bname, form in cur.fetchall():
    label = f"{mname}-{form}" if form else mname
    rows.append((iid, "passive", "mega_stone", None, label, None, 100, 0,
                 json.dumps({"holder": bname}, ensure_ascii=False), "배틀 중 1회 메가진화"))
    done.add(iid)
    mega += 1
cur.executemany("""insert into item_effect (item_id,hook,kind,target,code,value,chance_pct,single_use,cond,note)
    values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", rows)
db.commit()
left = sorted(n for i, n in champ.items() if i not in done)
print("rows", len(rows), "| 메가스톤", mega, "| 이름 없음:", unknown, "| 챔피언스 아이템 중 미정리:", left)
