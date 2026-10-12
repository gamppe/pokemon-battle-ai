"""대전 규칙(battle_format) / 성격(nature). 출처: Showdown config/formats.ts, data/rulesets.ts, mods/champions/scripts.ts"""
import os, pymysql
from fetch import get, names
db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"], database=os.environ.get("POKEMON_DB", "pokemon"), charset="utf8mb4")
cur = db.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS nature (
  nature_id TINYINT UNSIGNED PRIMARY KEY, name_ko VARCHAR(20) NOT NULL, name_en VARCHAR(20) NOT NULL,
  plus_stat ENUM('atk','def','spa','spd','spe') NULL, minus_stat ENUM('atk','def','spa','spd','spe') NULL)""")
cur.execute("""CREATE TABLE IF NOT EXISTS battle_format (
  format_id TINYINT UNSIGNED PRIMARY KEY AUTO_INCREMENT, code VARCHAR(40) NOT NULL UNIQUE, name VARCHAR(80) NOT NULL,
  game_id TINYINT UNSIGNED NOT NULL, game_type ENUM('singles','doubles') NOT NULL,
  level TINYINT UNSIGNED NOT NULL, team_size TINYINT UNSIGNED NOT NULL, pick_size TINYINT UNSIGNED NOT NULL,
  sp_total TINYINT UNSIGNED NOT NULL COMMENT 'stat points total', sp_max_per_stat TINYINT UNSIGNED NOT NULL, iv_fixed TINYINT UNSIGNED NOT NULL,
  species_clause BOOL NOT NULL, item_clause BOOL NOT NULL, ban_mythical BOOL NOT NULL, ban_restricted BOOL NOT NULL,
  notes TEXT NULL, FOREIGN KEY (game_id) REFERENCES game(game_id))""")
ST = {"attack": "atk", "defense": "def", "special-attack": "spa", "special-defense": "spd", "speed": "spe"}
rows = []
for n in names("nature"):
    d = get(f"nature/{n}")
    ko = next(x["name"] for x in d["names"] if x["language"]["name"] == "ko")
    en = next(x["name"] for x in d["names"] if x["language"]["name"] == "en")
    rows.append((d["id"], ko, en, ST.get((d["increased_stat"] or {}).get("name")), ST.get((d["decreased_stat"] or {}).get("name"))))
cur.execute("delete from nature")
cur.executemany("insert into nature values (%s,%s,%s,%s,%s)", rows)
cur.execute("select game_id from game where code='CHAMPIONS'"); cg = cur.fetchone()[0]
cur.execute("delete from battle_format")
cur.executemany("""insert into battle_format (code,name,game_id,game_type,level,team_size,pick_size,sp_total,sp_max_per_stat,iv_fixed,
  species_clause,item_clause,ban_mythical,ban_restricted,notes) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", [
  ("CHAMPIONS_BSS_MC", "[Gen 9 Champions] BSS Reg M-C", cg, "singles", 50, 6, 3, 66, 32, 31, 1, 1, 1, 1,
   "Flat Rules. 능력치: HP=종족값+SP+75, 그 외=(종족값+SP+20)*성격보정(1.1/0.9, 정수 버림). 시뮬: Showdown mods/champions"),
  ("CHAMPIONS_VGC_MC", "[Gen 9 Champions] VGC 2026 Reg M-C", cg, "doubles", 50, 6, 4, 66, 32, 31, 1, 1, 1, 1,
   "Flat Rules + Open Team Sheets")])
db.commit(); print(len(rows), "natures; formats 2")
