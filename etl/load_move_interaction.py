"""기술별 방어(Protect)·분신(Substitute)·마법반사 등과의 상호작용을 기술 플래그/대상/소스에서 자동 계산 -> move_interaction.
- protect  : blocked(방어에 막힘) / passes(protect 플래그 없어 통과) / na(자신·진영·필드 대상)
- substitute: passes(bypasssub 플래그라 분신 무시) / hits_sub(공격 기술이라 분신이 대신 맞음) / blocked(변화 기술이라 분신에 막힘) / na
- sub_after_effects: 분신을 맞혀도 이어지는 기술 후속 효과(소스의 onAfterSubDamage 보유 기술)
- kings_shield_style: King's Shield/Silk Trap/Burning Bulwark/Obstruct는 변화 기술을 막지 못함 -> 변화 기술이면 passes"""
import os, re, pymysql

HERE = os.path.dirname(os.path.abspath(__file__))
norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
src = open(os.path.join(HERE, "cache_sd_moves.ts"), encoding="utf-8").read()
after_sub = set()
for m in re.finditer(r"^\t(\w+): \{\n(.*?)^\t\},", src, re.S | re.M):
    if "onAfterSubDamage" in m.group(2):
        after_sub.add(m.group(1))

db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"],
                     database=os.environ.get("POKEMON_DB", "pokemon"), charset="utf8mb4")
cur = db.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS move_interaction (
  move_id SMALLINT UNSIGNED PRIMARY KEY,
  targets_foe BOOL NOT NULL,
  protect ENUM('blocked','passes','na') NOT NULL,
  substitute ENUM('passes','hits_sub','blocked','na') NOT NULL,
  sub_after_effects BOOL NOT NULL DEFAULT 0,
  kings_shield_blocks BOOL NOT NULL,
  magic_bounce BOOL NOT NULL, powder BOOL NOT NULL, sound BOOL NOT NULL,
  note VARCHAR(200) NULL, FOREIGN KEY (move_id) REFERENCES move(move_id))""")
cur.execute("delete from move_interaction")
FOE = {"normal", "any", "adjacentFoe", "allAdjacentFoes", "allAdjacent", "randomNormal", "scripted"}
cur.execute("select move_id, name_en, category, target from move")
moves = cur.fetchall()
cur.execute("select move_id, flag from move_flag where game_id=0")
flags = {}
for mid, f in cur.fetchall():
    flags.setdefault(mid, set()).add(f)
rows = []
for mid, name, cat, target in moves:
    fl = flags.get(mid, set())
    foe = target in FOE
    if foe:
        protect = "blocked" if "protect" in fl else "passes"
        if "bypasssub" in fl:
            sub = "passes"
        else:
            sub = "hits_sub" if cat != "status" else "blocked"
    else:
        protect, sub = "na", "na"
    kings = foe and "protect" in fl and cat != "status"      # 킹실드류는 공격 기술만 막음
    after = norm(name) in after_sub
    note = None
    if after:
        note = "분신을 맞혀도 후속 효과(압정 설치·필드 제거 등)가 이어짐"
    rows.append((mid, foe, protect, sub, after, kings,
                 "reflectable" in fl, "powder" in fl, "sound" in fl, note))
cur.executemany("""insert into move_interaction (move_id,targets_foe,protect,substitute,sub_after_effects,kings_shield_blocks,
    magic_bounce,powder,sound,note) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", rows)
db.commit()
cur.execute("select protect, substitute, count(*) from move_interaction group by 1,2 order by 3 desc")
print(cur.fetchall())
