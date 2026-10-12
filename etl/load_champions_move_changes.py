"""챔피언스에서만 달라지는 기술 효과/플래그/타입 (출처: Showdown data/mods/champions/moves.ts, 수동 반영).
규칙: 어떤 기술에 game_id=챔피언스 행이 있으면 그 행들만 사용하고, 없으면 game_id=0(공통) 행을 사용."""
import os, pymysql
db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"], database=os.environ.get("POKEMON_DB", "pokemon"), charset="utf8mb4")
cur = db.cursor()
def alter(sql):
    try: cur.execute(sql)
    except pymysql.err.OperationalError as e:
        if e.args[0] not in (1060, 1061): raise
alter("ALTER TABLE move_effect ADD COLUMN game_id TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '0=공통'")
alter("ALTER TABLE move_flag ADD COLUMN game_id TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '0=공통', DROP PRIMARY KEY, ADD PRIMARY KEY (move_id, flag, game_id)")
alter("ALTER TABLE game_move ADD COLUMN type_override TINYINT UNSIGNED NULL")
alter("ALTER TABLE game_move ADD COLUMN effects_overridden BOOL NOT NULL DEFAULT 0 COMMENT '1이면 move_effect/move_flag의 해당 game_id 행만 사용(없으면 효과 없음)'")
cur.execute("select game_id from game where code='CHAMPIONS'"); cg = cur.fetchone()[0]
cur.execute("select move_id, name_en from move"); mid = {n.lower().replace(" ", "").replace("-", ""): i for i, n in cur.fetchall()}
cur.execute("select type_id, name_en from type"); tid = {n.lower(): i for i, n in cur.fetchall()}
cur.execute("delete from move_effect where game_id=%s", (cg,)); cur.execute("delete from move_flag where game_id=%s", (cg,))

def copy_effects(m, skip=lambda r: False):
    cur.execute("""insert into move_effect (move_id,trigger_type,applies_to,kind,code,stages,chance_pct,game_id)
        select move_id,trigger_type,applies_to,kind,code,stages,chance_pct,%s from move_effect where move_id=%s and game_id=0""", (cg, m))
def add(m, trig, who, kind, code, stages, chance):
    cur.execute("insert into move_effect (move_id,trigger_type,applies_to,kind,code,stages,chance_pct,game_id) values (%s,%s,%s,%s,%s,%s,%s,%s)",
                (m, trig, who, kind, code, stages, chance, cg))
def drop(m, **where):  # 챔피언스 행 중 조건에 맞는 것 삭제
    cond = " and ".join(f"{k}=%s" for k in where)
    cur.execute(f"delete from move_effect where game_id=%s and move_id=%s and {cond}", (cg, m, *where.values()))
def copy_flags(m, extra):
    cur.execute("insert into move_flag (move_id,flag,game_id) select move_id,flag,%s from move_flag where move_id=%s and game_id=0", (cg, m))
    for f in extra: cur.execute("insert ignore into move_flag values (%s,%s,%s)", (m, f, cg))

for n in ("crushclaw", "direclaw", "dragonclaw", "metalclaw", "shadowclaw"):   # slicing 플래그 추가
    copy_flags(mid[n], ["slicing"])
for n in ("doubleshock", "dragoncheer", "howl"):                               # 플래그 변경(세부는 moves.ts 참고)
    pass
# 부가효과 변경
m = mid["moonblast"]; copy_effects(m); drop(m, trigger_type="secondary"); add(m, "secondary", "target", "stat_stage", "spa", -1, 10)
m = mid["ironhead"]; copy_effects(m); drop(m, trigger_type="secondary"); add(m, "secondary", "target", "volatile", "flinch", None, 20)
m = mid["freezedry"]; copy_effects(m); drop(m, trigger_type="secondary")                      # 얼음 상태 확률 제거
m = mid["direclaw"]; copy_effects(m); drop(m, trigger_type="secondary"); add(m, "secondary", "target", "status", "random(psn|par|slp)", None, 30)
m = mid["makeitrain"]; copy_effects(m); drop(m, kind="stat_stage", applies_to="self"); add(m, "primary", "self", "stat_stage", "spa", -2, 100)
m = mid["toxicthread"]; copy_effects(m); drop(m, kind="stat_stage"); add(m, "primary", "target", "stat_stage", "spe", -2, 100)
# 정확도/타입
cur.execute("update game_move set accuracy_override=95 where game_id=%s and move_id=%s", (cg, mid["makeitrain"]))
for n, t in (("growth", "grass"), ("snaptrap", "steel")):
    cur.execute("update game_move set type_override=%s where game_id=%s and move_id=%s", (tid[t], cg, mid[n]))
cur.execute("update game_move set effects_overridden=0 where game_id=%s", (cg,))
cur.execute("""update game_move g set effects_overridden=1 where g.game_id=%s and (
  exists (select 1 from move_effect e where e.game_id=g.game_id and e.move_id=g.move_id)
  or exists (select 1 from move_flag f where f.game_id=g.game_id and f.move_id=g.move_id) or g.move_id=%s)""", (cg, mid["freezedry"]))
db.commit()
cur.execute("select count(*) from move_effect where game_id=%s", (cg,)); print("챔피언스 전용 효과 행:", cur.fetchone()[0])
